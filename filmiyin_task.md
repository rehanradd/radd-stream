# 🤖 AUTONOMOUS SCRAPER SPECIFICATION FOR: `filmiyin`

> **ROLE**: You are building an isolated, production-grade streaming scraper for `radd-stream`.

## 1. ARCHITECTURAL PROFILE
- **Target URL**: https://filmiy.in
- **CMS / Framework**: unknown
- **Primary Discovery Route**: https://filmiy.in/sitemap.xml
- **Sitemaps**: https://filmiy.in/sitemap.xml
- **WP-JSON API**: None detected
- **Protection Layer**: none

## 2. DISCOVERED MEDIA ASSETS (SANITIZED SAMPLE)
- **Sample Title**: The Paradise (2026) (Hindi + Telugu) Dual Audio UnCut South Movie HD ESub » FilmyFly 2026 – Bollywood, South Hindi Dubbed, Hollywood Movies & Web Series
- **Description / Synopses**: ...
- **Embed Stream Servers Discovered (0)**:
- **Download Mirrors & Bridges Discovered (2)**:
  - `https://filmiy.in/page-how-to-download-movie.html`
  - `https://filmiy.in/page-how-to-download-movie.html`

## 3. INVIOLABLE CONSTRAINTS & RULES
1. **Pure Python Standard Library ONLY**: `urllib.request`, `json`, `re`, `sqlite3`, `html.parser`, `concurrent.futures`. Zero pip packages.
2. **Strict Staging Isolation**: Write exclusively to `/home/ubuntu/radd-stream-data/filmiyin.db`.
3. **Zero Provenance Leaks**: Scrub site names, upstream tokens, and tracker tags from all public outputs.
4. **18+ Safety Lexicon**: Evaluate tags and synopses. Flag adult content with `is_18_plus = 1`.
5. **Redundant Streaming**: Extract both watch/embed mirrors and direct download links across quality tiers (480p, 720p, 1080p).

## 4. CODE CONTRACT TO EMIT
Generate a complete Python module: `Fast_Fetch/importers/import_filmiyin.py` implementing:
- `def sync_catalog(limit=None):` -> enumerates and parses catalog items
- `def parse_page(html_or_url):` -> extracts clean metadata, embeds, and bridges
- `def resolve_links(post_data):` -> resolves downstream CDN mirrors
- `def export_staging(db_path):` -> commits cleanly into SQLite staging database