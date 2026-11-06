# Session 75 — Daily check-in coin system, Build 3: 24h VIP Pass for 500 coins (2026-11-07 ~01:30 PKT)

User order (00:46 PKT): "Complete all work one by one" on agy's daily check-in
proposal. Builds 1–2 (Session 74) shipped the 7-day ladder and the claim; this
build makes the first thing coins buy actually work.

## The gap, found by reading the code

`GET /api/v2/account/entitlement` answers from `payments.entitlement`, which
reads ONLY `user_accounts.vip_until` (paid membership). A coin-redeemed pass is
a bearer token (`redact.mint_vip_pass`, expiry only, no account id) recorded
NOWHERE — there was no passes table. So a redeemed `day` pass did NOT flip
entitlement, and the app gates VIP by `entitlement.vip` only. The token IS
honoured server-side when presented (`viewer.py` `request_is_vip` accepts a
valid signed `?vip=` pass), but nothing in the app ever stores or presents it —
a redeemed pass was nearly unusable from the app. Uniform rule adopted: a
minted VIP pass is a VIP entitlement until it expires.

## Server

- NEW `coin_passes` table in the `engagement` DDL (`account_id`, `plan`,
  `expires_at`, `created_at`, index on `(account_id, expires_at)`), installed
  by `ensure_schema` — `CREATE TABLE IF NOT EXISTS`, so existing DBs pick it up
  with no migration and no version bump.
- `engagement.redeem_pass` records the pass after the spend, in its own
  `_borrow` + `_commit`, only when `not spend["already_applied"]` (a same-second
  retry is already a no-op through the spend's idempotency key, and must not
  record twice). `record_engagement_day` records the Day-7 streak pass in the
  same connection/commit as the grant (plan label `"streak_day7"`), so the two
  cannot diverge.
- NEW `accounts.coin_pass_until(conn, account_id, now) -> float`: `MAX(expires_at)`
  over unexpired rows, 0.0 when there is no row — or no table at all (a DB that
  predates the table answers "no pass", not an error). Lives in `accounts.py`
  because `engagement` imports `accounts` and the reverse would be a cycle.
- `accounts.vip_status` now reads `MAX(vip_until, coin_pass_until)`; revoked
  keys still answer False, unknown keys still never raise.
- `payments.entitlement` now returns `vip = max(paid, coin-pass) > moment` with
  `vip_until` the later expiry; `pending` stays payments-only. Consequence,
  accepted: the `vip-pass` mint route now also mints a URL pass for a coin-pass
  holder — same capability, consistent. The admin panel reads the DB directly,
  so no paid/coin conflation there.
- Price: `REDEEM_COIN_COSTS["day"]` 30 → **500**, and the operator knob default
  `coin_redeem_day` 30 → **500** in `admin_panel.py` (the ladder and the knob
  must agree — a test enforces it). **Flagged for the user (owner pricing
  decision, do not invent prices):** with day=500, the weekend tier (70) and
  monthly_vip tier (200) now cost LESS than one day — incoherent; the operator
  can reprice via the `coin_redeem_weekend` / `coin_redeem_monthly` knobs, or
  the user can name new prices.

## App

- NEW wire models in `AccountWire.kt` (`CoinRedeemRequest` [plan only],
  `CoinRedeemed` [reward, cost, balance, alreadyApplied, expiresAt, pass],
  `CoinRedeemResponse`, `PassTier` [coins, pkr]) + `CoinCapsResponse.passes`.
  The keys are the server's own: `{"redeemed": {...}}` from `_redeem_view`,
  `{"passes": passes_projection(...)}` from the caps route.
- NEW Retrofit `redeemPass` + `SyncAccountRepository.redeemPass(plan)` and
  `loadPassCatalog()` (both following the `refreshEntitlement` verdict pattern).
- `VipViewModel` gains `passCatalog`, `redeemMessage`, `isRedeeming` +
  `redeemPass(plan)`: refuses when the wallet is short ("Not enough coins yet
  — keep checking in."), otherwise redeems, re-reads the balance, and calls
  `refreshEntitlement(force = true)` so the screen shows VIP at once.
  `loadWallet()` now reads the catalog too.
- `VipUpgradeScreen` StreakCard (the Daily Rewards card) gains a "Spend coins"
  section under the claim: the three tiers in ladder order (24-hour / Weekend /
  30-day VIP pass) with their coin cost and a Redeem button (enabled only when
  signed in, not redeeming, and balance >= cost), plus the redeem answer in the
  viewer's own words. No new composable — the count stays 15.

## Tests

- Server: `test_engagement.py` — a redeemed day pass is recorded (one row,
  right expiry) and a retry with the same idempotency key records nothing
  twice; the Day-7 streak pass is recorded like a redeemed one. `test_accounts.py`
  — NEW `CoinPassUntilTests`: a future pass returns its expiry, an expired one
  returns zero, no row returns zero, a DB without the table answers zero, not
  an error. `test_coins_engine.py` — a redeemed day pass makes `entitlement`
  VIP with `vip_until` ≈ the pass expiry (route level).
- Price ripple, all fixed in the tests, not the code: the day price lived in
  three places — `REDEEM_COIN_COSTS`, the `coin_redeem_day` knob default, and
  `test_engagement_ladder.py` (5 assertions + docstrings) plus one
  `test_engagement.py` redeem test that granted 100 coins for a 30-coin pass
  (now grants the ladder's own day cost). `test_coins_engine` reads the price
  dynamically and needed no change.
- App: `ModelsTest` — caps `passes` decode by plan, redeem request encodes to
  `{"plan":"day"}`, redeem response decodes the server's receipt.
- Local cluster after the fixes: `test_coins_engine` 37 OK, `test_engagement`
  29 OK, `test_engagement_ladder` 27 OK, `test_accounts_api` OK,
  `test_accounts` 64 OK, `test_redact` OK, `test_api_v2` OK,
  `test_admin_panel` OK, `test_device_trials_and_webhook` OK,
  `test_docs_invariants` 22 OK (before this checkpoint's count bump);
  `test_download_endpoint` still shows ONLY the 2 pre-existing operator-port
  401 failures (same two test names as Session 73, proven pre-existing by a
  stash baseline then).

## Not done

- Build 4 (Direct Download Pass, 100 — new credit store + consume step in the
  download flow + app logic). Build 5 (share +25 / finish-watch +15 with caps;
  themes 250 + request-a-movie 300). Device checks owner-only (redeem the day
  pass at 500 coins → the screen shows VIP at once; a short wallet disables
  the button; a second redeem of the same pass says "already have this pass";
  the Day-7 streak pass shows VIP for 24 hours).
