package com.raddstream.app.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.R
import com.raddstream.app.data.RegionChoice
import com.raddstream.app.data.RegionChoices
import com.raddstream.app.data.UserRegion
import com.raddstream.app.ui.theme.RaddStreamMark
import com.raddstream.app.viewmodel.RegionUiState
import com.raddstream.app.viewmodel.RegionViewModel

/**
 * The first-run choice: what this viewer came to watch, in three cards.
 *
 * One question, three answers, no brochure. Each card is a brand icon, a name, one short
 * line about what it holds, and the audio/subtitle promise it writes — nothing else. The
 * promise on the card and the record in storage cannot drift apart, because both come from
 * [com.raddstream.app.data.RegionChoices]: the screen never invents its own words.
 */
@Composable
fun RegionSelectionScreen(
    onContinue: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: RegionViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        RaddStreamMark(diameter = 56.dp)
        Spacer(Modifier.height(20.dp))
        Text(
            text = "What do you love to watch?",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.SemiBold,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = "Pick one — or skip and keep Desi. This only sets which audio and subtitle tracks the app prefers; the catalog is the same either way. You can change it later in Settings.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(28.dp))

        RegionChoices.ALL.forEachIndexed { index, choice ->
            AnimatedVisibility(
                visible = true,
                enter = fadeIn(tween(300, delayMillis = index * 90)) +
                    slideInVertically(tween(300, delayMillis = index * 90)) { it / 3 },
            ) {
                RegionChoiceCard(
                    choice = choice,
                    selected = choice.id == state.selectedId,
                    recommended = choice.id == UserRegion.DEFAULT,
                    onSelect = { viewModel.select(choice.id) },
                )
            }
            Spacer(Modifier.height(12.dp))
        }

        Spacer(Modifier.height(8.dp))
        Button(
            onClick = { viewModel.saveAndContinue(onContinue) },
            enabled = !state.isSaving,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            shape = RoundedCornerShape(12.dp),
        ) {
            if (state.isSaving) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    color = MaterialTheme.colorScheme.onPrimary,
                    strokeWidth = 2.dp,
                )
            } else {
                Text("Continue")
            }
        }
        if (state.saveFailed) {
            Spacer(Modifier.height(10.dp))
            // A message that appears under the thumb the viewer just used is invisible to a screen
            // reader unless it is announced, so this text node is a polite live region.
            Text(
                text = "Couldn't save your choice — please try again.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
            )
        }
        Spacer(Modifier.height(8.dp))
        TextButton(
            onClick = { viewModel.skipAndContinue(onContinue) },
            enabled = !state.isSaving,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
        ) {
            Text("Skip for now")
        }
        Spacer(Modifier.height(16.dp))
    }
}

/** The brand icon for a card: a clapperboard for Desi cinema, a lantern for East Asia, a globe for the world. */
private fun regionIconRes(choice: RegionChoice): Int = when (choice.id) {
    UserRegion.DESI_DUBS -> R.drawable.ic_region_desi
    UserRegion.EAST_ASIAN -> R.drawable.ic_region_east_asian
    else -> R.drawable.ic_region_international
}

/**
 * One selectable card: an icon tile, a name, one line about what it holds, and the
 * audio/subtitle promise as a pill. The whole surface is the tap target, and it carries a
 * radio-button role with a real selected state: a screen reader has to say which of the
 * three is the answer, not read the check mark as a separate picture.
 *
 * The selected card wears the brand jade — border, icon tile and pill all shift together
 * through [animateColorAsState], and the check badge scales in — so the answer reads at a
 * glance instead of needing a second look.
 */
@Composable
private fun RegionChoiceCard(
    choice: RegionChoice,
    selected: Boolean,
    recommended: Boolean,
    onSelect: () -> Unit,
) {
    val jade = MaterialTheme.colorScheme.primary
    val containerColor by animateColorAsState(
        if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
        label = "regionCardContainer",
    )
    val borderColor by animateColorAsState(
        if (selected) jade else MaterialTheme.colorScheme.outlineVariant,
        label = "regionCardBorder",
    )
    val iconTileColor by animateColorAsState(
        if (selected) jade.copy(alpha = 0.16f) else MaterialTheme.colorScheme.surfaceVariant,
        label = "regionIconTile",
    )
    val iconTint by animateColorAsState(
        if (selected) jade else MaterialTheme.colorScheme.onSurfaceVariant,
        label = "regionIconTint",
    )

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .selectable(
                selected = selected,
                role = Role.RadioButton,
                onClick = onSelect,
            ),
        shape = RoundedCornerShape(20.dp),
        color = containerColor,
        border = BorderStroke(
            if (selected) 2.dp else 1.dp,
            borderColor,
        ),
        tonalElevation = if (selected) 2.dp else 0.dp,
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(iconTileColor),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    // The qualified form, as in NavGraph: the top-level vectorResource does
                    // not exist in this Compose version (BOM 2024.06.00), only the Companion's.
                    imageVector = ImageVector.vectorResource(regionIconRes(choice)),
                    contentDescription = null,
                    tint = iconTint,
                    modifier = Modifier.size(26.dp),
                )
            }
            Spacer(Modifier.width(14.dp))
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = choice.title,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontWeight = FontWeight.SemiBold,
                    )
                    if (recommended) {
                        Spacer(Modifier.width(8.dp))
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(8.dp))
                                .background(jade.copy(alpha = 0.14f))
                                .padding(horizontal = 8.dp, vertical = 3.dp),
                        ) {
                            Text(
                                text = "Recommended",
                                style = MaterialTheme.typography.labelSmall,
                                color = jade,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                }
                Text(
                    text = choice.tagline,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(
                            if (selected) jade.copy(alpha = 0.14f)
                            else MaterialTheme.colorScheme.surfaceVariant,
                        )
                        .padding(horizontal = 8.dp, vertical = 3.dp),
                ) {
                    Text(
                        text = choice.preferencePill(),
                        style = MaterialTheme.typography.labelSmall,
                        color = if (selected) jade else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
            AnimatedVisibility(
                visible = selected,
                enter = scaleIn(tween(200)) + fadeIn(tween(200)),
                exit = scaleOut(tween(150)) + fadeOut(tween(150)),
            ) {
                Box(
                    modifier = Modifier
                        .padding(start = 12.dp)
                        .size(28.dp)
                        .clip(CircleShape)
                        .background(jade),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Default.Check,
                        // The row's own selected state already says this out loud; a second
                        // "Selected" from the picture is the same word twice.
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
        }
    }
}
