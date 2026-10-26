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

ONE WRITE ACTION, and only one: ``POST /admin/api/links/{link_id}/evidence``
re-folds that link's existing ``cat_link_evidence`` journal onto its row via
``catalog_v2.apply_evidence`` with its existing signature. Everything else is
read-only; see the comment on :func:`route_post` for why the POST takes no body.

Standard Library only, like the rest of the backend.
"""

from __future__ import annotations

import html
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

import catalog_v2
import config
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

def _provenance_offenders(text):
    """Every ``redact`` needle or forbidden key found anywhere in ``text``.

    This is the module-level assertion helper every screen runs its rendered body
    through before it may be emitted. ``redact.needles()`` is the broad detection
    vocabulary (site slugs + hoster brands, brand-shaped tokens); ``redact.
    PROVENANCE`` is checked as JSON-key form (``"source_site"``) so a structural
    leak cannot hide under the allowlist we wrote by hand. Empty list == clean.
    """
    low = str(text or "").lower()
    hits = []
    for needle in redact.needles():
        token = str(needle).lower()
        if len(token) >= 4 and token in low:
            hits.append(token)
    for key in redact.PROVENANCE:
        if f'"{str(key).lower()}"' in low:
            hits.append(str(key))
    return sorted(set(hits))


def _respond_json(status, payload, content_type=CONTENT_JSON):
    """Serialise, prove provenance-clean, and only then emit. A leak → fixed 500."""
    body = json.dumps(payload, ensure_ascii=False, default=str,
                      sort_keys=False).encode("utf-8")
    offenders = _provenance_offenders(body.decode("utf-8", "replace"))
    if offenders:
        # Fail closed: never partially render. Say only that we refused.
        return (500, CONTENT_TEXT, LEAK_MESSAGE.encode("utf-8"))
    return (status, content_type, body)


def _respond_html(html_text):
    offenders = _provenance_offenders(html_text)
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
    lost = ("SELECT w.id FROM cat_works w WHERE COALESCE(w.is_18_plus, 0) = 0"
            " AND EXISTS (SELECT 1 FROM cat_work_sites s JOIN posts p"
            " ON p.id = s.post_id WHERE s.work_id = w.id AND p.is_18_plus = 1)")
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


# The screen registry: name → (callable, whether it takes `n`).
_SCREENS = {
    "projection": (lambda conn, q: screen_projection(conn), False),
    "link-health": (lambda conn, q: screen_link_health(conn, _limit(q)), True),
    "review": (lambda conn, q: screen_review_queue(conn, _limit(q)), True),
    "adult": (lambda conn, q: screen_adult_proof(conn), False),
    "catalog": (lambda conn, q: screen_catalog_shape(conn, _limit(q)), True),
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


def render_admin_page(conn, q):
    brand = config.BRAND_APP_NAME or config.PROJECT_NAME
    projection = screen_projection(conn)
    link_health = screen_link_health(conn, _limit(q))
    review = screen_review_queue(conn, _limit(q))
    adult = screen_adult_proof(conn)
    shape = screen_catalog_shape(conn, _limit(q))

    parts = [
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{_e(brand)} — admin</title>",
        f"<style>{_STYLE}</style></head><body><div class=\"wrap\">",
        f"<h1>{_e(brand)}</h1>",
        '<p class="sub">Operator surface. Loopback only, no TLS — this is not'
        ' real web auth; see the module docstring before changing the gate.</p>',
        '<div class="warn"><strong>Read-only.</strong> This page never names a'
        ' source site, hoster or upstream URL. Machine data lives under'
        ' <code>' + _e(API_PREFIX) + '/&#42;</code>.</div>',
    ]

    def card(title, body_html):
        parts.append(f'<section class="card"><h2>{_e(title)}</h2>{body_html}'
                     '</section>')

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

    parts.append("</div></body></html>")
    return "".join(parts)


# ── dispatch ─────────────────────────────────────────────────────────────────

def _is_admin(path):
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


def _segments(path):
    return [piece for piece in (path or "").split("/") if piece]


def route_get(path, query, *, db_path, peer_address, token_header):
    """Serve one admin GET. Returns ``(status, content_type, body_bytes)`` when
    answered, or ``None`` when ``path`` is not under ``/admin`` (the caller falls
    through, exactly as ``api_v2.route_get`` reports "not mine")."""
    if not _is_admin(path):
        return None
    refusal = _gate(peer_address, token_header)
    if refusal is not None:
        return refusal
    try:
        with _session(db_path) as conn:
            segments = _segments(path)   # ["admin"] or ["admin","api",<name>]
            if segments == ["admin"]:
                return _respond_html(render_admin_page(conn, query))
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


def route_post(path, query, *, db_path, peer_address, token_header):
    """Serve one admin POST. Same tuple/``None`` contract as :func:`route_get`.

    This is the ONLY write in the module. It takes no request body: the mount
    owns the socket and reading one, and the documented action ("fold this link's
    recorded evidence back onto its row") needs only the link id from the path —
    ``catalog_v2.apply_evidence(conn, link_ids=[...])`` re-derives everything from
    the existing ``cat_link_evidence`` journal. Any *new* measurement ingest would
    require a body channel that lives in the mount, so none is wired here; the
    rest of the surface stays read-only, and no screen gains a setter that
    ``catalog_v2`` does not already expose."""
    if not _is_admin(path):
        return None
    refusal = _gate(peer_address, token_header)
    if refusal is not None:
        return refusal
    segments = _segments(path)
    try:
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
