# New-sites batch 1 — DramaDog + MegaCartoons + Castle importers

Session: Muse (subagent, parent main agent), 2026-11-10 ~01:12–02:xx PKT.
Base: main @ `5919b07`. Branch: `session-newsites-batch1`.
Scope: build only. No merge to main, no data merge (parent-gated).

## What was built

Three new importers in `Fast_Fetch/importers/`, each with an offline mocked
test module (temp DBs only) and a `backend-ci.yml` 🧪 step. Gate 72 → 75.
Registry sites 22 → 25 (`Fast_Fetch/domain_registry.json`, `updated_at`
2026-11-09T20:35:00Z).

### DramaDog — https://dramadog.app (short dramas, direct .m3u8)
- Live probe 2026-11-10 ~01:12 PKT: homepage 200 (title "DramaDog — Watch
  Short Dramas Free, All Episodes, No Ads"); `/sitemap.xml` is a sitemapindex
  of 30 child sitemaps, one per platform (dramawave, blinkdrama, goodshort,
  yourchannel, reelshort, stardust, flickreels, joyreels, dramabox, shortmax,
  netshort, rivoshort, storyreel, stardusttv, shortwave, idrama, hahip,
  moreshort, other + sitemap-pages.xml which is static pages, skipped).
  goodshort child sitemap: 2,942 drama URLs. ~19,972 series claimed.
- Drama page `/drama/<slug>` ships JSON-LD TVSeries (name, poster image,
  description, genres, `numberOfEpisodes`) + `data-ep` buttons + ep1 stream
  `https://v.dramadog.app/hls/<platform>/<id>/ep1.m3u8`. Verified on "After
  Divorce, My Three Brothers Spoil Me Rotten" (66 eps, goodshort/31001925906):
  ep1/ep30/ep60 → 206 + real #EXTM3U; ep80 → 404.
- `import_dramadog.py`: sitemapindex → per-platform child sitemaps,
  round-robin across platforms (representative batch, not 200 from one
  platform); `parse_drama_page` (JSON-LD → title/episodes/genres/poster/
  platform+id; fallback title from `<title>`, count from data-ep max);
  one post per series (media_type "series"), one release per episode
  (season 1, ep N), source_url = drama page, final_url = ep.m3u8,
  playback "direct", service "dramadog", mime
  `application/vnd.apple.mpegurl`. Ep1 + last episode Range-probed per title;
  middle eps stored active-by-pattern (`raw_meta.pattern_derived=true`);
  ep1 probe fail → title skipped; last-ep 404 → fall back to data-ep max.
  Adult via `fast_fetch.is_adult_title`. Session 106 wiring:
  `get_active_base_url` + `resolve_if_dead` retry once on 0-drama sync.
  Default DB `/home/ubuntu/radd-stream-data/dramadog.db`.
- Registry: api_type `xml_sitemap`, verified_by `sitemap`, slug `dramadog`.
- Test `test_dramadog_import.py`: 14/14 OK.

### MegaCartoons — https://www.megacartoons.net (cartoons)
- Live probe: apex 301 → www, homepage 200, title "MegaCartoons.net -
  Watch Online Cartoons". WordPress (Yoast in robots.txt).
  `/wp-json/wp/v2/posts` works (200, real posts). Posts carry a
  `video-series` taxonomy term id (e.g. 123 = DuckTales), resolvable via
  `/wp-json/wp/v2/video-series?include=<ids>&_fields=id,slug,name`.
  video-series sitemap: 31 series; video-sitemap.xml: 400 locs. Video NOT
  in wp-json content (synopsis only); post page HTML carries the direct
  .mp4 twice (JW Player `file: "https://ww.megacartoons.net/cartoons/
  ducktales/woo-oo.mp4"` + JSON-LD VideoObject `contentUrl`) and poster as
  `og:image`. No signing, no login.
- `import_megacartoons.py`: wp-json enumerate
  (`/wp-json/wp/v2/posts?per_page=100&page=N&orderby=date&order=desc`,
  `_fields=id,slug,link,title,date,video-series`); `fetch_series_names`
  via `video-series?include=`; page fetch per post → `parse_post_page`
  (.mp4 + og:image poster); `build_series_records`: one post per series
  (media_type "series", `is_animated=1`), episode N = date-ascending
  position in series (site publishes no S/E numbers; wp post id + title in
  raw_meta); play gate = Range 206 + video/mp4 AND ffprobe (video + audio
  + duration > 0) → `active`, else `unverified` (missing ffprobe binary
  fails closed the same way); `--no-ffprobe` flag. Default DB
  `.../megacartoons.db`.
- Registry: api_type `homepage` (NOT wp_rest_api — cartoon titles like
  "Woo-oo!" carry no QUALITY_MARKER, so the tracker's wp-json proof would
  fail with `wp-json-no-quality-marker`; enumeration via wp-json is
  documented in the registry entry's `notes`), verified_by `homepage`,
  mirrors apex + www.
- Test `test_megacartoons_import.py`: 12/12 OK.

### Castle — https://www.bulwik.com (movies; series out of batch 1)
- Live probe: homepage 200 (title "Hindi Dubbed Movies & Series, Free
  Streaming | Castle"). robots.txt names Sitemap: /sitemap.xml.
  sitemapindex: 204 child sitemaps — `/movies/sitemap/1..100.xml` (100 locs
  each, ~10,000 movies) + `/series/sitemap/1..100.xml` (~10,000 series
  season pages); "1 lakh+" claim is inflated.
- Movie page `/movie/<slug>/<id>` ships JSON-LD Movie (name, poster image
  `img1.bhcxy.com`, description, genre, datePublished, duration `PT123M`,
  contentRating PG) + signed HLS master
  `https://img01.tlnob.com/video/<hash>/index_401.m3u8?auth_key=…&expire=…`.
  The URL is JSON-escaped in the page (`\u0026` for `&`) and MUST be
  unescaped — a truncated URL (no expire param) 403s. Signature lives ~3h
  from minting; the page may be CDN-cached with an already-expired
  signature (a URL minted ~13h before its page fetch 403d, while a fresh
  one 200d with real #EXTM3U). Fresh signed URL pressed 3 ways (plain GET,
  +Referer, +Range) all → 200/206 + #EXTM3U.
- Series season pages (`/series/<slug>-season-N/<id>`) carry JSON-LD
  TVSeries (name, cast, numberOfEpisodes) but only ONE signed.m3u8 in
  static HTML; episodes 2+ load via JS with no discoverable endpoint —
  series are OUT of batch 1 (movies only), follow-up is JS-bundle analysis.
- `import_castle.py`: walks `/movies/sitemap/N.xml` in order (skips
  non-`/movie/` locs); `parse_movie_page` (JSON-LD Movie → title/year/
  genres/poster/duration via `parse_duration_iso` PT123M→123; contentRating
  + adult-title check → is_18_plus); signed URL extraction with
  `unescape_page_url` (strips trailing `\` first); expire param parsed,
  stale if < 10 min left (`STALE_SIGNATURE_SECONDS=600`); `build_record`:
  one post per movie (media_type "movie"), one release, one source,
  `is_temporary=1`, fresh+probed → `active`, stale/unprobed → `unverified`,
  no signed URL → None. Default DB `.../castle.db`.
- `host_resolvers.py`: `SERVICE_CASTLE = "castle"`, `CASTLE_HOST_RE`
  (bulwik.com), `CASTLE_PAGE_RE` (`/movie|/series/<slug>/<digits>`),
  `CASTLE_M3U8_RE`, `CASTLE_EXPIRE_RE`; `is_castle_page()`;
  `_castle_unescape()`; `unwrap_castle(url, fetch=None, verify=True)` —
  fetches the page, takes first `index_*.m3u8` tlnob URL (unescaped),
  parses expire → `expires_in`, Range-probes via
  `_probe_playlist_or_file(final_url, fetch, page_url)`; non-Castle URL →
  unknown before any request; page 404/410 → dead, 401/403/429 → blocked,
  else unknown; verify=False → unverified, page only. Wired into `main()`
  CLI dispatch (`elif is_castle_page(url)` before the mxdrop fallback).
- `fast_fetch.py`: Castle branch in the resolve dispatch, after the
  MovieBox branch (before vidbolt): triggers on `service in
  (hr.SERVICE_CASTLE, "castle")` or `"bulwik.com"` in source_u/cached_u;
  calls `hr.unwrap_castle`, sets fresh_url/fresh_temp/embed_verdict/
  `_gate_from_verdict` exactly like the MovieBox branch. Stored final_url
  never served, re-extract per press, importer must store the bulwik page
  URL as source_url.
- Registry: api_type `xml_sitemap`, verified_by `sitemap`, slugs
  ["castle", "bulwik"], notes record ~3h signed URL + unwrap_castle +
  series follow-up.
- Tests: `test_castle_import.py` 14/14 OK; `test_host_resolvers.py`
  230/230 OK (was 222, +8 `TestUnwrapCastle`).
- DramaDog slug-form fix (live 2026-11-10): `M3U8_RE` now also matches the
  drama slug as the stream id (blinkdrama/flickreels); test_dramadog_import
  14 → 15. The no-stream-in-static-HTML platforms (dramawave, yourchannel,
  reelshort, stardust, joyreels, …) still skip — JS/API follow-up.

## Real bug the tests caught and fixed
The signed-URL regex `[^\s"'<>\\]+` stopped at the backslash before
`\u0026`, truncating the URL (no expire param → CDN 403s) — the same
truncation the live probe hit. Fixed in BOTH `import_castle.py` and
`host_resolvers.py`: regex now `[^\s"'<>]+` (allows backslashes, stops at
the quote) + `unescape_*` strips a trailing `\` before `json.loads`.

## Test-harness fix the suites caught
`test_database.py` failed 8 resolve-routing tests (cineverse, filmu,
vibuxer, vidbolt, vidrift, iqsmart + 2 fall-throughs) because the
`_FakeResolvers` stub had no `SERVICE_CASTLE` — my new branch evaluated
`hr.SERVICE_CASTLE` first and the chain never reached the later branches.
Fix, mirroring the repo pattern: added `SERVICE_CASTLE = "castle"` +
`unwrap_castle` (active verdict, tlnob final URL, expires_in 10800.0) to
the stub, plus a new Castle routing test
(`test_resolve_live_source_routes_a_castle_row_to_the_castle_unwrapper`,
bulwik movie page → tlnob .m3u8, Stage-2 probe stubbed failing). Also
updated `test_domain_resolver.py`:
`test_shipped_registry_is_v2_with_all_22_sites` → `..._25_sites`.

## Suites run solo (CI way), all green
- test_dramadog_import.py 15/15 (was 14, +1 slug-form test);
  test_megacartoons_import.py 12/12;
  test_castle_import.py 14/14; test_host_resolvers.py 230/230;
  test_docs_invariants.py 22/22; test_domain_resolver.py 39/39;
  test_database.py 217/217 (was 216, +1 Castle routing test);
  test_redact.py 82/82.

## Live syncs (staging DBs only — run on the Oracle VM after the code lands)
Tracker run DONE 2026-11-10 ~01:41 PKT (evidence:
`~/workspace/goals/radd-stream-on-oracle-vm/hidden_files/registry-batch1-evidence-20261110.json`):
dramadog → https://dramadog.app, sitemap, active; megacartoons →
https://www.megacartoons.net, homepage, active; castle →
https://www.bulwik.com, sitemap, active. The run updated the COPY's
last_verified stamps (20:42:55–57Z); the committed registry keeps 20:20:00Z.

### DramaDog — DONE 2026-11-10 ~01:5x PKT, staging DB verified
- Sync 1 (limit 200, delay 0.25): 63 posts / 2,650 releases / 2,650
  sources, 137 skipped, 200 pages fetched, 0 failed.
- Skip diagnosis (live probe `/tmp/diag_dramadog.py`): the stream id is
  numeric on goodshort/blinkdrama but the drama SLUG on blinkdrama/
  flickreels (`hls/blinkdrama/hearts-under-fire/ep1.m3u8`); the importer's
  `M3U8_RE` only matched digits, so slug-form titles were skipped. The slug
  form plays and generalizes (ep2/ep30 → 206, ep51 → 404 at 51 eps;
  flickreels ep34 → 206). Fix: `M3U8_RE` group 2 widened to
  `[A-Za-z0-9_-]+`; new test `test_slug_stream_id_parses_and_generalizes`
  (test_dramadog_import.py 14 → 15, all OK).
- Sync 2 (same 200, upsert-safe): 89 posts / 3,683 releases / 3,683
  sources, 111 skipped. Verify OK (0 flagged 18+, 0 posts without release,
  0 sources without final_url). Platforms: blinkdrama 16, goodshort 16,
  flickreels 16, dramabox 13, shortmax 10, netshort 5, storyreel 3, +
  singles (17 platforms). Sample titles: "The Fallen Elf Princess",
  "Reborn to Freeze Them All", "My Fiancé Impregnated My Adopted
  Sister", "The Wolfless Alpha Walks Away".
- Remaining 111 skips: platforms whose drama pages carry NO stream URL in
  static HTML (dramawave 5,437 urls, yourchannel, reelshort, stardust,
  joyreels, …) — the stream URL loads via JS/API there. Follow-up: find
  the episode API/JS bundle for those platforms; the importable pool from
  static HTML is the ~17 platforms above.

### MegaCartoons — DONE 2026-11-10 ~02:11 PKT, staging DB verified
- ffprobe timed on the sample .mp4 (DuckTales "Woo-oo!"): video + audio,
  duration 2,643s, 6.1s per file (network-bound) — gate stayed ON.
- Sync (limit 200, delay 0.25, ~20 min, mostly ffprobe): 4 posts (series) /
  200 releases / 200 sources, ALL 200 active, 0 unverified. Verify OK
  (0 flagged 18+, 0 posts without release, 0 sources without final_url).
  Series: The Looney Tunes Show, The Batman, Spider-Man: The Animated
  Series, DuckTales (newest-first wp-json order clusters recent posts in
  few series). Sample final_url:
  `https://ww.megacartoons.net/cartoons/ducktales/the-last-adventure.mp4`.
- SSH dropped twice mid-run (hatch egress proxy flake, ~4.5 min per
  session); the sync process survived both drops (session leader) and
  finished. Lesson: for long VM syncs, a detached/nohup run + a separate
  waiter is sturdier than holding one SSH session.

### Castle — DONE 2026-11-10 ~02:2x PKT, staging DB verified
- Sync 1 (limit 200, delay 0.25, ~146s): 151 posts / 151 / 151, 48 skipped,
  1 page failed. BUT only 29 active / 122 unverified.
- Cause (proven from the DB): the signed URL `expire` is MILLISECONDS
  (13 digits); the importer interprets it correctly (fresh→active,
  stale→unverified, zero crossovers). The 122 stale rows all carried
  signatures minted ~14h before the sync (e.g. −863.6 min left) — the
  pages served CDN-cached signatures. The fail-closed design worked: stale
  was stored unverified, never served as active.
- Re-fetch test (3 stale pages, ~02:20 PKT): ALL THREE came back with
  FRESH signatures (176.5 min left) — a fresh page fetch re-mints, so
  press-time `unwrap_castle` re-extraction works for these rows, and a
  re-sync flips them.
- Sync 2 (same 200, upsert-safe): 149 written, 50 skipped, 1 failed.
  Final DB: 159 posts / 159 releases / 159 sources, 152 active, 7
  unverified, 0 flagged 18+, verify OK. Sample titles: "The Dark Heaven",
  "Software Sudheer", "Mookuthi Amman 2", "All Pass", "7 Star Boys",
  "Godzilla Minus Zero". Sample final_url:
  `https://img01.tlnob.com/video/ea0c32…/index_401.m3u8?auth_key=…&expire=1794269604272`.
- Remaining: 50 skipped (no signed URL on the page — needs a look at what
  those pages carry instead) + 1 page failed + 7 unverified. The 48→50
  skip count moved slightly between runs; the skip set is worth one
  diagnostic pass in a follow-up, not in this batch.

## Full-harvest estimates (what remains after the ~200/site proof batch)
- DramaDog ~19,972 series (sitemap platform counts; goodshort alone 2,942).
- MegaCartoons ~1,200+ posts across video-sitemaps (31 series).
- Castle ~10,000 movies + ~10,000 series season pages (series need the
  JS episode-loading follow-up first).

## Open items / follow-ups (not in this batch)
- Castle series: episode-loading endpoint needs JS-bundle analysis.
- MegaCartoons episode numbering is positional (date-ascending within
  series); a later pass could use the series page order.
- DramaDog middle episodes are active-by-pattern (probed at both ends per
  title); play-time Stage-2 probe is the final gate.
- ffprobe timing on the VM untested (check before the MegaCartoons live sync).
