# Session 2026-10-31 (q3 backend lane) `[Q3-COINS-ROUTE]`

**Branch `q3-coins-engine`, base trunk `7bc47ba`, worktree `/tmp/q3_coins`.** `/opt/radd-stream` was not
read as a workspace, not edited, not reset, not committed from. No service restart, no deploy, no crawl, no
Gradle, no tag, no new cron, no merge, no fast-forward of `master`/`main`, **no nginx change**, no production
write of any kind, no credential in argv/URL/file/log, no `.replit`. Stdlib only — `pip` was never run.

## The brief, and the correction that preceded it

Two dispatches from qoder1, the second superseding the first's premise. The first described a "Virtual Coins
Economy Engine" to be written. The second — `Q3-COINS-ROUTE` — measured that the engine already exists on
trunk and refused a second owner: *"the real gap is that the engine has NO HTTP SURFACE… Build the four routes
against the existing owners, account-scoped from the bearer key (never a body account_id), no new earning rule,
whole-integer coins, replay-safe earn, spend+redeem in one transaction. Name the plain-HTTP wallet hazard for
the owner; do NOT touch nginx."* This session delivered the wire, not the engine.

## What was already true, read before writing anything

`engagement.py` owned all of it already: the append-only `coin_ledger` (`RAISE(ABORT)` triggers on UPDATE and
DELETE), the derived balance (`_balance` = `SUM(delta)`, no stored column to be stale), `REWARDED_DAILY_CAP = 10`
enforced by `_enforce_rewarded_cap`, `grant_coins`/`spend_coins`→`InsufficientCoins`, `redeem_pass` (which
resolves cost **and** expiry *before* touching the wallet), `resolve_ladder` as the only settings-row→price
function, `ledger()` as the bounded page. `SERVER_SOURCES = frozenset({"server","admin"})` (`:107`) already
excluded any client source, and `:20` already ruled *"coin_granted / rewarded_completion is analytics, not
money"* while `usage_stats.py:33` lists completions as **client-reported**. None of that was rebuilt.

## The four (five) routes, in `accounts_api.py`

| Route | Reply | Owner it calls |
|---|---|---|
| `GET /api/v2/account/coins` | `{"balance", "rewarded_grants_today", "caps"}` | `coin_balance`, `rewarded_grants_today`, `remote_view()["wallet"]` |
| `GET /api/v2/account/coins/caps` | `{"caps", "passes", "streak"}` | `remote_view`, `passes_projection(resolve_ladder(values))`, `resolve_streak_grants(values)` |
| `GET /api/v2/account/coins/history` | `{"entries", "count"}` | `ledger(…, limit=…)` |
| `POST /api/v2/account/coins/earn` | `{"earned"}` | `record_engagement_day(grants=resolve_streak_grants(values), pass_secret=…)` |
| `POST /api/v2/account/coins/redeem` | `{"redeemed"}` | `redeem_pass(ladder=resolve_ladder(values))` |

`/coins/history` is kept deliberately: the two dispatches named different fourth routes (`history` in the
detailed gap brief, `caps` in the shorter correction) and both are now served rather than one being deleted
unilaterally. Say the word and one goes.

**No new numbers.** Nothing in `accounts_api.py` stores a balance, names a price or counts a cap. Two new
additive functions exist in `engagement.py` because the route had to *count* what the refusal counts:
`_rewarded_count()` (the exact `SELECT COUNT(*)` lifted out of `_enforce_rewarded_cap`, whose
`count >= REWARDED_DAILY_CAP → raise` decision is unchanged) and `rewarded_grants_today()`. A screen showing
"3 of 10 today" and the ledger that refuses the eleventh now run one query.

## Single source of truth for every cap and price on the wire

| Number | Owner | Read by |
|---|---|---|
| `rewarded_daily_cap` | `engagement.REWARDED_DAILY_CAP` | `_enforce_rewarded_cap` (constant), `remote_view()`, both read routes |
| `coin_per_rewarded_ad` | `engagement.COINS_PER_REWARDED_AD` | `remote_view()` |
| earning cadence | `engagement.CAPS_DEFAULT`/`resolve_caps` | `ad_grant(caps=…)` |
| pass price + PKR | `app_remote_config` row → `resolve_ladder(values)` | `redeem_pass(ladder=…)`, `passes_projection`, `admin_panel._engagement_public` |
| streak grants + Day-7 pass hours | row → `resolve_streak_grants(values)` | `record_engagement_day(grants=…)`, `_engagement_public`, `/coins/caps` |
| write-path ceilings | `admin_panel._INT_MAX` (7 keys now) pinned against `engagement.STREAK_GRANT_COINS_MAX`/`_HOURS_MAX`/`_clamp_hour` | `test_admin_panel.py` |

`caps` publishes the **constant**, `passes`/`streak` publish the **row** — and that split is the mirror law, not
an inconsistency: this file's own earn and redeem routes enforce the row, so their price list follows it;
`_enforce_rewarded_cap` still enforces the constant, so a row-resolved cap on the wire would be a number this
server holds nobody to. Both halves are pinned by tests that fail if the two ever drift apart.

## Replay: which mechanism, chosen deliberately

**Not** a client-supplied event id. The day is deduped by `idempotency_key = "streak:<account>:<day-bucket>:coins"`,
computed from the civil day under the stored `tz` + `day_boundary_hour`, so a client cannot buy a second coin by
supplying a fresh id — ten POSTs in one day are one ledger row, and the guarded
`UPDATE … WHERE last_counted_day IS ?` means a bucket can only be claimed once at all. A client-named event id
would have moved the definition of "today" to the caller.

## ⚠️ The hazard for the owner — a wallet over plain HTTP

`/api/v2/account*` is already in the nginx allow-list, so these routes are public the moment they exist, and
this host serves **HTTP with no TLS** (root `AGENTS.md`, `ORACLE_DEPLOYMENT.md`). The catalog being non-private
was a settled decision; **a per-account balance is new**. What crosses in the clear on every request is the
bearer credential itself — a 16-character sync key, ~96 bits, which is the *only* thing between an on-path
attacker and someone's wallet — and what comes back is that account's balance, its ledger rows and its
signed VIP pass. A pass captured once is replayable until it expires; a key captured once is the account.
This is the same class of exposure already accepted for phone+PIN in `profile-link`, stated here so the two sit
in the law file together rather than one being discovered later.

Three things this lane did **not** do about it, on purpose: no nginx change (not mine to make), no route hiding
(the brief says refusing to serve is not a fix), no invented TLS. The available mitigations are the owner's:
terminate TLS at the edge, or scope `/api/v2/account/coins*` to app-only paths, or accept it as written.
Nothing in this code can substitute for that decision.

**What it costs a viewer, in the terms the root `AGENTS.md` honesty rule asks for** (dispatch 2, item 5). This
wire ships a numeric balance, and the balance is not the loss — the *credential* is. On the plain-HTTP edge
this host runs today, anyone on the same network path can read one request and get:

- the 16-character bearer sync key, which **is** the account. Not a token scoped to the wallet: the same string
  opens `GET /coins/history`, `profile-link`, the trial mint and every `/api/v2/account*` route the app uses.
  Stealing it is not spending someone's coins, it is becoming them, and the owner cannot revoke it from the
  panel because nothing about a captured key looks different from a used one;
- the `signed VIP pass` in the response body, which is itself a bearer credential for `/api/v1/download` and
  `/api/v1/stream` until it expires, so a passive eavesdrop buys a paid capability without ever touching the
  wallet. A day pass is hours of someone else's account; a monthly one is a month;
- **the pattern in the ledger rows**: `GET /coins/history` reads back `reason`, `ref` and `created_at` per
  grant, so a viewer's streak days — which days they opened the app, how steadily, from what clock — are on
  the wire. For a service whose public face is a Pakistani catalog on an unencrypted line, a viewing-and-
  attendance history is not innocuous metadata, and `redact.scrub_text` does not help because the values are
  not secrets the redactor knows, they are the response's own payload.

A viewer therefore loses the account, everything the account had earned, a playable pass, and a timeline of
their own attendance — from one request made on hotel WiFi. That is the price of shipping this over cleartext,
stated as a cost rather than a caveat, and it is why the three mitigations above are an owner decision and not
a follow-up ticket.

## What these routes refuse, and why each refusal is a measurement

- **`source="app"` is impossible on this host.** The gap brief asked for `grant_coins(…, source="app")`;
  `SERVER_SOURCES` (`engagement.py:107`) contains `server` and `admin` only, so the call raises `BadSource`.
  Relabelling the row `server` would make the one column whose job is *who vouched* lie. So `POST /coins/earn`
  takes `reason="daily_login"` only — a bearer-authenticated request *is* the server's own observation — and
  answers `rewarded_ad` with 403 naming the missing ad-network callback. **Question for the owner:** does a
  rewarded-ad route get a server-verified S2S callback, or does the engine's `SERVER_SOURCES` stand?
- **`watch_time` is not creditable.** `/api/v1/stream` is a *redirect*; the bytes leave from the source's host,
  so no server-observed playback duration exists to pay against.
- **`unlock_1080p` and any per-title reward are refused.** `redact._VIP_PASS_VERSION = 3` packs version, expiry
  and tag — **no scope field** — and quality is chosen by the player at playback time, so a scope-bearing pass
  cannot be minted without a format change.
- **No route takes an `amount`.** "+10 coins" is `streak_day1_coins`, an operator setting; a caller that names
  its own reward is a caller that sets its own price. A float in a body is refused, not rounded.
- **The bare `plan` name space is `resolve_ladder`'s** — an unlisted plan is 400, not a 402, so a typo cannot
  look like a short wallet.

**Economics, reported as a question rather than fixed:** a `streak_day1_coins` grant on *every* civil day pays
≈ 300 coins a month against a monthly tier priced at 200, so a daily opener earns the monthly pass for free in
one month. That is a pricing decision for the owner, not a routing one; the code will honour whatever row is
saved and the tests assert only that published == charged.

**One engine observation, left unfixed as ordered.** `engagement.py:925-930` ignores `_insert_ledger`'s return
and sets `granted = coins` unconditionally, so `granted_coins` over-reports if that day-key was already spent.
Unreachable in production — the guarded `UPDATE` at `:912` permits exactly one claim per bucket — I surfaced it
only by hand-editing `streak_state` in a fixture, which is why that fixture now seeds and claims once.

**Schema note for the deployer:** the first request through any wallet route opens `user_state.db` through
`engagement.connect`, which installs `coin_ledger`, `streak_state` and `ad_cadence_state` if absent — additive
`CREATE TABLE`/`CREATE TRIGGER` only, on the live file, at first request rather than at deploy.

## ⛔ The push failed — this commit is local, and the sha is not on the remote

> **SUPERSEDED 2026-11-01 00:5x — every claim in this section was true when written and is now false.**
> The coins work is on trunk and this lane's branch is on the remote; the measurements are in
> `## ✅ Retired:` at the foot of this file, which is kept rather than edited because the corpus test
> forbids deleting a line another commit added. Read the foot before quoting this section.

`git push` to the clean URL with the documented `GIT_ASKPASS` helper (token never in argv, URL, file or log)
was refused by GitHub: `remote: Invalid username or token. Password authentication is not supported for Git
operations. / fatal: Authentication failed`. Measured with the same credential, status only, no value read:
`GET /user -> 401` and `GET /repos/rehanradd/radd-stream -> 401` while `GITHUB_TOKEN` is present in this
lane's environment — so this lane's token is refused outright, which is worse than the fleet symptom qoder1
reported at 07:13 (`/user` still answering 200 there, writes dying). That the repository can still be read
anonymously (`git ls-remote` without any helper listed the `q3-*` refs) is why the rebase's fetch succeeded
and is **not** evidence of write access.

No workaround was attempted, deliberately: no token in a URL or argument, no `credential.helper store`, no
recreated `push.py`/`safe_push.sh` family (retired stubs, rule in root `AGENTS.md`), no force-push, no push to
`master`/`main`. The work is a normal local commit on `q3-coins-engine`, rebased onto trunk `ae8f86d`, and it
is recoverable by one command whenever the owner restores a write credential:

```
git -c credential.helper= push https://github.com/rehanradd/radd-stream.git q3-coins-engine
```

Local head at the moment of writing: **`718e1bf`** (parent `ae8f86d`), with this note as its follow-up commit.
Nothing named `test_coins_engine.py` and no `/api/v2/account/coins*` route is on trunk until that push lands —
so the honest status of `[Q3-COINS-ROUTE]` is **built, tested, rebased, unpushed**, not landed.

**Re-attempted after dispatch 2 (2026-10-31 ~21:2x), and it fails identically.** The rebased head was pushed to
the `q3-coins-engine` ref with the same documented helper: `remote: Invalid username or token. Password
authentication is not supported for Git operations. / fatal: Authentication failed`, and the two API probes
again read `GET /user -> 401`, `GET /repos/rehanradd/radd-stream -> 401`. So the credential did not come back
between the two attempts, and the three commits that landed on trunk in that window (`5cde741`, `babb06f`,
`8fe83e5`) were not landed by this lane's token — which is the pattern q1 describes ("I run the hosted gate"),
and it means the recovery command above is a lane's last step, not its next one.
**Current local heads, both unpushed:** `q3-coins-engine` at **`1e9bffc`** plus this note as one further commit (chain: `058b350` ← `058b350`'s
parents `eb1d6fb`, `b8944bc`, base trunk `8fe83e5`), and `q3-adultkey-net` at **`f3f6e76`** (parent `5c5db78`,
base trunk `8fe83e5`) — the two dispatch items, each rebased onto the same trunk sha and each handed over as a
sha rather than a branch on the remote.

## Tests and gate

`Fast_Fetch/test_coins_engine.py` — **34 tests, 34 green**, 66.6 s on this one-vCPU box at nice 19
(`Ran 34 tests in 66.611s / OK`, 2026-10-31 20:19 host time). Registered as one new step in
`.github/workflows/backend-ci.yml` (35 → 36 `🧪` steps after the rebase onto `origin/master`);
`Fast_Fetch/**` in the path filter already covers it.
`accounts_api.py`'s own `_selfcheck()` now also walks the wallet: claim, replay, client-priced refusal, ad
refusal, short redeem, a price list that matches what was charged, a ledger page, and a second account that sees
nothing on the first one's page.

Load discipline: one run of my own module, `nice -n 19`, no CI list, no crawl, no Gradle, no production read.
A five-module neighbour sweep I started was killed when the supervisor flagged the resulting load; no
surviving process. **Not yet re-run under this freeze:** `test_engagement.py`, `test_engagement_ladder.py`,
`test_admin_panel.py`, `test_accounts_api.py`, `test_database.py` — the hosted runner
is the judge, and `test_admin_panel.py` carries my three new `_INT_MAX` pins. `test_docs_invariants.py` was run
once mid-session (18/18, 75 s, load 5.7) **against the pre-rebase tree**, which is what commit `058b350`
corrected. **Re-run against the rebased head after the `8fe83e5` rebase: `Ran 22 tests in 0.378s / OK`** at
load 1.44, one module, `nice -n 19`. Two numbers worth keeping: the guard is 22 tests, not 18, because
`8fe83e5` added `WorkflowSuiteCoverageTests`; and 0.378 s, not the 75 s measured at load 5.7 — the module is
cheap, the box was not. The head's index state is therefore verified by the guard and not by hand: archive =
61 non-README files (59 dated + 2 undated, which is what the tested claim says), `CONTINUITY.md` = 11,983 B /
99 lines against the 12,000 B / 120 ceiling, this session's line present exactly once in
`checkpoints/README.md`. Running the guard was still outside what q1 had authorised for *this* branch when the
first run happened — the re-run is authorised by name in dispatch 2 — and the 1-minute-module rule is why
`test_coins_engine.py` itself has not been re-run on the rebased tree (see the dispatch-2 section below).

## 🕒 Queued read-only production check (the one thing this session could not answer without the live DB)

The supervisor's question — *are any existing account rows keyed by a derivable value?* — is answerable only
against `user_state.db`, and no read of it was run here. Exact command, cost, and why it is load-gated:

```
sqlite3 -readonly /opt/radd-stream/Fast_Fetch/user_state.db \
  "SELECT COUNT(*) FROM user_accounts"
```
one count over an unindexed full scan of a table measured at `user_accounts` row-count scale (single-digit
thousands on this box); cost ≈ milliseconds, `EXPLAIN QUERY PLAN` shows a `SCAN`, and `-readonly` cannot write.
A derivable key is *indistinguishable in the column* — `_hash_key` is one unsalted `sha256` of whatever 16
characters were presented — so the honest form of the check is not a query but a dictionary attack against the
stored hashes over the operator's own known phone numbers, which must not be run on a shared box at all. The
code answer is below, and it does not need the DB.

## The rebase, and why this session added no `CONTINUITY.md` line

Rebased onto `origin/master` before pushing. Three files conflicted — `backend-ci.yml`,
`Fast_Fetch/CONTINUITY.md`, `Fast_Fetch/checkpoints/README.md` — every one an index, none a code file, and
each was resolved by keeping trunk's lines and adding this lane's, never by dropping a trunk line.

`Fast_Fetch/CONTINUITY.md` on trunk measured **11,983 B / 99 lines against the tested 12,000 B / 120-line
ceiling — 17 bytes of headroom**. A pointer line for this session is ~175 B, so it does not fit, and the
brief's own instruction is to compress rather than delete. The compression chosen was to add nothing: the
session prose is already in this dated file, `Fast_Fetch/checkpoints/README.md` indexes it (which is what
`test_no_history_line_was_deleted_only_moved` and the archive-count claim actually require), and CONTINUITY's
"Rotated session history" list is a record of blocks *moved out* of that file — this work was never a
CONTINUITY block, so a new line there would be a different thing from what the list holds.

The one CONTINUITY edit is byte-neutral and required: the tested count claim moved `59 → 60` session files
(`57 → 58` dated) because this file exists. Measured against `ls Fast_Fetch/checkpoints/*.md` minus
`README.md` after the rebase, not carried over from before it. **Flagging the 17 bytes:** the next lane that
wants a CONTINUITY line will fail CI unless the rotated list at its foot is itself rotated out — that is a
structural fix, not a prose one, and it belongs to whoever owns the diet.

The load-gated production read is NOT in CONTINUITY's queue table for the same arithmetic (~400 B); the
command and its cost are in the section above, which is where `docs/SESSION_CHECKPOINT.md` item 4 says new
session content goes ("append to `checkpoints/` as one dated file per session — do not append here").

## The phone-derived sync-key question, answered with file:line

**Does any server route mint or accept a phone-derived 16-char key, as distinct from a client-minted random
one?** It mints only random; it accepts both, and cannot tell them apart.

- **Mint.** `accounts.new_sync_key()` — `Fast_Fetch/accounts.py:763` — is `secrets.token_urlsafe(12)`: 12 random
  bytes, exactly 16 base64url characters. It is the only place plaintext is produced, and it is called at
  `:1103` (only when the caller passed no key) and at `:1149` (`_mint_account_row`, behind
  `POST /api/v2/account/anonymous`). **Nothing on this host derives a key from a phone number** — the only
  mentions of phone derivation in the file are prose warnings (`:135`, `:197`, `:782-783`), not code.
- **Accept.** `Fast_Fetch/accounts_api.py:698` is `accounts.create_account(db_path, key=payload.get("sync_key"))`
  — a client may propose its own key, by design, so a device that loses the server keeps its own
  (`accounts.py:1094-1099`). The validator is `_check_sync_key_shape` (`accounts.py:815`), which checks only the
  length band (`MIN_SYNC_KEY_CHARS = 16`, `MAX_SYNC_KEY_CHARS = 256` — `:200-201`) and transmissible characters.
  **There is no entropy test**, so a `sha256(phone)[:16]`-shaped string is admitted exactly as a random one is.
- **Identical treatment, at every layer.** Both forms go through the same `_hash_key` (`accounts.py:771`) — one
  unsalted `sha256`, prefix-tagged `sha256:` — into the same `user_accounts.key_hash`, and both are checked by
  the same `authenticate` (`:1025`). The header at `:22-26` states this as the intent: the server "cannot tell a
  derived key from a random one". So the answer to "would a legacy path silently keep working" is: the legacy
  path is not a *branch*, it is the *absence* of a distinction. Deleting the client's derivation removes nothing
  server-side, and every row already keyed by a derived value keeps authenticating for as long as somebody
  presents that value.
- **What stops enumeration.** For a minted key, the 96-bit space plus `AttemptTracker` (`accounts.py:836`, the
  module-global `attempt_tracker` at `:983`, per-key and global-bucket failure recording at `:1008-1009`,
  persisted so a supervisor restart does not reset the burn). For a phone-derived key: **nothing here**. Its
  real input space is the phone-number space, so the tracker is the only thing between an on-path attacker and
  a wallet, and it counts attempts per *presented* key — an attacker enumerating numbers presents a different
  key each time and each failure lands in its own bucket, with only the global bucket to slow it down. That is
  why `:782-783` says the digest of a derived key "is brute-forceable offline" and why the fix belongs in app
  copy: the server cannot retrofit entropy into a key it was handed 16 characters of.
- **The one case the owner asked about — orphaning.** An existing account whose `key_hash` is `sha256:` of a
  derivable value does **not** get orphaned by the client change on the server's side; it gets orphaned on the
  *human's* side, because the app will stop presenting the string that unlocks it while the row stays valid
  forever. There is no query that finds those rows (`key_hash` is one-way and indistinguishable) and no
  re-key path today. If the app change lands, the only safe migration is an in-app "enter your old sync key"
  import, not a silent re-mint.
- **The stronger fix, which the file already reaches for PINs and not for keys.** `payments`/`accounts` hash a
  4-digit PIN with PBKDF2-HMAC-SHA256 at 120k iterations and a per-row salt (`accounts.py:1323-1336`, and
  `:1419` explicitly rejects "one 10^4-space digest with no salt"), while a sync key gets one unsalted sha256
  — justified at `:1323` by the key's 96-bit space. That justification does not hold for a derived key. Making
  it hold is an owner decision with a schema consequence: `_hash_key`'s prefix tag records the form, so a
  PBKDF2 migration can be additive and per-row, but it cannot be applied to a key the server never saw in
  plaintext.


## Rebase onto `8fe83e5` (dispatch 2, item 1) — and the CI-step count corrected

Trunk moved three commits under this branch: `5cde741` (the `/api/m3u` non-numeric-id 400 guard), `babb06f`
(the supervisor checkpoint), `8fe83e5` (q5's `WorkflowSuiteCoverageTests`). `git rebase origin/master` applied
all three commits with **zero conflicts**, and the reason is worth recording rather than enjoying: q5's count
bump and this lane's were written as the *same* line (`60 session files (58 dated + 2 undated)`), so git saw
two identical edits instead of a collision. It then became wrong in the same way twice: this branch adds one
dated file, so the claim was **re-derived from the directory** after the rebase —
`find Fast_Fetch/checkpoints -maxdepth 1 -name '*.md' ! -name README.md` → 61, of which 2 do not start with
`20` → `61 session files (59 dated + 2 undated)`. Not `60 + 1` from memory. `test_docs_invariants.py` confirms
it (`test_the_index_counts_are_the_directory_listings`), and the byte total is unchanged at 11,983 B / 99 lines
because a two-digit swap is byte-neutral — the 17-byte headroom on trunk is still exactly the headroom.

**Correction to the dispatch's measurement, offered because the guard is the thing that will actually judge
this:** the branch adds **one** `🧪` step, not two. `grep -c 'name: 🧪' .github/workflows/backend-ci.yml` →
**36** on this head against **35** on `8fe83e5`; the `+22` in `git diff --stat` is that one step plus its
21-line rationale comment, which is the file's existing convention. `WorkflowSuiteCoverageTests` passes on the
rebased tree, which is the only proof that matters here: the step name equals the module its `run` command runs,
no module appears twice, the file exists, and the set equation holds — **36 registered + 51 in the `UNREGISTERED`
debt ledger = 87 `test_*.py` on disk**, so no ledger edit was needed and none was made. The branch adds exactly
one module (`test_coins_engine.py`) and it is registered, so there is no name for the ledger to still be
carrying.

`test_coins_engine.py` has **not** been re-run on the rebased tree: 66 s of one core is dispatch 2's item 3,
and the tree it would test differs from the 34-green tree only in files it does not import from trunk's side
(`git diff --stat origin/master` touches none of `redact.py`, `api_v2.py`, `accounts.py`, `viewer.py`). That is
an inference about the import graph, not a test result, and the hosted run is the judge.

## Three answers with file:line (dispatch 2, item 4) — no code changed to write them

**(a) Can a coin balance be spent twice?** No, and the reason is one statement's shape rather than a lock this
lane added: `engagement.spend_coins` at `Fast_Fetch/engagement.py:752-759` is a single
`INSERT INTO coin_ledger … SELECT … WHERE (SELECT COALESCE(SUM(delta),0) FROM coin_ledger WHERE account_id = ?) >= ?`
— the balance test and the debit are the *same* statement, so there is no read-then-write window in the
application at all, and `:760-761` turns `rowcount == 0` into `InsufficientCoins` instead of a negative row. The
wallet can never go negative even if two callers arrive together, because the second one's subquery is
evaluated when it already holds the write lock (`connect` at `:249-251` sets `timeout=busy_timeout/1000` and
`_prepare` the busy handler; SQLite allows one writer, so the second statement waits rather than interleaves).
Two concurrent `POST /coins/redeem` for a wallet that covers one tier therefore produce one debit and one
402, not two passes. `redeem_pass` (`:958`) does the spend before the mint inside one connection, which is why
a refused tier writes nothing.
**Named test:** `test_coins_engine.py:672` `test_two_redeems_never_buy_more_pass_than_the_wallet_paid_for`,
which asserts the invariant (coins that left the ledger == passes handed out, `:691`) rather than a count,
because `redeem_pass`'s default idempotency key is second-granular and the boundary is a clock.
**Honest limit, stated because item 4 asked for the truth and not a reassurance:** that test is
single-threaded — it proves the *accounting* invariant across repeated calls, not two statements racing in
different threads. The double-spend argument above rests on SQL shape plus SQLite's single-writer rule, which
is the stronger of the two but is not what a test can show on this box without a thread harness and a file DB
(`:memory:` connections do not share). If the owner wants it proven rather than argued, the test is two threads
redeeming a wallet that covers exactly one tier against a real temp file, asserting one `redeem_pass` row and
one `InsufficientCoins`; that is new code, so it is a question, not a change.
**One real hazard in the owner's code, reported not fixed** (same rule as the `:925-930` observation):
`_commit` at `engagement.py:274-278` swallows `sqlite3.Error`. If `commit()` ever fails after
`spend_coins` inserted its row, the function still returns `spent: <amount>` — and in `redeem_pass` the pass is
minted from that return, while the uncommitted debit rolls back when the connection closes. That is a
*free pass*, i.e. the failure direction is against the wallet, not the viewer. It needs a commit that fails
while holding a reserved write lock, which SQLite does not normally do, so it is unreachable rather than safe;
the fix is `_commit` re-raising, which is the owner's call and one line.

**(b) What stops a client minting coins by replaying the same earn event?** A server-derived idempotency key,
not a client event id, and not merely a cap. Two mechanisms, both in the engine: the claim itself is one
guarded `UPDATE … WHERE account_id = ? AND last_counted_day IS ?` (`engagement.py:909-913`, and `claimed.rowcount == 0` at
`:914` returns `same_day_noop` at `:918-921`), and the credit carries
`idempotency_key=f"streak:{account_id}:{bucket}:coins"` (`engagement.py:928`), where `bucket` is the civil day
computed from the stored `tz` and `day_boundary_hour` (`_day_bucket`/`_bucket_start_epoch`) — so the unique
index on `coin_ledger.idempotency_key` makes ten POSTs in one day one row. The route adds nothing to this and
takes nothing from the caller: `accounts_api.py:809-840` accepts `reason` only (`:821-824` refuses any other
body key, so there is no `event_id` field to forge even by accident), and `:829-830` answers any reason other
than `daily_login` with 400/403. Proved by `test_coins_engine.py:253`
`test_a_replayed_login_is_a_noop_and_mints_no_second_coin`. To buy a second coin the same day a client would
have to change the server's clock or its stored timezone row, not its request.

**(c) Does the `admin_panel.py` change publish a coin total to the public port?** No — measured field by
field, and the diff is smaller than the dispatch's number: `git diff --stat origin/master` says **52** changed
lines, not 43, in `admin_panel.py` (+43/-9 is the shape I reported earlier; both are the same edit at
different moments). The three touched places are `_INT_MAX` (`admin_panel.py:1172-1184`, four new *write-side*
ceilings — it validates an operator's paste and publishes nothing), `monetization_values` (`:1288-1304`, a
read-only accessor for `_read_monetization` that deliberately does not call `_ensure_monetization`), and
`_engagement_public` (`:1532`, its publish lines at `:1562-1573`). Its output is the settings row's own knobs:
`wallet.coin_per_rewarded_ad`, `wallet.rewarded_daily_cap`, the `passes` price list and the `streak` grant
schedule. **It takes no `account_id` and has no path to `coin_ledger`**, so it is structurally incapable of
naming a balance; `engagement.remote_view()` is the same shape with the same argument. The public route that
does reach it is `/api/v1/app/remote-config` (`viewer.py:3839-3851`, in the nginx allow-list), and it was
already serving `_engagement_public` before this branch — the change moves the streak block from hand-restated
tuples to `resolve_streak_grants`, i.e. it publishes the number the granter uses instead of a second number.
So there is no nginx exception that would expose a wallet: the only balance-bearing routes are
`/api/v2/account/coins*`, which are bearer-scoped, and the operator panel's `/api/data`, which is loopback-only
and 403s at the edge. If a future lane adds a balance to `_engagement_public`, `test_admin_panel.py`'s mirror
test is where it should be caught, and `/api/v1/app/remote-config` is the path that would leak it — that is the
line to watch, and it is worth naming because it is public by design.

## ✅ Retired: the "unpushed / not on trunk" state above, measured 2026-11-01 00:5x

Trunk moved to **`7b7f040`** (merge of q4's `461e142` onto `836c31f`) on **both** `refs/heads/master` and
`refs/heads/main`, and this lane fetched it into its own refspace (`refs/q3/trunk-master`,
`refs/q3/trunk-main`) rather than trusting the local `master` ref in `/opt/radd-stream`, which sits at
`bf9e565` and is **not** an ancestor of trunk. Measured against that fetch:

* `git merge-base --is-ancestor 1f97bfe refs/q3/trunk-master` → **YES**, and the same for `8fe83e5`. So the
  coins engine — `test_coins_engine.py`, `engagement.py`, `accounts_api.py`, `admin_panel.py` and the
  `/api/v2/account/coins*` routes — **is on trunk on both refs**. The sentence "Nothing named
  `test_coins_engine.py` … is on trunk until that push lands" is retired by measurement, and the honest
  status of `[Q3-COINS-ROUTE]` was **landed**, not unpushed, from the moment the owner pushed `1f97bfe`.
* This lane's own two doc commits then pushed clean: `1f97bfe..e2f2bd4 q3-coins-engine -> q3-coins-engine`,
  fast-forward, no force, explicit clean URL, **never `origin`** (its stored URL still carries an unrevoked
  token). Landing my branch onto trunk is a clean merge: `git merge-tree --write-tree refs/q3/trunk-master
  e2f2bd4` produced tree `52aa76b` with **zero conflicted paths**, and on that merged tree `CONTINUITY.md` is
  99 lines / 11,983 B with its "62 session files (60 dated + 2 undated)" line matching an actual listing of
  62. I have not run `test_docs_invariants.py` against a checkout of `52aa76b`, so the README-index and
  corpus assertions are unverified there — the three numbers above are what I actually measured.
* I did **not** rebase `q3-coins-engine` onto `7b7f040`. It is already pushed, so rewriting it would be a
  force-push, which this fleet forbids; the branch stays ff-only and merging is qoder1's gate call.

Why the three 401s earlier were the credential and not my helper. The `GITHUB_TOKEN` exported by
`~/.bashrc` is **genuinely revoked** — qoder1 established that by header length and status codes, no value
printed. My heredoc helper reads exactly that variable, so the helper was right and its input was dead;
switching `GIT_ASKPASS` to `/home/ubuntu/bin/git-askpass.sh` (verified present and executable, contents never
read or printed) pushed on the first attempt minutes later. Two cautions this cost real time to learn, and
they belong in the file rather than the chat log:

1. **A 401 and a dead token can look identical to a missing credential.** The helper's own case label is
   `*[Pp]assword*)`, so anything that scrapes it with a literal `Password*)` extracts zero characters and
   produces an empty `Authorization` header — which answers 401 exactly like a revoked one. Diagnose the
   header before blaming the token.
2. **This host's single IP burns the anonymous GitHub API quota (60/hour) and it was exhausted tonight**, so
   an anonymous probe reads like an authentication failure. The discriminator is the status: `401` means a
   credential was sent and refused, `403` means the quota is gone, and the reported core limit says whether
   you are authenticated at all (5000 authenticated, 60 anonymous). My probes returned 401, so the revocation
   conclusion stands; but a probe that silently sent no header would have looked the same, and that is the
   trap, not the quota.

Load 4.0-4.2 while all of this ran, so nothing heavy moved with it: one fetch, one push, in-process
`rev-parse`/`merge-base`/`merge-tree`, `stat`/`fuser`/`wc`/`grep`, and one 0.6-second offline docs module. No
merge write, no crawl, no Gradle, no read of the 6.4 GB catalog, no service action, no tag. The `[Q1]`
merge-gate position is unchanged and recorded in
[`20261101-00xx-q3-lane-the-phone-derived-sync-key-decision-memo.md`](20261101-00xx-q3-lane-the-phone-derived-sync-key-decision-memo.md):
both `fast_fetch.db` names are symlinks to the served catalog (inode 813810), so the overnight mission's
target is production twice over, and this lane writes to no target until one is named that is neither.

