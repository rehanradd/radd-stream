# AGENTS.md — Complete AI Agent Guide for radd-stream

> **READ THIS ENTIRE FILE before making any changes.**
> This is the single source of truth for every AI agent working on this project.
> Last updated: October 2026 | Session: Antigravity (Claude Opus 4.6)

---

> [!IMPORTANT]
> Read the actual repository state and project instructions before changing code.
> These notes do not grant account permissions or authorize production changes.
> Make routine, reversible technical decisions independently; ask the user before
> destructive or production-impacting actions. State blockers honestly and never
> disguise code behavior to bypass a platform's safety rules.
>
> **Project constraints:** Python standard library only, adult 18+ content stored
> with an is_18_plus flag and hidden at every presentation surface,
> strict staging database isolation, pre-push unit tests, and Master-Disciple
> Local AI law (delegate boilerplate to local Qwen 2.5 Coder via disciple.py to conserve cloud tokens).

---

## 0. Project Summary

The backend aggregates media catalog metadata and source links from configured
public sites, stores catalog records in SQLite, probes source endpoint
availability, and exposes API routes including source resolution. The Android
client consumes catalog metadata. Follow site terms, applicable law, and the
rules of the platform where you are working; do not conceal actual behavior.

---

## 1. Project Identity & Config

| Setting | Value |
|---------|-------|
| Project Name | `radd-stream` (configurable in `config.py`) |
| Version | 3.1.0 |
| GitHub | https://github.com/radddao/radd-stream |
| Main Engine | `Fast_Fetch/fast_fetch.py` (3,907 lines) |
| Database | `Fast_Fetch/fast_fetch.db` (SQLite, gitignored) |
| Config File | `Fast_Fetch/config.py` |
| Python Min | 3.11+ |
| Dependencies | ZERO — stdlib only |

**Rename project**: Edit only `config.py` → `PROJECT_NAME = "new-name"`. Nothing else needs to change.

**Change DB location**: Set env var `RADD_DB_PATH=/path/to/custom.db` OR edit `config.py` → `DB_PATH`.

---

## 2. Architecture Overview

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

---

## 3. All 10 Sites — Complete Reference

### 3.1 Vegamovies
| Field | Value |
|-------|-------|
| Domain | `vegamovies.gallery` |
| Known Aliases | `.yt`, `.one`, `.im`, `.vip`, `.wtf`, `.beer` |
| Sync Method | WP XML Sitemap |
| Sitemap URL | `https://vegamovies.gallery/sitemap.xml` → sub-sitemaps `post-sitemap1.xml`, `post-sitemap2.xml`... |
| Posts Cached | 14,025 |
| Content | Hollywood, International, Western Series, Anime |
| Post URL Pattern | `https://vegamovies.gallery/<title-year-quality>/` |
| Bridge | Nexdrive (`nexdrive.fit/genxfm...`) |
| CDN Chain | Nexdrive → FastDL / VCloud / HubCloud / VegaDrive / PixelDrain |
| Key Regex | `r'href=["\'](https?://nexdrive\.[a-z]+/[^\s"\'<>]+)["\']]'` |
| Sister Links | Links to RogMovies, GokuHD in nav |

**API/Data Endpoint:**
```
GET https://vegamovies.gallery/sitemap.xml
  → lists post-sitemap1.xml, post-sitemap2.xml, ...
GET https://vegamovies.gallery/post-sitemap1.xml
  → <loc> entries, one per post
```

---

### 3.2 RogMovies
| Field | Value |
|-------|-------|
| Domain | `rogmovies.one` |
| Known Aliases | `.wtf`, `.vip`, `.beer`, `.club`, `.fun` |
| Sync Method | WP XML Sitemap |
| Sitemap URL | `https://rogmovies.one/sitemap.xml` → `post-sitemap*.xml` |
| Posts Cached | 2,000 |
| Content | Bollywood, Tollywood, Pollywood, South Dubbed |
| Bridge | Nexdrive (identical to Vegamovies) |
| CDN Chain | Same as Vegamovies |

---

### 3.3 SSRMovies
| Field | Value |
|-------|-------|
| Domain | `ssrmovies.gripe` |
| Known Aliases | `.games` (old), `.monster`, `.club`, `.top` |
| Sync Method | **WP REST API** (sitemap redirects to homepage) |
| **API Endpoint** | `https://ssrmovies.gripe/wp-json/wp/v2/posts?per_page=100` |
| Content | Hindi Dubbed, Dual Audio, Web Series |
| Bridge | LinksZilla (`secure.linkszilla.top/view/<ID>`) |
| CDN Chain | LinksZilla → HubCloud / GDFlix / Direct-Cloud / Watch-Online |

**API Response Fields:**
```json
{
  "link": "https://ssrmovies.gripe/post-slug/",
  "slug": "post-slug",
  "date": "2024-01-15T12:00:00",
  "title": {"rendered": "Movie Name (2024)"},
  "content": {"rendered": "<HTML with download buttons>"}
}
```

**Paginate:** Add `&page=2`, `&page=3`... max 100/page.

---

### 3.4 KatMovieHD
| Field | Value |
|-------|-------|
| Domain | `katmoviehd.fans` |
| Landing | `katmovieshd.net` (redirects to `.fans`) |
| Known Aliases | `.rodeo`, `.top`, `.pictures`, `.eu` |
| Sync Method | SvelteKit JS data (`items:[{slug:"..."}]` in HTML) |
| Content | Multi-Audio Hollywood, 4K, Anime, Dual Audio |
| Bridge | KatDrive/DandnDn API |
| **API Endpoint** | `https://api.dandndn.one/api/v1/file/<ID>` |
| CDN Chain | KatDrive → HubCloud / 1fichier / Send.cm |

**Post URL:** `https://katmoviehd.fans/<slug>`
**Data:** Embedded in page HTML as `items:[{slug:"...", title:"..."}]`

---

### 3.5 7StarHD
| Field | Value |
|-------|-------|
| Domain | `7starhd.rich` |
| Known Aliases | `.run`, `.skin`, `.photos`, `.life`, `.vet`, `.com` |
| Sync Method | Homepage scrape — `<li class="thumb">` cards |
| Content | Bollywood, Hollywood Dual Audio, South Hindi Dubbed |
| Bridge | MobileJSR (`mobilejsr.com/view/<ID>`) |
| CDN Chain | MobileJSR → embed iframe → direct CDN |

**Homepage Pattern:**
```
GET https://7starhd.rich/
→ HTML with <li class="thumb"><a href="/post-slug/"> cards
```

**MobileJSR Bridge:**
```
URL: https://mobilejsr.com/view/<ID>
Contains: <iframe src="https://mobilejsr.com/embed/<ID>">
Embed HTML: direct video src or cloud mirror links
```

---

### 3.6 10xflix
| Field | Value |
|-------|-------|
| Domain | `10xflix.help` |
| Known Aliases | `.wiki`, `.me`, `.com`, `.org` |
| Sync Method | **WP REST API** |
| **API Endpoint** | `https://10xflix.help/wp-json/wp/v2/posts?per_page=100` |
| Content | Bollywood, Hollywood Dual Audio, South Hindi |
| Bridge | MobileJSR (same as 7StarHD) |
| CDN Chain | MobileJSR → embed iframe → direct CDN |

**Same WP REST API structure as SSRMovies.**

---

### 3.7 MultiMovies
| Field | Value |
|-------|-------|
| Domain | `multimovies.garden` |
| Known Aliases | `.com`, `.net`, `.live` |
| Sync Method | XML Sitemap with `sitemap-titles-*.xml` sub-sitemaps |
| **Sitemap Structure** | `sitemap.xml` → `sitemap-titles-1.xml`, `sitemap-titles-2.xml`... (10,000 entries each) |
| Posts Cached | ~10,000+ |
| Content | Bollywood, South Dubbed, Hollywood |
| **Data Endpoint** | `watchConfig` JSON embedded in post HTML |
| CDN Chain | watchConfig servers (embed iframes, HubCloud, GDFlix) |

**watchConfig JSON pattern in post HTML:**
```javascript
var watchConfig = {
  "sources": [
    {"label": "Server 1", "file": "https://embed.example.com/..."},
    {"label": "Server 2", "file": "https://hubcloud.ist/drive/..."}
  ]
}
```

**Sitemap URL Pattern:**
```
GET https://multimovies.garden/sitemap.xml
→ <loc>https://multimovies.garden/sitemap-titles-1.xml</loc>
→ <loc>https://multimovies.garden/sitemap-titles-2.xml</loc>
...each contains 10,000 /movie/ and /series/ URLs
```

---

### 3.8 HDHub4u
| Field | Value |
|-------|-------|
| Domain | `new3.hdhub4u.free` |
| Known Aliases | `new1`, `new2` (old), check site for current `new#` |
| Sync Method | **WP post-sitemap.xml** |
| **Sitemap URL** | `https://new3.hdhub4u.free/post-sitemap.xml` |
| Posts Cached | 1,000 |
| Content | Bollywood, Hollywood Dual Audio, Web Series |
| Bridge | greenmotors.cc (`https://greenmotors.club/?id=<BASE64>`) |
| CDN Chain | greenmotors (JS-rendered, stored as-is) → direct CDN |

**Bridge Note:** `greenmotors.cc` bridges require JavaScript rendering to resolve. We store the bridge URL as `final_url` since it's persistent (unlike MobileJSR which is stable). A JS-capable resolver can unwrap it later.

**Key Regex:**
```python
bridge_links = re.findall(r"""href=["'](https?://greenmotors\.[a-z]+/\?id=[A-Za-z0-9+/=_\-]+)["']""", html)
```

---

### 3.9 BollyShares
| Field | Value |
|-------|-------|
| Domain | `bollyshares.xyz` |
| Known Aliases | `bollywood1.xyz` (old) |
| Sync Method | **WP post-sitemap.xml** |
| **Sitemap URL** | `https://bollyshares.xyz/post-sitemap.xml` |
| Posts Cached | 200 |
| Content | Bollywood, South Hindi Dubbed |
| Bridge | `10moviesz.mom/?id=<ID>` short links |
| CDN Chain | 10moviesz → HubCloud / PixelDrain / direct |

**Key Regex:**
```python
bridge_links = re.findall(r"""href=["'](https?://10moviesz?\.[a-z]+/\?id=[^"'\s<>]+)["']""", html)
```

---

### 3.10 FilmyZilla
| Field | Value |
|-------|-------|
| Domain | `filmyzilla74.com` |
| Known Aliases | `filmyzilla71.com`, `filmyzilla73.com` (rotate numerically) |
| Sync Method | **XML Sitemap** |
| **Sitemap URL** | `https://www.filmyzilla74.com/sitemap.xml` |
| Posts Cached | 5,002 |
| Content | Bollywood, Hollywood Hindi Dubbed, Web Series |
| Bridge | Per-quality server pages: `/server/<id>/<filename>.html` |
| CDN Chain | /server/ page → embedded player / direct download |

**Post URL Pattern:** `https://www.filmyzilla74.com/movie/<id>/<Title-Year>.html`

**Quality Link Pattern:**
```python
server_links = re.findall(
    r'href=["\'](https?://www\.filmyzilla\d+\.com/server/\d+/[^"\'<>\s]+\.html)["\'"]',
    html
)
```

**Domain Rotation:** FilmyZilla increments the number: `71` → `73` → `74` → ... Check `normalize_url()` and update the fallback domain in DEFAULT_DOMAINS when the current one stops working.

---

## 4. Bridge & CDN Reference (All Known Services)

### 4.1 Nexdrive (`nexdrive.fit` / `nexdrive.beer`)
- **Used by:** Vegamovies, RogMovies
- **Pattern:** `https://nexdrive.fit/genxfm/<TOKEN>`
- **Contains:** Multiple download buttons (FastDL, VCloud, HubCloud, VegaDrive, PixelDrain, FilePress)
- **Unwrapper:** `unwrap_nexdrive()` in fast_fetch.py

### 4.2 FastDL (`fastdl.beer`)
- **Chain:** `embed.php?download=<ID>` → JS `var reurl="https://fastdl.beer/dl.php?link=<GOOGLE_CDN_URL>"`
- **Final CDN:** `video-downloads.googleusercontent.com/...`
- **Token life:** ~6-12 hours

### 4.3 VCloud (`vcloud.beer`)
- **Chain:** `/<ID>` → double Base64 decode → token URL → FSL (Cloudflare R2) or HubCloud
- **Final CDN:** `pub-XXXX.r2.dev/<hash>?token=...` (HTTP 206 resumable)
- **Decode:** `base64.b64decode(base64.b64decode(token)).decode('utf-8')`

### 4.4 HubCloud (`hubcloud.ist`)
- **Pattern 1:** `hubcloud.ist/drive/<ID>` → `gamerxyt.com/hubcloud.php` → Cloudflare R2
- **Pattern 2:** `gpdl2.hubcloud.ist/?id=<ID>` → `gamerxyt.com/dl.php?link=<GOOGLE_CDN>`
- **Unwrapper:** `unwrap_hubcloud_drive()` in fast_fetch.py
- **Expired:** Returns HTTP 400 with `"404 !.."` body

### 4.5 PixelDrain (`pixeldrain.com`)
- **Pattern:** `/u/<FILE_ID>` or `/d/<FILE_ID>`
- **Direct API:** `https://pixeldrain.com/api/file/<FILE_ID>` (HTTP 206, no ads)
- **Regex:** `r'/(?:u|d|api/file)/([A-Za-z0-9_-]+)'`
- **Unwrapper:** `unwrap_pixeldrain()` in fast_fetch.py

### 4.6 VegaDrive (`one.vegadrive.me`)
- **Pattern:** `/s/<ID>` → maps to `/d/<ID>/skyd` (10Gbps direct)
- **Old domain:** `one.vegadrive.app` (redirect tracked)

### 4.7 FilePress (`new1.filepress.lat`)
- **Pattern:** `/file/<ID>` → Google Drive proxy
- **Known mirrors:** `new1`, `new26`, `new30`...

### 4.8 MobileJSR (`mobilejsr.com`)
- **Used by:** 7StarHD, 10xflix
- **Pattern:** `mobilejsr.com/view/<ID>` → iframe `mobilejsr.com/embed/<ID>`
- **Status:** Stored as-is (stable persistent URL, no JS needed to store)

### 4.9 LinksZilla (`secure.linkszilla.top`)
- **Used by:** SSRMovies
- **Pattern:** `/view/<ID>` → page with buttons to HubCloud, GDFlix, Direct-Cloud
- **Unwrapper:** `unwrap_linkszilla()` in fast_fetch.py

### 4.10 GDFlix (`new5.gdflix.io`)
- **Pattern:** `/file/<ID>` → Google Drive streaming proxy

### 4.11 Direct-Cloud (`dl.direct-cloud.top`)
- **Pattern:** `/d/<ID>` → HTTP 302 → `storage.direct-cloud.org/d/<HASH>`

### 4.12 greenmotors.cc (`greenmotors.club`)
- **Used by:** HDHub4u
- **Pattern:** `/?id=<BASE64_ENCODED_PAYLOAD>`
- **Status:** JS-rendered only — stored as bridge URL, not resolved further

### 4.13 10moviesz.mom
- **Used by:** BollyShares
- **Pattern:** `/?id=<SHORT_ID>` → redirect to HubCloud/PixelDrain
- **Status:** Stored as bridge URL

### 4.14 FilmyZilla /server/ pages
- **Used by:** FilmyZilla
- **Pattern:** `/server/<numeric_id>/<filename>.html` — each is a quality variant page
- **Contains:** Embedded player or direct download link

### 4.15 Other CDN mirrors (auto-captured)
- **DropGalaxy:** `dropgalaxy.vip/<ID>`
- **Gofile:** `gofile.io/d/<ID>`
- **1fichier:** `1fichier.com/?<ID>`
- **MegaUp:** `megaup.mobi/#<ID>`
- **VikingFile:** `vikingfile.com/<ID>`
- **Firebase:** `firebasestorage.googleapis.com/v0/b/<BUCKET>/o/<PATH>?alt=media&token=<TOKEN>`
- **Cloudflare Workers:** `dl.<worker>.workers.dev/0:/<FILE>.mkv`

---

## 5. Cinemeta API (Free Metadata Enrichment)

No API key needed. Called automatically in `save_scraped_data()` if rating/poster/genres missing.

```
Movie search:
GET https://v3-cinemeta.strem.io/catalog/movie/top/search=<TITLE>.json
→ { "metas": [{"id": "tt...", "name": "...", "poster": "...", "imdbRating": "7.5", "genres": [...]}] }

Series search:
GET https://v3-cinemeta.strem.io/catalog/series/top/search=<TITLE>.json
→ same structure

By IMDb ID:
GET https://v3-cinemeta.strem.io/meta/movie/tt1234567.json
→ { "meta": {"poster": "...", "background": "...", "description": "...", "genres": [...]} }
```

---

## 6. Critical Rules — NEVER Violate

1. **No pip installs** — only stdlib: `urllib`, `sqlite3`, `re`, `json`, `ssl`, `base64`, `pathlib`, `concurrent.futures`, `argparse`, `html`, `time`, `os`, `sys`
2. **18+ content: store flagged, never display** — scrapers ingest all titles including adult, setting `is_18_plus=1` in every site staging DB; REST API, dashboard, M3U/stream routes, and the Android app must always filter `is_18_plus=1` out
3. **Safe media identity** — prefer matching IMDb/TMDB IDs, then a previously indexed site URL, then a unique title/year key of the same content type. Refuse ambiguous matches and conflicting IDs; `canonical_key` is indexed but deliberately not unique.
4. **Verify import after EVERY edit:**
   ```bash
   python -c "import fast_fetch; print('OK')"
   ```
5. **Regex with quotes** — ALWAYS use triple-quoted raw strings to avoid escaping hell:
   ```python
   # CORRECT:
   links = re.findall(r"""href=["'](https?://example\.com/[^"'<>\s]+)["']""", html)
   # WRONG (causes SyntaxError):
   links = re.findall(r'href=[\"\\'](https?://...)[\"\\']', html)
   ```
6. **Generated dumps stay off the repo** — `fast_fetch.py export` and `export-html` write **full ledger rows** (site names, hoster names, resource ids, final URLs). Both outputs are gitignored and belong on the operator's disk only; never re-add `database_view.html` or `fast_fetch_export.*` to git. To inspect one, generate it to `/tmp` from the populated DB:
   ```bash
   python3 -S fast_fetch.py export-html --output /tmp/database_view.html
   ```
7. **DB path is relative** — `BASE_DIR / "fast_fetch.db"` — never hardcode absolute Windows paths
8. **Test database changes offline** — run `python -S test_database.py` and `python -S test_vidout.py` from `Fast_Fetch/`.
9. **Test on live URL** after adding any new extractor:
   ```bash
   python fast_fetch.py fetch "https://newsite.com/post-slug/"
   ```
10. **Provenance stops at the HTTP edge** — `Fast_Fetch/redact.py` is the only thing between
    the ledger and a client. A new column is invisible until it is *deliberately published* in a
    `VIEWS` allowlist; a display string goes through `scrub_text()`; a playable, an artwork and
    a download are addressed by a signed `stream_id` handle, never a row id or an upstream URL.
    The operator's own view (raw `source_site`, `service`, `final_url`, `/api/v1/rules`,
    `/api/data`) is served on the loopback port `RADD_INTERNAL_PORT` (default `127.0.0.1:8081`)
    and `404`s on the public port. Rules of the road:
    - **Never** add a provenance key to a public emitter (`dict(row)`, `SELECT *` into JSON) —
      project it, or add it to `VIEWS` with a comment saying why a client needs it;
    - **Never** redact stored data — the ledger keeps everything (Zero Data Loss rule); redaction
      is a serialization decision at the edge, and tests assert the row is still intact;
    - after any API-shape change run `python3 -S -m unittest test_redact` **and** the real-data
      sweep: `python3 -S Fast_Fetch/sweep_public_edge.py --db /path/to/catalog_snapshot.db --probe`
      (it boots the server on a snapshot and asserts no site, no hoster, no upstream host and no
      provenance key reaches the public port, while the operator port still answers with all of
      it). `API_V2.md` §16.9 is the contract this enforces.

---

## 7. How to Add a New Site (8-Step Pattern)

### Step 1 — DEFAULT_DOMAINS (`line ~48`)
```python
"newsite": "https://newsite.com",
"newsite_sitemap": "https://newsite.com/sitemap.xml",
```

### Step 2 — SITE_CANDIDATE_TLDS (`line ~78`)
```python
"newsite": ["com", "net", "xyz", "top", "vip"],
```

### Step 3 — normalize_url() (`line ~155`)
```python
if "newsite" in host:
    active = DOMAINS.get("newsite", "https://newsite.com")
    active_host = urllib.parse.urlparse(active).netloc.lower()
    if host != active_host:
        return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))
```

### Step 4 — sync_sitemaps() block (before final `if verbose: print("Global sync")`)
```python
if site in ("newsite", "all"):
    if verbose:
        print(f"\n[i] Fetching sitemap for NEWSITE")
    try:
        c, _, xml = http_get("https://newsite.com/sitemap.xml")
        records = []
        if c == 200:
            for loc_m in re.finditer(r"<loc>(https?://newsite[^<]+)</loc>", xml):
                loc = loc_m.group(1).strip()
                slug = loc.rstrip("/").split("/")[-1]
                records.append((loc, "", slug, "newsite"))
        if records:
            with get_db() as conn:
                conn.executemany(
                    "INSERT INTO sitemap_cache (loc,lastmod,slug,scraped,site) VALUES(?,?,?,0,?) "
                    "ON CONFLICT(loc) DO UPDATE SET slug=excluded.slug,site=excluded.site",
                    records
                )
                total_added_global += len(records)
            if verbose:
                print(f"[✓] [NEWSITE] Cached {len(records)} posts")
    except Exception as e:
        if verbose:
            print(f"[!] Error: {e}")
```

### Step 5 — Extractor function
```python
def extract_post_data_newsite(post_url: str, html: str, verbose: bool = True) -> dict | None:
    slug = post_url.rstrip("/").split("/")[-1]
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    raw_title = title_m.group(1).strip() if title_m else slug
    # ... parse year, clean_title, canonical_key, poster_url ...
    # ... find bridge links using triple-quoted regex ...
    # ... build releases list ...
    return {
        "url": post_url, "slug": slug, "title": raw_title,
        "clean_title": clean_title, "year": year,
        "content_type": "movie", "seasons": None,
        "poster_url": poster_url, "backdrop_urls": None,
        "imdb_rating": None, "genres": None, "synopsis": None,
        "is_18_plus": 0, "is_animated": 0,
        "source_site": "newsite",
        "industry": cls_meta["industry"],
        "country": cls_meta["country"],
        "language": cls_meta["language"],
        "canonical_key": canonical_key,
        "releases": releases,
    }
```

### Step 6 — Dispatcher in extract_post_data()
```python
if "newsite" in f_lower:
    return extract_post_data_newsite(final_url, html, verbose)
```

### Step 7 — SITE_CHOICES / SITE_INDIVIDUAL (`line ~3305`)
```python
SITE_CHOICES = [..., "newsite", "all"]
SITE_INDIVIDUAL = [..., "newsite"]
```

### Step 8 — viewer.py badge + filter pill
- CSS: `.badge-ns { background: #color; color: #fff; }`
- Filter pill in Tab 1 and Tab 2 HTML
- `renderPosts` filter branch
- `siteBadgeClass` mapping
- Run: `python fast_fetch.py export-html`

---

## 8. Domain Self-Healing Mechanism

When a site changes domain (happens every 1-3 months):

1. `http_get()` follows 301/302 redirects — `final_url` captures the new domain
2. `normalize_url()` rewrites stored old-domain URLs to current before fetch
3. `harvest_sister_domains()` scrapes nav links — captures new domains from cross-links
4. `probe_candidate_domains()` tries known TLD variants if site goes dark
5. Manual override: `python fast_fetch.py set-domain vegamovies https://vegamovies.newdomain.com`
6. Batch migration: `python fast_fetch.py domain migrate oldhost.com newhost.com`

**TLD rotation patterns (known):**
- Vegamovies: `.gallery` → `.yt` → `.one` → `.im` → `.vip` → `.beer`
- RogMovies: `.wtf` → `.one` → `.vip` → `.club`
- SSRMovies: `.games` → `.gripe` → `.monster` → `.club`
- FilmyZilla: `71` → `73` → `74` → `75`... (numeric increment)
- HDHub4u: `new1` → `new2` → `new3`... (numeric `new#` prefix)

---

## 9. Database Tables (Implemented Schema)

`fast_fetch.py` is the source of truth for the SQLite schema and migrations.
The live database uses `posts`, `post_sources`, `releases`, `download_sources`,
`sitemap_cache`, and `domains_config`. It does not use the conceptual
`media_entities` or `source_urls` tables shown in earlier notes.

- `posts` holds shared title metadata and external IDs. Its `canonical_key` is
  indexed, not unique; title/year alone is not enough to force a merge.
- `post_sources` maps each `(source_site, URL)` to a `posts.id`, retaining the
  original site page URL, site-specific title and slug, and seen timestamps.
- `releases` belongs to a `posts.id` and carries its own `source_site` plus
  `origin_url` — the page that produced it. Releases are replaced per page, never
  per site, because one title can be published across several pages of the same
  site (a season page and an episode-pack page). Replacing per site silently
  deleted the earlier page's releases.
- `download_sources` belongs to a release and stores its source/health fields.
- `sitemap_cache` records discovery and crawl status; a successful scrape also
  creates a `post_sources` mapping.

Identity resolution prefers a matching IMDb/TMDB ID, then a previously
associated site URL, then a single title/year key of the same media type.
Conflicting IDs, URL mappings, or multiple canonical candidates fail explicitly
instead of picking the oldest database row. See `DATABASE_SCHEMA.md` for the
full schema and indexes.

### 9b. Catalog v2 (design approved, implementation in progress)

`Fast_Fetch/API_V2.md` is the contract for the next layer: a `cat_*` projection over
this ledger (works / seasons / episodes / releases-prints / links / tracks / evidence /
entitlements) plus the v2 REST surface the Android app and a future website will consume.
Read it before designing any new endpoint. Rules of thumb already settled there:
the ledger is append-only and never hand-edited, the projection is disposable and
rebuildable, movie/series never cross-merge, print quality and link playability are two
separate scores, and adult rows are stored but return 404 on every presentation surface.

---

## 10. Current Status & Stats

### Unified catalog — measured 2026-10-29 on the live host

The previous version of this table described the 2026-10-13 seed database
(51 titles, 1,662 releases, 4,351 sources). That is not the catalog any more, and
quoting it makes an agent plan work that is already done.

| Metric | Value |
|--------|-------|
| `posts` (ledger rows) | 146,176 |
| — of which `is_18_plus = 1` (stored, never displayed) | 14,617 |
| — displayable to a public caller | 131,559 |
| `releases` | 1,764,686 |
| `download_sources` | 4,044,659 |
| `post_sources` (per-site page links) | 300,013 |
| Distinct `source_site` | 28 → **31** with the third merge batch |
| Staging databases merged | 2 batches + `merged_catalog_20261025.db` in place |
| Third merge batch, landing 2026-10-29 | pagalmovies, filmyhit, filmywap |

**Link liveness is not a count of `status = 'active'`.** Every ingested row is
written `active` by the scraper, so before `link_state.propagate()` has knocked on
an endpoint, `status` proves nothing. `/api/v1/stats` now publishes
`sources_by_state` alongside the totals, and `active_sources` counts only links
with measured evidence behind them — a freshly merged catalog honestly reports
`active_sources: 0` with the whole population under `unchecked`.

### Sitemap breakdown — 2026-10-13 crawl state (superseded)

Kept for history. The current per-site queue is in `sitemap_cache` in the live
database, and in `SITES.md` §15; read it there rather than trusting this table.

| Site | URLs (Oct 13) |
|------|------|
| Vegamovies | 14,025 |
| FilmyZilla | 5,002 |
| RogMovies | 2,000 |
| HDHub4u | 1,000 |
| BollyShares | 200 |
| 7StarHD | 28 |
| SSRMovies, KatMovieHD, 10xflix, MultiMovies | via API/live fetch |

---

## 11. Session History (Append Here)

### Session 1-3 — Antigravity (Claude Sonnet) — Oct 2026
**Built:**
- Full engine from scratch: `fast_fetch.py` (3,907 lines)
- Sites 1-5: Vegamovies, RogMovies, SSRMovies, KatMovieHD, 7StarHD
- SSL context fix (global permissive context — bypasses all CDN cert issues)
- Cinemeta API enrichment (auto-fires in save_scraped_data)
- HTML viewer: viewer.py + database_view.html
- Sites 6-10: 10xflix, MultiMovies, HDHub4u, BollyShares, FilmyZilla
- All sync blocks added (sync_sitemaps)
- Fixed all regex escaping bugs (triple-quoted raw strings rule established)
- DEFAULT_DOMAINS, normalize_url, SITE_CHOICES all updated
- GitHub repo created: https://github.com/radddao/radd-stream
- Core files uploaded to GitHub via Python Contents API (no git needed)
- Created: AGENTS.md, README.md, SITES.md, SETUP.md, config.py, run.sh, run.bat, .replit, setup_check.py, requirements.txt
- Chat history exported (1,582 messages → CHAT_HISTORY.md)

**Verified live:**
- HDHub4u fetch: Papa's Friend S1 ✅ — greenmotors bridge + Cinemeta
- MultiMovies fetch: Pathaan ✅ — watchConfig servers + Cinemeta
- 10xflix fetch: Moonfall ✅ — MobileJSR + Cinemeta
- All 3 new sync blocks: HDHub4u (1,000), BollyShares (200), FilmyZilla (5,002)

---

## 12. TODO — Next Steps

### High Priority
- [ ] Add `watch-movies.com.pk` — Cloudflare JS challenge, needs special User-Agent + cookie headers
- [ ] Add `hdmoviesbd.xyz` — NXDOMAIN, find current mirror domain
- [ ] Add paginated HDHub4u category crawl (has `/category/` pages with 100s of posts each)
- [ ] Implement `greenmotors.cc` JS resolver (headless or regex-based decode of base64 payload)
- [ ] Implement `10moviesz.mom` resolver (follow redirect chain to final HubCloud/PixelDrain)

### Medium Priority
- [ ] Add more sites: filmywap, filmyhit, mp4moviez, world4ufree, bolly4u
- [ ] Build simple HTTP API server (stdlib `http.server`) over SQLite — `/api/search?q=...`, `/api/movie/<id>`
- [ ] Add auto-crawl scheduler (run `crawl` on a cron via `schedule` stdlib or external cron)
- [ ] Implement `heal --all` to batch re-resolve all expired/dead sources

### Low Priority
- [ ] Add M3U playlist export (`python fast_fetch.py export m3u`)
- [ ] Add Stremio addon interface (CORS-enabled HTTP server on port 7000)
- [ ] Add poster download/cache to local `posters/` folder
- [ ] Build a Telegram bot frontend for search/fetch commands

---

## 13. Platform-Specific Notes

### Windows
- UTF-8 console output is fixed at import (`sys.stdout.reconfigure`)
- Path separators use `pathlib.Path` — works on both `\` and `/`
- Use `run.bat` for one-command launch

### Linux / Ubuntu VPS / Oracle Cloud
For the actual Oracle host, secret-safe SSH/GitHub instructions, and the
domainless HTTP deployment plan, read
[`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md) before connecting or
changing the server.

- Current Oracle account: `ubuntu@92.4.95.252`, SSH port 22.
- Last verified host: Ubuntu 24.04.4, Python 3.12.3, non-interactive `sudo`
  available; no Python packages or Docker are required.
- Intended public URL is `http://92.4.95.252/`; it has no TLS. Do not send
  credentials over it or use it as a release Android endpoint.
- The backend defaults to `0.0.0.0` and has unauthenticated routes. For Oracle,
  start it with `serve --host 127.0.0.1 --port 8080`; never expose port 8080
  directly. Follow the runbook's public-route restrictions before enabling Nginx.
- Keep the SQLite database outside the Git checkout and out of Git. The prior
  database backup was deleted; a new catalog must be populated after deployment.

### Replit
- `.replit` file configures auto-run and port
- DB is stored at `/home/runner/radd-stream/Fast_Fetch/fast_fetch.db`
- Set `RADD_DB_PATH` env var in Replit Secrets if needed
- The HTML viewer can be served via Replit's built-in web server

### GitHub Codespace
- Python 3.11+ pre-installed
- `bash run.sh sync --site all` works immediately after clone
- Port 8080 auto-forwarded for HTML viewer if needed

---

## 14. Important Warnings for Future Agents

1. **`fast_fetch.db` is gitignored** — start fresh on new machines, run `sync` first
2. **Domain rotations happen every 1-3 months** — if a site returns 403, check and update DEFAULT_DOMAINS
3. **greenmotors.cc needs JS** — don't try to resolve these with urllib, store as-is
4. **HTML viewer is 7.8MB** — large because it embeds all DB data as JSON. Normal.
5. **Never `import requests`** — use `urllib.request` only
6. **Line numbers shift** — the architecture comments in this file show approximate line numbers that drift as code grows. Use `grep` or search to find actual locations.
7. **Unicode in print()** — always use `sys.stdout.write()` or ensure UTF-8 reconfigure when printing emojis on Windows
8. **Oracle/GitHub access** — use the secret-safe procedures in `../ORACLE_DEPLOYMENT.md`; never print, commit, or copy `GITHUB_TOKEN` or `ORACLE_SSH_KEY`
9. **Public API exposure** — the current HTTP API has no authentication and wildcard CORS; secure or restrict fetch/heal/resolve routes before proxying them publicly
