# Session 74 — Daily check-in coin system, Build 1: 7-day ladder + claim (2026-11-07 00:47 PKT)

User order via agy (00:46 PKT): "Complete all work one by one" on agy's daily
check-in proposal. Agy's directive: replace "watch ads for coins" with a daily
check-in + retention streak, coins spendable on a 24h VIP pass (500), a direct
download pass (100), themes (250), request-a-movie (300); extras share +25/day
and finish-watch +15.

## Evaluation first (sent to agy in tmux, agy agreed with the sequence)

- The server ALREADY has the whole engine: `POST /api/v2/account/coins/earn`
  (streak tick + grant, guarded UPDATE, idempotent per day-bucket),
  `POST /api/v2/account/coins/redeem`, `GET coins`, `coins/history`,
  `coins/caps`, `entitlement`. The app NEVER called any coins endpoint — the app
  is the gap.
- Shipped ladder paid Day 1 (10) + Day 3 (30) + a Day-7 24h pass. Agy's ladder
  (10/20/30/40/50/70/150) needs 5 new knobs — a small server change.
- 24h VIP pass already exists as the `day` tier (signed VIP pass, 24h, via
  `redeem_pass` + `redact.mint_vip_pass`); 500 is a price knob
  (`coin_redeem_day`), not code — operator sets it at gate time.
- Download pass is genuinely new (credit store + consume in the download flow +
  app logic). Share/finish-watch need new ledger reasons + anti-farm caps.
  Themes/request-a-movie need new spend types.
- Sequence: 1) server ladder extension, 2) app coins API + Daily Rewards UI +
  claim, 3) download-pass credit, 4) share/finish grants, 5) themes + request.
  No ad-network code anywhere; coins only from server-verified grants.
- Divergences kept, not hidden: the server's day-bucket rule (Karachi, 04:00
  boundary, a missed day resets) stands instead of agy's ">48h resets"; the
  Day-7 pass mint stays alongside the 150 coins; a streak past day 7 keeps
  counting but grants nothing until it resets (the ladder is seven days, not a
  cycle).

## What changed (Build 1)

- **Server.** `engagement.py`: `STREAK_GRANTS_COINS` is now the 7-day ladder
  `{1: 10, 2: 20, 3: 30, 4: 40, 5: 50, 6: 70, 7: 150}` and
  `STREAK_GRANT_SETTINGS` carries a knob per day (`streak_dayN_coins`).
  `record_engagement_day` needed no change — it grants `table["coins"]` for any
  streak day, so the ladder extension flows through the guarded UPDATE and the
  `streak:<account>:<bucket>:coins` idempotency key untouched.
- **Server tests.** `test_engagement.py`: the milestone test now expects 60
  coins over 3 days (3 grants); NEW 7-day test (370 coins over 7 days, 7 rows,
  day 8 advances the streak but grants 0 and the balance stays 370); NEW
  knob-resolution test (day-4 override to 44, blank row keeps the shipped ladder).
- **App.** NEW wire models in `AccountWire.kt` (`CoinEarnRequest`,
  `CoinEarned`, `CoinEarnResponse`, `CoinBalanceResponse`, `StreakLadder`,
  `CoinCapsResponse`) + 3 Retrofit methods (`getCoinBalance`, `getCoinCaps`,
  `earnDailyLogin`) + 3 `SyncAccountRepository` methods (`loadCoinBalance`,
  `loadStreakLadder`, `claimDailyLogin`, following the `refreshEntitlement`
  pattern: bearer key, `verdictOf` sign-out/pause/else-null).
  `VipViewModel` gains `coinBalance`, `streakLadder`, `claimMessage`,
  `isClaiming`, `claimedToday` + `loadWallet()` + `claimDailyLogin()` (server
  decides; `same_day_noop` says "Already claimed today"; unreachable server
  says exactly that, never "already claimed"). `VipUpgradeScreen` StreakCard
  is now the Daily Rewards card: 7 day-pills with the ladder's coins, a wallet
  line, a [Claim Today's Coins] button (disabled when not signed in, already
  claimed, or claiming), and the claim answer in the viewer's own words.
  @Composable count in VipUpgradeScreen stays 15 (the card was extended, no new
  composable added).
- **App tests.** `ModelsTest`: earn request encodes to `{"reason":"daily_login"}`;
  earn response, balance response and caps ladder decode (incl. a non-day key
  dropped by `byDay`).

## Checks

Local: `test_engagement` 27 OK, `test_engagement_ladder` + `test_accounts_api` +
`test_redact` 167 OK combined. Import verified after the edit. No new test
module (existing suites already registered). `/api/v2/account*` is already in
the nginx allow-list, so the coins routes need no gate change.

## Not done (next builds, one by one)

- Build 3: 24h VIP pass at 500 coins — verify `entitlement` honours a redeemed
  `day` pass, operator sets `coin_redeem_day=500` at gate time (a live-DB knob,
  not code).
- Build 4: Direct Download Pass (100) — new credit store + consume step in the
  download flow + app logic.
- Build 5: share +25 / finish-watch +15 (new ledger reasons + caps), themes
  (250) + request-a-movie (300) (new spend types + UI/endpoint).
- Device checks owner-only: claim on day 1 pays 10 and the pills show the
  ladder; a second claim the same day says "Already claimed today"; balance
  updates after a claim; unsigned-in viewer sees the sign-in note, not a claim.
