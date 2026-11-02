# Session checkpoint

Update this file after each independently verified milestone so work can resume across accounts, tools, and usage limits.

## ✅ Open items — index (q3, 2026-10-30; pointers only)

1. **This file is a pointer, not a history.** 61 files cover 2026-10-20 → 2026-11-01: 59 dated
   session blocks, one undated block, the entry template — every one verbatim. Newest first in
   [`checkpoints/README.md`](checkpoints/README.md). The count is `ls docs/checkpoints/*.md` minus
   `README.md`, and `Fast_Fetch/test_docs_invariants.py` checks the number written here against that
   listing — a stale count in an index is its own defect, so it is now a tested claim, not prose.
2. Start at `checkpoints/README.md`; it names every window and the file that holds it.
3. Root `AGENTS.md` + `docs/PROJECT_MAP.md` remain the law and the location map; this file is only
   the running log, and after this diet it no longer carries ~250 KB of it in every agent's context.
4. Append new sessions to `checkpoints/` as one dated file per session — **do not append here**.
   The old append-here behaviour is what made every lane re-read 249 KB before doing any work.
5. Verified by the guard test `Fast_Fetch/test_docs_invariants.py`: the invariant law text is still
   present in the three `AGENTS.md` files, and every original line of this file still exists in
   exactly one destination file.
6. **Trunk moved after this file was rotated, and the rebase absorbed it instead of dropping it.**
   `q3-docs-diet` rebased onto `4fe6f65`: q4's `[Q4-SAFETY]` halt-band entry and q2's MovieBox
   detail-API entry are verbatim in `checkpoints/`, linked above and in `checkpoints/README.md`.
   The safety finding stays current for every lane: `/opt/radd-stream` — the tree `ExecStart` loads,
   not a workspace — sat **85 commits behind with 22 dirty backend files**, so any restart today
   loads that superseded mixture, not trunk. Nobody has committed over it or reset it; the owner
   decides.
7. This lane's own rotation claim is checked, not asserted: `test_docs_invariants.py` enumerates the
   law strings *and* the headings of the absorbed trunk edits, so a later diet that drops one fails
   CI instead of silently losing it.
8. **`[Q3-ONBOARD-PAY]` backend, branch `q3-backend-auth-payments` @ `9df2f62`** — the device-gated
   3-day trial, the PBKDF2 phone+PIN link, and the merchant relay that can credit a claim (83 offline
   tests, CI step 33): pointer, not a copy —
   [`../Fast_Fetch/checkpoints/20261031-q3-lane-zero-friction-onboarding-and-the-merchant-relay.md`](../Fast_Fetch/checkpoints/20261031-q3-lane-zero-friction-onboarding-and-the-merchant-relay.md).
   Two findings outrank the feature itself: **the review that governs this exact task —
   `docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md`, R1-R9 — was already in trunk when the brief landed,
   and the brief did not name it**, so a lane re-derives from scratch what another lane already
   ruled (this lane's first draft of the session log told the owner to open an nginx route that R2
   rules against). Point at the governing ruling-file when you post a task. And
   **`Fast_Fetch/test_accounts.py` (61) and `Fast_Fetch/test_payments.py` (85) exist, pass, and are
   not in `backend-ci.yml` at all**, so `accounts.py` and `payments.py` — the money and the keys —
   have no hosted gate on any lane's push. Owner's call to register them; this lane reported and did
   not silently widen everyone's gate.
9. **`[Q3-PREMERGE-P]` — the pre-merge catalog copy and five-site merge are GATED, NOT OPEN.** qoder1
   approved the plan at `ef91096` with four corrections, landed into
   [`../Fast_Fetch/checkpoints/20261101-01xx-q3-lane-premerge-copy-plan-queued-not-run.md`](../Fast_Fetch/checkpoints/20261101-01xx-q3-lane-premerge-copy-plan-queued-not-run.md):
   **C1** the source-side `wal_checkpoint(TRUNCATE)` is withdrawn — a read-write open checkpoints and
   rewrites the file it touches, so the instruction would have written into five databases that are not the
   lane's, and `.backup` from `-readonly` folds the WAL by construction; **C2** `fuser` is informational only
   — the service holds **zero** `.db` fds between requests, so an empty `fuser` is the healthy state and my
   abort fired on it every time; the load-bearing guard is the source mtime+size pair taken immediately
   before *and* after the read; **C3 excluded `mp4moviez` and C3R reversed it inside the hour — merge all
   FIVE, mp4moviez last**, through `Fast_Fetch/importers/convert_mp4moviez.py`, which is already on trunk
   (`81cdff8`, `eac15bb`), opens the legacy db with `mode=ro`, and `os.replace`s a `mkstemp` build onto its
   target, so no schema code had to be written at 2 am after all; **C4** new Step 3.5
   baselines the verified copy so a failed merge never costs a second production read. Two defects this
   exchange produced, one on each side: qoder1's dispatched `--target` named `mp4moviez_staging.db`, which
   **already exists** and is refused without `--force` (`:548-549`) — and, counted read-only, is a **stale
   pre-`81cdff8` vault holding 11,403 posts / 43 flagged where the measured conversion is 28,066 / 88**, so
   merging the file at that path would have merged the exact surprise the stop-condition forbids; and my
   Step 7 kept the retired exclusion wording while Step 5.5 already merged five sites, which would have made
   the report misstate the database it describes. Fix approved: a fresh target name
   `mp4moviez_staging_20261101.db` (C3R-final) and no `--force` outside my own vault. Start signal:
   qoder1's `SUSTAINED-UNDER4` post **and** `MemAvailable > 1,500 MB` / `SwapFree > 800 MB` — and tonight's
   arithmetic does not fund the plan: the 01:52 sub-4 window (load1 3.48) closed at 01:55 (load1 4.85) after
   ~3 minutes, shorter than the 3–10 minute estimate for the 6.4 GB copy read. **Nothing has run against the
   catalog and this lane stops at the sha.** It lives here, not in `Fast_Fetch/CONTINUITY.md`, because that
   file sits at 11,958 of its own 12,000-byte archive guard (measured at `f12ab3f`) — item 16 would not fit,
   and I trimmed nothing to make room rather than silently drop another lane's facts.
   **Landed, then re-based.** qoder1 replayed my two documentation commits onto trunk as `f12ab3f` (main ==
   master; Backend CI `completed success` on both refs, runs 41247930663 / 41247930667), footprint exactly my
   four paths and no Python. A replay is not a merge: `60ef341` is **not an ancestor of trunk**, so
   `git diff 60ef341 trunk` reads trunk's *other* content as my deletion — that misreading produced a
   retracted §17n claim that my head deleted trunk's `_probe_dir()`. This lane now works from a fresh
   worktree at `f12ab3f` (`q3-premerge-exec-20261101`); nothing was reset, `60ef341` stays recoverable.
10. **`[Q1-DBPATH-HAZARD]` — measured; this lane is clean structurally, not luckily.** `DB_PATH` is
    `BASE_DIR`-relative (`config.py:119`, `BASE_DIR` at `:101`), and since 00:32 both
    `/opt/radd-stream/Fast_Fetch/fast_fetch.db` (00:32:17) and `/home/ubuntu/radd-stream-data/fast_fetch.db`
    (00:32:29) are **symlinks onto `merged_catalog_20261025.db`**: a default-path write from the live tree
    *is* a production write and the command line looks identical either way. From `/tmp/q3_premerge` the same
    import resolves to `/tmp/q3_premerge/Fast_Fetch/fast_fetch.db`, which **does not exist** — the ignore rule
    `.gitignore:18 *.db` means a worktree never gets the link. So: own worktree only, `RADD_DB_PATH` set
    explicitly, `config.DB_PATH` printed before any write. Per rule 4 the links are **reported as found, not
    fixed**; creator unknown. Freeze unchanged: no merge, no Gradle, no production read (load1 5.44).

---
## Rotated session history

Session blocks moved verbatim to [`docs/checkpoints/`](checkpoints/README.md); nothing was deleted or reworded.
The newest 14 are listed here; the complete index (all 54) is in `docs/checkpoints/README.md`.

- [2026-10-31 09:05 — q4 App lane `[Q4-ONBOARD-GREEN]`: onboarding went hosted-green at `03e926b`, the favourites rescue is provably not self-contained, and both lines own Room version 7](checkpoints/20261031-0905-q4-onboarding-hosted-green-and-the-favourites-version-collision.md) — three run ids measured, one destructive-migration trap found by reading
- [2026-10-30 22:55 — Release signing secrets active on GitHub, tag v1.0.0 triggered `[RELEASE-SIGNING-ACTIVE]`](checkpoints/20261030-2255-signing-keys-active-release-triggered.md) — release pipeline live
- [2026-10-30 10:xx — q6 lane `[Q6-DOC-TRUTH]`: eleven false API-security statements corrected against code, the never-discovered `App/.github/workflows` copies deleted, and two findings that contradict the docs (reported, unfixed)](checkpoints/20261030-10xx-q6-lane-doc-truth-the-api-security-paragraph.md) — written straight into the archive per rule 4

- [2026-10-30 (cont.) — MovieBox: detail-API parser, credits/backdrop/languages fixed, crawl gate refused `[Q2-MOVIEBOX-CRAWL]`](checkpoints/20261030-2026-10-30-cont-moviedbox-detail-api-parser-credits-backdrop.md) — 26 lines (absorbed from trunk `4fe6f65` during the q3 diet rebase)
- [2026-10-30 04:15 — qoder4 master: the box entered the halt band, and what was actually consuming it `[Q4-SAFETY]`](checkpoints/20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md) — 52 lines (absorbed from trunk `4fe6f65` during the q3 diet rebase)
- [2026-10-30 02:20 — qoder4 master: the admin-panel gate verdict, and the measurement that flipped](checkpoints/20261030-2026-10-30-02-20-qoder4-master-the-admin-panel-gate-verdic.md) — 37 lines
- [2026-10-30 01:10 — qoder4 master orchestrator: four false production claims retired, CI measured](checkpoints/20261030-2026-10-30-01-10-qoder4-master-orchestrator-four-false-pro.md) — 66 lines
- [q5 lane, 2026-10-30 — the engagement pillars are now admin-controllable, and one shadowed name c](checkpoints/20261030-q5-lane-2026-10-30-the-engagement-pillars-are-now-admin-co.md) — 64 lines
- [2026-10-29 01:50 — App docs honesty pass: four stale 2026-10-22 claims corrected, no build run](checkpoints/20261029-2026-10-29-01-50-app-docs-honesty-pass-four-stale-2026-10.md) — 125 lines
- [2026-10-29 01:40 — master (qoder4): the merges happened, and 10 vaults joined the live catalog](checkpoints/20261029-2026-10-29-01-40-master-qoder4-the-merges-happened-and-10.md) — 197 lines
- [2026-10-29 05:20 — master (account4): batch 3 landed (31 sites), a real 18+ leak found and quant](checkpoints/20261029-2026-10-29-05-20-master-account4-batch-3-landed-31-sites-a.md) — 92 lines
- [2026-10-29 05:5x — qoder5 (PRIORITY 1 `[Q5-P1-ADULTKEY]`): the adult flag moved from the row to ](checkpoints/20261029-2026-10-29-05-5x-qoder5-priority-1-q5-p1-adultkey-the-adul.md) — 38 lines
- [qoder4 (Master Orchestrator) — 2026-10-29 10:45-11:00, the backfill ran and was partly rolled ba](checkpoints/20261029-qoder4-master-orchestrator-2026-10-29-10-45-11-00-the-back.md) — 102 lines
- [2026-10-29 — `uncut`/`unrated` were never adult markers; the pattern is fixed, the 7,663 are sti](checkpoints/20261029-2026-10-29-uncut-unrated-were-never-adult-markers-the-patt.md) — 61 lines
- [q3 lane, 2026-10-29 ~17:05 host time — the audit blessed the leak, and here is the counterfactua](checkpoints/20261029-q3-lane-2026-10-29-17-05-host-time-the-audit-blessed-the-l.md) — 80 lines

## Moved out (reference prose, verbatim)

- Template for future checkpoints → [`checkpoints/TEMPLATE.md`](checkpoints/TEMPLATE.md) (120 lines) — the entry template

- the memory story rewritten twice because the first two readings were wrong → [`docs/checkpoints/undated-the-memory-story-rewritten-twice.md`](checkpoints/undated-the-memory-story-rewritten-twice.md)
