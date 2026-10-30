# Spec App Robolectric Arm64

> Moved **verbatim** out of `App/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `App/AGENTS.md`
> carried at this sha. Law stayed in `App/AGENTS.md`; this is the reference prose it now links to.
### from `App/AGENTS.md` lines 54-82

> **Nine tests never run HERE, and they do run on the hosted runner — GREEN as of 2026-10-30; the
> "red" in this heading is retired in the correction below (measured 2026-10-29 from the
> run-`40771307140` log, re-measured against the workflow API on 2026-10-30).** The `tasks.withType<Test>()` arm64 block in
> `app/build.gradle.kts` excludes `PosterCardProvenanceTest` (3 `@Test`s) and
> `ScreenSnapshotTest` (6 `@Test`s) whenever `os.arch` is `aarch64`/`arm64`, because Robolectric has
> no native runtime for ARM (robolectric/robolectric#9166) and it dies during `@Rule` evaluation, so
> an in-test `Assume` cannot catch it. An earlier version of this note called that "nine tests
> execute nowhere"; **that was false** — GitHub Actions is enabled (permissions `enabled`,
> `allowed_actions: all`, 42 runs, `ci.yml` 14 runs) and its x86_64 runner does execute both
> classes. What it executed was 9 failures inside Android's "636 tests completed, 9 failed": 6
> `androidx.compose.ui.test.ComposeTimeoutException` at `ScreenSnapshotTest.kt:75` and 3
> `AssertionError` at `PosterCardProvenanceTest.kt:40/50/56`. The arithmetic settles it: the hosted
> run completed **636** tests, which is exactly this box's **627** plus the **9** excluded here, so
> every one of those 627 was genuinely executed locally and the 9 were never attempted here at all.
> ⚠️ **SUPERSEDED 2026-10-30.** That sentence read "…is therefore **627 executed + 9 executed and
> FAILING on CI**". **Re-measured 2026-10-30 01:2x host time by the qoder3 lane**, token read from `os.environ` inside a `python3 -S` heredoc (never in argv, never in a URL), against `/repos/rehanradd/radd-stream/actions/workflows/<id>/runs?per_page=10`; the API prints UTC. Workflow ids: backend `398476976` (93 runs), Android `398476977` (28 runs), Release `398476978`. Backend `398476976` is `completed success` on **both** `master` and `main` at `87b7b6f` (19:42:59Z / 19:43:00Z) and at `1aafddb`. Android `398476977` is `completed success` on `main` and `master` at `9859b8a` (17:00Z), and every app-lane run after it is green: `217e8cd` (17:21:50Z) — the retry that retired the only recent failure, `99472e0` at 17:08:19Z — then `bc2e534`, `e6482e9`, `a3c34ff`, `bd45ba0`, `9a590bb`, and the newest run of any branch, `5e74aa2` on `q1-identity-fix` at 19:22:09Z. **There is no red app lane.** The correct reading of a green "627 / 0" gate on this box today
> is **627 executed here + 9 executed and PASSING on the hosted runner**. What stays true, and is
> the reason this note exists at all: the nine are excluded locally because Robolectric ships no ARM
> runtime (robolectric/robolectric#9166 — it dies during `@Rule` evaluation, so an in-test `Assume`
> cannot help), they are invisible to any number printed on this host, and only the hosted x86_64
> runner can judge them. The exclusion stays. Everything else in this block, including the
> `doFirst { logger.lifecycle(...) }` note and the 636 = 627 + 9 arithmetic, still reads as written:
> line in that block now names **both** suites, because it used to print only "Skipping
> PosterCardProvenanceTest" and silently dropped `ScreenSnapshotTest` from
> every local run. Anyone reading a gate number on this host should read it as *excluding* both
> suites; the exclusion itself stays, because an un-excludable Robolectric crash is worse. Both
> hosted signatures are real behaviour on x86_64, not arm64 artifacts: `captureToImage()` cannot
> complete under Robolectric at all, and the tile assertions were geometry failures against
> Robolectric's default 320dp window.
