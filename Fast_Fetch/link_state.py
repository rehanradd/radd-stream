#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
link_state.py — propagate ``link_health`` verdicts into the catalog, honestly.

Why this exists
---------------
``link_health.probe()`` has always been able to say *dead* / *expired* /
*resumable* / *http_status* about one URL, and ``fast_fetch.run_health_check()``
can write those three fields for **one post** at a time. Nothing in the repo ever
walked the unified ledger. The result, measured in ``Fast_Fetch/HANDOFF_audit.md``
§5 / defect D7: **every single row** of ``download_sources`` says ``status =
'active'`` (3,070,247 / 3,070,247 in ``merged_catalog.db``, ``last_checked_at``
NULL in all of them, ``http_status`` non-NULL in zero of them).

That blanket claim is not neutral. ``tiers.CANDIDATE_ORDER_SQL`` ranks
``status = 'active'`` above everything, so the projection treats an unprobed row
as a verified winner and the player gets pointed at servers nobody ever knocked
on. And ``/api/v1/stats``'s ``active_sources`` (viewer.py:2583) is
``SELECT COUNT(*) ... WHERE status = 'active'`` — equal to the total by
construction, i.e. meaningless.

What this module adds
---------------------
1. **Four honest ledger statuses.** ``active`` / ``dead`` / ``expired`` (the
   vocabulary ``fast_fetch`` already uses) plus ``unverified`` for "nobody has
   ever knocked on this endpoint". ``classify()`` maps a ``ProbeResult`` to one of
   them with a published table (below). A row that was never probed is *not*
   active, and this module is the only thing that says so.
2. **A batched, resumable, interrupt-safe sweep.** Keyed by an id cursor in
   ``link_state_cursor``; one bounded page of rows per batch; probing happens
   **outside any transaction**; the write is one short ``BEGIN IMMEDIATE`` per
   batch (default 200 rows) so a live crawler never waits behind a 3M-row update
   on a 1-CPU VM. Killed mid-batch, the cursor parks at the last committed row and
   the next run continues there. Without ``--apply`` the CLI is a *plan*: it counts
   the rows that need a verdict and makes no request at all, so pointing it at
   3,070,247 rows is safe.
3. **Zero data loss.** Nothing here deletes or NULLs a row. A dead link keeps its
   URL, its ``resource_id`` and its history, gains ``status='dead'`` + the probe
   evidence, and stays healable (``fast_fetch.heal_post_links`` selects exactly
   ``status IN ('dead','expired')``).
4. **Projection propagation.** The same verdict lands on ``cat_links`` (via the
   new ``cat_links.ledger_link_id`` column, falling back to a URL match for rows
   projected before that column existed) and appends an ``cat_link_evidence`` row,
   so ops see real state without waiting for a multi-hour rebuild.
5. **Honest statistics.** ``status_summary()`` / ``stats_payload()`` count real
   states and report ``unverified_sources`` + ``verification_coverage``, which is
   the number an operator needs and today's SQL cannot produce.

Status mapping (``classify()``, pure and network-free)
------------------------------------------------------
    ok                                    -> active
    http_401 / http_403 / http_429        -> expired   (a token or throttle, not a gone file)
    http_404 / http_410 / http_451        -> dead      (the resource is gone)
    any other 4xx, any 5xx                -> dead
    timeout / dns / tls / conn_reset /
    conn_error / redirect_loop /
    redirect_limit / empty_body           -> dead      (we could not get bytes)
    2xx that answers but is not media
    (not_media, html_page, embed)         -> active    + probe_error recorded
    blocked_target / blocklisted /
    invalid_url                           -> unverified (we never looked; not a verdict)

The ``not_media`` row is deliberate: ``status`` answers *"does this endpoint
answer me?"*, ``playability``/``kind`` answer *"can the player open what it
sent?"*. Bridges and embeds legitimately answer with a page — collapsing those
into ``dead`` would delete 90% of a working catalog on the first sweep, and
marking them ``active`` without a ``probe_error`` would be the same lie we are
removing. Both facts are recorded; ``tiers.score()`` reads ``status`` and the
projection's ``rank_score`` reads ``playability``.

Standard library only. Never imports ``config`` (that would compute, and maybe
create, ``DB_PATH`` while live crawlers hold the catalog).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

try:  # normal package-style import when run as Fast_Fetch/link_state.py
    from Fast_Fetch import link_health
except ImportError:  # running from inside Fast_Fetch/ (the documented way)
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import link_health  # type: ignore

__all__ = [
    "STATUS_ACTIVE", "STATUS_DEAD", "STATUS_EXPIRED", "STATUS_UNVERIFIED",
    "PROJECTED_UNCHECKED",
    "ensure_schema", "ensure_projection_schema", "connect",
    "classify", "is_verified", "effective_status", "should_probe",
    "propagate", "mark_unverified", "iter_pending",
    "status_summary", "stats_payload", "sync_projection", "candidate_links",
]

# ── vocabulary ───────────────────────────────────────────────────────────────

STATUS_ACTIVE = "active"
STATUS_DEAD = "dead"
STATUS_EXPIRED = "expired"
STATUS_UNVERIFIED = "unverified"
#: Every status this module will ever write into ``download_sources.status``.
LEDGER_STATUSES = (STATUS_UNVERIFIED, STATUS_ACTIVE, STATUS_DEAD, STATUS_EXPIRED)
#: A never-checked ledger row projects as ``unchecked``, which is already a legal
#: v2 value (api_v2.py:456) and already scores 0 in the rank ladder
#: (catalog_v2.py). ``unverified`` is the *ledger* word; ``unchecked`` is the
#: *projection*'s word for the same fact — one meaning, two published vocabularies.
PROJECTED_UNCHECKED = "unchecked"

_ERROR_CODES = ("timeout", "dns", "tls", "conn_reset", "conn_error",
                "redirect_loop", "redirect_limit", "empty_body",
                "invalid_url", "head_unsupported")
#: error codes that mean "we refused to look", so the row has no verdict at all.
_NO_VERDICT_ERRORS = ("blocked_target", "blocklisted", "invalid_url")

# ── knobs sized for a 1-CPU VM next to a live crawler ────────────────────────

DEFAULT_BATCH_SIZE = 200          # rows per page
MAX_BATCH_SIZE = 5000             # a page this big would hold the write lock too long
DEFAULT_BUSY_TIMEOUT_MS = 5000
#: How far ahead of the cursor a page may reach before a row is probed. Rows whose
#: URL is not probeable (magnet:, empty) are skipped without a write, so the cursor
#: must be able to move past them — that is what this window is for.
_SCAN_WINDOW_MULTIPLIER = 20
#: A verified row is re-probed once its verdict is older than this (30 days).
DEFAULT_STALE_AFTER_SECONDS = 30 * 86400


# ── schema (additive only, never destructive) ────────────────────────────────

#: column name -> DDL type, added to ``download_sources`` by ``ensure_schema``.
#: Everything here is new evidence the ledger has never carried; the columns the
#: old health checker already wrote (``status``, ``http_status``, ``is_resumable``,
#: ``file_size_bytes``, ``mime_type``, ``last_checked_at``) are reused, not cloned.
LEDGER_COLUMNS = {
    "checked_at": "REAL",            # unix epoch of the probe that produced `status`
    "probe_error": "TEXT",           # link_health's stable error code, "" when clean
    "protocol": "TEXT",              # hls|dash|progressive|embed|html_page|unusable
    "latency_ms": "INTEGER",
    "speed_mbps": "REAL",
    "cors_open": "INTEGER DEFAULT 0",
}

CURSOR_DDL = """
CREATE TABLE IF NOT EXISTS link_state_cursor (
    scope TEXT PRIMARY KEY,
    last_id INTEGER NOT NULL DEFAULT 0,
    rows_checked INTEGER NOT NULL DEFAULT 0,
    rows_updated INTEGER NOT NULL DEFAULT 0,
    rows_probed INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'running',
    run_id TEXT,
    started_at REAL,
    updated_at REAL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS link_state_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    rows_checked INTEGER NOT NULL DEFAULT 0,
    rows_updated INTEGER NOT NULL DEFAULT 0,
    by_status TEXT,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_link_state_checked
    ON download_sources(checked_at, id);
"""


def connect(path, *, read_only: bool = False, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
            row_factory: bool = True) -> sqlite3.Connection:
    """Open a catalog. ``read_only`` uses a ``file:...?mode=ro`` URI so an operator
    can inspect a live DB without ever risking a write."""
    text = str(path)
    if read_only:
        uri = f"file:{text}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=busy_timeout_ms / 1000.0)
    else:
        conn = sqlite3.connect(text, timeout=busy_timeout_ms / 1000.0)
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,)).fetchone() is not None


def ensure_schema(conn: sqlite3.Connection) -> dict:
    """Install the ledger columns and cursor tables this module needs.

    Additive and idempotent: existing columns are left exactly as they are, so
    running this against a live catalog is safe. Returns what was added."""
    added = {"columns": [], "tables": []}
    if not _has_table(conn, "download_sources"):
        raise sqlite3.OperationalError(
            "ensure_schema: no download_sources table — is this a ledger catalog?")
    have = _columns(conn, "download_sources")
    for name, ddl in LEDGER_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE download_sources ADD COLUMN {name} {ddl}")
            added["columns"].append(name)
    before = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.executescript(CURSOR_DDL)
    after = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    added["tables"] = sorted(after - before)
    conn.commit()
    return added


def ensure_projection_schema(conn: sqlite3.Connection) -> dict:
    """Give ``cat_links`` the foreign key into the ledger that a projection
    deliberately never had, so a verdict can reach the row the API serves without
    waiting for a rebuild. No-op when the projection is not in this file."""
    added = {"columns": [], "skipped": False}
    if not _has_table(conn, "cat_links"):
        added["skipped"] = True
        return added
    have = _columns(conn, "cat_links")
    if "ledger_link_id" not in have:
        conn.execute("ALTER TABLE cat_links ADD COLUMN ledger_link_id INTEGER")
        added["columns"].append("ledger_link_id")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cat_links_ledger"
                 " ON cat_links(ledger_link_id)")
    conn.commit()
    return added


# ── the verdict ──────────────────────────────────────────────────────────────

def _field(payload, name, default=None):
    if payload is None:
        return default
    if isinstance(payload, dict):
        value = payload.get(name, default)
    else:
        value = getattr(payload, name, default)
    return default if value is None else value


def classify(payload) -> str:
    """``ProbeResult`` (or an equivalent dict) -> one of ``LEDGER_STATUSES``.

    Pure: no clock, no network, no DB, so a test can table-drive every branch."""
    if payload is None:
        return STATUS_UNVERIFIED
    if bool(_field(payload, "ok", False)):
        return STATUS_ACTIVE
    error = str(_field(payload, "error", "") or "")
    status = int(_field(payload, "http_status", 0) or 0)
    if error in _NO_VERDICT_ERRORS:
        return STATUS_UNVERIFIED
    if status in (401, 403, 429):
        return STATUS_EXPIRED
    if status in (404, 410, 451):
        return STATUS_DEAD
    if 400 <= status < 600:
        return STATUS_DEAD
    if error in ("not_media",) or (error == "" and status and status < 400):
        # The endpoint answered; it just did not hand us media. Liveness: true.
        return STATUS_ACTIVE
    if error in _ERROR_CODES:
        return STATUS_DEAD
    if error.startswith("conn_error"):
        return STATUS_DEAD
    return STATUS_DEAD if error else STATUS_UNVERIFIED


def is_verified(row) -> bool:
    """True when something actually knocked on this endpoint.

    ``checked_at`` is this module's timestamp; ``last_checked_at`` / ``http_status``
    are the older health checker's evidence, so a row it measured counts too."""
    checked = _field(row, "checked_at")
    if checked not in (None, "", 0, 0.0):
        return True
    if _field(row, "last_checked_at") not in (None, ""):
        return True
    return _field(row, "http_status") not in (None, 0)


def effective_status(row) -> str:
    """The status a row *means*: an unprobed ``active`` claim is ``unverified``."""
    stored = str(_field(row, "status", "") or "").strip().lower()
    if stored and stored != STATUS_ACTIVE:
        # dead/expired/unverified were written on purpose — never soften them here.
        return stored
    if not is_verified(row):
        return STATUS_UNVERIFIED
    return STATUS_ACTIVE


def projected_state(row) -> str:
    """The projection's word for ``effective_status()``."""
    status = effective_status(row)
    return PROJECTED_UNCHECKED if status == STATUS_UNVERIFIED else status


def should_probe(row) -> bool:
    """Is there anything worth knocking on? ``magnet:``/empty URLs are not links a
    prober can judge, and they must not be silently re-labelled dead."""
    target = str(_field(row, "final_url", "") or _field(row, "source_url", "") or "").strip()
    if not target:
        return False
    return target.lower().startswith(("http://", "https://"))


def verdict_for(row, payload) -> dict | None:
    """Column values to write for one row + one probe. ``None`` = leave the row alone.

    ``checked_at`` is only stamped when the probe really produced a verdict, so a
    row we refused to look at (``blocked_target``) stays ``unverified` and remains
    eligible for a future run that has a legitimate reason to check it."""
    if payload is None:
        return None
    error = str(_field(payload, "error", "") or "")
    status = classify(payload)
    if status == STATUS_UNVERIFIED:
        return None
    now = float(_field(payload, "checked_at", 0.0) or 0.0) or time.time()
    return {
        "id": int(_field(row, "id", 0) or 0),
        "status": status,
        "http_status": int(_field(payload, "http_status", 0) or 0),
        "is_resumable": 1 if bool(_field(payload, "accepts_ranges", False)) else 0,
        "resumable": 1 if bool(_field(payload, "resumable", False)) else 0,
        "file_size_bytes": int(_field(payload, "size_bytes", 0) or 0) or None,
        "mime_type": _field(payload, "content_type", "") or None,
        "protocol": str(_field(payload, "protocol", "") or ""),
        "probe_error": error,
        "cors_open": 1 if bool(_field(payload, "cors_open", False)) else 0,
        "latency_ms": int(_field(payload, "latency_ms", 0) or 0),
        "speed_mbps": float(_field(payload, "download_speed_mbps", 0.0) or 0.0),
        "checked_at": now,
        # The legacy text stamp, in the exact format fast_fetch writes with
        # CURRENT_TIMESTAMP, because tiers._seconds_since() parses that shape.
        "last_checked_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)),
        "source_url": _field(row, "source_url", "") or "",
        "final_url": _field(row, "final_url", "") or "",
    }


# ── the sweep ────────────────────────────────────────────────────────────────

_UPDATE_LEDGER_SQL = """
    UPDATE download_sources
       SET status = :status,
           http_status = :http_status,
           is_resumable = :is_resumable,
           file_size_bytes = COALESCE(:file_size_bytes, file_size_bytes),
           mime_type = COALESCE(:mime_type, mime_type),
           last_checked_at = :last_checked_at,
           checked_at = :checked_at,
           probe_error = :probe_error,
           protocol = :protocol,
           latency_ms = :latency_ms,
           speed_mbps = :speed_mbps,
           cors_open = :cors_open
     WHERE id = :id
"""

_SELECT_PENDING_SQL = """
    SELECT id, release_id, source_url, final_url, service, source_name,
           playback_type, is_temporary, status, http_status, is_resumable,
           last_checked_at{extra}
      FROM download_sources
     WHERE id > :after
       {predicate}
     ORDER BY id
     LIMIT :limit
"""

_BASE_EVIDENCE = ("http_status", "last_checked_at")


def _available_evidence(conn: sqlite3.Connection) -> list[str]:
    """Which evidence columns this ledger really has.

    A read-only inspection of an *uninstalled* catalog (no ``--apply``) must still
    answer, so every query in this module is built from what the table actually
    carries instead of assuming ``ensure_schema()`` already ran."""
    if not _has_table(conn, "download_sources"):
        return []
    have = _columns(conn, "download_sources")
    return [name for name in ("checked_at", *_BASE_EVIDENCE) if name in have]


def _pending_where(*, only_unchecked: bool, stale_after_seconds: float | None,
                   site: str | None, evidence: list[str]) -> tuple[str, dict]:
    """Which rows still need a knock, as (SQL fragment, params it actually uses).

    Index-friendly (`id > cursor` walks the PK) and never re-selects a row this sweep
    answered: a row needs work when *no* evidence column is filled (a legacy
    ``last_checked_at`` from ``fast_fetch.run_health_check`` counts as evidence, so an
    already-measured catalog is not re-probed from zero) or when the verdict is older
    than ``stale_after_seconds``."""
    sql, params = "", {}
    if only_unchecked and evidence:
        empty = []
        for name in evidence:
            if name == "http_status":
                empty.append("(http_status IS NULL OR http_status = 0)")
            else:
                empty.append(f"{name} IS NULL")
        unverified = " AND ".join(empty)
        if stale_after_seconds and "checked_at" in evidence:
            now = time.time()
            stale = "checked_at < :stale_before"
            if "last_checked_at" in evidence:
                stale += " OR datetime(last_checked_at) < datetime(:stale_text)"
                params["stale_text"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.gmtime(now - float(stale_after_seconds)))
            params["stale_before"] = now - float(stale_after_seconds)
            sql = f"AND (({unverified}) OR {stale})"
        else:
            sql = f"AND ({unverified})"
    if site:
        sql += (" AND EXISTS (SELECT 1 FROM releases r"
                " WHERE r.id = download_sources.release_id AND r.source_site = :site)")
        params["site"] = site
    return sql, params


def iter_pending(conn: sqlite3.Connection, *, after_id: int = 0, batch_size: int = DEFAULT_BATCH_SIZE,
                 only_unchecked: bool = True, stale_after_seconds: float | None = None,
                 site: str | None = None, evidence: list[str] | None = None):
    """One bounded page of rows needing a verdict, ordered by rowid.

    Returns ``(rows, page_end_id)``: at most ``batch_size`` *probeable* rows, but the
    scan may reach past them so un-probeable URLs (magnet:, empty) cannot wedge the
    cursor forever. The caller advances to ``page_end_id``, the highest id actually
    seen, probed or not."""
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    evidence = _available_evidence(conn) if evidence is None else list(evidence)
    where, params = _pending_where(only_unchecked=only_unchecked,
                                   stale_after_seconds=stale_after_seconds, site=site,
                                   evidence=evidence)
    sql = _SELECT_PENDING_SQL.format(
        predicate=where,
        extra=", checked_at" if "checked_at" in evidence else "")
    params = dict(params, after=int(after_id), limit=batch_size * _SCAN_WINDOW_MULTIPLIER)
    rows = [dict(row) for row in conn.execute(sql, params)]
    selected, seen = [], int(after_id)
    for row in rows:
        seen = int(row["id"])
        if should_probe(row):
            selected.append(row)
            if len(selected) >= batch_size:
                break
    return selected, seen


def default_prober(rows, *, workers: int = 4, timeout: float | None = None,
                   sample_bytes: int | None = None):
    """Knock on every row through ``link_health.probe_many`` (ordered like input).

    ``allow_private`` is never set: production probing must not touch internal
    addresses (link_health's SSRF guard). Non-media rows come back with a
    ``blocked_target``/transport error and are recorded as such."""
    items = []
    for row in rows:
        item = {"url": row.get("final_url") or row.get("source_url") or "",
                "allow_private": False}
        if row.get("source_url"):
            item["final_url"] = row["source_url"]
        if row.get("service"):
            item["service"] = row["service"]
        items.append(item)
    kwargs = {"workers": max(1, int(workers))}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if sample_bytes is not None:
        kwargs["sample_bytes"] = sample_bytes
    return link_health.probe_many(items, **kwargs)


def _cursor_row(conn, scope: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM link_state_cursor WHERE scope = ?", (scope,)).fetchone()


def _write_cursor(conn, scope: str, *, last_id: int, rows_checked: int, rows_updated: int,
                  rows_probed: int, state: str, run_id: str, started_at: float,
                  detail: str) -> None:
    conn.execute(
        """
        INSERT INTO link_state_cursor (scope, last_id, rows_checked, rows_updated,
            rows_probed, state, run_id, started_at, updated_at, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scope) DO UPDATE SET
            last_id = excluded.last_id,
            rows_checked = link_state_cursor.rows_checked + excluded.rows_checked,
            rows_updated = link_state_cursor.rows_updated + excluded.rows_updated,
            rows_probed = link_state_cursor.rows_probed + excluded.rows_probed,
            state = excluded.state,
            run_id = excluded.run_id,
            updated_at = excluded.updated_at,
            detail = excluded.detail
        """,
        (scope, int(last_id), int(rows_checked), int(rows_updated), int(rows_probed),
         state, run_id, started_at, time.time(), detail))


def _apply_batch(conn, scope: str, run_id: str, started_at: float, updates: list,
                 cursor_to: int, *, sync_proj: bool, evidence: bool,
                 batch_rows: int) -> int:
    """One short write transaction: verdicts + cursor, then release the lock.

    Everything the batch needed from the network happened before this function was
    called, so the exclusive lock lives only for the microseconds an ``executemany``
    of <= ``MAX_BATCH_SIZE`` updates needs. That is the whole reason a 2.3M-row sweep
    can share a database with a live crawler."""
    if not updates:
        with conn:  # BEGIN/COMMIT around the cursor move only
            _write_cursor(conn, scope, last_id=cursor_to, rows_checked=batch_rows,
                          rows_updated=0, rows_probed=0, state="running",
                          run_id=run_id, started_at=started_at, detail="")
        return 0
    params = [
        {key: value for key, value in item.items()
         if key in ("id", "status", "http_status", "is_resumable", "file_size_bytes",
                    "mime_type", "last_checked_at", "checked_at", "probe_error",
                    "protocol", "latency_ms", "speed_mbps", "cors_open")}
        for item in updates
    ]
    by_status: dict[str, int] = {}
    for item in updates:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(_UPDATE_LEDGER_SQL, params)
        if sync_proj:
            _sync_updates(conn, updates, evidence=evidence)
        _write_cursor(conn, scope, last_id=cursor_to, rows_checked=batch_rows,
                      rows_updated=len(params), rows_probed=len(params),
                      state="running", run_id=run_id, started_at=started_at,
                      detail=json.dumps(by_status, sort_keys=True))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(params)


def _sync_updates(conn, updates: list, *, evidence: bool = True) -> None:
    """Mirror verdicts onto ``cat_links`` (and append ``cat_link_evidence``).

    Matched by the new ``ledger_link_id`` first; when that is NULL (a row projected
    before the column existed) fall back to the URL the projection was built from and
    backfill the key, so the next sweep is index-fast. A link that is not in the
    projection is simply not synced — the rebuild picks it up; we never insert
    catalog rows behind the projector's back."""
    touched: list[int] = []
    for item in updates:
        row = conn.execute(
            "SELECT id, ledger_link_id FROM cat_links WHERE ledger_link_id = ? LIMIT 1",
            (item["id"],)).fetchone()
        if row is None and item.get("source_url"):
            row = conn.execute(
                "SELECT id, ledger_link_id FROM cat_links"
                " WHERE url = ? OR url = ? ORDER BY id DESC LIMIT 1",
                (item.get("source_url"), item.get("final_url"))).fetchone()
            if row is not None:
                conn.execute("UPDATE cat_links SET ledger_link_id = ? WHERE id = ?",
                             (item["id"], row["id"]))
        if row is None:
            continue
        link_id = int(row["id"])
        touched.append(link_id)
        conn.execute(
            """
            UPDATE cat_links
               SET state = ?, resumable = ?, accepts_ranges = ?, cors_open = ?,
                   http_status = ?, protocol = ?,
                   content_type = COALESCE(?, content_type),
                   size_bytes = COALESCE(?, size_bytes),
                   latency_ms = ?, speed_mbps = ?, last_evidence_at = ?
             WHERE id = ?
            """,
            (state_for(item["status"]), item["resumable"], item["is_resumable"],
             item["cors_open"], item["http_status"], item["protocol"], item["mime_type"],
             item["file_size_bytes"], item["latency_ms"], item["speed_mbps"],
             item["checked_at"], link_id))
        if evidence and _has_table(conn, "cat_link_evidence"):
            conn.execute(
                """
                INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, http_status,
                    content_type, size_bytes, latency_ms, speed_mbps, accepts_ranges, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (link_id, item["checked_at"], 1 if item["status"] == STATUS_ACTIVE else 0,
                 item["protocol"], item["http_status"], item["mime_type"],
                 item["file_size_bytes"], item["latency_ms"], item["speed_mbps"],
                 item["is_resumable"], item["probe_error"] or None))
    if touched:
        # One scoped rank refresh per batch, AFTER the new columns landed, so the
        # ladder is computed from this probe and not from the values it replaced.
        marks = ",".join(str(int(value)) for value in touched)
        conn.execute(f"UPDATE cat_links SET rank_score = {RANK_SCORE_EXPR}"
                     f" WHERE id IN ({marks})")


def state_for(status: str) -> str:
    """Ledger status -> projected ``cat_links.state``."""
    if not status or status == STATUS_UNVERIFIED:
        return PROJECTED_UNCHECKED
    if status in (STATUS_ACTIVE, STATUS_DEAD, STATUS_EXPIRED):
        return status
    return PROJECTED_UNCHECKED


#: The rank ladder, imported once so the projection and this sync cannot drift.
def _rank_expr() -> str:
    try:
        try:
            from Fast_Fetch import catalog_v2
        except ImportError:
            import catalog_v2  # type: ignore
        return catalog_v2.RANK_SCORE_EXPR
    except Exception:
        return "rank_score"


RANK_SCORE_EXPR = _rank_expr()


def propagate(conn: sqlite3.Connection, *, scope: str = "default", prober=None,
              batch_size: int = DEFAULT_BATCH_SIZE, max_batches: int | None = None,
              workers: int = 4, only_unchecked: bool = True,
              stale_after_seconds: float | None = DEFAULT_STALE_AFTER_SECONDS,
              site: str | None = None, sync_projection: bool | None = None,
              resume: bool = True, progress=None, dry_run: bool = False,
              max_rows: int | None = None, timeout: float | None = None) -> dict:
    """Walk the ledger in bounded pages and write real verdicts. resumable by design.

    Args:
        scope: names one independent cursor, so two sweeps (e.g. per site) never
            fight over one position.
        prober: ``fn(rows) -> sequence of ProbeResult/dict/None``. Defaults to
            :func:`default_prober` (real network, SSRF-guarded). Tests inject a fake.
        batch_size: rows per page (clamped to ``MAX_BATCH_SIZE``).
        max_batches: stop after this many pages — how a cron job takes a slice of a
            3M-row catalog without ever holding the DB.
        only_unchecked: skip rows that already carry a verdict. False re-probes
            everything (idempotent: the same truth written twice changes nothing).
        stale_after_seconds: re-probe a verdict older than this (default 30 days).
        sync_projection: mirror verdicts into ``cat_links``. Auto-detects by default.
        resume: start where the cursor stopped. False rewinds to id 0.
        dry_run: write nothing. Without an explicit ``prober`` it is a *plan*: it
            counts the rows that need a verdict and makes no request at all, so an
            operator can point it at 3M rows and read the number safely. Pass a
            ``prober`` with ``dry_run`` only when knocking is intended.

    Returns a summary dict: rows_checked / rows_updated / batches / by_status /
    last_id / state ('complete' or 'running').
    """
    if not dry_run:
        ensure_schema(conn)
    if sync_projection is None:
        sync_projection = _has_table(conn, "cat_links")
    if sync_projection and not dry_run:
        ensure_projection_schema(conn)
    evidence = _available_evidence(conn)
    # A plan must not reach the network: a dry run over this catalog would else
    # issue three million HTTP requests. Probing only happens when asked for.
    plan_only = bool(dry_run) and prober is None
    prober = prober or (lambda rows: default_prober(rows, workers=workers, timeout=timeout))

    cursor_row_exists = _has_table(conn, "link_state_cursor")
    existing = _cursor_row(conn, scope) if cursor_row_exists else None
    cursor = 0
    started = float(existing["started_at"] or time.time()) if existing else time.time()
    if resume and existing is not None and str(existing["state"]) != "complete":
        cursor = int(existing["last_id"] or 0)
    run_id = f"{int(time.time() * 1000)}-{scope}"
    if not dry_run:
        conn.execute(
            "INSERT INTO link_state_runs (run_id, scope, started_at) VALUES (?, ?, ?)",
            (run_id, scope, started))
        conn.commit()

    summary = {"scope": scope, "run_id": run_id, "batches": 0, "rows_checked": 0,
               "rows_updated": 0, "rows_probed": 0, "by_status": {}, "last_id": cursor,
               "state": "running", "dry_run": bool(dry_run), "plan_only": plan_only,
               "schema_ready": "checked_at" in evidence}
    if plan_only:
        summary["note"] = ("plan: counted the rows that need a verdict, made no request,"
                           " wrote nothing. Pass --apply to work through them.")
    if not evidence:
        summary["note"] = ("no evidence columns and no cursor table: this connection is "
                           "read-only on an uninstalled catalog; every row is pending")
    try:
        while True:
            if max_batches is not None and summary["batches"] >= int(max_batches):
                break
            if max_rows is not None and summary["rows_checked"] >= int(max_rows):
                break
            rows, page_end = iter_pending(conn, after_id=cursor, batch_size=batch_size,
                                          only_unchecked=only_unchecked,
                                          stale_after_seconds=stale_after_seconds, site=site,
                                          evidence=evidence)
            if not rows:
                summary["state"] = "complete"
                break
            if plan_only:
                summary["rows_pending"] = summary.get("rows_pending", 0) + len(rows)
                summary["rows_checked"] += len(rows)
                summary["batches"] += 1
                cursor = int(page_end)
                summary["last_id"] = cursor
                if progress:
                    progress(summary)
                continue
            verdicts = list(prober(rows) or [])
            updates = []
            for index, row in enumerate(rows):
                payload = verdicts[index] if index < len(verdicts) else None
                item = verdict_for(row, payload)
                if item is not None:
                    updates.append(item)
            for item in updates:
                summary["by_status"][item["status"]] = \
                    summary["by_status"].get(item["status"], 0) + 1
            summary["rows_checked"] += len(rows)
            summary["rows_updated"] += 0 if dry_run else len(updates)
            summary["rows_probed"] += len(rows)
            summary["batches"] += 1
            cursor = int(page_end)
            summary["last_id"] = cursor
            if dry_run:
                summary["state"] = "running"
            else:
                _apply_batch(conn, scope, run_id, started, updates, cursor,
                             sync_proj=sync_projection, evidence=True, batch_rows=len(rows))
            if progress:
                progress(summary)
        if not dry_run:
            with conn:
                # A complete walk rewinds to 0 so the next scheduled run (or the
                # stale re-probe) starts from the top; an unfinished one parks the
                # cursor exactly where we stopped, which is the resume point.
                _write_cursor(conn, scope, last_id=0 if summary["state"] == "complete" else cursor,
                              rows_checked=0, rows_updated=0, rows_probed=0,
                              state=summary["state"], run_id=run_id, started_at=started,
                              detail=json.dumps(summary["by_status"], sort_keys=True))
                conn.execute(
                    "UPDATE link_state_runs SET finished_at = ?, rows_checked = ?,"
                    " rows_updated = ?, by_status = ?, detail = 'end' WHERE run_id = ?",
                    (time.time(), summary["rows_checked"], summary["rows_updated"],
                     json.dumps(summary["by_status"], sort_keys=True), run_id))
    except BaseException as exc:  # interrupted, killed, network blowup: keep the cursor
        if not dry_run:
            try:
                with conn:
                    _write_cursor(conn, scope, last_id=cursor, rows_checked=0,
                                  rows_updated=0, rows_probed=0, state="interrupted",
                                  run_id=run_id, started_at=started,
                                  detail=f"{type(exc).__name__}: {exc}"[:400])
                    conn.execute(
                        "UPDATE link_state_runs SET finished_at = ?, rows_checked = ?,"
                        " rows_updated = ?, detail = ? WHERE run_id = ?",
                        (time.time(), summary["rows_checked"], summary["rows_updated"],
                         f"interrupted {type(exc).__name__}"[:200], run_id))
            except sqlite3.Error:
                pass
        raise
    return summary


def mark_unverified(conn: sqlite3.Connection, *, batch_size: int = 1000,
                    max_batches: int | None = None, scope: str = "honesty-backfill",
                    dry_run: bool = False, resume: bool = True) -> dict:
    """Downgrade the *inherited lie*: rows that still say ``active`` but carry no
    evidence of ever being checked become ``unverified``.

    This is what makes ``viewer.py``'s existing
    ``WHERE status = 'active'`` count honest without editing viewer.py. Batched the
    same way as the sweep (bounded page, cursor, one short transaction), because a
    single ``UPDATE`` over 3M rows would lock the catalog against the crawler for
    minutes. Nothing is deleted, and a row re-acquires a real status the moment the
    prober reaches it."""
    ensure_schema(conn)
    cursor_row = _cursor_row(conn, scope)
    cursor = 0 if cursor_row is None or not resume else int(cursor_row["last_id"] or 0)
    if cursor_row is not None and not resume:
        cursor = 0
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    moved = 0
    batches = 0
    while True:
        if max_batches is not None and batches >= int(max_batches):
            break
        ids = [int(row[0]) for row in conn.execute(
            """
            SELECT id FROM download_sources
             WHERE id > ? AND (status IS NULL OR status = '' OR status = 'active')
               AND checked_at IS NULL AND last_checked_at IS NULL
               AND (http_status IS NULL OR http_status = 0)
             ORDER BY id LIMIT ?
            """, (cursor, batch_size)).fetchall()]
        if not ids:
            break
        cursor = ids[-1]
        batches += 1
        if not dry_run:
            marks = ",".join(str(value) for value in ids)
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    f"UPDATE download_sources SET status = '{STATUS_UNVERIFIED}'"
                    f" WHERE id IN ({marks})")
                _write_cursor(conn, scope, last_id=cursor, rows_checked=len(ids),
                              rows_updated=len(ids), rows_probed=0, state="running",
                              run_id=scope, started_at=time.time(), detail="unverified")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        moved += len(ids)
        if len(ids) < batch_size:
            break
    if not dry_run:
        with conn:
            _write_cursor(conn, scope, last_id=0 if max_batches is None else cursor,
                          rows_checked=0, rows_updated=0, rows_probed=0,
                          state="complete" if max_batches is None else "running",
                          run_id=scope, started_at=time.time(), detail="backfill end")
    return {"scope": scope, "batches": batches, "rows_moved": moved,
            "last_id": cursor, "dry_run": bool(dry_run)}


# ── honest statistics ────────────────────────────────────────────────────────

#: Counts keyed by the status a row *means*, so an unprobed ``active`` never
#: inflates ``active_sources``. Built per connection from the columns that exist, so
#: it answers on an uninstalled catalog too (``--stats`` with no ``--apply``).
def _summary_sql(evidence: list[str]) -> str:
    unprobed = " AND ".join(
        "(http_status IS NULL OR http_status = 0)" if name == "http_status"
        else f"{name} IS NULL" for name in evidence) or "1"
    return f"""
    SELECT CASE
             WHEN status IS NULL OR status = '' THEN '{STATUS_UNVERIFIED}'
             WHEN status <> '{STATUS_ACTIVE}' THEN status
             WHEN {unprobed} THEN '{STATUS_UNVERIFIED}'
             ELSE '{STATUS_ACTIVE}'
           END AS state,
           COUNT(*) AS n,
           SUM(CASE WHEN is_resumable = 1 THEN 1 ELSE 0 END) AS resumable,
           SUM(CASE WHEN is_temporary = 1 THEN 1 ELSE 0 END) AS temporary
      FROM download_sources
     GROUP BY state
     ORDER BY n DESC
    """


_PROJECTION_SUMMARY_SQL = """
    SELECT COALESCE(NULLIF(state, ''), 'unverified') AS state, COUNT(*) AS n,
           SUM(CASE WHEN resumable = 1 OR accepts_ranges = 1 THEN 1 ELSE 0 END) AS resumable,
           SUM(CASE WHEN ephemeral = 1 THEN 1 ELSE 0 END) AS temporary
      FROM cat_links
     GROUP BY state
"""


def status_summary(conn: sqlite3.Connection, *, projection: bool = False) -> dict:
    """Real status distribution + verification coverage, or an honest zero.

    ``coverage`` is the number today's dashboard cannot show: how much of the
    catalog we have actually knocked on. An empty catalog reports
    ``{"total": 0, "coverage": 0.0}``, never ``active``."""
    table = "cat_links" if projection else "download_sources"
    if not _has_table(conn, table):
        return {"total": 0, "by_status": {}, "resumable": 0, "temporary": 0,
                 "checked": 0, "coverage": 0.0, "unavailable": table}
    if projection:
        sql = _PROJECTION_SUMMARY_SQL
        unknown = (PROJECTED_UNCHECKED, "unknown", STATUS_UNVERIFIED)
    else:
        sql = _summary_sql(_available_evidence(conn))
        unknown = (STATUS_UNVERIFIED,)
    by_status, resumable = {}, 0
    temporary, checked, total = 0, 0, 0
    for row in conn.execute(sql):
        name = str(row["state"] or STATUS_UNVERIFIED)
        count = int(row["n"] or 0)
        by_status[name] = by_status.get(name, 0) + count
        total += count
        resumable += int(row["resumable"] or 0)
        temporary += int(row["temporary"] or 0)
        if name not in unknown:
            checked += count
    return {
        "total": total,
        "by_status": by_status,
        "resumable": resumable,
        "temporary": temporary,
        "checked": checked,
        "coverage": round(checked / total, 4) if total else 0.0,
    }


def stats_payload(conn: sqlite3.Connection, *, posts_table: str = "posts",
                  releases_table: str = "releases") -> dict:
    """The body ``/api/v1/stats`` should serve.

    Same keys viewer.py returns today (so the shipped Android app keeps working)
    plus the honest extras. ``active_sources`` here counts *verified* liveness:
    an unprobed catalog reports 0 active and ``verification_coverage: 0.0``
    instead of the current 100%-by-construction claim.

    viewer.py:2577-2593 still runs its own SQL
    (``SELECT COUNT(*) FROM download_sources WHERE status = 'active'``), which is
    why ``mark_unverified()`` exists: after that backfill viewer's number is
    honest too, with viewer.py untouched.
    """
    summary = status_summary(conn)
    by_status = summary["by_status"]
    counts = {}
    for name, table in (("posts", posts_table), ("releases", releases_table),
                        ("sources", "download_sources")):
        counts[name] = (int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                        if _has_table(conn, table) else 0)
    return {
        "posts": counts["posts"],
        "releases": counts["releases"],
        "sources": counts["sources"],
        "active_sources": by_status.get(STATUS_ACTIVE, 0),
        "resumable_sources": summary["resumable"],
        "temporary_sources": summary["temporary"],
        "unverified_sources": by_status.get(STATUS_UNVERIFIED, 0),
        "dead_sources": by_status.get(STATUS_DEAD, 0),
        "expired_sources": by_status.get(STATUS_EXPIRED, 0),
        "checked_sources": summary["checked"],
        "verification_coverage": summary["coverage"],
        "by_status": by_status,
    }


# ── read helpers the tier ladder uses ────────────────────────────────────────

def candidate_links(conn: sqlite3.Connection, release_id: int, *, ledger: bool = True) -> list[dict]:
    """One print's links as plain dicts carrying *real* state, ready for
    ``tiers.for_release``.

    A ledger row's ``status`` is deliberately rewritten through
    :func:`effective_status`, so the tier ladder sees ``unverified`` rather than
    the inherited ``active`` claim and refuses to reward it with the +40 liveness
    bonus (tiers.score) it cannot back up."""
    if ledger:
        rows = conn.execute(
            "SELECT * FROM download_sources WHERE release_id = ? ORDER BY id",
            (int(release_id),)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM cat_links WHERE release_id = ? ORDER BY id",
                            (int(release_id),)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["status"] = effective_status(item)
        item.setdefault("is_temporary", item.get("is_temporary") or 0)
        out.append(item)
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="link_state.py",
        description="Propagate link_health verdicts into the catalog ledger, in "
                    "bounded resumable batches.")
    parser.add_argument("--db", required=True, help="catalog SQLite file to work on")
    parser.add_argument("--scope", default="default",
                        help="cursor name (use one per catalog/site slice)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write; without it this is a read-only plan")
    parser.add_argument("--stats", action="store_true",
                        help="print honest status_summary / stats_payload and exit")
    parser.add_argument("--mark-unverified", action="store_true",
                        help="first downgrade evidence-free 'active' rows to 'unverified'")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-batches", type=int, default=None,
                        help="stop after N pages (how a cron job takes a slice)")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--site", default=None, help="only links under one source_site")
    parser.add_argument("--all-rows", action="store_true",
                        help="re-probe rows that already carry a verdict")
    parser.add_argument("--stale-hours", type=float,
                        default=DEFAULT_STALE_AFTER_SECONDS / 3600.0,
                        help="re-probe a verdict older than this (0 = never)")
    parser.add_argument("--restart", action="store_true", help="ignore the saved cursor")
    parser.add_argument("--projection", action="store_true",
                        help="summarise cat_links instead of download_sources for --stats")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    path = Path(args.db)
    if not path.exists():
        print(f"[!] no such database: {path}", file=sys.stderr)
        return 2
    if not args.apply:
        conn = connect(path, read_only=True)
        try:
            if args.stats:
                print(json.dumps(status_summary(conn, projection=args.projection),
                                 indent=2, sort_keys=True))
                return 0
            summary = propagate(
                conn, scope=args.scope, batch_size=args.batch_size,
                max_batches=args.max_batches, max_rows=args.max_rows,
                stale_after_seconds=(args.stale_hours * 3600) if args.stale_hours else None,
                only_unchecked=not args.all_rows, site=args.site,
                resume=not args.restart, dry_run=True)
            summary["plan"] = "read-only connection: nothing was written"
            print(json.dumps(summary, indent=2, sort_keys=True))
            print("[i] pass --apply to probe and write. (Production catalog deploy is the "
                  "operator's call.)", file=sys.stderr)
        finally:
            conn.close()
        return 0

    conn = connect(path)
    try:
        print(f"[i] schema: {ensure_schema(conn)}")
        if args.stats:
            print(json.dumps(stats_payload(conn), indent=2, sort_keys=True))
            return 0
        if args.mark_unverified:
            moved = mark_unverified(conn, batch_size=max(args.batch_size, 1000),
                                    resume=not args.restart)
            print(f"[✓] honesty backfill: {moved['rows_moved']} rows -> '{STATUS_UNVERIFIED}'"
                  f" in {moved['batches']} batches")
        result = propagate(
            conn, scope=args.scope, batch_size=args.batch_size,
            max_batches=args.max_batches, max_rows=args.max_rows, workers=args.workers,
            stale_after_seconds=(args.stale_hours * 3600) if args.stale_hours else None,
            only_unchecked=not args.all_rows, site=args.site, resume=not args.restart,
            progress=lambda done: print(
                f"  [{done['last_id']:>10}] batches={done['batches']}"
                f" checked={done['rows_checked']} updated={done['rows_updated']}"
                f" {done['by_status']}", flush=True))
        result["after"] = status_summary(conn)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
