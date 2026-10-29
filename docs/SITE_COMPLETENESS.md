# Site completeness — what the staging vaults actually contain

Measured 2026-10-30, 02:49 → 03:12 host time, by the q2 lane, at the request of
qoder4 (task #38's follow-up, "site-by-site completeness audit"). Every number
below was read from the vault files on disk; none of it is inferred from
CONTINUITY prose or from a site's importer.

## How this was measured

- **49 `.db` files** under `/home/ubuntu/radd-stream-data/`, one at a time, in
  ascending size order, `nice -n 10 ionice -c3`, single-threaded.
- Every connection was opened read-only:
  `sqlite3.connect("file:<path>?mode=ro", uri=True)`. Nothing was written,
  VACUUM'd or ANALYZEd; `merged_catalog_20261025.db` and
  `preapply_20261029_1726.db` were never counted (see the P rows).
- Every query carried a SQLite progress-handler deadline — 8 s in pass 1, 15 s
  in pass 2. A query that could not finish inside the budget is reported as
  **deferred**, never retried harder. This is the same dead-man rule the
  projection rebuild works under.
- `posts w/ 0 sources` = `posts` minus the distinct posts that have at least one
  link row through `releases → sources` (or the legacy
  `download_sources`/`post_sources` tables, noted per row).
- `18+` = `COUNT(*) FROM posts WHERE is_18_plus = 1`.
- `link status` is the vault's own status mix, where its link table has a status
  column. Where the older schema has none, the cell says `no-status-column`.
  **A link row is not a playable link**; nothing here was probed.
- Pass 2 started at 03:03 and was **stopped at 03:12 under the fleet notice**
  (load 8.72). The cells it had not reached are labelled `deferred`; the exact
  command to finish them is at the bottom.
- `fast_fetch_old_7mb_backup.db` is **root-owned, mode 0600** — unreadable to
  this account. Bucket E.

## The table

| vault | posts | releases | sources | posts w/ 0 sources | 18+ | link status | last mtime | bucket |
|---|---:|---:|---:|---:|---:|---|---|---|
| 10xflix | 13775 | 76923 | 228397 | 0 | deferred | — | 2026-10-24 | A |
| 5movierulz | 442 | 3262 | 6491 | 0 | 2 | active=2658,unknown=3833 | 2026-10-28 | A |
| 7starhd | 11791 | 33369 | 115208 | deferred (legacy link tables) | 2296 | active=99627 | 2026-10-24 | A |
| 9xmovies | 12060 | 30936 | 337595 | 0 | deferred | — | 2026-10-24 | A |
| animahd | 232 | 4801 | 9575 | 0 | 0 | active=25,unverified=9550 | 2026-10-28 | A |
| aryplus | 481 | 10860 | 10860 | 45 | 0 | unverified=10860 | 2026-10-28 | A |
| bolly4u | 15192 | 41004 | 22003 | 9233 | deferred | — | 2026-10-24 | A |
| bollyflix | 38 | 91 | 91 | 0 | 9 | unverified=91 | 2026-10-29 | A |
| desicinemas | 5223 | 5285 | 4339 | 974 | 7 | no-status-column | 2026-10-24 | A |
| desiserials | 34 | 200 | 359 | 0 | 0 | active=10,blocked=2,unverified=347 | 2026-10-28 | A |
| dramacool | 544 | 9675 | 9675 | 0 | 2 | unknown=9675 | 2026-10-28 | A |
| fast_fetch | 203 | 1214 | 5823 | 0 | 2 | active=5578 | 2026-10-27 | A* |
| fast_fetch_old_7mb_backup | — | — | — | unreadable | unreadable | — | 2026-10-26 | E |
| filmiyin | 3837 | 17541 | 17541 | 0 | 21 | js_required=17541 | 2026-10-29 | A |
| filmyhit | 16943 | 25520 | 112973 | 2758 | 117 | unverified=112973 | 2026-10-29 | A |
| filmywap | 80 | 3966 | 3966 | 1 | 2 | unverified=3966 | 2026-10-29 | A |
| filmyzilla | 15228 | 46372 | 80032 | 0 | deferred | no-status-column | 2026-10-24 | A |
| hdhub4u | 11224 | 129009 | 250925 | 0 | 826 | no-status-column | 2026-10-24 | A |
| hdtvb | 3774 | 16855 | 24575 | deferred (legacy link tables) | 1161 | active=16855 | 2026-10-24 | A |
| hindianimeszone | 36 | 40 | 40 | 0 | 1 | unverified=40 | 2026-10-29 | A |
| hindidubbedmovies | 40 | 49 | 57 | 0 | 0 | unverified=57 | 2026-10-29 | A |
| hindilinks4u | 26152 | 145196 | 145196 | 0 | deferred | no-status-column | 2026-10-23 | A |
| humtv_staging | 64 | 282 | 282 | 0 | 0 | unverified=282 | 2026-10-29 | A |
| katmoviehd | 38154 | 146244 | 163972 | 3987 | 1017 | no-status-column | 2026-10-24 | A |
| katmoviehd_refreshed | 22113 | 146244 | 163972 | 2988 | deferred | — | 2026-10-24 | A |
| kisskh | 669 | 11550 | 140746 | deferred | 10 | blocked=759,js_required=5,unverified=139982 | 2026-10-28 | A |
| kuttymovies | 900 | 2530 | 2530 | 0 | 3 | unverified=2530 | 2026-10-29 | A |
| levidia | 147 | 460 | 2976 | 0 | 0 | dead=65,unknown=2911 | 2026-10-28 | A |
| merged_catalog_20261025 | 130016 | 1383752 | 3783959 | deferred | deferred | — | 2026-10-29 | P |
| moviecok | 1738 | 7065 | 7452 | 0 | 4 | js_required=13,unknown=7439 | 2026-10-28 | A |
| moviehax | 35 | 35 | 62 | 0 | 17 | unverified=62 | 2026-10-29 | A |
| moviesmela | 16677 | 20770 | 57818 | 0 | deferred | — | 2026-10-29 | A |
| moviezguru | 3386 | 7334 | 8912 | 0 | 97 | no-status-column | 2026-10-24 | A |
| mp4moviez | 29848 | 54267 | — | 16168 | 91 | - | 2026-10-27 | B-shape |
| mp4moviez_staging | 11403 | 54263 | 54263 | 666 | 43 | unverified=54263 | 2026-10-29 | A |
| mp4moviez_staging2 | 11404 | 54267 | 54267 | 666 | 43 | unverified=54267 | 2026-10-29 | A |
| multimovies | 10498 | 532649 | 667041 | deferred | deferred | — | 2026-10-21 | C* |
| multimovies_full_20261022 | 10512 | 612180 | 747958 | deferred | deferred | — | 2026-10-22 | C* |
| pagalmovies | 6846 | 9451 | 9451 | 0 | 393 | dead=23,unknown=9428 | 2026-10-29 | A |
| preapply_20261029_1726 | 130016 | 1383752 | 3783959 | deferred | deferred | — | 2026-10-29 | P |
| rareanimes | 1328 | 17419 | 53767 | 0 | 7 | no-status-column | 2026-10-26 | A |
| resolvers | — | — | — | — | — | — | 2026-10-28 | N |
| rogmovies | 7750 | 52964 | 200898 | deferred | deferred | — | 2026-10-21 | C* |
| ssrmovies | 13916 | 46153 | 685282 | deferred | deferred | — | 2026-10-21 | C* |
| themoviebox | 44 | 0 | 0 | 44 | 0 | — | 2026-10-30 | B |
| toonworld4all | 932 | 66740 | 230282 | 0 | 17 | — | 2026-10-26 | A |
| user_state | — | — | — | — | — | — | 2026-10-29 | N |
| vegamovies | 13370 | 131658 | 412260 | deferred | deferred | — | 2026-10-24 | A |
| world4ufree | 14768 | 106972 | 254340 | 90 | deferred | — | 2026-10-24 | A |

`P` = production-class copy (stamped counters from `cat_projection_meta`, nothing
counted). `N` = not a site vault. `E` = unreadable. `A*` = the production
working copy, not a site vault. `B-shape` = links stored in `releases.url`
instead of a `sources` table (see the converter). `—` = not applicable or not
measured.

## Buckets

**A — mergeable now (posts > 0, releases > 0, sources > 0, mtime ≤ 7 days):**
hindianimeszone, hindidubbedmovies, desiserials, humtv, levidia, moviehax,
kuttymovies, filmywap, bollyflix, dramacool, aryplus, desicinemas, animahd,
moviecok, 5movierulz, hdtvb, filmyzilla, mp4moviez (via `mp4moviez_staging2`),
filmiyin, pagalmovies, moviezguru, hindilinks4u, filmyhit, kisskh, 7starhd,
hdhub4u, katmoviehd (via `katmoviehd_refreshed`), rareanimes, moviesmela,
toonworld4all, 10xflix, bolly4u, vegamovies, 9xmovies, world4ufree — **35
distinct sites**.

**B — catalog-only (the MovieBox failure repeated):**

- `themoviebox` — 44 posts, 0 releases, 0 sources, **all 44 posts linkless**.
  The site publishes no playable URL (see `SITES.md` §25: `detailUrl`,
  `sniffUrl`, `sourceUrl` are `""` and `dl` is null in both the page and
  `/wefeed-h5api-bff/detail`). Even after the fix on `q2-themoviebox-links`,
  a re-crawl yields releases-per-tier and **zero** sources. Catalog-only is the
  honest state until the site exposes a stream or another host carries the work.

- `mp4moviez` (legacy file) — 29,848 posts, 54,267 releases, **no `sources`
  table**; the links sit in `releases.url` (54,267 non-empty URLs covering
  13,680 posts; **16,168 posts have none**). This is a shape problem, not a
  capture problem: `importers/convert_mp4moviez.py` already re-homes the legacy
  crawl into `mp4moviez_staging2` (54,267 sources), which is the merge
  candidate. The main file is retained for provenance only.

**C\* — stale (> 7 days) but carrying links:** rogmovies (10-21, 200,898
sources), ssrmovies (10-21, 685,282), multimovies (10-21; `multimovies_full`
10-22 with 747,958). All four are one site each: rogmovies, ssrmovies,
multimovies. They need a **refresh**, not a link pass.

**Not site vaults:** `fast_fetch` (203 posts, legacy engine DB — a working copy,
not a staging site; counted for completeness), `fast_fetch_old_7mb_backup`
(root 0600, unreadable), `resolvers` (probe bookkeeping), `user_state`
(accounts/payments), `merged_catalog_20261025` and `preapply_20261029_1726`
(production-class; stamped: posts 130,016, releases 1,383,752, links 3,783,959).

## The two numbers

### 1. How many sites are truly scraped with links

**35 distinct sites** hold posts, releases and at least one link row, and were
last written within the 7-day freshness rule. Three more (rogmovies, ssrmovies,
multimovies) hold links but are older than 7 days, so **38 site vaults on disk
carry links**. One site (themoviebox) is catalog-only.

Three corrections the number needs to be honest:

- **"Has link rows" is not "plays".** Status mixes are overwhelmingly
  `unverified` (mp4moviez_staging2 54,267; filmyhit 112,973; kisskh 139,982), or
  `unknown` (dramacool 9,675; moviecok 7,439), or `js_required` (filmiyin —
  all 17,541), or the vault is old enough to have **no status column at all**
  (hdhub4u 250,925; 10xflix 228,397; hindilinks4u 145,196; katmoviehd 163,972;
  filmyzilla 80,032; moviezguru 8,912; rareanimes 53,767; desicinemas 4,339).
  Only **7starhd** (99,627 active), **hdtvb** (16,855 active) and the small
  `fast_fetch` copy (5,578 active) show a mostly-active link set. Nothing was
  probed for this audit — no HTTP was sent.
- **The margin is zero and shrinking.** 13 of the 35 vaults were last written
  2026-10-24 00:20–02:13; they cross the 7-day line on **2026-10-31**. Without
  refreshes, tomorrow's honest answer is 22, not 35.
- Two of the 35 (`hindianimeszone` 36 posts / 40 links, `hindidubbedmovies`
  40 / 57) are small enough that "scraped" should be read literally: the
  importer works, the vault is thin.

### 2. The shortest path to 35+

It is already 35 by the measured definition, so the work is keeping it there and
then widening it — in this order, cheapest first:

1. **Refresh the 3 stale linked sites** (rogmovies, ssrmovies, multimovies).
   No code change: `import_rogmovies.py`, `import_ssrmovies.py` and
   `import_multimovies.py` all call `fast_fetch.save_scraped_data`, which writes
   `download_sources`/`post_sources`, and each has `--limit`, `--workers`,
   `--delay` (`import_multimovies.py` also has `--refresh` and `--limit-roots`).
   One bounded `--limit` run per site re-freshens 38.
2. **Refresh the 13 vaults that go stale tomorrow** (desicinemas, hdtvb,
   filmyzilla, moviezguru, hindilinks4u, 7starhd, hdhub4u, katmoviehd, 10xflix,
   bolly4u, vegamovies, 9xmovies, world4ufree). Same shape: every one of them
   has an importer in `Fast_Fetch/import_*.py` that writes link rows.
3. **mp4moviez's 16,168 linkless posts** — the converter exists
   (`importers/convert_mp4moviez.py`, read-only source → new vault); the short
   path is a re-conversion after a bounded refresh of the legacy crawl, not a
   new parser.
4. **themoviebox cannot be crawled into bucket A.** Its detail API returns
   empty URLs. Making it link-bearing requires an external resolution route
   (another host that carries the work), which does not exist tonight. Do not
   count it.

No bucket-A site needs a new importer; no bucket-B site (other than themoviebox)
needs one either. The gap is freshness and conversion, not parsing.

## Per-importer evidence (bucket B and stale only)

| site | importer | what the code does with links | path |
|---|---|---|---|
| themoviebox | `importers/import_themoviebox.py` | fetches detail pages; parses `resource.seasons[].resolutions[]` into releases and the `dl` mirror block into sources with status | site publishes no playable URL; re-crawl gains releases, not links |
| mp4moviez | first mp4moviez pass (private schema); `importers/convert_mp4moviez.py` | legacy writer put URLs in `releases.url`; converter re-homes them into `sources` | convert, then refresh the remaining 16,168 |
| rogmovies | `import_rogmovies.py` | `fast_fetch.save_scraped_data` → `download_sources` | bounded refresh |
| ssrmovies | `import_ssrmovies.py` | same, plus WP REST seeding (`--sync-api`) | bounded refresh |
| multimovies | `import_multimovies.py`, `scrape_multimovies_full.py` | `post_sources` + `save_scraped_data` | bounded refresh |

## Deferred cells, and the exact command that finishes them

Stopped at 03:12 under the fleet notice; load 8.72, single core. When load < 4:

```bash
# fills 18+ for 12 vaults, zero-source for 6, and status for 12;
# every query still bounded by the 15 s progress-handler deadline
nice -n 10 ionice -c3 python3 -S /tmp/q2_audit/pass2.py
```

The scripts live in `/tmp/q2_audit/` (outside the repo); the exact SQL for every
deferred cell is duplicated in `Fast_Fetch/CONTINUITY.md` under `[Q2-AUDIT]`, so
nothing depends on `/tmp` surviving. The legacy zero-source counts (7starhd,
hdtvb) use a union over `download_sources`/`post_sources`; that branch is coded
in `pass2.py` but has not executed yet.

Still deferred after that, and why:

- `filmyzilla`, `hindilinks4u` 18+ — 15 s budget exceeded on a cold 33–62 MB
  file; the count itself is a plain `posts` scan.
- `kisskh`, `rogmovies`, `ssrmovies`, `multimovies`, `multimovies_full`,
  `vegamovies` zero-source — the distinct-join over 140k–750k link rows.
- `10xflix`, `bolly4u`, `9xmovies`, `world4ufree`, `toonworld4all`, `moviesmela`,
  `katmoviehd_refreshed` 18+ / status — pass 2 did not reach them.

## What was not verified

- **No link was probed.** Playability is unknown everywhere; status strings are
  whatever the importer/verifier last wrote. Only 7starhd, hdtvb and
  fast_fetch show large `active` counts.
- **Production counts are stamped, not re-measured.** `merged_catalog_20261025`
  and `preapply_20261029_1726` were not counted; the numbers shown are their
  `cat_projection_meta` values.
- `fast_fetch_old_7mb_backup.db` could not be read (root 0600) — not audited.
- `posts w/ 0 sources` is exact where a number is shown, `deferred` where the
  budget expired. It does not say *why* a post has no link.
- `multimovies_full_20261022` is a second copy of multimovies, not a second
  site; `katmoviehd_refreshed` and `mp4moviez_staging*` are the same sites as
  their base files. The 35 count deduplicates these.
- Nothing was merged, moved, or written under `/home/ubuntu/radd-stream-data/`.
