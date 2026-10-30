# 2026-10-28 22:05 — the push credential is ALIVE, master+main are synced, and the real ceiling is 1 CPU

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 22:05 — the push credential is ALIVE, master+main are synced, and the real ceiling is 1 CPU

- **The 21:40 entry below is superseded on one point: the token works.** `GET api.github.com/user`
  with `GITHUB_TOKEN` now answers **200 / login `rehanradd`**. It was 401 at 21:40; something changed
  since. No owner action is needed to push.
- **Pushed, after gating the exact committed tree.** `b1e9e73` → both `refs/heads/master`
  (`ff912c8..b1e9e73`) and `refs/heads/main` (`bc2bc0e..b1e9e73`), via the `ORACLE_DEPLOYMENT.md`
  askpass helper with the token read from the environment and the explicit clean URL — never `origin`.
  `main` was merely *behind*, not diverged: `bc2bc0e` is an ancestor of `ff912c8`, so both moves are
  fast-forwards. Six commits carried: `55f9c51`, `8ba614a`, `6a8072a`, `7ebbb10`, `979bba9`, `b1e9e73`.
- **Gate method worth copying:** the shared working tree was dirty with in-flight worker edits
  (9 importers modified, plus untracked `CatalogScale.kt`/`StatsHonestyTest.kt`/`import_aryplus.py`),
  so a test run *in place* would have measured the workers' WIP rather than the commits being pushed.
  Ran the suites in a detached `git worktree` at `b1e9e73`: **`test_database.py` 75 OK,
  `test_vidout.py` 6 OK, `test_host_resolvers.py` 171 OK — 252 tests, 0 failures.** Worktree removed
  afterwards.
- **The overload premise in the ops prompts is wrong: `nproc` is 1.** This VM has a *single* core, so
  the 4.0 load ceiling is roughly 4x too generous. Observed 6.5–8.4 with runqueue 8, i.e. ~8x
  oversubscribed, while one Gradle build (`:app:kaptGenerateStubsDebugKotlin`) plus 4–5 concurrent
  `qodercli` sessions plus the ARY Plus crawl ran together. New working ceiling: **keep load < 1.5**,
  which in practice means one actively-generating worker at a time.
- **Memory was the near-miss, now fixed.** Swap was 1.9 GiB of 2.0 GiB used (91 MiB free) with 2.6 GiB
  RAM available. Two idle `GradleDaemon`s and the `KotlinCompileDaemon` (~3.3 GiB RSS between them)
  were stopped with `gradle --stop` — no work lost, daemons respawn — taking available RAM from
  2.6 → 5.2 GiB. A 4 GiB `/swapfile2` was added at runtime (`swapon` output confirms 6.0 GiB total,
  4.2 GiB free). **`/etc/fstab` was NOT touched**, so `/swapfile2` disappears on reboot; say the word
  to make it permanent. Trade-off recorded honestly: killing the daemons is what made qoder1's next
  build cold-start, which is partly why load spiked.
- **The crawl is not the problem.** `import_aryplus.py crawl` runs `--workers 1` and 2 threads at
  ~1% CPU — it is network-bound and costs almost nothing. At 22:00 it was 400/1019 pages, 220 posts,
  6,901 sources. It is the one job that should keep running while everything else parks.
- **Fleet parked at 22:05** pending load < 1.5: qoder2 told to answer only the crawl-state question
  and idle; qoder3 told to run `test_database.py` once, report whether all 9 modified importers carry
  the `is_18_plus`/`is_animated` COALESCE fix, commit locally, and stop (its context is at 82%);
  qoder1 told to let build28 finish and start no further Gradle build. AnimaHD pilot is complete at
  232 posts.
- **Unexplained and for the owner:** besides qoder1 (317534), qoder2 (159201), qoder3 (671341) and
  this session, three more live `qodercli` processes hold this box — **560472** (~6.5 h, age 23.5k s),
  **89183** (~38 h) and **745967** (~13 min), all with cwd `/opt/radd-stream`. On one core they are a
  large share of the load. Not killed: terminating someone else's session is not an orchestrator's
  call.

