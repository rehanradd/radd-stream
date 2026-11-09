# Session 114 — app bugs found on real devices (region row, stuck player, VIP story) + seasons newest-first — 2026-11-09

Branch `session114-app-bugs` from `39bcaf96` (Session 113). Author rehanradd.
Builder does not push, deploy, or touch the live DB or live tree — the parent
pushes and gates. App-only session (no backend code changed; the only
`Fast_Fetch/` files are this checkpoint, the README pointer, and the
CONTINUITY count). No local Gradle run on this VM by owner order — CI
(`ci.yml` on push) is the verification path for the app items, so they are
code-complete, NOT verified. Device retest is the parent's step (Sauce Labs
trial remains: 28 days, ~41/60 live minutes left at 21:48 PKT 2026-11-08;
TestingBot 100 min is the reserve; Appetize is exhausted).

## 1. THE THREE DEVICE BUGS — VERIFIED BY THE PARENT ON REAL DEVICES

(a) REGION CONTROL DISAPPEARS (Sauce Labs, real Pixel 5, 21:48 PKT
2026-11-08). After switching Desi → East Asian in Settings, the
"Playback & Display / Watching region" row no longer appeared anywhere in
Settings, so the viewer could not switch back to Desi.

Root cause: navigation, not rendering. The Settings row has NO `if` gating
in code — it is unconditional inside `SettingsCard(title =
"Playback & Display")` (`SettingsScreen.kt`, was line 599). The row's screen
was destroyed underneath it: `NavGraph.kt` Region `onContinue` called
`navController.popBackStack(Screen.Home.route, inclusive = false)`, which
pops EVERYTHING above Home — when opened from Settings (stack Home →
Settings → Region) that pops Region AND Settings, dumping the viewer on
Home and destroying the Settings entry they came from. The region screen's
own subtitle promises "You can change it later in Settings", and Settings is
reachable only via the bottom bar, so the viewer had no way back. The row
was also the ~10th card down a very long Settings scroll, so even a viewer
who did return to Settings could miss it.

(b) STUCK PLAYER TRAPS THE USER (APKOnline tablet, 22:09 PKT 2026-11-08;
same trap on Sauce session 1). After a failed play (30 s give-up card;
Retry → "Cache engine failed" toast), Back / edge-swipe / fullscreen-toggle /
"Try another print" all failed to return to the detail page; only an app
restart escaped.

Root causes, demonstrated in code (a main-thread freeze was NOT evidenced
and was not chased):
- Give-up dialog ate Back and meant "keep waiting". `GiveUpCard`
  (`PlayerScreen.kt:1867`) is an `AlertDialog` with `onDismissRequest =
  onDismiss`. For the deadline branch the dismiss is
  `dismissDeadlineGiveUp()` — "keep waiting, with a fresh thirty seconds"
  (resets `startAttemptAtMs`, clears `deadlineGiveUp`); the ticker
  (`PlayerViewModel.kt:600-630`, every 200 ms) recomputes `deadlineGiveUp =
  elapsed >= 30_000 ms` until a first frame (`StartDeadline.hasFirstFrame` =
  `playbackState == STATE_READY` only). So Back dismissed the card but left
  the viewer in the player waiting, and the card returned. The card had NO
  "back to details" action — only Retry / Try another / Open external /
  Close, and Close meant keep waiting.
- Duplicate Player entries possible. NO Player navigation used
  `launchSingleTop`: Detail `onPlayStream`, Search direct URL, Downloads
  `onPlay`, `PlayerLocal` (two sites), Detail `onOpenProviderPage` Embed.
  A double-tap on Play (easy on a slow emulator — `playV2` has a 2 s
  timeout) stacks Player → Player, so one Back pops to an identical
  Player — looks exactly like "Back does nothing".
- "Try another print" is NOT a no-op (checked): `canTryAnotherPrint`
  derives from `nextPrintHandle != null` (`PlayerUiState.kt:371,385`);
  `tryNextPrint()` returns early only when the handle is null. The "Cache
  engine failed" toast comes from `CacheAffordance.kt:89`
  (`KeepUiState.Blocked(CacheState.FAILED, ...)`) — a Keep-chip toast, not
  the retry path. No `BackHandler` exists anywhere in `PlayerScreen.kt`
  (only `EmbedWebViewScreen.kt:113` has one); system Back relies on
  NavController default pop, which is correct once the two defects above
  are fixed.

(c) INCONSISTENT VIP PRESENTATION (Sauce Labs, 21:48 PKT 2026-11-08).
Settings → VIP Membership said "Free plan — playback stays at 720p" while
Settings → Account showed "Free VIP days are running on this install — 3
days left". Fresh installs get 3 free VIP days, so the VIP gate is inactive
and the 1080p refusal cannot be observed on them.

Root cause: the two cards read two different facts. Membership
(`SettingsScreen.kt`, VIP card) read `state.planIsVip` =
`entitlement?.vip == true` (`SettingsViewModel.kt:352`, collected from
`syncAccountRepository.entitlement`); Account read `account.trialSecondsLeft`
(observed via `observeTrial()`, `DeviceTrial.secondsRemaining` against the
server-read instant). The trial account IS a VIP account on the server —
`accounts.py:1421` mints it with `vip_until = now + trial_days * 86400`, and
the server quality gate (`viewer.py:503`) passes it via
`request_is_vip` — so the Membership line was factually wrong during the
trial. And the entitlement flow never learned the trial: `startDeviceTrial`
minted the key and stored the countdown but never refreshed the
entitlement, and `refreshEntitlement` was only ever called from
`VipViewModel` (lines 355, 542, 700) — i.e. only when the viewer opened a
VIP flow. The launch-time entitlement load (`SyncAccountRepository.kt:126`)
runs once and early-returns when non-null, so the Settings screen kept the
pre-trial "not VIP" reading while the Account card collected the live trial
countdown. The trial grant itself is unchanged.

(d) SEASONS NEWEST-FIRST (fourth item, from the Session 115 findings,
00:19 PKT 2026-11-09). The 115 builder measured that the server cannot fix
season order: the app re-sorts seasons ASC itself
(`V1CatalogMapper.kt:101` `.sorted()`) and never calls v2 work detail, so a
server flip would be dead code. The flip belongs in the app. A second
season sort exists for display — `ReleaseLayoutBuilder.kt:339`
(`bySeason.toSortedMap()`), which is what the Detail screen actually shows
(`state.layout?.seasons`). Both were flipped; nothing else sorts seasons.

## 2. THE FIXES — DONE

(a) `ui/navigation/NavGraph.kt:179` — Region `onContinue` now pops just the
Region screen (`popBackStack()`, no args) when opened from Settings, so the
viewer lands back on Settings with the row visible showing the new region;
on a first install the region screen IS the whole stack (MainActivity sets
`startDestination = Screen.Region.route` when the region is unanswered),
so there is nothing to pop and Home is pushed with Region leaving for good
(the `popUpTo(Region) inclusive` arm, unchanged). `SettingsScreen.kt:178`
— the region row moved out of "Playback & Display" into its own
"Watching region" card directly under "Catalog Server" at the top of
Settings, so it cannot be missed by scrolling.

(b) `ui/navigation/NavGraph.kt` — `launchSingleTop = true` on all six
player/embed navigations: Search direct URL (:235), Downloads `onPlay`
(:266) and `onPlayLocal` (:272), LocalFiles `onPlayLocal` (:284), Detail
`onPlayStream` (:303) and `onOpenProviderPage` Embed (:308). A double-tap
on the same Play can no longer stack two identical players; navigating to
a DIFFERENT stream still pushes a new entry (singleTop dedupes identical
routes only). `ui/screens/PlayerScreen.kt` — `GiveUpCard` gains
`onBackToDetails: () -> Unit` (:1873): `onDismissRequest` is now the exit
(Back and outside-tap leave the player), the dismiss row gains an explicit
"Back to details" button (`R.string.player_back_to_details`, new in
`strings.xml`), and "Close" still means keep waiting for a viewer who
wants to give the slow link more time — it is no longer the only way out.
Both call sites pass `onBackClick` (:487, :500). `dismissGiveUp()` /
`dismissDeadlineGiveUp()` are unchanged and still called by "Close".

(c) `sync/SyncAccountRepository.kt:263` — `startDeviceTrial` calls
`refreshEntitlement(force = true)` after a successful grant, so the
entitlement flow (and every collector — Settings Membership, Detail
gating) learns the trial VIP at once. A failed read keeps the previous
value; the trial grant itself is unchanged. `viewmodel/SettingsViewModel.kt`
— NEW pure `MembershipCardCopy.summary(planIsVip, planVipUntilMillis,
planPaymentPending, trialDays)` (:1349): VIP with date, VIP active,
payment pending (all three wordings preserved exactly), then a trial
branch — "Free VIP days are running on this install — N days left. 1080p
and 4K play until the days end." — then the free-plan fallback when the
trial has ended or was never granted. `ui/screens/SettingsScreen.kt` VIP
card now renders that summary (:241); the dead `planDateLabel` helper and
its three now-unused `java.*` imports were removed. The Account card copy
is unchanged; the two cards can never disagree again.

(d) `network/models/V1CatalogMapper.kt:104` — `.sorted()` →
`.sortedDescending()`: the latest season comes first (S04 before S01).
Episodes inside a season stay `.sortedBy { it.number }` (oldest-first);
the per-season `absoluteNumber = index + 1` is within-season and is
unaffected. `viewmodel/ReleaseLayoutBuilder.kt:388` — the display list is
`numbered.sortedByDescending { it.number }`, applied AFTER the show-wide
absolute numbering recompute (:373-377), so absolute numbers stay
chronological (S01E01 is still absolute 1) while the display is
newest-first. The default selected season
(`DetailViewModel.kt:434`, `layout.seasons.firstOrNull()?.number`) is now
the NEWEST season — the desired landing. `resumePrintFor` looks seasons up
by number, so it is order-independent; `VipQualityGate` maps seasons in
order and is unaffected.

## 3. TESTS — NEW, 7

- `ReleaseLayoutBuilderTest` +1: `seasons come out newest first and
  absolute numbers stay chronological` (S01E01, S01E02, S02E01 →
  seasons [2, 1]; absolute numbers 1, 2, 3; episodes within S01 [1, 2]).
  The pre-existing `series prints group into seasons and episodes` test
  survives unchanged (its S02E01 absoluteNumber == 3 assertion still
  holds under the flip).
- NEW `network/models/V1CatalogMapperSeasonsTest.kt` (1 test): S01E01,
  S01E02, S04E01 → `work.seasons` [4, 1]; episodes within S01 [1, 2].
- NEW `viewmodel/SettingsMembershipTest.kt` (5 tests): VIP with date,
  VIP without date ("VIP — active."), running trial (starts with the
  Account card's own `trialActive(3)` line and names 1080p/4K), pending
  payment keeps its wording even with a trial running, no VIP + no trial
  falls back to "Free plan — playback stays at 720p."
- No new unit tests for (a) navigation or (b) the give-up dialog: both
  are NavGraph / Compose UI with no existing harness for them, and the
  brief forbids inventing one. Their verification is the full gate
  (Android CI) + the parent's device retest. RegionChoices /
  RegionPreferenceTest behaviour is unchanged.

## 4. PRE-COMMIT CHECKS — CLEAN

Full import diff per edited Kotlin file vs base 39bcaf96: only
`SettingsScreen.kt` changes (+`MembershipCardCopy`, −`java.text
.SimpleDateFormat` / `java.util.Date` / `java.util.Locale`, all three
orphaned by the `planDateLabel` removal); every other file's import set
is identical. @Composable counts unchanged in every edited file
(NavGraph 1, SettingsScreen 11, PlayerScreen 46). `/*` vs `*/` counts
unchanged vs base everywhere (PlayerScreen's naive 23/22 is the
pre-existing string-content offset, not a new imbalance). New string
`player_back_to_details` used at the one new button; `strings.xml`
parses. A real compile slip was caught in review: the VIP card first
used `account.trialDays` before `val account = state.account` is
declared (line 302) — fixed to `state.account.trialDays`. `git diff`
reviewed in full before committing.

## 5. WHAT COULD NOT BE VERIFIED ON DEVICE (PARENT'S RETEST)

- (a) Region switch Desi → East Asian → back to Desi, landing on
  Settings with the row visible and the new region shown; first-run
  Region → Continue still lands on Home (no Settings in that stack).
- (b) Failed play → Back exits to the detail page (both the 30 s
  give-up card and the service give-up card); outside-tap on the card
  exits too; "Close" still keeps waiting; double-tap on Play stacks
  only one player; "Try another print" still walks to the next print.
- (c) Fresh install: Membership card shows the trial line with days
  left during the 3 free days, Account card agrees; after the trial
  lapses it falls back to "Free plan — playback stays at 720p"; the
  1080p refusal for a NON-trial user is still unobservable on a fresh
  install (debug builds grant 3 free VIP days per install).
- (d) A series with 2+ seasons opens on the newest season first,
  episodes within it oldest-first; absolute numbering / resume still
  chronological.
- CI (Android) is the compile + unit-test verdict for all of the above;
  no local Gradle run exists for this session by owner order.
