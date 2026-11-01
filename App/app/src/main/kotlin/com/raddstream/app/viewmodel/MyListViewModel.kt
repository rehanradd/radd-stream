package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.FavoritesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
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
     * Rows this device still stores and this build may not draw. Counted, never listed: the
     * viewer's list did not shrink, the server's answer about it changed.
     */
    val hiddenCount: Int = 0,
) {
    /** [AdultPolicy.hiddenNotice] — a number, because a notice naming a hidden title is a list of one. */
    val hiddenNotice: String? get() = AdultPolicy.hiddenNotice(hiddenCount)
}

@HiltViewModel
class MyListViewModel @Inject constructor(
    private val favoritesRepository: FavoritesRepository,
) : ViewModel() {

    private val sortFlow = MutableStateFlow(ListSort.RECENT)
    private val armedRemoval = MutableStateFlow<Int?>(null)

    val uiState: StateFlow<MyListUiState> = combine(
        favoritesRepository.getAllFavorites(),
        favoritesRepository.observeRefusedIds(),
        sortFlow,
        armedRemoval,
    ) { list, refused, sort, armed ->
        // The stored rows are filtered here, before anything sorts or maps them, so no later step
        // can be handed the unfiltered list by accident. `is18Plus` is the strict half and is null
        // for every row on today's wire; the refusal ledger is the half that fires against a public
        // route that 404s a flagged id exactly as it 404s an absent one.
        val visible = AdultPolicy.listableRows(
            rows = list,
            flagOf = FavoritePost::is18Plus,
            refusedOf = { it.id in refused },
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

    init {
        viewModelScope.launch {
            // One bounded pass per visit: at most
            // [AdultPolicy.MAX_REVALIDATION_CHECKS_PER_PASS] rows, and only rows whose last answer
            // has aged out, so opening My List a second time the same day asks nothing. What it
            // learns lands on the ledger, which re-emits [uiState] through the combine above — a
            // row the server has since refused leaves the grid while the viewer is looking at it.
            //
            // A pass that cannot finish may not cost the viewer the list they came for: the rows on
            // screen are already filtered by whatever the ledger holds, and the next visit tries
            // again. [com.raddstream.app.repository.CatalogRepository.probePost] reports a transport
            // failure as an absence of an answer rather than as a refusal, so the ordinary outage
            // never reaches this catch; the catch is for a database or wiring fault.
            try {
                favoritesRepository.revalidateSavedRows()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                // The ledger keeps what it held. Nothing here may hide or un-hide a row.
            }
        }
    }

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
