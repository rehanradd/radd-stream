# Spec Fast Fetch Catalog State

> Moved **verbatim** out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `Fast_Fetch/AGENTS.md`
> carried at this sha. Law stayed in `Fast_Fetch/AGENTS.md`; this is the reference prose it now links to.
### from `Fast_Fetch/AGENTS.md` lines 222-260

### Unified catalog — measured 2026-10-29 on the live host

The previous version of this table described the 2026-10-13 seed database
(51 titles, 1,662 releases, 4,351 sources). That is not the catalog any more, and
quoting it makes an agent plan work that is already done.

| Metric | Value |
|--------|-------|
| `posts` (ledger rows) | 146,176 |
| — of which `is_18_plus = 1` (stored, never displayed) | 14,617 |
| — displayable to a public caller | 131,559 |
| `releases` | 1,764,686 |
| `download_sources` | 4,044,659 |
| `post_sources` (per-site page links) | 300,013 |
| Distinct `source_site` | 28 → **31** with the third merge batch |
| Staging databases merged | 2 batches + `merged_catalog_20261025.db` in place |
| Third merge batch, landing 2026-10-29 | pagalmovies, filmyhit, filmywap |

**Link liveness is not a count of `status = 'active'`.** Every ingested row is
written `active` by the scraper, so before `link_state.propagate()` has knocked on
an endpoint, `status` proves nothing. `/api/v1/stats` now publishes
`sources_by_state` alongside the totals, and `active_sources` counts only links
with measured evidence behind them — a freshly merged catalog honestly reports
`active_sources: 0` with the whole population under `unchecked`.

### Sitemap breakdown — 2026-10-13 crawl state (superseded)

Kept for history. The current per-site queue is in `sitemap_cache` in the live
database, and in `SITES.md` §15; read it there rather than trusting this table.

| Site | URLs (Oct 13) |
|------|------|
| Vegamovies | 14,025 |
| FilmyZilla | 5,002 |
| RogMovies | 2,000 |
| HDHub4u | 1,000 |
| BollyShares | 200 |
| 7StarHD | 28 |
| SSRMovies, KatMovieHD, 10xflix, MultiMovies | via API/live fetch |
