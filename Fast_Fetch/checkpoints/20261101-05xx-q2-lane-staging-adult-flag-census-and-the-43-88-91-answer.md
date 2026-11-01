# q2 — staging adult-flag census, and what `43 / 88 / 91` actually was

**Lane:** qoder2 (`q2-admin-auth-upgrade`). **Base:** trunk `6014dd5`. **Host time:**
2026-11-01 05:18 → 05:45. **Ownership, so nobody re-litigates it at 06:00:** q5 owns the
adult *code* (`redact.py`, the flag derivation, the reconciliation); **q2 owns the
*count***. Nothing in this file changes behavior — every query was `mode=ro` and no
statement but `SELECT` was issued.

## Method, and the one rule it was bounded by

One pass per file, four numbers, `sqlite3.connect("file:…?mode=ro", uri=True)`, table
`posts`, with the `canonical_key` columns dropped when a vault does not have them:

```sql
SELECT (SELECT COUNT(*) FROM posts),
       (SELECT COUNT(*) FROM posts WHERE is_18_plus=1),
       (SELECT COUNT(DISTINCT canonical_key) FROM posts),
       (SELECT COUNT(*) FROM (SELECT canonical_key FROM posts GROUP BY canonical_key
          HAVING SUM(is_18_plus=1)>0 AND SUM(is_18_plus=0)=0)),      -- keys_all_flagged
       (SELECT COUNT(*) FROM (SELECT canonical_key FROM posts WHERE canonical_key<>''
          GROUP BY canonical_key HAVING SUM(is_18_plus=1)>0 AND SUM(is_18_plus=0)>0))  -- keys_both
```

`keys_both` excludes empty keys on purpose: `''` is what an un stamped row carries, and it is
not an identity. The first version of this census ran all ~40 vaults inside one unbuffered
process and lost **every** number to a 900 s timeout. This version prints per file with a
measured `seconds`, which is also the only honest way to price the remainder below. Excluded,
because they are not staging vaults: `merged_catalog_20261025.db` and
`preapply_20261029_1726.db` (6.1 GB each, the production catalog and its pre-apply copy),
`fast_fetch.db` (a symlink into the merged catalog), `user_state.db`, `resolvers.db`.

## The census — 25 files, 05:18–05:35, machine at load 9.13 / `cpu some avg10=99.96`

| file | rows | flagged | distinct keys | keys_all_flagged | **keys_both** | s |
|---|---|---|---|---|---|---|
| `moviezguru.db` | 3,386 | 97 | 3,386 | 97 | 0 | 46.9 |
| `pagalmovies.db` | 6,846 | 393 | 6,846 | 393 | 0 | 38.3 |
| `filmiyin.db` | 3,837 | 21 | 3,837 | 21 | 0 | 35.6 |
| `mp4moviez_staging.db` | 11,403 | **43** | 11,403 | 43 | 0 | 67.6 |
| `mp4moviez_staging2.db` | 11,404 | **43** | 11,404 | 43 | 0 | 84.9 |
| `filmyzilla.db` | 15,228 | 423 | 15,228 | 423 | 0 | 153.8 |
| `hdtvb.db` | 3,774 | 1,161 | 3,772 | 1,159 | **2** | 31.1 |
| `mp4moviez.db` | 29,848 | **91** | *no column* | — | — | 73.3 |
| `5movierulz.db` | 442 | 2 | 442 | 2 | 0 | 19.4 |
| `moviecok.db` | 1,738 | 4 | 1,738 | 4 | 0 | 3.7 |
| `animahd.db` | 232 | 0 | 232 | 0 | 0 | 2.8 |
| `desicinemas.db` | 5,223 | 7 | 5,223 | 7 | 0 | 0.6 |
| `aryplus.db` | 481 | 0 | 481 | 0 | 0 | 0.5 |
| `dramacool.db` | 544 | 2 | 544 | 2 | 0 | 3.6 |
| `bollyflix.db` | 38 | 9 | 38 | 9 | 0 | 0.0 |
| `filmywap.db` | 80 | 2 | 80 | 2 | 0 | 0.1 |
| `kuttymovies.db` | 900 | 3 | 900 | 3 | 0 | 0.1 |
| `moviehax.db` | 35 | 17 | 35 | 17 | 0 | 0.0 |
| `levidia.db` | 147 | 0 | 147 | 0 | 0 | 0.1 |
| `humtv_staging.db` | 64 | 0 | 64 | 0 | 0 | 0.0 |
| `desiserials.db` | 34 | 0 | 34 | 0 | 0 | 0.0 |
| `hindidubbedmovies.db` | 40 | 0 | 40 | 0 | 0 | 0.0 |
| `hindianimeszone.db` | 36 | 1 | 36 | 1 | 0 | 0.0 |
| `themoviebox.db` | 44 | 0 | 44 | 0 | 0 | 0.0 |
| `fast_fetch_old_7mb_backup.db` | `REFUSAL OperationalError: unable to open database file` | | | | | |

## `43 / 88 / 91` — one definition, three generations of the same site

Not three definitions, and not a conflict to reconcile. All three are
`COUNT(*) … WHERE is_18_plus=1` over mp4moviez data:

| number | file | table | query | count | status |
|---|---|---|---|---|---|
| **43** | `mp4moviez_staging.db` (11,403 rows) *and* `mp4moviez_staging2.db` (11,404) | `posts` | `COUNT(*) WHERE is_18_plus=1` | 43 | **measured here, twice** |
| **91** | `mp4moviez.db` — the legacy vault, 29,848 rows | `posts` | same | 91 | **measured here** |
| **88** | *no file on this host* | — | the 10-29 measured **conversion** run: 28,066 works / 54,267 releases / 54,267 sources / 88 adult rows | 88 | **not reproducible** |

`88` is quoted from `Fast_Fetch/checkpoints/20261029-2026-10-29-session-mp4moviez-becomes-mergeable-and-a-fleet.md:50`
and carried into `20261101-01xx-q3-lane-premerge-copy-plan-queued-not-run.md:50`. It counted
the **output of the converter** — a 28,066-work generation that was never landed as a vault.
The vault on disk holds 11,403 posts, not 28,066. So `88` measures a generation of the
pipeline, `91` measures the legacy table it read, and `43` measures the stale vault that
exists now.

**Retire `88` as a current fact.** It is a historical measurement of an artifact no longer on
disk; citing it next to a live count compares a run to a file. `43` and `91` both stand, and
they differ because the files differ: the legacy table carries 2.6× the rows and 2.1× the
flags of the vault.

**What the difference of 48 does *not* license.** It is tempting to read `91 − 43 = 48` as
"48 flagged rows were lost", and this census does not establish that. The two files are
different generations, not two counts of one set: the legacy table is 29,848 posts, the vault
11,403, and the 10-29 conversion output was 28,066 works — so the vault on disk is neither the
legacy table nor that conversion. To show a flagged work went missing you would need a
row-level comparison, and the one column that would make such a comparison meaningful,
`canonical_key`, **does not exist in `mp4moviez.db`**. So this lane names the gap and cannot
close it: the numbers are right, and the arithmetic between them is not a measurement.

## The finding that is not about mp4moviez

**`keys_both = 0` in every staging vault except one.** 24 of 25 files have
`distinct keys == rows` — inside a single site, `canonical_key` is unique per row, so a key
cannot hold both a flagged and an unflagged row. `hdtvb.db` is the sole exception: 3,774 rows
over 3,772 keys, and 2 keys carrying both.

That is directly relevant to the standing prose in root `AGENTS.md`, which says 442 distinct
`canonical_key` values contain both a flagged and an unflagged row, so 455 flagged works stay
reachable. **This census cannot reproduce 442 from any staging vault, and it should not be
expected to: the collision is created by the merge, not by the scrape.** It appears when two
sites' rows for the same film are unioned into one key — one site labels the work adult, the
other does not. Two consequences for whoever owns the adult code:

1. A per-vault `WHERE` clause cannot fix this, because per-vault there is nothing to fix. The
   reconciliation belongs in `merge_catalogs.py` (and in any re-merge), as a
   `MAX(is_18_plus)` over `canonical_key` — which is exactly the shape `AGENTS.md` asks for.
2. The one place the number *can* be measured is the merged catalog — 6.1 GB, a live write
   target, and the file the owner's hazard note protects. Not counted here, deliberately, and
   named below as the missing number rather than guessed at.

## Cost, and what is unfunded

Measured throughput on this box at this load: **0.9–5.0 s per MB** of vault, worst case on the
one file with no index on `canonical_key` (`filmyzilla.db`: 153.8 s for 33 MB).

**19 files, 4.3 GB — **MiB**, the sizes below summed — measured in decimal bytes as 4,605,050,880 B = 4.61 GB by `st_size`, the same quantity in a different unit, not a stale number, not run: `world4ufree` 801M, `9xmovies` 523M, `multimovies_full_20261022`
416M, `vegamovies` 348M, `multimovies` 334M, `ssrmovies` 272M, `bolly4u` 215M, `10xflix` 203M,
`toonworld4all` 192M, `moviesmela` 175M, `rogmovies` 150M, `katmoviehd_refreshed` 120M,
`rareanimes` 120M, `katmoviehd` 120M, `hdhub4u` 117M, `7starhd` 86M, `kisskh` 75M,
`filmyhit` 67M, `hindilinks4u` 59M.**

Projected **73–366 CPU-minutes** of `GROUP BY canonical_key` scans. That is heavy work under
the owner's freeze (`cpu some avg10` read 99.96 at 05:45; the 06:1x state puts it back at
load1 5.53 and keeps HEAVY frozen), so it is blocked, not skipped silently.

The estimate should not be read as one uniform rate, and the reason is an index. Three files
were inspected for a `canonical_key` index: `world4ufree.db` **has** `idx_w4u_canonical`,
`themoviebox.db` **has** `idx_themoviebox_posts_key`, and `filmyhit.db` has only `slug` and
`media_type` — no key index. A grouped scan over an indexed key is an index walk; over an
unindexed 33 MB table it sorted at 153.8 s (`filmyzilla.db`, the worst number in the table
above, ~4.7 s/MB against ~0.9 s/MB for the indexed or tiny files). So the expensive half of
that list is whichever of the 19 are unindexed, and the cheap way to finish this census is to
check `sqlite_master` for the index first and run the indexed files before the rest. **Done in the 08xx pricing pass** (`20261101-08xx-q2-lane-vault-pricing-no-cheap-count-and-the-plan-that-follows.md`): all 19 have `canonical_key`, 16 of them a key index, and **none has an index over the flag column**, so `COUNT(*) WHERE is_18_plus=1` plans `SCAN posts` in every file — the cheap form of this census does not exist, and adding the index is barred because these are q3's merge inputs.

## Also verified while running this

- `mp4moviez.db` **has `is_18_plus` and no `canonical_key` column** — q3's "hard blocker",
  now measured rather than asserted: 29,848 rows and 91 flags that cannot be reconciled by key
  at all, only through the converter.
- `fast_fetch_old_7mb_backup.db` refuses: `REFUSAL OperationalError: unable to open database
  file`. Reported verbatim; not repaired, and not counted.
- `bash -lc 'echo $RADD_DB_PATH'` → empty; resolved `config.DB_PATH` from this worktree is
  `/tmp/q2_admin_auth/Fast_Fetch/fast_fetch.db`. No ingest, sync, merge or repair ran tonight,
  so the production path was never a write target from this lane.
- `radd-backup-hf` **failed at 05:47:16** on `TimeoutStartSec=2h` (first failure in four
  nights; last good snapshot Oct 31 05:13), so there is no off-box copy of tonight's catalog.
  The kill stranded 22 GB of VACUUM snapshots in `/tmp/tmpjbp1_4w9` (mode 0700, contains
  `user_state.db`). **Untouched by this lane** — not deleted, not listed, not written to; it is
  evidence and the owner's call. This lane's only `/tmp` writes were small text files
  (census scripts and their output, all well under 1 MB), and no further `/tmp` scratch of any
  size is planned while that directory is evidence.
