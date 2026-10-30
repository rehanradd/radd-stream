# Session checkpoint

Update this file after each independently verified milestone so work can resume across accounts, tools, and usage limits.

## ✅ Open items — index (q3, 2026-10-30; pointers only)

1. **This file is a pointer, not a history.** 54 files cover 2026-10-20 → 2026-10-30: 52 dated
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

---
## Rotated session history

Session blocks moved verbatim to [`docs/checkpoints/`](checkpoints/README.md); nothing was deleted or reworded.
The newest 14 are listed here; the complete index (all 54) is in `docs/checkpoints/README.md`.

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
