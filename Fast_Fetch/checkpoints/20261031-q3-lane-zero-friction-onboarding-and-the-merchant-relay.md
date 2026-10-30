# Session 2026-10-31 (q3 backend lane) `[Q3-ONBOARD-PAY]`

**Branch `q3-backend-auth-payments`, base trunk `6a441ec`** (equal to `origin/master` at the moment of
the branch — `git rev-parse HEAD origin/master` answered the same sha twice, so this is a clean
stack, not a rebase). Worktree `/tmp/q3_backend_work`, created with
`git worktree add /tmp/q3_backend_work origin/master`. `/opt/radd-stream` was **not** read as a
workspace, not edited, not reset, not committed from. No service restart, no deploy, no crawl, no
Gradle, no tag, no new cron, no merge, no fast-forward of `master`/`main`, no production write of
any kind, no credential in argv/URL/file/log, no `.replit`. Stdlib only — `pip` was never run.

## The brief (qoder1 / master)

> Objective: Implement Hardware-Locked 3-Day Trial, Phone+PIN Linking, and Payment SMS Webhook.

Four deliverables: `device_trials (device_id TEXT PRIMARY KEY, account_id INTEGER NOT NULL,
first_seen_at REAL NOT NULL, trial_expires_at REAL NOT NULL)` in the `user_state.db` schema with
`grant_or_resume_device_trial(conn, device_id)` (new device → anonymous account with
`vip_until = now + 3*86400`; known device → the stored expiry, **no fresh 3 days**) and
`link_profile_with_pin(conn, account_id, name, phone, pin)` storing name, phone, a PIN hash and
`vip_until += 86400`; the two POST routes `/api/v2/account/anonymous` and
`/api/v2/account/profile-link`; `POST /api/v2/payment/sms-webhook` in `payments.py` &
`admin_panel.py`, guarded by `X-Merchant-Secret`, body `{"gateway": "jazzcash"|"easypaisa", "tid":
"...", "amount": 250}`, matching pending claims and calling `approve_payment()` automatically with
`reviewer="radd-relay"`, and — if no claim exists yet — recording the TID in
`verified_incoming_tids` for instant validation when the customer does file. Test module
`Fast_Fetch/test_device_trials_and_webhook.py`, stdlib, *"Must be 100% green before completing"*,
*"Keep VM load low (single core)"*.

## What was already true, read before writing anything

- The money ledger already existed and already refused the client's money: `payment_transactions`
  (`id, account_id, plan, amount_pkr, method, tid, status, submitted_at, reviewed_at,
  reviewer_note`), `status` defaulting to `pending`, prices from `MONETIZATION_FIELDS`
  (`vip_monthly_pkr` = 200, `vip_yearly_pkr` = 1500), `_clean_tid` shapes (`jazzcash` exactly 10
  digits, `easypaisa` 10-14, `raast` 12-28 alnum, `MAX_TID_CHARS` 40) and
  `PAYMENT_MIN_INTERVAL_SECONDS = 300` per account. `approve_payment()` already wrote an
  `payment_review_audit` row and extended `vip_until`.
- `user_accounts.vip_until` already existed and was already the single entitlement the download
  route asks about — a rewarded pass and a paid membership share it. So the trial needed **no new
  entitlement column**, only a new *record of the grant*.
- `AttemptTracker` already existed with the durability and the one rule this release leans on: it
  is consulted on the **failure** path only, `record_failure` writes and commits a
  `sync_key_attempts` row, `record_success` **deletes** it, and it is keyed by bucket, so a new
  bucket (`pin:<account_id>`) buys per-credential lockout without touching the key's budget.
- The `["payment"]` route already refused a client-set amount, which is the precedent the webhook
  inherits: the server's own price list is the only source of a PKR figure.
- **What did not exist:** `device_trials`, `verified_incoming_tids`, the profile columns, either
  new route, and any relay path in `payments.py`.

## The five surfaces, as built

1. **`device_trials`** — `Fast_Fetch/accounts.py:632`, in the same `_SCHEMA` string the accounts
   init path already runs, so `ensure_schema()` is still the only migration in this project and a
   new table needs no `SCHEMA_VERSION` bump. `device_id TEXT PRIMARY KEY` and nothing else is
   unique. Deliberately **no `FOREIGN KEY ... ON DELETE CASCADE`**: `prune_accounts()` deletes an
   idle account and the record of when a device first appeared must not vanish with it, or that
   device's next visit is indistinguishable from a brand-new one and mints a second free trial.
2. **`grant_or_resume_device_trial(conn_or_path, device_id, *, now=None, tracker=None)`** —
   `accounts.py:1182`. New device → mint an anonymous account, `vip_until = now + TRIAL_DAYS *
   DAY_SECONDS`, file the row. Known device → return the **stored** `trial_expires_at`; a resume
   never returns a plaintext key, because `device_id` is client-chosen and re-serving the key to
   whoever types that id is account takeover. If the row points at a revoked or deleted account the
   row is re-pointed at a fresh account and **keeps the original expiry**. Ten resumes of one device
   earn one clock — that is the whole test.
3. **`link_profile_with_pin(conn_or_path, account_id, *, name, phone, pin, ...)`** —
   `accounts.py:1391`, with four additive columns (`linked_at`, `profile_name`, `phone`,
   `pin_hash`) declared in `_NEW_COLUMNS` so a pre-release `user_state.db` gains them in place. The
   PIN is **not** a sync key and is not stored like one: PBKDF2-HMAC-SHA256, `PIN_ITERATIONS =
   120_000` (`accounts.py:270`; measured on this box at that count: 56.6 ms median, 51.6 min / 98.7
   max over twelve samples — the number itself is the floor ruled by R6, see the reconciliation
   below), 128-bit per-row salt, `pbkdf2_sha256$<iters>$<salt-hex>$<digest-hex>`, compared with
   `hmac.compare_digest`. The iteration count is bounded to `1_000..1_000_000` **before** anything
   is computed, so a hostile row cannot make the server spend a minute verifying a PIN. Online
   guessing is bounded by the existing `AttemptTracker` in bucket `pin:<account_id>`
   (`accounts._pin_bucket`, `accounts.py:1363`). The +1 day is granted once per account, mirrored by
   `linked_at` — which is set by the same write that grants the bonus, so there is no second flag
   that could disagree with the fact it is supposed to mirror.
4. **The routes** — `accounts_api.route_post`, tail `["anonymous"]` at `accounts_api.py:486`, placed
   **before** the no-bearer 401 guard (it is unauthenticated by construction, like creation) and
   taking no `trial_days`: a client that could set its own trial length could set its own price,
   which is the rule `["payment"]` already enforces on money. Tail `["profile-link"]` at `:509`
   sits **after** the guard, and the `account_id` it writes is derived only from
   `accounts.authenticate(db_path, key, ...)`. A body carrying `account_id` is **ignored, not
   refused** — refusing would advertise that the field is the interesting one.
5. **The relay** — `payments.sms_webhook` (`payments.py:807`), `_credit_from_relay` (`:763`),
   `merchant_authorized` (`:669`), `verify_merchant_header` (`:688`), `unclaimed_credits` (`:873`),
   and the `verified_incoming_tids (gateway, tid, amount_pkr, verified_at)` table keyed on
   `(gateway, tid)` together (`accounts.py:613`). `MERCHANT_SECRET_HEADER = "X-Merchant-Secret"`,
   `MERCHANT_SECRET_ENV = "RADD_MERCHANT_SECRET"`, `RELAY_REVIEWER = "radd-relay"` (`:623`),
   `WEBHOOK_PATH = "/api/v2/payment/sms-webhook"` (`:638`), `VERIFIED_TID_MAX_AGE_SECONDS =
   7 * 86400`. The HTTP mount is `viewer.DashboardHandler._merchant_relay` (`viewer.py:3406`).


## The ordering bug the first draft had, and the rule that replaced it

There are two real orderings and my first `sms_webhook` only understood one:

- **SMS first, claim later** — the relay files a `verified_incoming_tids` row; `submit_payment`
  then reads it (`_verified_incoming`) and hands the row to `_credit_from_relay`, so a payer whose
  money had already arrived stops seeing `pending`.
- **Claim first, SMS later** — the callback arrives at a ledger that already has the row. The first
  draft demanded a `verified_incoming_tids` record here too, which is nonsense: **the callback
  itself is the verification** in that ordering, and requiring a record made the common case (submit
  the form, then watch the SMS arrive) answer `not-verified` and leave money in the queue forever.

`_credit_from_relay` now takes the callback's own amount and compares it against the claim row's
**server-priced** `amount_pkr`, and both orderings funnel through that one function. The checks, in
order, each with its own machine word: `already-credited` → row missing (`not-verified`) →
gateway ≠ the claim's `method` (`gateway-mismatch`) → no amount supplied (`no-amount`) → price ≤ 0
or amount ≠ price (`amount-mismatch`) → `approve_payment(reviewer="radd-relay")` → `not changed` →
`already-credited`. Only then is the record consumed.

**One TID buys one membership**, by three mechanisms rather than by one: the record is **deleted**
when it is spent (`_consume_verified`), `_claim_already_credited` is checked on **both** paths as
defense-in-depth if that delete is lost, and a callback for an already-`approved` TID short-circuits
at the top of `sms_webhook`. A replay of the file-the-fact branch cannot refresh the clock either,
because `INSERT OR IGNORE` keeps the **original** `verified_at` — replaying an SMS does not buy the
record a second week.

Every refusal moves **toward a human and away from a credit**: a missing, unreadable or stale record
leaves the row `pending`. `unclaimed_credits` excludes only an **approved** claim for
(gateway, TID), so a record whose pending claim was refused on amount stays visible on the operator
page instead of silently disappearing behind it — that exclusion was my second bug, and it also
briefly had its two bind parameters in the wrong order.

## Deliberate deviations from the brief, named rather than hidden

1. **The webhook is mounted in `viewer.DashboardHandler._merchant_relay`, not in
   `admin_panel.py`.** The brief said `payments.py` & `admin_panel.py`. `admin_panel` routes sit
   behind `_gate` = loopback **and** `RADD_ADMIN_TOKEN`, and `OPERATOR_ONLY_PREFIXES` 403s them at
   the edge, so a relay on the internet could never reach the callback — mounting it there is a
   route that exists and never fires. `payments.py` holds the logic and the secret; `viewer.py`
   holds the six-line mount (secret first, body second: an unauthorised caller does not get the body
   read), reached in `do_POST` **before** both `accounts_api` and the dashboard dispatchers.
   `admin_panel.py` still got real work: `_payment_rows` now carries `unclaimed`, the page's
   "Nothing here verifies a payment" warning is narrowed to name the single automatic path, and a
   new **"Relay-confirmed, unclaimed"** section (gateway / TID / PKR / seen) prints the records that
   have no claim yet. Rendered against a temp DB: 4,683 bytes, the TID present, `radd-relay` present.
2. **The bonus day is `max(now, vip_until) + 86400`, not `vip_until += 86400`.** The literal
   arithmetic on a lapsed trial banks a day onto a date nobody can see: an account whose trial
   ended ten days ago and links today would still be expired. Stated in the docstring and pinned by
   `test_a_lapsed_trial_is_extended_from_today_not_from_a_date_nobody_can_see`.
3. **The body field stays `amount`** as written, but it is checked against the server's own
   `amount_pkr`, so the relay can neither set a price nor waive one. `_clean_amount` excludes `bool`
   and a TID that arrives as a JSON number is normalised to digits rather than refused.
4. **`link_profile_with_pin(conn, account_id, ...)`** keeps the brief's signature, and the HTTP
   surface never lets a caller supply that `account_id`.
5. **No `redact.BUCKET_LIMITS` change** — the callback answers a replay-safe projection of
   `{verified, matched, approved, recorded, reason}` and nothing else, so it belongs in the ordinary
   public bucket. No `sync_key_attempts`-style device counter was invented for it.

## Tests: `Fast_Fetch/test_device_trials_and_webhook.py` — **83 tests, 100% green**

Seven classes, all offline, no socket: `TrialLedgerSchema` (both tables arrive through
`accounts.ensure_schema`, exact column lists, `device_id` is the only primary key,
`(gateway, tid)` is the only primary key, `payment_transactions` has **no** UNIQUE because one
payment can legitimately be claimed twice by two people, and a legacy `user_state.db` gains the four
profile columns additively); `TrialGrant` (~15 refused `device_id` shapes write **nothing**, the
expiry boundary, revoke→re-issue keeping the clock, deleted-account→re-issue, two devices are two
clocks, `trial_days=0` cannot be smuggled in, an `IntegrityError` race still yields one row, three
prune scenarios); `ProfileLink` (PBKDF2 storage shape, two links of the same PIN produce different
digests, a re-link needs the PIN on file, `PINMismatch` is 401 and `WeakPIN`/`WeakProfile` are 400,
a burned `pin:` bucket still admits the person who knows their four digits and the row is **gone**
after that success, a `sha256:` key digest cannot be spent as a PIN, `999999999999999` iterations is
refused instead of computed, six malformed digests verify nothing, no answer carries a secret);
`AccountSurfaceRoutes` (201 then 200, no `account_id` and no `sync_key` on a resume, body
`account_id` ignored, 401 without a bearer, no PIN or digest in any body, and
`payments.entitlement`'s keys exactly `{vip, vip_until, pending}`); `MerchantSecret`;
`RelayCredits` (both orderings, replay, theft, half-payment, wrong gateway, missing table);
`WebhookMount` (the real `viewer` method driven by a header mapping — secret absent and secret wrong
answer **identically**, the body is never read without the secret, a nonsense payment shape is a 400
not a 500, and no response is a sentence about anybody's money); `OperatorSurface`.

Four defects the suite caught, all mine, all fixed in this session: the `sms_webhook` ordering bug
above; `unclaimed_credits` hiding a still-spendable record; a shared **process-global**
`attempt_tracker` leaking PIN failures between tests in one run, which made eight cases report
`Locked` where they meant to prove `PINMismatch` (each test now gets its own tracker — the suite
must not depend on a module global it did not create); and one wrong expectation of mine, that
`payments.entitlement` answers `{"vip": False, ...}` for a stranger's key. It **raises**
`UnknownAccount`, which is the better behaviour: returning a zeroed answer would tell a guesser the
question was well-formed and only the answer was no, and would make a revoked account look like a
paying one whose clock ran out. The test now asserts a never-minted key and a revoked key take the
identical path.

## Measurements (this box, one vCPU, executed only with the 1-min load under 4)

| command | result |
|---|---|
| `cat /proc/loadavg` before the first run | `1.03 1.20 1.55` |
| `nice -n 19 python3 -S test_device_trials_and_webhook.py` | `Ran 83 tests in 13.247s` — **OK**; re-run after the R5 rename and the 120k change: `Ran 83 tests in 13.137s` — **OK** |
| `nice -n 19 python3 -S test_database.py` | `Ran 133 tests in 25.165s` — **OK**; re-run `31.197s` — **OK** |
| `nice -n 19 python3 -S test_redact.py` | `Ran 61 tests in 15.161s` — **OK**; re-run `15.797s` — **OK** |
| `nice -n 19 python3 -S Fast_Fetch/test_payments.py` | `Ran 85 tests in 13.331s` — **OK** (see the note below: CI does not run this one) |
| `nice -n 19 python3 -S Fast_Fetch/test_accounts.py` | `Ran 61 tests in 8.716s` — **OK** (same note) |
| `nice -n 19 python3 -S Fast_Fetch/test_docs_invariants.py` | `Ran 18 tests` — **OK** after the CONTINUITY/README index edits |
| `nice -n 19 python3 -S Fast_Fetch/payments.py` | `payments selfcheck OK — pending, approved, replayed, VIP, and the relay credited one claim and refused a replay, a theft and a partial` |
| `nice -n 19 python3 -S Fast_Fetch/accounts_api.py` | `accounts_api selfcheck OK — one favorite, adult and forged refs refused, one trial resumed and one profile linked` |
| `hashlib.pbkdf2_hmac` at 120,000, twelve samples | median **56.6 ms**, min 51.6, max 98.7 (one core, `nice -n 19`, load 1.34) |
| `grep -c 'name: 🧪' .github/workflows/backend-ci.yml` | **32 → 33** (re-counted, never remembered; `test_device_trials_and_webhook.py` is the new step and the trunk 3-module quick gate was **not** substituted for it) |

Per qoder1's local gate for this brief the standing set was my own new module plus `test_redact.py`
and `test_database.py`, one module per invocation under `nice -n 19`. I ran **two more than that
gate names** — `test_payments.py` and `test_accounts.py` — and the reason is a finding worth more
than the extra twelve seconds of a 1-vCPU box: **`Fast_Fetch/test_payments.py` (85 tests) and
`Fast_Fetch/test_accounts.py` (61 tests) exist and are not in `backend-ci.yml` at all.** Grepped:
the workflow's `test_` steps are **33 `🧪` steps = 32 `run: python3 -S …` + 1 `run: time python3 -S …`**
(the timed one is `test_admin_panel.py`), and grepping the file for `test_accounts`, `test_payments`
and `test_admin_panel` returns hits for `test_admin_panel.py` only (`:56` in a comment, `:254-255` as
the step). So the two suites that judge the exact files I edited hardest — `payments.py` and
`accounts.py` — are invisible to CI, and AGENTS.md rule 3 ("never break existing tests") could only
be honoured by running them here. Both green. The gate's load intent was respected: five invocations,
serial, `nice -n 19`, load 1.0–1.9 throughout. CI's full 33-step list is what the hosted runner
judges and was not run locally.

**The registered-suite gap is not mine to close quietly** — adding two steps to `backend-ci.yml`
changes what every lane's push is gated on, and if either suite has a host-dependent failure it would
turn trunk red for reasons nobody owns. It is reported for the owner or master to rule on.


Diffstat against `origin/master` (`git diff --stat`, final, after the R5/R6/R1-R2 reconciliation
edits): `accounts.py +574`, `payments.py +400`, `accounts_api.py +147`, `viewer.py +68`,
`admin_panel.py +47`, `backend-ci.yml +19`, `CONTINUITY.md 3/-2`, `checkpoints/README.md +1` —
1,208 insertions / 53 deletions across eight files — plus two new files, the 1,126-line test module
and this log.

## Reconciliation with `docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` — found mid-session, and it governs this exact feature

Halfway through I found that this brief is **not** the first word on this feature in the repository.
`docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` (460 lines, in trunk) reproduces the Antigravity lane's
original spec verbatim in its Appendix A and then rules on it in nine numbered rulings R1-R9, each
with a measurement behind it. My brief — "Implement Hardware-Locked 3-Day Trial, Phone+PIN Linking,
and Payment SMS Webhook" — is that same spec's headline, phrased in the spec's own vocabulary, and it
did not point at the review. So I read the review and reconciled. What follows is where the code
agrees, where I changed it to agree, and where it still does not.

**Already satisfied when I checked:**
- **R3** ("the relay's `amount` is evidence, never authority"): `_credit_from_relay` compares the
  callback's amount against the **claim row's** stored, server-quoted `amount_pkr` and leaves the row
  `pending` on any difference; the plan's length still comes only from `approve_payment`'s
  `days(plan)`, which raises on an unknown plan rather than defaulting to 30 days.
- **R4(1)** the triple match against a `pending` row and never against an `approved` one, and
  **R4(2)** `UNIQUE(gateway, tid)` — which `verified_incoming_tids` **has**, as its
  `PRIMARY KEY (gateway, tid)`, so a replayed SMS cannot file a second record or refresh the first.
- **R4(3)**'s comparison: `merchant_authorized` is `hmac.compare_digest` with no default secret.
- **R4(4)**'s audit row: the credit goes *through* `approve_payment(reviewer="radd-relay")`, so the
  existing append-only `payment_review_audit` records it, with the amount and gateway in the note.
- **R6**'s central demand: phone+PIN is a verification factor and **never credential material**.
  Nothing derives a key from anything a person types; `new_sync_key()`'s random mint is still the only
  credential, which is exactly the defect class R6 was written against (`unsalted
  SHA256("radd-stream-v2" + phone + pin)` over a 10⁴ space).
- **R7**'s boundary on the anonymous population: name and phone are written **only** on a
  volunteered, linked account; a silent mint stores no contact data at all.

**Changed because of the review, in this session:**
1. **R5 — the naming.** The brief's phrase "hardware-locked" is a claim this code cannot keep:
   `device_id` is a client-reported string, an emulator hands out fresh ones, and `docs/
   IDENTITY_AND_TRIAL_ABUSE.md` §3 measured **zero** attestation calls across `App/app/src`. Every
   occurrence in the new code now says **trial gate** and states the limit next to it
   (`accounts.py:236`, the `device_trials` table comment at `:632`, the section header, and
   the CI step's comment). R5's second half — a `trial_gate TEXT NOT NULL` column recording *which*
   gate minted a grant — is **not** built, because the brief fixed the table's four columns and my
   own schema test asserts that list exactly; it is a one-column change plus a test edit, and it
   belongs to the owner's next word, not to a silent deviation here.
2. **R6 — the cost floor.** `PIN_ITERATIONS` was 100,000 (my own earlier choice, justified by the
   one-CPU box). R6 rules `≥ 120_000`, and the measurement I made at 120,000 (56.6 ms median) says
   the box pays it for a once-in-a-lifetime action, so the constant is now **120_000** with R6 cited
   in its comment. Stored digests carry their own iteration count, so this is forward-only: a row
   minted at 100k this week still verifies at 100k, and `_verify_pin_hash` reads the count back out
   of the digest rather than assuming.
3. **R1/R2 — the transport, and a correction to my own earlier claim.** My first draft of this log
   told the owner to "add one nginx `location` line" for `/api/v2/payment/sms-webhook`. **That was
   wrong and the review says why**: this host has no TLS, so a static long-lived `X-Merchant-Secret`
   posted from the operator's phone over Pakistani mobile data crosses the network in the clear to
   anyone on the path, and whoever sniffs it can approve their own VIP indefinitely on our bill. The
   ruled transport is an **outbound SSH tunnel from the operator phone**
   (`autossh -M 0 -N -L 127.0.0.1:8099:127.0.0.1:8080 ubuntu@92.4.95.252`, relay POSTs to
   `http://127.0.0.1:8099` + the path), which lands on loopback at the very handler this session
   mounted, costs $0, needs no new listener, and gives encryption *and* device authentication. So
   `/api/v2/payment/*` **staying 403 at the public edge is the control**. Both places that said
   otherwise are corrected in code (`payments.py:626-637` beside `WEBHOOK_PATH`, and
   `viewer.py:3424-3437` in `_merchant_relay`'s docstring), and gap 1 below is rewritten to match.
   This is also the answer to my earlier "deliberate deviation 1": mounting in `viewer.do_POST` is
   not merely a workaround for `admin_panel`'s loopback+token gate, it is **where a tunneled request
   actually lands**.

**Where the code still does not meet the review — named, not smoothed over:**
- **R4(1) payer phone suffix**: not matched, and it *cannot* be — the brief's callback body is
  `{gateway, tid, amount}` and carries no payer number. Matching the suffix needs the relay to parse
  it out of the SMS **and** the claim to store a phone, which only exists after `profile-link`. An
  anonymous account has nothing to compare. This is a spec change, not a code change.
- **R4(3) timestamp + nonce window and a per-tunnel request bucket**: not built. The mount sits
  outside `accounts_api`'s limiter, so the callback is presently uncounted. Its exposure after R2 is
  a caller who already holds the loopback tunnel, and a wrong TID only files a record that is
  single-use, 7-days-bounded and spendable solely by an exact three-way match — which is why this was
  left as a named gap rather than bolted on untested at the end of a session. The place to add it is
  beside `_note_usage` in the mount's own path.
- **R4(4) `match_basis`**: folded into the audit note's text, not a column.
- **R7's mandatory delete path** ("wipe contact info for account N", keeping the ledger row and
  NULLing `name`/`phone`/`pin_hash`): **not built.** The brief did not ask for it and the review calls
  it non-optional for the owner's stated Pakistan → India → Asia → Europe rollout. This is the
  largest single unmet ruling in this session and the first thing a follow-up should build.
- **R8's provisional rows** (`account_kind='anonymous'`, `activated_at NULL` until the first real
  read/write, `activated` reported separately from `minted`, GC at `anonymous_provisional_ttl_days`):
  **not built.** Consequence, stated plainly: every scripted mint is already a "user" in the panel
  the owner asked for, and the `device_id` gate is the only brake besides nginx's 30-burst
  `limit_req` on `/api/v2/account*`.
- **R9's ten admin-panel fields** (`trial_days_on_install`, `trial_days_on_profile_link`,
  `anonymous_mint_enabled`, `anonymous_provisional_ttl_days`, `trial_gate_mode`,
  `radd_relay_enabled`, `radd_relay_last_seen_at`, `radd_relay_min_amount_match`,
  `coin_earn_watch_minutes`/`coin_value_pkr`, `device_tracking_enabled`): **none exist** — I grepped
  `admin_panel.py` for each name. So the trial's 3 days and the +1 day are **code constants**
  (`accounts.TRIAL_DAYS`, `accounts.PROFILE_BONUS_SECONDS`) rather than the admin knobs R9 rules for
  them, and there is no `radd_relay_enabled` kill switch. The relay is nevertheless dark in the sense
  R2's ordering wanted, by a different mechanism: the secret is unset on this host, and
  `merchant_authorized` returns False for every caller when it is.
- **R3's price conflict, reported and NOT touched**: R3 rules **₨250** for Monthly VIP
  (`docs/MONETIZATION_AND_FLEET_PLAN.md`) and calls `payments.py:99` `PLAN_DEFAULTS = {"vip_monthly":
  (200, 30), ...}` stale, alongside my own brief's `"amount": 250` example. I did **not** change it:
  the same figure is the default in `admin_panel.MONETIZATION_FIELDS`, which `test_admin_panel.py`
  asserts and CI runs, and a price is the owner's number to move, not a lane's. The relay is correct
  at either value because it reads the admin table at request time and refuses anything that is not
  the row's own stored price. To make the ruling true: change both defaults together, in one commit,
  with `test_admin_panel.py` and `test_payments.py` re-run.
- **R6's "≥32-byte sync key"**: the module's mint is 96 bits, which is `accounts.new_sync_key()`'s
  existing law and predates this session. Raising it is a change to a function every account in the
  ledger was minted by, and to `test_accounts.py`; not mine to make silently.

## Honest gaps — reported, not fixed

1. **`/api/v2/payment/sms-webhook` answers on loopback and is 403 at the public edge — and that is
   the design, per R1/R2.** The relay's transport is the operator phone's outbound SSH tunnel to
   `127.0.0.1:8080`, not a public route; nobody should add an nginx `location` for it. What the
   owner still has to do is set `RADD_MERCHANT_SECRET` on the service and stand up the tunnel (and
   the companion APK), because an unset secret authorises no caller at all. I did **not** open a
   socket to the public edge to re-measure the 403 tonight; that figure is the review's own table
   against `/etc/nginx/sites-available/radd-stream` (`:69` account prefix proxied, `:108`
   `^~ /api/` returns 403), read from `docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` R1 rather than
   re-confirmed by this lane.
2. **A relay that names a TID before its real payer files a claim can be spent by a stranger.** A
   bank SMS carries no account, so a verified TID is a bearer instrument: whichever pending claim
   matches on gateway + TID + the server's own PKR is the one that gets credited. The record is
   single-use and 7-days-bounded, and the operator page lists what has no claim yet, but there is no
   cryptographic binding between an SMS and an account and there cannot be with this input.
3. **No PIN reset path exists.** A customer who forgets four digits cannot be helped by any route
   this server has, and a phone-SMS OTP would need a gateway this box does not have. The owner needs
   to decide, not me.
4. **No profile read route.** `profile-link` writes and answers once; nothing reads `profile_name`
   or `phone` back, so the app must keep what it submitted. (Deliberate: a read would put a phone
   number on the wire again for no user need.)
5. **One TID, one credit is enforced by reads, not by a unique index** — `tid` has no UNIQUE
   constraint in `payment_transactions` and `verified_incoming_tids` is consumed rather than
   marked. A unique index would be the stronger guarantee and would fail on existing duplicate TIDs
   in any real ledger; adding it is a data migration, not a schema line.
6. **`idle_days` silence can restart a trial clock.** `prune_accounts()` deletes an idle account and
   then sweeps `device_trials` for rows whose expiry is past the cutoff **and** whose account is
   gone, so a device silent past the retention window is indistinguishable from a new one. That is
   the documented retention policy doing exactly what it says, and the suite asserts it rather than
   hiding it — but it is a free-VIP path gated by time, and it should be read as one.
7. **A `device_id` is a claim, not proof.** It is client-chosen, so a rotated or re-fetched install
   id is a new device; only the client's honesty ties it to hardware. The PBKDF2 choice and the
   `pin:` bucket assume that.
8. **The PIN crosses a plain-HTTP wire in the clear**, on a host with no TLS. Stated in
   `link_profile_with_pin`'s docstring: the limiter is the only thing between a 4-digit PIN and a
   local watcher, and anyone who has already captured the sync key owns the account anyway. The
   +1 day is small on purpose.
9. `admin_panel` still shows a raw TID on the loopback page (unchanged behaviour), and the new
   "Relay-confirmed, unclaimed" section inherits that trust boundary rather than widening it.

## Next action for whoever picks this up

The owner's remaining actions are **`RADD_MERCHANT_SECRET` on the service and
the phone→loopback tunnel** (R2) — explicitly **not** an nginx change, see gap 1. Then, in the order
`docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` §2 already rules: **R7's contact-wipe admin route** (the
largest unmet ruling here), **R8's provisional-row accounting** (`account_kind`/`activated_at`, so
the usage panel can tell a mint from a user), **R9's ten admin fields** (which is what turns
`accounts.TRIAL_DAYS` and `PROFILE_BONUS_SECONDS` into knobs and gives the relay its
`radd_relay_enabled` switch), then the companion APK against a **test** merchant number. `/opt/radd-stream`
remains behind trunk and the service has not been restarted by this lane, so none of this is live.

## How this session ended, measured

Four commits on branch `q3-backend-auth-payments`, base `6a441ec`, pushed to the explicit clean URL
with the heredoc `GIT_ASKPASS` helper (`origin` was never used — its stored remote still carries the
owner's unrevoked token), and `ls-remote` confirms the tip landed:

| sha | subject |
|---|---|
| `f0829f5` | `feat(accounts): a device-gated 3-day trial and a PBKDF2 phone+PIN profile link` |
| `daa231e` | `feat(payments): an SMS relay that can credit a claim, on one exact match` |
| `1653efc` | `test(payments,accounts): 83 offline tests … — and CI runs them` |
| `9df2f62` | `docs(continuity): the [Q3-ONBOARD-PAY] session log, and the indexes recounted` |
| `ccd9cf3` | `docs(checkpoint): point the cross-account index at [Q3-ONBOARD-PAY] …` (branch tip) |

**Hosted Backend CI: run `41122473554`, `completed success`, job `python3 -S offline suites`** — all
33 `🧪` steps green on the hosted runner at `9df2f623`, including the new step and the timed
`test_admin_panel.py` that the two edits to `admin_panel.py` could have broken. (Runner architecture
was not read from the run, so it is not claimed here — the local box is arm64 and this suite opens no
socket, which is the only portability surface it has.) `ccd9cf3` is a `docs/`-only commit and
`backend-ci.yml` filters on `Fast_Fetch/**` + the workflow file, so it correctly started no run; the
code at the tip is byte-identical to the code CI judged. Nothing was merged, no `master`/`main` ref
moved, no tag, no deploy, no service restart.

**And one housekeeping fact the next lane inherits from mine:** appending item 12 put
`Fast_Fetch/CONTINUITY.md` at **120 of 120 lines and 11,996 of 12,000 bytes** — exactly against both
ceilings in `test_docs_invariants.py::IndexShapeTests`, which pass but have no slack. The item is one
line because there was room for one line, and the full record is this file. So the next backend
session that wants an index entry must **rotate an existing item's body into `checkpoints/` first**
and then append — not raise a ceiling, which is a deliberate documented edit, and not append and let
CI fail. `test_docs_invariants.py` was re-run after this write: **18 tests OK**.
