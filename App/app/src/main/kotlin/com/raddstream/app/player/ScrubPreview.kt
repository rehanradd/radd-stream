package com.raddstream.app.player

import android.content.Context
import android.os.Build
import android.view.TextureView
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.SeekParameters
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import com.raddstream.app.brand.Brand

/**
 * Scrub thumbnails — the preview picture above the seek bar while the viewer
 * drags to a new position (YouTube-style), plus the time the toast already
 * printed. Owner order 2026-11-11: Android 5 (API 21-22) does not get it;
 * every device that supports it does. minSdk stays 21.
 *
 * Why a second player, not MediaMetadataRetriever: most of what this app
 * plays is HLS, and the retriever reads media FILES — it cannot open a
 * playlist, so `getFrameAtTime` on an HLS address returns null. A preview
 * player is the same Media3 stack as the main player, so it plays whatever
 * the main player plays (HLS and progressive alike) and the frame it shows
 * is the frame the main player would land on. Server-side sprites would be
 * the other honest route, but the backend serves no sprite; that is a
 * backend task, not this one.
 *
 * The preview player is deliberately NOT a second playback path: it is
 * muted (volume 0), always paused (`playWhenReady = false`), takes no
 * audio focus, has no MediaSession and no wake lock, and renders only into
 * the toast's TextureView. It seeks with CLOSEST_SYNC, like the main
 * player, so a scrub seek snaps to a keyframe instead of decoding forward.
 * It fetches through the same data source as the main player (our user
 * agent, cross-protocol redirects on — the resolver 302s are the normal
 * path), so a thumbnail fetch behaves exactly like a playback fetch.
 *
 * The TextureView IS the thumbnail — no Bitmap is captured or copied. While
 * the viewer drags, the preview player is always seeking and the TextureView
 * keeps showing the last frame it rendered, which is the wrong scene for
 * the time the toast prints. So the toast only shows the TextureView once
 * the target has sat still for [ScrubThumbnails.SETTLE_MS] (see
 * PlayerScreen): by then the preview player has had a chance to render the
 * frame at that position. The time text is always correct; the picture is
 * a visual aid that arrives a beat later.
 *
 * Lifecycle: created lazily on the first scrub (API 23+ only), released
 * when the player screen leaves. It holds no media item until the first
 * scrub, so an idle screen pays for one idle player, not a stream.
 */
object ScrubThumbnails {

    /**
     * Scrub thumbnails exist on API 23+ (Android 6.0) and above only. The
     * [sdkInt] parameter is the device's API level (defaults to the running
     * device) — it exists so the gate is a pure function a JVM test can
     * call with 21, 22 and 23 directly.
     */
    fun isSupported(sdkInt: Int = Build.VERSION.SDK_INT): Boolean =
        sdkInt >= Build.VERSION_CODES.M

    /**
     * Whether the toast shows the thumbnail for [targetMs]. The thumbnail
     * only shows once the target has settled ([settledMs] == [targetMs])
     * AND a preview player exists. While the finger is still moving the
     * settled target trails (or is null), so the toast shows only the time
     * — the frame on screen would be from the last settled position, the
     * wrong scene for the time being printed.
     */
    fun shouldShowThumbnail(settledMs: Long?, targetMs: Long, previewAvailable: Boolean): Boolean =
        previewAvailable && settledMs == targetMs

    /**
     * How long the scrub target must sit still before the thumbnail appears.
     * During a fast drag the preview player never settles, so showing the
     * TextureView then would show the frame from the last settled position.
     */
    const val SETTLE_MS: Long = 300L

    /** Thumbnail size in the toast: 16:9, small enough to sit over the chrome. */
    const val THUMBNAIL_WIDTH_DP: Int = 160
    const val THUMBNAIL_HEIGHT_DP: Int = 90
}

/**
 * A muted, paused ExoPlayer that renders the frame at a scrub target into a
 * TextureView. One instance per player screen; create it lazily on the
 * first scrub and [release] it when the screen leaves.
 */
@OptIn(UnstableApi::class)
class ScrubPreviewPlayer(context: Context) {

    private val player: ExoPlayer
    private var currentUrl: String? = null

    init {
        // Same fetch behaviour as the main player (PlaybackService): our
        // user agent, cross-protocol redirects on, local schemes through
        // DefaultDataSource so a finished download previews in airplane mode.
        val httpFactory = DefaultHttpDataSource.Factory()
            .setUserAgent(Brand.userAgent)
            .setAllowCrossProtocolRedirects(true)
        val dataFactory = DefaultDataSource.Factory(context.applicationContext, httpFactory)
        player = ExoPlayer.Builder(context.applicationContext)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataFactory))
            .build()
        player.volume = 0f
        player.playWhenReady = false
        // Snap to the nearest sync frame, like the main player: a scrub seek
        // is a preview, not a frame-exact landing.
        player.setSeekParameters(SeekParameters.CLOSEST_SYNC)
    }

    /**
     * Point the preview at the rendition now playing. A no-op when the URL
     * is blank or unchanged (a quality switch is the only thing that moves
     * it, and a scrub never changes quality). The item comes from
     * [PlaybackMediaItemFactory.buildPreview] — this file is the one place
     * that composes MediaItems (UniversalSourceTest pins it), so the preview
     * never builds one itself; the manifest declaration rides along, or an
     * HLS link is opened by the progressive reader and fails.
     */
    fun setRendition(rendition: PlaybackRendition) {
        val url = rendition.playback.playUrl
        if (url.isNullOrBlank() || url == currentUrl) return
        currentUrl = url
        player.setMediaItem(PlaybackMediaItemFactory.buildPreview(rendition))
        player.prepare()
    }

    /** Seek the preview to the scrub target. No-op until a rendition is set. */
    fun previewAt(positionMs: Long) {
        if (currentUrl == null) return
        player.seekTo(positionMs.coerceAtLeast(0L))
    }

    /** Attach the toast's TextureView as the preview surface. */
    fun setVideoTextureView(view: TextureView) {
        player.setVideoTextureView(view)
    }

    /** Detach the surface (the toast hid). The player stays prepared. */
    fun clearVideoTextureView(view: TextureView) {
        player.clearVideoTextureView(view)
    }

    /** Release the preview player. Call when the player screen leaves. */
    fun release() {
        player.release()
    }
}
