# SPEC AGENTS MEASURED NOTES

> Moved **verbatim** out of `AGENTS.md` by the 2026-10-30 documentation diet.
> The diet splits LAW / LOG / SPEC and never deletes: every line below is
> byte-identical to what `AGENTS.md` carried at `dc73ac7`.
### from `AGENTS.md` lines 224-229

**This host has ONE vCPU** (`nproc` = 1). Measured at 01:30 with five agent lanes running:
load average 10.2, core 91 % user / 1 % idle / 0 % wait, run queue 8–9. A 6-second
`/proc/<pid>/stat` utime+stime delta attributed **167.7 % of the entire machine to the five
`qodercli` lanes plus tmux and `jbd2`**, while `radd-stream` itself consumed **29.8 CPU-seconds
across 2 h 10 min of uptime — about 0.4 % of a core**. We are the load; production is not.
Full per-route costs are in [`docs/CAPACITY_MEASURED.md`](docs/CAPACITY_MEASURED.md).

---

### from `AGENTS.md` lines 272-279

1. Run CI's **25 `🧪` steps**, one invocation each — measured from backend run `40954291359`
   (sha `396e476`, `completed success`): database, vidout, catalog_v2, release_descriptor,
   link_health, link_state, evidence_writeback, api_v2, redact, tiers, catalog_api,
   provenance_stamping, merge_catalogs, site_scout, backup_manager, usage_stats,
   operator_isolation, media_search, migrate_search_indexes, bounded_ledger, project_readonly,
   posts_query_plan, adult_twin_probe, link_sweep_budget, admin_panel. The older "17 modules /
   791 tests at `9859b8a`" figure is historical — it was true then and is not the current list,
   so do not quote it as if it were.

---

### from `AGENTS.md` lines 284-289

**Run the gate in a worktree at the tip, not in `/opt/radd-stream`.** Measured 2026-10-29 18:55: the
live tree is checked out at its own `bf9e565` and its `Fast_Fetch/test_database.py` contains **76**
`def test_` methods, while the pushed tip (`6e54909`) contains **124**. Same command, two different
gates, because `/opt/radd-stream` is a diverged older draft carrying other lanes' uncommitted edits
(56 dirty paths right now, `AGENTS.md` staged). A "green" from the live tree is a weaker claim than
CI's, and can silently test deleted code.

---

### from `AGENTS.md` lines 306-307

| GitHub Actions | ✅ **Enabled and running** — `/repos/rehanradd/radd-stream/actions/permissions` returns `{"enabled": true, "allowed_actions": "all"}` (measured 2026-10-29 03:54 host time; 40 runs recorded). The earlier "⛔ disabled at the account level" line in this file was **wrong** and is retired. All three repo-root workflows are `state=active`: `🐍 Backend CI`, `🔨 CI — Android Build & Test`, `🚀 Release — Sign & Publish APK + AAB`. The copies that used to sit under `App/.github/workflows` were never discovered by GitHub and have since been deleted (with them went the repo's only `pull_request` trigger — CI runs on push, not on PR). | Gate is live |
| CI health (both sides) | 🐍 **Backend CI is GREEN** — `completed success` on both `master` and `main` at `f0c1ca3`, and green on every adult-fix commit (`ab78849`, `8ad9862`, `6b28e48`, `f6637c9`, `c4a1302`). 🔨 **Android CI IS NOW GREEN — FIRST TIME EVER** — measured 2026-10-29 at `2caadb3`, `completed success` on **both** `master` and `main` (run `40874380668`); all 14 steps green, including the single combined `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` step, `BUILD SUCCESSFUL in 7m 2s`, `:app:testDebugUnitTest` executed, no lint errors emitted. The previous "still RED: 636 tests / 9 failed / 23 lint errors" line was a **misdiagnosis**: every fix for it existed in `5446771`, but that commit was **local-only on a `master` that had diverged** from `origin/master` (`git merge-base --is-ancestor 5446771 origin/master` → NO; 2 local-only vs 26 remote-only) and `ci.yml` triggers on `App/**`, so nothing had fed it since `11742e0` (2026-10-28T21:21, failure). **It was unfed, not red** — I cherry-picked it onto `f0c1ca3` as `2caadb3` and pushed to both refs. The trap that hid this stays true: `ScreenSnapshotTest` and `PosterCardProvenanceTest` are excluded from every local arm64 run (Robolectric #9166), so only the hosted runner can judge them. `tags: 0`, `releases: 0` still, and signing is genuinely blocked on the four absent keystore secrets (see the measured note in Secrets above) — a debug APK is available from CI meanwhile. **Re-measured 2026-10-29 22:5x via `/actions/runs?per_page=6`** (91 runs total): 🐍 Backend CI is `completed success` on **both** `master` and `main` at `9859b8a` and at `6f7e3a0` — i.e. green on the 17-module list this file now documents, judged by the hosted runner and not only by this box. 🔨 Android is green on `master` (`2caadb3`) but **red on the live app lane**: branch `q1-ad-cadence` failed its combined Gradle step at `99472e0` (run `40917741872`, step `🏗️🧪🔍 Gradle: debug APK + unit tests + lint (single invocation)`, no annotations attached — read the job log, not the summary) with a retry `in_progress` at `217e8cd`. A green `master` does not mean the app lane is safe to merge. **⚠️ That last sentence was true at 22:5x and is now measured false — re-measured 2026-10-30 00:5x from `/actions/workflows/398476977/runs?per_page=12`: the retry `217e8cd` came back `completed success` (17:18), and every Android run after it is green — `bc2e534` on `q1-ad-cadence`, `e6482e9` on `q2-scenarios-fixes`, and `a3c34ff`/`bd45ba0`/`9a590bb`/`5e74aa2` on `q1-identity-fix`, the newest being `5e74aa2` at 19:17. Both trunk refs are green at `9859b8a` (Android) and `87b7b6f` (backend, on both `master` and `main`). There is no red app lane to wait on. `tags: []` and `releases: []` re-measured empty; the only Release run that has ever existed (`40876596427`, `workflow_dispatch`, 12:50, `35f9e89`) failed at its first step, "🗝️ Verify signing secrets are present (fail loudly if not)", and `/actions/secrets` returns `[]` — so signing is blocked on the owner adding the four keystore secrets, which is the only CI gate left that agents cannot close.** | Release blocked on owner secrets only |

---

### from `AGENTS.md` lines 329-357

# Run offline tests — one module per invocation; this runner ignores extra names.
# There are 68 `test_*.py` modules under Fast_Fetch/ and Fast_Fetch/importers/ — 48 at the
# Fast_Fetch/ root and 20 in importers/ (measured 2026-10-29 at `5c331d6` with
# `find . -name 'test_*.py' -not -path './.git/*' | wc -l`; re-measure it, do not trust this
# number, it has already gone stale twice in one day).
# These three are the standing *quick* gate — they are NOT what CI judges.
python3 -S Fast_Fetch/test_database.py    # 133 tests at the tip (was 124, was 76 — re-count)
python3 -S Fast_Fetch/test_vidout.py      # 6 tests
python3 -S Fast_Fetch/importers/test_host_resolvers.py   # 171 tests

# The REAL gate is exactly what backend-ci.yml runs — 25 modules, one per invocation (measured
# from CI run `40954291359` at `396e476`; it was 17 at `9859b8a`, and it will be more again — read
# the workflow file, this comment is a snapshot). As of
# `9859b8a` those 17 are CI's own list; the two extra suites the older version of this block
# described (`importers/test_host_resolvers.py`, `importers/test_convert_mp4moviez.py`) are NOT
# in CI and the 17th slot is not what this file used to claim:
#   test_database test_vidout test_catalog_v2 test_release_descriptor test_link_health
#   test_link_state test_evidence_writeback test_api_v2 test_redact test_tiers
#   test_catalog_api test_provenance_stamping test_merge_catalogs test_site_scout
#   test_backup_manager test_usage_stats test_operator_isolation
# Measured 2026-10-29 at `9859b8a`: 17/17 rc=0, **791 tests, 0 failures**, and GitHub's own
# `🐍 Backend CI — Stdlib Python` reported `completed success` on both `master` and `main` for
# that sha and for `6f7e3a0` — so this list and this count are corroborated by the runner, not
# just by a local box. `test_usage_stats.py` is 94 tests and `test_operator_isolation.py` is 28;
# run them with `RADD_USER_STATE_DB` pointed at a fixture, never the live state file.
# Measured earlier the same day: the 3-module quick gate stayed green while CI was red for five
# pushes, because it omits test_evidence_writeback.py and test_merge_catalogs.py. Run CI's list.
# Note `test_all_sites.py` is deliberately excluded from CI (`backend-ci.yml:33`) — it is a live
# 10-site network audit, not an offline test.

---

### from `AGENTS.md` lines 379-395

# GitHub only discovers workflows under the repository-root .github/workflows/.
# Root now carries ci.yml, release.yml and backend-ci.yml; the copies that used to sit
# in App/.github/workflows were never discovered and have since been deleted.

# To create a signed release — ⛔ OWNER'S CALL ONLY, AND IT CANNOT SUCCEED TODAY:
# tags: [] and releases: [] measured 2026-10-30, and /actions/secrets returns []. The one
# Release run that has ever existed (40876596427) failed at its signing-secrets gate. No
# agent may create or push a tag; the owner adds the four keystore secrets and tags.
# 1. Tag the commit
git tag v1.0.0
# 2. Push the tag with Git using the temporary askpass helper in ORACLE_DEPLOYMENT.md,
#    against the explicit clean URL. (Measured 2026-10-30: `origin`'s stored URL is
#    itself clean now, so the stated reason for avoiding it is gone — but keep the
#    explicit URL and the askpass flow, because the credential is still unrevoked and
#    a token in a URL is the leak this rule exists to prevent.)
git push https://github.com/rehanradd/radd-stream.git v1.0.0
# → GitHub Actions builds signed APK + creates Release automatically
