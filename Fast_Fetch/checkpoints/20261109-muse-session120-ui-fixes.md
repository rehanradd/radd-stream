# Session 120 — UI fixes from the Session 117 device retest (TestingBot video)

Date: 2026-11-09 ~04:0x–04:30 PKT. Base: session117-player-back @ fe725d8.
Branch: session120-ui-fixes. App only; no backend change, no push (parent verifies
and pushes), no local Gradle run by owner order — CI (ci.yml on push) judges.

## What the retest showed (TestingBot, real Galaxy S24, APK 282, video 6m50s)

1. Give-up card: "Open with another player" wrapped onto FOUR lines ("Open /
   with / anothe / r") and "Close" printed OVER its final "r" — two buttons
   colliding, partly unreadable.
2. Player waited 30 s and never started: "Starting playback…" / "Taking longer
   than usual — your link is being found" / clock 0:00, total --:--, chip
   "Keeping 0 B of 3.05 GB". Then a second card: "Nothing playable here right
   now / ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT / Every option for this print
   failed." — its buttons laid out cleanly in two rows.
3. Search: first section headed "Series — 4" over poster cards reading
   "2026 · Movie". Open keyboard covered the top results row; the empty-state
   hint hid behind the keyboard's clipboard bar.
4. Details (Ali Baba [Tamil]): Play greyed out, "No playable copy for this
   title yet — downloads are available", plus a "Go VIP" upsell card.
5. First run: ~55 s black screen first session, ~20 s later ones.

## Fixes

1. GiveUpCard buttons stack vertically (PlayerScreen.kt): AlertDialog lays its
   two button slots side by side in one row, so five actions
   (Retry / Try another print / Open with another player / Back to details /
   Close) overflowed a 360 dp phone. All five now sit in one full-width
   Column in the confirm slot; the dismiss slot is empty. The second card
   looked clean only because it offered four buttons (no "Try another print")
   — the handoff card now offers it too when `canTryAnotherPrint`, since the
   deadline card already did and the viewer could otherwise only retry the
   same dead ladder.
2. Search grouping collapse (SearchViewModel.kt) — the real root cause of the
   "Series — 4" header over film cards: `groupBy { typeGroupKey(it) }
   .toSortedMap(typeComparator)` is a TreeMap, and a TreeMap treats two keys
   as the SAME key when the comparator returns 0. `typeOrder` only matched the
   plural labels ("Movies"), never the raw wire keys it was handed ("movie"),
   so every key compared equal: the map kept the FIRST key and the LAST value
   — a "Series" header, the Movies count, film cards. Grouping is now an
   extracted, tested `groupSearchResults()` that builds the list and sorts it
   by `typeOrder(label)`; every rail survives, in Movies/Series/Seasons/Anime
   order. Label agreement, same fix: `normalizeTypeLabel` now maps
   documentary/sport_event/music_video/tv_special/miniseries instead of
   "Other", and `WorkTypeLabel.of` paints "Season" (not "Complete_season")
   and proper words for the rest, so a header always names the cards under
   it. Pinned test updated (AnimeWireTest: "Complete_season" was deliberate
   during the anime work; the user now reports the mismatch as a bug).
3. Keep chip text (CacheAffordance.kt): "Keeping 0 B of 3.05 GB" read as "the
   player downloads the whole file before it plays". It does not — verified in
   code: `PlaybackMediaItemFactory.build` hands ExoPlayer the redirector URL
   at once (streaming-first, no cache gate) and `seedPreviewFor` runs a
   bounded ~40 MiB ahead-window in parallel; the chip now reads "Saving a copy
   in the background" (+ live rate when > 0) and never quotes the full size.
   The timeout itself is the SOURCE host: ExoPlayer's
   `ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT` after our redirector 302'd
   there. Auto-failover DOES run on it — retry same once, silent hop to a
   backup copy of the rung, next rank, max 3 ranks (`PlaybackFailurePolicy`
   retrySame=1, maxRanks=3) — and the NO_CANDIDATE card means that ladder was
   exhausted; `tryNextPrint()` genuinely moves to a different print (verified:
   stages the next handle + backups, starts it). The Ali Baba film's named
   print is dead server-side (Session 113), so no app change can play it.
4. Black first run (MainActivity.kt + themes): no single app-side blocker in
   code — the start-destination resolution is local DataStore reads, and the
   2x15 s default probe is skipped on a fresh install (no saved URL) — the
   ~55 s is dominated by cold install/start on the cloud device. What the code
   DID show: the launch window was flat near-black ink with no branding and
   the first frame was a bare spinner. New `launch_background` drawable (ink +
   centred logo mark on API 23+, flat ink on 21-22 where a layer-list item
   cannot carry gravity) as `windowBackground` in all three theme files, and
   the waiting state is now a branded column (mark + name + spinner +
   "Loading…", new `app_loading` string).
5. Keyboard (SearchScreen.kt): `.imePadding()` on the content column (pattern
   already used in SetupScreen) so results scroll above the keyboard.
6. Item 5 data check — greyed-out Play is CORRECT, no mapping bug: post
   150799 (Ali Baba [Tamil] series) has 13 releases, all 13 tiers
   `download_only`, `playable: false`, link status `expired`. The "Go VIP"
   card is the designed first-party sponsor slot for non-ad-free viewers.

## Tests (new/changed, CI judges — no local Gradle run)

- SearchGroupingTest (4): mixed movie+series keeps both rails with correct
  headers/counts (the regression case: series first, movies last); every card
  paints its header word; rail order Movies/Series/Seasons/Anime; typeless
  row lands in Other.
- KeepChipTextTest (3): Keeping text, rate suffix, Watching/Stored unchanged.
- PlayerBackExitTest (+3 source pins): actions in a full-width Column, no
  "Row {" in GiveUpCard, handoff card offers onTryAnother.
- AnimeWireTest: season labels "Season" (was "Complete_season").

## Pre-push checks (read, not built)

Import diff per edited file: MainActivity +9 used (Image, Arrangement, Column,
padding, size, Text, painterResource, stringResource, dp; Box removed, unused),
SearchScreen +1 imePadding, used. @Composable counts unchanged (PlayerScreen
46/46, SearchScreen 7/7). Comment balance unchanged vs base (PlayerScreen's
naive 23/22 is the pre-existing string-content offset). New drawables parse as
XML. `ReleaseLayoutBuilder.toSortedMap()` checked: natural Int ordering, no
collapse — not the same bug.

## Not verified without a device

Card layout on a real 360 dp phone; branded launch on first install; search
rails with a live mixed query; chip text during a real start. Retest targets:
Ali Baba film (dead print — expect the same timeout, but with clean buttons),
any mixed-type search, fresh install cold start. Session 121 (full-video UI
audit) runs separately; its findings land after this session.
