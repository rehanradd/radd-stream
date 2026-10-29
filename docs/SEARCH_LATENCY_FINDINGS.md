# Search latency — corrected measurements and the query-plan evidence

Written 2026-10-30 by the q3 lane, after the q4 master measured production while my
report was landing. **This file retires claims in my own `1d483ee` report and in the
`Fast_Fetch/CONTINUITY.md` entry for it.** Read the corrections first; the original
fix (`media_search.py`, shipped and gated) is unaffected.

## 0. The file everything is measured against

`/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` — 6 396 899 328 bytes,
`page_size` 4096, WAL, **150 799** `posts`, **275 488** `cat_work_sites`, opened
`mode=ro`. This is `RADD_DB_PATH`, what the running service reads. Every index below
came from `sqlite_master` on that file, which is not an execution and costs nothing.

| table | indexes present in production |
|---|---|
| `posts` | `idx_posts_source_ind(source_site,industry)`, `idx_posts_canonical_key(canonical_key)`, `idx_posts_tmdb(tmdb_id)`, `idx_posts_imdb(imdb_id)`, `idx_posts_slug(slug)` |
| `releases` | `idx_releases_post(post_id)`, `idx_releases_origin(post_id,source_site,origin_url)`, `idx_releases_source_site(source_site)` |
| `download_sources` | `idx_sources_rel(release_id)`, `idx_sources_res(resource_id)`, `idx_sources_status_temp(status,is_temporary)`, `idx_sources_rel_status(release_id,status)`, `idx_sources_service(service)` |
| `cat_work_sites` | **`idx_cat_work_sites_post(post_id)`**, `sqlite_autoindex_cat_work_sites_1` |

## 1. CORRECTED — "`cat_work_sites.post_id` is unindexed" is false, and it inverted my table

My vault copy (`vault/catalog_copy.db`, same 150 799 / 275 488 row counts) **already had**
`idx_cat_work_sites_post`. `vault/probe_bridge.py` printed
`# dropped idx_cat_work_sites_post — schema now equals production's` and that comment was
wrong: dropping it made the schema **unequal** to production. Consequences:

- The "no bridge index" column of my published five-number table is a **degraded schema
  that does not exist on any real deployment**. Delete it.
- The column I labelled "+ step-1 index" is simply **production as it is**: `inception`
  913.5 ms, `kpop` 825.7 ms, `don` 77.9 ms, `love` 89.6 ms, `a` 0.1 ms (no SQL issued).
- The 0.9 s "build the bridge index" figure was measured **rebuilding an index that was
  already there**. It says nothing about production, which needs no build.
- The claim "inception and kpop are not faster than the live edge until the migration
  runs" is false: the migration has nothing to run for them. It is also false for a
  second reason — see §3.

## 2. CORRECTED — the migration's step 1 is a no-op on production

`migrate_search_indexes.py` step 1 issues
`CREATE INDEX IF NOT EXISTS idx_cat_work_sites_post ON cat_work_sites(post_id)`. Against
the file above, `apply` finds it present and prints `already present — skipped`, and
`verify` passes it. **Step 1 changes nothing on production.** What the script still adds
is step 2 (FTS5) and the `PRAGMA`-guarded, idempotent, reversible *harness*; and FTS5 is
a capability nothing in `Fast_Fetch` reads yet — `test_media_search.py` asserts
`inspect.getsource(media_search)` contains no `posts_fts`.

## 3. CORRECTED — `inception`/`kpop` are not speedups, and the two tables are different experiments

Live edge, old code, 18:05: `inception` 318 ms, `kpop` 580 ms. In-process on the copy,
old statement alone: 1 272.7 ms and 665.9 ms. Those columns are **not comparable** — the
edge number includes nginx plus whatever the dirty `/opt/radd-stream` tree actually ran,
and the in-process number includes cold page-in of a 6.4 GB file at load ~7 with five
lanes live (that run's own warm-up line reads 35.5 s). Against each other, the fix's real
wins on the two pathological cases hold — `don` 1 178.4 → 77.9 ms, `love` 4 481.0 →
89.6 ms, `a` 25 904.8 ms → 0.1 ms with no SQL — and for `inception`/`kpop` I must claim
**no improvement**, only that the shape is bounded (≤ 200 candidates, five statements)
where the old one was not. Nobody should apply a migration on the strength of those two
rows.

## 4. `/api/v1/posts?q=` — the 66 s was an in-process query, and it is not an index problem

`vault/compare.txt` line `7.70 posts 'inception' OK 66322.0 ms`: **in-process against the
copy**, not a live-edge timing, no URL, and I did not take an edge sample (that route
holds a service thread and the unit was OOM-killed at 19:14:31). The SQL is exactly the
two statements `viewer.api_v1_get_posts` builds (`Fast_Fetch/viewer.py:2633-2652`):

```sql
SELECT COUNT(*) FROM posts p WHERE COALESCE(p.is_18_plus,0)=0
  AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ?);          -- total

SELECT p.id, …, COUNT(DISTINCT r.id), COUNT(DISTINCT s.id)
 FROM posts p LEFT JOIN releases r ON r.post_id = p.id
 LEFT JOIN download_sources s ON s.release_id = r.id
 WHERE COALESCE(p.is_18_plus,0)=0
   AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ?)
 GROUP BY p.id ORDER BY p.id DESC LIMIT ? OFFSET ?;                        -- page
-- params: ['%inception%'] x 3, then [limit, offset]
```

`EXPLAIN QUERY PLAN` on the production file, read-only:

```
COUNT:  SCAN p
PAGE:   SCAN p
        SEARCH r USING COVERING INDEX idx_releases_post (post_id=?) LEFT-JOIN
        SEARCH s USING COVERING INDEX idx_sources_rel (release_id=?) LEFT-JOIN
        USE TEMP B-TREE FOR count(DISTINCT)          (twice)
```

So: the joins are already covered, the default sort builds **no** order B-tree, and the
work is **two full scans of `posts`** per request — one to compute an exact `total` for
pagination nobody looks at while typing, one for the page — each scanning with three
leading-wildcard `LIKE`s, which is exactly the predicate no B-tree can serve. That is
where 66 s lives, and no index in `migrate_search_indexes.py` touches it.
`sort=trending` *does* add `USE TEMP B-TREE FOR ORDER BY` over every matched group;
`sort=` default does not.

## 5. The correctness half, separate from latency

`viewer.py:2546` builds the pattern as `f"%{query}%"`:

- **No minimum length.** `q=a` is answered with rows (measured 10 at the production edge,
  and pinned by test on a fixture). One keystroke costs two full scans of 150 799 wide
  rows.
- **`LIKE` metacharacters are not escaped.** `q=%` becomes `LIKE '%%%'`, i.e. every row,
  and `q=_` becomes a one-character wildcard. Two keystrokes can ask for the whole
  catalog and the route pays the exact-total scan for it.

Proposed rule, for the route the app's search box calls (this brief authorises no change):

1. `MIN_QUERY_CHARS = 2` on `q=`: below it, issue **no SQL**, return `results: []` with a
   `hint`, exactly as `media_search` now does. This is a UX floor *and* the availability
   fix; they are the same query, which is why I stopped treating them as two problems.
2. Escape `%`/`_` (reuse `media_search._escape_like`) and pass `ESCAPE '\'`.
3. Stop computing an exact `total` when `q` is present: return `has_more` from
   `LIMIT+1`, or a capped count. That deletes one of the two scans on every keystroke,
   and it is the only part of this route that a bounded change can remove without an
   FTS5 build.
4. The app-side half (debounce ≥ 300 ms, min token, cancel in flight, never retry on
   timeout) is **still not landed** — no Android in my scope, and no Gradle on this box.
   Targets: `SearchViewModel.kt:383`/`:281`/`:169-172`/`:174-178`/`:265`/`:269`/
   `:307-308`, `CatalogRepository.kt:37`, `ApiProvider.kt:50-53`. Server-side 1–3 make
   the app floor a courtesy, not the only defence.

## 6. Why my copy was not production, in one sentence worth keeping

`catalog_v2.ensure_schema()` creates **neither** `releases` **nor** `download_sources`,
and none of the join indexes — pinned by
`test_posts_query_plan.test_ensure_schema_alone_does_not_give_the_join_indexes`. A
database built from `ensure_schema` therefore plans `SCAN releases` where production
plans `SEARCH … USING COVERING INDEX idx_releases_post`, and any latency or
"missing index" claim measured on it is that file's number, not production's. On this box
the two look-alike candidates are `radd-stream-data/merged_catalog_20261025.db`
(150 799 posts) and `radd-stream-data/fast_fetch.db` (203 posts); the q4 master recorded
making the same mistake earlier this week. Name the file in every number, from now on in
this repo, in the same sentence as the number.

## 7. Evidence, reproducible offline

`Fast_Fetch/test_posts_query_plan.py` — 6 tests, temp-directory fixture with the
production index set built explicitly, no network, no production file, ~16 s:

```
python3 -S Fast_Fetch/test_posts_query_plan.py
```

It asserts the two `SCAN p` passes, the two covering-index searches, the absence of an
`ORDER BY` B-tree at default sort and its presence at `sort=trending`, that `q=a` is
answered rather than refused, and that `q=%` matches every row. The plan text in §4 came
from `EXPLAIN QUERY PLAN` on the production file with `nice -n 19 ionice -c3`, which does
not execute the statement.

**No production change comes out of this brief.** No DDL applied, no service restart,
`/opt/radd-stream` untouched.
