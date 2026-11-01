# 📊 Adult Vault Census — 2026-11-01 (the #37 run, and the 18 sidecar pairs it did not touch)

Executed under the 2026-11-01 owner ruling: *"skip the vaults with 0-byte wal/shm debris, do not
delete debris, work the other 5 only and list skipped vaults"* and *"18 stale pairs: do not delete,
list them only, continue without deleting."* Nothing here is a write: every vault was opened
`mode=ro`, no sidecar was deleted, and no production path was touched.

Tool: [`adult_vault_census.py`](adult_vault_census.py) at `4c59864` (`--tier ABC --budget 2400`).
Command form for the next lane: `python3 -S Fast_Fetch/adult_vault_census.py --tier ABC --budget 2400`.

---

## 1. What was counted

`complete: true`, `elapsed: 26.0 s`, `skipped: []`. Five vaults, 595.9 MB, all with
`size_delta_vs_pricing: 0` — the files that were priced at 08xx are the files that were counted.

| vault | tier | size | rows | flagged | % flagged | keys_both | s |
|---|---|---|---|---|---|---|---|
| hindilinks4u.db | A | 62.1 MB | 26,152 | 988 | 3.78% | 0 | 6.5 |
| filmyhit.db | A | 70.6 MB | 16,943 | 117 | 0.69% | 0 | 3.8 |
| kisskh.db | A | 78.1 MB | 669 | 10 | 1.50% | 0 | 2.0 |
| moviesmela.db | B | 183.7 MB | 16,677 | 19 | 0.11% | 0 | 13.3 |
| toonworld4all.db | B | 201.4 MB | 932 | 17 | 1.82% | 0 | 0.4 |
| **total** | | **595.9 MB** | **61,373** | **1,151** | **1.88%** | **0** | **26.0** |

`keys_both` is the count of distinct non-empty, non-`unknown` `canonical_key` values that carry both
a flagged and an unflagged row; `rows_on_exposed_keys` / `flagged_rows_on_exposed_keys` (also 0 in
all five) are the rows those keys own. **Zero in every vault re-measures, on real data, the 05xx
finding: the flagged/unflagged key collision that leaves 455 adult works reachable under an
unflagged twin is created by the merge, not by any scraper.** Fixing it belongs to the merge step,
not to a `WHERE` clause in a public route.

## 2. What was barred, and what is still unknown

Twelve priced vaults carry a 0-byte `-wal` and a 32,768-byte `-shm`, no `-journal`. Per the ruling
they are listed, never opened, and the debris is left alone:

| vault | tier | bytes |
|---|---|---|
| 7starhd.db | A | 90,001,408 |
| hdhub4u.db | B | 122,228,736 |
| katmoviehd.db | B | 125,546,496 |
| rareanimes.db | B | 125,554,688 |
| rogmovies.db | C | 157,319,168 |
| 10xflix.db | C | 212,877,312 |
| bolly4u.db | C | 225,685,504 |
| ssrmovies.db | C | 284,966,912 |
| multimovies.db | C | 349,741,056 |
| vegamovies.db | C | 364,945,408 |
| 9xmovies.db | C | 548,896,768 |
| world4ufree.db | C | 840,065,024 |
| **barred_bytes** | | **3,447,828,480** |

Two more rows are lineage, not sites: `katmoviehd_refreshed.db` (125,571,072 B) of `katmoviehd.db`,
and `multimovies_full_20261022.db` (435,691,520 B) of `multimovies.db`; counting both members of a
pair spends 561,262,592 B twice for the same works. Twenty-six `.db` files on disk are unpriced
(`unpriced_on_disk`), including `themoviebox.db`, `filmywap.db`, and `desicinemas.db` — those have no
tier row and no cost, and are named rather than ignored.

**So the adult-flag census covers 595.9 MB of a 4.6 GB staging corpus, and 61,373 rows of it. The
flag counts for 3.45 GB — the entire tier-C set — are still unknown, and are unknown by ruling, not
by outage.** What is known about them: their schema carries the flag column and no index over it
(priced 08xx), their aggregate size, and that they are byte-identical to their 08xx pricing except
that a sidecar sits beside each.

## 3. The 18 stale sidecar pairs (listed; nothing deleted)

Every one of the 18 pairs has the identical shape: `-wal` **0 bytes**, `-shm` **32,768 bytes**, **no
`-journal` anywhere in the directory**, and `fuser` over all 36 sidecar files finds **no holder**.
The `-wal` mtimes run 04:51:10 → 04:51:59 — 18 writes 49 seconds apart, one lane opening these
vaults read-write and exiting uncleanly. A 0-byte `-wal` means no un-checkpointed frame, so the main
database file is not hiding recent content; it is the `-shm` that proves no process is attached and
still alive.

| vault | db bytes | db mtime | -wal | -wal mtime | -shm | -shm mtime |
|---|---|---|---|---|---|---|
| 10xflix.db | 212,877,312 | 10-24 01:57:07 | 0 | 04:51:10 | 32,768 | 08:24:55 |
| 7starhd.db | 90,001,408 | 10-24 01:55:42 | 0 | 04:51:13 | 32,768 | 08:24:56 |
| 9xmovies.db | 548,896,768 | 10-24 01:56:38 | 0 | 04:51:15 | 32,768 | 08:24:56 |
| bolly4u.db | 225,685,504 | 10-24 01:57:03 | 0 | 04:51:18 | 32,768 | 08:24:57 |
| desicinemas.db | 7,643,136 | 10-24 02:13:48 | 0 | 04:51:20 | 32,768 | 05:57:45 |
| filmyzilla.db | 33,665,024 | 10-24 01:12:07 | 0 | 04:51:28 | 32,768 | 05:53:02 |
| hdhub4u.db | 122,228,736 | 10-24 00:30:21 | 0 | 04:51:29 | 32,768 | 08:24:58 |
| hdtvb.db | 32,059,392 | 10-24 02:13:43 | 0 | 04:51:30 | 32,768 | 05:55:35 |
| katmoviehd.db | 125,546,496 | 10-24 00:20:30 | 0 | 04:51:35 | 32,768 | 08:24:58 |
| katmoviehd_refreshed.db | 125,571,072 | 10-24 22:29:51 | 0 | 04:51:37 | 32,768 | 08:24:59 |
| moviezguru.db | 47,370,240 | 10-24 02:13:50 | 0 | 04:51:41 | 32,768 | 05:48:26 |
| multimovies.db | 349,741,056 | 10-21 21:47:11 | 0 | 04:51:44 | 32,768 | 08:25:00 |
| multimovies_full_20261022.db | 435,691,520 | 10-22 02:01:33 | 0 | 04:51:45 | 32,768 | 08:25:01 |
| rareanimes.db | 125,554,688 | 10-26 17:43:05 | 0 | 04:51:48 | 32,768 | 08:25:01 |
| rogmovies.db | 157,319,168 | 10-21 21:47:43 | 0 | 04:51:50 | 32,768 | 08:25:03 |
| ssrmovies.db | 284,966,912 | 10-21 21:47:43 | 0 | 04:51:53 | 32,768 | 08:25:03 |
| vegamovies.db | 364,945,408 | 10-24 00:36:38 | 0 | 04:51:57 | 32,768 | 08:25:05 |
| world4ufree.db | 840,065,024 | 10-24 01:12:24 | 0 | 04:51:59 | 32,768 | 08:25:05 |

14 of the 18 are priced (12 counted-as-barred, 2 held as lineage); 4 — `desicinemas`, `filmyzilla`,
`hdtvb`, `moviezguru` — are among the 26 unpriced names. **The `-shm` mtimes (08:24–08:25) are later
than the `-wal` mtimes (04:51), which is what a *read-only* open of a WAL-mode database does to the
shared-memory file when no other process holds it** — so at least one lane has been through these
files since 04:51 without clearing the debris. Deleting the pair is a recovery decision for whoever
owns those vaults; this census prints the inventory and moves on.

## 4. The cost model in the pricing pass is wrong about its own unit

The 08xx plan priced a walk at **0.9–5.0 s per file MB**, which projected these 595.9 MB into
**536–2,980 s**. The walk took **26.0 s** — between 20× and 115× cheaper than the quoted window.

The unit is wrong. File bytes include indexes, free pages, and tables the census never reads; the
thing it actually reads is `posts`. `toonworld4all.db` is the proof: the second-largest admitted
file (201.4 MB) with the third-fewest rows (932) took **0.42 s**, while `kisskh.db` (78.1 MB, 669
rows) took 2.03 s. Per-row time still ranges 330–4,470 rows/s across the five, because a row's cost
is its text, so neither bytes nor row count is the right predictor — but bytes are demonstrably not
it, and they were the only input the pricing pass had.

**Consequence for the 3,447,828,480 barred bytes:** the published tier estimates (tier C 69–384
CPU-min for the whole corpus) were built on the same wrong unit. At the *measured* aggregate rate of
this run (26.0 s / 595.9 MB = 0.044 s/MB) the barred set would cost **~150 s**, not tens of minutes.
That is an extrapolation from five vaults and it is not a window request — it is a correction to the
number the next lane will be quoted. A rate proved on one vault with a `releases`-shaped schema
would settle it; the classification rule is already in the code either way.

## 5. Reproducing this

`run()` refuses rather than reporting a shorter success: a vault that moves under the walk, or a
sidecar that *appears* during it, aborts the whole census (`assert_untouched`). The pre-open
sidecar check bars a vault and continues, which is the ruling; the mid-walk check is a live co-writer
and stays a walk-ender. `FORBIDDEN` names the merged production catalog and every `*_readonly.db`
snapshot, so no argument form reaches a production file. Suite:
[`test_adult_vault_census.py`](test_adult_vault_census.py) (`SidecarRulingTests` pins that a barred
vault is never opened — its body is replaced with non-SQLite bytes in the fixture — and that the
debris still exists after the run).
