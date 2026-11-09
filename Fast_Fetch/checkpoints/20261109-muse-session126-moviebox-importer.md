# Session 126 — MovieBox importer: feed filters + trailer-CDN drop (2026-11-09)

Parent-reviewed, built by builder e8dd63aa in the Session 126 MovieBox
full-catalog job. Branch `session126-moviebox-importer`, base main `ce4fdd1`.
The full harvest and its endpoint map live outside the repo in
`~/workspace/goals/radd-stream-on-oracle-vm/hidden_files/moviebox-full-catalog-map-20261109.md`;
this checkpoint covers only the code change landing here. The data merge
(3,411 works into the live catalog) is a separate parent gate job.

## What changed

`Fast_Fetch/importers/import_themoviebox.py` (+73/−8):

- Feed filters: `_walk_feed` takes `filters` merged into the filter POST
  body; threaded through `sync_catalog` and `harvest_catalog` and exposed
  as CLI `--year/--genre/--sort/--country/--classify` on `sync` and
  `harvest`. Measured 2026-11-09: `{"year": "2024"}` (a STRING — an integer
  400s) returned 50/50 items with releaseDate in 2024; `{"genre":
  "Action"}` returned 44/44 carrying Action. `subjectType` is decoration
  and is not relied on. Only `sort=Latest` enumerates works (disjoint
  pages); `Hot` returns sports clips, `newest` concert mixes, unsorted
  pages reshuffle. Year cells cover 2019–2026 only; each year caps at 100
  pages (5,000 items).
- Trailer-CDN drop: `_direct_media_urls` drops any URL on
  `macdn.aoneroom.com` outright. Measured on two live movies: the only
  macdn mp4 in a detail payload is the trailer (82 s / 117 s, 2.7 MB /
  4.6 MB), mirrored once more in a sibling `video` array outside the
  `trailer` subtree — which is how the proof crawl staged two trailers as
  `-sd` prints. A work's own print is never on macdn (resolved through
  the play API to a signed URL on another host). The trailer URL stays in
  `raw_meta` as evidence, never as a source.
- Module docstring corrected (the old "cannot be filtered" claim) and the
  search-token flow documented (X-Client-Token `<unix-seconds>,<md5 of
  reversed seconds>` → `x-user` header → Bearer for `/subject/search`;
  never send both headers).

`Fast_Fetch/importers/test_themoviebox_import.py` (+27): PRINT_URL fixture
host moved off macdn to `pbcdnw.aoneroom.com`; new regression test
`test_a_macdn_url_is_dropped_wherever_it_sits` (trailer in a sibling
`video` array must not become a release, must stay in `raw_meta` as
evidence); docstring rule updated.

`Fast_Fetch/importers/test_themoviebox_links.py` (1 line): playable-URL
fixture host moved off macdn.

## Verification (parent, at the branch tip)

- `test_themoviebox_detail_api`: 18 OK.
- `test_themoviebox_import`: 54 OK (was 53; +1 regression test).
- `test_themoviebox_links`: 7 OK.
- Staging counts verified directly on the VM before this commit:
  3,411 posts (2,687 movies, 724 series), 8,849 releases, 8,849 sources,
  0 direct links, 16 adult posts, 43 metadata-only posts.
- Play probes (builder, resolver `unwrap_moviebox` verify=True): movies
  3/3 active; series 8/9 active on retry (9th failed 3× on transport
  only); final 6/6 active (newest + oldest movies and series, incl. 12
  Angry Men 1957).

## Deliberately not in this change

- No merge: staging only. The merge gate (fresh backup → merge_catalogs
  → verify counts + press a merged row → v2 projection rebuild) runs
  separately; the 16 adult posts must carry the 18+ flag through, and the
  43 metadata-only posts must not be treated as an error.
- No search-based harvest: 172 seed rows failed deterministically
  ("no-subject", 168 titles missing incl. Aquaman and Avengers: Endgame)
  and the 43 metadata-only posts need the search API (Bearer flow) as the
  recovery path — a follow-up importer feature.
- No resolver transport retry: `host_resolvers.http_request` returns
  status 0 on the first TLS reset while the importer retries 6×; the
  intermittent "unknown" verdicts at press time are a follow-up.
- No year+genre gap-fill for the 100-page cap; no `/platform/play-list`
  probe; 123moviesfree.club not harvested separately (same backend, dedup
  by canonical key would collapse most of it).
