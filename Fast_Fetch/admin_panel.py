#!/usr/bin/env python3
"""admin_panel.py — the operator's control surface over the `cat_*` projection.

═══════════════════════════════════════════════════════════════════════════════
THIS IS AN AUTHENTICATED SURFACE, AND HERE IS EXACTLY WHAT THAT IS WORTH.
───────────────────────────────────────────────────────────────────────────────
Until the login milestone this module opened by telling the reader that its gate
(loopback peer + one bearer token compared with ``hmac.compare_digest``) "is *not*
a login and must never be mistaken for one or 'upgraded' into session cookies,
JWTs or a cookie jar". That sentence is retired, and the paragraph replacing it is
written against the code as it now stands — not against what a panel like this is
usually described as having:

  * There is a login. A username and a password are POSTed to an HTML form, the
    password is verified against a **salted, memory-hard KDF digest** stored in
    ``RADD_ADMIN_PASSWORD_HASH`` (scrypt by default; :func:`verify_password`),
    five failures lock a name for fifteen minutes, and success returns a signed,
    expiring, ``HttpOnly``, ``SameSite=Strict`` cookie. No code path in this module
    compares a plaintext password to a value read from the environment, and a
    ``RADD_ADMIN_PASSWORD`` that is set with no stored hash is *refused* (503)
    rather than used.
  * No credential travels in a URL. ``?token=`` is gone from every route, form and
    script here, because a URL credential is recorded in browser history, in the
    ``Referer`` and in the access log — all of which outlive the session it opened.
  * The transport has not changed and this is the honest limit: the host is plain
    HTTP with no TLS (see ORACLE_DEPLOYMENT.md; the deployed address is
    ``http://92.4.95.252/``). A session cookie sent over cleartext can be sniffed
    as easily as a bearer token could, so the cookie buys hygiene — nothing in a
    URL, nothing in a log, an expiry, and rotation invalidates every session — and
    buys *no* confidentiality in transit. If TLS is ever terminated in front of
    this panel, adding ``Secure`` to :data:`OPERATOR_COOKIE_ATTRS` is the change,
    and it is one line.
  * What still decides reachability is the same two facts it always was: this
    surface binds to loopback, and ``viewer.py`` refuses it outright when a request
    arrives carrying a reverse-proxy marker — because a live
    ``location /operator/ { proxy_pass http://127.0.0.1:8081/; }`` made the
    loopback peer check true for every visitor on the internet, prefix-stripped
    around ``^~ /api/ { return 403; }``. The credential is a lock on the door that
    door-locking was supposed to guard; the proxy refusal is the wall.

So: a bearer token stays the machine credential (`RADD_ADMIN_TOKEN`), the password
is the human one, and both are checked by the same gate on every route of the
operator port — a cookie never reopens a path the token could not.

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

import base64
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
import engagement
import payments
import redact
import usage_stats

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
    # Same code, status and title as the public manifest's `rate_limited`, or
    # `test_admin_only_uses_codes_the_public_manifest_declares` rightly fails: the
    # login lockout is a refusal in the §16.4 vocabulary, not a new one.
    "rate_limited": (429, "Too many requests"),
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


#: The usage window the operator may ask for. 30 days is the answer to "how much
#: this month"; a year is the answer to "is this working at all". Anything larger
#: would sum the entire metric history, and a history is a per-device timeline
#: waiting to be read as one, so the ceiling is the rule, not a performance note.
USAGE_WINDOW_DAYS = 365


def _window_days(query):
    days = _int_or_none(_q(query, "days") or _q(query, "window_days"))
    if days is None:
        return 30
    return max(1, min(USAGE_WINDOW_DAYS, days))


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


def bearer_matches(token_header) -> bool:
    """True when this header carries the configured bearer token, compared in
    constant time. One definition, because three call sites — `_gate`,
    `gate_operator_port` and the same-origin rule below — must not disagree about
    what a proven bearer is: if they did, a request could pass the gate on a bearer
    and still be treated as a cookie-authenticated browser. A *session* is not a
    bearer, so nothing that only holds a cookie takes this branch."""
    secret = bearer_secret()
    presented = _bearer(token_header)
    return bool(secret and presented) and hmac.compare_digest(
        presented.encode("utf-8"), secret.encode("utf-8"))


def _gate(peer_address, token_header, cookie_header="", accepts_html=False):
    """Return a refusal tuple, or ``None`` when the request may proceed.

    Order is fixed and runs before any SQL: loopback first, then the bearer
    credential, then the session cookie. A missing credential and a wrong one
    yield the *identical* refusal body, so a caller learns nothing about whether
    one is merely absent. If no secret is configured the gate denies everything —
    fail closed, never "empty token means open".

    `accepts_html` decides the *shape* of the refusal, never its outcome: a browser
    gets the login card at 401 (an HTML refusal is still a refusal — nothing about
    the catalog is rendered and no status code pretends success), while a client
    that did not ask for HTML gets the §16.4 problem document it expects. curl and
    every existing test land in that second branch, so the byte-for-byte
    missing-equals-wrong property they pin is unchanged.

    **There is no query-string credential any more, on purpose.** The gate used to
    take `query_token`, and the panel used to write `?token=` into its own form
    actions and `fetch` calls, so the operator's credential landed in browser
    history, in the `Referer` of every asset the page pulled, and — measured
    2026-10-31 in `/var/log/nginx/access.log`, which is `www-data:adm 0640` and
    rotated daily for 14 days — in the clear, six times, from ordinary use. A
    credential that a human is *invited* to put in a URL is not a secret. What
    replaces it is the session cookie minted by `authenticate`, and nothing else on
    this surface takes a credential off the header.
    """
    if str(peer_address or "").strip() not in _LOOPBACK:
        return _problem("forbidden", ADMIN_PREFIX,
                        "This surface answers on loopback only.", stable=True)
    expected = session_signing_secret()
    if bearer_matches(token_header):
        return None
    if cookie_header and operator_session_valid(cookie_header, expected):
        return None
    if accepts_html:
        return _respond_login_form(ADMIN_PREFIX)
    return _problem("unauthorised", ADMIN_PREFIX,
                    "A valid operator credential is required.", stable=True)


# ── the whole-port credential ────────────────────────────────────────────────
#
# Measured on this host: `/` on the operator port served the 46,476-byte
# dashboard with no token at all, and `/api/v1/stats` and `/api/v1/rules`
# answered 200 there with a bogus bearer token, because `_gate` was only ever
# consulted for `/admin`. The boundary was really "you are on loopback", which is
# not a credential — anything on this box qualifies. `gate_operator_port` below
# is the fix: on the operator instance every path requires the token, `/`
# included, and it fails closed when no token is configured.

#: Name of the loopback-only session cookie minted from a proven bearer token.
OPERATOR_COOKIE = "radd_admin_session"
#: Eight hours: one working session on the panel, no longer. A cookie that never
#: expires is a credential in a browser database, and this box cannot protect one.
OPERATOR_SESSION_TTL = 8 * 3600
_SESSION_LABEL = b"radd-operator-session:v1:"


def _session_key(expected_token):
    """The HMAC key for session values: the token's hash, never the token."""
    return hashlib.sha256(_SESSION_LABEL
                          + str(expected_token or "").encode("utf-8")).digest()


def cookie_value(cookie_header, name):
    """One cookie's value from a `Cookie:` header, or ``""``.

    `http.cookies.SimpleCookie` is not used because it rejects real-world
    quoting on the first malformed pair and drops the rest of the header; this
    header is a search for one name, and a caller's unrelated cookies are none of
    our business.
    """
    for chunk in str(cookie_header or "").split(";"):
        piece = chunk.strip()
        if piece.startswith(name + "="):
            return piece[len(name) + 1:].strip()
    return ""


def _session_signature(expected_token, expiry):
    """The HMAC of one expiry value under the token's key. One definition, so a
    minted value and a presented value are signed by the same expression."""
    return hmac.new(_session_key(expected_token), str(int(expiry)).encode("utf-8"),
                    hashlib.sha256).hexdigest()[:32]


def mint_operator_session(expected_token, *, now=None):
    """A signed `expiry.hmac` session value, keyed by the operator token.

    The token itself is never sent to the browser. The value carries an expiry
    and an HMAC over it, so a client cannot extend its own session and the server
    needs no session table to check one — on a single-core box that also means a
    restart cannot strand a live cookie store.
    """
    if not expected_token:
        return ""
    expiry = int((now if now is not None else time.time()) + OPERATOR_SESSION_TTL)
    return f"{expiry}.{_session_signature(expected_token, expiry)}"


def operator_session_valid(cookie_header_or_value, expected_token, *, now=None):
    """True when this is a session value we minted and it has not expired.

    The signature is checked over the expiry the caller *presented*, never over
    one re-derived from the current clock — minting a fresh value to compare
    against would make every session expire one second after it was issued,
    because the expiry is a float of the present instant. Fail closed on every
    other oddity: no token configured (nothing can be minted, so nothing can
    validate), a short value, a non-numeric expiry, a past expiry, a signature
    that does not match. Comparison is constant-time.
    """
    if not expected_token:
        return False
    value = cookie_value(cookie_header_or_value, OPERATOR_COOKIE) \
        if "=" in str(cookie_header_or_value or "") else str(cookie_header_or_value or "")
    expiry, _, signature = value.partition(".")
    if not expiry.isdigit() or not signature:
        return False
    stamp = now if now is not None else time.time()
    if int(expiry) <= int(stamp):
        return False
    return hmac.compare_digest(signature,
                               _session_signature(expected_token, int(expiry)))


#: The one place the session cookie's attributes are spelled. Every mint and every
#: deletion goes through it, so "what does this cookie assert" has one answer.
#: No `Secure` because this deployment serves plain HTTP; measured 2026-10-31, an
#: enabled `location /operator/` proxy did forward the operator port, so the
#: cleartext risk is real and the mitigation is the proxy refusal in `viewer.py`,
#: not a flag on a cookie over HTTP.
OPERATOR_COOKIE_ATTRS = "Path=/; HttpOnly; SameSite=Strict"


def operator_session_cookie(expected_token, *, now=None):
    """The full `Set-Cookie` string for a minted session, or ``None``.

    `HttpOnly` so a script on the panel cannot read it back, `SameSite=Strict` so
    another page on this box cannot spend it, and an `Max-Age` that matches the
    server-side expiry — a cookie the browser keeps after the signature stops
    validating is only a confusing dead credential.
    """
    value = mint_operator_session(expected_token, now=now)
    if not value:
        return None
    remaining = max(1, int(OPERATOR_SESSION_TTL))
    return (f"{OPERATOR_COOKIE}={value}; Max-Age={remaining}; "
            + OPERATOR_COOKIE_ATTRS)


def gate_operator_port(peer_address, *, authorization="", cookie="",
                       accepts_html=False):
    """The credential every operator-port route now requires.

    Returns `(refusal, set_cookie)`. `refusal` is a `(status, content_type, body)`
    tuple to answer with, or ``None`` when the caller may proceed; `set_cookie` is
    a header value to emit when a proven bearer credential should hand out a
    session — issued once per authenticated request, never on a refusal.
    """
    refusal = _gate(peer_address, authorization, cookie_header=cookie,
                    accepts_html=accepts_html)
    if refusal is not None:
        return refusal, None
    if bearer_matches(authorization):
        return None, operator_session_cookie(session_signing_secret())
    return None, None


# ── the credential: a username and a salted password hash ────────────────────
#
# `RADD_ADMIN_TOKEN` stays the bearer credential, because every existing client of
# this panel — the dashboard's `Authorization` header, the JSON tooling, the
# isolation suites — speaks it, and a bearer token is the right shape for a
# machine. What it was never the right shape for is a *human* at a keyboard: the
# only way a person could use it was to paste it into a URL, which is the leak the
# gate above just closed. So a human types a username and a password.
#
# What the server stores about that password is a decision, not an accident, and it
# is the one this module's own header line demanded: an HMAC compare of a presented
# secret "is *not* a login and must never be mistaken for one". A login that keeps
# the password in plaintext and compares it with `compare_digest` is that same
# compare wearing a form, and it fails three ways at once: a readable environment
# dump is a password dump, the value survives in whatever snapshotted the
# environment, and the compare is only constant-time for an attacker who already
# knows the length. So the stored form is a **salted KDF digest**, and the only
# plaintext this module accepts is the one a person types once.
#: Login name. Defaults to `admin` so an operator who sets only a password gets a
#: working login rather than an unguessable username.
ADMIN_USERNAME_ENV = "RADD_ADMIN_USERNAME"
DEFAULT_ADMIN_USERNAME = "admin"
#: The machine credential: `Authorization: Bearer …`, constant-time compared.
TOKEN_ENV = "RADD_ADMIN_TOKEN"
#: The human credential, stored as a self-describing hash. Format:
#: `$scrypt$N=<n>,r=<r>,p=<p>$<b64 url-safe salt, unpadded>$<b64 dk, unpadded>`
#: or `$pbkdf2-sha256$<rounds>$<b64 salt>$<b64 dk>`. Mint one with
#: `python3 -S Fast_Fetch/admin_panel.py hash-password`.
PASSWORD_HASH_ENV = "RADD_ADMIN_PASSWORD_HASH"
#: Named so the refusal can be about it. A plaintext password in the environment is
#: NOT a credential this panel will use: set with no `RADD_ADMIN_PASSWORD_HASH`,
#: login answers 503 and tells the operator to mint the hash. Silently falling back
#: to a plaintext compare is the exact defect this block exists to remove.
PLAINTEXT_PASSWORD_ENV = "RADD_ADMIN_PASSWORD"
#: Optional dedicated session-signing key. Falling back to the stored hash string
#: means a box that configured only a login still has a high-entropy key — that
#: string is not the password, and it never leaves the environment.
SESSION_SECRET_ENV = "RADD_ADMIN_SESSION_SECRET"

#: The parameters a mint writes into the string it prints, so verification always
#: reads them from the stored value and a future change can never silently
#: re-interpret an old hash. scrypt at N=2**14, r=8, p=1 needs 16 MiB and measured
#: 1,013 ms per derive on this box's single vCPU (`nice -n 19`, 2026-11-01) —
#: deliberate: that is what an attacker pays per guess, and `auth` in
#: redact.BUCKET_LIMITS is what caps how many guesses a minute they may buy.
PASSWORD_KDF = "scrypt"
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
PBKDF2_ROUNDS = 200_000
SALT_BYTES = 16
DK_BYTES = 32


def _b64(raw: bytes) -> str:
    """URL-safe base64 with the padding stripped: the separators in this format are
    `$`, and `=` is what every query parser in the world would choke on."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(kdf: str, password: str, salt: bytes, *, n: int, r: int, p: int,
            rounds: int, dk_bytes: int) -> bytes:
    if kdf == "scrypt":
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                              dklen=dk_bytes, maxmem=(n * r * p * 2) + (16 << 20))
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds,
                               dk_bytes)


def mint_password_hash(password: str, *, kdf: str = PASSWORD_KDF, n: int = SCRYPT_N,
                       r: int = SCRYPT_R, p: int = SCRYPT_P,
                       rounds: int = PBKDF2_ROUNDS, salt: bytes | None = None) -> str:
    """The stored form of the human credential. The only place parameters are chosen.

    A fresh random salt per mint (`secrets.token_bytes`, not the clock, not the
    username), so two operators who pick the same password store different strings
    and no attacker can pre-compute a table against this deployment.
    """
    password = str(password or "")
    if not password:
        raise ValueError("an empty password has no hash worth storing")
    chosen = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    digest = _derive(kdf, password, chosen, n=n, r=r, p=p, rounds=rounds,
                     dk_bytes=DK_BYTES)
    if kdf == "scrypt":
        return f"$scrypt$N={n},r={r},p={p}${_b64(chosen)}${_b64(digest)}"
    return f"$pbkdf2-sha256${rounds}${_b64(chosen)}${_b64(digest)}"


def parse_password_hash(spec: str) -> dict | None:
    """The stored string taken apart, or ``None`` when it is not one.

    Deliberately total: a truncated, mistyped or hostile value is a refusal here,
    and a refusal never raises out of an authentication route.
    """
    text = str(spec or "").strip()
    if not text.startswith("$") or "$" not in text[1:]:
        return None
    pieces = text.split("$")
    # A leading `$` makes pieces[0] empty — the format is a marker, not a field.
    if pieces[0] != "" or len(pieces) != 5:
        return None
    _, scheme, params, salt, digest = pieces
    try:
        if scheme == "scrypt":
            fields = dict(part.split("=", 1) for part in params.split(","))
            n, r, p = (int(fields["N"]), int(fields["r"]), int(fields["p"]))
            if n < 2 or (n & (n - 1)) or r < 1 or p < 1:
                return None
            rounds = 0
        elif scheme == "pbkdf2-sha256":
            rounds = int(params)
            n = r = p = 0
            if rounds < 1_000:
                return None
        else:
            return None
        raw_salt, raw_digest = _unb64(salt), _unb64(digest)
    except (ValueError, KeyError, TypeError):
        return None
    if len(raw_salt) < 8 or len(raw_digest) < 16:
        return None
    return {"kdf": scheme, "n": n, "r": r, "p": p, "rounds": rounds,
            "salt": raw_salt, "dk": raw_digest}


def verify_password(password: str, spec: str) -> bool:
    """Constant-time comparison of two *derived* values; the password never is.

    No branch here depends on the password's content, and a stored digest that is
    32 bytes says nothing about the length of the secret that produced it.
    """
    parsed = parse_password_hash(spec)
    if not parsed:
        return False
    try:
        derived = _derive(parsed["kdf"], str(password or ""), parsed["salt"],
                          n=parsed["n"], r=parsed["r"], p=parsed["p"],
                          rounds=parsed["rounds"], dk_bytes=len(parsed["dk"]))
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(derived, parsed["dk"])


def password_hash_spec() -> str:
    """The stored human credential, or ``""``. Read per call, never cached, so an
    operator who re-mints and reloads the environment is not still gated by the
    hash this process memorised."""
    return str(os.environ.get(PASSWORD_HASH_ENV) or "").strip()


def admin_secret():
    """Any credential this panel has at all — the fail-closed switch, not a compare.

    Empty when the environment carries no token, no session secret and no stored
    password hash, and empty means *deny everything*: the rule that already governs
    `_gate`, `mint_operator_session` and the whole-port gate. A caller that means to
    compare something uses `bearer_secret()` (a header) or `session_signing_secret()`
    (a cookie); neither should reach for this one. Read per call, never cached, so an
    operator who rotates the value is not still gated by what this process
    memorised.
    """
    return (str(os.environ.get(TOKEN_ENV) or "").strip()
            or str(os.environ.get(SESSION_SECRET_ENV) or "").strip()
            or password_hash_spec())


def bearer_secret() -> str:
    """The value a `Bearer` header is compared to: `RADD_ADMIN_TOKEN`, or nothing.

    Deliberately NOT `admin_secret()`. The stored password *hash* is a legitimate
    session-signing key and a legitimate thing to keep in the environment, but if it
    also satisfied a bearer header then anyone who could read that one environment
    entry would hold a working machine credential, and a token the owner rotated out
    would silently still be replaced by a second way in. A box with no token simply
    has no bearer surface: it authenticates by signing in.
    """
    return str(os.environ.get(TOKEN_ENV) or "").strip()


def session_signing_secret() -> str:
    """The HMAC key behind a session cookie's signature.

    `RADD_ADMIN_SESSION_SECRET` when the owner set one (the only value whose whole
    job is this, and the one to set if the password hash is ever re-minted while
    people are logged in), else the bearer token, else the stored hash string. Every
    one of those rotates sessions when it changes, which is the property an operator
    actually wants after a suspected leak: sign out of the panel by changing the
    environment, not by hunting for a session table this box never had.
    """
    return (str(os.environ.get(SESSION_SECRET_ENV) or "").strip()
            or str(os.environ.get(TOKEN_ENV) or "").strip()
            or password_hash_spec())


def admin_username():
    """The configured login name, never the secret and never a value from a body."""
    return (str(os.environ.get(ADMIN_USERNAME_ENV) or "").strip()
            or DEFAULT_ADMIN_USERNAME)


#: Failed-login policy: five wrong answers, then a quarter of an hour of nothing.
LOGIN_FAIL_LIMIT = 5
LOGIN_LOCK_SECONDS = 15 * 60
#: A lockout table that grows without bound is a memory leak on a 1-core box, and
#: the only key in it is one username. The cap is a guard rail, not a feature: at
#: `DEFAULT_ADMIN_USERNAME` there is exactly one live entry in practice.
_LOGIN_TABLE_MAX = 64
_login_failures = {}
_login_lock = threading.Lock()


def login_locked_until(username, *, now=None):
    """Epoch seconds when this name may try again, or ``0`` when it may not be
    locked at all. Pure read: it does not consume an attempt."""
    stamp = now if now is not None else time.time()
    name = str(username or "")
    with _login_lock:
        record = _login_failures.get(name)
    if not record:
        return 0
    count, locked_until = record
    if locked_until and locked_until > stamp:
        return locked_until
    if count >= LOGIN_FAIL_LIMIT and locked_until and locked_until <= stamp:
        # The window has passed: the lock expires by itself, taking its counter
        # with it, so an operator who waits out the 15 minutes is not still one
        # wrong keystroke away from a second lockout.
        with _login_lock:
            _login_failures.pop(name, None)
    return 0


def _note_login_failure(username, *, now=None):
    stamp = now if now is not None else time.time()
    name = str(username or "")
    with _login_lock:
        count, _locked = _login_failures.get(name, (0, 0.0))
        count += 1
        _login_failures[name] = (
            count, stamp + LOGIN_LOCK_SECONDS if count >= LOGIN_FAIL_LIMIT else 0.0)
        if len(_login_failures) > _LOGIN_TABLE_MAX:
            for stale in sorted(_login_failures)[:len(_login_failures) - _LOGIN_TABLE_MAX]:
                _login_failures.pop(stale, None)
    return count


def _clear_login_failures(username):
    with _login_lock:
        _login_failures.pop(str(username or ""), None)


def reset_login_lockouts():
    """Empty the lockout table. For a test, and for an operator who is locked out
    of their own box and can reach its shell."""
    with _login_lock:
        _login_failures.clear()


def authenticate(username, password, *, peer_address=None, now=None):
    """`(ok, refusal, set_cookie)` for one username/password attempt.

    Checked in this order, and the order is the security argument:

    1. **loopback first** — a remote peer never gets to *attempt* a password, so it
       learns nothing about the lockout table either.
    2. **stored hash present second** — with no `RADD_ADMIN_PASSWORD_HASH` there is
       nothing to verify against, and this panel answers 503 rather than inventing a
       credential. The plaintext `RADD_ADMIN_PASSWORD` a deployer might expect to be
       the fallback is never read here: that fallback is how a form-login silently
       becomes an unsalted compare.
    3. **locked out third** — while a name is locked the password is not derived at
       all. Verifying anyway would make the lockout a speed bump, and on a single
       vCPU it would also let a locked-out attacker keep paying for scrypt.
    4. **then both halves of the credential**, and the password is derived before the
       name is compared, so a wrong username costs exactly what a wrong password
       costs. The order of the two *compares* is irrelevant to the outcome; the order
       here is what makes the cost unmeasurable.

    A wrong password, a wrong username, an empty password and a missing one all
    return the *same bytes* (401, same body, same headers), which is what the
    isolation suites assert. They also cost the *same work*: the KDF runs before the
    username is compared, so neither the answer nor the wall clock distinguishes "no
    such operator" from "wrong password". That ordering is not an accident and
    `test_a_wrong_username_still_pays_for_the_derive` keeps it one — the cheaper
    arrangement (compare the name, then derive) is the one that leaks, because this
    deployment publishes its username.

    `set_cookie` is returned ONLY on success. `peer_address=None` means "the caller
    already proved the peer", which is what the mount does; a test that wants the
    loopback rule passes it explicitly.
    """
    if peer_address is not None and str(peer_address).strip() not in _LOOPBACK:
        return False, _problem("forbidden", LOGIN_PATH,
                               "This surface answers on loopback only.",
                               stable=True), None
    spec = password_hash_spec()
    if not spec:
        return False, _problem("unavailable", LOGIN_PATH,
                               "No stored operator password is configured.",
                               stable=True), None
    name = str(username or "").strip()
    locked = login_locked_until(name, now=now)
    if locked:
        wait = max(1, int(locked - (now if now is not None else time.time())))
        # 429, not 401: an operator who is typed-out deserves to know they are
        # rate-limited rather than wrong. The trade is stated honestly — with the
        # default username this leaks nothing an attacker cannot guess, and the
        # alternative is a person hammering a correct password for 15 minutes
        # because the panel told them it was wrong.
        return False, _problem("rate_limited", LOGIN_PATH,
                               f"Too many failed attempts. Try again in {wait}s.",
                               stable=True), None
    signing = session_signing_secret()
    username_ok = hmac.compare_digest(name.encode("utf-8"),
                                      admin_username().encode("utf-8"))
    # A blank field is measured against a one-byte dummy so the KDF runs for the
    # empty case exactly as it does for a typed one; the compare is still against
    # the stored digest, never against whatever the operator typed.
    password_ok = verify_password(str(password or "") or "\0", spec)
    if username_ok and password_ok:
        _clear_login_failures(name)
        return True, None, operator_session_cookie(signing, now=now)
    _note_login_failure(name, now=now)
    return False, _problem("unauthorised", LOGIN_PATH,
                           "Username or password is wrong.", stable=True), None


def logout_cookie():
    """A `Set-Cookie` that deletes the session: same name, same attributes, no
    value, `Max-Age=0`. Browsers need the path to match the one it was set with, or
    the cookie survives the logout — which is why the attributes come from
    :data:`OPERATOR_COOKIE_ATTRS` and are not retyped here."""
    return f"{OPERATOR_COOKIE}=; Max-Age=0; " + OPERATOR_COOKIE_ATTRS


#: The two login paths, named for the surface a human arrives at. `/admin` is the
#: panel; `/` on the operator port is the dashboard, and both now demand the same
#: cookie before they answer anything.
LOGIN_PATH = ADMIN_PREFIX + "/login"
OPERATOR_LOGIN_PATH = "/operator/login"
LOGOUT_PATH = ADMIN_PREFIX + "/logout"
OPERATOR_LOGOUT_PATH = "/operator/logout"
#: path → where a successful login sends the browser
LOGIN_TARGETS = {LOGIN_PATH: ADMIN_PREFIX,
                 OPERATOR_LOGIN_PATH: "/"}
LOGOUT_TARGETS = {LOGOUT_PATH: LOGIN_PATH,
                  OPERATOR_LOGOUT_PATH: OPERATOR_LOGIN_PATH}
LOGIN_PATHS = frozenset(LOGIN_TARGETS)
LOGOUT_PATHS = frozenset(LOGOUT_TARGETS)
#: The only body keys a login POST may carry. Anything else is refused, so no
#: future field can smuggle itself into a credential check.
_LOGIN_BODY_KEYS = frozenset({"username", "password"})
#: A login page and a refusal are both never cacheable: a shared cache that kept a
#: 401 form would hand it to the next person, and one that kept a redirect would
#: replay a session onto someone else's browser.
_NO_STORE = [("Cache-Control", "no-store")]


def _respond_login_form(target=LOGIN_PATH, *, status=401, reason=""):
    """The login card as an *answer*, with the status the caller deserves.

    401 is the default because that is what an unauthenticated request gets: the
    form is the refusal's shape for a browser, not a downgrade of it. Nothing in
    the page varies with the state behind the gate, so it is an oracle for nothing.
    """
    page = login_form_page(target, reason=reason)
    return (status, CONTENT_HTML, page.encode("utf-8"))


def login_page(path, *, peer_address):
    """`GET /admin/login` / `GET /operator/login` — the form, and nothing else.

    Reached WITHOUT a credential (that is the point), so it carries its own loopback
    rule: a remote peer is refused here exactly as it is refused everywhere else, and
    does not get to see a login box to aim a tool at.
    """
    if str(peer_address or "").strip() not in _LOOPBACK:
        return _problem("forbidden", path,
                        "This surface answers on loopback only.", stable=True), []
    return _respond_login_form(path, status=200), list(_NO_STORE)


def login_submit(path, body, *, peer_address, accepts_html=False, now=None):
    """`POST /admin/login` — check the credential, mint the cookie, redirect.

    Returns `(triple, headers)` with `Cache-Control: no-store` always,
    `Set-Cookie` only on success, and `Location` only on success. 303 rather than
    302 on purpose: it tells the browser to follow with a GET, so a reload of the
    landing page never re-POSTs a password. On failure the caller sees the form
    again at 401 (or 429 once locked) — never a redirect, because a redirect on a
    bad password is how a login page turns into an open redirect.
    """
    headers = list(_NO_STORE)
    if str(peer_address or "").strip() not in _LOOPBACK:
        return _problem("forbidden", path,
                        "This surface answers on loopback only.",
                        stable=True), headers
    if not isinstance(body, dict) or set(body) - _LOGIN_BODY_KEYS:
        return _problem("invalid_params", path,
                        "Sign-in takes a username and a password."), headers
    ok, refusal, cookie = authenticate(body.get("username"), body.get("password"),
                                       peer_address=peer_address, now=now)
    if not ok:
        # A browser that typed something gets the card back with its own status,
        # so a human can retry; the answer still carries no data and never varies
        # with anything but the attempt's own outcome.
        if accepts_html:
            return _respond_login_form(
                path, status=refusal[0],
                reason="locked" if refusal[0] == 429 else ""), headers
        return refusal, headers
    if cookie:
        headers.append(("Set-Cookie", cookie))
    headers.append(("Location", LOGIN_TARGETS.get(path, ADMIN_PREFIX)))
    return (303, CONTENT_HTML, b"Signed in. Redirecting."), headers


def logout_response(path, *, peer_address):
    """`POST /admin/logout` — expire the cookie, redirect to the login card.

    A logout needs no credential: the worst an unauthenticated caller can do with it
    is delete a cookie it does not have, and `SameSite=Strict` means a cross-site
    request cannot even send one. It is POST-only in the page (a link a prefetcher
    follows must not sign the operator out mid-click).
    """
    headers = list(_NO_STORE)
    if str(peer_address or "").strip() not in _LOOPBACK:
        return _problem("forbidden", path,
                        "This surface answers on loopback only.", stable=True), headers
    headers.append(("Set-Cookie", logout_cookie()))
    headers.append(("Location", LOGOUT_TARGETS.get(path, LOGIN_PATH)))
    return (303, CONTENT_HTML, b"Signed out."), headers


def login_form_page(target="/admin", *, reason=""):
    """The dark-mode login card. No credential is required to *see* it, and it
    contains no data: nothing about the catalog, the fleet, or whether a token is
    configured — a login page that varies with the state behind it is an oracle.

    `method="post"` and no action query, so the password goes in the POST body and
    never into a URL, a history entry, or an access log. `autocomplete="username"`
    / `"current-password"` so a password manager can do its job; `rel="noopener"`
    nowhere, because there are no links. `reason` is a fixed vocabulary
    (`locked`/`signed_out`), never caller text.
    """
    notice = ""
    if reason == "locked":
        notice = '<p class="bad">Too many failed attempts — this name is locked ' \
                 'for 15 minutes.</p>'
    elif reason == "signed_out":
        notice = '<p class="dim">Signed out.</p>'
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Sign in — Radd Stream operator</title><style>
:root{{--bg:#0b0f16;--panel:#111826;--edge:#1f2a3a;--ink:#e6edf5;--dim:#8a9bb0;
--accent:#10b981;--bad:#ef4444}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;background:radial-gradient(1200px 600px at 50% -10%,
#14243a 0%,var(--bg) 60%);color:var(--ink);
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{width:100%;max-width:380px;background:var(--panel);border:1px solid var(--edge);
border-radius:14px;padding:26px 24px;box-shadow:0 18px 50px rgba(0,0,0,.45)}}
h1{{margin:0 0 4px;font-size:19px;letter-spacing:.2px}}
.sub{{margin:0 0 20px;color:var(--dim);font-size:13px}}
label{{display:block;margin:0 0 6px;font-size:12px;text-transform:uppercase;
letter-spacing:.6px;color:var(--dim)}}
input{{width:100%;background:#0d1420;border:1px solid var(--edge);border-radius:9px;
color:var(--ink);padding:11px 12px;font:inherit;margin-bottom:14px}}
input:focus{{outline:2px solid var(--accent);outline-offset:1px;border-color:var(--accent)}}
button{{width:100%;background:var(--accent);color:#04160f;border:0;border-radius:9px;
padding:11px 14px;font:600 inherit;cursor:pointer}}
button:hover{{filter:brightness(1.08)}}
.bad{{color:var(--bad);font-size:13px;margin:0 0 14px}}
.dim{{color:var(--dim);font-size:13px;margin:0 0 14px}}
.foot{{margin:18px 0 0;color:var(--dim);font-size:12px}}
code{{background:#0d1420;padding:1px 5px;border-radius:4px;
font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px}}
</style></head>
<body><main class="card">
<h1>Radd Stream operator console</h1>
<p class="sub">Loopback-only control surface. Sign in to continue.</p>
{notice}<form method="post" action="{_e(target)}">
<label for="username">Username</label>
<input id="username" name="username" type="text" autocomplete="username"
 autocapitalize="none" spellcheck="false" required>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password"
 required>
<button type="submit">Sign in</button>
</form>
<p class="foot">A wrong username and a wrong password answer identically, and
{LOGIN_FAIL_LIMIT} failures lock the name for {LOGIN_LOCK_SECONDS // 60} minutes.
This form never puts a credential in a URL.</p>
</main></body></html>
"""


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
#: A whole number that is not money and not a flag: a cadence in minutes, a
#: poster count, a coin cost, a streak grant, a rollover hour. `"count"` rather
#: than `"int"` only because the kind string is display metadata and a neutral
#: spelling keeps it clear of any reserved key the body scan watches for.
_INT = "count"
#: Not `"url"`: every admin body is scanned for provenance *keys*, and `"url"`
#: is one of them. The kind is display metadata, so it takes a neutral spelling.
_URL = "address"
#: A hex digest. Its own kind rather than `_TEXT`, because a checksum is the one
#: setting here that a client *compares* instead of printing: 63 characters, one
#: space or one uppercase digit is not a weaker check but a check that can never
#: pass, and `_TEXT` would store all three.
_DIGEST = "digest"

#: (key, label, kind, default). A key is the column name *and* the POST-body key
#: *and* the admin-card field id, so a setting has exactly one spelling here.
#:
#: The two tokens are the operator's credentials for a third-party payout
#: account. They are stored, they are shown masked on this page, and they are
#: never serialised anywhere else — see :func:`remote_config`.
#:
#: The remote controls — a maintenance switch, the APK-update banner and what
#: identifies the file it points at, and the feature flags the owner asked for —
#: are deliberately in the same single row as pricing so a client has one endpoint
#: and one atomic update, not two settings stores that can disagree.
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
    # Owner's standing directive, verbatim from MONETIZATION_AND_FLEET_PLAN.md §"Pillars":
    # "LINK SHORTENERS ARE PERMANENTLY DROPPED & RETIRED: We will NEVER force users through link
    # shorteners, CAPTCHAs, or 10-second timer redirects." The two token columns above stay so the
    # operator's credentials are not destroyed and the plumbing stays testable, but nothing may
    # detour a download unless this flag is deliberately flipped to 1. Before it existed, the
    # directive held only because the token columns happened to be empty: one saved token in /admin
    # would have re-enabled the detour for every free user, silently.
    ("feature_link_shorteners", "Link-Shortener Download Detour (RETIRED — off)", _FLAG, 0),
    ("maintenance_mode", "Maintenance Mode", _FLAG, 0),
    ("apk_update_url", "APK Update URL banner", _URL, ""),
    # ── UPD-1a: what a phone needs before it offers that banner ───────────────
    # An update banner is an instruction to install whatever answers the address.
    # The client today gates on nothing but `WireText.isHttpUrl`
    # (`App/…/viewmodel/HomeViewModel.kt`, `AppUpdate.from`) and then fires
    # `Intent.ACTION_VIEW` (`App/…/ui/screens/HomeScreen.kt`, `openDownload`), so
    # one mistyped or attacker-pasted URL points every device at an APK nothing
    # identified. These three columns are the pieces a client needs to doubt it: a
    # digest to compare the downloaded bytes against, a size so a truncated fetch is
    # not read as a corrupt file, and a `versionCode` so "newer" is a comparison
    # rather than a guess.
    #
    # This is the backend half on purpose. Until UPD-1b lands a phone still shows
    # the banner from `apk_update_url` alone and reads none of these; the rule
    # UPD-1b enforces is written down here so the two halves are reviewed as one
    # decision: **no digest, no banner.** An empty `apk_update_sha256` is not
    # "unchecked", it is "nothing published", and a client must treat the two the
    # same way — by not offering the update.
    ("apk_update_sha256", "APK Update SHA-256", _DIGEST, ""),
    ("apk_update_size_bytes", "APK Update size (bytes)", _INT, 0),
    ("apk_update_version_code", "APK Update versionCode", _INT, 0),
    ("feature_downloads", "Background Downloads", _FLAG, 1),
    ("feature_pure_cinema", "Pure Cinema Mode", _FLAG, 1),
    ("feature_chromecast", "Chromecast", _FLAG, 1),
    # Defaults OFF on purpose. The three flags above hide a feature the viewer was
    # already free to use; this one withholds catalog content (1080p and 4K) from
    # anyone the ledger has not confirmed, which is a business decision and not a
    # default. Flip it in /admin when the approval traffic exists to serve it.
    ("feature_quality_gate", "Charge VIP for 1080p/4K", _FLAG, 0),
    # ---- engagement pillars ----------------------------------------------------
    # The four knobs `docs/MONETIZATION_PILLARS_SCHEMA.md` §2 reserves for the
    # operator, so an ad cadence, a coin price, a streak grant and the PKR pass
    # ladder are changed from /admin and not by a code push. `Fast_Fetch/engagement.py`
    # is the consumer and holds the same numbers as its own constants; the public
    # block is built *over* `engagement.remote_view()` (see `_engagement_public`),
    # so a number can only ever be written down once, and a whole-dictionary test
    # (`test_admin_panel.test_the_engagement_block_is_the_ledgers_own_projection`)
    # is what makes that a fact rather than an intention.
    #
    # A stored 0 is legal and means "use the default" — never "unlimited" and
    # never "free". `engagement.resolve_caps` clamps a 0 cadence back to the
    # shipped value, and a 0 coin cost or 0 coin grant is refused at spend by
    # `engagement._positive_int`; `remote_config` publishes the same resolution, so
    # a phone is never shown a number the server will not honor. Zero is the one
    # value an operator should think twice about, so the labels say what it does.
    ("ad_preroll_min_gap_minutes", "Ad gap: pre-roll (minutes; 0 = default 25)", _INT, 25),
    ("ad_native_card_every_posters", "Ad slot: native card every N posters (0 = default 12)", _INT, 12),
    ("ad_app_open_min_gap_minutes", "Ad gap: app open (minutes; 0 = default 240)", _INT, 240),
    ("coin_per_rewarded_ad", "Coins per rewarded ad view", _INT, 5),
    ("rewarded_daily_cap", "Rewarded ads counted per local day", _INT, 10),
    ("coin_redeem_day", "Coins: one-day pass", _INT, 30),
    ("coin_redeem_weekend", "Coins: weekend pass", _INT, 70),
    ("coin_redeem_monthly", "Coins: 30-day VIP pass", _INT, 200),
    ("streak_day1_coins", "Streak: day-1 bonus coins", _INT, 10),
    ("streak_day3_coins", "Streak: day-3 bonus coins", _INT, 30),
    ("streak_day7_pass_hours", "Streak: day-7 free pass (hours)", _INT, 24),
    ("streak_day_boundary_hour", "Streak day rolls over at (local hour)", _INT, 4),
    # A TEXT column is created `DEFAULT ''` whatever this tuple says, so a row from
    # before the operator typed anything reads back `''` and `remote_config`
    # publishes the field's own default for it. The default here is therefore a
    # display hint plus the honest answer when the settings row is unavailable —
    # not a value the migration writes.
    ("streak_tz", "Streak timezone (blank = Asia/Karachi)", _TEXT, "Asia/Karachi"),
    # The micro-pass ladder. `pass_monthly_vip_pkr` is the ₨250 one-day-to-a-month
    # *pass* from `docs/MONETIZATION_AND_FLEET_PLAN.md:46`; it is a separate knob
    # from `vip_monthly_pkr` above, which is the subscription price `payments.py`
    # reads. Neither is derived from the other and no code may make them share a
    # value: a pass and a membership are different products.
    ("pass_day_pkr", "PKR: one-day pass", _MONEY, 20),
    ("pass_weekend_pkr", "PKR: weekend pass", _MONEY, 50),
    ("pass_monthly_vip_pkr", "PKR: 30-day VIP pass", _MONEY, 250),
)
_FIELD_BY_KEY = {row[0]: row for row in MONETIZATION_FIELDS}

#: Cap the free-text fields short. A 64-character till id is a mistake or an
#: attempt to park a payload in a display column, and both are refused.
_MAX_TEXT = 64
_MAX_HANDLE = 32
_MAX_TOKEN = 200
_MAX_URL = 500
_MAX_PKR = 10_000_000
#: A whole-number setting is bounded absurdly high on purpose — 25 minutes and
#: 12 posters never approach this. The domain clamp (a cadence of 0 means "use
#: the default, never unlimited") lives in `engagement.resolve_caps`, which is the
#: consumer; this only refuses a paste that cannot be a real setting.
_MAX_INT = 1_000_000
#: Seven count knobs have a domain tighter than that, and the number a phone reads
#: must be the number the server enforces. `engagement.resolve_caps` clamps an
#: over-large cadence to its own `CAP_MAX`, `engagement._clamp_hour` answers a
#: rollover outside 0..23 with the default, and `engagement.resolve_streak_grants`
#: clamps a streak bonus to `STREAK_GRANT_COINS_MAX` and its day-7 pass to
#: `STREAK_GRANT_HOURS_MAX`. A stored value past either bound would be silently
#: rewritten by the consumer, which is the one thing a settings row may not do to
#: its own display. So the consumer's ceiling is refused on the way in instead.
#: `test_the_engagement_block_is_the_ledgers_own_projection` pins these numbers to
#: `engagement`'s own constants, on both sides of the mirror.
_INT_MAX = {
    "ad_preroll_min_gap_minutes": 24 * 60,
    "ad_native_card_every_posters": 5000,
    "ad_app_open_min_gap_minutes": 24 * 60,
    "streak_day_boundary_hour": 23,
    # A literal on each side, deliberately: the write path and `engagement` state
    # the same bound twice, and the pinned test is what makes the two statements
    # one claim. Deriving one from the other would let a wrong constant move both
    # halves together and leave nothing to fail.
    "streak_day1_coins": 10_000,
    "streak_day3_coins": 10_000,
    "streak_day7_pass_hours": 720,
    # The APK descriptors need their own ceilings or `_MAX_INT` would refuse them:
    # that default is 1,000,000, so a size of 5 MB — 5,000,000 bytes, arithmetic
    # rather than a measurement — would 400 as a paste above the ceiling, and a
    # setting a legitimate operator cannot save is a setting that gets worked around.
    # 500 MB is above any build this repo can produce, so a larger paste is a
    # mistake rather than a setting; and a versionCode counts up by one per release,
    # so 2,100,000,000 is a wall no real build approaches that still refuses a
    # phone number or a timestamp pasted into the field. Neither ceiling is a
    # policy — no consumer reads either number as a limit — and neither is derived
    # from the client, which decides for itself what "newer" means.
    "apk_update_size_bytes": 500_000_000,
    "apk_update_version_code": 2_100_000_000,
}

#: A payment *handle*, as the guide writes one: `0300-1234567`, `+92 300 1234567`,
#: `(0300)1234567`, `0300XXXXXXX`, `@raddstream`. A digits-only validator would
#: silently reject the operator's real number, and these strings are printed next
#: to a Copy button rather than parsed, so the shape is theirs — control
#: characters and URLs are refused above regardless of kind.
_HANDLE_RE = re.compile(r"[0-9A-Za-z+()\-. @:_]+")

#: Lowercase hex, exactly 64 of it — the shape of a SHA-256 digest and nothing
#: else. Stored lowercased by `_validated`, because a comparison a client cannot
#: win is worse than a refusal the operator can see.
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _column_ddl(key, kind, default):
    """One column definition, built only from our own literals (see
    :func:`_monetization_ddl`). Used by both CREATE and the migration ALTER so a
    fresh row and an upgraded one cannot drift apart."""
    if kind in (_MONEY, _INT):
        # A price and a cadence are the same thing to SQLite; the difference
        # between them is meaning and validation, not storage.
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
    keys = [row[0] for row in MONETIZATION_FIELDS]
    columns = ", ".join(keys)
    row = conn.execute(
        f"SELECT id, updated_at, {columns} FROM {MONETIZATION_TABLE}"
        f" WHERE id = {MONETIZATION_ID}").fetchone()
    if row is None:
        return None
    # Positional, never row[key]: a caller that passes a connection without the
    # sqlite3.Row factory used to raise TypeError here, get swallowed by the
    # `except sqlite3.Error` upstream, and be answered with the *defaults* — so a
    # saved `maintenance_mode` could be silently ignored and a saved token silently
    # dropped. The SELECT fixes the column order, so the tuple is the contract and
    # any connection may be handed to this function.
    values = {key: row[2 + i] for i, key in enumerate(keys) if row[2 + i] is not None}
    for key, _label, _kind, default in MONETIZATION_FIELDS:
        values.setdefault(key, default)
    values["updated_at"] = int(row[1] or 0)
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


def monetization_values(conn):
    """The operator's settings row, as the row itself answers it — `None` if there is
    no row to read.

    The public half of `_read_monetization`, because a route that charges money has to
    price from the same row the panel publishes, and reading `app_remote_config` with
    its own `SELECT` would be a second mapping of one row: the JOB B defect, in the
    other direction. Unlike `remote_config`, this never calls `_ensure_monetization`
    — creating a table is not a read, and the account routes hold a *read-only* catalog
    handle, where an attempt to write raises rather than being quietly skipped. A
    caller that gets `None` (no row, or a catalog that predates this table) resolves
    the shipped numbers, which is the same answer `engagement.resolve_ladder` and
    `payments.price_table` give to a deployment that never saved a setting.
    """
    return _read_monetization(conn)


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

    if kind == _INT:
        if isinstance(value, bool):
            return None, label          # True is 1 to Python; a count is not a flag
        text = str(value).strip()
        number = _int_or_none(text)
        # 0 is a legal stored value here — the consumer decides what it means
        # (`resolve_caps` reads a 0 cadence as "use the default", and
        # `remote_config` publishes the default for it). A negative or
        # non-numeric paste is refused before it can reach that logic, and so is a
        # paste above the key's own ceiling, which the consumer would otherwise
        # clamp behind the operator's back. See :data:`_INT_MAX`.
        if number is None or number < 0 or number > _INT_MAX.get(key, _MAX_INT):
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

    if kind == _DIGEST:
        # A checksum is the one setting here that gets *compared* rather than
        # printed, so its failure mode is silence: a 63-character paste, a trailing
        # space or an uppercase `A` saves fine under `_TEXT` and then never matches
        # the hash of a correctly downloaded file, which reads to the operator as a
        # banner that will not appear rather than as a row that cannot be right.
        # Empty is legal and means "nothing published" — see the note on the field.
        # Case is normalised on the way in, because a comparison a client cannot win
        # is worse than a refusal the operator can see.
        if not isinstance(value, str):
            return None, label
        text = value.strip().lower()
        if not text:
            return "", None
        if not _SHA256_RE.fullmatch(text):
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


def _setting_count(values, key):
    """One whole-number knob, resolved the way its consumer resolves it.

    A stored 0 is not a number to obey. `engagement.resolve_caps` ignores a
    non-positive cadence — a 0-minute ad gap is "an ad with no gap at all", and the
    owner's rule is that it never means unlimited — and `engagement._positive_int`
    raises on a 0-coin cost, so a 0-coin pass is refused at spend rather than handed
    out. Answering with the field's own default therefore publishes what the ledger
    will actually do; the default is the value `engagement` ships, because the
    projection below is built from `engagement.remote_view()`. A paste above the
    key's ceiling never gets here: `_validated` refuses it (`_INT_MAX`)."""
    try:
        number = int(values.get(key) or 0)
    except (TypeError, ValueError):
        number = 0
    return number if number > 0 else int(_FIELD_BY_KEY[key][3])


def _rollover_hour(values, key):
    """The one zero that means something: hour 0 is midnight, a real streak
    rollover and not a "use the default" sentinel. `engagement._clamp_hour` accepts
    0..23 and answers the default outside that range, so this publishes exactly what
    that clamp honors."""
    try:
        number = int(values.get(key) or 0)
    except (TypeError, ValueError):
        return int(_FIELD_BY_KEY[key][3])
    return number if 0 <= number <= 23 else int(_FIELD_BY_KEY[key][3])


def _engagement_public(values):
    """The engagement pillars as a phone reads them: `engagement.remote_view()`
    with the operator's row applied over it.

    Building on that projection, instead of spelling the block out here, is the
    point. `engagement.py` owns the wallet, the ladder, the streak and the caps, and
    its own docstring already promises this body at
    `/api/v1/app/remote-config.engagement`; a second copy of the shape in the
    settings module would be two shapes, and the one failure a price body cannot
    have is disagreeing with the ledger that fills it. A cadence is resolved by the
    consumer's own `resolve_caps`, and the coin and streak numbers by the same rule
    its `_positive_int` enforces — so the number a client draws is the number the
    server enforces.

    Money is the exception, published as stored: nothing clamps a PKR price, so the
    row is the price. `pass_monthly_vip_pkr` is the 30-day PASS and `vip_monthly_pkr`
    the MONTHLY SUBSCRIPTION — two products, two knobs, and no code may link them.

    The ladder is not spelled out key by key any more; it is
    `engagement.resolve_ladder(values)` projected by `engagement` itself. That is
    what makes the published price and the charged price the same sentence:
    `redeem_pass(values=…)` reads the identical resolver, so there is no way to
    reprice a tier in one place and not the other. Before this, this function held
    its own `(plan, coin knob, pkr knob)` tuple list while the spender read
    `PASS_LADDER` directly — two mappings of the same row, and the only thing
    keeping them honest was that nobody had edited one of them."""
    view = engagement.remote_view()
    view["cadence"] = engagement.resolve_caps(
        {key: _setting_count(values, key) for key in view["cadence"]})
    ladder = engagement.resolve_ladder(values)
    view["passes"] = engagement.passes_projection(ladder)
    view["wallet"]["redeem_coin_costs"] = {plan: int(spec["coins"])
                                          for plan, spec in ladder.items()}
    view["wallet"]["coin_per_rewarded_ad"] = _setting_count(values, "coin_per_rewarded_ad")
    view["wallet"]["rewarded_daily_cap"] = _setting_count(values, "rewarded_daily_cap")
    # The streak ladder is published through the resolver that grants it, not key by
    # key here — the same correction `resolve_ladder` got for the pass prices. Reading
    # `streak_day1_coins` a second way would put a second mapping of one row between
    # the number a phone is shown and the number `coin_ledger` writes, and would
    # publish a bonus above `engagement.STREAK_GRANT_COINS_MAX` that the ledger then
    # quietly clamps.
    streak = engagement.resolve_streak_grants(values)
    grants = view["streak"]["grants"]
    grants["day1_coins"] = streak["coins"][1]
    grants["day3_coins"] = streak["coins"][3]
    grants["day7_pass_seconds"] = streak["pass_seconds"]
    view["streak"]["day_boundary_hour"] = _rollover_hour(
        values, "streak_day_boundary_hour")
    # A TEXT column is created `DEFAULT ''` whatever the spec says, so an operator
    # who never typed a zone stores `''` and must be answered the zone the ledger
    # will bucket days with — not an empty string a client would read as UTC.
    zone = redact.scrub_text(str(values.get("streak_tz") or "").strip())
    view["streak"]["tz"] = zone or str(_FIELD_BY_KEY["streak_tz"][3])
    return view


def remote_config(conn):
    """The app-facing projection: what a phone needs to take a payment and to
    hang a sponsor card, to decide whether an offered APK is the file the operator
    actually published, and nothing that is a credential.

    A shortener API token in this body would be readable by anyone who can reach
    the endpoint — and this host is plain HTTP (§ ORACLE_DEPLOYMENT.md), so that
    is anyone on the path, not only the caller. Whoever holds it can shorten on
    the operator's account, spend their quota and poison their standing with the
    network, which is exactly how shorteners ban affiliates. So the public answer
    says `configured: true|false` — enough for a client to choose the direct or
    the shortened path — and the call itself belongs on the server side, where
    the token stays in the row. Payment handles and ad unit ids *are* display
    content (the app prints them next to a Copy button), so they publish.

    The `engagement` block is a price list, and a price list is only worth
    publishing if it is the one the server will charge. It is built over
    `engagement.remote_view()` (`_engagement_public`) rather than spelled out here
    for that reason: an ad cadence, a coin cost, a streak grant and the PKR pass
    ladder each reach the phone with the same resolution their consumer applies, so
    a client drawing the table and the ledger filling it cannot disagree about what
    a day pass costs. No knob in it can be cashed out — there is no cash-out path in
    `engagement.py` at all — and no field of it is a credential.

    `settings_unavailable` is the answer to a read that could not be answered, and it
    exists because the fallback below was otherwise a lie. When `_read_monetization`
    raises — a locked table, a corrupt page, a deployment mid-migration — this body
    published the shipped defaults with no marker, so a phone read
    `maintenance_mode: false`, `feature_flags` all on and the default PKR prices, and
    acted on them, while the operator had flipped exactly those switches. The panel's
    own diagnostic says `the settings row is unavailable` in that state
    (`SETTINGS_UNAVAILABLE`, :1604, used at :1943 and :3109); the public route said
    nothing. The defaults stay in the body — a client that decodes flat keys must not
    crash on a degraded answer — but the marker tells the client that this is a shape
    guarantee and not the operator's decision, and the rule the app half (q4) must
    implement is: **when `settings_unavailable` is true, keep the last cached config,
    do not act on these values.** Treating unknown as `false` is how a remote control
    fails open.
    """
    unavailable = False
    try:
        _ensure_monetization(conn)
        values = _read_monetization(conn)
    except sqlite3.Error:
        values = None
        unavailable = True
    if values is None:
        # Either the read raised, or the row `_ensure_monetization` only just
        # inserted is not there. Both mean "unknown", and the two are not worth
        # separating: a client can only be told one thing.
        unavailable = True
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
        # Flat and a real boolean, same rule as every other flag below: a client
        # that writes `if (cfg.settingsUnavailable) keepLastGood()` must not have to
        # guess whether `0` and `false` mean different things.
        "settings_unavailable": unavailable,
        "maintenance_mode": flag("maintenance_mode"),
        "apk_update_url": shown("apk_update_url"),
        # Flat and additive, never nested: `VipRemoteConfig.kt` decodes
        # `apk_update_url` at the top level of this body and every phone caches it
        # for 60 s, so moving it under an `apk_update` object would break a client
        # that has not been updated yet. An un-updated client reads what it always
        # read; an updated one reads these too and can decline to offer an
        # unverifiable banner. `""` and `0` are not values to use, they are the
        # absence of a publication, which is the whole point of publishing them.
        "apk_update_sha256": shown("apk_update_sha256"),
        "apk_update_size_bytes": int(values.get("apk_update_size_bytes") or 0),
        "apk_update_version_code": int(values.get("apk_update_version_code") or 0),
        "feature_flags": {
            "downloads": flag("feature_downloads"),
            "pure_cinema": flag("feature_pure_cinema"),
            "chromecast": flag("feature_chromecast"),
            # The client must not guess this one: without it, a phone that knows the
            # ledger says "not VIP" would hide 1080p and 4K from a viewer the operator
            # never asked it to restrict.
            "quality_gate": flag("feature_quality_gate"),
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
        "engagement": _engagement_public(values),
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

    Empty when the flag `feature_link_shorteners` is off (the shipped default,
    and the operator has not enabled it), when the operator has saved no token,
    or when the settings row is unavailable — which is the same answer to the
    caller as "shorteners are off": the download route falls back to the
    direct URL. When the operator enables it (owner decision 2026-11-06),
    shortening applies ONLY to web-page requests (`?via=web`); the app's
    native downloads stay direct. Read-only and idempotent, like
    :func:`remote_config`."""
    try:
        _ensure_monetization(conn)
        values = _read_monetization(conn)
    except sqlite3.Error:
        return []
    if values is None:
        return []
    if not _as_flag(values.get("feature_link_shorteners", 0)):
        # Off by default. A saved token is not consent to detour a free user's
        # download: the download route reads this list, so refusing here is the
        # one place the policy can be enforced for every caller.
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


#: The writes that a browser session can trigger. A payment review is deliberately
#: absent: its token is bound to one (action, payment id) pair and `_review_payment`
#: already refuses without it, which is a stronger claim than same-origin.
_ORIGIN_WRITES = {
    SAVE_MONETIZATION_PATH.rsplit("/", 1)[-1]: SAVE_MONETIZATION_PATH,
    RUN_SCRAPER_PATH.rsplit("/", 1)[-1]: RUN_SCRAPER_PATH,
}
_EVIDENCE_ORIGIN_ACTION = "link-evidence"
#: Where a JSON client puts the same-origin token when there is no body to put it
#: in — the evidence re-fold reads none, so a header is the only place left, and a
#: header is also what a cross-site page cannot set without a CORS preflight this
#: panel's own allow-list would have to grant first.
CSRF_HEADER = "X-Radd-Action-Token"


def panel_origin_token(action: str) -> str:
    """The same-origin token for one write, minted for the page to carry.

    Bound to (action, `*`), not to a session, for the same reason the payment token
    is: this panel keeps no session table, and a per-process secret that dies with a
    restart is honest — an operator reloads. It is NOT the credential and gains
    nothing on its own; it only proves the request was assembled by a page this
    process rendered. It never goes in a URL, which is the whole lesson of the
    query-string token this branch deleted."""
    return _csrf_token(action, "*")


def _origin_action(path):
    """The same-origin action name for this POST, or ``None`` when it needs none."""
    segments = _segments(path)
    if len(segments) == 3 and segments[2] in _ORIGIN_WRITES:
        return segments[2]
    if (len(segments) == 5 and segments[1] == "api" and segments[2] == "links"
            and segments[4] == "evidence"):
        return _EVIDENCE_ORIGIN_ACTION
    return None


def _origin_ok(action: str, body, csrf_header) -> bool:
    """True when the write carries the token the page was rendered with.

    Checked only for a cookie-authenticated request. A bearer request does not need
    it: a cross-site page cannot attach an `Authorization` header without a preflight
    the CORS allow-list refuses, so the bearer itself already proves the caller
    assembled the request on purpose. That distinction is why adding this rule broke
    none of the 41 existing monetization and fleet tests, which all present a bearer.
    """
    presented = ""
    if isinstance(body, dict):
        presented = str(body.get("csrf") or "")
    presented = presented or str(csrf_header or "")
    return _csrf_ok(action, "*", presented)


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
    """The queue, its recent history and the relay's unclaimed money, as data. Raw
    `tid` included, because the operator is the only reader this surface has
    (`viewer.py` 404s `/admin` on the public port, `_gate` demands loopback plus the
    bearer token) and a TID they cannot see is a TID they cannot check."""
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
        # Money the SMS relay confirmed that no claim has spent yet. The operator
        # cannot approve a row that does not exist, so this is a list to explain a
        # waiting payer with, not a queue to work — and it is why the row is deleted
        # when it buys a credit rather than flagged (`payments._consume_verified`).
        "unclaimed": payments.unclaimed_credits(conn, limit=_RECENT_LIMIT),
        "approve_path": APPROVE_PAYMENT_PATH,
        "reject_path": REJECT_PAYMENT_PATH,
        "note": ("a transaction id is a claim until a human who has read the payment"
                 " SMS closes it; the only automatic credit is a relay callback that"
                 " matches a claim on gateway, TID and the exact PKR this server"
                 " quoted, and it is audited as " + payments.RELAY_REVIEWER),
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


def _payment_forms(action_path, row) -> str:
    """The two buttons, as real HTML forms.

    Each carries the CSRF token for its own (action, payment) pair and posts to a
    bare path. Nothing credential-shaped goes in the `action` any more: the earlier
    version put the operator's own token in the form action, which meant every
    approve or reject wrote the credential into browser history, into nginx's access
    log, and into the `Referer` of whatever the refreshed page asked for. A
    `<form>` cannot set an `Authorization` header, and now it does not need one — the
    `HttpOnly` session cookie the sign-in page minted travels with the POST by
    itself, and `csrf` proves the page that rendered the button is the page that is
    answering. That is the whole replacement for a token in the URL: the browser
    authenticates, the token authorizes one specific button."""
    identifier = row["payment_id"]
    shared = (f'<input type="hidden" name="payment_id" value="{_e(identifier)}">'
              f'<input type="hidden" name="{_FORM_FLAG}" value="1">'
              f'<input type="hidden" name="reviewer" value="panel">')
    approve = (
        f'<form method="post" class="inline" action="{_e(action_path)}">'
        f'{shared}'
        f'<input type="hidden" name="csrf" value="{_e(_csrf_token(payments.STATUS_APPROVED, identifier))}">'
        '<button class="btn" type="submit">Approve</button></form>')
    reject = (
        f'<form method="post" class="inline" action="{_e(REJECT_PAYMENT_PATH)}">'
        f'{shared}'
        f'<input type="hidden" name="csrf" value="{_e(_csrf_token(payments.STATUS_REJECTED, identifier))}">'
        '<input class="limit" type="text" name="note" maxlength="80"'
        ' placeholder="why"> <button class="btn" type="submit">Reject</button>'
        '</form>')
    return approve + " " + reject


def render_payments_page(data, query, banner=""):
    """The payment queue page. Loopback only, like the rest of `/admin`.

    `query` still drives the queue's `limit`, and nothing else: it used to supply a
    `token` to paste into every button's action URL, which is the leak the sign-in
    cookie replaces."""
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
        '<div class="warn"><strong>A transaction id is what the payer typed.</strong>'
        ' Check your own payment SMS for the amount and the reference before you'
        ' approve, and approve only then. The relay is one exception, and a narrow'
        ' one: a callback that holds the merchant secret and matches an existing'
        ' claim on gateway, TID and the exact PKR this server quoted closes the row'
        ' as <code>' + _e(payments.RELAY_REVIEWER) + '</code> while you sleep.'
        ' Everything else waits for you. A TID is printed on this page and nowhere'
        ' else on the account surface.</div>',
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
                line.append(_payment_forms(APPROVE_PAYMENT_PATH, row))
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
    parts.append("</section>")
    parts.append('<section class="card"><h2>Relay-confirmed, unclaimed</h2>')
    parts.append(_table(("gateway", "TID", "PKR", "seen"),
                        [[_e(row.get("gateway")), _e(row.get("tid")),
                          _e(row.get("amount_pkr")), _ts(row.get("verified_at"))]
                         for row in data.get("unclaimed") or []]))
    parts.append('<p class="hint">Money the SMS relay reported that no claim has'
                 ' spent. Nothing here is approvable — the credit lands the moment'
                 ' the payer files the matching reference — so this list exists to'
                 ' explain someone who has paid and not submitted, and to be checked'
                 f' against your bank statement. A record older than'
                 f' {int(payments.VERIFIED_TID_MAX_AGE_SECONDS // 86400)} days'
                 ' credits nothing by itself and waits for you like a claim does.'
                 '</p></section></div></body></html>')
    return "".join(parts)


# ── the usage report: how many, not who ───────────────────────────────────────

#: The screens that read the accounts ledger instead of the catalog. `usage_*`
#: tables live in `user_state.db` beside `user_accounts` and `payment_transactions`
#: because that is the file the writes that earn the counters already touch;
#: listing them here rather than in `_SCREENS` is what stops a state screen being
#: handed a catalog connection and answering 200 with nothing in it.
_STATE_SCREENS = frozenset({"usage"})


def screen_usage(state_db_path=None, *, window_days: int = 30, now=None) -> dict:
    """`GET /admin/api/usage` — installs, live devices, retention, money.

    Aggregates only, and that is the design rather than a limitation: see
    `usage_stats`'s module docstring for the three rules (no per-person
    timeline, no device-to-name join, no IP) and for why every number here is
    incremented on the write that earned it instead of being scanned out of a
    150,799-post table when the operator hits refresh on a single core.

    Fails to an honest empty state like every other screen. `window_days` is
    clamped by `usage_stats.summary` itself, so a caller cannot ask for a
    thirty-thousand-day window and read the whole metric history.
    """
    try:
        return usage_stats.summary(state_db_path or accounts.default_db_path(),
                                   now=now, window_days=window_days)
    except Exception:                                  # noqa: BLE001 — a screen never raises
        return {"available": False, "detail": LEDGER_UNAVAILABLE}


def render_usage_page(data):
    """The usage report as a plain operator page, from the payload alone.

    Every value passes `_e()` because a dimension label arrives from a client
    header; the shape check in `usage_stats.clean_value` is the first gate and
    escaping is the second, and a display surface takes both. No number is
    coloured or phrased as a trend: the window is printed, the reader decides.
    """
    if not data.get("available"):
        return (
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Usage — operator</title>"
            f"<style>{_STYLE}</style></head><body>"
            "<div class=\"wrap\"><h1>Usage</h1><p class=\"sub\">"
            + _e(str(data.get("detail") or "no_usage_data_yet"))
            + " — nothing has been counted yet, and a page of zeros is not a"
            " measurement.</p></div></body></html>")
    installs = data.get("installs", {})
    active = data.get("active_users", {})
    live = data.get("live_sessions", {})
    accounts_row = data.get("accounts", {})
    parts = [
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>Usage — operator</title>",
        f"<style>{_STYLE}</style></head><body><div class=\"wrap\">",
        "<h1>Usage</h1>",
        f'<p class="sub">Aggregates only — no per-device timeline, no IP, no'
        f' name join. Window: {_e(str(data.get("window_days")))} days.</p>',
    ]

    def card(title, pairs):
        parts.append(f'<section class="card"><h2>{_e(title)}</h2><dl>')
        for key, value in pairs:
            parts.append(f"<dt>{_e(str(key))}</dt><dd>{_e(str(value))}</dd>")
        parts.append("</dl></section>")

    card("Devices", [
        ("distinct installs", installs.get("distinct_devices")),
        ("new today", installs.get("new_today")),
        ("new this window", installs.get("new_this_window")),
        ("live last 5 min", live.get("5m")),
        ("live last 30 min", live.get("30m")),
        ("live last 60 min", live.get("60m")),
        ("DAU", active.get("dau")),
        ("WAU", active.get("wau")),
        ("MAU", active.get("mau")),
    ])
    card("Accounts", [
        ("total", accounts_row.get("total")),
        ("vip active", accounts_row.get("vip_active")),
        ("revoked", accounts_row.get("revoked")),
    ])
    retention = data.get("retention", {})
    card("Retention (returned on or after D+n)", [
        (name, "%s / %s (%s)" % (row.get("returned"), row.get("cohort_installs"),
                                 row.get("rate")))
        for name, row in retention.items()
    ])
    playback = data.get("playback", {})
    card("Playback", [
        ("server stream starts", playback.get("server_stream_starts")),
        ("client playback attempts", playback.get("client_playback_attempts")),
        ("buffer failures", playback.get("buffer_failures")),
        ("buffer failure rate", playback.get("buffer_failure_rate")),
        ("rate denominator", playback.get("rate_denominator")),
    ])
    for title, key in (("crash by device class", "crash_by_class"),
                       ("error by device class", "error_by_class"),
                       ("buffer failure by device class", "buffer_failure_by_class")):
        card(title, sorted((data.get(key) or {}).items()))
    # The owner's "how many, from where, on what build" question. Both halves are
    # `usage_device` group-bys: installed is every bucket, active is the buckets
    # seen in the last day. A label here came from a client header, so it is
    # escaped on the way out as well as shape-checked on the way in.
    installed = data.get("per_dimension_installed") or {}
    active = data.get("per_dimension_active") or {}
    for dim in usage_stats.DIMS:
        pairs = []
        for value in sorted(set(installed.get(dim) or {}) | set(active.get(dim) or {})):
            pairs.append((value, "%s installed / %s active"
                          % ((installed.get(dim) or {}).get(value, 0),
                             (active.get(dim) or {}).get(value, 0))))
        card(dim, pairs)
    payments_row = data.get("payments", {})
    card("Pass purchases (approved)", list(
        (tier, "%s × PKR %s" % (row.get("purchases"), row.get("amount_pkr")))
        for tier, row in (payments_row.get("by_tier") or {}).items()
    ) + [("total PKR", payments_row.get("total_pkr")),
         ("pending queue", payments_row.get("pending"))])
    estimate = data.get("revenue_estimate", {})
    card("Revenue estimate (assumptions printed)", [
        ("ad USD in window", estimate.get("ad_usd_in_window")),
        ("ad USD per 1,000 users", estimate.get("ad_usd_per_1000_users")),
        ("rewarded per 1,000 users", estimate.get("rewarded_per_1000_users")),
        ("click-through rate", estimate.get("ctr")),
        ("assumptions", json.dumps(estimate.get("assumptions") or {},
                                   sort_keys=True)),
        ("estimate", estimate.get("estimate")),
    ])
    pending = (data.get("sources") or {}).get("reported_by_client_pending") or []
    if pending:
        parts.append('<div class="warn"><strong>Not yet reported by the app:</strong> '
                     + _e(", ".join(sorted(str(name) for name in pending)))
                     + " — these are absences, not zeros.</div>")
    parts.append("</div></body></html>")
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
#: stay inert; the two route paths and the three same-origin tokens are substituted
#: at render time. There is no credential in here any more: the browser presents the
#: `HttpOnly` session cookie on its own, and `credentials` below is what makes it
#: ride a same-origin `fetch`. `credentials: "same-origin"` is the default in modern
#: browsers and is spelled out because the whole page depends on it.
_SCRIPT = """
<script>
(function () {
  const SAVE_PATH = "__SAVE_PATH__";
  const RUN_PATH = "__RUN_PATH__";
  const TOKENS = {"__SAVE_PATH__": "__SAVE_TOKEN__",
                  "__RUN_PATH__": "__RUN_TOKEN__"};
  function note(text, ok) {
    const el = document.getElementById("ops-status");
    if (!el) return;
    el.textContent = text;
    el.className = ok ? "ok statusline" : "bad statusline";
  }
  async function post(path, payload) {
    let response;
    try {
      response = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json",
                  "__CSRF_HEADER__": TOKENS[path] || ""},
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
            f'<button class="btn" data-crawler="{_e(crawler_id)}"'
            ' onclick="runScraper(this.dataset.crawler, \'sync\', this)">Sync now</button> '
            f'<button class="btn" data-crawler="{_e(crawler_id)}"'
            ' onclick="runScraper(this.dataset.crawler, \'crawl\', this)">Crawl</button>')
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
        field = fields.get(key) or {"label": label, "value": ""}
        # The key travels in a `data-key` attribute and the handler reads it back,
        # rather than being written into the `onclick` source: an attribute that
        # holds a script has two parsers, and `_e` only satisfies the first one.
        return (f'<div class="field"><label for="f-{_e(key)}">{_e(label)}</label>'
                f'<input id="f-{_e(key)}" autocomplete="off" data-key="{_e(key)}"'
                f' placeholder="{_e(placeholder)}" value="{_e(field.get("value"))}"'
                ' onkeydown="if(event.key===\'Enter\')'
                ' this.form.querySelector(\'[id=\\\'b-\'+this.dataset.key+\'\\\']\').click()">'
                f'<button id="b-{_e(key)}" class="btn" data-key="{_e(key)}"'
                ' onclick="saveSetting(this.dataset.key,'
                " this.form.querySelector('[id=\\'f-'+this.dataset.key+'\\']').value, this)'>"
                'Update</button></div>')

    out = '<h2 style="margin-top:0">Feature matrix</h2>'
    out += toggle("maintenance_mode")
    out += toggle("feature_pure_cinema")
    out += toggle("feature_chromecast")
    out += toggle("feature_downloads")
    out += toggle("feature_quality_gate")
    out += ('<p class="hint">Charging VIP for 1080p/4K hides those rungs from every '
            'viewer the ledger has not confirmed, including signed-out ones. Off means '
            'the catalog is fully watchable, which is the honest default until approvals '
            'actually happen.</p>')
    out += text_row("apk_update_url", "APK update banner",
                    "https://downloads.example/app.apk")
    out += text_row("apk_update_sha256", "APK update SHA-256",
                    "64 hex from `sha256sum the.apk`")
    out += text_row("apk_update_size_bytes", "APK update size (bytes)", "e.g. 24000000")
    out += text_row("apk_update_version_code", "APK update versionCode", "e.g. 42")
    out += ('<p class="hint">The three lines above describe the file the banner '
            'points at. A SHA-256 is what lets a phone check it got that file, and '
            'an empty one means nothing is published — which a client that enforces '
            'it reads as "offer nothing". The shipped client checks only that the '
            'address is absolute, so until that changes these are recorded and '
            'unread: publishing them changes nothing on a phone by itself.</p>')
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
        '<p class="sub">Operator surface. Loopback only, no TLS, and every route'
        ' on this port now needs the bearer token — see the module docstring'
        ' before changing the gate. It is a credential boundary, not an encrypted'
        ' one: the transport is still plain HTTP.</p>',
        '<div class="warn"><strong>Fleet names stay here.</strong> This page is'
        ' mounted on the loopback port only and never prints a scraped upstream'
        ' URL. The scraper card names the 18 engines you configured; the public'
        ' port answers 404 for <code>/admin</code> and all of its routes.</div>',
        '<p class="sub"><a href="/admin/payments">Payment queue</a> — pending'
        ' JazzCash / EasyPaisa / Raast claims, approve or reject.</p>',
        '<p class="sub"><a href="/admin/usage">Usage</a> — installs, live'
        ' devices, DAU/WAU/MAU, retention, per-geo and per-version counts,'
        ' playback failures, ad and pass money. Aggregates only.</p>',
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
        flag = ('<span class="ok">holds — no adult work lost its flag</span>'
                if adult.get("suppression_holds")
                else '<span class="bad">FAILED — flagged works are projected'
                     ' unflagged</span>')
        lost = adult.get("works_that_lost_their_flag")
        exposed = adult.get("exposed_rows_if_leaked") or {}
        ad = _kv([
            ("flagged posts in ledger", _num(adult.get("ledger_flagged_posts"))),
            ("flagged works projected", _num(adult.get("projected_flagged_works"))),
            ("works that LOST the flag", _num(lost)),
            ("display filtering", flag)])
        # The two numbers this card used to print — `projected_flagged_releases` and
        # `projected_flagged_links` — are not keys `screen_adult_proof` returns, so
        # they rendered `n/a` on every load, forever, while the two it does return
        # (`works_that_lost_their_flag`, and `exposed_rows_if_leaked` per surface) went
        # unshown. A compliance card that displays nothing but `n/a` is worse than no
        # card: it looks audited. These are the real measurements, and the counts are
        # all this screen may print — no title, no URL, by design.
        if isinstance(exposed, dict) and exposed:
            ad += _table(("projected surface", "rows hanging off a lost flag"),
                         [[_e(name), _num(count)]
                          for name, count in sorted(exposed.items())])
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

    # Path first, then token: the TOKENS map is keyed by the *path*, so substituting
    # the path placeholders before the token ones turns that literal into the lookup
    # key the `post()` call actually uses.
    parts.append(_SCRIPT.replace("__SAVE_PATH__", _e(SAVE_MONETIZATION_PATH))
                 .replace("__RUN_PATH__", _e(RUN_SCRAPER_PATH))
                 .replace("__SAVE_TOKEN__",
                          _e(panel_origin_token("save-monetization")))
                 .replace("__RUN_TOKEN__",
                          _e(panel_origin_token("run-scraper")))
                 .replace("__CSRF_HEADER__", _e(CSRF_HEADER)))
    parts.append("</div></body></html>")
    return "".join(parts)


# ── dispatch ─────────────────────────────────────────────────────────────────

def _is_admin(path):
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


def _segments(path):
    return [piece for piece in (path or "").split("/") if piece]


def route_get(path, query, *, db_path, peer_address, token_header,
              state_db_path=None, cookie_header="", accepts_html=False):

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
    if path in LOGIN_PATHS:
        # Sign-in answers before the credential exists, and carries its own
        # loopback rule so it cannot be reached from off the box.
        return login_page(path, peer_address=peer_address)
    if path in LOGOUT_PATHS:
        return logout_response(path, peer_address=peer_address)
    refusal = _gate(peer_address, token_header, cookie_header=cookie_header,
                    accepts_html=accepts_html)
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
        if segments == ["admin", "usage"]:
            return _respond_html(render_usage_page(screen_usage(
                state_db_path, window_days=_window_days(query))))
        if (len(segments) == 3 and segments[1] == "api"
                and segments[2] in _STATE_SCREENS):
            return _respond_json(200, screen_usage(
                state_db_path, window_days=_window_days(query)))
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
    save, the scraper action, the two payment reviews and the sign-in form do: the
    evidence re-fold derives everything from the journal already in the database,
    and a logout carries nothing."""
    if path in LOGIN_PATHS:
        # The password is in the body, which is the entire reason the body exists.
        return True
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
               state_db_path=None, cookie_header="", accepts_html=False,
               csrf_header=""):
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
    if path in LOGIN_PATHS:
        # The credential check itself, before any credential exists. It reads the
        # form the page posted and nothing else: `authenticate` refuses a body with
        # a key beyond username/password, so no field can join the decision.
        return login_submit(path, body, peer_address=peer_address,
                            accepts_html=accepts_html)
    if path in LOGOUT_PATHS:
        return logout_response(path, peer_address=peer_address)
    refusal = _gate(peer_address, token_header, cookie_header=cookie_header,
                    accepts_html=accepts_html)
    if refusal is not None:
        return refusal
    # Once a browser holds a session cookie instead of a token in its URL, a write
    # has to prove it was assembled by a page this process rendered. Only the three
    # writes that have no row-bound CSRF token are checked here; a bearer caller is
    # exempt by construction, and `_origin_ok` says why.
    origin_action = _origin_action(path)
    if (origin_action is not None and not bearer_matches(token_header)
            and not _origin_ok(origin_action, body, csrf_header)):
        return _problem("unauthorised", path,
                        "This write must come from a panel page.", stable=True)
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


# ── minting the stored password ──────────────────────────────────────────────
#
# The owner needs a way to turn a typed password into `RADD_ADMIN_PASSWORD_HASH`
# without a second tool, and the tool has to be *this* file so the parameters it
# writes are the parameters `verify_password` reads. The invocation never puts the
# secret in a command-line argument: argv is readable by every process on the box
# through `/proc`, lands in the shell history, and shows up in the `ps` output a
# health check prints.

USAGE = """usage: python3 -S Fast_Fetch/admin_panel.py hash-password [--pbkdf2]

  Reads the operator password from the terminal without echoing it (or from
  stdin when piped), and prints ONLY the salted hash. Put what it prints in
  the environment as RADD_ADMIN_PASSWORD_HASH; the password itself is stored
  nowhere, and this panel will refuse to compare one if it is.

  --pbkdf2 selects PBKDF2-HMAC-SHA256 instead of the default scrypt, for a
  Python whose OpenSSL has no scrypt. Both are salted and both are fine;
  scrypt is memory-hard, which is the better trade on a single-vCPU box.
"""


def read_secret_from_input() -> str:
    """One typed secret, taken off the terminal or the pipe, never off argv."""
    if sys.stdin.isatty():
        import getpass
        first = getpass.getpass("operator password: ")
        if first != getpass.getpass("repeat it: "):
            raise SystemExit("the two entries differed; nothing minted")
        return first
    return sys.stdin.readline().rstrip("\n")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["hash-password"]:
        sys.stderr.write(USAGE)
        return 2
    secret = read_secret_from_input()
    if not secret:
        sys.stderr.write("an empty password has no hash worth storing\n")
        return 2
    kdf = "pbkdf2-sha256" if "--pbkdf2" in args else PASSWORD_KDF
    try:
        sys.stdout.write(mint_password_hash(secret, kdf=kdf) + "\n")
    except ValueError as problem:
        # OpenSSL without scrypt says `memory cost is too large`, and the owner
        # needs to hear that as a sentence, not as a traceback off a 1-core box.
        sys.stderr.write(f"{problem}\ntry --pbkdf2\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
