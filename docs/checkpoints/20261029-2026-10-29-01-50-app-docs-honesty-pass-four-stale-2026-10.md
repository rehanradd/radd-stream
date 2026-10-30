# 2026-10-29 01:50 — App docs honesty pass: four stale 2026-10-22 claims corrected, no build run

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 01:50 — App docs honesty pass: four stale 2026-10-22 claims corrected, no build run

**Scope:** documentation only. No `.kt`, `.kts`, `.xml`, resource or `.py` file was touched, and
**zero Gradle invocations** — load sat at 2.5–4.9 with crawlers running, and the owner's hold
("no Gradle until I confirm under 0.5") stands. Gradle cannot see a `.md` diff, so the App gate is
unchanged: **627 tests / 0 failures / 0 skipped** at `b7bc479` (build28), of which **9 tests are
excluded on aarch64** — see the limitation below.

**Re-measured read-only (no DB file opened — `merged_catalog_20261025.db` and `fast_fetch.db` were
not touched):** `GET /api/v1/posts?type=anime&limit=1` on `127.0.0.1:8080` → `200 in 0.24 s`,
`total: 5847`, row carries `is_animated: 1`; plain `?limit=1` → `total: 130795`; and **`subtitled` is
absent from both live rows**, re-confirming that the deployed service still has not been restarted,
so the next deploy's release note owes that chip.

**Four defects, each re-verified against `App/app/src` before being rewritten:**
1. `App/README.md` + `App/design/SCREENS.md` claimed the Anime chip returns zero results, that there
   is no hero banner and no per-type rows. False: `HomeScreen.kt:237`, `SearchScreen.kt:73-79`,
   `viewer.py:2530` (live `5847`), and `HeroCarousel` composed at `HomeScreen.kt:126` with
   `MediaRail` sections at `:142`.
2. `App/docs/PLAN.md` marked Continue Watching, Downloads, auto-advance/resume/subtitles/quality
   switching and deep links + share as not implemented. All are: `WatchHistory.kt:20` +
   `AppDatabase.kt:111-122` + `HomeViewModel.kt:132`; `DownloadsScreen.kt` + `NavGraph.kt:203` +
   `DownloadService.kt:55`; `PlaybackService.kt:516-534`/`:176`→`:473`/`:93-109`/`:178`,`:375`;
   `NavGraph.kt:168,223` and `DetailScreen.kt:216`→`shareTitle` at `:1037`.
   **The one real gap, now stated as the gap:** `AndroidManifest.xml:59-65` advertises
   `<scheme>://stream/12345`, but `NavGraph.kt` registers `navDeepLink` only for `browse/{type}` and
   `detail/{postId}` — no Player pattern, and `brand.properties:178-181` has no `stream` host — so
   that URI cold-starts to the normal destination. `shareTitle` sends `copy.share_template`
   (`brand.properties:167`, a title sentence) with **no URI**, so the share is not a deep link
   either. Both stay un-advertised until a `player/{handle}` route exists; the Player argument is an
   opaque handle, never a URL.
3. `App/docs/PLAYER_SPEC.md` cited `player/ui/GestureLayer.kt` and "decomposed in `player/ui/`" at
   `:36` and `:55` — that package does not exist (the code is `player/PlayerGestures.kt` +
   `ui/screens/PlayerScreen.kt`). It also invented component names: `PlayerTopBar`/`BottomBar`/
   `SeekRipple` are really `TopBar`/`BottomControls`/`DoubleTapRipple`. §5's "no Android SDK in this
   workspace / nothing was compiled or run" is false — `local.properties` →
   `sdk.dir=/home/ubuntu/android-sdk` and `app/build/outputs/apk/debug/app-debug.apk` (22,738,552 B,
   2026-10-27) was built on this box; the real limit is that nothing has run on a **device**.
4. Root `AGENTS.md` repo map: "wireframes for all 7 screens" → "7 screens (NavGraph registers 13
   routes)", counted at `NavGraph.kt:123-281`.

**Two things that moved after the first commit, both caught by re-measuring rather than by reading:**

- **Citation drift is real and it is everyone's problem.** `Fast_Fetch/viewer.py` grew from the
  3,447 lines §5 was measured against to **3,539** during this shift's ingest work, so the
  `viewer.py:NNNN` cites copied out of it stopped landing. Every one this session wrote or could
  verify was re-grepped to where the code actually is now — anime predicate `:2530`, the same
  predicate as an `industry` facet `:2555`, `subtitled` appended at `:2636` by `_subtitled_posts()`
  at `:2466`, `_bucket_for()` `:2957`, `send_json()` `:2939`, `start_server()` `:3491`,
  `api_v1_get_posts()` `:2507`, the list `SELECT` `:2612-2617`, the adult `WHERE` `:2515`, releases
  `id ASC` `:2696`, the source tier `CASE` `:2702-2712`, the stats answer `:2902-2909` behind
  `_STATS_CACHE` `:2831`. A resolver that indexes by basename and reports any citation landing on a
  blank line or past EOF now runs clean over the whole diff — **48 citations checked, including the
  continuation cites like `:2555` and `:2628/:2636`, 0 unresolved.** Two things it taught, both
  recorded rather than "fixed": (a) `app/build.gradle.kts:220-233` is a *correct* citation that a
  naive basename index sends to the 9-line `App/build.gradle.kts` instead of the 357-line
  `App/app/build.gradle.kts`, so a scan that resolves by filename alone invents defects — resolve by
  path and fall back to a unique-basename walk; (b) the only cites still pointing at retired line
  numbers sit in **dated session logs** — Session 6's "verified against code" list
  (`viewer.py:1898/:1905-1909/:1942/:2037/:2211`) and the v2-mount note (`:2464` GET, `:2700` POST) —
  and they stay as written, because a log records what was true when it was measured. They are named
  by content rather than by line number on purpose: appending a log entry shifts every later line in
  this guide, and they moved +9 while this section was being written. The rule: **a
  `viewer.py:NNNN` citation is a date-stamped claim — re-grep before repeating one.**
- **`/api/v1/stats` and `/api/v1/posts` no longer even agree on which one is bigger.** Measured
  today on both `92.4.95.252` and loopback: `stats.posts 116922` against
  `/api/v1/posts?limit=1 → total 131559`. They are two snapshots of two tables — the endpoint
  prefers the projection's stamped tally (`cat_projection_meta`, `viewer.py:2854-2869`) while the
  list route counts the live `posts` table (`:2605`, adult-scoped), and this shift's merges grew
  one without rebuilding the other. Yesterday the adult-flagged projection made the stored figure
  the *larger* one. So `App/README.md`'s stats note and `App/AGENTS.md` §5's warning now say
  "different populations, no arrow", not "stats overstates". **The consequence is a shipped-code
  defect, recorded and not fixed under the hold:** `CatalogScale.connectionNotice` and `SCOPE_NOTE`
  still assert the smaller-than direction in main code. Proposed line — *"This server stores $posts
  works — its own total, not the count you can browse here"* — plus a `StatsHonestyTest` case that
  refuses a directional claim, because the current guard bans the words "Title" and "Stream" and
  went green on a sentence that is now measurably backwards. `connectionNotice(0)` has the same
  disease in miniature: it promises a catalog smaller than zero.

**Also corrected this pass, in place:** `App/README.md:34-39` claimed the backend has "no
authentication, no API keys, no sessions, and no rate limiting", answers
`Access-Control-Allow-Origin: *` and "binds `0.0.0.0` by default" — all four false against the
lines above, and the file contradicted itself because its §Backend API already carried the
measured state. It now names the bearer-only account routes, the token bucket, the empty CORS
allow-list and the loopback bind, and keeps the part that is still true: no TLS, catalog reads
public, nothing behind them private.

**Known limitation, recorded not fixed:** `PosterCardProvenanceTest` (3 `@Test`s) and
`ScreenSnapshotTest` (6) are excluded at `App/app/build.gradle.kts:220-233` whenever `os.arch` is
aarch64/arm64 — Robolectric ships no native runtime for ARM and dies during `@Rule` evaluation, so an
in-test `Assume` cannot help — and ⚠️ **the clause that followed this one is false as of
2026-10-30.** It read "and GitHub Actions is disabled at the account level, so **those 9
tests currently execute nowhere**. Report a local green as *618 executed + 9 excluded*."
Actions is enabled — `/actions/permissions` returns `enabled: true`, `allowed_actions: all`
(measured 2026-10-29, and the workflow-API reads below are from my own run tonight) — and the
hosted x86_64 runner does execute both classes. Re-measured 2026-10-30 by the qoder3 lane from
`/actions/workflows/398476977/runs` (token read from `os.environ`, never in argv or a URL):
Android is `completed success` on `main` and `master` at `9859b8a` and on every app branch
after it, newest `5e74aa2` at 19:22:09Z. Those 9 tests execute on the hosted runner and
**pass**, so report a local green as *627 executed here + 9 executed and passing on CI*, not
*618 + 9 excluded*. The exclusion itself stays: it is forced by Robolectric #9166, not by CI
being unavailable. The
`doFirst { logger.lifecycle(...) }` line at `:227` names only `PosterCardProvenanceTest`, so
`ScreenSnapshotTest` is dropped from every local run **silently**; the honest fix is one extra
sentence in that log line, which is a build-file edit and therefore waits for the hold to lift.

**Still stale and deliberately untouched (flagged, not half-fixed from memory):** root
`AGENTS.md`'s "BUILD_PLAN.md ← no local Android Studio needed" map line and `README.md:170-171`'s
"no rate limiting; `send_json()` sets `Access-Control-Allow-Origin: *` (viewer.py:2037) and
`start_server()` binds `0.0.0.0` (viewer.py:2211)" — that one is the *root* README, and both
numbers point at a file that has since moved. `App/AGENTS.md` §5/§1a carry the measured text to
fold them into; a docs agent should cite those sections rather than re-auditing `viewer.py` from
recall. (`App/README.md`'s copy of the same claim is now fixed, above.)

**Two idle JVM daemons on this host, so nobody blames the crawls for load:** a Gradle daemon
(`pid 756708`, `-Xmx1536m`) and a Kotlin compile daemon (`pid 761442`, `-Xmx1536m`, autoshutdown
7200 s) have been resident since the last builds and idly hold ~2–3 % CPU each on a 1-core box —
roughly 0.05 of load, i.e. they are **not** what pushes load to 4–6. They are also the reason a
first build after an idle stretch costs ~12 minutes (build28: `BUILD SUCCESSFUL in 12m 10s`, cold
daemon) instead of ~2. No daemon was started or stopped this session; stopping another agent's
daemon is a build-system action, not a docs fix.

**Git:** staged hunk-precisely (`git apply --cached` of a single-hunk patch for root `AGENTS.md`),
because that file and `docs/SESSION_CHECKPOINT.md` carry other agents' uncommitted work. No push,
no `Fast_Fetch/*` path staged, no credential printed.

