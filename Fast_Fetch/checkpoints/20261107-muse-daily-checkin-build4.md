# Session 76 — Daily check-in coin system, Build 4: Direct Download Pass for 100 coins (2026-11-07 ~01:30 PKT)

User order (00:46 PKT): "Complete all work one by one" on agy's daily check-in
proposal. Builds 1–3 shipped the 7-day ladder, the claim, and the 24h VIP pass
(500 coins, CI green on f783b2c, Android run 42287922463 + Backend run
42287922705, APK app-debug-236). This build makes the second thing coins buy
actually work.

## The gap, found by reading the code

A free viewer who wants a file has two routes, and neither takes coins. The
in-app download is already direct (no shortener ever touches it), and the
[Get Free Web Link] button (Session 73) opens the browser at
`/api/v1/download?id=<handle>&via=web`, where the server shortens the target
through ShrinkMe when the operator enabled it. Agy's "Instant/Direct Download
Pass, 100 coins/movie (bypass the ShrinkMe web shortener)" had no server side
at all: no credit store, no redeem, no consume step in the download flow. The
credit is genuinely new — a count-based redeemable, not a time pass — so it
needed its own table, its own signed token, and its own consume in the
download route.

## Server

- NEW `coin_download_credits` table in the `engagement` DDL (`account_id`,
  `handle`, `expires_at`, `used_at`, `created_at`), installed by
  `ensure_schema` — `CREATE TABLE IF NOT EXISTS`, so existing DBs pick it up
  with no migration and no version bump. `handle` is the opaque download id
  the credit was bought for: a credit for one movie buys no other.
- NEW `redact.mint_download_credit` / `parse_download_credit` — version byte
  4, tag domain `b"dlc"`, body is the 8-byte credit row id. A VIP pass (version
  3, expiry body) must never parse as a credit and a credit must never parse
  as a pass; the token carries only the id — expiry, handle and use live in
  the row, so a leaked token is one download of one movie, and only until it
  is spent.
- `engagement.DOWNLOAD_CREDIT_COINS = 100`, `DOWNLOAD_CREDIT_SECONDS = 86400`
  (a bought credit stays good for a day — the viewer buys it and taps the
  link, so the window only covers a browser that opens late). Price resolves
  through `resolve_download_credit(values)` with the same whole-number knob
  rule as the ladder (stored 0 or unparseable paste means the shipped number,
  never free); the operator knob is `coin_redeem_download`, default 100 in
  `admin_panel.py`.
- NEW `engagement.redeem_download_credit(conn, account_id, *, handle,
  credit_secret, now, values, idempotency_key)` — spends the resolved price
  with reason `"redeem_download"` (new in both `LEDGER_REASONS` and
  `SPEND_REASONS`), then records the row and mints the token. The spend's
  idempotency key is `redeem-download:<account>:<handle>:<second>`, so a
  same-second double-tap spends nothing twice; a replay re-derives the token
  from the live row and reports the row's own expiry, not a fresh day — and
  when the replay's credit is already spent it answers token null and
  expires 0.0, not a fresh promise.
- NEW `engagement.consume_download_credit(conn_or_path, token, *, handle,
  credit_secret, now) -> bool` — True only when the token is ours, names a
  credit bought for this exact download id, is unexpired, and has never been
  used. The consume is one guarded UPDATE (`used_at IS NULL AND expires_at >
  ?`), so two browsers racing the same token get one file and one refusal.
  Anything else is False, never an exception: the download route falls back
  to its ordinary shortening, so a bad token costs a direct link, never the
  download itself.
- NEW route `POST /api/v2/account/coins/redeem-download` (body: `handle`
  only) — the handle IS the purchase, so the route checks it is one of our
  own signed tokens (`redact.parse_token`, signed-only) before any coin
  moves; a credit for a handle that never resolves would be 100 coins for
  nothing. Short wallet answers 402 `licence_required`, the same as the pass
  route, naming no number. Answer: `{"credit": {token, handle, cost, balance,
  already_applied, expires_at}}`.
- `GET /api/v2/account/coins/caps` now also publishes
  `"download": {"coins": resolve_download_credit(values)}` — row-resolved, so
  the price a phone is shown and the price the wallet is debited are one
  read. The `caps` wallet block is untouched (it is the shipped projection).
- `viewer.py` `/api/v1/download`: inside the free-tier branch, before the
  shortening decision, a `credit` query param is consumed against the user-state
  DB (`engagement.default_db_path()`), and `via_web` shortens only when no
  credit was spent (`if via_web and not credit_used`). A credit is consumed
  only when the file redirect is actually served — the adult gate, the quality
  gate and the resolver all run first — and VIPs never reach the consume at
  all (their downloads are already direct).

## App

- `AccountWire.kt` — `CoinCapsResponse` gains `download: DownloadCreditPrice`
  (0 when the server predates the credit: the phone offers no direct link
  rather than inventing a price); NEW `CoinDownloadCreditRequest(handle)`,
  `CoinDownloadCredit` (token/handle/cost/balance/alreadyApplied/expiresAt),
  `CoinDownloadCreditResponse`.
- `RaddStreamApi.kt` — NEW `redeemDownloadCredit` POST.
- `SyncAccountRepository.kt` — NEW `loadDownloadCreditPrice()` +
  `redeemDownloadCredit(handle)`, same verdict pattern as the pass methods.
- `WebDownloadUrl.kt` — NEW `webDownloadUrlWithCredit(base, handle, token)`
  (`...&via=web&credit=<token>`).
- `DetailViewModel.kt` — `DetailUiState` gains `downloadCreditPrice`,
  `coinBalance`, `directLinkMessage`; when the keep dialog opens for a free
  viewer the price and the balance are read so the button can say what a
  direct link costs and whether the wallet covers it; NEW
  `directDownloadUrlFor(handle)` (suspend): redeems, updates the balance,
  returns the credited browser URL, or null with the reason in
  `directLinkMessage` ("Could not reach the server" / "That direct link was
  already used"). Confirm/dismiss clear the message.
- `DetailScreen.kt` — `KeepConfirmDialog` gains a "Direct Link — N coins"
  button for free viewers when the server published a price, enabled only
  when the balance covers it, plus the failure message when one is set.
  @Composable count stays 15.

## Tests

- `test_redact.py` — NEW download-credit round trip + no pass confusion
  (tamper, wrong secret, garbage, VIP pass never parses as a credit and vice
  versa). 76 OK.
- `test_engagement.py` — NEW section 11 (5 tests): price resolves from its
  knob and 0 means default; a credit is recorded and spends exactly once
  (second consume False, wrong handle False); a credit for another movie or
  a lapsed one spends nothing and stays unspent; a redeem retry mints nothing
  twice and re-derives the token with the row's expiry; a short wallet mints
  nothing. 34 OK (was 29).
- `test_coins_engine.py` — NEW `RedeemDownload` class (6 tests): short wallet
  402 + ledger unmoved; a credit costs the published price and names its
  movie (token parses to the credit row id); the price charged is the price
  the caps route publishes (knob 7 → caps 7 → charge 7); caps publishes the
  download price by default; a handle that is not ours is a 400 and spends
  nothing (incl. an extra key); a second purchase in the same second is a
  replay, not a second spend. 43 OK (was 37).
- `test_download_endpoint.py` — NEW 2 socket tests: a bought credit skips the
  shortener once and only once (second use of the same token is shortened,
  `used_at` set); a credit for another movie or a bad token still shortens
  and stays unspent. 23 tests, only the 2 pre-existing operator-port 401
  failures remain (Session 73 baseline).
- Full cluster OK: `test_accounts`, `test_accounts_api`, `test_api_v2`,
  `test_admin_panel`, `test_device_trials_and_webhook`,
  `test_engagement_ladder`, `test_docs_invariants` (count bumped 86 → 87).
- App: `ModelsTest` +4 tests (caps download decode, caps without a download
  block offers no link, request encodes to `{"handle":"..."}`, receipt
  decodes), `WebDownloadUrlTest` +2 tests (credit appends after the web
  marker, token is URL-encoded). @Composable count in DetailScreen stays 15;
  braces/parens balanced and `/*` vs `*/` balanced in all edited app files
  (the one apparent imbalance is the pre-existing `"video/*"` MIME string);
  every new import is used.

## Not done

Push (this commit, then CI judges — nothing is in flight). Build 5 (share +25
/ finish-watch +15, themes 250, request-a-movie 300) still to come. Device
checks owner-only (buy a direct link at 100 coins → the browser opens the
file, not the ShrinkMe page; a short wallet disables the button; a second tap
on the same link goes through the shortener).
