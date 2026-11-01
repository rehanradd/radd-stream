# qoder1 gating lane — the two gate previews judged: the q4 pair runs green together, and the q2→q5 merge is green under CI's own module list

**Token:** Q1-GATEPREVIEW-20261101 · **Trunk during this pass:** `c2528e1` on both `refs/heads/main` and
`refs/heads/master`, unchanged · **Host:** 1 vCPU; 1-min load ranged 0.35 → 5.24 across the pass,
`MemAvailable` 3,694 MB at the run start and 2,256 MB at the peak.
**Nothing was pushed, tagged, merged into trunk, deployed, or written to a production database by this
pass**, and no credential was read, printed, retried, or tested — the write credential is dead and its
restoration is an owner action. Both preview heads stay local: `git ls-remote --heads origin
'q1-gate-preview*'` returns **0 refs**.

## What was asked, and what the answer turned out to be

Muse's 12:03 order was to run the q4 **union** suite locally in a measured window ("watchdog floor
1700 M, stop if load nears 4, report the verdict only"), after two preview passes had already established
the git-level facts. The verdicts:

1. **`057d344` — the q4 pair, `:app:compileDebugKotlin :app:testDebugUnitTest` → PASS.** `BUILD SUCCESSFUL
   in 6m 7s`; **795 tests / 94 suites / 0 failures / 0 errors / 0 skipped**; all 94 result XMLs written
   inside the single second 12:10:51–12:10:52, every one newer than the run's start stamp, so none is a
   stale report. This is the first evidence that `718a8ef` (admin-control) and `ede66f4` (update-integrity)
   compile **and run** as one tree — previously each had only ever been judged at its own SHA, where hosted
   CI reported `success` for both but for different trees.
2. **`a9cab3a` — q5 @ `c0e86e5` onto the post-q2 trunk `f294bee`: PASS under backend CI's own module
   list.** Offline sweep, one module per invocation (this runner ignores extra names), **45/45 modules
   `rc=0` / `OK`, 0 failures**, 12:16:59 → 12:23:53 (6m 54s wall). Slowest: `test_catalog_api.py` 63 s,
   `test_operator_isolation.py` 47 s, `test_database.py` / `test_catalog_v2.py` 26 s. The list is the one
   read out of this tree's `.github/workflows/backend-ci.yml`, so the merged gate list is 41 (trunk) + 1
   (q2 `test_public_edge_scenarios`) + 3 (q5 `test_clip_bytes_guard`, `test_fts5_capability`,
   `test_handle_provenance`) = **45**, and the sweep proves no module was lost in the merge.

## The two corrections this pass forced, both mine

* **I nearly reported the union run as aborted, and it was not.** My load watchdog printed
  `LOAD_GUARD_TRIPPED load1=3.93 ceiling=3.8` but **failed to kill anything**: its
  `pkill -TERM -P "$ME"` cannot reach the Gradle client because that process's parent is `timeout`, not the
  script, and the daemon-matching pattern does not match the daemon's own command line. Reading the guard
  file as a stop, I killed the wrapper shell by hand while load was 5.24. The orphaned `timeout` +
  `gradlew` kept running and **finished successfully** — which is why the log has no `GRADLE_EXIT=` marker
  (the marker printer died, the build did not). The verdict therefore rests on the `BUILD SUCCESSFUL` line
  plus 94 fresh zero-failure XMLs, which is stronger evidence than an exit code, and on
  `:app:testDebugUnitTest`'s own arm64 `doFirst` line appearing in the log (proof the task executed rather
  than being cached). **The broken kill path is disclosed, not fixed** — it is in my own throwaway
  `/tmp/qbuild_q4prev_union.sh`, not in the repo, and the Python sweep used a *pause-and-resume* guard
  instead, which did work (3 `LOAD_WAIT` events, then it continued).
* **A count I quoted to the supervisor was wrong by one.** I reported the merged backend CI list as 44
  modules; measured from the workflow files themselves it is **45** — I read trunk `c2528e1` as 40 when it
  carries **41** (`git show <ref>:… | grep -oE 'python3 -S [^ ]+\.py' | sort -u | wc -l` → 41 / 42 / 44 for
  `c2528e1` / `f294bee` / `c0e86e5`). The conclusion the number supported is unchanged: the merge adds
  exactly the four new modules and drops none.

## What this does NOT change — the sequencing rule

Both q4 heads are FF-able onto trunk **one at a time**, and no commit contains both, so they must still be
gated **individually**: hosted CI has never judged a tree carrying `718a8ef` and `ede66f4` together, and a
local green union run cannot substitute for it, because pushing that union to `main` is precisely what
would trigger `ci.yml` (`push: branches: ["**"]`, `paths: ["App/**"]`) against the combined tree. Likewise
`c0e86e5` is **not** FF after `f294bee` lands — `f294bee` is not its ancestor — so q5 must be gated as a
merge, which is what `a9cab3a` previews. The preview being green makes the *merge* safe; it does not make
it fast-forwardable, and it does not lift the gate.

The merge itself needed 2 resolutions, both in append-only pointer archives, both mechanical:
`Fast_Fetch/CONTINUITY.md` item 1's session-file count (re-counted from the directory, never copied —
**71 = 69 dated + 2 undated** at `a9cab3a`, 72 with this file) and `Fast_Fetch/checkpoints/README.md`'s
index (both lanes' entries kept **verbatim**, union, 0 deletions). That is the sanctioned rule for these
two files, and `test_docs_invariants.py` is the judge: its `test_the_index_counts_are_the_directory_listings`
compares the written number against the directory glob, and `test_no_history_line_was_deleted_only_moved`
requires the newest sorted archive to be indexed.

## Recorded and not fixed, with the owner named

* **`native_card_every_posters` has two owners on trunk** — `VipRemoteAds.feedCardEveryPosters`
  (`@SerializedName(value="feed_card_posters", alternate=[...native_card_every_posters...])`) and
  `VipRemoteAdCadence.feedCardEveryPosters`
  (`@SerializedName(value="ad_native_card_every_posters", alternate=[native_card_every_posters])`) both
  claim the same alternate wire key, so one server field can populate two model paths and they can
  disagree. Pre-existing on `c2528e1`, not introduced by either q4 head (the union diff touches neither
  declaration). Filed as task **#48** for **qoder4** to judge — record only, qoder4's worktree was not
  touched.
* **The 9 arm64-excluded cases still ran nowhere here.** `ScreenSnapshotTest` (6) and
  `PosterCardProvenanceTest` (3) are excluded by the `os.arch` block in `app/build.gradle.kts` (no
  Robolectric native runtime, robolectric/robolectric#9166); 795 executed tests here means those 9 are
  additional and hosted-only. The union figure is therefore **795 local + 9 hosted-judged**, not 804.
* **Lint is unmeasured for the pair** — it was not in the 12:03 invocation, and the earlier attempt at
  `:app:lintDebug` died on the queue's own 30-minute timeout at `lintAnalyzeDebugUnitTest`
  (`GRADLE_EXIT=124`, a timeout, not a build failure) at load 9. `ci.yml`'s `lintDebug` leg remains the
  measurement.
* **`GITHUB_TOKEN` for this lane still answers 401 on `/user`** (owner-only fix at wake-up); a green
  `ls-remote` proves only that the repo is public, never write access.

## Commands that judge this entry, in order, without a build

```sh
# git-level facts
git -C /tmp/q1_preview_q4 log --oneline -3          # 057d344 ← b50e617 ← c2528e1
git -C /tmp/q1_preview_seq log --oneline -1         # a9cab3a (parents f294bee, c0e86e5)
git -C /tmp/q1_preview_q4 status --porcelain        # empty, before and after
# test-level facts
ls -l /tmp/q1_preview_q4/App/app/build/test-results/testDebugUnitTest/   # 94 XMLs @ 12:10:51-52
grep -c '^PASS' /tmp/q1_seq_pytest.log; grep -c '^FAIL' /tmp/q1_seq_pytest.log   # 45 / 0
```
