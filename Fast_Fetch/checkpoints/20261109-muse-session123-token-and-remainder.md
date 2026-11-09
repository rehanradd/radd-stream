# Session 123 — token system + audit remainder (2026-11-09, builder)

Branch `session123-token-and-remainder`, base main @ 4421cb2. NOT pushed — the
parent does CI/APK/push. No local Gradle run (owner order), no APK built, no
device session started. Commits A–L below, all by rehanradd <rehanradd@gmail.com>.

## What landed, in brief order

- **A `9ccc779` — token system first.** `RaddTokens.kt` (spacing, radius,
  motion, touch, elevation, colour, type aliases over the existing systems);
  player chrome folded into brand roles (Color.kt §13: stage/sheet/dialog →
  Ink ramp, AccentOrange → new `colors.dark.player_accent=#FF8552`,
  narration/keep states → Success/Danger/TideIndigo at 40%); secondary
  container warmed #3A1210 → #40201B (hue, not contrast — 9.69:1 was already
  fine). 8-test `RaddTokensTest`. Closes D-50/D-51/D-52.
- **B `bab58a6` — SU-1.** `OfflineCacheEngine.serveUri` serves a partial
  progressive file through the proxy capped at the manifest's contiguous
  prefix (`selectServeFile`: complete wins, else largest partial with a taskId
  and a progressive extension, never m3u8); `PlayerLoadingIndicator` (real
  indeterminate ring) replaces the decorative `LoadingWave`; consent is a
  bottom sheet with 3 check-marked reassurances (D-1); region screen gains
  the "Free forever · No account needed" strip (D-4). D-35 poster-behind-
  loading NOT built: no poster field exists in the player route — plumbing
  NavGraph → PlaybackService → PlayerUiState is a bigger change; recorded.
- **C `2f0b884` — VIP-4.** The pass button says "Activate 4-Hour VIP Pass",
  not "Watch Ad"; no ad plays, no ad is promised, no SDK wired.
- **D `c4e1225` — PL-1.** Autoplay-next waits 10 s with a Cancel before it
  advances (`AutoplayCountdown` pure type, `PlayerUiState.autoplayCountdownSeconds`,
  `AutoplayCountdownCard`); manual Next and a new bundle clear the countdown.
- **E `1abb3fa` — DE-1.** Detail autoplay plays the resume when one exists,
  once `resumeLoaded` has answered — the load runs in its own coroutine, so
  deciding on `post` alone would almost always decide before the answer.
- **F `69c6d30` — missing screens.** `GET /api/v2/account/overview` (balance
  + streak + cadence, `account_id` stripped per §16.9) + Dashboard, Check-in
  (7-day ladder), Coins (balance + pass catalog + history), Profile screens;
  coin screens decode `engagement.*`, never the dead top-level wallet/streak
  keys. `test_coins_engine` 86 OK (was 82).
- **G `ecf5b1b` — wiring.** Wi-Fi-only gates on `DetailViewModel.keep`,
  `confirmKeep` and `PlayerViewModel.keepCurrent` (the `keepRung` leak);
  binge prefetch now calls `engine.seedPreview` after a usable probe; series
  auto-delete at player END on the episode's own cache key, complete keeps
  only (title-matching series keeps is forbidden — it would delete a season).
- **H `6a17345` — `is_resumable` index + report POSTs.** Index on
  `download_sources(is_resumable)` (`test_database` 216 OK); the player POSTs
  dead-link reports (first frame = played, give-up = failed) and pack-offset
  reports when the episode id resolves. **Nginx gap (parent's step):** no
  location exists for `/api/v2/links/*/report` or `/api/v2/episodes/*/offset`
  — the `^~ /api/` catch-all 403s them; the app drops failures silently, so
  the feature ships safe and goes live when the two POST-only locations land.
- **I `a792a44` — quality-gate mint refusal + VIP pass bearer.** `/play`
  answers 200 with `playable: false, reason: premium_quality_requires_vip`
  for a gated named print (a free sibling still wins the walk); the sync key
  rides `/play` as a header (same-host Retrofit, no redirect) but NEVER as a
  player/download header (ExoPlayer forwards headers to 302 targets) — the
  signed `?vip=` pass (6 h TTL, in-memory cache only) rides stream/download
  URLs instead. `test_api_v2` 71 OK; `test_accounts_api` 38 OK.
- **J `94ded78` — server remainder.** `resolved_link_cache.py` (lazy-first
  freshness over the ledger row — no second table: the row already stores
  final_url/expires_at/last_checked_at, and only 298 of 4,074,415 live rows
  carry a measured expiry — + top-200 eager `warm()`); `maintenance.py`
  (bounded propagate + warm + heal tick inside `serve`, env-gated
  `RADD_MAINTENANCE=off`, 6 h default, first tick after 60 s, memory floor
  1500 MB skips a tick; `ping_domains` stays CLI-only — a domain migration is
  an operator decision); `fts_search.py` (standalone FTS5 over normalised
  title/original-title/genres/aliases, rebuilt by the projector at the end
  of `_finalize`; the v2 search already accelerated on `cat_works_fts` when
  present — the table simply never existed). FTS proven end to end on a
  fixture projection (2 works → 2 FTS rows, "amelie" → work 1). Tests:
  `test_resolved_link_cache` 14 OK, `test_maintenance` 11 OK, `test_fts_search`
  9 OK; all three registered in backend-ci.yml; invariants OK. **Rename
  (fixup commit):** the module was first written as `resolved_cache.py`, but
  that name collided with qoder12's unlanded Phase-1 module — `test_host_classifier.py`
  guards `import resolved_cache` and calls `init_resolved_cache` /
  `record_resolved_cache` on it, so the new file made 31 of its tests error
  instead of skip (first full gate: 63/64 PASS, FAILED MODULES: 1). Renamed
  to `resolved_link_cache.py` (module, test, `maintenance.py` import, CI step,
  docs); the old name stays free for qoder12's module if it ever lands.
- **K `757f56f` — Home HO-1…HO-8.** Hero posters de-duplicated out of their
  own rail; "Your library" / "Browse by type" (was two "Browse"); JumpOffRow
  actually scrolls; search bar inside the 16 dp margin; tile renamed "Paste
  a video link" (HO-5); check-in card shows the SERVER's streak (overview
  read in `loadCheckInWallet`, claim answer refreshes it) and the claim
  states its amount ("Claim 10 coins for Day 3", from the ladder at the next
  claimable day); guests get a Sign-in button to Settings. Pure helpers
  `checkInDayLine` / `claimButtonLabel` pinned by `HomeCheckInTextTest` (7).
- **L `757f56f` — Search/Details/dialogs.**
  Search field is a filled pill with the one prompt "Search movies and
  shows" (D-15); Detail Play keeps a tonal fill when disabled + Download is
  a labelled secondary button (D-29); synopsis "Read more" appears exactly
  when the text overflows (D-31); rung rows share one pill language and tonal
  icon pads (D-33); one dialog title style everywhere — `RaddDialogTitle`
  (display, semibold, 20sp) at all 10 AlertDialog sites (D-2); give-up card
  gains a 1 dp outline (D-48); error card body left-aligned to match (D-47).

## Verified already-built, no code needed

- D-34 top-bar title: two lines since Session 121 P-32. D-45 dialog icon:
  warning triangle since Session 121 P-34. D-49 dead space: the 120/121
  five-action vertical stack sizes the dialog to its content. D-31's button
  existed (length-gated); L makes it overflow-gated. Broadcasts already
  render as cards above the catalog. Whole-movie download while watching was
  largely built (`keepCurrent`/adopt); G closed the Wi-Fi gate only.

## Deliberately left out

- **Strings-map:** no runtime path feeds server strings into `Brand` today
  (`Brand.load` reads compiled `brand.json` only; `useSnapshot` is
  tests/dev), and no panel UI exists to edit a server map. A half-built map
  would be dead code. Next session: server `strings` in remote-config +
  app merge (server wins over compiled) + panel UI to edit it.
- **D-35 poster behind player loading:** needs poster plumbing through
  NavGraph → PlaybackService → PlayerUiState; D-36 (real indicator) is done.
- **featureFlags.search/sharing/ads_enabled:** not invented — no panel UI.
- **Cast backfill `--apply`:** gate-only, parent's step.
- **WebDownloadUrl `?via=web` pass, CacheSeeds, EmbedWebViewModel:** the
  `?vip=` pass was deliberately not put in a browser URL (lands in browser
  history) — deferred to the next session.
- D-3/D-5/D-6/D-7/D-8/D-10/D-11/D-12/D-13/D-14/D-25/D-27/D-28/D-30/D-32/D-35/
  D-37/D-38/D-40/D-41/D-42/D-43, D-16/D-18…D-24, HO-9/HO-10/HO-11 and the
  rest of the 157-issue audit remain open.

## Checks

Backend suites run this session: test_api_v2 71 OK, test_accounts_api 38 OK,
test_coins_engine 86 OK, test_database 216 OK (skipped=1), test_catalog_v2
103 OK, test_docs_invariants OK, test_resolved_link_cache 14 OK,
test_maintenance 11 OK, test_fts_search 9 OK. Pre-push Kotlin checks per
commit: import diffs accounted, `/*` vs `*/` at baseline (DetailScreen
29/28, PlayerScreen 23/22 — pre-existing `"video/*"` string literals), no
brand-name strings, no raw Color(0x…) outside Color.kt. No local Gradle run
by owner order — CI (ci.yml on push) is the verification path. Full backend
gate run at session end; result in the parent's report.

## Not done (parent / next session)

Push + CI + APK (parent); gate-deploy (parent, incl. the two nginx report
locations); device verification of all of A–L on the next TestingBot
session (tokens/chrome fold, SU-1 partial playback, VIP-4 rename, PL-1
countdown, DE-1 resume, new screens, Wi-Fi gates, binge bytes, series
auto-delete, quality-gate refusal, VIP pass on URLs, HO-1…HO-8, search pill,
rung/dialog changes); strings-map; D-35 poster plumbing; the remaining
audit surface listed above.
