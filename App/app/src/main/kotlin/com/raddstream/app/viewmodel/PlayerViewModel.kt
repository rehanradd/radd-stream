package com.raddstream.app.viewmodel

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.annotation.OptIn
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.C
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.raddstream.app.brand.Brand
import com.raddstream.app.player.AspectMode
import com.raddstream.app.player.AudioBoost
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.player.AudioTrackPolicy
import com.raddstream.app.player.AudioTrackRow
import com.raddstream.app.player.BingePrefetchPlanner
import com.raddstream.app.player.BingePreloadDecision
import com.raddstream.app.player.CacheAffordance
import com.raddstream.app.player.CacheEngineHolder
import com.raddstream.app.player.CacheSnapshot
import com.raddstream.app.player.CacheState
import com.raddstream.app.player.CalibrationState
import com.raddstream.app.player.DeferredOffsetReporter
import com.raddstream.app.player.EpisodeOffsets
import com.raddstream.app.player.EpisodeProgression
import com.raddstream.app.player.ExternalSubtitle
import com.raddstream.app.player.HandoffWhy
import com.raddstream.app.player.KeepResult
import com.raddstream.app.player.KeepUiState
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.NextEpisodeAction
import com.raddstream.app.player.PlaybackBundle
import com.raddstream.app.player.PlaybackMediaItemFactory
import com.raddstream.app.player.PlaybackRendition
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.player.PlayerUiState
import com.raddstream.app.player.QualityLadder
import com.raddstream.app.player.RippleState
import com.raddstream.app.player.RotationMode
import com.raddstream.app.player.ScreenZone
import com.raddstream.app.player.SleepMode
import com.raddstream.app.player.SleepTick
import com.raddstream.app.player.SleepTimer
import com.raddstream.app.player.StartResolution
import com.raddstream.app.player.SubtitleUiSettings
import com.raddstream.app.player.TrackUiOption
import com.raddstream.app.player.subtitle.SubtitleCue
import com.raddstream.app.player.subtitle.SubtitleFile
import com.raddstream.app.player.subtitle.SubtitleFormat
import com.raddstream.app.player.subtitle.SubtitleParser
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.streamRedirectUrl
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlin.math.sign
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * UI brain of the player. It does NOT own an ExoPlayer — [com.raddstream.app.player.PlaybackService]
 * does. This ViewModel drives that player through a Media3 [MediaController] (the same object
 * that backs notifications / lock screen / headsets) and keeps every MX-style control surface
 * state in one immutable [PlayerUiState].
 *
 * Created with `hiltViewModel()` from `PlayerScreen`.
 */
@HiltViewModel
@OptIn(UnstableApi::class)
class PlayerViewModel @Inject constructor(
    @ApplicationContext private val appContext: Context,
    private val apiProvider: ApiProvider,
    private val settingsRepository: ServerSettingsRepository,
    private val catalogRepository: CatalogRepository,
) : ViewModel() {

    private val store: PlayerSessionStore = PlayerSessionStore.Instance

    private var controller: MediaController? = null
    private var tickerJob: Job? = null
    private var keepJob: Job? = null
    private var settingsJob: Job? = null
    private var bingeResolveJob: Job? = null
    private var bingePrefetchJob: Job? = null

    private val sleepTimer = SleepTimer()

    /**
     * The binge policy plus the fire-once set it makes its caller own. Lives here because
     * the ViewModel is the only place that knows both the progress tick and the session
     * lifecycle; the planner itself never touches the player.
     */
    private val bingePlanner = BingePrefetchPlanner()

    /** The next episode's handle, once looked up; null means "not addressable yet". */
    private var nextEpisodeHandle: String? = null

    /** In-run resume memory; cross-launch persistence is a data-agent request (handoff). */
    private val resumeByTarget = HashMap<String, Long>()

    private val _ui = MutableStateFlow(PlayerUiState())
    val uiState: StateFlow<PlayerUiState> = _ui.asStateFlow()

    private val _events = MutableSharedFlow<PlayerEvent>(extraBufferCapacity = 8)
    val events: SharedFlow<PlayerEvent> = _events.asSharedFlow()

    /** The service-side player, exposed read-only so `PlayerView` can attach to it. */
    private val _player = MutableStateFlow<Player?>(null)
    val player: StateFlow<Player?> = _player.asStateFlow()

    /** Externally parsed subtitle (custom-render path). Null → native rendering only. */
    private var customSubtitleFile: SubtitleFile? = null

    init {
        connectController()
        observeStore()
        observeSettings()
    }

    /**
     * The two preferences the policy classes read. Collected, not sampled, so the settings
     * screen changing a value is felt by a player that is already running.
     */
    private fun observeSettings() {
        settingsJob?.cancel()
        settingsJob = viewModelScope.launch {
            settingsRepository.audioBoostLevel.collect { level ->
                _ui.update { it.copy(audioBoostLevel = AudioBoost.clampLevel(level)) }
                applyPlayerVolume()
            }
        }
        viewModelScope.launch {
            settingsRepository.preferredAudioLanguage.collect { language ->
                _ui.update { it.copy(preferredAudioLanguage = language) }
                applyPreferredAudioTrack()
            }
        }
    }

    // ── Service connection ───────────────────────────────────────────────────────

    private fun connectController() {
        val token = SessionToken(appContext, ComponentName(appContext, com.raddstream.app.player.PlaybackService::class.java))
        // MediaController.Builder in 1.3.1 has only buildAsync() (verified in source).
        val future = MediaController.Builder(appContext, token).buildAsync()
        future.addListener({
            try {
                val c = future.get()
                controller = c
                _player.value = c
                c.addListener(playerListener)
                _ui.update { it.copy(connected = true) }
                startTicker()
            } catch (t: Throwable) {
                _ui.update { it.copy(connectionError = "Playback service unavailable: ${t.message}") }
            }
        }, ContextCompat.getMainExecutor(appContext))
    }

    private val playerListener = object : Player.Listener {
        override fun onIsPlayingChanged(isPlaying: Boolean) {
            _ui.update { it.copy(isPlaying = isPlaying) }
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            _ui.update {
                it.copy(
                    isBuffering = playbackState == Player.STATE_BUFFERING,
                    isEnded = playbackState == Player.STATE_ENDED,
                )
            }
            if (playbackState == Player.STATE_ENDED) {
                rememberResume()
                handleSleepEndOfVideo()
            }
        }

        override fun onTracksChanged(tracks: Tracks) {
            _ui.update { state ->
                state.copy(
                    audioTracks = TrackMapper.options(tracks, C.TRACK_TYPE_AUDIO),
                    subtitleTracks = TrackMapper.options(tracks, C.TRACK_TYPE_TEXT),
                    frameRate = TrackMapper.selectedVideoFrameRate(tracks) ?: state.frameRate,
                )
            }
            // Tracks only become decidable now: the media item is prepared, so the audio
            // language the user set in Settings can be applied to the list the player just
            // reported. Also the first chance a fresh playback gets — a preference set before
            // the stream existed could not be honoured anywhere else.
            applyPreferredAudioTrack()
        }

        override fun onPlaybackParametersChanged(playbackParameters: PlaybackParameters) {
            _ui.update {
                it.copy(
                    speed = playbackParameters.speed,
                    // While boosting, the boost value is "the" speed; keep the flag honest.
                    boosting = it.boosting && playbackParameters.speed != it.speed,
                )
            }
        }
    }

    private fun observeStore() {
        viewModelScope.launch {
            store.bundle.collect { b ->
                _ui.update { it.copy(bundle = b, activeRendition = store.activeRendition()) }
                armQualityChoices()
                // A rung Auto moved to is the SAME episode in a different address, so the
                // binge policy must not be re-armed by it; only a new file or a new episode
                // is a new lifecycle. The cache session does change with the address.
                refreshKeepState()
                val key = bingeBundleKey(b)
                if (key != watchedBingeKey) {
                    watchedBingeKey = key
                    bingePlanner.reset()
                    nextEpisodeHandle = null
                    if (b != null) prepareBingePrefetch(b)
                }
            }
        }
        viewModelScope.launch {
            store.activeRenditionIndex.collect {
                _ui.update { it.copy(activeRendition = store.activeRendition()) }
                armQualityChoices()
                refreshKeepState()
            }
        }
        viewModelScope.launch {
            store.autoBand.collect { band -> _ui.update { it.copy(autoQualityBand = band) } }
        }
        viewModelScope.launch {
            store.failoverLog.collect { log -> _ui.update { it.copy(failoverLog = log) } }
        }
        viewModelScope.launch {
            store.settledBanner.collect { banner -> _ui.update { it.copy(settledBanner = banner) } }
        }
        viewModelScope.launch {
            store.giveUp.collect { pair -> _ui.update { it.copy(giveUp = pair) } }
        }
        viewModelScope.launch {
            store.nextEpisode.collect { action ->
                if (action != null) handleCrossEpisodeAction(action)
            }
        }
    }

    private var watchedBingeKey: String? = null

    private fun startTicker() {
        tickerJob?.cancel()
        var lastSleepTick = System.currentTimeMillis()
        tickerJob = viewModelScope.launch {
            while (true) {
                val c = controller
                if (c != null && c.isConnected) {
                    val now = System.currentTimeMillis()
                    _ui.update {
                        it.copy(
                            positionMs = c.currentPosition,
                            bufferedMs = bufferedOf(c),
                            durationMs = if (c.duration > 0) c.duration else it.durationMs,
                        )
                    }
                    // Sleep timer advance + fade (player volume = user volume × fade factor)
                    if (_ui.value.sleep.mode == SleepMode.COUNTDOWN) {
                        val tick = sleepTimer.onTick(now - lastSleepTick)
                        applySleep(tick)
                    }
                    tickBingePreload(_ui.value.positionMs, _ui.value.durationMs)
                    lastSleepTick = now
                }
                delay(200)
            }
        }
    }

    private fun bufferedOf(c: MediaController): Long =
        if (c.bufferedPosition > 0) c.bufferedPosition else c.currentPosition

    // ── Play entry points ────────────────────────────────────────────────────────

    /**
     * Route path `player/{streamId}/{title}`: one opaque handle of ours. The address the
     * player loads is our own redirector for that handle, built here — never a URL that
     * came from a scraper, and never one that names where the file lives.
     */
    fun startStreamHandle(streamId: String, title: String, startOverrideMs: Long? = null) {
        if (_ui.value.bundle?.renditions?.firstOrNull()?.playback?.streamId == streamId) return
        viewModelScope.launch {
            val playUrl = streamRedirectUrl(apiProvider.currentBaseUrl(), streamId)
            // Runner-ups of this rung, staged by the detail screen: handles only, so a
            // 403 mid-play costs one silent hop instead of a dialog and a quality drop.
            val bundle = PlaybackBundle.forStreamHandle(streamId = streamId, playUrl = playUrl,
                                                       title = title,
                                                       backupHandles = store.peekFailover(streamId))
            beginBundle(bundle, title, resumeKey = streamId, overrideMs = startOverrideMs)
        }
    }

    // ── The visible quality switch (Auto + one row per rung of this scope) ─────────

    /**
     * The ladder of the scope being watched. Held here rather than re-read from the store on
     * every tap because Auto moves playback onto a rung whose handle the detail screen never
     * staged a ladder under — the plan belongs to the scope, not to the launched address.
     */
    private var ladderPlan: PlayerSessionStore.AutoLadderPlan? = null

    /** The rung the server called best-and-playable, remembered so "Auto" can return to it. */
    private var autoRungHandle: String? = null

    /** Read the staged ladder for the address now playing, if this scope has one. */
    private fun armQualityChoices() {
        val handle = _ui.value.activeRendition?.playback?.streamId?.trim()?.takeIf { it.isNotEmpty() }
            ?: return
        val plan = store.peekAutoLadder(handle) ?: return
        ladderPlan = plan
        if (plan.auto) autoRungHandle = plan.startBand?.let { band ->
            plan.rungs.firstOrNull { it.band == band }?.streamId
        } ?: handle
        _ui.update {
            it.copy(
                qualityRungs = plan.rungs,
                qualityBand = plan.startBand ?: it.qualityBand,
                qualityAuto = plan.auto,
            )
        }
    }

    /**
     * Choose a rung, or give the choice back to Auto ([band] = `auto`).
     *
     * The position is carried over, which is the whole point of a quality switch: a viewer
     * who asks for Full HD mid-scene must not be sent back to the beginning. Switching to a
     * rung means starting playback on that rung's own handle — the address is still only ever
     * ours, and the ladder plus that rung's runner-ups are re-staged under it first so a CDN
     * that refuses still hops silently instead of showing an error.
     */
    fun selectQualityBand(band: String?) {
        val plan = ladderPlan ?: return
        val wantedAuto = band.isNullOrBlank() || band.equals(LadderForScope.AUTO, ignoreCase = true)
        val targetBand = if (wantedAuto) {
            autoRungHandle?.let { handle -> plan.rungs.firstOrNull { it.streamId == handle }?.band }
                ?: plan.startBand
        } else {
            band
        }
        val rung = plan.rungs.firstOrNull { it.band == targetBand } ?: return
        val active = _ui.value.activeRendition
        val auto = wantedAuto
        store.autoQuality.configure(plan.rungs, rung.band, auto)
        store.setAutoBand(if (auto) store.autoQuality.currentBand else null)
        _ui.update { it.copy(qualitySheetVisible = false, qualityBand = rung.band, qualityAuto = auto) }
        if (rung.streamId == active?.playback?.streamId) return

        val title = _ui.value.pendingTitle ?: active?.displayLabel() ?: Brand.name
        val positionMs = controller?.takeIf { it.isConnected }?.currentPosition ?: 0L
        ladderPlan = PlayerSessionStore.AutoLadderPlan(plan.rungs, rung.band, auto)
        store.stageFailover(rung.streamId, rung.backupHandles)
        store.stageAutoLadder(rung.streamId, plan.rungs, rung.band, auto)
        startStreamHandle(rung.streamId, title, startOverrideMs = positionMs.takeIf { it > 1_000 })
    }

    fun showQualitySheet() {
        if (_ui.value.qualityRungs.isEmpty()) return
        _ui.update { it.copy(qualitySheetVisible = true) }
    }

    fun hideQualitySheet() {
        _ui.update { it.copy(qualitySheetVisible = false) }
    }

    /** Full contract path: ordered candidate links (API_V2 §5 PlayBundle). */
    fun startBundle(bundle: PlaybackBundle, title: String, explicitStartMs: Long? = null) {
        store.installBundle(bundle)
        val key = bundle.target.workKey
            ?: bundle.renditions.firstOrNull()?.playback?.playUrl
            ?: "b${bundle.session.id}"
        val resume = explicitStartMs ?: resumeByTarget[key] ?: 0L
        val first = bundle.renditions.firstOrNull()
        val offset = if (first == null) null else EpisodeOffsets.resolveStart(first, bundle.target, store.learnedOffsets)
        val offsetMs = (offset as? StartResolution.At)?.positionMs
        when {
            explicitStartMs != null ->
                loadNow(title, key, resumePosition = 0, override = explicitStartMs)

            offset is StartResolution.NeedsCalibration -> {
                // Packed season without offsets: show the pack warning UI, start at 0.
                _ui.update {
                    it.copy(calibration = CalibrationState(targetEpisode = bundle.target.episode, warning = offset.packWarning))
                }
                loadNow(title, key, resumePosition = resume, override = null)
            }

            offsetMs != null && offsetMs > 0 ->
                // Packed file: "start Episode 5" == seek into the file at READY.
                loadNow(title, key, resumePosition = 0, override = offsetMs)

            resume > RESUME_PROMPT_THRESHOLD_MS ->
                _ui.update { it.copy(resumeOfferMs = resume, pendingResumeKey = key, pendingTitle = title) }

            else -> loadNow(title, key, resumePosition = resume, override = null)
        }
    }

    private fun beginBundle(
        bundle: PlaybackBundle,
        title: String,
        resumeKey: String,
        overrideMs: Long? = null,
    ) {
        store.installBundle(bundle)
        val resume = resumeByTarget[resumeKey] ?: 0L
        when {
            // A quality switch lands on a new address mid-scene: the position is the one
            // thing it must not lose, so it is an override, never a "resume from?" prompt.
            overrideMs != null -> loadNow(title, resumeKey, resumePosition = 0, override = overrideMs)

            resume > RESUME_PROMPT_THRESHOLD_MS ->
                _ui.update { it.copy(resumeOfferMs = resume, pendingResumeKey = resumeKey, pendingTitle = title) }

            else -> loadNow(title, resumeKey, resumePosition = 0, override = null)
        }
    }

    private fun loadNow(title: String, resumeKey: String, resumePosition: Long, override: Long?) {
        store.requestLoad(title = title, resumePositionMs = resumePosition, startOverrideMs = override)
        _ui.update { it.copy(resumeOfferMs = null, pendingResumeKey = null, giveUp = null, pendingTitle = title) }
        resumeByTarget[resumeKey] = resumePosition.coerceAtLeast(resumeByTarget[resumeKey] ?: 0L)
    }

    /** Answer to the "Resume from 12:34?" dialog (MX "resume playback" prompt). */
    fun resolveResume(resume: Boolean) {
        val ms = _ui.value.resumeOfferMs ?: return
        val key = _ui.value.pendingResumeKey ?: return
        val title = _ui.value.pendingTitle ?: Brand.name
        if (resume) {
            loadNow(title, key, resumePosition = ms, override = null)
        } else {
            resumeByTarget.remove(key)
            loadNow(title, key, resumePosition = 0, override = null)
        }
    }

    /** "Play again from" — MX dialog to start at an arbitrary position. */
    fun playFrom(positionMs: Long) {
        val title = _ui.value.activeRendition?.displayLabel() ?: Brand.name
        val key = store.bundle.value?.target?.workKey ?: title
        loadNow(title, key, resumePosition = 0, override = positionMs.coerceAtLeast(0))
    }

    private fun rememberResume() {
        val c = controller ?: return
        val bundle = store.bundle.value ?: return
        val key = bundle.target.workKey ?: c.currentMediaItem?.mediaId ?: return
        val pos = c.currentPosition
        if (pos > 5_000 && pos < c.duration) resumeByTarget[key] = pos else resumeByTarget.remove(key)
    }

    // ── Transport & value controls ───────────────────────────────────────────────

    fun togglePlayPause() {
        val c = controller ?: return
        if (c.isPlaying) {
            rememberResume()
            c.pause()
        } else {
            if (c.playbackState == Player.STATE_IDLE) c.prepare()
            c.play()
        }
    }

    fun seekBy(deltaMs: Long) {
        val c = controller ?: return
        if (!_ui.value.seekEnabled) return
        // Media3 1.3.1's Player has no seekBy(); an absolute relative-position seek is equivalent.
        c.seekTo((c.currentPosition + deltaMs).coerceAtLeast(0L))
    }

    fun seekTo(positionMs: Long) {
        val c = controller ?: return
        if (!_ui.value.seekEnabled) return
        c.seekTo(positionMs.coerceAtLeast(0))
    }

    /** Double-tap ripple feedback for the screen (side + seconds, animated by nonce). */
    fun showRipple(zone: ScreenZone, deltaMs: Long) {
        _ui.update { it.copy(ripple = RippleState(zone, deltaMs, System.nanoTime())) }
    }

    fun clearRipple() {
        _ui.update { it.copy(ripple = null) }
    }

    /** Frame-step: 1/fps seek (Media3 1.3.1 has no frame API — PLAYER_SPEC §2.3). */
    fun stepFrame(direction: Int) {
        val fps = _ui.value.frameRate?.takeIf { it > 0f } ?: 24f
        val delta = (1000f / fps) * direction.sign
        seekTo(_ui.value.positionMs + delta.toLong())
    }

    fun setSpeed(speed: Float) {
        val c = controller ?: return
        val clamped = speed.coerceIn(0.25f, 4f)
        _ui.update { it.copy(boosting = false) }
        c.playbackParameters = PlaybackParameters(clamped)
    }

    /** Long-press speed boost (MX): the screen MUST call [endBoost] on release. */
    fun beginBoost(boostSpeed: Float = 2f) {
        val c = controller ?: return
        if (_ui.value.boosting) return
        _ui.update { it.copy(boosting = true) }
        c.playbackParameters = PlaybackParameters(boostSpeed.coerceIn(0.25f, 4f))
    }

    fun endBoost() {
        val c = controller ?: return
        if (!_ui.value.boosting) return
        val restore = _ui.value.speed.coerceIn(0.25f, 4f)
        _ui.update { it.copy(boosting = false) }
        c.playbackParameters = PlaybackParameters(restore)
    }

    /**
     * The user's own volume 0..1, as the right-half gesture sets it. The value handed to
     * the player is this times the persisted boost, clamped into the 0..1 contract by
     * [AudioBoostUi.effectivePlayerGain] — see [applyPlayerVolume].
     */
    fun setUserVolume(volume: Float) {
        val clamped = if (volume.isFinite()) volume.coerceIn(0f, 1f) else 1f
        _ui.update { it.copy(userVolume = clamped) }
        applyPlayerVolume()
    }

    /**
     * The audio level control (1.0 = untouched, [AudioBoost.MAX] = the 200% request). Stored
     * through the same DataStore the settings screen writes, so a level mixed in the player
     * is the level the next episode starts with and the one the settings screen shows.
     */
    fun setAudioBoostLevel(level: Float) {
        val clamped = AudioBoost.clampLevel(level)
        _ui.update { it.copy(audioBoostLevel = clamped) }
        applyPlayerVolume()
        viewModelScope.launch { settingsRepository.saveAudioBoostLevel(clamped) }
    }

    /**
     * The one place that writes `Player.setVolume`. Three inputs multiply into one legal
     * number: the persisted boost, the user's own volume and the sleep fade — each clamped
     * only once, at the end, because the platform's contract is the product, not any one
     * factor. The boost can never push the result past 1.0; what it does buy is headroom
     * below the ceiling, which is why the caption comes from
     * [AudioBoostUi.honestSummary] and not from the requested number.
     */
    private fun applyPlayerVolume() {
        val state = _ui.value
        val fade = if (state.sleep.mode == SleepMode.COUNTDOWN) {
            SleepTimer.volumeFactorFor(state.sleep.remainingMs, state.sleep.fadeMs)
        } else {
            1f
        }
        val safeFade = if (fade.isFinite()) fade.coerceIn(0f, 1f) else 1f
        controller?.volume = AudioBoostUi.effectivePlayerGain(state.audioBoostLevel, state.userVolume) * safeFade
    }

    fun retryCurrentCandidates() {
        val title = _ui.value.activeRendition?.displayLabel() ?: Brand.name
        store.clearGaveUp()
        store.requestLoad(title = title, resumePositionMs = _ui.value.positionMs)
    }

    /** Manual "next episode" button — same event path as auto-advance at media end. */
    fun requestNextEpisode() {
        val bundle = store.bundle.value
        val target = bundle?.target
        if (target == null || (target.episode <= 0 && target.season <= 0)) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("No episode context on this link"))
            }
            return
        }
        viewModelScope.launch {
            _events.emit(
                PlayerEvent.PlayNextEpisode(
                    workKey = target.workKey,
                    postId = target.id.takeIf { it > 0 },
                    season = target.season,
                    episode = (target.episode.coerceAtLeast(1)) + 1,
                ),
            )
        }
    }

    // ── Smart binge pre-caching ──────────────────────────────────────────────────

    /**
     * Start looking up the next episode's handle while the current one is still playing, so
     * the policy has something to ask for at the threshold instead of discovering at 85% that
     * nobody ever resolved the successor.
     *
     * Skipped when the next episode lives in THIS file (a packed season whose offset the
     * server or the learned ledger already knows): there is no second address to warm, and
     * the in-file advance the service performs on END is the whole feature there. That path
     * is left exactly as it was.
     */
    private fun prepareBingePrefetch(bundle: PlaybackBundle) {
        val target = bundle.target
        val rendition = store.activeRendition() ?: bundle.renditions.firstOrNull()
        val isSeries = EpisodeProgression.seriesLikeWorkType(target.workType) || target.episode > 0
        if (!isSeries || target.id <= 0 || rendition == null) return
        if (nextEpisodeIsInThisFile(bundle, rendition)) return
        val nextEpisode = target.episode.coerceAtLeast(1) + 1
        bingeResolveJob?.cancel()
        bingeResolveJob = viewModelScope.launch {
            val ladder = catalogRepository.getPostDetail(target.id)
                ?.let { detail -> QualityLadder.forNumberedScope(detail.optionGroups, target.season.takeIf { it > 0 }, nextEpisode) }
                ?: LadderForScope.EMPTY
            nextEpisodeHandle = ladder.resolvedFor(LadderForScope.AUTO)?.streamId?.takeIf { it.isNotBlank() }
        }
    }

    /** True when the successor's start position in this same file is already known. */
    private fun nextEpisodeIsInThisFile(bundle: PlaybackBundle, rendition: PlaybackRendition): Boolean {
        val coverage = rendition.coverage
        if (!coverage.isPacked()) return false
        val target = bundle.target
        val next = target.episode.coerceAtLeast(1) + 1
        val season = coverage.season.takeIf { it > 0 } ?: target.season
        val known = coverage.episodes.any { it.number == next } ||
            store.learnedOffsets.lookup(target.workKey, season, next, rendition.print.label) != null
        // A pack that simply runs on (no chapter row) still needs no second address, so it
        // counts as in-file: the service seeks at END and there is nothing to pre-fetch.
        return known || coverage.lastEpisode == 0 || next <= coverage.lastEpisode
    }

    /**
     * One binge tick: ask the policy, and act on a real request exactly once.
     *
     * WHAT THE ACT HONESTLY IS: [BingePreloader] emits a request for the head bytes of the
     * next episode because the cache boundary it was written against has no head-pull entry
     * point — only whole-file [ProgressiveCacheEngine.adopt] — and inventing one is the data
     * agent's call, not this wiring's. So the executable part today is the one thing that
     * genuinely costs nothing and genuinely speeds the transition: ask our own redirector
     * about that handle (`redirect=0`), which resolves and caches the upstream link
     * server-side and proves the handle is alive before the viewer lands on it. The message
     * says exactly that, never "downloaded".
     */
    private fun tickBingePreload(positionMs: Long, durationMs: Long) {
        val bundle = store.bundle.value ?: return
        val target = bundle.target
        val isSeries = EpisodeProgression.seriesLikeWorkType(target.workType) || target.episode > 0
        val decision = bingePlanner.tick(positionMs, durationMs, isSeries, nextEpisodeHandle)
        if (decision is BingePreloadDecision.PrefetchNextHead) prefetchNextEpisodeHead(decision.handle)
    }

    private fun prefetchNextEpisodeHead(handle: String) {
        bingePrefetchJob?.cancel()
        bingePrefetchJob = viewModelScope.launch {
            val answer = runCatching { catalogRepository.resolveStream(handle) }.getOrNull()
            // `streamId` is the model's own "this answer is usable" test: a successful lookup
            // that produced no handle of ours is a false success and says nothing to the user.
            if (answer?.streamId == null) return@launch
            _events.emit(
                PlayerEvent.Message("Next episode ready — its link is live, so advancing will not wait on a lookup"),
            )
        }
    }

    private fun bingeBundleKey(bundle: PlaybackBundle?): String? = bundle?.let {
        "${it.session.id}-${it.target.workKey}-${it.target.season}-${it.target.episode}-${it.target.id}"
    }

    // ── Sheet visibility ─────────────────────────────────────────────────────────

    fun showSpeedSheet() {
        _ui.update { it.copy(speedSheetVisible = true) }
    }

    fun hideSpeedSheet() {
        _ui.update { it.copy(speedSheetVisible = false) }
    }

    fun showTracksSheet() {
        _ui.update { it.copy(tracksSheetVisible = true) }
    }

    fun hideTracksSheet() {
        _ui.update { it.copy(tracksSheetVisible = false) }
    }

    fun showSubtitleSheet() {
        _ui.update { it.copy(subtitleSheetVisible = true) }
    }

    fun hideSubtitleSheet() {
        _ui.update { it.copy(subtitleSheetVisible = false) }
    }

    fun showPrintSheet() {
        _ui.update { it.copy(printSheetVisible = true) }
    }

    fun hidePrintSheet() {
        _ui.update { it.copy(printSheetVisible = false) }
    }

    fun showSleepSheet() {
        _ui.update { it.copy(sleepSheetVisible = true) }
    }

    fun hideSleepSheet() {
        _ui.update { it.copy(sleepSheetVisible = false) }
    }

    fun showPlayFromDialog() {
        _ui.update { it.copy(playFromDialogVisible = true) }
    }

    fun hidePlayFromDialog() {
        _ui.update { it.copy(playFromDialogVisible = false) }
    }

    // ── Aspect / rotation / lock / audio-only ────────────────────────────────────

    fun cycleAspect() {
        _ui.update { it.copy(aspect = AspectMode.nextOf(it.aspect)) }
    }

    fun setAspect(mode: AspectMode) {
        _ui.update { it.copy(aspect = mode) }
    }

    fun cycleRotation() {
        _ui.update { it.copy(rotation = RotationMode.nextOf(it.rotation)) }
    }

    fun setLocked(locked: Boolean) {
        _ui.update { it.copy(locked = locked) }
    }

    fun toggleAudioOnly() {
        val c = controller ?: return
        val to = !_ui.value.audioOnly
        // Background/audio-only playback: video renderer off, audio keeps running via session.
        c.trackSelectionParameters = c.trackSelectionParameters.buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_VIDEO, to)
            .build()
        _ui.update { it.copy(audioOnly = to) }
    }

    /**
     * MX "downmix to stereo" analogue: 1.3.1 cannot downmix, but can restrict SELECTION to
     * stereo tracks (setMaxAudioChannelCount verified). Documented in PLAYER_SPEC §2.3.
     */
    fun toggleStereoOnly() {
        val c = controller ?: return
        val to = !_ui.value.stereoOnly
        c.trackSelectionParameters = c.trackSelectionParameters.buildUpon()
            .setMaxAudioChannelCount(if (to) 2 else Integer.MAX_VALUE)
            .build()
        _ui.update { it.copy(stereoOnly = to) }
    }

    // ── Tracks: audio & subtitle selection ───────────────────────────────────────

    fun selectAudioTrack(option: TrackUiOption?) = selectTrack(C.TRACK_TYPE_AUDIO, option)

    /** null → subtitles off. */
    fun selectSubtitleTrack(option: TrackUiOption?) = selectTrack(C.TRACK_TYPE_TEXT, option)

    /**
     * Apply the user's audio language to the tracks the player just reported.
     *
     * [AudioTrackPolicy.pickPreferred] returns null in the two cases where forcing a
     * selection would make things worse — the stream has nothing in that language, and the
     * language is already playing — so a null answer is honoured as "change nothing" rather
     * than second-guessed here. Media3's own locale heuristic is left in charge exactly when
     * the user never expressed a preference.
     */
    private fun applyPreferredAudioTrack() {
        val state = _ui.value
        val preferred = state.preferredAudioLanguage?.takeIf { it.isNotBlank() } ?: return
        if (controller == null) return
        val picked = AudioTrackPolicy.pickPreferred(state.audioTrackRows(), preferred) ?: return
        if (picked == state.selectedAudioId) return
        val option = state.audioTracks.firstOrNull { it.id == picked } ?: return
        selectAudioTrack(option)
    }

    /**
     * The audio-track cycle affordance: the next playable track, wrapping. Refused out loud
     * when there is nothing to cycle between, because a button that silently does nothing
     * reads as a broken button.
     */
    fun cycleAudioTrack() {
        val state = _ui.value
        val next = AudioTrackPolicy.nextInCycle(state.audioTrackRows(), state.selectedAudioId)
        if (next == null) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("Only one audio track on this print — nothing to switch to"))
            }
            return
        }
        val option = state.audioTracks.firstOrNull { it.id == next } ?: return
        selectAudioTrack(option)
        val name = AudioTrackPolicy.nameFor(option.language)
        viewModelScope.launch {
            _events.emit(PlayerEvent.Message("Audio: ${name ?: option.label}"))
        }
    }

    private fun selectTrack(trackType: Int, option: TrackUiOption?) {
        val c = controller ?: return
        var builder = c.trackSelectionParameters.buildUpon()
            .clearOverridesOfType(trackType)
        if (trackType == C.TRACK_TYPE_TEXT) {
            builder = builder.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, option == null)
        }
        if (option != null) {
            builder = builder.setOverrideForType(
                TrackSelectionOverride(option.group, listOf(option.trackIndex)),
            )
        }
        c.trackSelectionParameters = builder.build()
        _ui.update {
            if (trackType == C.TRACK_TYPE_AUDIO) it.copy(selectedAudioId = option?.id)
            else it.copy(selectedSubtitleId = option?.id)
        }
    }

    // ── Subtitles: settings + external files ─────────────────────────────────────

    fun setSubtitleSettings(settings: SubtitleUiSettings) {
        _ui.update { it.copy(subtitle = settings.clamped()) }
    }

    /** Bundle-provided or SAF-picked external subtitle. SRT/VTT → custom render (delay!),
     *  exotic formats → Media3 native SubtitleConfiguration (no delay in 1.3.1). */
    fun addExternalSubtitle(url: String, label: String, formatHint: String) {
        viewModelScope.launch {
            val ext = ExternalSubtitle(
                url = url,
                label = label,
                formatHint = formatHint,
                customRendered = PlaybackMediaItemFactory.isCustomRenderable(formatHint),
            )
            if (ext.customRendered) {
                val text = fetchSubtitleText(url)
                if (text == null) {
                    _events.emit(PlayerEvent.Message("Could not load subtitle file: $label"))
                    return@launch
                }
                customSubtitleFile = SubtitleParser.parse(text, SubtitleFormat.fromFileNameOrMime(formatHint))
                _ui.update { it.copy(customSubtitleLoaded = label) }
            } else {
                val bundle = store.bundle.value
                val index = store.activeRenditionIndex.value
                val rendition = bundle?.renditions?.getOrNull(index)
                val c = controller
                if (bundle == null || rendition == null || c == null || c.mediaItemCount == 0) return@launch
                val natives = _ui.value.nativeExternals + ext
                val item = PlaybackMediaItemFactory.build(
                    rendition = rendition,
                    target = bundle.target,
                    title = _ui.value.pendingTitle ?: rendition.displayLabel(),
                    externalSubtitles = natives,
                )
                c.replaceMediaItem(index, item)
                c.seekTo(_ui.value.positionMs)
                c.prepare()
                _ui.update { it.copy(nativeExternals = natives) }
            }
        }
    }

    fun removeCustomSubtitle() {
        customSubtitleFile = null
        _ui.update { it.copy(customSubtitleLoaded = null) }
    }

    private suspend fun fetchSubtitleText(url: String): String? = withContext(Dispatchers.IO) {
        try {
            when {
                url.startsWith("content://") ->
                    appContext.contentResolver.openInputStream(Uri.parse(url))?.use { stream ->
                        stream.bufferedReader().readText().takeIf { it.length < MAX_SUBTITLE_BYTES }
                    }
                url.startsWith("http://") || url.startsWith("https://") -> {
                    val request = okhttp3.Request.Builder().url(url).build()
                    okhttp3.OkHttpClient().newCall(request).execute().use { response ->
                        if (!response.isSuccessful) null
                        else response.body?.string()?.takeIf { it.length < MAX_SUBTITLE_BYTES }
                    }
                }
                else -> null
            }
        } catch (_: Exception) {
            null
        }
    }

    /** Active subtitle lines for the custom overlay (delay applied here — MX subtitle sync). */
    fun overlayCues(positionMs: Long): List<SubtitleCue> {
        val file = customSubtitleFile ?: return emptyList()
        return file.activeCues(positionMs, _ui.value.subtitle.delayMs)
    }

    // ── Sleep timer (fade-out per MX behavior) ───────────────────────────────────

    fun startSleepCountdown(ms: Long) {
        sleepTimer.start(ms)
        _ui.update { it.copy(sleep = sleepTimer.snapshot()) }
    }

    fun sleepAtVideoEnd() {
        sleepTimer.armEndOfVideo()
        _ui.update { it.copy(sleep = sleepTimer.snapshot()) }
    }

    fun cancelSleep() {
        sleepTimer.cancel()
        _ui.update { it.copy(sleep = sleepTimer.snapshot()) }
        applyPlayerVolume() // restore the full mix immediately
    }

    private fun applySleep(tick: SleepTick) {
        _ui.update { it.copy(sleep = tick.state) }
        // The fade multiplies the SAME product as the boost (see [applyPlayerVolume]); two
        // writers of `volume` would each overwrite the other's factors.
        applyPlayerVolume()
        if (tick.shouldPause) {
            controller?.pause()
            viewModelScope.launch { _events.emit(PlayerEvent.Message("Sleep timer — playback paused")) }
            cancelSleep()
        }
    }

    /** END_OF_VIDEO sleep is enforced on the ended signal. */
    private fun handleSleepEndOfVideo() {
        if (_ui.value.sleep.mode == SleepMode.END_OF_VIDEO) {
            cancelSleep()
            viewModelScope.launch { _events.emit(PlayerEvent.Message("Sleep timer — video finished")) }
        }
    }

    // ── Episode progression + offsets ────────────────────────────────────────────

    private fun handleCrossEpisodeAction(action: NextEpisodeAction) {
        store.clearNextEpisode()
        when (action) {
            is NextEpisodeAction.NextBundleRequest -> viewModelScope.launch {
                _events.emit(
                    PlayerEvent.PlayNextEpisode(
                        workKey = action.workKey,
                        postId = action.postId,
                        season = action.season,
                        episode = action.nextEpisode,
                    ),
                )
            }

            is NextEpisodeAction.CalibrationNeeded -> _ui.update {
                it.copy(
                    calibration = CalibrationState(
                        targetEpisode = action.nextEpisode,
                        warning = action.packWarning
                            ?: "Packed file — where does Episode ${action.nextEpisode} start?",
                    ),
                )
            }

            else -> Unit
        }
    }

    /** "Mark current position as Episode N start" — calibrates the pack offset. */
    fun calibrateEpisodeStart(episodeNumber: Int) {
        val bundle = store.bundle.value ?: return
        val rendition = store.activeRendition() ?: return
        val position = controller?.currentPosition ?: _ui.value.positionMs
        val report = EpisodeOffsets.buildReport(
            target = bundle.target,
            rendition = rendition,
            episodeNumber = episodeNumber,
            offsetMs = position,
            chapterTitle = null,
        )
        if (report == null) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("This link has no stable work identity — offset not reported"))
            }
            return
        }
        store.learnedOffsets.learn(report, store.offsetReporter)
        _ui.update { it.copy(calibration = null) }
        val queued = store.offsetReporter is DeferredOffsetReporter
        viewModelScope.launch {
            _events.emit(
                PlayerEvent.Message(
                    "Episode $episodeNumber marked at ${(position / 1000L).formatTime()}" +
                        (if (queued) " (queued for server)" else ""),
                ),
            )
        }
    }

    /** Open the calibration dialog manually (menu path) for the current target episode. */
    fun openCalibration() {
        val bundle = store.bundle.value
        val current = bundle?.target?.episode?.takeIf { it > 0 } ?: 1
        _ui.update {
            it.copy(
                calibration = CalibrationState(
                    targetEpisode = current,
                    warning = "Scrub/pause exactly where this episode starts in the packed " +
                        "file, then mark it. Offsets feed the shared cat_offsets ledger.",
                ),
            )
        }
    }

    fun dismissCalibration() {
        _ui.update { it.copy(calibration = null) }
    }

    // ── Signature feature: watching → keeping ────────────────────────────────────

    /** Re-attaches the cache observer to the CURRENT rendition (called on every switch). */
    fun refreshKeepState() {
        keepJob?.cancel()
        latestSnapshot = null
        val engine = CacheEngineHolder.engine
        val key = store.cacheKey()
        if (engine == null || key == null) {
            _ui.update { it.copy(keep = KeepUiState.Unavailable, keepRequested = false) }
            return
        }
        keepJob = viewModelScope.launch {
            engine.observe(key).collect { snapshot ->
                latestSnapshot = snapshot
                _ui.update { it.copy(keep = CacheAffordance.uiStateFor(snapshot, it.keepRequested)) }
            }
        }
    }

    private var latestSnapshot: CacheSnapshot? = null

    /** The *Keep this* button. Hands engine position + already-fetched bytes, never restarts. */
    fun keepCurrent() {
        val engine = CacheEngineHolder.engine
        val key = store.cacheKey()
        val c = controller
        if (engine == null || key == null) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("Download engine not wired into this build yet"))
            }
            return
        }
        val rendition = store.activeRendition() ?: return
        _ui.update { it.copy(keepRequested = true) }
        viewModelScope.launch {
            val request = CacheAffordance.buildAdoptRequest(
                key = key,
                snapshot = latestSnapshot,
                positionMs = c?.currentPosition ?: _ui.value.positionMs,
                bufferedMs = c?.bufferedPosition ?: _ui.value.positionMs,
                durationMs = _ui.value.durationMs,
                expectedTotalBytes = rendition.print.sizeBytes.takeIf { it > 0 },
                resumable = rendition.playback.resumable || rendition.playback.acceptsRanges == true,
                printLabel = rendition.displayLabel(),
            )
            val result = try {
                engine.adopt(request)
            } catch (t: Throwable) {
                KeepResult.Failed(t.message ?: "engine error")
            }
            _ui.update { it.copy(keep = keepUiFor(result), keepRequested = result is KeepResult.Stored) }
            _events.emit(PlayerEvent.Message(keepMessage(result)))
        }
    }

    private fun keepUiFor(result: KeepResult): KeepUiState = when (result) {
        is KeepResult.Stored -> KeepUiState.Stored(result.playableOffline, null)
        is KeepResult.OnlyPlayableInApp -> KeepUiState.Blocked(
            CacheState.APP_PRIVATE_ONLY,
            "Kept — playable in ${Brand.shortName} only (${result.ttlSeconds?.let { "${it / 3600} h" } ?: "TTL unknown"})",
        )
        is KeepResult.StorageFull -> KeepUiState.Blocked(
            CacheState.STORAGE_FULL,
            "Storage full: need ${CacheAffordance.formatBytes(result.requiredBytes)}, " +
                "${CacheAffordance.formatBytes(result.availableBytes)} free",
        )
        is KeepResult.Interrupted -> KeepUiState.Blocked(
            CacheState.INTERRUPTED,
            "Interrupted at ${CacheAffordance.formatBytes(result.fetchedBytes)}" +
                (if (result.willAutoResume) " — resuming" else ""),
        )
        is KeepResult.Failed -> KeepUiState.Blocked(CacheState.FAILED, result.message)
        KeepResult.EngineNotWired -> KeepUiState.Unavailable
    }

    private fun keepMessage(result: KeepResult): String = when (result) {
        is KeepResult.Stored -> "Kept for offline"
        is KeepResult.OnlyPlayableInApp -> "Kept — file is app-private (playable here only)"
        is KeepResult.StorageFull -> "Storage full — free up space and keep again"
        is KeepResult.Interrupted -> "Keep interrupted — will resume from already-saved bytes"
        is KeepResult.Failed -> "Keep failed: ${result.message}"
        KeepResult.EngineNotWired -> "Keep engine not available in this build"
    }

    // ── GiveUp / external handoff helpers for the screen ────────────────────────

    fun openWithExternalPlayer() {
        val url = store.activeRendition()?.playback?.playUrl ?: return
        viewModelScope.launch { _events.emit(PlayerEvent.OpenExternalPlayer(url)) }
    }

    /** User dismissed the giveUp card. */
    fun dismissGiveUp() {
        store.clearGaveUp()
    }

    fun dismissSettledBanner() {
        store.clearSettledBanner()
        _ui.update { it.copy(settledBanner = null) }
    }

    override fun onCleared() {
        rememberResume()
        tickerJob?.cancel()
        keepJob?.cancel()
        settingsJob?.cancel()
        bingeResolveJob?.cancel()
        bingePrefetchJob?.cancel()
        _player.value = null
        controller?.removeListener(playerListener)
        controller?.release()
        controller = null
        super.onCleared()
    }

    companion object {
        const val RESUME_PROMPT_THRESHOLD_MS = 10_000L
        const val MAX_SUBTITLE_BYTES = 4_000_000
    }
}

/** Long → "h:mm:ss" / "m:ss" — top-level so both ViewModel and UI can reuse it. */
fun Long.formatTime(): String {
    val totalSeconds = this / 1000
    val seconds = totalSeconds % 60
    val minutes = (totalSeconds / 60) % 60
    val hours = totalSeconds / 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds)
    else "%d:%02d".format(minutes, seconds)
}

/** What the screen must route elsewhere (next-episode bundle, external hand-off). */
sealed class PlayerEvent {
    data class Message(val text: String) : PlayerEvent()
    data class PlayNextEpisode(val workKey: String?, val postId: Int?, val season: Int, val episode: Int) : PlayerEvent()
    data class OpenExternalPlayer(val url: String) : PlayerEvent()
}

@OptIn(UnstableApi::class)
internal object TrackMapper {

    /** Rows for the audio/text selection sheets, rebuilt from the controller's [Tracks]. */
    fun options(tracks: Tracks, trackType: Int): List<TrackUiOption> {
        val out = ArrayList<TrackUiOption>()
        tracks.groups.forEachIndexed { groupIndex, group ->
            if (group.type != trackType) return@forEachIndexed
            for (i in 0 until group.length) {
                val format = group.getTrackFormat(i)
                val fallback = if (trackType == C.TRACK_TYPE_AUDIO) "Audio ${i + 1}" else "Subtitle ${i + 1}"
                out.add(
                    TrackUiOption(
                        id = "g$groupIndex-t$i",
                        group = group.mediaTrackGroup,
                        trackIndex = i,
                        label = (format.label ?: format.language ?: fallback).toString(),
                        language = format.language,
                        supported = group.isTrackSupported(i),
                        selected = group.isTrackSelected(i),
                    ),
                )
            }
        }
        return out
    }

    /** Selected video fps for frame-stepping math; null when unknown (Format.frameRate field). */
    fun selectedVideoFrameRate(tracks: Tracks): Float? {
        for (group in tracks.groups) {
            if (group.type != C.TRACK_TYPE_VIDEO) continue
            for (i in 0 until group.length) {
                if (group.isTrackSelected(i)) {
                    val rate = group.getTrackFormat(i).frameRate
                    if (rate > 0f) return rate
                }
            }
        }
        return null
    }
}
