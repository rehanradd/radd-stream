# moved verbatim out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

## 9. Database Tables (Implemented Schema)

`fast_fetch.py` is the source of truth for the SQLite schema and migrations.
The live database uses `posts`, `post_sources`, `releases`, `download_sources`,
`sitemap_cache`, and `domains_config`. It does not use the conceptual
`media_entities` or `source_urls` tables shown in earlier notes.

- `posts` holds shared title metadata and external IDs. Its `canonical_key` is
  indexed, not unique; title/year alone is not enough to force a merge.
- `post_sources` maps each `(source_site, URL)` to a `posts.id`, retaining the
  original site page URL, site-specific title and slug, and seen timestamps.
- `releases` belongs to a `posts.id` and carries its own `source_site` plus
  `origin_url` — the page that produced it. Releases are replaced per page, never
  per site, because one title can be published across several pages of the same
  site (a season page and an episode-pack page). Replacing per site silently
  deleted the earlier page's releases.
- `download_sources` belongs to a release and stores its source/health fields.
- `sitemap_cache` records discovery and crawl status; a successful scrape also
  creates a `post_sources` mapping.

Identity resolution prefers a matching IMDb/TMDB ID, then a previously
associated site URL, then a single title/year key of the same media type.
Conflicting IDs, URL mappings, or multiple canonical candidates fail explicitly
instead of picking the oldest database row. See `DATABASE_SCHEMA.md` for the
full schema and indexes.

### 9b. Catalog v2 (design approved, implementation in progress)

`Fast_Fetch/API_V2.md` is the contract for the next layer: a `cat_*` projection over
this ledger (works / seasons / episodes / releases-prints / links / tracks / evidence /
entitlements) plus the v2 REST surface the Android app and a future website will consume.
Read it before designing any new endpoint. Rules of thumb already settled there:
the ledger is append-only and never hand-edited, the projection is disposable and
rebuildable, movie/series never cross-merge, print quality and link playability are two
separate scores, and adult rows are stored but return 404 on every presentation surface.

---

