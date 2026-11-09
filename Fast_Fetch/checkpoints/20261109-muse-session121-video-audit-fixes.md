# Session 121 — full-video UI audit fixes (36 issues, TestingBot video)

Date: 2026-11-09 ~05:0x–05:30 PKT. Base: session120-ui-fixes @ a0584d0 (CI green
both workflows, APK 285). Branch: session121-video-audit-fixes. App only; no
backend change, no push (parent verifies and pushes), no local Gradle run by
owner order — CI (ci.yml on push) judges.

Source of truth: `goals/radd-stream-on-oracle-vm/hidden_files/session120-full-video-ui-audit.md`
(36 issues: 6 P0, 16 P1, 14 P2, grounded in App source + Netflix/Prime/Disney+/
YouTube/JioHotstar patterns). Audit numbering is used throughout; the task
brief's paraphrase renumbers some items and adds items the audit does not
contain. Video: TestingBot, Galaxy S24 Android 14, 6:56, session 8abf2bf4
(2026-11-08 21:15:13 UTC). Diff: 27 files + 2 new test files, +629/−129.

## P0

- **P-1 Playback never starts (3:30–6:50):** UI parts only — honest human error
  copy (P-6), no raw codes (P-6), "Try another print" reaching a different
  print (already wired in 120). No server-side fix attempted; the Ali Baba
  film's named print is dead server-side and the failover ladder exhausts
  correctly (established in 120).
- **P-2 Give-up card overlap: SKIP — already fixed in 120** (verified: all five
  actions stack vertically full-width, dismiss slot empty).
- **P-3 "Keeping 0 B of 3.05 GB" chip: SKIP — already fixed in 120** (verified:
  "Saving a copy in the background").
- **P-4 Search "Series — 4" heading over Movie cards: SKIP — already fixed in
  120** (verified: `groupSearchResults()` sorts by `typeOrder`, no TreeMap).
- **P-5 Raw JSON array in series details** (`2026 · Series · ["Tamil",
  "English"]`): root was `DetailScreen.kt` using `post.language` raw in the
  meta list. Fixed twice, idempotently: mapper-side
  (`V1CatalogMapper.kt`: `WireText.listOf(detail.language).joinToString(", ")`)
  and at the render site (`DetailScreen.kt`, same call). `WireText.listOf`
  parses JSON-array strings, CSV, and " + "-joined lists, never throws.
- **P-6 Raw ExoPlayer code** (`ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT`,
  wrapped mid-word): root was `PlaybackService.summarize()` returning
  `"$causeName $detail"` with `causeName = e.errorCodeName`, flowing through
  the failover Handoff into the give-up card. Fixed at the Handoff boundary:
  pure `humanizeErrorSummary(raw)` in `RenditionFailover.kt` maps known
  `ERROR_CODE_*` prefixes to human sentences (timeout / unreachable server /
  not-a-video / copy gone / device cannot play / unknown code → generic
  sentence, code never shown); already-human messages pass through
  ("Reached max_ranks=…", "link expired…", "No directly playable…",
  "Playback stopped"). Raw code stays in logcat via a `Log.d` in
  `PlaybackService.onPlayerError` before calling `onFailure`.
  `RenditionFailover.kt` stays Android-free (JVM-unit-testable). New test
  `player/FailoverHumanMessageTest.kt` (4 tests incl. the machine-level
  Handoff detail + record reason). Note: `PlayerViewModel.kt:461`
  `connectionError = "Playback service unavailable: ${t.message}"` is a
  separate raw-ish path, left alone (out of scope).

## P1

- **P-7 "Quality: Ali Baba aur 40 Bhoot":** root was
  `PlaybackRendition.displayLabel()` falling back to `PrintInfo.summary()`,
  which fell back to `label` — the title — when resolution/sourceTag/codec
  were all blank/unknown. Fixed: `summary()` returns `""` when no parts
  (its only caller is `displayLabel`); new pure helper
  `looksLikeQualityLabel` gates the "Quality:" line in `StartNoticeCard` and
  the TopBar subtitle (subtitle dropped entirely when nothing quality-like
  remains; HLS/expiring/Auto tags still shown on their own). New test
  `player/PlaybackRenditionLabelTest.kt` (3 tests).
- **P-8 Film size "≈ 513 B" for a 3.05 GB file:** `QualityLadder.formatBytes`
  is correct; the input `sizeBytes`=513 is bogus (probe measured a
  redirect/landing page, not the file). Fixed in the app: `sizeLine` returns
  null when `sizeBytes < 1 MB` (implausibly small for video); the row shows
  only the behaviour word. Test added (`QualityLadderTest`: 513 → null,
  1,000,000 → "977 KB"). The server-side probe fix is out of scope.
- **P-9 Tier chip "Stan / dard":** `TierPill` text had no wrap control. Fixed:
  `maxLines = 1` + `softWrap = false`.
- **P-10 Two stacked VIP upsell cards:** (a) at most one shows —
  `premiumSourcesLocked` → `VipSourcesCard` only (kept at its original
  position after the rungs); else if `!adFree` → `SponsorCard` only. (b) The
  "Sponsored" label row is dropped and the default title
  `Brand.copy("sponsor_title", "Go VIP — no sponsor cards")` → "Go VIP" (it
  is a first-party VIP house card, not a sponsored slot). (c) Root cause of
  the false promise: `premiumLocked` (`DetailViewModel.kt`) used
  `VipQualityGate.hasPremiumPrints`, which checks resolution only — a 1080p
  download_only print counted as premium. New
  `VipQualityGate.hasPlayablePremiumPrints(layout, freeQualityCap)` requires
  premium resolution AND (`playableHere` OR `opensProviderPage`); used in
  `publishViewerContent` for `premiumLocked` (also fixes `includedLine`);
  ladder-scope check excludes `scope.downloadOnlyBands`. Test added
  (`VipQualityGateTest`: download-only 1080p → old check true, new check
  false; playable 1080p → true; provider-page 1080p → true).
- **P-11 No duration: 0:00 / --:-- whole session:** `BottomControls` and
  `EdgeHud` showed position + `"--:--"` total when `durationMs <= 0`. Fixed:
  hide the total until `durationMs > 0`; while `startPhase != NONE` show
  "Loading…" (existing `app_loading` string) in place of the time row; once
  playing with unknown duration, position alone. Removed the now-unused
  `player_time_of_unknown` string (verified no other references).
- **P-12 Keyboard covers search results:** 120's `.imePadding()` is present
  (verified). Remaining part fixed: dismiss keyboard on submit
  (`KeyboardActions.onSearch` clears focus + hides keyboard, then submits)
  and on scroll (`SearchBody` hoists `resultsScroll`, `LaunchedEffect` on
  its value clears focus when > 0).
- **P-13 "12 results" twice:** top bar showed `resultsSummary(...)` when
  `hasSearched` AND the body count row showed the same. Fixed: top bar
  always "Search"; body count row kept (next to Sort).
- **P-14 Suggestion chips clipped at right edge:** suggestions `LazyRow` had
  only vertical content padding. Fixed: end padding 16.dp (start 0 — outer
  Column already pads 16.dp). Fade skipped.
- **P-15 "?" badge on first search poster: PROVED NOT app UI.** Appears in
  exactly ONE frame (frame_030, 2:30), gone by frame_031 (2:35) and
  frame_032 (2:40); zoomed crop shows a grey speech-bubble with a tail at
  the keyboard boundary — a Gboard key-preview popup, not an app element.
  No "?" literal, no Help icon, no tooltip composable exists in the app;
  `ImageFallbackCard` renders title initials or the brand mark, never "?".
  Defensive hardening only: `fallbackLabel` sanitized in `ImageFallbackCard`
  (a label with no letter/digit renders the mark alone), so "?" can never
  render. The audit's root-cause guess was wrong; the hardening is still
  worth doing.
- **P-16 Selected "All" chip is dark red/maroon, app accent is green: ROOT
  CAUSE FOUND.** `FilterChip`'s default `selectedContainerColor` =
  `secondaryContainer` = `RaddCoralContainerDark` = `#3A1210` (maroon) from
  `brand.properties`; dark scheme primary is jade `#2BC79A`. Live
  remote-config verified via the public read-only endpoint: accent empty,
  so NOT the operator accent; theme is brand-locked
  (`dynamicColor=false`). Fixed: shared helper `raddFilterChipColors()` in
  `ui/components/CommonUi.kt` (selected container `primaryContainer`, label
  + icons `onPrimaryContainer`; unselected defaults unchanged), applied at
  ALL 9 `FilterChip` sites (verified by grep): Search suggestions /
  FilterRail / recents / Plan / FacetChips (5), MyList sort, Detail season
  chips, Settings ChipRow + ContactDialog.
- **P-17 No visible back/exit button in the player while loading:** chrome
  only showed `if (controlsVisible && !state.locked)`; `BackHandler` (117)
  works but is invisible. Fixed: `chromeVisible = controlsVisible ||
  state.startPhase != StartPhase.NONE`; TopBar/EdgeHud show while
  `chromeVisible && !locked`; CenterControls/BottomControls still gated on
  `controlsVisible` only.
- **P-18 Error card promises "keep it for offline" but offers no keep
  button:** audit's blessed alternative taken — change the COPY, do not add
  a keep button. The player's `keepCurrent()` is a progressive-cache adopt,
  not a full download; a failed print has no cached bytes, so a Keep button
  there would fail confusingly. New copy: NO_CANDIDATE_LEFT → "Every option
  for this print failed. Retry, try another print, or open it in another
  player."; DOWNLOAD_ONLY → "This quality can't stream here. Go back to the
  title to keep it for offline, or open it in another player."
- **P-19 "Close player" (white) vs green actions; "Close" vs "Close player"
  between dialogs:** in the 120 base there is ONE `GiveUpCard` for both
  variants and the dismiss is `player_close` ("Close", white 0.7 alpha) in
  both — the two-labels problem from APK 282 is already unified by 120.
  BUT "Close" means "keep waiting" (`onDismiss` dismisses the card, player
  keeps waiting), NOT "close player". Fixed (deviates from the audit's
  literal "Close player", which would misdescribe the action): dismiss
  renamed to "Keep waiting" (new string `player_keep_waiting`), subdued
  white style kept. `player_close` kept (still used by another dialog).
- **P-20 Hero title collides with poster's baked-in title art:** scrim was
  `0f → 0f, 0.45f → 0.15f, 1f → 0.92f`. Fixed: `0.35f → 0.25f, 0.7f →
  0.65f, 1f → 0.95f`.
- **P-21 First-run: analytics dialog over pure black, no splash:** 120
  already added a branded launch background + loading screen (verified in
  `MainActivity.kt`). Remaining part fixed: the consent dialog now shows
  only when `analyticsConsentKnown && analyticsConsent == null &&
  destination == Screen.Home.route` — it waits until Home is the
  destination, so the first thing a new viewer meets is the app, not a
  question; a first-run viewer answers it on the next launch instead.
  Limitation: `destination` is a `val` captured at composition start, so a
  further deferral until Home's rails load would need a Home-loaded signal
  from `HomeViewModel` — follow-up.
- **P-22 Bottom VIP card half-hidden behind system nav bar:** `DetailContent`
  `LazyColumn` bottom content padding was a fixed 40.dp, ignoring the
  Scaffold's bottom padding. Fixed: `contentPadding.calculateBottomPadding()
  + 40.dp`.

## P2

- **P-23 Genre picker dead black space below Continue:** content ended after
  Continue + 16.dp spacer. Fixed: `verticalArrangement =
  Arrangement.Center` on the Column (short content centres; tall content
  still scrolls from the top).
- **P-24 No Skip on genre picker:** added `RegionViewModel.skip(onSaved)`
  (`select(UserRegion.DEFAULT)` then `saveAndContinue(onSaved)`;
  `UserRegion.DEFAULT` = Desi) + a "Skip" `TextButton` under Continue
  (disabled while saving).
- **P-25 Home "Media browser" heading; no Continue Watching row at top:**
  Continue Watching IS first and pinned in code (`HomeScreen.kt:200`) —
  renders when progress exists; the video was a fresh install (no
  progress), so absence is expected → verified present. Remaining fix:
  "Media browser" → "Browse" (`BrowserStrip` header).
- **P-26 No Play action on Home hero (biggest item, done last):** hero HAS a
  Watch Now button but `onClick = onPostClick` → opens DETAILS, doesn't
  start playback. Fixed: (a) Detail route gains an optional `autoplay` arg
  — `Screen.Detail` route `"detail/{postId}?autoplay={autoplay}"`,
  `ARG_AUTOPLAY`, `createRoute(postId, autoplay: Boolean = false)`; NavGraph
  adds the `navArgument` (BoolType, default false) and passes `autoplay` to
  `DetailScreen`; `DetailViewModel.playBest()` picks the best print from the
  current layout (same `maxByOrNull { rankKey }` across workPrints + season
  episode prints + packedPrints as the screen's own Play button) and calls
  `playPrint` (locked/no-playable degrades gracefully — stays on details
  with the reason via `actionMessage`); `DetailScreen` has `autoplay:
  Boolean = false` + `LaunchedEffect(state.post?.id, autoplay)` with a
  `remember`ed `autoPlayedFor` flag so it auto-plays once per title. (b)
  Hero "+ My List" toggle: `HomeViewModel` exposes `favoriteIds: Set<Int>`
  in `HomeUiState` (observed from `favoritesRepository.getAllFavorites()`
  via new `observeFavorites()` in `init`) + `toggleFavorite(post)` (same
  add/remove the details page uses); `HomeScreen` gains
  `onWatchNowClick: (Int) -> Unit = onPostClick`; NavGraph passes
  `onWatchNowClick = { navigate(Screen.Detail.createRoute(postId, autoplay
  = true)) }`; `HeroCarousel` gains `onWatchNow` / `isFavorite` /
  `onToggleFavorite`; Watch Now calls `onWatchNow` (slide tap still opens
  details); a second Button beside it (surface 0.55 alpha container,
  matching the year/type badges) with Favorite/FavoriteBorder icon +
  "My List"/"Saved" text.
- **P-27 Home search bar is a fake field: VERIFIED in code — it navigates.**
  `HeroSearchBar(onClick = onSearchClick)` → `Screen.Search.route`. Closed
  as verified, no change.
- **P-28 Search card subtitle clipped** ("Dual Audio" cut off at card
  bottom; the audit misread it as "Desi Audio" — no such string exists):
  zoomed crop shows the pill cut mid-glyph by a straight edge with no
  rounded corner below → the **rail** clips it; the rail is ~one badge-row
  short. Exact Compose measurement cause not statically provable. Fixed:
  reserve a fixed-height badge slot (`Box` height 24.dp — the `Pill`'s own
  height — always present even when badges empty) so card height is
  invariant to badge presence; plus details Text `maxLines = 2` (was 1)
  with ellipsis.
- **P-29 "Anime" type chip tight/clipped at right edge:** `FilterRail`
  `LazyRow` had only vertical content padding. Fixed: end padding 16.dp
  (same pattern as P-14).
- **P-30 Back arrow on a bottom-nav tab root (Search):** Search is a tab
  root AND reached from Home's search bar (same route, no distinction in
  current code). Fixed: arrow removed entirely (tab root; bottom nav always
  visible) — removed `navigationIcon`, the `onBackClick` param from
  `SearchScreen`, the NavGraph arg, and the now-unused `ArrowBack` import.
  Only one `SearchScreen(` call site exists.
- **P-31 Synopsis cut mid-sentence, no visible "more": VERIFIED in code.**
  `ExpandableSynopsis` exists — `maxLines = 4` + "Read more"/"Show less"
  when `text.length > 180`. The video cut is the fold, not the component.
  Closed as verified, no change.
- **P-32 Details top-bar title truncated:** title `maxLines = 1` +
  Ellipsis. Fixed: `maxLines = 2` with `titleMedium` style (fits the 64dp
  bar); full title also in `PosterHeader` (maxLines=3).
- **P-33 Five actions in one dialog is too many:** 120's vertical stack
  made all 5 readable. Fixed by hierarchy, not removal: keep all 5 — each
  is a distinct recovery path for a multi-source player, and removing them
  would remove recovery options at a failure moment. Retry + Back to
  details stay green (primary); Try another print + Open with another
  player white/subdued (0.85 alpha); Keep waiting white 0.7 (dismiss).
- **P-34 Wavy-line loader as dialog icon:** `GiveUpCard` icon was
  `ic_logo_mark` (brand mark, 32dp). Fixed: `Icons.Default.Warning` (coral
  tint `RaddCoral400` — matches `ConnectionErrorCard`, which already uses
  it). `LoadingWave` kept as the loading animation (the problem was one
  asset doing three jobs, not the loader itself).
- **P-35 "Keeping" chip overlaps the player title row:** `TopBar` Row = back
  button + title Column (`weight(1f)`) + `KeepChip` + print-sheet button;
  frame 046 shows the chip squeezing the title to "Ali Baba …" (no literal
  overlap in that frame, but the crowding is real, worse at 360dp). Fixed:
  `KeepChip` moved OUT of the TopBar into `BottomControls` as its own row
  above the Scrubber (start-aligned, 12dp horizontal + 8dp top padding),
  guarded by `if (state.keep !is KeepUiState.Unavailable)` (an empty row
  would still take its top padding). It is NOT a seventh transport button,
  so the six-primaries rule still holds; pureCinema/EdgeHud never had the
  chip (unchanged).
- **P-36 No attempt counter during the 30 s wait:** new string
  `player_attempt_counter` = "Trying copy %1$d of %2$d"; computed at the
  call site from `state.bundle?.renditions` (total) + `state.activeRendition`'s
  index in the bundle (attempt = index + 1, default 0); shown only when
  total > 1; new `attemptLabel: String? = null` param on `StartNoticeCard`,
  rendered under the title (before the slow-hint block).

## Brief-only items (no audit counterpart) — verified present, not built

- "Save to My List" button: top-bar heart toggle exists and works
  (`DetailScreen.kt:223`, filled + secondary tint when saved).
- "Quality row opens nothing": quality-sheet rows are clickable; print-sheet
  "Change quality" opens the sheet.
- "Keep chip Saved state": Stored state "Kept ✓" exists.
- "Play button greyed out with no reason": reason text exists under the
  button (`DetailScreen.kt:483-490`, shown when prints exist but none can
  start).
- Brief's search hint "Search titles, actors, or genres": the API only
  searches titles; implemented as "Search for a title" instead (honest).

## Checks

- Pre-push Kotlin checks clean over all 29 files: every added import used
  (one removed import: `ArrowBack` in SearchScreen — correct); @Composable
  counts unchanged except CommonUi 16→17 (the new `raddFilterChipColors()`
  helper — expected); `/*` vs `*/` balance unchanged vs base (DetailScreen
  26/25 and PlayerScreen 23/22 are the pre-existing counting artifact from
  MIME strings `"video/*"` and `"*/*"`, not unclosed comments); no `/*`
  written inside any KDoc/comment; `strings.xml` parses OK; no new
  drawables added. No new network data classes, so rule 7 needs no new
  JSON deserialization test.
- New tests: `FailoverHumanMessageTest` (4), `PlaybackRenditionLabelTest`
  (3); extended: `QualityLadderTest` (P-8), `VipQualityGateTest` (P-10).
  Expectations hand-checked against source (e.g. `formatBytes(1_000_000)`
  = "977 KB"; `bitrateClass` for 1080p non-official = "Standard bitrate";
  `RankedLink.isProviderPage` is the `isPageVerdict(kind, playability)`
  rule, so the test's kind="external" + WEBVIEW page link counts).
- Diff read line by line in full (all 27 files + 2 new test files + 2
  extended test files). Extra verifications during review: 9/9
  `raddFilterChipColors()` call sites; only one `SearchScreen(` call site;
  `painterResource` still used elsewhere in PlayerScreen (import not
  orphaned); `player_close` still used by another dialog; zero remaining
  `player_time_of_unknown` references.
- No local Gradle run by owner order — CI (ci.yml on push) is the gate.
  **Not done:** push (parent's step, then CI judges); device retest (see
  below).

## Device retest needed (after APK 286, CI)

Almost everything visual needs a device pass: P-5 language line, P-7 quality
line, P-9 tier chip, P-10 single upsell card, P-11 duration, P-12 keyboard
dismiss, P-16 green chips, P-17 back button while loading, P-20 hero scrim,
P-21 first-run splash, P-22 bottom padding, P-25 "Browse" heading, P-26 hero
Play/My List, P-28 badge clip (root cause inferred, not proven), P-30 Search
back arrow. TestingBot minutes are exhausted and the 7-day trial needs a card
(owner decision, parked); ~10 Sauce Labs minutes remain.

## Known limitations / follow-ups

- P-8: server-side probe fix out of scope (probe measured a redirect, not the
  file).
- P-21: further deferral until Home's rails load needs a Home-loaded signal
  from `HomeViewModel`.
- P-6: `PlayerViewModel.kt:461` `connectionError` raw-ish path left alone
  (out of scope).
- P-14: fade skipped (end padding only).
- P-28: root cause inferred from the crop, not proven — the device retest
  decides.
- P-19: audit's literal "Close player" deliberately not used — it would
  misdescribe a dismiss that means "keep waiting".
- P-18: copy changed, no keep button added — a failed print has no cached
  bytes for a keep to adopt.
