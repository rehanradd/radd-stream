package com.raddstream.app.player

import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi

/** An external subtitle the user picked (SAF file or bundle-provided URL). */
data class ExternalSubtitle(
    val url: String,
    val label: String,
    val formatHint: String, // "srt" | "vtt" | "ass" | "ttml" ...
    /** true → rendered by our overlay (delay-capable); false → handed to Media3 natively. */
    val customRendered: Boolean,
)

/**
 * Translation layer from the failover contract (PlayBundle) to Media3 `MediaItem`s.
 * Only file that touches Android types among the player model files; kept dumb on purpose.
 */
@OptIn(UnstableApi::class)
object PlaybackMediaItemFactory {

    fun build(
        rendition: PlaybackRendition,
        target: PlayTarget,
        title: String,
        externalSubtitles: List<ExternalSubtitle> = emptyList(),
    ): MediaItem {
        val manifestMime = manifestMimeType(rendition.playback)
        val builder = MediaItem.Builder()
            .setUri(rendition.playback.playUrl)
            .setMediaId("${target.workKey ?: "w${target.id}"}-r${rendition.releaseId}-${rendition.rank}")
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(episodeAwareTitle(target, title))
                    .apply {
                        if (rendition.playback.isHls()) setMediaType(MediaMetadata.MEDIA_TYPE_VIDEO)
                    }
                    .build(),
            )
        if (manifestMime != null) {
            builder.setMimeType(manifestMime)
        }

        // Native subtitle configurations for non-custom-render externals (API_V2 tracks.subtitles
        // and user-picked exotic formats). SRT/VTT we parse ourselves for the overlay; both
        // paths obey the same subtitle-sync offset (see OffsetSubtitleDecoderFactory).
        val nativeSubs = externalSubtitles.filterNot { it.customRendered }
        if (nativeSubs.isNotEmpty()) {
            builder.setSubtitleConfigurations(
                nativeSubs.map { it.toSubtitleConfiguration() },
            )
        }

        rendition.playback.drm?.let { drm ->
            val system = drm["system"]?.lowercase()
            val licenseUrl = drm["license_url"]
            if (system == "widevine" && !licenseUrl.isNullOrBlank()) {
                builder.setDrmConfiguration(
                    // Media3 1.3.1: DrmConfiguration is nested in MediaItem; C.WIDEVINE_UUID is already a UUID.
                    MediaItem.DrmConfiguration.Builder(C.WIDEVINE_UUID)
                        .setLicenseUri(licenseUrl)
                        .build(),
                )
            }
        }
        return builder.build()
    }

    fun episodeAwareTitle(target: PlayTarget, title: String): String {
        if (target.season <= 0 && target.episode <= 0) return title
        val s = if (target.season > 0) "S%02d".format(target.season) else ""
        val e = if (target.episode > 0) "E%02d".format(target.episode) else ""
        val prefix = listOf(s, e).filter { it.isNotEmpty() }.joinToString(" ")
        return "$prefix · $title"
    }

    /**
     * The Media3 content type this link must be declared as, or null to leave the choice to the
     * progressive extractors.
     *
     * Media3 1.3.1 picks the [androidx.media3.exoplayer.source.MediaSource] from
     * `Util.inferContentTypeForUriAndMimeType(uri, mimeType)`, which consults exactly two things:
     * the mime type declared on the `MediaItem`, and the URI's **path** extension. There is no
     * `SniffingMediaSource` at this version, so nothing re-inspects the bytes to discover a
     * playlist — an answer of `CONTENT_TYPE_OTHER` is a progressive source, full stop.
     *
     * That matters here because a playback address is our own
     * `<server>/api/v1/stream?id=<handle>`, which carries no extension at all, and a hoster's
     * playlist often rides inside a query string (`…/watch?f=https://…/index.m3u8`) where
     * `Uri.getPath()` cannot see it either. Undeclared, both become progressive, read an `#EXTM3U`
     * text body, find no container magic, and throw `UnrecognizedInputFormatException` before the
     * first frame. Declaring the manifest type is what makes this one player really play
     * everything.
     *
     * MP4 and MKV are deliberately absent from this rule: they are *containers* selected by
     * extractor sniffing inside the progressive source, which recognises an MP4 `ftyp` box and an
     * MKV EBML header on any extensionless address. Declaring a container mime would only add a
     * way to be wrong when the server mislabels one, so progressive links keep the sniffed path.
     *
     * WHY THE MANIFEST EVIDENCE IS ORDERED THIS WAY — measured against `Fast_Fetch/catalog_v2.py`
     * `_protocol_of()` (:1391), which writes this field: it answers `hls` only for a link stored as
     * `kind = hls_manifest`, so `protocol = "hls"` is solid evidence and is never a guess. But the
     * same function returns `progressive` for *anything* whose playability is stream/download/both,
     * and it has no `dash` branch at all — so a manifest the projection did not name is still a
     * manifest, and the mime the resolver reported and the extension inside the address both outrank
     * a coarse `progressive` word here. An unknown word (`http/1.1`, `unknown`, a value this app has
     * never seen) declares nothing, which is the same answer it gets today.
     *
     * The returned constants are the only two strings Media3's own matcher accepts for a manifest;
     * inventing a mime spelling here would silently fall through to progressive, which is the bug
     * this exists to fix. `UniversalSourceTest` pins the identity against `MimeTypes`.
     */
    fun manifestMimeType(playback: PlaybackInfo): String? {
        val mime = playback.mimeType?.trim()?.lowercase()
        return when {
            playback.isHls() || mime?.contains("mpegurl") == true -> MimeTypes.APPLICATION_M3U8
            playback.isDash() || mime?.contains("dash+xml") == true -> MimeTypes.APPLICATION_MPD
            else -> null
        }
    }

    private fun ExternalSubtitle.toSubtitleConfiguration(): MediaItem.SubtitleConfiguration =
        MediaItem.SubtitleConfiguration.Builder(Uri.parse(url))
            .setMimeType(mimeForFormat(formatHint))
            .setLabel(label)
            .build()

    fun mimeForFormat(format: String?): String = when (format?.lowercase()) {
        "srt", "subrip" -> MimeTypes.APPLICATION_SUBRIP
        "vtt", "webvtt" -> MimeTypes.TEXT_VTT
        "ass", "ssa", "substation" -> MimeTypes.TEXT_SSA
        "ttml", "dfxp", "stpp" -> MimeTypes.APPLICATION_TTML
        else -> MimeTypes.APPLICATION_SUBRIP // sniffed at parse time; SubRip is the safest default
    }

    /** Formats our custom overlay renderer supports (delay/offset/styling path). */
    fun isCustomRenderable(format: String?): Boolean =
        format?.lowercase() in setOf("srt", "subrip", "vtt", "webvtt", "srt; charset=utf-8")
}
