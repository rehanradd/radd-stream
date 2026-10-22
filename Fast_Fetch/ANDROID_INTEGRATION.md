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
| `/api/v1/stream` | `GET` | `id` (source ID, required), `redirect` (`1` or `0`) | Just-in-Time (JIT) stream resolver. When `redirect=1` (default), returns **HTTP 302 Found** directly to the live, unexpired video stream for native player playback. When `redirect=0`, returns JSON with refreshed token metadata. |
| `/api/v1/rules` | `GET` | None | Remote regex and extraction rules for client-side IP unwrapping (Android device IP). |
| `/api/v1/stats` | `GET` | None | Live system metrics: total posts, releases, sources, active links, and resumable streams. |
| `/api/m3u` | `GET` | `id` (post ID) | `audio/x-mpegurl` playlist download for the post's non-dead sources, ordered `is_resumable DESC, id ASC` (viewer.py:185-207) — a **different** ordering from the API detail route. Empty body for an adult-flagged or unknown id. |
| `/client` | `GET` | None | Built-in touch-optimized mobile web client (PWA ready). |

The remaining `GET` routes in `do_GET()` are dashboard/admin oriented, not client
integration points: `/api/data`, `/api/sitemap`, `/api/fetch`,
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

The `data` object is the raw `posts` row plus two injected arrays
(viewer.py:1930-1965):

```
posts row: id, url, slug, title, clean_title, year, content_type, seasons,
           poster_url, backdrop_urls, imdb_rating, genres, synopsis,
           is_18_plus, is_animated, lastmod, created_at, updated_at,
           source_site, industry, country, language, canonical_key,
           tmdb_id, imdb_id
       + source_pages: [{source_site, url, source_title}]
       + releases:     [{id, post_id, release_title, season, episode, quality,
                         codec, size, languages, intermediate_url, created_at,
                         source_site, origin_url,
                         sources: [{id, release_id, source_name, service,
                                     resource_id, source_url, final_url,
                                     playback_type, is_temporary, status,
                                     is_resumable, http_status, file_size_bytes,
                                     mime_type, last_checked_at, created_at,
                                     updated_at}]}]
```

Adult-flagged titles return `404 {"success": false, "error": "Post not found"}`,
never a body. The same filter applies to `/api/m3u`, where
`generate_m3u_playlist()` returns an empty string for a flagged post
(viewer.py:185-189), and to source resolution.

`/api/heal?id={post_id}` is **routed but unusable**: the handler builds
`resp_payload` and never writes it to the socket (viewer.py:2100-2108), so an
HTTP/1.1 client waits for a response that never arrives. A missing or non-numeric
`id` also raises before any response is sent. Do not wire any client to this
route; call `fast_fetch.heal_post_links()` from Python instead.

### Stream resolver response fields

`/api/v1/stream` with `redirect=1` (the default) emits a bare `302` with
`Location` plus `Access-Control-Allow-Origin: *` and `Connection: close`, and no
body (viewer.py:2141-2147). With `redirect=0` it returns the
`resolve_live_source()` dict directly; the keys actually produced are
`success`, `id`, `url`, `cached`, `refreshed`, `service`, `is_temporary`,
`is_resumable`, `source_name`, `mime_type` — note `is_temporary` and
`is_resumable` are JSON **booleans**, and a failed resolution returns
`{"success": false, "error": ...}` with HTTP `404`.

### Security posture — there is none

Every route is **completely unauthenticated**:
there is no API key, no bearer token, no session, and no rate limiting anywhere
in `viewer.py`. `send_json()` stamps `Access-Control-Allow-Origin: *` on every
response (viewer.py:2037), and `start_server()` defaults to binding
`0.0.0.0` (viewer.py:2211). The Oracle host serves plain HTTP with no TLS.
Treat the catalog and every resolved stream URL as public to anyone who can
reach the port, and never put credentials or personal data behind this API.


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

## 5. Client-Side IP Unwrapping with Remote Rules

Certain CDN edge nodes bind generated streaming tokens to the client IP address (Cloudflare R2, Google CDN). While `radd-stream` performs server-side resolution, clients can also execute client-side extraction using rules from `GET /api/v1/rules`:

```json
{
  "version": "1.0",
  "name": "radd-stream-client-rules",
  "services": {
    "pixeldrain": {
      "pattern": "https://pixeldrain\\.com/u/([A-Za-z0-9_-]+)",
      "endpoint": "https://pixeldrain.com/api/file/{id}",
      "is_temporary": 0,
      "tier": 1
    },
    "vegadrive": {
      "pattern": "https://(?:one\\.)?vegadrive\\.(?:me|app)/(?:s|d)/([A-Za-z0-9_-]+)",
      "endpoint": "https://one.vegadrive.me/d/{id}/skyd",
      "is_temporary": 0,
      "tier": 1
    },
    "direct_cloud": {
      "pattern": "https://(?:dl\\.)?direct-cloud\\.(?:top|org)/d/([A-Za-z0-9_-]+)",
      "action_endpoint": "https://storage.direct-cloud.org/action",
      "action_type": "DOWNLOAD_GENERATE",
      "tier": 2,
      "is_temporary": 1
    },
    "greenmotors": {
      "pattern": "https://greenmotors\\.[a-z]+/\\?id=([A-Za-z0-9+/=_\\-]+)",
      "type": "multi_layer_b64_rot13",
      "tier": 2,
      "is_temporary": 0
    }
  }
}
```

### Client Execution Logic:
1. When downloading/streaming from a mobile device, fetch rules once and cache for 24 hours.
2. If `pattern` matches `pixeldrain.com/u/{id}`, construct `https://pixeldrain.com/api/file/{id}` directly on device.
3. If `pattern` matches `direct_cloud`, the device requests `https://storage.direct-cloud.org/action` with session cookies to bind the Google CDN token to the carrier's mobile IP.
4. Fall back to server JIT resolver `/api/v1/stream?id={id}&redirect=1` whenever client-side execution is unavailable.

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

    fun getRules(): JSONObject {
        val url = "$baseUrl/api/v1/rules"
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
