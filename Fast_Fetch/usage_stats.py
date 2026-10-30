#!/usr/bin/env python3
"""Operator-only usage analytics: installs, live devices, retention, money.

The owner's question is a count, not a story: how many installs, how many
devices are live right now, how many accounts, how much money. Every number
here answers that question for a *population* and never for a person, and the
rules that keep it that way are load-bearing, not decoration:

1. **Aggregates only.** A device is known as `dev-<salted digest>` — the same
   one-way, salted, truncated scheme `payments.account_hint` uses for an
   account. One row per install carries its cohort day, its last-seen instant
   and four dimension labels. There is no event log keyed by device and no
   timeline to reconstruct: activity collapses into per-day counters that name
   no device at all. No IP is read, so none can be stored.
2. **Loopback only.** This module serves no route. The report surfaces on
   `/admin/api/usage`, which `admin_panel._gate` already denies to anyone who is
   not on loopback with the operator token, and which `viewer` 404s on the
   public port before the panel is ever consulted.
3. **Incremental on write, never on read.** Every counter is an UPSERT fired by
   the request that earned it. `summary()` reads three small tables plus the
   payment queue — never `posts`, `releases` or `download_sources`, which on
   this box are 150,799 / 1.7M / 4.0M rows and would turn a dashboard refresh
   into a self-inflicted denial of service on one core.
   `test_usage_stats.py` proves the absence of the scan instead of asserting it
   in prose.

Two families of number arrive by different doors, and the report labels which:

* **Server-observed** — an authenticated call on the account surface carries a
  sync key and (once the app lane adds them) an install header, so installs,
  active windows, DAU/WAU/MAU, retention and per-geo/locale/version/device-class
  counts are measured from traffic that already reaches us.
* **Client-reported** — ad requests, fills, impressions, clicks, rewarded
  completions, coin grants, crashes and buffering failures happen on the phone.
  They arrive inside the optional `usage` block of the existing
  `POST /api/v2/account/progress` body: no new route, no nginx change, nothing a
  caller may post that the server did not already accept. Until the client sends
  that block these counters read zero, and `summary()` says so in
  `reported_by_client_pending` rather than inventing a number.

    python3 -S Fast_Fetch/test_usage_stats.py
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sqlite3
import time

import accounts

#: Bumped when the shape below changes in a way an old row cannot be read as.
SCHEMA_VERSION = 1

#: The one-way form of a device key. Salted so a stolen table cannot be
#: rainbowied against a guessable install UUID, and truncated because a counter
#: needs collision-free buckets, not 64 hex characters of index padding.
DEVICE_PREFIX = "dev-"
DEVICE_HASH_CHARS = 16
DEVICE_SALT_ENV = "RADD_USAGE_SALT"
#: A stable default: cohorts must survive a restart, so the salt cannot be
#: per-process randomness. Rotating `RADD_USAGE_SALT` re-keys every install and
#: retention cohorts restart from the day of the rotation — a deployment
#: decision, which is why it is an environment variable and not a constant.
DEVICE_SALT_DEFAULT = "radd-usage-device:v1:"

#: A device is "live" in a window when its last-seen instant falls inside it.
#: Exact, because `last_seen_at` is the maximum activity time we have recorded.
LIVE_WINDOW_SECONDS = (("5m", 300), ("30m", 1800), ("60m", 3600))
#: Rolling, not calendar: `dau` is the last 86,400 s, `wau` the last 7 days,
#: `mau` the last 30. A calendar-day distinct count would need a per-device set
#: of days, which is the timeline rule 1 forbids.
ACTIVITY_WINDOWS = (("dau", 86400), ("wau", 7 * 86400), ("mau", 30 * 86400))
#: Coarse retention: the device came back on or after install day + N. "Returned
#: exactly on day N" needs per-day membership per device — again a timeline.
#: This is the standard coarse definition and the key says so.
RETENTION_DAYS = (1, 7, 30)
#: `last_seen_at` is rewritten at most this often, mirroring
#: `accounts.LAST_SEEN_WRITE_INTERVAL`: a browse-heavy session must not become
#: one write per request on a single-core box.
SEEN_WRITE_INTERVAL = 900.0
#: One client submission may not report a million impressions.
MAX_EVENT_COUNT = 1000
#: Dimension values come from a header or a client body, so they are shape-
#: checked rather than trusted, and anything odder folds to a fixed label.
_VALUE_RE = re.compile(r"^[A-Za-z0-9._+-]{1,32}$")
#: Rule 1 is a property of storage, not of intent. A colon already cannot survive
#: `_VALUE_RE`, so IPv6 is refused by the shape rule; a dotted quad is the one
#: address form that passes it, and it is refused here rather than trusted to
#: callers not to put an address in `X-App-Version`.
_DOTTED_QUAD_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,3})?$")
DIMS = ("geo", "locale", "app_version", "device_class")
UNKNOWN_VALUE = "unknown"

#: The closed vocabulary of counted events. A metric outside this set is
#: refused rather than stored, so no caller can inflate an arbitrary key space.
METRICS = frozenset({
    "session",
    "account_request",
    "playback_start",
    "playback_attempt",
    "playback_buffer_failure",
    "playback_error",
    "crash",
    "error",
    "ad_request",
    "ad_fill",
    "ad_impression",
    "ad_click",
    "rewarded_completion",
    "coin_granted",
})
#: Metrics only the phone can tell us about; the server cannot see them.
REPORTED_ONLY = frozenset({
    "playback_attempt",
    "playback_buffer_failure",
    "playback_error",
    "crash",
    "error",
    "ad_request",
    "ad_fill",
    "ad_impression",
    "ad_click",
    "rewarded_completion",
    "coin_granted",
})
#: The app's own field names, mapped onto our vocabulary so the client contract
#: can stay readable while the counter set stays closed.
CLIENT_FIELDS = {
    "ad_requests": "ad_request",
    "ads_filled": "ad_fill",
    "ad_impressions": "ad_impression",
    "ad_clicks": "ad_click",
    "rewarded_completions": "rewarded_completion",
    "coins_granted": "coin_granted",
    "playback_attempts": "playback_attempt",
    "playback_buffer_failures": "playback_buffer_failure",
    "playback_errors": "playback_error",
    "crashes": "crash",
    "errors": "error",
}
#: Events also split by device class — the per-class rate the owner asked for.
_CLASS_SPLIT_METRICS = frozenset({"crash", "error", "playback_buffer_failure"})

#: Memo of (connection, path) pairs whose schema is installed. Keyed by the path
#: as well as the object id, because a freed connection's id can be reused by a
#: connection to a different file.
_SCHEMA_READY: set[tuple[int, str]] = set()

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS usage_device (
        device_hash    TEXT PRIMARY KEY,
        install_day    INTEGER NOT NULL,
        first_seen_at  REAL NOT NULL,
        last_seen_at   REAL NOT NULL,
        geo            TEXT NOT NULL DEFAULT 'unknown',
        locale         TEXT NOT NULL DEFAULT 'unknown',
        app_version    TEXT NOT NULL DEFAULT 'unknown',
        device_class   TEXT NOT NULL DEFAULT 'unknown',
        retained_1     INTEGER NOT NULL DEFAULT 0,
        retained_7     INTEGER NOT NULL DEFAULT 0,
        retained_30    INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_metric (
        day    INTEGER NOT NULL,
        metric TEXT NOT NULL,
        total  REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (day, metric)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_dim_metric (
        day    INTEGER NOT NULL,
        dim    TEXT NOT NULL,
        value  TEXT NOT NULL,
        metric TEXT NOT NULL,
        total  REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (day, dim, value, metric)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_usage_device_last_seen"
    " ON usage_device(last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_device_install_day"
    " ON usage_device(install_day)",
    "CREATE INDEX IF NOT EXISTS idx_usage_metric_day ON usage_metric(day)",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the three tables and their indexes. Idempotent: two first requests
    racing through here both succeed, because every statement is guarded."""
    for statement in _DDL:
        conn.execute(statement)
    try:
        conn.commit()
    except sqlite3.Error:
        pass


@contextlib.contextmanager
def _borrow(handle):
    """Accept a `sqlite3.Connection` or a db path, yield a ready connection.

    Same convention `accounts` uses: the HTTP host keeps one connection per
    worker thread and passes it in, an operator CLI just names a file. Our own
    open reuses `accounts.connect` so the busy timeout, WAL and row factory are
    one decision made in one place.
    """
    if isinstance(handle, sqlite3.Connection):
        _install_schema(handle, ":conn:")
        yield handle
        return
    conn = accounts.connect(handle, install_schema=False)
    try:
        _install_schema(conn, str(handle))
        yield conn
    finally:
        conn.close()


def _install_schema(conn: sqlite3.Connection, path: str) -> None:
    key = (id(conn), path)
    if key not in _SCHEMA_READY:
        ensure_schema(conn)
        _SCHEMA_READY.add(key)


def device_salt() -> str:
    return os.environ.get(DEVICE_SALT_ENV, "").strip() or DEVICE_SALT_DEFAULT


def device_token(raw) -> str:
    """The salted, truncated, one-way device key — or ``""`` for nothing.

    Accepts an install id straight from the client header, or a credential we
    already hash (a sync key, or its stored `sha256:` form) so a client that
    sends no install header still lands in a stable, unlinkable bucket: the
    digest of a digest, the same construction as `payments.account_hint`. It
    never returns its input and never returns anything reversible.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    digest = hashlib.sha256((device_salt() + text).encode("utf-8")).hexdigest()
    return DEVICE_PREFIX + digest[:DEVICE_HASH_CHARS]


def day_of(ts: float) -> int:
    """UTC day number — the cohort bucket. One definition, shared with reads."""
    return int(float(ts) // 86400)


def clean_value(value) -> str:
    """A dimension label that passes the shape check, else `unknown`.

    Header- and client-supplied text is never stored raw: 32 characters of
    `[A-Za-z0-9._+-]` or nothing. Locales arrive lower-cased and regions
    upper-cased so the panel can read them without a second rule.
    """
    text = str(value or "").strip()
    if not text or len(text) > 32 or not _VALUE_RE.match(text):
        return UNKNOWN_VALUE
    if _DOTTED_QUAD_RE.match(text):
        return UNKNOWN_VALUE
    return text


def _count(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number < 0:               # NaN, negatives
        return 0.0
    return min(number, float(MAX_EVENT_COUNT))


def attributes_from_headers(headers) -> dict:
    """geo / locale / app version / device class, from request headers only.

    `geo` is the region subtag of `Accept-Language` (`en-PK` → `PK`) — a
    preference the client states, deliberately not an IP lookup, because rule 1
    forbids holding an IP in any form. `X-Install-Id`, `X-App-Version` and
    `X-Device-Class` are ours. `User-Agent` is not parsed: a device model string
    is a fingerprint and this table has no business holding one.
    """
    def header(name, default=""):
        try:
            return str(headers.get(name, default) or default or "")
        except (AttributeError, TypeError):
            return default

    language = header("Accept-Language").strip()
    first = language.split(",")[0].strip() if language else ""
    primary = first.split(";")[0].strip()
    parts = [piece for piece in re.split(r"[-_]", primary) if piece]
    region = parts[1] if len(parts) > 1 and len(parts[1]) == 2 else ""
    return {
        "geo": clean_value(region.upper()) if region else UNKNOWN_VALUE,
        "locale": clean_value(primary.lower()) if primary else UNKNOWN_VALUE,
        "app_version": clean_value(header("X-App-Version").strip()),
        "device_class": clean_value(header("X-Device-Class").strip().lower()),
    }


def install_id_from_headers(headers) -> str:
    try:
        return str(headers.get("X-Install-Id", "") or "").strip()
    except (AttributeError, TypeError):
        return ""


def _bump(conn: sqlite3.Connection, day: int, metric: str, amount: float,
          dim: str | None = None, value: str | None = None) -> None:
    """One incremental counter write — never read-modify-write, so two workers
    adding the same event both land, because SQL performs the sum."""
    if metric not in METRICS or amount <= 0:
        return
    if dim is None:
        conn.execute(
            "INSERT INTO usage_metric(day, metric, total) VALUES(?,?,?)"
            " ON CONFLICT(day, metric) DO UPDATE SET total = total + excluded.total",
            (day, metric, float(amount)))
        return
    conn.execute(
        "INSERT INTO usage_dim_metric(day, dim, value, metric, total) VALUES(?,?,?,?,?)"
        " ON CONFLICT(day, dim, value, metric)"
        " DO UPDATE SET total = total + excluded.total",
        (day, dim, value or UNKNOWN_VALUE, metric, float(amount)))


def _identity(install_id=None, credential=None) -> str:
    """The device bucket: the client's install id when it sent one, else the
    salted digest of the credential it presented, else nothing."""
    return device_token(install_id) or device_token(credential)


def record_seen(db, *, install_id=None, credential=None, headers=None,
                now: float | None = None, count_request=True,
                credential_is_known: bool = True) -> dict | None:
    """Mark one device live and count what this request implies.

    Called from the account surface — the only place a caller has already
    identified itself. Because a pre-change app sends no `X-Install-Id`, its
    bucket falls back to the credential, so installs and accounts can read equal
    today; `summary()` reports that fallback instead of hiding it.

    **A device row is written only for a credential the server issued**
    (`credential_is_known`, answered by the caller from `accounts.key_is_known`).
    Without that gate, anyone could grow `usage_device` one row per guess by
    presenting random sync keys, and rule 3 — counters bounded by installs, not by
    traffic — would be a sentence in a docstring rather than a property of the
    table. A caller with no valid account can still raise `account_request`; it
    cannot create a device.

    Returns the bucket and attributes, or ``None`` when there was nothing to
    identify: an anonymous call still raises the request total and marks no
    device. Analytics never breaks the user's request — every failure path here
    rolls back and returns quietly.
    """
    stamp = float(now if now is not None else time.time())
    identified = bool(install_id or credential)
    if identified and not credential_is_known:
        install_id, credential = None, None
    token = _identity(install_id, credential)
    attrs = attributes_from_headers(headers if headers is not None else {})
    day = day_of(stamp)
    try:
        with _borrow(db) as conn:
            if count_request:
                _bump(conn, day, "account_request", 1.0)
                conn.commit()
            if not token:
                return None
            row = conn.execute(
                "SELECT install_day, last_seen_at FROM usage_device WHERE device_hash = ?",
                (token,)).fetchone()
            first_ever = row is None
            install_day = day if first_ever else int(row["install_day"])
            previous_seen = float(row["last_seen_at"]) if row else 0.0
            conn.execute(
                "INSERT INTO usage_device(device_hash, install_day, first_seen_at,"
                " last_seen_at, geo, locale, app_version, device_class)"
                " VALUES(?,?,?,?,?,?,?,?)"
                " ON CONFLICT(device_hash) DO UPDATE SET"
                "   last_seen_at = MAX(usage_device.last_seen_at, excluded.last_seen_at),"
                "   geo = CASE WHEN excluded.geo <> 'unknown'"
                "     THEN excluded.geo ELSE usage_device.geo END,"
                "   locale = CASE WHEN excluded.locale <> 'unknown'"
                "     THEN excluded.locale ELSE usage_device.locale END,"
                "   app_version = CASE WHEN excluded.app_version <> 'unknown'"
                "     THEN excluded.app_version ELSE usage_device.app_version END,"
                "   device_class = CASE WHEN excluded.device_class <> 'unknown'"
                "     THEN excluded.device_class ELSE usage_device.device_class END",
                (token, install_day, stamp, stamp, attrs["geo"], attrs["locale"],
                 attrs["app_version"], attrs["device_class"]))
            # Coarse retention: the later visit itself proves the cohort returned,
            # so one UPDATE per horizon crossed is enough — no day set per device.
            for horizon in RETENTION_DAYS:
                if day - install_day >= horizon:
                    conn.execute(
                        "UPDATE usage_device SET retained_%d = 1 WHERE device_hash = ?"
                        % horizon, (token,))
            if first_ever or stamp - previous_seen >= SEEN_WRITE_INTERVAL:
                _bump(conn, day, "session", 1.0)
            conn.commit()
            return {"device_hash": token, "install_day": install_day,
                    "first_seen": bool(first_ever), **attrs}
    except sqlite3.Error:
        return None


def record_event(db, *, metric: str, count=1, dims: dict | None = None,
                 day: int | None = None, now: float | None = None) -> bool:
    """Count one event, optionally split across dimensions in `DIMS`.

    A playback request with no install header still raises the daily total; only
    the per-device split needs the client. Returns True when something was
    written, so a caller can tell a refused metric from an accepted one.

    `day` is a **day number** (`day_of` of the instant you mean), for backfilling
    a day the counter missed; pass `now` for an instant instead. Both are the same
    `day_of` the read side uses, so a backfilled row lands in the window a report
    will actually look at.
    """
    bucket = int(day) if day is not None else day_of(
        float(now if now is not None else time.time()))
    name = str(metric)
    amount = _count(count)
    if name not in METRICS or amount <= 0:
        return False
    try:
        with _borrow(db) as conn:
            _bump(conn, bucket, name, amount)
            for dim, value in (dims or {}).items():
                if dim in DIMS:
                    _bump(conn, bucket, name, amount, dim=dim,
                          value=clean_value(value))
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def record_client_usage(db, payload, *, headers=None,
                        now: float | None = None) -> dict:
    """Fold the optional `usage` block of an existing account POST into counters.

    The block rides on `POST /api/v2/account/progress` — a route that already
    exists, already authenticates, already accepts a JSON object — so no new
    public surface appears. Every field is a whole number the client counted on
    its own side, clamped to `MAX_EVENT_COUNT` per submission; names outside
    `CLIENT_FIELDS` are ignored rather than stored, and crash / error / buffer
    totals are additionally split by device class.

    Returns the metrics actually written.
    """
    if not isinstance(payload, dict):
        return {}
    block = payload.get("usage")
    if not isinstance(block, dict):
        return {}
    stamp = float(now if now is not None else time.time())
    bucket = day_of(stamp)
    attrs = attributes_from_headers(headers if headers is not None else {})
    device_class = attrs["device_class"]
    written: dict[str, float] = {}
    try:
        with _borrow(db) as conn:
            for field, metric in CLIENT_FIELDS.items():
                amount = _count(block.get(field))
                if amount <= 0:
                    continue
                _bump(conn, bucket, metric, amount)
                written[metric] = written.get(metric, 0.0) + amount
                if metric in _CLASS_SPLIT_METRICS:
                    _bump(conn, bucket, metric, amount, dim="device_class",
                          value=device_class)
            conn.commit()
    except sqlite3.Error:
        return {}
    return written


# ── the report ───────────────────────────────────────────────────────────────

def _scalar(conn, sql, *args, default=0):
    """One number, or `default` when the table is not there yet. An absent
    table is an honest zero, never a 500 on the operator's own panel."""
    try:
        value = conn.execute(sql, args).fetchone()[0]
    except sqlite3.Error:
        return default
    return default if value is None else value


def _windows(conn, *, now: float) -> dict:
    """Live-session and active-user counts, in the shape the report wants.

    Every one is `COUNT(*) WHERE last_seen_at >= now - N` over one row per
    device, which is exact for a distinct-active count in a rolling window: a
    device was active in the window if and only if its maximum activity time is
    inside it.
    """
    live = {}
    for name, seconds in LIVE_WINDOW_SECONDS:
        live[name] = int(_scalar(
            conn, "SELECT COUNT(*) FROM usage_device WHERE last_seen_at >= ?",
            now - seconds))
    active = {}
    for name, seconds in ACTIVITY_WINDOWS:
        active[name] = int(_scalar(
            conn, "SELECT COUNT(*) FROM usage_device WHERE last_seen_at >= ?",
            now - seconds))
    return {"live_sessions": live, "active_users": active}


def _retention(conn, *, today: int) -> dict:
    """Returned-on-or-after D+n, over the cohort old enough to have had the chance.

    A device installed yesterday is not a failed D30 retention; it is not in the
    denominator. Counting it would make the rate trend down simply because the
    app is growing, which is the classic way for this chart to lie.
    """
    out: dict[str, dict] = {}
    for horizon in RETENTION_DAYS:
        cutoff = today - horizon
        installs = int(_scalar(
            conn, "SELECT COUNT(*) FROM usage_device WHERE install_day <= ?", cutoff))
        returned = int(_scalar(
            conn, "SELECT COUNT(*) FROM usage_device"
            " WHERE install_day <= ? AND retained_%d = 1" % horizon, cutoff))
        out["d%d" % horizon] = {
            "cohort_installs": installs,
            "returned": returned,
            "rate": (round(returned / installs, 4) if installs else None),
        }
    return out


def _dimension_counts(conn, *, since: float | None = None) -> dict:
    """Distinct installs per geo / locale / app version / device class.

    A `GROUP BY` over one row per install — bounded by the install count, never
    by the catalog. `since` narrows it to devices seen inside a window, which is
    how the panel shows *active* per-geo and not only installed per-geo.
    """
    out: dict[str, dict] = {}
    for dim in DIMS:
        where, args = ("", ())
        if since is not None:
            where, args = " WHERE last_seen_at >= ?", (since,)
        try:
            rows = conn.execute(
                "SELECT %s, COUNT(*) FROM usage_device%s GROUP BY %s"
                " ORDER BY 2 DESC LIMIT 24" % (dim, where, dim), args).fetchall()
        except sqlite3.Error:
            rows = []
        out[dim] = {str(row[0] or UNKNOWN_VALUE): int(row[1]) for row in rows}
    return out


def _metric_totals(conn, *, from_day: int, to_day: int) -> dict:
    try:
        rows = conn.execute(
            "SELECT metric, SUM(total) FROM usage_metric"
            " WHERE day >= ? AND day <= ? GROUP BY metric",
            (from_day, to_day)).fetchall()
    except sqlite3.Error:
        rows = []
    return {str(row[0]): float(row[1] or 0) for row in rows}


def _by_class(conn, *, from_day: int, to_day: int, metric: str) -> dict:
    try:
        rows = conn.execute(
            "SELECT value, SUM(total) FROM usage_dim_metric"
            " WHERE day >= ? AND day <= ? AND dim = 'device_class' AND metric = ?"
            " GROUP BY value ORDER BY 2 DESC",
            (from_day, to_day, metric)).fetchall()
    except sqlite3.Error:
        rows = []
    return {str(row[0] or UNKNOWN_VALUE): float(row[1] or 0) for row in rows}


def _payments(conn) -> dict:
    """Pass purchases by tier, straight from the payment queue.

    The queue is the ledger of record and it is bounded by what users filed, not
    by the catalog, so one aggregate `GROUP BY` here is not the scan rule 3
    forbids. `purchases` and `total_pkr` count the `approved` rows only — the
    money; `pending` is the operator's work queue, printed beside it so the two
    cannot be mistaken for each other. A rejected claim is in neither.

    Money leaves here as `int`, because that is the type the ledger of record
    reads it as (`payments.payment_detail`/`list_payments` both
    `int(row["amount_pkr"] or 0)`) and PKR is priced in whole rupees everywhere in
    this project. A `float` cast in the projection was the one place in the money
    path that turned a whole number into a number with a decimal point on the way
    out; `1500.0` prints as money, gets summed as a binary fraction and is the
    shape from which "off by one paisa" bugs start. This changes no stored value
    and no wire contract — the same rupee count, now the same type the queue holds.
    """
    out: dict[str, object] = {"by_tier": {}, "total_pkr": 0,
                              "purchases": 0, "pending": 0}
    try:
        rows = conn.execute(
            "SELECT plan, COUNT(*), COALESCE(SUM(amount_pkr), 0)"
            " FROM payment_transactions WHERE status = 'approved' GROUP BY plan"
            " ORDER BY 2 DESC").fetchall()
    except sqlite3.Error:
        rows = []
    tiers: dict[str, dict] = {}
    for plan, count, amount in rows:
        tiers[str(plan or UNKNOWN_VALUE)] = {"purchases": int(count),
                                             "amount_pkr": int(amount or 0)}
    out["by_tier"] = tiers
    out["total_pkr"] = sum(row["amount_pkr"] for row in tiers.values())
    out["purchases"] = sum(row["purchases"] for row in tiers.values())
    out["pending"] = int(_scalar(
        conn, "SELECT COUNT(*) FROM payment_transactions WHERE status = 'pending'"))
    return out


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def revenue_estimate(*, metrics: dict, users: float, days: int,
                     ecpm_usd: float | None = None,
                     pkr_per_usd: float | None = None) -> dict:
    """Ad and pass revenue per 1,000 users, with its assumptions in the payload.

    An estimate earns the name only if it prints what it assumed:
    `RADD_AD_ECPM_USD` (default 0.9 — the midpoint of the $0.3–1.5 Pakistan band
    the monetization plan settled on, not a network quote) and
    `RADD_PKR_PER_USD` (default 278). Nothing here is billed or reconciled; the
    networks settle elsewhere and this box cannot see their dashboards.
    """
    ecpm = float(ecpm_usd) if ecpm_usd is not None else _env_float("RADD_AD_ECPM_USD", 0.9)
    fx = float(pkr_per_usd) if pkr_per_usd is not None else _env_float("RADD_PKR_PER_USD", 278.0)
    impressions = float(metrics.get("ad_impression", 0))
    clicks = float(metrics.get("ad_click", 0))
    rewarded = float(metrics.get("rewarded_completion", 0))
    population = max(float(users), 1.0)
    window_days = max(float(days), 1.0)
    ad_usd = impressions / 1000.0 * ecpm
    per_1000 = ad_usd / population * 1000.0
    return {
        "assumptions": {"ecpm_usd": ecpm, "pkr_per_usd": fx,
                        "window_days": window_days,
                        "basis": "impressions x eCPM — not a network report"},
        "ad_usd_in_window": round(ad_usd, 4),
        "ad_usd_per_1000_users": round(per_1000, 4),
        "ad_usd_per_1000_users_per_day": round(per_1000 / window_days, 6),
        "ctr": round(clicks / impressions, 4) if impressions else None,
        "rewarded_per_1000_users": round(rewarded / population * 1000.0, 2),
        "estimate": True,
    }


def summary(db, *, now: float | None = None, window_days: int = 30) -> dict:
    """The whole operator answer, in one bounded read of four small tables.

    `available` is False until any usage row exists — the panel then says
    `no_usage_data_yet` rather than serving a page of zeros that reads like a
    measurement. `sources` labels every event family as observed, reported or
    derived, because a count the client has not been sending is an absence, not
    a zero.
    """
    stamp = float(now if now is not None else time.time())
    today = day_of(stamp)
    window_days = max(1, int(window_days))
    from_day = today - window_days + 1
    with _borrow(db) as conn:
        installs = int(_scalar(conn, "SELECT COUNT(*) FROM usage_device"))
        payload = {
            "available": installs > 0,
            "generated_at": stamp,
            "window_days": window_days,
            "installs": {
                "distinct_devices": installs,
                "new_today": int(_scalar(
                    conn, "SELECT COUNT(*) FROM usage_device WHERE install_day = ?",
                    today)),
                "new_this_window": int(_scalar(
                    conn, "SELECT COUNT(*) FROM usage_device WHERE install_day >= ?",
                    from_day)),
            },
            "accounts": {
                "total": int(_scalar(conn, "SELECT COUNT(*) FROM user_accounts")),
                "revoked": int(_scalar(
                    conn, "SELECT COUNT(*) FROM user_accounts"
                    " WHERE revoked_at IS NOT NULL")),
                "vip_active": int(_scalar(
                    conn, "SELECT COUNT(*) FROM user_accounts"
                    " WHERE vip_until >= ? AND revoked_at IS NULL", stamp)),
            },
            "retention": _retention(conn, today=today),
            "per_dimension_installed": _dimension_counts(conn),
            "per_dimension_active": _dimension_counts(conn, since=stamp - 86400),
            "metrics": _metric_totals(conn, from_day=from_day, to_day=today),
            "crash_by_class": _by_class(conn, from_day=from_day, to_day=today,
                                        metric="crash"),
            "error_by_class": _by_class(conn, from_day=from_day, to_day=today,
                                        metric="error"),
            "buffer_failure_by_class": _by_class(
                conn, from_day=from_day, to_day=today,
                metric="playback_buffer_failure"),
            "payments": _payments(conn),
            **_windows(conn, now=stamp),
        }
    metrics = payload["metrics"]
    server_starts = float(metrics.get("playback_start", 0))
    client_attempts = float(metrics.get("playback_attempt", 0))
    stalls = float(metrics.get("playback_buffer_failure", 0))
    # The denominator has to be the same population as the numerator: a stall is
    # one the *client* saw. Until the app reports attempts we divide by our own
    # stream hits and label that we did, because a rate built across two
    # populations is the number most likely to be believed and to be wrong.
    denominator = client_attempts or server_starts
    which = "client_attempts" if client_attempts else "server_starts"
    payload["playback"] = {
        "server_stream_starts": server_starts,
        "client_playback_attempts": client_attempts,
        "buffer_failures": stalls,
        "buffer_failure_rate": round(stalls / denominator, 4) if denominator else None,
        "rate_denominator": which,
        "starts_per_device": (round(denominator / installs, 2) if installs else None),
    }
    payload["revenue_estimate"] = revenue_estimate(
        metrics=metrics, users=payload["active_users"]["mau"] or installs,
        days=window_days)
    payload["sources"] = {
        "observed_by_server": sorted(METRICS - REPORTED_ONLY),
        "reported_by_client": sorted(REPORTED_ONLY),
        "reported_by_client_pending": sorted(
            name for name in REPORTED_ONLY if not metrics.get(name)),
    }
    payload["identity"] = {
        "device_key": "salted sha256, truncated to %d chars" % DEVICE_HASH_CHARS,
        "ip_stored": False,
        "per_person_timeline": False,
        "note": ("a device bucket is X-Install-Id when the app sends it and the"
                 " salted credential otherwise; until the app lane sends the"
                 " header, distinct_devices and accounts can legitimately read"
                 " equal, and that is the fallback rather than a defect"),
    }
    if not payload["available"]:
        payload["no_usage_data_yet"] = True
    return payload
