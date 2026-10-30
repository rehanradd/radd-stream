# moved verbatim out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

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

