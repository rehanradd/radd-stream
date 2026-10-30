# 2026-10-30 04:0x → — q3 lane, THE DOCUMENTATION DIET (docs split, guard test, no production touch)

**Brief (from q4 master):** the auto-loaded docs had become a performance defect — measured
2026-10-30: `App/AGENTS.md` 177 KB, `docs/SESSION_CHECKPOINT.md` 249 KB, `Fast_Fetch/CONTINUITY.md`
277 KB, `Fast_Fetch/AGENTS.md` 38.9 KB, root `AGENTS.md` 37.7 KB; all Markdown 1.84 MB; every lane
auto-loads them, ≈ 45 k tokens before any work. **Do it as a SPLIT, never a deletion** — LAW (short,
invariant rules) stays in the AGENTS.md files; LOG moves to one dated file per session; SPEC moves to
`docs/` and is linked, not inlined. Targets: root ≤ 8 KB, `App/` ≤ 10 KB, `Fast_Fetch/` ≤ 8 KB, each
checkpoint a ≤ 20-line open-items index. NON-NEGOTIABLE: every law line survives **verbatim**. Add
one offline guard test and register it in CI. Work on a fresh worktree from `dc73ac7`, branch
`q3-docs-diet`, hand over the sha + a before/after byte table + the test's `Ran N tests / OK` line.
Do not merge, do not touch production, do not delete any historical text — move it.

## What landed

- **Base:** `dc73ac7` (which already carries my `56e743b` per-host serialiser). Branch
  `q3-docs-diet`, pushed to that branch only — no trunk landing, per the fleet notice.
- **Five passes, all scripted, all conservation-checked before writing.** The check is a
  `collections.Counter` multiset equality: for each file, `kept ∪ moved == original` line-for-line;
  any residue prints `REFUSE` and nothing is written.
  1. `Fast_Fetch/CONTINUITY.md` → 44 dated files in `Fast_Fetch/checkpoints/` + `README.md` index.
  2. `docs/SESSION_CHECKPOINT.md` → 50 dated files in `docs/checkpoints/` + `README.md` + `TEMPLATE.md`.
  3. SPEC sections out of `App/AGENTS.md` and `Fast_Fetch/AGENTS.md` into `docs/SPEC_*.md`.
  4. Root `AGENTS.md`: repo tree, the adult-flag evidence narrative, the guardrail's 01:30
     measurement, the per-sha CI-health narrative, the quick-command comment blocks and the tag
     procedure moved to `docs/SPEC_REPO_MAP.md`, `docs/SPEC_ADULT_FLAG_EVIDENCE.md`,
     `docs/SPEC_AGENTS_MEASURED_NOTES.md`; each emptied section keeps a pointer that says why the
     text moved and what stayed as law.
  5. The guard test.
- **`Fast_Fetch/test_docs_invariants.py` — 12 tests, `Ran 12 tests / OK`.** ~90 invariant phrases
  matched on whitespace-normalised text (so re-wrapping a paragraph cannot hide a lost law line):
  the secrets table and the verify-names-only rule, the whole adult invariant chain including the
  442/455 hole, `inherit_key_adult()`, the 2,600/3,486/69,773 residual and the pattern law, all
  seven fleet-guardrail steps with rule 7's 266.312 s measurement, the CI-counting truth, the
  keystore-secrets state, the loopback-not-token boundary, and the eleven standing rules. Plus byte
  ceilings, rotated-destination existence, full-index reachability and link resolution.
- **New law written (it existed nowhere):** count CI's suites with
  `grep -c 'name: 🧪' .github/workflows/backend-ci.yml`, never `grep 'run: python3 -S'` — the timed
  `test_admin_panel.py` step is a suite the latter misses (26 vs 25 measured at `56e743b`).
- **Registered in CI** as `🧪 test_docs_invariants.py` → **28** `🧪` steps on this branch, while
`grep -o 'run: python3 -S'` reports 27 — the new law demonstrating itself on the file it guards.

## What the diet found (real defects, all fixed)

- **Two link bugs of my own making.** The rotators wrote `](Fast_Fetch/checkpoints/…)` inside
  `Fast_Fetch/CONTINUITY.md` and `](docs/checkpoints/…)` inside `docs/SESSION_CHECKPOINT.md` —
  correct from the repo root, dangling from the file. 22 links repaired, 3 more made relative in the
  open-items index, and the link test now catches the class.
- **One rotated file was un-indexed:** `docs/checkpoints/undated-the-memory-story-rewritten-twice.md`
  existed but no index reached it. Added to `docs/checkpoints/README.md`.
- **One stale claim corrected in place, with its history kept:** root `AGENTS.md` asserted a
  `paths-ignore` filter for `backend-ci.yml`. Re-measured against the tree: the file's md5 matches
  `git show dc73ac7:.github/workflows/backend-ci.yml` and its push trigger is
  `paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]` — an allow-list. The historical
  paragraph stays (it was true at its own date) and the correction now states the method as the law:
  *read the workflow's own trigger block before predicting whether CI will run.*
- **CONTINUITY index item 5 was stale** ("reconciliation + test unwritten"). Corrected: the key-level
  law landed; the measured residual is the re-key migration, not the reconciliation.

## Sizes — before → after (bytes, measured)

| file | before (`dc73ac7`) | after (rebased onto trunk `4fe6f65`) | target |
|---|---|---|---|
| `Fast_Fetch/CONTINUITY.md` | 277,009 | **8,819** | ≤ 20-line index ✅ |
| `docs/SESSION_CHECKPOINT.md` | 248,840 | **5,426** | ≤ 20-line index ✅ |
| `App/AGENTS.md` | 177,371 | **11,993** | ≤ 10 KB — missed by 2 KB |
| `Fast_Fetch/AGENTS.md` | 38,909 | **13,668** | ≤ 8 KB — missed |
| root `AGENTS.md` | 37,670 | **28,746** | ≤ 8 KB — missed |
| **the five, total** | **779,799** | **68,652 (−91.2 %)** | |

(The two logs are bigger here than at `42464cb` — 65,714 B — because the rebase absorbed trunk's
three post-rotation doc edits into the index layout: q4's `[Q4-SAFETY]` halt-band entry, q2's
MovieBox detail-API checkpoint entry, and q2's `[Q2-MOVIEBOX-CRAWL]` CONTINUITY session block. They
went to `checkpoints/` as dated files and cost the indexes ~3 KB of new pointer lines. Still 91 %
smaller than what every lane auto-loaded.)

(All Markdown in the repo went 1,844,304 → 1,920,647 B across 68 → 190 files — the diet *adds* 76 KB
of headers, indexes and provenance lines to the moved text. It is a relocation, not a compression:
what shrank is what every lane auto-loads, which is the defect that was reported. **Say it plainly
so nobody later "fixes" it by deleting archives:** tracked Markdown bytes went UP on purpose. An
archive is not loaded by any agent, so its bytes cost nothing; a law line inside an auto-loaded file
costs 45 k tokens every session. If a future lane sees the total rise and calls it a regression, this
paragraph is the answer.)

**Every number in this table is `git cat-file -s` / `wc -c` on the tree being committed, not a figure
taken while the files were still being edited.** The first pass printed 64,663 B and CONTINUITY
6,511 B; both were mid-work measurements, before the final pointer lines landed, and the original
commit message still carries the 64,663 figure. Corrected here rather than amended in Git — the
committed message is history, this table is the measurement.

## The rebase: trunk moved while the diet was open, and a rotation has to eat that

`q3-docs-diet` was written against `dc73ac7`. Trunk moved to `4fe6f65` (q2's MovieBox detail-API fix
plus q4's `[Q4-SAFETY]` landing), and three doc edits landed *into the files I had just rotated* —
which is exactly how a diet silently deletes someone else's history: the append-here habit, one file,
two lanes, and a rebase that "takes my version" loses theirs.

What this lane did instead, measured and checked:

- `git rebase --onto 4fe6f65 dc73ac7` — conflicts only in `Fast_Fetch/CONTINUITY.md`,
  `docs/SESSION_CHECKPOINT.md` (both resolved to the index layout, never to "mine").
- Each trunk insertion extracted by `difflib` opcode (not by hand-copied line numbers), conservation
  checked as a multiset before any write, then re-verified after the write, and put in one dated file
  per session with the trunk sha and line range in its header:
  `Fast_Fetch/checkpoints/20261030-q2-themoviebox-crawl-…` (100 lines),
  `docs/checkpoints/20261030-2026-10-30-04-15-qoder4-…` (42),
  `docs/checkpoints/20261030-2026-10-30-cont-…` (16).
- `Fast_Fetch/SITES.md` — this lane never rotated it, so q2's corrected §25 site notes came through
  untouched. Recorded so the next reader does not go looking for them in `checkpoints/`.
- Every new archive is named by both the auto-loaded index and `checkpoints/README.md`; the merged
  `backend-ci.yml` keeps trunk's `🧪 test_themoviebox_detail_api.py` where trunk put it and the
  guard step last — **29 `🧪` steps, 28 `run: python3 -S` matches**, the counting law holding.
- Re-measured against the *new* trunk: `TOTAL VANISHED LINES vs 4fe6f65: 0` across all five files
  (3,627 CONTINUITY lines and 3,088 SESSION_CHECKPOINT lines checked, not sampled).
- The guard test grew rather than relaxed: 17 cases now, including q4's halt-band law lines, q2's
  crawl-gate-refusal lines, `SITES.md`'s "no playable print is resolvable from this host" verdict, a
  check that every enumerated target file is *reachable from an index* (law nobody can find is law
  lost), and a check that the archive counts claimed in the two indexes equal the directory listings.

## The honest finding: the 8 KB target and "verbatim law" are mutually unsatisfiable

The brief's NON-NEGOTIABLE list is itself larger than 8 KB. Measured in this file today: the adult
invariant chain 6.5 KB, the Secrets section (table + measured keystore state + the verify-names-only
rule) 2.8 KB, Cross-Agent push law 3.4 KB, the 7-step guardrail 3.4 KB, Key Links (whose
operator-panel cell is one enumerated law sentence plus its measurement) 1.8 KB, the eleven standing
rules 2.0 KB — **≈ 20 KB of law before any heading, pointer or command.** Cutting to 8 KB would mean
either rewording law (forbidden) or relocating it out of the auto-loaded file (also against the
brief's own LAW rule). So I kept law verbatim, moved everything that is evidence, and set the guard
test's ceilings at the measured floor + headroom (root 32 KB, `Fast_Fetch/` 18 KB, `App/` 15 KB).

**What the fleet actually got:** the five files a lane auto-loads went **779,799 B → 68,652 B
(−91.2 %)**, ≈ 45 k tokens → ≈ 17 k (68,652 B of the 1.92 MB of Markdown). The remaining reduction
available is *de-duplication*, not trimming: root
`AGENTS.md` §"Important Rules" is restated in `Fast_Fetch/AGENTS.md` §11 and `App/AGENTS.md`, and
`Fast_Fetch/AGENTS.md` §6 repeats the adult law. Say the word and I'll make root the single home for
shared law and have the two sub-guides link it — that gets all three under their targets without
moving a law sentence out of an auto-loaded file.

## Not done, truthfully

- Not merged; not landed on `master`/`main`; production untouched; no service action; no tag; no
  crawl; no Gradle; no heavy read. Load was 10.28 at 04:41 and every command ran under `nice -n 19`,
  one at a time.
- CI has **not** verified this branch yet — the push happens after this entry; the verdict will be
  reported separately, and it judges `Fast_Fetch/**` (the new suite) on the hosted runner.
