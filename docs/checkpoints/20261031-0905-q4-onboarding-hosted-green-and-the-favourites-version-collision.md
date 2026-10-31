# 2026-10-31 ~09:05 host time — q4 App lane: onboarding went hosted-green, and the favourites rescue is provably not self-contained

**Lane:** qoder4 (account4), App. **Branches:** `q4-onboard-trial-ui` @ `03e926b`,
`q4-player-guard-followup` @ `93a6547`, `q4-fav-recheck-rescue` @ `583fd54` (q1's preservation push,
audited here, not authored here). **No Gradle ran on this box at any point in this session.**

## What is now measured, with the run id beside it

| Branch | sha | Hosted run | State, read from the API |
|---|---|---|---|
| `q4-onboard-trial-ui` | `ab8d4d5` | `41157483215` | failure — `:app:compileDebugUnitTestKotlin`, 7 errors, all in `DeviceTrialTest.kt` |
| | `cfd6de3` | `41159934843` | failure — compiled, 766 tests ran, **1** failed: `tooling/CommentBalanceTest` |
| | **`03e926b`** | **`41160533249`** | **success** — all 10 steps, `BUILD SUCCESSFUL in 3m 33s`, `assembleDebug` + `testDebugUnitTest` + `lintDebug` executed |
| `q4-player-guard-followup` | `93a6547` | `41158986663` | success — the instant-start/load-control guard is green against the real owners |
| `q4-fav-recheck-rescue` | `583fd54` | `41157938495` | failure — `:app:compileDebugKotlin`, 35 errors in `FavoritePost`, `FavoritesRepository`, `MyListScreen` |

The three-day silent trial, the countdown card, the phone+PIN link modal and the copy law are
therefore gate-passing code. Still unwitnessed: every one of them on hardware, and `DeviceIdentity`
in particular. The trial badge lives only in the Settings account card, not in `HomeScreen` or
`VipUpgradeScreen`.

## The rescue is mid-flight, and the reason is a Room version collision

`583fd54` is trunk `4a8c163` plus 260 additive lines. Four things it references are not on its own
parent: `AdultPolicy` and `UnavailableWork` (both live only on `origin/q1-rescue-untracked` @
`1c83e1c`, whose parent does not contain trunk), `Post.is18Plus` / `PostDetail.is18Plus`, and
`MyListUiState.hiddenCount` / `hiddenNotice` (both only in `/tmp/q1_rescue_app_20261031/`).

The one that would have cost a user data, found by reading and by nothing else: **both lines own
version 7.** Trunk's `MIGRATION_6_7` creates `ad_cadence` and its entities list ends at
`AdCadenceEntity`; the live tree's uncommitted `MIGRATION_6_7` instead adds `is18Plus`, `checkedAt`
and `unavailable_works` and has no `AdCadenceEntity`. `/opt/radd-stream` HEAD `bf9e565` and trunk
`4a8c163` are not ancestors of each other, measured in both directions. Landing the rescue as
written means a device that already ran 6→7 never re-runs that step, `favorite_posts` stays without
the two columns, Room's schema check fails on open — and `DatabaseModule.kt:43` registers
`fallbackToDestructiveMigration()`, so the failure is not a crash, it is the viewer's saved list
deleted. That is the exact second bug the feature exists to prevent.

Correct landing, recorded so the next lane does not rediscover it: keep `MIGRATION_6_7` = ad_cadence
untouched, add `MIGRATION_7_8` with the three statements, set `version = 8`, register it, add
`UnavailableWorkEntity` beside `AdCadenceEntity`, and **retarget** the two new
`FavoritesSchemaGuardTest` cases — they currently assert `object : Migration(6, 7)` contains the
`ADD COLUMN`s, which both fails against trunk and forbids the fix. The suite's existing contiguity
case then forces `version = 8`, so the numbering cannot silently drift again.

Two smaller truths about that feature: `FavoriteDao.favoriteIds()` has no caller in the rescue, in
the snapshot, or in the live tree; and revalidation is screen-driven (`MyListViewModel.kt:48` on
opening My List, `PlayerViewModel.kt:1113` on a stream refusal) — nothing schedules a pass.

## Open, and needing someone else's decision

1. `/tmp/q1_rescue_app_20261031/` holds 41 `.kt` files and nine of them reference `AdultPolicy`.
   That content is on no remote, `/tmp` is not a backup, and the live tree is the only other copy.
   Offered as a labelled WIP branch push; awaiting q1's word, so it is not pushed unilaterally.
2. `CommentBalanceTest`'s scanner treats a `'` as a char-literal start, so any backticked test name
   containing an apostrophe is reported as an unbalanced file even though the compiler accepts it.
   Four of mine hit it and were reworded; the hole itself belongs to that suite's owner, and its own
   positive controls would not distinguish a fix from a regression.
3. The favourites-union build is staged, not started: one hosted run ≈ 7 m wall, zero load here, and
   no local `gradlew` until q1 posts load under 4 and then under 0.5 for builds specifically.

## Rules kept

No `./gradlew`, no local test module, no build, no crawl, no merge, no service restart, no nginx
change, no tag, no release, no keystore work. `/opt/radd-stream` used as nothing but a read target.
Staged paths by name, never `git add -A`, never force-push, branch pushes only to my own refs via
the askpass flow against the explicit clean URL. No device id, phone number or PIN in any log,
fixture, command argument or commit message.
