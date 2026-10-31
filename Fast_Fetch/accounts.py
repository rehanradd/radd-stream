#!/usr/bin/env python3
"""
Fast_Fetch/accounts.py — the server side of the OPTIONAL user account.
════════════════════════════════════════════════════════════════════════════════════
WHAT THIS IS, STATED PLAINLY (DAO.md principle #6: describe the work accurately)
--------------------------------------------------------------------------------
The host serves **plain HTTP only** (`http://92.4.95.252/`, nginx :80 →
127.0.0.1:8080, no TLS anywhere — `API_V2.md` §8.3, `ORACLE_DEPLOYMENT.md`).
Anything secret sent to it can be read by whoever is looking at the wire. So a
password-based account cannot be built here honestly, and `API_V2.md` §8.3 says
exactly that: *"no Authorization header, no device token, no account concept may
be sent to this host."*

This module does not pretend otherwise. It implements the only account shape that
survives cleartext transport:

* **A sync key, never a password.** An account *is* a high-entropy random token
  (`secrets.token_urlsafe(12)`, 96 bits) minted at creation and shown exactly
  once. There is no password, no email, no recovery question — nothing a human
  would reuse elsewhere and nothing an attacker gains a foothold from. There is
  no login: the key is the account, and there is nothing to log *in* to.
  A client MAY derive its 16 characters from something a viewer already knows
  (the Android app offers a Pakistani mobile number as a convenience). The server
  never receives the number, cannot tell a derived key from a random one, and
  treats it identically. That convenience is worth strictly less than a minted
  key: anyone who knows the number can derive the same string, so the app must
  say so in the UI instead of calling it a secret.
* **The blast radius is a bookmark list.** What an account holds is favorites and
  playback progress — `work_key` plus season/episode plus seconds watched. If a
  sync key is captured off the wire, the most an observer can do is read or
  scribble on a list of catalog work keys. That is the whole of it, and it is why
  this account is *optional*, why the app must keep working with none at all, and
  why the app should say so in one sentence of UI copy.
* **No personal data, except the one profile the owner asked for.** No free-text
  notes, no device label, no avatar, no address. The release that added the
  device-gated trial and phone+PIN linking (`grant_or_resume_device_trial`,
  :func:`link_profile_with_pin`) put four columns on `user_accounts` —
  `profile_name`, `phone`, `pin_hash`, `linked_at` — and that is the complete list
  of what the server now knows about a person: a name they typed, a number they
  typed, and a hash of a PIN they typed. Nothing here is ever serialised to a
  caller (:func:`to_public` is the only sanctioned wire shape and it reads
  favorites and progress), the PIN is stored only as a PBKDF2 digest with a
  per-row salt, and the *phone* is stored in the clear because the operator has to
  be able to find an account by it — which means this file now holds personal data
  and must be treated as such in backups, on disks, and in any future export. That
  is a decision, not an oversight, and it is reversible only by deleting the
  columns.
* **The key is stored hashed, one-way.** See `_hash_key()` for why sha256 is the
  honest choice here and why a password KDF would be a lie about the protection
  actually on offer.
* **Revocation is deletion-shaped.** `revoke_account()` rewrites the stored hash
  into an inert tombstone, so a revoked account stops resolving through the same
  code path as an account that never existed — there is no separate "revoked"
  answer for a prober to tell apart.

WHAT THE STATE MODEL IS
--------------------------------------------------------------------------------
The client already keeps this data locally in Room, and its schema is the model
for what the server may accept — nothing the client cannot send is stored here:

* `App/app/src/main/kotlin/com/raddstream/app/data/local/FavoritePost.kt` —
  a favorite is one work (`id`, `addedAt`); the rest of its fields (`title`,
  `cleanTitle`, `year`, `contentType`, `posterUrl`, `imdbRating`) are *catalog*
  data the app copied for offline display. The server is the catalog, so it stores
  the identity — `work_key` — plus `added_at`, and resolves everything else.
* `App/app/src/main/kotlin/com/raddstream/app/data/cache/CacheTaskEntity.kt` —
  progress is tracked in absolute units with percent *derived for display only*
  (`downloadedBytes`/`totalSizeBytes`, `percent()` never used for math). Same rule
  here: `position_seconds` / `duration_seconds` are stored, a percentage is the
  caller's arithmetic. Its `playOffsetSeconds` / `packTotalDurationSeconds` are
  why a progress row is scoped by season *and* episode, not by work alone.
* `App/app/src/main/kotlin/com/raddstream/app/ui/navigation/Screen.kt` — the
  player is addressed by an *opaque server handle*, never by a URL, because a
  route argument "is an address that leaves the app". Same law here: a favorite or
  a progress row names a work and nothing else. **No function in this file accepts
  or stores a caller-supplied URL for a media item.**

Why `work_key` and not `cat_works.id`: `API_V2.md` §3 — ids are re-allocated by
every projection rebuild, so anything a client persists must key on the stable
string and re-resolve numbers after a revision change (§16.2).

PROVENANCE, ABSOLUTE
--------------------------------------------------------------------------------
A user-visible string must never name a source site or a hoster (`redact.py`,
`API_V2.md` §16.9). Two consequences, both enforced here:

1. **Storage.** No title, no label, no URL, no site column. Only `work_key`
   values, which are our own identity strings (`catalog_v2.work_key_for` →
   `imdb:tt…`, `tmdb:…`, `family:normalized title:year`). `_normalize_work_key`
   additionally rejects anything URL-shaped, so a `https://` string cannot be
   filed into this table by accident or by an attacker.
2. **Serialisation.** `redact.PROVENANCE` forbids the literal key name
   `work_key` in anything the public port serialises, and the *value* can be just
   as bad: a polluted scraped headline became a real work key in this catalog
   (`series:absolutely anything 2015 brrip katmoviehd watch online:2015`), so
   echoing a raw key would name a site whatever key name hid it. Therefore
   **`to_public()` is the only sanctioned way to put one of these rows on the
   wire**: it drops `account_id` and moves the identifier to `work_ref` — the same
   name the catalog already uses for a minted work handle — which is in
   `redact.MINTED_KEYS`, so the caller passes it through
   `redact.mint_text()` and the public body carries an opaque handle instead of a
   searchable key. `to_public()` refuses to work without a mint callable — the
   safe default is the one that cannot leak.

ADULT RULE, ABSOLUTE
--------------------------------------------------------------------------------
`is_18_plus = 1` works are stored but never displayed (`API_V2.md` §13: to an
unprivileged caller an adult work is *indistinguishable from a work that does not
exist* — same status, same body, no count skew). Applied here:

* a write naming a flagged `work_key` raises the identical `UnknownWork` that a
  write naming an absent `work_key` raises, from the identical branch, with the
  identical message and no key echoed back (`_require_visible`);
* a read filters rows whose work has become invisible (the flag can flip when a
  newly scraped post joins the work — `catalog_v2` makes it a one-way ratchet)
  rather than returning them, and never deletes them: flag at write time, filter
  at display time, lose nothing;
* nothing in this module can express "this one exists and is flagged". The only
  answers are "not visible to you" and "visible".

A `catalog` handle (a `cat_works`-bearing connection or path, or a
`callable(work_key) -> bool`) is therefore **required** on every write. Without
one this module refuses the write rather than silently storing a flagged work key.
Fail closed.

THE LIMITER, AND WHAT IT DOES NOT DO
--------------------------------------------------------------------------------
`AttemptTracker` keeps a fixed-window failure count per presented-key hash
(in-process, mirrored into `sync_key_attempts` so a restart does not reset it).
It exists so that hammering one captured or guessed string burns out.

Honest limits — the part a reviewer must not be sold:
* A minted key is 96 bits, so guessing a live key is not a threat model at all.
  The limiter changes nothing about that.
* A key the app derived from a phone number is NOT 96 bits of entropy: the phone
  space is small enough to enumerate offline. This module cannot see the
  difference, so the app's copy must say, plainly, that a phone number is a
  convenience and not a secret. Nothing here may describe it as protected.
* A limiter keyed on the *guess* cannot slow an attacker who changes the guess
  every attempt; that is what the per-IP token buckets of §16.5 (`redact.
  RateLimiter`) are for, and the HTTP layer applies those. A shared secondary
  bucket (`GLOBAL_BUCKET`) is charged on the failure path so a flood of distinct
  wrong keys is at least counted, on disk, for the operator to see.
* The limiter is never consulted on the success path. A burned-out bucket can
  therefore never deny a legitimate device. Making it the other way around would
  hand an anonymous attacker a denial-of-service against every account whose key
  he can guess wrong — which is every account.

WHY THIS FILE HAS NO HTTP IN IT
--------------------------------------------------------------------------------
`viewer.py` owns status codes, RFC 9457 problem bodies (§16.4), `RateLimit-*`
headers and the adult-rule response shape. This module owns the state and raises
typed errors carrying a `code` and a `status` (`AccountError`) so the mapping
stays in one place and this file stays testable without a socket.

DATABASE LOCATION
--------------------------------------------------------------------------------
`user_state.db`, always outside the git checkout (`AGENTS.md`: keep databases out
of git). Resolution order: explicit argument → `RADD_USER_STATE_DB` →
`config.DATA_DIR` (which is `/home/ubuntu/radd-stream-data` on this host) →
`$XDG_DATA_HOME` or `~/.local/share`. There is deliberately no fallback into
`Fast_Fetch/`.

Stdlib only: `secrets`, `hashlib`, `hmac`, `sqlite3`, `time`, `re`, `contextlib`,
`pathlib`, `os`. Zero pip packages.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

#: Bumped only when the shape of the state changes incompatibly; additive columns
#: are installed by `_migrate_columns` and never require a bump. A NEW TABLE (the
#: `payment_transactions` ledger, `device_trials`) likewise needs no bump:
#: `ensure_schema()` runs the whole `CREATE ... IF NOT EXISTS` script on every
#: `connect()`, so an older file gains the table on its next open and every older
#: row is still valid.
SCHEMA_VERSION = 1

DB_FILENAME = "user_state.db"
DEFAULT_BUSY_TIMEOUT_MS = 5000

# ── tuning knobs (every one overridable per call, so tests stay deterministic) ─
#: A minted sync key is 96 bits of `secrets` output, which base64url renders as 16
#: characters. 16 is the floor a *client-minted* key must clear to be admitted at
#: all: below it even a random value is close enough to guessable to be worth
#: refusing. A key the app derived from a phone number is also 16 characters and
#: clears this shape check; its real strength is the phone space, which the app's
#: own copy has to be honest about (module docstring).
MIN_SYNC_KEY_CHARS = 16
MAX_SYNC_KEY_CHARS = 256
MAX_WORK_KEY_CHARS = 256
#: Fixed window for the per-key attempt counter, and how long a burned-out key
#: stays burned out.
DEFAULT_MAX_FAILURES = 8
DEFAULT_WINDOW_SECONDS = 600.0
DEFAULT_LOCK_SECONDS = 900.0
#: The shared bucket charged by every failed attempt, so a flood of *distinct*
#: wrong keys is also counted. High enough never to affect real traffic.
DEFAULT_GLOBAL_MAX_FAILURES = 600
GLOBAL_BUCKET = "*global*"
#: How stale a remembered failure may get before the tracker forgets it.
ATTEMPT_HORIZON_SECONDS = 7 * 86400.0
#: An account nobody has touched in this long is removed with its rows, so the
#: table cannot grow forever.
DEFAULT_IDLE_DAYS = 120
#: Per-account row caps: the bound on how large one library can get. A long
#: series episode-by-episode is comfortably below these; exceeding them is a
#: client bug worth surfacing rather than unbounded growth on a 1-CPU box.
MAX_FAVORITES = 5000
MAX_PROGRESS = 5000
#: A client clock further ahead than this is not trusted as a tie-break: it is
#: clamped to our receipt time, so one device stuck showing 2035 cannot freeze a
#: row against every other device forever.
CLOCK_SKEW_TOLERANCE = 24 * 3600.0
#: `last_seen_at` is rewritten at most this often, so reading a library does not
#: turn every browse request into a write.
LAST_SEEN_WRITE_INTERVAL = 900.0

# ── the trial gate and the linked profile ────────────────────────────────────
#: Days of VIP a never-before-seen device gets, and the only length that number
#: ever has: the clock starts at first sight and NEVER restarts, so the row in
#: `device_trials` is the whole of the grant. A caller that wants a different
#: width passes `trial_days` per call (tests do); nothing on the wire sets it.
#:
#: It is a TRIAL GATE, not a hardware lock, and the difference is load-bearing
#: rather than modest (`docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` R5): the
#: `device_id` is a string the client reports, an emulator hands out fresh ones, a
#: re-flashed or OTA'd device can look new, and nothing in this design attests
#: anything — `docs/IDENTITY_AND_TRIAL_ABUSE.md` §3 measured zero attestation calls
#: across `App/app/src`. What it does stop is the ordinary case the owner named: a
#: viewer who uninstall-reinstalls to farm another free week.
TRIAL_DAYS = 3
DAY_SECONDS = 86400.0
#: The day a linked profile adds. Granted exactly once per account, judged from
#: `user_accounts.linked_at` — the column the same write sets — so a customer who
#: re-links to fix a typo cannot farm bonus days off one phone number.
PROFILE_BONUS_SECONDS = 86400.0
#: A device id is the app's own installation identifier (ANDROID_ID, a UUID):
#: bounded and character-checked because it becomes a PRIMARY KEY straight from a
#: request body, and an unbounded one is an unbounded row.
MIN_DEVICE_ID_CHARS = 8
MAX_DEVICE_ID_CHARS = 128
#: A PIN is 4-8 decimal digits — 10^4 at the floor. Nothing about a slow hash
#: fixes that: what makes a 4-digit PIN survivable online is the attempt limiter
#: (`_pin_bucket`, which reuses `AttemptTracker`'s fixed window), and what makes
#: it survivable in a stolen database file is that the answer is PBKDF2 with a
#: per-row salt rather than the unsalted sha256 a 96-bit sync key can afford.
#: The number below is a *choice*, and the honest reason it is not bigger: this
#: box has one CPU, the hash runs inside the request that a real viewer is waiting
#: on, and Python's `hashlib.pbkdf2_hmac` is C code — 120k iterations measured a
#: 56.6 ms median (51.6 min / 98.7 max, twelve samples) of that one core on the
#: live host 2026-10-31, which is a person linking a phone once, not a per-browse
#: cost. It is NOT protection against an attacker who owns the file and can spend
#: the whole machine offline for a week on 10^4 guesses; no iteration count
#: reachable at this price is, for a secret this short.
#: 120_000 is the floor set by `docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` R6
#: ("PBKDF2-HMAC-SHA256 with a per-account random salt, >= 120_000"), which is
#: what the review ruled for a credential whose whole space is 10^4.
PIN_ITERATIONS = 120_000
MIN_PIN_DIGITS = 4
MAX_PIN_DIGITS = 8
#: Stored form of a PIN, prefix-tagged for the same reason `HASH_PREFIX` is: the
#: column records which construction made it, so a future release can migrate row
#: by row instead of guessing, and `_verify_pin_hash` can refuse a foreign shape
#: rather than compare across forms. `sha256:`/`revoked:` are rejected outright —
#: a sync-key digest must never be mistaken for a PIN digest.
PIN_HASH_PREFIX = "pbkdf2_sha256$"
#: The stored PIN's iteration count is read back out of its own digest so an old
#: row keeps the cost it was minted at; an absurd parsed value is refused rather
#: than spent.
MAX_PIN_ITERATIONS = 1_000_000
#: Both are free text typed on a phone, both arrive on a public unauthenticated
#: route, and both are stored. Bounded hard, control characters stripped, and
#: never on the wire: `to_public()` is the only sanctioned way this module puts a
#: row on the wire and it reads favorites and progress, not these columns.
MAX_PROFILE_NAME_CHARS = 60
MIN_PHONE_DIGITS = 8
MAX_PHONE_DIGITS = 16

#: Compiled shapes for the three strings above. `fullmatch` at every call site:
#: these are the complete grammar of what may be stored, not a substring test.
_DEVICE_ID_RE = re.compile(r"[A-Za-z0-9._:-]+")
_PIN_RE = re.compile(r"[0-9]+")
#: C0/C1 controls and DEL, which have no business in a name a terminal will print.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: The one-way form a sync key is stored in (`_hash_key`).
HASH_PREFIX = "sha256:"
#: Stored form of a revoked account's hash: unreachable by any presented key.
TOMBSTONE_PREFIX = "revoked:"
#: The wire name `to_public()` gives the identifier. It is `work_ref` because that
#: is what the catalog calls the same object (`api_v2` mints a work key into
#: `work_ref` on every item), and one concept gets one name on the wire. The key is
#: in `redact.MINTED_KEYS` and absent from `redact.PROVENANCE`, so the edge's
#: deny-by-default projection neither strips it nor scans its value as a site name.
PUBLIC_REF_KEY = "work_ref"

# ── errors the HTTP layer maps to a status code ──────────────────────────────


class AccountError(Exception):
    """Base for every refusal in this module.

    `code` is the `API_V2.md` §16.4 problem code and `status` the HTTP status the
    caller should send. No message here ever carries a work key, a sync key, a
    site name or any value the response must not repeat."""

    code = "account_error"
    status = 400
    default_detail = "request refused"

    def __init__(self, detail: str = ""):
        text = str(detail or self.default_detail)[:200]
        super().__init__(text)
        self.detail = text


class UnknownAccount(AccountError):
    """No such account.

    Deliberately the same answer — same class, same message, same code path — for
    a wrong key, a revoked key and a key that was never issued. Nothing observable
    from outside can tell those three apart, which is the point."""

    code = "not_found"
    status = 404
    default_detail = "not found"


class UnknownWork(AccountError):
    """That work is not on this server — the byte-same answer for a work that does
    not exist and one that exists flagged `is_18_plus` (§13). A malformed key is
    refused here too for the same reason: "not visible to you" is the only fact
    this module is willing to express about an identifier."""

    code = "not_found"
    status = 404
    default_detail = "not found"


class Locked(AccountError):
    """This key has failed too often in the current window. `retry_after` is the
    §16.5 `Retry-After` seconds the caller must send. Only ever raised on the
    failure path, so a real key can never be locked out."""

    code = "rate_limited"
    status = 429
    default_detail = "too many attempts with that key"

    def __init__(self, detail: str = "", retry_after: float = 0.0):
        super().__init__(detail)
        self.retry_after = max(1, int(round(retry_after)))


class CatalogUnreachable(AccountError):
    """The visibility oracle itself could not be read.

    A 5xx, not a 404, and the difference matters: a 404 would be a claim about the
    work we cannot support, and silently accepting the write would look like the
    adult rule had been waved through. Nothing about the work leaks either way."""

    code = "dependency_unavailable"
    status = 503
    default_detail = "catalog could not be read"


class InvalidProgress(AccountError):
    """`position_seconds`/`duration_seconds` were not non-negative finite numbers."""

    code = "invalid_progress"
    status = 400
    default_detail = "invalid playback position"


class AccountFull(AccountError):
    """This library hit its per-account row cap (`MAX_FAVORITES`/`MAX_PROGRESS`)."""

    code = "account_full"
    status = 409
    default_detail = "this library is at its row limit"


class WeakSyncKey(AccountError):
    """A caller-minted key was too short, too long, or not transmissible as a
    header value. Refusing to create a guessable account is the honest option."""

    code = "weak_sync_key"
    status = 400
    default_detail = "that sync key is not strong enough"


class WeakDeviceId(AccountError):
    """The `device_id` was missing, blank, over-long, or not transmissible. It
    becomes a PRIMARY KEY straight out of a request body, so a string that cannot
    be stored safely is refused rather than truncated into the table."""

    code = "invalid_request"
    status = 400
    default_detail = "that device id is not usable"


class WeakProfile(AccountError):
    """A name or phone that cannot be stored honestly: empty, over the length
    bound, or not a phone-shaped run of digits once separators are dropped."""

    code = "invalid_request"
    status = 400
    default_detail = "that name or phone number is not valid"


class WeakPIN(AccountError):
    """A PIN outside `MIN_PIN_DIGITS`..`MAX_PIN_DIGITS` decimal digits. Refusing
    it is the whole of what this module can do about a weak choice: the limiter is
    what actually stands between a 4-digit PIN and a guesser, and a PIN this file
    will not store is never counted as protection anywhere else."""

    code = "weak_pin"
    status = 400
    default_detail = "that PIN must be 4 to 8 digits"


class PINMismatch(AccountError):
    """The PIN presented for an already-linked profile is not the one on file.
    Only ever reachable by a caller that already holds the account's sync key —
    that is who the re-link rule protects, and the reason it is not the same
    byte-shaped 404 a stranger gets for a wrong key. 401 because a wrong PIN is a
    failed credential, which is also what the HTTP edge answers (§16.4's
    `unauthorised` carries 401 and nothing here may invent a code)."""

    code = "unauthorised"
    status = 401
    default_detail = "that PIN is not correct for this profile"


# ── paths and connections ────────────────────────────────────────────────────


def default_db_path() -> Path:
    """Where `user_state.db` lives. Never inside the git checkout."""
    env = os.environ.get("RADD_USER_STATE_DB")
    if env:
        return Path(env).expanduser()
    try:
        import config  # stdlib-only sibling; its DATA_DIR already prefers the data disk

        data_dir = getattr(config, "DATA_DIR", None)
        if data_dir:
            return Path(data_dir) / DB_FILENAME
    except Exception:
        pass
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "radd-stream" / DB_FILENAME


def _prepare(conn: sqlite3.Connection, busy_timeout_ms: int) -> None:
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    # WAL: this table is read on every browse request and written when someone
    # hearts a title; without it a writer and a reader serialize on one CPU.
    # `foreign_keys` is PER-CONNECTION and must be set here, or the cascade delete
    # on an account quietly does nothing and orphan rows accumulate forever.
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass
    conn.execute("PRAGMA foreign_keys = ON")


def connect(db_path=None, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
            install_schema: bool = True) -> sqlite3.Connection:
    """Open (creating if needed) the user-state database, ready to use."""
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
    """Accept a `sqlite3.Connection` or a db path, yield a connection.

    Every public function takes either, matching the `catalog_v2` split between
    `project(conn)` and `project_db(db_path)`: the HTTP host keeps one connection
    per worker thread (note `sqlite3`'s default `check_same_thread` — a caller
    sharing a connection across threads must open it with that flag cleared, or
    simply pass a path per request), an operator CLI just names a file. A path we
    own is closed on the way out; a connection the caller handed us never is."""
    if isinstance(handle, sqlite3.Connection):
        yield handle
        return
    conn = connect(handle)
    try:
        yield conn
    finally:
        conn.close()


def _commit(conn: sqlite3.Connection) -> None:
    """Commit our own work. These are leaf writes: dropping a user's favorite
    because a request forgot to commit is a worse failure than committing a
    transaction the caller happened to have open."""
    try:
        conn.commit()
    except sqlite3.Error:
        pass


# ── schema ───────────────────────────────────────────────────────────────────
#
# `CREATE TABLE IF NOT EXISTS` cannot alter an existing table, so every column
# added after the first release is ALSO declared in `_NEW_COLUMNS` and installed
# by a guarded `ALTER` — the `import_hindilinks4u.py` pattern, with the same
# warning: every index that could touch a migrated column is created AFTER the
# ALTER block, never inside the DDL script.

DDL = """
CREATE TABLE IF NOT EXISTS user_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL DEFAULT 0,
    revoked_at REAL,
    vip_until REAL NOT NULL DEFAULT 0,
    -- The linked profile, all four written by `link_profile_with_pin()` and none
    -- of them ever for the wire: `to_public()` is not involved, no public route
    -- reads these columns, and the operator CLI prints row counts only. A new
    -- database gets them here; an existing one gets them from `_NEW_COLUMNS`.
    linked_at REAL,
    profile_name TEXT,
    phone TEXT,
    pin_hash TEXT
);

CREATE TABLE IF NOT EXISTS user_favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    work_key TEXT NOT NULL,
    season_number INTEGER NOT NULL DEFAULT 0,
    episode_number INTEGER NOT NULL DEFAULT 0,
    added_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    work_key TEXT NOT NULL,
    season_number INTEGER NOT NULL DEFAULT 0,
    episode_number INTEGER NOT NULL DEFAULT 0,
    position_seconds REAL NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    client_updated_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_key_attempts (
    bucket TEXT PRIMARY KEY,
    window_started_at REAL NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_state_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- No FOREIGN KEY ... ON DELETE CASCADE on purpose: `prune_accounts()` deletes
    -- an idle account, and a money ledger that vanishes with the account that
    -- paid into it is not auditable. The row outlives the account.
    account_id INTEGER NOT NULL,
    plan TEXT NOT NULL,
    amount_pkr INTEGER NOT NULL,
    method TEXT NOT NULL,
    tid TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    submitted_at REAL NOT NULL,
    reviewed_at REAL,
    reviewer_note TEXT
);

CREATE TABLE IF NOT EXISTS payment_review_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    prior_vip_until REAL NOT NULL DEFAULT 0,
    new_vip_until REAL NOT NULL DEFAULT 0,
    reviewer TEXT NOT NULL DEFAULT '',
    note TEXT,
    acted_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS verified_incoming_tids (
    -- Money the SMS relay has already seen arrive, filed against the transaction
    -- id rather than against an account, because when the bank SMS lands the payer
    -- has not necessarily submitted the claim yet. `payments.sms_webhook()` is the
    -- only writer and `payments.submit_payment()` is the only consumer: a claim
    -- whose TID is here at the same price is credited on arrival instead of waiting
    -- for a human. `gateway` is part of the key because two networks can each write
    -- the same digits into a phone; one row per (network, TID) is the honest unit.
    --
    -- The row is DELETED when it buys the credit, not marked spent. Replaying the
    -- same SMS, or a second account claiming the same TID, must not be able to buy
    -- a second membership off one payment; see `payments._claim_already_credited`.
    gateway TEXT NOT NULL,
    tid TEXT NOT NULL,
    amount_pkr INTEGER NOT NULL,
    verified_at REAL NOT NULL,
    PRIMARY KEY (gateway, tid)
);

CREATE TABLE IF NOT EXISTS device_trials (
    -- The trial-gate ledger: one row per device id the server has ever
    -- seen, and the ONLY place a device's trial clock lives. It is a gate on a
    -- client-reported string, not an attestation (see `TRIAL_DAYS`), and it is
    -- called a gate for that reason. `account_id` has no
    -- FOREIGN KEY ... ON DELETE CASCADE for the same reason the money ledger has
    -- none: `prune_accounts()` deletes an idle account, and a record of when a
    -- device first appeared must not vanish with it, or the next visit from that
    -- device would be indistinguishable from a brand-new one and mint a second
    -- free trial. `grant_or_resume_device_trial()` re-points a stale row at a
    -- freshly minted account and keeps the ORIGINAL expiry.
    --
    -- No index on `account_id` either: every read is by the `device_id` primary
    -- key, and the one `prune_accounts()` write filters a table this small with a
    -- scan. An index nobody queries is a permanent write cost for nothing.
    device_id TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    first_seen_at REAL NOT NULL,
    trial_expires_at REAL NOT NULL
);
"""

#: Columns this release needs that an older database may not have, as
#: `name -> (declaration, backfill)`. A backfill runs in the same migration step,
#: so a row written by the older release is immediately comparable by the newer
#: code (that is what makes `client_updated_at` usable as the tie-break at all).
_NEW_COLUMNS = {
    "user_accounts": {
        "last_seen_at": ("REAL NOT NULL DEFAULT 0", "SET last_seen_at = created_at"),
        "revoked_at": ("REAL", None),
        # Epoch seconds; 0 means never granted. A rewarded pass and a paid
        # membership use the same column, because the question the download
        # route asks is the same for both: is this account VIP right now?
        "vip_until": ("REAL NOT NULL DEFAULT 0", None),
        # The linked profile. `linked_at` doubles as the record that the
        # one-time bonus day was already spent: it is set by the same write that
        # grants the bonus, so there is no second flag that could disagree with
        # the fact it is supposed to mirror. NULL means never linked.
        "linked_at": ("REAL", None),
        "profile_name": ("TEXT", None),
        "phone": ("TEXT", None),
        "pin_hash": ("TEXT", None),
    },
    "user_progress": {
        "client_updated_at": ("REAL NOT NULL DEFAULT 0", "SET client_updated_at = updated_at"),
    },
}

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_user_fav_account ON user_favorites(account_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_fav_scope
    ON user_favorites(account_id, work_key, season_number, episode_number);
CREATE INDEX IF NOT EXISTS idx_user_prog_account ON user_progress(account_id, client_updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_prog_scope
    ON user_progress(account_id, work_key, season_number, episode_number);
CREATE INDEX IF NOT EXISTS idx_user_accounts_last_seen ON user_accounts(last_seen_at);
-- The operator's queue is `status` ordered by `submitted_at`; the rate limiter's
-- question is "when did THIS account last submit", and both must not scan.
CREATE INDEX IF NOT EXISTS idx_user_payment_status
    ON payment_transactions(status, submitted_at);
CREATE INDEX IF NOT EXISTS idx_user_payment_account
    ON payment_transactions(account_id, submitted_at);
CREATE INDEX IF NOT EXISTS idx_payment_audit_payment
    ON payment_review_audit(payment_id, acted_at);
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
    """Install or migrate the user-state schema. Idempotent and additive: an
    existing row is never rewritten, and nothing is ever dropped — a migration
    that loses a user's bookmarks is not a migration.

    Same name and same contract as `catalog_v2.ensure_schema` /
    `link_state.ensure_schema`. Returns what was added, so an operator can see a
    migration happened:
    `{"schema_version": N, "added_columns": ["user_progress.client_updated_at"]}`."""
    conn.executescript(DDL)
    added = _migrate_columns(conn)
    conn.executescript(_INDEXES)
    conn.execute("INSERT OR REPLACE INTO user_state_meta(key, value) VALUES(?, ?)",
                 ("schema_version", str(SCHEMA_VERSION)))
    return {"schema_version": SCHEMA_VERSION, "added_columns": added}


def _migrate_columns(conn: sqlite3.Connection) -> list:
    """Guarded `ALTER`s for columns a newer release needs, each followed by its
    backfill, all before any index touches them (`PRAGMA table_info` is the guard,
    so re-running is a no-op and an unknown table is skipped rather than raised)."""
    added = []
    for table, wanted in _NEW_COLUMNS.items():
        if not _has_table(conn, table):
            continue                      # brand-new database: the DDL already has them
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
    """The schema version stamped in the file; `0` if this module never saw it."""
    with _borrow(conn_or_path) as conn:
        if not _has_table(conn, "user_state_meta"):
            return 0
        row = conn.execute(
            "SELECT value FROM user_state_meta WHERE key = 'schema_version'").fetchone()
        try:
            return int(row[0]) if row else 0
        except (TypeError, ValueError):
            return 0


# ── the sync key ─────────────────────────────────────────────────────────────


def new_sync_key() -> str:
    """A fresh 96-bit sync key, urlsafe so it survives a header and a query
    string unchanged. 12 random bytes render as exactly 16 base64url characters —
    the length the Android app's one-tap screen calls a "16-character sync key".
    The only place the plaintext form is produced."""
    return secrets.token_urlsafe(12)


def _hash_key(key: str) -> str:
    """The stored form of a sync key: one unsalted sha256, prefix-tagged.

    Why not PBKDF2/scrypt/argon2, when "hash a credential" conventionally means a
    slow KDF? Because a slow KDF exists to make a *low-entropy human secret*
    expensive to search. A minted key is 96 bits of uniform randomness from
    `secrets`, so an attacker holding this database file faces 2^96 preimages
    whatever we spend per hash, and the digest is not invertible by anybody.
    Making it slow would buy nothing against that attacker while costing this
    one-CPU box a cycle on every single request.

    A key the APP derived from a phone number is the opposite case: its real input
    space is the phone space, so the digest of one is brute-forceable offline no
    matter what this function costs. A slow KDF would not change that verdict — it
    would only make every legitimate request on this one-CPU box expensive — so the
    honest fix is in the app's copy, which must say a phone number is a
    convenience and not a secret. Pretending a bcrypt-shaped function protects a
    number-derived key would advertise a capability this file does not have
    (DAO.md #6).

    The `sha256:` prefix is not decoration either: it records which form the column
    holds, so a future release that needs a different construction can migrate row
    by row instead of guessing, and `_verify_hash` can refuse to compare across
    forms rather than silently answering "wrong key"."""
    return HASH_PREFIX + hashlib.sha256(str(key).encode("utf-8")).hexdigest()


def _verify_hash(stored, presented_hash: str) -> bool:
    """Constant-time comparison of two stored-form hashes.

    The row is found by hash equality on a unique index; this is the check that
    what we are about to trust really matches what was presented, and it is
    `hmac.compare_digest` and never `==`, a prefix test or a length shortcut: a
    comparison that short-circuits on the first differing byte is an oracle on the
    digest, and the digest is the only thing between a stolen database file and a
    guess. It also refuses a tombstone and any other prefix outright, so a revoked
    account can be reached through no path at all."""
    if not isinstance(stored, str) or not isinstance(presented_hash, str):
        return False
    if stored.startswith(TOMBSTONE_PREFIX) or not stored.startswith(HASH_PREFIX):
        return False
    return hmac.compare_digest(stored.encode("utf-8"), presented_hash.encode("utf-8"))


def _check_sync_key_shape(key) -> str:
    """Validate a client-minted key without ever logging it: length band and
    transmissible characters only. Returns the key stripped."""
    if not isinstance(key, str):
        raise WeakSyncKey("a sync key must be a string")
    text = key.strip()
    if not (MIN_SYNC_KEY_CHARS <= len(text) <= MAX_SYNC_KEY_CHARS):
        raise WeakSyncKey(
            f"a sync key must be {MIN_SYNC_KEY_CHARS}..{MAX_SYNC_KEY_CHARS} characters")
    # No whitespace, no control characters, no quote/backslash: the key travels as
    # a header value and can travel as a query parameter, and anything that cannot
    # survive either is not a key the app could use. Case is preserved — folding it
    # here would quietly throw away a bit of entropy per character.
    if any(ord(c) < 33 or ord(c) == 127 or c in '"\\' for c in text):
        raise WeakSyncKey("a sync key must not contain whitespace or control characters")
    return text


# ── the attempt tracker ──────────────────────────────────────────────────────


class AttemptTracker:
    """Fixed-window failure counter per presented key, in-process and persisted.

    Memory holds the live window so a burst of guesses costs no I/O; the
    `sync_key_attempts` row is written on every change so a restart (this box runs
    the API under a supervisor that restarts it) inherits the burnout instead of
    handing the guesser a fresh budget. A key not seen since process start has its
    durable row read back first: the table is the source of truth at cold start and
    memory is only the fast path.

    NOT safe across two processes sharing this file — each would keep its own
    window and the row would carry the last writer. That is stated, not hidden:
    today's deployment is one process behind nginx, and the cross-process control
    is the per-IP bucket in `redact.RateLimiter` (§16.5).
    """

    def __init__(self, *, max_failures: int = DEFAULT_MAX_FAILURES,
                 window_seconds: float = DEFAULT_WINDOW_SECONDS,
                 lock_seconds: float = DEFAULT_LOCK_SECONDS,
                 global_max_failures: int = DEFAULT_GLOBAL_MAX_FAILURES,
                 cache_limit: int = 4096):
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = float(window_seconds)
        self.lock_seconds = float(lock_seconds)
        self.global_max_failures = max(1, int(global_max_failures))
        self.cache_limit = max(16, int(cache_limit))
        self._mem: dict[str, tuple[float, int, float]] = {}

    # -- reads -------------------------------------------------------------- #

    def _limit(self, bucket: str) -> int:
        return self.global_max_failures if bucket == GLOBAL_BUCKET else self.max_failures

    def _load(self, conn: sqlite3.Connection, bucket: str) -> tuple[float, int, float]:
        if bucket in self._mem:
            return self._mem[bucket]
        row = conn.execute(
            "SELECT window_started_at, failures, locked_until FROM sync_key_attempts"
            " WHERE bucket = ?", (bucket,)).fetchone()
        state = (float(row[0]), int(row[1]), float(row[2])) if row else (0.0, 0, 0.0)
        self._remember(bucket, state)
        return state

    def _remember(self, bucket: str, state: tuple[float, int, float]) -> None:
        self._mem[bucket] = state
        if len(self._mem) > self.cache_limit:
            # Bounded memory: a flood of distinct wrong keys must not be able to
            # grow our RSS. An evicted window survives in the table and reloads on
            # the next hit, so this costs a read, never a reset.
            for stale in list(self._mem)[:max(1, len(self._mem) // 4)]:
                self._mem.pop(stale, None)

    def state(self, conn: sqlite3.Connection, bucket: str,
              now: float | None = None) -> dict:
        """`{failures, locked, retry_after, window_started_at}` for one bucket at
        `now`. A pure read: an aged-out window is reported refilled, not written.

        When a lock has expired the budget restarts from zero rather than carrying
        the full count over: "burned out" must actually mean "come back later", and
        a window whose failures were all spent under a lock has nothing left to
        say about the next attempt."""
        now = time.time() if now is None else float(now)
        started, failures, locked_until = self._load(conn, bucket)
        if locked_until > now:
            return {"bucket": bucket, "failures": failures, "locked": True,
                    "retry_after": locked_until - now, "window_started_at": started}
        if locked_until:
            return {"bucket": bucket, "failures": 0, "locked": False,
                    "retry_after": 0.0, "window_started_at": now}
        if not started or now - started >= self.window_seconds:
            return {"bucket": bucket, "failures": 0, "locked": False,
                    "retry_after": 0.0, "window_started_at": now}
        return {"bucket": bucket, "failures": failures, "locked": False,
                "retry_after": 0.0, "window_started_at": started}

    def retry_after(self, conn: sqlite3.Connection, bucket: str,
                    now: float | None = None) -> float:
        return float(self.state(conn, bucket, now)["retry_after"])

    # -- writes ------------------------------------------------------------- #

    def record_failure(self, conn: sqlite3.Connection, bucket: str,
                       now: float | None = None) -> dict:
        """Charge one failed presentation.

        Locking is one-way within a window: once locked, further failures do NOT
        push `locked_until` back, or an attacker could extend his own lockout of a
        key forever by hammering it — which would then be a way to make a burned
        bucket permanently indistinguishable from a dead one."""
        now = time.time() if now is None else float(now)
        current = self.state(conn, bucket, now)
        if current["locked"]:
            return current
        started = current["window_started_at"]
        failures = current["failures"] + 1
        locked_until = now + self.lock_seconds if failures >= self._limit(bucket) else 0.0
        self._remember(bucket, (started, failures, locked_until))
        conn.execute(
            """
            INSERT INTO sync_key_attempts(bucket, window_started_at, failures, locked_until)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(bucket) DO UPDATE SET
                window_started_at = excluded.window_started_at,
                failures = excluded.failures,
                locked_until = excluded.locked_until
            """, (bucket, started, failures, locked_until))
        _commit(conn)
        return {"bucket": bucket, "failures": failures, "locked": locked_until > now,
                "retry_after": max(0.0, locked_until - now), "window_started_at": started}

    def record_success(self, conn: sqlite3.Connection, bucket: str,
                       now: float | None = None) -> None:
        """Forget one bucket's window — but only write when there is something to
        forget, so a successful request (the common case by far) does not turn into
        a DELETE plus a commit on every page of the catalog."""
        started, failures, locked_until = self._load(conn, bucket)
        if not failures and not locked_until:
            self._mem.pop(bucket, None)
            return
        self._mem.pop(bucket, None)
        conn.execute("DELETE FROM sync_key_attempts WHERE bucket = ?", (bucket,))
        _commit(conn)

    def sweep(self, conn: sqlite3.Connection, now: float | None = None,
              horizon: float | None = None) -> int:
        """Drop attempt rows older than `horizon` and their memory mirrors, so the
        table cannot accumulate one row per guessed string forever."""
        now = time.time() if now is None else float(now)
        cutoff = now - (ATTEMPT_HORIZON_SECONDS if horizon is None else float(horizon))
        rows = conn.execute(
            "SELECT bucket FROM sync_key_attempts WHERE window_started_at < ?"
            " AND locked_until < ?", (cutoff, cutoff)).fetchall()
        for row in rows:
            self._mem.pop(str(row[0]), None)
        conn.execute("DELETE FROM sync_key_attempts WHERE window_started_at < ?"
                     " AND locked_until < ?", (cutoff, cutoff))
        _commit(conn)
        return len(rows)

    def reset(self) -> None:
        """Forget every in-process window (tests, or a deliberate operator unlock).
        Does not touch the durable rows — call :meth:`sweep` for that."""
        self._mem.clear()


#: The process-wide limiter the HTTP layer should use. A caller may pass its own to
#: `authenticate`/`resolve_account` for an isolated budget or a deterministic test.
attempt_tracker = AttemptTracker()


# ── authentication ───────────────────────────────────────────────────────────


def _authenticate(conn: sqlite3.Connection, key, *, now: float | None = None,
                  tracker: AttemptTracker | None = None,
                  touch: bool = True) -> dict:
    """Resolve a presented sync key to a live account row.

    The limiter is consulted on the FAILURE path only, by design (module
    docstring): a burned-out bucket must never be able to deny a real key. A wrong
    key, a revoked key and a key that was never issued take the same branch — one
    `SELECT` that misses, one failure charged, one `UnknownAccount` — so neither
    the existence nor the history of an account is observable through here."""
    if not isinstance(key, str) or not key.strip():
        raise UnknownAccount()
    tracker = tracker if tracker is not None else attempt_tracker
    now = time.time() if now is None else float(now)
    wanted = _hash_key(key.strip())
    row = conn.execute(
        "SELECT id, key_hash, created_at, last_seen_at, vip_until FROM user_accounts"
        " WHERE key_hash = ?", (wanted,)).fetchone()
    if row is None or not _verify_hash(row["key_hash"], wanted):
        per_key = tracker.record_failure(conn, wanted, now)
        tracker.record_failure(conn, GLOBAL_BUCKET, now)
        if per_key["locked"]:
            raise Locked(retry_after=per_key["retry_after"])
        raise UnknownAccount()
    tracker.record_success(conn, wanted, now)
    account = {"account_id": int(row["id"]), "created_at": float(row["created_at"]),
               "last_seen_at": float(row["last_seen_at"] or 0) or float(row["created_at"]),
               "vip_until": float(row["vip_until"] or 0)}
    if touch and now - account["last_seen_at"] >= LAST_SEEN_WRITE_INTERVAL:
        conn.execute("UPDATE user_accounts SET last_seen_at = ? WHERE id = ?",
                     (now, account["account_id"]))
        account["last_seen_at"] = now
        _commit(conn)
    return account


def authenticate(conn_or_path, key, *, now: float | None = None,
                 tracker: AttemptTracker | None = None) -> dict:
    """The public form: resolve a sync key to its account and bump `last_seen_at`.

    This is what every stateful route calls first. Raises `UnknownAccount` (404) or
    `Locked` (429); returns `{"account_id", "created_at", "last_seen_at",
    "vip_until"}` — never a hash, never a key."""
    with _borrow(conn_or_path) as conn:
        try:
            return _authenticate(conn, key, now=now, tracker=tracker)
        finally:
            _commit(conn)


def vip_status(conn_or_path, key, *, now: float | None = None) -> dict:
    """Read-only VIP check for a presented sync key.

    Deliberately not :func:`authenticate`: the download route asks "is this VIP?"
    on every free request, and a wrong or absent key is an ordinary free user —
    not an attack worth charging against that key's attempt budget (which would
    let anyone lock out a real viewer by hammering their handle). A revoked key
    is not VIP. Returns `{"vip": bool, "vip_until": epoch_seconds}` and never
    raises for an unknown key."""
    moment = time.time() if now is None else float(now)
    if not isinstance(key, str) or not key.strip():
        return {"vip": False, "vip_until": 0.0}
    wanted = _hash_key(key.strip())
    with _borrow(conn_or_path) as conn:
        row = conn.execute(
            "SELECT key_hash, vip_until, revoked_at FROM user_accounts"
            " WHERE key_hash = ?", (wanted,)).fetchone()
    if (row is None or row["revoked_at"] is not None
            or not _verify_hash(row["key_hash"], wanted)):
        return {"vip": False, "vip_until": 0.0}
    until = float(row["vip_until"] or 0)
    return {"vip": until > moment, "vip_until": until}


def key_is_known(conn_or_path, key, *, now: float | None = None) -> bool:
    """Whether this exact sync key is an account this server issued and has not
    revoked. Read-only, no attempt budget charged, no `last_seen_at` written.

    Deliberately not :func:`authenticate`: a caller that only needs to know
    "should I count this device" must not charge a stranger's guesses against a
    real viewer's lockout budget, and must not write on a request that failed.
    """
    if not isinstance(key, str) or not key.strip():
        return False
    wanted = _hash_key(key.strip())
    with _borrow(conn_or_path) as conn:
        row = conn.execute("SELECT revoked_at FROM user_accounts WHERE key_hash = ?",
                           (wanted,)).fetchone()
    return row is not None and row["revoked_at"] is None


def resolve_account(conn_or_path, key, *, now: float | None = None,
                    tracker: AttemptTracker | None = None) -> dict:
    """Alias of :func:`authenticate`, for the caller that just wants to know which
    account a key means. Same answers, same limiter, same leaks-none."""
    return authenticate(conn_or_path, key, now=now, tracker=tracker)


# ── accounts ─────────────────────────────────────────────────────────────────


def create_account(conn_or_path, key=None, *, now: float | None = None) -> dict:
    """Open a sync account and return the plaintext key — the only time this, or
    anything else, can produce it. Show it once, then never again.

    `key` may be a token the *app* minted with :func:`new_sync_key()` (so a device
    that loses the server keeps its own key): it is validated for entropy, never
    logged, never stored in the clear. `None` mints one here.

    Returns `{"account_id", "sync_key", "created_at", "created"}`. Re-presenting an
    existing key is idempotent and answers `created=False` with `sync_key=None` —
    the plaintext is not ours to hand back, and pretending we created a second
    account for the same key would be a lie about what the table says."""
    now = time.time() if now is None else float(now)
    plaintext = new_sync_key() if key is None else _check_sync_key_shape(key)
    wanted = _hash_key(plaintext)
    with _borrow(conn_or_path) as conn:
        row = conn.execute("SELECT id, created_at FROM user_accounts WHERE key_hash = ?",
                           (wanted,)).fetchone()
        if row is not None:
            return {"account_id": int(row["id"]), "sync_key": None,
                    "created_at": float(row["created_at"]), "created": False}
        conn.execute(
            "INSERT INTO user_accounts(key_hash, created_at, last_seen_at, revoked_at)"
            " VALUES(?, ?, ?, NULL)", (wanted, now, now))
        account_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        _commit(conn)
    return {"account_id": account_id, "sync_key": plaintext, "created_at": now,
            "created": True}


# ── the trial gate ───────────────────────────────────────────────────────────


def _check_device_id(device_id) -> str:
    """Validate a client-supplied device identifier without storing junk: bounded,
    stripped, and only characters an installation id actually contains (hex, a
    UUID's dashes, base64url, a colon). No whitespace, no quote, no slash, no
    control character — this string becomes a PRIMARY KEY straight out of a request
    body, and it never becomes anything else, so there is nothing to escape into.
    """
    if not isinstance(device_id, str):
        raise WeakDeviceId("a device id must be a string")
    text = device_id.strip()
    if not (MIN_DEVICE_ID_CHARS <= len(text) <= MAX_DEVICE_ID_CHARS):
        raise WeakDeviceId(
            f"a device id must be {MIN_DEVICE_ID_CHARS}..{MAX_DEVICE_ID_CHARS} "
            "characters")
    if not _DEVICE_ID_RE.fullmatch(text):
        raise WeakDeviceId("that device id uses characters this server cannot store")
    return text


def _mint_account_row(conn, now: float, vip_until: float) -> tuple:
    """Insert an anonymous account and hand back `(account_id, plaintext_key)`.

    The key is generated here and returned once: it is stored as
    `_hash_key(plaintext)` and nothing in this module can serve the plaintext again
    (docstring: "show it once, then never again"). Private because every caller
    that needs the key has to say so in its own response contract."""
    plaintext = new_sync_key()
    conn.execute(
        "INSERT INTO user_accounts(key_hash, created_at, last_seen_at, revoked_at,"
        " vip_until) VALUES(?, ?, ?, NULL, ?)",
        (_hash_key(plaintext), now, now, float(vip_until)))
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]), plaintext


def _trial_answer(device: str, row, vip_until: float, *, sync_key=None,
                  created: bool = False, reissued: bool = False,
                  now: float = 0.0) -> dict:
    """Shape the one response both branches of
    :func:`grant_or_resume_device_trial` give back.

    `trial_expires_at` is always what the ledger says, never a recomputed
    `now + days`, which is the difference between resuming a trial and silently
    granting a second one. `sync_key` is the plaintext only when this call minted
    the account it belongs to, and `vip_until` is the account's live entitlement —
    which a paid plan can carry past the trial, so the two numbers are reported
    separately rather than one standing in for the other."""
    return {
        "device_id": device,
        "account_id": int(row["account_id"]),
        "sync_key": sync_key,
        "created": created,
        "reissued": reissued,
        "first_seen_at": float(row["first_seen_at"]),
        "trial_expires_at": float(row["trial_expires_at"]),
        "trial_seconds_remaining": max(0.0, float(row["trial_expires_at"]) - now),
        "vip_until": float(vip_until or 0),
    }


def grant_or_resume_device_trial(conn_or_path, device_id, *,
                                 now: float | None = None,
                                 trial_days: float = TRIAL_DAYS) -> dict:
    """Start a device's free trial, or resume the one it already has.

    A device the server has never seen gets a brand-new anonymous account (no key
    the human typed, no password, nothing to reuse elsewhere) with
    `vip_until = now + trial_days * 86400`. A device that HAS been seen gets
    **its own stored `trial_expires_at` back** — the clock is the `device_trials`
    row, so reinstalling, revoking the account, or waiting out `prune_accounts()`
    cannot buy a second free trial. That is the entire point of the feature and the
    whole reason the ledger exists: `user_accounts.vip_until` is an entitlement,
    this row is the *record of the grant*, and only the second one is
    un-restartable.

    If the account a trial row points at is gone or revoked, the row re-points at a
    freshly minted account and KEEPS the original expiry — the device gets a usable
    account, which may already be expired, and never a fresh three days. That is
    the one branch that hands back a plaintext key for an existing device, because
    the key belongs to an account minted by this very call.

    Otherwise the resume answer carries `sync_key: None`, and the reason is the
    rule this module has never been able to break: the key is stored one-way, so a
    device that lost it cannot be given it back on the strength of a
    client-chosen `device_id` — which would be an account takeover for anyone who
    guessed one (`created=False`, `reissued=False`, and the app must keep the key
    it was shown at mint).

    Returns `{"device_id", "account_id", "sync_key", "created", "reissued",
    "first_seen_at", "trial_expires_at", "trial_seconds_remaining", "vip_until"}`.
    Concurrent first-sight of one device is settled by the primary key: the loser
    rolls back its orphan account and answers with the winner's row."""
    device = _check_device_id(device_id)
    moment = time.time() if now is None else float(now)
    seconds = max(0.0, float(trial_days)) * DAY_SECONDS
    with _borrow(conn_or_path) as conn:
        row = conn.execute("SELECT * FROM device_trials WHERE device_id = ?",
                           (device,)).fetchone()
        if row is not None:
            return _resume_or_reissue(conn, device, row, moment)
        try:
            account_id, plaintext = _mint_account_row(conn, moment, moment + seconds)
            trial_row = {"account_id": account_id, "first_seen_at": moment,
                         "trial_expires_at": moment + seconds}
            conn.execute(
                "INSERT INTO device_trials(device_id, account_id, first_seen_at,"
                " trial_expires_at) VALUES(?, ?, ?, ?)",
                (device, account_id, moment, moment + seconds))
            _commit(conn)
        except sqlite3.IntegrityError:
            # Another request minted this device between our read and our write.
            # The rollback takes our orphan account with it, so a race cannot leave
            # a second live account behind for the same device id.
            conn.rollback()
            row = conn.execute("SELECT * FROM device_trials WHERE device_id = ?",
                               (device,)).fetchone()
            if row is None:
                raise
            return _resume_or_reissue(conn, device, row, moment)
    return _trial_answer(device, trial_row, moment + seconds, sync_key=plaintext,
                         created=True, now=moment)


def _resume_or_reissue(conn, device: str, row, now: float) -> dict:
    """The resume half of :func:`grant_or_resume_device_trial`, and the only place
    that decides whether a trial row's account is still somebody's."""
    account = conn.execute(
        "SELECT id, vip_until, revoked_at FROM user_accounts WHERE id = ?",
        (int(row["account_id"]),)).fetchone()
    if account is not None and account["revoked_at"] is None:
        return _trial_answer(device, row, account["vip_until"], now=now)
    expiry = float(row["trial_expires_at"])
    account_id, plaintext = _mint_account_row(conn, now, expiry)
    conn.execute("UPDATE device_trials SET account_id = ? WHERE device_id = ?",
                 (account_id, device))
    _commit(conn)
    resumed = {"account_id": account_id, "first_seen_at": row["first_seen_at"],
               "trial_expires_at": expiry}
    return _trial_answer(device, resumed, expiry, sync_key=plaintext, reissued=True,
                         now=now)


# ── the linked profile ───────────────────────────────────────────────────────


def _check_profile_name(name) -> str:
    """Bound and clean a display name. Control characters become a SPACE (a name
    that carries a newline can otherwise forge a line in an operator's log or
    terminal, and "Ali\\nKhan" is two words rather than one long one), whitespace is
    collapsed, then length-checked — a name that arrives as only punctuation or
    spaces is an empty name and gets refused, not stored."""
    if not isinstance(name, str):
        raise WeakProfile("a display name must be a string")
    text = " ".join(_CONTROL_RE.sub(" ", name).split()).strip()
    if not text:
        raise WeakProfile("a display name is required")
    if len(text) > MAX_PROFILE_NAME_CHARS:
        raise WeakProfile(f"a display name must be {MAX_PROFILE_NAME_CHARS} "
                          "characters or fewer")
    return text


def _normalize_phone(phone) -> str:
    """Digits only, so `+92 300 1234567`, `0300-1234567` and `03001234567` all
    arrive as one shape. Deliberately NOT a country-code normalizer: folding the
    local `0300…` form into the international `92300…` one would mean deciding
    which country every caller is in, and a wrong guess there silently merges two
    different people's numbers. Two spellings of one number therefore stay two
    rows, which is reported rather than hidden — the bonus is granted once per
    *account* (see :func:`link_profile_with_pin`), so it is not a way to earn days.
    """
    if not isinstance(phone, str):
        raise WeakProfile("a phone number must be a string")
    digits = "".join(ch for ch in phone if ch.isdigit() and ch.isascii())
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        raise WeakProfile(
            f"a phone number must have {MIN_PHONE_DIGITS}..{MAX_PHONE_DIGITS} digits")
    return digits


def _check_pin(pin) -> str:
    """`MIN_PIN_DIGITS`..`MAX_PIN_DIGITS` ASCII digits, nothing else. ASCII on
    purpose: `str.isdigit()` also accepts `²` and Arabic-Indic `٣`, which would let
    two visually identical PINs hash to different digests, so the shape is checked
    against an explicit byte class and never against Unicode's opinion."""
    if not isinstance(pin, str):
        raise WeakPIN("a PIN must be a string of digits")
    text = pin.strip()
    if not (MIN_PIN_DIGITS <= len(text) <= MAX_PIN_DIGITS):
        raise WeakPIN(
            f"a PIN must be {MIN_PIN_DIGITS}..{MAX_PIN_DIGITS} digits")
    if not _PIN_RE.fullmatch(text):
        raise WeakPIN("a PIN must be digits only")
    return text


def _hash_pin(pin: str, *, iterations: int = PIN_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 with a fresh 128-bit per-row salt, prefix-tagged with the
    cost that made it.

    This is NOT `_hash_key`, and the difference is the whole reason both exist: a
    96-bit minted sync key has no searchable space, so one unsalted sha256 is the
    honest cost, while a 4-digit PIN is 10,000 candidates and a stolen database
    file gets a week offline on them. The salt stops one precomputed table from
    answering every row at once; the iterations slow the guesser who works row by
    row. Neither makes a 4-digit PIN strong, and neither is described here as
    doing so — the thing standing between a PIN that short and a guesser trying
    them over the network is :class:`AttemptTracker` (see `_pin_bucket`)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return "%s%d$%s$%s" % (PIN_HASH_PREFIX, iterations, salt.hex(), digest.hex())


def _verify_pin_hash(stored, pin) -> bool:
    """Re-derive a presented PIN at the cost factor recorded in the row and compare
    in constant time.

    Refuses anything that is not `PIN_HASH_PREFIX`-shaped — including a `sha256:`
    sync-key digest and a `revoked:` tombstone, so no column in this database can
    be spent as the other kind of credential. An iteration count outside
    `1_000`..`MAX_PIN_ITERATIONS` is refused rather than computed: a corrupt or
    hand-edited row must not be able to make one request cost a minute of this box
    (a free denial of service) or 12 iterations (a giveaway)."""
    if not isinstance(stored, str) or not stored.startswith(PIN_HASH_PREFIX):
        return False
    parts = stored[len(PIN_HASH_PREFIX):].split("$")
    if len(parts) != 3:
        return False
    count_text, salt_hex, digest_hex = parts
    try:
        iterations = int(count_text)
        salt = bytes.fromhex(salt_hex)
        want = bytes.fromhex(digest_hex)
    except (TypeError, ValueError):
        return False
    if not (1_000 <= iterations <= MAX_PIN_ITERATIONS):
        return False
    got = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), salt, iterations)
    return hmac.compare_digest(got, want)


def _pin_bucket(account_id) -> str:
    """The attempt window for one account's PIN guesses. Namespaced so it can never
    collide with a bucket keyed on a sync-key digest (`GLOBAL_BUCKET` aside, which
    no PIN path charges — that one counts wrong *keys*, and a wrong PIN is not
    evidence anybody guessed a key)."""
    return "pin:%d" % int(account_id)


def _require_pin_match(conn, account_id, stored_hash, pin, now: float,
                       tracker: AttemptTracker) -> None:
    """Verify a PIN against the row's digest, charging the fixed window on a
    miss. Same shape as `_authenticate`: the limiter is consulted on the failure
    path only, so a burned-out bucket can never deny the person who actually knows
    their PIN, and a guesser runs into `Locked` long before 10^4 tries.

    Raises `PINMismatch` (401) or `Locked` (429) and never says which of a wrong
    PIN and no stored PIN it saw, because a row with no digest is a row nobody
    should be trying to re-link anyway."""
    bucket = _pin_bucket(account_id)
    if _verify_pin_hash(stored_hash, pin):
        tracker.record_success(conn, bucket, now)
        return
    state = tracker.record_failure(conn, bucket, now)
    if state["locked"]:
        raise Locked(retry_after=state["retry_after"])
    raise PINMismatch()


def link_profile_with_pin(conn_or_path, account_id, *, name, phone, pin,
                          now: float | None = None,
                          tracker: AttemptTracker | None = None) -> dict:
    """Bind a name, a phone and a PIN to an account, and grant the bonus day —
    once.

    The first link on an account extends `vip_until` by `PROFILE_BONUS_SECONDS`;
    every later one extends nothing. The record of that is `linked_at`, the column
    the same write sets, so there is no second flag that could drift out of step
    with the fact it tracks and no way to earn the day twice by fixing a typo,
    changing a number, or replaying the request.

    A re-link must present the PIN already on file — the stored digest is proof of
    ownership of the profile, not decoration nobody reads. The PIN itself cannot be
    changed through this function (there is no second field for a new one), and
    there is no PIN reset path yet either: a customer who forgets four digits loses
    the ability to edit that profile, which is a product gap the owner has to
    decide, not something this docstring should pretend away.

    `account_id` is not authority: this writes onto whatever number it is handed,
    so every caller must resolve it from an authenticated sync key first (see
    :func:`authenticate`), and a revoked or absent account is refused exactly like
    any other read. The plaintext PIN never reaches the table, the log, or a
    return value.

    The PIN is a verification factor and never credential material, which is the
    ruling this function exists to honor (`docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md`
    R6). The recovered spec wanted `sync_key = unsalted-SHA256("radd-stream-v2" +
    phone + pin)`: one 10^4-space digest with no salt, which turns a stolen
    `user_state.db` into every linked account — the same defect the phone-derived
    key in `SyncContract.kt` already is, with a thousand times less entropy.
    Nothing here derives a key from anything a person types; `new_sync_key()`'s
    random mint stays the only credential, and this row only proves somebody knew
    the four digits.

    Returns `{"account_id", "linked", "bonus_granted", "vip_until", "phone",
    "name"}` — the phone is the normalized digits (an operator needs to see it, and
    it is not for the wire) and no key, hash or digest is among them."""
    wanted = int(account_id)
    profile_name = _check_profile_name(name)
    digits = _normalize_phone(phone)
    pin_digits = _check_pin(pin)
    moment = time.time() if now is None else float(now)
    with _borrow(conn_or_path) as conn:
        row = conn.execute(
            "SELECT id, vip_until, revoked_at, linked_at, pin_hash FROM user_accounts"
            " WHERE id = ?", (wanted,)).fetchone()
        if row is None or row["revoked_at"] is not None:
            raise UnknownAccount()
        limiter = tracker if tracker is not None else attempt_tracker
        first_link = row["linked_at"] is None
        if first_link:
            # `max(now, vip_until)` rather than a literal `+ 86400`: a trial that
            # lapsed a week ago has already spent its day, and adding to the old
            # number would grant a bonus measured from a date nobody can see. Same
            # law `payments.approve_payment()` applies to a paid plan.
            vip_until = max(moment, float(row["vip_until"] or 0)) + PROFILE_BONUS_SECONDS
            linked_at = moment
        else:
            _require_pin_match(conn, wanted, row["pin_hash"], pin_digits, moment,
                               limiter)
            vip_until = float(row["vip_until"] or 0)
            linked_at = float(row["linked_at"])
        conn.execute(
            "UPDATE user_accounts SET profile_name = ?, phone = ?, pin_hash = ?,"
            " linked_at = ?, vip_until = ? WHERE id = ?",
            (profile_name, digits, _hash_pin(pin_digits), linked_at, vip_until,
             wanted))
        _commit(conn)
    return {"account_id": wanted, "linked": True, "bonus_granted": first_link,
            "vip_until": vip_until, "name": profile_name, "phone": digits}


def revoke_account(conn_or_path, key, *, now: float | None = None,
                   tracker: AttemptTracker | None = None) -> dict:
    """Destroy a sync account: the row stays for audit, the key stops working
    forever.

    The stored hash is rewritten to a `revoked:<sha256>` tombstone. `_hash_key` of
    anything cannot produce that form and `_verify_hash` refuses it, so a revoked
    account stops matching through the identical miss path a never-existed account
    takes — there is no "revoked" answer to distinguish, and no function here can
    serve that library again. Its favorites and progress become unreachable and are
    collected by :func:`prune_accounts` once idle.

    Returns `{"revoked": True, "account_id": N}`. Presenting an unknown or
    already-revoked key raises `UnknownAccount`, exactly as any other read would, so
    "was that key ever somebody's account?" is not a question this answers."""
    now = time.time() if now is None else float(now)
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker, touch=False)
        wanted = _hash_key(str(key).strip())
        tombstone = TOMBSTONE_PREFIX + hashlib.sha256(
            ("revoke:" + wanted).encode("utf-8")).hexdigest()
        conn.execute(
            "UPDATE user_accounts SET key_hash = ?, revoked_at = ?, last_seen_at = ?"
            " WHERE id = ?",
            (tombstone, now, account["last_seen_at"], account["account_id"]))
        _commit(conn)
        return {"revoked": True, "account_id": account["account_id"]}


def account_stats(conn_or_path, key, *, now: float | None = None,
                  tracker: AttemptTracker | None = None) -> dict:
    """Row counts for one account. An operator/CLI diagnostic: it says nothing
    about any work, so it is deliberately not part of any public payload."""
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        out = dict(account)
        out["favorites"] = int(conn.execute(
            "SELECT COUNT(*) FROM user_favorites WHERE account_id = ?",
            (account["account_id"],)).fetchone()[0])
        out["progress"] = int(conn.execute(
            "SELECT COUNT(*) FROM user_progress WHERE account_id = ?",
            (account["account_id"],)).fetchone()[0])
        return out


def prune_accounts(conn_or_path, *, idle_days: float = DEFAULT_IDLE_DAYS,
                   now: float | None = None, tracker: AttemptTracker | None = None,
                   sweep_attempts: bool = True) -> dict:
    """Remove accounts unused for `idle_days`, and with them their favorites and
    progress.

    This is what bounds the table: an optional feature nobody prunes is a table
    that only ever grows, on a box with one CPU and a disk full of catalogs. An
    account is idle when BOTH `created_at` and `last_seen_at` are older than the
    cutoff, so a freshly minted key that was never exercised still gets its full
    grace period, and a row migrated from a schema without `last_seen_at` falls
    back to its creation date instead of being deleted on sight.

    Children are deleted explicitly, not only via `ON DELETE CASCADE`, so pruning
    stays correct on a connection where the caller never set `PRAGMA foreign_keys`
    — without that pragma a cascade is a silent no-op, which is a leak, not a
    feature. Revoked tombstones age out here like anything else.

    With `sweep_attempts` (default) the stale rows of :class:`AttemptTracker` age
    out on the same call, so the attempt table cannot grow one row per guessed
    string forever either.

    A `device_trials` row is collected only when BOTH of those are true: the
    account it points at is gone, and the trial itself expired past the same
    cutoff. A live account keeps its trial record whatever its expiry (that row is
    the thing that stops a second free grant), and an expired trial belonging to a
    still-live account survives too, because that account may be paid. The case
    this does collect is a device whose owner vanished from this server entirely —
    and the law already applied to a person that absent for `idle_days` is that
    their account is gone, so their clock is allowed to restart with it. That is a
    decision with a price on it, stated plainly: `idle_days` of total silence is
    also the window in which a device can come back and be treated as new.

    Returns `{"removed", "favorites_removed", "progress_removed", "cutoff",
    "attempts_removed", "trials_removed"}`. Never touches an account still in
    use."""
    now = time.time() if now is None else float(now)
    cutoff = now - max(0.0, float(idle_days)) * 86400.0
    idle = ("(CASE WHEN last_seen_at > created_at THEN last_seen_at ELSE created_at END) < ?")
    with _borrow(conn_or_path) as conn:
        ids = [int(row[0]) for row in conn.execute(
            f"SELECT id FROM user_accounts WHERE {idle}", (cutoff,))]
        favorites = progress = attempts = trials = 0
        if ids:
            marks = ",".join("?" * len(ids))
            favorites = int(conn.execute(
                f"SELECT COUNT(*) FROM user_favorites WHERE account_id IN ({marks})",
                ids).fetchone()[0])
            progress = int(conn.execute(
                f"SELECT COUNT(*) FROM user_progress WHERE account_id IN ({marks})",
                ids).fetchone()[0])
            conn.execute(f"DELETE FROM user_favorites WHERE account_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM user_progress WHERE account_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM user_accounts WHERE id IN ({marks})", ids)
        if _has_table(conn, "device_trials"):
            trials = int(conn.execute(
                "SELECT COUNT(*) FROM device_trials WHERE trial_expires_at < ?"
                " AND account_id NOT IN (SELECT id FROM user_accounts)",
                (cutoff,)).fetchone()[0])
            conn.execute("DELETE FROM device_trials WHERE trial_expires_at < ?"
                         " AND account_id NOT IN (SELECT id FROM user_accounts)",
                         (cutoff,))
        if sweep_attempts:
            attempts = (tracker if tracker is not None else attempt_tracker).sweep(conn, now)
        _commit(conn)
    return {"removed": len(ids), "favorites_removed": favorites,
            "progress_removed": progress, "cutoff": cutoff,
            "attempts_removed": attempts, "trials_removed": trials}


# ── the visibility oracle (adult rule + provenance rule) ─────────────────────


def _open_catalog_read_only(path) -> sqlite3.Connection:
    """A catalog connection opened `mode=ro`: this module must never be the thing
    that writes to a projected catalog — or to the multi-hour projection database
    that sits beside it."""
    text = str(path)
    conn = sqlite3.connect(f"file:{text}?mode=ro", uri=True,
                           timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
    return conn


#: `cat_works` is the surface a `work_key` lives on (`catalog_v2.work_key_for`),
#: and the predicate is the one `redact.adult_clause` / every v2 list route uses.
_CATALOG_VISIBLE_SQL = (
    "SELECT 1 FROM cat_works WHERE work_key = ?"
    " AND (is_18_plus IS NULL OR is_18_plus = 0) LIMIT 1")

#: A `work_key` we could plausibly have minted: `imdb:tt1234567`, `tmdb:12345`,
#: `series:a normalized title:2024`. Anything scheme-ish, path-ish or
#: control-character-ish is not our identifier — it is somebody trying to get a URL
#: into the user-state table, and the provenance rule says it does not get in.
#: Refused as `UnknownWork`: "I cannot see that work" is the only sentence this API
#: says about an identifier, in either case.
_URLISH_RE = re.compile(r"""://|\\|%2f|/|^(?:https?|ftp|file|data|javascript):""",
                        re.IGNORECASE)


def _normalize_work_key(work_key) -> str:
    text = str(work_key if work_key is not None else "").strip()
    if not (1 <= len(text) <= MAX_WORK_KEY_CHARS):
        raise UnknownWork()
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise UnknownWork()
    if _URLISH_RE.search(text):
        raise UnknownWork()
    return text


def _normalize_scope(season_number, episode_number) -> tuple[int, int]:
    """Season/episode as stored ints, `0` meaning "not applicable" (a movie, a work
    watched without an episode, a single-season show).

    `0` and NOT `NULL` is deliberate: SQLite treats NULLs as DISTINCT inside a
    UNIQUE index, so `UNIQUE(account_id, work_key, season, episode)` with NULL
    scopes would happily file the same favorite twice and re-add would not be
    idempotent — the exact defect the re-add test in `test_accounts.py` exists to
    catch."""
    out = []
    for value in (season_number, episode_number):
        if value in (None, "", 0, "0", False):
            out.append(0)
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise UnknownWork() from None
        if not (0 <= number <= 99999):
            raise UnknownWork()
        out.append(number)
    return out[0], out[1]


def work_is_visible(catalog, work_key) -> bool:
    """Is this `work_key` a work the public may be told about at all?

    `catalog` may be a `cat_works`-bearing connection, a path to one, or a
    `callable(work_key) -> bool` (the HTTP layer's own cached lookup, which is what
    it should pass — one lookup per request, not one `sqlite3.connect` per row).

    A missing `cat_works`, an unreadable file or a raising callable is
    :class:`CatalogUnreachable`, never `False`: an absent table means "I could not
    check", and answering 404 for every work because a deployment pointed at the
    wrong file would be indistinguishable from the adult rule having eaten the
    catalog."""
    text = str(work_key or "")
    if not text:
        return False
    # A `sqlite3.Connection` IS callable (`conn("SELECT …")` runs the SQL), so the
    # type checks below are ordered deliberately: ask for a Connection first or a
    # catalog handle would be invoked as a statement instead of being queried.
    conn = catalog if isinstance(catalog, sqlite3.Connection) else None
    if conn is None and callable(catalog):
        try:
            return bool(catalog(text))
        except Exception as exc:                     # the oracle itself failed
            raise CatalogUnreachable(str(exc)[:200]) from exc
    owns = False
    if conn is None:
        try:
            conn = _open_catalog_read_only(catalog)
            owns = True
        except sqlite3.Error as exc:
            raise CatalogUnreachable(str(exc)[:200]) from exc
    try:
        try:
            return conn.execute(_CATALOG_VISIBLE_SQL, (text,)).fetchone() is not None
        except sqlite3.Error as exc:
            raise CatalogUnreachable(str(exc)[:200]) from exc
    finally:
        if owns:
            conn.close()


def _require_visible(catalog, work_key) -> str:
    """Normalize a work key and assert it is displayable, or raise `UnknownWork`.

    A flagged work raises the identical error an absent work raises, from the
    identical branch, with an identical message and no key echoed back: that is
    §13's rule implemented on the WRITE path too, not just the read path, so a
    client cannot even file a bookmark it would not be shown."""
    text = _normalize_work_key(work_key)
    if catalog is None:
        # Fail closed rather than store a key we could not check. Deliberately a
        # 5xx: the caller mis-wired its dependency, and pretending the work does
        # not exist would blame the user for our plumbing.
        raise CatalogUnreachable(
            "a catalog visibility check is required for every write")
    if not work_is_visible(catalog, text):
        raise UnknownWork()
    return text


def to_public(row, mint) -> dict:
    """Project one state row into something the public port may serialise.

    `mint` is required and must turn a work key into an opaque handle — in
    deployment that is `lambda key: redact.mint_text(key, redact.stream_secret(db))`.
    The name is `PUBLIC_REF_KEY` (`work_ref`), chosen because `redact.MINTED_KEYS`
    already masks it from the sentinel scan and `redact.PROVENANCE` does not forbid
    it, so the value is our noise and the identifier survives the edge scrubber
    intact — and because it is the same key the catalog uses for a minted work
    handle, so a client learns one name, not two.

    Passing `mint=None` raises instead of falling back to the raw key: a work key
    can itself be a polluted scraped headline (`series:… katmoviehd …`), so a
    default that leaked one would be the one bug this function exists to prevent.
    The row that comes back has no `account_id` either — our row number is not the
    client's identity, and ids move on every rebuild (§3)."""
    if not callable(mint):
        raise ValueError("a public payload must not carry a raw work key; pass a mint callable")
    if not isinstance(row, dict):
        raise ValueError("to_public takes one row dict")
    out = {}
    for key, value in row.items():
        if key == "work_key":
            out[PUBLIC_REF_KEY] = mint(value)
        elif key in ("account_id", "id", "key_hash"):
            continue
        else:
            out[key] = value
    return out


def to_public_list(rows, mint) -> list:
    """:func:`to_public` over a list, order preserved (newest-first as read)."""
    return [to_public(row, mint) for row in rows]


# ── favorites ────────────────────────────────────────────────────────────────


def _favorite_row(conn, account_id, work_key, season, episode) -> dict:
    row = conn.execute(
        "SELECT work_key, season_number, episode_number, added_at FROM user_favorites"
        " WHERE account_id = ? AND work_key = ? AND season_number = ?"
        " AND episode_number = ?",
        (account_id, work_key, season, episode)).fetchone()
    if row is None:
        return {}
    return {"work_key": str(row["work_key"]),
            "season_number": int(row["season_number"]),
            "episode_number": int(row["episode_number"]),
            "added_at": float(row["added_at"])}


def put_favorite(conn_or_path, key, work_key, *, catalog=None, season_number=None,
                 episode_number=None, added_at: float | None = None,
                 now: float | None = None, tracker: AttemptTracker | None = None) -> dict:
    """Add a favorite for the account behind `key`. Re-adding is idempotent: one
    row, and the row that comes back is what the table holds, not what this call
    asked for.

    Two devices with the same key ARE the same account, so whichever one hearts a
    title first owns the timestamp: `added_at` is `LEAST`ed, never overwritten.
    A device whose clock is behind must not move a bookmark backwards, and one
    whose clock is ahead must not jump it forward — either way the earliest claim
    of "since when did you want this" is the honest one.

    `catalog` is required (see `_require_visible`) and is the adult + provenance
    gate: the key is checked against `cat_works` before anything is written, so no
    flagged work and no caller-supplied URL can enter this table."""
    now = time.time() if now is None else float(now)
    text = _require_visible(catalog, work_key)
    season, episode = _normalize_scope(season_number, episode_number)
    stamp = now if added_at is None else float(added_at)
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        existing = _favorite_row(conn, account["account_id"], text, season, episode)
        if not existing:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM user_favorites WHERE account_id = ?",
                (account["account_id"],)).fetchone()[0])
            if total >= MAX_FAVORITES:
                raise AccountFull(f"a library holds at most {MAX_FAVORITES} favorites")
        conn.execute(
            """
            INSERT INTO user_favorites(account_id, work_key, season_number, episode_number, added_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(account_id, work_key, season_number, episode_number) DO UPDATE SET
                added_at = MIN(added_at, excluded.added_at)
            """, (account["account_id"], text, season, episode, stamp))
        _commit(conn)
        return _favorite_row(conn, account["account_id"], text, season, episode)


def delete_favorite(conn_or_path, key, work_key, *, catalog=None, season_number=None,
                    episode_number=None, now: float | None = None,
                    tracker: AttemptTracker | None = None) -> bool:
    """Remove a favorite. Deleting something already gone answers `False` — not an
    error, and not a hint about whether the work exists.

    When `catalog` is given the visibility check runs first, so a removal aimed at
    an invisible (or flagged) work key raises the same `UnknownWork` a write would
    and deletes nothing: this function cannot be used to ask whether a key is in
    somebody's list."""
    now = time.time() if now is None else float(now)
    text = _normalize_work_key(work_key)
    season, episode = _normalize_scope(season_number, episode_number)
    if catalog is not None and not work_is_visible(catalog, text):
        raise UnknownWork()
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        cur = conn.execute(
            "DELETE FROM user_favorites WHERE account_id = ? AND work_key = ?"
            " AND season_number = ? AND episode_number = ?",
            (account["account_id"], text, season, episode))
        _commit(conn)
        return cur.rowcount > 0


def list_favorites(conn_or_path, key, *, catalog=None, limit: int | None = None,
                   now: float | None = None, tracker: AttemptTracker | None = None,
                   hide_invisible: bool = True) -> list:
    """The account's favorites, newest `added_at` first: the shape a second device
    needs to rebuild the same library.

    Titles, posters and years are NOT returned — they are catalog data, the caller
    resolves them from the work identifier, and that is also why this response can
    never name a site. When `catalog` is given, rows whose work has since become
    invisible (absent, or flagged `is_18_plus` after the bookmark was filed) are
    filtered here at display time and are never deleted: the row stays, so the
    title reappears if the flag ever clears, and the ledger loses nothing.

    Returns internal rows with `work_key`; pass them through :func:`to_public`
    before serialising."""
    now = time.time() if now is None else float(now)
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        sql = ("SELECT work_key, season_number, episode_number, added_at FROM user_favorites"
               " WHERE account_id = ? ORDER BY added_at DESC, id DESC")
        params: list = [account["account_id"]]
        if limit:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        rows = conn.execute(sql, params).fetchall()
    out = [{"work_key": str(r["work_key"]), "season_number": int(r["season_number"]),
            "episode_number": int(r["episode_number"]), "added_at": float(r["added_at"])}
           for r in rows]
    if catalog is not None and hide_invisible:
        out = [row for row in out if work_is_visible(catalog, row["work_key"])]
    return out


# ── playback progress ────────────────────────────────────────────────────────


def _progress_row(conn, account_id, work_key, season, episode) -> dict:
    row = conn.execute(
        "SELECT work_key, season_number, episode_number, position_seconds,"
        " duration_seconds, client_updated_at, updated_at FROM user_progress"
        " WHERE account_id = ? AND work_key = ? AND season_number = ?"
        " AND episode_number = ?",
        (account_id, work_key, season, episode)).fetchone()
    if row is None:
        return {}
    return {"work_key": str(row["work_key"]),
            "season_number": int(row["season_number"]),
            "episode_number": int(row["episode_number"]),
            "position_seconds": float(row["position_seconds"]),
            "duration_seconds": float(row["duration_seconds"]),
            "client_updated_at": float(row["client_updated_at"]),
            "updated_at": float(row["updated_at"])}


def _seconds(value, field: str) -> float:
    """A non-negative finite number, or `InvalidProgress`.

    NaN and inf are refused outright rather than clamped: they would be stored,
    then compared, and every `>=` against a NaN is false — one poisoned row would
    then accept any later write from any device, which is precisely the
    last-write-wins property this table exists to guarantee."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvalidProgress(f"{field} must be a number of seconds") from None
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        raise InvalidProgress(f"{field} must be a non-negative finite number")
    return number


def put_progress(conn_or_path, key, work_key, *, catalog=None, position_seconds=0.0,
                 duration_seconds=0.0, season_number=None, episode_number=None,
                 client_updated_at: float | None = None, now: float | None = None,
                 tracker: AttemptTracker | None = None) -> dict:
    """Record where the viewer stopped, last-write-wins per (work, season, episode).

    STALENESS IS DECIDED ON THE CLIENT'S CLOCK, not ours. Two devices syncing one
    library are two clocks, and the only timestamp either can honestly mean by
    "I watched this most recently" is its own — so `client_updated_at` is the
    comparison key and `updated_at` (our receipt time) is bookkeeping. A write whose
    client timestamp is not newer than the stored one is **ignored, not rejected**:
    the answer is the row that survived, with `applied: False`, so a client retrying
    an old position learns the row is intact instead of hearing an error. A tie goes
    to what the server already holds — the same instant cannot be newer than itself.

    A client clock more than `CLOCK_SKEW_TOLERANCE` ahead of ours is clamped to our
    receipt time; otherwise a device stuck showing 2035 would win every comparison
    forever and no other device could ever update that row again. With no
    `client_updated_at` supplied we use ours, which makes single-device use
    trivially correct.

    `position_seconds` is clamped into `[0, duration_seconds]` when a duration is
    known, so a client reporting 4000 s into a 2000 s file cannot make the row
    unsatisfiable. No percentage is stored: `CacheTaskEntity.percent()` is the
    client's derived display value and the same rule applies on the server."""
    now = time.time() if now is None else float(now)
    text = _require_visible(catalog, work_key)
    season, episode = _normalize_scope(season_number, episode_number)
    position = _seconds(position_seconds, "position_seconds")
    duration = _seconds(duration_seconds, "duration_seconds")
    if duration > 0:
        position = min(position, duration)
    if client_updated_at is None:
        stamp = now
    else:
        stamp = _seconds(client_updated_at, "client_updated_at")
        if stamp > now + CLOCK_SKEW_TOLERANCE:
            stamp = now
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        current = _progress_row(conn, account["account_id"], text, season, episode)
        if current and float(current["client_updated_at"]) >= stamp:
            current["applied"] = False
            return current
        if not current:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM user_progress WHERE account_id = ?",
                (account["account_id"],)).fetchone()[0])
            if total >= MAX_PROGRESS:
                raise AccountFull(
                    f"an account holds at most {MAX_PROGRESS} progress rows")
        conn.execute(
            """
            INSERT INTO user_progress(account_id, work_key, season_number, episode_number,
                                      position_seconds, duration_seconds,
                                      client_updated_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, work_key, season_number, episode_number) DO UPDATE SET
                position_seconds = excluded.position_seconds,
                duration_seconds = excluded.duration_seconds,
                client_updated_at = excluded.client_updated_at,
                updated_at = excluded.updated_at
            """, (account["account_id"], text, season, episode, position, duration,
                  stamp, now))
        _commit(conn)
        row = _progress_row(conn, account["account_id"], text, season, episode)
        row["applied"] = True
        return row


def get_progress(conn_or_path, key, work_key, *, catalog=None, season_number=None,
                 episode_number=None, now: float | None = None,
                 tracker: AttemptTracker | None = None) -> dict:
    """One (work, season, episode) progress row, or `{}` when nothing is stored.

    An invisible or malformed work key is answered with `{}` rather than
    `UnknownWork`: "no progress for you" and "no such work" are the same sentence
    under §13, and a 404 here would let a prober ask which flagged titles this
    account has watched. A row that exists for a work that has since been flagged is
    filtered here too, exactly like :func:`list_progress`.

    The account key is checked FIRST, in every path: a read that answered
    `{}` for a bad key plus a odd work key would be a success-shaped reply an
    attacker could use to skip the limiter."""
    now = time.time() if now is None else float(now)
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        try:
            text = _normalize_work_key(work_key)
            season, episode = _normalize_scope(season_number, episode_number)
        except UnknownWork:
            return {}
        row = _progress_row(conn, account["account_id"], text, season, episode)
    if not row:
        return {}
    if catalog is not None and not work_is_visible(catalog, row["work_key"]):
        return {}
    return row


def list_progress(conn_or_path, key, *, catalog=None, limit: int | None = None,
                  now: float | None = None, tracker: AttemptTracker | None = None,
                  hide_invisible: bool = True) -> list:
    """Continue-watching, most recently updated first. The same display-time adult
    filter as :func:`list_favorites`, for the same reason."""
    now = time.time() if now is None else float(now)
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        sql = ("SELECT work_key, season_number, episode_number, position_seconds,"
               " duration_seconds, client_updated_at, updated_at FROM user_progress"
               " WHERE account_id = ? ORDER BY client_updated_at DESC, id DESC")
        params: list = [account["account_id"]]
        if limit:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        rows = conn.execute(sql, params).fetchall()
    out = [{"work_key": str(r["work_key"]), "season_number": int(r["season_number"]),
            "episode_number": int(r["episode_number"]),
            "position_seconds": float(r["position_seconds"]),
            "duration_seconds": float(r["duration_seconds"]),
            "client_updated_at": float(r["client_updated_at"]),
            "updated_at": float(r["updated_at"])} for r in rows]
    if catalog is not None and hide_invisible:
        out = [row for row in out if work_is_visible(catalog, row["work_key"])]
    return out


def delete_progress(conn_or_path, key, work_key, *, season_number=None,
                    episode_number=None, now: float | None = None,
                    tracker: AttemptTracker | None = None) -> bool:
    """Forget progress for one (work, season, episode) — "watched", "start over".
    An unknown or malformed work key answers `False` and deletes nothing; the
    account key is always checked first."""
    now = time.time() if now is None else float(now)
    with _borrow(conn_or_path) as conn:
        account = _authenticate(conn, key, now=now, tracker=tracker)
        try:
            text = _normalize_work_key(work_key)
            season, episode = _normalize_scope(season_number, episode_number)
        except UnknownWork:
            return False
        cur = conn.execute(
            "DELETE FROM user_progress WHERE account_id = ? AND work_key = ?"
            " AND season_number = ? AND episode_number = ?",
            (account["account_id"], text, season, episode))
        _commit(conn)
        return cur.rowcount > 0


# ── operator CLI ─────────────────────────────────────────────────────────────
#
# No HTTP here (that is viewer.py's) and no network either: this is for the
# operator's own shell and cron. `create` is the one command that prints a secret —
# to stdout, once, by design, exactly as the API returns it once.


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Manage the optional sync-key accounts in user_state.db.")
    parser.add_argument("--db", default=None, help="path (default: %s)" % default_db_path())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create", help="mint an account and print its sync key once")
    p_revoke = sub.add_parser("revoke", help="revoke the account behind a sync key")
    p_revoke.add_argument("key")
    p_prune = sub.add_parser("prune", help="delete accounts idle for N days")
    p_prune.add_argument("--idle-days", type=float, default=DEFAULT_IDLE_DAYS)
    p_stats = sub.add_parser("stats", help="row counts for one account")
    p_stats.add_argument("key")
    sub.add_parser("summary", help="how many accounts and rows exist in total")
    return parser.parse_args(argv)


def _summary(conn_or_path) -> dict:
    with _borrow(conn_or_path) as conn:
        out = {}
        for table in ("user_accounts", "user_favorites", "user_progress",
                      "sync_key_attempts", "device_trials"):
            out[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        out["accounts_live"] = int(conn.execute(
            "SELECT COUNT(*) FROM user_accounts WHERE revoked_at IS NULL").fetchone()[0])
        # How much personal data this file actually holds. The operator's number to
        # decide whether that is still the right trade (`profile_state` prints the
        # name and phone of ONE account, given its id; nothing prints a list).
        out["profiles_linked"] = int(conn.execute(
            "SELECT COUNT(*) FROM user_accounts WHERE linked_at IS NOT NULL").fetchone()[0])
    out["schema_version"] = schema_version(conn_or_path)
    return out


def main(argv=None) -> int:
    args = parse_args(argv)
    db = args.db or default_db_path()
    if args.command == "create":
        account = create_account(db)
        print(f"account {account['account_id']} created")
        print(f"sync key (shown once, store it now): {account['sync_key']}")
        return 0
    if args.command == "revoke":
        result = revoke_account(db, args.key)
        print(f"account {result['account_id']} revoked")
        return 0
    if args.command == "prune":
        result = prune_accounts(db, idle_days=args.idle_days)
        print(f"removed {result['removed']} idle accounts "
              f"({result['favorites_removed']} favorites, "
              f"{result['progress_removed']} progress rows, "
              f"{result['attempts_removed']} attempt rows, "
              f"{result['trials_removed']} expired trial rows)")
        return 0
    if args.command == "stats":
        for name, value in account_stats(db, args.key).items():
            print(f"{name}: {value}")
        return 0
    for name, value in _summary(db).items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
