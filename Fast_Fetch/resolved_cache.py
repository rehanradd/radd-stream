#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolved_cache — the Phase-1 pre-resolve cache (design: /tmp/resolved_cache_design.md).

Every play request today runs ``resolve_live_source`` inside the request path: a
refresh decision tree plus a live probe, measured at ~42s solo and ~130s under
8-way concurrency on this 1-CPU VM. This table moves that cost off the request
path: a fresh, probe-accepted row here answers the stream route with an instant
302, and the expensive resolver only runs on a miss (or in the prefetch pool,
later, with ``source='pool'``).

What a row means
--------------
A row exists only because some URL was *accepted* — written here after a
``resolve_live_source`` success (which has already passed the stage-2 strict
gate) or after a pool worker probes it.  Unprobed scraper defaults never enter
this table; that is the whole point (see the 4.0M-`active`-vs-21-probed audit).

Category / kind are ORTHOGONAL, deliberately:
  * ``category`` — who minted the URL: ``'A'`` a direct-CDN file host that
    ``host_classifier.is_direct_file`` recognizes by BOTH service label and
    URL host (pixeldrain, r2/google_cdn, fastdl.beer — never hubcloud, whose
    unwrap fails open onto an HTML page), ``'B'`` everything the classifier
    does not vouch for as a direct file. It chooses the freshness cap.
  * ``kind`` — what the answer *is*: ``'file'`` or ``'playlist'``. mxdrop and
    pkembed are category B but sign category-A-shaped *file* URLs, and the
    stage-2 rule "a playlist is never a download" is enforced on ``kind``.

Freshness is epoch REAL everywhere — never a localized timestamp string. The
v1 staleness check (``fast_fetch.py`` ``resolve_live_source``, the
``time.strptime``+``time.mktime`` branch) over-ages every link by the host's
UTC offset (5h on this PKT box); this module must not inherit that bug.

``ip_bound`` (NULL=untested / 0=no / 1=yes) guards the one thing a shared cache
gets wrong: a CDN token bound to the *requesting* IP must not be replayed to
another client.  ``lookup_cache`` refuses ``ip_bound=1`` rows unless the caller
explicitly opts in (same-IP serving), which the request path never does today.
"""

from __future__ import annotations

import sqlite3
import time
import urllib.parse

__all__ = [
    "init_resolved_cache",
    "lookup_cache",
    "record_resolved_cache",
    "note_failure",
    "REVERIFY_MARGIN_SECONDS",
    "MAX_FAIL_COUNT",
]

#: A cache row is refused inside this margin of its measured death, so a token
#: never dies in flight between our 302 and the player's first byte.
REVERIFY_MARGIN_SECONDS = 60.0
#: Consecutive client failure reports (POST /links/{id}/report "failed") after
#: which a nominally fresh row stops being served, until a fresh resolve resets
#: it. This is the circuit that keeps a poisoned or revoked URL out of service.
MAX_FAIL_COUNT = 3
#: No-measurement trust ceilings (seconds): the resolver's 6h temporary-token
#: heuristic for temporaries, and a full day for permanent direct files.
HEURISTIC_CAP_TEMPORARY_SECONDS = 6 * 3600.0
HEURISTIC_CAP_PERMANENT_SECONDS = 24 * 3600.0
#: A measured window longer than this still gets re-verified by this clock, so
#: a "permanent" signed URL cannot sit in the cache forever (the hoster can
#: revoke mid-window; only the pool re-probe refreshes it).
POOL_RECHECK_SECONDS = 24 * 3600.0

#: Playlist media types — kind derivation only.
_PLAYLIST_MIMES = ("application/vnd.apple.mpegurl", "application/x-mpegurl",
                   "audio/mpegurl", "application/dash+xml")

#: One statement per entry — NEVER conn.executescript(): it issues an
#: implicit COMMIT first, which would hijack whatever the calling transaction
#: had pending on this shared connection (crown order qoder12_addendum,
#: defect 1; the record path's "the caller's transaction owns it" contract
#: depends on every statement here running WITHOUT committing).
_DDL_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS resolved_cache (
        link_id           INTEGER PRIMARY KEY,        -- download_sources.id
        url               TEXT NOT NULL,
        category          TEXT NOT NULL CHECK (category IN ('A','B')),
        kind              TEXT NOT NULL CHECK (kind IN ('file','playlist')),
        mime_type         TEXT,
        file_size_bytes   INTEGER,
        resolved_at       REAL NOT NULL,              -- epoch seconds (time.time)
        expires_at        REAL,                       -- epoch; NULL = never measured
        reverify_after    REAL NOT NULL,              -- hit is valid while now < this
        is_resumable      INTEGER NOT NULL DEFAULT 0 CHECK (is_resumable IN (0,1)),
        http_status       INTEGER,
        source            TEXT NOT NULL DEFAULT 'jit'
                              CHECK (source IN ('pool','jit')),
        ip_bound          INTEGER CHECK (ip_bound IN (0,1)),   -- NULL = untested
        fail_count        INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rc_reverify ON resolved_cache(reverify_after)",
    ("CREATE INDEX IF NOT EXISTS idx_rc_expiry "
     "ON resolved_cache(expires_at) WHERE expires_at IS NOT NULL"),
)

# A missing table is the common case (fresh DB), a present table the hot case;
# probe with a prepared no-op read rather than running DDL on every request.
_SCHEMA_OK = "resolved_cache"


def _is_concurrent_create(exc: sqlite3.OperationalError) -> bool:
    """True only for ``already exists`` — the signature of another connection
    having run the same DDL between our existence-check and our create.
    A typo'd column or a broken statement is NOT this failure and must never
    be tolerated the same way (crown order qoder12_night, Step 0)."""
    return "already exists" in str(exc).lower()


def init_resolved_cache(conn: sqlite3.Connection) -> None:
    """Create the table and its indexes, one statement per ``execute``.

    Deliberately NOT ``executescript`` — that commits the caller's pending
    transaction first (addendum defect 1). Every statement is IF NOT EXISTS,
    so a creator that lost the race is recognised from its error text and
    treated as success; any other OperationalError re-raises unchanged.
    Idempotent; safe to call per request; never commits anything by itself.
    """
    for statement in _DDL_STATEMENTS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if not _is_concurrent_create(exc):
                raise


def _ensure_schema(conn: sqlite3.Connection) -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK is None:
        init_resolved_cache(conn)
        return
    try:
        conn.execute("SELECT 1 FROM resolved_cache LIMIT 0")
    except sqlite3.OperationalError:
        init_resolved_cache(conn)


def _derive_kind(data: dict, url: str) -> str:
    kind = data.get("kind")
    if kind in ("file", "playlist"):
        return kind
    mime = (data.get("mime_type") or "").lower().split(";")[0].strip()
    if mime in _PLAYLIST_MIMES or "mpegurl" in mime or "dash+xml" in mime:
        return "playlist"
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith(".m3u8") or path.endswith(".mpd") or path.endswith(".m3u"):
        return "playlist"
    return "file"


def _derive_category(data: dict, url: str) -> str:
    """Cache horizon A only when BOTH hold — this is the Crown-Prince HIGH-fix:

      1. the service label is itself a trusted direct-file kind, per
         ``host_classifier`` (the single authority — this module keeps no host
         list of its own; the taxonomy-collision ruling says kind letters and
         horizon letters are decided by predicates, not by duplicated tables);
      2. the resolved URL's HOST names a direct-file host (``is_direct_file``).

    A service name alone no longer mints A. That was the defect: the HubCloud
    unwrap (``fast_fetch.unwrap_hubcloud``) fails open — it hands back the
    HTML landing page with ``service="hubcloud", is_temporary=0`` — and the
    old marker list gave that bridge 24h of permanent-file trust. A bridge,
    a drive-viewer page, or an unrecognised host now caps at the 6h
    temporary horizon, the safe direction.
    """
    service = (data.get("service") or "").strip().lower()
    if not service:
        return "B"
    try:
        import host_classifier
    except Exception:      # noqa: BLE001 — degraded: trust nothing, cap B
        return "B"
    if not host_classifier.is_direct_file("", service):
        return "B"
    return "A" if host_classifier.is_direct_file(url) else "B"


def _epoch(value) -> float | None:
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return None
    return stamp


def _compute_reverify_after(*, resolved_at: float, expires_at: float | None,
                           category: str, is_temporary: bool,
                           now: float) -> float:
    """The one-column freshness horizon: a hit is served while now < this."""
    cap = (HEURISTIC_CAP_TEMPORARY_SECONDS if is_temporary or category == "B"
           else HEURISTIC_CAP_PERMANENT_SECONDS)
    if expires_at is not None:
        # A measured (or packer-signed) window beats every heuristic — but it
        # is still capped, so a hoster promise of "7 days" cannot go a week
        # without re-verification.
        horizon = min(expires_at, resolved_at + max(cap, POOL_RECHECK_SECONDS))
    else:
        horizon = resolved_at + cap
    return horizon - REVERIFY_MARGIN_SECONDS


def record_resolved_cache(conn: sqlite3.Connection, link_id: int,
                          data: dict, *, source: str = "jit",
                          now: float | None = None) -> dict | None:
    """Upsert the cache row for ``link_id`` from a successful resolve answer.

    ``data`` is the dict ``resolve_live_source`` returns (``url`` required;
    ``mime_type``, ``file_size_bytes``, ``is_resumable``, ``http_status``,
    ``expires_at``/``expires_in``, ``is_temporary``, ``service``, ``ip_bound``
    used where present). Returns the stored row summary, or None when there was
    nothing to cache (no url). Does NOT commit — the caller's transaction owns
    that, matching ``fast_fetch.get_db`` and ``viewer.get_db`` semantics.
    """
    url = data.get("url")
    if not url:
        return None
    if data.get("stale"):
        # v1's frozen-URL envelope (success+stale): a URL we could NOT
        # re-resolve is never bankable, whoever the caller is. The pool's
        # v2 contract already refuses it; this makes the cache independent
        # of the caller remembering (emperor order, pool healing).
        return None
    _ensure_schema(conn)
    if source not in ("pool", "jit"):
        raise ValueError(f"invalid source {source!r}")
    resolved_at = _epoch(data.get("resolved_at")) or now or time.time()
    expires_at = _epoch(data.get("expires_at"))
    if expires_at is None:
        remaining = _epoch(data.get("expires_in"))
        if remaining is not None:
            expires_at = resolved_at + max(0.0, remaining)
    kind = _derive_kind(data, url)
    category = _derive_category(data, url)
    is_temporary = bool(data.get("is_temporary"))
    reverify_after = _compute_reverify_after(
        resolved_at=resolved_at, expires_at=expires_at, category=category,
        is_temporary=is_temporary, now=now or time.time())
    ip_bound = data.get("ip_bound")
    if ip_bound is not None:
        ip_bound = 1 if ip_bound else 0
    conn.execute(
        """
        INSERT INTO resolved_cache (link_id, url, category, kind, mime_type,
            file_size_bytes, resolved_at, expires_at, reverify_after,
            is_resumable, http_status, source, ip_bound, fail_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)
        ON CONFLICT(link_id) DO UPDATE SET
            url=excluded.url, category=excluded.category, kind=excluded.kind,
            mime_type=excluded.mime_type,
            file_size_bytes=excluded.file_size_bytes,
            resolved_at=excluded.resolved_at, expires_at=excluded.expires_at,
            reverify_after=excluded.reverify_after,
            is_resumable=excluded.is_resumable,
            http_status=excluded.http_status, source=excluded.source,
            ip_bound=excluded.ip_bound, fail_count=0
        """,
        (int(link_id), url, category, kind, data.get("mime_type"),
         data.get("file_size_bytes"), resolved_at, expires_at, reverify_after,
         1 if data.get("is_resumable") else 0, data.get("http_status"),
         source, ip_bound))
    return {"link_id": int(link_id), "url": url, "category": category,
            "kind": kind, "expires_at": expires_at, "source": source,
            "reverify_after": reverify_after}


def note_failure(conn: sqlite3.Connection, link_id: int) -> int:
    """Close the circuit for one link whose URL was just probed and found dead.

    This is the incrementer the guard in ``lookup_cache`` reads — without it
    ``fail_count`` stays 0 forever and a known-dead URL is re-served and
    re-probed indefinitely (addendum defect 2). The request path calls it
    exactly where a dead URL is *measured*, not assumed: after
    ``resolve_live_source`` has run its probes and answered without a playable
    URL (or with a stale one). Returns the number of rows touched (0 when the
    link has no cache row — a failure of an uncached link is not circuit
    evidence). Like ``record_resolved_cache`` this does NOT commit; the
    caller's transaction owns it."""
    _ensure_schema(conn)
    cur = conn.execute(
        "UPDATE resolved_cache SET fail_count = fail_count + 1 "
        "WHERE link_id = ?", (int(link_id),))
    return cur.rowcount


def lookup_cache(conn: sqlite3.Connection, link_id: int, want: str = "watch", *,
                 allow_ip_bound: bool = False,
                 now: float | None = None) -> dict | None:
    """Return a servable cache row for ``link_id``, or None (miss).

    ``want`` mirrors the stage-2 gate: ``"download"`` accepts a single file
    only — a playlist is segments, not a file — ``"watch"`` accepts playlist or
    file. A row is refused when its horizon has passed, when the failure
    circuit is open, or (unless the caller opts in) when it is marked
    IP-bound, because a shared cache must not replay one client's token to
    another. This is the only check the cache path adds over the request
    route's own adult/18+ gate, which must ALWAYS run before this function.
    """
    if want not in ("watch", "download", "either"):
        want = "either"
    _ensure_schema(conn)
    now = now if now is not None else time.time()
    sql = ("SELECT link_id, url, category, kind, mime_type, file_size_bytes, "
           "resolved_at, expires_at, reverify_after, is_resumable, http_status, "
           "source, ip_bound, fail_count FROM resolved_cache "
           "WHERE link_id = ? AND reverify_after > ? AND fail_count < ?")
    params: list = [int(link_id), now, MAX_FAIL_COUNT]
    if want == "download":
        sql += " AND kind = 'file'"
    if not allow_ip_bound:
        sql += " AND (ip_bound IS NULL OR ip_bound = 0)"
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    hit = dict(zip((c for c in _ROW_COLUMNS), tuple(row)))
    hit["expires_in"] = (max(0.0, round(hit["expires_at"] - now, 3))
                         if hit["expires_at"] is not None else None)
    return hit


_ROW_COLUMNS = ("link_id", "url", "category", "kind", "mime_type",
                "file_size_bytes", "resolved_at", "expires_at",
                "reverify_after", "is_resumable", "http_status", "source",
                "ip_bound", "fail_count")
