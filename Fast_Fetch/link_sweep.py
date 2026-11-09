"""link_sweep.py — the bounded link-health sample (docs/LINK_HEALTH_SWEEP.md §8.2).

A full sweep of the catalog is infeasible on this box (§1: ≈ 7 days of the only
core), so this module does the largest honest thing instead: a stratified
probability sample of the projected links, probed politely, whose outcome the
operator can read on the admin panel. It is the `link_sweep.py` the design
lists as its item 2, built on the machinery that already exists rather than
beside it:

* the sample is stratified by registered host of `cat_links.url`
  (`link_health._host_of`), allocated proportionally to each host's link
  count, so the one sentence it supports is the design's §2 claim — "between
  P−3.1 % and P+3.1 % of links answer" at the default 1,000-link limit;
* probing goes through `link_health.probe_many`, so the per-host serialiser
  (`host_gate`, 1 in-flight request per host, 1.0–1.2 s spacing) is enforced,
  not commented;
* a host that answers 429 is parked for the rest of the run (§3: a 429 is a
  request to slow down, and returning twenty seconds later is how an IP gets
  a permanent block);
* verdicts are written to a staging file first (never a writable catalog
  connection), and `merge` applies them through the one existing door,
  `catalog_v2.apply_evidence`, then stamps the run summary into
  `cat_projection_meta` as `link_sweep_last_run` — the stored number
  `admin_panel.screen_link_health` reads, so the operator sees the sweep
  without any live scan.

Subcommands (migrate_search_indexes.py's shape: a required --target, a plan
that prints the cost before anything runs):

    python3 -S Fast_Fetch/link_sweep.py plan   --target CATALOG.db [--limit N]
    python3 -S Fast_Fetch/link_sweep.py run    --target CATALOG.db [--limit N]
                                               [--staging PATH] [--seed S]
    python3 -S Fast_Fetch/link_sweep.py status [--staging PATH]
    python3 -S Fast_Fetch/link_sweep.py merge  --target CATALOG.db [--staging PATH]

`plan` and `run` open the catalog read-only; `run` writes only the staging
file; `merge` is the one subcommand that writes the catalog, and it is the
operator's explicit action (like `migrate_search_indexes.py apply --execute`).
A staging file holds ONE sample: a second `run` against the same file resumes
it (links already evidenced are not re-probed); a fresh sample needs a fresh
--staging path.

Guards (the design's §3/§4, enforced per batch of 500 links):

* request cap: at most MAX_LINKS_PER_RUN links per run. At the measured
  good case of 1 request per link that is the design's 10,000-request cap;
  worst case is 12 requests per link (`test_link_sweep_budget.py` pins the
  12), so the default 1,000-link run costs ~1,000–2,000 requests;
* load: above LOAD_CEILING the run sleeps 60 s and re-checks; after 30 min
  it stops, flushes, and exits 0 with a note naming the load;
* memory: below 2,500 MB MemAvailable or 800 MB SwapFree the run stops,
  flushes, and exits 0 with a note — checked per batch, from /proc/meminfo.

Stdlib only. No network except the probes themselves; no production file is
touched except by `merge`, and never the live catalog unless the operator
points --target at it.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

#: The default sample: 1,000 links buys ±3.1 % at 95 % (design §2).
DEFAULT_LIMIT = 1000
#: Hard stop on links per run — the design's 10,000-request cap at the
#: measured good case of one request per link.
MAX_LINKS_PER_RUN = 10_000
#: Links per probe batch: the unit of the flush and the abort check (design §4).
BATCH_SIZE = 500
#: A host sampled below this many links supports no percentage at all (§2) —
#: the per-host table refuses it rather than rounding it.
MIN_PER_HOST = 30
#: Memory floor (design §4): stop below this much available memory / swap.
MEMORY_FLOOR_MB = 2500.0
SWAP_FLOOR_MB = 800.0
#: Load ceiling (design §4 + the fleet guardrail): heavy work freezes above it.
LOAD_CEILING = 4.0
#: Seconds between load re-checks while parked above the ceiling.
LOAD_WAIT_SECONDS = 60.0
#: Give up waiting on load after this long (30 min) and stop cleanly.
LOAD_MAX_WAIT_SECONDS = 1800.0
#: Workers for probe_many — the design's operating point (one per host).
DEFAULT_WORKERS = 8
#: Where a run's staging file lives when the operator names no path.
DEFAULT_STAGING = Path("/tmp/link_sweep.db")

#: Verdicts a probe can earn, in the projection's vocabulary.
_VERDICTS = ("alive", "dead", "expired", "blocked", "no_verdict")

_STAGING_DDL = """
CREATE TABLE IF NOT EXISTS link_sweep_sample (
    link_id INTEGER PRIMARY KEY,
    host TEXT NOT NULL,
    sampled_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS link_sweep_evidence (
    link_id INTEGER PRIMARY KEY,
    verdict TEXT NOT NULL,
    probed_at REAL NOT NULL,
    ok INTEGER NOT NULL,
    protocol TEXT,
    http_status INTEGER,
    content_type TEXT,
    size_bytes INTEGER,
    latency_ms INTEGER,
    speed_mbps REAL,
    accepts_ranges INTEGER,
    error TEXT,
    url TEXT
);
CREATE TABLE IF NOT EXISTS link_sweep_run (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    started_at REAL,
    updated_at REAL,
    sample_limit INTEGER,
    links_done INTEGER NOT NULL DEFAULT 0,
    alive INTEGER NOT NULL DEFAULT 0,
    dead INTEGER NOT NULL DEFAULT 0,
    expired INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    no_verdict INTEGER NOT NULL DEFAULT 0,
    host_parked INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
"""


# ── the arithmetic (pinned independently by test_link_sweep_budget.py) ────────

def margin(p: float, n: int, z: float = 1.96) -> float:
    """95 % normal-approximation half-width. `n = 0` is undefined, not zero."""
    if n <= 0:
        raise ValueError("a sample of zero supports no claim")
    return z * math.sqrt(max(p, 0.0) * (1.0 - max(p, 0.0)) / n)


def sample_size_for(margin_wanted: float, p: float = 0.5) -> int:
    """Links needed for a ±`margin_wanted` claim at 95 % (worst case p = 0.5)."""
    return int(math.ceil((1.96 ** 2) * p * (1.0 - p) / (margin_wanted ** 2)))


def estimate_hours(n_links: int, workers: int = DEFAULT_WORKERS,
                   t_ok: float = 0.6, dead_fraction: float = 0.10,
                   t_dead: float = 8.0, spacing: float = 1.0) -> float:
    """Wall hours for `n_links` at the polite ceiling: the larger of the
    thread-bound term (live links at `t_ok`, the dead tail at the full
    connect timeout) and the per-host politeness term. Same two ceilings as
    the budget test; the numbers are the code's own constants."""
    if n_links <= 0:
        return 0.0
    live = n_links * (1.0 - dead_fraction)
    dead = n_links * dead_fraction
    thread_s = (live * t_ok + dead * t_dead) / max(1, workers)
    politeness_s = n_links * spacing / max(1, workers)
    return max(thread_s, politeness_s) / 3600.0


# ── guards ───────────────────────────────────────────────────────────────────

def _read_mem() -> tuple[float | None, float | None]:
    """(MemAvailable MB, SwapFree MB) from /proc/meminfo, or Nones off-Linux."""
    available = swap_free = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) / 1024.0
                elif line.startswith("SwapFree:"):
                    swap_free = int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None, None
    return available, swap_free


def _load_average() -> float | None:
    """1-minute load, or None where the platform cannot report it."""
    try:
        return float(os.getloadavg()[0])
    except (OSError, AttributeError):
        return None


def _mem_ok() -> tuple[bool, str]:
    """The design's §4 floor: a reading we have binds; no reading does not."""
    available, swap_free = _read_mem()
    if available is not None and available < MEMORY_FLOOR_MB:
        return False, f"MemAvailable {available:.0f} MB < {MEMORY_FLOOR_MB:.0f} MB floor"
    if swap_free is not None and swap_free < SWAP_FLOOR_MB:
        return False, f"SwapFree {swap_free:.0f} MB < {SWAP_FLOOR_MB:.0f} MB floor"
    return True, ""


# ── the sample ───────────────────────────────────────────────────────────────

def _probeable(url: str, final_url: str) -> bool:
    """Anything worth knocking on: an http(s) address, not empty, not magnet:.

    The same rule `link_state.should_probe` applies to a ledger row, applied
    here to a projected link's two URL columns.
    """
    target = (final_url or url or "").strip()
    if not target:
        return False
    return target.lower().startswith(("http://", "https://"))


def strata(conn: sqlite3.Connection) -> dict:
    """The population, in one sequential pass over the projected links.

    Returns the probeable total, the per-host counts, and how many rows were
    unprobeable (empty/magnet:/hostless) — the strata the sample is drawn
    from. A scan of the URL column is a CLI cost, never a request-path cost.
    """
    import link_health

    by_host: dict[str, int] = {}
    unprobeable = 0
    total = 0
    for link_id, url, final_url in conn.execute(
            "SELECT id, url, final_url FROM cat_links ORDER BY id"):
        total += 1
        if not _probeable(url or "", final_url or ""):
            unprobeable += 1
            continue
        host = link_health._host_of(final_url or url or "")
        if not host:
            unprobeable += 1
            continue
        by_host[host] = by_host.get(host, 0) + 1
    return {"population": sum(by_host.values()), "total_links": total,
            "by_host": by_host, "unprobeable": unprobeable}


def allocate(by_host: dict, limit: int) -> dict:
    """Proportional allocation by largest remainder: the shares sum to
    `limit` (or to the population when it is smaller), and a host whose share
    rounds to zero gets nothing rather than a token link."""
    population = sum(by_host.values())
    take = max(0, min(int(limit), population))
    if take == 0 or population == 0:
        return {}
    raw = {host: take * count / population for host, count in by_host.items()}
    out = {host: int(math.floor(share)) for host, share in raw.items()}
    leftover = take - sum(out.values())
    for host, _ in sorted(raw.items(),
                          key=lambda item: (item[1] - math.floor(item[1]),
                                            item[0]),
                          reverse=True):
        if leftover <= 0:
            break
        if out[host] == 0 and raw[host] < 0.5:
            continue
        out[host] += 1
        leftover -= 1
    return {host: n for host, n in out.items() if n > 0}


def draw_sample(conn: sqlite3.Connection, limit: int, *,
                seed: int | None = None) -> tuple[list[dict], dict]:
    """Draw the stratified sample: pass 1 counts the strata, pass 2 takes a
    reservoir per host. Returns the sampled rows and the plan that produced
    them (strata, allocation, population)."""
    import link_health

    strata_info = strata(conn)
    allocation = allocate(strata_info["by_host"], limit)
    rng = random.Random(seed)
    reservoirs: dict[str, list[dict]] = {host: [] for host in allocation}
    seen: dict[str, int] = {host: 0 for host in allocation}
    for link_id, url, final_url, service in conn.execute(
            "SELECT id, url, final_url, service FROM cat_links ORDER BY id"):
        if not _probeable(url or "", final_url or ""):
            continue
        host = link_health._host_of(final_url or url or "")
        if host not in reservoirs:
            continue
        seen[host] += 1
        row = {"link_id": int(link_id), "url": url or "",
               "final_url": final_url or "", "service": service or "",
               "host": host}
        reservoir = reservoirs[host]
        if len(reservoir) < allocation[host]:
            reservoir.append(row)
        elif rng.random() < allocation[host] / seen[host]:
            reservoir[rng.randrange(len(reservoir))] = row
    sample = [row for rows in reservoirs.values() for row in rows]
    sample.sort(key=lambda row: row["link_id"])
    plan = {"population": strata_info["population"],
            "total_links": strata_info["total_links"],
            "unprobeable": strata_info["unprobeable"],
            "limit": int(limit),
            "sampled": len(sample),
            "allocation": allocation,
            "hosts": len(allocation),
            "estimated_hours": round(estimate_hours(len(sample)), 2)}
    return sample, plan


# ── staging ──────────────────────────────────────────────────────────────────

def ensure_staging(conn: sqlite3.Connection) -> None:
    """Create the staging tables (additive only)."""
    conn.executescript(_STAGING_DDL)
    conn.commit()


def _run_row(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM link_sweep_run WHERE id = 1").fetchone()
    return dict(row) if row is not None else None


def _upsert_run(conn: sqlite3.Connection, **fields) -> None:
    """Write the one run row (INSERT … ON CONFLICT — the row is a singleton)."""
    conn.execute(
        "INSERT INTO link_sweep_run (id, started_at, updated_at, sample_limit,"
        " links_done, alive, dead, expired, blocked, no_verdict, host_parked,"
        " rows_written, notes) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET"
        " updated_at = excluded.updated_at,"
        " sample_limit = excluded.sample_limit,"
        " links_done = excluded.links_done, alive = excluded.alive,"
        " dead = excluded.dead, expired = excluded.expired,"
        " blocked = excluded.blocked, no_verdict = excluded.no_verdict,"
        " host_parked = excluded.host_parked,"
        " rows_written = excluded.rows_written, notes = excluded.notes",
        (fields.get("started_at"), fields.get("updated_at"),
         fields.get("sample_limit"), fields.get("links_done", 0),
         fields.get("alive", 0), fields.get("dead", 0),
         fields.get("expired", 0), fields.get("blocked", 0),
         fields.get("no_verdict", 0), fields.get("host_parked", 0),
         fields.get("rows_written", 0), fields.get("notes", "")))


def status(staging_conn: sqlite3.Connection) -> dict:
    """The run's stored numbers — read, never scanned from the catalog."""
    ensure_staging(staging_conn)
    run = _run_row(staging_conn) or {}
    by_verdict = {row[0]: int(row[1]) for row in staging_conn.execute(
        "SELECT verdict, COUNT(*) FROM link_sweep_evidence GROUP BY verdict")}
    sampled = int(staging_conn.execute(
        "SELECT COUNT(*) FROM link_sweep_sample").fetchone()[0])
    evidenced = int(staging_conn.execute(
        "SELECT COUNT(*) FROM link_sweep_evidence").fetchone()[0])
    measured = sum(by_verdict.get(name, 0)
                   for name in ("alive", "dead", "expired"))
    out = {"available": bool(run),
           "started_at": run.get("started_at"),
           "updated_at": run.get("updated_at"),
           "sample_limit": run.get("sample_limit"),
           "sampled": sampled, "evidenced": evidenced,
           "links_done": int(run.get("links_done") or 0),
           "alive": int(run.get("alive") or 0),
           "dead": int(run.get("dead") or 0),
           "expired": int(run.get("expired") or 0),
           "blocked": int(run.get("blocked") or 0),
           "no_verdict": int(run.get("no_verdict") or 0),
           "host_parked": int(run.get("host_parked") or 0),
           "rows_written": int(run.get("rows_written") or 0),
           "by_verdict": by_verdict,
           "notes": run.get("notes") or ""}
    out["measured"] = measured
    out["alive_share"] = (round(out["alive"] / measured, 4)
                          if measured else None)
    out["margin_95"] = (round(margin(0.5, measured), 4)
                        if measured >= MIN_PER_HOST else None)
    return out


# ── probing ──────────────────────────────────────────────────────────────────

def _verdict_of(result) -> str:
    """One probe result -> the run's bucket, in the projection's vocabulary.

    `link_state.classify` is the pure classifier (token rot 401/403/429 is
    `expired`, a measured 404 is `dead`, a refusal to look is
    `unverified`); the run splits `unverified` into `blocked` (the host was
    blocklisted) and `no_verdict` (anything else we refused to judge).
    """
    import link_state

    status = link_state.classify({
        "ok": bool(getattr(result, "ok", False)),
        "http_status": int(getattr(result, "http_status", 0) or 0),
        "error": str(getattr(result, "error", "") or "")})
    if status == link_state.STATUS_ACTIVE:
        return "alive"
    if status in (link_state.STATUS_DEAD, link_state.STATUS_EXPIRED):
        return status
    if str(getattr(result, "error", "") or "") == "blocklisted":
        return "blocked"
    return "no_verdict"


def _probe_items(rows: list[dict]) -> list[dict]:
    """Rows -> probe_many items, mirroring `link_state.default_prober`: the
    knock target is the cached resolution when there is one, else the bridge
    URL; the bridge travels as `final_url` for reference."""
    items = []
    for row in rows:
        target = (row.get("final_url") or "").strip() or (row.get("url") or "")
        item = {"url": target, "allow_private": False}
        if row.get("url"):
            item["final_url"] = row["url"]
        if row.get("service"):
            item["service"] = row["service"]
        items.append(item)
    return items


def run_sample(catalog_conn: sqlite3.Connection,
               staging_conn: sqlite3.Connection, *, limit: int = DEFAULT_LIMIT,
               seed: int | None = None, workers: int = DEFAULT_WORKERS,
               prober=None, sleep=time.sleep) -> dict:
    """Probe the sample and write the verdicts to staging, one batch at a time.

    `prober` is `fn(items) -> results in input order` (default:
    `link_health.probe_many`, workers=8); tests inject a fake. Returns the
    run summary (the same shape `status()` reads back). A run that stops on
    a guard returns state `paused_memory` / `paused_load` with a note; a run
    that finishes returns `complete`. Re-running against the same staging
    file resumes the stored sample — links already evidenced are not
    re-probed.
    """
    import link_health

    ensure_staging(staging_conn)
    now = time.time()
    existing = _run_row(staging_conn)
    started_at = existing["started_at"] if existing else now
    stored_sample = [dict(row) for row in staging_conn.execute(
        "SELECT link_id, host FROM link_sweep_sample ORDER BY link_id")]
    if stored_sample:
        sample = []
        for row in stored_sample:
            found = catalog_conn.execute(
                "SELECT id, url, final_url, service FROM cat_links"
                " WHERE id = ?", (row["link_id"],)).fetchone()
            if found is None:
                continue
            sample.append({"link_id": int(found["id"]), "url": found["url"] or "",
                           "final_url": found["final_url"] or "",
                           "service": found["service"] or "",
                           "host": row["host"]})
        plan = {"resumed": True, "sampled": len(sample),
                "limit": existing["sample_limit"] if existing else int(limit)}
    else:
        sample, plan = draw_sample(catalog_conn, limit, seed=seed)
        if len(sample) > MAX_LINKS_PER_RUN:
            raise ValueError(
                f"sample of {len(sample)} links exceeds the"
                f" {MAX_LINKS_PER_RUN}-link run cap; raise --limit or split the run")
        with staging_conn:
            staging_conn.executemany(
                "INSERT OR IGNORE INTO link_sweep_sample"
                " (link_id, host, sampled_at) VALUES (?, ?, ?)",
                [(row["link_id"], row["host"], now) for row in sample])
    evidenced = {int(row[0]) for row in staging_conn.execute(
        "SELECT link_id FROM link_sweep_evidence")}
    pending = [row for row in sample if row["link_id"] not in evidenced]
    counts = {"links_done": 0, "alive": 0, "dead": 0, "expired": 0,
              "blocked": 0, "no_verdict": 0, "host_parked": 0,
              "rows_written": 0}
    if existing:
        for key in counts:
            counts[key] = int(existing.get(key) or 0)
    parked: set[str] = set()
    state = "complete"
    notes = ""
    probe = prober or (lambda items: link_health.probe_many(
        items, workers=max(1, int(workers))))
    while pending:
        ok_mem, mem_note = _mem_ok()
        if not ok_mem:
            state = "paused_memory"
            notes = mem_note
            break
        load = _load_average()
        waited = 0.0
        while load is not None and load > LOAD_CEILING:
            sleep(LOAD_WAIT_SECONDS)
            waited += LOAD_WAIT_SECONDS
            if waited > LOAD_MAX_WAIT_SECONDS:
                state = "paused_load"
                notes = (f"load {load:.2f} stayed above {LOAD_CEILING} for"
                         f" {waited:.0f}s; run paused, resume it later")
                break
            load = _load_average()
        if state == "paused_load":
            break
        batch, pending = pending[:BATCH_SIZE], pending[BATCH_SIZE:]
        # Links on a host parked by an earlier batch never reach a probe:
        # they are done for this run and counted, not silently dropped.
        parked_now = [row for row in batch if row["host"] in parked]
        batch = [row for row in batch if row["host"] not in parked]
        counts["host_parked"] += len(parked_now)
        results = probe(_probe_items(batch)) if batch else []
        evidence_rows = []
        for row, result in zip(batch, results):
            verdict = _verdict_of(result)
            counts[verdict] += 1
            counts["links_done"] += 1
            if int(getattr(result, "http_status", 0) or 0) == 429:
                parked.add(row["host"])
            evidence_rows.append((
                row["link_id"], verdict,
                float(getattr(result, "checked_at", 0.0) or now),
                1 if getattr(result, "ok", False) else 0,
                str(getattr(result, "protocol", "") or ""),
                int(getattr(result, "http_status", 0) or 0),
                str(getattr(result, "content_type", "") or ""),
                int(getattr(result, "size_bytes", 0) or 0),
                int(getattr(result, "latency_ms", 0) or 0),
                float(getattr(result, "download_speed_mbps", 0.0) or 0.0),
                1 if getattr(result, "accepts_ranges", False) else 0,
                str(getattr(result, "error", "") or ""),
                str(getattr(result, "url", "") or row["url"])))
        # Parked hosts' remaining links never reach a probe: they are done
        # for this run, counted, and dropped from the pending list.
        newly_parked = 0
        if parked:
            kept = []
            for row in pending:
                if row["host"] in parked:
                    newly_parked += 1
                else:
                    kept.append(row)
            pending = kept
        counts["host_parked"] += newly_parked
        counts["rows_written"] += len(evidence_rows)
        with staging_conn:
            staging_conn.executemany(
                "INSERT OR REPLACE INTO link_sweep_evidence"
                " (link_id, verdict, probed_at, ok, protocol, http_status,"
                "  content_type, size_bytes, latency_ms, speed_mbps,"
                "  accepts_ranges, error, url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                evidence_rows)
            _upsert_run(staging_conn, started_at=started_at, updated_at=time.time(),
                        sample_limit=plan.get("limit", int(limit)), notes=notes,
                        **counts)
    with staging_conn:
        _upsert_run(staging_conn, started_at=started_at, updated_at=time.time(),
                    sample_limit=plan.get("limit", int(limit)), notes=notes,
                    **counts)
    summary = status(staging_conn)
    summary["state"] = state
    summary["notes"] = notes
    summary["plan"] = plan
    return summary


# ── merge ────────────────────────────────────────────────────────────────────

def merge(catalog_conn: sqlite3.Connection,
          staging_conn: sqlite3.Connection, *, batch_size: int = BATCH_SIZE,
          now: float | None = None) -> dict:
    """Apply the staged evidence to the catalog through `apply_evidence`,
    then stamp the run summary where the panel reads it.

    The operator's explicit action (the only writer in this module). Evidence
    is handed over in link_id order, in batches; a replay is a no-op because
    `apply_evidence` dedupes on (link_id, probed_at), so merging twice
    changes nothing the second time.
    """
    import catalog_v2

    moment = time.time() if now is None else float(now)
    ensure_staging(staging_conn)
    rows = [dict(row) for row in staging_conn.execute(
        "SELECT link_id, verdict, probed_at, ok, protocol, http_status,"
        " content_type, size_bytes, latency_ms, speed_mbps, accepts_ranges,"
        " error, url FROM link_sweep_evidence ORDER BY link_id")]
    run = status(staging_conn)
    merged = 0
    updated_total = 0
    for start in range(0, len(rows), max(1, int(batch_size))):
        chunk = rows[start:start + max(1, int(batch_size))]
        results = [{
            "link_id": int(item["link_id"]),
            "probed_at": float(item["probed_at"]),
            "ok": bool(item["ok"]),
            "protocol": item["protocol"] or "",
            "http_status": int(item["http_status"] or 0),
            "content_type": item["content_type"] or "",
            "size_bytes": int(item["size_bytes"] or 0),
            "latency_ms": int(item["latency_ms"] or 0),
            "speed_mbps": float(item["speed_mbps"] or 0.0),
            "accepts_ranges": bool(item["accepts_ranges"]),
            "error": item["error"] or "",
            "url": item["url"] or "",
        } for item in chunk]
        outcome = catalog_v2.apply_evidence(catalog_conn, results)
        merged += len(chunk)
        updated_total += int(outcome.get("links_updated") or 0)
    measured = (run["alive"] + run["dead"] + run["expired"])
    stamp = {
        "started_at": run.get("started_at"),
        "finished_at": run.get("updated_at"),
        "sample_limit": run.get("sample_limit"),
        "links_done": run["links_done"],
        "alive": run["alive"], "dead": run["dead"], "expired": run["expired"],
        "blocked": run["blocked"], "no_verdict": run["no_verdict"],
        "host_parked": run["host_parked"],
        "alive_share": run["alive_share"],
        "margin_95": run["margin_95"],
        "merged_links": merged,
        "links_updated": updated_total,
        "applied_at": moment,
    }
    catalog_conn.execute(
        "INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES (?, ?)",
        ("link_sweep_last_run", json.dumps(stamp, sort_keys=True)))
    catalog_conn.commit()
    return {"evidence_rows": len(rows), "merged_links": merged,
            "links_updated": updated_total, "stamp": stamp}


# ── CLI ──────────────────────────────────────────────────────────────────────

def _open_catalog(target: Path, *, read_only: bool) -> sqlite3.Connection:
    if not target.is_file():
        raise SystemExit(f"ABORT: --target is not a file: {target}")
    if read_only:
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    return conn


def _open_staging(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        if not path.is_file():
            raise SystemExit(f"ABORT: no staging file at {path}; run first")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _require_projection(conn: sqlite3.Connection, target: Path) -> None:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master"
        " WHERE type = 'table' AND name = 'cat_links'").fetchone()
    if not row or not row[0]:
        raise SystemExit(
            f"ABORT: {target} has no cat_links projection;"
            " run catalog_v2.project first")


def _print_plan(plan: dict, strata_info: dict) -> None:
    print(f"population (probeable projected links): {plan['population']:,}"
          f" of {plan['total_links']:,} cat_links"
          f" ({plan['unprobeable']:,} unprobeable)")
    print(f"hosts: {plan['hosts']} (sample limit {plan['limit']},"
          f" sampled {plan['sampled']})")
    print("allocation (top 10 hosts by sample):")
    for host, n in sorted(plan["allocation"].items(),
                          key=lambda item: -item[1])[:10]:
        print(f"  {host}: {n} of {strata_info['by_host'][host]:,}")
    small = [host for host, n in plan["allocation"].items() if n < MIN_PER_HOST]
    if small:
        print(f"per-host percentage: {len(small)} sampled host(s) below"
              f" {MIN_PER_HOST} links — no percentage is claimed for them")
    print(f"estimated wall time at the polite ceiling: ~{plan['estimated_hours']}h"
          f" ({plan['sampled']:,} links, 8 workers, 1s host spacing)")
    if estimate_hours(plan["population"]) > 72:
        print("a full sweep of this population is infeasible on one vCPU"
              " (docs/LINK_HEALTH_SWEEP.md §1); this sample buys one sentence:")
    print(f"  ±{margin(0.5, max(1, plan['sampled'])):.1%} at 95 %"
          f" on the share of sampled links that answer")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded link-health sample: plan | run | status | merge.")
    parser.add_argument("action", choices=("plan", "run", "status", "merge"))
    parser.add_argument("--target", type=Path, default=None,
                        help="catalog database (read-only except merge;"
                        " required for plan/run/merge)")
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING,
                        help="sweep staging file (default %(default)s)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="sample size (default %(default)s)")
    parser.add_argument("--seed", type=int, default=None,
                        help="reservoir seed; omit for a fresh draw")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="probe_many workers (default %(default)s)")
    args = parser.parse_args(argv)
    if args.action != "status" and args.target is None:
        parser.error("--target is required for plan, run and merge")
    if args.action in ("plan", "run", "merge") and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.action == "status":
        # Opened read-write on purpose: a missing staging file means "no run
        # yet", which status reports honestly instead of aborting.
        with _open_staging(args.staging) as staging:
            print(json.dumps(status(staging), indent=2, sort_keys=True,
                             default=str))
        return 0
    with _open_catalog(args.target, read_only=args.action != "merge") as catalog:
        _require_projection(catalog, args.target)
        if args.action == "plan":
            strata_info = strata(catalog)
            allocation = allocate(strata_info["by_host"], args.limit)
            plan = {"population": strata_info["population"],
                    "total_links": strata_info["total_links"],
                    "unprobeable": strata_info["unprobeable"],
                    "limit": int(args.limit),
                    "sampled": min(int(args.limit), strata_info["population"]),
                    "allocation": allocation,
                    "hosts": len(allocation),
                    "estimated_hours": round(estimate_hours(
                        min(int(args.limit), strata_info["population"])), 2)}
            _print_plan(plan, strata_info)
            return 0
        if args.action == "run":
            with _open_staging(args.staging) as staging:
                summary = run_sample(catalog, staging, limit=args.limit,
                                     seed=args.seed, workers=args.workers)
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
            return 0
        with _open_staging(args.staging, read_only=True) as staging:
            summary = merge(catalog, staging)
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
