# moved verbatim out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

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

