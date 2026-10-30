# Session 2026-10-30 (qoder4 master orchestrator) — Antigravity's MovieBox importer, finished, tested, and run bounded `[Q4-MASTER]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-30 (qoder4 master orchestrator) — Antigravity's MovieBox importer, finished, tested, and run bounded `[Q4-MASTER]`

**What the owner asked, literally:** "if you have not started moviebox scraper then
check it and run it". Checked first, and the honest answer was that the scraper
existed but *could not have produced correct data*: `import_themoviebox.py` sat
untracked in the live tree at 1,383 lines, `themoviebox.db` was 53 KB and empty,
and the scout blueprint that seeded it claimed `cms: unknown`,
`rest_api.usable: false`, `data_source: html_scrape`, `link_patterns: []`,
`sitemap_url: null`. Three of those four claims are false.

**Measured, not assumed.** `/sitemap.xml` is a real HTTP 404 (12 connections, one
answering a 130,846-byte HTML page). The catalog is the site's own JSON feed —
`POST h5-api.aoneroom.com/wefeed-h5api-bff/subject/filter` — which answers 200
unauthenticated with full subject objects. The playable print is nowhere in it or
in any detail page: `detailUrl`/`sniffUrl`/`sourceUrl` empty, `dl: null`,
`resource.seasons[].resolutions[]` names 360/480/1080 with no URLs, and the only
mp4 anywhere is `trailer.videoAddress.url` on the **same** `macdn.aoneroom.com`
edge with the **same** `-ld/-sd/-hd.mp4` shape. Graph position is the only thing
that tells a trailer from a feature, so the media walk prunes by key and drops —
unconditionally — anything not on the site's own media hosts.

**Five rules the live captures forced**, each now a test: one work per detail page
(a measured page returned 19 records, 18 of them cast members and banners);
`subjectType` is the only media-type authority because `season: 0` with
`seasons[{se:0,maxEp:0}]` is the site's "not a series" sentinel; a dub is a
**separate subject** with the same title and year, so identity is
`subjectId → detailPath → title`; artwork is an object (`cover.url`, `blurHash`,
`avgHue*`) not a string; and a titled subject with no print is **written**, not
called an error.

**Two defects the mocked suite caught before anything shipped.** The lenient host
filter staged a foreign ad mp4 as a film's print. And `harvest_catalog` held a
write transaction while `export_staging` opened a **second** connection to the
same file — SQLite waited the full 60 s and raised `database is locked`, so every
live harvest died at its first batch. `export_staging` now takes `conn=`.

**Live pilot (bounded, `nice -n 19 ionice -c3`, started at load 5.1 / MemAvailable
5,099 MB / SwapFree 3,180 MB, finished at load 4.2).** `harvest --pages 2
--limit 40` → 46 items, **40 posts, 6 rejected as music mixes, 0 duplicates, 0
locks**. `crawl --limit 6 --workers 1 --delay 1.0` → **6/6 pages in 39 s, 6
metadata-only, 0 failed, 0 releases, 0 sources** — the detail pages carry the same
empty print fields the feed does, so the finding is now measured on both surfaces.
Final vault: 44 works, 0 releases, 0 sources, 44 with poster/year/genre/rating,
10 with a real dub list, 0 adult-flagged in the sample.

**The live run then caught three more defects a mocked suite structurally
could not**, and this is the argument for running things bounded instead of
trusting green unit tests: `duration: 0` landed as a real running time in 40 of 40
rows; a present-but-empty `subtitles: ""` shadowed the populated `dubs: []`, so a
triple-dubbed work stored **no languages at all**; and — the big one — the server
**ignores the `subjectType` body key**, so the per-type request loop was fetching
one random soup twice. `{subjectType: 1}`, `{2}`, `"1"}`, `{subjectTypes:[1]}` and
`{subjectType:1, areaName:"india"}` all return the identical type histogram.
`sort` is honored and only swaps in different non-works (`sort=newest` → type 7
concert mixes, `sort=hot` → type 9 sports clips).

**Therefore MovieBox is not a bulk-crawlable catalog and will not be treated as
one.** 100 items over 2 pages against a 44-row vault produced **84 duplicates and
4 new rows**; `pager.totalCount: 1000000` is a pager fiction. The one endpoint that
*does* filter (`/subject/search`) is authenticated, and the site's own bundle
computes the `X-Client-Token` client-side — that token is their access control and
this importer does not reverse-engineer it. Everything recorded here comes from
endpoints answering 200 to an unauthenticated browser request
(`/subject/trending`, `/home?host=`, `/tab/get-bottom-tab-list` all do).
Schedule the site as a **periodic metadata top-up**; never list it as
scraped-and-playable.

**Corrected doc:** the scout blueprint at
`/home/ubuntu/radd-stream-data/themoviebox_blueprint.json` was rewritten in place
with the measured values (`data_source: json_feed`, `rest_api.usable: true`, the
type table, the transport flapping rate, the token boundary) and every superseded
claim left visible in its `notes`; the pre-revision file is at
`/tmp/themoviebox_blueprint.pre-revision.json`. `SITES.md` gains §25 and a row in
the §15 built table carrying the metadata-only caveat in the table itself.

**Numbers.** 47 tests in `test_themoviebox_import.py` (network fully mocked),
plus CI's real 17-module list re-run locally on the same tree. No Gradle, no
service restart, no write outside `themoviebox.db`, production catalog untouched.

**Next on this lane:** nothing. The importer is honest about what it can and
cannot get; the remaining MovieBox work is a different problem (a print resolver
for a client-side play path we have deliberately not reverse-engineered), and it
is not worth a fleet slot while the app lane and the projection (#10) are behind.

---

