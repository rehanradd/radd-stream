package com.raddstream.app.viewmodel

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.C
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.VideoSize
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.raddstream.app.brand.Brand
import com.raddstream.app.player.AbRepeat
import com.raddstream.app.player.AspectMode
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.player.AudioTrackPolicy
import com.raddstream.app.player.AudioTrackRow
import com.raddstream.app.player.AutoplayCountdown
import com.raddstream.app.player.BingePrefetchPlanner
import com.raddstream.app.player.BingePreloadDecision
import com.raddstream.app.player.CacheAffordance
import com.raddstream.app.player.CacheSessionKey
import com.raddstream.app.player.PreviewRequest
import com.raddstream.app.player.CacheEngineHolder
import com.raddstream.app.player.CacheSnapshot
import com.raddstream.app.player.CacheState
import com.raddstream.app.player.CalibrationState
import com.raddstream.app.player.DataSaver
import com.raddstream.app.player.DeferredOffsetReporter
import com.raddstream.app.player.directVideoIsHls
import com.raddstream.app.player.directVideoMime
import com.raddstream.app.player.directVideoTitle
import com.raddstream.app.player.EpisodeOffsets
import com.raddstream.app.player.EpisodeProgression
import com.raddstream.app.player.ExternalSubtitle
import com.raddstream.app.player.KeepResult
import com.raddstream.app.player.KeepUiState
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.LadderRung
import com.raddstream.app.player.LanguageDefaults
import com.raddstream.app.player.NextEpisodeAction
import com.raddstream.app.player.PlaybackBundle
import com.raddstream.app.player.PlaybackInfo
import com.raddstream.app.player.PlaybackMediaItemFactory
import com.raddstream.app.player.PlaybackRendition
import com.raddstream.app.player.PlayTarget
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.player.PrintInfo
import com.raddstream.app.player.SessionInfo
import com.raddstream.app.player.ShareMoment
import com.raddstream.app.player.PlayerUiState
import com.raddstream.app.player.QualityLadder
import com.raddstream.app.player.RippleState
import com.raddstream.app.player.ScreenZone
import com.raddstream.app.player.SleepMode
import com.raddstream.app.player.SleepTick
import com.raddstream.app.player.SleepTimer
import com.raddstream.app.player.StartDeadline
import com.raddstream.app.player.StartPhase
import com.raddstream.app.player.SubtitleTrackDecision
import com.raddstream.app.player.SubtitleTrackPolicy
import com.raddstream.app.player.SubtitleUiSettings
import com.raddstream.app.player.TrackUiOption
import com.raddstream.app.player.TracksInfo
import com.raddstream.app.player.ViewMode
import com.raddstream.app.player.abRepeatWithA
import com.raddstream.app.player.abRepeatWithB
import com.raddstream.app.player.loopTargetMs
import com.raddstream.app.player.majorVersionOf
import com.raddstream.app.player.resolveStartBand
import com.raddstream.app.player.shouldAutoAdvance
import com.raddstream.app.player.shouldShowCoach
import com.raddstream.app.player.subtitle.SubtitleCue
import com.raddstream.app.player.subtitle.SubtitleFile
import com.raddstream.app.player.subtitle.SubtitleFormat
import com.raddstream.app.player.subtitle.SubtitleParser
import com.raddstream.app.player.subtitles.SubtitleOffset
import com.raddstream.app.data.LocalResumeRepository
import com.raddstream.app.data.isLocalResumeUri
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.cache.ConnectivityProbe
import com.raddstream.app.data.cache.NetworkClass
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.models.parseCastNames
import com.raddstream.app.network.streamRedirectUrl
import com.raddstream.app.network.withVipPass
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
import com.raddstream.app.sync.SyncAccountRepository
import com.raddstream.app.ui.navigation.DeepLinks
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
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import retrofit2.HttpException

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
    private val favoritesRepository: FavoritesRepository,
    private val syncAccountRepository: SyncAccountRepository,
    private val watchHistoryDao: WatchHistoryDao,
    private val localResumeRepository: LocalResumeRepository,
    private val connectivityProbe: ConnectivityProbe,
) : ViewModel() {

    private val store: PlayerSessionStore = PlayerSessionStore.Instance

    private var controller: MediaController? = null
    private var tickerJob: Job? = null

    /**
     * Monotonic instant the current load was requested (`elapsedRealtime`, so a sleeping
     * phone does not gift the deadline free seconds). Stamped in [loadNow] — the one funnel
     * every play path goes through — and in [retryCurrentCandidates], the one path that
     * bypasses it. Null once a first frame has rendered, so no stale attempt can fire.
     */
    private var startAttemptAtMs: Long? = null

    /**
     * Link-report bookkeeping (Session 123): the handle a `played` report was
     * already sent for, and the attempt a `failed` report was already sent for.
     * One report per handle / per attempt — the ticker visits every 200 ms and
     * must never turn one playback into dozens of rows. Both reset naturally:
     * a new bundle carries a new handle, a new attempt a new timestamp.
     */
    private var playedReportHandle: String? = null
    private var failedReportAttemptAtMs: Long? = null

    private var keepJob: Job? = null
    private var settingsJob: Job? = null
    private var bingeResolveJob: Job? = null
    private var bingePrefetchJob: Job? = null

    /**
     * The operator's `feature_flags.downloads`, on until the board says otherwise. It decides
     * whether this player offers a keep at all — see [refreshKeepState] and [keepCurrent].
     */
    private var downloadsAllowed: Boolean = true

    /**
     * The viewer's own player defaults (plan §5 step 10, P36): autoplay-next, on until
     * the viewer turns it off (plan D4), and the standing default quality band ("auto"
     * = no default). Collected, not sampled, so a change in Settings reaches a player
     * that is already running before the next episode ends.
     */
    private var autoplayNext: Boolean = true
    private var defaultQualityBand: String = LadderForScope.AUTO

    private val sleepTimer = SleepTimer()

    /**
     * The binge policy plus the fire-once set it makes its caller own. Lives here because
     * the ViewModel is the only place that knows both the progress tick and the session
     * lifecycle; the planner itself never touches the player.
     */
    private val bingePlanner = BingePrefetchPlanner()

    /** The next episode's handle, once looked up; null means "not addressable yet". */
    private var nextEpisodeHandle: String? = null

    /**
     * Everything needed to open the successor without touching the catalog again: its
     * handle, rungs and the scope it belongs to. [resolved] flips when the 85% pass has
     * asked our redirector about the handle, which is what makes the open instant.
     */
    private data class PreparedNextEpisode(
        val season: Int,
        val episode: Int,
        val handle: String,
        val title: String,
        val backupHandles: List<String>,
        val rungs: List<LadderRung>,
        val startBand: String?,
        val auto: Boolean,
        val resolved: Boolean = false,
        /** PL-12: the successor's still, year and cast — the end card's "Up next" preview. */
        val posterUrl: String? = null,
        val year: Int? = null,
        val castNames: List<String> = emptyList(),
    )

    private var preparedNextEpisode: PreparedNextEpisode? = null

    /**
     * PL-12: publish the prepared successor's title, number and still into the state —
     * the end card's "Up next" preview and the countdown card read it from here — or
     * clear all four when nothing is prepared. Called wherever `preparedNextEpisode`
     * is assigned or cleared, so the state can never name a successor that is gone.
     */
    private fun publishNextEpisode() {
        val prepared = preparedNextEpisode
        _ui.update {
            it.copy(
                nextEpisodeTitle = prepared?.title,
                nextEpisodeSeason = prepared?.season,
                nextEpisodeEpisode = prepared?.episode,
                nextEpisodePosterUrl = prepared?.posterUrl,
            )
        }
    }

    /**
     * The autoplay-next countdown (Session 123, PL-1): the job ticking the ten
     * seconds between an episode's end and the advance, and the action it will
     * fire when it reaches zero. Cancelling the job is cancelling the advance —
     * the viewer chose to stay — so every path that opens something else
     * (a manual Next, a new bundle) clears both without firing.
     */
    private var autoplayCountdownJob: Job? = null
    private var pendingAutoplayAction: NextEpisodeAction.NextBundleRequest? = null

    /** In-run resume memory; cross-launch persistence is a data-agent request (handoff). */
    private val resumeByTarget = HashMap<String, Long>()

    /**
     * The key the current bundle was opened under — the stream-id handle (or the local file
     * address for an on-device print). Every read of [resumeByTarget] uses it, and
     * [seedResumeFromStoredPositions] resolves the work scope through it (`peekWorkRef` maps
     * handle → scope), so positions measured during playback must be written under it too.
     * Sweep #10: `rememberResume` used to key by `target.workKey` instead, orphaning every
     * pause/destroy position under a key no reader consults while the stale handle-keyed
     * seed kept offering "Resume from X".
     */
    private var activeResumeKey: String? = null

    /**
     * Whether this device has a sync key, mirrored so a twice-a-second tick can read a boolean
     * instead of suspending on a Flow. False is the ordinary case, and then every account call
     * below returns before it builds a request — the player is exactly what it was before the
     * optional account existed.
     */
    private var syncSignedIn: Boolean = false

    /**
     * Whether the server has confirmed paid VIP for this account. Mirrored rather than
     * sampled for the same reason as [syncSignedIn]: a break decision is made on a tap, not
     * in a suspending context. It is the ledger's answer and nothing else — a rewarded
     * device pass is a separate fact and is read where it is stored.
     */
    private var syncEntitled: Boolean = false

    /**
     * The operator's 1080p/4K switch, mirrored from remote config. On is the shipped default,
     * the fail-closed mirror of the server gate (seeded and live ON): until remote config
     * says otherwise, a free viewer is never offered a rung the server will 402.
     * [premiumAccess] is what the gate is actually handed at every site below.
     */
    private var qualityGateEnabled: Boolean = true
    private var freeQualityCap: String = "720p"
    /** Data Saver — on by default, so mobile-data titles start at 480p. */
    private var dataSaver: Boolean = true
    /** Wi-Fi-only downloads — on by default; the Keep button honours it (Session 123). */
    private var wifiOnlyDownloads: Boolean = true
    /** Delete a watched download to free the space — on by default (Session 123: series episodes too). */
    private var autoDeleteWatched: Boolean = true

    /** A confirmed member, or everyone while the operator has not turned gating on. */
    private val premiumAccess: Boolean get() = VipQualityGate.premiumAccess(qualityGateEnabled, syncEntitled)

    private val _ui = MutableStateFlow(PlayerUiState())
    val uiState: StateFlow<PlayerUiState> = _ui.asStateFlow()

    /**
     * Whether the first-run gesture coach (plan §5 step 7) is owed right now. False
     * until the stored version is read — never show on a guess — and false again once
     * it is marked seen for this major version. The screen reads this, never the raw
     * stored version, so a half-loaded DataStore can never flash the overlay.
     */
    private val _showCoach = MutableStateFlow(false)
    val showCoach: StateFlow<Boolean> = _showCoach.asStateFlow()

    private val _events = MutableSharedFlow<PlayerEvent>(extraBufferCapacity = 8)
    val events: SharedFlow<PlayerEvent> = _events.asSharedFlow()

    /** The service-side player, exposed read-only so `PlayerView` can attach to it. */
    private val _player = MutableStateFlow<Player?>(null)
    val player: StateFlow<Player?> = _player.asStateFlow()

    /** Externally parsed subtitle (custom-render path). Null → native rendering only. */
    private var customSubtitleFile: SubtitleFile? = null
    /** True when the loaded overlay file came from the bundle (Gap A3), not from the viewer. */
    private var customSubtitleFromBundle: Boolean = false

    init {
        connectController()
        observeStore()
        observeSettings()
        observeSyncAccount()
    }

    /**
     * The two account facts this player cares about, plus the one device fact: is there a key,
     * what does the ledger say about it, and is a rewarded pass still running. Collected rather
     * than sampled, so signing in or out mid-session is felt by a player that is already
     * running, and so the tick loop never has to suspend to ask.
     */
    private fun observeSyncAccount() {
        viewModelScope.launch {
            syncAccountRepository.signedIn.collect { signIn -> syncSignedIn = signIn }
        }
        viewModelScope.launch {
            syncAccountRepository.entitlement.collect { earned ->
                syncEntitled = earned?.vip == true
                // A membership approved mid-playback should make its rungs selectable now,
                // not after the next episode.
                armQualityChoices()
            }
        }
        viewModelScope.launch {
            settingsRepository.qualityGateEnabled.collect { enabled ->
                qualityGateEnabled = enabled
                armQualityChoices()
            }
        }
        viewModelScope.launch {
            settingsRepository.freeQualityCap.collect { cap ->
                freeQualityCap = cap
                armQualityChoices()
            }
        }
        viewModelScope.launch {
            settingsRepository.dataSaver.collect { enabled ->
                dataSaver = enabled
                _ui.update { it.copy(dataSaver = enabled) }
                armQualityChoices()
            }
        }
        viewModelScope.launch {
            settingsRepository.autoPip.collect { enabled ->
                _ui.update { it.copy(autoPip = enabled) }
            }
        }
        viewModelScope.launch {
            settingsRepository.wifiOnlyDownloads.collect { enabled ->
                wifiOnlyDownloads = enabled
            }
        }
        viewModelScope.launch {
            settingsRepository.autoDeleteWatched.collect { enabled ->
                autoDeleteWatched = enabled
            }
        }
    }

    /**
     * The preferences the policy classes read. Collected, not sampled, so the settings
     * screen changing a value is felt by a player that is already running.
     */
    private fun observeSettings() {
        settingsJob?.cancel()
        settingsJob = viewModelScope.launch {
            settingsRepository.audioBoostLevel.collect { level ->
                _ui.update { it.copy(audioBoostLevel = AudioBoostUi.offeredLevel(level)) }
                applyPlayerVolume()
            }
        }
        viewModelScope.launch {
            combine(
                settingsRepository.userRegion,
                settingsRepository.preferredAudioLanguage,
                settingsRepository.preferredSubtitleLanguage,
            ) { region, audio, subtitle ->
                Triple(
                    LanguageDefaults.effectiveAudioLanguage(audio, region),
                    LanguageDefaults.effectiveAudioFallback(region),
                    LanguageDefaults.effectiveSubtitleLanguage(subtitle, region),
                )
            }.collect { (audio, fallback, subtitle) ->
                _ui.update {
                    it.copy(
                        preferredAudioLanguage = audio,
                        preferredAudioFallback = fallback,
                        preferredSubtitleLanguage = subtitle,
                    )
                }
                applyPreferredAudioTrack()
                applyPreferredSubtitleTrack()
            }
        }
        // …plus the one display preference the player owns: Ghost mode or the full chrome.
        viewModelScope.launch {
            settingsRepository.viewModeChoice.collect { name ->
                _ui.update { it.copy(viewMode = ViewMode.fromName(name)) }
            }
        }
        // The stored subtitle look. Nothing is written back: the sync offset belongs to this
        // viewing, so the live value rides through `withDelay` and a store answer — including
        // the echo of the viewer's own write — can never reset a delay they dialled in.
        viewModelScope.launch {
            settingsRepository.subtitleStyle.collect { style ->
                _ui.update { it.copy(subtitle = style.withDelay(it.subtitle.delayMs)) }
            }
        }
        // …and the operator's answer for that same preference. Nothing is written back: the
        // viewer's stored choice survives, and PlayerUiState.pureCinema is the one place that
        // refuses to honour it while `pure_cinema` is off, so the frame returns on its own.
        viewModelScope.launch {
            settingsRepository.pureCinemaFeatureEnabled.collect { allowed ->
                _ui.update { it.copy(pureCinemaAllowed = allowed) }
            }
        }
        // The board's downloads switch, which decides whether the keep chip is offered at all.
        // Re-asking the keep state is what makes a refresh take the chip away mid-play instead
        // of leaving a button that can no longer write a file.
        viewModelScope.launch {
            settingsRepository.downloadsFeatureEnabled.collect { allowed ->
                downloadsAllowed = allowed
                refreshKeepState()
            }
        }
        // The first-run gesture coach (plan §5 step 7): owed when never shown, or last
        // shown for a different major version than the one running now. Collected, not
        // sampled, so marking it seen hides it at once without a relaunch.
        viewModelScope.launch {
            settingsRepository.coachSeenVersion.collect { seen ->
                _showCoach.value = shouldShowCoach(seen, Brand.versionName)
            }
        }
        // The viewer's own player defaults (plan §5 step 10): the autoplay-next switch
        // gates the auto-advance, and the default band is the rung a new title starts
        // on when Play was Auto. Collected, not sampled, so a change in Settings reaches
        // a player that is already running.
        viewModelScope.launch {
            settingsRepository.autoplayNext.collect { enabled -> autoplayNext = enabled }
        }
        viewModelScope.launch {
            settingsRepository.defaultQuality.collect { band -> defaultQualityBand = band }
        }
        // The player chrome theme this device wears: collected, not sampled, so
        // a change on the VIP screen reaches a player that is already running.
        viewModelScope.launch {
            settingsRepository.playerTheme.collect { theme ->
                _ui.update { it.copy(playerTheme = theme) }
            }
        }
    }

    /**
     * The first-run gesture coach has been shown for this major version: record it so it
     * never shows again until a major version change. Called when the viewer taps it away
     * or its 4 s timer ends — either way the lesson was delivered, not skipped.
     */
    fun markCoachSeen() {
        viewModelScope.launch {
            settingsRepository.saveCoachSeenVersion(majorVersionOf(Brand.versionName))
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
                // The service is a process singleton and may still hold a previous screen's
                // sync; a fresh ViewModel starts at 0, so publish that before playback starts.
                store.subtitleOffsetMs = _ui.value.subtitle.delayMs
                c.addListener(playerListener)
                _ui.update { it.copy(connected = true) }
                startTicker()
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        connectionError = "Playback service unavailable: ${t.message}",
                        // PL-3: a bind failure with no network is the offline card, not the
                        // generic service error — the viewer can act on the first, not the second.
                        isOffline = connectivityProbe.current() == NetworkClass.NONE,
                    )
                }
            }
        }, ContextCompat.getMainExecutor(appContext))
    }

    private val playerListener = object : Player.Listener {
        override fun onIsPlayingChanged(isPlaying: Boolean) {
            // PL-3: a first frame playing is the proof the network is back — the
            // offline card clears itself, no retry tap needed.
            _ui.update { it.copy(isPlaying = isPlaying, isOffline = if (isPlaying) false else it.isOffline) }
        }

        override fun onVideoSizeChanged(videoSize: VideoSize) {
            // PL-10: the video's own aspect ratio, for the PiP params. A zero height
            // is a size that says nothing — keep the previous ratio, never a NaN.
            if (videoSize.height > 0) {
                _ui.update { it.copy(videoAspectRatio = videoSize.width.toFloat() / videoSize.height.toFloat()) }
            }
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            _ui.update {
                it.copy(
                    isBuffering = playbackState == Player.STATE_BUFFERING,
                    isEnded = playbackState == Player.STATE_ENDED,
                    // The ended successor offer dies the moment playback leaves the ended
                    // state — a replay or a new title must not inherit the last episode's
                    // Next Episode button.
                    endedHasNextEpisode = if (playbackState == Player.STATE_ENDED) it.endedHasNextEpisode else false,
                )
            }
            if (playbackState == Player.STATE_ENDED) {
                rememberResume()
                handleSleepEndOfVideo()
                maybeAutoDeleteWatchedEpisode()
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
            // the stream existed could not be honoured anywhere else. The subtitle row applies
            // at the same moment, for the same reason, through its own fire-once gate.
            applyPreferredAudioTrack()
            applyPreferredSubtitleTrack()
            applyBundleCustomSubtitle()
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
                // A new bundle is a new episode: any countdown belonging to the
                // ended one is dropped, never carried across.
                clearAutoplayCountdown()
                _ui.update { it.copy(bundle = b, activeRendition = store.activeRendition(), endedHasNextEpisode = false) }
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
                    preparedNextEpisode = null
                    publishNextEpisode()
                    bingeResolveJob?.cancel()
                    bingePrefetchJob?.cancel()
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

    /** The last A-B loop-back, on the monotonic clock: the re-arm guard in the policy. */
    private var lastAbLoopAtMs: Long? = null

    /** Which file the staged A-B segment belongs to (target + title); a new file clears it. */
    private var abRepeatScopeKey: String? = null

    private fun startTicker() {
        tickerJob?.cancel()
        var lastSleepTick = System.currentTimeMillis()
        tickerJob = viewModelScope.launch {
            while (true) {
                val c = controller
                if (c != null && c.isConnected) {
                    val now = System.currentTimeMillis()
                    val wasStarting = _ui.value.startPhase != StartPhase.NONE
                    _ui.update {
                        it.copy(
                            positionMs = c.currentPosition,
                            bufferedMs = bufferedOf(c),
                            durationMs = if (c.duration > 0) c.duration else it.durationMs,
                        )
                    }
                    // A-B repeat (§5 P14): the ticker already visits every 200 ms, so
                    // it is the clock — when the playhead reaches B, seek back to A.
                    // The re-arm window inside the policy keeps a seek still in flight
                    // from being re-issued on every visit.
                    val loopTo = loopTargetMs(
                        _ui.value.positionMs, _ui.value.abRepeat, lastAbLoopAtMs,
                        SystemClock.elapsedRealtime(),
                    )
                    if (loopTo != null) {
                        lastAbLoopAtMs = SystemClock.elapsedRealtime()
                        seekTo(loopTo)
                    }
                    // The start deadline (§5 P5): the ticker already visits every 200 ms, so
                    // it is the clock — no second thread. A first frame disarms the attempt
                    // and records how long the start took, but only when the player really
                    // was starting: a quality switch mid-scene must not overwrite the
                    // route-open measurement with a near-zero one. The frame test is
                    // READY only, never a known duration: a stalled copy can know its
                    // duration from the playlist or file header while the picture is
                    // still black, and the old `isPlaying || duration > 0` test disarmed
                    // the deadline on that alone — the Pushpa 2 retest buffered forever
                    // with no error and no give-up card.
                    val attemptAt = startAttemptAtMs
                    if (attemptAt != null) {
                        val elapsed = SystemClock.elapsedRealtime() - attemptAt
                        val firstFrame = StartDeadline.hasFirstFrame(c.playbackState)
                        if (firstFrame) {
                            startAttemptAtMs = null
                            _ui.update {
                                it.copy(
                                    startElapsedMs = 0,
                                    lastFirstFrameMs = if (wasStarting) elapsed else it.lastFirstFrameMs,
                                    deadlineGiveUp = false,
                                )
                            }
                            // The link played: one `played` report per handle (Session
                            // 123). The first frame is the proof — a stalled copy can
                            // know its duration from the header while the picture is
                            // still black, so duration alone never counts. Best-effort
                            // and silent; a failed report is dropped, never shown.
                            reportLinkPlayedOnce(elapsed)
                        } else {
                            _ui.update {
                                it.copy(
                                    startElapsedMs = elapsed,
                                    deadlineGiveUp = elapsed >= StartDeadline.GIVE_UP_AFTER_MS,
                                )
                            }
                            // The link never produced a first frame before the
                            // deadline: one `failed` report per attempt (Session 123).
                            // This is the dead-link signal the server's link-health
                            // axis is built on — the give-up card the viewer sees is
                            // the same event, reported once, at the same moment.
                            if (elapsed >= StartDeadline.GIVE_UP_AFTER_MS &&
                                failedReportAttemptAtMs != attemptAt
                            ) {
                                failedReportAttemptAtMs = attemptAt
                                reportLinkFailedOnce(elapsed)
                            }
                        }
                    }
                    // Sleep timer advance + fade (player volume = user volume × fade factor)
                    if (_ui.value.sleep.mode == SleepMode.COUNTDOWN) {
                        val tick = sleepTimer.onTick(now - lastSleepTick)
                        applySleep(tick)
                    }
                    tickBingePreload(_ui.value.positionMs, _ui.value.durationMs)
                    // The playhead is NOT reported from here. This ticker only runs while the player
                    // screen is composed, so pumping the cache from it stops the moment the viewer
                    // backgrounds the app — and at this clock it would ask the engine for a task
                    // lookup five times a second. PlaybackService owns the feed: it lives as long as
                    // the audio does, and it ticks the cache on the cache's own cadence.
                    // The account's own heartbeat: one report per fifteen seconds at most, and
                    // the gate is a boolean read, so this tick costs nothing when it is not due.
                    if (c.isPlaying) reportResume(c, c.currentPosition, forced = false)
                    lastSleepTick = now
                }
                delay(200)
            }
        }
    }

    private fun bufferedOf(c: MediaController): Long =
        if (c.bufferedPosition > 0) c.bufferedPosition else c.currentPosition

    // ── Link reports (Session 123) ────────────────────────────────────────────

    /** The handle this playback is streaming through, or null for local files. */
    private fun currentReportHandle(): String? =
        store.activeRendition()?.playback?.streamId?.takeIf { it.isNotBlank() }

    /**
     * One `played` report per handle: the first frame is the proof the link
     * works. Runs in the background and never touches the UI — a failed report
     * is dropped by the repository, never shown and never retried.
     */
    private fun reportLinkPlayedOnce(firstFrameMs: Long) {
        val handle = currentReportHandle() ?: return
        if (playedReportHandle == handle) return
        playedReportHandle = handle
        viewModelScope.launch {
            catalogRepository.reportLink(
                handle = handle,
                event = "played",
                latencyMs = firstFrameMs.toInt().coerceAtLeast(0),
            )
        }
    }

    /**
     * One `failed` report per attempt: the give-up deadline passed with no
     * first frame. Same best-effort rule as [reportLinkPlayedOnce].
     */
    private fun reportLinkFailedOnce(elapsedMs: Long) {
        val handle = currentReportHandle() ?: return
        viewModelScope.launch {
            catalogRepository.reportLink(
                handle = handle,
                event = "failed",
                latencyMs = elapsedMs.toInt().coerceAtLeast(0),
                error = "Playback did not start",
            )
        }
    }

    // ── Play entry points ────────────────────────────────────────────────────────

    /**
     * Route path `player/{streamId}/{title}`: one opaque handle of ours. The address the
     * player loads is our own redirector for that handle, built here — never a URL that
     * came from a scraper, and never one that names where the file lives.
     */
    fun startStreamHandle(streamId: String, title: String, startOverrideMs: Long? = null) {
        viewModelScope.launch {
            // Session 126 (audit bug d): re-seed BEFORE the early-return guard — the
            // position may have moved on another device since this handle was opened,
            // and the old code returned without ever asking. The seed only writes
            // when the fresh row is strictly later (see ResumeSeed.newerSeed).
            // A hung resume lookup must never hold back Play: the seed is a
            // nicety, and five seconds without an answer means playing from
            // the start instead of waiting on a row.
            withTimeoutOrNull(5_000) { seedResumeFromStoredPositions(streamId, startOverrideMs) }
            if (_ui.value.bundle?.renditions?.firstOrNull()?.playback?.streamId == streamId) return@launch
            // A pasted direct link, staged under its opaque key by the search
            // screen: no redirector, no server round-trip, no resume history —
            // the address itself is the whole ladder, one rung.
            store.peekDirectUrl(streamId)?.let { directUrl ->
                beginBundle(
                    directPlaybackBundle(streamId, directUrl),
                    title,
                    resumeKey = streamId,
                    overrideMs = startOverrideMs,
                )
                return@launch
            }
            val playUrl = withVipPass(
                streamRedirectUrl(apiProvider.currentBaseUrl(), streamId),
                // Session 123: the VIP pass rides the URL because the player
                // follows the 302 outside this process — a header cannot ride
                // along, and the sync key must never be handed to a file host
                // on a redirect. A guest or free account sends no pass.
                syncAccountRepository.currentVipPass(),
            )
            // Runner-ups of this rung, staged by the detail screen: handles only, so a
            // 403 mid-play costs one silent hop instead of a dialog and a quality drop.
            val bundle = PlaybackBundle.forStreamHandle(streamId = streamId, playUrl = playUrl,
                                                       title = title,
                                                       backupHandles = store.peekFailover(streamId))
                .withStagedTarget(streamId)
                .withStagedCoverage(streamId)
                .withStagedTracks(streamId)
            beginBundle(bundle, title, resumeKey = streamId, overrideMs = startOverrideMs)
        }
    }

    /**
     * The route carries one opaque handle, but the detail screen staged which work and which
     * episode that handle is. Stamping that onto the bundle is what lets the service decide
     * that an END has a successor at all, and what gives binge pre-caching a post id to look
     * the successor's ladder up by. A handle with no staged scope (a deep link) keeps the
     * route bundle's empty target, so it behaves exactly as before.
     */
    private fun PlaybackBundle.withStagedTarget(streamId: String): PlaybackBundle {
        val scope = store.peekWorkRef(streamId) ?: return this
        if (scope.postId <= 0) return this
        return copy(
            target = PlayTarget(
                kind = if (scope.episode > 0) "episode" else "work",
                id = scope.postId,
                workKey = scope.workRef.takeIf { it.isNotBlank() },
                workType = scope.workType,
                season = scope.season,
                episode = scope.episode,
            ),
        )
    }

    /**
     * The coverage the detail screen staged for this handle (plan §5 step 13): the
     * print's episode boundaries and chapter titles, from the v2 bundle. A handle
     * launched the old way has none staged, so the rendition keeps the default empty
     * coverage — the scrubber draws no ticks, exactly as before.
     */
    private fun PlaybackBundle.withStagedCoverage(streamId: String): PlaybackBundle {
        val coverage = store.peekCoverage(streamId) ?: return this
        val first = renditions.firstOrNull() ?: return this
        return copy(renditions = listOf(first.copy(coverage = coverage)) + renditions.drop(1))
    }

    /**
     * The subtitle tracks the detail screen staged for this handle (Gap A3).
     * A handle launched the old way has none staged, so the rendition keeps
     * the default empty tracks — the subtitle sheet simply offers nothing
     * extra, exactly as before.
     */
    private fun PlaybackBundle.withStagedTracks(streamId: String): PlaybackBundle {
        val tracks = store.peekTracks(streamId)
        if (tracks.isEmpty()) return this
        val first = renditions.firstOrNull() ?: return this
        return copy(renditions = listOf(first.copy(tracks = TracksInfo(subtitles = tracks))) + renditions.drop(1))
    }

    /**
     * Route path `player_local/{uri}/{title}`: a finished public download. The bytes are on
     * this device, so no redirector and no upstream origin is involved — the bundle carries
     * the local content/file URI and every other control surface behaves exactly as usual.
     */
    fun startLocalUri(uri: String, title: String) {
        val clean = uri.trim()
        if (clean.isEmpty()) return
        if (_ui.value.bundle?.renditions?.firstOrNull()?.playback?.playUrl == clean) return
        val extension = Uri.parse(clean).lastPathSegment?.substringAfterLast('.')?.lowercase()
        val mime = extension?.let {
            android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(it)
        }
        val bundle = PlaybackBundle(
            session = SessionInfo(id = "local-${clean.hashCode().toString(16)}"),
            target = PlayTarget(kind = "local", id = 0),
            renditions = listOf(
                PlaybackRendition(
                    rank = 1,
                    print = PrintInfo(label = "Downloaded"),
                    playback = PlaybackInfo(
                        playUrl = clean,
                        streamId = "local",
                        label = "Saved to device",
                        protocol = "progressive",
                        mimeType = mime,
                        resumable = true,
                        kind = "direct",
                        playabilityWire = "stream",
                    ),
                ),
            ),
        )
        beginBundle(bundle, title, resumeKey = clean)
    }

    /**
     * One rung, no server: a pasted .mp4/.m3u8 address staged under its opaque
     * key. The shape mirrors [startLocalUri] — the player already knows how to
     * play a bundle whose only rendition is a direct file — with two honest
     * differences: `resumable` is false, because the address is unprobed and
     * the player must not claim a Range resume it never measured; and the
     * protocol and mime come from the address itself, so Media3 picks the
     * right reader for a playlist versus a single file.
     */
    private fun directPlaybackBundle(key: String, url: String): PlaybackBundle {
        val isHls = directVideoIsHls(url)
        return PlaybackBundle(
            session = SessionInfo(id = key),
            target = PlayTarget(kind = "direct", id = 0),
            renditions = listOf(
                PlaybackRendition(
                    rank = 1,
                    print = PrintInfo(label = "Direct link"),
                    playback = PlaybackInfo(
                        playUrl = url,
                        streamId = key,
                        label = directVideoTitle(url),
                        protocol = if (isHls) "hls" else "progressive",
                        mimeType = directVideoMime(url),
                        resumable = false,
                        kind = "direct",
                        playabilityWire = "stream",
                    ),
                ),
            ),
        )
    }

    /**
     * The stored position for the scope this handle is about to play, in the one place this
     * player already looks. [ResumeSeed] owns the precedence; what lives here is the two reads
     * and the write into [resumeByTarget] — the same map a position on THIS device writes.
     *
     * Nothing is re-ordered and nothing blocks the play button on it: both lookups are local
     * Room reads that only run when this process has no live position to offer, so a slow
     * account row cannot hold back playback, and a playback the detail screen could not name
     * has nothing to look up at all.
     */
    private suspend fun seedResumeFromStoredPositions(resumeKey: String, explicitStartMs: Long?) {
        if (explicitStartMs != null) return
        val existing = resumeByTarget[resumeKey]
        val scope = store.peekWorkRef(resumeKey)
        if (scope == null) {
            // A local file has no work ref for Room or the sync account to hang a
            // position on — its resume lives in the local store instead, and only
            // a device address may read it (a staged direct-URL key never does).
            if (!isLocalResumeUri(resumeKey)) return
            val localMs = localResumeRepository.positionFor(resumeKey) ?: return
            val seed = if (existing == null) {
                ResumeSeed.seedFor(explicitStartMs, existing, null, localMs)
            } else {
                // Session 126 (audit bug d): the position moved elsewhere — take the
                // newer row, never move the seed backwards.
                ResumeSeed.newerSeed(existing, null, localMs)
            } ?: return
            // Re-checked: write only while the map still holds the value this decision
            // was based on — a position measured while this lookup was running outranks it.
            if (resumeByTarget[resumeKey] == existing) resumeByTarget[resumeKey] = seed
            return
        }
        val syncedMs = if (syncSignedIn) {
            syncAccountRepository.resumePositionMs(scope.workRef, scope.season, scope.episode)
        } else {
            null
        }
        val localMs = watchHistoryDao.findScope(scope.workRef, scope.season, scope.episode)
            ?.positionMs
        val seed = if (existing == null) {
            ResumeSeed.seedFor(explicitStartMs, existing, syncedMs, localMs)
        } else {
            ResumeSeed.newerSeed(existing, syncedMs, localMs)
        } ?: return
        // Re-checked: a position measured while these lookups were running outranks either row.
        if (resumeByTarget[resumeKey] == existing) resumeByTarget[resumeKey] = seed
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
        val staged = store.peekAutoLadder(handle) ?: return
        // The detail screen already gates what it stages, but a deep link or a membership
        // that lapsed mid-session could still hand us a premium rung. The player applies the
        // same rule at the point the switch is built, so no premium choice is ever offered.
        val rungs = staged.rungs.filter { VipQualityGate.allowsBand(it.band, premiumAccess, freeQualityCap) }
        if (rungs.isEmpty()) return
        // The standing default band (plan §5 step 10): an explicit tap outranks it, it
        // outranks Auto's pick, and a band missing from this ladder is ignored.
        val (startBand, auto) = resolveStartBand(
            stagedStartBand = staged.startBand,
            stagedAuto = staged.auto,
            defaultBand = defaultQualityBand,
            rungBands = rungs.map { it.band },
        )
        // Data Saver caps the start on mobile data — 480p when the ladder has it —
        // and the auto pointer with it, so Auto cannot quietly start above the cap.
        // The rungs themselves are untouched: the viewer can still switch up.
        val onWifi = connectivityProbe.current() == NetworkClass.WIFI
        val cappedStartBand = DataSaver.capBand(startBand, rungs.map { it.band }, dataSaver, onWifi)
        val cappedAutoBand = staged.autoBand
            ?.takeIf { band -> rungs.any { it.band == band } }
            ?.let { DataSaver.capBand(it, rungs.map { it.band }, dataSaver, onWifi) }
        val plan = staged.copy(
            rungs = rungs,
            startBand = cappedStartBand,
            auto = auto,
            autoBand = cappedAutoBand,
        )
        ladderPlan = plan
        if (plan.auto) autoRungHandle = staged.startBand?.let { band ->
            // The same cap as the start band above: Auto's first rung is the
            // capped one on mobile data, not the staged one above it.
            val capped = DataSaver.capBand(band, rungs.map { it.band }, dataSaver, onWifi)
            plan.rungs.firstOrNull { it.band == capped }?.streamId
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
        val rung = plan.rungs.firstOrNull { it.band == targetBand }
        if (rung == null) {
            // Audit bug (b): the old code returned silently, so a tap on a band the
            // scope does not offer did nothing at all — no switch, no message. The
            // viewer is told, in the same snackbar every other player message uses.
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("That quality is not offered for this title"))
            }
            return
        }
        if (!VipQualityGate.allowsBand(rung.band, premiumAccess, freeQualityCap)) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message(VipQualityGate.lockedMessage(freeQualityCap)))
            }
            return
        }
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
        // The work did not change, only its address: carry the staged handle over, so a
        // quality switch (or a silent hop onto this rung's runner-up) keeps reporting resume
        // points against the same scope the detail screen named.
        store.peekWorkRef(active?.playback?.streamId)?.let { scope ->
            store.stageWorkRef(rung.streamId, scope)
            rung.backupHandles.forEach { store.stageWorkRef(it, scope) }
        }
        // D-35: carry the display metadata with the scope, so the loading state after a
        // quality switch still shows the poster instead of a black void.
        store.peekTitleMeta(active?.playback?.streamId)?.let { meta ->
            store.stageTitleMeta(rung.streamId, meta)
            rung.backupHandles.forEach { store.stageTitleMeta(it, meta) }
        }
        startStreamHandle(rung.streamId, title, startOverrideMs = positionMs.takeIf { it > 1_000 })
    }

    fun showQualitySheet() {
        if (_ui.value.qualityRungs.isEmpty()) return
        _ui.update { it.copy(qualitySheetVisible = true) }
    }

    fun hideQualitySheet() {
        _ui.update { it.copy(qualitySheetVisible = false) }
    }

    /** The Quality sheet's Data Saver row (Session 126): one tap, persisted, felt at once. */
    fun toggleDataSaver() {
        viewModelScope.launch { settingsRepository.saveDataSaver(!dataSaver) }
    }

    /**
     * SC.24: share a moment — the title, the timestamp, and the app's own deep link,
     * handed to the share sheet by the screen. A local file has no stream handle to
     * link to, so there is nothing to share: the row is hidden for local bundles and
     * this guard is the second door.
     */
    fun shareMoment() {
        val streamId = _ui.value.activeRendition?.playback?.streamId?.trim()?.takeIf { it.isNotBlank() }
            ?: return
        if (streamId == "local") return
        val title = _ui.value.pendingTitle ?: _ui.value.activeRendition?.displayLabel() ?: Brand.name
        val text = ShareMoment.shareText(title, _ui.value.positionMs, DeepLinks.streamUri(streamId, title))
        viewModelScope.launch { _events.emit(PlayerEvent.ShareMoment(text)) }
    }

    private fun beginBundle(
        bundle: PlaybackBundle,
        title: String,
        resumeKey: String,
        overrideMs: Long? = null,
    ) {
        // A new file starts with no segment: the old A-B points are positions in a
        // different file. A quality switch keeps the same work, season, episode and
        // title, so the segment survives it — the range is in the file, not the
        // address. The scope key is the target plus the title, because a deep link
        // carries the empty target and only its title tells it apart.
        val scopeKey = "${bundle.target.kind}:${bundle.target.id}:${bundle.target.season}:${bundle.target.episode}:$title"
        if (abRepeatScopeKey != scopeKey) {
            _ui.update { it.copy(abRepeat = AbRepeat()) }
            lastAbLoopAtMs = null
            abRepeatScopeKey = scopeKey
        }
        store.installBundle(bundle)
        activeResumeKey = resumeKey
        // Gap A3: the bundle's own SRT/VTT subtitle loads into the overlay
        // here (and again when the tracks report, below) — the preference
        // may not be in state yet at install time, and the fire-once gate
        // makes the second call a no-op when the first already ran.
        applyBundleCustomSubtitle()
        // D-35 / PL-11: publish the title's display metadata and the series scope for
        // this bundle — the loading state shows the staged poster, the More sheet
        // shows its series rows only for a series scope. A deep link or a local file
        // has nothing staged, so the poster clears and the rows hide, honestly.
        val meta = store.peekTitleMeta(resumeKey)
        _ui.update {
            it.copy(
                posterUrl = meta?.posterUrl,
                titleYear = meta?.year,
                castNames = meta?.castNames.orEmpty(),
                isSeriesScope = EpisodeProgression.seriesLikeWorkType(bundle.target.workType) ||
                    bundle.target.episode > 0,
            )
        }
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
        startAttemptAtMs = SystemClock.elapsedRealtime()
        playedReportHandle = null // a new attempt may play a handle that already failed
        // PL-3: ask the probe at the moment of the load — offline at start shows the
        // offline card with Retry at once, not the 30-second deadline card. A retry
        // re-asks, so the card clears the moment the network is back.
        val offlineNow = connectivityProbe.current() == NetworkClass.NONE
        _ui.update {
            it.copy(
                resumeOfferMs = null,
                pendingResumeKey = null,
                giveUp = null,
                pendingTitle = title,
                startElapsedMs = 0,
                deadlineGiveUp = false,
                isOffline = offlineNow,
            )
        }
        activeResumeKey = resumeKey
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
        val key = activeResumeKey ?: store.bundle.value?.target?.workKey ?: title
        loadNow(title, key, resumePosition = 0, override = positionMs.coerceAtLeast(0))
    }

    private fun rememberResume(forced: Boolean = true) {
        val c = controller ?: return
        val bundle = store.bundle.value ?: return
        // Write under the key every reader consults — the opened handle, not the work key.
        val key = activeResumeKey ?: bundle.target.workKey ?: c.currentMediaItem?.mediaId ?: return
        val pos = c.currentPosition
        if (pos > 5_000 && pos < c.duration) resumeByTarget[key] = pos else resumeByTarget.remove(key)
        // A local file's position must survive the process: the in-memory map dies
        // with it, so a device address is also written to the local resume store
        // under the same guards (a finished or barely-started file clears it).
        if (isLocalResumeUri(key)) {
            viewModelScope.launch { localResumeRepository.savePosition(key, pos, c.duration) }
        }
        reportResume(c, pos, forced)
    }

    /**
     * Tell the optional sync account where viewing is, at the same moment this class already
     * remembers it for itself. Three rules decide everything here, and all three live in
     * [SyncAccountRepository] rather than in this player:
     *  - the work is named by the handle the detail screen staged, never by a title, a row id
     *    or a work key. Nothing staged means nothing reported: a deep-linked playback has no
     *    provenable identity on the account surface, and guessing is not an option;
     *  - [forced] is a stop, a pause or a teardown — positions worth a request. Anything else
     *    goes through the fifteen-second gate, which is checked WITHOUT suspending so a
     *    twice-a-second tick costs one boolean and no coroutine at all;
     *  - a refusal is silent and cannot touch playback. Every failure path in the sync layer
     *    returns a value this function throws away, because a viewer mid-scene must never lose
     *    their picture to a resume-point upload.
     */
    private fun reportResume(c: MediaController, positionMs: Long, forced: Boolean) {
        val scope = store.currentSyncScope() ?: return
        if (positionMs <= 0L) return
        val durationMs = if (c.duration > 0) c.duration else _ui.value.durationMs
        rememberLocally(scope, positionMs, durationMs, forced)
        if (!syncSignedIn) return
        if (!forced && !syncAccountRepository.progressReportDue()) return
        viewModelScope.launch {
            val coinsEarned = syncAccountRepository.reportProgress(
                workRef = scope.workRef,
                season = scope.season,
                episode = scope.episode,
                positionMs = positionMs,
                durationMs = durationMs,
                forced = forced,
            )
            // The server pays once per finished title; the toast is the only
            // sign the viewer gets, and it shows only when the server says it
            // paid — never on a position the server did not reward.
            if (coinsEarned > 0) {
                _events.emit(PlayerEvent.Message("+$coinsEarned coins for finishing this title"))
            }
        }
    }

    /**
     * Continue watching is a local fact, not an account feature: a guest who never signed in
     * still gets a rail. Writes ride the same forced-or-fifteen-seconds gate as the account
     * report (the tick calls this five times a second, so an ungated write would be a database
     * hammer), and a scope with no history row — a deep link this app never opened — updates
     * nothing rather than inventing a title.
     */
    private fun rememberLocally(
        scope: PlayerSessionStore.SyncScope,
        positionMs: Long,
        durationMs: Long,
        forced: Boolean,
    ) {
        val now = System.currentTimeMillis()
        if (!forced && now - lastHistoryWriteAt < HISTORY_WRITE_INTERVAL_MS) return
        lastHistoryWriteAt = now
        viewModelScope.launch {
            watchHistoryDao.recordPosition(
                workRef = scope.workRef,
                season = scope.season,
                episode = scope.episode,
                positionMs = positionMs,
                durationMs = durationMs,
                updatedAt = now,
            )
        }
    }

    /** Epoch millis of the last local history write; see [rememberLocally]. */
    private var lastHistoryWriteAt: Long = 0L

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

    /** A-B repeat (§5 P14): set point A at the current playhead. */
    fun setAbPointA() {
        _ui.update { it.copy(abRepeat = abRepeatWithA(it.abRepeat, it.positionMs)) }
    }

    /** A-B repeat (§5 P14): set point B at the current playhead. */
    fun setAbPointB() {
        _ui.update { it.copy(abRepeat = abRepeatWithB(it.abRepeat, it.positionMs)) }
    }

    /** A-B repeat (§5 P14): clear the segment; playback continues normally. */
    fun clearAbRepeat() {
        _ui.update { it.copy(abRepeat = AbRepeat()) }
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
        if (clamped > 0f) lastAudibleVolume = clamped
        _ui.update { it.copy(userVolume = clamped) }
        applyPlayerVolume()
    }

    /** The last audible level, so un-muting restores what the viewer had, not full blast. */
    private var lastAudibleVolume: Float = 1f

    /**
     * Mute / un-mute from the Volume button. Muting keeps the last audible level aside;
     * un-muting restores it. A gesture drag to silence is the same act, so [setUserVolume]
     * is what records the restore point, not this function.
     */
    fun toggleMute() {
        if (_ui.value.userVolume > 0f) setUserVolume(0f)
        else setUserVolume(lastAudibleVolume)
    }

    /** Fullscreen (immersive, system bars hidden) ↔ normal (system bars shown). */
    fun toggleFullscreen() {
        _ui.update { it.copy(fullscreen = !it.fullscreen) }
    }

    /**
     * The audio level control. 1.0 is the untouched baseline and 1.0 is also the most this
     * build can apply, so the stored value can never hold a promise the player cannot keep —
     * including a level an older build wrote above the ceiling, which is sanitised on read too.
     * Stored through the same DataStore the settings screen writes, so a mix made in the player
     * is the level the next episode starts with and the one the settings screen shows.
     */
    fun setAudioBoostLevel(level: Float) {
        val clamped = AudioBoostUi.offeredLevel(level)
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
        startAttemptAtMs = SystemClock.elapsedRealtime()
        playedReportHandle = null // a new attempt may play a handle that already failed
        _ui.update { it.copy(deadlineGiveUp = false, startElapsedMs = 0) }
        store.requestLoad(title = title, resumePositionMs = _ui.value.positionMs)
    }

    /**
     * Manual failover (§5 P5, the 8 s action): jump to the next print now instead of
     * waiting for the staged failover to exhaust the one being tried. The next print's own
     * runner-ups are staged under it first, and its work scope is carried over, exactly
     * as a quality switch does — so resume points and binge context survive the hop.
     * A no-op when [PlayerUiState.canTryAnotherPrint] is false; the button is never
     * offered then, so this is a guard, not a path the viewer can reach.
     */
    fun tryNextPrint() {
        val handle = _ui.value.nextPrintHandle ?: return
        val active = _ui.value.activeRendition
        val title = _ui.value.pendingTitle ?: active?.displayLabel() ?: Brand.name
        val positionMs = controller?.takeIf { it.isConnected }?.currentPosition ?: 0L
        val next = _ui.value.bundle?.renditions?.firstOrNull { it.playback.streamId == handle }
        val backups = (next?.playback?.backupStreamIds
            ?: active?.playback?.backupStreamIds.orEmpty())
            .filter { it != handle }
        store.stageFailover(handle, backups)
        store.peekWorkRef(active?.playback?.streamId)?.let { scope ->
            store.stageWorkRef(handle, scope)
            backups.forEach { store.stageWorkRef(it, scope) }
        }
        startStreamHandle(handle, title, startOverrideMs = positionMs.takeIf { it > 1_000 })
    }

    /**
     * The viewer dismissed the 30 s give-up card: keep waiting, with a fresh thirty
     * seconds. A dismiss is not a fix — if the copy is truly dead the card comes back —
     * but a viewer who is still willing to wait should not be nagged every tick.
     */
    fun dismissDeadlineGiveUp() {
        startAttemptAtMs = SystemClock.elapsedRealtime()
        playedReportHandle = null // a new attempt may play a handle that already failed
        _ui.update { it.copy(deadlineGiveUp = false, startElapsedMs = 0) }
    }

    /** Manual "next episode" button — same event path as auto-advance at media end. */
    fun requestNextEpisode() {
        // A manual Next while the countdown is running replaces it: the viewer
        // already chose, so the held advance is dropped, never fired twice.
        clearAutoplayCountdown()
        _ui.update { it.copy(endedHasNextEpisode = false) }
        val bundle = store.bundle.value
        val target = bundle?.target
        if (target == null || (target.episode <= 0 && target.season <= 0)) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("No episode context on this link"))
            }
            return
        }
        val season = target.season
        val nextEpisode = (target.episode.coerceAtLeast(1)) + 1
        viewModelScope.launch {
            if (openNextEpisode(season, nextEpisode, target.id.takeIf { it > 0 })) return@launch
            _events.emit(
                PlayerEvent.PlayNextEpisode(
                    workKey = target.workKey,
                    postId = target.id.takeIf { it > 0 },
                    season = season,
                    episode = nextEpisode,
                ),
            )
        }
    }

    /**
     * Whether the END that just happened leads anywhere. A packed file's in-file successor
     * counts, so the advance is never offered before a dead end.
     */
    private fun hasSuccessorAtEnd(state: PlayerUiState): Boolean {
        val bundle = store.bundle.value ?: return false
        return when (
            EpisodeProgression.computeNext(
                bundle = bundle,
                rendition = store.activeRendition(),
                learned = store.learnedOffsets,
                positionMs = state.positionMs,
                durationMs = state.durationMs,
            )
        ) {
            is NextEpisodeAction.InFileSeek,
            is NextEpisodeAction.NextBundleRequest,
            is NextEpisodeAction.CalibrationNeeded,
            -> true
            else -> false
        }
    }

    // ── Smart binge pre-caching ──────────────────────────────────────────────────

    /**
     * Start looking up the next episode's handle while the current one is still playing, so
     * the policy has something to ask for at the threshold instead of discovering at 85% that
     * nobody ever resolved the successor.
     *
     * The episode context comes from the bundle when the server supplied one, and from the
     * scope the detail screen staged otherwise — a route launch carries one opaque handle,
     * so without that stamp there would be no post id to look a successor's ladder up by.
     *
     * Skipped when the next episode lives in THIS file (a packed season whose offset the
     * server or the learned ledger already knows): there is no second address to warm, and
     * the in-file advance the service performs on END is the whole feature there.
     */
    private fun prepareBingePrefetch(bundle: PlaybackBundle) {
        val target = bundle.target
        val rendition = store.activeRendition() ?: bundle.renditions.firstOrNull()
        val scope = store.currentSyncScope()
        val episode = target.episode.takeIf { it > 0 } ?: scope?.episode ?: 0
        val season = target.season.takeIf { it > 0 } ?: scope?.season ?: 0
        val postId = target.id.takeIf { it > 0 } ?: scope?.postId ?: 0
        val isSeries = EpisodeProgression.seriesLikeWorkType(target.workType ?: scope?.workType) ||
            episode > 0
        if (!isSeries || postId <= 0 || episode <= 0 || rendition == null) return
        if (nextEpisodeIsInThisFile(bundle, rendition)) return
        val nextEpisode = episode + 1
        val expectedKey = bingeBundleKey(bundle)
        bingeResolveJob?.cancel()
        bingeResolveJob = viewModelScope.launch {
            val prepared = lookupNextEpisode(postId, season, nextEpisode) ?: return@launch
            // A bundle switch while the lookup ran means this successor belongs to a
            // viewing the viewer already left; never arm it against the new episode.
            if (bingeBundleKey(store.bundle.value) != expectedKey) return@launch
            nextEpisodeHandle = prepared.handle
            preparedNextEpisode = prepared
            publishNextEpisode()
        }
    }

    /** The successor's own ladder, reduced to what a hand-off needs. */
    private suspend fun lookupNextEpisode(postId: Int, season: Int, episode: Int): PreparedNextEpisode? {
        val detail = runCatching { catalogRepository.getPostDetail(postId) }.getOrNull() ?: return null
        val ladder = VipQualityGate.gate(
            QualityLadder.forNumberedScope(
                detail.optionGroups,
                season.takeIf { it > 0 },
                episode,
            ),
            premiumAccess,
            freeQualityCap,
        )
        val option = ladder.resolvedFor(LadderForScope.AUTO) ?: return null
        val handle = option.streamId.takeIf { it.isNotBlank() } ?: return null
        val rungs = ladder.options
            .filter { it.playsHere && it.streamId.isNotBlank() && it.band.isNotBlank() }
            .map {
                LadderRung(
                    band = it.band,
                    streamId = it.streamId,
                    backupHandles = it.backupHandles,
                    label = it.title,
                )
            }
        val title = detail.cleanTitle?.takeIf { it.isNotBlank() } ?: detail.title
        return PreparedNextEpisode(
            season = season,
            episode = episode,
            handle = handle,
            title = title,
            backupHandles = option.backupHandles,
            rungs = rungs,
            startBand = option.band,
            auto = ladder.autoBand != null && option.band == ladder.autoBand,
            posterUrl = detail.posterUrl,
            year = detail.year,
            castNames = parseCastNames(detail.castNames),
        )
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
     * Session 123: the act used to be only a probe — the redirector was asked
     * about the handle and the successor marked resolved, but zero bytes were
     * fetched, so the advance still waited on the first bytes. The head-pull
     * entry point the old comment said did not exist is the engine's own
     * `seedPreview` (the same bounded ahead-window the player seeds while
     * watching), so the tick now pulls the next episode's head through it
     * after a usable probe. The budget (`mayPreview`) and the Wi-Fi-only
     * switch still apply: on mobile data with Wi-Fi-only on, the link stays
     * warm and the bytes wait for Wi-Fi.
     */
    private fun tickBingePreload(positionMs: Long, durationMs: Long) {
        val bundle = store.bundle.value ?: return
        val target = bundle.target
        val episode = target.episode.takeIf { it > 0 } ?: store.currentSyncScope()?.episode ?: 0
        val isSeries = EpisodeProgression.seriesLikeWorkType(target.workType) || episode > 0
        val decision = bingePlanner.tick(positionMs, durationMs, isSeries, nextEpisodeHandle)
        if (decision is BingePreloadDecision.PrefetchNextHead) prefetchNextEpisodeHead(decision.handle)
    }

    /**
     * Ask the redirector about one handle and report what the answer *was*, as primitives —
     * same reasoning as `CatalogRepository.probePost`: the refusal/silence distinction is what
     * decides whether a viewer's saved row gets hidden, and a `runCatching` that flattens a 404
     * and a dead socket into `null` is exactly the bug that rule exists to avoid.
     */
    private suspend fun probeHandle(handle: String): HandleProbe = try {
        HandleProbe(catalogRepository.resolveStream(handle), null, null, noAnswer = false)
    } catch (e: HttpException) {
        HandleProbe(null, e.code(), null, noAnswer = false)
    } catch (e: Exception) {
        HandleProbe(null, null, null, noAnswer = true)
    }

    private fun prefetchNextEpisodeHead(handle: String) {
        bingePrefetchJob?.cancel()
        bingePrefetchJob = viewModelScope.launch {
            val probe = probeHandle(handle)
            // A redirector that refuses this handle by name is not a hiccup: the successor is
            // gone, and a saved row pointing at it must stop looking playable. Silence, by
            // contrast, says nothing and is left as one.
            if (probe.answer == AdultPolicy.ServerAnswer.GONE) {
                store.currentSyncScope()?.postId
                    // 0 is the scope's "no post" default, never a row to mark.
                    ?.takeIf { it > 0 }
                    ?.let { savedId -> favoritesRepository.recordStreamRefusal(savedId) }
                _events.emit(PlayerEvent.Message(NEXT_UNAVAILABLE))
                return@launch
            }
            val answer = probe.response
            // `streamId` is the model's own "this answer is usable" test: a successful lookup
            // that produced no handle of ours is a false success and says nothing to the user.
            if (answer?.streamId == null) return@launch
            val prepared = preparedNextEpisode
            if (prepared != null && prepared.handle == handle) {
                preparedNextEpisode = prepared.copy(resolved = true)
            }
            // Session 123: the probe alone never fetched a byte. Pull the next
            // episode's head through the engine's preview pass now — the same
            // bounded ahead-window the player seeds while watching — so the
            // advance starts on bytes already on disk. The engine's own budget
            // (`mayPreview`) decides whether the bytes are affordable, and the
            // Wi-Fi-only switch decides whether mobile data may buy them: with
            // Wi-Fi-only on and no Wi-Fi, the link stays warm and the bytes
            // wait. A preview that fails is silent — the advance still works,
            // it just waits on the first bytes again.
            val engine = CacheEngineHolder.engine
            val onWifi = connectivityProbe.current() == NetworkClass.WIFI
            if (engine != null && !DataSaver.wifiOnlyBlocks(wifiOnlyDownloads, onWifi)) {
                val url = withVipPass(
                    streamRedirectUrl(apiProvider.currentBaseUrl(), handle),
                    // Session 123: the preview fetches bytes through the same
                    // redirector the player uses, so the same pass rides it —
                    // a VIP next episode prefetches instead of 402ing.
                    syncAccountRepository.currentVipPass(),
                )
                val label = prepared
                    ?.takeIf { it.handle == handle }
                    ?.let { "Episode ${it.episode}" }
                    ?: "Next episode"
                runCatching {
                    engine.seedPreview(
                        PreviewRequest(
                            key = CacheSessionKey(renditionKey = handle, url = url),
                            url = url,
                            expectedTotalBytes = answer.fileSizeBytes?.takeIf { it > 0L },
                            resumable = answer.resumable ?: false,
                            printLabel = label,
                        ),
                    )
                }
            }
            _events.emit(
                PlayerEvent.Message("Next episode ready — its link is live, so advancing will not wait on a lookup"),
            )
        }
    }

    /**
     * Open the successor requested by the END signal or the manual next button.
     *
     * [preparedNextEpisode] is the fast path: the ladder was already resolved and the
     * redirector was already asked at 85%, so this is an install and a load. When nothing
     * was prepared (a very short episode, a seek past the threshold, a just-opened link)
     * the ladder is looked up now, which is still the same hand-off minus the warming.
     * False means no playable rung exists, and the caller falls back to the app's event
     * route rather than pretending the episode advanced.
     */
    private suspend fun openNextEpisode(season: Int, episode: Int, postId: Int?): Boolean {
        val prepared = preparedNextEpisode
            ?.takeIf { it.season == season && it.episode == episode }
            ?: lookupNextEpisode(
                postId = postId?.takeIf { it > 0 } ?: store.currentSyncScope()?.postId ?: return false,
                season = season,
                episode = episode,
            )
            ?: return false
        openPrepared(prepared)
        return true
    }

    private fun openPrepared(prepared: PreparedNextEpisode) {
        // Carry the work's scope onto every address of the successor, exactly as the detail
        // screen does when it launches a rung: a resume point belongs to the episode, not to
        // whichever handle happens to serve it.
        store.currentSyncScope()?.let { current ->
            val scope = current.copy(season = prepared.season, episode = prepared.episode)
            (listOf(prepared.handle) + prepared.backupHandles +
                prepared.rungs.flatMap { listOf(it.streamId) + it.backupHandles })
                .distinct()
                .forEach { store.stageWorkRef(it, scope) }
        }
        // D-35: carry the successor's display metadata with its scope, so the loading
        // state of the next episode shows its poster instead of a black void.
        val nextMeta = PlayerSessionStore.TitleMeta(
            posterUrl = prepared.posterUrl,
            year = prepared.year,
            castNames = prepared.castNames,
        )
        (listOf(prepared.handle) + prepared.backupHandles +
            prepared.rungs.flatMap { listOf(it.streamId) + it.backupHandles })
            .distinct()
            .forEach { store.stageTitleMeta(it, nextMeta) }
        store.stageFailover(prepared.handle, prepared.backupHandles)
        if (prepared.rungs.isNotEmpty()) {
            store.stageAutoLadder(prepared.handle, prepared.rungs, prepared.startBand, prepared.auto)
        }
        preparedNextEpisode = null
        nextEpisodeHandle = null
        publishNextEpisode()
        startStreamHandle(prepared.handle, prepared.title)
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

    /** Opens the sync sheet alone: the subtitle list and the offset control never stack. */
    fun showSubtitleOffsetSheet() {
        _ui.update { it.copy(subtitleSheetVisible = false, subtitleOffsetSheetVisible = true) }
    }

    fun hideSubtitleOffsetSheet() {
        _ui.update { it.copy(subtitleOffsetSheetVisible = false) }
    }

    /**
     * Live subtitle sync. Called on every slider frame and on each quick button, so the
     * custom SRT/VTT overlay re-renders on the next frame AND the service's decoder wrapper
     * retimes the native track from the same number while playback continues.
     *
     * A positive value shows the text later, matching both render paths.
     */
    fun setSubtitleOffset(delayMs: Long) {
        val clamped = SubtitleOffset.clamp(delayMs)
        _ui.update { it.copy(subtitle = it.subtitle.copy(delayMs = clamped)) }
        store.subtitleOffsetMs = clamped
    }

    fun showPrintSheet() {
        _ui.update { it.copy(printSheetVisible = true) }
    }

    fun hidePrintSheet() {
        _ui.update { it.copy(printSheetVisible = false) }
    }

    fun showMoreSheet() {
        _ui.update { it.copy(moreSheetVisible = true) }
    }

    fun hideMoreSheet() {
        _ui.update { it.copy(moreSheetVisible = false) }
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

    fun toggleOrientation() {
        _ui.update { it.copy(orientation = it.orientation.toggled()) }
    }

    fun setLocked(locked: Boolean) {
        _ui.update { it.copy(locked = locked) }
    }

    /**
     * Full chrome ↔ Ghost mode. Persisted through the same DataStore the settings screen
     * writes, so the next episode opens in the frame the viewer last asked for, and so the
     * two entry points (this button and the settings row) can never disagree.
     *
     * The operator's `pure_cinema` switch is the one thing that can refuse this: the screen
     * already hides both buttons while it is off, and this guard is what stops any other caller
     * from smuggling chrome away behind that switch. The stored choice is not rewritten, so the
     * viewer gets the mode back the moment the board allows it again.
     */
    fun toggleViewMode() {
        val to = ViewMode.nextOf(_ui.value.viewMode)
        if (to == ViewMode.PURE_CINEMA && !_ui.value.pureCinemaAllowed) return
        _ui.update { it.copy(viewMode = to) }
        viewModelScope.launch { settingsRepository.saveViewModeChoice(to.name) }
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
     * neither the viewer nor their region expressed a preference (East Asian audio); a
     * viewer who never chose still gets their region's default, Hindi for Desi.
     */
    private fun applyPreferredAudioTrack() {
        val state = _ui.value
        val preferred = state.preferredAudioLanguage?.takeIf { it.isNotBlank() } ?: return
        if (controller == null) return
        val picked = AudioTrackPolicy.pickPreferred(
            state.audioTrackRows(),
            preferred,
            state.preferredAudioFallback,
        ) ?: return
        if (picked == state.selectedAudioId) return
        val option = state.audioTracks.firstOrNull { it.id == picked } ?: return
        selectAudioTrack(option)
    }

    /**
     * The (playback, preference) pair the subtitle row has already honoured.
     *
     * WHY TEXT NEEDS A GATE AUDIO DOES NOT: audio can only ever be asked to select a track or
     * to say nothing, and a hand-picked track simply re-reports itself. The subtitle row also
     * says "turn off", and `onTracksChanged` fires after every selection made from the
     * Subtitles sheet — re-running an Off on that report would silence what the viewer just
     * chose, mid-episode. The pair is keyed on the binge lifecycle rather than the media item,
     * for the same reason the planner is: a silent failover or an Auto move is a new address
     * for the same viewing, and dropping the subtitles under either would be a second bug.
     * A new file, a new episode, or a new preference value changes the pair and re-arms it.
     */
    private var subtitleHonouredFor: Pair<String, String?>? = null

    /**
     * The (playback, preference) pair the bundle's own custom subtitle
     * already honoured — the same fire-once discipline as
     * [subtitleHonouredFor], on its own gate, so loading the overlay file
     * never spends the native row's gate and a sheet selection never
     * re-fetches under the viewer.
     */
    private var bundleCustomSubtitleHonouredFor: Pair<String, String?>? = null

    /**
     * Apply the Settings subtitle language to the text tracks the player just reported.
     *
     * [SubtitleTrackPolicy.decide] makes the three-way call and goes through the same
     * matcher the audio row uses, so a preference typed as "Hindi" finds a track tagged "hi"
     * here exactly as it does for audio, and an unmatched preference leaves the player's own
     * default alone instead of guessing. Off is the same act as the sheet's "Turn subtitles
     * off": it disables the text renderer, which also quietens a native external file.
     */
    private fun applyPreferredSubtitleTrack() {
        if (controller == null) return
        val state = _ui.value
        // Before the gate: a file with no text tracks has nothing to pick and nothing to
        // silence, and it must not spend the pair a file that has tracks will need.
        if (state.subtitleTracks.isEmpty()) return
        val key = bingeBundleKey(store.bundle.value).orEmpty() to state.preferredSubtitleLanguage
        if (key == subtitleHonouredFor) return
        subtitleHonouredFor = key
        when (val decision = SubtitleTrackPolicy.decide(state.subtitleTrackRows(), state.preferredSubtitleLanguage)) {
            SubtitleTrackDecision.TurnOff -> selectSubtitleTrack(null)
            SubtitleTrackDecision.LeaveAlone -> Unit
            is SubtitleTrackDecision.Select -> {
                val option = state.subtitleTracks.firstOrNull { it.id == decision.id } ?: return
                selectSubtitleTrack(option)
            }
        }
    }

    /**
     * Load the bundle's own custom-rendered (SRT/VTT) subtitle track into
     * the overlay (Gap A3). Native tracks reach the Media3 picker through
     * the factory; SRT/VTT are filtered out there by design — the overlay
     * renders them — so without this the bundle's most common subtitle
     * format would arrive and then never display. The pick follows the
     * same policy as the native row ([SubtitleTrackPolicy.decide]): the
     * viewer's language, and nothing when it matches none — never a
     * guess, and Off loads nothing. Fire-once per bundle + preference on
     * its own gate, so a failover hop or a sheet selection never
     * re-fetches under the viewer. A new bundle retires the previous
     * bundle's file; a viewer-picked SAF file is theirs and stays.
     */
    private fun applyBundleCustomSubtitle() {
        val bundle = store.bundle.value ?: return
        val rendition = store.activeRendition() ?: bundle.renditions.firstOrNull() ?: return
        val custom = rendition.tracks.subtitles.filter {
            PlaybackMediaItemFactory.isCustomRenderable(it.format) && !it.url.isNullOrBlank()
        }
        val state = _ui.value
        val key = bingeBundleKey(bundle).orEmpty() to state.preferredSubtitleLanguage
        if (key == bundleCustomSubtitleHonouredFor) return
        bundleCustomSubtitleHonouredFor = key
        if (customSubtitleFromBundle) {
            customSubtitleFile = null
            customSubtitleFromBundle = false
            _ui.update { it.copy(customSubtitleLoaded = null) }
        }
        if (custom.isEmpty()) return
        val rows = custom.mapIndexed { index, track ->
            AudioTrackRow(
                id = "bundle-sub-$index",
                language = track.language,
                label = track.language,
                selected = false,
                supported = true,
            )
        }
        val picked = when (val decision = SubtitleTrackPolicy.decide(rows, state.preferredSubtitleLanguage)) {
            is SubtitleTrackDecision.Select -> custom.getOrNull(rows.indexOfFirst { it.id == decision.id })
            else -> null
        } ?: return
        val url = picked.url ?: return
        viewModelScope.launch {
            val text = fetchSubtitleText(url)
            if (text == null) return@launch
            customSubtitleFile = SubtitleParser.parse(text, SubtitleFormat.fromFileNameOrMime(picked.format ?: ""))
            customSubtitleFromBundle = true
            val label = AudioTrackPolicy.nameFor(picked.language)
                ?: picked.language?.takeIf { it.isNotBlank() } ?: "Subtitles"
            _ui.update { it.copy(customSubtitleLoaded = label) }
        }
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
        // Remember the pick: the next episode (and the next visit) auto-applies this
        // language, not the old Settings choice. The sync delay is deliberately never
        // saved — it belongs to this viewing. Turning subtitles off is a pick too: it
        // saves the literal "Off", because saving nothing would let the region default
        // (English) come back on the next episode and undo the viewer in front of us.
        val language = persistedLanguageFor(option)
        if (language != null) {
            viewModelScope.launch {
                if (trackType == C.TRACK_TYPE_AUDIO) settingsRepository.savePreferredAudioLanguage(language)
                else settingsRepository.savePreferredSubtitleLanguage(language)
            }
        } else if (trackType == C.TRACK_TYPE_TEXT) {
            viewModelScope.launch {
                settingsRepository.savePreferredSubtitleLanguage(ServerSettingsRepository.SUBTITLE_OFF)
            }
        }
    }

    // ── Subtitles: settings + external files ─────────────────────────────────────

    /**
     * Change how subtitles look, and remember it. Size, seat, weight, plate and colour are the
     * viewer's own style and survive a restart, a process kill and the next title; the sync
     * offset is the one field the store is never told, because it belongs to this viewing.
     */
    fun setSubtitleSettings(settings: SubtitleUiSettings) {
        val style = settings.clamped()
        _ui.update { it.copy(subtitle = style) }
        viewModelScope.launch { settingsRepository.saveSubtitleStyle(style) }
    }

    /** Bundle-provided or SAF-picked external subtitle. SRT/VTT → our overlay (delay read
     *  directly); exotic formats → Media3 SubtitleConfiguration (delay via the decoder wrapper). */
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
                customSubtitleFromBundle = false
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
        customSubtitleFromBundle = false
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

    /**
     * Series auto-delete (Session 123): a series episode the viewer just
     * finished, whose keep is complete, deletes itself — the same promise the
     * Downloads sweep already keeps for movies, extended to the one case the
     * sweep cannot identify. The sweep matches by title against movie rows
     * only, because one watched episode must never delete the whole season;
     * here the identity is exact instead — this player holds the episode's
     * own cache key, and only a complete keep (`KeepUiState.Stored`) is
     * touched, so a keep still fetching is left alone. Movies keep their
     * sweep and are never touched here; the message names what went, so the
     * deletion is never silent.
     */
    private fun maybeAutoDeleteWatchedEpisode() {
        if (!autoDeleteWatched) return
        val bundle = store.bundle.value ?: return
        val target = bundle.target
        val episode = target.episode.takeIf { it > 0 } ?: store.currentSyncScope()?.episode ?: 0
        if (episode <= 0) return
        if (_ui.value.keep !is KeepUiState.Stored) return
        val engine = CacheEngineHolder.engine ?: return
        val key = store.cacheKey() ?: return
        viewModelScope.launch {
            runCatching { engine.cancelKeep(key) }
            _events.emit(PlayerEvent.Message("Deleted Episode $episode — you finished watching it."))
        }
    }

    // ── Episode progression + offsets ────────────────────────────────────────────

    private fun handleCrossEpisodeAction(action: NextEpisodeAction) {
        store.clearNextEpisode()
        when (action) {
            is NextEpisodeAction.NextBundleRequest -> viewModelScope.launch {
                // The autoplay-next switch (plan §5 step 10, P36) is the promise: with it
                // off, the episode ends on the Next Episode button instead of advancing.
                // The action is already consumed above, so the button re-derives the next
                // episode through requestNextEpisode — nothing here fires twice.
                if (!shouldAutoAdvance(autoplayNext, action)) {
                    _ui.update { it.copy(endedHasNextEpisode = true) }
                    return@launch
                }
                // Session 123 (PL-1): the episode no longer advances the instant it
                // ends. The viewer gets ten seconds and a Cancel first — the advance
                // waits for the countdown to finish.
                startAutoplayCountdown(action)
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

    /**
     * The autoplay-next countdown (Session 123, PL-1).
     *
     * The state is the pure [AutoplayCountdown] ticking once a second; the
     * advance it fires is exactly the path that used to run the instant the
     * episode ended — the between-episodes break decision, then the advance —
     * only delayed by ten seconds. Cancelling the job (the viewer's Cancel, a
     * manual Next, a new bundle, or the ViewModel dying) drops the held action
     * without firing it: a countdown that never reaches zero advances nothing.
     */
    private fun startAutoplayCountdown(action: NextEpisodeAction.NextBundleRequest) {
        clearAutoplayCountdown()
        pendingAutoplayAction = action
        autoplayCountdownJob = viewModelScope.launch {
            var countdown = AutoplayCountdown.start()
            while (true) {
                _ui.update { it.copy(autoplayCountdownSeconds = countdown.secondsLeft) }
                delay(1_000L)
                countdown = countdown.tick() ?: break
            }
            _ui.update { it.copy(autoplayCountdownSeconds = null) }
            val held = pendingAutoplayAction
            pendingAutoplayAction = null
            if (held == null) return@launch
            // Session 126 (PL-2): the countdown used to ask the sponsor seam here and
            // hold the advance behind a fake ad. There is no ad to show and no network
            // to fill one, so the advance runs now, exactly as the viewer expected.
            advanceCrossEpisode(held)
        }
    }

    /** The countdown's Cancel: stay on the ended episode and offer the buttons instead. */
    fun cancelAutoplayCountdown() {
        clearAutoplayCountdown()
        _ui.update { it.copy(autoplayCountdownSeconds = null, endedHasNextEpisode = true) }
    }

    /** Drops the countdown and its held action without firing either. */
    private fun clearAutoplayCountdown() {
        autoplayCountdownJob?.cancel()
        autoplayCountdownJob = null
        pendingAutoplayAction = null
        _ui.update { it.copy(autoplayCountdownSeconds = null) }
    }

    /**
     * The successor hand-off itself: the prepared bundle opened at 85% wins, then a cold resolve,
     * and only then the app route.
     */
    private suspend fun advanceCrossEpisode(action: NextEpisodeAction.NextBundleRequest) {
        // The prepared successor (resolved at 85%) opens without a catalog lookup;
        // a cold END still resolves on demand before falling back to the app route.
        if (openNextEpisode(action.season, action.nextEpisode, action.postId)) return
        _events.emit(
            PlayerEvent.PlayNextEpisode(
                workKey = action.workKey,
                postId = action.postId,
                season = action.season,
                episode = action.nextEpisode,
            ),
        )
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
        // The server post (Session 123): the catalog's own episode id rides on
        // the coverage's enumerated episodes. When it resolves, the offset is
        // shared with every later viewer at once; when it does not (an older
        // bundle without episode ids), the local learned offset still stands
        // and the deferred reporter keeps the report queued for the server.
        val episodeId = rendition.coverage.episodes
            .firstOrNull { it.number == episodeNumber }
            ?.episodeId
        viewModelScope.launch {
            val shared = episodeId?.let {
                catalogRepository.reportEpisodeOffset(
                    episodeId = it,
                    offsetSeconds = report.offsetSeconds,
                    chapterTitle = report.chapterTitle,
                    releaseLabel = report.releaseLabel,
                )
            } == true
            val queued = !shared && store.offsetReporter is DeferredOffsetReporter
            _events.emit(
                PlayerEvent.Message(
                    "Episode $episodeNumber marked at ${(position / 1000L).formatTime()}" +
                        (if (shared) " (shared with the server)" else if (queued) " (queued for server)" else ""),
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

    /**
     * Re-attaches the cache observer to the CURRENT rendition (called on every switch).
     *
     * With the operator's downloads switch off the chip is removed rather than left clickable:
     * [KeepUiState.Unavailable] is the state this screen already renders as "no keep here".
     */
    fun refreshKeepState() {
        keepJob?.cancel()
        latestSnapshot = null
        val engine = CacheEngineHolder.engine
        val key = store.cacheKey()
        if (engine == null || key == null || !downloadsAllowed ||
            store.bundle.value?.target?.kind == "local"
        ) {
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
        // PL-5: a local file is already on this device — there is nothing to keep, and
        // the tap says so instead of offering a download of a file that is already here.
        if (store.bundle.value?.target?.kind == "local") {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("Already on this device"))
            }
            return
        }
        if (!downloadsAllowed) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("Keeping files for offline is switched off for this server"))
            }
            return
        }
        // Session 123: the same Wi-Fi-only gate the detail screen's Keep
        // honours. A hundreds-of-megabytes download starting on mobile data
        // because the viewer tapped Keep mid-playback is the expensive
        // mistake the switch exists to prevent — the message says where the
        // switch lives, so the tap is never left guessing.
        if (DataSaver.wifiOnlyBlocks(wifiOnlyDownloads, connectivityProbe.current() == NetworkClass.WIFI)) {
            viewModelScope.launch {
                _events.emit(PlayerEvent.Message("Wi-Fi only is on — connect to Wi-Fi to download this title. You can change it in Settings."))
            }
            return
        }
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
                title = _ui.value.pendingTitle ?: "",
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
            // A null window is the pinned answer the tap above produced — no auto-delete — so it
            // gets the words that are true for it. "TTL unknown" would describe a missing number
            // with the vocabulary of a promise kept forever.
            "Kept — playable in ${Brand.shortName} only" +
                (result.ttlSeconds?.let { " (${it / 3600} h)" } ?: " until you delete it"),
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

        /** At most one local history write per this interval; a forced stop always writes. */
        const val HISTORY_WRITE_INTERVAL_MS = 15_000L
    }
}

/** Long → "h:mm:ss" / "m:ss" — top-level so both ViewModel and UI can reuse it. */
fun Long.formatTime(): String {
    val totalSeconds = this / 1000
    val seconds = totalSeconds % 60
    val minutes = (totalSeconds / 60) % 60
    val hours = totalSeconds / 3600
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds)
    else "%d:%02d".format(minutes, seconds)
}

/** What the screen must route elsewhere (next-episode bundle, external hand-off). */
sealed class PlayerEvent {
    data class Message(val text: String) : PlayerEvent()
    data class PlayNextEpisode(val workKey: String?, val postId: Int?, val season: Int, val episode: Int) : PlayerEvent()
    data class OpenExternalPlayer(val url: String) : PlayerEvent()
    /** SC.24: share-a-moment text for the system share sheet. */
    data class ShareMoment(val text: String) : PlayerEvent()
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

/**
 * The language a live track pick writes back to Settings, or null when the pick
 * says nothing about the standing preference. A picked track's language is the
 * viewer's choice for this show and the next visit; turning subtitles off is
 * viewing-scoped — it must not delete the stored language, or the next episode
 * would start silent for a viewer who wants Hindi. A track with no language tag
 * has nothing to persist either.
 *
 * Top-level (not a ViewModel member) so the unit test can call it directly — the
 * ViewModel's eight injected deps have no fakes anywhere in the repo.
 */
internal fun persistedLanguageFor(option: TrackUiOption?): String? =
    option?.language?.trim()?.takeIf { it.isNotEmpty() }

/**
 * What one `/api/v1/stream` lookup established: the body if there was one, the status if the
 * transport answered, and [noAnswer] when nothing came back at all. See
 * `viewmodel/AdultPolicy.serverAnswerFor` for what each combination is allowed to conclude.
 */
data class HandleProbe(
    val response: com.raddstream.app.network.models.StreamResponse?,
    val httpStatus: Int?,
    val bodyClaimsSuccess: Boolean?,
    val noAnswer: Boolean,
) {
    val answer: AdultPolicy.ServerAnswer
        get() = AdultPolicy.serverAnswerFor(httpStatus, response?.success ?: bodyClaimsSuccess, noAnswer)
}

/** The only wording a refused successor may get. No title, no handle, no upstream address. */
private const val NEXT_UNAVAILABLE = "The next episode is no longer offered by this server."
