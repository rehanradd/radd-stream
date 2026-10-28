# SITES.md — Deep-Dive Site Reference

> Complete technical reference for every supported site: domains, API/data endpoints, bridge chains, regex patterns, and known issues.

---

## Quick Reference Table

| Site | Domain | Data Source | Bridge | Known TLD Rotations |
|------|---------|------------|--------|---------------------|
| Vegamovies | vegamovies.gallery | WP XML Sitemap | Nexdrive | `.gallery → .yt → .one → .vip` |
| RogMovies | rogmovies.one | WP XML Sitemap | Nexdrive | `.wtf → .one → .vip` |
| SSRMovies | ssrmovies.gripe | WP REST API | LinksZilla | `.games → .gripe → .monster` |
| KatMovieHD | katmoviehd.fans | SvelteKit JS | KatDrive/DandnDn | `.fans → .rodeo → .top` |
| 7StarHD | 7starhd.rich | Homepage scrape | MobileJSR | `.rich → .run → .com` |
| 10xflix | 10xflix.help | WP REST API | MobileJSR | `.help → .wiki → .me` |
| MultiMovies ⭐ | multimovies.garden | JSON APIs + XML Sitemap | watchConfig initialServers (7 embeds) | `.garden → .com → .net → .org` |
| HDHub4u | new8.hdhub4u.cl | WP post-sitemap.xml | linkrit.com bridges + hubcloud.ist direct | `new2/new3.hdhub4u.free → new8.hdhub4u.cl` |
| BollyShares | bollyshares.xyz | WP post-sitemap.xml | 10moviesz.mom | `bollywood1.xyz → bollyshares.xyz` |
| FilmyZilla | thefilmyzilla.in | XML Sitemap | /server/ pages → /download/<id>/server_N + fzcdn.store | `71 → 73 → 74 → 75 → thefilmyzilla.in` |
| HindiLinks4u | www.hindilinks4u.zip | XML post-sitemap | video_tabs embed servers (playmogo/mixdrop/…) | `.pink (Cloudflare JS challenge) → .zip (plain HTML)` |
| ToonWorld4All | toonworld4all.me | WP REST API + archive.toonworld4all.me/episode SSR | `window.__PROPS__` encodes[] → /redirect/<hex> → hubcloud.ist | `.me / www .me` |

---

## Scraped vs merely documented — measured 2026-10-29

The table above documents twelve sites; the fleet's staging databases under
`/home/ubuntu/radd-stream-data/` cover thirty. Those are different claims, and
`merge_catalogs.py` can only read the second kind. Every row below is a
`COUNT(*)` against the file, not a note about what a parser could do:
**posts / releases / sources**, plus the queue (`scraped = -1` parked, `0`/`2`
pending). A row with `no-key` has no `posts.canonical_key` and no `sources`
table, so it is **not mergeable as it stands**. For the twelve sites that have a
module, re-measure with `python3 -S Fast_Fetch/importers/import_<site>.py stats`
— it prints exactly these columns as JSON; the other eighteen were written by
`fast_fetch.py` and are counted with a `COUNT(*)` against their file.

| Staging database | posts | releases | sources | 18+ | queue parked / pending | mergeable |
|---|---|---|---|---|---|---|
| 10xflix | 13,775 | 76,923 | 228,397 | 2,665 | 1,189 / 0 | yes |
| 5movierulz | 442 | 3,262 | 6,491 | 2 | 0 / 0 | yes |
| 7starhd | 11,791 | 33,369 | 99,627 | 2,296 | 7,938 / 0 | yes |
| 9xmovies | 12,060 | 30,936 | 337,595 | 2,726 | 5,770 / 1 | yes |
| animahd | 232 | 4,801 | 9,575 | 0 | 1 / 0 | yes |
| aryplus | 481 | 10,860 | 10,860 | 0 | 538 / 0 | yes |
| bolly4u | 15,192 | 41,004 | 22,003 | 972 | 7,735 / 1 | yes |
| desicinemas | 5,223 | 5,285 | 4,339 | 7 | 0 / 1 | yes |
| desiserials | 34 | 200 | 359 | 0 | 0 / 0 | yes (200-row pilot only) |
| dramacool | 544 | 9,675 | 9,675 | 2 | 0 / 0 | yes |
| filmiyin | 3,837 | 17,541 | 17,541 | 21 | 1,841 / 0 | yes — queue closed twice |
| filmyzilla | 15,228 | 46,372 | 80,032 | 423 | 3,462 / 0 | yes |
| hdhub4u | 11,224 | 129,009 | 250,925 | 826 | 1,147 / 0 | yes |
| hdtvb | 3,774 | 16,855 | 16,855 | 1,161 | 3,684 / 0 | yes |
| hindilinks4u | 26,152 | 145,196 | 145,196 | 988 | 3,673 / 0 | yes |
| katmoviehd | 38,154 | 146,244 | 163,972 | 1,017 | 162 / 3,452 | yes |
| kisskh | 669 | 11,550 | 140,746 | 10 | 4 / 2 | yes |
| levidia | 147 | 460 | 2,976 | 0 | 0 / 0 | yes |
| moviecok | 1,738 | 7,065 | 7,452 | 4 | 0 / 8 | yes |
| moviesmela | 16,677 | 20,770 | 57,818 | 19 | 0 / 118 | yes |
| moviezguru | 3,386 | 7,334 | 8,912 | 97 | 4 / 0 | yes |
| **mp4moviez** | 29,848 | 54,267 | — | 91 | 0 / 3,119 | **no-key** — see § MP4Moviez |
| multimovies | 10,498 | 532,649 | 595,218 | 30 | 0 / 769 | yes |
| pagalmovies | 6,842 | 9,447 | 9,447 | 393 | 7,535 / 7 | yes |
| rareanimes | 1,328 | 17,419 | 53,767 | 7 | 1,295 / 0 | yes |
| rogmovies | 7,750 | 52,964 | 193,048 | 879 | 0 / 0 | yes |
| ssrmovies | 13,916 | 46,153 | 665,025 | 924 | 0 / 0 | yes |
| toonworld4all | 932 | 66,740 | 230,282 | 17 | 1,324 / 0 | yes |
| vegamovies | 13,370 | 131,658 | 398,253 | 445 | 324 / 5 | yes |
| world4ufree | 14,768 | 106,972 | 254,340 | 425 | 2,921 / 0 | yes |

Two further claims this table retires:

- **A dedicated importer module exists for**: 5movierulz, animahd, aryplus,
  desiserials, dramacool, filmiyin, kisskh, levidia, moviecok, moviesmela,
  mp4moviez (converter, not crawler), pagalmovies — twelve, in
  `Fast_Fetch/importers/`. Every other site above was written by a parser inside
  `fast_fetch.py` and has no module of its own.
- **`mp4moviez.db` is the largest asset the merge queue cannot read.** It holds
  29,848 pages scraped before the fleet schema existed: no `canonical_key`, no
  `sources` table, so `_source_family()` raises
  `ValueError: Source database has neither download_sources nor sources table`.
  `Fast_Fetch/importers/import_mp4moviez.py` converts it (verified: 28,066 works,
  54,267 releases, 54,267 sources, and the result reads back through
  `merge_catalogs._collect_staging_post`). Before this file, SITES.md had
  MP4Moviez listed under *Sites To Add Next* with a domain nobody scraped —
  neither half of that was true. See § MP4Moviez.

---

## MP4Moviez (`www.mp4moviez.deal`)

- **Scraped domain:** `https://www.mp4moviez.deal` (the `mp4moviez.cloud` in
  § Sites To Add Next was never the scraped host; the XML sitemap that filled
  `mp4moviez.db` is this one's).
- **State today:** 29,848 pages and 54,267 download rows already in
  `mp4moviez.db`, scraped by an earlier worker in a schema the merge queue
  rejects. No live crawl is running against it; `import_mp4moviez.py` is a
  **converter**, and it converts.
- **What the conversion does and does not do:** keys every work on the site's own
  page slug, unions the 336 slugs that a re-post under a new `c<id>` path
  duplicates, copies the legacy columns into `raw_meta`, then replaces `posts`
  and `releases` inside one `BEGIN IMMEDIATE` transaction that rolls back whole.
  It writes one `sources` row per release with `playback_type = download`,
  `status = unverified`, `final_url = NULL` and `last_checked = NULL`, because
  the stored link is `dl.php?id=<n>&q=<tier>` and nothing here followed it. A
  converter that wrote `active` would be claiming a probe that did not happen.
- **The hole in the asset:** 14,730 of the 29,848 stored pages are titled, dated,
  `c<id>`-anchored works with **zero download rows**. Re-fetched 2026-10-29, they
  answer HTTP 200 with 11-12 kB of HTML whose 39 anchors are *all* category links —
  no `<h1>`-`<h4>`, no `dl.php` anywhere. The site kept the URLs and emptied the
  pages, so no re-drive and no parser recovers them; the `data-key` attributes on
  those pages belong to an ad SDK on `<ins data-cp-host=…>` elements, not to a
  gated download button. They convert as catalog entries with metadata and no
  sources, which is reachable-and-known-empty, not missing.
- **Dropped by design:** 1,438 category/listing pages, 9 copyright-takedown
  notices, 2 `sitemap*.xml` rows, 7 untitled rows.
- **Queue:** 3,119 URLs were never fetched (1,781 of them listing or pagination
  rows, many storing a literal `&amp;p=2`). The converter leaves `sitemap_cache`
  exactly as it found it.

---

## 1. Vegamovies (`vegamovies.gallery`)

### Identity
- **Primary domain:** `https://vegamovies.gallery`
- **CMS:** WordPress
- **Target content:** Hollywood, International, Western Series, Anime, Dual Audio

### Data Endpoints
```
Sitemap index:
  GET https://vegamovies.gallery/sitemap.xml
  Response: XML with <loc> entries for sub-sitemaps

Sub-sitemaps (one per ~500-1000 posts):
  GET https://vegamovies.gallery/post-sitemap1.xml
  GET https://vegamovies.gallery/post-sitemap2.xml
  ...
  Each: <url><loc>POST_URL</loc><lastmod>DATE</lastmod></url>

Optional — WP REST API (may be enabled):
  GET https://vegamovies.gallery/wp-json/wp/v2/posts?per_page=100
```

### Post Structure
```
URL pattern:  /movie-title-year-quality-format/
Post HTML:
  - <title>: "Movie Title (Year) | Vegamovies Official"
  - og:image: poster URL (may be base64 encoded u= param)
  - Nexdrive links: href="https://nexdrive.fit/genxfm/..."
  - Multiple Nexdrive links per post = multiple qualities (480p, 720p, 1080p)
  - Each Nexdrive page = one quality, multiple CDN servers
```

### Bridge Chain: Nexdrive
```
Post page
  └─ Nexdrive link: https://nexdrive.fit/genxfm/<TOKEN>
      └─ Nexdrive page contains buttons:
          ├─ FastDL: https://fastdl.beer/embed.php?download=<ID>
          │    └─ JS: var reurl="https://fastdl.beer/dl.php?link=<GOOGLE_CDN_URL>"
          │    └─ Final: https://video-downloads.googleusercontent.com/...
          ├─ VCloud: https://vcloud.beer/<ID>
          │    └─ JS: var url = atob(atob('...'))
          │    └─ Fetch token URL → FSL (Cloudflare R2) or HubCloud
          │    └─ Final R2: https://pub-XXXX.r2.dev/<hash>?token=...
          ├─ HubCloud: https://hubcloud.ist/drive/<ID>
          │    └─ Redirect → gamerxyt.com/hubcloud.php
          │    └─ Final: video-downloads.googleusercontent.com/...
          ├─ VegaDrive: https://one.vegadrive.me/s/<ID>
          │    └─ Maps to: /d/<ID>/skyd (10Gbps)
          ├─ PixelDrain: https://pixeldrain.com/u/<ID>
          │    └─ API: pixeldrain.com/api/file/<ID>
          └─ FilePress: https://new1.filepress.lat/file/<ID>
```

### Key Regex Patterns
```python
# Nexdrive links on post page
nex_links = re.findall(r"""href=["'](https?://nexdrive\.[a-z]+/[^"'<>\s]+)["']""", html)

# FastDL CDN extract
cdn_m = re.search(r'var\s+reurl\s*=\s*["\']([^"\']+)["\']', fastdl_html)

# VCloud base64
b64_m = re.search(r'atob\(atob\(["\']([^"\']+)["\']\)\)', vcloud_html)
url = base64.b64decode(base64.b64decode(b64_m.group(1))).decode()

# VegaDrive
vd_id = re.search(r'/s/([A-Za-z0-9]+)', vegadrive_url).group(1)
final = f"https://one.vegadrive.me/d/{vd_id}/skyd"

# PixelDrain
pd_id = re.search(r'/(?:u|d|api/file)/([A-Za-z0-9_-]+)', pd_url).group(1)
final = f"https://pixeldrain.com/api/file/{pd_id}"
```

---

## 2. RogMovies (`rogmovies.one`)

### Identity
- **Primary domain:** `https://rogmovies.one`
- **CMS:** WordPress
- **Target content:** Bollywood, Tollywood, Pollywood, South Dubbed, Indian Web Series

### Data Endpoints
```
Sitemap index:
  GET https://rogmovies.one/sitemap.xml
Sub-sitemaps:
  GET https://rogmovies.one/post-sitemap1.xml
  GET https://rogmovies.one/post-sitemap2.xml
```

### Notes
- Identical architecture to Vegamovies (same Nexdrive bridge chain)
- Cross-links with Vegamovies in nav — harvest_sister_domains() catches domain updates
- Extractor: uses same `parse_post_metadata()` + `unwrap_nexdrive()` flow (default extractor)

---

## 3. SSRMovies (`ssrmovies.gripe`)

### Identity
- **Primary domain:** `https://ssrmovies.gripe`
- **Old domain:** `ssrmovies.games` (HTTP 301 → gripe)
- **CMS:** WordPress

### Data Endpoints
```
WP REST API (sitemap redirects to homepage — use API instead):
  GET https://ssrmovies.gripe/wp-json/wp/v2/posts?per_page=100
  GET https://ssrmovies.gripe/wp-json/wp/v2/posts?per_page=100&page=2
  ...paginate until empty array

Response: JSON array of post objects
Fields used:
  post["link"]              → canonical post URL
  post["slug"]              → URL slug
  post["date"]              → publish date
  post["title"]["rendered"] → post title
  post["content"]["rendered"] → HTML body with download buttons
```

### Bridge Chain: LinksZilla
```
Post page
  └─ LinksZilla link: https://secure.linkszilla.top/view/<ID>
      └─ Page contains mirror buttons:
          ├─ HubCloud Drive: hubcloud.ist/drive/<ID>
          ├─ GDFlix: new5.gdflix.io/file/<ID>
          ├─ Direct-Cloud: dl.direct-cloud.top/d/<ID> → storage.direct-cloud.org
          ├─ Watch-Online: watch-online.mom/e/<ID>
          ├─ VikingFile, Gofile, 1fichier, MegaUp, UploadFlix, HexLoad
          └─ ClicknUpload
```

### Key Regex
```python
linkszilla_links = re.findall(r"""href=["'](https?://secure\.linkszilla\.top/view/[^"'<>\s]+)["']""", html)
hubcloud_links = re.findall(r"""href=["'](https?://hubcloud\.ist/drive/[^"'<>\s]+)["']""", lz_html)
gdflix_links = re.findall(r"""href=["'](https?://new\d+\.gdflix\.[a-z]+/file/[^"'<>\s]+)["']""", lz_html)
```

---

## 4. KatMovieHD (`katmoviehd.fans`)

### Identity
- **Primary domain:** `https://katmoviehd.fans`
- **Landing/mirror:** `https://katmovieshd.net` (302 → fans)
- **CMS:** SvelteKit (Next.js-style SSR)

### Data Endpoints
```
Catalog data (embedded in HTML, not a separate API):
  GET https://katmoviehd.fans/
  Response HTML contains:
    items:[{slug:"post-slug",title:"Movie (2024)",...},{...}]
  Regex: r'items:\[(.*?)\]' → extract slugs

Post URL: https://katmoviehd.fans/<slug>
Post API (if available): https://katmoviehd.fans/api/post/<slug>

KatDrive/DandnDn CDN API:
  GET https://api.dandndn.one/api/v1/file/<FILE_ID>
  Returns: {"url": "https://hubcloud.ist/drive/...", ...}
```

### Bridge Chain: KatDrive
```
Post page
  └─ KatDrive link: https://katdrive.net/<ID> or dandndn API
      └─ API: api.dandndn.one/api/v1/file/<ID>
          └─ Returns direct links:
              ├─ HubCloud Drive
              ├─ 1fichier.com
              └─ Send.cm
```

---

## 5. 7StarHD (`7starhd.rich`)

### Identity
- **Primary domain:** `https://7starhd.rich`
- **CMS:** WordPress

### Data Endpoints
```
Homepage scrape (no sitemap/API):
  GET https://7starhd.rich/
  Response HTML: <li class="thumb"><a href="/post-slug/">
  Filter out: /page/, /category/, /tag/, /genre/, /how-to, /disclaimer, /dmca

Category pages (bonus — more posts):
  GET https://7starhd.rich/category/bollywood/page/2/
  GET https://7starhd.rich/category/hollywood/page/2/
```

### Bridge Chain: MobileJSR
```
Post page
  └─ MobileJSR link: https://mobilejsr.com/view/<ID>
      └─ Page HTML: <iframe src="https://mobilejsr.com/embed/<ID>">
          └─ Embed HTML contains:
              ├─ Direct video <source src="..."> or
              ├─ Cloud mirror links (GDrive, HubCloud, etc.)
              └─ Stored as-is (stable persistent URL)
```

### Key Regex
```python
# Homepage post links
post_links = re.findall(r"""href=["'](https?://7starhd\.rich/[a-zA-Z0-9\-_]+/)["']""", html)
# MobileJSR bridges
mj_links = re.findall(r"""href=["'](https?://mobilejsr\.com/view/[^"'<>\s]+)["']""", html)
```

---

## 6. 10xflix (`10xflix.help`)

### Identity
- **Primary domain:** `https://10xflix.help`
- **Old domain:** `10xflix.wiki` (normalize → .help)
- **CMS:** WordPress

### Data Endpoints
```
WP REST API:
  GET https://10xflix.help/wp-json/wp/v2/posts?per_page=100
  GET https://10xflix.help/wp-json/wp/v2/posts?per_page=100&page=2
  Same structure as SSRMovies REST API response
```

### Bridge
- Same as 7StarHD: MobileJSR links in post content

---

## 7. MultiMovies (`multimovies.garden`) — ⭐ PRIORITY #1

> **Best quality, most sources, most accurate metadata. This is our crown jewel.**

### Identity
- **Primary domain:** `https://multimovies.garden`
- **CMS:** Custom (NOT WordPress) — SPA-like with server-rendered HTML + embedded JSON
- **Content:** Movies, TV Series, Anime — Hindi, English, Dual Audio, Multi-language
- **TLD rotations:** `.garden → .com → .net → .org → .live`

### JSON API Endpoints (Discovered 2026-10-13)

```
🔍 SEARCH API (returns structured JSON, no scraping needed):
  GET https://multimovies.garden/api/search?q=<query>
  Response: {
    "movies": [{id, title, type, year, rating, quality, poster, url}, ...],
    "tv_shows": [{id, title, type, year, rating, quality, poster, url}, ...],
    "people": [...],
    "results": [{id, title, type, year, ...}, ...],
    "total": N
  }
  - poster URLs are TMDB: https://image.tmdb.org/t/p/w185/<hash>.jpg
  - url format: /movie/<slug>-<id> or /series/<slug>-<id>

📊 DISCOVER API (trending/popular catalog):
  GET https://multimovies.garden/api/discover
  Response: {
    "items": [{id, type, slug, url, title, year, rating, quality, audio, kind, poster, backdrop, views}, ...],
    "sections": [...],
    "reason": "...",
    "personalized": bool,
    "signal_count": N
  }
  - Returns most popular/trending titles
  - Includes view counts, backdrop URLs, quality info
```

### XML Sitemap (Bulk Catalog)
```
Sitemap index:
  GET https://multimovies.garden/sitemap.xml
  Lists: sitemap-titles-1.xml, sitemap-titles-2.xml, ...
         sitemap-episodes-*.xml (skip these — episodes are fetched per-series)

Title sitemaps (10,000 entries each):
  GET https://multimovies.garden/sitemap-titles-1.xml
  Filter: only URLs containing /movie/ or /series/
```

### URL Structure
```
Movies:   /movie/<slug>-<numeric_id>     (e.g. /movie/kalki-2898-ad-55025)
Series:   /series/<slug>-<id>            (e.g. /series/mirzapur-2571)
Episodes: /series/<slug>-<id>/season/<N>/episode/<N>

⚠️ The numeric ID suffix is REQUIRED — slug-only URLs return 404
```

### watchConfig (Verified Structure — NOT what was documented before)

The old documentation was WRONG. Here is the actual verified structure:

```javascript
// Found in EVERY movie page and EVERY episode page (NOT series root)
const watchItem = {
  "titleId": 55025,
  "title": "Kalki 2898 - AD",
  "poster": "https://image.tmdb.org/t/p/w342/<hash>.jpg",
  "backdrop": "https://image.tmdb.org/t/p/w780/<hash>.jpg",
  "type": "movie",      // or "tv"
  "url": "/movie/kalki-2898-ad-55025"
};

const watchConfig = {
  "titleId": 55025,
  "season": null,        // or season number for episodes
  "episode": null,       // or episode number
  "initialServers": [    // ← NOT "sources" — this was wrong in old docs
    {
      "id": "mirror_15031",
      "name": "Filesforever Mirror",
      "type": "iframe",
      "url": "https://filesforever.link/embed/pumu7an",
      "quality": "1080p",
      "is_custom": true   // Custom uploaded = highest quality
    },
    {
      "id": "autoembed_1",
      "name": "Cineverse",
      "type": "iframe",
      "url": "https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=801688",
      "quality": "HD",
      "is_custom": false
    },
    // ... more servers
  ],
  "directEpisode": true,
  "playRequested": true
};
```

**Regex to extract:**
```python
re.search(r'watchConfig\s*=\s*(\{.*?\});', html, re.DOTALL)
# Then: json.loads(match)[\"initialServers\"]
```

### Embed Servers (7 Verified)

| # | Server Name | Domain | ID Type | URL Pattern (Movie) | URL Pattern (TV) | Stream Resolution |
|---|------------|--------|---------|---------------------|------------------|-------------------|
| 1 | **Filesforever** | `filesforever.link` | Custom hash | `/embed/<hash>` | N/A | ✅ 1080p custom upload |
| 2 | **Cineverse** | `rozgarlelo.modiplay.xyz` | TMDB ID | `/embed/tmdb/movie?id=<tmdb>` | `/embed/tmdb/tv?id=<tmdb>&s=N&e=N` | iframe (slow/timeout) |
| 3 | **GD Mirror** | `streams.iqsmartgames.com` | IMDB ID | `/embed/movie/<imdb>?key=<apikey>` | `/embed/tv/<tmdb>/S/E?key=<apikey>` | iframe (JS-rendered) |
| 4 | **Vidrift** | `embed.vidrift.net` | TMDB ID | `/embed/movie/<tmdb>` | `/embed/tv/<tmdb>/S/E` | HLS via JS |
| 5 | **VIDOUT** | `vidout.pages.dev` | IMDB ID | `/movie/<imdb>` | `/tv/<tmdb>/sN/eN` | ✅ Direct m3u8 HLS |
| 6 | **Filmu** | `embed.filmu.in` | TMDB ID | `/movie/<tmdb>` | `/tv/<tmdb>/S/E` | Vite JS player |
| 7 | **VidBolt** | `vidbolt.xyz` | TMDB ID | `/movie/<tmdb>` | `/tv/<tmdb>/S/E` | JS player |

### TMDB & IMDB ID Extraction

The embed URLs expose both TMDB and IMDB IDs for free metadata enrichment:
```python
# TMDB ID from embed URLs (numeric, 4+ digits)
tmdb_id = re.search(r'/(?:movie|tv)/(\d{4,})', embed_url)
# Also: /embed/tmdb/movie?id=<tmdb_id>

# IMDB ID from embed URLs (tt followed by 7+ digits)
imdb_id = re.search(r'/(tt\d{7,})', embed_url)

# API key for GD Mirror (static, shared):
# ?key=e11a7debaaa4f5d25b671706ffe4d2acb56efbd4
```

### Series Episode Architecture

```
Series root page (/series/<slug>-<id>):
  → Lists all seasons and episodes as HTML links
  → Does NOT contain watchConfig (no streams on root page)
  → Has Schema.org BreadcrumbList JSON-LD

Episode page (/series/<slug>-<id>/season/N/episode/N):
  → HAS its own watchConfig with initialServers (6 servers per episode)
  → Has Schema.org TVEpisode JSON-LD with name, description, season, episode number
  → Has const seasonEpisodeNumbers = [1,2,3,...] (episode count per season)
  → Each episode streams via all 6 autoembed servers with /tv/<tmdb>/S/E URLs
```

### Schema.org Structured Data
```json
// On search results page (SearchAction):
{"@type": "SearchAction", "target": {"urlTemplate": "https://multimovies.garden/search?q={search_term_string}"}}

// On episode pages (TVEpisode):
{"@type": "TVEpisode", "name": "Episode Title", "episodeNumber": 1, "partOfSeason": {"seasonNumber": 1}}
```

### JS Files
```
/assets/js/main.js      → Contains fetch('/api/search?q=') autocomplete logic
/assets/js/discovery.js  → Contains fetch('/api/discover') trending/catalog logic
```

---

## 8. HDHub4u (`new3.hdhub4u.free`)

### Identity
- **Primary domain:** `https://new3.hdhub4u.free`
- **Domain pattern:** `newN.hdhub4u.free` where N increments
- **CMS:** WordPress

### Data Endpoints
```
WP post sitemap (most reliable):
  GET https://new3.hdhub4u.free/post-sitemap.xml
  Contains 1,000 most recent post URLs

Category pages (thousands more):
  GET https://new3.hdhub4u.free/bollywood/page/2/
  GET https://new3.hdhub4u.free/hollywood/page/2/
  GET https://new3.hdhub4u.free/web-series/page/2/
  HTML: <li class="thumb"><a href="POST_URL">
```

### Bridge Chain: greenmotors.cc
```
Post page
  └─ greenmotors link: https://greenmotors.club/?id=<BASE64_PAYLOAD>
      └─ Multi-layer decode: b64 -> b64 -> rot_13 -> b64 -> JSON {'o': b64_dest} -> b64 -> hblinks archive URL
      └─ Follows hblinks archive page to extract HubCloud, PixelDrain, and Direct-Cloud mirrors
      └─ Unwraps to final direct streaming links (Cloudflare R2, PixelDrain API, Google CDN)
```

### Key Regex
```python
bridge_links = re.findall(
    r"""href=["'](https?://greenmotors\.[a-z]+/\?id=[A-Za-z0-9+/=_\-]+)["']""",
    html
)
```

### Quality Detection
```python
# Find quality from surrounding HTML context
idx_pos = html.find(bridge_url)
nearby = html[max(0, idx_pos-300):idx_pos+200]
qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', nearby, re.I)
```

---

## 9. BollyShares (`bollyshares.xyz`)

### Identity
- **Primary domain:** `https://bollyshares.xyz`
- **Old domain:** `bollywood1.xyz` (normalize → bollyshares.xyz)

### Data Endpoints
```
WP post sitemap:
  GET https://bollyshares.xyz/post-sitemap.xml
  Contains ~200 recent posts

Homepage (fallback):
  GET https://bollyshares.xyz/
  Links: href="https://bollyshares.xyz/free-<title>/"
```

### Bridge Chain: 10moviesz.mom
```
Post page
  └─ 10moviesz link: https://10moviesz.mom/?id=<SHORT_ID>
      └─ HTTP redirect → HubCloud / PixelDrain / direct CDN
      └─ Stored as-is for now
      └─ [TODO] Follow redirect chain to resolve final URL
```

### Key Regex
```python
bridge_links = re.findall(
    r"""href=["'](https?://10moviesz?\.[a-z]+/\?id=[^"'\s<>]+)["']""",
    html
)
```

---

## 10. FilmyZilla (`thefilmyzilla.in`)

### Identity
- **Primary domain:** `https://www.filmyzilla74.com`
- **Domain pattern:** `filmyzilla<N>.com` — numeric increment
- **Known history:** 71 → 73 → 74 (check when 74 stops working)

### Data Endpoints
```
XML Sitemap:
  GET https://www.filmyzilla74.com/sitemap.xml
  May contain sub-sitemaps or direct URL list

Post URL pattern:
  https://www.filmyzilla74.com/movie/<numeric-id>/<Title-Year-hindi-movie>.html

Quality pages (per-quality download):
  https://www.filmyzilla74.com/server/<numeric-id>/<filename-quality>.html
  Example: /server/8247/Ae-Dil-Hai-Mushkil-2016-Hindi-Movie-720p-HDRip.html
```

### Key Regex
```python
# Absolute quality page links
server_links = re.findall(
    r'href=["\'](https?://www\.filmyzilla\d+\.com/server/\d+/[^"\'<>\s]+\.html)["\']',
    html
)
# Relative quality page links (fallback)
rel_links = re.findall(r'href=["\'](/server/\d+/[^"\'<>\s]+\.html)["\']', html)
# Build absolute: base_domain + rel_link
```

---

## 11. HindiLinks4u (`www.hindilinks4u.zip`)

**Staging DB:** `/home/ubuntu/radd-stream-data/hindilinks4u.db` · **Importer:** `Fast_Fetch/import_hindilinks4u.py`

- `hindilinks4u.pink` is behind a Cloudflare JS challenge — do NOT bypass it.
  `www.hindilinks4u.zip` serves the same catalog as plain HTML (registered in
  `domain_registry.json` as the active base URL).
- **Discovery:** `sitemap_index.xml` → `post-sitemap*.xml`, excluding
  `/category/`, `/tag/`, `/author/`, `/feed/` URLs (~32k posts).
- **Extraction:** `<title>` (cleaned of trailing separators/dangling parens),
  `og:image` poster, meta-description synopsis, `imdb.com/title/tt…` id,
  series detection via `season|episode|complete|series` keywords.
- **Servers:** `<ul id="video_tabs">` tab anchors (`Server N`) plus generic
  external anchors matched against known embed hosts (playmogo, mixdrop,
  streamtape, upcloud, …) and `.mkv`/`.mp4` filenames.
- **Adult:** flagged, never skipped — `is_18_plus = MAX(existing, new)` on upsert.

## 12. ToonWorld4All (`toonworld4all.me`) — Hindi anime

**Staging DB:** `/home/ubuntu/radd-stream-data/toonworld4all.db` · **Importer:** `Fast_Fetch/import_toonworld4all.py`

- **Discovery:** open WP REST API `/wp-json/wp/v2/posts?per_page=100&page=N&_fields=…`
  (paginated, raw JSON cached in `sitemap_cache.raw_json`).
- **Episode pages:** `archive.toonworld4all.me/episode/<slug>` embed a
  `window.__PROPS__` JSON blob with show/season/episode/air/poster/overview
  metadata and `encodes[]` (resolution, codec, size) each holding `files[]`
  mirrors of a `/redirect/<hex>` link; `streams[]` for watch pages.
- **Redirect unwrap:** the `/redirect/<hex>` page embeds
  `window.__PROPS__ = {"destination":…, "link":{"domain":"https://hubcloud.ist/video/","hidden":"…"}}`
  → final URL = `domain + hidden`. Unwrapping is a per-file request, so the fleet runs a
  two-pass strategy: crawl with bridges stored (fast), then
  `import_toonworld4all.py --resolve-bridges` back-fills `final_url` for every
  `sources.row WHERE final_url = source_url AND source_url LIKE '%/redirect/%'`.
  `--resolve` does it inline instead (≈10x slower). Nothing is ever discarded if unwrap fails.
- **Canonical keys:** season-scoped — `generate_canonical_key(title, year) + "_sNN"`
  for series, because `generate_canonical_key` strips `season \d+` and would
  otherwise collide all seasons into one post.
- **Legacy bridges:** `*.tw4all.workers.dev/redirect?data=<b64>` also decoded.

## 13. CDN Services — Complete Bridge Reference

### Direct-Resolve Services (automatic in fast_fetch.py)

| Service | URL Pattern | Final CDN | Resumable |
|---------|------------|-----------|-----------|
| FastDL | `fastdl.beer/embed.php?download=<ID>` | `video-downloads.googleusercontent.com` | No |
| VCloud (FSL) | `vcloud.beer/<ID>` → FSL | `pub-*.r2.dev` | ✅ HTTP 206 |
| VCloud (Hub) | `vcloud.beer/<ID>` → Hub | `googleusercontent.com` | No |
| HubCloud | `hubcloud.ist/drive/<ID>` | `googleusercontent.com` or R2 | No |
| PixelDrain | `pixeldrain.com/u/<ID>` | `pixeldrain.com/api/file/<ID>` | ✅ HTTP 206 |
| VegaDrive | `one.vegadrive.me/s/<ID>` | `/d/<ID>/skyd` | ✅ |
| FilePress | `new1.filepress.lat/file/<ID>` | Google Drive proxy | No |
| Firebase | `firebasestorage.googleapis.com/...` | Direct GCS | ✅ |

### Store-As-Is Services (JS-rendered or redirect-only)

| Service | URL Pattern | Note |
|---------|------------|------|
| MobileJSR | `mobilejsr.com/view/<ID>` | Stable persistent embed |
| greenmotors | `greenmotors.club/?id=<B64>` | JS renders link |
| 10moviesz | `10moviesz.mom/?id=<ID>` | Redirect chain |
| LinksZilla | `secure.linkszilla.top/view/<ID>` | Page with mirror buttons |
| GDFlix | `new5.gdflix.io/file/<ID>` | Google Drive proxy |
| Direct-Cloud | `dl.direct-cloud.top/d/<ID>` | 302 → storage node |
| Watch-Online | `watch-online.mom/e/<ID>` | Embedded player |

---

## 14. Domain Management Commands

```bash
# Override a domain when site moves
python Fast_Fetch/fast_fetch.py set-domain vegamovies https://vegamovies.newdomain.com

# Migrate all DB records from old to new domain  
python Fast_Fetch/fast_fetch.py domain migrate vegamovies.gallery vegamovies.newdomain.com

# Probe candidate TLDs for a dead site
python Fast_Fetch/fast_fetch.py probe-domain vegamovies

# Check which domains are currently configured
python Fast_Fetch/fast_fetch.py stats  # shows domain_config entries
```

---

## 15. Sites To Add Next

| Site | Likely Domain | Method | Notes |
|------|--------------|--------|-------|
| Filmywap | filmywap.com (rotates) | XML sitemap | Large catalog |
| Filmyhit | filmyhit.link | XML sitemap | Punjab + Bollywood |
| MP4Moviez | ~~mp4moviez.cloud~~ `www.mp4moviez.deal` | already scraped | **Not a to-add site.** 29,848 pages already in `mp4moviez.db`; see § MP4Moviez for the converter that makes it mergeable |
| World4uFree | world4ufree.biz | XML sitemap | Dual audio |
| Bolly4u | bolly4u.trade | XML sitemap | Bollywood |
| watch-movies.com.pk | watch-movies.com.pk | CF challenge | Needs special headers |
| hdmoviesbd.xyz | NXDOMAIN | Find mirror | Domain dead |
| Movierulz | movierulz.plz | Cloudflare | Complex JS |
| 9xmovies | 9xmovies.care | XML sitemap | South + Bolly |
| Kuttymovies | kuttymovies.cool | XML sitemap | Tamil focus |
