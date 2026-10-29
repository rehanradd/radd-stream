#!/usr/bin/env python3
"""
Fast_Fetch/engagement.py — the engagement pillars `MONETIZATION_FIELDS` does not cover.
════════════════════════════════════════════════════════════════════════════════════════
WHAT THIS IS, STATED PLAINLY
--------------------------------------------------------------------------------
The four earning/engagement mechanisms the owner wants controllable from the admin
panel but that today are literals in the APK (see
`docs/MONETIZATION_PILLARS_SCHEMA.md`, the design this file implements):

  1. **Ad-cadence caps as data** — pre-roll 1/25 min, native card 1/12 posters,
     app-open 1/4 h. The caps are config (`CAPS_DEFAULT`, overridable later from
     `app_remote_config`); `ad_cadence_state` is the server-side *frequency* those
     caps are checked against, so a phone that ignores the cap still cannot be
     served a second pre-roll inside the window.
  2. **The coin wallet** — a balance and an **append-only** earn/spend ledger.
     No coin is created by a client claim: the only writers are `grant_coins` /
     `spend_coins`, and the `usage_stats` telemetry that already reports
     `coin_granted` / `rewarded_completion` is analytics, not money, and is
     deliberately **not** wired here.
  3. **The 7-day streak** — a state machine with explicit reset semantics, bucketed
     by the user's timezone with a rollover hour so a Pakistani viewer at 02:00
     counts toward the *previous* civil day instead of resetting or double-crediting.
  4. **The PKR micro-pass ladder** — day ₨20 / weekend ₨50 / Monthly VIP ₨250,
     with coin redemption costs. This ladder lives *here*, not in `payments.py`,
     by the owner's instruction (that file is a collision zone).

THE LAWS THIS MODULE ENCODES
--------------------------------------------------------------------------------
* **Append-only, structurally.** Two `BEFORE UPDATE` / `BEFORE DELETE` triggers on
  `coin_ledger` call `RAISE(ABORT, …)`, so "append-only" is a property of the
  storage, not a promise in a docstring. A correction is a new compensating
  `reason='refund'` row, never an edit.
* **The balance is derived, never stored.** There is no `balance` column; it is
  `SUM(delta)`. A race cannot corrupt it and a tamper cannot set it.
* **No client-created coin, no cash-out.** Positive deltas require `source` in
  `{server, admin}`; there is no `client` source, and no table here has a field
  that could express "withdraw these coins for money" (§A no-deception).
* **You cannot spend what you do not have.** `spend_coins` does its balance check
  and its insert in a *single* `INSERT … SELECT … WHERE balance >= cost`
  statement — atomic by construction — so two concurrent redemptions cannot both
  pass a separate read-check and drive the balance negative.
* **Idempotent grants.** Every earn path can carry an `idempotency_key`; the UNIQUE
  index + `INSERT OR IGNORE` make a retried S2S callback or a replayed streak tick
  land once.
* **Stdlib only.** Same rule as the rest of `Fast_Fetch/`.

WHY THIS FILE HAS NO HTTP IN IT
--------------------------------------------------------------------------------
Routes belong in `accounts_api.py` / `viewer.py`; the read projection for the phone
is `remote_view()` (defaults now, overridden by the admin knobs in deliverable (c)).
This module is the ledger and the state machine, nothing else.

SCHEMA HOME
--------------------------------------------------------------------------------
The tables live in the **user-state database** (`RADD_USER_STATE_DB`, default
`user_state.db`) — the same file `accounts.py` owns — because a wallet, a streak,
and a cadence cursor are per-account state, not the single operator config row
(`app_remote_config`). `ensure_schema()` calls `accounts.ensure_schema()` first so
the FK parent (`user_accounts`) always exists regardless of which module opens the
file first. Additive and idempotent, never destructive: a migration that loses a
user's coins is not a migration.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import accounts  # stdlib sibling; the schema home + FK parent + _borrow/_commit
import redact    # signed VIP-pass primitives: mint_vip_pass / parse_vip_pass

BASE_DIR = Path(__file__).parent.resolve()

#: Bumped only on an incompatible shape change; a new column is installed by
#: `_migrate_columns` and needs no bump (mirrors `accounts.SCHEMA_VERSION`).
SCHEMA_VERSION = 1

DEFAULT_BUSY_TIMEOUT_MS = 5000

# ── tuning knobs (every one overridable per call, so tests stay deterministic) ─

#: The three ad-cadence caps (Pillar 1, plan lines 18/21/26). Defaults are the
#: plan's own numbers, so an operator who has never opened `/admin` still ships
#: the capped behaviour.
CAPS_DEFAULT = {
    "ad_preroll_min_gap_minutes": 25,
    "ad_native_card_every_posters": 12,
    "ad_app_open_min_gap_minutes": 240,
}
#: A bad save is clamped to a sane ceiling; a zero/negative value is interpreted
#: as "use the default", NEVER as "serve constantly" — the cap must not be
#: defeatable by setting it to 0.
CAP_MAX = {
    "ad_preroll_min_gap_minutes": 24 * 60,
    "ad_native_card_every_posters": 5000,
    "ad_app_open_min_gap_minutes": 24 * 60,
}

#: The only sources allowed to mint a positive delta. There is deliberately no
#: 'client' entry (§A: no coin created by a client claim).
SERVER_SOURCES = frozenset({"server", "admin"})

#: Reason vocabulary. `ref` names one of these; it is never a title or a URL.
LEDGER_REASONS = frozenset({
    "rewarded_ad", "streak_day", "redeem_pass", "admin_grant", "refund",
})
#: Debits. Redemption of a pass, and a `refund` that claws back a wrong credit
#: (a compensating row — the append-only way to undo a mistake; a refund that
#: *returns* coins after a failed spend is instead a positive `grant_coins`).
SPEND_REASONS = frozenset({"redeem_pass", "refund"})

#: Coins credited per *server-verified* rewarded completion (q3 owns the admin
#: knob; this is the default it overrides). `coin_value_pkr` stays q3's.
COINS_PER_REWARDED_AD = 5
#: A viewer cannot farm unlimited coins from ads: cap rewarded grants per day-bucket.
REWARDED_DAILY_CAP = 10

#: Streak clock: Pakistani civil day by default. `day_boundary_hour` is the local
#: rollover — activity before it counts toward the previous day.
STREAK_TZ_DEFAULT = "Asia/Karachi"
DAY_BOUNDARY_HOUR_DEFAULT = 4
#: Coin grants at these streak milestones (plan Pillar 2, lines 33–35).
STREAK_GRANTS_COINS = {1: 10, 3: 30}
#: The Day-7 milestone mints a 24-hour ad-free pass rather than coins.
STREAK_PASS_DAY = 7
DAY_SECONDS = 24 * 3600
STREAK_PASS_SECONDS = DAY_SECONDS

#: The pass ladder (Pillar 3), owned here, NOT in `payments.py`. Monthly VIP is
#: ₨250 per `docs/MONETIZATION_AND_FLEET_PLAN.md:46`, ruled authoritative by Q4;
#: `payments.PLAN_DEFAULTS` keeps its own (200) value untouched and Q4 reconciles.
REDEEM_COIN_COSTS = {"day": 30, "weekend": 70, "monthly_vip": 200}
MONTHLY_SECONDS = 30 * DAY_SECONDS
PASS_LADDER = {
    "day": {"pkr": 20, "coins": REDEEM_COIN_COSTS["day"],
            "duration_seconds": DAY_SECONDS},
    "weekend": {"pkr": 50, "coins": REDEEM_COIN_COSTS["weekend"],
               "duration": "next_local_weekend_end"},
    "monthly_vip": {"pkr": 250, "coins": REDEEM_COIN_COSTS["monthly_vip"],
                    "duration_seconds": MONTHLY_SECONDS},
}
AD_SLOTS = frozenset({"preroll", "app_open", "native_card"})

_META_KEY = "engagement_schema_version"


# ── errors ────────────────────────────────────────────────────────────────────


class EngagementError(Exception):
    """Base for every refusal this module makes; callers catch this, not the DB."""


class UnknownAccount(EngagementError):
    def __init__(self, account_id):
        super().__init__(f"no such account: {account_id!r}")


class BadAmount(EngagementError):
    pass


class BadSource(EngagementError):
    """A grant that tried to come from a client. There is no such path."""

    default_detail = "a coin may only be minted by a server or admin source"


class BadReason(EngagementError):
    pass


class InsufficientCoins(EngagementError):
    def __init__(self, account_id, balance, cost):
        super().__init__(
            f"account {account_id} has {balance} coins, needs {cost}")


class RewardedCapReached(EngagementError):
    def __init__(self, account_id, count):
        super().__init__(
            f"account {account_id} already has {count} rewarded grants today "
            f"(cap {REWARDED_DAILY_CAP})")


class UnknownPlan(EngagementError):
    def __init__(self, plan):
        super().__init__(f"unknown pass plan: {plan!r}")


class BadSlot(EngagementError):
    pass


# ── paths and connections (mirror accounts.py) ────────────────────────────────


def default_db_path() -> Path:
    """The engagement tables live in the user-state DB — resolve through
    `accounts` so the two modules can never drift to two different files."""
    return accounts.default_db_path()


def _prepare(conn: sqlite3.Connection, busy_timeout_ms: int) -> None:
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass
    # Per-connection, and required for the ON DELETE CASCADE + FK integrity.
    conn.execute("PRAGMA foreign_keys = ON")


def connect(db_path=None, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
           install_schema: bool = True) -> sqlite3.Connection:
    """Open (creating if needed) the user-state DB with the engagement schema
    installed, ready to use."""
    path = Path(db_path) if db_path is not None else default_db_path()
    if str(path) != ":memory:":
        parent = Path(path).parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=busy_timeout_ms / 1000.0)
    conn.row_factory = sqlite3.Row
    _prepare(conn, busy_timeout_ms)
    if install_schema:
        ensure_schema(conn)
        conn.commit()
    return conn


@contextlib.contextmanager
def _borrow(handle):
    """Accept a `sqlite3.Connection` or a db path, yield a connection. Same
    contract as `accounts._borrow`: an operator CLI names a file, the HTTP host
    hands a per-thread connection; a path we opened is closed on the way out, a
    connection the caller handed us never is."""
    if isinstance(handle, sqlite3.Connection):
        yield handle
        return
    conn = connect(handle)
    try:
        yield conn
    finally:
        conn.close()


def _commit(conn: sqlite3.Connection) -> None:
    try:
        conn.commit()
    except sqlite3.Error:
        pass


def _now(now) -> float:
    return float(time.time() if now is None else now)


# ── schema ────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS coin_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Entitlement state, not a receipt: a deleted account's coins die with it
    -- (no cash value to preserve, per §A), so this cascades. The money ledger
    -- in `payments` deliberately does NOT — the asymmetry is the point.
    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    delta INTEGER NOT NULL,              -- signed; earn > 0, spend < 0; whole coins
    reason TEXT NOT NULL,
    ref TEXT,                            -- pass/streak/admin reference; never a title
    idempotency_key TEXT UNIQUE,         -- NULL allowed; a duplicate key = the SAME grant
    source TEXT NOT NULL,                -- 'server' | 'admin' — never 'client'
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS streak_state (
    account_id INTEGER PRIMARY KEY REFERENCES user_accounts(id) ON DELETE CASCADE,
    tz TEXT NOT NULL DEFAULT 'Asia/Karachi',
    day_boundary_hour INTEGER NOT NULL DEFAULT 4,
    last_counted_day TEXT,               -- 'YYYY-MM-DD' bucket last credited, or NULL
    current_streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    last_grant_reason TEXT,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ad_cadence_state (
    account_id INTEGER PRIMARY KEY REFERENCES user_accounts(id) ON DELETE CASCADE,
    last_preroll_at REAL NOT NULL DEFAULT 0,
    last_app_open_at REAL NOT NULL DEFAULT 0,
    native_poster_cursor INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
"""

#: A later release declares new columns here and `_migrate_columns` installs them
#: with a guarded `ALTER` + backfill. Empty today: every column is in the DDL.
_NEW_COLUMNS: dict = {}

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_coin_ledger_append_only_update
BEFORE UPDATE ON coin_ledger
BEGIN
    SELECT RAISE(ABORT, 'coin_ledger is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_coin_ledger_append_only_delete
BEFORE DELETE ON coin_ledger
BEGIN
    SELECT RAISE(ABORT, 'coin_ledger is append-only: DELETE forbidden');
END;
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_coin_ledger_account
    ON coin_ledger(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_coin_ledger_rewarded
    ON coin_ledger(account_id, reason, created_at);
CREATE INDEX IF NOT EXISTS idx_streak_state_updated ON streak_state(updated_at);
"""


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (name,)).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set:
    if not _has_table(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_schema(conn: sqlite3.Connection) -> dict:
    """Install or migrate the engagement schema. Idempotent and additive —
    nothing is dropped, no row is rewritten. Runs `accounts.ensure_schema` first
    so the FK parent (`user_accounts`) exists whichever module opens the DB first.

    Order is the `accounts` lesson: DDL → column ALTERs → triggers → indexes, with
    any index or trigger that could touch a migrated column installed AFTER the
    ALTER block, never inside the DDL script. Returns what was added so an
    operator sees that a migration happened."""
    accounts.ensure_schema(conn)
    conn.executescript(DDL)
    added = _migrate_columns(conn)
    conn.executescript(_TRIGGERS)
    conn.executescript(_INDEXES)
    conn.execute(
        "INSERT OR REPLACE INTO user_state_meta(key, value) VALUES(?, ?)",
        (_META_KEY, str(SCHEMA_VERSION)))
    return {"schema_version": SCHEMA_VERSION, "added_columns": added}


def _migrate_columns(conn: sqlite3.Connection) -> list:
    added = []
    for table, wanted in _NEW_COLUMNS.items():
        if not _has_table(conn, table):
            continue
        have = _columns(conn, table)
        for column, (decl, backfill) in wanted.items():
            if column in have:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            if backfill:
                conn.execute(f"UPDATE {table} {backfill}")
            added.append(f"{table}.{column}")
    return added


def schema_version(conn_or_path) -> int:
    """The engagement schema version stamped in the file; `0` if never installed."""
    with _borrow(conn_or_path) as conn:
        if not _has_table(conn, "user_state_meta"):
            return 0
        row = conn.execute(
            "SELECT value FROM user_state_meta WHERE key = ?", (_META_KEY,)).fetchone()
        try:
            return int(row[0]) if row else 0
        except (TypeError, ValueError):
            return 0


# ── the day-bucket math (Pillar 3 / timezone) ─────────────────────────────────


def _clamp_hour(value) -> int:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return DAY_BOUNDARY_HOUR_DEFAULT
    return hour if 0 <= hour <= 23 else DAY_BOUNDARY_HOUR_DEFAULT


def _tzinfo(tz: str):
    """The zone a civil day is measured in. Falls back to a fixed UTC+05:00 for
    Karachi rather than the machine's local zone: without a tz database the
    streak must still mean the same day to every Pakistani user, wherever the
    server physically sits."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz)
    except Exception:
        return timezone(timedelta(hours=5))


def _day_bucket(now_epoch, tz: str = STREAK_TZ_DEFAULT,
                boundary_hour: int = DAY_BOUNDARY_HOUR_DEFAULT) -> str:
    """The civil-day bucket an instant falls in, given a local rollover hour.

    bucket = calendar date of (`now` shifted back by the boundary). With the
    default 04:00 rollover, 02:00 PKT on day D lands in bucket D-1, and 05:00
    PKT on day D lands in D — so a session that runs past midnight neither
    resets the streak nor earns a second 'Day 1' for the same evening."""
    info = _tzinfo(tz)
    local = datetime.fromtimestamp(float(now_epoch), info)
    shifted = local - timedelta(hours=_clamp_hour(boundary_hour))
    return shifted.strftime("%Y-%m-%d")


def _bucket_start_epoch(bucket: str, tz: str, boundary_hour: int) -> float:
    """The instant a bucket begins: the rollover hour on that local calendar day."""
    info = _tzinfo(tz)
    naive = datetime.strptime(bucket, "%Y-%m-%d").replace(
        hour=_clamp_hour(boundary_hour), minute=0, second=0, microsecond=0)
    return naive.replace(tzinfo=info).timestamp()


def _bucket_diff_days(later: str, earlier: str) -> int:
    """Whole calendar days between two 'YYYY-MM-DD' buckets (later - earlier)."""
    return (datetime.strptime(later, "%Y-%m-%d").date()
            - datetime.strptime(earlier, "%Y-%m-%d").date()).days


def _weekend_expiry(now_epoch, tz: str = STREAK_TZ_DEFAULT) -> float:
    """End of the coming local weekend = the next Monday 00:00 local. A weekend
    pass bought on Friday runs to Sunday night; one bought midweek runs to the
    coming weekend's end. Never a past instant (a Monday call rolls to the next
    Monday)."""
    info = _tzinfo(tz)
    local = datetime.fromtimestamp(float(now_epoch), info)
    days = (0 - local.weekday()) % 7
    if days == 0:
        days = 7
    target = (local + timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return target.timestamp()


# ── caps (Pillar 1) ───────────────────────────────────────────────────────────


def resolve_caps(overrides=None) -> dict:
    """Merge an operator's overrides (from `app_remote_config` in deliverable (c))
    over the defaults, bounding every value. A zero/negative override keeps the
    default — a cap of 0 never means 'unlimited'; an over-large one is clamped."""
    caps = dict(CAPS_DEFAULT)
    for key, value in (overrides or {}).items():
        if key not in caps:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        caps[key] = min(number, CAP_MAX[key])
    return caps


# ── the wallet (Pillar 2) ─────────────────────────────────────────────────────


def _require_account(conn: sqlite3.Connection, account_id) -> None:
    if not conn.execute(
            "SELECT 1 FROM user_accounts WHERE id = ? LIMIT 1",
            (int(account_id),)).fetchone():
        raise UnknownAccount(account_id)


def _positive_int(value, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise BadAmount(f"{name} must be a whole number of coins")
    if number <= 0:
        raise BadAmount(f"{name} must be a positive whole number of coins")
    return number


def _insert_ledger(conn: sqlite3.Connection, *, account_id, delta, reason,
                   source, ref, idempotency_key, created_at) -> int:
    """One ledger row, or none if `idempotency_key` already exists. Returns the
    number of rows actually written (1 = fresh, 0 = deduplicated replay)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO coin_ledger"
        "(account_id, delta, reason, ref, idempotency_key, source, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (int(account_id), int(delta), str(reason), ref, idempotency_key,
         str(source), float(created_at)))
    return cur.rowcount


def _balance(conn: sqlite3.Connection, account_id) -> int:
    """The wallet is derived, never stored: a whole-number `SUM(delta)`."""
    return int(conn.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM coin_ledger WHERE account_id = ?",
        (int(account_id),)).fetchone()[0])


def coin_balance(conn_or_path, account_id) -> int:
    with _borrow(conn_or_path) as conn:
        return _balance(conn, account_id)


def _enforce_rewarded_cap(conn: sqlite3.Connection, account_id, moment: float,
                          *, tz, day_boundary_hour) -> None:
    if reason_cap_disabled():
        return
    tz = tz or STREAK_TZ_DEFAULT
    boundary = DAY_BOUNDARY_HOUR_DEFAULT if day_boundary_hour is None else day_boundary_hour
    bucket = _day_bucket(moment, tz, boundary)
    start = _bucket_start_epoch(bucket, tz, boundary)
    count = int(conn.execute(
        "SELECT COUNT(*) FROM coin_ledger"
        " WHERE account_id = ? AND reason = 'rewarded_ad'"
        " AND created_at >= ? AND created_at < ?",
        (int(account_id), start, start + DAY_SECONDS)).fetchone()[0])
    if count >= REWARDED_DAILY_CAP:
        raise RewardedCapReached(int(account_id), count)


def reason_cap_disabled() -> bool:
    """A single, documented switch for tests to lift the daily cap. Off always in
    production; kept here so no test needs to fake 10 rows to reach the boundary."""
    return os.environ.get("RADD_ENGAGEMENT_NO_REWARDED_CAP") == "1"


def grant_coins(conn_or_path, account_id, *, amount, reason, source="server",
                ref=None, idempotency_key=None, now=None, tz=None,
                day_boundary_hour=None) -> dict:
    """Credit the wallet. The ONLY ways a coin comes into existence.

    * `source` must be `server` or `admin`; a client claim never reaches here (the
      `usage_stats` telemetry route is not wired to this function).
    * `reason='rewarded_ad'` is capped at `REWARDED_DAILY_CAP` grants per
      day-bucket, so a viewer cannot farm unlimited coins from ads.
    * `idempotency_key` (e.g. the ad network's callback id) makes a retry land as
      one grant.
    """
    amount = _positive_int(amount, "amount")
    if source not in SERVER_SOURCES:
        raise BadSource(f"{source!r}: {BadSource.default_detail}")
    if reason not in LEDGER_REASONS:
        raise BadReason(f"unknown ledger reason: {reason!r}")
    moment = _now(now)
    with _borrow(conn_or_path) as conn:
        _require_account(conn, account_id)
        if reason == "rewarded_ad":
            _enforce_rewarded_cap(conn, account_id, moment, tz=tz,
                                  day_boundary_hour=day_boundary_hour)
        wrote = _insert_ledger(
            conn, account_id=account_id, delta=amount, reason=reason,
            source=source, ref=ref, idempotency_key=idempotency_key,
            created_at=moment)
        balance = _balance(conn, account_id)
        _commit(conn)
    return {"account_id": int(account_id), "delta": amount, "reason": reason,
            "granted": int(wrote), "idempotent": wrote == 0, "balance": balance}


def spend_coins(conn_or_path, account_id, *, amount, reason="redeem_pass",
                ref=None, idempotency_key=None, now=None) -> dict:
    """Debit the wallet — but only as much as is there.

    The check and the write are one `INSERT … SELECT … WHERE balance >= cost`
    statement, so the balance can never go negative even under two simultaneous
    redemptions. `InsufficientCoins` is raised when the guarded insert writes no
    row. An `idempotency_key` that already exists is reported as already applied
    with no second deduction."""
    amount = _positive_int(amount, "amount")
    if reason not in SPEND_REASONS:
        raise BadReason(f"a spend must be one of {sorted(SPEND_REASONS)}, not {reason!r}")
    moment = _now(now)
    with _borrow(conn_or_path) as conn:
        _require_account(conn, account_id)
        if idempotency_key is not None and conn.execute(
                "SELECT 1 FROM coin_ledger WHERE idempotency_key = ? LIMIT 1",
                (idempotency_key,)).fetchone():
            return {"account_id": int(account_id), "spent": 0,
                    "already_applied": True, "balance": _balance(conn, account_id)}
        cur = conn.execute(
            "INSERT INTO coin_ledger"
            "(account_id, delta, reason, ref, idempotency_key, source, created_at)"
            " SELECT ?, ?, ?, ?, ?, 'server', ?"
            " WHERE (SELECT COALESCE(SUM(delta), 0) FROM coin_ledger"
            "        WHERE account_id = ?) >= ?",
            (int(account_id), -amount, reason, ref, idempotency_key, moment,
             int(account_id), amount))
        if cur.rowcount == 0:
            raise InsufficientCoins(int(account_id), _balance(conn, account_id), amount)
        balance = _balance(conn, account_id)
        _commit(conn)
    return {"account_id": int(account_id), "spent": amount, "reason": reason,
            "already_applied": False, "balance": balance}


def ledger(conn_or_path, account_id, *, limit: int = 50) -> list:
    """The account's history, newest first — for the app's wallet screen and the
    operator's audit view. Read-only; a row can never be edited or deleted."""
    limit = max(1, min(int(limit), 200))
    with _borrow(conn_or_path) as conn:
        rows = conn.execute(
            "SELECT id, delta, reason, ref, source, created_at FROM coin_ledger"
            " WHERE account_id = ? ORDER BY id DESC LIMIT ?",
            (int(account_id), limit)).fetchall()
    return [{"id": int(r["id"]), "delta": int(r["delta"]), "reason": str(r["reason"]),
             "ref": r["ref"], "source": str(r["source"]),
             "created_at": float(r["created_at"] or 0)} for r in rows]


# ── the streak (Pillar 3) ─────────────────────────────────────────────────────


def streak_state(conn_or_path, account_id) -> dict:
    with _borrow(conn_or_path) as conn:
        row = conn.execute(
            "SELECT * FROM streak_state WHERE account_id = ?",
            (int(account_id),)).fetchone()
    if row is None:
        return {"account_id": int(account_id), "current_streak": 0,
                "best_streak": 0, "last_counted_day": None,
                "tz": STREAK_TZ_DEFAULT,
                "day_boundary_hour": DAY_BOUNDARY_HOUR_DEFAULT}
    return {"account_id": int(account_id),
            "current_streak": int(row["current_streak"]),
            "best_streak": int(row["best_streak"]),
            "last_counted_day": row["last_counted_day"],
            "tz": str(row["tz"]), "day_boundary_hour": int(row["day_boundary_hour"])}


def record_engagement_day(conn_or_path, account_id, *, now=None, tz=None,
                          day_boundary_hour=None, pass_secret=None) -> dict:
    """Advance the streak for the current day-bucket. The only mutator; returns the
    transition so the caller never has to guess.

    * same bucket already credited → `same_day_noop` (no grant, no increment);
    * exactly one bucket after the last → `advanced` (current += 1);
    * a gap of ≥2 buckets, or a first-ever day → `reset` / `started` (current = 1);
    * crossing a milestone grants the ladder coin (ledger, idempotent), and the
      Day-7 milestone mints a signed 24 h pass via `redact.mint_vip_pass` when a
      `pass_secret` is supplied.

    The day is claimed with one guarded `UPDATE … WHERE last_counted_day IS ?`, so
    two concurrent calls for the same account cannot both credit the same bucket or
    mint the same pass twice."""
    moment = _now(now)
    tz = tz or STREAK_TZ_DEFAULT
    boundary = DAY_BOUNDARY_HOUR_DEFAULT if day_boundary_hour is None else day_boundary_hour
    with _borrow(conn_or_path) as conn:
        _require_account(conn, account_id)
        conn.execute(
            "INSERT OR IGNORE INTO streak_state"
            "(account_id, tz, day_boundary_hour, updated_at) VALUES(?,?,?,?)",
            (int(account_id), tz, _clamp_hour(boundary), moment))
        row = conn.execute(
            "SELECT * FROM streak_state WHERE account_id = ?",
            (int(account_id),)).fetchone()
        # The stored zone and rollover own the meaning of "day"; an arg that
        # disagrees with the stored row does not silently redefine history.
        zone = str(row["tz"] or tz)
        bound = _clamp_hour(row["day_boundary_hour"])
        bucket = _day_bucket(moment, zone, bound)
        last = row["last_counted_day"]
        current = int(row["current_streak"])
        best = int(row["best_streak"])
        if last == bucket:
            return {"account_id": int(account_id), "status": "same_day_noop",
                    "current_streak": current, "best_streak": best,
                    "bucket": bucket, "granted_coins": 0, "pass": None}
        if last is None:
            new_current, status = 1, "started"
        else:
            gap = _bucket_diff_days(bucket, last)
            if gap == 1:
                new_current, status = current + 1, "advanced"
            else:
                new_current, status = 1, "reset"
        new_best = max(best, new_current)
        claimed = conn.execute(
            "UPDATE streak_state SET current_streak = ?, best_streak = ?,"
            " last_counted_day = ?, last_grant_reason = ?, updated_at = ?"
            " WHERE account_id = ? AND last_counted_day IS ?",
            (new_current, new_best, bucket, status, moment, int(account_id), last))
        if claimed.rowcount == 0:
            fresh = conn.execute(
                "SELECT current_streak, best_streak FROM streak_state WHERE account_id = ?",
                (int(account_id),)).fetchone()
            return {"account_id": int(account_id), "status": "same_day_noop",
                    "current_streak": int(fresh["current_streak"]),
                    "best_streak": int(fresh["best_streak"]),
                    "bucket": bucket, "granted_coins": 0, "pass": None}
        granted = 0
        if new_current in STREAK_GRANTS_COINS:
            coins = STREAK_GRANTS_COINS[new_current]
            _insert_ledger(
                conn, account_id=account_id, delta=coins, reason="streak_day",
                source="server", ref=f"streak-day-{new_current}",
                idempotency_key=f"streak:{account_id}:{bucket}:coins",
                created_at=moment)
            granted = coins
        pass_token, pass_expires = None, None
        if new_current == STREAK_PASS_DAY and pass_secret:
            # `redact.mint_vip_pass` packs the expiry as a signed 64-bit int, so
            # the token's own resolution is whole seconds — report what the token
            # actually says, not a float that a round trip would not reproduce.
            pass_expires = float(int(moment + STREAK_PASS_SECONDS))
            pass_token = redact.mint_vip_pass(pass_expires, pass_secret)
        _commit(conn)
    return {"account_id": int(account_id), "status": status,
            "current_streak": new_current, "best_streak": new_best,
            "bucket": bucket, "granted_coins": granted,
            "pass": pass_token, "pass_expires_at": pass_expires}


# ── the pass ladder (Pillar 3): redeem coins for a signed pass ────────────────


def pass_ladder() -> dict:
    """The published price ladder — read by the app and (in deliverable c) the
    admin card. Monthly VIP is ₨250 per the plan doc (authoritative), independent
    of `payments.PLAN_DEFAULTS`, which is left untouched."""
    return {name: dict(spec) for name, spec in PASS_LADDER.items()}


def redeem_pass(conn_or_path, account_id, *, plan, pass_secret, now=None,
                tz=None, idempotency_key=None) -> dict:
    """Turn coins into a signed VIP pass. A coin spend first (refusing
    `InsufficientCoins` if the wallet is short), then a capability token minted
    with `redact.mint_vip_pass` — honoured on `/api/v1/download` and unforgeable
    and non-replayable after expiry (M-MON-02). Coins are spendable ONLY on these
    passes: there is no cash-out path anywhere in this module (§A)."""
    if plan not in PASS_LADDER:
        raise UnknownPlan(plan)
    if not pass_secret:
        raise EngagementError("a pass must be signed with a secret")
    moment = _now(now)
    cost = int(PASS_LADDER[plan]["coins"])
    if idempotency_key is None:
        idempotency_key = f"redeem:{account_id}:{plan}:{int(moment)}"
    spend = spend_coins(conn_or_path, account_id, amount=cost, reason="redeem_pass",
                        ref=plan, idempotency_key=idempotency_key, now=moment)
    spec = PASS_LADDER[plan]
    if plan == "weekend":
        expires = _weekend_expiry(moment, tz or STREAK_TZ_DEFAULT)
    else:
        expires = moment + int(spec["duration_seconds"])
    expires = float(int(expires))   # the signed token's resolution is whole seconds
    token = redact.mint_vip_pass(expires, pass_secret)
    return {"plan": plan, "cost": cost, "balance": spend["balance"],
            "already_applied": spend["already_applied"], "pass": token,
            "expires_at": expires}


# ── ad cadence, server-side (Pillar 1) ────────────────────────────────────────


def cadence_state(conn_or_path, account_id) -> dict:
    with _borrow(conn_or_path) as conn:
        row = conn.execute(
            "SELECT * FROM ad_cadence_state WHERE account_id = ?",
            (int(account_id),)).fetchone()
    if row is None:
        return {"account_id": int(account_id), "last_preroll_at": 0.0,
                "last_app_open_at": 0.0, "native_poster_cursor": 0}
    return {"account_id": int(account_id),
            "last_preroll_at": float(row["last_preroll_at"] or 0),
            "last_app_open_at": float(row["last_app_open_at"] or 0),
            "native_poster_cursor": int(row["native_poster_cursor"] or 0)}


def ad_grant(conn_or_path, account_id, *, slot, now=None, caps=None) -> dict:
    """Ask the server whether an ad slot may fire now, and record the frequency.

    Enforcement is server-side first: a phone that ignores the cap still cannot be
    handed a second pre-roll inside the window, and the reply carries
    `next_eligible_at` so a well-behaved client knows when to come back. A `0`
    cap never means 'unlimited' — `resolve_caps` turns it into the default."""
    if slot not in AD_SLOTS:
        raise BadSlot(f"unknown ad slot: {slot!r}")
    resolved = resolve_caps(caps)
    moment = _now(now)
    with _borrow(conn_or_path) as conn:
        _require_account(conn, account_id)
        conn.execute(
            "INSERT OR IGNORE INTO ad_cadence_state(account_id) VALUES(?)",
            (int(account_id),))
        row = conn.execute(
            "SELECT * FROM ad_cadence_state WHERE account_id = ?",
            (int(account_id),)).fetchone()
        allow = False
        next_eligible_at = None
        cursor = int(row["native_poster_cursor"] or 0)
        if slot == "native_card":
            cursor += 1
            if cursor >= resolved["ad_native_card_every_posters"]:
                allow, cursor = True, 0
            conn.execute(
                "UPDATE ad_cadence_state SET native_poster_cursor = ?, updated_at = ?"
                " WHERE account_id = ?", (cursor, moment, int(account_id)))
        else:
            column = "last_preroll_at" if slot == "preroll" else "last_app_open_at"
            gap = resolved["ad_preroll_min_gap_minutes" if slot == "preroll"
                          else "ad_app_open_min_gap_minutes"] * 60
            last = float(row[column] or 0)
            if last == 0 or moment - last >= gap:
                allow = True
                conn.execute(
                    f"UPDATE ad_cadence_state SET {column} = ?, updated_at = ?"
                    " WHERE account_id = ?", (moment, moment, int(account_id)))
            else:
                next_eligible_at = last + gap
        _commit(conn)
    return {"account_id": int(account_id), "slot": slot, "allow": allow,
            "now": moment, "next_eligible_at": next_eligible_at,
            "native_poster_cursor": cursor}


# ── the app read projection (defaults now; admin knobs override in deliverable c) ─


def remote_view() -> dict:
    """The shape the phone reads under `/api/v1/app/remote-config.engagement`.
    Exposed from defaults today so the client can integrate against it now; when
    the admin columns land in (c), those override these values. Publishes costs and
    grant sizes as data — the whole point of the no-deception rule is that a user
    can see the real numbers, and there is no field here a coin could be cashed
    out through."""
    return {
        "wallet": {
            "coin_per_rewarded_ad": COINS_PER_REWARDED_AD,
            "rewarded_daily_cap": REWARDED_DAILY_CAP,
            "redeem_coin_costs": dict(REDEEM_COIN_COSTS),
        },
        "streak": {
            "grants": {"day1_coins": STREAK_GRANTS_COINS[1],
                       "day3_coins": STREAK_GRANTS_COINS[3],
                       "day7_pass_seconds": STREAK_PASS_SECONDS},
            "tz": STREAK_TZ_DEFAULT,
            "day_boundary_hour": DAY_BOUNDARY_HOUR_DEFAULT,
        },
        "passes": {name: {"pkr": int(spec["pkr"]), "coins": int(spec["coins"]),
                          "duration_seconds": spec.get("duration_seconds")}
                   for name, spec in PASS_LADDER.items()},
        "cadence": dict(CAPS_DEFAULT),
    }


def account_overview(conn_or_path, account_id) -> dict:
    """Everything the app shows about one account's engagement, in one read."""
    with _borrow(conn_or_path) as conn:
        balance = _balance(conn, account_id)
    return {"account_id": int(account_id), "balance": balance,
            "streak": streak_state(conn_or_path, account_id),
            "cadence": cadence_state(conn_or_path, account_id)}


# ── self-check: `python3 -S Fast_Fetch/engagement.py` (temp file, no port) ─────


def _selfcheck() -> int:
    import tempfile
    from contextlib import closing
    secret = "selfcheck-secret"
    with tempfile.TemporaryDirectory() as work:
        state = Path(work) / "user_state.db"
        with closing(accounts.connect(state)) as conn:
            ensure_schema(conn)
            conn.commit()
            account_id = accounts.create_account(conn, key="y" * 20)["account_id"]

            # append-only: an UPDATE on the ledger must abort
            grant_coins(conn, account_id, amount=10, reason="admin_grant",
                        source="admin", ref="seed")
            try:
                conn.execute("UPDATE coin_ledger SET delta = 999 WHERE account_id = ?",
                             (account_id,))
                raise AssertionError("append-only trigger did not fire on UPDATE")
            except sqlite3.Error:
                pass

            # no client source
            try:
                grant_coins(conn, account_id, amount=50, reason="rewarded_ad",
                            source="client")
                raise AssertionError("client source was accepted")
            except BadSource:
                pass

            # idempotent grant
            first = grant_coins(conn, account_id, amount=5, reason="rewarded_ad",
                                idempotency_key="cb-1")
            replay = grant_coins(conn, account_id, amount=5, reason="rewarded_ad",
                                 idempotency_key="cb-1")
            assert first["balance"] == replay["balance"] == 15, (first, replay)

            # cannot spend what you do not have
            try:
                spend_coins(conn, account_id, amount=10_000)
                raise AssertionError("overspend was allowed")
            except InsufficientCoins:
                pass

            # top up to afford a pass, then redeem it (coins -> signed capability)
            grant_coins(conn, account_id, amount=30, reason="admin_grant",
                        source="admin", ref="topup")
            redeemed = redeem_pass(conn, account_id, plan="day", pass_secret=secret)
            assert redact.parse_vip_pass(redeemed["pass"], secret, now=moment_before(
                redeemed["expires_at"])) == redeemed["expires_at"]
            assert redact.parse_vip_pass(redeemed["pass"], secret,
                                         now=redeemed["expires_at"] + 1) is None

            # streak: a 02:00 PKT day belongs to the previous bucket
            tick = record_engagement_day(conn, account_id, now=_epoch_at(
                "2026-01-06T02:00:00", "+05:00"))
            assert tick["bucket"] == "2026-01-05", tick
            again = record_engagement_day(conn, account_id, now=_epoch_at(
                "2026-01-05T23:00:00", "+05:00"))
            assert again["status"] == "same_day_noop", again
        print("[.] engagement selfcheck OK — append-only, no-client-coin, "
              "idempotent, no-overspend, signed pass, PKT day bucket")
    return 0


def moment_before(expires: float) -> float:
    return expires - 1.0


def _epoch_at(iso_local: str, offset: str) -> float:
    """Epoch seconds for a wall-clock string with an explicit UTC offset — so the
    self-check pins a Pakistani local time without depending on the host zone."""
    return datetime.strptime(f"{iso_local}{offset}",
                             "%Y-%m-%dT%H:%M:%S%z").timestamp()


if __name__ == "__main__":
    raise SystemExit(_selfcheck())
