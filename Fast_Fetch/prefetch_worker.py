#!/usr/bin/env python3
"""
Fast_Fetch/prefetch_worker.py — background prefetch pool for Tier-1 stream links.
═════════════════════════════════════════════════════════════════════════════
`resolved_cache.py` says the expensive resolver should run "on a miss (or in
the prefetch pool, later, with source='pool')". This is that pool worker.

The JIT resolver (`fast_fetch.resolve_live_source`) turns a stored bridge URL
into a playable token when a user asks for it. That is correct but cold: the
first viewer of a popular title pays the full unwrap latency (measured ~42 s
solo on this box), and a token that quietly died mid-evening fails in the
player instead of at the desk. This daemon keeps the hottest end of the
catalog warm so the stream route answers from cache:

* It selects the top N (default 200) priority titles. No play-count column
  exists in the ledger (`viewer.py` says the same and refuses to invent one),
  so priority uses the only popularity-adjacent signal we carry: how many
  prints and mirrors the catalog holds for the work, tie-broken by recency —
  identical to the "trending" sort already published by the browse API.
* For each title it finds the Tier-1 link: the single best *playable* winner
  across the title's releases, ranked by `tiers.for_release` (band, then
  playback kind, then live-ness, then measured server preference) — the exact
  link the "Auto" player would start at.
* Warmth is judged by `resolved_cache.lookup_cache` itself, so the pool and
  the request path share one freshness rule: a row counts when its horizon
  (`reverify_after`, already capped and margin-adjusted from the observed
  TTL) still lies at least one hour ahead. Anything else — missing, inside
  the hour, failure-circuited, IP-bound — is re-resolved through the
  production JIT path and written back with `record_resolved_cache(...,
  source='pool')`, which stores the *observed* expiry and only the heuristics
  when the host declared nothing. A row is never written for a failed
  resolve: the table holds accepted URLs only. Failed links are backed off
  in-process (the schema deliberately has no failure row), so a dead Tier-1
  candidate is retried every `--fail-backoff` seconds rather than every
  sweep.

Politeness is part of the contract: one resolve at a time, a fixed delay
between resolves, and a `/proc/loadavg` gate before every single one — this
box also serves the API, and a warm-up that slows down live playback has
failed at its own job. Measured 2026-11-04: this host idles at load 6–8, so
the default ceiling of 2.0 parks the worker permanently; run it with
`--load-ceiling` tuned for the box (or let it fire only in quiet windows).

Adult law applies here before anywhere else: the priority query excludes
`is_18_plus=1` posts *and* any post sharing a `canonical_key` with a flagged
one, so this worker never even resolves a link for a flagged work, let alone
caches a playable token for it. The JIT path would refuse too (and answers
`not_found` under v2); refusing earlier is cheaper and leaves nothing to leak.

Stdlib only, like everything else in Fast_Fetch. Run it under systemd or
`nohup`; SIGINT/SIGTERM finish the current wait and exit cleanly.

Usage:
    python3 -S Fast_Fetch/prefetch_worker.py                 # daemon, forever
    python3 -S Fast_Fetch/prefetch_worker.py --once          # single pass
    python3 -S Fast_Fetch/prefetch_worker.py --dry-run       # show plan only
    python3 -S Fast_Fetch/prefetch_worker.py --limit 3 --db /tmp/scratch.db
"""

from __future__ import annotations

import argparse
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

#: The pool this worker keeps warm, and the rhythm it keeps it warm with.
TOP_N = 200
RESOLVE_DELAY_SECONDS = 2.0      # between two resolves, never between skips
LOAD_CEILING = 2.0               # 1-minute /proc/loadavg above which we wait
LOAD_POLL_SECONDS = 15.0         # how often we re-read loadavg while gated
MIN_FRESH_WINDOW_SECONDS = 3600.0  # "warm" = horizon at least this far ahead
SCAN_INTERVAL_SECONDS = 900.0    # pause between full sweeps
FAILURE_BACKOFF_SECONDS = 15 * 60.0  # in-process retry delay for cold links

_STOP = False


def _handle_stop(signum, frame):
    global _STOP
    _STOP = True


def log(msg: str) -> None:
    print(f"[prefetch {time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def sleep_chunks(seconds: float) -> None:
    """Sleep that reacts to SIGINT/SIGTERM within a fifth of a second.

    `time.sleep` is restarted after a handled signal since PEP 475, so a
    plain 15-minute sleep would ignore the stop flag for its whole duration.
    """
    deadline = time.time() + seconds
    while not _STOP:
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


def current_load() -> float:
    """1-minute load average, or 0.0 where /proc/loadavg does not exist.

    On a non-Linux box there is no measured number to gate on and inventing
    one would gate us to a fiction; the resolve delay alone still throttles.
    """
    try:
        with open("/proc/loadavg") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def wait_for_quiet_machine(load_ceiling: float) -> tuple[bool, bool]:
    """Returns (did_block, stopping). Blocks until 1-minute loadavg drops to the ceiling."""
    blocked = False
    while not _STOP and current_load() > load_ceiling:
        if not blocked:
            log(f"load {current_load():.2f} > {load_ceiling:.1f}; waiting")
            blocked = True
        sleep_chunks(LOAD_POLL_SECONDS)
    return blocked, _STOP


def select_priority_posts(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Top `limit` works by the ledger's only honest popularity proxy.

    The adult exclusion is deliberately two clauses: a flagged row is out, and
    so is every row whose `canonical_key` names a flagged work — 455 flagged
    works are still reachable under an unflagged twin (AGENTS.md, known hole),
    and a prefetcher must not warm the twin of a hidden title.
    """
    return conn.execute(
        """
        SELECT p.id AS post_id,
               COALESCE(NULLIF(TRIM(p.clean_title), ''), p.title) AS title,
               COUNT(DISTINCT r.id) + COUNT(DISTINCT s.id) AS priority
        FROM posts p
        LEFT JOIN releases r ON r.post_id = p.id
        LEFT JOIN download_sources s ON s.release_id = r.id
        WHERE p.is_18_plus = 0
          AND (p.canonical_key IS NULL OR NOT EXISTS (
                   SELECT 1 FROM posts f
                   WHERE f.is_18_plus = 1 AND f.canonical_key = p.canonical_key))
        GROUP BY p.id
        ORDER BY priority DESC, p.id DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()


def tier1_source_id(conn: sqlite3.Connection, tiers, post_id: int) -> int | None:
    """The download_sources id the "Auto" player would pick first for this work.

    Reuses `tiers.for_release` rather than re-ranking, so there is exactly one
    definition of "best copy" in the repo. Winners are compared by band:
    2160p beats 1080p beats … beats unspecified, and only play-mode tiers
    qualify — a download-only title has nothing to warm.
    """
    best: tuple[int, int] | None = None  # (band_index, source_id); lower index wins
    for release in conn.execute("SELECT * FROM releases WHERE post_id = ?", (post_id,)):
        links = [dict(row) for row in conn.execute(
            "SELECT * FROM download_sources WHERE release_id = ?", (release["id"],))]
        if not links:
            continue
        ladder = tiers.for_release(dict(release), links)
        for tier in ladder.get("tiers", []):
            if tier.get("mode") != "play" or not tier.get("link"):
                continue
            band_index = tiers.BANDS.index(tier["band"]) if tier["band"] in tiers.BANDS \
                else len(tiers.BANDS)
            source_id = tier["link"].get("id")
            if source_id is None:
                continue
            if best is None or band_index < best[0]:
                best = (band_index, int(source_id))
    return best[1] if best else None


def horizon_seconds_left(row: dict, now: float) -> float:
    """How long a cache hit stays servable — the same column the request path obeys.

    `lookup_cache` already refused rows past `reverify_after` (and open failure
    circuits / IP-bound tokens), so any row reaching here is servable; the pool
    asks the stricter question: is it servable a full hour from now?
    """
    return row["reverify_after"] - now


def prefetch_once(*, limit: int, min_fresh: float, load_ceiling: float,
                  fail_backoff: float, dry_run: bool, verbose: bool,
                  _failure_backoff: dict[int, float]) -> dict:
    import fast_fetch
    import resolved_cache
    import tiers

    stats = {"posts": 0, "tier1": 0, "warm": 0, "resolved": 0,
             "failed": 0, "skipped_no_link": 0, "gated": 0}
    now = time.time()
    with fast_fetch.get_db() as conn:
        resolved_cache.init_resolved_cache(conn)
        conn.commit()
        posts = select_priority_posts(conn, limit)
        stats["posts"] = len(posts)
        if verbose or dry_run:
            log(f"selected {len(posts)} priority titles")
        resolved_any = False
        for post in posts:
            if _STOP:
                break
            source_id = tier1_source_id(conn, tiers, post["post_id"])
            if source_id is None:
                stats["skipped_no_link"] += 1
                continue
            stats["tier1"] += 1
            hit = resolved_cache.lookup_cache(conn, source_id, now=now)
            if hit is not None and horizon_seconds_left(hit, now) >= min_fresh:
                stats["warm"] += 1
                continue
            if now < _failure_backoff.get(source_id, 0.0):
                continue
            if dry_run:
                log(f"would resolve source #{source_id} for '{post['title']}'")
                stats["resolved"] += 1
                continue
            blocked, stopping = wait_for_quiet_machine(load_ceiling)
            if stopping:
                break
            if blocked:
                stats["gated"] += 1
            if resolved_any:
                sleep_chunks(RESOLVE_DELAY_SECONDS)
            if _STOP:
                break
            resolved_any = True
            try:
                # v2=True: the honest contract. A failed unwrap answers
                # no_playable_source instead of success+stale, and the cache
                # must never store a URL we believe is dead. Adult refusal is
                # already guaranteed by the query; v2 additionally keeps a
                # typo'd id indistinguishable from a hidden one.
                result = fast_fetch.resolve_live_source(source_id, v2=True)
            except Exception as exc:  # a broken resolve must not kill the daemon
                result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            stats["resolved"] += 1
            if result.get("success"):
                _failure_backoff.pop(source_id, None)
                stored = resolved_cache.record_resolved_cache(
                    conn, source_id, result, source="pool")
                conn.commit()
                if verbose:
                    remaining = (horizon_seconds_left(stored, time.time())
                                 if stored else 0.0)
                    log(f"warm #{source_id} '{post['title']}' "
                        f"horizon {remaining / 3600.0:.1f}h "
                        f"({stored['category']}/{stored['kind']})" if stored else
                        f"resolve for #{source_id} returned no cacheable url")
            else:
                stats["failed"] += 1
                _failure_backoff[source_id] = time.time() + fail_backoff
                log(f"cold #{source_id} '{post['title']}': "
                    f"{result.get('error') or result.get('code')}")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Background prefetch pool keeping Tier-1 links warm in resolved_cache.")
    parser.add_argument("--limit", type=int, default=TOP_N,
                        help=f"priority titles per sweep (default {TOP_N})")
    parser.add_argument("--db", default=None,
                        help="ledger path (default: config DB_PATH / RADD_DB_PATH)")
    parser.add_argument("--interval", type=float, default=SCAN_INTERVAL_SECONDS,
                        help="seconds between sweeps (default 900)")
    parser.add_argument("--min-fresh", type=float, default=MIN_FRESH_WINDOW_SECONDS,
                        help="cache horizon must outlive this many seconds (3600)")
    parser.add_argument("--load-ceiling", type=float, default=LOAD_CEILING,
                        help="max 1-minute loadavg before resolving (2.0)")
    parser.add_argument("--fail-backoff", type=float, default=FAILURE_BACKOFF_SECONDS,
                        help="seconds before retrying a failed link (900)")
    parser.add_argument("--once", action="store_true", help="single sweep, then exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be resolved; touch nothing remote")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.db:
        # Must precede the fast_fetch import: config.py freezes DB_PATH at
        # import time, and fast_fetch.resolve_live_source writes through it.
        os.environ["RADD_DB_PATH"] = str(Path(args.db).resolve())

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    log(f"starting: top {args.limit}, fresh window {args.min_fresh:.0f}s, "
        f"load ceiling {args.load_ceiling:.1f}, "
        f"db {os.environ.get('RADD_DB_PATH', 'default')}")
    failure_backoff: dict[int, float] = {}
    while True:
        started = time.time()
        try:
            stats = prefetch_once(limit=args.limit, min_fresh=args.min_fresh,
                                  load_ceiling=args.load_ceiling,
                                  fail_backoff=args.fail_backoff,
                                  dry_run=args.dry_run, verbose=args.verbose,
                                  _failure_backoff=failure_backoff)
            log("sweep: " + " ".join(f"{k}={v}" for k, v in stats.items()) +
                f" in {time.time() - started:.1f}s")
        except Exception as exc:
            log(f"sweep failed: {type(exc).__name__}: {exc}")
            if args.dry_run:
                return 1
        if args.once or _STOP:
            return 0
        sleep_chunks(max(1.0, args.interval - (time.time() - started)))
        if _STOP:
            return 0


if __name__ == "__main__":
    sys.exit(main())
