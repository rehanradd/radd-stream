# 🔭 Site Scout: Automated Scraper Synthesis & Reverse-Engineering Engine
**Project**: `radd-stream`  
**Status**: Future Architecture & Tooling Specification  
**Author**: Antigravity & Core Team  
**Date Added**: October 23, 2026  

---

## 1. Vision & Purpose

Throughout the scraping of 18+ high-volume streaming platforms (Vegamovies, Bolly4u, KatmovieHD, 10xflix, World4uFree, DesiCinemas, etc.), we learned that site structures follow predictable patterns across WordPress, Blogger, and custom CMSs.

**`Site Scout`** is an open-source reverse-engineering tool and AI synthesizer designed to:
1. Analyze any target media streaming or download website in under 60 seconds.
2. Perform automated DOM archaeology (title, year, audio languages, posters, download buttons, bridges).
3. Generate a standardized **Site Fingerprint Schema (JSON)**.
4. Synthesize a complete, production-ready Python stdlib scraper (`import_<site>.py`) that crawls directly into its own isolated staging database (`/home/ubuntu/radd-stream-data/<site>.db`).

---

## 2. System Architecture

```
                  Target Website URL (e.g., https://target-streaming.com)
                                            │
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │       Stage 1: Recon & CMS Fingerprinting     │
                    │  • Inspects headers, meta, robots.txt         │
                    │  • Tests wp-json REST API & XML sitemaps      │
                    └───────────────────────┬───────────────────────┘
                                            │
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │    Stage 2: Semantic DOM Archaeology Engine   │
                    │  • HTML AST parsing (stdlib html.parser)      │
                    │  • Poster / Backdrop resolution heuristic     │
                    │  • Title, Year, Audio, Genre regex extractors │
                    │  • Download container & button isolation      │
                    └───────────────────────┬───────────────────────┘
                                            │
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │    Stage 3: Link & Redirect Graph Tracer      │
                    │  • Follows button links 1-2 hops deep         │
                    │  • Detects CDNs (PixelDrain, R2, GDrive)      │
                    │  • Identifies Bridge Shorteners (HubCloud etc)│
                    └───────────────────────┬───────────────────────┘
                                            │
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │    Stage 4: AI Scraper Synthesis Generator    │
                    │  • Produces site_blueprint.json               │
                    │  • Calls local Qwen (via disciple code)       │
                    │  • Generates Fast_Fetch/import_<site>.py      │
                    └───────────────────────────────────────────────┘
```

---

## 3. Four Core Stages

### Stage 1: Recon & CMS Fingerprinting
- **Sitemap Discovery**: Probes `/sitemap_index.xml`, `/post-sitemap.xml`, `/sitemap.xml`, and `/robots.txt`.
- **REST API Probe**: Checks if `/wp-json/wp/v2/posts` is publicly open. If open, bypasses HTML scraping entirely and consumes raw structured JSON.
- **Feed Probes**: Checks `/feed` and `/rss` for latest post updates.

### Stage 2: Semantic DOM Archaeology
- **Sample Selection**: Fetches 10–20 random posts across different categories to prevent single-post formatting anomalies.
- **Title & Year Extraction**: Distinguishes between site branding (e.g. `Vegamovies.to - `) and actual movie title + release year `(19\d\d|20\d\d)`.
- **Poster Extractor**: Isolates featured image tags, filtering out ad banners, logos, and badges.
- **Attributes Matrix**: Automatically maps regex groups for:
  - Resolution: `480p`, `720p`, `1080p`, `4k`, `UHD`, `HDR`
  - Audio/Language: `Hindi`, `English`, `Dual Audio`, `Multi Audio`, `Bengali`, `Urdu`
  - Codec: `x264`, `x265`, `HEVC`, `10Bit`

### Stage 3: Link & Redirect Graph Tracer
- Traces `href` attributes inside identified download blocks.
- Classifies link destinations against known hoster registries:
  - Direct Cloud: `pixeldrain.com`, `drive.google.com`, `r2.dev`, `gofile.io`
  - Bridge Networks: `hubcloud.*`, `fastilinks.*`, `wlinksi.*`, `mzgserver.*`
  - Stream Embeds: `streamtape.com`, `vidhide.com`, `1xplayer.*`
- Tests whether bridge pages contain known bypass patterns (AJAX tokens, form submits, direct download button redirects).

### Stage 4: AI Code Synthesizer
- Outputs a standardized `site_blueprint.json`:
```json
{
  "site_name": "target_site",
  "base_url": "https://target-site.com",
  "cms": "wordpress",
  "sitemap_url": "https://target-site.com/post-sitemap.xml",
  "title_regex": "(?P<title>.+?)\\s*\\((?P<year>\\d{4})\\)",
  "poster_selector": "article .post-thumbnail img",
  "link_patterns": [
    {"kind": "bridge", "regex": "https://hubcloud\\.[a-z]+/drive/[a-zA-Z0-9]+"}
  ]
}
```
- Passes blueprint to local AI (`disciple code` with `qwen2.5-coder:1.5b`) to instantly emit a tested `import_<site>.py` following Radd-Stream's strict stdlib staging guidelines.

---

## 4. Technical Hurdles & Mitigation Strategies

1. **WAF & Cloudflare JS Challenges**:
   - Use browser-like TLS headers and User-Agent cycling.
   - For severe Turnstile / DDoS-Guard sites, provide a headless browser hook for initial token exchange.
2. **Dynamic Next.js / Single Page Apps**:
   - Inspect `<script id="__NEXT_DATA__">` JSON payloads before parsing DOM.
3. **Multi-Domain Mirror Shifting**:
   - Maintain a dynamic domain resolver that tracks when sites migrate from `.com` to `.to` or `.watch`.
4. **Human Formatting Variances**:
   - Rely on content clustering rather than strict XPath/CSS selectors.

---

## 5. Execution Roadmap

- **Phase 1**: Implement `Fast_Fetch/site_scout.py` (CLI reconnaissance & blueprint generator).
- **Phase 2**: Implement `Fast_Fetch/bridge_tracer.py` (Redirect graph follower).
- **Phase 3**: Connect with `disciple.py` to automate full scraper generation.
- **Phase 4**: Open-source standalone repository as a community media scraper generator.
