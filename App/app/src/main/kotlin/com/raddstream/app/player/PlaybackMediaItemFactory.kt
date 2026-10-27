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
