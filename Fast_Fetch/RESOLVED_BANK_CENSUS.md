# RESOLVED_BANK_CENSUS — blast-radius evidence for task #24 (`_derive_kind`)

**Author:** qoder14 · **Date:** 2026-11-05 02:44–02:47 PKT · **Method:** stdlib
`sqlite3` over `file:…?mode=ro` URIs only. Zero writes, zero copies, zero temp DBs,
no `/opt` edits. `loadavg` at session start 6.07 / 5.48 / 5.15; at final queries
5.93 / 5.58 / 5.22.

## ⚠️ OPENING CORRECTION (crown re-scope, 2026-11-05 ~02:43)

**Mis-banked production links today = 0, because the resolved-cache feature is not
deployed.** The ~185,000 figure quoted all night (116,604 `google_cdn` + 68,502
`mega` in `download_sources`) was a *source-table* count presented as if it were
*bank exposure* — it is neither a banked-row count nor a viewer/fragment count.
Two further corrections this census measured:

1. The 200,000-row `resolved_cache` bank exists only in a **synthetic bench DB**
   (`/tmp/resolved_cache_bench.db`), and its rows contain **zero** fragment- or
  viewer-shaped URLs — the bench cannot demonstrate the #24 harm at all.
2. Inside production `download_sources`, the `google_cdn` label does **not** mark
   Google Drive links: **0 of 116,604** rows carry `drive.google.com` or a `/view`
   path. The `mega` label is 88 % non-mega (`archive.toonworld4all.me` redirect
   pages). Every table below carries its provenance so the number survives being
   quoted after the people watching it go to bed.

## Legality of the tables

Every table is labelled:
- **SYNTHETIC** — a bench DB created by a lane for load testing. Not production.
  Not evidence of what is banked; only of rates within the fixture.
- **PRODUCTION-READ-ONLY** — queries against the live catalog, `mode=ro`, indexed
  where possible. Counts of the *source* population (`download_sources`) = what
  **would** be offered to the cache at first deploy, NOT what is cached.

---

## A. PRODUCTION-READ-ONLY — the bank is empty

DB: `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` (6,396,915,712 B =
6.1 GB, mtime 2026-11-04 23:04 PKT; `/opt/radd-stream/Fast_Fetch/fast_fetch.db`
symlinks to it; systemd unit runs `serve` with `RADD_DB_PATH` pointing at it).

```sql
SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%resolved%';
-- → []   (2026-11-05 02:44, load 6.07)
```

**No `resolved_cache` table exists in the production catalog.** Also probed
read-only, same timestamp: `/home/ubuntu/radd-stream-data/resolvers.db`
(tables `resolvers`, `resolver_probes` — different feature),
`/opt/radd-stream/Fast_Fetch/multimovies.db` (empty). Every other `.db` on the
box carrying a `resolved_cache` table was found by name and checked: the two
bench files in §B and the lane-server bench in §C.

Consequences, stated plainly:
- Banked rows `kind='file' AND category='A'` in production: **0**.
- `reverify_after` in future / `fail_count>0` among misbanked production rows:
  **0 / 0 — structurally**, there are no rows at all.
- `resolved_cache.py` changed on disk *during this census* (qoder12 live edit,
  observed 02:45) — the bank will materialize only when the unit is restarted
  with the deployed code, which is crown-gated. Numbers in §D are **projected at
  first deploy**, never "currently banked".

## B. SYNTHETIC — `/tmp/resolved_cache_bench.db` (49.2 MB bench fixture)

DB: `/tmp/resolved_cache_bench.db`, 51,621,888 B, mtime 2026-11-04 22:31,
**200,000 rows**, schema carries an extra `backend` column (bench-only).
Query timestamp 02:44, load 6.07 → 5.93. Full-table scans below are labelled
`CENSUS-SYNTHETIC` and are legitimate only because the table is 200k/49 MB.

Kind × horizon grid — `SELECT kind, category, COUNT(*) FROM resolved_cache GROUP BY 1,2;`

| kind | category | rows |
|---|---|---|
| file | A | 99,595 |
| file | B | 25,238 |
| playlist | A | 188 |
| playlist | B | 74,979 |

A+file by backend — `SELECT backend, COUNT(*) FROM resolved_cache WHERE kind='file' AND category='A' GROUP BY 1 ORDER BY 2 DESC;` (2.44 s):
`fsl_r2` 20,064 · `hubcloud-10g` 20,044 · `pixeldrain` 19,922 · `google_cdn` 19,879 · `fastdl-beer` 19,686 —
a flat ~20k×5 distribution; the uniformity is generator output, not traffic.

**The #24 shapes are absent:**
```sql
SELECT COUNT(*) FROM resolved_cache WHERE kind='file' AND category='A' AND url LIKE '%#%';           -- 0 (0.46 s)
SELECT COUNT(*) FROM resolved_cache WHERE kind='file' AND category='A'
   AND (url LIKE '%/view%' OR url LIKE '%/preview%' OR url LIKE '%folderview%' OR url LIKE '%/file/d/%');  -- 0 (0.98 s)
```
And a Python pass (30.5 s) applying qoder14's committed `host_classifier.is_direct_file`
shape gate + the handoff's extension rule to **every** A+file URL:
`fragment=0, viewer=0, WOULD-STOP-BEING-FILE=0`.

`fail_count` (the crown's item 4): `SELECT COUNT(*) FROM resolved_cache WHERE fail_count>0;` → **0**
(all 200k rows; generator never wrote failures). `reverify_after>now` among A+file:
**78,839** (`SELECT COUNT(*) … WHERE kind='file' AND category='A' AND reverify_after>?` with
epoch param, 2.62 s).

**Verdict on this bench:** it can size a cache and exercise horizons, but it
**cannot demonstrate task #24's defect** — zero rows exhibit the fragment or
viewer shapes the fix targets. Acceptance evidence for qoder12's change must be
**targeted fixtures** (the xfail assertions in
`test_host_classifier.TestViewerShapeGate.test_kind_gate_expectations`), not a
rerun of this bench. CENSUS-SYNTHETIC; label every number taken from it.

## C. SYNTHETIC (lane-server) — `/tmp/phase1_bench.db`

167,936 B, mtime 2026-11-05 02:43, **1 row**:

```sql
SELECT link_id, category, kind, substr(url,1,70), fail_count FROM resolved_cache;
-- (5, 'A', 'file', 'https://pixeldrain.com/api/file/s2yMcLkb', 0)
```

The entire real bank of this lane is one **genuine** pixeldrain API direct-file
URL — the exact shape the #24 fix must KEEP banking as `kind='file'` A (see
`test_real_direct_files_STILL_pass_the_gate`, 23.98 h measured). Nothing here is
at risk from the fix.

## D. PRODUCTION-READ-ONLY — projected exposure at first deploy

Source: production catalog `download_sources` (4,073,865 links; prior coverage
census). Every query below ran through `idx_sources_service`
(`EXPLAIN QUERY PLAN … 'SEARCH download_sources USING INDEX idx_sources_service (service=?)'`,
verified 0.01 s, printed at run time), then filters inside the seeked subset
(< 120k rows each). Timestamps 02:44–02:45, load 6.07→5.93. These count **source
links a JIT resolve could one day bank**, not banked rows.

| service label | rows | what the URLs actually are (host census) | fragment / viewer shapes |
|---|---|---|---|
| `google_cdn` | 116,604 | `vcloud.beer` 103,547 · `photojin.study` 12,655 · `www.filmyzilla75.com` 402 · **drive.google.com: 0** | `/view`: **0** · `uc?export=download`: **0** |
| `mega` | 68,502 | `archive.toonworld4all.me/redirect/<600-hex>` 60,520 · **real `mega.nz`: 7,972** · `mega.dp.ua` 10 | mega.nz rows **WITH `#`: 7,972 = 100 %** |
| `gdflix` | 89,451 | packer/bridge family | not queried (B-horizon already) |
| `gdtot` | 78,440 | packer/bridge family | not queried |
| `drive` | 142 | `drive.klop.me`: 139 — a third-party host, **not** Google Drive | — |

Example (all queries follow this shape; full text re-runnable as written):
```sql
SELECT COUNT(*) FROM download_sources WHERE service='mega'
   AND source_url LIKE 'https://mega.nz%' AND source_url LIKE '%#%';      -- 7,972 (0.80 s)
SELECT COUNT(*) FROM download_sources WHERE service='google_cdn'
   AND source_url LIKE '%drive.google.com%';                               -- 0 (1.40 s)
SELECT COUNT(*) FROM download_sources WHERE service='google_cdn'
   AND source_url LIKE 'https://vcloud.beer%';                             -- 103,547 (1.57 s)
```

**One-off unindexed scan, disclosed:** before the crown re-scoped this brief I ran
`SELECT COUNT(*) FROM download_sources WHERE source_url LIKE '%drive.google.com%'`
across the whole table — plan `SCAN download_sources`, **14.52 s, once**, 6,349
rows. No further unindexed full scans were run after 02:44. Treat the 6,349 as
census-accurate (count(*) is exact) but as the class of query this order bans;
re-run only via a host index or the per-service seeks above.

### Honest blast radius of the #24 fix, replacing the ~185k figure

- **Currently hidden or refused that plays today: none.** The production bank is
  empty (§A); the fix cannot hide a single playable link before deploy.
- **Projected at first deploy, per family, if JIT resolves these source rows
  under the pre-fix `_derive_kind`:** the fix flips `kind='file'`→non-file for A/B
  horizon rows whose URL has no real file extension and no confirmed
  non-HTML Content-Type and fails the `is_direct_file` shape gate. On the source
  population that is: 7,972 mega.nz cryptolinks (**every one carries `#key`; a
  fragment never reaches the server, so `/download` following them could never
  produce bytes anyway — the fix refuses a promise, not a download**), the
  60,520 `archive.toonworld4all.me/redirect/<hex>` pages mislabelled `mega`, and
  the 116,604 `vcloud.beer`-shaped `google_cdn` links (no extension, bridge hosts;
  already horizon-B under the AND rule since 02:05, so they were never "24 h
  permanent" — only `kind` was lying).
- **What stays `kind='file'` A:** pixeldrain (`/u/` and `/api/file/` — the lane's
  one real banked row, §C), `fsl_r2` object keys with real extensions,
  `fastdl-beer` file paths, `drive…uc?export=download` — pinned green by
  `test_host_classifier` 71 OK and re-measurable via
  `test_horizon_deltas_measured_not_just_letters`.
- **The night's headline corrected:** "~185k mis-banked production links with a
  24 h permanent horizon" → **0 mis-banked (bank does not exist); 185,106 source
  rows carry service labels that are themselves 88–100 % misapplied; the
  genuinely unreplayable cryptolink family is 7,972; and the bench DB that made
  the number sound like banked exposure contains zero instances of the defect.**

## Re-run recipe

Same commands, same order, all `mode=ro`:
1. `SELECT name FROM sqlite_master WHERE name LIKE '%resolved%'` on the three DBs
   (paths above) — expect `[]` in production until the feature is deployed; re-run
   this census's §A items (reverify/fail_count/blast) once rows exist.
2. §B queries unchanged against `/tmp/resolved_cache_bench.db`.
3. §D per-service queries — keep `EXPLAIN QUERY PLAN` output in the log; every
   number here ran sub-2 s on `idx_sources_service`.

*Provenance travels with the number: every figure above carries its DB path,
label (SYNTHETIC / PRODUCTION-READ-ONLY / CENSUS-SYNTHETIC), SQL, timing, and
the loadavg of its run.*
