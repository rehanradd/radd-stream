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

        // A manifest must be told what it is before the reader is chosen: see manifestMimeType.
        manifestMimeType(rendition.playback)?.let { builder.setMimeType(it) }

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

    /**
     * A minimal MediaItem for the scrub-preview player (ScrubPreviewPlayer): the
     * URI plus the manifest declaration, nothing else — no mediaId, no metadata,
     * no subtitles, no DRM. The preview is muted, paused and never shown as a
     * title, so it needs none of those; what it does need is the manifest
     * declaration, or an HLS link is opened by the progressive reader and fails
     * before the first frame (see manifestMimeType).
     *
     * This lives here, not in ScrubPreviewPlayer, because this file is the one
     * place that composes MediaItems — UniversalSourceTest pins the census to
     * this file alone, so a second MediaItem.Builder() anywhere else is a
     * second answer to what a link contains.
     */
    fun buildPreview(rendition: PlaybackRendition): MediaItem {
        val builder = MediaItem.Builder()
            .setUri(rendition.playback.playUrl)
        // A manifest must be told what it is before the reader is chosen: see manifestMimeType.
        manifestMimeType(rendition.playback)?.let { builder.setMimeType(it) }
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
     * The manifest container this link's bytes are, as the one MIME string Media3 recognises —
     * or null to leave the choice to Media3's own inference.
     *
     * Inference reads a URI's path extension and a declared type; it never sniffs bytes, and
     * every address this app plays is our own `/api/v1/stream?id=<handle>`, which has no
     * extension and is redirected long after the reader has been picked. So an HLS link left
     * undeclared is opened by the progressive reader, which meets `#EXTM3U` where an MP4 box
     * should be and fails with `UnrecognizedInputFormatException` before the first frame. The
     * server already knows which protocol it recorded for the link; this is where that
     * knowledge crosses into Media3.
     *
     * The wire spelling is normalised, not trusted: a CDN answers `application/vnd.apple.mpegurl`
     * as often as the Media3 constant's own text, and the content type the backend stores is the
     * header verbatim. An alias Media3 does not know is the silent progressive reader again, so
     * every match here is against a known set and the value handed back is always the constant.
     *
     * Progressive MP4, MKV and WebM are deliberately NOT declared: their readers do sniff the
     * container from the bytes, which is the one thing an extensionless address cannot break.
     */
    fun manifestMimeType(playback: PlaybackInfo): String? {
        val declared = playback.mimeType?.lowercase()?.trim()?.substringBefore(';')?.trim().orEmpty()
        return when {
            playback.isHls() || declared in hlsManifestMimes -> MimeTypes.APPLICATION_M3U8
            playback.isDash() || declared in dashManifestMimes -> MimeTypes.APPLICATION_MPD
            else -> null
        }
    }

    private val hlsManifestMimes: Set<String> = setOf(
        MimeTypes.APPLICATION_M3U8.lowercase(),
        "application/vnd.apple.mpegurl",
        "application/vnd.mpegurl",
        "application/mpegurl",
        "audio/mpegurl",
    )

    private val dashManifestMimes: Set<String> = setOf(
        MimeTypes.APPLICATION_MPD.lowercase(),
        "application/mpd",
    )

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

    /**
     * Bundle subtitle tracks (Gap A3) as the externals [build] takes: the
     * label is the track's language, the format hint is the server's
     * format, and the render path follows the same rule as a user-picked
     * file — SRT/VTT go to our overlay, everything else to Media3.
     * A track with no URL can never be fetched, so it is dropped here
     * rather than handed to the player to fail on.
     */
    fun externalsFromTracks(tracks: TracksInfo): List<ExternalSubtitle> =
        tracks.subtitles.mapNotNull { track ->
            val url = track.url?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            ExternalSubtitle(
                url = url,
                label = track.language?.takeIf { it.isNotBlank() } ?: "Subtitles",
                formatHint = track.format.orEmpty(),
                customRendered = isCustomRenderable(track.format),
            )
        }
}
