package com.raddstream.app.player

import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets

/**
 * What text pasted into the search bar is — the answer to "is this a link to
 * play, or a title to search for", as a pure rule with no network, no store,
 * no clock. Only a direct video file over http(s) is playable here: a
 * YouTube address names a page whose file this player cannot open, and any
 * other http(s) address names a page this app never renders — the viewer is
 * offered the system browser for it instead. A title, a fragment, or
 * anything without a scheme is the catalog search's job.
 */
sealed interface PastedText {
    /** A direct video file the player can open at once: .mp4 or .m3u8 over http(s). */
    data class DirectVideo(val url: String, val title: String, val isHls: Boolean) : PastedText

    /** A YouTube address, which this player cannot open: no direct file behind it. */
    data object YouTube : PastedText

    /**
     * An http(s) address that is not a video file: a page. The app never
     * renders it — the row offers to open it in the system browser, which
     * is the browser-identity handoff without building a web browser.
     */
    data class PageLink(val url: String) : PastedText

    /** Anything else: a title, a fragment — the catalog search owns it. */
    data object NotAUrl : PastedText
}

fun classifyPastedText(raw: String): PastedText {
    val text = raw.trim()
    if (text.isBlank()) return PastedText.NotAUrl
    val uri = try {
        URI(text)
    } catch (_: Exception) {
        return PastedText.NotAUrl
    }
    val scheme = uri.scheme?.lowercase() ?: return PastedText.NotAUrl
    if (scheme != "http" && scheme != "https") return PastedText.NotAUrl
    val host = uri.host?.lowercase() ?: return PastedText.NotAUrl
    if (host == "youtu.be" || host == "youtube.com" || host.endsWith(".youtube.com")) {
        return PastedText.YouTube
    }
    val path = uri.path?.lowercase() ?: return PastedText.NotAUrl
    val isHls = path.endsWith(".m3u8")
    if (!isHls && !path.endsWith(".mp4")) return PastedText.PageLink(url = text)
    return PastedText.DirectVideo(url = text, title = directVideoTitle(text), isHls = isHls)
}

/** The file name at the end of the address, decoded; "Video link" when there is none. */
fun directVideoTitle(url: String): String {
    val segment = try {
        URI(url).path?.substringAfterLast('/')?.takeIf { it.isNotBlank() }
    } catch (_: Exception) {
        null
    } ?: return "Video link"
    val decoded = try {
        URLDecoder.decode(segment, StandardCharsets.UTF_8.name())
    } catch (_: Exception) {
        segment
    }
    return decoded.takeIf { it.isNotBlank() } ?: "Video link"
}

/** True when the address names an HLS playlist rather than a single file. */
fun directVideoIsHls(url: String): Boolean = try {
    URI(url).path?.lowercase()?.endsWith(".m3u8") == true
} catch (_: Exception) {
    false
}

/** The reader Media3 needs: a manifest mime for playlists, plain mp4 otherwise. */
fun directVideoMime(url: String): String =
    if (directVideoIsHls(url)) "application/vnd.apple.mpegurl" else "video/mp4"
