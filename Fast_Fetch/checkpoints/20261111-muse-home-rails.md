# 2026-11-11 — Muse [HOME-RAILS]: /api/v1/trending, /api/v1/related, /api/v1/facets + app wiring

**What:** the missing-pieces audit gap #5 (Home rails), built on `muse/home-rails-20261111` from main `3baf5ab6` (the panel merge), one commit `9e6c91e1`.

**Backend (`Fast_Fetch/viewer.py`):**
- `GET /api/v1/trending` — the "Most Sources" order as its own route; delegates to `api_v1_get_posts(sort="trending")`, so the deadline, adult clause, hides and envelope are identical to `/api/v1/posts`.
- `GET /api/v1/related?work_id=` — "Because you watch", scored on the seed post: shared cast +5 each (first 5), shared genre +3 each (first 5), same industry +1, same content type +1, year within ±2 +1; order score, then (release_count + source_count), then id; only score > 0 is returned. A missing or adult seed answers an empty page (total 0), never an error; a non-integer work_id raises ValueError and the route answers 400.
- `GET /api/v1/facets` — `{genres, languages, industries, types}`, each entry `{key, label, count}`. Genres are the 10 panel categories; languages the top 12; industries the 5 fixed keys; types the content_type values.
- `genre=` filter extended 5 → 10 panel categories; new `language=` filter. The filters and the facets share the same predicates (`GENRE_FILTER_SQL`, `INDUSTRY_FILTER_SQL`, the `language=` LIKE), so a facet count is exactly what the matching filter returns — a chip never promises a count its tap cannot keep. All three endpoints apply the adult clause, the panel hides and the 10 s deadline (503).
- `category_works` lives in the PANEL DB, not the catalog — the facets genre counts are computed from `posts.genres` with the filter's own predicates, not read from the panel table.

**App:**
- `RaddStreamApi` + `CatalogRepository`: `getTrending` / `getRelated` / `getFacets` (facets returns null on failure, like `browseWorksV2`).
- `HomeViewModel`: "Because you watch" rail, inserted after "Recently added" and seeded from the first Continue Watching post (removed when there is no seed, reloaded when the seed changes); facets state fetched on load and refresh; "Most Sources" falls back through `/api/v1/trending` when the v2 browse is empty, then to the old list on an old server. `HomeSection` gains `relatedWorkId` (cached in `HomeCache`, so a restored rail reloads with its seed); `browseEquivalent` is false for a related rail too.
- `HomeScreen`: facet chip row (genres + industries, each with its count) landing on Search with the filter applied. Language chips wait for a Search language filter.
- `Search`: `genre`/`industry` route args + `initialGenre`/`initialIndustry`; `GenreFilter` 5 → 10 (the new genres also appear in Search's own filter chips).
- `FacetsWireTest`: JSON test for the new models.

**Tests:** `Fast_Fetch/test_home_rails.py` (25 tests: trending order + identity with `sort=trending`, related scoring/tiebreak/empty-seed/adult-seed/no-neighbours/400, facets shape + facet-count-equals-filter-total for all four groups, all-10 genre filter, language filter + LIKE escaping, hidden-work exclusion on all three, HTTP route tests). Registered in both ledgers via the `backend-ci.yml` run step. Affected suites green: database, redact, panel_feed, media_search, search_fuzzy, scale_pragmas, posts_query_plan, catalog_api, ci_manifest, docs_invariants. The public-edge sweep (`sweep_public_edge.py`) now scans the three new routes too; it reports only the pre-existing `/api/v1/posts?page=250` → 400 (the `POSTS_MAX_OFFSET` guard, not a leak).

**Checks:** full import diff per edited Kotlin file (only additions, all used; no removed imports); duplicate top-level type grep over the whole App tree: 0 duplicates (`FacetEntry`, `FacetsResponse`, `FacetChip` each defined once). No local Gradle run by owner order — CI (`ci.yml` + `backend-ci.yml` on push) is the verification path. No live-tree change, no service restart, no tag.

**Deploy note for the gate:** nginx's public allow-list does not yet include `/api/v1/trending`, `/api/v1/related`, `/api/v1/facets` — the gate must add them (same as `/api/v2/play` was added), or the app gets 403 in public. The live deploy waits until after the rev-8 swap (~20:40 PKT tonight).

**Not done:** push (this commit, then CI judges); parent merge into main; gate deploy.
