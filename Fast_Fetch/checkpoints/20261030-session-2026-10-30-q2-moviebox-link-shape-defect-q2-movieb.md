# Session 2026-10-30 (q2, MovieBox link-shape defect) `[Q2-MOVIEBOX]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-30 (q2, MovieBox link-shape defect) `[Q2-MOVIEBOX]`

**The owner's question, answered by measurement, not by the old prose.** The staging vault
`/home/ubuntu/radd-stream-data/themoviebox.db` (114 KB) reads `posts 44 / releases 0 / sources 0`,
and the older entries that call this importer "finished" are true about metadata and misleading
about links. Two bounded read-only probes on 2026-10-30 02:26 settled why:

- `GET /detail/prison-break-mdR9oayBqn3` → 200, 409,998 B, captured at
  `/tmp/moviebox_capture/sample_detail.html`. Its `__NUXT_DATA__` (36,126 B) carries
  `detailUrl: ""`, `sniffUrl: ""`, `sourceUrl: ""`, `dl: null`, and
  `resource: {seasons: [...], source: "ailok.pe"}` with resolutions 360/480/720/1080 and per-season
  `epNum`. The only mp4 on the page is `trailer.videoAddress.url` (126 s, 848×476).
- `GET /wefeed-h5api-bff/detail?subjectId=2835060171381039112` → 200, 39,788 B. Same answer: the
  three URL fields are empty strings, `dl` is null, `resource` has tiers and no URL. `hasResource:
  true` and `watchTimeLimit: 15` say the print is resolved by the logged-in player.

**Where the pipeline stops, precisely.** It does not stop at the fetch:
`crawl_pending` → `http_get` → `parse_page` ran — 6 of the 44 `sitemap_cache` rows are `scraped=1`,
and every posted row's `raw_meta` carries page-derived `trailer_url`/`subjectId`. It does not stop
at the regex either: `MEDIA_URL_RE` matches the page's only mp4, and `_collect_candidates` prunes
it because it sits under the `trailer` key (`NONPLAYABLE_KEYS`, line ~171). The pipeline stops
where the site stops: **no playable URL is published to an unauthenticated client**. The defect
was that the parser then discarded the *structure* it had — the declared renditions — leaving the
vault reporting `0 releases` for a work whose page lists twenty.

**The fix** (`Fast_Fetch/importers/import_themoviebox.py`):
`_resource_renditions` reads every `seasons[].resolutions[]` entry (season, tier, `epNum`, source
host); `_declared_releases` turns each into a release with an **empty** source list and
`raw_meta.episodes`; `_mirror_sources`/`_attach_mirrors` store any populated `dl`-shaped mirror
with its status, `dead` included (no populated `dl` has been captured live — this is the rule for
when one appears); `_enrich_with_declared_media` is shared by `parse_page` (single-work payloads
only, so a sibling card's tiers cannot leak) and `harvest_catalog`; `crawl_pending`'s
`metadata_only` and `stats.metadata_only_posts` now count by absent **sources**, not absent
releases. Parsing the captured page with the new code yields **1 post, 20 releases (5 seasons ×
360/480/720/1080), 0 sources**, trailer kept as evidence only.

**Tests.** `Fast_Fetch/importers/test_themoviebox_links.py` — 7 tests in 0.02 s, devalue-encoded
fixtures, in-memory SQLite, no sockets; `CAPTURED_RESOURCE` is the page's `resource` block verbatim.
`test_themoviebox_import.py` kept 47/47 green with three assertions updated to the new policy
(declared tier = release, no invented source; `metadata_only` by sources). New step in
`backend-ci.yml` (26 test steps now). The existing three "releases == []" assertions on payloads
that declare no tiers are unchanged and still pass.

**What was NOT done, deliberately.** No crawl — the vault on disk still holds the 44 rows written
by the old code, so `0 releases / 0 sources` describes that file, not the parser. No write to
`themoviebox.db`, no merge, no production DB touched. No second sample page (the one page plus one
API call above were the whole budget); no repeated curls.

**Queued action — bounded re-crawl, same gate as every heavy run: load < 4 AND MemAvailable >
4000 MB AND no other crawler AND an explicit `--limit`:**

```bash
# 1) let the six already-crawled rows be re-derived (staging DB only, 6 rows):
sqlite3 /home/ubuntu/radd-stream-data/themoviebox.db \
  "UPDATE sitemap_cache SET scraped=0 WHERE scraped=1;"
# 2) crawl at most 6 pages, one worker, one second apart:
nice -n 5 ionice -c2 -n6 python3 -S \
  /tmp/q2_moviebox/Fast_Fetch/importers/import_themoviebox.py \
  crawl --limit 6 --workers 1 --delay 1.0
```

Expected cost: 6 pages × ~6.5 s ≈ 40 s wall clock (measured 6 pages in 39 s on 2026-10-30), ~1–2
CPU-seconds, under 60 connections given the ~31 % TLS success rate. Expected outcome: `releases=20`
per captured-shape series, **`sources=0`**, `metadata_only=6`. A full 44-row re-derivation is
≈ 5 minutes wall clock and should be a separate, equally gated decision.

**Correction to older prose.** The `[Q4-MASTER]` entry's "44 works staged, 0 releases and 0 sources
by design" is accurate about that run but reads as "done". The vault has never contained a
playable MovieBox link, and after this session it still does not — what changes is that a work's
declared tiers are now stored as releases instead of vanishing.
