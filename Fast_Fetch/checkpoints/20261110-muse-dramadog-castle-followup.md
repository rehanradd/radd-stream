# DramaDog + Castle follow-up — episode API, img1 variant, series verdict

Session: Muse (subagent, parent main agent), 2026-11-10 ~16:00–17:3x PKT.
Base: main @ `8033113f`. Branch: `muse/dramadog-castle-followup-20261110`.
Scope: build only. No merge to main, no data merge (parent-gated), no gate
deploy, no service restart, no APK anywhere. Staging DBs only.

## DramaDog — the no-stream platforms are solved: GET /api/eps/<drama_id>

Live diagnosis from the Oracle VM (all fetches on-VM, this session):

* The skipped platforms' drama pages carry NO `v.dramadog.app` stream, but
  they DO carry a JSON-LD `VideoObject` with ep1's `contentUrl` on the
  platform's own CDN, plus a numeric drama id (poster `/c/<id>.webp` and
  the `/api/eps/<id>` link on the page).
* `GET https://dramadog.app/api/eps/<drama_id>` answers
  `[{"host": ..., "urls": [ep1.m3u8, …, epN.m3u8]}]` — one URL per
  episode, in order. Verified on three platforms: URL count ==
  `numberOfEpisodes` exactly (dramawave 30/30, yourchannel 70/70,
  reelshort 28/28), all unique .m3u8, ep1/middle/last all Range-probe
  206 + real `#EXTM3U`.
  * dramawave: `video-v1.mydramawave.com` — "The Heir's Captive" (30 eps)
  * yourchannel: `video.indouzhuan.cn` — "Eight Years, No Longer His" (70)
  * reelshort: `v-mps.crazymaplestudios.com` — "The King's Little
    Miracle Lulu" (28)
* The data-ep buttons are doubled (60 buttons for 30 episodes — desktop +
  mobile lists), so `max_data_ep` is NOT the episode count; the API list
  is authoritative and `numberOfEpisodes` agrees with it.

Built in `import_dramadog.py` (same patterns as batch 1):

* `parse_drama_page` now also extracts `drama_id` (`/api/eps/<id>` first,
  poster `/c/<id>.webp` second) and `video_object_url` (VideoObject
  `contentUrl`).
* New `fetch_episode_urls(base_url, drama_id, fetch)` — fails closed to
  `[]` on any transport/parse/empty failure; the title is then skipped.
* `build_record` takes either URL source: the `v.dramadog.app` pattern
  (unchanged) or the API list. Ep1 + last episode are probed in both
  paths; middle episodes are active-by-pattern with
  `raw_meta.pattern_derived` + `episode_source` ("pattern" | "api").
  On the API path a last episode that does not probe trims trailing dead
  URLs (up to 3) instead of staging episodes that do not exist. One
  behavior tightening vs batch 1: on the pattern path, if the last
  episode still does not probe after the data-ep fallback, the title is
  now skipped instead of staged — fail closed.
* `sync` calls the API (with the normal delay) when a page has no
  `v.dramadog.app` stream but has a `drama_id`; `totals.api_resolved`
  counts titles resolved that way.

Tests: `test_dramadog_import.py` 15 → 25 (all OK) — drama-id extraction
(api link + poster fallback), VideoObject URL, API list parsing +
fail-closed cases, API-path build (30 releases, first/last probed,
middle pattern-derived, `resource_id` `api/22262/epN`), trailing-trim,
sync API fallback (round-robin picks one pattern + one API title) and
sync skip when the API is empty.

Proof sync (Oracle VM, staging DB
`/home/ubuntu/radd-stream-data/dramadog-followup.db`, limit 50):
48 posts / 2,203 releases / 2,203 sources, 2 skipped, 0 failed,
**22 titles resolved via the API** (1,137 sources) across stardust-tv,
my-muse, cloudfront, cinerrashort, dramoviashort, miralunedrama,
rivoshort, versevoyagetv, crazymaplestudios, mydramawave, indouzhuan,
yourwebnovel. Verify OK (0 flagged 18+, 0 posts without release,
0 sources without final_url; all 2,203 sources active). Sample API
titles: "The Heir's Captive", "Eight Years, No Longer His", "The
King's Little Miracle Lulu", "Revenge Begins with a Broken
Engagement" (100 eps). The 2 skipped titles were not recorded by name
(sync only counts skips); rate 48/50.

## Castle — skip set diagnosed and fixed (3 causes, all fixed)

Live diagnosis (re-walked movies sitemaps 1–2, 200 pages, then re-fetched
all 53 first-pass skips with delay):

* 15 of 53 skips were TRANSIENT: the signed-URL block is flaky per
  request — the same page served a fresh img01 URL on re-fetch (e.g.
  "Scene", "Resident Evil", "Clayface", "Moana", "Drishyam 2").
  Fix: a page with no signed URL is re-fetched once before it is
  skipped (`totals.pages_retried` / `retry_recovered`).
* 16 of 53 skips were the VARIANT HOST: the signed master lives on
  `img1.tlnob.com` as `index_365.m3u8`, not `img01` / `index_401`
  (e.g. "Meesaya Murukku", "Jailer", "Moh", "Spider-Man: Brand New
  Day", "Drishyam", "Sardar 2"). Same `?auth_key=…&expire=…` signing.
  Fix: `SIGNED_M3U8_RE` (importer) and `CASTLE_M3U8_RE`
  (`host_resolvers.py`, so `unwrap_castle` re-extracts img1 URLs on
  every press too) widened to `img0?1\.tlnob\.com`.
* 22 of 53 skips are GENUINELY SOURCELESS: no .m3u8 of any kind on the
  page, mostly unreleased titles (`datePublished` 2026 — "A Story of
  Derry", "All That We Never Were", "Cocoons", "Basant Kaur", …; two
  2025, one 2024). Correctly skipped; nothing to fix.
* The 1 failed page: the sitemap loc for "romanchakam" carries a
  zero-width space in its slug (`roma\u200bnchakam` — the sitemap
  literally contains U+200B). Fix: `clean_sitemap_loc` strips U+200B
  and the literal `\u200b` escape text from locs before use. Covered
  by offline tests; the live 50-title sync did not reach that URL
  (it sits in sitemap 2, past the first 50 picks), so the sanitizer
  has no live proof yet.

Built in `import_castle.py` + `host_resolvers.py` (same patterns as
batch 1; `unwrap_castle` docstring updated for the img1 form).

Tests: `test_castle_import.py` 14 → 19 (all OK) — img1/index_365 parse
+ active build, retry-once sync (first fetch no-stream, second signed),
sitemap `\u200b` sanitization (both forms) in parse and in sync.
`test_host_resolvers.py` 230 → 231 (all OK) — new
`test_img1_index_365_variant_resolves` (active, `expires_in` > 0).

Proof sync (Oracle VM, staging DB
`/home/ubuntu/radd-stream-data/castle-followup.db`, limit 50):
47 posts / 47 / 47, 3 skipped, 0 failed, 3 pages retried (0 recovered
— the 3 retried were the genuinely sourceless 2026 titles). Verify OK
(0 flagged 18+, 0 posts without release, 0 sources without final_url;
44 active, 3 unverified = stale signatures, fail-closed as designed).
img1 live: 2 sources (`index_365`) — "Meesaya Murukku" and "Mookuthi
Amman"; img01: 45. Unverified: "The Odyssey", "Oh..! Sukumari",
"Mookuthi Amman". "Scene" (a batch-1 skip) staged this time.

## Castle series — NO endpoint exists; series import NOT implemented

JS-bundle analysis (series page "Marshals" season 2, 4 episodes):

* The full episode list IS in static HTML (Next.js RSC payload,
  `self.__next_f`): per episode id, number, duration, `videos`
  (SD 480P / HD 720P / FHD 1080P with byte sizes), audio tracks
  (Hindi default, English), subtitles. But NO per-episode stream URL
  anywhere in the page, the JS bundles, or any discoverable endpoint.
* The ONE signed .m3u8 on a season page is the `trailerUrl` (passed to
  the trailer player component) — NOT an episode stream.
* Episode play is an encrypted handoff, not a URL fetch:
  1. `GET https://api.hbzws.com/film-api/v0.1/configurationitem/get`
     (`group=flixfox_config`, `key=domain`, `domain=www.bulwik.com`,
     `appCode` header, default value `"CaslteWeb"`) answers 200 with
     an AES-CBC-encrypted (CryptoJS) blob, not JSON — the key is
     `bs$qofKubsX@cR6I` (Base64 `YnMkcW9mS3Vic1hAY1I2SQ==`). It holds
     the `playerUrl` (external player host), `qrCodeUrl`, theme, lang.
  2. On episode click the page AES-CBC-encrypts
     `{movieId, episodeId, qrCodeUrl, theme, lang}` (key = IV =
     Base64 `ZGIyMTM5NTYxYzlmZTA2OA==` → `db21395619fe068`) and opens
     `playerUrl/<ciphertext>` in a new tab; the external player app
     resolves the video itself.
* What is missing, precisely: there is no endpoint that returns a
  per-episode .m3u8. Getting one would need decrypting the hbzws
  config (replicable — key is in the bundle) AND reverse-engineering
  the external player app's own resolution backend, which is a
  separate unknown app. That is browser-level / player-app work, out
  of this follow-up's scope. Per the brief: reported, not faked.
  Staging a series post with no playable source would also violate
  the verify gate (0 sources without final_url), so series stay out.

## CI failure on the first push — fixed by a follow-up commit

* First push (`aa25695`): backend CI run 42807581476 completed
  **failure** — the only failing step was `test_docs_invariants.py`
  (`test_the_index_counts_are_the_directory_listings`):
  `CONTINUITY.md` claimed 135 archive files but
  `Fast_Fetch/checkpoints` held 136 once this checkpoint file was
  added. The local run had passed only because it ran BEFORE the
  checkpoint file was written — the checkpoint itself broke the
  invariant it documents. Lesson: re-run `test_docs_invariants.py`
  AFTER writing the checkpoint file, never before.
* Fix (second commit on the same branch): `CONTINUITY.md` count
  135 → 136 (134 dated + 2 undated) + this session's entry at the top
  of `Fast_Fetch/checkpoints/README.md` (newest-first list, same
  practice as batch 1). `test_docs_invariants.py` 22/22 OK after the
  fix; re-pushed, CI re-run pending (see report).

## Suites run solo (CI way), all green

* test_dramadog_import.py 25/25 (was 15, +10)
* test_castle_import.py 19/19 (was 14, +5)
* test_host_resolvers.py 231/231 (was 230, +1)
* test_docs_invariants.py OK; test_domain_resolver.py OK;
  test_database.py OK (skipped=1). Gate stays 75 🧪 steps (no new
  modules — the touched suites were already in backend-ci.yml).

## Live state (not changed by this session)

* No live-tree edit, no trunk push, no tag, no release, no service
  restart, no production DB write. Staging DBs only, on the VM:
  `dramadog-followup.db`, `castle-followup.db`.
* VM clone `/tmp/muse-panel-push` was NOT touched (checked-out branch
  is session-linkhealth-drift-warm; only read for a Fast_Fetch base
  copy into `/home/ubuntu/dc-followup`, which the syncs ran from).
* The 13 MB `scp -r Fast_Fetch` to the VM stalled at 2.3 MB (~8 KB/s
  through the hatch egress proxy) and was killed; replaced by a VM-side
  `cp -r` of the VM clone's Fast_Fetch plus scp of just the 6 changed
  files (~372 KB). Same proxy flake as batch 1's SSH drops.

## Open / still blocked

* Castle series import: blocked on the missing episode-stream endpoint
  (see above) — needs player-app reverse engineering or a browser
  session; not attempted here.
* Castle `\u200b` sitemap sanitizer: offline-tested only; needs a live
  sync that reaches sitemap 2's romanchakam URL for a live proof.
* The 2 skipped DramaDog titles in the proof sync were not named
  (sync counts only); a re-sync with skip logging would name them.
* Full-harvest estimate unchanged: DramaDog ~19,972 series now
  importable across ALL ~30 platforms (API path unlocks the ~13
  no-stream platforms: dramawave 5,437 + yourchannel 2,812 +
  reelshort 1,928 + stardust/joyreels/stardusttv/…); Castle ~10,000
  movies with ~44% fewer skips (31 of 53 first-pass skips now
  recoverable: 15 retry + 16 img1).
