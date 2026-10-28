# radd-stream — Universal Media Metadata & CDN Latency Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-green.svg)](requirements.txt)
[![Sites: 10](https://img.shields.io/badge/sites-10-orange.svg)](#supported-sites)
[![DB: SQLite](https://img.shields.io/badge/database-SQLite-lightblue.svg)](#database)

A **zero-dependency** (100% Python standard library) distributed media aggregator, edge link resolver, and relational catalog database engine. No pip packages. No npm. No Docker. Runs identically on Windows, Linux VPS, Replit, or macOS with standard Python 3.8+.

---

## What It Does

- **Aggregates** public media catalog posts from 10 distributed sources (22,000+ public URLs cached)
- **Resolves** multi-hop redirect chains and tokenized CDN routes to **direct stream endpoints**
- **Enriches** every title automatically with canonical IMDb rating, TMDB poster, genres, and synopsis via open Cinemeta REST API
- **Deduplicates** canonically — merges multiple distributed release variants under one master SQLite media entity
- **Diagnostic Probing** — evaluates HTTP Range requests (206 Partial Content) and connection latency to test network health
- **Heals** expired stream tokens automatically by re-requesting fresh gateways
- **Exports** a single-file standalone HTML offline dashboard for instantaneous querying

---

## Supported Sites

| Site | Domain | Sync Method | Posts Cached | CDN/Bridge |
|------|---------|-------------|-------------|------------|
| Vegamovies | vegamovies.gallery | WP XML Sitemap | 14,025 | Nexdrive → FastDL / VCloud / HubCloud |
| RogMovies | rogmovies.one | WP XML Sitemap | 2,000 | Nexdrive → same |
| SSRMovies | ssrmovies.gripe | WP REST API | ~100/batch | LinksZilla → HubCloud / GDFlix / Direct-Cloud |
| KatMovieHD | katmoviehd.fans | SvelteKit JS | ~50 | KatDrive API → HubCloud / 1fichier |
| 7StarHD | 7starhd.rich | Homepage scrape | 28 | MobileJSR → direct CDN |
| 10xflix | 10xflix.help | WP REST API | ~100/batch | MobileJSR → direct CDN |
| MultiMovies | multimovies.garden | XML Sitemap (10K/file) | ~10,000 | watchConfig JSON → embed servers |
| HDHub4u | new3.hdhub4u.free | WP post-sitemap.xml | 1,000 | greenmotors.cc base64 bridges |
| BollyShares | bollyshares.xyz | WP post-sitemap.xml | 200 | 10moviesz.mom short links |
| FilmyZilla | filmyzilla74.com | XML Sitemap | 5,002 | /server/`<id>`/`<fn>`.html quality pages |

---

## Quick Start

### Windows
```cmd
run.bat sync
run.bat search "pathaan"
run.bat fetch "https://multimovies.garden/movie/pathaan-2023/"
run.bat stats
```

### Linux / macOS / VPS / Replit
```bash
bash run.sh sync
bash run.sh search "pathaan"
bash run.sh fetch "https://multimovies.garden/movie/pathaan-2023/"
bash run.sh stats
```

### Direct Python (any platform)
```bash
python Fast_Fetch/fast_fetch.py sync --site all
python Fast_Fetch/fast_fetch.py search "avengers"
python Fast_Fetch/fast_fetch.py fetch "https://vegamovies.gallery/avengers-2019/"
python Fast_Fetch/fast_fetch.py stats
python Fast_Fetch/fast_fetch.py export-html   # Open database_view.html in browser
```

### First-Time Setup (any platform)
```bash
python setup_check.py                            # Verify environment
python Fast_Fetch/fast_fetch.py sync --site all  # Populate local sitemap URL indexes
python Fast_Fetch/fast_fetch.py crawl 100        # Fetch & resolve 100 posts
python Fast_Fetch/fast_fetch.py export-html      # Generate HTML dashboard
```

---

## Requirements

- **Python 3.11+** only
- **Zero pip installs** — uses only: `urllib`, `sqlite3`, `re`, `json`, `ssl`, `base64`, `pathlib`, `concurrent.futures`
- Internet connection for scraping (offline browsing works on cached DB)

---

## Verification

Run the offline checks from the repository root:

```bash
python -S Fast_Fetch/test_database.py
python -S Fast_Fetch/test_vidout.py
python setup_check.py
```

The live audit requires internet access and stores its sample ingests only in a
temporary SQLite database:

```bash
python Fast_Fetch/test_all_sites.py
```

---

## REST API for Catalog Metadata

Run the local API and dashboard from the repository root:

```bash
python Fast_Fetch/fast_fetch.py web --port 8080
```

Use the machine's reachable IP or hostname as the base URL when connecting from
another device. These examples cover the metadata endpoints used by the Android
catalog client:

```bash
curl "http://127.0.0.1:8080/api/v1/posts?q=pathaan&type=movie&page=1&limit=20"
curl "http://127.0.0.1:8080/api/v1/stats"
```

### `GET /api/v1/posts`

Query parameters:

| Name | Optional | Meaning |
|---|---:|---|
| `q` | yes | Search title, clean title, or slug |
| `type` | yes | Filter by `movie`, `series`, `complete_season`, or `ongoing_season` |
| `page` | yes | 1-based page number (default `1`) |
| `limit` | yes | Results per page (default `20`, capped at `100`) |

> ⚠️ **Reality (verified against viewer.py 2026-10-22):** `type` is compared to
> `posts.content_type` with exact SQL equality (`p.content_type = ?`,
> viewer.py:1898), and the writers only ever emit the four values listed above
> (`classify_media()`, fast_fetch.py:1613-1622). **`?type=anime` returns zero
> rows** — it is not an error, just an empty result. Anime lives in the separate
> `is_animated` / `industry` columns, and neither is exposed as a query parameter
> by this API yet, so anime filtering needs a new `animated` flag before clients
> can offer it.

The response contains `page`, `limit`, `total`, `total_pages`, and a `results`
array. Each result carries exactly these keys (viewer.py:1905-1909): `id`,
`clean_title`, `title`, `year`, `content_type`, `seasons`, `poster_url`,
`imdb_rating`, `imdb_id`, `tmdb_id`, `genres`, `source_site`, `industry`,
`country`, `language`, `release_count`, and `source_count`. `slug` is **not**
part of the list payload; it appears only on the detail response.

### `GET /api/v1/posts/{id}`

Returns `{"success": true, "data": {...}}` — the `posts` row plus
`source_pages[]` and `releases[]`, each release embedding its own `sources[]`.
Releases are ordered `id ASC` only; there is no quality sorting and no
season/episode grouping (viewer.py:1942). The priority ordering applies only to
`sources` within a release (viewer.py:1946-1961). Unknown or adult-flagged ids
return `404`.

### `GET /api/v1/stats`

Returns catalog and diagnostic counts: `posts`, `releases`, `sources`,
`active_sources`, `resumable_sources`, and `temporary_sources`. Counts are live
and grow with every scraper run — older docs quoted `131 / 1031 / 2017`, which
was a 2026-10-13 snapshot and should be read only as an illustrative example, not
a current total. Note also that these counts include `is_18_plus = 1` rows that
`/api/v1/posts` hides, so the browsable catalog is smaller than `posts` suggests.

### Authentication and transport

There is **none**. `viewer.py` implements no API key, token, session, or rate
limiting; `send_json()` sets `Access-Control-Allow-Origin: *` on every response
(viewer.py:2037) and `start_server()` binds `0.0.0.0` by default (viewer.py:2211).
There is no TLS anywhere in the backend, and the Oracle deployment is plain HTTP.
Treat every route, the whole catalog, and every resolved stream URL as public to
anyone who can reach the port.

The `resolve_live_source()` JIT resolver at `/api/v1/stream` is implemented and is
used by the Android detail/player screens; the older claim that the app "does not
implement stream resolution or playback" no longer matches `App/app/src`.

> `/api/heal?id=…` is routed but **broken and unusable**: its handler builds a
> response payload and never writes it to the socket (viewer.py:2100-2108), so
> HTTP/1.1 clients hang until they time out. Use the `fast_fetch.py heal` CLI
> instead.

---

## Android App

The native Kotlin/Jetpack Compose client lives in `App/`. It is built for media
catalogs and backends the operator is authorized to access. As verified in
`App/app/src` on 2026-10-22, the current implementation includes first-run server
setup, a catalog grid, title search, Room-backed favorites, a detail screen, and
Media3 playback through `/api/v1/stream`. That build has **not** been verified on
a physical device, and the season/episode release model does not match the API
(see [`App/AGENTS.md`](App/AGENTS.md) §6).

GitHub Actions runs Android tests, lint, and the debug build from the repository
root. Download the debug APK from the workflow run's **Artifacts** section.
Tagged release builds require the signing secrets listed in
[`App/docs/BUILD_PLAN.md`](App/docs/BUILD_PLAN.md). See
[`App/README.md`](App/README.md) for the app's current scope and setup.

---

## Project Structure

```
radd-stream/
├── Fast_Fetch/
│   ├── fast_fetch.py       ← Main engine (6,370 lines: scraper + DB + CLI + resolver)
│   ├── viewer.py           ← REST API + dashboard HTTP server (all /api/* routes)
│   ├── config.py           ← Project config (name, paths, settings)
│   ├── database_view.html  ← Offline DB browser (auto-generated, open in browser)
│   ├── AGENTS.md           ← REQUIRED READING for any AI agent
│   ├── SITES.md            ← Deep-dive reference for every site + bridge
│   ├── SETUP.md            ← Platform-specific setup guide
│   └── fast_fetch.db       ← SQLite database (gitignored, regeneratable)
├── App/                    ← Kotlin / Jetpack Compose Android catalog client
├── .github/workflows/      ← Android CI and release workflows
├── run.sh                  ← Linux/Mac/VPS/Replit launcher
├── run.bat                 ← Windows launcher
├── setup_check.py          ← Environment verifier (run first on any new machine)
├── requirements.txt        ← Empty (zero deps)
├── .replit                 ← Replit configuration
└── README.md
```

---

## CLI Reference

```
python fast_fetch.py sync [--site SITE] [--limit N] [--categories] Sync URL index from sitemaps
python fast_fetch.py sync-categories [--site SITE] [--pages N] [--category CAT] Ingest category archives (HDHub4u/SSRMovies)
python fast_fetch.py search QUERY [--site SITE] [--limit N] Instant offline title search
python fast_fetch.py fetch URL [--site SITE]               Fetch, resolve & save a post
python fast_fetch.py crawl [LIMIT] [--site SITE]           Auto-crawl latest N posts
python fast_fetch.py view ID                               View a saved entry + sources
python fast_fetch.py stats                                 Database metrics
python fast_fetch.py export [json|csv]                     Export data
python fast_fetch.py export-html                           Regenerate HTML dashboard
python fast_fetch.py set-domain NAME URL                   Override a site domain
python fast_fetch.py check-links [--id ID]                 Health-check source URLs
python fast_fetch.py heal [--id ID] [--all]               Re-resolve dead/expired links
```

### `--site` values
`vegamovies` | `rogmovies` | `ssrmovies` | `katmoviehd` | `7starhd` | `10xflix` | `multimovies` | `hdhub4u` | `bollyshares` | `filmyzilla` | `all`

---

## Configuration

Edit `Fast_Fetch/config.py` to:
- Change the project name → `PROJECT_NAME = "my-stream-db"`
- Set custom DB path → `DB_PATH = Path("/data/mydb.db")`
- Or use environment variables:
  ```bash
  export RADD_DB_PATH=/data/custom.db
  export RADD_HTTP_TIMEOUT=30
  export RADD_CINEMETA=0   # disable enrichment
  python Fast_Fetch/fast_fetch.py sync
  ```

---

## Database Schema

The live schema and migrations are defined by `Fast_Fetch/fast_fetch.py`;
`Fast_Fetch/DATABASE_SCHEMA.md` documents the implemented tables and indexes.
The main tables are:

- `posts`: one shared media row when identity is supported by matching external
  IDs, an existing page association, or one unambiguous type-aware title/year
  match. `canonical_key` is indexed but is not unique.
- `post_sources`: each original `(site, page URL)` and its site-specific title,
  slug, and first/last-seen timestamps, linked to the shared post.
- `releases`: release variants with their own `source_site` attribution.
- `download_sources`: source/bridge records attached to a release.
- `sitemap_cache` and `domains_config`: discovery and domain settings.

Conflicting IDs, reused URLs with incompatible known type/year, and ambiguous
title matches fail explicitly instead of merging records arbitrarily. Legacy
release rows without reliable site attribution remain unattributed.

---

## Deploying on Different Platforms

### Replit
1. Import from GitHub: `https://github.com/rehanradd/radd-stream`
2. Replit auto-detects `.replit` config — press **Run** or use the Shell:
   ```bash
   python Fast_Fetch/fast_fetch.py sync --site all
   ```

### Oracle Cloud / Ubuntu VPS
```bash
sudo apt update && sudo apt install python3.11 -y
git clone https://github.com/rehanradd/radd-stream.git
cd radd-stream
python3 setup_check.py
bash run.sh sync --site all
```

### GitHub Codespace
1. Open repo → Code → Codespaces → New codespace
2. Terminal is ready, Python 3.11+ pre-installed:
   ```bash
   bash run.sh sync --site all
   ```

### Windows (Local)
```cmd
git clone https://github.com/rehanradd/radd-stream.git
cd radd-stream
python setup_check.py
run.bat sync --site all
```

---

## For AI Agents

**Read `Fast_Fetch/AGENTS.md` FIRST** — it contains the complete architecture, all site patterns, bridge chains, constraints, session history, and what's TODO next.

Quick start prompt for any AI tool:
> "Read Fast_Fetch/AGENTS.md before doing anything. That file is your complete guide. Zero pip dependencies — stdlib only. Verify with: python -c 'import fast_fetch; print(OK)' after every change."

---

## Adding New Sites

See `Fast_Fetch/AGENTS.md` → "How to Add a New Site" section for the exact 8-step pattern.

---

## Philosophy

- **Own your data** — SQLite file, fully portable, no vendor lock-in
- **Zero deps** — runs on any machine with Python 3.11+
- **Auto-healing** — domain changes tracked, expired links revived
- **Canonical** — one entry per title across all 10+ sites
- **Enriched** — Cinemeta auto-fills IMDb, TMDB poster, genres, synopsis
- **No 18+ content** — enforced at database level (`is_18_plus=0`)
