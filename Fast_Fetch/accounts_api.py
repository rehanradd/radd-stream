#!/usr/bin/env python3
"""accounts_api.py — the HTTP edge for optional sync accounts.

`accounts.py` owns the data: accounts, favorites, progress, the brute-force
limiter. This module owns the wire: header parsing, status codes, JSON shape,
and the one thing `accounts.py` cannot do by itself — turn a minted `work_ref`
back into a work key without ever letting a raw work key cross the boundary in
either direction.

═══════════════════════════════════════════════════════════════════════════════
WHAT THIS IS NOT. Read it before "hardening" anything.
───────────────────────────────────────────────────────────────────────────────
* **Not a login.** There is no password, no email, no session cookie, no JWT.
  A sync account is one 256-bit key the app minted or we minted once; showing
  it *is* authenticating. That is deliberate: the mandate is an *optional*
  cross-device sync of favorites and resume points, not an identity system,
  and every identity mechanism added here would be data we have to protect and
  a way for a user to be locked out of their own list.
* **Not confidential in transit.** The deployed host is plain HTTP with no TLS
  (see ORACLE_DEPLOYMENT.md; ``http://92.4.95.252/``). The sync key in the
  ``Authorization`` header therefore travels in the clear, and anyone on the
  path between the app and this VM can read it and *become* that account —
  its favorites and resume points, which is all an account holds. No header
  trick, hash or token format fixes that; only TLS does, and this VM has no
  certificate. The app must warn the user once, at account creation, and the
  operator must not put anything sensitive behind an account. This paragraph
  is the honest state of the feature, not a TODO to delete.
* **Not an access-control system for the catalog.** Everything a signed-out
  client may see, a signed-in client may see. An account changes what is
  *stored* for you, never what you are *allowed to read*.

PROVENANCE (absolute; `redact.py` is the vocabulary owner):
  A `cat_works.work_key` is built from scraped data and can contain a site
  name (`series:… katmoviehd …`), so it is never sent to a client and never
  accepted from one. Out: every row goes through `accounts.to_public(row, mint)`
  with `mint = lambda k: redact.mint_text(k, secret)`, which replaces the key
  with `work_ref` (`accounts.PUBLIC_REF_KEY`, the same name `api_v2` uses on a
  catalog item) — reversible only with the install secret. In: a client echoes
  a `work_ref` back and `redact.parse_text` recovers the key, rejecting anything
  it did not mint itself. Nothing else in this module can name a work.

ADULT SUPPRESSION:
  `accounts.py` re-checks visibility against the catalog before it stores or
  returns anything (`work_is_visible`), so an adult `work_key` presented as a
  minted ref is refused exactly the way a nonexistent one is. This edge does
  not get to decide that and does not try.

CONTRACT (mirrors `admin_panel.py` so mounting is identical):
  `route_get(path, query, *, db_path, catalog_path, secret, headers)` and
  `route_post(path, body, *, …)` return ``(status, content_type, body_bytes)``
  when they answered and ``None`` when the path is not theirs. No sockets, no
  handler object, so every route here is testable as a function call.

Stdlib only.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing

import accounts
import api_v2
import payments
import redact
import usage_stats

PREFIX = "/api/v2/account"
JSON = "application/json; charset=utf-8"
PROBLEM = "application/problem+json; charset=utf-8"

#: The only keys a payment submission may carry. `plan` selects the price, `method`
#: selects the transaction-id shape, `tid` is the claim itself. Anything else —
#: above all `amount_pkr`/`amount`, the exact key a caller would send to price its
#: own purchase — is a 400 before the ledger is opened, so a client can never be
#: the one that decides what VIP costs.
_PAYMENT_KEYS = frozenset({"plan", "method", "tid"})

#: The account surface is tiny and every call is cheap, so the edge keeps one
#: limiter for the whole process — the same object `accounts.py` falls back to,
#: made explicit here so a mount that forgets to pass one still throttles.
LIMITER = accounts.attempt_tracker

#: §16.5's own read is `api_v2.read_body`; nothing here re-parses a body, so
#: there is exactly one body-size ceiling on this server.
DEFAULT_N = 200
MAX_N = 1000

#: How long a `GET /api/v2/account/vip-pass` answer stays good. A pass has no
#: revocation list, so this is the only knob that limits the damage of one that
#: leaked — through an access log, a history entry, or a screen recording of a
#: share sheet. Six hours covers an evening of downloading on one device, which is
#: the whole use case, and it is still far shorter than the month a payer bought.
#: The app is expected to re-ask when it refreshes its entitlement.
VIP_PASS_TTL_SECONDS = 6 * 3600

#: `accounts.py` codes mapped onto §16.4's closed vocabulary, because this edge
#: publishes the same problem bodies as the rest of v2 and may not invent codes:
#: `/manifest` publishes `error_codes`, and a code nobody declared is a client
#: that branches on a string no other route can ever answer. The four account
#: codes with no §16.4 equivalent (`dependency_unavailable`, `invalid_progress`,
#: `weak_sync_key`, `account_full`) collapse into the declared one whose status
#: they already carry, and `detail` — not `code` — says which.
_STATUS = {
    "not_found": "not_found",
    "rate_limited": "rate_limited",
    "dependency_unavailable": "unavailable",
    "invalid_progress": "invalid_params",
    "weak_sync_key": "invalid_params",
    "account_full": "forbidden",
    "account_error": "invalid_params",
}


def _problem(code: str, status: int, detail: str = "", instance: str = "",
             *, retry_after: int | None = None) -> tuple:
    """The v2 refusal shape (`api_v2.problem`), built rather than written: same
    `type` URI, same closed code list, same `_flag_value_deny` on the detail, so
    an account refusal is indistinguishable in shape from a catalog one.
    Anything undeclared answers `not_found`, exactly as `api_v2` does."""
    resolved = api_v2._CODE_ALIASES.get(str(code or ""), _STATUS.get(str(code or ""), str(code or "")))
    if resolved not in api_v2.PROBLEM_CODES or api_v2._FLAG_KEY_RE.search(resolved):
        resolved, status = "not_found", 404
    status, title = api_v2.PROBLEM_CODES[resolved]
    body = {
        "type": f"/api/v2/problems/{resolved}",
        "title": title,
        "status": status,
        "instance": instance,
        "code": resolved,
        "request_id": api_v2.request_id(),
    }
    if detail:
        body["detail"] = api_v2._flag_value_deny(redact.scrub_text(detail))
    if retry_after is not None:
        body["retry_after"] = max(1, int(retry_after))
    return (status, PROBLEM, json.dumps(body, separators=(",", ":")).encode("utf-8"))


def _respond(payload: dict, status: int = 200) -> tuple:
    return (status, JSON, json.dumps(payload, separators=(",", ":"),
                                     sort_keys=True).encode("utf-8"))


class _Minter:
    """One request's secret, carried as a value instead of a global.

    This server answers requests on threads, so a module-level secret bound at
    dispatch time would be read by another request mid-flight; and minting with
    the wrong secret is silent — the handle simply stops parsing later. Passing
    the callable down makes both impossible, and it is the same trick
    `accounts.to_public` uses to make "forgot to mint" raise instead of leak."""

    def __init__(self, secret: str):
        self.secret = str(secret or "")

    def __call__(self, value) -> str:
        return redact.mint_text(str(value), self.secret)

    def work_key(self, ref):
        """Inverse of `__call__`: our own handle back to a work key, `None` otherwise.

        A client that sends a raw `series:… ` key instead of a handle gets the
        same answer as one sending garbage, which is a 400 from the caller.
        Nothing here echoes the input, so the refusal teaches nothing about the
        format."""
        if not isinstance(ref, str) or not ref:
            return None
        return redact.parse_text(ref, self.secret)


def _bearer(headers) -> str:
    """The sync key out of the request headers, `""` when absent.

    `headers` is any mapping with case-insensitive `.get` (an
    `http.client.HTTPMessage` from the server, a plain dict in a test)."""
    raw = str((headers or {}).get("Authorization", "") or "")
    parts = raw.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def _segments(path: str) -> list[str]:
    return [s for s in str(path or "").split("/") if s]


def is_account(path: str) -> bool:
    return path == PREFIX or path.startswith(PREFIX + "/")


def _number(payload, name, default=0.0) -> float:
    """A JSON number we can hand to the store, or the default. A caller that
    sends `"position_seconds": "abc"` gets 0 and a 201, not a 500 quoting its
    own bad value back — the position is the client's business, ours is to
    store a number."""
    try:
        return float(payload.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _limit(query, name="limit", default=DEFAULT_N) -> int:
    try:
        raw = int((query or {}).get(name, [default])[0])
    except (TypeError, ValueError, IndexError, AttributeError):
        return default
    return max(1, min(raw, MAX_N))


_SCHEMA_READY = False


def state_db():
    """The user-state path, with its tables made sure of once per process.

    `accounts.ensure_schema` is `CREATE … IF NOT EXISTS`, so two first requests
    on two threads racing through here is harmless — and cheaper than the
    alternative of every route catching "no such table: user_accounts" or
    `viewer.py` learning that this module owns a second database file."""
    global _SCHEMA_READY
    path = accounts.default_db_path()
    if not _SCHEMA_READY:
        with closing(accounts.connect(path)) as conn:
            accounts.ensure_schema(conn)
        _SCHEMA_READY = True
    return path


def _catalog_handle(catalog_path):
    """A read-only catalog connection for this request, or `None` if none can open.

    `None` is not "skip the adult check": `accounts._require_visible` answers an
    unreadable oracle with `CatalogUnreachable` (503), and that is the honest
    order of mistakes. A deployment pointed at the wrong file must not be able to
    store favorites for works it cannot see — silently waving the visibility rule
    through is worse than a 503, and it is also how a rebuild in progress should
    read: not ready, try later.

    The caller owns this connection and closes it in a `finally`. Handing
    `accounts` the *path* instead would be one `sqlite3.connect` per row for every
    list, which is the thing `work_is_visible`'s own docstring warns against."""
    if not catalog_path:
        return None
    try:
        return accounts._open_catalog_read_only(catalog_path)
    except sqlite3.Error:
        return None


def _account_view(created: dict) -> dict:
    """`create_account` returns our row number; the client never sees it (§3)."""
    return {"created_at": created["created_at"], "created": bool(created["created"])}


def _note_usage(db_path, key, headers, count_request=True):
    """Mark the calling device live, from the credential and headers already here.

    The account surface is the only place a caller has identified itself, so it
    is where the operator's install/device counters get earned — no new route,
    no new bucket, nothing a client has to opt into. The device bucket is the
    client's `X-Install-Id` when the app lane sends one and the salted digest of
    the sync key otherwise (`usage_stats.record_seen`), so a revoked key simply
    stops being seen; the key itself is never stored and no IP is read.

    A device row appears only for a key this server actually issued
    (`accounts.key_is_known`, read-only and never chargeable against a real
    viewer's lockout budget). Without that gate a stranger could grow the install
    table one row per guess, and a counter that anyone can inflate is not a
    counter — so an unknown credential raises `account_request` at most and marks
    no device. `count_request` is False for an unauthenticated GET for the same
    reason: a probe with no key at all should buy no write whatsoever.

    Analytics is never allowed to break a user's request, so this swallows
    everything and returns quietly: a favorite that failed to save because a
    counter table was locked is a worse outcome than a missing count.
    """
    try:
        return usage_stats.record_seen(
            db_path,
            install_id=usage_stats.install_id_from_headers(headers),
            credential=key, headers=headers, count_request=count_request,
            credential_is_known=bool(key) and accounts.key_is_known(db_path, key))
    except Exception:                                # noqa: BLE001 — counting never fails a request
        return None


def _note_client_usage(db_path, payload, key, headers):
    """Fold the optional `usage` block of an existing POST into the counters.

    Rides on `POST /api/v2/account/progress`, which already exists, already
    authenticates and already accepts a JSON object. Ads, coins, crashes and
    buffering happen on the phone; this is the only way their totals reach a
    server that is not permitted to open a new public route for them.
    """
    try:
        return usage_stats.record_client_usage(db_path, payload, headers=headers)
    except Exception:                                # noqa: BLE001 — counting never fails a request
        return {}


# ── refusal wrapping ─────────────────────────────────────────────────────────

def _refused(error: Exception, path: str) -> tuple:
    if isinstance(error, accounts.AccountError):
        retry = (getattr(error, "retry_after", 0) or accounts.DEFAULT_LOCK_SECONDS
                 if isinstance(error, accounts.Locked) else None)
        return _problem(getattr(error, "code", "invalid_params"),
                        int(getattr(error, "status", 400) or 400),
                        getattr(error, "detail", ""), path, retry_after=retry)
    return _problem("internal", 500, "the account service failed", path)


# ── routes ───────────────────────────────────────────────────────────────────

def _target(payload, mint, path):
    """The work one write is about, or the refusal that says it is not ours.

    Both halves come back from here because every write needs the same two
    sentences: "that is not a handle we minted" (400, and the input is never
    quoted) and nothing else. A raw `work_key` in a request body is a 400 for
    the same reason a forged signature is."""
    work = mint.work_key(payload.get("work_ref"))
    if work is None:
        return None, _problem("invalid_params", 400,
                              "work_ref is not a handle this service minted", path)
    return work, None


def route_get(path, query, *, db_path, catalog_path, secret, headers) -> tuple | None:
    """GET on the account surface. `None` means "not mine", fall through."""
    if not is_account(path):
        return None
    mint = _Minter(secret)
    key = _bearer(headers)
    tail = _segments(path)[len(_segments(PREFIX)):]
    catalog = None
    _note_usage(db_path, key, headers, count_request=bool(key))
    try:
        catalog = _catalog_handle(catalog_path)
        if tail == []:
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            return _respond({"account": {
                "created_at": account["created_at"],
                "last_seen_at": account["last_seen_at"],
            }})
        if tail == ["favorites"]:
            accounts.authenticate(db_path, key, tracker=LIMITER)
            rows = accounts.list_favorites(db_path, key, limit=_limit(query),
                                           catalog=catalog, tracker=LIMITER)
            return _respond({"favorites": [accounts.to_public(r, mint) for r in rows],
                             "count": len(rows)})
        if tail == ["progress"]:
            accounts.authenticate(db_path, key, tracker=LIMITER)
            rows = accounts.list_progress(db_path, key, limit=_limit(query),
                                          catalog=catalog, tracker=LIMITER)
            return _respond({"progress": [accounts.to_public(r, mint) for r in rows],
                             "count": len(rows)})
        if tail == ["entitlement"]:
            # The one read that answers "am I VIP yet?". A caller with no key at
            # all gets 401 rather than the favorites routes' 404: this is not a
            # lookup that can miss, it is a question only an account can ask.
            if not key:
                return _problem("unauthorised", 401,
                                "a bearer sync key is required", path)
            earned = payments.entitlement(db_path, key, tracker=LIMITER)
            return _respond({"entitlement": redact.project(
                earned, "account_entitlement")})
        if tail == ["vip-pass"]:
            # Mint the capability a *URL* can carry. `/api/v1/download` shortens a
            # free viewer's link and lets a member straight through, and it decides
            # from either an `Authorization` header or a `?vip=` pass — but the
            # player and the system download manager follow that redirect outside
            # this process, so a header cannot ride along. The pass is therefore the
            # only way an entitled account can reach the bypass it paid for.
            #
            # What it is not: an account. It carries one expiry instant and no user
            # id, price or payment detail (`redact.mint_vip_pass`), so a leaked pass
            # reveals nothing about a person and cannot be pointed at one. What that
            # costs is honesty: there is no revocation list, so the window stays
            # short and the app is expected to ask again.
            if not key:
                return _problem("unauthorised", 401,
                                "a bearer sync key is required", path)
            earned = payments.entitlement(db_path, key, tracker=LIMITER)
            moment = time.time()
            membership_end = float(earned.get("vip_until") or 0.0)
            if not earned.get("vip"):
                # 402, not 403: §16.4 already declares "a licence is required before
                # this can be played", and this is that sentence about a pass.
                return _problem("licence_required", 402,
                                "this account has no live membership", path)
            expires_at = min(moment + VIP_PASS_TTL_SECONDS, membership_end)
            if expires_at <= moment:
                # Lost the membership between the check and here. Same answer as
                # having none, never a pass that parses as already expired.
                return _problem("licence_expired", 410,
                                "this membership has lapsed", path)
            return _respond({
                "pass": redact.mint_vip_pass(expires_at, secret),
                "expires_at": expires_at,
                "membership_until": membership_end,
            })
        return _problem("not_found", 404, "no such account route", path)
    except Exception as error:                      # noqa: BLE001 — the edge answers, it never re-raises
        return _refused(error, path)
    finally:
        if catalog is not None:
            catalog.close()


def route_post(path, body, *, db_path, catalog_path, secret, headers) -> tuple | None:
    """POST on the account surface. `body` is the already-parsed JSON object,
    read by `api_v2.read_body` so one ceiling covers the whole server."""
    if not is_account(path):
        return None
    mint = _Minter(secret)
    payload = body if isinstance(body, dict) else {}
    tail = _segments(path)[len(_segments(PREFIX)):]
    key = _bearer(headers)
    # Creation is the one unauthenticated call: it earns a request count and no
    # device, because there is nothing to identify it by.
    _note_usage(db_path, key, headers, count_request=True)
    catalog = None
    try:
        catalog = _catalog_handle(catalog_path)
        if tail == []:
            # Creation is the one unauthenticated call, and it authenticates
            # nothing afterwards: an existing key re-presented here answers
            # `created: False` without ever returning a plaintext second time.
            created = accounts.create_account(db_path, key=payload.get("sync_key"))
            out = _account_view(created)
            if created["sync_key"]:
                out["sync_key"] = created["sync_key"]
            return _respond({"account": out}, status=201 if created["created"] else 200)
        if not key:
            return _problem("unauthorised", 401, "a bearer sync key is required", path)
        if tail == ["revoke"]:
            accounts.revoke_account(db_path, key, tracker=LIMITER)
            return _respond({"revoked": True})
        if tail == ["favorites"]:
            work, refusal = _target(payload, mint, path)
            if refusal:
                return refusal
            row = accounts.put_favorite(db_path, key, work,
                                        season_number=payload.get("season_number"),
                                        episode_number=payload.get("episode_number"),
                                        catalog=catalog,
                                        tracker=LIMITER)
            return _respond({"favorite": accounts.to_public(row, mint)}, status=201)
        if tail == ["favorites", "remove"]:
            work, refusal = _target(payload, mint, path)
            if refusal:
                return refusal
            gone = accounts.delete_favorite(db_path, key, work,
                                            season_number=payload.get("season_number"),
                                            episode_number=payload.get("episode_number"),
                                            catalog=catalog,
                                            tracker=LIMITER)
            return _respond({"removed": bool(gone)})
        if tail == ["progress"]:
            work, refusal = _target(payload, mint, path)
            if refusal:
                return refusal
            row = accounts.put_progress(db_path, key, work,
                                        position_seconds=_number(payload, "position_seconds"),
                                        duration_seconds=_number(payload, "duration_seconds"),
                                        season_number=payload.get("season_number"),
                                        episode_number=payload.get("episode_number"),
                                        client_updated_at=_number(payload, "client_updated_at", 0.0) or None,
                                        catalog=catalog,
                                        tracker=LIMITER)
            _note_client_usage(db_path, payload, key, headers)
            return _respond({"progress": accounts.to_public(row, mint)}, status=201)
        if tail == ["progress", "remove"]:
            work, refusal = _target(payload, mint, path)
            if refusal:
                return refusal
            gone = accounts.delete_progress(db_path, key, work,
                                            season_number=payload.get("season_number"),
                                            episode_number=payload.get("episode_number"),
                                            tracker=LIMITER)
            return _respond({"removed": bool(gone)})
        if tail == ["payment"]:
            # A claim, not an entitlement: `payments.submit_payment` stores what
            # the operator's own price table says the plan costs, and only a
            # human on the loopback panel can turn it into VIP.
            extra = sorted(str(name) for name in payload if name not in _PAYMENT_KEYS)
            if extra:
                # Named once, without the offending key spelled back: a body that
                # carried `amount_pkr` is either a buggy client or someone testing
                # whether this server prices itself, and neither gets a lesson.
                return _problem("invalid_params", 400,
                                "a payment submission accepts plan, method and tid only",
                                path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            filed = payments.submit_payment(
                db_path, account["account_id"],
                plan=payload.get("plan"), method=payload.get("method"),
                tid=payload.get("tid"), catalog_path=catalog_path)
            return _respond({"payment": redact.project(filed, "account_payment")},
                            status=201)
        return _problem("not_found", 404, "no such account route", path)
    except Exception as error:                      # noqa: BLE001 — the edge answers, it never re-raises
        return _refused(error, path)
    finally:
        if catalog is not None:
            catalog.close()


def _selfcheck() -> int:
    """`python3 -S Fast_Fetch/accounts_api.py` — no port, temp DB, real round trip."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as work:
        db = Path(work) / "user_state.db"
        catalog = Path(work) / "cat.db"
        secret = "unit-secret"
        conn = sqlite3.connect(str(catalog))
        conn.execute("CREATE TABLE cat_works (work_key TEXT, is_18_plus INTEGER DEFAULT 0)")
        conn.execute("INSERT INTO cat_works VALUES ('movie:in:1000:sample', 0)")
        conn.execute("INSERT INTO cat_works VALUES ('movie:in:1001:adult katmoviehd title', 1)")
        conn.commit()
        conn.close()
        headers = {}
        made = route_post(PREFIX, {}, db_path=db, catalog_path=catalog,
                          secret=secret, headers=headers)
        assert made[0] == 201, made
        key = json.loads(made[2])["account"]["sync_key"]
        auth = {"Authorization": f"Bearer {key}"}
        ref = redact.mint_text("movie:in:1000:sample", secret)
        added = route_post(f"{PREFIX}/favorites", {"work_ref": ref}, db_path=db,
                           catalog_path=catalog, secret=secret, headers=auth)
        assert added[0] == 201 and "work_key" not in added[2].decode(), added
        adult = route_post(f"{PREFIX}/favorites",
                           {"work_ref": redact.mint_text(
                               "movie:in:1001:adult katmoviehd title", secret)},
                           db_path=db, catalog_path=catalog, secret=secret, headers=auth)
        assert adult[0] == 404, adult
        forged = route_post(f"{PREFIX}/favorites", {"work_ref": "AAA= raw"},
                            db_path=db, catalog_path=catalog, secret=secret, headers=auth)
        assert forged[0] == 400, forged
        listed = route_get(f"{PREFIX}/favorites", {}, db_path=db, catalog_path=catalog,
                           secret=secret, headers=auth)
        assert json.loads(listed[2])["count"] == 1, listed
        assert "katmoviehd" not in listed[2].decode()
        anon = route_get(PREFIX, {}, db_path=db, catalog_path=catalog,
                         secret=secret, headers={})
        assert anon[0] == 404, anon            # UnknownAccount: no key at all
        other = route_get("/api/v2/browse", {}, db_path=db, catalog_path=catalog,
                          secret=secret, headers={})
        assert other is None, other
        print("[.] accounts_api selfcheck OK — one favorite, adult and forged refs refused")
        return 0


if __name__ == "__main__":
    raise SystemExit(_selfcheck())
