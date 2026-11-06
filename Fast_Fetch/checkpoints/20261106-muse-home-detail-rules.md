# 2026-11-06 — Muse [MUSE-HOME-DETAIL-RULES]: Home + Detail research rules

**Agent:** Muse (BoNzoO), coded directly. Same branch as Sessions 40–62
(`muse/app-panel-connection-20261106`).

## What it is

The UX master plan's Home and Detail rules, built — the two screens research
judged most broken after first run.

**Home.** Continue Watching first and pinned, at most 10 rows total. The cap
is a pure function, `visibleHomeRows(sections, hasContinueWatching)`, so with
a saved title on screen the page carries nine content rails, never sixteen.
An offline banner ("You are offline — only titles saved on this device are
available") shows only when something saved is actually on screen — the
network rails are not cached, so the banner never claims saved titles over
rows that came from the server. A successful empty load is no longer a blank
page: "Nothing here yet — check your server in Settings", with a button to
Setup. `ConnectivityProbe.current()` is read once per `loadAll` into
`HomeUiState.isOffline`.

**Detail.** A Resume button that names the episode and what is left
("Resume S1:E3 · 23 min left"), from the newest resumable watch-history row
for the work (`findWork` on the DAO; a finished row is not a resume). The
button only shows when the v2 layout actually has a print for that episode
(`resumePrintFor`) — otherwise plain Play, so the button never promises a
tap that goes nowhere. Runtime and season count in the header (runtime rides
the v1 detail from the `cat_works` row, see below; season count needs no
server change — the app already has the seasons). Progress marks on episode
rows: a bar plus the remaining label, or "Watched" when it ran to the end; a
row never watched shows nothing, no bar, no guess. An included line states
what the plan covers ("Included in free — up to 720p"; at 480p cap, "480p
included — 720p, 1080p and 4K need VIP"). The "Open" button is renamed
"Opens the provider's page" — one word hid that the tap leaves the app's
player for the provider's page, with its player and its ads.

## Server

`api_v1_get_post_detail` now carries `runtime_minutes` from the `cat_works`
row, looked up by the same `catalog_v2.work_key_for` derivation the detail
route already mints for the work ref (`imdb:` / `tmdb:` / `family:title:year`).
The whole block is guarded: a title with no work row simply sends no key,
and the app shows nothing. Two tests in `test_database.py` — one pins the
absence, one pins 142 minutes from a planted work row. **test_database.py:
135 OK (skipped=1). test_panel_feed.py: 29 OK. test_contact_intake.py: 8 OK.**

## App

- `PostDetail.runtimeMinutes: Int?` (nullable — a missing key decodes to
  null; decode test in `ModelsTest`).
- `HomeViewModel` gains the `connectivityProbe` constructor argument and
  `isOffline` state; no test constructs the ViewModel directly.
- `DetailViewModel` gains `resume`, `resumePlayable`, `episodeProgress`,
  `includedLine` state + `loadResume()` / `playResume()` + pure top-level
  helpers `resumePointFor`, `episodeProgressFor`, `resumePrintFor`,
  `formatRuntimeMinutes` (tested in `DetailResumeTest`, 6 cases).
- `visibleHomeRows` tested in `HomeRowsTest` (4 cases).
- No new strings.xml entries — every label is a Kotlin literal in the
  screens, and the player-string guards do not scan those files.

## Also in this push

The panel-keys CI failure, fixed: Android run 42149015453 failed at
`kaptGenerateStubsDebugUnitTestKotlin` — the Session 61 edit that inserted
the 480p-cap test deleted the `@Test` + `fun` header of the next test (`a
free viewer gets the free rungs and a fresh auto pointer`), leaving its body
floating at class level and one brace too many at the end of the file.
Restored exactly those two header lines (verified against the parent
commit; braces 17/17, 9 @Test functions). Backend run 42149015415 on the
same sha was SUCCESS.

## Not done

Push (this commit, then CI judges — the panel-keys runs are finished, so
nothing is in flight). The panel workspace files (tabs, Live page,
broadcasts target_detail, disclaimer tuning keys, tuning_consumers labels)
still await the gate. Next: Settings/Downloads/Search/My List research
rules. Device checks owner-only.
