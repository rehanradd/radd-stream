# moved verbatim out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

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

