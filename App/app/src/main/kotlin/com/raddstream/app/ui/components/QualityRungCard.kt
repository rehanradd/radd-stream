package com.raddstream.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.raddstream.app.viewmodel.LadderForScope
import com.raddstream.app.viewmodel.QualityOption

/**
 * The quality switch and the download card, in one row per rung — exactly one option
 * each, the way the server collapsed them (`Fast_Fetch/tiers.py`).
 *
 * WHY THE USER NEVER SEES A LINK LIST: the ledger holds up to six copies of a print on
 * six servers, and the owner's rule is that a viewer chooses a *picture*, not a server.
 * Auto is the default (the ladder's own pointer, i.e. the best rung that plays here),
 * and a rung whose only copy cannot be presented says "Download only" out loud instead
 * of failing invisibly. Nothing here can name a site, a hoster or an address: the row
 * is built from [QualityOption], and that type has no field for either.
 */
@Composable
fun QualityRungCard(
    ladder: LadderForScope,
    selectedBand: String?,
    onPlayRung: (QualityOption) -> Unit,
    onKeepRung: (QualityOption) -> Unit,
    /** Which scope these rungs belong to — "Season 2 · Episode 5", null for the whole work. */
    scopeTitle: String? = null,
    modifier: Modifier = Modifier,
) {
    if (ladder.isEmpty) return
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(bottom = 8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            text = scopeTitle?.let { "Quality · $it" } ?: "Quality",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            text = "Auto plays the best picture this connection can hold.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        ladder.options.forEach { option ->
            RungRow(
                option = option,
                isAuto = option.band == ladder.autoBand,
                selected = selectedBand == option.band ||
                    (selectedBand == LadderForScope.AUTO && option.band == ladder.autoBand),
                onPlay = { onPlayRung(option) },
                onKeep = { onKeepRung(option) },
            )
        }
    }
}

@Composable
private fun RungRow(
    option: QualityOption,
    isAuto: Boolean,
    selected: Boolean,
    onPlay: () -> Unit,
    onKeep: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = if (selected) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface,
        tonalElevation = if (selected) 2.dp else 0.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = option.title,
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (isAuto) {
                        Spacer(Modifier.width(6.dp))
                        AssistChip(
                            onClick = onPlay,
                            label = { Text("Auto", style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                Text(
                    text = option.detailLine,
                    style = MaterialTheme.typography.labelSmall,
                    color = if (option.downloadOnly) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            // One action per rung: it plays here, or it is kept. Never both, never a list.
            if (option.playsHere) {
                IconButton(onClick = onPlay) {
                    Icon(
                        imageVector = Icons.Default.PlayArrow,
                        contentDescription = "Play in ${option.title}",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            }
            IconButton(onClick = onKeep) {
                Icon(
                    imageVector = Icons.Default.Download,
                    contentDescription = "Download ${option.title}",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
