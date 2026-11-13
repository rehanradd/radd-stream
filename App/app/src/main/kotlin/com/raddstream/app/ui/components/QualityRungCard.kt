package com.raddstream.app.ui.components

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption
import com.raddstream.app.player.carriesPreferredAudio
import com.raddstream.app.player.preferredAudioFirst
import com.raddstream.app.ui.theme.RaddMotion

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
    /**
     * The viewer's preferred audio languages (audit #32). The card leads
     * with rows carrying them, and the first such row is labelled
     * "your pick". Empty orders nothing.
     */
    preferredAudio: Set<String> = emptySet(),
    modifier: Modifier = Modifier,
) {
    if (ladder.isEmpty) return
    // Display order only — the ladder's own order (and Auto's pointer)
    // never moves; only the rows the viewer reads are re-led.
    val ordered = preferredAudioFirst(ladder.options, preferredAudio)
    var pickGiven = false
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
            text = "Auto plays the best picture your plan can hold.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        // D-1: the effective auto band, not the server pointer. The gate nulls
        // `autoBand` when it gates the server's auto rung out (Salaar, free
        // user: the server points at 2160p, the gate keeps 720p) — and with a
        // null pointer neither the Auto pill nor the Auto selection matched
        // anything, so the active choice was invisible while Auto was the
        // default. `autoOption` already falls back to the first playable rung,
        // so its band is the answer for both the pill and the selection.
        val effectiveAutoBand = ladder.effectiveAutoBand
        ordered.forEach { option ->
            val isPick = !pickGiven && carriesPreferredAudio(option, preferredAudio)
            if (isPick) pickGiven = true
            RungRow(
                option = option,
                isAuto = option.band == effectiveAutoBand,
                selected = selectedBand == option.band ||
                    (selectedBand == LadderForScope.AUTO && option.band == effectiveAutoBand),
                tier = tierLabel(option),
                isPick = isPick,
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
    /** Audit #32: the lead preferred-audio row — its facts line says "your pick". */
    isPick: Boolean = false,
    onPlay: () -> Unit,
    onKeep: () -> Unit,
) {
    // Restyle 2026-11-13: the selected rung's container morphs — its corners
    // open from 12dp to 28dp on the default-spatial spring, so the chosen
    // quality visibly settles instead of just changing colour.
    val corner by animateDpAsState(
        targetValue = if (selected) 28.dp else 12.dp,
        animationSpec = RaddMotion.defaultSpatial(),
        label = "rungCorner",
    )
    Surface(
        shape = RoundedCornerShape(corner),
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
                        // D-33: "Auto" is a pill in the same language as the
                        // tier pill — not an AssistChip that looks like a
                        // label and plays on tap. The play button plays.
                        RungPill(text = "Auto", highlighted = false)
                    }
                    Spacer(Modifier.width(6.dp))
                    // Robo run 3: every rung's tier pill said bare "Standard",
                    // identical across rungs — so the pill carries its rung.
                    RungPill(
                        text = tier,
                        highlighted = tier == "VIP",
                        contentDescription = "$tier tier, ${option.title}",
                    )
                }
                Text(
                    text = option.detailLine,
                    style = MaterialTheme.typography.labelSmall,
                    color = if (option.downloadOnly) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    // Robo run 3: every rung's subtext said bare "Plays here",
                    // identical across rungs — so the line carries its rung.
                    modifier = Modifier.semantics {
                        contentDescription = "${option.title}: ${option.detailLine}"
                    },
                )
                // The honest facts, each only when measured: the print's audio
                // languages, the copy's stream shape, and what an hour of it
                // costs in data. A rung whose copy was never probed shows no
                // category rather than a guessed one, and a rung with no stored
                // languages shows no audio.
                // Audit #31: "Resumable" is dropped — it is a server word, and
                // the detail screen's capability chips no longer carry it either.
                // Audit #11: the data estimate surfaces Data Saver's promise
                // here on the detail screen, in the same words the player
                // quality picker already uses.
                val facts = listOfNotNull(
                    audioBadgeText(dualAudio = false, languages = option.audioLanguages),
                    option.streamCategory?.label,
                    UserWords.dataEstimateForQuality(option.band),
                    // Audit #32: the lead preferred-audio row says so, in the
                    // same line as its audio — "Hindi audio · your pick".
                    "your pick".takeIf { isPick },
                ).joinToString(" · ")
                if (facts.isNotEmpty()) {
                    Text(
                        text = facts,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        // Robo run 7: every rung's facts line said the same
                        // "Hindi + English audio" — the spoken line carries
                        // its rung, the same pattern as the detail line above.
                        modifier = Modifier.semantics {
                            contentDescription = "${option.title}: $facts"
                        },
                    )
                }
            }
            // One action per rung: it plays here, or it is kept. Never both, never a list.
            // D-33: the glyphs sit on tonal pads, not bare on the row — a bare
            // icon reads as decoration, a pad reads as a button.
            if (option.playsHere) {
                RungIconButton(onClick = onPlay) {
                    Icon(
                        imageVector = Icons.Default.PlayArrow,
                        contentDescription = "Play in ${option.title}",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            }
            RungIconButton(onClick = onKeep) {
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
 * One rung action: a 48dp tonal pad with the glyph centred. The pad is the
 * button — the same surfaceVariant the rung's quiet pills use, so the row
 * has one action language instead of bare glyphs beside filled buttons.
 */
@Composable
private fun RungIconButton(
    onClick: () -> Unit,
    content: @Composable () -> Unit,
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.size(48.dp),
    ) {
        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
            content()
        }
    }
}

/**
 * One pill language for the rung row (D-33): the tier a rung requires and the
 * "Auto" mark share it, so the row never shows two chip styles again. VIP
 * draws the eye (it is the reason the rung may be absent for a free viewer);
 * everything else sits quiet. A pill is a label, not a button — tapping it
 * plays nothing. One word, never wrapped mid-word (Session 121, P-9).
 */
@Composable
private fun RungPill(
    text: String,
    highlighted: Boolean,
    /** Spoken name when the bare pill word repeats across rows (the tier pill). Null leaves the paint text as the spoken text. */
    contentDescription: String? = null,
) {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = if (highlighted) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.surfaceVariant
        },
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            softWrap = false,
            color = if (highlighted) {
                MaterialTheme.colorScheme.onPrimaryContainer
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp).then(
                if (contentDescription != null) {
                    Modifier.semantics { this.contentDescription = contentDescription }
                } else {
                    Modifier
                }
            ),
        )
    }
}
