package com.raddstream.app.player

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * One playhead reading in TIME, published by the player for the cache engine to convert into a byte
 * offset. Deliberately tiny: it carries our redirector address (the same [CacheSessionKey.url] the
 * affordance already keys on) plus the position/duration the engine needs — no provenance, no byte
 * math here. The wiring layer owns turning this into [com.raddstream.app.data.cache.CoverageMapping]
 * bytes.
 */
data class PlayheadTick(val url: String, val positionMs: Long, val durationMs: Long)

/**
 * In-process junction between [PlaybackService] (owns the ExoPlayer) and PlayerViewModel
 * (owns the UI state). The service and the UI live in the SAME process (no `android:process`
 * on the service in AndroidManifest.xml), so a plain observable store is the simplest
 * Media3-idiomatic way to share the PlayBundle and the failover narration without
 * serializing it through Intent extras.
 *
 * The ViewModel is created by Hilt; this store is deliberately a process singleton exposed
 * via [Companion.Instance] so the service can read it WITHOUT any new Hilt module
 * (the di package belongs to another agent — see HANDOFF_appplayer.md if a real binding is wanted).
 * Tests construct their own instance.
 */
class PlayerSessionStore(
    val offsetReporter: OffsetReporter = DeferredOffsetReporter(),
    val learnedOffsets: LearnedOffsetStore = LearnedOffsetStore(),
) {

    private val _bundle = MutableStateFlow<PlaybackBundle?>(null)
    val bundle: StateFlow<PlaybackBundle?> = _bundle.asStateFlow()

    private val _activeRenditionIndex = MutableStateFlow(-1)
    val activeRenditionIndex: StateFlow<Int> = _activeRenditionIndex.asStateFlow()

    private val _failoverLog = MutableStateFlow<List<FailoverRecord>>(emptyList())
    val failoverLog: StateFlow<List<FailoverRecord>> = _failoverLog.asStateFlow()

    /** "Settled on ..." banner content; null = silent start. */
    private val _settledBanner = MutableStateFlow<String?>(null)
    val settledBanner: StateFlow<String?> = _settledBanner.asStateFlow()

    /** Set by the service when playback fully died; UI shows retry / keep-on-device actions. */
    private val _giveUp = MutableStateFlow<Pair<String, HandoffWhy>?>(null)
    val giveUp: StateFlow<Pair<String, HandoffWhy>?> = _giveUp.asStateFlow()

    /** The active file ended and continuing needs UI/app involvement (next episode flow). */
    private val _nextEpisode = MutableStateFlow<NextEpisodeAction?>(null)
    val nextEpisode: StateFlow<NextEpisodeAction?> = _nextEpisode.asStateFlow()

    /**
     * The playhead tap the offline cache engine reads to buffer ahead of playback. Drop-oldest with
     * a one-slot buffer: a fast player never needs to queue history, and a slow engine consumer must
     * not be fed stale positions. [reportPlayhead] is the minimal public hook the player calls.
     */
    private val _playhead = MutableSharedFlow<PlayheadTick>(
        replay = 0,
        extraBufferCapacity = 1,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val playhead: SharedFlow<PlayheadTick> = _playhead.asSharedFlow()

    fun reportPlayhead(url: String?, positionMs: Long, durationMs: Long) {
        val clean = url?.trim()?.takeIf { it.isNotEmpty() } ?: return
        _playhead.tryEmit(PlayheadTick(clean, positionMs.coerceAtLeast(0L), durationMs.coerceAtLeast(0L)))
    }

    /**
     * The rung Auto is currently playing, mirrored for the UI. Null when Auto is not armed
     * (a hand-picked band, or a deep-linked title with no staged ladder), which is exactly
     * when the top bar must NOT show an Auto label.
     */
    private val _autoBand = MutableStateFlow<String?>(null)
    val autoBand: StateFlow<String?> = _autoBand.asStateFlow()

    fun setAutoBand(band: String?) {
        _autoBand.value = band?.takeIf { it.isNotBlank() }
    }

    /** Load requests posted by the ViewModel, consumed by the service via [currentRequest]. */
    private val _loadRequest = MutableStateFlow<LoadRequest?>(null)
    val loadRequest: StateFlow<LoadRequest?> = _loadRequest.asStateFlow()

    /**
     * The one Auto-quality picture, shared on purpose: the service feeds it measured
     * transfers and asks it which rung to play, the ViewModel only reads [currentBand] and
     * [estimateBps] to label the top bar. Two players would mean two estimates and two
     * opinions about the same network, which is how a quality switch oscillates.
     */
    val autoQuality = AutoQualityDirector()

    data class LoadRequest(
        val nonce: Long,
        val resumePositionMs: Long,
        val startOverrideMs: Long?,
        val title: String,
    )

    fun requestLoad(title: String, resumePositionMs: Long = 0, startOverrideMs: Long? = null) {
        _loadRequest.value = LoadRequest(System.nanoTime(), resumePositionMs, startOverrideMs, title)
    }

    fun awaitNextEpisode(action: NextEpisodeAction) {
        _nextEpisode.value = action
    }

    fun clearNextEpisode() {
        _nextEpisode.value = null
    }

    fun installBundle(newBundle: PlaybackBundle) {
        _bundle.value = newBundle
        _failoverLog.value = emptyList()
        _giveUp.value = null
        _nextEpisode.value = null
        _activeRenditionIndex.value = -1
        _settledBanner.value = null
        // A new bundle is a new network picture and a new ladder; carry neither over.
        _autoBand.value = null
    }

    fun renditions(): List<PlaybackRendition> = _bundle.value?.renditions.orEmpty()

    fun activeRendition(): PlaybackRendition? = renditions().getOrNull(_activeRenditionIndex.value)

    /**
     * Swap one rendition in place after Auto moved the playback to another rung of the SAME
     * ladder. Index-preserving on purpose: the failover plan, the cache session and the
     * resume position all key off the position in the list, and a rung change must not look
     * like a candidate change to any of them.
     */
    fun replaceRendition(index: Int, rendition: PlaybackRendition) {
        val b = _bundle.value ?: return
        val list = b.renditions
        if (index !in list.indices) return
        _bundle.value = b.copy(renditions = list.toMutableList().also { it[index] = rendition })
    }

    fun setActiveIndex(index: Int, announceSettled: Boolean = false) {
        _activeRenditionIndex.value = index
        if (announceSettled) {
            val r = activeRendition()
            val died = _failoverLog.value.count { it.action != "skipped" }
            _settledBanner.value = r?.displayLabel()?.let { label ->
                if (died > 0) "Playing: $label (after $died failed candidate${if (died == 1) "" else "s"})"
                else "Playing: $label"
            }
        }
    }

    fun appendFailover(records: List<FailoverRecord>) {
        _failoverLog.value = _failoverLog.value + records
    }

    fun resetFailoverLog() {
        _failoverLog.value = emptyList()
    }

    fun markGaveUp(reason: String, why: HandoffWhy) {
        _giveUp.value = reason to why
    }

    fun clearGaveUp() {
        _giveUp.value = null
    }

    fun clearSettledBanner() {
        _settledBanner.value = null
    }

    /** Cache boundary identity for the current rendition (see CacheContract.kt). */
    fun cacheKey(): CacheSessionKey? {
        val b = _bundle.value ?: return null
        val r = activeRendition() ?: return null
        val url = r.playback.playUrl ?: return null
        if (url.isBlank()) return null
        return CacheSessionKey(
            renditionKey = "${b.session.id ?: "s"}-${r.releaseId}-${r.rank}",
            url = url,
        )
    }

    companion object {
        /** Process-wide instance used by the service and the screen's ViewModel. */
        val Instance: PlayerSessionStore by lazy { PlayerSessionStore() }

        /** A handful of open titles is all the staging a back-navigation ever needs. */
        const val MAX_STAGED_FAILOVERS = 24
    }

    /**
     * The silent runner-ups of the rung a playback is about to start from, staged by
     * the detail screen and read by the player.
     *
     * WHY HERE AND NOT IN THE NAVIGATION ROUTE: the route stays one opaque handle
     * (`player/{streamId}/{title}`), so a ladder of handles never enters the back
     * stack, saved state, a `radd://` deep link or a log. Handles only, in memory
     * only, on the main thread only — nothing here survives a process death, and a
     * deep-linked playback simply starts with no runner-ups, exactly as before.
     */
    private val stagedFailovers = LinkedHashMap<String, List<String>>()

    fun stageFailover(streamId: String, handles: List<String>) {
        if (streamId.isBlank()) return
        val clean = handles.filter { it.isNotBlank() && it != streamId }
        stagedFailovers.remove(streamId)
        if (clean.isNotEmpty()) stagedFailovers[streamId] = clean
        while (stagedFailovers.size > MAX_STAGED_FAILOVERS) {
            stagedFailovers.remove(stagedFailovers.keys.first())
        }
    }

    /** Read without consuming: re-opening the same rung still gets its runner-ups. */
    fun peekFailover(streamId: String): List<String> = stagedFailovers[streamId].orEmpty()

    fun clearStagedFailovers() {
        stagedFailovers.clear()
    }

    /**
     * The rung list Auto may move along, staged by the detail screen next to the runner-ups
     * of the launched rung and read by the service when it arms [autoQuality].
     *
     * Same discipline as [stageFailover]: bands and handles only, in memory only, nothing
     * survives a process death. A deep-linked playback simply has no ladder, so Auto has
     * nowhere to move and stays silent rather than inventing a rung.
     */
    private val stagedAutoLadders = LinkedHashMap<String, AutoLadderPlan>()

    fun stageAutoLadder(streamId: String, rungs: List<LadderRung>, startBand: String?, auto: Boolean) {
        if (streamId.isBlank()) return
        val usable = rungs.filter { it.usable }.distinctBy { it.band }
        stagedAutoLadders.remove(streamId)
        if (usable.isNotEmpty()) {
            stagedAutoLadders[streamId] = AutoLadderPlan(usable, startBand?.takeIf { it.isNotBlank() }, auto)
        }
        while (stagedAutoLadders.size > MAX_STAGED_FAILOVERS) {
            stagedAutoLadders.remove(stagedAutoLadders.keys.first())
        }
    }

    fun peekAutoLadder(streamId: String?): AutoLadderPlan? =
        streamId?.trim()?.takeIf { it.isNotEmpty() }?.let { stagedAutoLadders[it] }

    fun clearStagedAutoLadders() {
        stagedAutoLadders.clear()
    }

    /** One scope's rung list, the rung playback starts on, and whether Auto owns the choice. */
    data class AutoLadderPlan(
        val rungs: List<LadderRung>,
        val startBand: String?,
        val auto: Boolean,
        /** The rung the server called best-and-playable — what choosing "Auto" means here. */
        val autoBand: String? = null,
    )
}
