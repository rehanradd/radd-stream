# Session 118 — New importers: HarPal Geo, MovieNestBD, MoviesDrive (2026-11-09)

**Scope:** first Tier-1 discovery builds (round-2 ranked order). Three staging
importers + registry entries (19 → 22 sites) + tests. No push, no deploy, no
live-DB writes, no first live scrape runs — those are a later gated step.

## 1. HarPal Geo — `Fast_Fetch/import_harpalgeo.py` (official Geo dramas)

- **Live proof (Oracle VM, 01:33–01:44 PKT 2026-11-09):** homepage 200 (321 KB,
  31 distinct `/program/` links, no .m3u8); program page `/program/Bano` 200
  (306 KB, 12 episode links, titles carry "Episode N" + air date); episode
  page 200 (302 KB, videojs + `<video>`, exactly ONE .m3u8 on Geo's official
  CDN host 5centscdn); that playlist fetches **200 (830 B), valid HLS master
  720p/480p/240p (h264+aac), ffprobe `format_name=hls`**. No crack needed.
  `/sitemap.xml` 307s away — no sitemap; catalog = homepage program list +
  program episode lists. Teaser pages exist ("Episode 26 Teaser") and are
  skipped by label.
- **Importer:** one post per program (series, Urdu, Pakistan), one release per
  full episode (E##, 720p = master top variant), source = direct .m3u8
  (`playback_type="direct"`, service `5centscdn`), source_url = episode page.
  `--sync-programs` → sitemap_cache, resumable; `--limit/--workers/--delay`.
- **Tests:** `test_harpalgeo_import.py`, **10 OK** (programs/episodes/teaser
  drop, 5centscdn preference, title parse, save path, sync, registry).

## 2. MovieNestBD — `Fast_Fetch/import_movienestbd.py` (public no-key JSON API)

- **Live proof (VM):** `/api/v1/search/suggest?q=ramayana` 200 (338 B, title/
  slug/year); `/api/v1/search?q=ramayana` 200 (count 3); `?q=a&page=2` 200
  (18 rows/page, `has_next/has_prev/page/total_pages`, count 16,341 for "a");
  `/api/v1/movie/<slug>` 200 (3,113 B movie: quality PreDvD, rating 8.9,
  `watch` on player.jiofiles.pics; 2,272 B series: `is_series`, `episodes`
  null, `links[]` per quality on embed.jiofiles.pics). `/api/v1/movies` and
  `/api/v1/trending` are **404 HTML** — search is the only enumeration
  surface. `/movie/<slug>` HTML is 404 — API only. No download field seen.
- **Importer:** enumerate search one letter at a time (a-z0-9), paginate to
  `has_next=false`; one post per title (series = one row per season slug,
  season from `...-sN` suffix); one source per `links[]` entry + main watch
  (service `jiofiles`, `playback_type="url"`, stored as-is — **jiofiles is a
  NEW host, not cracked, so rows are catalog + bridge, not proven playable**);
  `is_adult` from the API is the 18+ authority. `--sync-search --letters`.
- **Tests:** `test_movienestbd_import.py`, **9 OK** (movie/series/adult/
  quality/season/no-sources/save/sync/registry).

## 3. MoviesDrive — `Fast_Fetch/import_moviesdrive.py` (wp-json)

- **Live proof (VM):** `/wp-json/wp/v2/posts?per_page=3` 200 (34 KB, full
  post objects); post content carries 4 `mdrive.lol/archive/<id>/` links (one
  per quality) + noise (mirror links, t.me, IMDb — dropped); archive page 200
  (36 KB, itself a WP post; `<title>` carries quality+size, body links
  `hubcloud.ist/drive/...` and, on other posts, `gdflix.vip/file/...`).
- **Importer:** one post per WP post (title/year via shared
  `parse_post_metadata`), one release per archive link (quality/size/codec
  from the archive title, languages from the WP title), one source per
  file-host anchor (hubcloud/gdflix, `playback_type="download"`, final_url
  as-is — resolver unwraps at play time). `--sync-posts` → sitemap_cache.
- **Tests:** `test_moviesdrive_import.py`, **10 OK** (archive links/sources,
  post shape, no-links/no-host Nones, languages, save/sync/registry).

## 4. Registry + CI

- `domain_registry.json`: 3 entries (harpalgeo `homepage`, movienestbd
  `json_api` + `api_endpoint /api/v1/search`, moviesdrive `wp_rest_api` +
  `api_endpoint /wp-json/wp/v2/posts`), all `status active`, verified
  2026-11-08T20:44:00Z; `updated_at` bumped. Sites 19 → 22.
- `backend-ci.yml`: 3 new 🧪 steps after the xprimehub step (same offline
  pattern). New test files are IN the gate, not in UNREGISTERED.

## 5. VidCore — INVESTIGATED ONLY, NOT wired (no playable URL proven)

- **Chain traced live (VM):** GoMovies `/movies` is a TMDB-driven JS page
  (484 KB, 252 TMDB mentions); watch URLs are
  `/watch/<tmdb-id>-<slug>-<year>/` (from `js/script.js`); watch page 200
  (52 KB) carries the iframe `vidcore.net/movie/<id>?autoPlay=true...`
  (VidCore named first of 5 servers: VidCore/VidFast/VidNest/vidsrc/
  EmbedMaster); `vidcore.net` **301 → vidcore.io**; embed page 200 (49 KB,
  Next.js app, `<video>` shell present, **no .m3u8/.mp4, no /api/ string** in
  static HTML or in the 6 fetched JS chunks).
- **Where the stream hides:** the page's RSC payload carries an 86-char
  base64url `en` prop (encrypted blob); the bundle ships crypto-browserify
  AES (chunk aaea2bcf) and hls.js (chunk 281, 1.3 MB, contains "m3u8" only as
  player code); subtitles fetch `/wyzie...`. The decrypt call site — which
  turns `en` into a source URL, and with what key — was NOT located in the
  minified bundle after 6 chunk fetches + string hunts.
- **Verdict: NOT proven, no unwrapper branch written.** Blocker: needs a
  browser-network capture (Playwright on the VM, record the requests the
  player makes when it loads) or deeper bundle deminification to find the
  `en` decrypt + the source endpoint. One unwrap would unlock the 23-clone
  Cineby family + round-1's 5 clones — highest-leverage crack in round 2,
  still open.

## 6. What remains (later gated steps, NOT this session)

- First live scrape runs per importer (small `--limit`, staging DBs only):
  HarPal `--sync-programs` + `--limit 5`; MovieNestBD `--sync-search
  --letters a --limit 20`; MoviesDrive `--sync-posts --limit 10`. Verify
  staging row counts + a sample release each, then the merge/publish gate.
- MovieNestBD full sweep is big (~16k titles for "a" alone) — run letter by
  letter, not in one job; jiofiles unwrap is a separate crack task.
- VidCore crack (see §5 blocker) + MoviesRoot / ApneTV hosts after it.
- Gate: full backend gate run 3× on this tree. Run 1: FAILED MODULES 2 —
  test_domain_resolver (2 hardcoded "19 sites" counts — FIXED to 22, plus the
  test rename) and test_api_v2 (known ETag-304 gate-load flake; solo 64 OK).
  Run 2 after the fix: FAILED MODULES 1 — test_api_v2 only. Run 3: FAILED
  MODULES 2 — test_api_v2 + test_redact. test_redact is the documented load
  flake (AGENTS.md 2026-11-09): PublicEdgeHttpTests time out at load ~3.7;
  PROVEN not this session — clean base dd2663ee fails the same module with
  7 errors under the same load (my tree: 5, then 2 on re-run). My diff
  touches neither redact.py nor api_v2.py. Importer solos 13/18/53/7 OK.
  New tests 29 OK (10+9+10). No green full-gate run achieved only because
  of these two documented load flakes; parent decides push on that basis.
