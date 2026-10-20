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
| `/api/v1/posts` | `GET` | `q` (search query), `type` (movie/series/anime), `page`, `limit` | Paginated catalog search and discovery. Returns clean metadata, posters, IMDb ratings, and counts. |
| `/api/v1/posts/{id}` | `GET` | None | Full detail for a single media title: all release variants (480p, 720p, 1080p, 4K), seasons, episodes, and direct sources ordered by priority tier. |
| `/api/v1/stream` | `GET` | `id` (source ID, required), `redirect` (`1` or `0`) | Just-in-Time (JIT) stream resolver. When `redirect=1` (default), returns **HTTP 302 Found** directly to the live, unexpired video stream for native player playback. When `redirect=0`, returns JSON with refreshed token metadata. |
| `/api/v1/rules` | `GET` | None | Remote regex and extraction rules for client-side IP unwrapping (Android device IP). |
| `/api/v1/stats` | `GET` | None | Live system metrics: total posts, releases, sources, active links, and resumable streams. |
| `/client` | `GET` | None | Built-in touch-optimized mobile web client (PWA ready). |

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
        val q = URLEncoder.encode(query, "UTF-8")
        val t = URLEncoder.encode(type, "UTF-8")
        val url = "$baseUrl/api/v1/posts?q=$q&type=$t&page=$page&limit=$limit"
        return httpGetJson(url)
    }

    fun getPostDetail(postId: Int): JSONObject {
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
