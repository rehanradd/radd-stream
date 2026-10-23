# 📱 Android Client Integration & Architecture Guide

> Complete technical guide for integrating native Android applications, mobile web clients, and third-party media players (ExoPlayer, VLC, MPV, MX Player) with the `radd-stream` REST API backend.

---

## 1. System Architecture

```
┌────────────────────────────────────────────────────────┐
│               Native Android Client App                │
│         (Kotlin / ExoPlayer / Media3 / VLC)            │
└───────────────▲────────────────────────▲───────────────┘
                │                        │
       1. REST Metadata           2. JIT Stream URL
       (/api/v1/posts)          (/api/v1/stream?id=X)
                │                        │
┌───────────────▼────────────────────────▼───────────────┐
│               radd-stream API Server                   │
│                    (viewer.py)                         │
└───────────────┬────────────────────────┬───────────────┘
                │                        │
        3. Local DB Index       4. JIT Unwrapper
        (fast_fetch.db)       (fast_fetch.resolve_live)
                                         │
                                         ▼
                            HTTP 302 Redirect Location
                                         │
                        ┌────────────────▼───────────────┐
                        │        Edge CDN Servers        │
                        │ • Google CDN (206 Partial)     │
                        │ • Cloudflare R2 (fsl_r2)       │
                        │ • PixelDrain API (/api/file/)  │
                        │ • HubCloud 10Gbps Skyd         │
                        └────────────────────────────────┘
```

---

## 2. Core REST API Endpoints for Mobile Clients

| Endpoint | Method | Query Parameters | Description |
| :--- | :--- | :--- | :--- |
| `/api/v1/posts` | `GET` | `q` (search query), `type` (`movie` / `series` / `complete_season` / `ongoing_season`), `page`, `limit` | Paginated catalog search and discovery. Returns clean metadata, posters, IMDb ratings, and counts. |
| `/api/v1/posts/{id}` | `GET` | None | Full detail for a single media title, wrapped as `{"success": true, "data": {...}}`. Releases come back in plain `id ASC` order — they are **not** sorted by quality tier and there is **no** season/episode grouping. The tier ordering applies only to the `sources` array inside each release. |
| `/api/v1/stream` | `GET` | `id` (a **signed handle** we mint, required), `redirect` (`1` or `0`) | Just-in-Time (JIT) stream resolver. When `redirect=1` (default), returns **HTTP 302 Found** directly to the live, unexpired video stream for native player playback. When `redirect=0`, returns JSON with refreshed token metadata — and no URL. A raw database row id is rejected with `400`. |
| `/api/v1/rules` | `GET` | None | ~~Remote regex and extraction rules for client-side unwrapping~~ **operator port only.** It is `404` on the public base URL: it names every hoster endpoint we unwrap, so serving it publicly hands a third party our whole resolution stack. Unwrapping is server-side, see §5. |
| `/api/v1/stats` | `GET` | None | Live system metrics: total posts, releases, sources, active links, and resumable streams. Scale only — no per-site breakdown. |
| `/api/m3u` | `GET` | `id` (post ID) | `audio/x-mpegurl` playlist download for the post's non-dead sources, ordered `is_resumable DESC, id ASC` (viewer.py:185-207) — a **different** ordering from the API detail route. Empty body for an adult-flagged or unknown id. Every entry is `http://<our-host>/api/v1/stream?id=<handle>`. |
| `/client` | `GET` | None | Built-in touch-optimized mobile web client (PWA ready). |

> 🔇 **Provenance never crosses the public edge** (`Fast_Fetch/redact.py`, API_V2.md §16.9).
> No public response carries a source-site name, a hoster/service name, an upstream page URL
> or a raw playable URL; artwork and streams are addressed by our own opaque handles. The app
> must not try to reconstruct or display what it no longer receives — the `label` fields on a
> release and on a link (§2, detail shape) are what the UI is built from. The ledger keeps all
> of it; `127.0.0.1:8081` serves it to the operator.

The remaining `GET` routes in `do_GET()` are dashboard/admin oriented, not client
integration points: `/api/data` (the full catalog dump — **operator port only**, it would
be a clone of the collection in one request), `/api/sitemap`, `/api/fetch`,
`/api/health-check`, `/`, `/index.html`, `/mobile`, `/favicon.ico`. There is **no
`/api/v1/sync`** and no `POST` handler at all.

> ⚠️ **Reality (verified against viewer.py 2026-10-22)** — three things in this
> section used to be wrong, and they cost people afternoons:
>
> 1. **There is no `?type=anime`.** `api_v1_get_posts()` (viewer.py:1897-1899)
>    filters with `p.content_type = ?` — exact string equality. No writer in the
>    codebase ever stores `'anime'` in `content_type`: `classify_media()`
>    (fast_fetch.py:1613-1622) only ever produces `movie`, `series`,
>    `complete_season`, or `ongoing_season`. So `?type=anime` returns
>    `{"total": 0, "results": []}` — an empty grid, not an error.
>    Anime is expressed through the separate `posts.is_animated` and
>    `posts.industry` columns, and **neither is exposed as a query parameter on
>    this API yet**. The dashboard's "Anime" pill works only because it filters
>    the already-downloaded payload in browser JS (viewer.py:1051-1052), not
>    because the REST route supports it. Adding a real anime filter requires a
>    backend change (an `animated=1` flag parameter) plus populating
>    `is_animated` in every scraper — today only `import_ssrmovies.py:470` sets
>    it. Until then, do not add an Anime chip to any client.
> 2. **`/api/v1/posts/{id}` does not order or group releases.**
>    `api_v1_get_post_detail()` (viewer.py:1942) runs
>    `SELECT * FROM releases WHERE post_id = ? ORDER BY id ASC` — insertion order
>    only, no quality sort, no season/episode grouping. Clients must group by
>    `season` / `episode` themselves.
> 3. **The priority tier ordering applies to sources within a release**
>    (viewer.py:1946-1961), in this exact order: `status = 'active'` first, then
>    `is_temporary ASC`, then a `CASE service` of `pixeldrain` (1), `vegadrive`
>    (2), `hubcloud_10g` (3), `fsl_r2` (4), `fastdl` (5), `google_cdn` (6),
>    everything else (99). Note the CASE matches those **exact literal strings**:
>    staging rows commonly carry host-derived names such as `fastdl-beer`,
>    `vcloud-beer`, or `hubcloud-ist`, which all fall through to `99` and so keep
>    arbitrary relative order. Verify the `service` values your scraper writes
>    before relying on tier ordering.

### Detail-response shape actually returned by `/api/v1/posts/{id}`

On the **public** port the `data` object is a projected view (`redact.VIEWS`), not the
row — a column is invisible until it is deliberately published:

```
post:  id, title, clean_title, year, content_type, seasons, imdb_rating, imdb_id,
       tmdb_id, genres, synopsis, is_animated, industry, country, language,
       poster_url, backdrop_urls        ← always our own /api/v1/art handle
     + releases: [{id, post_id, release_title, season, episode, quality, codec,
                   size, languages, label}]        ← "1080p WEB-DL · H.265 · Hindi 5.1"
       sources: [{stream_id, play_url, label, release_id, status,
                  is_temporary, is_resumable, http_status, file_size_bytes,
                  mime_type}]
```
(`kind`/`tier`/`protocol`/`rank_score`/`latency_ms`/`speed_mbps` exist on the v2 link
view, `catalog_api._link_view`, not on this v1 row — same rule, more fields.)

What is **not** in a public response, on any route: `source_site`, `source_name`,
`service`, `resource_id`, `url`, `slug`, `page_url`, `origin_url`, `intermediate_url`,
`final_url`, `source_pages`, `is_18_plus`. `stream_id` is a signed opaque handle — it is
not the row id and cannot be walked (`/api/v1/stream?id=<raw row id>` → `400`). The same
detail request on the operator port (`127.0.0.1:8081`) returns the raw ledger rows with
every one of those fields, because healing and diagnostics need them.

Adult-flagged titles return `404 {"success": false, "error": "Post not found"}`,
never a body. The same answer applies to an adult title's artwork handle and to an
adult link's stream handle (`/api/v1/stream` → `404`), and to `/api/m3u`, where
`generate_m3u_playlist()` returns an empty string for a flagged post. Hidden, not deleted.

`/api/heal?id={post_id}` is **operator-port only and still unusable over HTTP**: the
handler builds `resp_payload` and never writes it to the socket, so an HTTP/1.1 client
waits for a response that never arrives. Call `fast_fetch.heal_post_links()` from
Python instead.

### Stream resolver response fields

`/api/v1/stream` with `redirect=1` (the default) emits a bare `302` with
`Location` plus `Access-Control-Allow-Origin: *` and `Connection: close`, and no
body — that `Location` is the one and only place an upstream host appears, and it is
the player's business, not the UI's. With `redirect=0` on the **public** port the
answer is the handle's own descriptor, never a target:

```json
{"success": true, "stream_id": "kQ3q…", "kind": "url", "mime_type": "video/mp4",
 "file_size_bytes": 2405181686, "resumable": true, "expires_in": 21600}
```

`url`, `service` and `source_name` are no longer in it (they are on the operator port,
which answers with `resolve_live_source()`'s full dict). A failed resolution returns
`{"success": false, "error": ...}` with HTTP `404`, and so does a handle for a hidden
(18+) link — `redact.link_is_adult()` — so a hidden title cannot be played by guessing
an address.

### Security posture — as much as a stdlib HTTP-only box can have

There is still **no authentication**: no API key, no bearer token, no session. What has
changed is that the public port no longer answers with anything worth scraping whole:

- every response is a projection (`redact.project`), so provenance fields are absent by
  construction rather than by luck (§2 above);
- playables, artwork and streams are addressed by signed opaque handles; a raw row id is
  rejected (`400`), so 3.07 M links cannot be walked;
- `IETF RateLimit-*` + `Retry-After` headers on every response — buckets `browse`
  60/min, `play` 30/min, `reports` 10/min;
- the whole-catalog dump (`/api/data`), the bridge table (`/api/v1/rules`), the sitemap
  feed, `/api/fetch`, `/api/heal`, `/api/health-check` are **operator-port only** —
  `404` on the public port;
- the operator port is a second bind on `127.0.0.1` (`RADD_INTERNAL_PORT`, default 8081).
  Policy hangs on the *port*, because a request can forge a header but not a port.

`send_json()` still stamps `Access-Control-Allow-Origin: *` (viewer.py), `start_server()`
still defaults to `0.0.0.0`, and the Oracle host serves plain HTTP with no TLS. Treat
everything the public port does return as public to anyone who can reach it — which is
now exactly what a user sees, plus nothing that names where it came from. Never put
credentials or personal data behind this API.


---

## 3. Native Android Player Integration (ExoPlayer / Media3)

### 3.1 Handling HTTP 302 Redirects Automatically
`ExoPlayer` / `AndroidX Media3` natively supports HTTP 302 redirects when configured with `DefaultHttpDataSource.Factory`:

```kotlin
// ExoPlayerStreamHelper.kt
package com.radd.stream

import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory

class ExoPlayerStreamHelper(private val context: Context) {

    fun buildPlayerForSource(serverBaseUrl: String, sourceId: Int): ExoPlayer {
        // Point directly to JIT stream resolver endpoint with redirect=1
        val streamUrl = "$serverBaseUrl/api/v1/stream?id=$sourceId&redirect=1"

        // Permissive HTTP data source with redirect following and Range header support
        val httpDataSourceFactory = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15000)
            .setReadTimeoutMs(15000)
            .setUserAgent("radd-stream-android/1.0")

        val mediaSourceFactory = DefaultMediaSourceFactory(context)
            .setDataSourceFactory(httpDataSourceFactory)

        val player = ExoPlayer.Builder(context)
            .setMediaSourceFactory(mediaSourceFactory)
            .build()

        val mediaItem = MediaItem.Builder()
            .setUri(streamUrl)
            .build()

        player.setMediaItem(mediaItem)
        player.prepare()
        return player
    }
}
```

---

## 4. Launching External Native Players via Android Intents

For power users who prefer VLC, MPV, or MX Player on their phone or Android TV box, Android `Intent` allows launching the stream URL directly:

```kotlin
// ExternalPlayerLauncher.kt
package com.radd.stream

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast

object ExternalPlayerLauncher {

    fun launchVlc(context: Context, streamUrl: String, title: String) {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(streamUrl), "video/*")
            setPackage("org.videolan.vlc")
            putExtra("title", title)
            putExtra("from_start", false)
            putExtra("position", 0)
        }
        tryLaunch(context, intent, "VLC Player not installed")
    }

    fun launchMpv(context: Context, streamUrl: String) {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(streamUrl), "video/*")
            setPackage("is.xyz.mpv")
        }
        tryLaunch(context, intent, "MPV Player not installed")
    }

    fun launchMxPlayer(context: Context, streamUrl: String, title: String) {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(streamUrl), "video/*")
            setPackage("com.mxtech.videoplayer.ad")
            putExtra("title", title)
        }
        tryLaunch(context, intent, "MX Player not installed")
    }

    private fun tryLaunch(context: Context, intent: Intent, fallbackMsg: String) {
        try {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(context, fallbackMsg, Toast.LENGTH_SHORT).show()
            // Fallback to chooser
            val chooser = Intent.createChooser(intent, "Play with...")
            chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(chooser)
        }
    }
}
```

---

## 5. Resolution Is Server-Side — the Client Never Unwraps a Hoster

Some CDN edge nodes bind a generated streaming token to the client IP (Cloudflare R2,
Google CDN), which is why this used to be a client feature: `GET /api/v1/rules` handed the
app a regex and an endpoint per hoster, and the device did the unwrapping itself.

**That contract is withdrawn from the public API.** The rules document names every hoster
endpoint we know how to unwrap — publishing it meant any third party could rebuild both our
catalog *and* our resolution stack with two requests, which is exactly the reuse hole this
phase exists to close. `/api/v1/rules` is now served on the operator port only
(`127.0.0.1:8081`) and `404`s on the public port.

What replaces it, per link:

| Client wants | Client calls | Server does |
| :--- | :--- | :--- |
| to play | `GET /api/v1/stream?id=<handle>` | `fast_fetch.resolve_live_source()` unwraps the bridge, caches the result, and answers `302` with the live URL |
| to know what it is | the `label` on the release and on the link | quality/behaviour words only — "1080p WEB-DL · H.265 · Hindi 5.1", "Fast direct" |
| to diagnose a broken bridge | nothing, from a device | an operator reads `/api/v1/rules` and `resolve_live_source`'s log on the box |

Two honest caveats, because the IP-binding problem was real:

- A hoster that binds its token to the *requesting IP* can produce a URL the server resolved
  but the device cannot replay. That is a per-source property, not a client bug; the player's
  failover ladder moves to the next candidate for the same print
  (`App/.../player/RenditionFailover.kt`), and the reason it shows is a state, never a hoster.
- Removing client-side unwrapping does not remove any playable source. Every source still has
  a server-side path, and one that genuinely only ever resolves to an archive or an embed page
  is offered as **Download only** rather than as a player surface.

Do **not** reintroduce a device-side rule fetch, and do not cache or persist an upstream URL
in a public payload — the one place an upstream host may appear is the `Location` of the
`302` the player follows.

---

## 6. Zero-Dependency API Client Implementation (Pure Kotlin)

```kotlin
// RaddStreamClient.kt
package com.radd.stream

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class RaddStreamClient(private val baseUrl: String) {

    fun searchPosts(query: String = "", type: String = "", page: Int = 1, limit: Int = 20): JSONObject {
        // `type` must be exactly one of: movie | series | complete_season | ongoing_season.
        // Anything else (including "anime") matches zero rows — see section 2.
        // Send `type` only when non-empty, or omit it entirely.
        val q = URLEncoder.encode(query, "UTF-8")
        val t = URLEncoder.encode(type, "UTF-8")
        val url = "$baseUrl/api/v1/posts?q=$q&type=$t&page=$page&limit=$limit"
        return httpGetJson(url)
    }

    fun getPostDetail(postId: Int): JSONObject {
        // Response is nested: {"success": true, "data": {post..., source_pages[], releases[]}}
        val url = "$baseUrl/api/v1/posts/$postId"
        return httpGetJson(url)
    }

    fun getStats(): JSONObject {
        val url = "$baseUrl/api/v1/stats"
        return httpGetJson(url)
    }

    private fun httpGetJson(urlString: String): JSONObject {
        val url = URL(urlString)
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "GET"
        conn.connectTimeout = 8000
        conn.readTimeout = 8000
        conn.setRequestProperty("User-Agent", "radd-stream-client/1.0")

        return try {
            val reader = BufferedReader(InputStreamReader(conn.inputStream))
            val sb = StringBuilder()
            var line: String?
            while (reader.readLine().also { line = it } != null) {
                sb.append(line)
            }
            reader.close()
            JSONObject(sb.toString())
        } finally {
            conn.disconnect()
        }
    }
}
```
