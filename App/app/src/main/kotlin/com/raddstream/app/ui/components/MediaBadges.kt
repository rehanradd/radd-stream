package com.raddstream.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.HdrFormat
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.Resolution
import com.raddstream.app.network.models.SourceTag
import com.raddstream.app.viewmodel.RankedPrint

/**
 * Small reusable status/badge primitives. Colors come ONLY from
 * `MaterialTheme.colorScheme` (no raw hex). Anything that wants a dedicated
 * semantic colour is requested as a theme token in docs/HANDOFF_appui.md; until
 * that token exists it maps to the nearest M3 role so nothing is hardcoded.
 */

@Composable
fun Pill(
    text: String,
    modifier: Modifier = Modifier,
    backgroundColor: Color = MaterialTheme.colorScheme.surfaceVariant,
    contentColor: Color = MaterialTheme.colorScheme.onSurfaceVariant,
    contentDescription: String? = null,
) {
    val a11yLabel = contentDescription
    Surface(
        modifier = if (a11yLabel != null) {
            // `this.` qualifies the SemanticsPropertyReceiver property — a bare
            // `contentDescription` here would hit this function's val parameter of the same name.
            modifier.semantics { this.contentDescription = a11yLabel }
        } else {
            modifier
        },
        color = backgroundColor,
        contentColor = contentColor,
        shape = RoundedCornerShape(6.dp),
    ) {
        Box(Modifier.padding(horizontal = 8.dp, vertical = 3.dp)) {
            Text(
                text = text,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
            )
        }
    }
}

/**
 * The print-quality badge — the "quality axis" of a release (4K · DV · BluRay).
 * Deliberately loud for HDR/4K, muted for unknown, and *error*-coloured for CAM so
 * the discouraged bootleg is unmistakable (owner brief + API_V2.md §3 ordering).
 */
@Composable
fun PrintQualityBadge(print: RankedPrint, modifier: Modifier = Modifier) {
    val bg = when {
        print.isCam -> MaterialTheme.colorScheme.errorContainer
        print.resolution == Resolution.R2160 -> MaterialTheme.colorScheme.primaryContainer
        print.isOfficialPrint -> MaterialTheme.colorScheme.tertiaryContainer
        else -> MaterialTheme.colorScheme.surfaceVariant
    }
    val fg = when {
        print.isCam -> MaterialTheme.colorScheme.onErrorContainer
        print.resolution == Resolution.R2160 -> MaterialTheme.colorScheme.onPrimaryContainer
        print.isOfficialPrint -> MaterialTheme.colorScheme.onTertiaryContainer
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Pill(
        text = print.qualityLabel,
        modifier = modifier,
        backgroundColor = bg,
        contentColor = fg,
        contentDescription = "Picture quality ${print.qualityLabel}" +
            if (print.isCam) ", cam recording — low quality" else "",
    )
}

/**
 * HDR half of the quality axis ("DV", "HDR10+", "HDR10", "HLG"). Kept separate from
 * [PrintQualityBadge] so a tier can read "4K · HDR10 · WEB-DL" without inventing a
 * combined label the server never sent.
 */
@Composable
fun HdrBadge(print: RankedPrint, modifier: Modifier = Modifier) {
    val text = hdrBadgeText(print.hdr) ?: return
    Pill(
        text = text,
        modifier = modifier,
        backgroundColor = MaterialTheme.colorScheme.tertiaryContainer,
        contentColor = MaterialTheme.colorScheme.onTertiaryContainer,
        contentDescription = "High dynamic range $text",
    )
}

internal fun hdrBadgeText(formats: List<HdrFormat>): String? =
    formats.asSequence()
        .map {
            when (it) {
                HdrFormat.DOLBY_VISION -> "DV"
                HdrFormat.HDR10_PLUS -> "HDR10+"
                HdrFormat.HDR10 -> "HDR10"
                HdrFormat.HLG -> "HLG"
                HdrFormat.UNKNOWN -> ""
            }
        }
        .filter { it.isNotEmpty() }
        .distinct()
        .take(2)
        .joinToString(" + ")
        .ifBlank { null }

/** Distribution half of the quality axis: "WEB-DL", "BluRay", "HDTV", "CAM". */
@Composable
fun PrintSourceBadge(print: RankedPrint, modifier: Modifier = Modifier) {
    val text = sourceBadgeText(print.sourceTag) ?: return
    Pill(
        text = text,
        modifier = modifier,
        backgroundColor = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        contentDescription = "Source $text",
    )
}

internal fun sourceBadgeText(tag: SourceTag): String? = when (tag) {
    SourceTag.UHD_BLURAY -> "UHD BluRay"
    SourceTag.BLURAY -> "BluRay"
    SourceTag.WEB_DL -> "WEB-DL"
    SourceTag.WEBRIP -> "WEBRip"
    SourceTag.HDTV -> "HDTV"
    SourceTag.DVD_RIP -> "DVD"
    SourceTag.TELESYNC -> "TS"
    SourceTag.TELECINE -> "Telecine"
    SourceTag.PPV -> "PPV"
    SourceTag.CAM -> "CAM"
    SourceTag.HDT_C -> "HDTC"
    SourceTag.UNKNOWN -> null
}

/**
 * The audio axis: "Dual Audio Hindi + English" only when the label really named two
 * tracks, a plain "Hindi + English audio" otherwise. No invented "Multi-audio" — a
 * print that names no language simply gets no badge.
 */
@Composable
fun AudioBadge(print: RankedPrint, modifier: Modifier = Modifier) {
    val text = audioBadgeText(print.dualAudio, print.languages) ?: return
    Pill(
        text = text,
        modifier = modifier,
        backgroundColor = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        contentDescription = "Audio $text",
    )
}

internal fun audioBadgeText(
    dualAudio: Boolean,
    languages: List<String>,
    maxLanguages: Int = 2,
): String? {
    val names = languages.map { it.trim() }.filter { it.isNotEmpty() }.distinct().take(maxLanguages)
    if (names.isEmpty()) return if (dualAudio) "Dual Audio" else null
    val joined = names.joinToString(" + ")
    return if (dualAudio) "Dual Audio $joined" else "$joined audio"
}

/**
 * The subtitle axis: hardcoded vs external is a real difference (one cannot be turned
 * off), so each gets its own word. Language names are only listed when the label
 * carried them.
 */
@Composable
fun SubtitleBadge(print: RankedPrint, modifier: Modifier = Modifier) {
    val text = subtitleBadgeText(
        available = print.subtitlesAvailable,
        external = print.subtitlesExternal,
        hardcoded = print.subtitlesHardcoded,
        languages = print.subtitleLangs,
    ) ?: return
    Pill(
        text = text,
        modifier = modifier,
        backgroundColor = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        contentDescription = text,
    )
}

internal fun subtitleBadgeText(
    available: Boolean,
    external: Boolean,
    hardcoded: Boolean,
    languages: List<String>,
    maxLanguages: Int = 2,
): String? {
    if (!available && !external && !hardcoded && languages.isEmpty()) return null
    val names = languages.map { it.trim() }.filter { it.isNotEmpty() }.distinct().take(maxLanguages)
    val suffix = if (names.isEmpty()) "" else " " + names.joinToString("/")
    return when {
        hardcoded -> "Hardcoded subs$suffix"
        external -> "External subs$suffix"
        else -> "Subtitles$suffix"
    }
}

/** Compact "CAM" discouragement chip shown alongside a bootleg print. */@Composable
fun CamBadge(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(6.dp))
            .background(MaterialTheme.colorScheme.errorContainer)
            .border(1.dp, MaterialTheme.colorScheme.error, RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Icon(
            Icons.Default.Visibility,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onErrorContainer,
            modifier = Modifier.size(13.dp),
        )
        Text(
            "Cam recording",
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onErrorContainer,
        )
    }
}

/**
 * Link-health chip — the *second* quality axis (does this specific link actually
 * work / is it ephemeral / is it resumable). We only claim what v1 lets us know
 * honestly (scrape-time status + temporary/resumable); measured speed is requested
 * in the handoff and is NOT faked here.
 */
@Composable
fun LinkHealthChip(
    health: LinkState,
    ephemeral: Boolean,
    resumable: Boolean,
    modifier: Modifier = Modifier,
) {
    val dotColor = when (health) {
        LinkState.ACTIVE -> MaterialTheme.colorScheme.primary
        LinkState.DEAD, LinkState.EXPIRED -> MaterialTheme.colorScheme.error
        LinkState.UNCHECKED, LinkState.UNKNOWN -> MaterialTheme.colorScheme.outline
    }
    val healthText = when (health) {
        LinkState.ACTIVE -> "Working"
        LinkState.DEAD -> "Dead"
        LinkState.EXPIRED -> "Expired"
        LinkState.UNCHECKED, LinkState.UNKNOWN -> "Unverified"
    }
    val desc = buildString {
        append("Link status $healthText")
        if (ephemeral) append(", link expires soon")
        if (resumable) append(", resumable download")
    }
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(6.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .semantics { contentDescription = desc }
            .padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(dotColor),
        )
        Text(
            healthText,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (ephemeral) {
            Icon(Icons.Default.Timer, contentDescription = null, tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(13.dp))
        }
        if (resumable) {
            Icon(Icons.Default.Download, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(13.dp))
        }
    }
}

/** Generic capability chip (4K / HDR / audio languages / Streamable). */
@Composable
fun CapabilityChip(text: String, modifier: Modifier = Modifier) {
    Pill(
        text = text,
        modifier = modifier,
        backgroundColor = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}
