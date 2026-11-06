package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.data.local.WatchHistoryMerge
import com.raddstream.app.repository.FavoritesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Watch history, from the same source the Continue watching rail reads — local rows this
 * device wrote while playing, folded with a newer synced position for the same scope —
 * minus the rail's one filter: this screen lists everything, newest first, including a
 * title watched to the end. The refusal filter is the same one the rail applies
 * ([AdultPolicy.listableRows]), so a title the server stopped serving does not reappear
 * here after leaving Home.
 */
@HiltViewModel
class WatchHistoryViewModel @Inject constructor(
    private val watchHistoryDao: WatchHistoryDao,
    private val syncedProgressDao: SyncedProgressDao,
    private val favoritesRepository: FavoritesRepository,
) : ViewModel() {

    private val _rows = MutableStateFlow<List<HistoryRow>>(emptyList())
    val rows = _rows.asStateFlow()

    init {
        viewModelScope.launch {
            combine(
                watchHistoryDao.observeRecent(WatchHistoryMerge.HISTORY_LIMIT * 2),
                syncedProgressDao.observeRecent(WatchHistoryMerge.HISTORY_LIMIT * 2),
                favoritesRepository.observeRefusedIds(),
            ) { local, synced, refused ->
                // A history row is a cached surface like any other: it names a work this
                // device watched, and the ledger may have refused an answer about it since.
                // `flagOf` is a constant null because `watch_history` keeps no adult column —
                // the table is written by playback, and no payload ever told us a flag. Null is
                // "not told", which [AdultPolicy] reads as no evidence either way, so the refusal
                // is what removes a row here and a 200 later puts it back.
                AdultPolicy.listableRows(
                    rows = WatchHistoryMerge.mergeAll(local, synced),
                    flagOf = { null },
                    refusedOf = { it.postId in refused },
                )
            }
                .collect { merged ->
                    _rows.value = merged.map { WatchHistoryRow.of(it) }
                }
        }
    }
}
