# Session 2026-10-29 (qoder2 fleet lane) — mp4 vault, four WP sites, filmywap retry

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (qoder2 fleet lane) — mp4 vault, four WP sites, filmywap retry

**Scope.** Scraper lane only: `Fast_Fetch/importers`, importer tests, `SITES.md`, and
per-site staging vaults under `/home/ubuntu/radd-stream-data/`. The production catalog
(`merged_catalog_20261025.db`, `fast_fetch.db`) was never opened; no prod merge was run.

**mp4moviez vault (ready for the merge queue).**
`/home/ubuntu/radd-stream-data/mp4moviez_staging.db` — 11,403 posts / 54,263 releases /
54,263 sources / 32,967 sitemap rows, 43 posts `is_18_plus=1`. Built by the new
`convert_mp4moviez.py` (legacy rows → staging shape, survivor per canonical key, unioned
releases). Proof: a full-vault merge into a fresh temp target produced exactly
11,403 / 54,263 / 54,263 in 271.3 s with **0 identity conflicts** and no duplicate
`source_url`; converter + 10 tests committed (`81cdff8`). The master merge queue owns the
actual load.

**pagalmovies.** Re-pulled the 714-byte sitemapindex and its children against the 16,022
`loc`s already cached: 8 new `.casa` locs, all serving the byte-identical 24,955-byte
homepage shell (HTTP 200). The shell verdict is now `soft404_homepage_shell` (retryable,
not `removed`); the 6,439-row shell cohort was re-sampled and recovered 0 posts.
Committed `cb988d3`.

**KuttyMovies.** 905 sitemap locs → 900 posts / 2,530 releases / 2,530 sources, 5 locs left
queued on transport failure, 0 parked, 3 posts `is_18_plus=1`, 1,262 s at one worker and
no 429.

**Four new sites (scout → staging DB → bounded pilot → SITES §20–§23).**

| Site | Queued locs | Pilot pages | posts | releases | sources | adult |
|---|---|---|---|---|---|---|
| moviehax | 15,174 | 40 | 35 | 35 | 62 | 17 |
| bollyflix | 17,837 (REST) | 40 | 38 | 91 | 91 | 9 |
| hindidubbedmovies | 2,117 | 40 | 40 | 49 | 57 | 0 |
| hindianimeszone | 821 (REST) | 40 | 36 | 40 | 40 | 1 |

moviehax plays only through `POST /wp-admin/admin-ajax.php` `action=doo_player_ajax` (the
look-alike action answers 400, `/wp-json/dooplayer/v2/…` answers an empty 200). bollyflix
and hindianimeszone publish no usable post sitemap, so the importer seeds from open WP REST
(`X-WP-Total` / `X-WP-TotalPages`). hindidubbedmovies uses LiteSpeed lazy iframes
(`data-litespeed-src`) plus first-party `trembed`/`trdownload` links; its whole-pilot merge
into an empty target landed 40 / 49 / 57 / 40 with 0 conflicts. All adult flags are set at
write; no adult title is displayed anywhere.

**Filmywap (cooldown honored).** 1,522 sitemap locs → **80 posts / 3,966 releases /
3,966 sources**, 2 adult, 1 parked (`9-1-1`, three `http-500`), **1,441 locs still queued
with zero attempts spent**. The site is episode-bound (~22.5 episodes per series, one API
call each; 75 s/page measured), so a 120-page batch overran the hour and then met an
`http-429`, which wrote `kind=http-429` on that row, paused the run, and left the queue
intact. A stalled `/api/stream` used to burn two 60 s timeouts per episode (four lost
episodes ≈ 800 s); episode walks now make one attempt and abort after three consecutive
failures, recording `episode_gaps` / `episode_aborted` in `posts.raw_meta` (`0d1dd71`).
Residue: one early post (`Aghori Baba`) has no releases, carried over from the first build.

**Gate.** All 15 CI modules green (`test_database` 76, `test_vidout` 6, `test_catalog_v2`
91, `test_release_descriptor` 24, `test_link_health` 57, `test_link_state` 28,
`test_evidence_writeback` 12, `test_api_v2` 46, `test_redact` 49, `test_tiers` 23,
`test_catalog_api` 127, `test_provenance_stamping` 12, `test_merge_catalogs` 5,
`test_site_scout` 25, `test_backup_manager` 14) plus `test_host_resolvers` 171,
`test_pagalmovies_import` 65, `test_convert_mp4moviez` 10, `test_import_wp_family` 23,
`test_filmywap_import` 35, `test_kuttymovies_import` 45.

**Push state.** Local HEAD carries seven commits on top of `94d40fc`; remote `master`
(`f3924a3`) is 13 ahead. `git merge-tree` reports content conflicts in `AGENTS.md`,
`docs/PROJECT_MAP.md` and `docs/SESSION_CHECKPOINT.md` — all three owned by the master
lane — so `HEAD:master` was not pushed then; the lane's commits went to
`refs/heads/qoder2-fleet-20261029`. Master integration has since been done by merging
`f3924a3` in an isolated worktree, taking the master lane's text for those three docs
plus `AGENTS.md`; this log is on `master`/`main` after that merge.

