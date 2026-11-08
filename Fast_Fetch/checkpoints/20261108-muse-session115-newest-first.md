# Session 115 — newest-first ordering (MUSE-SESSION115-NEWEST-FIRST)

Date: 2026-11-08 ~23:52–00:15 PKT. Branch `session115-newest-first` from 39bcaf96
(Session 113). Builder: Muse subagent. Parent verifies, pushes, gates.

## The bug

`/api/v1/posts` sorted by post id DESC — the autoincrement import id — not by
release year. The app's Search default sort is already `NEWEST` ("newest"), and
Home/Browse pass no sort at all, so every list the user sees is import order
wearing a "Newest" label. A fresh scrape of a 1998 film lands on top of a 2026
title. Standing order since 2026-11-02, never fully built.

Evidence (file:line):

- `Fast_Fetch/viewer.py` `api_v1_get_posts` sort block (~3146): sort values are
  `rating` / `title` / `trending` only; default and ANY unknown value fall
  through to `ORDER BY p.id DESC`. `grep -n newest Fast_Fetch/viewer.py`
  returns nothing — there was zero `newest` in viewer.py.
- Live probe 23:5x PKT: `/api/v1/posts?limit=5` and `?limit=5&sort=newest`
  return IDENTICAL rows in IDENTICAL order (ids 150799–150795, years 2026,
  2026, 2022, 2022, 2022) — `sort=newest` was silently ignored.
- A real newest sort already existed in v2 but was unreachable and buggy:
  `catalog_api.py _sort_expr("newest")` = year * 1e10 + first_seen_at, but the
  app never calls v2 browse for lists, v2 browse is NOT in the nginx public
  allow-list (would 403), and the expression has no clamp — its top live row
  is year 2099.
- `media_search.search_by_media` has `sort="newest"` (year DESC) but only
  orders a capped newest-first window, not the main list.

## Phase 1 measurements (read-only, live catalog via SSH)

- Posts 150,799 rows; year NULL 10,184 (6.8%, must sort last); year = 0: 1;
  year < 1900: 1; year > 2026: **49 junk future years** (2090: 1, 2070: 2,
  2060: 14, 2050: 4, 2040: 16, 2030: 8). 2026: 13,882; 2025: 22,175;
  2024: 14,954; 2020s: 89,075; 2010s: 33,594; 2000s: 9,828; 1990s: 3,747.
  cat_works 129,457; year NULL/0: 9,555 (7.4%); `first_seen_at` NULL: **0**
  (always populated — good tiebreak); year > 2026: 46.
- posts has NO year index (only source/canonical/tmdb/imdb/slug). cat_works
  has `idx_cat_works_title (title, year)` and `idx_cat_works_browse
  (updated_at DESC)` — neither serves year-DESC ordering.
- Cost, same served GROUP BY query shape, live DB, warm cache:
  `ORDER BY p.id DESC LIMIT 20` = **0.002s** (LIMIT short-circuits via PK
  order). `ORDER BY COALESCE(p.year, 0) DESC, p.id DESC LIMIT 20` =
  **4.846s** (EXPLAIN adds `USE TEMP B-TREE FOR ORDER BY` — must group ALL
  ~135k posts before sorting). Naive year-DESC top row is id 24853, year
  **2099** — junk future years would top the list without a clamp.
- Two-step design (probe 2, `/tmp/year-probe2.py`, live): step 1 ids-only
  `ORDER BY <clamped year> DESC, p.id DESC LIMIT 20` = **0.328s** (page 1),
  0.338s (OFFSET 20), 0.548s (OFFSET 1000); step 2 counts for just those 20
  ids = **0.001s**. Total ~0.33s, ~15x cheaper than the one-query shape, no
  index, no migration, no projection rebuild. Clamped top-20 is exactly
  right: 2027 Star Trek: Strange New Worlds S04 first (genuine next-year
  title), then 2026 titles by id DESC; junk years (2099, 2077, 2073, 2067 —
  mostly mis-parsed titles like "Cyberpunk 2077") buried with the NULLs.
- v2 newest-expr timing over cat_works: 0.424s, top row year 2099 (unclamped).

## Design (built, not just reported)

Newest-first = year DESC, then id DESC (total order, stable offset paging),
with the year clamped: effective year = year if 1900 <= year <=
current_year+1 else 0 (sorts last with NULLs); ceiling from SQLite
`CAST(strftime('%Y','now') AS INTEGER)` so it never rots. `+1` headroom
keeps genuine next-year titles (Star Trek S04, 2027) on top.

- `/api/v1/posts` (`viewer.py`): `sort=""` (the app's Home/Browse/Search
  default) and explicit `sort=newest` take a **two-step path** — step 1 picks
  the page's ids from `posts` alone with the clamped year order; step 2
  fetches the page's counts by id (`p.id IN (...)`, no ORDER BY, no LIMIT);
  the order is imposed in Python. `rating` / `title` / `trending` keep the
  exact single-query path; unknown sort values keep today's `p.id DESC`.
  The WHERE is reused verbatim in step 1 (every clause names only `p.*` or a
  self-contained EXISTS — verified by grep; the adult clause, hides, facets
  and fuzzy ids all carry over unchanged).
- `catalog_api.py _sort_expr("newest")`: same clamp applied to the v2
  expression, so v2 newest stops topping 2099 junk. v2 browse default stays
  `trending` (unchanged — the app does not call it).
- No scraper/importer touched (user order). No index, no migration, no
  projection rebuild.

## Seasons — measured, NOT built here (app-side work)

- v1 post detail releases order `season ASC, episode ASC` (`viewer.py:862`);
  v2 work detail serializes seasons `ORDER BY number` ASC
  (`catalog_api.py:1496`); episodes `ORDER BY s.number, e.number` ASC.
- The app re-sorts seasons ASC itself (`V1CatalogMapper.kt:101` `.sorted()`),
  and **the app never uses v2 work detail** (only `AccountWire.kt`
  references CatalogV2 types; `DetailViewModel` has no v2 detail call). So a
  server-side season flip would change NOTHING the user sees. Seasons
  newest-first needs an app change (mapper `.sorted()` →
  `.sortedDescending()` + default selected season = newest) — Session 114 or
  the next app session. Episodes within a season must stay ASC (E1→E2 is
  correct viewing order); only the SEASON list order flips.

## What was built

- `Fast_Fetch/viewer.py`: `_NEWEST_YEAR_SQL` constant; sort branch maps
  `""` / `"newest"` to the two-step path (`order_sql = None` sentinel);
  step-1 ids query + early empty return; `select_sql` shared by both paths;
  step-2 by-id fetch; Python reorder by the step-1 id list.
- `Fast_Fetch/catalog_api.py`: clamped `newest` expression in `_sort_expr`.
- Tests (3 new):
  - `test_database.py::DatabaseSaveTests.test_api_v1_list_defaults_to_newest_first`:
    7 seeded rows (2026/2025/2000/1999/NULL/0/2099) — default years
    `[2026, 2025, 2000, 1999]` then `{None, 0, 2099}`; explicit newest
    matches default; title stays alphabetical; trending stays id DESC.
  - `test_catalog_api.py::BrowseTests.test_newest_clamps_junk_and_missing_years_to_the_tail`:
    junk 2099 + missing-year rows project and land in the tail; first item
    still 2024; clamped sequence non-increasing.
  - `test_posts_query_plan.py`: docstring + transcriptions updated to the
    new three-pass default (total + narrow ids + page); new test pins the
    ids pass DOES sort a temp B-tree (narrow, by design) while the page pass
    reaches rows by PK with no ORDER BY; old two-pass shape pinned for the
    non-newest sorts; order-B-tree test now covers unknown-sort + newest
    page + trending.
- `test_posts_query_plan.py` note: the old "two full passes" claim is now
  "three passes for the default, two for the old sorts" — the test file
  itself invites updating test + findings together when the statement
  changes, and this checkpoint is the findings doc.

## Tests

- New tests solo: test_database newest-first OK; test_catalog_api clamp OK;
  test_posts_query_plan 7 OK.
- Full modules: test_database 202 OK (skipped=1); test_catalog_api full OK;
  test_redact OK.
- Importer modules solo: test_dub_collision_census 13, test_themoviebox_links
  7, test_themoviebox_detail_api 18, test_themoviebox_import 53 — all OK.
- Negative control: with the fix stashed (`viewer.py` + `catalog_api.py`
  reverted, tests kept), both behaviour tests FAIL (1 failure each — the
  v1 test returns id DESC with 2099 first; the v2 test puts 2099 on top);
  with the fix both pass. The query-plan tests are transcription pins and
  pass either way by design.
- Full gate: **52/52 PASS** (`run-backend-gate.py`, re-run after the first
  run hit 2 failures that were a full `/tmp` tmpfs, not the code —
  `database or disk is full` in `test_media_search` + `test_usage_stats`;
  freed 169M of stale verify-clone/bundle artifacts, both modules pass
  solo 44 + 100 OK, gate re-run FAILED MODULES: 0, exit 0). The gate regex
  covers 52 modules; the 4 `importers/` modules it misses ran solo OK
  (13/7/18/53), covering all 56 backend-ci 🧪 steps.

## Live-proof plan (for the parent, after the gate deploy)

- `/api/v1/posts?limit=5` → 2027 Star Trek S04 first, then 2026 titles
  (NOT id 24853 / year 2099 anywhere near the top).
- `/api/v1/posts?limit=5&sort=newest` → same order as the default.
- `/api/v1/posts?limit=5&sort=trending` / `rating` / `title` → their old
  orders, unchanged.
- A 1998 title freshly scraped afterwards must NOT appear on page 1.
- Season order unchanged in the app until the app-side fix lands (known gap,
  not a regression).

## Open / follow-ups

- Seasons newest-first is app-side work (see above) — Session 114 or next
  app session.
- `media_search.search_by_media` `sort="newest"` has no clamp either
  (`-(int(t[4]["year"] or 0))`) — its window is id-walked and capped, so
  junk years rarely surface, but the same one-line clamp applies; follow-up.
- Offset paging can shift if a new 2026 import lands mid-scroll (same caveat
  as today's id-DESC paging); keyset/cursor paging for v1 lists is out of
  scope.
