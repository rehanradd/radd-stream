package com.raddstream.app.viewmodel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.MimeTypes
import com.raddstream.app.network.models.LiveTvChannel
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

/**
 * The Live TV tab's state: one server fetch, then client-side filtering.
 *
 * The served list is small (17 channels at v1), so the category chips and
 * the name search filter the rows already on the device instead of a
 * network round-trip per tap. The endpoint's own `?category=` filter stays
 * available for a day the list grows large enough to page.
 *
 * A channel is played by its signed `stream_id` handle through the existing
 * player — this ViewModel never holds, shows or routes an upstream URL.
 *
 * App-design audit #13: the last good list is cached on this device, so a
 * down server shows yesterday's channels (labelled as cached) instead of
 * a dead tab. The tab itself is never hidden — the backend fix for the
 * 503 is a server job; the app's job is to fail gracefully.
 */
@HiltViewModel
class LiveTvViewModel @Inject constructor(
    private val repository: CatalogRepository,
    @ApplicationContext private val context: Context,
) : ViewModel() {

    data class UiState(
        val isLoading: Boolean = true,
        val channels: List<LiveTvChannel> = emptyList(),
        val categories: List<String> = emptyList(),
        val selectedCategory: String? = null,
        val query: String = "",
        val error: String? = null,
        /** True when [channels] are the saved list, not a fresh fetch. */
        val showingCached: Boolean = false,
    ) {
        /** What the grid shows: the chosen category, then the name search. */
        val visibleChannels: List<LiveTvChannel>
            get() {
                val byCategory = if (selectedCategory == null) {
                    channels
                } else {
                    channels.filter { it.category == selectedCategory }
                }
                val needle = query.trim().lowercase()
                return if (needle.isEmpty()) {
                    byCategory
                } else {
                    byCategory.filter { it.name.lowercase().contains(needle) }
                }
            }
    }

    private val _uiState = MutableStateFlow(UiState())
    val uiState = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val response = repository.getLiveTvChannels()
                saveCache(response.channels, response.categories)
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        channels = response.channels,
                        categories = response.categories,
                        error = null,
                        showingCached = false,
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                // Audit #13/#14: plain words, never a raw code — and the
                // last good list stays on screen when there is one.
                val cached = loadCache()
                if (cached != null) {
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            channels = cached.first,
                            categories = cached.second,
                            error = LIVE_TV_TROUBLE,
                            showingCached = true,
                        )
                    }
                } else {
                    _uiState.update {
                        it.copy(isLoading = false, error = LIVE_TV_TROUBLE)
                    }
                }
            }
        }
    }

    private fun saveCache(channels: List<LiveTvChannel>, categories: List<String>) {
        runCatching {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_CACHED_LIST, LiveTvCache.encode(channels, categories))
                .apply()
        }
    }

    private fun loadCache(): Pair<List<LiveTvChannel>, List<String>>? = runCatching {
        val json = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_CACHED_LIST, null)
        LiveTvCache.decode(json)
    }.getOrNull()

    companion object {
        const val LIVE_TV_TROUBLE =
            "Live TV is having trouble right now. Check your connection or try again."
        private const val PREFS_NAME = "live_tv_cache"
        private const val KEY_CACHED_LIST = "cached_list"
    }

    fun onCategorySelected(category: String?) {
        _uiState.update { it.copy(selectedCategory = category) }
    }

    fun onQueryChanged(query: String) {
        _uiState.update { it.copy(query = query) }
    }

    private var warmJob: Job? = null
    private var lastWarmedHandle: String? = null

    /**
     * Batch C — warm one channel's link in the background, on tap.
     *
     * The tap navigates straight to the player with a cold handle, so the
     * player pays the server's live resolve (~1.6 s for a live channel,
     * measured 2026-11-14) inside "Finding your video". This ask is
     * metadata only (`GET /api/v1/stream?redirect=0`): on a cache miss the
     * server live-resolves the link and banks the answer, so the player's
     * redirector 302s from cache instead. It runs in parallel with the
     * navigation — it never gates it — and a warm that fails is silent:
     * Play still works, it just waits on the first bytes again. Same shape
     * as DetailViewModel.warmScopeLink, and the same guard
     * ([shouldWarmHandle]). No byte seed here — HLS is a live playlist,
     * not a file — and no warm store: the player never calls
     * `resolveStream` at start (it follows the redirector's 302), so the
     * banked server answer is the whole mechanism.
     */
    fun warmChannel(streamId: String) {
        if (!shouldWarmHandle(streamId, lastWarmedHandle)) return
        warmJob?.cancel()
        warmJob = viewModelScope.launch {
            val warmed = runCatching {
                withTimeout(30_000) { repository.resolveStream(streamId) }
            }.isSuccess
            if (warmed) lastWarmedHandle = streamId
        }
    }

    /**
     * Live TV is HLS, always: every channel in the registry serves an
     * `.m3u8` playlist (759/759), and the player opens the bare handle
     * through our extensionless redirector — which carries no `.m3u8` for
     * the reader to infer from. Staging the manifest MIME here is what lets
     * the player declare HLS before the first frame instead of opening the
     * playlist with the progressive reader (`UnrecognizedInputFormatException`,
     * Robo #4). Same in-memory-only discipline as the warm: a playback
     * launched any other way simply has no entry and builds as before.
     */
    fun stageLiveChannel(streamId: String) {
        PlayerSessionStore.Instance.stageManifestMime(streamId, MimeTypes.APPLICATION_M3U8)
    }
}
