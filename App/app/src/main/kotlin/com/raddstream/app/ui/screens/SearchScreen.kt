package com.raddstream.app.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.player.PastedText
import com.raddstream.app.player.classifyPastedText
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.InlineLoadFailure
import com.raddstream.app.ui.components.ErrorState
import com.raddstream.app.ui.components.LoadingState
import com.raddstream.app.ui.components.MediaRail
import com.raddstream.app.ui.components.Pill
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.components.SectionHeader
import com.raddstream.app.ui.components.raddFilterChipColors
import com.raddstream.app.viewmodel.GenreFilter
import com.raddstream.app.viewmodel.IndustryFilter
import com.raddstream.app.viewmodel.QualityFilter
import com.raddstream.app.viewmodel.SearchSort
import com.raddstream.app.viewmodel.SearchUiState
import com.raddstream.app.viewmodel.SearchViewModel
import com.raddstream.app.viewmodel.resultsSummary

private val typeChips = listOf(
    "All" to null,
    "Movies" to "movie",
    "Series" to "series",
    // Not a `content_type`: the server answers `type=anime` from the `is_animated` flag.
    "Anime" to "anime",
    "Seasons" to "complete_season",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
// Session 121 (P-30): Search is a bottom-nav tab root — there is nowhere to go back
// to from it, so the top bar carries no back arrow and takes no callback. (The Home
// search bar navigates to this same tab, not to a pushed copy.)
fun SearchScreen(
    onPostClick: (Int) -> Unit = {},
    onPlayDirectUrl: (url: String, title: String) -> Unit = { _, _ -> },
    /** A query to run at once — an actor tap on a detail card lands here with the name filled in. */
    initialQuery: String? = null,
    viewModel: SearchViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    var showSheet by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    // Session 121 (P-12): submitting a search, or scrolling the results, dismisses
    // the keyboard — an open keyboard over the results was the whole complaint.
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current

    // An actor tap runs as a search at once — and is recorded as a recent,
    // like any search the viewer ran. Keyed on the argument, so a rotation
    // or a later edit never re-runs it.
    LaunchedEffect(initialQuery) {
        if (!initialQuery.isNullOrBlank()) viewModel.runRecent(initialQuery)
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                // Session 121 (P-13): the count lives in the body, next to Sort —
                // the top bar saying "12 results" as well was the same number twice.
                title = { Text("Search") },
                actions = {
                    if (state.hasFacetFilters) {
                        // The pill names the facets, never the sort — and it
                        // opens the sheet, so a viewer can see which filters
                        // are actually on instead of taking the pill's word.
                        Box(
                            modifier = Modifier.clickable(
                                role = Role.Button,
                                onClickLabel = "Open filters",
                            ) { showSheet = true },
                        ) {
                            Pill(text = "Filtered", backgroundColor = MaterialTheme.colorScheme.primaryContainer, contentColor = MaterialTheme.colorScheme.onPrimaryContainer)
                        }
                        Spacer(Modifier.width(8.dp))
                    }
                    IconButton(onClick = { showSheet = true }) {
                        Icon(Icons.Default.Tune, contentDescription = "Filters and sort")
                    }
                },
            )
        },
    ) { contentPadding ->
        // Session 120: the open keyboard covered the top row of results and the
        // empty-state hint hid behind its clipboard bar — the content never
        // accounted for the IME. imePadding lifts the whole column above the
        // keyboard (with adjustResize in the manifest) so results stay
        // reachable while typing.
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .imePadding()
                .padding(horizontal = 16.dp),
        ) {
            OutlinedTextField(
                value = state.query,
                onValueChange = viewModel::onQueryChanged,
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                // The API searches titles and cast names, so the label says
                // both honestly — "actors or genres" would still promise
                // what the server cannot do.
                label = { Text("Search for a title or an actor") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                trailingIcon = {
                    if (state.query.isNotEmpty()) {
                        IconButton(onClick = { viewModel.onQueryChanged("") }) {
                            Icon(Icons.Default.Close, contentDescription = "Clear search")
                        }
                    }
                },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                // Session 121 (P-12): searching dismisses the keyboard so the
                // results are visible instead of sitting under it.
                keyboardActions = KeyboardActions(onSearch = {
                    focusManager.clearFocus()
                    keyboardController?.hide()
                    viewModel.submitCurrentQuery()
                }),
            )

            Spacer(Modifier.height(8.dp))
            val pasted = classifyPastedText(state.query)
            when (pasted) {
                is PastedText.DirectVideo -> {
                    DirectVideoRow(
                        url = pasted.url,
                        title = pasted.title,
                        onPlay = { onPlayDirectUrl(pasted.url, pasted.title) },
                    )
                    Spacer(Modifier.height(8.dp))
                }
                PastedText.YouTube -> {
                    Text(
                        text = "YouTube links can't play in Radd. Paste a direct .mp4 or .m3u8 link instead.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    )
                    Spacer(Modifier.height(8.dp))
                }
                is PastedText.PageLink -> {
                    PageLinkRow(url = pasted.url)
                    Spacer(Modifier.height(8.dp))
                }
                PastedText.NotAUrl -> {
                    // The Home tile says "Play a video link", but nothing on
                    // this screen said a link could be pasted here — the field
                    // only reacts once a URL is typed. One honest line: a
                    // direct .mp4 or .m3u8 link plays in the app, any other
                    // web link opens in the browser. It stays up while the
                    // field holds a half-typed address, not only while it is
                    // empty — a hint that vanishes the moment typing starts
                    // teaches nothing.
                    if (state.query.isEmpty() || looksLikeUrlPrefix(state.query)) {
                        Text(
                            text = "You can also paste a direct video link (.mp4 or .m3u8) here to play it — or any web link to open it in your browser.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        )
                        Spacer(Modifier.height(8.dp))
                    }
                }
            }
            // The rail stays up whatever is pasted: a link replaces the
            // results, never the whole search UI.
            FilterRail(state = state, viewModel = viewModel, onOpenFilters = { showSheet = true })

            if (pasted is PastedText.NotAUrl) {
                // Type-ahead titles for what is being typed. A tap searches for
                // that title — it never opens a page, because a suggestion names
                // a work, not a post.
                if (state.suggestions.isNotEmpty()) {
                    LazyRow(
                        modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        // Session 121 (P-14): the last suggestion chip was clipped at the
                        // right edge — the row needs the same end padding the rail gets.
                        contentPadding = PaddingValues(start = 0.dp, end = 16.dp, top = 4.dp, bottom = 4.dp),
                    ) {
                        items(state.suggestions, key = { it.id }) { suggestion ->
                            FilterChip(
                                colors = raddFilterChipColors(),
                                selected = false,
                                onClick = { viewModel.runSuggestion(suggestion.title) },
                                label = {
                                    Text(
                                        if (suggestion.year != null) {
                                            "${suggestion.title} (${suggestion.year})"
                                        } else {
                                            suggestion.title
                                        },
                                    )
                                },
                            )
                        }
                    }
                } else if (state.suggestionsUnavailable && state.query.length >= 2) {
                    // The suggest call itself failed — blocked route, old
                    // server, dead socket. Say so, instead of silently
                    // showing no chips as if nothing matched.
                    Text(
                        text = "Suggestions aren't available on this server — type the full title and search.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    )
                }

                SearchBody(
                    state = state,
                    viewModel = viewModel,
                    onPostClick = onPostClick,
                    onOpenFilters = { showSheet = true },
                )
            } else if (state.recents.isNotEmpty()) {
                // A pasted link replaces the results, not the history: the
                // recents stay reachable so the viewer is never stranded on
                // a link row with nowhere to go.
                RecentsSection(state = state, viewModel = viewModel)
            }
        }

        if (showSheet) {
            ModalBottomSheet(
                onDismissRequest = { showSheet = false },
                sheetState = sheetState,
                containerColor = MaterialTheme.colorScheme.surface,
            ) {
                FilterSheetContent(
                    state = state,
                    viewModel = viewModel,
                    onDone = { showSheet = false },
                )
            }
        }
    }
}

/**
 * One pasted address, one play button: the row says what will play — the file
 * name, with the pasted address underneath — and nothing about where it came
 * from beyond the address itself. The viewer typed it, so showing it back is
 * showing their own text, not a catalog link. One Play control, not two:
 * the icon button and the text button used to do the same thing.
 */
@Composable
private fun DirectVideoRow(url: String, title: String, onPlay: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = url,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Button(onClick = onPlay) {
            Text("Play")
        }
    }
}

/**
 * One pasted page address: what it is, the address itself, and the one
 * honest action — open it in the system browser. The app never renders the
 * page: that is the browser's job, and this row is the handoff to it. When
 * no browser on the device can take the link, the row says so instead of
 * failing silently.
 */
@Composable
private fun PageLinkRow(url: String) {
    val context = LocalContext.current
    var openFailed by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(
                Icons.Default.OpenInNew,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Column(Modifier.weight(1f)) {
                Text(
                    text = "This looks like a web page",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = url,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Button(onClick = {
                openFailed = try {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                    false
                } catch (_: Exception) {
                    true
                }
            }) {
                Text("Open")
            }
        }
        if (openFailed) {
            Text(
                text = "No browser on this device could open the link.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            )
        }
    }
}

/** A half-typed address: the paste hint stays up while the field holds one. */
private fun looksLikeUrlPrefix(query: String): Boolean {
    val text = query.trim().lowercase()
    return text.startsWith("http") || text.startsWith("www.") || text.contains("://")
}

/**
 * The rail in one scrolled line: the Type chips the viewer reaches for
 * most, then the Filters button for everything else (industry, genre,
 * quality, plan, sort, years). One ungrouped ~30-chip scroll buried the
 * type choice behind captions; the sheet owns the rest.
 */
@Composable
private fun FilterRail(state: SearchUiState, viewModel: SearchViewModel, onOpenFilters: () -> Unit) {
    LazyRow(
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        // Session 121 (P-29): the last chip ("Anime") was clipped at the right edge —
        // the row needs end padding; start stays 0 because the outer column already
        // pads 16 dp.
        contentPadding = PaddingValues(start = 0.dp, end = 16.dp, top = 4.dp, bottom = 4.dp),
    ) {
        items(typeChips) { (label, value) ->
            FilterChip(
                colors = raddFilterChipColors(),
                selected = state.filters.type == value,
                onClick = { viewModel.selectType(value) },
                label = { Text(label) },
            )
        }
        item {
            FilterChip(
                colors = raddFilterChipColors(),
                selected = false,
                onClick = onOpenFilters,
                label = {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Icon(Icons.Default.Tune, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("Filters")
                    }
                },
            )
        }
    }
}

/**
 * The recent-searches rail: a lazy row (never a fixed Row that clips the
 * 9th chip) with a Clear action. Used on the empty screen and under a
 * pasted link, where it is the way back.
 */
@Composable
private fun RecentsSection(state: SearchUiState, viewModel: SearchViewModel) {
    Column(Modifier.fillMaxWidth()) {
        SectionHeader(
            title = "Recent searches",
            modifier = Modifier.padding(top = 8.dp),
            action = {
                TextButton(onClick = viewModel::clearRecents) { Text("Clear") }
            },
        )
        LazyRow(
            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(start = 0.dp, end = 16.dp, top = 4.dp, bottom = 4.dp),
        ) {
            items(state.recents, key = { it }) { recent ->
                FilterChip(
                    colors = raddFilterChipColors(),
                    selected = false,
                    onClick = { viewModel.runRecent(recent) },
                    label = { Text(recent) },
                )
            }
        }
    }
}

@Composable
private fun SearchBody(
    state: SearchUiState,
    viewModel: SearchViewModel,
    onPostClick: (Int) -> Unit,
    onOpenFilters: () -> Unit,
) {
    // Session 121 (P-12): scrolling the results dismisses the keyboard — the open
    // keyboard covering the top row was the other half of the complaint (the first
    // half was submit, handled at the field). Hoisted here so the list state is
    // remembered unconditionally, not inside the branch that renders the list.
    val listState = rememberLazyListState()
    val focusManager = LocalFocusManager.current
    LaunchedEffect(listState.firstVisibleItemIndex, listState.firstVisibleItemScrollOffset) {
        if (listState.firstVisibleItemIndex > 0 || listState.firstVisibleItemScrollOffset > 0) {
            focusManager.clearFocus()
        }
    }
    when {
        !state.hasSearchIntent -> {
            if (state.recents.isNotEmpty()) {
                RecentsSection(state = state, viewModel = viewModel)
            } else {
                EmptyState(
                    title = "Search your catalog",
                    message = "Type a title or an actor's name, or pick a filter to begin. Recent searches will show up here.",
                    icon = { Icon(Icons.Default.Search, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(40.dp)) },
                )
            }
        }
        state.isLoading && state.groups.isEmpty() -> LoadingState(
            Modifier.fillMaxWidth().height(160.dp),
        )
        state.error != null && state.groups.isEmpty() -> ErrorState(message = state.error ?: "Search failed.", onRetry = viewModel::submitCurrentQuery)
        state.groups.isEmpty() -> EmptyState(
            title = "No matches",
            message = when {
                state.query.isNotBlank() && state.hasActiveFilters ->
                    "No titles matched \"${state.query}\" with the current filters."
                state.query.isNotBlank() -> "No titles matched \"${state.query}\"."
                else -> "Nothing in the catalog matched these filters."
            },
            action = {
                if (state.hasActiveFilters) {
                    OutlinedButton(onClick = viewModel::resetFilters) { Text("Clear filters") }
                }
            },
        )
        state.isFuzzy && state.showExactOnly -> EmptyState(
            // Exact-only on a fuzzy page is the empty state: every row the
            // server sent is one-edit-away, so there is nothing exact to
            // list — and the way back is right here.
            title = "No exact matches",
            message = "No titles exactly match \"${state.query}\".",
            icon = { Icon(Icons.Default.Search, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(40.dp)) },
            action = {
                OutlinedButton(onClick = viewModel::showCloseMatches) { Text("Show close matches") }
            },
        )
        else -> LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
            item {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = resultsSummary(state.resultCount, state.serverTotal, state.hasMore),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    TextButton(onClick = onOpenFilters) {
                        Icon(Icons.Default.Tune, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Sort · ${state.sort.label}")
                    }
                }
            }

            // The server found nothing exact and answered one edit away
            // instead. Name the query, so the viewer knows why "Avengers"
            // is what came back for "Avngers" — and offer the exact-only
            // view, which is the empty state above.
            if (state.isFuzzy) {
                item {
                    Column(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                        Text(
                            text = "No exact match for \"${state.query}\" — showing the closest titles.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        TextButton(onClick = viewModel::showExactOnly) { Text("Show exact matches only") }
                    }
                }
            }

            state.groups.forEach { group ->
                item {
                    SectionHeader(
                        title = group.label,
                        subtitle = "${group.items.size} ${if (group.items.size == 1) "title" else "titles"}",
                        modifier = Modifier.padding(horizontal = 0.dp),
                    )
                }
                item {
                    MediaRail(items = group.items, key = { it.id }) { post ->
                        PosterCard(post = post, onClick = { onPostClick(post.id) })
                    }
                }
                item { Spacer(Modifier.height(12.dp)) }
            }

            if (state.hasMore) {
                item {
                    Box(Modifier.fillMaxWidth().padding(vertical = 16.dp), contentAlignment = Alignment.Center) {
                        OutlinedButton(onClick = viewModel::loadMore, enabled = !state.isLoadingMore) {
                            Text(if (state.isLoadingMore) "Loading…" else "Load more")
                        }
                    }
                }
            }

            // A failed next page used to be invisible: the retry path was reachable only when
            // every group was empty, so a search that died on page 3 looked like a catalog that
            // simply had three pages.
            state.error?.let { failure ->
                item { InlineLoadFailure(message = failure, onRetry = viewModel::loadMore) }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun FilterSheetContent(
    state: SearchUiState,
    viewModel: SearchViewModel,
    onDone: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp)
            .padding(bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // Type moved here from the rail: the rail now carries only the Type
        // chips and the Filters button, so the sheet is the one place where
        // every facet lives together.
        FacetChips(
            title = "Type",
            options = typeChips,
            label = { it.first },
            isSelected = { state.filters.type == it.second },
            onSelect = { viewModel.selectType(it.second) },
        )
        FacetChips(
            title = "Industry",
            options = IndustryFilter.entries,
            label = { it.label },
            isSelected = { state.filters.industry == it },
            onSelect = viewModel::selectIndustry,
        )
        FacetChips(
            title = "Genre",
            options = GenreFilter.entries,
            label = { it.label },
            isSelected = { state.filters.genre == it },
            onSelect = viewModel::selectGenre,
        )
        FacetChips(
            title = "Quality",
            options = QualityFilter.entries,
            label = { it.label },
            isSelected = { state.filters.quality == it },
            onSelect = viewModel::selectQuality,
        )
        if (!state.isVip) {
            Text("Plan", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    colors = raddFilterChipColors(),
                    selected = state.filters.includedOnly,
                    onClick = { viewModel.setIncludedOnly(!state.filters.includedOnly) },
                    label = { Text("Included in my plan") },
                )
            }
        }

        Text("Sort results", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
        Text(
            "Facets and sort run on the server before paging, so they narrow the whole catalog. " +
                "Only the year range applies to the loaded pages.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        SearchSort.entries.forEach { sort ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .clickable { viewModel.setSort(sort) },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(selected = state.sort == sort, onClick = { viewModel.setSort(sort) })
                Spacer(Modifier.width(8.dp))
                Text(sort.label)
            }
        }

        Spacer(Modifier.height(8.dp))
        Text("Year range", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            YearField(
                label = "From",
                value = state.filters.yearFrom?.toString() ?: "",
                onSet = { it?.let { n -> viewModel.setYearRange(n, state.filters.yearTo) } ?: viewModel.setYearRange(null, state.filters.yearTo) },
            )
            YearField(
                label = "To",
                value = state.filters.yearTo?.toString() ?: "",
                onSet = { it?.let { n -> viewModel.setYearRange(state.filters.yearFrom, n) } ?: viewModel.setYearRange(state.filters.yearFrom, null) },
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            TextButton(onClick = viewModel::resetFilters) { Text("Reset") }
            Button(onClick = onDone) { Text("Apply") }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun <T> FacetChips(
    title: String,
    options: List<T>,
    label: (T) -> String,
    isSelected: (T) -> Boolean,
    onSelect: (T) -> Unit,
) {
    Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { option ->
            FilterChip(
                colors = raddFilterChipColors(),
                selected = isSelected(option),
                onClick = { onSelect(option) },
                label = { Text(label(option)) },
            )
        }
    }
}

@Composable
private fun YearField(label: String, value: String, onSet: (Int?) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = { raw -> onSet(raw.filter(Char::isDigit).takeIf { it.isNotBlank() }?.toIntOrNull()) },
        label = { Text(label) },
        singleLine = true,
        modifier = Modifier.width(140.dp),
    )
}
