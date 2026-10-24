# Scrape-Completeness Audit — Milestone 7 ground truth

> READ-ONLY audit. All DB reads used `sqlite3.connect("file:...?mode=ro", uri=True)` + `busy_timeout`.
> No DB was written, no git mutation run, no env var value printed. Counts are snapshots taken
> 2026-10-22 ~05:00-05:15 while hdhub4u + toonworld4all crawlers and a full projection were live,
> so a few sites are moving numbers (marked below).

Legend: **sm** = sitemap_cache rows, **p0** = scraped=0 (pending), **f-1** = scraped=-1 (failed),
**d1** = scraped=1 (indexed), **posts** = posts rows, **rel** = releases rows,
**links** = download_sources (Family A) or sources (Family B) rows,
**OUTSTANDING** = p0 + f-1 (URLs not yet turned into a post).

## 1. Per-site completeness table

| site | sm | p0 | f-1 | d1 | posts | rel | links | OUTSTANDING | gap % of sm | notes |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 10xflix | 17,658 | 0 | 1,189 | 16,469 | 13,775 | 76,923 | 228,397 | **1,189** | 6.7% | |
| 7starhd | 23,519 | 0 | 7,938 | 15,581 | 11,791 | 33,369 | 99,627 | **7,938** | 33.8% | worst failed ratio, large site |
| 9xmovies | 20,382 | 1 | 5,770 | 14,611 | 12,060 | 30,936 | 337,595 | **5,771** | 28.3% | |
| bolly4u | 36,026 | 1 | 7,735 | 28,290 | 15,192 | 41,004 | 22,003 | **7,736** | 21.5% | links<<rel, see defect D5 |
| desicinemas | 5,306 | 1 | 0 | 5,305 | 5,223 | 5,285 | 4,339 | **1** | 0.0% | near done; BAD schema, see D1/D2 |
| filmyzilla | 20,666 | 0 | 3,462 | 17,204 | 15,228 | 46,372 | 80,032 | **3,462** | 16.8% | |
| hdhub4u | 28,763 | ~2,648 | 1,122 | ~24,993 | ~11,217 | ~114,996 | ~210,216 | **~3,770** | 13% | LIVE crawler, numbers moving |
| hdtvb | 11,404 | 0 | 3,684 | 7,720 | 3,774 | 16,855 | 16,855 | **3,684** | 32.3% | ALL stamped `hdhub4u`, see D3 |
| hindilinks4u | 32,271 | 8,129 | 2,170 | 21,972 | 25,780 | 105,682 | 105,682 | **10,299** | 31.9% | largest pending backlog |
| katmoviehd | 51,044 | 883 | 5,339 | 44,822 | 35,624 | 130,389 | 148,063 | **6,222** | 12.2% | |
| moviezguru | 3,391 | 0 | 4 | 3,387 | 3,386 | 7,334 | 8,912 | **4** | 0.1% | effectively done |
| multimovies | 72,499 | 769 | 0 | 71,730 | 10,498 | 532,649 | 595,218 | **769** | 1.1% | 71k URLs → 10.5k posts (episode→season collapse) |
| rareanimes | 2,624 | 0 | 1,295 | 1,329 | 1,295 | 17,419 | 53,767 | **1,295** | 49.4% | half the catalog failed |
| rogmovies | 7,878 | 0 | 0 | 7,878 | 7,750 | 52,964 | 193,048 | **0** | 0.0% | COMPLETE (index-wise) |
| ssrmovies | 27,018 | 0 | 0 | 27,018 | 13,916 | 46,153 | 665,025 | **0** | 0.0% | COMPLETE (index-wise) |
| toonworld4all | 2,293 | ~1,324 | 0 | ~969 | 932 | 66,740 | 230,282 | **~1,324** | 58% | LIVE crawler, only ~42% done |
| vegamovies | 14,336 | 8 | 323 | 14,005 | 13,368 | 131,654 | 398,243 | **331** | 2.3% | |
| world4ufree | 24,254 | 0 | 2,921 | 21,333 | 14,768 | 106,972 | 254,340 | **2,921** | 12.0% | |

**TOTAL outstanding across staging = ~56,700 URLs** (sum of the OUTSTANDING column).
Fully sitemap-complete (0 outstanding): **rogmovies, ssrmovies** only. Near-complete: moviezguru(4), desicinemas(1), vegamovies(331), multimovies(769).
Far from done: toonworld4all (~58% pending), rareanimes (~49% failed), 7starhd (~34% failed), hdtvb (~32%), hindilinks4u (~32% pending+failed), 9xmovies (~28%).

### SITES.md vs staging DB vs importer coverage mismatches
- Every site with a staging DB also has an importer, and vice-versa (18 each). No orphan importer.
- Sites with a staging DB are **not yet merged into `merged_catalog.db`** (see §4): 9xmovies, bolly4u, filmyzilla, hindilinks4u, toonworld4all, world4ufree. Those 6 staging catalogs exist on disk but are absent from the unified catalog.

## 2. What `scraped` values mean (verified in code, not assumed)

Core engine `fast_fetch.py`:
- `scraped = 0` → **pending**, `crawl` selects only `WHERE scraped = 0` (fast_fetch.py:5114,5119,5129,5134).
- `scraped = 1` → **indexed**; set only after a successful `save_scraped_data` (fast_fetch.py:4324).
- `scraped = -1` → **failed**: set when `extract_post_data` returns no releases (fast_fetch.py:5166) or raises (fast_fetch.py:5170).

**Terminal vs retry:** none of `1` / `-1` are ever re-selected by `crawl` (the query is `= 0` only). So **`-1` is terminal — failed pages are NOT auto-retried; they are silently lost** unless an operator runs `UPDATE sitemap_cache SET scraped=0 WHERE scraped=-1`. That is exactly the manual requeue the two crawlers used. Sites that DO ship an auto-requeue: vegamovies has a `reset` path `UPDATE ... scraped=0 WHERE site='vegamovies' AND scraped=-1` (import_vegamovies.py:471-473); desicinemas increments an `error_count` column instead of -1 (import_desicinemas.py:549).

Per-site semantics drift (schema D):
- Family A DBs (7starhd, hdtvb, multimovies, rogmovies, ssrmovies, vegamovies) use the core `0/1/-1`.
- Family B DBs additionally write `scraped = 2` for a *skipped* page: 9xmovies (import_9xmovies.py:680), moviezguru (import_moviezguru.py:484), world4ufree (import_world4ufree.py:781). **In the live data `scraped=2` count is 0 for every DB**, so those skipped paths are effectively writing -1 or not firing — the `2` state is dead code / unpopulated.
- desicinemas writes `scraped=1` even on some non-save paths (import_desicinemas.py:544,635) — so for desicinemas `scraped=1` does not strictly guarantee a `posts` row.

Rows sitting in each state (all 18 DBs): scraped=1 = **424,663**, scraped=0 = **~13,863**, scraped=-1 = **~42,838**, scraped=2 = 0. (Derived from the table above; -1 dominates the outstanding backlog — most "missing" pages are hard failures, not unvisited URLs.)

## 3. Structural sitemap incompleteness (which sites could be MISSING pages, provably)

The completeness table assumes each `sitemap_cache` is itself complete. Several discovery paths can silently miss pages:

- **10xflix, world4ufree, ssrmovies (WP REST, "empty-page" early-stop):** the sync loop breaks after 3 consecutive pages that add no NEW slugs — `if max_pages is None and consecutive_empty_new >= 3: break` (import_10xflix.py:771-773, import_world4ufree.py:647, import_ssrmovies.py:253). WP returns newest-first, so on a re-sync this stops before reaching the old tail and can strand never-cached pages. **Highest structural risk.**
- **hdhub4u (Typesense):** paginates `limit=250&page=N` and breaks when `found` is reached or a short page arrives (import_hdhub4u.py:734-797). Typesense enforces a `search_cutoff`/`max_candidates` result window (often 10,000); if the server-side collection exceeds that, `hits` empties early and the tail is never queued. sitemap has 28,763, so it paged past 10k here — but verify against the API's `found`.
- **vegamovies / rogmovies / hdtvb (XML sitemap):** URL filter keeps only `/download-` or trailing-`/` links and drops `/category/`, `/tag/`, `/page/` (import_vegamovies.py:186-190, import_rogmovies.py:186-188). Any legit permalink that does not end in `/` or lack `/download-` is silently discarded. Sub-sitemaps are discovered dynamically (good), but only those matching `"post-sitemap" or "sitemap"` are followed.
- **desicinemas, hindilinks4u, filmyzilla (XML sitemap):** sitemap-driven; completeness = whatever the site publishes. WP `sitemap_index.xml` can itself be stale.
- **rareanimes (WP + master index):** the master-movies index pass filters out `/category/`,`/tag/`,`/page/`,`/contact` (import_rareanimes.py:773) — same trailing-slash class of drop.

**How to PROVE each site's sitemap is complete (countable checks, read-only / external):**
1. **WP sites** (10xflix, 7starhd, 9xmovies, bolly4u, moviezguru, rareanimes, ssrmovies, toonworld4all, world4ufree):
   `curl -sI "<base>/wp-json/wp/v2/posts?per_page=1" | grep -i x-wp-total` → compare the declared total against `SELECT COUNT(*) FROM sitemap_cache;`. If `x-wp-total > sitemap_cache` the sync missed pages. Re-run with an explicit high `max_pages` to bypass the empty-page break, then re-diff.
2. **Typesense (hdhub4u):** `curl` the search URL page=1, read `.found`, compare vs `COUNT(*) FROM sitemap_cache`.
3. **XML-sitemap sites** (vegamovies, rogmovies, hdtvb, desicinemas, hindilinks4u, filmyzilla):
   `curl -s <base>/sitemap.xml | grep -oE '<loc>.*</loc>'` then fetch each sub-sitemap and count `<loc>` vs `sitemap_cache`.
4. Universal internal check for stranded pages: `SELECT scraped, COUNT(*) FROM sitemap_cache GROUP BY scraped;` — a re-sync that leaves `scraped=0` at 0 but `x-wp-total` higher means the discovery itself is short.

## 4. Cross-site duplication and identity ladder (merged_catalog.db, read-only)

`merged_catalog.db`: posts=**72,420**, releases=1,017,834, download_sources=2,370,867, post_sources=190,465.

- **Distinct works:** `COUNT(DISTINCT canonical_key)` = 70,624 vs 72,436 post rows → **1,809 canonical_keys carry >1 posts row = 1,812 duplicate post rows.** The identity ladder is NOT collapsing these.
  - 747 of those groups disagree movie-vs-series (`_find_existing_post` requires `_post_type_matches`, fast_fetch.py:3986; cross-site classifier divergence blocks the merge → siblings).
  - 1,063 groups agree on family yet still duplicate — year disagreement or external-id conflict (`_identity_values_conflict`, fast_fetch.py:3992) filters the candidate. e.g. `100-days-to-live_2019` exists twice (ssrmovies + multimovies, both movie, both year 2019) — a tmdb/imdb conflict most likely.
- **post_sources is populated but split across siblings.** 190,526 source-page rows across 72,455 posts (multimovies alone: 68,992 pages → 8,089 posts, katmoviehd 34,019 → 13,036). For the 1,812 duplicate works the second site's page was written under a NEW post rather than linked to the existing one, so cross-site "same work, multiple sources" is UNDER-recorded and the same title shows up as multiple catalog entries.
- **Merge coverage gap (the real blocker for M7).** These staging sites are **absent** from merged posts: 9xmovies, bolly4u, filmyzilla, hindilinks4u, toonworld4all, world4ufree. Two more are present but MISLABELLED:
  - desicinemas (5,223 rows) sits under `source_site='unknown'` because its `posts` table has **no site/source_site column** (defect D1).
  - hdtvb (3,774 rows) is stamped `source_site='hdhub4u'` (defect D3), so it silently interleaves with real hdhub4u.

## 5. Link integrity / playability / resolver back-fill

- **All 2,370,867 `download_sources` in merged_catalog.db are `status='active'`.** Dead/`expired` distribution = 0/0. The health checker (`link_health.py`, which can set `dead`/`expired`/`is_resumable`/`http_status`) has NOT propagated results into the unified catalog — so the catalog claims 100% liveness with zero verification. `active_sources` from `/api/v1/stats` is therefore not trustworthy.
- **Resolver back-fill (`--resolve-bridges`):** there is no standalone `--resolve-bridges` command in `fast_fetch.py`/`catalog_v2.py`. Bridge resolution happens at scrape time inside extractors (e.g. greenmotors/linkszilla/mobilejsr unwrappers, fast_fetch.py:2025-3465). The ONLY back-fill observed running is **toonworld4all** via `--resolve-bridges` (import_toonworld4all.py:745,756), tracked in `/home/ubuntu/radd-stream-data/toon_resolve.log`: **35,400 / 226,438 links resolved, unresolved=0, ETA ~997 min (~15.6% done).** Nothing comparable ran for other sites.
- **Projected catalog (`catalog_full.db`, 3.2 GB) could not be read** — it was continuously locked by the live projection job (`database is locked`) across retries; it uses a `-journal` (delete-mode) write, not WAL, so no stable read snapshot was available. This is the one number I could NOT capture; re-run §5 checks after projection finishes, or point them at a fresh `cp` copy.
- On the small legacy `data/fast_fetch.db` (203 posts, not the production catalog) `final_url != source_url` for 1,735/5,578 links — i.e. only ~31% of stored links were ever resolved to a direct final URL; the rest are still bridge URLs. Expect the same or worse ratio site-wide until a resolve back-fill runs per catalog.

## 6. Prioritized punch list to honestly declare "each site scraped 100%"

Ordered by leverage. "Verify" commands are exact and re-runnable read-only.

1. **[P0] Merge the 6 un-merged staging DBs into `merged_catalog.db`.** Until done the unified catalog is missing 9xmovies, bolly4u, filmyzilla, hindilinks4u, toonworld4all, world4ufree entirely (~89,980 staging posts of unique-ish works).
   Run: `python merge_catalogs.py /home/ubuntu/radd-stream-data/<site>.db --target-db /home/ubuntu/radd-stream-data/merged_catalog.db` for each.
   Verify: `SELECT source_site, COUNT(*) FROM posts GROUP BY source_site;` lists all 18 sites (and 0 rows under `unknown`).
2. **[P0] Fix source_site stamping BEFORE merging (defects D1/D3).** Re-stamp hdtvb rows from `hdhub4u`→`hdtvb` and give desicinemas a `source_site`; else the merge keeps the wrong attribution.
   Verify: `SELECT source_site,COUNT(*) FROM posts WHERE source_site IN ('unknown','hdhub4u');` shows only real hdhub4u and no `unknown`.
3. **[P1] Drain the failure backlog (`scraped=-1`, ~42,838 URLs).** For each staging DB: requeue `UPDATE sitemap_cache SET scraped=0 WHERE scraped=-1;`, re-run the crawler, and triage the ones that fail twice (page removed vs parser gap). Biggest first: 7starhd 7,938, bolly4u 7,735, 9xmovies 5,770, katmoviehd 5,339, world4ufree 2,921, rareanimes 1,295, hindilinks4u 2,170.
   Verify: `SELECT COUNT(*) FROM sitemap_cache WHERE scraped=-1;` == 0 AND `scraped=0` == 0 per DB.
4. **[P1] Drain the pending backlog (`scraped=0`).** hindilinks4u 8,129, toonworld4all ~1,324, hdhub4u ~2,648, katmoviehd 883, multimovies 769, vegamovies 8. Let the two live crawlers finish toon/hdhub4u.
   Verify: `SELECT COUNT(*) FROM sitemap_cache WHERE scraped!=1;` == 0 per DB.
5. **[P1] Prove each sitemap is complete (§3 checks) BEFORE trusting "0 outstanding".** Especially re-run the WP syncs for 10xflix/world4ufree/ssrmovies with an explicit high `max_pages` to defeat the `consecutive_empty_new>=3` break, and diff against `x-wp-total`.
   Verify: `sitemap_cache count == declared API total` per site.
6. **[P2] Collapse the 1,812 duplicate-key works.** Either fix `_post_type_matches`/external-id filtering so cross-site pages merge into one post + post_sources, or run a dedup pass.
   Verify: `SELECT COUNT(*) FROM (SELECT canonical_key FROM posts WHERE canonical_key!='' GROUP BY canonical_key HAVING COUNT(*)>1);` → 0.
7. **[P2] Run link health across the catalog** so `status` reflects reality (active vs dead) instead of all-active, and finish the toon resolve back-fill.
   Verify: `SELECT status,COUNT(*) FROM download_sources GROUP BY status;` returns a real distribution; `resolved=N/N, unresolved=0` in toon_resolve.log.
8. **[P3] Clear orphan releases/links:** 20,429 merged releases have NO download_sources; 94 multimovies posts have no releases; 52 merged posts have no releases.
   Verify: `SELECT COUNT(*) FROM releases r WHERE NOT EXISTS(SELECT 1 FROM download_sources d WHERE d.release_id=r.id);` → 0.

## 7. Real defects found while counting (file:line)

- **D1 — desicinemas `posts` has no `id`, no `url`/`slug`, no `source_site`, and an invalid `media_type`.** Schema created at import_desicinemas.py (posts CREATE TABLE); observed columns: canonical_key,title,clean_title,year,media_type,poster_url,backdrop_url,imdb_id,tmdb_id,synopsis,is_18_plus,scraped_at,raw_meta,director,cast_names,languages,genres. 2,195 desicinemas rows are `media_type='episode'`, a value `classify_media()` never emits (only movie/series/complete_season/ongoing_season, fast_fetch.py:1613-1622). merge_catalogs coerces it to `series` (merge_catalogs.py:86,126). Consequence: desicinemas lands as `source_site='unknown'` (5,223 rows in merged).
- **D2 — three-way schema drift between staging DBs.** Family A (unified): posts/releases/download_sources/post_sources, `releases.post_id` FK (7starhd,hdtvb,multimovies,rogmovies,ssrmovies,vegamovies). Family B (staging): posts/releases/**sources**, `releases.post_canonical_key`, `posts.site`/`media_type`, no `post_sources`, no `origin_url` (10xflix,9xmovies,bolly4u,desicinemas,filmyzilla,hdhub4u,hindilinks4u,katmoviehd,moviezguru,rareanimes,toonworld4all,world4ufree). Merge handles both (merge_catalogs.py:41-47,59-69) but `post_sources` cross-site linkage is only available for Family A.
- **D3 — hdtvb importer hardcodes `hdhub4u` everywhere.** import_hdtvb.py:199 (sitemap insert site), :369, :384 (post source_site), :401 (mark scraped WHERE site='hdhub4u'), :424, :433 (crawler SELECT site='hdhub4u'), :537, :539 (stats). Result: all 11,404 hdtvb sitemap rows and 3,774 posts are stamped `hdhub4u`; merging hdtvb.db would collide with the real hdhub4u catalog. Copy-paste bug from import_hdhub4u.py.
- **D4 — `scraped=2` "skipped" state is written but never read or requeued.** Written by 9xmovies/moviezguru/world4ufree (import_9xmovies.py:680, import_moviezguru.py:484, import_world4ufree.py:781); the crawl query only selects `scraped=0`, and no code selects `=2`. Currently 0 rows sit at 2, so skipped items are being lost to `-1` instead.
- **D5 — bolly4u link integrity anomaly:** 41,004 releases but only 22,003 sources, and posts=15,192 vs d1=28,290 scraped URLs (heavily deduped). Most bolly4u releases carry 0 or partial download sources — inspect `sources` per release before trusting counts.
- **D6 — merged releases with no sources:** 20,429/1,017,834 (merge_catalogs.py:105-118 keeps a release even when its `sources` list is empty). 52 merged posts and 94 multimovies staging posts have zero releases at all.
- **D7 — all links marked `active`:** no path in the merge/projection writes `status='dead'`/`expired`; `/api/v1/stats` `active_sources` equals total sources by construction (see §5).
```