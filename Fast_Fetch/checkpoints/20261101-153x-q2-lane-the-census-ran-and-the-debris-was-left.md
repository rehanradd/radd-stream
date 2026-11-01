# [Q2-THE-CENSUS-RAN] 2026-11-01 15:3x — q2 lane, #37 executed under the sidecar ruling; 5 vaults, 61,373 rows, 26.0 s, 3.45 GB left unread by order

Tag: `[Q2-THE-CENSUS-RAN]`. Lane: q2 (`/tmp/q2_admin_auth`, branch `q2-census-pricing`).
Slice: owner ruling (1) sidecar 37, ruling (2) the 18 stale pairs.
Nothing here is a production write: every vault opened `mode=ro`, no sidecar deleted, no service
touched, no tag, no merge, no test module run locally (the freeze stands; CI judges the code).

## The ruling, and the thing it made possible

The 09:07 rule — "a `-wal`/`-shm`/`-journal` beside a vault aborts the census" — taken literally made
#37 **unrunnable forever**, because 14 of 19 priced vaults have had debris beside them since 04:51.
The owner's answer was not to relax it but to classify it: *a pre-existing sidecar bars that vault,
it does not bar the walk; work the five that are clean, list what you skipped, delete nothing.* That
is now `sidecar_state()` + a bar check in `run()` (`4c59864`), placed **after** the existence check
and **before** the budget check, so a barred vault consumes no budget and no open, and `complete`
means "everything the ruling admitted was counted" rather than "everything in the plan was".

The distinction that survives the ruling is the one that matters: a sidecar found **before** we open
is another lane's crash artifact — name it, leave it. A sidecar that **appears while this process
counts** is a live co-writer, and `assert_untouched` still ends the whole walk. The suite pins both
halves, including that the barred vault is never opened by replacing its body with
`b"this is not a sqlite file"` and asserting no refusal, then that `-wal` and `-shm` still exist
after the run.

## What is now measured, for the first time on real data

`--tier ABC --budget 2400` → `complete: true`, `elapsed: 26.0`, `skipped: []`, and all five admitted
vaults at `size_delta_vs_pricing: 0` (the files priced at 08xx are the files counted).

| vault | tier | size | rows | flagged | keys_both | s |
|---|---|---|---|---|---|---|
| hindilinks4u | A | 62.1 MB | 26,152 | 988 | 0 | 6.5 |
| filmyhit | A | 70.6 MB | 16,943 | 117 | 0 | 3.8 |
| kisskh | A | 78.1 MB | 669 | 10 | 0 | 2.0 |
| moviesmela | B | 183.7 MB | 16,677 | 19 | 0 | 13.3 |
| toonworld4all | B | 201.4 MB | 932 | 17 | 0 | 0.4 |
| **total** | | **595.9 MB** | **61,373** | **1,151** (1.88%) | **0** | **26.0** |

**`keys_both` = 0 in all five** re-measures, on production-shaped vaults, what #35 derived from a
subset: the flagged/unflagged `canonical_key` collision that leaves 455 adult works reachable under
an unflagged twin is **merge-created, not scrape-created**. So the fix is `MAX(is_18_plus)`
reconciliation across every row sharing a key at merge time — not a further `WHERE` clause in a
public route, which is what AGENTS.md keeps asking for and what would not close it.

What is **not** known, and is unknown by ruling rather than by outage: the flag counts for the
12 barred vaults (**3,447,828,480 B**, the whole tier-C set), 2 lineage files (561,262,592 B), and
26 unpriced `.db` names on disk including `themoviebox.db`, `filmywap.db`, `desicinemas.db`. Full
table: [`../ADULT_VAULT_CENSUS_20261101.md`](../ADULT_VAULT_CENSUS_20261101.md).

## The 18 pairs, listed and left alone (ruling 2)

Identical shape in all 18: `-wal` **0 B**, `-shm` **32,768 B**, **no `-journal` in the directory at
all**, `fuser` over all 36 sidecar files finds **no holder**. `-wal` mtimes 04:51:10→04:51:59, i.e.
18 opens 49 s apart by one lane that exited uncleanly.

Two details worth recording because they change the reading. **`-shm` mtimes are 08:24–08:25, later
than the `-wal` writes** — that is what a read-only open of a WAL database does to the shared-memory
file when nothing else holds it, so at least one lane has passed through these vaults *after* the
crash without clearing it; whoever expects "the debris is old" to be true should look at those two
timestamps. And the set is **14 priced + 4 unpriced** (`desicinemas`, `filmyzilla`, `hdtvb`,
`moviezguru`), of which 12 were barred as count targets and 2 held as lineage — so the sidecar
footprint and the census footprint are not the same list, and a lane that assumes they are will
report coverage it does not have.

Nothing was deleted. Deleting a WAL sidecar is a recovery decision owned by whoever wrote it; a
0-byte `-wal` means no un-checkpointed frame, so the main files are not hiding recent content — that
is the evidence the owner needs to decide it, and it is now on the record either way.

## The cost model's unit is wrong, and it is 20–115× off

The 08xx plan priced a walk at **0.9–5.0 s per file MB** → these 595.9 MB projected to
**536–2,980 s**. The walk took **26.0 s**. The driver is not the file: it is `posts`.
`toonworld4all` is the proof — the second-largest admitted file, 932 rows, **0.42 s**, while
`kisskh` at a third its size took 2.03 s. Per-row time still spreads 330–4,470 rows/s, because a
row's cost is its text, so row count is not the right unit either — but bytes were the only input
the pricing pass had, and they are demonstrably not it.

Consequence, stated as an extrapolation and not as a window request: at this run's measured aggregate
(0.0436 s/MB) the 3,447,828,480 barred bytes would cost **~150 s**, against the published tier
figures that come out in tens of CPU-minutes. The next lane quoted a 9–50 minute census for work that
on this evidence is a sub-three-minute one, and the correction is cheap to prove: one vault with a
known row count, counted, and the unit is settled. It is not settled here, because five vaults with
three different row densities is a correction to a number, not a model.

## Where #18 stands, and why I did not start it

Ruling (4) says run #18 with the head-pass staging decision recorded. Load on this box at 15:38 read
`4.43, 5.28, 4.59` — not a sub-4 window, and #18's rebuild reads a 6.4 GB ledger and keeps every row
alive in `_WorkAccumulator.posts`, so its cost is resident memory that no plan-only pass can size.
The decision itself is writeable now (see the next checkpoint when it is taken): **do not refactor
`catalog_v2.project` to stream; run it as-is with peak RSS sampled live, and let the sample be the
number** — because a refactor of the projection is a bigger freeze-breaking change than measuring it,
and `price_projection.py` already says the memory shape is ~1.01× retained text. That is the
recording to do, and the run waits on the window, not on me.

## Handoffs

- **q3 (merge owner):** `keys_both` = 0 in every clean vault; the 455-work exposure is merge-created,
  so the reconciliation belongs in `merge_catalogs.py` and its guard must not be re-baselined by an
  index on `is_18_plus` (still barred — it rewrites a merge input's size+mtime and trips C2).
- **Whoever owns those vaults:** 18 pairs listed above; `fuser` shows no holder, no `-journal` exists,
  every `-wal` is 0 B. The debris is yours to decide, not mine to delete. Note the 08:2x `-shm` times.
- **Owner:** the census covered 595.9 MB of 4.6 GB by ruling. If the tier-C numbers are wanted, the
  corrected unit says ~150 s of read-only walk once the sidecar question is decided, not 285 CPU-min.
