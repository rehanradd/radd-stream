# 🤖 AUTONOMOUS SCRAPER SPECIFICATION FOR: `pagalmovies`

> **ROLE**: You are building an isolated, production-grade streaming scraper for `radd-stream`.

## 1. ARCHITECTURAL PROFILE
- **Target URL**: https://www.pagalmovies.fit
- **CMS / Framework**: unknown
- **Primary Discovery Route**: https://www.pagalmovies.fit/sitemap.xml
- **Sitemaps**: https://www.pagalmovies.fit/sitemap.xml
- **WP-JSON API**: None detected
- **Protection Layer**: none

## 2. DISCOVERED MEDIA ASSETS (SANITIZED SAMPLE)
- **Sample Title**: Eyes 2026 Atrangii Hot Short Film Download Pagalmovies
- **Description / Synopses**: ...
- **Embed Stream Servers Discovered (2)**:
  - `https://five.vidcloud.quest/d/<ID>/watch_online`
  - `https://five.vidcloud.quest/d/<ID>/skydrop (10Gbps)`
- **Download Mirrors & Bridges Discovered (3)**:
  - `https://www.pagalmovies.fit/server/<file_id>/...`
  - `https://five.vidcloud.quest/d/<ID>/gofile`
  - `https://five.vidcloud.quest/d/<ID>/buzzheavier`

## 3. INVIOLABLE CONSTRAINTS & RULES
1. **Pure Python Standard Library ONLY**: `urllib.request`, `json`, `re`, `sqlite3`, `html.parser`, `concurrent.futures`. Zero pip packages.
2. **Strict Staging Isolation**: Write exclusively to `/home/ubuntu/radd-stream-data/pagalmovies.db`.
3. **Zero Provenance Leaks**: Scrub site names, upstream tokens, and tracker tags from all public outputs.
4. **18+ Safety Lexicon**: Evaluate tags and synopses. Flag adult content with `is_18_plus = 1`.
5. **Redundant Streaming**: Extract both watch/embed mirrors and direct download links across quality tiers (480p, 720p, 1080p).

## 4. CODE CONTRACT TO EMIT
Generate a complete Python module: `Fast_Fetch/importers/import_pagalmovies.py` implementing:
- `def sync_catalog(limit=None):` -> enumerates and parses catalog items
- `def parse_page(html_or_url):` -> extracts clean metadata, embeds, and bridges
- `def resolve_links(post_data):` -> resolves downstream CDN mirrors
- `def export_staging(db_path):` -> commits cleanly into SQLite staging database