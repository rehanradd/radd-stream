package com.raddstream.app.ui.screens

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayArrow
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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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

/** One line of the facet rail: a quiet group caption or a selectable chip. */
private sealed interface FilterRailEntry {
    data class Caption(val label: String) : FilterRailEntry
    data class Choice(val label: String, val selected: Boolean, val onClick: () -> Unit) : FilterRailEntry
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(
    onBackClick: () -> Unit,
    onPostClick: (Int) -> Unit = {},
    onPlayDirectUrl: (url: String, title: String) -> Unit = { _, _ -> },
    viewModel: SearchViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    var showSheet by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        if (state.hasSearched) {
                            resultsSummary(state.resultCount, state.serverTotal, state.hasMore)
                        } else {
                            "Search"
                        },
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (state.hasActiveFilters) {
                        Pill(text = "Filtered", backgroundColor = MaterialTheme.colorScheme.primaryContainer, contentColor = MaterialTheme.colorScheme.onPrimaryContainer)
                        Spacer(Modifier.width(8.dp))
                    }
                    IconButton(onClick = { showSheet = true }) {
                        Icon(Icons.Default.Tune, contentDescription = "Filters and sort")
                    }
                },
            )
        },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .padding(horizontal = 16.dp),
        ) {
            OutlinedTextField(
                value = state.query,
                onValueChange = viewModel::onQueryChanged,
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                label = { Text("Title") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                trailingIcon = {
                    if (state.query.isNotEmpty()) {
                        IconButton(onClick = { viewModel.onQueryChanged("") }) {
                            Icon(Icons.Default.Close, contentDescription = "Clear search")
                        }
                    }
                },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { viewModel.submitCurrentQuery() }),
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
                PastedText.NotAUrl -> {
                    // The Home tile says "Play a video link", but nothing on
                    // this screen said a link could be pasted here — the field
                    // only reacts once a URL is typed. One honest line, only
                    // while the field is empty: a direct .mp4 or .m3u8 link
                    // plays in the app. No promise of general web browsing;
                    // the YouTube line above still says no to those.
                    if (state.query.isEmpty()) {
                        Text(
                            text = "You can also paste a direct video link (.mp4 or .m3u8) here to play it in the app.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        )
                        Spacer(Modifier.height(8.dp))
                    }
                }
            }
            if (pasted is PastedText.NotAUrl) {
                FilterRail(state = state, viewModel = viewModel)
            }

            // Type-ahead titles for what is being typed. A tap searches for
            // that title — it never opens a page, because a suggestion names
            // a work, not a post.
            if (pasted is PastedText.NotAUrl && state.suggestions.isNotEmpty()) {
                LazyRow(
                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding = PaddingValues(vertical = 4.dp),
                ) {
                    items(state.suggestions, key = { it.id }) { suggestion ->
                        FilterChip(
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
            }

            if (pasted is PastedText.NotAUrl) {
                SearchBody(
                    state = state,
                    viewModel = viewModel,
                    onPostClick = onPostClick,
                    onOpenFilters = { showSheet = true },
                )
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
 * showing their own text, not a catalog link.
 */
@Composable
private fun DirectVideoRow(url: String, title: String, onPlay: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        IconButton(onClick = onPlay) {
            Icon(Icons.Default.PlayArrow, contentDescription = "Play video link")
        }
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
 * The whole filter surface in one scrolled line: Type, Industry, Genre, Quality and
 * Sort. Every choice re-runs the debounced server search, so a chip narrows the
 * catalog rather than the handful of rows this device happens to hold.
 */
@Composable
private fun FilterRail(state: SearchUiState, viewModel: SearchViewModel) {
    val entries = buildList {
        add(FilterRailEntry.Caption("Type"))
        typeChips.forEach { (label, value) ->
            add(FilterRailEntry.Choice(label, state.filters.type == value) { viewModel.selectType(value) })
        }
        add(FilterRailEntry.Caption("Industry"))
        IndustryFilter.entries.forEach { industry ->
            add(
                FilterRailEntry.Choice(
                    industry.label,
                    state.filters.industry == industry,
                ) { viewModel.selectIndustry(industry) },
            )
        }
        add(FilterRailEntry.Caption("Genre"))
        GenreFilter.entries.forEach { genre ->
            add(
                FilterRailEntry.Choice(
                    genre.label,
                    state.filters.genre == genre,
                ) { viewModel.selectGenre(genre) },
            )
        }
        add(FilterRailEntry.Caption("Quality"))
        QualityFilter.entries.forEach { quality ->
            add(
                FilterRailEntry.Choice(
                    quality.label,
                    state.filters.quality == quality,
                ) { viewModel.selectQuality(quality) },
            )
        }
        // A VIP viewer has everything included, so the chip would narrow
        // their catalog for nothing. Free viewers get the one filter that
        // answers "can I watch this without paying".
        if (!state.isVip) {
            add(FilterRailEntry.Caption("Plan"))
            add(
                FilterRailEntry.Choice(
                    "Included in my plan",
                    state.filters.includedOnly,
                ) { viewModel.setIncludedOnly(!state.filters.includedOnly) },
            )
        }
        add(FilterRailEntry.Caption("Sort"))
        SearchSort.entries.forEach { sort ->
            add(FilterRailEntry.Choice(sort.label, state.sort == sort) { viewModel.setSort(sort) })
        }
    }

    LazyRow(
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        contentPadding = PaddingValues(vertical = 4.dp),
    ) {
        items(entries.size) { index ->
            when (val entry = entries[index]) {
                is FilterRailEntry.Caption -> Text(
                    text = entry.label,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = if (index == 0) 0.dp else 12.dp),
                )
                is FilterRailEntry.Choice -> FilterChip(
                    selected = entry.selected,
                    onClick = entry.onClick,
                    label = { Text(entry.label) },
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
    when {
        !state.hasSearchIntent -> {
            if (state.recents.isNotEmpty()) {
                Column(Modifier.fillMaxWidth()) {
                    SectionHeader(title = "Recent searches", modifier = Modifier.padding(top = 8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        state.recents.take(8).forEach { recent ->
                            FilterChip(selected = false, onClick = { viewModel.runRecent(recent) }, label = { Text(recent) })
                        }
                    }
                }
            } else {
                EmptyState(
                    title = "Search your catalog",
                    message = "Type a title or pick a filter to begin. Recent searches will show up here.",
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
        else -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
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

            // The server found nothing exact and answered one edit away
            // instead. Say so, so the viewer knows why "Avengers" is what
            // came back for "Avngers".
            if (state.isFuzzy) {
                Text(
                    text = "Showing close matches — check the spelling.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
                )
            }

            state.groups.forEach { group ->
                SectionHeader(title = group.label, subtitle = "${group.items.size}", modifier = Modifier.padding(horizontal = 0.dp))
                MediaRail(items = group.items, key = { it.id }) { post ->
                    PosterCard(post = post, onClick = { onPostClick(post.id) })
                }
                Spacer(Modifier.height(12.dp))
            }

            if (state.hasMore) {
                Box(Modifier.fillMaxWidth().padding(vertical = 16.dp), contentAlignment = Alignment.Center) {
                    OutlinedButton(onClick = viewModel::loadMore, enabled = !state.isLoadingMore) {
                        Text(if (state.isLoadingMore) "Loading…" else "Load more")
                    }
                }
            }

            // A failed next page used to be invisible: the retry path was reachable only when
            // every group was empty, so a search that died on page 3 looked like a catalog that
            // simply had three pages.
            state.error?.let { failure ->
                InlineLoadFailure(message = failure, onRetry = viewModel::loadMore)
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
