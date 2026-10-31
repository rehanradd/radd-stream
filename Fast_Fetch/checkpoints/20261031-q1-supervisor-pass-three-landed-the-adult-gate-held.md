# qoder1 supervisor pass — the census CI step landed, the relay defect that deleted payments, and an empty branch

**Token:** Q1-SUPERVISOR-PASS-2 · **Base:** `7bc47ba` → landed trunk `e7f6bbb` on `master` and `main`
· **Host:** 1 vCPU, load 3.97 → 6.88 across the pass, `mem_avail` ~4,269 MB, `swap_free` ~2,735 MB —
the hard floor was never breached, so the freeze held the whole time and **no python suite, build, crawl,
Gradle run or production read was executed by me.** Every gate in this entry is a hosted GitHub Actions
run, read anonymously from the API. That is the point of the pass: three of the four lanes were judged by
free CPU instead of by this box.

## Landed

**`q2-census-ci` (`e3d881f`) → trunk `0afea35`.** Two files: `backend-ci.yml` +17 and a checkpoint. No
Python changed, so the module under test is the one already landed as `a424ffc`. Verified before landing,
not after: the workflow's `paths:` filter is `Fast_Fetch/**` + the workflow file, which really does cover
`Fast_Fetch/importers/`; `main()` runs `unittest.main` unless `--census` is present, so CI cannot trigger
the heavy staging read; and the run on the branch (41153679953) reports 39 steps with
`🧪 test_dub_collision_census.py -> success`. The three headline numbers stay **queued** with the exact
command, the nearest measured comparable (12.0 s for a 16,943-row `GROUP BY canonical_key` at load 0.91)
and the JSON keys wanted. Refusing to take them at load 4.83 was correct behaviour, not a shortfall.

**`q4-player-zero-buffer` (`269fec0`) → trunk `a775ba7`.** The `CLOSEST_SYNC` re-land: 6 lines in
`PlaybackService.kt` (`androidx.media3.exoplayer.SeekParameters` + `exo.setSeekParameters(...)`, the
`common` package does not exist at Media3 1.3.1 and a `val` reassignment cannot compile), plus 2 cases in
`PlayerBufferingTest`. Run 41153914187 `assembleDebug + testDebugUnitTest + lintDebug` = success, so the
import compiles and the cases executed. **And a folklore claim about the tree is retired:** Session 31's
instant-start and manifest-mime work IS on trunk, under names nobody had cited —
`PlaybackService.kt:119 .setLoadControl(loadControl())` reads `PlayerBuffering`
(`MIN 15_000 / MAX 50_000 / BUFFER_FOR_PLAYBACK_MS 500 / AFTER_REBUFFER_MS 1_000 /
PRIORITIZE_TIME_OVER_SIZE true`, measured at this head) and `PlaybackMediaItemFactory.kt:46` applies
`manifestMimeType()` defined at `:101`. `tooling/InstantStartGuardTest.kt` is absent because three of its
assertions name `instantStartLoadControl()` / `START_BUFFER_MS` — shapes that never shipped. qoder4
leaving it off rather than landing a red suite is the correct call; the guard must be rewritten against
the real names.

**`q2-raddrelay` (`9125ce8`) → trunk `e7f6bbb`.** Held first at `2c2ad6b`, then re-reviewed. The consent
review passed all four questions I set, each verified in code: `RECEIVE_SMS` only, no `READ_SMS`; senders
matched by `when (sender?.trim())` on two literals (an allow-list, not a substring); the only SMS read is
`Telephony.Sms.Intents.getMessagesFromIntent(intent)` with no `content://sms` and no cursor anywhere in
`src/main`; and the body is parsed to `(gateway, tid, amount)`, which are exactly the three keys the queue
persists, `allowBackup="false"`, no log line carries a body.

**What made me hold it — a defect that destroyed the only record that money arrived.** Shipped default
`DEFAULT_URL = "http://92.4.95.252"` + `WEBHOOK_PATH = /api/v2/payment/sms-webhook`, and I re-measured
`/etc/nginx/sites-enabled/`: the proxied v2 prefix is `^~ /api/v2/account` and the catch-all is
`location ^~ /api/ { return 403; }`. So the default is answered by a *proxy*, and the old table read
`401, 403 -> Reject`, and `Reject` did `queue.removeAt(0)`. Every real payment SMS would have been posted
once, refused for a reason that has nothing to do with the credential, and permanently deleted from the
only device that knew it happened — with a log line blaming the merchant secret, sending the operator to
look for a problem that does not exist. All three edges are now in: the tunnel endpoint is the default
(`http://127.0.0.1:8099`, so `usesCleartextTraffic` means localhost, not the open internet);
classification is one pure function `RelayVerdict.of` where **401 alone** means the credential was refused
(the server verifies the header before reading a byte of the body), 403 is a route refusal, and an unseen
status retries rather than deleting; and `Reject` moves the item to a dead-letter list, replayable, since
`payments.sms_webhook` dedupes on gateway+TID+quoted PKR. 9 new tests; run 41155931301 green.

## Refused / standing

**`q5-adultkey-reconciliation` (`bea5c4f`) — its own CI step is red, so it is not landable, and the root
cause is one guard line.** Run 41155094460: `Ran 8 tests in 0.293s`, `FAILED (errors=2)`, both in qoder5's
new cases at `test_merge_catalogs.py:419` and `:441`, both `sqlite3.OperationalError: no such table:
adult_fold_journal` from the audit read at `:358`. Cause read off the code:
`apply_corroborated_adult_fold` is the only place that executes `ADULT_FOLD_JOURNAL_DDL`
(`fast_fetch.py:800`), and `merge_catalogs.py:265` guards the call with `if apply and exposures:` — so on
exactly the two paths the tests name (nothing to fold, fold skipped) the table is never created. The fix I
asked for is in the schema, not the test: create the journal unconditionally at the top of
`reconcile_adult_on_merge`, because `undo_corroborated_adult_fold` already tolerates the missing table
(`:827`) while an operator auditing a fold-nothing merge must get **zero rows, not an OperationalError** —
a database that cannot be audited is indistinguishable from a broken one. Also asked: report a skipped
fold in `stats`, since `merge_site_db:424` skips the whole reconcile under `adult_fold=False` and "looked
and folded nothing" vs "was told not to look" are different facts.

**I verified the branch's central safety claim myself, in code, and it holds** — this is the launch gate's
key property and until now only a docstring implied it: `ADULT_TITLE_PATTERNS` (`fast_fetch.py:188-193`)
is 16 explicit tokens and contains **neither `uncut` nor `unrated`**, so `adult_rule_agrees()` cannot
reproduce a flag standing only on release vocabulary, which means the 375-of-407 mainstream works are
structurally incapable of being fold *sources*. The 407-regression cannot return through this path.
Grouping is exact `canonical_key` then `(normalized clean_title, year)`, and `work_identity` returns `None`
for an empty title or a non-numeric year, so the titleless "unknown" bucket cannot group. Report-only by
default (`backfill_adult_key.py` prints the count and the first 10, writes only under
`--corroborate --apply`, reverses only its own flips under `--undo`) — my brief said `--owner-go`; the
naming difference is recorded here so the owner's instruction stays traceable.
**Hazard stated, not fixed:** `ADULT_SOURCE_SITES = frozenset()` (`:271`), so `site_implies_adult()` answers
0 for every row and the docstring's second corroboration tier cannot fire today. Fail-closed is right; the
prose should say the list is empty, and populating it is an owner decision with a hiding consequence.

**`q3-coins-engine` was an empty branch, and the dispatch described already-landed code.** `git log`
shows the ref sitting at trunk `7bc47ba` with zero commits of its own while its pane was idle — the owner
was told qoder3 was building the Virtual Coins Economy Engine. It exists on trunk in
`Fast_Fetch/engagement.py`: `coin_ledger`/`streak_state`/`ad_cadence_state` DDL (`:288`, `:302`, `:313`),
`CAPS_DEFAULT`/`CAP_MAX` (`:91`, `:99`), `REWARDED_DAILY_CAP = 10` enforced by `_enforce_rewarded_cap`
(`:648`) with its escape hatch behind an env var (`:665`), `coin_balance` (`:643`), `grant_coins` (`:671`),
`spend_coins` (`:704`) raising `InsufficientCoins` (`:193`), `redeem_pass` (`:871`) minting a capability
token — tested by `test_engagement.py` (25) and `test_engagement_ladder.py`, both in CI's list. So the
brief I sent was a correction, not a task: **the gap is HTTP**, verified by grep — no coin route in
`api_v2.py`, `accounts_api.route_get`/`route_post` mounted at `viewer.py:3533`/`:3940` for
`/api/v2/account*` only, and nothing in the app calls a coin endpoint. An earned balance can exist and a
viewer can never see, earn from the phone, or redeem it. Four routes, extending the owners, with the
non-negotiables: `account_id` from the bearer key and never from a body field, no new earning rule, integer
coins only, a replay guard on the farmable rewarded grant, and `spend_coins` + `redeem_pass` in one
transaction. **Deployment truth handed to the owner, not worked around:** `/api/v2/account*` is already in
the nginx allow-list, so these routes go public the moment they exist — over plain HTTP, with a
16-character key as the only bearer credential. A wallet is not the catalog; the hazard is named for the
owner's decision, and no agent touches nginx.

## Standing, unchanged, and whose

`link_is_adult` fail-OPEN on an unknown link id (the docstring at `redact.py:1083` claims the opposite;
qoder5 documented the real behaviour) — one owner decision, not a drive-by fix. `q3-adultkey-net`
unmerged. The live tree is still 60 files dirty and `viewer.py` ~473 lines behind trunk. Orphan pid
1845966. ~45 remote heads and 56 worktrees of sprawl. App Session 39/40 name seven test files that exist
nowhere. The §13 player hue, `DynamicServerDiscovery`, episode-offset calibration, the `subtitled` deploy
note, and the first tag (`v1.0.0` — only after Android CI is green at a head carrying the App work, and
signing is still blocked on the four keystore secrets, which the owner must add).

## Rules kept

No `.py` written by me. No service restart, no nginx change, no tag, no `git add -A`, no `origin` remote,
no credential in a URL, argv, file or log (the log fetch used a 0600 curl config with `user =`, never a
header on the command line). Worktrees only (`/tmp/q1_rev_*`, `/tmp/q1_land_*`), never
`/opt/radd-stream` as a workspace. Every landing gated on hosted CI measured at the branch head, then
re-verified as a clean descendant of the trunk it landed on.
