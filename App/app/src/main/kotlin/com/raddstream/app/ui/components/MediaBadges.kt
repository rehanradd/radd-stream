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
import androidx.compose.material.icons.filled.OnlinePrediction
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
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.Resolution
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
        contentDescription = "RankedPrint quality ${print.qualityLabel}" +
            if (print.isCam) ", cam recording — low quality" else "",
    )
}

/** Compact "CAM" discouragement chip shown alongside a bootleg print. */
@Composable
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

/** Ranked 1..N ordinal badge for the failover plan (API_V2.md §5). */
@Composable
fun RankBadge(rank: Int, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(22.dp)
            .clip(CircleShape)
            .background(
                if (rank == 1) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant
            ),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = rank.toString(),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = if (rank == 1) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Small streaming/monitoring affordance glyph used by health summaries. */
@Composable
fun HealthLegend(modifier: Modifier = Modifier) {
    Icon(
        Icons.Default.OnlinePrediction,
        contentDescription = null,
        tint = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier.size(14.dp),
    )
}
