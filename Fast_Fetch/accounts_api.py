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
* **Not a login — except in one direction added on purpose.** There is no
  password, no email, no session cookie, no JWT. A sync account is one 256-bit key
  the app minted or we minted once; showing it *is* authenticating. That is
  deliberate: the mandate is an *optional* cross-device sync of favorites and
  resume points, not an identity system, and every identity mechanism added here
  would be data we have to protect and a way for a user to be locked out of their
  own list.
  The two routes this release adds are the exception, and they are narrow:
  `POST /anonymous` turns a device id into an account with a three-day trial, and
  `POST /profile-link` attaches a name, a phone and a 4-digit PIN to an account the
  caller already holds the key for. Neither is a *login* — nothing in this module
  accepts a phone number plus a PIN as authority, the PIN is only ever checked
  against a profile that already exists, and a customer who forgets four digits
  cannot get their account back through any route here. If somebody later wants
  phone+PIN sign-in, that is a different feature with a different threat model
  (10^4 guesses against a national numbering plan, on a host with no TLS) and it
  must not be built by quietly removing the bearer requirement from these routes.
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
* **Not a wallet, and not a mint.** `/coins/*` is a wire over the wallet
  `engagement.py` already owns: a balance that is `SUM(delta)` over the append-only
  `coin_ledger`, a streak record that claims its day with one guarded `UPDATE`, and a
  pass ladder whose cost *and* expiry resolve through `engagement.resolve_ladder` —
  the same resolver that builds the price block the phone drew its buttons from.
  Nothing here stores a balance, names a price, or counts a cap; a second column,
  price list or constant for any of those is exactly the defect JOB B removed from the
  pricer, and an HTTP edge is where it would grow back.
  The corollary is what these routes refuse, and each refusal is a measured fact about
  this host rather than caution. `watch_time` is not creditable because elapsed viewing
  is not something this server observes: a stream is a *redirect* — the bytes leave from
  the source's own host — so a client reporting minutes is reporting them about itself.
  `rewarded_ad` is not creditable either, for the same reason one step on: the only
  completion signal on this box is `usage_stats`'s client-reported telemetry, which
  `engagement.py:20` calls analytics and not money, and no ad network calls *this*
  server back to say a video finished. `engagement.SERVER_SOURCES` is the ledger's own
  answer to both — a client claim mints nothing — so a route that relayed one would
  either be refused by `grant_coins` or would have to label the row `source="server"`,
  which is a lie in the one column whose whole job is who vouched. A daily login is the
  different kind of statement: a bearer-authenticated request *is* the observation, the
  grant is the streak ladder's own, and it lands once per civil day however often it is
  posted. That pair is also why no earning route may take an `amount`: "+10 coins" is
  `streak_day1_coins`, an operator setting, and a caller that could name its own reward
  is a caller that is setting its own price.
* **A wallet over plain HTTP.** `/api/v2/account*` is already in the nginx allow-list,
  so these routes are public the moment they exist, and this host serves HTTP with no
  TLS (root `AGENTS.md`, `ORACLE_DEPLOYMENT.md`). For catalog reads that is a settled
  decision — "the catalog is not private". A balance is not the catalog: the whole
  credential for moving real rupee-value is a 16-character sync key that crosses the
  path in the clear, next to the phone+PIN that already does. That is a hazard for the
  owner to accept or fix, not a reason to hide the route and not something this file can
  fix; it is recorded in `Fast_Fetch/checkpoints/` with the rest of the plaintext list.

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
import admin_panel
import api_v2
import engagement
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

#: The only keys an earning request may carry. `amount` and `minutes` are the two worth
#: naming: a client that can say how many coins it earned is a client setting its own
#: price, and a body `account_id` would be a wallet with no owner.
_EARN_KEYS = frozenset({"reason"})
#: The only key a redemption may carry. `media_id`/`work_ref` are refused with the rest:
#: what is sold here is a time-boxed pass over the catalog, never one title.
#: `idempotency_key` is the client's retry token for a spend (see
#: `_client_idempotency_key`): a retry with the same token spends nothing
#: twice, and the server namespaces it per account and operation before it
#: reaches the ledger.
_REDEEM_KEYS = frozenset({"plan", "idempotency_key"})
#: The only key a download-credit purchase may carry. The handle IS the title
#: here — a credit buys one direct download of one movie, so the download id
#: is the purchase, not a detail smuggled past the price.
_DOWNLOAD_KEYS = frozenset({"handle", "idempotency_key"})
#: The only key a share claim may carry: the minted handle of the shared work.
#: The server cannot observe a share, so the handle is the whole proof the
#: work exists and is ours.
_SHARE_KEYS = frozenset({"work_ref"})
#: The keys a movie request may carry: the title (required) and the viewer's
#: own note (optional). Nothing else — a request is a title, not a form.
_REQUEST_MOVIE_KEYS = frozenset({"title", "notes", "idempotency_key"})
#: The only key a theme purchase may carry: the theme id. The price is one
#: price for every theme, so the name is the purchase.
_REDEEM_THEME_KEYS = frozenset({"theme", "idempotency_key"})

#: A client-supplied idempotency key is a short opaque string: long enough
#: for a UUID, short enough that it cannot smuggle a payload into a ledger
#: column.
_IDEMPOTENCY_KEY_MAX = 128


def _client_idempotency_key(payload, account_id, operation, path):
    """The client's retry token, namespaced into the ledger's key space.

    Returns `(key, None)` — `key` is None when the client sent none, and
    the engine's own second-granularity default applies — or `(None, refusal)`
    for a malformed token. The namespacing is the load-bearing part:
    `spend_coins` dedupes on the key alone (UNIQUE, no account column), so a
    raw client string would let one account's key block — or free-ride —
    another account's spend. The server composes
    `client:{account}:{operation}:{token}`, and the token itself is only the
    retry marker. A token that arrives already namespaced is still only a
    token: the composition runs regardless, so a client cannot pick its own
    ledger key.
    """
    raw = payload.get("idempotency_key")
    if raw is None:
        return None, None
    if (not isinstance(raw, str) or not raw.strip()
            or len(raw) > _IDEMPOTENCY_KEY_MAX):
        return None, _problem(
            "invalid_params", 400,
            "an idempotency key is a short string", path)
    return (f"client:{int(account_id)}:{operation}:{raw.strip()}", None)
#: A title a viewer types is their own words, and a request that is a page of
#: text is not a request: 200 characters for the title, 500 for the note.
_REQUEST_TITLE_MAX = 200
_REQUEST_NOTES_MAX = 500

#: The one earnable `reason`, and what it does. Not a price: `daily_login` is the app's
#: name for claiming today in the streak ladder, so the size of the grant is
#: `engagement.resolve_streak_grants`'s business (an operator knob) and the day is
#: claimed by one guarded `UPDATE` inside `record_engagement_day`. A coin figure in this
#: file would be the second price list JOB B removed.
_EARN_DAILY_LOGIN = "daily_login"

#: What this edge refuses to credit, each with the sentence that says why. 403
#: (`forbidden`, "This action is not allowed") is the declared code that fits: the
#: caller is authenticated, its wallet is not short, and no edit of its request makes
#: the feature exist. Both of these are the brief's own earning rules, and both fail on
#: a measured fact about this host rather than on caution.
_REFUSED_EARN = {
    "rewarded_ad": (
        "a rewarded-ad credit needs the ad network's own completion callback and this "
        "server holds none: the only completion signal on this host is client-reported "
        "telemetry, which engagement.py calls analytics and not money"),
    "watch_time": (
        "watch-time credit needs playback this server observed, and it observes none: a "
        "stream is a redirect, so elapsed minutes are a client claim and a client claim "
        "mints no coin"),
}

#: Rewards this server will not sell, with the same 403 reasoning. `unlock_1080p` is not
#: laziness — see the two measured reasons in the sentence.
_REFUSED_REWARDS = {
    "unlock_1080p": (
        "a single-title quality unlock is not sold here. the pass this server signs "
        "carries one expiry and no scope, and quality is chosen by the player at "
        "playback time, so a coin spent on it would buy nothing the server enforces"),
}

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

#: §16.4's closed vocabulary, and the four account codes with no §16.4 equivalent
#: (`dependency_unavailable`, `invalid_progress`, `weak_sync_key`, `account_full`)
#: collapse into the declared one whose status they already carry, and `detail` —
#: not `code` — says which. `weak_pin` and `invalid_request` join them for the same
#: reason: a PIN that is four characters is a bad parameter, and `unauthorised`
#: (which `PINMismatch` carries) is already declared, so it needs no mapping and
#: answers 401 — the same answer a missing bearer key gets, which is the honest one:
#: a wrong PIN is a failed credential, not a forbidden action.
_STATUS = {
    "not_found": "not_found",
    "rate_limited": "rate_limited",
    "dependency_unavailable": "unavailable",
    "invalid_progress": "invalid_params",
    "weak_sync_key": "invalid_params",
    "weak_pin": "invalid_params",
    "invalid_request": "invalid_params",
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


def _trial_view(trial: dict) -> dict:
    """The same law as `_account_view`, one step further: `grant_or_resume_device_trial`
    hands back `account_id` and the wire does not carry it, because §3 makes our row
    numbers somebody else's join key.

    What it does publish is the clock — `trial_expires_at` and the remaining seconds —
    because the app has to show a countdown, and `vip_until` because a trial that a
    payment extended has to read as extended. `created` is the one bit that tells the
    app whether this response is the last time it will ever see `sync_key`: a resume
    carries `None` there, and no replay of the device id changes that (the reason is
    in `grant_or_resume_device_trial`: handing the key back on a client-chosen id
    would be a takeover for anyone who guessed one)."""
    return {"created": bool(trial["created"]),
            "reissued": bool(trial["reissued"]),
            "first_seen_at": trial["first_seen_at"],
            "trial_expires_at": trial["trial_expires_at"],
            "trial_seconds_remaining": trial["trial_seconds_remaining"],
            "vip_until": trial["vip_until"]}


def _profile_view(linked: dict) -> dict:
    """The caller's own three values back to them, and no digest with them.

    `name` and `phone` are what this request just submitted, to a caller that already
    proved it holds the account's sync key — the only place either may appear. The
    hash, the salt and the iteration count are not: a response that carried them
    would let a wire-tap on this plain-HTTP host try PINs offline at whatever speed
    the KDF allows, which is the exact thing `accounts._hash_pin` exists to prevent."""
    return {"linked": True,
            "name": linked["name"],
            "phone": linked["phone"],
            "bonus_granted": bool(linked["bonus_granted"]),
            "vip_until": linked["vip_until"]}


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


# ── the wallet's wire shape (the numbers all come from `engagement`) ──────────


def _settings(catalog):
    """The operator's `app_remote_config` row, or `{}` when there is no row to read.

    Read through `admin_panel`, which owns that table — a `SELECT` here would be a
    second mapping of one settings row, the defect JOB B removed from the pass ladder
    and the reason `resolve_ladder` is the only function that turns a row into prices.
    `{}` is not a failure: it resolves to the shipped ladder and the shipped streak
    grants, which is the same answer `payments.price_table` gives a deployment that has
    never saved a setting. The catalog handle is read-only, so nothing here can create
    the table — and a route that charges money has no business creating schema anyway.
    """
    if catalog is None:
        return {}
    try:
        values = admin_panel.monetization_values(catalog)
    except sqlite3.Error:
        return {}
    return values or {}


def _civil_zone(values):
    """The zone a streak day is counted in, and the hour it rolls over — the two
    `app_remote_config` knobs the streak owns, passed through unresolved so
    `engagement`'s own defaults apply to a blank or a bad paste. A stored row for this
    account wins over both whatever is sent here; `record_engagement_day` says so."""
    zone = str(values.get("streak_tz") or "").strip()
    return {"tz": zone or None,
            "day_boundary_hour": values.get("streak_day_boundary_hour")}


def _ledger_entry(row) -> dict:
    """One `coin_ledger` row, as the wallet owner shows it.

    `source` stays in, beside `reason`: a `refund` the server issued and a `refund` an
    operator typed are different events with the same reason, and an account is allowed
    to ask who vouched for its own credit. What never crosses is anything the ledger does
    not hold — `idempotency_key` is not even selected by `engagement.ledger`.

    `ref` is scrubbed on the way out, not because the write path is trusted to keep a
    site name or a URL out of it (`engagement.py` says a ref is never a title, and
    `admin_grant` lets an operator type one) but because this body leaves on the public
    port and a stored free-text column is exactly the thing §13 says to clean at the
    edge. `reason` and `source` are closed vocabularies, validated on write, so they
    pass through untouched."""
    ref = row["ref"]
    return {"id": int(row["id"]), "delta": int(row["delta"]),
            "reason": str(row["reason"]), "source": str(row["source"]),
            "ref": redact.scrub_text(ref) if ref else None,
            "created_at": float(row["created_at"] or 0.0)}


def _earn_view(day: dict) -> dict:
    """What a daily-login call answers. No `account_id` on the wire: §16.9 gives no
    client a server-side primary key to point at, and this caller has already proven
    the key that owns the row."""
    out = {"status": str(day["status"]),
           "current_streak": int(day["current_streak"]),
           "best_streak": int(day["best_streak"]),
           "day": str(day["bucket"]),
           "coins_granted": int(day["granted_coins"])}
    if day.get("pass"):
        # Only the Day-7 milestone carries one, and it is this account's own pass.
        out["pass"] = day["pass"]
        out["pass_expires_at"] = day.get("pass_expires_at")
    return out


def _redeem_view(redeemed: dict) -> dict:
    cost = int(redeemed["cost"])
    return {"reward": str(redeemed["plan"]), "cost": cost,
            "balance": int(redeemed["balance"]),
            "already_applied": bool(redeemed["already_applied"]),
            "expires_at": float(redeemed["expires_at"]),
            "pass": redeemed["pass"]}


def _download_view(credit: dict) -> dict:
    return {"token": credit["token"], "handle": str(credit["handle"]),
            "cost": int(credit["cost"]), "balance": int(credit["balance"]),
            "already_applied": bool(credit["already_applied"]),
            "expires_at": float(credit["expires_at"])}


def _share_view(share: dict) -> dict:
    return {"granted": bool(share["granted"]), "coins": int(share["coins"]),
            "balance": int(share["balance"])}


def _request_view(request: dict) -> dict:
    return {"id": request["id"], "title": str(request["title"]),
            "cost": int(request["cost"]), "balance": int(request["balance"]),
            "already_applied": bool(request["already_applied"])}


def _theme_view(theme: dict) -> dict:
    return {"theme": str(theme["theme"]), "cost": int(theme["cost"]),
            "balance": int(theme["balance"]),
            "already_applied": bool(theme["already_applied"]),
            "owned": [str(name) for name in theme["owned"]]}


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
        if tail == ["coins"]:
            # The wallet a caller may read is only its own, and the number is the same
            # `SUM(delta)` the spender checks before it debits — so a reply and a
            # refusal cannot disagree about what this account holds, because there is
            # no second balance to disagree with. One state connection for the branch:
            # `_borrow(path)` would open (and re-install schema) once per call.
            if not key:
                return _problem("unauthorised", 401,
                                "a bearer sync key is required", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            zone = _civil_zone(_settings(catalog))
            with closing(engagement.connect(db_path)) as wallet:
                return _respond({
                    "balance": engagement.coin_balance(wallet, account["account_id"]),
                    "rewarded_grants_today": engagement.rewarded_grants_today(
                        wallet, account["account_id"], tz=zone["tz"],
                        day_boundary_hour=zone["day_boundary_hour"]),
                    # `remote_view()` is the ledger's own published block, called rather
                    # than copied, so this cannot become a third statement of a cap. It
                    # answers the shipped numbers on purpose: `rewarded_daily_cap` is the
                    # knob `remote_view()`'s docstring still names as enforced from the
                    # constant, and a row-resolved cap here would be a number this
                    # server does not actually hold anyone to.
                    "caps": dict(engagement.remote_view()["wallet"])})
        if tail == ["coins", "history"]:
            # The account's own ledger rows, newest first, on the owner's bounded page.
            # `ref` comes along because a `ref` is a ladder tier or a streak day and
            # never a title — which is what makes a wallet history safe to publish at
            # all on a host that hides nothing else about a work.
            if not key:
                return _problem("unauthorised", 401,
                                "a bearer sync key is required", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            with closing(engagement.connect(db_path)) as wallet:
                entries = engagement.ledger(wallet, account["account_id"],
                                            limit=_limit(query, "limit", 20))
            return _respond({"entries": [_ledger_entry(row) for row in entries],
                             "count": len(entries)})
        if tail == ["coins", "caps"]:
            # What a phone needs before it is asked to earn or to spend: the ceilings
            # the ledger holds, the pass prices and the streak grants this server will
            # actually charge and pay.
            #
            # Every block is the owner's own function, called on the request. A number
            # restated here is a second number, and the two halves of the mirror law are
            # which of these are row-resolved: `["coins","earn"]` hands
            # `resolve_streak_grants(values)` to `record_engagement_day` and
            # `["coins","redeem"]` hands `resolve_ladder(values)` to `redeem_pass`, so
            # `streak` and `passes` follow the saved row because this file's own routes
            # enforce the row. `caps` is the shipped projection because
            # `_enforce_rewarded_cap` still reads `REWARDED_DAILY_CAP` rather than the
            # row: publishing the row's 3 while the ledger hands out 10 would make this
            # route the lie. Same reasoning, opposite resolution, and both belong to the
            # enforcement site rather than to this route.
            if not key:
                return _problem("unauthorised", 401,
                                "a bearer sync key is required", path)
            accounts.authenticate(db_path, key, tracker=LIMITER)
            values = _settings(catalog)
            return _respond({
                "caps": dict(engagement.remote_view()["wallet"]),
                "passes": engagement.passes_projection(
                    engagement.resolve_ladder(values)),
                "download": {"coins": engagement.resolve_download_credit(values)},
                "request": {"coins": engagement.resolve_request_movie_coins(values)},
                "themes": engagement.themes_projection(values),
                "streak": engagement.resolve_streak_grants(values)})
        if tail == ["coins", "themes"]:
            # What this account owns, and what a theme costs: the picker reads
            # both from one place, so a theme it shows as locked is one the
            # redeem route will actually sell, at the price the picker shows.
            if not key:
                return _problem("unauthorised", 401,
                                "a bearer <redacted> key is required", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            values = _settings(catalog)
            with closing(engagement.connect(db_path)) as wallet:
                owned = engagement.owned_themes(wallet, account["account_id"])
            return _respond({"themes": owned,
                             "prices": engagement.themes_projection(values)})
        return _problem("not_found", 404, "no such account route", path)
    except Exception as error:                      # noqa: BLE001 — the edge answers, it never re-raises
        return _refused(error, path)
    finally:
        if catalog is not None:
            catalog.close()


def route_post(path, body, *, db_path, catalog_path, secret, headers,
               client_ip=None) -> tuple | None:
    """POST on the account surface. `body` is the already-parsed JSON object,
    read by `api_v2.read_body` so one ceiling covers the whole server.
    `client_ip` is the address the edge saw (or None when the caller has
    none): only the anonymous trial mint charges against it, so a direct
    test call passes nothing and pays nothing."""
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
        if tail == ["anonymous"]:
            # The zero-friction entry: a device id in, an account out, nothing typed
            # and nothing to remember. Unauthenticated by construction, like
            # creation, and counted the same way (`_note_usage` above ran with no
            # key, so this gets a request count and no device).
            #
            # What it is NOT is a way to get more free VIP: the three days live in
            # `device_trials`, keyed on the id, and the server hands back the stored
            # expiry for any device it has already seen. `trial_days` is not a
            # parameter of this route and no body field can become one — a client
            # that could set its own trial length would be a client that sets its own
            # price, which is the rule `["payment"]` below enforces on money.
            trial = accounts.grant_or_resume_device_trial(
                db_path, payload.get("device_id"), client_ip=client_ip)
            out = _trial_view(trial)
            if trial["sync_key"]:
                out["sync_key"] = trial["sync_key"]
            return _respond({"account": out}, status=201 if trial["created"] else 200)
        if not key:
            return _problem("unauthorised", 401, "a bearer sync key is required", path)
        if tail == ["revoke"]:
            accounts.revoke_account(db_path, key, tracker=LIMITER)
            return _respond({"revoked": True})
        if tail == ["profile-link"]:
            # Bearer first, always: `link_profile_with_pin` writes onto whatever
            # `account_id` it is handed, so the number may only ever come from a key
            # this server minted and has not revoked — never from the body. A body
            # that carries `account_id` is ignored on purpose rather than refused:
            # refusing would advertise that the field is the interesting one.
            #
            # The PIN is what makes a re-link edit the profile instead of stealing
            # it, and the +1 day it earns is granted once per account (`linked_at`),
            # so replaying this call is a no-op on the entitlement. What it costs on
            # a plain-HTTP host is stated in `accounts.link_profile_with_pin`: the
            # PIN and the phone cross the wire in the clear, the limiter is the only
            # thing between a 4-digit PIN and a guesser, and a watcher who captured
            # the sync key already owns the account anyway.
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            linked = accounts.link_profile_with_pin(
                db_path, account["account_id"],
                name=payload.get("name"), phone=payload.get("phone"),
                pin=payload.get("pin"), tracker=LIMITER)
            return _respond({"profile": _profile_view(linked)},
                            status=201 if linked["bonus_granted"] else 200)
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
            # A finished title pays once, ever: 90% watched counts as finished
            # because the player may never report exactly 100%. The grant is a
            # server-side decision on numbers the server already holds — the
            # phone never claims a finish, it only reports a position — and
            # since this release it also needs the server to have *seen* the
            # watching: `finish_watch_observed` demands the first applied
            # progress report be at least 45% of the runtime ago, so one
            # instant "I finished it" claim pays nothing. A 2x viewer still
            # passes; a farmer must space reports over ~45% of the runtime
            # per title. The progress write above already recorded this
            # report's observation, so a first-ever report measures a span
            # of zero and is refused here, honestly.
            coins_earned = 0
            position = float(row.get("position_seconds") or 0.0)
            duration = float(row.get("duration_seconds") or 0.0)
            if duration > 0 and position >= engagement.FINISH_WATCH_FRACTION * duration:
                account = accounts.authenticate(db_path, key, tracker=LIMITER)
                values = _settings(catalog)
                with closing(engagement.connect(db_path)) as wallet:
                    seen = engagement.finish_watch_observed(
                        wallet, account["account_id"], work=work,
                        season=int(row.get("season_number") or 0),
                        episode=int(row.get("episode_number") or 0),
                        duration_seconds=duration)
                    if seen["observed"]:
                        grant = engagement.grant_finish_watch(
                            wallet, account["account_id"], work=work,
                            season=int(row.get("season_number") or 0),
                            episode=int(row.get("episode_number") or 0),
                            values=values)
                        coins_earned = grant["coins"] if grant["granted"] else 0
            return _respond({"progress": accounts.to_public(row, mint),
                             "coins_earned": coins_earned}, status=201)
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
        if tail == ["coins", "earn"]:
            # The daily claim, and what is *not* taken from the caller is the point:
            # no `amount`, no `minutes`, no `event_id`, no `account_id`. The size of the
            # grant is the ladder's own (`streak_day1_coins`, an operator setting,
            # resolved through `engagement.resolve_streak_grants` so the number this
            # reply reports is the number the ledger wrote), the day is claimed by one
            # guarded `UPDATE` inside `record_engagement_day`, and the account is the one
            # the bearer key names. Replay is therefore answered twice over and by the
            # server alone: the guarded UPDATE leaves the streak where it is, and the
            # credit carries `idempotency_key = "streak:<account>:<day-bucket>:coins"` —
            # a key computed from the civil day, not from anything the client typed, so
            # there is no fresh event id that buys a second coin the same day.
            extra = sorted(str(name) for name in payload if name not in _EARN_KEYS)
            if extra:
                return _problem("invalid_params", 400,
                                "an earning request accepts reason only", path)
            reason = str(payload.get("reason") or "")
            refusal = _REFUSED_EARN.get(reason)
            if refusal:
                return _problem("forbidden", 403, refusal, path)
            if reason != _EARN_DAILY_LOGIN:
                return _problem("invalid_params", 400, "no such earning reason", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            values = _settings(catalog)
            zone = _civil_zone(values)
            with closing(engagement.connect(db_path)) as wallet:
                day = engagement.record_engagement_day(
                    wallet, account["account_id"],
                    grants=engagement.resolve_streak_grants(values),
                    pass_secret=secret, tz=zone["tz"],
                    day_boundary_hour=zone["day_boundary_hour"])
            return _respond({"earned": _earn_view(day)})
        if tail == ["coins", "redeem"]:
            # Coins into a signed pass. This route never calls `spend_coins` itself,
            # because the order is the whole lesson: `redeem_pass` resolves the tier's
            # cost *and* its expiry from the ladder before the wallet is touched, and it
            # does the spend and the mint in one connection's transaction, so a tier this
            # module cannot time costs nothing rather than taking coins and minting
            # nothing. Handing it the already-resolved `ladder` — the same table the row
            # produces — is what keeps the price this reply reports and the price the
            # wallet was debited one read rather than two.
            extra = sorted(str(name) for name in payload if name not in _REDEEM_KEYS)
            if extra:
                return _problem("invalid_params", 400,
                                "a redemption accepts plan and idempotency_key only", path)
            plan = str(payload.get("plan") or "")
            refusal = _REFUSED_REWARDS.get(plan)
            if refusal:
                return _problem("forbidden", 403, refusal, path)
            ladder = engagement.resolve_ladder(_settings(catalog))
            # The ladder is the whole name space: no reward table lives here, so a tier
            # the operator's row prices is a tier this route can sell, and nothing else.
            if plan not in ladder:
                return _problem("invalid_params", 400, "no such reward", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            client_key, key_refusal = _client_idempotency_key(
                payload, account["account_id"], "redeem", path)
            if key_refusal is not None:
                return key_refusal
            with closing(engagement.connect(db_path)) as wallet:
                try:
                    redeemed = engagement.redeem_pass(
                        wallet, account["account_id"], plan=plan,
                        idempotency_key=client_key,
                        pass_secret=secret, ladder=ladder)
                except engagement.InsufficientCoins:
                    # 402 — §16.4's "a licence is required before this can be played",
                    # said about a wallet instead of a file. `InsufficientCoins` names
                    # the account id and both numbers; none of it reaches the wire. The
                    # caller can read its own balance from `GET /coins`, and a refusal
                    # that quotes the cost is a hint about what to farm.
                    return _problem("licence_required", 402,
                                    "this wallet cannot cover that reward", path)
            return _respond({"redeemed": _redeem_view(redeemed)})
        if tail == ["coins", "redeem-download"]:
            # Coins into one direct download of one movie. The handle IS the
            # purchase: a credit bought for one download id spends on no other,
            # so the route checks the handle is one of our own signed tokens
            # before any coin moves — a credit for a handle that never resolves
            # would be 100 coins for nothing. The price is resolved from the
            # operator's row, the same read the caps route publishes.
            extra = sorted(str(name) for name in payload if name not in _DOWNLOAD_KEYS)
            if extra:
                return _problem("invalid_params", 400,
                                "a download purchase accepts handle and idempotency_key only", path)
            handle = str(payload.get("handle") or "")
            if not redact.parse_token(handle, secret, signed_only=True):
                return _problem("invalid_params", 400, "no such download", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            client_key, key_refusal = _client_idempotency_key(
                payload, account["account_id"], "redeem-download", path)
            if key_refusal is not None:
                return key_refusal
            values = _settings(catalog)
            with closing(engagement.connect(db_path)) as wallet:
                try:
                    credit = engagement.redeem_download_credit(
                        wallet, account["account_id"], handle=handle,
                        idempotency_key=client_key,
                        credit_secret=secret, values=values)
                except engagement.InsufficientCoins:
                    # Same 402 as the pass route: the refusal names no number,
                    # and the caller reads its own balance from `GET /coins`.
                    return _problem("licence_required", 402,
                                    "this wallet cannot cover that download", path)
            return _respond({"credit": _download_view(credit)})
        if tail == ["coins", "share"]:
            # One share of a movie pays 25 coins, once a day. The server cannot
            # observe a share — the app's chooser returning proves nothing —
            # so this is a bounded client claim, the same shape as the
            # daily-login claim: the app reports it, the server verifies the
            # work handle is one of ours (a forged handle is a 400 before any
            # coin moves) and the day bucket is the enforcement. The reply
            # carries the grant, so the app shows "+25" only when the server
            # says it paid.
            extra = sorted(str(name) for name in payload if name not in _SHARE_KEYS)
            if extra:
                return _problem("invalid_params", 400,
                                "a share claim accepts work_ref only", path)
            work, refusal = _target(payload, mint, path)
            if refusal:
                return refusal
            # The adult law covers the share too: a flagged work is
            # indistinguishable from one that never existed, so the refusal is
            # the same 400 `_target` gives a forged handle — same code, same
            # words, nothing echoed back. A minted handle for a work the
            # catalog never held is refused the same way.
            if not accounts.work_is_visible(catalog, work):
                return _problem("invalid_params", 400,
                                "work_ref is not a handle this service minted", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            values = _settings(catalog)
            with closing(engagement.connect(db_path)) as wallet:
                share = engagement.grant_share(
                    wallet, account["account_id"], work=work, values=values)
            return _respond({"share": _share_view(share)})
        if tail == ["coins", "request-movie"]:
            # One requested movie costs 300 coins and queues the title for the
            # operator. The title is the viewer's own words, capped at the
            # route — a request that is a page of text is not a request — and
            # the spend and the queue entry are one purchase: a retry with the
            # same second spends nothing and queues nothing twice.
            extra = sorted(str(name) for name in payload if name not in _REQUEST_MOVIE_KEYS)
            if extra:
                return _problem("invalid_params", 400,
                                "a movie request accepts title, notes and idempotency_key only", path)
            title = str(payload.get("title") or "").strip()
            notes = str(payload.get("notes") or "").strip()
            if not title or len(title) > _REQUEST_TITLE_MAX or len(notes) > _REQUEST_NOTES_MAX:
                return _problem("invalid_params", 400,
                                "a movie request needs a short title", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            client_key, key_refusal = _client_idempotency_key(
                payload, account["account_id"], "request-movie", path)
            if key_refusal is not None:
                return key_refusal
            values = _settings(catalog)
            with closing(engagement.connect(db_path)) as wallet:
                try:
                    request = engagement.request_movie(
                        wallet, account["account_id"], title=title, notes=notes,
                        values=values, idempotency_key=client_key)
                except engagement.InsufficientCoins:
                    # Same 402 as the pass route: the refusal names no number,
                    # and the caller reads its own balance from `GET /coins`.
                    return _problem("licence_required", 402,
                                    "this wallet cannot cover that request", path)
            return _respond({"request": _request_view(request)})
        if tail == ["coins", "redeem-theme"]:
            # One player theme costs 250 coins and is owned forever. The theme
            # must be one this server sells — an unknown name is a 400 before
            # any coin moves — and a theme already owned costs nothing: the
            # route answers `already_applied` with the ownership it already
            # holds, and no spend runs at all.
            extra = sorted(str(name) for name in payload if name not in _REDEEM_THEME_KEYS)
            if extra:
                return _problem("invalid_params", 400,
                                "a theme purchase accepts theme and idempotency_key only", path)
            theme = str(payload.get("theme") or "")
            if theme not in engagement.PURCHASABLE_THEMES:
                return _problem("invalid_params", 400, "no such theme", path)
            account = accounts.authenticate(db_path, key, tracker=LIMITER)
            client_key, key_refusal = _client_idempotency_key(
                payload, account["account_id"], "redeem-theme", path)
            if key_refusal is not None:
                return key_refusal
            values = _settings(catalog)
            with closing(engagement.connect(db_path)) as wallet:
                owned = engagement.owned_themes(wallet, account["account_id"])
                if theme in owned:
                    return _respond({"theme": _theme_view({
                        "theme": theme, "cost": engagement.resolve_theme_coins(values),
                        "balance": engagement.coin_balance(wallet, account["account_id"]),
                        "already_applied": True, "owned": owned})})
                try:
                    bought = engagement.redeem_theme(
                        wallet, account["account_id"], theme=theme, values=values,
                        idempotency_key=client_key)
                except engagement.InsufficientCoins:
                    # Same 402 as the pass route: the refusal names no number,
                    # and the caller reads its own balance from `GET /coins`.
                    return _problem("licence_required", 402,
                                    "this wallet cannot cover that theme", path)
            return _respond({"theme": _theme_view(bought)})
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
        trial = route_post(f"{PREFIX}/anonymous", {"device_id": "selfcheck-device-1"},
                           db_path=db, catalog_path=catalog, secret=secret, headers={})
        assert trial[0] == 201, trial
        fresh = json.loads(trial[2])["account"]
        assert fresh["created"] and fresh["sync_key"], fresh
        again = route_post(f"{PREFIX}/anonymous", {"device_id": "selfcheck-device-1"},
                           db_path=db, catalog_path=catalog, secret=secret, headers={})
        resumed = json.loads(again[2])["account"]
        assert again[0] == 200 and not resumed["created"], again
        assert resumed["trial_expires_at"] == fresh["trial_expires_at"], resumed
        assert "sync_key" not in resumed or not resumed["sync_key"], resumed
        junk = route_post(f"{PREFIX}/anonymous", {"device_id": "x"}, db_path=db,
                          catalog_path=catalog, secret=secret, headers={})
        assert junk[0] == 400, junk
        mine = {"Authorization": "Bearer " + fresh["sync_key"]}
        linked = route_post(f"{PREFIX}/profile-link",
                            {"name": "Self Check", "phone": "+92 300 1234567",
                             "pin": "4821"}, db_path=db, catalog_path=catalog,
                            secret=secret, headers=mine)
        assert linked[0] == 201, linked
        assert json.loads(linked[2])["profile"]["bonus_granted"], linked
        assert b"pin" not in linked[2].lower() and b"4821" not in linked[2], linked
        wrong = route_post(f"{PREFIX}/profile-link",
                           {"name": "Self Check", "phone": "03001234567", "pin": "9999"},
                           db_path=db, catalog_path=catalog, secret=secret, headers=mine)
        assert wrong[0] == 401, wrong
        naked = route_post(f"{PREFIX}/profile-link",
                           {"name": "Self Check", "phone": "03001234567", "pin": "4821"},
                           db_path=db, catalog_path=catalog, secret=secret, headers={})
        assert naked[0] == 401, naked
        other = route_get("/api/v2/browse", {}, db_path=db, catalog_path=catalog,
                          secret=secret, headers={})
        assert other is None, other
        # The wallet: one day claimed, one replay refused, one short redemption that
        # writes nothing, one pass bought for exactly the ladder's own price.
        wallet = route_get(f"{PREFIX}/coins", {}, db_path=db, catalog_path=catalog,
                           secret=secret, headers=auth)
        assert wallet[0] == 200, wallet
        opening = json.loads(wallet[2])
        assert opening["balance"] == 0 and opening["rewarded_grants_today"] == 0, opening
        earned = route_post(f"{PREFIX}/coins/earn", {"reason": "daily_login"},
                            db_path=db, catalog_path=catalog, secret=secret, headers=auth)
        assert earned[0] == 200, earned
        first = json.loads(earned[2])["earned"]
        assert first["status"] == "started" and first["coins_granted"] > 0, first
        again = route_post(f"{PREFIX}/coins/earn", {"reason": "daily_login"},
                           db_path=db, catalog_path=catalog, secret=secret, headers=auth)
        replay = json.loads(again[2])["earned"]
        assert replay["status"] == "same_day_noop" and replay["coins_granted"] == 0, replay
        priced = route_post(f"{PREFIX}/coins/earn",
                            {"reason": "daily_login", "amount": 500},
                            db_path=db, catalog_path=catalog, secret=secret, headers=auth)
        assert priced[0] == 400, priced
        claimed = route_post(f"{PREFIX}/coins/earn", {"reason": "rewarded_ad"},
                             db_path=db, catalog_path=catalog, secret=secret, headers=auth)
        assert claimed[0] == 403, claimed
        short = route_post(f"{PREFIX}/coins/redeem", {"plan": "monthly_vip"},
                           db_path=db, catalog_path=catalog, secret=secret, headers=auth)
        assert short[0] == 402, short
        assert json.loads(route_get(f"{PREFIX}/coins", {}, db_path=db,
                                    catalog_path=catalog, secret=secret,
                                    headers=auth)[2])["balance"] == first["coins_granted"]
        with closing(engagement.connect(db)) as state:
            tier = engagement.resolve_ladder()["day"]
            shortfall = tier["coins"] - first["coins_granted"]
            if shortfall > 0:
                engagement.grant_coins(
                    state, accounts.authenticate(db, key)["account_id"],
                    amount=shortfall, reason="admin_grant", source="admin",
                    idempotency_key="selfcheck-topup")
        bought = route_post(f"{PREFIX}/coins/redeem", {"plan": "day"},
                            db_path=db, catalog_path=catalog, secret=secret,
                            headers=auth)
        assert bought[0] == 200, bought
        receipt = json.loads(bought[2])["redeemed"]
        assert receipt["cost"] == tier["coins"], receipt
        assert redact.parse_vip_pass(receipt["pass"], secret) == receipt["expires_at"], receipt
        unlisted = route_post(f"{PREFIX}/coins/redeem", {"plan": "unlock_1080p"},
                              db_path=db, catalog_path=catalog, secret=secret,
                              headers=auth)
        assert unlisted[0] == 403, unlisted
        listed = route_get(f"{PREFIX}/coins/caps", {}, db_path=db,
                           catalog_path=catalog, secret=secret, headers=auth)
        assert listed[0] == 200, listed
        assert json.loads(listed[2])["passes"]["day"]["coins"] == receipt["cost"], listed
        seen = route_get(f"{PREFIX}/coins/history", {}, db_path=db,
                         catalog_path=catalog, secret=secret, headers=auth)
        assert seen[0] == 200 and json.loads(seen[2])["count"] >= 2, seen
        stranger = accounts.create_account(db)["sync_key"]
        theirs = route_get(f"{PREFIX}/coins/history", {}, db_path=db,
                           catalog_path=catalog, secret=secret,
                           headers={"Authorization": f"Bearer {stranger}"})
        assert json.loads(theirs[2])["count"] == 0, theirs
        print("[.] accounts_api selfcheck OK — one favorite, adult and forged refs "
              "refused, one trial resumed and one profile linked, one day claimed and "
              "one replay refused, a client-priced claim and a quality unlock refused, "
              "a short redemption that wrote nothing, one pass bought at the ladder's "
              "own price, one price list that matched the charge and one ledger page "
              "that showed a stranger nothing")
        return 0


if __name__ == "__main__":
    raise SystemExit(_selfcheck())
