package com.raddstream.app.player

import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Media3 `MediaSessionService` owning the single app-wide [ExoPlayer].
 *
 * Responsibilities (mirrors API_V2.md §5 "App behaviour the contract mandates" + MX parity):
 *  - **Failover**: on a player error, consult [FailoverStateMachine] (retry once → next rank,
 *    max_ranks cap) while preserving the playback position across the switch, and record
 *    *which print settled and why each previous candidate died* in [PlayerSessionStore] so
 *    the overlay can tell the user.
 *  - **In-file episode advance**: when a packed print (season_pack / episode_range) ends and
 *    the next episode's offset is known (learned `cat_offsets` semantics or server chapter
 *    row), seek instead of stopping; otherwise hand a [NextEpisodeAction] to the UI.
 *  - **Media session**: notifications, lock screen, headset buttons and `PlaybackService`
 *    background survival come free from `MediaSession` — the screen controls it via
 *    `MediaController` (PlayerViewModel), never a second player.
 *
 * The UI-side commands arrive through the shared [PlayerSessionStore] (same process) — no
 * Intent serialization. HLS/progressive source selection stays with Media3's default media
 * source factory (media3-exoplayer-hls is already a dependency).
 */
@OptIn(UnstableApi::class)
class PlaybackService : MediaSessionService() {

    private var mediaSession: MediaSession? = null
    private var player: ExoPlayer? = null
    private val store: PlayerSessionStore = PlayerSessionStore.Instance
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var failover: FailoverStateMachine? = null

    /** Resume target for the rendition currently being loaded (seek once READY). */
    private var pendingResumeMs: Long? = null
    private var lastKnownPositionMs: Long = 0
    private var titleHint: String = "Radd Stream"

    override fun onCreate() {
        super.onCreate()
        // Cross-protocol redirects ON: resolver 302s are the normal path on this backend.
        // Cleartext: debug builds allow http (app/src/debug/AndroidManifest.xml); the release
        // HTTP-only gap is documented in PLAYER_SPEC.md §3.4 + HANDOFF_appplayer.md.
        val httpFactory = DefaultHttpDataSource.Factory()
            .setUserAgent("RaddStream/1.0 (Android Media3)")
            .setAllowCrossProtocolRedirects(true)

        val exo = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(httpFactory))
            .setSeekBackIncrementMs(MX_SKIP_MS)
            .setSeekForwardIncrementMs(MX_SKIP_MS)
            .setAudioAttributes(AudioAttributes.DEFAULT, /* handleAudioFocus= */ true)
            .build()
        // Screen-off playback (MX "keep playing with screen off") — no sensor needed.
        exo.setWakeMode(C.WAKE_MODE_LOCAL)
        exo.addListener(playerListener)
        player = exo

        mediaSession = MediaSession.Builder(this, exo).build()

        scope.launch {
            store.loadRequest.collect { request ->
                if (request != null && request.nonce != lastHandledNonce) {
                    lastHandledNonce = request.nonce
                    handleLoad(request)
                }
            }
        }
    }

    private var lastHandledNonce: Long = -1L

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? =
        mediaSession

    private fun handleLoad(request: PlayerSessionStore.LoadRequest) {
        val bundle = store.bundle.value ?: return
        val exo = player ?: return
        exo.pause()
        if (bundle.isStale(System.currentTimeMillis())) {
            store.markGaveUp(
                "Play bundle expired — fetch a fresh link",
                HandoffWhy.NO_CANDIDATE_LEFT,
            )
            return
        }
        titleHint = request.title
        store.clearGaveUp()
        store.resetFailoverLog()
        val machine = FailoverStateMachine(bundle.renditions, bundle.failurePolicy)
        failover = machine
        val start = machine.selectInitial()
        store.appendFailover(machine.log) // why any lower-ranked candidate was skipped
        if (start == null) {
            // Nothing our player can present. Say so plainly, and offer the keep-only link when
            // one exists — there is no embed/WebView escape hatch in this app to fall back to.
            val keepOnly = machine.keepOnlyFallback()
            store.markGaveUp(
                if (keepOnly != null) {
                    "$NOT_PLAYABLE_HERE — this rank can only be kept on the device"
                } else {
                    "No directly playable link in this bundle"
                },
                if (keepOnly != null) HandoffWhy.DOWNLOAD_ONLY else HandoffWhy.NO_CANDIDATE_LEFT,
            )
            return
        }
        pendingResumeMs = request.startOverrideMs ?: request.resumePositionMs.takeIf { it > 0 }
        lastKnownPositionMs = pendingResumeMs ?: 0L
        store.setActiveIndex(start)
        loadRendition(bundle, start)
    }

    private fun loadRendition(bundle: PlaybackBundle, index: Int) {
        val rendition = bundle.renditions.getOrNull(index) ?: return
        val exo = player ?: return
        if (rendition.playback.isExpired(System.currentTimeMillis())) {
            // Never play a rotted URL silently — §5: re-request instead.
            failover?.let { machine ->
                val decision = machine.onFailure("link expired before load")
                applyDecision(bundle, decision, preservePositionMs = lastKnownPositionMs)
            }
            return
        }
        val item = PlaybackMediaItemFactory.build(rendition, bundle.target, titleHint)
        exo.setMediaItem(item)
        exo.prepare()
        exo.playWhenReady = true
    }

    private fun applyDecision(
        bundle: PlaybackBundle,
        decision: FailoverDecision,
        preservePositionMs: Long,
    ) {
        when (decision) {
            is FailoverDecision.RetrySame -> {
                store.appendFailover(listOf(decision.record))
                scope.launch {
                    delay(decision.backoffMs)
                    loadRendition(bundle, decision.index)
                }
            }

            is FailoverDecision.Advance -> {
                store.appendFailover(listOf(decision.record))
                pendingResumeMs = preservePositionMs.takeIf { it > 0 }
                store.setActiveIndex(decision.index, announceSettled = true)
                loadRendition(bundle, decision.index)
            }

            is FailoverDecision.Handoff -> {
                decision.record?.let { store.appendFailover(listOf(it)) }
                store.markGaveUp(decision.detail ?: "Playback stopped", decision.why)
            }
        }
    }

    private val playerListener = object : Player.Listener {
        override fun onPlaybackStateChanged(playbackState: Int) {
            when (playbackState) {
                Player.STATE_READY -> {
                    pendingResumeMs?.let { pos ->
                        player?.seekTo(pos)
                        pendingResumeMs = null
                    }
                }

                Player.STATE_ENDED -> handleEnded()

                else -> Unit
            }
        }

        override fun onPositionDiscontinuity(
            oldPosition: Player.PositionInfo,
            newPosition: Player.PositionInfo,
            reason: Int,
        ) {
            if (reason == Player.DISCONTINUITY_REASON_SEEK ||
                reason == Player.DISCONTINUITY_REASON_SEEK_ADJUSTMENT
            ) {
                lastKnownPositionMs = newPosition.positionMs
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            val bundle = store.bundle.value ?: return
            lastKnownPositionMs = maxOf(lastKnownPositionMs, errorGetMs())
            val machine = failover ?: return
            val decision = machine.onFailure(summarize(error))
            applyDecision(bundle, decision, preservePositionMs = lastKnownPositionMs)
        }

        private fun errorGetMs(): Long = runCatching { player?.currentPosition ?: 0L }.getOrDefault(0L)

        private fun summarize(e: PlaybackException): String {
            val causeName = e.errorCodeName
            val detail = e.message?.substringBefore('\n')?.take(90).orEmpty()
            return "$causeName $detail".trim()
        }
    }

    /** MX-style auto-advance across coverage types (in-file part 1; cross-file via store). */
    private fun handleEnded() {
        val bundle = store.bundle.value ?: return
        val active = store.activeRendition() ?: return
        val exo = player ?: return
        val action = EpisodeProgression.computeNext(
            bundle = bundle,
            rendition = active,
            learned = store.learnedOffsets,
            positionMs = exo.currentPosition,
            durationMs = maxOf(exo.duration, 0L),
        )
        when (action) {
            is NextEpisodeAction.InFileSeek -> {
                pendingResumeMs = action.positionMs
                exo.seekTo(action.positionMs)
                exo.playWhenReady = true
            }

            is NextEpisodeAction.NextBundleRequest,
            is NextEpisodeAction.CalibrationNeeded,
            -> store.awaitNextEpisode(action)

            NextEpisodeAction.StopHere, NextEpisodeAction.Unknown -> Unit
        }
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        val p = player
        if (p == null || !p.playWhenReady || p.mediaItemCount == 0) {
            stopSelf()
        }
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        scope.cancel()
        mediaSession?.run {
            player.release()
            release()
            mediaSession = null
        }
        player = null
        super.onDestroy()
    }

    companion object {
        /** MX default double-tap / seek button increment. */
        const val MX_SKIP_MS = 10_000L
    }
}
