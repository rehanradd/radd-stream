package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.FavoritesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

enum class ListSort(val label: String) { RECENT("Recently added"), TITLE("Title A–Z") }

data class MyListUiState(
    val favorites: List<Post> = emptyList(),
    val sort: ListSort = ListSort.RECENT,
    val isLoading: Boolean = false,
    /** The row whose removal the viewer has asked for and not yet confirmed, by id. */
    val armedRemovalId: Int? = null,
    /**
     * Saved rows this device may not list — flagged by a payload, or refused by the server since
     * they were saved. Count only, never names: an "unavailable: <title>" line is a list of one,
     * which is the thing the invariant forbids.
     */
    val hiddenCount: Int = 0,
) {
    /** The one sentence [hiddenCount] may become. */
    val hiddenNotice: String? get() = AdultPolicy.hiddenNotice(hiddenCount)
}

@HiltViewModel
class MyListViewModel @Inject constructor(
    private val favoritesRepository: FavoritesRepository,
) : ViewModel() {

    private val sortFlow = MutableStateFlow(ListSort.RECENT)
    private val armedRemoval = MutableStateFlow<Int?>(null)

    init {
        // Re-ask about the saved rows whose last answer has aged out, in the background. Opening
        // My List is the moment a stale clearance matters, and a pass that hid rows on a socket
        // error would be worse than the hole it closes — see AdultPolicy.serverAnswerFor.
        viewModelScope.launch { favoritesRepository.revalidateSavedRows() }
    }

    val uiState: StateFlow<MyListUiState> = combine(
        favoritesRepository.getAllFavorites(),
        favoritesRepository.observeRefusedIds(),
        sortFlow,
        armedRemoval,
    ) { list, refusedIds, sort, armed ->
        // The filter runs HERE, before anything reaches a LazyColumn item, because this list is
        // drawn from Room with no network in the loop: the server's SQL clause cannot reach a row
        // this device saved last month and the ledger hid yesterday.
        val visible: List<FavoritePost> = AdultPolicy.listableRows(
            rows = list,
            flagOf = FavoritePost::is18Plus,
            refusedOf = { it.id in refusedIds },
        )
        val sorted: List<FavoritePost> = when (sort) {
            ListSort.RECENT -> visible.sortedByDescending { it.addedAt }
            ListSort.TITLE -> visible.sortedBy { (it.cleanTitle ?: it.title).lowercase() }
        }
        MyListUiState(
            favorites = sorted.map(FavoritePost::toPost),
            sort = sort,
            isLoading = false,
            armedRemovalId = armed,
            hiddenCount = list.size - visible.size,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = MyListUiState(isLoading = true),
    )

    fun setSort(sort: ListSort) {
        sortFlow.value = sort
    }

    /** A held tile is a wish. It becomes a deletion only when [confirmRemoval] says so. */
    fun requestRemoval(postId: Int) =
        takeStep(MyListRemoval.step(armedRemoval.value, RemovalTrigger.LONG_PRESS, postId))

    fun confirmRemoval() =
        takeStep(MyListRemoval.step(armedRemoval.value, RemovalTrigger.CONFIRM, null))

    fun cancelRemoval() =
        takeStep(MyListRemoval.step(armedRemoval.value, RemovalTrigger.CANCEL, null))

    private fun takeStep(step: RemovalStep) {
        armedRemoval.value = step.armed
        step.removeNow?.let { id ->
            viewModelScope.launch { favoritesRepository.removeFavorite(id) }
        }
    }
}
