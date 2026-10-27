#!/usr/bin/env python3
"""admin_panel.py — the operator's control surface over the `cat_*` projection.

═══════════════════════════════════════════════════════════════════════════════
THIS IS NOT REAL WEB AUTHENTICATION. READ THIS BEFORE "IMPROVING" IT.
───────────────────────────────────────────────────────────────────────────────
The gate below (loopback peer + one bearer token compared with
``hmac.compare_digest``) is *not* a login and must never be mistaken for one or
"upgraded" into session cookies, JWTs or a cookie jar. Two hard facts decide it:

  * The host is plain HTTP with no TLS (see ORACLE_DEPLOYMENT.md; the deployed
    address is ``http://92.4.95.252/``). Any bearer token typed into this gate
    travels across the wire *in the clear* — a single sniff on the path steals it,
    and a cookie would be stolen exactly as easily. Adding client-side session
    state would only widen the blast radius; it buys no secrecy that HTTP can't
    provide, and inventing one here would hide that fact behind a confident API.
  * Because the token cannot be kept secret in transit, the loopback requirement
    (the peer address must be 127.0.0.1/::1) plus the deployment rule that
    **nginx must never proxy ``/admin``** is the *actual* protection. The bearer
    token is a second, cheap lock on an already-localhost-only door — a defence
    against a stray local process or a mis-bound socket, not against a network
    attacker who can reach the port.

So the security model is: reachability is controlled by the bind address and the
reverse-proxy config (owned by ``viewer.py`` + nginx, never by this module), and
the token is an operator-consent check on the one machine that is allowed to see
this page. If you are about to add cookies, remember you would be replacing an
honest localhost-only gate with a fake remote-authentication one over cleartext.

───────────────────────────────────────────────────────────────────────────────
DESIGN / CONVENTION (mirrors ``api_v2.py`` deliberately, invents nothing new):
  * Dispatch is ``route_get(path, query, *, db_path, peer_address, token_header)``
    and ``route_post(...)``. Peer address and bearer token are *explicit*
    arguments, never read off a handler object, so this module owns no socket and
    the mounting code in ``viewer.py`` stays the only thing that knows about
    connections, TLS-less transport and header plumbing. That is what makes every
    screen here unit-testable by a plain function call.
  * A route returns the SAME response shape the screens produce — a
    ``(status, content_type, body_bytes)`` tuple — when it answered, and ``None``
    when the path is not under ``/admin`` so the caller falls through. That is
    ``api_v2.route_get``'s "answered / not answered" contract, expressed as a
    value instead of a write, because there is no handler here to write to. JSON
    for ``/admin/api/*`` (``application/json``), one dark HTML page at ``/admin``
    (``text/html``), and ``application/problem+json`` for the refusals — the exact
    content types ``api_v2`` uses, and "unavailable" answers the same 503 with the
    same problem body shape it uses.
  * Nothing here may raise out of a route: every screen catches ``sqlite3.Error``
    and renders an honest empty state for a database that has no ``cat_*`` tables
    at all ("the projection has not been built yet").

PROVENANCE (absolute, ``redact.py`` is the vocabulary owner):
  ``cat_releases`` literally carries ``source_site`` and ``origin_url`` columns
  and ``cat_links`` carries ``url``/``final_url``. No SELECT list in this module
  names any of them, and every rendered body — JSON or HTML — is scanned by
  :func:`_provenance_offenders` before it may leave. A leak fails *closed*: the
  screen answers a fixed 500 string rather than partially rendering. Titles and
  labels are additionally run through ``redact.scrub_text`` at build time.

  One narrow, deliberate exception: the loopback-only HTML fleet card prints the
  18 *configured* crawler names from :data:`FLEET_SITES` so an operator can tell
  their own engines apart. Those names are configuration, not scraped provenance,
  and the page is never mounted on the public port (``viewer.py`` 404s ``/admin``
  there). The JSON screen ``/admin/api/fleet`` stays opaque (stable
  ``crawler-NN`` handles only) and every other needle — hosters, mirrors,
  upstream URLs — still fails the whole page closed. No scraped URL is ever
  rendered anywhere in this module.

WRITES, and only five: ``POST /admin/api/links/{link_id}/evidence`` re-folds
that link's existing ``cat_link_evidence`` journal onto its row via
``catalog_v2.apply_evidence`` with its existing signature;
``POST /admin/action/save-monetization`` persists the operator's own payment, ad
and shortener settings to ``app_remote_config``;
``POST /admin/action/run-scraper`` queues one bounded crawler/sitemap run for a
validated crawler handle, records it in ``admin_fleet_audit`` and spawns it as a
background child process; and ``POST /admin/action/approve-payment`` /
``/admin/action/reject-payment`` close ONE ``payment_transactions`` row (see
``payments.py``) behind a CSRF token minted by this process. The last four
consume a request body, and none of them reads a socket: the mount parses the
body (JSON, or the form-encoding this page's own ``<form>`` posts) and hands the
dict in as ``body`` (see :func:`takes_body`). Everything else is read-only; see
the comment on :func:`route_post`.

THE PAYMENT QUEUE (``/admin/payments``, ``docs/FULL_MASTER_FEATURE_INVENTORY.md``
§M-MON-01), and the one place a transaction id is ever printed:
  A claimed JazzCash / EasyPaisa / Raast payment lives in the accounts ledger
  (``user_state.db``), not the catalog, so this surface opens that file too and
  the two writes go through ``payments.approve_payment`` / ``reject_payment``,
  which credit ``vip_until`` and close the row in one IMMEDIATE transaction.
  A TID is a payment artifact: it appears on this loopback screen — whose entire
  job is comparing it against the operator's own SMS — in NO account-surface
  response, and in no log line this module writes. The account is named here by
  ``payments.account_hint``, a truncated second-generation digest of the stored
  key hash: enough to match a payer's screenshot to a row, not enough to
  enumerate, reverse, or print a hash.
Standard Library only, like the rest of the backend.
"""

from __future__ import annotations

import hashlib
import html
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import accounts
import catalog_v2
import config
import payments
import redact

ADMIN_PREFIX = "/admin"
API_PREFIX = "/admin/api"

#: The peer addresses this surface will answer. Anything else is refused before a
#: single byte of SQL runs. Loopback is the whole access model (see the docstring).
_LOOPBACK = frozenset({"127.0.0.1", "::1"})

CONTENT_JSON = "application/json; charset=utf-8"
CONTENT_HTML = "text/html; charset=utf-8"
CONTENT_PROBLEM = "application/problem+json; charset=utf-8"
CONTENT_TEXT = "text/plain; charset=utf-8"

#: Honest empty state for a ledger with no projection yet, and the fixed string a
#: provenance leak collapses to. Neither may itself contain a needle.
NOT_BUILT = "the projection has not been built yet"
LEAK_MESSAGE = "admin response refused: provenance leak detected"
GENERIC_ERROR = "admin screen failed"

#: The `cat_*` tables a projection can hold. A missing one is simply not counted;
#: a missing `cat_works` means there is no projection at all.
_CAT_TABLES = (
    "cat_works", "cat_seasons", "cat_episodes", "cat_releases", "cat_links",
    "cat_review_queue", "cat_entitlements", "cat_link_evidence", "cat_offsets",
    "cat_projection_meta",
)
#: Layer-0 ledger tables, counted only to show how far the catalog has moved since
#: the last projection (never displayed per site, which would be provenance).
_LEDGER_TABLES = ("posts", "releases", "download_sources")

# ── scraper fleet ────────────────────────────────────────────────────────────
#
#: The 18 configured crawlers, one dedicated staging importer each. Ordered and
#: fixed on purpose: the ``crawler-NN`` handle an operator sees is
#: ``index + 1`` in this tuple, so it is stable between requests and restarts.
#: A handle never changes meaning, which is what makes it safe to queue a run
#: against it and safe to write it into the audit journal.
FLEET_SITES = (
    "10xflix", "7starhd", "9xmovies", "bolly4u", "desicinemas", "filmyzilla",
    "hdhub4u", "hdtvb", "hindilinks4u", "katmoviehd", "moviezguru",
    "multimovies", "rareanimes", "rogmovies", "ssrmovies", "toonworld4all",
    "vegamovies", "world4ufree",
)
_CRAWLER_SITES = {f"crawler-{index:02d}": site
                  for index, site in enumerate(FLEET_SITES, 1)}

FLEET_PATH = "/admin/api/fleet"
RUN_SCRAPER_PATH = "/admin/action/run-scraper"

#: Sites whose sitemap sync is implemented by the main engine's ``sync`` command.
#: Every other crawler has its own staging importer with a dedicated flag.
_ENGINE_SYNC_SITES = frozenset({
    "vegamovies", "rogmovies", "ssrmovies", "7starhd", "katmoviehd",
    "multimovies", "10xflix", "hdhub4u", "filmyzilla",
})
_SCRIPT_SYNC_FLAGS = {
    "9xmovies": "--sync-api",
    "bolly4u": "--sync-api",
    "desicinemas": "--sync-sitemaps",
    "hdtvb": "--sync-sitemap",
    "hindilinks4u": "--sync-sitemap",
    "moviezguru": "--sync-api",
    "rareanimes": "--sync-api",
    "toonworld4all": "--sync-api",
    "world4ufree": "--sync-api",
}

#: The crawler run is bounded on purpose: an operator pressing a button must not
#: turn into an unbounded scrape of a 600k-row staging database.
DEFAULT_CRAWL_LIMIT = 25
MAX_CRAWL_LIMIT = 1000
FLEET_MODES = ("sync", "crawl")

_AUDIT_TABLE = "admin_fleet_audit"
_AUDIT_LIMIT = 20
#: Serialises the "is this crawler already running?" check with the insert that
#: reserves it. SQLite would serialise the writes anyway; this makes the decision
#: and the reservation one step for two POSTs arriving together.
_FLEET_LOCK = threading.Lock()
#: One audit row per queued job. `pid` is kept so a restarted panel can still tell
#: a running child from an orphaned row without trusting the stored status.
_AUDIT_DDL = (
    f"CREATE TABLE IF NOT EXISTS {_AUDIT_TABLE} ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "crawler_id TEXT NOT NULL, "
    "action TEXT NOT NULL, "
    "status TEXT NOT NULL, "
    "started_at INTEGER NOT NULL, "
    "finished_at INTEGER, "
    "pid INTEGER, "
    "exit_code INTEGER, "
    "detail TEXT NOT NULL DEFAULT '')"
)

#: The only keys a scraper action accepts. Anything else is refused before a
#: command line is built, so there is no path from the request body to argv.
_ACTION_KEYS = frozenset({"crawler", "mode", "limit"})

#: §16.4 subset — the only codes this module answers, with the status/title pair
#: api_v2 uses. Kept local so this module mounts without importing the v2 stack.
_PROBLEM = {
    "invalid_params": (400, "Invalid request parameters"),
    "unauthorised": (401, "Authentication required"),
    "forbidden": (403, "This action is not allowed"),
    "not_found": (404, "The requested resource does not exist"),
    "internal": (500, "Internal error"),
    "unavailable": (503, "The catalog is not ready"),
}

DEFAULT_N = 20
MAX_N = 200


# ── request session (same shape as api_v2.session, kept local & socket-free) ──

@contextmanager
def _session(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── parameter helpers (mirror api_v2._q / _int_or_none) ───────────────────────

def _q(query, name, default=""):
    values = query.get(name) if query else None
    if not values:
        return default
    return str(values[0]).strip()


def _int_or_none(value):
    text = str(value if value is not None else "").strip()
    if not text or not text.lstrip("-").isdigit():
        return None
    return int(text)


def _limit(query, default=DEFAULT_N):
    n = _int_or_none(_q(query, "n") or _q(query, "limit"))
    if n is None:
        n = default
    return max(1, min(MAX_N, n))


# ── provenance: the fail-closed vocabulary scan every body passes through ─────

def _provenance_offenders(text, allow=frozenset()):
    """Every ``redact`` needle or forbidden key found anywhere in ``text``.

    This is the module-level assertion helper every screen runs its rendered body
    through before it may be emitted. ``redact.needles()`` is the broad detection
    vocabulary (site slugs + hoster brands, brand-shaped tokens); ``redact.
    PROVENANCE`` is checked as JSON-key form (``"source_site"``) so a structural
    leak cannot hide under the allowlist we wrote by hand. Empty list == clean.

    ``allow`` is reserved for the fleet card's own configured crawler names (see
    the module docstring). It only removes those exact tokens from the needle
    scan; every hoster/mirror needle and every provenance key still applies.
    """
    low = str(text or "").lower()
    allowed = {str(token).lower() for token in allow}
    hits = []
    for needle in redact.needles():
        token = str(needle).lower()
        if token in allowed:
            continue
        if len(token) >= 4 and token in low:
            hits.append(token)
    for key in redact.PROVENANCE:
        if f'"{str(key).lower()}"' in low:
            hits.append(str(key))
    return sorted(set(hits))


def _fleet_needle_allow():
    """Needles that are *part of a configured crawler's own name*.

    ``redact`` carries both ``katmoviehd`` (the site) and ``katmovie`` (its mirror
    family); printing the configured name ``katmoviehd`` necessarily contains the
    latter. The page may therefore allow every needle that occurs inside a
    :data:`FLEET_SITES` entry — and nothing else. Computing it from the live
    needle set means a dynamically learned variant is covered too, while a hoster
    or mirror token that is not part of a crawler name still fails closed.
    """
    haystack = " ".join(FLEET_SITES).lower()
    return frozenset(str(needle).lower() for needle in redact.needles()
                     if str(needle).lower() in haystack)


def _respond_json(status, payload, content_type=CONTENT_JSON):
    """Serialise, prove provenance-clean, and only then emit. A leak → fixed 500."""
    body = json.dumps(payload, ensure_ascii=False, default=str,
                      sort_keys=False).encode("utf-8")
    offenders = _provenance_offenders(body.decode("utf-8", "replace"))
    if offenders:
        # Fail closed: never partially render. Say only that we refused.
        return (500, CONTENT_TEXT, LEAK_MESSAGE.encode("utf-8"))
    return (status, content_type, body)


def _respond_html(html_text, allow=frozenset()):
    offenders = _provenance_offenders(html_text, allow=allow)
    if offenders:
        return (500, CONTENT_TEXT, LEAK_MESSAGE.encode("utf-8"))
    return (200, CONTENT_HTML, html_text.encode("utf-8"))


def _problem(code, instance, detail="", *, stable=False):
    """A §16.4-shaped problem body. ``stable=True`` omits the per-call
    ``request_id`` so the gate's refusals are byte-for-byte identical (a missing
    token and a wrong token must be indistinguishable, with nothing random to tell
    them apart). A routed data response keeps its request id."""
    status, title = _PROBLEM.get(code, _PROBLEM["not_found"])
    body = {
        "type": f"/admin/problems/{code}",
        "title": title,
        "status": status,
        "instance": instance,
        "code": code,
    }
    if not stable:
        body["request_id"] = "adm_" + uuid.uuid4().hex[:16]
    if detail:
        body["detail"] = redact.scrub_text(detail)
    # A refusal is a problem document, not data: `application/problem+json`, so a
    # client that only understands the §16.4 vocabulary can tell the two apart
    # without parsing the body.
    return _respond_json(status, body, content_type=CONTENT_PROBLEM)


# ── the gate ─────────────────────────────────────────────────────────────────

def _bearer(token_header):
    text = str(token_header or "").strip()
    if text.lower().startswith("bearer "):
        text = text[len("bearer "):].strip()
    return text


def _gate(peer_address, token_header):
    """Return a refusal tuple, or ``None`` when the request may proceed.

    Order is fixed and runs before any SQL: loopback first, then the bearer token.
    A missing token and a wrong token yield the *identical* 401 body, so a caller
    learns nothing about whether one is merely absent. If no token is configured
    the gate denies everything — fail closed, never "empty token means open".
    """
    if str(peer_address or "").strip() not in _LOOPBACK:
        return _problem("forbidden", ADMIN_PREFIX,
                        "This surface answers on loopback only.", stable=True)
    expected = os.environ.get("RADD_ADMIN_TOKEN", "")
    provided = _bearer(token_header)
    if not expected or not hmac.compare_digest(
            provided.encode("utf-8"), expected.encode("utf-8")):
        return _problem("unauthorised", ADMIN_PREFIX,
                        "A valid operator bearer token is required.", stable=True)
    return None


# ── small read helpers ───────────────────────────────────────────────────────

def _count(conn, table):
    """Row count for one table, or ``None`` when the table does not exist. Never
    raises: an absent table is an honest zero, not an error."""
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return None


def _has_projection(conn):
    return _count(conn, "cat_works") is not None


def _clean_text(value, fallback=""):
    text = redact.scrub_text(str(value if value is not None else ""))
    return text if text else fallback


def _unavailable():
    return {"available": False, "detail": NOT_BUILT}


# ── screens: each returns a JSON-safe dict, catches sqlite3.Error → empty ─────

def screen_projection(conn):
    """The four §16.2 rev keys, projected_at, a per-table census, and how far the
    ledger has moved since the projection."""
    if not _has_projection(conn):
        return _unavailable()
    try:
        versions = catalog_v2.projection_versions(conn)
        out = {
            "available": True,
            "revisions": {key: int(versions.get(key, 0))
                          for key in catalog_v2.REVISION_KEYS},
            "schema_version": catalog_v2.SCHEMA_VERSION,
            "table_counts": {t: _count(conn, t) for t in _CAT_TABLES},
            "ledger": {t: _count(conn, t) for t in _LEDGER_TABLES},
        }
        row = conn.execute(
            "SELECT value FROM cat_projection_meta WHERE key = 'projected_at'"
        ).fetchone()
        out["projected_at"] = row[0] if row else None
        # Drift: what the ledger holds now that the projection does not yet show.
        drift = {}
        for ledger_table, cat_table in (("posts", "cat_works"),
                                       ("releases", "cat_releases"),
                                       ("download_sources", "cat_links")):
            moved = _count(conn, ledger_table)
            shown = out["table_counts"].get(cat_table)
            if moved is not None and shown is not None:
                drift[cat_table] = moved - shown
        out["ledger_ahead_by"] = drift
        return out
    except sqlite3.Error:
        return _unavailable()


def screen_link_health(conn, n):
    """Counts by state, the N links with the oldest evidence, and dead links per
    quality band. SELECT lists never touch url/final_url/source_site."""
    if not _has_projection(conn):
        return _unavailable()
    try:
        by_state = {row["state"]: row["n"] for row in conn.execute(
            "SELECT COALESCE(state, 'unknown') AS state, COUNT(*) AS n"
            " FROM cat_links GROUP BY COALESCE(state, 'unknown')")}
        oldest = []
        for row in conn.execute(
            "SELECT id, work_id, state, playability, latency_ms, speed_mbps,"
            " last_evidence_at FROM cat_links"
            " ORDER BY last_evidence_at ASC, id ASC LIMIT :lim", {"lim": n}):
            oldest.append({
                "link_id": row["id"], "work_id": row["work_id"],
                "state": row["state"], "playability": row["playability"],
                "latency_ms": row["latency_ms"],
                "speed_mbps": row["speed_mbps"],
                "last_evidence_at": row["last_evidence_at"],
            })
        dead_by_band = {row["band"]: row["n"] for row in conn.execute(
            "SELECT COALESCE(r.resolution, 'unknown') AS band, COUNT(*) AS n"
            " FROM cat_links l JOIN cat_releases r ON r.id = l.release_id"
            " WHERE l.state = 'dead' GROUP BY COALESCE(r.resolution, 'unknown')")}
        return {
            "available": True,
            "by_state": by_state,
            "oldest_evidence": oldest,
            "dead_by_band": dead_by_band,
        }
    except sqlite3.Error:
        return _unavailable()


def screen_review_queue(conn, n):
    """Open cat_review_queue rows grouped by kind. Work title + release label only
    — never page_url, never detail (both carry scraped provenance).

    READ-ONLY BY NECESSITY: clearing an item means setting ``resolved_at``, but
    ``catalog_v2`` exposes no resolve/dequeue setter, and this module adds none.
    So the operator sees the queue here and acts on it through ``catalog_v2``
    directly (or a rebuild); there is deliberately no ``POST .../review/...``."""
    if not _has_projection(conn):
        return _unavailable()
    try:
        groups = {row["kind"]: row["n"] for row in conn.execute(
            "SELECT COALESCE(kind, 'unknown') AS kind, COUNT(*) AS n"
            " FROM cat_review_queue WHERE resolved_at IS NULL"
            " GROUP BY COALESCE(kind, 'unknown')")}
        items = []
        for row in conn.execute(
            """
            SELECT q.id, q.kind, q.raised_at, w.title AS title,
                   r.quality_label AS quality_label, r.label AS label
            FROM cat_review_queue q
            LEFT JOIN cat_works w ON w.id = q.work_id
            LEFT JOIN cat_releases r ON r.id = q.release_id
            WHERE q.resolved_at IS NULL
            ORDER BY q.raised_at DESC LIMIT :lim
            """, {"lim": n}):
            items.append({
                "queue_id": row["id"],
                "kind": _clean_text(row["kind"], "unknown"),
                "raised_at": row["raised_at"],
                "title": _clean_text(row["title"], "—"),
                "label": _clean_text(row["quality_label"] or row["label"], "—"),
            })
        return {"available": True, "total_open": sum(groups.values()),
                "by_kind": groups, "items": items}
    except sqlite3.Error:
        return _unavailable()


def screen_adult_proof(conn):
    """The operator's evidence that display filtering holds — and proof here is a
    *carry-through* question, not a row count.

    Adult titles are stored on purpose: the projection carries `is_18_plus` onto
    `cat_works` (catalog_v2 writes it) and suppression happens at the HTTP edge
    (`redact.adult_clause`). So counting flagged rows inside `cat_*` proves
    nothing — a non-zero count is the correct state, and a screen that called it a
    failure would sit red forever while everything worked.

    The one thing that can genuinely fail is the flag going missing on the way in:
    a work built from a post that the ledger flagged, projected as unflagged,
    would be served to everyone. That is what this screen hunts, and it reports the
    row count hanging off such works, because a lost flag is a leak with a size.
    """
    if not _has_projection(conn):
        return _unavailable()
    try:
        ledger_flagged = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0]
    except sqlite3.Error:
        ledger_flagged = None
    # A work is "unflagged but adult" when any post folded into it is flagged in
    # the ledger while the projected work row says otherwise.
    lost = ("SELECT DISTINCT s.work_id FROM cat_work_sites s JOIN posts p"
            " ON p.id = s.post_id JOIN cat_works w ON w.id = s.work_id"
            " WHERE p.is_18_plus = 1 AND COALESCE(w.is_18_plus, 0) = 0")
    surfaces = (
        ("releases", "cat_releases", "work_id"),
        ("links", "cat_links", "work_id"),
        ("episodes", "cat_episodes", "work_id"),
    )
    try:
        lost_ids = [row[0] for row in conn.execute(lost)]
        projected_flagged = conn.execute(
            "SELECT COUNT(*) FROM cat_works WHERE is_18_plus = 1").fetchone()[0]
        exposed = {}
        for name, table, column in surfaces:
            if not lost_ids:
                exposed[name] = 0
                continue
            marks = ",".join("?" * len(lost_ids))
            exposed[name] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({marks})",
                lost_ids).fetchone()[0]
    except sqlite3.Error:
        return _unavailable()
    leaked_works = len(lost_ids)
    return {
        "available": True,
        "ledger_flagged_posts": int(ledger_flagged) if ledger_flagged is not None else None,
        "projected_flagged_works": int(projected_flagged),
        "works_that_lost_their_flag": leaked_works,
        "exposed_rows_if_leaked": exposed,
        "suppression_holds": leaked_works == 0,
        "note": ("flagged works are projected on purpose — suppression is the"
                 " edge's deny clause, so this proves only that no adult work lost"
                 " its flag on the way in"),
    }


def screen_catalog_shape(conn, n):
    """Totals per work_type, per band, top-N works by episode count, and the
    identity_suspect counts. Titles scrubbed; no source columns selected."""
    if not _has_projection(conn):
        return _unavailable()
    try:
        by_work_type = {row["work_type"]: row["n"] for row in conn.execute(
            "SELECT COALESCE(work_type, 'unknown') AS work_type, COUNT(*) AS n"
            " FROM cat_works GROUP BY COALESCE(work_type, 'unknown')")}
        by_band = {row["band"]: row["n"] for row in conn.execute(
            "SELECT COALESCE(resolution, 'unknown') AS band, COUNT(*) AS n"
            " FROM cat_releases GROUP BY COALESCE(resolution, 'unknown')")}
        top_works = []
        for row in conn.execute(
            "SELECT id, title, work_type, episode_count FROM cat_works"
            " ORDER BY episode_count DESC, id ASC LIMIT :lim", {"lim": n}):
            top_works.append({
                "work_id": row["id"],
                "title": _clean_text(row["title"], "—"),
                "work_type": _clean_text(row["work_type"], "unknown"),
                "episode_count": int(row["episode_count"] or 0),
            })
        works_suspect = conn.execute(
            "SELECT COUNT(*) FROM cat_works WHERE identity_suspect = 1").fetchone()[0]
        releases_suspect = conn.execute(
            "SELECT COUNT(*) FROM cat_releases WHERE identity_suspect = 1").fetchone()[0]
        return {
            "available": True,
            "by_work_type": by_work_type,
            "by_band": by_band,
            "top_works_by_episodes": top_works,
            "identity_suspect": {"works": int(works_suspect),
                                 "releases": int(releases_suspect)},
        }
    except sqlite3.Error:
        return _unavailable()


# ── scraper fleet: status, audit journal, and the one spawn path ─────────────
#
# The fleet screen never opens a staging database: a 600k-row staging DB on the
# same 1-CPU box would make the operator page slow to load for a number the
# per-crawler status file already carries. It reads those files, the audit
# journal, and the process table — all cheap, all local.

def _status_dir():
    """Where the ``<site>_status.json`` progress files live. A helper so tests can
    point it at a temp directory instead of the deployment's own history."""
    return Path(config.BASE_DIR)


def _epoch(value):
    """An epoch int from a status file's number, numeric string or ISO stamp."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if text.lstrip("-").isdigit():
        return int(text)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _status_snapshot(site):
    """The numeric progress a crawler last wrote, or ``None`` when it never ran.

    Only counters and a timestamp are copied out of the file. The file itself
    carries a ``site`` field and free text; neither is needed here, and neither
    may reach a body."""
    path = _status_dir() / f"{site}_status.json"
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        mtime = int(path.stat().st_mtime)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    def pick(*names):
        for name in names:
            value = data.get(name)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                return int(value.strip())
        return None

    done = pick("completed", "completed_roots")
    pending = pick("pending", "total_pending")
    total = pick("total", "total_roots")
    if total is None and done is not None and pending is not None:
        total = done + pending
    percent = pick("percent")
    if percent is None and total:
        percent = int(round(100.0 * (done or 0) / total))
    last_at = None
    for name in ("timestamp", "updated_at", "start_time"):
        last_at = _epoch(data.get(name))
        if last_at is not None:
            break
    return {
        "done": done,
        "pending": pending,
        "total": total,
        "failed": pick("failed"),
        "releases": pick("releases", "total_releases"),
        "sources": pick("sources", "total_sources"),
        "percent": percent,
        "last_sync_at": last_at if last_at is not None else mtime,
    }


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _running_sites():
    """Sites with a live crawler process, read off ``/proc`` on Linux.

    This is what makes the panel honest about a run started from cron or a shell,
    not only one queued here. A platform without ``/proc`` simply reports idle;
    the audit journal still covers every run this panel itself launched."""
    running = set()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return running
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                parts = [piece.decode("utf-8", "replace")
                         for piece in handle.read().split(b"\0") if piece]
        except OSError:
            continue
        if not parts:
            continue
        joined = " ".join(parts)
        for site in FLEET_SITES:
            if f"import_{site}.py" in joined:
                running.add(site)
            elif (any(piece.endswith("fast_fetch.py") for piece in parts)
                  and "sync" in parts and "--site" in parts and site in parts):
                running.add(site)
    return running


def _ensure_audit(conn):
    conn.execute(_AUDIT_DDL)


def _audit_start(conn, crawler_id, action, started_at):
    cursor = conn.execute(
        f"INSERT INTO {_AUDIT_TABLE}(crawler_id, action, status, started_at)"
        " VALUES(?, ?, 'running', ?)", (crawler_id, action, int(started_at)))
    return int(cursor.lastrowid)


def _write_audit(db_path, statement, params):
    """Best-effort background write: the watchdog must not raise into a dead
    thread because the catalog was busy for a moment."""
    try:
        with _session(db_path) as conn:
            conn.execute(statement, params)
    except sqlite3.Error:
        pass


def _watch_job(db_path, audit_id, process):
    try:
        code = process.wait()
    except Exception:                       # noqa: BLE001 — never kill the thread
        code = -1
    _write_audit(
        db_path,
        f"UPDATE {_AUDIT_TABLE} SET status = ?, finished_at = ?, exit_code = ?"
        " WHERE id = ?",
        ("ok" if code == 0 else "failed", int(time.time()), int(code), int(audit_id)))


def _audit_effective_status(status, pid):
    if status != "running":
        return status
    if pid is None:
        return "starting"
    return "running" if _pid_alive(pid) else "orphaned"


def screen_fleet(conn, n):
    """The 18 crawlers, their last recorded progress, and the recent audit tail.

    Deliberately *opaque*: handles are ``crawler-NN`` from :data:`FLEET_SITES`
    order, and nothing here prints a site name, a host or a scraped URL. The
    loopback HTML card merges the configured names in at render time; this JSON
    body stays clean, which is the invariant the rest of the module enforces."""
    try:
        _ensure_audit(conn)
        rows = list(conn.execute(
            f"SELECT id, crawler_id, action, status, started_at, finished_at,"
            f" pid, exit_code, detail FROM {_AUDIT_TABLE}"
            " ORDER BY id DESC LIMIT :lim", {"lim": int(n)}))
    except sqlite3.Error:
        rows = []
    running = _running_sites()
    for row in rows:
        if row["status"] == "running" and row["pid"] is not None \
                and _pid_alive(row["pid"]):
            site = _CRAWLER_SITES.get(str(row["crawler_id"]))
            if site:
                running.add(site)

    crawlers, active = [], 0
    for crawler_id, site in _CRAWLER_SITES.items():
        snapshot = _status_snapshot(site)
        state = "active" if site in running else "idle"
        active += state == "active"
        crawlers.append({
            "crawler_id": crawler_id,
            "state": state,
            "last_sync_at": (snapshot or {}).get("last_sync_at"),
            "done": (snapshot or {}).get("done"),
            "pending": (snapshot or {}).get("pending"),
            "total": (snapshot or {}).get("total"),
            "failed": (snapshot or {}).get("failed"),
            "releases": (snapshot or {}).get("releases"),
            "sources": (snapshot or {}).get("sources"),
            "percent": (snapshot or {}).get("percent"),
        })

    audit = [{
        "audit_id": int(row["id"]),
        "crawler_id": _clean_text(row["crawler_id"], "unknown"),
        "action": _clean_text(row["action"], "unknown"),
        "status": _audit_effective_status(row["status"], row["pid"]),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "exit_code": row["exit_code"],
        "detail": _clean_text(row["detail"], ""),
    } for row in rows]

    return {
        "available": True,
        "total": len(FLEET_SITES),
        "active": int(active),
        "modes": list(FLEET_MODES),
        "default_limit": DEFAULT_CRAWL_LIMIT,
        "max_limit": MAX_CRAWL_LIMIT,
        "crawlers": crawlers,
        "recent_audit": audit,
    }


def _fleet_command(site, mode, limit):
    """The argv for one validated run. Every piece is a literal or an integer;
    the site must be in :data:`FLEET_SITES`, so a request body can never add an
    argument, a path or a shell word."""
    if site not in FLEET_SITES:
        raise ValueError("unknown crawler")
    if mode not in FLEET_MODES:
        raise ValueError("unknown mode")
    engine = Path(config.BASE_DIR) / "fast_fetch.py"
    script = Path(config.BASE_DIR) / f"import_{site}.py"
    if mode == "sync":
        if site in _ENGINE_SYNC_SITES:
            return [sys.executable, str(engine), "sync", "--site", site]
        return [sys.executable, str(script), _SCRIPT_SYNC_FLAGS[site]]
    limit = int(limit)
    if site == "multimovies":
        return [sys.executable, str(script), "--limit-roots", str(limit)]
    return [sys.executable, str(script), "--limit", str(limit)]


def _spawn_fleet_run(site, mode, limit, crawler_id, audit_id, db_path):
    """Start one crawler in its own session and keep its audit row truthful.

    Returns the child pid. Stdout/stderr go to a per-handle log under
    ``config.LOG_DIR``; that log is never served by this module."""
    command = _fleet_command(site, mode, limit)
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"fleet-{crawler_id}.log"
    with log_path.open("ab") as sink:
        process = subprocess.Popen(
            command, cwd=str(config.BASE_DIR), stdin=subprocess.DEVNULL,
            stdout=sink, stderr=subprocess.STDOUT, start_new_session=True)
    _write_audit(
        db_path,
        f"UPDATE {_AUDIT_TABLE} SET pid = ? WHERE id = ?",
        (int(process.pid), int(audit_id)))
    threading.Thread(target=_watch_job,
                     args=(db_path, int(audit_id), process), daemon=True).start()
    return int(process.pid)


# ── monetization: the operator's own settings, not scraped data ──────────────

#: One row, `id = 1`, in the catalog database this panel already reads. The
#: single-row shape is `docs/MASTER_ADMIN_MONETIZATION_SPEC.md` §2: this is a
#: settings record, not a collection, so there is no key to guess and nothing for
#: a caller to enumerate.
MONETIZATION_TABLE = "app_remote_config"
MONETIZATION_ID = 1
SAVE_MONETIZATION_PATH = "/admin/action/save-monetization"
SETTINGS_UNAVAILABLE = "the settings row is unavailable"

_TEXT = "text"
_PHONE = "phone"
_MONEY = "pkr"
_TOKEN = "token"
_FLAG = "flag"
#: Not `"url"`: every admin body is scanned for provenance *keys*, and `"url"`
#: is one of them. The kind is display metadata, so it takes a neutral spelling.
_URL = "address"

#: (key, label, kind, default). A key is the column name *and* the POST-body key
#: *and* the admin-card field id, so a setting has exactly one spelling here.
#:
#: The two tokens are the operator's credentials for a third-party payout
#: account. They are stored, they are shown masked on this page, and they are
#: never serialised anywhere else — see :func:`remote_config`.
#:
#: The last five are the app's remote controls: a maintenance switch, the
#: address of the APK-update banner, and the three feature flags the owner asked
#: for. They are deliberately in the same single row as pricing so a client has
#: one endpoint and one atomic update, not two settings stores that can disagree.
MONETIZATION_FIELDS = (
    ("pak_till_id", "JazzCash Merchant Till ID", _TEXT, ""),
    ("pak_jazzcash_number", "JazzCash Mobile Account", _PHONE, ""),
    ("pak_easypaisa_number", "EasyPaisa Mobile Number", _PHONE, ""),
    ("pak_raast_id", "Raast Instant ID", _PHONE, ""),
    ("vip_monthly_pkr", "VIP Monthly PKR", _MONEY, 200),
    ("vip_yearly_pkr", "VIP Yearly PKR", _MONEY, 1500),
    ("monetag_zone_id", "Monetag Rewarded Video zone ID", _TEXT, ""),
    ("adsterra_tag_id", "Adsterra Native banner ID", _TEXT, ""),
    ("shrinkme_api_token", "ShrinkMe API token", _TOKEN, ""),
    ("droplink_api_token", "Droplink API token", _TOKEN, ""),
    ("maintenance_mode", "Maintenance Mode", _FLAG, 0),
    ("apk_update_url", "APK Update URL banner", _URL, ""),
    ("feature_downloads", "Background Downloads", _FLAG, 1),
    ("feature_pure_cinema", "Pure Cinema Mode", _FLAG, 1),
    ("feature_chromecast", "Chromecast", _FLAG, 1),
)
_FIELD_BY_KEY = {row[0]: row for row in MONETIZATION_FIELDS}

#: Cap the free-text fields short. A 64-character till id is a mistake or an
#: attempt to park a payload in a display column, and both are refused.
_MAX_TEXT = 64
_MAX_HANDLE = 32
_MAX_TOKEN = 200
_MAX_URL = 500
_MAX_PKR = 10_000_000

#: A payment *handle*, as the guide writes one: `0300-1234567`, `+92 300 1234567`,
#: `(0300)1234567`, `0300XXXXXXX`, `@raddstream`. A digits-only validator would
#: silently reject the operator's real number, and these strings are printed next
#: to a Copy button rather than parsed, so the shape is theirs — control
#: characters and URLs are refused above regardless of kind.
_HANDLE_RE = re.compile(r"[0-9A-Za-z+()\-. @:_]+")


def _column_ddl(key, kind, default):
    """One column definition, built only from our own literals (see
    :func:`_monetization_ddl`). Used by both CREATE and the migration ALTER so a
    fresh row and an upgraded one cannot drift apart."""
    if kind == _MONEY:
        return f"{key} INTEGER NOT NULL DEFAULT {int(default)}"
    if kind == _FLAG:
        return f"{key} INTEGER NOT NULL DEFAULT {1 if default else 0}"
    return f"{key} TEXT NOT NULL DEFAULT ''"


def _monetization_ddl():
    """The CREATE for the settings row, built from the field spec so the spec and
    the schema cannot drift apart. Every interpolated piece is our own literal:
    column names come from `MONETIZATION_FIELDS`, defaults through `int()`."""
    columns = [_column_ddl(key, kind, default)
               for key, _label, kind, default in MONETIZATION_FIELDS]
    return (f"CREATE TABLE IF NOT EXISTS {MONETIZATION_TABLE} ("
            f"id INTEGER PRIMARY KEY CHECK (id = {MONETIZATION_ID}), "
            + ", ".join(columns)
            + ", updated_at INTEGER NOT NULL DEFAULT 0)")


def _ensure_monetization(conn):
    """Make the table and its single row exist, and add any columns a deployment
    predates. Run on the read path as well as the write path: an operator who has
    never saved anything should see a card showing the defaults, which is the
    truth, not an empty state.

    `CREATE TABLE IF NOT EXISTS` will not add a column to a table that already
    exists, so the remote controls would silently be absent in a database created
    before this session. The per-column `ALTER TABLE ... ADD COLUMN` keeps the
    upgrade in place; every name and default still comes from the field spec."""
    conn.execute(_monetization_ddl())
    existing = {row[1] for row in conn.execute(
        f"PRAGMA table_info({MONETIZATION_TABLE})")}
    for key, _label, kind, default in MONETIZATION_FIELDS:
        if key not in existing:
            conn.execute(f"ALTER TABLE {MONETIZATION_TABLE}"
                         f" ADD COLUMN {_column_ddl(key, kind, default)}")
    conn.execute(f"INSERT OR IGNORE INTO {MONETIZATION_TABLE}(id) VALUES(?)",
                 (MONETIZATION_ID,))


def _read_monetization(conn):
    columns = ", ".join(row[0] for row in MONETIZATION_FIELDS)
    row = conn.execute(
        f"SELECT id, updated_at, {columns} FROM {MONETIZATION_TABLE}"
        f" WHERE id = {MONETIZATION_ID}").fetchone()
    if row is None:
        return None
    values = {key: row[key] for key, _l, _k, default in MONETIZATION_FIELDS
              if row[key] is not None}
    for key, _label, _kind, default in MONETIZATION_FIELDS:
        values.setdefault(key, default)
    values["updated_at"] = int(row["updated_at"] or 0)
    return values


def _mask_token(value):
    """A secret, as this page is allowed to show it: enough tail to tell two
    accounts apart, never enough to use. An unset secret shows as unset."""
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * 8
    return "*" * 8 + text[-4:]


def _as_flag(value):
    """`1`, `0` or `None`. Accepts the JSON booleans the app sends and the
    `"on"`/`"off"` strings a plain HTML form posts, and nothing else — `2` is a
    mistake, not a truthy value to round up."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value if value in (0, 1) else None
    text = str(value if value is not None else "").strip().lower()
    if text in ("1", "true", "on", "yes"):
        return 1
    if text in ("0", "false", "off", "no", ""):
        return 0
    return None


def _monetization_view(values):
    """The admin card's fields from raw stored values, secrets masked."""
    fields = []
    for key, label, kind, default in MONETIZATION_FIELDS:
        raw = values.get(key, default)
        secret = kind == _TOKEN
        if secret:
            value = _mask_token(raw)
            configured = bool(str(raw or "").strip())
        elif kind == _FLAG:
            # A flag always has a value; `0` must render as "off", not as an
            # empty string (``str(0 or "")`` is the trap this branch avoids).
            value = "on" if _as_flag(raw) else "off"
            configured = True
        else:
            value = str(raw if raw is not None else "")
            configured = bool(value.strip())
        fields.append({
            "key": key,
            "label": label,
            "kind": kind,
            "secret": secret,
            "default": default,
            "configured": configured,
            "value": value,
        })
    return fields


def screen_monetization(conn):
    """The Monetization & Operator Settings card, as data.

    Nothing here is read from the `cat_*` projection — these are the operator's
    own settings, so the card answers with defaults on a ledger that has no
    projection at all. The fail-closed provenance scan still runs over the body
    like every other screen, which is why a value that names a scraped site or
    hoster cannot be saved and echoed back."""
    try:
        _ensure_monetization(conn)
        values = _read_monetization(conn)
    except sqlite3.Error:
        return {"available": False, "detail": SETTINGS_UNAVAILABLE}
    if values is None:
        return {"available": False, "detail": SETTINGS_UNAVAILABLE}
    return {
        "available": True,
        "updated_at": values["updated_at"],
        "currency": "PKR",
        "fields": _monetization_view(values),
        "secrets_masked": True,
        "save_path": SAVE_MONETIZATION_PATH,
        "note": ("tokens are stored and shown masked; the public"
                 " /api/v1/app/remote-config publishes the payment handles, ad"
                 " unit ids and pricing, never the tokens"),
    }


def _validated(key, value):
    """`(clean_value, None)` or `(None, label)`.

    A refusal names the field and never the content: an error body that echoed
    what it rejected would put the operator's own pasted text back into a
    response log, and there is nothing in this form worth leaking that way."""
    _key, label, kind, _default = _FIELD_BY_KEY[key]
    if kind == _FLAG:
        flag = _as_flag(value)
        if flag is None:
            return None, label
        return flag, None

    if kind == _MONEY:
        if isinstance(value, bool):
            # True *is* 1 to Python; a price is not a flag.
            return None, label
        text = str(value).strip() if not isinstance(value, str) else value.strip()
        number = _int_or_none(text)
        if number is None or number < 0 or number > _MAX_PKR:
            return None, label
        return number, None

    if kind == _URL:
        # The update banner is the one field that is an address on purpose. It
        # still has to be an absolute http(s) address: `javascript:`/`file:` in a
        # field the app renders as a link is how a settings row becomes an
        # injection, and a relative path would point at whatever host opened it.
        if not isinstance(value, str):
            return None, label
        text = value.strip()
        if not text:
            return "", None
        if len(text) > _MAX_URL:
            return None, label
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
            return None, label
        if any(ch.isspace() for ch in text):
            return None, label
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return None, label
        if "@" in parsed.netloc:
            # Credentials in a URL would be published to every phone that reads
            # the config; refuse the paste instead of leaking it.
            return None, label
        if redact.scrub_text(text) != text:
            return None, label
        return text, None

    if isinstance(value, int):
        value = str(value)          # a numeric till id from a form is still a till id
    if not isinstance(value, str):
        return None, label
    text = value.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return None, label
    if "://" in text or text.lower().startswith(("http:", "ftp:", "mailto:")):
        # These fields hold identifiers, not addresses. A URL here is either a
        # paste mistake or an attempt to publish somebody else's host from a
        # settings row, and this panel does not print URLs at all.
        return None, label
    if kind == _PHONE:
        if text and not _HANDLE_RE.fullmatch(text):
            return None, label
        if len(text) > _MAX_HANDLE:
            return None, label
    elif kind == _TOKEN:
        if len(text) > _MAX_TOKEN:
            return None, label
    elif len(text) > _MAX_TEXT:
        return None, label
    if text and redact.scrub_text(text) != text:
        # The public edge runs `scrub_text` on what it publishes. A value it
        # would rewrite is a value an app must not show: a payment handle with a
        # piece missing is a lost payment, and a stored string that cannot
        # survive its own display is a paste mistake worth naming now rather than
        # a 500 on the card later.
        return None, label
    return text, None


def _save_monetization(conn, payload):
    """Validate the whole body, then write it in one transaction.

    All-or-nothing on purpose: a half-applied pricing block (monthly saved,
    yearly rejected) would bill a subscriber off a config the operator never
    approved. Nothing is executed before every field is acceptable, so the
    `_session` commit at the end of the route is the only durable moment. An
    empty body is refused rather than treated as "clear everything"."""
    if not isinstance(payload, dict) or not payload:
        return None, ["at least one setting"]
    rejected, unknown, clean = [], [], {}
    for key in payload:
        if key not in _FIELD_BY_KEY:
            unknown.append(str(key))
    for key, _label, _kind, _default in MONETIZATION_FIELDS:
        if key not in payload:
            continue                # a partial save edits only what was sent
        value, error = _validated(key, payload[key])
        if error:
            rejected.append(error)
        else:
            clean[key] = value
    if unknown or rejected:
        return None, rejected + [f"unknown setting: {name}" for name in unknown]
    try:
        _ensure_monetization(conn)
        assignments = ", ".join(f"{key} = :{key}" for key in clean)
        params = dict(clean)
        params["id"] = MONETIZATION_ID
        params["updated_at"] = int(time.time())
        conn.execute(
            f"UPDATE {MONETIZATION_TABLE} SET {assignments},"
            f" updated_at = :updated_at WHERE id = :id", params)
        values = _read_monetization(conn)
    except sqlite3.Error:
        return None, [SETTINGS_UNAVAILABLE]
    if values is None:
        return None, [SETTINGS_UNAVAILABLE]
    return {"available": True, "saved": sorted(clean),
            "updated_at": values["updated_at"],
            "fields": _monetization_view(values)}, None


def remote_config(conn):
    """The app-facing projection: what a phone needs to take a payment and to
    hang a sponsor card, and nothing that is a credential.

    A shortener API token in this body would be readable by anyone who can reach
    the endpoint — and this host is plain HTTP (§ ORACLE_DEPLOYMENT.md), so that
    is anyone on the path, not only the caller. Whoever holds it can shorten on
    the operator's account, spend their quota and poison their standing with the
    network, which is exactly how shorteners ban affiliates. So the public answer
    says `configured: true|false` — enough for a client to choose the direct or
    the shortened path — and the call itself belongs on the server side, where
    the token stays in the row. Payment handles and ad unit ids *are* display
    content (the app prints them next to a Copy button), so they publish.
    """
    try:
        _ensure_monetization(conn)
        values = _read_monetization(conn)
    except sqlite3.Error:
        values = None
    if values is None:
        values = {key: default for key, _l, _k, default in MONETIZATION_FIELDS}
        values["updated_at"] = 0

    def shown(key):
        # Display text at the edge, same rule as every other public string.
        return redact.scrub_text(str(values.get(key, "") or ""))

    def flag(key):
        # A boolean to a phone, never the stored 0/1: a client comparing
        # `featureFlags.downloads === true` must not depend on SQLite's truthiness.
        return bool(_as_flag(values.get(key, 0)))

    return {
        "success": True,
        "currency": "PKR",
        "updated_at": int(values.get("updated_at") or 0),
        "maintenance_mode": flag("maintenance_mode"),
        "apk_update_url": shown("apk_update_url"),
        "feature_flags": {
            "downloads": flag("feature_downloads"),
            "pure_cinema": flag("feature_pure_cinema"),
            "chromecast": flag("feature_chromecast"),
        },
        "vip": {
            "monthly_pkr": int(values.get("vip_monthly_pkr") or 0),
            "yearly_pkr": int(values.get("vip_yearly_pkr") or 0),
        },
        "payments": {
            "jazzcash": {"till_id": shown("pak_till_id"),
                         "mobile_account": shown("pak_jazzcash_number")},
            "easypaisa": {"mobile_number": shown("pak_easypaisa_number")},
            "raast": {"instant_id": shown("pak_raast_id")},
        },
        "ads": {
            "monetag_rewarded_zone_id": shown("monetag_zone_id"),
            "adsterra_native_banner_id": shown("adsterra_tag_id"),
        },
        "link_shorteners": [
            {"network": "shrinkme",
             "configured": bool(str(values.get("shrinkme_api_token") or "").strip())},
            {"network": "droplink",
             "configured": bool(str(values.get("droplink_api_token") or "").strip())},
        ],
    }


#: The networks the download route can shorten through, in rotation order, and
#: the settings column that holds each one's API token. The token is a payout
#: credential: it leaves this module only as a `(network, token)` tuple handed to
#: the server-side shortener call, never as a serialised body (see
#: :func:`remote_config`).
SHORTENER_TOKEN_FIELDS = (
    ("shrinkme", "shrinkme_api_token"),
    ("droplink", "droplink_api_token"),
)


def shortener_targets(conn):
    """Configured `(network, token)` pairs, rotation order, server side only.

    Empty when the operator has saved no token or the settings row is
    unavailable — which is the same answer to the caller as "shorteners are
    off": the download route falls back to the direct URL. Read-only and
    idempotent, like :func:`remote_config`."""
    try:
        _ensure_monetization(conn)
        values = _read_monetization(conn)
    except sqlite3.Error:
        return []
    if values is None:
        return []
    targets = []
    for network, key in SHORTENER_TOKEN_FIELDS:
        token = str(values.get(key) or "").strip()
        if token:
            targets.append((network, token))
    return targets


def _run_scraper_action(path, body, db_path):
    """Queue one bounded crawler/sitemap run. Returns the route tuple.

    The body may only carry a crawler handle, a mode and an integer limit. The
    handle maps onto :data:`FLEET_SITES`; the mode onto a fixed argv shape; the
    limit is clamped to ``1..MAX_CRAWL_LIMIT``. Nothing from the request is ever
    interpolated into a command string or echoed back, so a wrong handle is a
    plain 400 and never a probe for which sites exist."""
    unknown = sorted(str(key) for key in body if key not in _ACTION_KEYS)
    if unknown:
        return _problem("invalid_params", path, "Unknown action setting.")
    crawler = str(body.get("crawler", "")).strip().lower()
    site = _CRAWLER_SITES.get(crawler)
    if site is None:
        return _problem("invalid_params", path, "Unknown crawler handle.")
    mode = str(body.get("mode", "sync")).strip().lower()
    if mode not in FLEET_MODES:
        return _problem("invalid_params", path, "Mode must be sync or crawl.")
    raw_limit = body.get("limit", DEFAULT_CRAWL_LIMIT)
    if isinstance(raw_limit, bool):
        return _problem("invalid_params", path,
                        f"Limit must be an integer between 1 and {MAX_CRAWL_LIMIT}.")
    limit = _int_or_none(raw_limit)
    if limit is None or not 1 <= limit <= MAX_CRAWL_LIMIT:
        return _problem("invalid_params", path,
                        f"Limit must be an integer between 1 and {MAX_CRAWL_LIMIT}.")

    try:
        with _FLEET_LOCK, _session(db_path) as conn:
            _ensure_audit(conn)
            busy = site in _running_sites()
            if not busy:
                for row in conn.execute(
                        f"SELECT crawler_id, pid FROM {_AUDIT_TABLE}"
                        " WHERE status = 'running'"):
                    if (_CRAWLER_SITES.get(str(row["crawler_id"])) == site
                            and (row["pid"] is None or _pid_alive(row["pid"]))):
                        busy = True
                        break
            if busy:
                return _problem("invalid_params", path,
                                "That crawler already has a run in progress.")
            started = int(time.time())
            audit_id = _audit_start(conn, crawler, mode, started)
    except sqlite3.Error:
        return _problem("unavailable", path, "The audit journal is unavailable.")

    try:
        pid = _spawn_fleet_run(site, mode, limit, crawler, audit_id, db_path)
    except (OSError, ValueError, KeyError):
        # The exception text could carry a local path; the operator gets a fixed
        # sentence and the audit row says only that the spawn failed.
        _write_audit(
            db_path,
            f"UPDATE {_AUDIT_TABLE} SET status = 'failed', finished_at = ?,"
            " detail = 'spawn failed' WHERE id = ?", (started, audit_id))
        return _problem("internal", path, "The crawler could not be started.")
    return _respond_json(202, {
        "ok": True,
        "accepted": True,
        "job": {
            "crawler_id": crawler,
            "action": mode,
            "audit_id": audit_id,
            "pid": pid,
            "started_at": started,
        },
    })


# ── the payment queue: pending claims, one click to close them ───────────────
#
# `docs/FULL_MASTER_FEATURE_INVENTORY.md` §M-MON-01. A user has posted a
# transaction id; nothing on this server can verify it against a bank, so a human
# with the operator's phone is the verifier and this page is what they click.
# The ledger itself lives in `payments.py` / `user_state.db`; everything here is
# the operator's view of it plus the two writes that close a row.

PAYMENTS_PATH = "/admin/payments"
APPROVE_PAYMENT_PATH = "/admin/action/approve-payment"
REJECT_PAYMENT_PATH = "/admin/action/reject-payment"
#: action segment (from the path) → the status `payments.py` writes.
_PAYMENT_ACTIONS = {
    APPROVE_PAYMENT_PATH.rsplit("/", 1)[-1]: payments.STATUS_APPROVED,
    REJECT_PAYMENT_PATH.rsplit("/", 1)[-1]: payments.STATUS_REJECTED,
}
#: The only keys a review POST may carry. `note` is the operator's reason, shown
#: back to the payer as a boolean-free string on this page only; `reviewer` is a
#: free-text label for the audit row. An unknown key is refused the same way the
#: scraper action refuses one: no path from a request body to anything executed.
_PAYMENT_BODY_KEYS = frozenset({"payment_id", "csrf", "note", "reviewer", "_form"})
#: Tells this module the POST came from the page's own `<form>` (so it answers
#: with the refreshed page) rather than from a JSON client (which gets the JSON
#: receipt). The parsed keys are identical either way.
_FORM_FLAG = "_form"

_PENDING_LIMIT = 100
_RECENT_LIMIT = 20

LEDGER_UNAVAILABLE = "the payment ledger is unavailable"

#: A CSRF token proves the POST came from a page THIS process rendered — the one
#: thing a cross-origin form cannot do, since it cannot read the response. The
#: secret is per-process and never stored, printed or shipped: a restart
#: invalidates a page left open in a tab, and the operator reloads. That is the
#: right trade against putting a forgeable long-lived token in a file.
_CSRF_SECRET = secrets.token_bytes(32)
_CSRF_CHARS = 32
_MAX_NOTE = 200


def _csrf_token(action: str, payment_id) -> str:
    """One token bound to (action, payment id) — not to a session, because this
    panel has no session and no cookie, and a token good for exactly one button on
    exactly one row is less to leak and less to replay."""
    digest = hmac.new(_CSRF_SECRET, f"{action}:{payment_id}".encode("utf-8"),
                      hashlib.sha256).hexdigest()
    return digest[:_CSRF_CHARS]


def _csrf_ok(action: str, payment_id, token) -> bool:
    """Constant-time, length-clamped, and identical for a missing and a wrong
    token: nothing here tells a prober whether a row exists yet."""
    return hmac.compare_digest(_csrf_token(action, payment_id),
                               str(token or "")[:_CSRF_CHARS])


@contextmanager
def _ledger(state_db_path=None):
    """A connection to the accounts ledger, schema included.

    The queue lives in `user_state.db` — the same file as `user_accounts.vip_until`
    — because a credit that wrote to a different file than the ledger row it
    approves would not be one transaction, and the whole guarantee of the approve
    path is that it is. `accounts.connect` runs the same idempotent
    `ensure_schema()` the account edge runs, so a deployment whose state file
    predates this release gains the two tables on its first operator read instead
    of answering 500 until somebody notices."""
    conn = accounts.connect(Path(state_db_path) if state_db_path
                            else accounts.default_db_path())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _payment_rows(conn, limit: int = _PENDING_LIMIT) -> dict:
    """The queue and its recent history, as data. Raw `tid` included, because the
    operator is the only reader this surface has (`viewer.py` 404s `/admin` on the
    public port, `_gate` demands loopback plus the bearer token) and a TID they
    cannot see is a TID they cannot check."""
    pending = payments.list_payments(conn, status=payments.STATUS_PENDING, limit=limit)
    recent = payments.list_payments(conn, status=None, limit=_RECENT_LIMIT)
    for row in pending:
        row["audit"] = payments.audit_for(conn, row["payment_id"], limit=3)
    return {
        "available": True,
        "currency": "PKR",
        "plans": [{"plan": name, "amount_pkr": payments.default_price(name),
                   "days": payments.plan_days(name)}
                  for name in payments.plan_names()],
        "pending_count": len(pending),
        "pending": pending,
        "recent": recent,
        "approve_path": APPROVE_PAYMENT_PATH,
        "reject_path": REJECT_PAYMENT_PATH,
        "note": ("a transaction id is a claim until a human who has read the"
                 " payment SMS closes it; nothing here verifies one"),
    }


def screen_payments(state_db_path=None, *, limit: int = _PENDING_LIMIT) -> dict:
    """`GET /admin/api/payments` — the queue as JSON. Fails to an honest empty
    state rather than a crash, like every other screen."""
    try:
        with _ledger(state_db_path) as conn:
            return _payment_rows(conn, limit=limit)
    except sqlite3.Error:
        return {"available": False, "detail": LEDGER_UNAVAILABLE}


def _review_payment(action, path, body, state_db_path):
    """Close one ledger row. Returns `(result, None)` or `(None, refusal_tuple)`.

    Order is fixed: shape, then the CSRF token, then the write. A row that does
    not exist and a row whose token does not match take the same 403 — a
    mismatched token is refused without the ledger being opened at all, so this
    route cannot be used to ask "does payment 17 exist?"."""
    if not isinstance(body, dict):
        return None, refuse_bad_body(path)
    unknown = sorted(str(key) for key in body if key not in _PAYMENT_BODY_KEYS)
    if unknown:
        return None, _problem("invalid_params", path, "Unknown review setting.")
    payment_id = _int_or_none(body.get("payment_id"))
    if payment_id is None or payment_id < 1:
        return None, _problem("invalid_params", path,
                              "Payment id must be a positive integer.")
    if not _csrf_ok(action, payment_id, body.get("csrf")):
        return None, _problem("forbidden", path,
                              "That review token does not match this payment.")
    note = str(body.get("note", "") or "")[:_MAX_NOTE]
    reviewer = str(body.get("reviewer", "") or "")[:40]
    try:
        with _ledger(state_db_path) as conn:
            if action == payments.STATUS_APPROVED:
                result = payments.approve_payment(conn, payment_id,
                                                  reviewer=reviewer, note=note)
            else:
                result = payments.reject_payment(conn, payment_id,
                                                 reviewer=reviewer, note=note)
    except accounts.AccountError as error:
        return None, _problem(getattr(error, "code", "invalid_params")
                              if getattr(error, "code", "") in _PROBLEM
                              else "not_found", path, getattr(error, "detail", ""))
    except sqlite3.Error:
        return None, _problem("unavailable", path, LEDGER_UNAVAILABLE)
    return result, None


def _review_banner(result: dict) -> str:
    """The one sentence the page may say about a review. It names no payer, no
    key and no TID, and it says plainly when the click credited nobody."""
    if result["changed"]:
        if result["status"] == payments.STATUS_APPROVED:
            return (f"payment {result['payment_id']} approved — "
                    f"{result['days']} days credited, no double credit on replay")
        return f"payment {result['payment_id']} rejected — vip_until was not touched"
    return (f"payment {result['payment_id']} was already "
            f"{result['status']} — nothing was written and no second credit was made")


def _payment_forms(action_path, row, token) -> str:
    """The two buttons, as real HTML forms.

    Each carries the CSRF token for its own (action, payment) pair, the admin
    bearer token the gate already demanded (a `<form>` cannot set an
    `Authorization` header, so the page's own token travels in the action URL —
    this is the loopback panel of an operator who typed that token themselves),
    and for a reject a short note the operator can type."""
    identifier = row["payment_id"]
    shared = (f'<input type="hidden" name="payment_id" value="{_e(identifier)}">'
              f'<input type="hidden" name="{_FORM_FLAG}" value="1">'
              f'<input type="hidden" name="reviewer" value="panel">')
    approve = (
        f'<form method="post" class="inline" action="'
        f'{_e(action_path)}?token={_e(token)}">'
        f'{shared}'
        f'<input type="hidden" name="csrf" value="{_e(_csrf_token(payments.STATUS_APPROVED, identifier))}">'
        '<button class="btn" type="submit">Approve</button></form>')
    reject = (
        f'<form method="post" class="inline" action="'
        f'{_e(REJECT_PAYMENT_PATH)}?token={_e(token)}">'
        f'{shared}'
        f'<input type="hidden" name="csrf" value="{_e(_csrf_token(payments.STATUS_REJECTED, identifier))}">'
        '<input class="limit" type="text" name="note" maxlength="80"'
        ' placeholder="why"> <button class="btn" type="submit">Reject</button>'
        '</form>')
    return approve + " " + reject


def render_payments_page(data, query, banner=""):
    """The payment queue page. Loopback only, like the rest of `/admin`."""
    token = _q(query, "token")
    parts = [
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>payments — admin</title>",
        f"<style>{_STYLE}</style>",
        "<style>form.inline { display: inline; }</style></head><body>",
        '<div class="wrap">',
        "<h1>Payment queue</h1>",
        '<p class="sub"><a href="/admin">operator panel</a> · pending claims'
        ' against the PKR price list. Loopback only, no TLS.</p>',
        '<div class="warn"><strong>Nothing here verifies a payment.</strong> A'
        ' transaction id is what the payer typed. Check your own payment SMS for'
        ' the amount and the reference before you approve, and approve only then.'
        ' A TID is printed on this page and nowhere else on the account surface.'
        '</div>',
    ]
    if banner:
        parts.append(f'<p id="ops-status" class="ok statusline">{_e(banner)}</p>')
    else:
        parts.append('<p id="ops-status" class="statusline"></p>')
    if not data.get("available"):
        parts.append('<section class="card"><div class="empty">'
                     + _e(LEDGER_UNAVAILABLE) + '</div></section>')
        parts.append("</div></body></html>")
        return "".join(parts)

    prices = ", ".join(f"{row['plan']} = PKR {row['amount_pkr']} for"
                       f" {row['days']} days" for row in data.get("plans") or [])
    parts.append(f'<p class="hint">Server price list (the client cannot set an'
                 f' amount): {_e(prices)}</p>')

    def table(rows, *, actions):
        cells = []
        for row in rows or []:
            submitted = _ts(row.get("submitted_at"))
            trail = "; ".join(
                f"{entry['action']} by {entry['reviewer']}"
                for entry in row.get("audit") or [])
            line = [_e(row.get("hint")) or '<span class="empty">—</span>',
                    _e(row.get("method")), _e(row.get("tid")),
                    _e(row.get("amount_pkr")), _e(row.get("plan")), submitted]
            if actions:
                line.append(_payment_forms(APPROVE_PAYMENT_PATH, row, token))
            else:
                line.append(_e(row.get("status"))
                            + (" — " + _e(row.get("reviewer_note"))
                               if row.get("reviewer_note") else "")
                            + ("; " + _e(trail) if trail else ""))
            cells.append(line)
        return cells

    parts.append('<section class="card"><h2>Pending</h2>')
    parts.append(_table(("account", "method", "TID", "PKR", "plan", "submitted",
                         "actions"),
                        table(data.get("pending"), actions=True)))
    parts.append(f'<p class="hint">{_e(data.get("pending_count"))} open claim(s).'
                 ' The account column is a one-way fingerprint of the sync key'
                 " the payer holds — it identifies the row to you and nothing to"
                 " anyone else.</p></section>")
    parts.append('<section class="card"><h2>Recently reviewed</h2>')
    parts.append(_table(("account", "method", "TID", "PKR", "plan", "submitted",
                         "outcome"),
                        table(data.get("recent"), actions=False)))
    parts.append("</section></div></body></html>")
    return "".join(parts)


# The screen registry: name → (callable, whether it takes `n`).
_SCREENS = {
    "projection": (lambda conn, q: screen_projection(conn), False),
    "link-health": (lambda conn, q: screen_link_health(conn, _limit(q)), True),
    "review": (lambda conn, q: screen_review_queue(conn, _limit(q)), True),
    "adult": (lambda conn, q: screen_adult_proof(conn), False),
    "catalog": (lambda conn, q: screen_catalog_shape(conn, _limit(q)), True),
    "fleet": (lambda conn, q: screen_fleet(conn, _limit(q)), True),
    "monetization": (lambda conn, q: screen_monetization(conn), False),
}


# ── the one dark HTML page ────────────────────────────────────────────────────

#: Written as a plain constant, never an f-string, so the CSS braces need no
#: escaping and cannot accidentally interpolate a needle into the stylesheet.
_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 20px 64px; background: #06090B; color: #E4EDEA;
       font: 15px/1.55 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       font-variant-numeric: tabular-nums; }
.wrap { max-width: 960px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 2px; }
h2 { font-size: 16px; margin: 0; color: #A5BDB8; font-weight: 600; }
.sub { color: #93AEA9; margin: 0 0 28px; }
.warn { border: 1px solid #FF6B70; background: #2a1113; color: #FFB4A8;
        padding: 12px 16px; border-radius: 8px; margin: 0 0 28px; font-size: 14px; }
.card { border: 1px solid #3A4B49; border-radius: 12px; padding: 18px 20px;
        margin: 0 0 20px; background: #0E1518; }
.card h2 { margin-bottom: 12px; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px;
     margin: 0; }
dt { color: #93AEA9; }
dd { margin: 0; }
table { border-collapse: collapse; width: 100%; margin-top: 6px; font-size: 14px; }
th, td { text-align: left; padding: 4px 10px 4px 0; border-bottom: 1px solid #1E282B; }
th { color: #93AEA9; font-weight: 600; }
code { background: #141D20; padding: 1px 6px; border-radius: 4px; font-size: 13px; }
.ok { color: #4FE3A3; }
.bad { color: #FF6B70; }
.empty { color: #93AEA9; font-style: italic; }
a { color: #2BC79A; }
.toggle { display: inline-flex; align-items: center; gap: 8px; margin: 6px 18px 6px 0; }
.toggle input { accent-color: #2BC79A; width: 16px; height: 16px; }
.field { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 7px 0; }
.field label { flex: 0 0 195px; color: #93AEA9; }
.field input { flex: 1 1 160px; background: #141D20; color: #E4EDEA;
               border: 1px solid #3A4B49; border-radius: 6px; padding: 6px 8px;
               font: inherit; }
.btn { background: #12362C; color: #4FE3A3; border: 1px solid #2BC79A;
       border-radius: 6px; padding: 5px 10px; font: inherit; cursor: pointer; }
.btn:hover { background: #17483A; }
.btn:disabled { opacity: .5; cursor: default; }
.limit { width: 74px; background: #141D20; color: #E4EDEA; border: 1px solid #3A4B49;
         border-radius: 6px; padding: 4px 6px; font: inherit; }
.statusline { min-height: 1.4em; margin: 10px 0 0; }
.hint { color: #93AEA9; font-size: 13px; margin: 6px 0 0; }
"""


def _e(value):
    return html.escape(str(value if value is not None else ""))


def _kv(pairs):
    out = ["<dl>"]
    for key, value in pairs:
        out.append(f"<dt>{_e(key)}</dt><dd>{value}</dd>")
    out.append("</dl>")
    return "".join(out)


def _table(headers, rows):
    if not rows:
        return '<div class="empty">nothing to show</div>'
    out = ["<table><thead><tr>"]
    out += [f"<th>{_e(h)}</th>" for h in headers]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _num(value):
    if value is None:
        return '<span class="empty">n/a</span>'
    return _e(value)


def _map_rows(mapping):
    return [[_e(key), _e(count)] for key, count in sorted(
        (mapping or {}).items(), key=lambda item: str(item[0]))]


def _ts(value):
    try:
        return _e(time.strftime("%Y-%m-%d %H:%M:%S UTC",
                               time.gmtime(float(value))))
    except (TypeError, ValueError):
        return _e(value if value is not None else "n/a")


#: The page's own controls. A plain constant (not an f-string) so the JS braces
#: stay inert; the two route paths are substituted at render time. The bearer
#: token is read from the page's own query string, never embedded in the HTML.
_SCRIPT = """
<script>
(function () {
  const TOKEN = new URLSearchParams(window.location.search).get("token") || "";
  const SAVE_PATH = "__SAVE_PATH__";
  const RUN_PATH = "__RUN_PATH__";
  function note(text, ok) {
    const el = document.getElementById("ops-status");
    if (!el) return;
    el.textContent = text;
    el.className = ok ? "ok statusline" : "bad statusline";
  }
  async function post(path, payload) {
    if (!TOKEN) {
      note("Open this page with ?token=... to use the controls.", false);
      return null;
    }
    let response;
    try {
      response = await fetch(path + "?token=" + encodeURIComponent(TOKEN), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
    } catch (error) {
      note("Request failed.", false);
      return null;
    }
    let data = null;
    try { data = await response.json(); } catch (error) { data = null; }
    if (!response.ok) {
      note((data && data.detail) || "Refused.", false);
      return null;
    }
    return data;
  }
  window.saveSetting = async function (key, value, button) {
    if (button) button.disabled = true;
    const data = await post(SAVE_PATH, {[key]: value});
    if (button) button.disabled = false;
    if (data) note("Saved " + key + " at " + new Date().toLocaleTimeString() + ".", true);
  };
  window.runScraper = async function (crawler, mode, button) {
    const input = document.getElementById("crawl-limit");
    const limit = input ? (parseInt(input.value, 10) || 25) : 25;
    if (button) button.disabled = true;
    const data = await post(RUN_PATH, {crawler: crawler, mode: mode, limit: limit});
    if (button) button.disabled = false;
    if (data) note("Queued " + crawler + " (" + mode + ", limit " + limit + ").", true);
  };
})();
</script>
"""


def _progress_cell(item):
    done, total = item.get("done"), item.get("total")
    if done is None and total is None:
        return '<span class="empty">no run recorded</span>'
    if total is None:
        return _e(done)
    percent = item.get("percent")
    suffix = f" ({int(percent)}%)" if percent is not None else ""
    return f"{_e(done if done is not None else 0)}/{_e(total)}{_e(suffix)}"


def _fleet_card(fleet):
    """The Scraper Management card. Names come from :data:`FLEET_SITES`, the
    configured fleet — the one page-level allowlist in this module."""
    if not fleet.get("available"):
        return '<div class="empty">fleet status unavailable</div>'
    rows = []
    for item in fleet.get("crawlers") or []:
        crawler_id = str(item.get("crawler_id") or "")
        name = _CRAWLER_SITES.get(crawler_id, "—")
        state = str(item.get("state") or "idle")
        badge = ('<span class="ok state">active</span>' if state == "active"
                 else '<span class="state">idle</span>')
        last = (_ts(item.get("last_sync_at"))
                if item.get("last_sync_at") else '<span class="empty">never</span>')
        actions = (
            f'<button class="btn" onclick="runScraper(\'{_e(crawler_id)}\','
            f' \'sync\', this)">Sync now</button> '
            f'<button class="btn" onclick="runScraper(\'{_e(crawler_id)}\','
            f' \'crawl\', this)">Crawl</button>')
        rows.append([f"<code>{_e(crawler_id)}</code>", _e(name), badge, last,
                     _progress_cell(item), _num(item.get("failed")), actions])
    limit = int(fleet.get("default_limit") or DEFAULT_CRAWL_LIMIT)
    maximum = int(fleet.get("max_limit") or MAX_CRAWL_LIMIT)
    out = ('<p class="hint">Bounded crawl limit '
           f'<input id="crawl-limit" class="limit" type="number" min="1"'
           f' max="{maximum}" value="{limit}"> titles per run. '
           'Sync reads the sitemap; Crawl pages stored titles.</p>')
    out += _table(("crawler", "engine", "state", "last sync", "progress",
                   "failed", "actions"), rows)
    audit = [[_num(row.get("audit_id")), _e(row.get("crawler_id")),
              _e(row.get("action")), _e(row.get("status")),
              _ts(row.get("started_at")), _ts(row.get("finished_at")),
              _num(row.get("exit_code"))]
             for row in fleet.get("recent_audit") or []]
    out += '<h2 style="margin-top:18px">Recent scraper audit</h2>'
    out += _table(("#", "crawler", "action", "status", "started", "finished",
                   "exit"), audit)
    return out


def _config_card(monetization):
    """The App Remote Config & Feature Matrix: live toggles for the app controls
    and 1-click updates for the Pakistani payment channels."""
    if not monetization.get("available"):
        return '<div class="empty">' + _e(SETTINGS_UNAVAILABLE) + '</div>'
    fields = {field["key"]: field for field in monetization.get("fields") or []}

    def toggle(key):
        field = fields.get(key) or {"label": key, "value": "off"}
        checked = " checked" if _as_flag(field.get("value")) else ""
        return (f'<label class="toggle"><input type="checkbox"'
                f' data-key="{_e(key)}"{checked}'
                f' onchange="saveSetting(this.dataset.key, this.checked, this)">'
                f' <span>{_e(field.get("label", key))}</span></label>')

    def text_row(key, label, placeholder=""):
        field = fields.get(key) or {"value": ""}
        return (f'<div class="field"><label for="f-{_e(key)}">{_e(label)}</label>'
                f'<input id="f-{_e(key)}" autocomplete="off"'
                f' placeholder="{_e(placeholder)}" value="{_e(field.get("value"))}"'
                f' onkeydown="if(event.key===\'Enter\')'
                f' document.getElementById(\'b-{_e(key)}\').click()">'
                f'<button id="b-{_e(key)}" class="btn"'
                f' onclick="saveSetting(\'{_e(key)}\','
                f' document.getElementById(\'f-{_e(key)}\').value, this)">'
                'Update</button></div>')

    out = '<h2 style="margin-top:0">Feature matrix</h2>'
    out += toggle("maintenance_mode")
    out += toggle("feature_pure_cinema")
    out += toggle("feature_chromecast")
    out += toggle("feature_downloads")
    out += text_row("apk_update_url", "APK update banner",
                    "https://downloads.example/app.apk")
    out += ('<h2 style="margin-top:18px">Pakistani payment channels</h2>'
            '<p class="hint">Updates publish immediately to'
            ' <code>/api/v1/app/remote-config</code>.</p>')
    out += text_row("pak_till_id", "JazzCash Merchant Till ID", "e.g. 123456")
    out += text_row("pak_jazzcash_number", "JazzCash Mobile Account", "0300-1234567")
    out += text_row("pak_easypaisa_number", "EasyPaisa Mobile Number", "0300-1234567")
    out += text_row("pak_raast_id", "Raast Instant ID", "03001234567")

    table = _table(("setting", "value", "stored"),
                   [[_e(field["label"]),
                     _e(field["value"]) if field["configured"]
                     else '<span class="empty">not set</span>',
                     '<span class="bad">secret — masked</span>' if field["secret"]
                     else _e(field["kind"])]
                    for field in monetization.get("fields") or []])
    out += ('<h2 style="margin-top:18px">All settings</h2>' + table)
    out += _kv([("updated_at", _ts(monetization.get("updated_at"))
                 if monetization.get("updated_at")
                 else '<span class="empty">never saved</span>')])
    return out


def render_admin_page(conn, q):
    brand = config.BRAND_APP_NAME or config.PROJECT_NAME
    projection = screen_projection(conn)
    link_health = screen_link_health(conn, _limit(q))
    review = screen_review_queue(conn, _limit(q))
    adult = screen_adult_proof(conn)
    shape = screen_catalog_shape(conn, _limit(q))
    monetization = screen_monetization(conn)
    fleet = screen_fleet(conn, _limit(q))

    parts = [
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{_e(brand)} — admin</title>",
        f"<style>{_STYLE}</style></head><body><div class=\"wrap\">",
        f"<h1>{_e(brand)}</h1>",
        '<p class="sub">Operator surface. Loopback only, no TLS — this is not'
        ' real web auth; see the module docstring before changing the gate.</p>',
        '<div class="warn"><strong>Fleet names stay here.</strong> This page is'
        ' mounted on the loopback port only and never prints a scraped upstream'
        ' URL. The scraper card names the 18 engines you configured; the public'
        ' port answers 404 for <code>/admin</code> and all of its routes.</div>',
        '<p class="sub"><a href="/admin/payments">Payment queue</a> — pending'
        ' JazzCash / EasyPaisa / Raast claims, approve or reject.</p>',
        '<p id="ops-status" class="statusline"></p>',
    ]

    def card(title, body_html):
        parts.append(f'<section class="card"><h2>{_e(title)}</h2>{body_html}'
                     '</section>')

    card("Scraper management", _fleet_card(fleet))
    card("App remote config & feature matrix", _config_card(monetization))

    if not projection.get("available"):
        card("Projection", '<div class="empty">' + _e(NOT_BUILT) + '</div>')
    else:
        rev_html = _kv([("schema_version", _num(projection.get("schema_version"))),
                        ("projected_at", _ts(projection.get("projected_at")))])
        rev_html += _table(("revision", "value"),
                           _map_rows(projection.get("revisions")))
        rev_html += _table(("cat_* table", "rows"),
                           _map_rows(projection.get("table_counts")))
        rev_html += _table(("ledger table", "rows"),
                           _map_rows(projection.get("ledger")))
        rev_html += _table(("table", "ledger ahead by"),
                           _map_rows(projection.get("ledger_ahead_by")))
        card("Projection status", rev_html)

    if not link_health.get("available"):
        card("Link health", '<div class="empty">' + _e(NOT_BUILT) + '</div>')
    else:
        lh = _table(("state", "links"), _map_rows(link_health.get("by_state")))
        lh += _table(("band", "dead links"), _map_rows(link_health.get("dead_by_band")))
        oldest = [[_num(row["link_id"]), _num(row["work_id"]), _e(row["state"]),
                   _e(row["playability"]), _num(row["last_evidence_at"])]
                  for row in link_health.get("oldest_evidence") or []]
        lh += _table(("link", "work", "state", "playability", "oldest evidence"),
                     oldest)
        card("Link health", lh)

    if not review.get("available"):
        card("Review queue", '<div class="empty">' + _e(NOT_BUILT) + '</div>')
    else:
        rv = _kv([("open items", _num(review.get("total_open")))])
        rv += _table(("kind", "open"), _map_rows(review.get("by_kind")))
        items = [[_num(row["queue_id"]), _e(row["kind"]), _e(row["title"]),
                  _e(row["label"]), _ts(row["raised_at"])]
                 for row in review.get("items") or []]
        rv += _table(("#", "kind", "work title", "release label", "raised"), items)
        card("Review queue", rv)

    if not adult.get("available"):
        card("Adult suppression proof", '<div class="empty">' + _e(NOT_BUILT) + '</div>')
    else:
        flag = ('<span class="ok">holds — zero flagged rows projected</span>'
                if adult.get("suppression_holds")
                else '<span class="bad">FAILED — flagged rows reached the'
                     ' projection</span>')
        ad = _kv([("flagged posts in ledger", _num(adult.get("ledger_flagged_posts"))),
                  ("flagged works projected", _num(adult.get("projected_flagged_works"))),
                  ("flagged releases projected", _num(adult.get("projected_flagged_releases"))),
                  ("flagged links projected", _num(adult.get("projected_flagged_links"))),
                  ("display filtering", flag)])
        ad += '<p class="sub">' + _e(adult.get("note", "")) + '</p>'
        card("Adult suppression proof", ad)

    if not shape.get("available"):
        card("Catalog shape", '<div class="empty">' + _e(NOT_BUILT) + '</div>')
    else:
        sh = _table(("work_type", "works"), _map_rows(shape.get("by_work_type")))
        sh += _table(("band", "prints"), _map_rows(shape.get("by_band")))
        sh += _table(("suspect scope", "count"),
                     _map_rows(shape.get("identity_suspect")))
        tops = [[_num(row["work_id"]), _e(row["title"]), _e(row["work_type"]),
                 _num(row["episode_count"])]
                for row in shape.get("top_works_by_episodes") or []]
        sh += _table(("work", "title", "type", "episodes"), tops)
        card("Catalog shape", sh)

    parts.append(_SCRIPT.replace("__SAVE_PATH__", _e(SAVE_MONETIZATION_PATH))
                 .replace("__RUN_PATH__", _e(RUN_SCRAPER_PATH)))
    parts.append("</div></body></html>")
    return "".join(parts)


# ── dispatch ─────────────────────────────────────────────────────────────────

def _is_admin(path):
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


def _segments(path):
    return [piece for piece in (path or "").split("/") if piece]


def route_get(path, query, *, db_path, peer_address, token_header,
              state_db_path=None):

    """Serve one admin GET. Returns ``(status, content_type, body_bytes)`` when
    answered, or ``None`` when ``path`` is not under ``/admin`` (the caller falls
    through, exactly as ``api_v2.route_get`` reports "not mine").

    ``state_db_path`` is the accounts ledger (``user_state.db``) the payment queue
    reads. It is a parameter and not a global because the mount owns both paths and
    a test owns its own temp files: the catalog and the ledger are two different
    SQLite files, and only ``/admin/payments`` and its JSON screen touch the second
    one."""
    if not _is_admin(path):
        return None
    effective_token = token_header or (query.get("token", [""])[0] if query else "")
    refusal = _gate(peer_address, effective_token)
    if refusal is not None:
        return refusal
    try:
        segments = _segments(path)   # ["admin"] or ["admin","api",<name>]
        if segments == ["admin", "payments"]:
            # Rendered from the ledger alone: a catalog with no projection still
            # has a payment queue, and a payment queue with no pending claim is
            # still a page.
            data = screen_payments(state_db_path, limit=_limit(query, _PENDING_LIMIT))
            return _respond_html(render_payments_page(data, query))
        if (len(segments) == 3 and segments[1] == "api"
                and segments[2] == "payments"):
            return _respond_json(200, screen_payments(
                state_db_path, limit=_limit(query, _PENDING_LIMIT)))
        with _session(db_path) as conn:
            if segments == ["admin"]:
                return _respond_html(render_admin_page(conn, query),
                                     allow=_fleet_needle_allow())
            if len(segments) == 3 and segments[1] == "api":
                name = segments[2]
                entry = _SCREENS.get(name)
                if entry is None:
                    return _problem("not_found", path, "No such admin screen.")
                data = entry[0](conn, query)
                if not data.get("available"):
                    # Honest empty state: 200 with the message, never a crash.
                    return _respond_json(200, data)
                return _respond_json(200, data)
            return _problem("not_found", path, "No such admin route.")
    except Exception:
        # Never raise out of the route.
        return _problem("internal", path, GENERIC_ERROR)


_BODY_ACTIONS = frozenset({
    SAVE_MONETIZATION_PATH.rsplit("/", 1)[-1],
    RUN_SCRAPER_PATH.rsplit("/", 1)[-1],
    APPROVE_PAYMENT_PATH.rsplit("/", 1)[-1],
    REJECT_PAYMENT_PATH.rsplit("/", 1)[-1],
})


def takes_body(path):
    """Whether this admin POST consumes a request body — so the mount knows when
    to read one and can leave every other POST's bytes alone. Only the settings
    save, the scraper action and the two payment reviews do: the evidence re-fold
    derives everything from the journal already in the database."""
    segments = _segments(path)
    return (len(segments) == 3 and segments[1] == "action"
            and segments[2] in _BODY_ACTIONS)


def form_encoded(content_type) -> bool:
    """Whether the mount should hand us a urlencoded form instead of JSON. The
    payment queue's Approve/Reject buttons are real ``<form>``s, so that a review
    works with JavaScript switched off; every other admin action stays JSON."""
    return str(content_type or "").split(";")[0].strip().lower() == \
        "application/x-www-form-urlencoded"


def parse_form_body(raw) -> dict:
    """A urlencoded body into the flat dict the action expects.

    Keys are kept as written and values are the first occurrence, so a body that
    repeats ``payment_id`` cannot make a route choose between two rows. Never
    raises: an unparseable body is an empty dict, and every action already refuses
    a body without its own keys."""
    try:
        text = bytes(raw).decode("utf-8", "replace")
    except (TypeError, ValueError):
        return {}
    pairs = urllib.parse.parse_qs(text, keep_blank_values=True)
    return {key: values[0] for key, values in pairs.items() if values}


def refuse_bad_body(path):
    """The mount's answer for a body that is not a JSON object, in this module's
    own problem vocabulary — the caller that owns the socket should not invent a
    second error shape for a route it does not implement."""
    return _problem("invalid_params", path, "The request body must be a JSON object.")


def route_post(path, query, *, db_path, peer_address, token_header, body=None,
               state_db_path=None):
    """Serve one admin POST. Same tuple/``None`` contract as :func:`route_get`.

    Five writes, no more. ``POST /admin/api/links/{id}/evidence`` takes no body:
    the mount owns the socket and the documented action ("fold this link's
    recorded evidence back onto its row") needs only the link id from the path —
    ``catalog_v2.apply_evidence(conn, link_ids=[...])`` re-derives everything from
    the existing ``cat_link_evidence`` journal. Four actions do take a body and
    receive it already parsed as ``body`` (see :func:`takes_body`), because
    reading a socket is the mount's job and not this module's:
    ``/admin/action/save-monetization`` writes the settings row,
    ``/admin/action/run-scraper`` queues one validated, bounded crawler child, and
    ``/admin/action/approve-payment`` / ``reject-payment`` close one claimed
    payment behind a CSRF token minted here (see :data:`_CSRF_SECRET`).
    No screen gains a setter that ``payments.py`` does not already expose."""
    if not _is_admin(path):
        return None
    effective_token = token_header or (query.get("token", [""])[0] if query else "")
    refusal = _gate(peer_address, effective_token)
    if refusal is not None:
        return refusal
    segments = _segments(path)
    try:
        if takes_body(path):
            if segments[2] in _PAYMENT_ACTIONS:
                result, denied = _review_payment(_PAYMENT_ACTIONS[segments[2]],
                                                 path, body, state_db_path)
                if denied is not None:
                    return denied
                if not (isinstance(body, dict) and str(body.get(_FORM_FLAG) or "")):
                    # A JSON client gets a receipt. No TID in it: the operator's
                    # own tool can re-read the queue for that, and a response that
                    # echoed one would be one more place a payment artifact could
                    # end up in a log.
                    return _respond_json(200, {"ok": True, "review": result})
                # The page's own form: answer with the refreshed queue and one
                # sentence about what the click did, so a double-click visibly
                # credits nobody the second time.
                data = screen_payments(state_db_path)
                return _respond_html(render_payments_page(
                    data, query, _review_banner(result)))
            if not isinstance(body, dict):
                return refuse_bad_body(path)
            if segments[2] == RUN_SCRAPER_PATH.rsplit("/", 1)[-1]:
                return _run_scraper_action(path, body, db_path)
            with _session(db_path) as conn:
                saved, rejected = _save_monetization(conn, body)
            if rejected:
                return _problem("invalid_params", path,
                                "Rejected: " + ", ".join(rejected))
            return _respond_json(200, saved)
        if not (len(segments) == 5 and segments[1] == "api" and segments[2] == "links"
                and segments[4] == "evidence"):
            return _problem("not_found", path, "No such admin action.")
        link_id = _int_or_none(segments[3])
        if link_id is None or link_id < 1:
            return _problem("invalid_params", path, "Link id must be a positive integer.")
        with _session(db_path) as conn:
            if not _has_projection(conn):
                return _problem("unavailable", path, NOT_BUILT)
            exists = conn.execute(
                "SELECT id FROM cat_links WHERE id = :id", {"id": int(link_id)}
            ).fetchone()
            if exists is None:
                return _problem("not_found", path, "No such link in the projection.")
            try:
                counters = catalog_v2.apply_evidence(conn, link_ids=[int(link_id)])
            except ValueError:
                # apply_evidence raises ValueError when the projection is absent.
                return _problem("unavailable", path, NOT_BUILT)
            safe = redact.scrub(counters if isinstance(counters, dict)
                                else {"applied": counters})
            safe["link_id"] = int(link_id)
            return _respond_json(200, {"ok": True, "evidence": safe})
    except sqlite3.Error:
        return _problem("unavailable", path, NOT_BUILT)
    except Exception:
        return _problem("internal", path, GENERIC_ERROR)
