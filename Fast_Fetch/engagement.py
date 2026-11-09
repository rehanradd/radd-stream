#!/usr/bin/env python3
"""
Fast_Fetch/engagement.py — the four engagement pillars behind the knobs the admin panel now carries.
════════════════════════════════════════════════════════════════════════════════════════
WHAT THIS IS, STATED PLAINLY
--------------------------------------------------------------------------------
The four earning/engagement mechanisms the owner wants controllable from the admin
panel but that today are literals in the APK (see
`docs/MONETIZATION_PILLARS_SCHEMA.md`, the design this file implements):

  1. **Ad-cadence caps as data** — pre-roll 1/25 min, native card 1/12 posters,
     app-open 1/4 h. The caps are config (`CAPS_DEFAULT`, overridable from
     `app_remote_config` via `admin_panel.MONETIZATION_FIELDS`); `ad_cadence_state`
     is the server-side *frequency* those
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
    "rewarded_ad", "streak_day", "redeem_pass", "redeem_download",
    "redeem_theme", "redeem_request", "share", "finish_watch",
    "admin_grant", "refund",
})
#: Debits. Redemption of a pass, and a `refund` that claws back a wrong credit
#: (a compensating row — the append-only way to undo a mistake; a refund that
#: *returns* coins after a failed spend is instead a positive `grant_coins`).
SPEND_REASONS = frozenset({"redeem_pass", "redeem_download", "redeem_theme",
                            "redeem_request", "refund"})

#: Coins credited per *server-verified* rewarded completion (q3 owns the admin
#: knob; this is the default it overrides). `coin_value_pkr` stays q3's.
COINS_PER_REWARDED_AD = 5
#: A viewer cannot farm unlimited coins from ads: cap rewarded grants per day-bucket.
REWARDED_DAILY_CAP = 10

#: The velocity guard: how many credit grants one account may take in a
#: rolling window before the funnel refuses. Normal earning is slow — a
#: rewarded ad, a finished title, a share, a streak day — so twenty grants
#: in ten minutes is already far above any real viewing session (the
#: existing tests pin eleven: ten ads plus a streak grant at one timestamp),
#: and a script hammering the earn routes trips it in seconds. The
#: rewarded-ad daily cap is the tighter rule for ads; this one catches every
#: reason at once, including ones no per-reason cap exists for. Admin grants
#: are exempt: the operator's own hand is not the farming vector, and the
#: ledger itself is the audit trail for those.
VELOCITY_WINDOW_SECONDS = 600.0
VELOCITY_MAX_GRANTS = 20

#: Streak clock: Pakistani civil day by default. `day_boundary_hour` is the local
#: rollover — activity before it counts toward the previous day.
STREAK_TZ_DEFAULT = "Asia/Karachi"
DAY_BOUNDARY_HOUR_DEFAULT = 4
#: Coin grants at these streak milestones (plan Pillar 2, lines 33–35), now the
#: 7-day daily check-in ladder the owner approved 2026-11-07: 10/20/30/40/50/70
#: and a 150-coin jackpot on day 7. A streak past day 7 keeps counting but grants
#: nothing further until it resets — the ladder is seven days, not a cycle.
STREAK_GRANTS_COINS = {1: 10, 2: 20, 3: 30, 4: 40, 5: 50, 6: 70, 7: 150}
#: The Day-7 milestone mints a 24-hour ad-free pass as well as the 150 coins.
STREAK_PASS_DAY = 7
DAY_SECONDS = 24 * 3600
STREAK_PASS_SECONDS = DAY_SECONDS

#: The pass ladder (Pillar 3), owned here, NOT in `payments.py`. Monthly VIP is
#: ₨250 per `docs/MONETIZATION_AND_FLEET_PLAN.md:46`, ruled authoritative by Q4;
#: `payments.PLAN_DEFAULTS` keeps its own (200) value untouched and Q4 reconciles.
#: The 24-hour VIP pass costs 500 coins by the owner's daily check-in plan
#: (2026-11-07): ten days of check-ins for one day of VIP, so a pass is earned,
#: not given away after two mornings. The weekend and monthly tiers keep their
#: shipped prices; the operator re-prices any tier with its knob
#: (`coin_redeem_day`, `coin_redeem_weekend`, `coin_redeem_monthly`).
REDEEM_COIN_COSTS = {"day": 500, "weekend": 70, "monthly_vip": 200}

#: One direct download — a free viewer skipping the web shortener for one
#: movie — costs 100 coins by the same plan. The operator re-prices it with
#: the `coin_redeem_download` knob, resolved by `resolve_download_credit`.
DOWNLOAD_CREDIT_COINS = 100
#: A bought credit stays good for a day: the viewer buys it and taps the link,
#: so the window only covers a browser that opens late, not a coin saved
#: for a later film.
DOWNLOAD_CREDIT_SECONDS = 86_400.0

#: One share of a movie pays 25 coins, once a day (daily check-in Build 5).
#: One finished title pays 15, once per title ever. One requested movie costs
#: 300; one player theme costs 250. Each has its operator knob
#: (`coin_share`, `coin_finish_watch`, `coin_redeem_request`,
#: `coin_redeem_theme`), resolved by the functions below — a stored 0 or an
#: unparseable paste means the shipped number, never free.
SHARE_COINS = 25
FINISH_WATCH_COINS = 15
#: A title counts as finished at 90% watched: the player may never report
#: exactly 100%, and a viewer who watched nine tenths of a film finished it.
FINISH_WATCH_FRACTION = 0.9
#: The finish-watch grant also needs the server to have *seen* the watching:
#: the span between the first and the latest applied progress report must be
#: at least this fraction of the finished span (0.9 x duration). 0.5 is the
#: playback-speed tolerance — the player offers up to 4x, and a viewer at 2x
#: legitimately finishes in half the runtime, so the gate demands half the
#: finished span, not the whole of it. A farmer must therefore space reports
#: over ~45% of the runtime per title, in parallel at best, and a single
#: instant "I finished it" claim — span zero — pays nothing. The span is
#: measured on the server's own receipt times in `watch_observations`
#: (`accounts.put_progress` records them); a client clock is a claim, and
#: the span between two claims proves nothing.
FINISH_WATCH_OBSERVED_TOLERANCE = 0.5
REQUEST_MOVIE_COINS = 300
THEME_COINS = 250

#: The player themes coins can buy. `jade` is the shipped look — free, always
#: owned, never sold — so it is not in this table: a theme here is a chrome
#: skin for the player's non-meaning surfaces (plates, rails, icon tints),
#: never a recolour of the meaning-carrying accent, which DESIGN_SYSTEM §9
#: forbids replacing. One price for every theme, resolved by
#: `resolve_theme_coins`.
PURCHASABLE_THEMES = ("midnight", "ember")
MONTHLY_SECONDS = 30 * DAY_SECONDS
#: The ladder is data end to end: each tier carries its price, the rule that says
#: when its pass stops working, and the names of the two `app_remote_config` knobs
#: that let the operator reprice it. Nothing may branch on a tier's *name* —
#: `redeem_pass` used to compute the weekend expiry with `if plan == "weekend"`, so
#: adding a fourth tier meant editing the spender, and a tier whose rule the data
#: did not declare was only discovered after the coins had already been spent.
#: An expiry is now resolved before the spend, so a malformed tier refuses and
#: writes nothing.
PASS_LADDER = {
    "day": {"pkr": 20, "coins": REDEEM_COIN_COSTS["day"],
            "coin_setting": "coin_redeem_day", "pkr_setting": "pass_day_pkr",
            "expiry_rule": "after_seconds", "duration_seconds": DAY_SECONDS},
    "weekend": {"pkr": 50, "coins": REDEEM_COIN_COSTS["weekend"],
                "coin_setting": "coin_redeem_weekend",
                "pkr_setting": "pass_weekend_pkr",
                "expiry_rule": "local_weekend_end"},
    "monthly_vip": {"pkr": 250, "coins": REDEEM_COIN_COSTS["monthly_vip"],
                    "coin_setting": "coin_redeem_monthly",
                    "pkr_setting": "pass_monthly_vip_pkr",
                    "expiry_rule": "after_seconds",
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


class VelocityLimitReached(EngagementError):
    """Too many credit grants in the rolling window: a farming pattern."""

    def __init__(self, account_id, count):
        super().__init__(
            f"account {account_id} already has {count} credit grants in "
            f"{int(VELOCITY_WINDOW_SECONDS)} seconds "
            f"(max {VELOCITY_MAX_GRANTS})")

    #: The route answers 429 with this long to wait before trying again.
    retry_after = int(VELOCITY_WINDOW_SECONDS)


class UnknownPlan(EngagementError):
    def __init__(self, plan):
        super().__init__(f"unknown pass plan: {plan!r}")


class BadLadder(EngagementError):
    """A tier whose own data cannot say when it expires. Refusing this is the
    point: it is raised *before* any coin is spent, so the answer to a broken
    ladder is nothing written, not a debit and no pass."""


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

CREATE TABLE IF NOT EXISTS coin_passes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- A redeemed or streak-minted VIP pass, recorded so `entitlement` and the
    -- download/stream VIP checks can see it: the signed token alone carries no
    -- account, so without this row a pass the server itself minted would not
    -- make its owner VIP anywhere the app looks. Expired rows are dead, not
    -- deleted — the ledger keeps its history and the read is MAX(expires_at).
    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    plan TEXT NOT NULL,                  -- 'day' | 'weekend' | 'monthly_vip' | 'streak_day7'
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS coin_download_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- One direct download, bought with coins: the row is the credit, the token
    -- is only its signed id. `handle` is the opaque download id it was bought
    -- for — a credit for one movie buys no other — and `used_at` is the
    -- single-use guard: the consume is one guarded UPDATE, so two browsers
    -- racing the same token get one file and one refusal.
    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    handle TEXT NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS movie_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- One requested movie, bought with coins: the spend and the queue entry are
    -- two writes of one purchase, so a request that never reached the queue
    -- cost nothing. `title` is the viewer's own words, capped at the route;
    -- `status` is the operator's workflow ('open' | 'indexed' | 'declined').
    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS purchased_themes (
    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    -- One owned player theme: the row IS the ownership, so the app reads what
    -- this account owns from here and never from a claim. The pair is the key
    -- because a theme is bought once and kept — there is nothing to buy twice.
    theme_id TEXT NOT NULL,
    purchased_at REAL NOT NULL,
    PRIMARY KEY (account_id, theme_id)
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
CREATE INDEX IF NOT EXISTS idx_coin_passes_account
    ON coin_passes(account_id, expires_at);
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


# ── the ladder's expiry rules, named by the data that uses them ───────────────

def _expiry_after_seconds(plan: str, spec: dict, moment: float, tz) -> float:
    seconds = spec.get("duration_seconds")
    if seconds is None:
        raise BadLadder(f"tier {plan!r} declares after_seconds with no "
                        "duration_seconds to count")
    if isinstance(seconds, bool):
        # True is 1 to Python, and a pass that lasts one second is not a tier.
        raise BadLadder(f"tier {plan!r} has a duration_seconds that is a flag, "
                        f"not a length: {seconds!r}")
    try:
        number = int(seconds)
    except (TypeError, ValueError):
        raise BadLadder(f"tier {plan!r} has a duration_seconds that is not a whole "
                        f"number of seconds: {seconds!r}")
    if number <= 0:
        # `moment + 0` is an expiry in the past: the pass would mint and read as
        # already dead, so the coins go and nothing is granted. A tier cannot be
        # sold with a length that is not a length.
        raise BadLadder(f"tier {plan!r} has a non-positive duration_seconds: {number}")
    return moment + number


def _expiry_local_weekend_end(plan: str, spec: dict, moment: float, tz) -> float:
    return _weekend_expiry(moment, tz or STREAK_TZ_DEFAULT)


#: The whole vocabulary of expiry a tier may name. A tier that names anything else
#: is a data mistake, and `BadLadder` is what a data mistake answers with — before
#: the spend, never after it.
EXPIRY_RULES = {
    "after_seconds": _expiry_after_seconds,
    "local_weekend_end": _expiry_local_weekend_end,
}


def tier_expiry(plan: str, moment=None, tz=None, ladder=None) -> float:
    """When one tier's pass stops working, resolved from the tier's own data.

    There is no plan name in this function's branches, and that is the point: the
    ladder says how long a pass runs, so adding a tier is an edit to
    :data:`PASS_LADDER` and not an edit to the code that spends coins. Whole
    seconds, because that is the resolution the signed token carries."""
    table = ladder if ladder is not None else PASS_LADDER
    try:
        spec = table[plan]
    except KeyError:
        raise UnknownPlan(plan)
    rule = EXPIRY_RULES.get(str(spec.get("expiry_rule") or ""))
    if rule is None:
        raise BadLadder(f"tier {plan!r} names no expiry rule this module knows: "
                        f"{spec.get('expiry_rule')!r}")
    moment = _now(moment)
    return float(int(rule(plan, spec, moment, tz)))


def resolve_ladder(values=None) -> dict:
    """The ladder as the operator priced it, in one place.

    `values` is the `app_remote_config` row. The coin cost follows the rule every
    other whole-number knob follows: a stored 0 or an unparseable paste is "use
    the shipped number", never "free" and never unlimited. The PKR price is
    published as stored, because a price of 0 here is a deliberate act (a free
    tier) and not a sentinel — but a value that cannot be read at all answers the
    shipped price rather than raising, because a settings row that 500s the price
    block is how a phone ends up showing no price at all.

    This is the only function that turns a settings row into a ladder: the panel's
    public block and `redeem_pass` both read the numbers through it, which is what
    makes "the price a phone is shown" and "the price the server charges" the same
    sentence rather than two that happen to agree today.
    """
    ladder = {}
    for name, shipped in PASS_LADDER.items():
        spec = dict(shipped)
        if values:
            try:
                coins = int(values.get(shipped["coin_setting"]) or 0)
            except (TypeError, ValueError):
                coins = 0
            spec["coins"] = coins if coins > 0 else int(shipped["coins"])
            raw = values.get(shipped["pkr_setting"])
            try:
                spec["pkr"] = int(raw or 0)
            except (TypeError, ValueError):
                spec["pkr"] = int(shipped["pkr"])
        ladder[name] = spec
    return ladder


def resolve_download_credit(values=None) -> int:
    """The direct-download price as the operator priced it, in one place.

    The same whole-number knob rule as the ladder: a stored 0 or an
    unparseable paste is "use the shipped number", never "free". This is the
    only function that turns a settings row into the price — the caps route
    publishes it and `redeem_download_credit` charges it — so the price a
    phone is shown and the price the wallet is debited are one read.
    """
    if not values:
        return int(DOWNLOAD_CREDIT_COINS)
    try:
        coins = int(values.get("coin_redeem_download") or 0)
    except (TypeError, ValueError):
        coins = 0
    return coins if coins > 0 else int(DOWNLOAD_CREDIT_COINS)


def _resolve_coin_knob(values, key: str, shipped: int) -> int:
    """One whole-number coin knob, by the rule every such knob follows: a
    stored 0 or an unparseable paste is "use the shipped number", never "free"
    and never unlimited."""
    if not values:
        return int(shipped)
    try:
        coins = int(values.get(key) or 0)
    except (TypeError, ValueError):
        coins = 0
    return coins if coins > 0 else int(shipped)


def resolve_share_coins(values=None) -> int:
    """The share grant as the operator priced it (the app learns the number
    from the share route's own answer, not from a pre-read)."""
    return _resolve_coin_knob(values, "coin_share", SHARE_COINS)


def resolve_finish_watch_coins(values=None) -> int:
    """The finish-watch grant as the operator priced it (the app learns the
    number from the progress route's own answer, not from a pre-read)."""
    return _resolve_coin_knob(values, "coin_finish_watch", FINISH_WATCH_COINS)


def resolve_request_movie_coins(values=None) -> int:
    """The movie-request price as the operator priced it."""
    return _resolve_coin_knob(values, "coin_redeem_request", REQUEST_MOVIE_COINS)


def resolve_theme_coins(values=None) -> int:
    """The player-theme price as the operator priced it (one price, every theme)."""
    return _resolve_coin_knob(values, "coin_redeem_theme", THEME_COINS)


def themes_projection(values=None) -> dict:
    """The `themes` block a phone reads: every purchasable theme and the one
    price they all share, built from the same resolver the redeem route
    charges through — so the price a picker shows and the price the wallet is
    debited are one read."""
    price = resolve_theme_coins(values)
    return {theme: {"coins": price} for theme in PURCHASABLE_THEMES}


def passes_projection(ladder) -> dict:
    """The `passes` block a phone reads, built from an already-resolved ladder.

    One builder for both prices a client can see: `remote_view()` feeds it the
    shipped ladder, `admin_panel._engagement_public` feeds it the operator's row.
    A key added to a ladder tier therefore appears in the public body without a
    second edit, and the two views cannot be different dictionaries."""
    out = {}
    for name, spec in ladder.items():
        out[name] = {"pkr": int(spec["pkr"]), "coins": int(spec["coins"]),
                     "expiry_rule": str(spec.get("expiry_rule") or ""),
                     "duration_seconds": spec.get("duration_seconds")}
    return out


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


def _rewarded_count(conn: sqlite3.Connection, account_id, moment: float,
                    *, tz, day_boundary_hour) -> int:
    """How many rewarded grants this account has in the current day-bucket — the one
    query the cap and the wallet screen share.

    It is a function rather than four lines inside :func:`_enforce_rewarded_cap`
    because a route that shows a viewer "3 of 10 today" must count the same rows the
    ledger counts before it refuses the fourth. Two `SELECT COUNT(*)` statements with
    the same bucket arithmetic written twice is how a published number and an enforced
    one start disagreeing, and this file has already paid for that once."""
    tz = tz or STREAK_TZ_DEFAULT
    boundary = DAY_BOUNDARY_HOUR_DEFAULT if day_boundary_hour is None else day_boundary_hour
    bucket = _day_bucket(moment, tz, boundary)
    start = _bucket_start_epoch(bucket, tz, boundary)
    return int(conn.execute(
        "SELECT COUNT(*) FROM coin_ledger"
        " WHERE account_id = ? AND reason = 'rewarded_ad'"
        " AND created_at >= ? AND created_at < ?",
        (int(account_id), start, start + DAY_SECONDS)).fetchone()[0])


def rewarded_grants_today(conn_or_path, account_id, *, now=None, tz=None,
                          day_boundary_hour=None) -> int:
    """The account's rewarded-ad grants counted in the civil day the cap uses.

    Read-only, and it reports the count whether or not the cap is lifted
    (:func:`reason_cap_disabled` is a test switch, not a fact about the ledger): the
    number a wallet screen shows is the number of rows, and the number that decides a
    refusal is `REWARDED_DAILY_CAP`'s comparison against this same count.
    """
    with _borrow(conn_or_path) as conn:
        return _rewarded_count(conn, account_id, _now(now), tz=tz,
                               day_boundary_hour=day_boundary_hour)


def _enforce_rewarded_cap(conn: sqlite3.Connection, account_id, moment: float,
                          *, tz, day_boundary_hour) -> None:
    if reason_cap_disabled():
        return
    count = _rewarded_count(conn, account_id, moment, tz=tz,
                            day_boundary_hour=day_boundary_hour)
    if count >= REWARDED_DAILY_CAP:
        raise RewardedCapReached(int(account_id), count)


def _enforce_velocity(conn: sqlite3.Connection, account_id, moment: float) -> None:
    """Refuse a credit when this account has already taken too many in the
    rolling window. Counts every positive ledger row — grants, not spends —
    so no reason can be farmed around the guard by switching reasons. A
    refund that returns coins is a positive row too, and counts: a refund
    loop is the same shape as a grant loop."""
    count = int(conn.execute(
        "SELECT COUNT(*) FROM coin_ledger"
        " WHERE account_id = ? AND delta > 0 AND created_at >= ?",
        (int(account_id), float(moment) - VELOCITY_WINDOW_SECONDS)).fetchone()[0])
    if count >= VELOCITY_MAX_GRANTS:
        raise VelocityLimitReached(int(account_id), count)


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
    * Every reason is velocity-guarded: more than `VELOCITY_MAX_GRANTS`
      credits in `VELOCITY_WINDOW_SECONDS` refuses, whatever the reason —
      a script cannot farm around a per-reason cap by switching reasons.
      Admin grants are exempt from the velocity guard (the operator's own
      hand is not the farming vector); the rewarded-ad cap still binds them.
    * `idempotency_key` (e.g. the ad network's callback id) makes a retry land as
      one grant — and a retry is answered before any cap or velocity check, so a
      harmless retry is never turned into a refusal.
    """
    amount = _positive_int(amount, "amount")
    if source not in SERVER_SOURCES:
        raise BadSource(f"{source!r}: {BadSource.default_detail}")
    if reason not in LEDGER_REASONS:
        raise BadReason(f"unknown ledger reason: {reason!r}")
    moment = _now(now)
    with _borrow(conn_or_path) as conn:
        _require_account(conn, account_id)
        # A retry is not a new grant, whatever the caps say: the key already
        # exists, so answer the already-applied shape before any refusal can
        # turn a harmless retry into an error. The insert below still
        # dedupes the two-at-once race; this read only keeps the common case
        # honest. (Spends already answer replays this way.)
        if idempotency_key is not None and conn.execute(
                "SELECT 1 FROM coin_ledger WHERE idempotency_key = ? LIMIT 1",
                (idempotency_key,)).fetchone():
            return {"account_id": int(account_id), "delta": amount, "reason": reason,
                    "granted": 0, "idempotent": True, "balance": _balance(conn, account_id)}
        if reason == "rewarded_ad":
            _enforce_rewarded_cap(conn, account_id, moment, tz=tz,
                                  day_boundary_hour=day_boundary_hour)
        if source != "admin":
            _enforce_velocity(conn, account_id, moment)
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


def _bounded_count(value, shipped, ceiling) -> int:
    """One whole-number knob, resolved the way every other one on this host is: a
    stored 0, a blank or an unparseable paste means "use the shipped number", and a
    number above `ceiling` is clamped to it. Zero is never free and a cap is never
    unlimited — the sentence `resolve_caps` already states for the ad cadence, here
    because a fat-fingered `1000000` in a bonus field makes every pass free."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(shipped)
    if number <= 0:
        return int(shipped)
    return min(number, int(ceiling))


#: Which `app_remote_config` knob sizes which streak milestone. The milestones are
#: code: a knob can make day 1's reward bigger or smaller, it cannot invent a day.
STREAK_GRANT_SETTINGS = {1: "streak_day1_coins", 2: "streak_day2_coins",
                          3: "streak_day3_coins", 4: "streak_day4_coins",
                          5: "streak_day5_coins", 6: "streak_day6_coins",
                          7: "streak_day7_coins"}
STREAK_PASS_HOURS_SETTING = "streak_day7_pass_hours"
#: A bad save is clamped, not trusted. 10,000 coins is 300 one-day passes, so it is
#: far past any plausible bonus and still below a paste error's damage.
STREAK_GRANT_COINS_MAX = 10_000
#: The day-7 bonus is a *pass*, so its ceiling is the longest pass the ladder sells.
#: Anything a month long is a membership, and a streak reward must not become one.
STREAK_GRANT_HOURS_MAX = MONTHLY_SECONDS // 3600


def resolve_streak_grants(values=None) -> dict:
    """The streak ladder as the operator set it: `{"coins": {day: coins}, "pass_seconds": n}`.

    `values` is the `app_remote_config` row, and this is the same job
    :func:`resolve_ladder` does for prices — one function that turns a settings row
    into the ladder, read by whoever grants the reward. It exists because
    :func:`remote_view` names the divergence it closes: `record_engagement_day` read
    `STREAK_GRANTS_COINS` while `remote_config` published `streak_day1_coins`, so an
    operator lowering the bonus changed the number a phone shows and not the number
    the ledger writes. Wiring it was left for "the route that owns each grant", and
    that route is `POST /api/v2/account/coins/earn`; it resolves the table once and
    passes it in, so the reply and the ledger cannot disagree about what day 1 paid.

    With no row, or a row whose knobs are blank or zero, this answers the shipped
    numbers exactly — so every caller that has never heard of it behaves as before.
    """
    stored = values or {}
    coins = {day: _bounded_count(stored.get(key), STREAK_GRANTS_COINS[day],
                                 STREAK_GRANT_COINS_MAX)
             for day, key in STREAK_GRANT_SETTINGS.items()}
    hours = _bounded_count(stored.get(STREAK_PASS_HOURS_SETTING),
                           STREAK_PASS_SECONDS // 3600, STREAK_GRANT_HOURS_MAX)
    return {"coins": coins, "pass_seconds": hours * 3600}


def record_engagement_day(conn_or_path, account_id, *, now=None, tz=None,
                          day_boundary_hour=None, pass_secret=None,
                          values=None, grants=None) -> dict:
    """Advance the streak for the current day-bucket. The only mutator; returns the
    transition so the caller never has to guess.

    * same bucket already credited → `same_day_noop` (no grant, no increment);
    * exactly one bucket after the last → `advanced` (current += 1);
    * a gap of ≥2 buckets, or a first-ever day → `reset` / `started` (current = 1);
    * crossing a milestone grants the ladder coin (ledger, idempotent), and the
      Day-7 milestone mints a signed 24 h pass via `redact.mint_vip_pass` when a
      `pass_secret` is supplied.

    * `values` is the `app_remote_config` row and `grants` a table already resolved
      by :func:`resolve_streak_grants` (a caller that resolved it for its own reply
      passes it here so the two cannot diverge) — the same pair `redeem_pass` takes.
      Both default to the shipped ladder.

    The day is claimed with one guarded `UPDATE … WHERE last_counted_day IS ?`, so
    two concurrent calls for the same account cannot both credit the same bucket or
    mint the same pass twice."""
    moment = _now(now)
    tz = tz or STREAK_TZ_DEFAULT
    boundary = DAY_BOUNDARY_HOUR_DEFAULT if day_boundary_hour is None else day_boundary_hour
    table = grants if grants is not None else resolve_streak_grants(values)
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
        coins = table["coins"].get(new_current)
        if coins:
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
            pass_expires = float(int(moment + table["pass_seconds"]))
            pass_token = redact.mint_vip_pass(pass_expires, pass_secret)
            # A streak-minted pass is a VIP pass too: record it, so the 24 hours
            # it buys are visible to `entitlement` exactly like a redeemed one.
            # Same connection and commit as the grant, so the two cannot diverge.
            _record_coin_pass(conn, account_id, "streak_day7", pass_expires, moment)
        _commit(conn)
    return {"account_id": int(account_id), "status": status,
            "current_streak": new_current, "best_streak": new_best,
            "bucket": bucket, "granted_coins": granted,
            "pass": pass_token, "pass_expires_at": pass_expires}


# ── the pass ladder (Pillar 3): redeem coins for a signed pass ────────────────


def pass_ladder(values=None) -> dict:
    """The published price ladder — read by the app and (in deliverable c) the
    admin card. Monthly VIP is ₨250 per the plan doc (authoritative), independent
    of `payments.PLAN_DEFAULTS`, which is left untouched.

    This is :func:`resolve_ladder` under its older name, not a second table: a
    ladder with two accessors is a ladder with two answers."""
    return resolve_ladder(values)


def _record_coin_pass(conn: sqlite3.Connection, account_id, plan, expires_at,
                      created_at) -> None:
    """Record a minted VIP pass against its account, so `entitlement` and the
    VIP checks can see it. The caller owns the transaction: this only executes
    the INSERT, it never commits."""
    conn.execute(
        "INSERT INTO coin_passes(account_id, plan, expires_at, created_at)"
        " VALUES(?,?,?,?)",
        (int(account_id), str(plan), float(expires_at), float(created_at)))


def redeem_pass(conn_or_path, account_id, *, plan, pass_secret, now=None,
                tz=None, idempotency_key=None, values=None, ladder=None) -> dict:
    """Turn coins into a signed VIP pass. A coin spend first (refusing
    `InsufficientCoins` if the wallet is short), then a capability token minted
    with `redact.mint_vip_pass` — honoured on `/api/v1/download` and unforgeable
    and non-replayable after expiry (M-MON-02). Coins are spendable ONLY on these
    passes: there is no cash-out path anywhere in this module (§A).

    Everything the pass has to say about itself — its price and the instant it
    dies — is resolved from the tier's own data *before* the wallet is touched, so
    a refusal writes nothing. `spend_coins` used to run first and the expiry
    branch second, which meant a tier the code did not understand cost coins and
    minted nothing; that is the one failure a spend cannot have, and no ordering
    of `if plan == …` fixes it, because the bug was the ordering.

    `values` is the `app_remote_config` row and `ladder` a table already resolved
    by :func:`resolve_ladder` (a caller that resolved it for its own reply passes
    it here so the two cannot diverge). Both default to the shipped ladder. The
    price is read from the same table the phone's price list is built from, so a
    cheapening can only ever be a cheapening of both."""
    if not pass_secret:
        raise EngagementError("a pass must be signed with a secret")
    table = ladder if ladder is not None else resolve_ladder(values)
    if plan not in table:
        raise UnknownPlan(plan)
    spec = table[plan]
    moment = _now(now)
    cost = _positive_int(spec.get("coins"), f"{plan} coin cost")
    expires = tier_expiry(plan, moment, tz=tz, ladder=table)
    if idempotency_key is None:
        idempotency_key = f"redeem:{account_id}:{plan}:{int(moment)}"
    spend = spend_coins(conn_or_path, account_id, amount=cost, reason="redeem_pass",
                        ref=plan, idempotency_key=idempotency_key, now=moment)
    expires = float(int(expires))   # the signed token's resolution is whole seconds
    token = redact.mint_vip_pass(expires, pass_secret)
    if not spend["already_applied"]:
        # The spend and the record are two writes, not one transaction: a retry
        # with the same idempotency key must not record the same pass twice, and
        # a record that failed after the spend still leaves the caller holding
        # the token (the download bypass works from the token alone).
        with _borrow(conn_or_path) as conn:
            _record_coin_pass(conn, account_id, plan, expires, moment)
            _commit(conn)
    return {"plan": plan, "cost": cost, "balance": spend["balance"],
            "already_applied": spend["already_applied"], "pass": token,
            "expires_at": expires, "expiry_rule": str(spec.get("expiry_rule") or "")}


# ── the direct-download credit (daily check-in Build 4) ──────────────────────


def redeem_download_credit(conn_or_path, account_id, *, handle, credit_secret,
                           now=None, values=None, idempotency_key=None) -> dict:
    """Spend coins on one direct download of one movie.

    The credit is a row, not a pass: the token is only the row's signed id, so
    the browser that presents it needs no account and the server still knows
    exactly which download it was bought for. The spend and the row are two
    writes — a retry with the same idempotency key spends nothing and mints
    nothing twice, and a row that failed after the spend still leaves the
    caller holding the token (the download bypass works from the token alone).
    """
    moment = time.time() if now is None else float(now)
    cost = resolve_download_credit(values)
    key = (f"redeem-download:{account_id}:{handle}:{int(moment)}"
           if idempotency_key is None else str(idempotency_key))
    spend = spend_coins(conn_or_path, account_id, amount=cost,
                        reason="redeem_download", ref=str(handle),
                        idempotency_key=key, now=moment)
    expires = float(int(moment + DOWNLOAD_CREDIT_SECONDS))
    token = None
    if not spend["already_applied"]:
        with _borrow(conn_or_path) as conn:
            row = conn.execute(
                "INSERT INTO coin_download_credits"
                "(account_id, handle, expires_at, created_at)"
                " VALUES(?,?,?,?)",
                (int(account_id), str(handle), expires, moment))
            _commit(conn)
            token = redact.mint_download_credit(int(row.lastrowid), credit_secret)
    else:
        # A replay buys nothing twice, and mints nothing twice either: the
        # caller already holds the token from the first answer, so this only
        # re-derives it — and reports the row's own expiry, not a fresh day.
        with _borrow(conn_or_path) as conn:
            found = conn.execute(
                "SELECT id, expires_at FROM coin_download_credits"
                " WHERE account_id = ? AND handle = ? AND used_at IS NULL"
                " AND expires_at > ? ORDER BY id DESC LIMIT 1",
                (int(account_id), str(handle), moment)).fetchone()
        if found is not None:
            token = redact.mint_download_credit(int(found["id"]), credit_secret)
            expires = float(found["expires_at"])
        else:
            # The replay's own credit is already spent: there is no live token
            # to re-derive, and the expiry is the row's, not a fresh day.
            expires = 0.0
    return {"handle": str(handle), "cost": cost, "balance": spend["balance"],
            "already_applied": spend["already_applied"], "token": token,
            "expires_at": expires}


def consume_download_credit(conn_or_path, token, *, handle, credit_secret,
                            now=None) -> bool:
    """Spend one download credit on this download, or refuse it.

    True only when the token is ours, names a credit bought for this exact
    download id, is unexpired, and has never been used — the consume is one
    guarded UPDATE, so two browsers racing the same token get one file and
    one refusal. Anything else is False, never an exception: the download
    route falls back to its ordinary shortening, so a bad token costs the
    caller a direct link, never the download itself.
    """
    moment = time.time() if now is None else float(now)
    credit_id = redact.parse_download_credit(token, credit_secret)
    if credit_id is None:
        return False
    try:
        with _borrow(conn_or_path) as conn:
            changed = conn.execute(
                "UPDATE coin_download_credits SET used_at = ?"
                " WHERE id = ? AND handle = ? AND used_at IS NULL"
                " AND expires_at > ?",
                (moment, int(credit_id), str(handle), moment))
            _commit(conn)
            return changed.rowcount == 1
    except Exception:  # noqa: BLE001 — a credit the store cannot read spends nothing
        return False


# ── the Build 5 grants and spends ─────────────────────────────────────────────


def grant_share(conn_or_path, account_id, *, work, now=None, values=None) -> dict:
    """Pay one share of a movie: 25 coins, once a day per account.

    The server cannot observe a share — the app's chooser returning does not
    prove the share left the phone — so this is a bounded client claim, the
    same shape as the daily-login claim: the app reports it, the server
    verifies the work handle is ours (the route does that before calling
    here) and the day bucket is the enforcement. The idempotency key is the
    account + the Karachi day bucket, so a second share the same day pays
    nothing, whatever title it names.
    """
    moment = time.time() if now is None else float(now)
    bucket = _day_bucket(moment, STREAK_TZ_DEFAULT, DAY_BOUNDARY_HOUR_DEFAULT)
    amount = resolve_share_coins(values)
    granted = grant_coins(conn_or_path, account_id, amount=amount, reason="share",
                          source="server", ref=str(work),
                          idempotency_key=f"share:{account_id}:{bucket}", now=moment)
    # `grant_coins` reports a replay as `idempotent` (the write landed zero
    # rows) — that is the already-paid answer, not a second grant.
    return {"granted": not granted["idempotent"], "coins": amount,
            "balance": granted["balance"]}


def finish_watch_observed(conn_or_path, account_id, *, work, season=0,
                          episode=0, duration_seconds=0.0, now=None) -> dict:
    """Did the server itself see this account watch this title?

    Reads the `watch_observations` row `accounts.put_progress` keeps: the
    span between the first applied progress report and now must be at least
    `FINISH_WATCH_FRACTION * FINISH_WATCH_OBSERVED_TOLERANCE` of the
    duration. A missing row, a missing table (a wallet opened before this
    release installed the schema), or a duration the caller never knew all
    answer `observed: False` — the grant fails closed, never open. This is
    the only measurement the grant trusts: the play and stream routes are
    anonymous redirects, so no press can be attributed to an account without
    a contract change, and the progress reports *are* the server-observed
    playback evidence.
    """
    moment = time.time() if now is None else float(now)
    required = (FINISH_WATCH_FRACTION * FINISH_WATCH_OBSERVED_TOLERANCE
                * float(duration_seconds or 0.0))
    answer = {"observed": False, "span_seconds": 0.0,
              "required_seconds": required}
    with _borrow(conn_or_path) as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table'"
            " AND name = 'watch_observations'").fetchone()
        if table is None:
            return answer
        row = conn.execute(
            "SELECT first_seen_at FROM watch_observations"
            " WHERE account_id = ? AND work_key = ?"
            " AND season_number = ? AND episode_number = ?",
            (int(account_id), str(work), int(season or 0),
             int(episode or 0))).fetchone()
    if row is None:
        return answer
    span = moment - float(row[0])
    answer["span_seconds"] = span
    answer["observed"] = span >= required > 0
    return answer


def grant_finish_watch(conn_or_path, account_id, *, work, season=0, episode=0,
                       now=None, values=None) -> dict:
    """Pay one finished title: 15 coins, once per title ever.

    The idempotency key is the account + the work + the season/episode, so a
    rewatch pays nothing and a series pays per episode, not per season. The
    caller decides what "finished" means — the progress route checks the
    90% threshold before calling here — so this function only pays, never
    measures. The caller must ALSO have checked that the watch was observed
    (`finish_watch_observed`): this function cannot tell a real viewing from
    a single instant claim, and a grant made without that check is the farming
    hole this release closes.
    """
    moment = time.time() if now is None else float(now)
    amount = resolve_finish_watch_coins(values)
    granted = grant_coins(conn_or_path, account_id, amount=amount,
                          reason="finish_watch", source="server", ref=str(work),
                          idempotency_key=(
                              f"finish-watch:{account_id}:{work}:"
                              f"{int(season or 0)}:{int(episode or 0)}"),
                          now=moment)
    # `grant_coins` reports a replay as `idempotent` — a rewatch pays nothing.
    return {"granted": not granted["idempotent"], "coins": amount,
            "balance": granted["balance"]}


def request_movie(conn_or_path, account_id, *, title, notes="", now=None,
                  values=None, idempotency_key=None) -> dict:
    """Spend coins on one requested movie and queue it for the operator.

    The spend and the queue entry are two writes of one purchase: a retry with
    the same idempotency key spends nothing and queues nothing twice. The
    title is the viewer's own words, capped by the route; the status starts
    'open' and only a human on the panel moves it.
    """
    moment = time.time() if now is None else float(now)
    cost = resolve_request_movie_coins(values)
    key = (f"request-movie:{account_id}:{int(moment)}"
           if idempotency_key is None else str(idempotency_key))
    spend = spend_coins(conn_or_path, account_id, amount=cost,
                        reason="redeem_request", ref=str(title),
                        idempotency_key=key, now=moment)
    request_id = None
    if spend["already_applied"]:
        # A replay reports the request it filed, not a fresh id.
        with _borrow(conn_or_path) as conn:
            row = conn.execute(
                "SELECT id FROM movie_requests WHERE account_id = ? AND title = ?"
                " ORDER BY created_at DESC LIMIT 1",
                (int(account_id), str(title))).fetchone()
            request_id = int(row["id"]) if row is not None else None
    else:
        with _borrow(conn_or_path) as conn:
            row = conn.execute(
                "INSERT INTO movie_requests"
                "(account_id, title, notes, status, created_at)"
                " VALUES(?,?,?,'open',?)",
                (int(account_id), str(title), str(notes or ""), moment))
            _commit(conn)
            request_id = int(row.lastrowid)
    return {"title": str(title), "cost": cost, "balance": spend["balance"],
            "already_applied": spend["already_applied"], "id": request_id}


#: The statuses the operator may move a request to. The schema comment on
#: `movie_requests` names this workflow; 'open' is the start and only a human
#: on the panel moves it. A crawl trigger does NOT change the status — the run
#: is recorded in the fleet audit journal, and the request stays open until
#: the operator has seen the title.
REQUEST_TERMINAL_STATUSES = ("indexed", "declined")
_REQUEST_STATUSES = ("open",) + REQUEST_TERMINAL_STATUSES


def list_movie_requests(conn_or_path, *, status=None, limit=100,
                        oldest_first=False) -> list:
    """The operator's queue, newest first, every row a plain dict.

    `status` filters to one workflow state; an unknown one is a caller bug and
    fails loudly instead of silently returning the wrong queue. `oldest_first`
    is the queue order — the operator works the oldest request first — while
    the recent list stays newest first.
    """
    if status is not None and status not in _REQUEST_STATUSES:
        raise ValueError(f"unknown request status: {status!r}")
    direction = "ASC" if oldest_first else "DESC"
    with _borrow(conn_or_path) as conn:
        if status is None:
            rows = conn.execute(
                "SELECT id, account_id, title, notes, status, created_at"
                " FROM movie_requests ORDER BY created_at"
                f" {direction}, id {direction} LIMIT ?",
                (int(limit),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, account_id, title, notes, status, created_at"
                " FROM movie_requests WHERE status = ?"
                f" ORDER BY created_at {direction}, id {direction} LIMIT ?",
                (str(status), int(limit))).fetchall()
    return [{
        "id": int(row["id"]),
        "account_id": int(row["account_id"]),
        "title": str(row["title"]),
        "notes": str(row["notes"] or ""),
        "status": str(row["status"]),
        "created_at": float(row["created_at"]),
    } for row in rows]


def set_request_status(conn_or_path, request_id, status) -> dict | None:
    """Move one open request to 'indexed' or 'declined'.

    Returns ``{"id", "status", "changed"}``; ``None`` when the row does not
    exist. A re-mark writes nothing and reports the status the row already
    holds, the same shape as a replayed spend — the operator's double-click
    closes nobody twice.
    """
    if status not in REQUEST_TERMINAL_STATUSES:
        raise ValueError(f"unknown request status: {status!r}")
    with _borrow(conn_or_path) as conn:
        row = conn.execute(
            "SELECT status FROM movie_requests WHERE id = ?",
            (int(request_id),)).fetchone()
        if row is None:
            return None
        current = str(row["status"])
        if current != "open":
            return {"id": int(request_id), "status": current,
                    "changed": False}
        conn.execute(
            "UPDATE movie_requests SET status = ? WHERE id = ?",
            (str(status), int(request_id)))
        _commit(conn)
        return {"id": int(request_id), "status": str(status),
                "changed": True}


def owned_themes(conn_or_path, account_id) -> list:
    """The theme ids this account owns, oldest purchase first. `jade` is the
    shipped look and is owned by everyone, so it is always in the answer
    whether or not a row says so — the table only ever holds purchases."""
    with _borrow(conn_or_path) as conn:
        rows = conn.execute(
            "SELECT theme_id FROM purchased_themes WHERE account_id = ?"
            " ORDER BY purchased_at",
            (int(account_id),)).fetchall()
    return ["jade"] + [str(row["theme_id"]) for row in rows
                       if str(row["theme_id"]) != "jade"]


def redeem_theme(conn_or_path, account_id, *, theme, now=None, values=None,
                 idempotency_key=None) -> dict:
    """Spend coins on one player theme and record the ownership.

    The theme must be one of `PURCHASABLE_THEMES` — the route checks that
    before calling here, so a name this server never sold cannot be bought.
    The purchase is the (account, theme) pair: a retry with the same
    idempotency key spends nothing and records nothing twice, and a theme
    already owned costs nothing at all — the route answers `already_applied`
    with the ownership it already holds.
    """
    moment = time.time() if now is None else float(now)
    cost = resolve_theme_coins(values)
    key = (f"redeem-theme:{account_id}:{theme}:{int(moment)}"
           if idempotency_key is None else str(idempotency_key))
    spend = spend_coins(conn_or_path, account_id, amount=cost,
                        reason="redeem_theme", ref=str(theme),
                        idempotency_key=key, now=moment)
    if not spend["already_applied"]:
        with _borrow(conn_or_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO purchased_themes"
                "(account_id, theme_id, purchased_at) VALUES(?,?,?)",
                (int(account_id), str(theme), moment))
            _commit(conn)
    return {"theme": str(theme), "cost": cost, "balance": spend["balance"],
            "already_applied": spend["already_applied"],
            "owned": owned_themes(conn_or_path, account_id)}


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

    Deliverable (c) landed: `admin_panel.remote_config()` builds its `engagement`
    block *over this function* and applies the operator's `app_remote_config` row
    on top, so the numbers a client sees are the shipped ones until a knob is saved
    and the saved ones after. The ad cadence is applied at the enforcement site
    (`ad_grant(caps=…)`), and the pass ladder is now applied at its enforcement
    site too: `redeem_pass(values=…)` prices and times a pass through
    :func:`resolve_ladder`, the same resolver that builds the `passes` block below,
    so a published price and a charged price are one number read twice rather than
    two numbers that happen to agree. One enforcement site still reads this
    module's constant rather than the row — `_enforce_rewarded_cap`
    (`REWARDED_DAILY_CAP`) — and wiring it belongs with the rewarded-ad route,
    which does not exist yet; it is not cosmetic there either, but the mistake
    runs the other way: a lowered cap would publish a stricter ceiling than the
    ledger hands out. `record_engagement_day` has left that list: the streak
    grants reach it through :func:`resolve_streak_grants`, supplied by the caller
    that owns the grant. Publishes costs and grant sizes as data — the whole
    point of the rule is that a user can see the real numbers, and there is no
    field here a coin could be cashed out through."""
    ladder = resolve_ladder()
    return {
        "wallet": {
            "coin_per_rewarded_ad": COINS_PER_REWARDED_AD,
            "rewarded_daily_cap": REWARDED_DAILY_CAP,
            "redeem_coin_costs": {name: int(spec["coins"])
                                  for name, spec in ladder.items()},
        },
        "streak": {
            "grants": {"day1_coins": STREAK_GRANTS_COINS[1],
                       "day3_coins": STREAK_GRANTS_COINS[3],
                       "day7_pass_seconds": STREAK_PASS_SECONDS},
            "tz": STREAK_TZ_DEFAULT,
            "day_boundary_hour": DAY_BOUNDARY_HOUR_DEFAULT,
        },
        "passes": passes_projection(ladder),
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
