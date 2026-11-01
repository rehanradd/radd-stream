package com.raddstream.app.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityChoice
import com.raddstream.app.player.QualityOption

/**
 * The quality menu: one row per picture THIS title actually has, and a tap selects.
 *
 * It used to be two things at once — a list of bands and a set of action buttons, with a Play icon
 * and a Download icon on every row. That is how the detail page ended up with about forty buttons,
 * and why the owner's simplification had to start here: once the page has exactly one Play and one
 * Download, a band row's only honest gesture is SELECT. The two buttons above it then act on what
 * was chosen, at the quality the viewer saved.
 *
 * Two more rules the row carries, both from the spec:
 *  - only bands that exist. The list is the ladder's own collapse ([LadderForScope]) — already one
 *    rung per band the switch measured — so nothing here can add a 1080p row to a title that has
 *    none. A menu that did would be offering a picture that cannot arrive.
 *  - no capability vocabulary. A row shows the picture and its size. It never says "Download only",
 *    never names a protocol, a codec, a host or an address: those words are what turned a quality
 *    list into a server list. A rung whose file cannot be kept is not offered by the Download
 *    button at all (see [com.raddstream.app.player.DownloadOffers]), and still appears here, because
 *    it is a real picture the viewer can watch.
 */
@Composable
fun QualityRungCard(
    ladder: LadderForScope,
    selectedBand: String?,
    onSelectBand: (QualityOption) -> Unit,
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
        ladder.options.forEach { option ->
            BandRow(
                option = option,
                // Matched folded, so the row that lights up is the row the play decision is using
                // even when the ladder spelled its band as `4K` and the plan resolved to `2160p`.
                selected = QualityChoice.canonical(selectedBand) == QualityChoice.canonical(option.band),
                onSelect = { onSelectBand(option) },
            )
        }
    }
}

@Composable
private fun BandRow(
    option: QualityOption,
    selected: Boolean,
    onSelect: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = if (selected) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface,
        tonalElevation = if (selected) 2.dp else 0.dp,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(role = Role.Button, onClick = onSelect),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    // The band in the viewer's own words, so the row a viewer taps says the same
                    // thing as the note the app paints when it could not deliver that picture.
                    text = QualityChoice.labelOf(option.band) ?: option.title,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                option.sizeLine?.let { size ->
                    Text(
                        text = size,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (selected) {
                Icon(
                    imageVector = Icons.Default.Check,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}
