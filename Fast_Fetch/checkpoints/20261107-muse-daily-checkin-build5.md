# Session 77 — Daily check-in coin system, Build 5: share +25, finish-watch +15, themes 250, request-a-movie 300 (2026-11-07 ~02:00 PKT)

User order (00:46 PKT): "Complete all work one by one" on agy's daily check-in
proposal. Builds 1–4 shipped the 7-day ladder, the claim, the 24h VIP pass
(500 coins, CI green on f783b2c), and the direct download credit (100 coins,
CI green on fc35d4d, Android run 42290507268 + Backend run 42290507351, APK
app-debug-237). Agy approved the Build 5 design and said "Proceed with the
build" (~01:47 PKT). This build is the last four items on that proposal.

## The four gaps, found by reading the code

- **Share.** The app's `DetailScreen.shareTitle` fires an Android chooser with
  the deep link; the server can never observe a share, so no coin could ever
  be paid for one. The grant is a bounded client claim, the same shape as the
  daily-login claim: the app reports it, the server verifies the work handle
  is ours and the day bucket is the enforcement.
- **Finish-watch.** The progress route recorded positions and answered them;
  nothing ever paid for finishing. The player already posts progress on a
  tick (gated to one call per 15 s) and forced on pause/teardown
  (`PlayerViewModel.reportResume`, forced path), so a ≥90% position reaches
  the server for any real viewing — verified by reading the code before
  building, as the design note required.
- **Request-a-movie.** No table, no route, no form: a viewer with coins had
  no way to ask for a missing title. A new `movie_requests` table, not the
  free-form `contact_messages` (a different thing).
- **Themes.** No theme setting existed anywhere, and the player has two
  accents — jade (brand primary) and `AccentOrange`. The design note's open
  point is settled here, not invented around: a theme must NOT recolour the
  meaning-carrying accent (DESIGN_SYSTEM.md §9 forbids replacing it), so a
  theme is a chrome skin only — background, HUD plates/chips/cards, rail
  track, played fill + seek thumb. The played fill's meaning is positional
  (its length says how much played, not its hue), so the fill and thumb may
  wear the theme's colour while the selected-rung jade stays jade. Three
  themes: `jade` (the shipped look — free, always owned, never sold),
  `midnight` (deep navy, steel-blue fill), `ember` (warm charcoal, muted
  amber fill, clearly darker than AccentOrange so the rail never reads as a
  live-state orange).

## Server

- NEW `movie_requests` table in the `engagement` DDL (`account_id`, `title`,
  `notes`, `status` default `'open'`, `created_at`) and NEW
  `purchased_themes` table (`account_id`, `theme_id`, `purchased_at`,
  PRIMARY KEY the pair — a theme is bought once and kept). Both `CREATE TABLE
  IF NOT EXISTS`, so existing DBs pick them up with no migration.
- `LEDGER_REASONS` += `share`, `finish_watch`, `redeem_theme`,
  `redeem_request`; `SPEND_REASONS` += `redeem_theme`, `redeem_request`.
- NEW constants `SHARE_COINS = 25`, `FINISH_WATCH_COINS = 15`,
  `FINISH_WATCH_FRACTION = 0.9`, `REQUEST_MOVIE_COINS = 300`,
  `THEME_COINS = 250`, `PURCHASABLE_THEMES = ("midnight", "ember")`.
  NEW knob resolvers `resolve_share_coins` (`coin_share`),
  `resolve_finish_watch_coins` (`coin_finish_watch`),
  `resolve_request_movie_coins` (`coin_redeem_request`),
  `resolve_theme_coins` (`coin_redeem_theme`) — all through one shared
  `_resolve_coin_knob`: a stored 0 or an unparseable paste means the shipped
  number, never free. NEW `themes_projection(values)` (theme -> coins, one
  price for every theme). Knob defaults in `admin_panel.py`:
  `coin_share` 25, `coin_finish_watch` 15, `coin_redeem_request` 300,
  `coin_redeem_theme` 250.
- NEW `engagement.grant_share` — 25 coins, idempotency key
  `share:<account>:<Karachi day-bucket>` (04:00 boundary, the streak's own
  clock), so a second share the same day pays nothing whatever title it
  names. One paid share a day, not one per title, because a per-title cap
  would let one phone farm 250 coins by sharing ten movies. Returns
  `{"granted", "coins", "balance"}`; a replay is reported via
  `grant_coins`' `idempotent` flag (it has no `already_applied` key — that
  was caught before the first test run).
- NEW `engagement.grant_finish_watch` — 15 coins, idempotency key
  `finish-watch:<account>:<work>:<season>:<episode>`, so a rewatch pays
  nothing and a series pays per episode. The function only pays; the
  progress route decides what "finished" means.
- NEW `engagement.request_movie` — spends 300 with reason `redeem_request`
  (idempotency key `request-movie:<account>:<second>`), then inserts the
  queue row only when the spend was not a replay; a replay reports the
  request id it filed, looked up from the table.
- NEW `engagement.owned_themes` — always starts with `jade`; the table only
  ever holds purchases. NEW `engagement.redeem_theme` — spends 250 with
  reason `redeem_theme`, `INSERT OR IGNORE` into `purchased_themes`,
  answers with the ownership it holds now.
- NEW routes in `accounts_api.py`: `POST /coins/share` (body `work_ref`
  only, validated by `_target` AND `accounts.work_is_visible` — the adult
  law covers the share too, so a flagged work is refused with the same 400
  a forged handle gets); `POST /coins/request-movie` (body `title` +
  optional `notes`, title non-blank and ≤200 chars, notes ≤500, short
  wallet → 402 `licence_required`); `POST /coins/redeem-theme` (body
  `theme` only, unknown name → 400, a theme already owned answers
  `already_applied` with the ownership it holds and no spend runs at all);
  `GET /coins/themes` (owned themes + prices, one read for the picker).
  The progress route now checks the finish after `put_progress`: duration
  > 0 and position ≥ 0.9 × duration → `grant_finish_watch`, and the reply
  gains `"coins_earned"` (15 on a finish, 0 otherwise, additive to the
  existing `progress` block). The caps route now publishes `"request":
  {"coins": ...}` (the form shows the price before the tap, so the price
  shown and the price charged are one read) and `"themes":
  themes_projection(values)`. Share and finish-watch get NO caps key: the
  app shows nothing before the act, and the reply carries the number.
- FIXED (pre-existing, found while verifying): the module selfcheck called
  `accounts.register`, which does not exist (`create_account` is the real
  name) — the selfcheck could not have run at HEAD. One word changed; the
  selfcheck now passes end to end. Also fixed the same hour: the
  redeem-theme route's already-owned branch called `engagement.balance`,
  which does not exist — it is `engagement.coin_balance`.

## App

- NEW wire models (`AccountWire.kt`): `CoinShareRequest` (`work_ref` only),
  `CoinShare`, `CoinShareResponse`; `CoinRequestMovieRequest` (title +
  notes), `CoinMovieRequest`, `CoinRequestMovieResponse`;
  `CoinRedeemThemeRequest` (theme only), `CoinTheme`, `CoinRedeemThemeResponse`;
  `CoinThemesResponse` (owned + prices). `CoinCapsResponse` gains
  `request: DownloadCreditPrice` and `themes: Map<String,
  DownloadCreditPrice>` (both default-empty/0, so an older server simply
  publishes nothing). `ProgressWriteResponse` gains `coinsEarned: Int = 0`.
- NEW Retrofit methods: `reportShare`, `requestMovie`, `getCoinThemes`,
  `redeemTheme`. NEW repo methods (`SyncAccountRepository`): `reportShare`,
  `requestMovie`, `loadCoinThemes`, `redeemTheme`, `loadThemeCatalog`,
  `loadRequestPrice` — all following the existing null-on-unreachable
  pattern (a failed report never blocks the share, which already left the
  phone).
- `reportProgress` now returns the coins earned (Int) instead of `SyncAck`
  — its only caller ignored the ack — and `PlayerViewModel.reportResume`
  emits `PlayerEvent.Message("+$coins coins for finishing this title")`
  when the server says it paid. The toast shows only on a positive number.
- `DetailViewModel.reportShare(workRef)` — fires after the chooser, shows
  "+N coins for sharing" only when the server granted, and updates the
  balance; a second share the same day and a failed report are both silent.
  `DetailScreen.shareTitle` takes an `onShared` callback; the call site
  passes `viewModel::reportShare(post.workRef)`. A post with no workRef
  still shares; only the coin report is skipped.
- NEW `PlayerChromeTheme` (`Color.kt`): the six chrome surfaces
  (background, bar, chip, card, track, played) per theme id, with `forId`
  defaulting to jade for anything unknown. All raw `Color(0x…)` literals
  live in `Color.kt`, so the brand test's allowlist holds.
- NEW `ServerSettingsRepository.playerTheme` Flow + `savePlayerTheme`
  (unknown ids ignored, never stored). `PlayerUiState.playerTheme`
  (default jade), collected by `PlayerViewModel` so a pick on the VIP
  screen reaches a player that is already running.
- `PlayerScreen` now wears the theme: root background, TopBar plate,
  CenterControls chip, EdgeHud rail (track + played fill) and chips,
  BottomControls bar, Scrubber fill + thumb, KeepChip idle bar, and the
  transient overlays (HudToast, UnlockFab, EndedButtons — threaded a
  `chrome` param, since they take no state). The selected-rung jade, the
  audio icon, the boost badge, and every AccentOrange usage are untouched.
  The four now-unused `RaddHud*` imports were removed. @Composable count in
  PlayerScreen stays 46; DetailScreen stays 15.
- `VipViewModel`: NEW state (`themeCatalog`, `requestPrice`, `ownedThemes`,
  `selectedTheme`, `requestMessage`/`isRequesting`,
  `themeMessage`/`isBuyingTheme`); `loadWallet` also reads the theme
  catalog, the request price and the owned themes; `observeTheme` collects
  the stored pick. NEW `requestMovie(title)` (blank title and short wallet
  are messages, not crashes; a replay is reported as already filed),
  `buyTheme(theme)` (owned themes cost nothing and are worn at once; a
  purchase saves the pick and refreshes the balance), `selectTheme(theme)`
  (wear an owned theme without buying).
- `VipUpgradeScreen`: NEW `RequestMovieCard` (title field capped at 200
  chars, the server's own cap; button disabled while blank, requesting, or
  short of the published price; the card is absent until the server
  publishes a price) and NEW `ThemeCard` (Jade free, Midnight/Ember with
  the published price; Buy when locked, Wear when owned, "wearing" on the
  active one; absent until the server publishes prices). Both sit under the
  streak card, only when signed in. @Composable count in VipUpgradeScreen
  goes 15 → 17 — exactly the two cards added.
- NEW app tests (`ModelsTest`, +11): share request/response (including a
  second share the same day as no grant), request-movie request/response,
  redeem-theme request/response, themes response, caps request + themes,
  progress write with and without `coins_earned` (an older server pays
  nothing).

## Checks (local, the CI way)

- `test_coins_engine` 67 OK (was 43; +24: Share 6, FinishWatch 5,
  RequestMovie 7, Themes 6 — the knob cases assert 0/unparseable → shipped).
- `test_accounts_api` 38 OK (its selfcheck now passes end to end, after the
  `register` → `create_account` fix).
- `test_api_v2` 46 OK, `test_admin_panel` 94 OK, `test_engagement` 34 OK,
  `test_engagement_ladder` 27 OK, `test_redact` 76 OK, `test_accounts` 64
  OK, `test_device_trials_and_webhook` 83 OK, `test_docs_invariants` OK
  (count bumped 87 → 88).
- `test_download_endpoint` 23 tests with only the 2 PRE-EXISTING
  operator-port 401 failures from Session 73 (same two test names, untouched
  code — `viewer.py` was not edited in this build).
- App: braces/parens balanced and `/*` vs `*/` balanced in all 13 edited
  Kotlin files (PlayerScreen's +1 is pre-existing at HEAD, same as
  DetailScreen's `"video/*"` MIME string); every new import is used;
  @Composable counts as above; no string literal with a letter+whitespace
  added to PlayerScreen.kt. No local Gradle run (owner order: GitHub Actions
  only) — CI judges the app.
- **Not done:** push (this commit, then CI judges — nothing is in flight).
  Device checks owner-only (share a title → "+25 coins" once a day, a
  second share the same day shows nothing; finish a title past 90% → "+15
  coins" toast once, a rewatch shows nothing; request a movie at 300 coins
  → the request is queued; buy Midnight at 250 coins → the player wears it
  at once, and the accent that marks a selected control stays jade).

## Fix — Android CI failed on 7899a9d, two missing imports (02:15 PKT)

- Android run 42294440062 FAILED at `:app:compileDebugKotlin`; Backend run
  42294440031 SUCCESS. The log's `e:` lines: `SyncAccountRepository.kt:759
  Unresolved reference 'DownloadCreditPrice'` and
  `VipUpgradeScreen.kt:394/424 Unresolved reference 'PlayArrow'`.
- Both are Build 5's own import-block edits (the CoinRedeemed trap, again):
  (1) VipUpgradeScreen lost the pre-existing `PlayArrow` import while
  gaining Movie/Palette; (2) `loadThemeCatalog` used the
  `DownloadCreditPrice` type without ever importing it.
- A full import diff `fc35d4d` → `7899a9d` across all 13 edited Kotlin files
  proved these were the only two. Fixed with two one-line imports; the fix
  commit re-runs CI, which also finally exercises the 11 new ModelsTest
  tests (the failed run died before any test executed).

## Decisions the user still owns

- The pass-ladder price flag from Build 3 stands: day = 500 coins, weekend
  = 70, monthly_vip = 200 — a weekend still costs less than one day. The
  operator can reprice via the knobs, or the user can name new prices.
- The movie-request queue has no panel surface yet: requests land in the
  `movie_requests` table (`status` 'open'), and the operator reads them from
  the database until a panel page is built (a gate item, not part of this
  build).
