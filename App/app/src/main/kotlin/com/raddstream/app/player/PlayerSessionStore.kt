package com.raddstream.app.player

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

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

    /** Load requests posted by the ViewModel, consumed by the service via [currentRequest]. */
    private val _loadRequest = MutableStateFlow<LoadRequest?>(null)
    val loadRequest: StateFlow<LoadRequest?> = _loadRequest.asStateFlow()

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
    }

    fun renditions(): List<PlaybackRendition> = _bundle.value?.renditions.orEmpty()

    fun activeRendition(): PlaybackRendition? = renditions().getOrNull(_activeRenditionIndex.value)

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
    }
}
