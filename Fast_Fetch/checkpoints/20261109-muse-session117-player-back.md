# Session 117 — player system-Back + wrong duration (114 retest fixes)

Retest of APK 280 (Session 114) on a real Pixel 5, Sauce Labs, 01:20 PKT
2026-11-09: region switch-back PASS, VIP wording PASS, stuck-player exit
FAIL, newest-season FAIL (untestable — see below). This session fixes the
two real defects the retest exposed, both verified in code first.

## 1. System Back never left the player

Retest: phone Back (gesture swipe) pressed once while the give-up card was
up and three times during playback — the player never exited. The top-left
arrow DOES exit (verified). Cause, verified in code: the only `BackHandler`
in the whole app lived in `EmbedWebViewScreen.kt`; `PlayerScreen.kt` had
none, so during playback no handler of its own existed. Session 114 had
added the on-screen "Back to details" button only.

Fix (`PlayerScreen.kt`): one `BackHandler { onBackClick() }` in
`PlayerScreenContent`, so it covers both entry points (stream handle and
local file). It is registered first, so a dialog or sheet that is showing
wins the press — its handler was added later and both end in the same place
(back to details). The lock does not gate it: a locked player must still
let its viewer out. `launchSingleTop` untouched.

Reversal, recorded deliberately: Session 114's log says a root
`BackHandler` in PlayerScreen was "deliberately left out (default
NavController pop is correct once the card and the stacking are fixed)".
The 01:20 PKT retest proves that wrong on a real device — a delivered
back event exited nothing, card up or playing. This session adds the
handler 114 declined, on that evidence.

Outside-tap, verified NOT broken: `GiveUpCard` already wires
`AlertDialog(onDismissRequest = onBackToDetails)` with default dialog
properties (`dismissOnClickOutside = true`), so a tap outside the card
leaves the player. The retest could not exercise it (playback started on
its own); no code change, pinned by test instead.

Why one swipe can still look dead: the player hides the system bars with
`BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE`, so in immersive fullscreen the
first edge swipe is the OS revealing the bars, not a back event. Standard
Android behaviour, not changed; a delivered back event now always exits.

## 2. Every clock at one minute or more was wrong

Retest: the player showed total duration **127:07:51** for the Ali Baba
file. Root cause, one line in `PlayerViewModel.formatTime()` (used by the
position/duration, scrub toast, sleep timer, chapters, A-B points, local
files — every time the app prints): `val hours = totalSeconds / 60`
divided by 60, not 3600. 7,671 s / 60 = 127 "hours", minutes
(7,671 / 60) % 60 = 7, seconds 51. Fixed to `/ 3600`. A 90-second
position used to print "1:01:30"; it now prints "1:30".

## Tests (new, 12)

- `FormatTimeTest` (8): 0 → "0:00", 45 s → "0:45", 90 s → "1:30",
  59:59 stays in minutes, 1:00:00, 1:01:01, the retest value 7,671,000 ms
  → "2:07:51", 24:00:00.
- `PlayerBackExitTest` (4, source-drift pattern): the `BackHandler`
  import exists; `BackHandler { onBackClick() }` sits inside
  `PlayerScreenContent`; the give-up card keeps
  `onDismissRequest = onBackToDetails`; exactly two `BackHandler`
  mentions in the file (import + the one call).

No local Gradle run by owner order — CI judges.

## Seasons: no code change, retest targets found

The retest could not find a 2+ season title by browsing (the catalog
lists each season as a separate post). Multi-season works DO exist, so
the retest can target one directly: Family Guy work 73762 (24 seasons),
One Piece 59950 (23), American Dad 72649 (22), Pokemon 74557 (20).
The 114 mapper tests already pin the ordering; the device check is the
parent's step.

## Pre-push checks

- Import diff base→HEAD per edited file: PlayerScreen +1
  (`androidx.activity.compose.BackHandler`, used at line 282);
  PlayerViewModel unchanged. No dropped imports.
- `@Composable` counts unchanged (PlayerScreen 46/46).
- `/*` vs `*/` balance unchanged in both edited files (PlayerScreen
  23/22 before and after — the gap is pre-existing string literals
  `"*/*"` and `"video/*"`, not a comment).
- No new network data class (rule 7 needs nothing). No brand change.
- No push/deploy/tag from this session (parent's step).
