package com.raddstream.app.images

import java.net.URI

/**
 * Phase 7 (M4): which image URLs the app may fetch directly.
 *
 * The catalog's art already travels through the server: `redact.public_art_value`
 * wraps any non-public-CDN poster/backdrop into `/api/v1/art?id=<signed>&k=…`, so
 * a catalog row never hands Coil a scraper's upstream address in the first place.
 * This policy is the client-side second lock on the same door — the one place art
 * loads ([CatalogImage]) refuses any URL that is not our own server, a public
 * image CDN, or a neutral upload host, and paints the fallback card instead.
 *
 * Fail OPEN while the configured server host is still loading (`serverHost == null`):
 * the server already vets catalog art, so the loading window only skips this
 * defense-in-depth check — it never invents an address, and a null host is a
 * loading state, not a reason to blank every poster on first launch.
 *
 * A relative URL is never allowed: the server always sends absolute art URLs on
 * real requests, so a relative one is a row the server did not vet.
 */
object ArtUrlPolicy {

    /**
     * The public image CDNs the server's art proxy passes through untouched
     * (`redact.PUBLIC_IMAGE_HOSTS`) — mirrors, not inventions; a host leaves
     * this list only when the server's list does.
     */
    val PUBLIC_IMAGE_HOSTS: Set<String> = setOf(
        "image.tmdb.org",
        "image.themoviedb.org",
        "www.themoviedb.org",
        "m.media-amazon.com",
        "assets-in.bmscdn.com",
        "i.ytimg.com",
        "encrypted-tbn0.gstatic.com",
        "occ-0-5264-3647.1.nflxso.net",
        "resizing.flixster.com",
    )

    /** Neutral upload hosts the catalog legitimately points art at. */
    val NEUTRAL_UPLOAD_HOSTS: Set<String> = setOf(
        "i.imgur.com",
        "iili.io",
        "imgurworld.top",
        "catimages.org",
        "i.imageflix.cam",
    )

    private const val GOOGLE_USER_CONTENT_SUFFIX = ".googleusercontent.com"

    /** True when Coil may fetch [url]: our server, a public CDN, or a neutral upload host. */
    fun isAllowed(url: String?, serverHost: String?): Boolean {
        if (url.isNullOrBlank()) return false
        if (serverHost == null) return true
        val uri = runCatching { URI(url.trim()) }.getOrNull() ?: return false
        val scheme = uri.scheme?.lowercase() ?: return false
        if (scheme != "http" && scheme != "https") return false
        val host = uri.host?.lowercase()?.trimEnd('.') ?: return false
        if (host == serverHost.lowercase().trimEnd('.')) return true
        if (host in PUBLIC_IMAGE_HOSTS) return true
        if (host in NEUTRAL_UPLOAD_HOSTS) return true
        if (host == "googleusercontent.com" || host.endsWith(GOOGLE_USER_CONTENT_SUFFIX)) return true
        return false
    }

    /** The host of a configured server URL (`https://raddstream.duckdns.org` → that host), or null. */
    fun hostOf(serverUrl: String?): String? {
        if (serverUrl.isNullOrBlank()) return null
        return runCatching { URI(serverUrl.trim()).host?.lowercase()?.trimEnd('.') }.getOrNull()
    }
}
