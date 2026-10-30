# Spec Fast Fetch Architecture

> Moved **verbatim** out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `Fast_Fetch/AGENTS.md`
> carried at this sha. Law stayed in `Fast_Fetch/AGENTS.md`; this is the reference prose it now links to.
### from `Fast_Fetch/AGENTS.md` lines 55-114

```
fast_fetch.py
│
├── [L1-50]   Imports + UTF-8 fix + SSL_CONTEXT + BASE_DIR/DB_PATH
├── [L48-89]  DEFAULT_DOMAINS dict  — all 10 site URLs + sitemaps
├── [L92-104] get_domains()         — reads live overrides from domains_config table
├── [L107-]   set_domain()          — writes domain override to DB
│
├── [L155-]   normalize_url()       — auto-fixes stale/old domains before HTTP
│             └── Checks: multimovies, bollyshares, filmyzilla, 10xflix, vegamovies, etc.
│
├── [L208-]   harvest_sister_domains() — scrapes nav links for live domain updates
│
├── [L290-]   http_get()            — SSL-patched urllib with retries + redirect tracking
│             └── Returns (status_code, final_url, html_body)
│
├── [L706-973] sync_sitemaps()      — fills sitemap_cache table
│   ├── Block 1 [L716]:  Vegamovies, RogMovies    (WP XML Sitemap)
│   ├── Block 2 [L788]:  SSRMovies                 (WP REST API)
│   ├── Block 3 [L823]:  7StarHD                   (Homepage scrape)
│   ├── Block 4 [L858]:  KatMovieHD                (SvelteKit items[])
│   ├── Block 5 [L893]:  MultiMovies               (sitemap-titles-*.xml)
│   ├── Block 6 [L936]:  10xflix                   (WP REST API)
│   ├── Block 7 [L971]:  HDHub4u                   (WP post-sitemap.xml)
│   ├── Block 8 [L???]:  BollyShares               (WP post-sitemap.xml)
│   └── Block 9 [L???]:  FilmyZilla                (XML Sitemap)
│
├── [L1002-]  parse_post_metadata() — default metadata parser (Vega/Rog style)
│
├── CDN Unwrappers:
│   ├── unwrap_nexdrive()           — Nexdrive bridge → multi-CDN
│   ├── unwrap_fastdl()             — FastDL embed → Google CDN
│   ├── unwrap_vcloud()             — VCloud double-base64 → R2/HubCloud
│   ├── unwrap_hubcloud_drive()     — HubCloud → gamerxyt → Google CDN
│   ├── unwrap_pixeldrain()         — pixeldrain.com/u/ID → /api/file/ID
│   ├── unwrap_vegadrive()          — vegadrive → /d/ID/skyd
│   ├── unwrap_mobilejsr()          — mobilejsr.com/view/ID → embedded links
│   └── unwrap_linkszilla()         — linkszilla → HubCloud/GDFlix/Direct-Cloud
│
├── Site Extractors:
│   ├── extract_post_data_ssrmovies()    — LinksZilla bridges
│   ├── extract_post_data_katmoviehd()   — KatDrive API (dandndn.one)
│   ├── extract_post_data_7starhd()      — MobileJSR bridges
│   ├── extract_post_data_10xflix()      — MobileJSR bridges
│   ├── extract_post_data_multimovies()  — watchConfig JSON servers
│   ├── extract_post_data_hdhub4u()      — greenmotors.cc base64 bridges
│   ├── extract_post_data_bollyshares()  — 10moviesz.mom short links
│   ├── extract_post_data_filmyzilla()   — /server/<id>/<fn>.html pages
│   └── extract_post_data()             — DISPATCHER (routes to above)
│
├── [L???]  fetch_cinemeta_metadata()    — Cinemeta API enrichment
├── [L???]  save_scraped_data()          — guarded identity matching + atomic SQLite save
├── [L???]  classify_media()             — industry/language/country detection
├── [L???]  generate_canonical_key()     — fallback title/year identity key
│
└── [L3300+] CLI argparse main()
    ├── sync, search, fetch, crawl, view, stats
    ├── export, export-html, set-domain, check-links, heal
    └── SITE_CHOICES / SITE_INDIVIDUAL lists
```
