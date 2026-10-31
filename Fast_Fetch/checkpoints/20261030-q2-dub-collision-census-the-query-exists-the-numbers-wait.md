# [Q2-DUB-COLLISION-CENSUS] The query is built and measured; the numbers wait on the hold

**Date:** 2026-10-30 (late) · **Lane:** q2 (`/home/ubuntu/.qoder_account2`) · **Branch:** `q2-dub-collision`
· **Base:** `6a441ec` · **Supervisor token:** Q2-DUB-COLLISION-CENSUS · **Status: LANDED as `a424ffc`;
the numbers are a queued quiet-window action (see the 2026-10-31 section at the end).**

## What was asked, and what this session did

qoder1 asked how often `canonical_key = generate_canonical_key(clean_title, year)`
(`Fast_Fetch/fast_fetch.py:572`) names two different works — specifically a dubbed print and its
original — across the per-site staging vaults, plus the adult-twin share, plus a key recommendation.

This session delivered the **read-only query as a test module**,
`Fast_Fetch/importers/test_dub_collision_census.py` (13 offline tests, 13/13 OK in 4.9 s, run before
the HOLD took effect), and measured the schema facts the query depends on. **It did not produce the
three headline numbers.** The box crossed the 4.0 load ceiling before the first corpus pass and kept
climbing (0.91 → 5.18 → 6.35 → 9.81 → the supervisor's 12.5); the census refuses at load ≥ 4 by
design (`run_census`, exit 2, names what it did not reach).

## The fact that reshaped the query

Every staging database declares `canonical_key` **PRIMARY KEY or UNIQUE**:

| database | measured DDL |
|---|---|
| themoviebox | `canonical_key TEXT PRIMARY KEY` |
| filmyhit | `canonical_key TEXT PRIMARY KEY` |
| hindilinks4u | `canonical_key TEXT UNIQUE` |
| world4ufree | `canonical_key TEXT UNIQUE` |

Consequence: **a dub twin cannot exist inside one staging database.** The second subject with the
same title+year is refused or collapses onto the first row. The collision is only observable
**across databases** — which is also the shape of the merged ledger, where `canonical_key` is a
plain column and 442 keys are documented to carry both a flagged and an unflagged row (root
`AGENTS.md`). So the census intersects key sets across databases rather than grouping within one.

The second consequence is about cost: the grouping is a **covering-index read** on
`canonical_key`, not a table scan. Measured plans (`EXPLAIN QUERY PLAN`, recorded before any
aggregate, as instructed):

```
themoviebox   SEARCH posts USING COVERING INDEX idx_themoviebox_posts_key (canonical_key>?)
hindilinks4u  SEARCH posts USING COVERING INDEX idx_posts_canonical (canonical_key>?)
filmyhit      SEARCH posts USING COVERING INDEX sqlite_autoindex_posts_1 (canonical_key>?)
```

The module therefore runs in two phases: read key sets from the covering index, then fetch
`languages` / `is_18_plus` by point lookup **only for keys seen in two or more databases**. No
full-table scan, no sort, no `GROUP_CONCAT` over the corpus.

## Measured corpus

39 one-per-site staging databases (second/third scrapes of the same site excluded:
`katmoviehd_refreshed`, `mp4moviez_staging{,2}`, `multimovies_full_20261022`; production and the two
6 GB artifacts are in `NEVER_SCAN`). Row estimate by `max(rowid)` — an O(1) b-tree peek and an
**upper bound**, not a count:

- ≈ **370,584 rows** total; ≈ **340,734** in databases that have `canonical_key`
  (`mp4moviez.db`, 29,850 rows, predates the column and is skipped loudly);
- themoviebox itself: **44 rows, 44 distinct keys, 0 flagged** — no twin in the 44-row sample,
  which is an absence in a convenience sample, not evidence against the phenomenon.

Schema variance the query must survive (from `PRAGMA table_info(posts)`, all 49 databases):

| missing column | canonical databases | how the query handles it |
|---|---|---|
| `languages` | 10 (7starhd, bolly4u, hdtvb, moviezguru, multimovies, rareanimes, rogmovies, ssrmovies, vegamovies, world4ufree) | empty signature; not counted as divergence |
| `source_site` | 12 (incl. 10xflix, 9xmovies, filmyzilla, hdhub4u, hindilinks4u, katmoviehd, world4ufree) | site taken from the database file name |
| `raw_meta` | 17 | subtitle evidence unavailable; audio only |
| `canonical_key` | 1 (`mp4moviez`) | skipped, named in the report |

Divergence is normalized in Python: `Hindi, English` and `English/Hindi` are one audio set;
SQL's `COUNT(DISTINCT languages)` would call them different.

## The three deliverables — not yet answered

1. **Keys across more than one `source_site` with divergent audio** — count pending the corpus pass.
2. **How many of those carry a flagged and a clean row** — pending; this is the number that decides
   whether the adult-twin leak is a mis-keyed dub or a real adult work.
3. **Recommendation** — the structural part is already decidable and does **not** depend on the
   counts: `title+year` is a **work** key, not a **print** key, so no re-key of the 69,773-row
   ledger is warranted. The ledger already carries per-print identity without a new key:
   `posts.url` / `slug` (one row per print), `raw_meta.subjectId`/`detailPath` on themoviebox rows
   (the importer now stamps the id — task #44), `languages` and `releases.audio_languages` as the
   semantic discriminator, and `is_18_plus` as the per-row flag the public surface must reconcile
   per key (`MAX(is_18_plus)`), as root `AGENTS.md` already prescribes. The counts decide one thing
   only: whether the reconcile rule hides *works* (the twin is the same film) or must stay
   per-print (a dubbed family film sharing a key with an unrelated adult title). This session does
   not guess that answer.

## The exact heavy command, and its measured cost

```bash
nice -n 19 python3 -S Fast_Fetch/importers/test_dub_collision_census.py --census
# exits 2 and names every database it did not reach if load1 >= 4.0
```

Measured cost so far: a full-scan `GROUP BY canonical_key` over the 16,943-row filmyhit database
took **12.0 s** at load 0.91 on this 1-vCPU box. The two-phase census replaces that with covering-
index reads of ≈340k keys across 39 databases plus point lookups for colliding keys only; the
end-to-end figure will be measured when the hold lifts (estimate 1–3 min, single core, `nice 19`).

## Unrun checks

- `test_docs_invariants.py` — **not run**: the HOLD forbids python. The checkpoint count in
  `CONTINUITY.md` was bumped 52 → 53 and this file was indexed in `checkpoints/README.md`, which is
  what the suite checks.
- The census itself — not run: load 9.81–12.5 throughout; the gate is binding.

## Gate log (load1 / MemAvailable / SwapFree)

| when | load1 | MemAvailable | SwapFree | action |
|---|---|---|---|---|
| session start | 0.91 | 6,268 MB | 3,470 MB | OK band, schema probes only |
| after filmyhit probe | 5.18 | — | — | stopped scans |
| mid-design | 6.35 | — | — | stopped scans |
| before live pass | 9.81 | 4,688 MB | 3,152 MB | refused; wrote module and report |
| HOLD from qoder1 | 12.5 | — | — | no execution; commit + push only |

## Supervisor pass, 2026-10-31 — landed, CI-gated, numbers queued

qoder1 landed this branch on trunk as **`a424ffc`** (merge of `b37b74c`; 13 tests OK, read-only,
stdlib only) and asked for three things: a backend-CI step for the module, the three headline
numbers, and the merge-step recommendation stated plainly. The step and the recommendation are in
this commit. **The numbers were not taken.**

### Why the numbers are still missing

The ceiling moved down while the box was busy: the first check this session read **3.25**, the
next read one minute later was **4.83**, and the supervisor's standing rule for this pass is
"no test suite, python run or build while load ≥ 3.5". The module's own gate refuses at load ≥ 4
(`run_census`, exit 2) and that refusal is correct; the supervisor's rule is stricter. Nothing was
run — no python, no sqlite, no test suite, no build. Editing and reading only.

### The queued action — exact command, cost, and the numbers wanted

```bash
cd /tmp/q2_collide        # any worktree at trunk; never /opt/radd-stream
nice -n 19 python3 -S Fast_Fetch/importers/test_dub_collision_census.py --census \
  > /tmp/q2_census_20261031.json
# exit 0: whole corpus read. exit 2: the load gate stopped it and
# `stopped` names the databases it did not reach — a partial run, not a result.
```

Cost: 39 one-per-site vaults, ≈340k keys read through the covering index on `canonical_key`, then
point lookups of `languages`/`is_18_plus` only for keys present in two or more databases. The nearest
measured comparable is a 12.0 s full-scan `GROUP BY canonical_key` over the 16,943-row filmyhit
vault at load 0.91 — this design does strictly less work per row, so the estimate is **1–3 minutes,
single core, one database at a time, `nice -n 19`**; the run itself reports `wall_seconds`.

Numbers wanted, by their keys in the JSON report:

1. `keys_across_more_than_one_site` and `divergent_keys_across_sites` — deliverable 1 (a key naming
   two prints across vaults).
2. `divergent_keys_with_flagged_and_clean_rows` — deliverable 2; the adult-twin share is that count
   over `divergent_keys` (and over `divergent_keys_across_sites` when the collision is cross-site).
3. `examples` (up to 15, ordered divergent-then-flagged first) — the concrete pairs, with each key's
   `language_sets`, `sites` and `flagged`/`unflagged` counts.
4. `stopped` must be `null` before any of the above is quoted as a corpus number, and
   `databases_skipped` must be read — `mp4moviez.db` (29,850 rows) predates `canonical_key` and is
   skipped, so the corpus is the key-carrying vaults only.

### The merge-step recommendation, stated once and plainly (for qoder3)

This is the finding that retires the staging-time framing of the launch gate.

1. **`canonical_key` is a work key, not a print key — and that is not a defect.** Title+year names
   the work; the public URL space, every importer and all 69,773 ledger rows are derived from it.
   Re-keying would be a migration across the whole catalog to fix a collision that is not at the key.
2. **A dub twin cannot exist inside a staging vault.** Measured DDL: themoviebox and filmyhit declare
   `canonical_key TEXT PRIMARY KEY`; hindilinks4u and world4ufree declare `UNIQUE`. A second subject
   with the same title+year is refused or collapses onto the first row. So "the scraper mis-keyed the
   dub print" is the wrong frame — the vault physically cannot hold both prints.
3. **The collision is therefore a merge-time and read-time phenomenon**, appearing exactly when two
   vaults contribute rows for one key — the 442-key shape already documented in root `AGENTS.md`.
   The question for the merge is not "should title+year change" but "what happens when a second vault
   brings a different print under an existing key".
4. **The adult half of the rule is in code, not just on paper.** `inherit_key_adult`
   (`Fast_Fetch/fast_fetch.py:612`) flags every row sharing a key and runs inside the write
   transaction that sets a flag (`fast_fetch.py:4666`); `merge_catalogs.py:337` writes through
   `save_scraped_data`, so a twin merging under a flagged print is flagged by the same statement.
   `adult_key_exposures` is the read-only audit and `reconcile_key_adult` the backfill, and
   `test_redact.py:996` proves the search route stops serving the unflagged twin after reconcile.
   No staging schema change, no new column, no re-key.
5. **What already separates the prints, without a new ledger field:** `posts.url` / `slug` (one row
   per print per site), `post_sources` (the merge records every page that fed a post, so a twin's
   URL survives as a source row instead of overwriting), `raw_meta.subjectId` / `detailPath`
   (themoviebox; task #44 now stamps the id), and per-release audio — `merge_catalogs.py:100` maps
   `audio_languages` into `releases.languages`. **One concrete merge recommendation:** a same-key row
   whose audio set differs must contribute its audio at release granularity, because the post-level
   `posts.language` is COALESCE-first (a non-empty value is never overwritten), so a dub absorbed into
   an existing post row would otherwise lose its only print-level discriminator.
6. **What the counts still decide — exactly one thing:** whether hiding by `MAX(is_18_plus)` per key
   hides *works* (correct when the twin is the same film) or must stay per-print (wrong if an
   unrelated adult title shares a key with a clean family film). The query is built to answer that;
   the quiet window is the only thing outstanding.

### CI

`.github/workflows/backend-ci.yml` now runs the module's offline suite (header list + `🧪` step, in
the file's existing style). The workflow's `paths:` filter is `Fast_Fetch/**`, which covers
`Fast_Fetch/importers/` — the step is fed. `--census` is deliberately not in CI, same reason as
`test_adult_twin_probe.py`: the hosted runner is not allowed to decide when a heavy staging read is
polite.

