"""The resolved-link cache: lazy-first reads, eager top-N warming (Session 123).

Scale plan B2 named this module, and the wiring audit listed it under the
server fixes. What it is, precisely:

* LAZY-FIRST: the resolver already stores every resolution on the ledger row
  itself (`download_sources.final_url`, `expires_at`, `last_checked_at`) and
  serves a fresh one without re-unwrapping. This module owns the *freshness
  decision* for that stored resolution — one indexed read, one answer — so the
  warmer, the tests and any future caller apply exactly the rule the resolver
  applies inline in `fast_fetch.resolve_live_source`, instead of each
  retyping it. It does not change what the resolver does on a press.
* EAGER: nothing pre-resolved the links `/play` picks first, so a first press
  paid the full unwrap every time. `warm()` resolves the top-N highest-ranked
  playable public links ahead of presses, which fills the row cache the
  resolver then serves from. The default N is 200 (the scale plan's number);
  the caller paces the run — resolving is network work, seconds per link.

Why there is no second table: the row already stores the resolution and its
measured lifetime, and a second store would be a second truth that drifts
(the scale plan's own warning was "do NOT trust DB expires_at — zero rows";
on the live catalog only 298 of 4,074,415 rows carry one, because most hosts
declare no lifetime and the resolver honestly clears it. The cache's job is
to warm the rows that *can* be fresh and to read the freshness rule in one
place — not to invent a lifetime the host never declared). The ledger row is
the cache; this module is its reader and its warmer.

The adult rule: the eager set is public links only. A flagged work's links
are never pressed publicly, so warming them would spend unwrap work on
addresses no viewer may ever be served — and a warmer that touched them
would be a second surface that knows about rows the public must not see.
"""
from __future__ import annotations

import sqlite3
import time

#: The temporary-link ceiling, in hours — the same number the resolver
#: applies inline when a stored resolution carries no measured expiry
#: (`fast_fetch.resolve_live_source`: a temporary row whose `last_checked_at`
#: is older than this is re-resolved). A measured `expires_at` always beats
#: it; a host that declared no lifetime keeps `expires_at` NULL, and the
#: next press falls back to this ceiling rather than to an invented window.
TEMPORARY_FRESH_HOURS = 6.0

#: How many failed link ids a warm report carries. The counts are the whole
#: report; the ids are only the first few, for the log line.
_MAX_FAILURE_IDS = 20

#: Playabilities a press can serve. `download`-only copies never play, so
#: warming them would spend unwrap work on addresses no player may use.
_PLAYABLE_KINDS = ("stream", "both")


def freshness(conn: sqlite3.Connection, link_id: int, *,
              now: float | None = None) -> dict | None:
    """Whether one link's stored resolution is fresh, or None for no row.

    The answer mirrors the resolver's own freshness branch, in order:

    * no `final_url` stored — stale (`no_cached_url`): there is nothing to
      serve without unwrapping;
    * a measured `expires_at` — fresh while it lies in the future, stale
      once past (`measured_window` either way);
    * no measured expiry and the row is temporary — fresh while
      `last_checked_at` is inside the 6-hour ceiling, stale after it
      (`temporary_ceiling` / `temporary_stale`); an unreadable timestamp
      is stale, like the resolver's own `except` branch;
    * no measured expiry and the row is permanent — fresh
      (`permanent_cached`): a permanent address is served as stored, and
      the probe the resolver runs on press is what proves it, not this read.
    """
    moment = time.time() if now is None else float(now)
    row = conn.execute(
        "SELECT id, final_url, is_temporary, expires_at, last_checked_at "
        "FROM download_sources WHERE id = ?", (int(link_id),)).fetchone()
    if row is None:
        return None
    _id, final_url, is_temporary, expires_at, last_checked_at = row
    if not (final_url or "").strip():
        return {"fresh": False, "reason": "no_cached_url",
                "expires_at": None, "expires_in": None}
    if expires_at is not None:
        try:
            stamp = float(expires_at)
        except (TypeError, ValueError):
            # An unreadable stamp is no measurement at all — fall through
            # to the ceiling/permanent branch below, like the resolver's
            # `_expiry_fields` returning None/None, instead of inventing
            # a verdict from a value nobody can read.
            stamp = None
        if stamp is not None:
            remaining = stamp - moment
            return {"fresh": remaining > 0, "reason": "measured_window",
                    "expires_at": stamp, "expires_in": max(0.0, round(remaining, 3))}
    if int(is_temporary or 0):
        if not last_checked_at:
            return {"fresh": False, "reason": "temporary_stale",
                    "expires_at": None, "expires_in": None}
        try:
            checked = time.mktime(time.strptime(
                str(last_checked_at).split(".")[0], "%Y-%m-%d %H:%M:%S"))
        except (TypeError, ValueError):
            return {"fresh": False, "reason": "temporary_stale",
                    "expires_at": None, "expires_in": None}
        age_hours = (moment - checked) / 3600.0
        return {"fresh": age_hours <= TEMPORARY_FRESH_HOURS,
                "reason": "temporary_ceiling" if age_hours <= TEMPORARY_FRESH_HOURS
                else "temporary_stale",
                "expires_at": None,
                "expires_in": max(0.0, round(
                    (TEMPORARY_FRESH_HOURS - age_hours) * 3600.0, 3))}
    return {"fresh": True, "reason": "permanent_cached",
            "expires_at": None, "expires_in": None}


def top_links(conn: sqlite3.Connection, *, limit: int = 200) -> list[int]:
    """The eager set: the highest-ranked playable public links.

    Ordered by the projector's `rank_score` — the same order `/play` picks
    from — so the links a press reaches first are the ones warmed first.
    Public only (`cat_works.is_18_plus = 0`); `download`-only copies are
    excluded (they never play); rows with no ledger id cannot be resolved.
    `state` is deliberately NOT filtered: an `unchecked` link has earned no
    verdict yet, and filtering on it would warm nothing on a fresh catalog.
    """
    rows = conn.execute(
        """
        SELECT l.ledger_link_id
        FROM cat_links l
        JOIN cat_works w ON w.id = l.work_id
        WHERE w.is_18_plus = 0
          AND l.playability IN ('stream', 'both')
          AND l.ledger_link_id IS NOT NULL
        ORDER BY l.rank_score DESC, l.id ASC
        LIMIT ?
        """, (int(limit),)).fetchall()
    return [int(row[0]) for row in rows]


def warm(conn: sqlite3.Connection, *, limit: int = 200, resolve=None,
         now: float | None = None) -> dict:
    """Resolve the eager set ahead of presses, and report what happened.

    Links whose stored resolution is already fresh are skipped, not
    re-resolved — the warm fills cold rows, it does not churn warm ones.
    Each remaining link is resolved once through `resolve` (default:
    `fast_fetch.resolve_live_source`, imported lazily so this module stays
    importable without the resolver); a resolver that returns
    `success: False`, or raises, counts as failed and never aborts the run.
    The report is counts plus the first few failed ids, for the log line.
    """
    if resolve is None:
        import fast_fetch

        resolve = fast_fetch.resolve_live_source
    report = {"attempted": 0, "already_fresh": 0, "refreshed": 0,
              "served_cached": 0, "failed": 0, "failures": []}
    for link_id in top_links(conn, limit=limit):
        report["attempted"] += 1
        fresh = freshness(conn, link_id, now=now)
        if fresh is not None and fresh["fresh"]:
            report["already_fresh"] += 1
            continue
        try:
            answer = resolve(int(link_id)) or {}
        except Exception:      # noqa: BLE001 — one dead link must not end the run
            answer = {}
        if not isinstance(answer, dict) or not answer.get("success"):
            report["failed"] += 1
            if len(report["failures"]) < _MAX_FAILURE_IDS:
                report["failures"].append(int(link_id))
        elif answer.get("refreshed"):
            report["refreshed"] += 1
        elif answer.get("cached"):
            report["served_cached"] += 1
        else:
            report["refreshed"] += 1
    return report
