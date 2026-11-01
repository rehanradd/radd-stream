# MUSE PHASE 1 (q5) — the money-and-keys verdict, from the code at trunk

**Scope and method.** Everything below was read from source in my worktree at branch
`q5-agents-count-method-20261101`, which contains trunk `636eda5` (`git merge-base --is-ancestor 636eda5 HEAD`
→ yes). **No database was opened, no route was probed, no write was attempted** — a production read is
frozen on this box and I have not needed it: every claim here is a statement about code, so a line number
is a complete citation. Where a question can only be answered by reading rows, it is listed under *Not
measured* rather than guessed at. Money = `payments.py` + `engagement.py` + the coin ledger; keys =
`accounts.py` + the `redact.py` handle/pass minters.

**Verdict in one line:** the money path is **integer, append-only and atomic where it matters**, and I
found no way to spend a coin twice or mint one from a client; the key path is **sound for the secret it
actually protects and weak in two places it does not say it is weak** — a fixed keystream under the
"opaque" public handles, and 32-bit tags on the two handle minters while the capability pass gets 64.
Neither is a live theft: both are properties to fix before the app leans harder on them.

---

## A. Money — what is true, with the line it is true at

| # | claim | cite |
|---|---|---|
| M1 | **Money is an integer end to end.** Coins: `delta INTEGER NOT NULL` ("whole coins"). Balance is **derived**, never stored — `SELECT COALESCE(SUM(delta),0)` — so there is no balance column to drift, to be written stale, or to be raced. | `engagement.py:294`, `:636-640` |
| M2 | PKR is coerced through one gate: `int(value)`, **`bool` rejected on purpose** ("a column holding `1` where a price should be is a mistake, not PKR 1"), range-bounded by `_MAX_PKR = 10_000_000`, `None` for anything unusable. Floats survive only in *timestamps* (`created_at REAL`). | `payments.py:221-233`, `:109`, `engagement.py:299` |
| M3 | **A client cannot name its own price.** A body carrying `amount_pkr`/`amount` is refused with one uniform answer; the plan name is the only price input, and the reply's `amount_pkr` is what *this server* charges at that moment. | `payments.py:37-38`, `:174`, `:359-374` |
| M4 | **Check-and-debit is one statement.** `INSERT … SELECT … WHERE (SELECT SUM(delta) …) >= ?` — the balance test runs under SQLite's write lock, so two simultaneous redemptions cannot both pass it; `rowcount == 0` raises `InsufficientCoins`. This is the correct shape, and it is why there is no read-modify-write window to close with a mutex. | `engagement.py:752-761` |
| M5 | **The ledger is append-only by the database, not by convention**: `BEFORE UPDATE` and `BEFORE DELETE` triggers `RAISE(ABORT, …)`. A disputed grant is still there to be read. Coins cascade with the account (entitlement, not a receipt); the **payments** ledger deliberately does not — that asymmetry is documented at the schema and is the right way round. | `engagement.py:326-338`, `:290-292` |
| M6 | **Idempotency is a constraint, not a memory.** `idempotency_key TEXT UNIQUE` with `NULL` allowed. A retried ad callback lands once. | `engagement.py:297`, `:44` |
| M7 | **A price the operator never saved does not become free VIP.** `price_table()` falls back to the shipped `PLAN_DEFAULTS`, but an *unusable* stored price yields a refusal: "the price of that plan is unavailable". `0` is treated as a broken settings row, not a bargain. Fail-closed, correctly. | `payments.py:235-273`, `:375-377` |
| M8 | **A ladder tier that cannot say when it expires is refused before any coin moves.** `BadLadder` is raised pre-debit; the historic bug was ordering (`spend` first, `expiry` branch second), which cost coins and minted nothing. The docstring names the ordering as the bug, which is the right lesson to leave in the file. | `engagement.py:211-215`, `:960-990` |
| M9 | Grants are server-authored only: `source` must be in `SERVER_SOURCES` (`'server'`/`'admin'`), `reason` in a closed set, `amount` a positive int, and the rewarded-ad path is capped per day-bucket. A client claim "never reaches here" because the telemetry route is not wired to `grant_coins`. | `engagement.py:712-721`, `:183-190`, `:120-121` |

### Money — two defects worth a ticket, neither of them theft

**MD-1 — a same-key race answers 500 instead of "already applied".** `spend_coins` reads for the key
(`:747-751`) and then writes with a **plain** `INSERT … SELECT` (`:752-759`), while `grant_coins`'s writer
`_insert_ledger` uses `INSERT OR IGNORE` (`:627-633`). Two requests carrying the same `idempotency_key`
in flight together: the first commits, the second's pre-check saw nothing, and its insert hits the UNIQUE
constraint and raises `sqlite3.IntegrityError` out of the route. **No money is lost and no double-debit
occurs** — the constraint is exactly what makes that true — but a well-behaved client that retries gets a
500 where the API promises `already_applied: True`. The minimal fix is to catch `IntegrityError` on the
`idempotency_key` column and re-read, returning the same `already_applied` shape the pre-check returns;
it must not become `INSERT OR IGNORE`, which is how you get MD-2.

**MD-2 — `INSERT OR IGNORE` conflates "duplicate key" with "the row was rejected".** `_insert_ledger`
returns `cur.rowcount`, and `grant_coins` reports `{"granted": wrote, "idempotent": wrote == 0}`
(`:722-729`). `OR IGNORE` suppresses **every** constraint violation, not only the UNIQUE one: a `NOT NULL`,
a `CHECK`, or a foreign-key failure (`account_id REFERENCES user_accounts(id)`, with
`PRAGMA foreign_keys = ON` per-connection at `:237`) all arrive at the caller as *a deduplicated replay*
— a successful-looking reply in which nothing was granted. Today it is unreachable, and the reason it is
unreachable is call order: `_require_account` (`:718`) and the reason/source validation (`:712-715`) run
first, so the only live constraint is the key. That is a **load-bearing accident**: the next column with
a `CHECK` turns "this grant was rejected" into "this grant was already made". Either insert without
`OR IGNORE` and handle the UNIQUE violation explicitly, or distinguish the two outcomes (SQLite's
`changes()` cannot tell them apart; the constraint name in the exception message can).

### Money — one design question to decide before Phase 3

**MQ-1 — the default idempotency key for a redemption is second-granular.** `redeem_pass` synthesises
`f"redeem:{account_id}:{plan}:{int(moment)}"` when the caller passes no key (`:987-988`). A retry that
lands one second later is, to this scheme, a *new purchase*: coins move twice and two passes are minted.
Nothing is stolen — the viewer got what they paid for, twice — but a timeout-prone network makes a viewer
pay for a pass they already hold, and the app cannot currently tell the server "this is the same intent".
The design answer is to make the key **caller-owned for this route** (the app generates one per user
tap, per the same discipline as the ad callback id) rather than to widen the server's time bucket —
a 60-second bucket would silently *refuse* a second legitimate purchase of the same plan. Both options
need the app lane (q4) to agree; that is why this is a question and not a patch.

---

## B. Keys — what is sound

| # | claim | cite |
|---|---|---|
| K1 | **Comparisons are constant-time everywhere I could reach.** `hmac.compare_digest` on pass tags, token tags and stored key digests — never `==`, never a prefix or length test. The file states the rule and the code follows it. | `redact.py:885`, `:917`, `:940`; `accounts.py:803-812`, `:1360` |
| K2 | **A minted sync key does not need a slow KDF.** `secrets.token_urlsafe(12)` = 96 uniform bits, digested unsalted `sha256:`; the search space, not the per-hash cost, is what protects it, and the docstring argues this explicitly rather than assuming it. | `accounts.py:768`, `:771-795`, `:299` |
| K3 | **The PIN's weakness is admitted, not hidden** — 4 digits under 120k-iteration PBKDF2 is guessable by whoever owns the file, and the comment says so — and the *actual* control is the attempt tracker: `sync_key_attempts` is mirrored in-process so a restart does not reset the window, `locked_until` cannot be extended by the attacker's own traffic, and stale buckets are swept by the housekeeper. | `accounts.py:258-266`, `:1331`, `:573`, `:129`, `:873-970`, `:922`, `:1571` |
| K4 | **The capability pass is the strongest thing in the set**: version byte + 8-byte expiry + **8-byte HMAC tag** (64-bit) over a domain-separated message (`b"vip" + body`), verified with `compare_digest`, and expiry is compared against the server clock. Truncating `expires_at` to whole seconds *before* signing (`engagement.py:991`) is the right detail — a sub-second float would make the token unstable. | `redact.py:891-921` |
| K5 | **A phone-derived key is the file's own named exception**: same digest, real input space = the phone-number space, so the digest is brute-forceable "no matter what this function costs". The code says this; nobody should re-litigate it as a docstring bug. | `accounts.py:782-790` |

## B′. Keys — two properties that are weaker than the naming suggests

**KD-1 — the handle "cipher" uses a fixed keystream, so one known pair de-opaques every handle.**
`_keystream(secret, n, salt)` is `SHA-256(secret ‖ salt ‖ counter)` iterated to length — the only inputs
are the secret, a **purpose label** (`"id"` / `"txt"`) and a block counter. `mint_token` XORs an 8-byte
row id against it (`redact.py:832-840`, `:856-861`). Consequence: *the pad is identical for every row id*,
because every id is packed as `>q` = 8 bytes. Anyone holding one `(row id, handle)` pair — which the
deployment hands out freely wherever both forms are visible, e.g. the operator panel's `/api/data` full
rows and any log line naming an id beside a `stream_id` — recovers the pad and can then decode **every**
8-byte handle in the wild back to its sequential row id. What that does *not* buy: the tag is still
HMAC-under-the-secret, so a decoded id cannot be re-minted as a valid handle for a *chosen* id
(the public port also refuses plain integers when `signed_only` is set). So the exposure is
**de-anonymisation of observed handles and loss of the enumeration defence the docstring at `:869-872`
claims to provide**, not forgery. Fix shape (stdlib, cheap): draw `secrets.token_bytes(8)` per mint, mix
it into the keystream salt, carry it in the token body, and sign `nonce ‖ body` — the pad then differs
per handle. Token grows 8 bytes; nothing about the API shape changes.

**KD-2 — the two handle minters sign with a 32-bit tag while the pass signs with 64.** `mint_token` and
`mint_text` truncate the digest to `[:4]` (`:860`, `:884`, `:928`, `:941`); `mint_vip_pass` uses `[:8]`
(`:904`). 4 bytes is deliberate (handles ride in URLs), and the forgery cost per guess is 2⁻³², which is
*fine* for a row-id handle and *wrong-shaped* for anything that grants access: a VIP pass — which is a
capability, "whoever holds it is treated as VIP", with no revocation list — would be a 2³²-guess oracle
if it had inherited the 4-byte form. It does not, so today the asymmetry is a note, not a hole. Two
follow-ups: keep the 8-byte tag on anything that carries an entitlement (a guard test can pin the
truncation length per minter, because today nothing stops a future `[:4]` landing on a capability), and
rate-limit or reject-loop the routes that call `parse_token`, since 2⁻³² per guess is only a large number
if guesses are free.

**KD-3 — an unconfigured signing secret silently publishes raw row ids.** Every call site I read is
written `mint_token(id, secret) if secret else str(id)` (e.g. `api_v2.py:1141`, `:1342`,
`catalog_api.py:703`). That fallback is the right behaviour for a development box and the wrong default
for a deployment: it turns the opaque-handle rule into a configuration accident, one env var away from
being broken, with no log line and no failing test. The cheap instrument is the guard q4 already needs —
see [`MUSE_PHASE1_Q5_CINEFINDER_QA.md`](MUSE_PHASE1_Q5_CINEFINDER_QA.md) §2: *a public response must not
carry a bare integer where a handle belongs*, asserted by a test that starts the server with the secret
unset and expects a refusal, not a plain id.

**KD-4 — scope: the credential store is wired into the nightly off-box copy, and the store is empty
today.**
Q1's bounded read-only counts at 05:25 are `user_accounts=0`, non-null `key_hash=0`,
`payment_transactions=0`, `user_favorites=0`, `verified_incoming_tids=0`, `sync_key_attempts=3`, so K2/K3
describe a store with **no live secret in it yet**. The first convenience sign-in writes the first
`sha256:` digest. And as of 06:1x the egress has not happened either: that night's run was killed by its
own 2 h `TimeoutStartSec` and the last good off-box snapshot is Oct 31 05:13, which leaves a stranded
22 GB snapshot set on local disk — evidence, the owner's call, untouched by me. Full write-up and the
proposed allow-list: [`BACKUP_SNAPSHOT_SCOPE_FINDING.md`](BACKUP_SNAPSHOT_SCOPE_FINDING.md). Nothing here
changes that this is an owner decision, and nothing here was edited.

---

## C. Not measured (say so rather than imply it)

1. **Whether any phone-derived (low-entropy) sync key exists** — a read-only query on `key_hash` shapes;
   Q1's counts say the table is empty today, so the question is moot until the first account is created.
2. **Whether `INSERT OR IGNORE` has ever swallowed a real rejection** — needs a ledger-vs-expectation
   reconciliation over `coin_ledger`; the row counts of that table are unknown to me.
3. **Any cardinality of `payments`** (pending/approved volumes, per-plan distribution) — production read.
4. **The rate at which `parse_token` is reached with a bad tag** — no request log was read, so KD-2's
   "guesses are cheap" premise is untested on this deployment.
5. **That the live `user_state.db` schema matches the DDL in these modules** — the deployed file is a
   migration ahead or behind, and I did not open it. Any change to the triggers or the UNIQUE constraint
   must be checked against `accounts.py:2070`'s table list and the migration path, not against this file.

## D. What I recommend, in the order I would do it

1. MD-1 (catch the UNIQUE violation, answer `already_applied`) — small, behaviour-preserving, testable in
   a tempdir with two threads.
2. KD-1 (per-handle nonce in the keystream) — the only item here that changes a wire format; do it before
   the app puts handles in more places, and *pin the version byte* so an old handle keeps parsing.
3. MD-2 (drop `OR IGNORE` on the money writer) — pair with a test that a constraint failure raises.
4. KD-3 (guard: no bare id on a public response) — belongs to the same guard family as the cine-finder
   work, so land them together rather than twice.
5. MQ-1 (caller-owned redeem key) — needs q4's agreement on the app side; decide, then build.
6. K-side docs: nothing. The `accounts.py` docstrings are the best-written part of this subsystem.
