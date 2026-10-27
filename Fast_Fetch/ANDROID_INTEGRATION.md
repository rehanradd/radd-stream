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
| `/api/v1/search/by-media` | `GET` | `q` (**required** — a title, or the fragment one remembers), `duration_s`, `resolution` (`1080p`, `1920x1080`, `4K`, …), `language`, `limit` | Identify a file the viewer already holds. The media facts are evidence, not extra keywords: each hint comes back classified as `matched_on`, `mismatched_on` or `unknown_on`, because a hint the ledger cannot answer is not agreement. Rows are the same shape as `/api/v1/posts` (plus `runtime_minutes`, `resolutions` and the three lists). No `q` is a `400`, not a popularity list: duration and rung alone match thousands of the 130 000 works here. |
| `/api/v1/stream` | `GET` | `id` (a **signed handle** we mint, required), `redirect` (`1` or `0`) | Just-in-Time (JIT) stream resolver. When `redirect=1` (default), returns **HTTP 302 Found** directly to the live, unexpired video stream for native player playback. When `redirect=0`, returns JSON with refreshed token metadata — and no URL. A raw database row id is rejected with `400`. |
| `/api/v1/rules` | `GET` | None | ~~Remote regex and extraction rules for client-side unwrapping~~ **operator port only.** It is `404` on the public base URL: it names every hoster endpoint we unwrap, so serving it publicly hands a third party our whole resolution stack. Unwrapping is server-side, see §5. |
| `/api/v1/stats` | `GET` | None | Live system metrics: total posts, releases, sources, active links, and resumable streams. Scale only — no per-site breakdown. |
| `/api/v1/app/remote-config` | `GET` | None | The operator's monetization settings as a phone may see them: `vip` pricing in PKR, `payments` (JazzCash till + mobile account, EasyPaisa, Raast), `ads` (Monetag rewarded zone, Adsterra native tag), and a `link_shorteners` rotation list with `configured` per network. **No credentials:** a shortener API token stays in the row, because a client that holds it can shorten on the operator's account over an endpoint with no TLS. Shortening is therefore server-side; a client only decides direct-vs-shortened from `configured`. Cached `max-age=60`; unset fields come back as empty strings, never an error. |
| `/api/v1/download` | `GET` | `id` (signed handle), `redirect` (`1`/`0`), `vip` (a `vip-pass`, §7.1) | The **download** twin of `/api/v1/stream`, and the only route that runs the operator's shortener waterfall. `redirect=1` answers 302 — to the media URL for a member, or to a shortened link for a free caller (a page a human taps through, so this route is for an `ACTION_DOWNLOAD`/browser hand-off, **not** for the app's byte-piping cache, which stays on `/api/v1/stream`). `redirect=0` answers the descriptor (`stream_id`, `filename`, `mime_type`, `file_size_bytes`, `resumable`, `expires_in`, `download_url`). If every shortener is unconfigured, erroring or slow the direct URL is used instead: monetization can never break a download. Public since 2026-10-27 — before that nginx's `^~ /api/` deny answered it `403`, so the entire waterfall was unreachable from any client. |
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
`/api/v1/sync`** — cross-device sync is the optional v2 account surface (§7), and it is
the only thing on this server that is `POST`ed to with a credential. `do_POST()` itself
is not empty any more: it answers `/admin*` (operator port only), `/api/v2/account*` (§7),
and the v2 write routes (`POST /api/v2/play`, `POST /api/v2/links/{ref}/report`,
`POST /api/v2/episodes/{ref}/offset`); every other
path is a `404`, the same answer an unknown path gets on `GET`.

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

Nothing here is *required* to read the catalog: every v1 and v2 browse, detail, artwork
and stream route answers a signed-out client. What was added since is one **optional**
authenticated surface — `/api/v2/account*` (§7), a bearer sync key — and it changes what
is *stored* for a viewer, never what they are *allowed to read*. Beyond that, the public
port no longer answers with anything worth scraping whole:

- every response is a projection (`redact.project`), so provenance fields are absent by
  construction rather than by luck (§2 above);
- playables, artwork and streams are addressed by signed opaque handles; a raw row id is
  rejected (`400`), so 3.07 M links cannot be walked;
- `IETF RateLimit-*` + `Retry-After` headers on every response — buckets `browse`
  60/min, `play` 30/min, `reports` 10/min, `account` 30/min per client IP
  (`redact.BUCKET_LIMITS`);
- the whole-catalog dump (`/api/data`), the bridge table (`/api/v1/rules`), the sitemap
  feed, `/api/fetch`, `/api/heal`, `/api/health-check` are **operator-port only** —
  `404` on the public port;
- the operator port is a second bind on `127.0.0.1` (`RADD_INTERNAL_PORT`, default 8081).
  Policy hangs on the *port*, because a request can forge a header but not a port.

`send_json()` still stamps `Access-Control-Allow-Origin: *` (viewer.py), `start_server()`
still defaults to `0.0.0.0`, and the Oracle host serves plain HTTP with no TLS. Treat
everything the public port does return as public to anyone who can reach it — which is
now exactly what a user sees, plus nothing that names where it came from.

The one credential this API accepts is a §7 sync key, and it is the reason the missing
TLS is a real user-facing problem rather than a footnote: on `http://92.4.95.252` the
`Authorization: Bearer …` header crosses the network in the clear, so anyone on the path
can read it and become that account — which is only that viewer's favorites and resume
points, and is exactly why nothing personal, no password and no email may be stored
behind one. The app says this to the viewer on the card that creates the key. The fix is
a certificate on the host, not a cleverer token format, and it is the owner's call
(`ORACLE_DEPLOYMENT.md`).


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

### 5.1 The quality ladder — one option per quality, never a link list

`GET /api/v1/posts/{id}` answers, in addition to `releases`, an `option_groups` array: the
whole title's links folded into **one winner per quality band, per season/episode scope**
(`Fast_Fetch/tiers.py`). The ledger still holds every copy of every print — six mirrors of the
same 1080p disc are six rows in SQLite and **one** row on screen.

```json
{"season": "1", "episode": "3",
 "tiers": [{"band": "1080p", "quality": "1080p", "label": "Full HD · X264",
            "mode": "play", "playable": true, "copies": 4,
            "link": {"stream_id": "AftsgBBMlHvg0xriBg", "kind": "resolve",
                     "playable": true, "play_url": "http://<us>/api/v1/stream?id=…",
                     "expires_at": null, "file_size_bytes": 2013265920, "resumable": true}}],
 "auto": {"band": "1080p", "reason": "best", "stream_id": "AftsgBBMlHvg0xriBg"},
 "download_only_bands": ["2160p"]}
```

What the client does with it — the two screens the owner asked for:

- **Player**: start at `auto.stream_id`. The quality switch lists `tiers[]` and shows only
  `label` ("4K Ultra HD", "Full HD · X264"). Never render `copies`, never render a server name
  (there is none to render), never sort or re-rank locally.
- **Download card**: the same `tiers[]` in the same order, one row per quality, so 480p / 720p /
  1080p / 4K is the whole UI. A tier with `mode: "download_only"` is labelled **"Download
  only"** and is not offered to the player — that is the honest label for a print we can fetch
  but not stream here.
- `band` is the stable key for UI and for the user's stored preference
  (`2160p|1080p|720p|480p|sd|unspecified`); `label` is display copy and may be reworded at any
  time, so never key on it.

Order and selection are the server's job: playability first, then live-vs-dead, then measured
speed and latency, then resumability, then freshness, then a sanity check on file size, then the
server preference the healers earned. That ranking is a *sort key* — the client gets the
outcome, never the inputs, and cannot reconstruct which hoster won. Failover stays silent: if a
`302` target refuses the device, ask for the next candidate for the same print and, if the band
is exhausted, step one band down.

Honest limit: a long-running series with per-episode prints produces one group per episode, and
the biggest title in the catalog (1,174 scoped releases) serialises to ~6 MB, of which the
ladder is ~1 MB and the pre-existing `releases` list is the rest. Episode lists for series that
large should come from the paginated v2 routes (`API_V2.md §12`) once mounted; do not fetch that
detail payload on a phone network as a habit.

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

---

## 7. Optional Sync Accounts — `/api/v2/account*`

The one part of this API that knows who you are, and the only thing the app sends a
credential for. It is **optional**: a fresh install is signed out, nothing on the browse or
play path asks, and pressing "Sync" is what creates an account.

### 7.1 The routes

`Fast_Fetch/accounts_api.py` owns this edge, `Fast_Fetch/accounts.py` owns the data. Full
contract in `API_V2.md` §12.1; this is the client-facing summary.

| Route | Verb | Body / query | Answer |
| :--- | :--- | :--- | :--- |
| `/api/v2/account` | `POST` | `{}` — or `{"sync_key": "…"}` to adopt a key this app already minted | `201 {"account": {"created": true, "created_at": …, "sync_key": "…"}}`, or `200 {"account": {"created": false, "created_at": …}}` when that key already exists. **The plaintext key is returned exactly once.** |
| `/api/v2/account` | `GET` | — | `{"account": {"created_at", "last_seen_at"}}` |
| `/api/v2/account/favorites` | `GET` | `?limit=` (default 200, clamped to 1000) | `{"favorites": [{work_ref, season_number, episode_number, added_at}], "count": n}` |
| `/api/v2/account/favorites` | `POST` | `{work_ref, season_number?, episode_number?}` | `201 {"favorite": {…}}` |
| `/api/v2/account/favorites/remove` | `POST` | same body | `{"removed": true/false}` |
| `/api/v2/account/progress` | `GET` | `?limit=` | `{"progress": [{work_ref, season_number, episode_number, position_seconds, duration_seconds, client_updated_at, updated_at}], "count": n}` |
| `/api/v2/account/progress` | `POST` | `{work_ref, position_seconds, duration_seconds, season_number?, episode_number?, client_updated_at?}` | `201 {"progress": {…}}` — last-write-wins per (work, season, episode) |
| `/api/v2/account/progress/remove` | `POST` | `{work_ref, season_number?, episode_number?}` | `{"removed": true/false}` |
| `/api/v2/account/vip-pass` | `GET` | — | `200 {"pass": "…", "expires_at": …, "membership_until": …}` for an account with a live membership; `402 licence_required` for a free one, `401` with no key. The pass is the **only** VIP proof a URL can carry: `/api/v1/download` accepts an `Authorization` header or `?vip=`, and a redirect the system download manager follows cannot carry a header, so without this route a payer would still be walked through the operator's shortener. No identity, no payment detail, six-hour window, never longer than the membership. |
| `/api/v2/account/revoke` | `POST` | — | `{"revoked": true}` |

Every row is identified by `work_ref` — the same minted handle a catalog item carries —
never by a `work_key` and never by `account_id`. A raw `work_key` in a request body is a
`400`, the same answer as a forged handle, and neither quotes the caller's input back.

### 7.2 What a client must do with a refusal

Refusals are RFC 9457 `application/problem+json` with the same closed code list as the
catalog (`api_v2.PROBLEM_CODES`), so one parser covers both. `detail` is a sentence for
logs, never for a viewer. The mapping `SyncContract.verdictOf()` implements:

- `401` / `unauthorised` → **sign this device out.** Never retry a 401 in-session: the sync
  key *is* the whole credential, so "asking harder" is a brute-force attempt against your
  own viewer, and `accounts.LIMITER` locks the key on a failure window (`429`).
- `429` / `rate_limited` → **pause the session** and stop writing until `Retry-After`
  passes. Applies to both the per-IP `account` bucket and the per-key lockout.
- `404` **and the request carried no `work_ref`** → the account itself is unknown; sign out.
- `404` / `400` / `403` / `409` **on a call that named a work** → that one item is refused
  (hidden adult title, or a work no longer in the projection — indistinguishable by
  design, `accounts.work_is_visible`); drop the item, keep the account.
- `5xx` / anything unmapped → keep the local write. Sync is a copy, not the record.

Local state is written first and synced after, so a viewer's list never waits on this VM.

### 7.3 Limits a client must not try to grow

No passwords, no email, no sessions, no JWT, and no user-visible profile: an account holds
favorites and resume points and nothing else, and it grants no additional access — an
authenticated client sees exactly what a signed-out one does. An adult-flagged work cannot
be favorited or given a resume point even with a valid minted handle; the answer is the
same `404` an unknown work gets. A library is capped at 5,000 favorites and 5,000 progress
rows (`accounts.MAX_FAVORITES` / `MAX_PROGRESS`), and the answer when it is full is `409
account_full` — a client that hits it should stop syncing, not retry. A `client_updated_at`
more than a day ahead of this server's clock is clamped to the receipt time, so one device
showing 2035 cannot freeze a row. And the caveat that matters most is the one on the account
card in the app: this host is plain HTTP, so `Authorization: Bearer …` travels in the clear
(§"Security posture"). Turn on TLS on the host before telling anyone an account is safe.
