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
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption

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
    /** The tier each rung requires ("VIP" / "Standard"), from the ViewModel. */
    tierLabel: (QualityOption) -> String = { "Standard" },
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
                tier = tierLabel(option),
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
    /** "VIP" or "Standard" — the tier this rung requires, never the viewer's. */
    tier: String,
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
                    Spacer(Modifier.width(6.dp))
                    TierPill(tier = tier)
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
                // The honest facts, each only when measured: the print's audio
                // languages, the copy's stream shape, and resumability. A rung
                // whose copy was never probed shows no category rather than a
                // guessed one, and a rung with no stored languages shows no audio.
                val facts = listOfNotNull(
                    audioBadgeText(dualAudio = false, languages = option.audioLanguages),
                    option.streamCategory?.label,
                    "Resumable".takeIf { option.resumable },
                ).joinToString(" · ")
                if (facts.isNotEmpty()) {
                    Text(
                        text = facts,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
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

/**
 * The tier a rung requires, as a small pill beside its title. VIP draws the
 * eye (it is the reason the rung may be absent for a free viewer); Standard
 * sits quiet. It is a label, not a button — tapping it plays nothing.
 */
@Composable
private fun TierPill(tier: String) {
    val isVip = tier == "VIP"
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = if (isVip) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.surfaceVariant
        },
    ) {
        Text(
            text = tier,
            style = MaterialTheme.typography.labelSmall,
            // Session 121 (P-9): the pill is one word ("Standard" / "VIP") and must
            // never wrap mid-word ("Stan / dard") when the rung row runs out of room.
            maxLines = 1,
            softWrap = false,
            color = if (isVip) {
                MaterialTheme.colorScheme.onPrimaryContainer
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}
