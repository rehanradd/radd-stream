package com.raddstream.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.ui.components.CatalogImage
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.viewmodel.HistoryRow
import com.raddstream.app.viewmodel.WatchHistoryViewModel

/**
 * Everything this phone watched, newest first — including titles watched to the end.
 *
 * The rows come from the same merged source as the Continue watching rail (local rows
 * folded with a newer synced position), so the two surfaces can never disagree about
 * where a title stopped; the only difference is the filter, and this screen has none.
 * A row taps through to Detail exactly when the rail's rule says it can be routed
 * (`postId > 0`); an unroutable row is shown, not hidden, and simply does not tap.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WatchHistoryScreen(
    onBackClick: () -> Unit,
    onPostClick: (Int) -> Unit,
    viewModel: WatchHistoryViewModel = hiltViewModel(),
) {
    val rows by viewModel.rows.collectAsState()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("Watch history") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { contentPadding ->
        if (rows.isEmpty()) {
            EmptyState(
                title = "Nothing watched yet",
                message = "Titles you watch on this phone will show up here, newest first — " +
                    "including ones you finished.",
                icon = {
                    Icon(
                        Icons.Default.History,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.secondary,
                        modifier = Modifier.size(40.dp),
                    )
                },
                modifier = Modifier.padding(contentPadding),
            )
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(contentPadding),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                // Keyed on the scope, not the work: two rows of the same series are two
                // different episodes, and a duplicate key would crash the list.
                items(rows, key = { "${it.postId}|${it.scopeLabel.orEmpty()}" }) { row ->
                    HistoryRowItem(
                        row = row,
                        onClick = { onPostClick(row.postId) },
                    )
                }
            }
        }
    }
}

/** One watched scope: poster, title, scope + day, and where viewing stopped. */
@Composable
private fun HistoryRowItem(
    row: HistoryRow,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = row.tappable, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CatalogImage(
            url = row.posterUrl,
            contentDescription = row.title,
            modifier = Modifier.size(width = 56.dp, height = 84.dp),
            fallbackLabel = row.title,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(
                text = row.title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = listOfNotNull(row.scopeLabel, row.dateLabel)
                    .joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            row.statusLabel?.let { status ->
                Text(
                    text = status,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            row.progressFraction?.let { fraction ->
                LinearProgressIndicator(
                    progress = { fraction },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}
