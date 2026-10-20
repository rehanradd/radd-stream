# ⚡ Fast_Fetch — World's #1 Streaming & Media Database Engine

> **"The Dao of Streaming"** — The most complete, most powerful, most resilient movie & TV database ever built. Zero dependencies. Infinite growth. Every title. Every source. Always alive.
>
> 📜 Read [DAO.md](DAO.md) — The Eternal Project Manifesto

---

> [!IMPORTANT]
> This guide does not grant repository, account, or production permissions.
> Read [DAO.md](DAO.md) and [AGENTS.md](AGENTS.md) before starting; ask before destructive or production-impacting actions.
> Constraint: Python stdlib only. No pip. No adult content. Test everything.

---

## 🌟 Executive Summary

**Fast_Fetch** indexes, parses, probes, and monitors direct streaming and download media links from WordPress movie/series distribution networks (Vegamovies ecosystem). Rather than downloading large video files, it unwraps multi-hop ad bridges, resolves intermediate token gates, and extracts clean, raw CDN video streams (Google Direct CDN, Cloudflare R2, VegaDrive, PixelDrain, Filepress, Firebase) directly into SQLite.

### Key Capabilities
* **Multi-Site Catalog**: Supports the ten configured site parsers. Confidently matched media shares one `posts` row while `post_sources` retains each site's page and `releases.source_site` retains release provenance.
* **Safe Cross-Site Identity**: Prefer IMDb/TMDB identifiers, then an existing site-page mapping, then a unique title/year match of the same media type. Ambiguous matches and conflicting identities are rejected; the canonical key is not unique.
* **Smart Organization & Taxonomy**: Automatic categorization by first-seen site, release/page provenance, `industry` (Hollywood, Bollywood, Pollywood, Tollywood, Gujarati Cinema, Anime, K-Drama), `country`, and `language`.
* **Offline Search**: Query locally cached sitemap URLs and indexed media without repeated site-search requests. Sitemap counts are discovered-page counts, not the number of saved master media rows.
* **Direct CDN Unwrapping**: Automatically unwraps Nexdrive, V-Cloud, HubCloud, FastDL, VegaDrive, PixelDrain, and Filepress into raw video streaming links (`video/mkv`, `video/mp4`).
* **Live Health & Dead Link Finder**: High-concurrency probing classified into `🟢 Active`, `⚡ Resumable (HTTP 206)`, `🟡 Expired Token`, or `🔴 Dead Link`.
* **Range Resumability Detection**: Probes `Range: bytes=0-100` support to classify links suitable for pause/resume, instant video seeking, and multi-threaded download acceleration (IDM / aria2).
* **Automated Self-Healing Engine**: Automatically re-contacts intermediate bridges to re-generate fresh, valid authentication tokens when links expire.
* **20-Year Future-Proofing (Dynamic Domains)**: Multi-layer defense against domain bans: silent 301/302 redirect tracking, pre-fetch normalizer, sister-site cross-link harvester, candidate TLD fallback probing, and atomic database URL migration.
* **Rich Metadata & Content Classification**: High-resolution TMDB posters, screenshot backdrops, IMDb ratings, genres, synopsis, with strict word-boundary classification for `🔞 18+ Adult` and `🎨 Anime/Animation`.
* **Universal Access**: CLI, multi-threaded local Web Dashboard (`viewer.py` on `localhost:8080`), and a standalone offline portable dashboard (`database_view.html`).

---

## 📁 Repository File Structure

```
Fast_Fetch/
├── fast_fetch.py          # Core engine: Scraper, unwrappers, health checker, self-healing, CLI
├── viewer.py              # Zero-dependency multi-threaded HTTP server & dashboard (port 8080)
├── fast_fetch.db          # Local SQLite database, created/migrated at runtime (gitignored)
├── database_view.html     # Generated offline snapshot; may be stale until export-html is run
├── DATABASE_SCHEMA.md     # Full relational database ER diagram & schema documentation
├── NAVIGATORS.md          # Technical documentation of bridge unwrappers & CDN mechanics
├── test_database.py       # Offline SQLite identity, migration, and concurrency regressions
├── test_vidout.py         # Offline VIDOUT HLS parser regressions
├── test_all_sites.py      # Live site/parser/database ingestion audit (temporary DB)
└── README.md              # System documentation & usage guide
```

The database is a shared catalog with per-site provenance, not strict isolation
by site. Older release rows with unknown provenance are not assigned the
parent post's first-seen site. See `DATABASE_SCHEMA.md` for migration details.

### Verification

From the repository root:

```bash
python -S Fast_Fetch/test_database.py
python -S Fast_Fetch/test_vidout.py
python setup_check.py
python Fast_Fetch/test_all_sites.py   # live network audit; writes only to a temporary database
```

---

## 🚀 Quick Start & CLI Reference

### 1. Database Exploration & Viewing
```powershell
# Open local interactive web explorer (default: http://localhost:8080)
python fast_fetch.py web

# Export latest database state to standalone offline HTML dashboard
python fast_fetch.py export-html

# List all indexed media posts in the database
python fast_fetch.py list

# View full release breakdown, episode lists, and direct links for a specific post
python fast_fetch.py view 1
python fast_fetch.py view "chal-mera-putt"

# Show database metrics (sitemaps, posts, releases, sources)
python fast_fetch.py stats
```

### 2. Multi-Site Sitemaps & Instant Search
```powershell
# Instant offline search across both sites (< 1ms)
python fast_fetch.py search "jawan"

# Search specifically within RogMovies (Indian/Bollywood) or Vegamovies (Hollywood/World)
python fast_fetch.py search "punjabi" --site rogmovies
python fast_fetch.py search "attack on titan" --site vegamovies

# Synchronize sitemaps into local cache
python fast_fetch.py sync --site all
python fast_fetch.py sync --site rogmovies --limit 5

# Ingest paginated category archives for full catalog coverage (HDHub4u & SSRMovies)
python fast_fetch.py sync-categories --site all --pages 3
python fast_fetch.py sync-categories --site hdhub4u --category bollywood-movies --pages 5
python fast_fetch.py sync --site ssrmovies --categories --cat-pages 3
```

### 3. Live Health Checking & Dead Link Finder
```powershell
# Run live diagnostic on all links in database (concurrency: 12 workers)
python fast_fetch.py health-check

# Diagnostic on a specific post only
python fast_fetch.py health-check --id 3

# Only check links previously flagged as dead or expired
python fast_fetch.py health-check --dead-only

# Run health check AND automatically self-heal any dead/expired links found!
python fast_fetch.py health-check --heal
```

### 4. Self-Healing Engine
```powershell
# Regenerate fresh tokens and revive dead links for a single post
python fast_fetch.py heal 3

# Revive dead links across all posts in the entire database
python fast_fetch.py heal --all
```

### 5. Dynamic Domain Management (Future-Proofing)
```powershell
# View all active domain endpoints and mirrors
python fast_fetch.py domain list

# Ping all mirrors and auto-update any moved or redirected domains
python fast_fetch.py domain ping

# Harvest sister network domains from live website headers
python fast_fetch.py domain harvest

# Manually update a mirror if a domain changes
python fast_fetch.py domain set rogmovies "https://rogmovies.one"
python fast_fetch.py domain set vegamovies "https://vegamovies.gallery"

# Atomically migrate all historical database URLs when a domain retires
python fast_fetch.py domain migrate rogmovies.wtf rogmovies.one
```

### 6. On-Demand Fetching & Batch Crawling
```powershell
# On-demand scraping and direct link resolution (auto-classifies industry and country)
python fast_fetch.py fetch "https://rogmovies.one/download-chal-mera-putt-2019-punjabi-full-movie-480p-720p-1080p-web-dl/"
python fast_fetch.py fetch "https://vegamovies.gallery/download-attack-on-titan-season-4-hindi-dubbed-web-dl-480p-720p-1080p/"

# Batch crawl next N unscraped posts from sitemap cache
python fast_fetch.py crawl 10 --site rogmovies
python fast_fetch.py crawl 10 --site vegamovies
```

---

## 🌐 Supported Bridges & Direct CDN Gateways

| Bridge / Service | Service Key | Direct CDN Resolution Mechanism | Status |
|---|---|---|:---:|
| **Google Direct CDN** | `google_cdn` | `video-downloads.googleusercontent.com` (Raw high-speed MKV video) | 🟢 Active |
| **Cloudflare R2** | `fsl_r2` | `pub-....r2.dev` (Full HTTP Range 206 partial content resumability) | 🟢 Active |
| **PixelDrain** | `pixeldrain.com` | `pixeldrain.com/api/file/<ID>` (Direct high-speed stream API) | 🟢 Active |
| **VegaDrive** | `vegadrive` | `one.vegadrive.me/d/<ID>/skyd` (10Gbps direct stream) | 🟢 Active |
| **FilePress / FileBee** | `filepress` | Proxied Google Drive direct stream (`filepress.lat` / `filebee.xyz`) | 🟢 Active |
| **FastDL** | `fastdl` | JavaScript regex unwrapping to Google UserContent CDN | 🟢 Active |
| **V-Cloud** | `vcloud` | Double Base64 decoding (`atob(atob(...))`) to R2/HubCloud tokens | 🟢 Active |
| **HubCloud 10Gbps** | `hubcloud` | Unwrapped to direct Google CDN via redirect parameter | 🟢 Active |
| **Google Firebase** | `firebase` | `firebasestorage.googleapis.com` (Direct cloud bucket streams) | 🟢 Active |
| **Cloudflare Workers** | `workers_dev` | `dl.*.workers.dev` (Google Drive reverse proxy streams) | 🟢 Active |
| **DropGalaxy VIP** | `dropgalaxy` | Direct high-speed file storage | 🟢 Active |
| **Cloud Mirrors** | `gofile`, `1fichier`, `megaup` | Gofile, 1fichier, MegaUp, VikingFile, 7-Up secondary mirrors | 🟢 Active |

---

## 📊 Database Health & Diagnostic Status

Current production database metrics:
* **Sitemap URLs Cached**: `16,025` posts (`14,025` Vegamovies + `2,000` RogMovies)
* **Indexed Media Posts**: `45`
  * 🎬 **Hollywood & International**: 21
  * 🇮🇳 **Bollywood, Tollywood & Regional**: 12
  * 🎨 **Anime & Animated**: 8
* **Release Variants**: `1,641` (Single episodes, 480p/720p/1080p/4K, batch season packs)
* **Resolved Direct Links**: `4,266` sources (🟢 `4,024` Verified Active | ⚡ `260` Resumable Range 206)

---

## 📺 VLC / Streaming Integration

Fast_Fetch exports direct M3U playlists compatible with VLC, Infuse, IINA, and Kodi.

* **Endpoint**: `http://localhost:8080/api/m3u?id=<post_id>`
* Automatically filters out broken/dead links so players don't stutter or skip.
* Prioritizes HTTP Range resumable streams first for instant scrubbing and playback buffering.

---

## 🔮 Roadmap: Scaling to the World Tree

1. **Multi-Source Crawling**: Add pluggable scrapers for additional distribution networks (KatMovieHD, MoviesMod, BollyFlix) sharing the same relational schema.
2. **Automated Cron Health Audits**: Background scheduled timer to audit all stored links once per day and auto-heal degraded links.
3. **Headless REST API / Sidecar**: Serve JSON endpoints for mobile streaming apps (React Native / Flutter) and personal home-lab media servers.
