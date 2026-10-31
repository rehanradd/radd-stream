package com.raddstream.app.player

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.Renderer
import androidx.media3.exoplayer.SeekParameters
import androidx.media3.exoplayer.analytics.AnalyticsListener
import androidx.media3.exoplayer.source.LoadEventInfo
import androidx.media3.exoplayer.source.MediaLoadData
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.exoplayer.text.TextOutput
import androidx.media3.exoplayer.text.TextRenderer
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.raddstream.app.brand.Brand
import com.raddstream.app.player.subtitles.OffsetSubtitleDecoderFactory
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
 *  - **Auto quality**: when the viewer left the ladder on Auto, Media3's own load
 *    statistics (bytes and wall time per finished load) feed
 *    [AdaptiveQualitySwitcher] through the shared [PlayerSessionStore.autoQuality]
 *    director, and a rung change is applied as a same-position handle swap on our own
 *    redirector — see [evaluateAutoQuality].
 *
 * The UI-side commands arrive through the shared [PlayerSessionStore] (same process) — no
 * Intent serialization. Which container a link is gets declared per item by
 * [PlaybackMediaItemFactory] (our play addresses carry no file extension, so Media3 cannot
 * infer one); everything below that stays Media3's own — the default media source factory picks
 * the HLS, DASH and progressive readers from the declared type, and `media3-exoplayer-hls` plus
 * `media3-exoplayer-dash` are already dependencies.
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
    private var titleHint: String = Brand.name

    override fun onCreate() {
        super.onCreate()
        // Cross-protocol redirects ON: resolver 302s are the normal path on this backend.
        // Cleartext: debug builds allow http (app/src/debug/AndroidManifest.xml); the release
        // HTTP-only gap is documented in PLAYER_SPEC.md §3.4 + HANDOFF_appplayer.md.
        val httpFactory = DefaultHttpDataSource.Factory()
            .setUserAgent(Brand.userAgent)
            .setAllowCrossProtocolRedirects(true)
        // Local playback: a finished download is a `content://` (MediaStore) or
        // `file://` URI, not an HTTP address. Handing DefaultHttpDataSource a
        // content URI makes ExoPlayer fail before the first frame, so all reads
        // go through DefaultDataSource — it opens local schemes directly (no
        // network, no connectivity check) and delegates http(s) to the factory
        // above. This is what makes a saved file play in airplane mode.
        val dataFactory = DefaultDataSource.Factory(this, httpFactory)

        // TextRenderer is the one renderer we replace: it is final in 1.3.1 and knows no
        // subtitle offset, so its decoder gets a wrapper that holds each cue block back by
        // the live sync value (see OffsetSubtitleDecoderFactory). Every other renderer stays
        // exactly as DefaultRenderersFactory builds it.
        val renderersFactory = object : DefaultRenderersFactory(this) {
            override fun buildTextRenderers(
                context: Context,
                output: TextOutput,
                outputLooper: Looper,
                extensionRendererMode: Int,
                out: ArrayList<Renderer>,
            ) {
                out.add(
                    TextRenderer(
                        output,
                        outputLooper,
                        OffsetSubtitleDecoderFactory { store.subtitleOffsetMs },
                    ),
                )
            }
        }

        val exo = ExoPlayer.Builder(this)
            .setRenderersFactory(renderersFactory)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataFactory))
            .setLoadControl(loadControl())
            .setSeekBackIncrementMs(MX_SKIP_MS)
            .setSeekForwardIncrementMs(MX_SKIP_MS)
            .setAudioAttributes(AudioAttributes.DEFAULT, /* handleAudioFocus= */ true)
            .build()
        // Screen-off playback (MX "keep playing with screen off") — no sensor needed.
        exo.setWakeMode(C.WAKE_MODE_LOCAL)
        // Seeking snaps to the nearest sync frame instead of decoding forward from the previous
        // one, which is what makes dragging the scrub bar feel immediate. Costs frame-exact
        // landing; nobody scrubs for that. A `val` reassignment would not compile here — ExoPlayer
        // exposes this as a setter whose getter returns a different type.
        exo.setSeekParameters(SeekParameters.CLOSEST_SYNC)
        exo.addListener(playerListener)
        exo.addAnalyticsListener(autoQualityListener)
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
        startAutoQualityTicker()
        startPlayheadPump()
    }

    private var lastHandledNonce: Long = -1L

    /**
     * The buffering policy, in one call. [PlayerBuffering] owns the four numbers and the reason
     * for each; this is the only place they are handed to Media3, in the order
     * `setBufferDurationsMs` takes them — minimum, maximum, to start, to start again after a
     * stall — because the method is positional and a swap of two of them compiles happily.
     */
    private fun loadControl(): DefaultLoadControl =
        DefaultLoadControl.Builder()
            .setPrioritizeTimeOverSizeThresholds(PlayerBuffering.PRIORITIZE_TIME_OVER_SIZE)
            .setBufferDurationsMs(
                PlayerBuffering.MIN_BUFFER_MS,
                PlayerBuffering.MAX_BUFFER_MS,
                PlayerBuffering.BUFFER_FOR_PLAYBACK_MS,
                PlayerBuffering.BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS,
            )
            .build()

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? =
        mediaSession

    private suspend fun handleLoad(request: PlayerSessionStore.LoadRequest) {
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
            // one exists. A page link is never in this bundle — `DetailViewModel` opens the
            // provider-page screen for it before playback is launched — so these two exits are
            // the whole answer here, and there is no in-player escape hatch to fall back to.
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
        armAutoQuality(bundle, start)
        // A kept copy is always the better source, offline or not: no CDN, no redirect, and the
        // bytes are already on this device. Ask before touching the network, and never let a
        // local read failure block the remote one — the failover machine still holds the bundle's
        // own rung and will advance to it if the local copy turns out to be unusable.
        val rendition = bundle.renditions.getOrNull(start)
        val localUrl = localCopyUrlFor(rendition)
        if (rendition != null && localUrl != null) {
            store.appendFailover(
                listOf(
                    FailoverRecord(
                        rendition.rank, rendition.releaseId, rendition.displayLabel(),
                        "saved on this device", "playing the kept copy",
                    ),
                ),
            )
            loadRenditionOf(
                bundle,
                rendition.copy(
                    playback = rendition.playback.copy(
                        playUrl = localUrl,
                        // The kept bytes do not rot: the redirector's expiry no longer applies.
                        expiresAt = null,
                        ephemeral = false,
                    ),
                ),
            )
        } else {
            loadRendition(bundle, start)
        }
    }

    /**
     * The loopback address of a complete kept copy of this rendition, or null when there is none.
     *
     * The cache identifies a file by the opaque handle embedded in OUR OWN redirector address, so
     * only such an address can name one. A `content://`/`file://` download and a deep link have no
     * such handle and are played exactly as handed over. An engine failure is silence, not an
     * error: the caller then streams from the server as it always did.
     */
    private suspend fun localCopyUrlFor(rendition: PlaybackRendition?): String? {
        val playback = rendition?.playback ?: return null
        val url = playback.playUrl?.takeIf { it.isNotBlank() } ?: return null
        val handle = playback.streamId?.takeIf { it.isNotBlank() } ?: return null
        val engine = CacheEngineHolder.engine ?: return null
        return try {
            engine.playableUri(CacheSessionKey(renditionKey = handle, url = url))
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            null
        }
    }

    private fun loadRendition(bundle: PlaybackBundle, index: Int) =
        loadRenditionOf(bundle, bundle.renditions.getOrNull(index))

    /**
     * Start one rendition exactly as given. Taking the rendition rather than an index is what
     * lets a silent hop play a *different handle of the same rung*: the copy the caller hands
     * here is the active rendition with our own redirector's `id=` swapped, so nothing about
     * the quality, the print or the origin changes.
     */
    private fun loadRenditionOf(bundle: PlaybackBundle, rendition: PlaybackRendition?) {
        val exo = player ?: return
        rendition ?: return
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
        // Every load of a real address is a title being watched, which is the whole trigger a
        // preview has. A hop to a backup of the same print seeds again through the same line, and
        // the engine's own idempotence turns that second ask into no second row. A kept copy played
        // from disk is not: its address is our loopback proxy, which names no handle of the
        // redirector's, so the ask falls through to nothing.
        seedPreviewFor(rendition)
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

            is FailoverDecision.AdvanceBackup -> {
                // Silent by design: no banner, no "settled on" chip, same rung. Only the
                // auditable trail records the hop, for the diagnostics sheet.
                store.appendFailover(listOf(decision.record))
                val active = bundle.renditions.getOrNull(decision.index) ?: return
                val hopped = active.copy(
                    playback = active.playback.copy(playUrl = decision.playUrl, streamId = decision.streamId),
                )
                pendingResumeMs = preservePositionMs.takeIf { it > 0 }
                loadRenditionOf(bundle, hopped)
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

    /**
     * Band the loaded rung plays at, in the switcher's vocabulary. The print's own
     * resolution string is used when the ladder knows that band, so a hand-picked rung and
     * an Auto rung are described the same way; otherwise the staged start band.
     */
    private fun bandOfRendition(rendition: PlaybackRendition?): String? {
        val resolution = rendition?.print?.resolution?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
        return if (resolution != null && store.autoQuality.rungFor(resolution) != null) {
            resolution
        } else {
            store.autoQuality.currentBand
        }
    }

    // ── Auto quality: measured throughput → the next rung of the staged ladder ────

    /**
     * Arm the shared director for one playback. Called on every load, so a deep-linked
     * title (no ladder staged) gets an unarmed director instead of inheriting the previous
     * title's rung list — Auto then has nowhere to move and says nothing.
     */
    private fun armAutoQuality(bundle: PlaybackBundle, index: Int) {
        val plan = store.peekAutoLadder(bundle.renditions.getOrNull(index)?.playback?.streamId)
        val rungs = plan?.rungs.orEmpty()
        val startBand = plan?.startBand
            ?: bundle.renditions.getOrNull(index)?.print?.resolution?.trim()?.lowercase()
        store.autoQuality.configure(rungs, startBand, plan?.auto == true)
        store.setAutoBand(if (store.autoQuality.isEnabled()) store.autoQuality.currentBand else null)
    }

    /**
     * Media3's own load statistics are the sample source: every finished load reports the
     * bytes it moved and the wall time it took. No hand-rolled counting data source is
     * needed (and 1.3.1 ships no `CounterDataSource` to wrap with), which also means the
     * numbers are exactly what the player's bandwidth meter saw.
     */
    private val autoQualityListener = object : AnalyticsListener {
        override fun onLoadCompleted(
            eventTime: AnalyticsListener.EventTime,
            loadEventInfo: LoadEventInfo,
            mediaLoadData: MediaLoadData,
        ) {
            feedSample(loadEventInfo, mediaLoadData)
        }

        override fun onLoadCanceled(
            eventTime: AnalyticsListener.EventTime,
            loadEventInfo: LoadEventInfo,
            mediaLoadData: MediaLoadData,
        ) {
            // A cancelled load moved real bytes in real time (a seek, a rung change); the
            // sample is valid. Load ERRORS are not fed — a stalled connection reports a
            // tiny duration and would look like a spectacular speed.
            feedSample(loadEventInfo, mediaLoadData)
        }

        private fun feedSample(loadEventInfo: LoadEventInfo, mediaLoadData: MediaLoadData) {
            if (mediaLoadData.trackType !in MEASURABLE_TRACK_TYPES) return
            store.autoQuality.push(loadEventInfo.bytesLoaded, loadEventInfo.loadDurationMs)
        }
    }

    private fun startAutoQualityTicker() {
        scope.launch {
            while (true) {
                delay(AUTO_QUALITY_TICK_MS)
                evaluateAutoQuality()
            }
        }
    }

    /**
     * Feed the offline cache the playhead, from the one place that is alive for the whole of
     * playback.
     *
     * This is the pump the brief's `onPlayheadAdvanced` hook runs on. The engine's entry point looks
     * a task up by the key of the address being watched and returns when nothing answers, so a
     * progressing playhead only extends retention if SOMETHING is publishing it — and until now the
     * only publisher was the player screen's 200 ms UI ticker, which stops the moment the viewer
     * leaves the screen. Backgrounding a title to keep listening is the normal way this app is used,
     * so the cache was being fed while the poster was on screen and never again. The service owns the
     * player, so the service owns the position.
     *
     * Five seconds, and only on a move: [CacheCoordinator.onPlayheadAdvanced] answers a single
     * bounded pass and then parks until the byte it is shown advances further, so a faster feed
     * buys nothing but [com.raddstream.app.data.cache.CacheTaskDao] lookups — five a second at the
     * old cadence, for a window measured in tens of megabytes.
     */
    private fun startPlayheadPump() {
        scope.launch {
            var lastReportedMs = -1L
            while (true) {
                delay(PLAYHEAD_PUMP_MS)
                val exo = player ?: continue
                // A paused player has no forward edge to anticipate; a seek still moves the
                // position, and that is reported on the next tick exactly like playback does.
                if (!exo.isPlaying) continue
                val duration = if (exo.duration > 0L) exo.duration else exo.contentDuration
                if (duration <= 0L) continue
                val position = exo.currentPosition.coerceAtLeast(0L)
                if (position == lastReportedMs) continue
                lastReportedMs = position
                store.reportPlayhead(store.activeRendition()?.playback?.playUrl, position, duration)
            }
        }
    }

    /**
     * Watching is not keeping, and this says nothing either way. It creates the one opportunistic
     * row the playhead pump above needs in order to have anything to extend: the engine's playhead
     * entry point resolves a task by the watched address and no-ops when there is none, so a
     * preview that is never seeded leaves the whole ahead-of-playback path dead on arrival.
     *
     * Silent by contract. A preview nobody asked for must not be able to produce a gate, a spinner,
     * a toast, a Downloads row it cannot fill, or an evicted copy it did not want — [CacheEngineHolder]
     * gives the engine every one of those refusals, and none of them belongs on screen.
     */
    private fun seedPreviewFor(rendition: PlaybackRendition?) {
        val playback = rendition?.playback ?: return
        val url = playback.playUrl?.takeIf { it.isNotBlank() } ?: return
        val handle = playback.streamId?.takeIf { it.isNotBlank() } ?: return
        val engine = CacheEngineHolder.engine ?: return
        scope.launch {
            try {
                engine.seedPreview(
                    PreviewRequest(
                        key = CacheSessionKey(renditionKey = handle, url = url),
                        url = url,
                        expectedTotalBytes = rendition.print.sizeBytes.takeIf { it > 0L },
                        resumable = playback.resumable || playback.acceptsRanges == true,
                        printLabel = rendition.displayLabel(),
                    ),
                )
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                // The stream plays exactly as it would have. A preview is the only kind of cache
                // work that can fail without the viewer ever having a right to know.
            }
        }
    }

    /**
     * One Auto decision per [AUTO_QUALITY_TICK_MS]. Only ever while the viewer is actually
     * watching: while paused or buffering nothing is being fed, so nothing is known, and a
     * switch would be a guess.
     */
    private fun evaluateAutoQuality() {
        val director = store.autoQuality
        if (!director.isEnabled()) return
        val exo = player ?: return
        if (exo.playbackState != Player.STATE_READY || !exo.isPlaying) return
        val bundle = store.bundle.value ?: return
        val index = store.activeRenditionIndex.value
        val active = bundle.renditions.getOrNull(index) ?: return
        lastKnownPositionMs = maxOf(lastKnownPositionMs, runCatching { exo.currentPosition }.getOrDefault(0L))
        // Re-sync with reality first: a silent hop or a rank failover may have moved the rung.
        director.markPlaying(bandOfRendition(active))
        val from = director.currentBand
        val target = director.targetBand() ?: return
        if (target == from) return
        switchRungTo(bundle, index, active, target, from)
    }

    /**
     * Move playback to another rung of the SAME staged ladder, keeping the position. This is
     * the rung-level sibling of [FailoverDecision.AdvanceBackup]: one handle of ours is
     * swapped for another on our own redirector by [streamUrlForHandle], so the address the
     * player gets is still ours, only now addressed to the band Auto chose.
     *
     * The failover plan is rebuilt from the updated rung list because its runner-ups belong
     * to the rung, not to the slot in the list — leaving the old plan in place would hop a
     * later error back to the rung we just left. If that rebuild does not land on the index
     * we are playing (a multi-rank bundle), the switch is refused rather than guessed.
     */
    private fun switchRungTo(
        bundle: PlaybackBundle,
        index: Int,
        active: PlaybackRendition,
        targetBand: String,
        fromBand: String?,
    ) {
        val director = store.autoQuality
        val rung = director.rungFor(targetBand) ?: return
        if (rung.streamId == active.playback.streamId) return
        val newUrl = streamUrlForHandle(active.playback.playUrl, rung.streamId)
        if (newUrl == null) {
            director.markPlaying(fromBand)
            store.appendFailover(
                listOf(
                    FailoverRecord(
                        active.rank, active.releaseId, active.displayLabel(),
                        "auto wanted $targetBand", "skipped (no address of ours on that rung)",
                    ),
                ),
            )
            return
        }
        val swapped = active.copy(
            playback = active.playback.copy(
                playUrl = newUrl,
                streamId = rung.streamId,
                backupStreamIds = rung.backupHandles,
            ),
            print = active.print.copy(resolution = targetBand),
        )
        val updated = bundle.copy(renditions = bundle.renditions.toMutableList().also { it[index] = swapped })
        val machine = FailoverStateMachine(updated.renditions, updated.failurePolicy)
        if (machine.selectInitial() != index) {
            director.markPlaying(fromBand)
            store.appendFailover(
                listOf(
                    FailoverRecord(
                        active.rank, active.releaseId, active.displayLabel(),
                        "auto wanted $targetBand", "skipped (failover plan is multi-rank)",
                    ),
                ),
            )
            return
        }
        failover = machine
        store.replaceRendition(index, swapped)
        store.setAutoBand(targetBand)
        store.appendFailover(
            listOf(
                FailoverRecord(
                    swapped.rank, swapped.releaseId, swapped.displayLabel(),
                    "measured ${formatBitrate(director.estimateBps)}",
                    "auto moved ${fromBand ?: "the current rung"} → $targetBand",
                ),
            ),
        )
        pendingResumeMs = lastKnownPositionMs.takeIf { it > 0 }
        loadRenditionOf(updated, swapped)
    }

    private fun formatBitrate(bps: Long): String = when {
        bps >= 1_000_000 -> "%.1f Mbps".format(bps / 1_000_000.0)
        bps >= 1_000 -> "%d kbps".format(bps / 1_000)
        else -> "$bps bps"
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

        /**
         * How often Auto is allowed to move a rung. Comfortably longer than the switcher's
         * own smoothing window matters (a step down still needs five confirmed samples), and
         * short enough that a viewer on a dying link is off the too-high rung within a
         * re-buffer rather than within a scene.
         */
        const val AUTO_QUALITY_TICK_MS = 2_000L

        /**
         * How often the service offers the playhead to the offline cache. Longer than the UI's own
         * 200 ms clock on purpose: the engine answers one bounded pass per advance and then parks,
         * so anything faster is a database lookup per frame for a window that is tens of megabytes
         * wide. Five seconds is short enough that a viewer who seeks onto unbuffered ground has an
         * ahead-pass running before the player has re-buffered twice.
         */
        const val PLAYHEAD_PUMP_MS = 5_000L

        /** Loads worth measuring: media bytes. Subtitles and metadata would dilute the rate. */
        val MEASURABLE_TRACK_TYPES = setOf(C.TRACK_TYPE_DEFAULT, C.TRACK_TYPE_VIDEO, C.TRACK_TYPE_AUDIO)
    }
}
