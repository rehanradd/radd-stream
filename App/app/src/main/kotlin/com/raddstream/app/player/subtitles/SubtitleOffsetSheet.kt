package com.raddstream.app.player.subtitles

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * The MX-style subtitle sync control: a live offset for both subtitle render paths.
 *
 * The sign follows the overlay's own convention ([com.raddstream.app.player.subtitle.SubtitleFile]):
 * a POSITIVE offset shows the text later than the picture, a NEGATIVE offset shows it earlier.
 * Every callback here is fired while the finger is still down, so the overlay re-renders and
 * the native track's decoder retimes on the next frame rather than after the sheet is dismissed.
 */
object SubtitleOffset {

    /** The slider and the two fine buttons move in tenths of a second. */
    const val FINE_STEP_MS = 100L

    /** The two coarse buttons move in half seconds. */
    const val COARSE_STEP_MS = 500L

    /** Matches [com.raddstream.app.player.SubtitleUiSettings.clamped]'s delay window. */
    const val RANGE_MS = 60_000L

    fun clamp(offsetMs: Long): Long = offsetMs.coerceIn(-RANGE_MS, RANGE_MS)

    fun shift(currentMs: Long, deltaMs: Long): Long = clamp(currentMs + deltaMs)

    fun reset(): Long = 0L

    /** Slider output is rounded to a tenth of a second so the readout never shows noise. */
    fun quantize(offsetMs: Long): Long =
        clamp((offsetMs.toDouble() / FINE_STEP_MS).roundToLong() * FINE_STEP_MS)

    /** `In sync`, `+0.5s` or `-0.1s`; values finer than 100 ms keep two decimals. */
    fun format(offsetMs: Long): String {
        val clamped = clamp(offsetMs)
        if (clamped == 0L) return "In sync"
        val sign = if (clamped > 0) "+" else "-"
        val absMs = abs(clamped)
        val remainder = absMs % 1000
        val fraction = if (remainder % FINE_STEP_MS == 0L) {
            (remainder / FINE_STEP_MS).toString()
        } else {
            (remainder / 10).toString().padStart(2, '0')
        }
        return "$sign${absMs / 1000}.${fraction}s"
    }

    /** The plain-language direction shown under the readout. */
    fun describe(offsetMs: Long): String {
        val clamped = clamp(offsetMs)
        return when {
            clamped > 0 -> "Subtitles appear later than the picture"
            clamped < 0 -> "Subtitles appear earlier than the picture"
            else -> "Picture and subtitles are aligned"
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SubtitleOffsetSheet(
    offsetMs: Long,
    hasCustomOverlay: Boolean,
    onOffsetChange: (Long) -> Unit,
    onDismiss: () -> Unit,
) {
    val offset = SubtitleOffset.clamp(offsetMs)
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(),
        containerColor = MaterialTheme.colorScheme.surface,
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 28.dp),
        ) {
            Text(
                text = "Subtitle sync",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                text = "Shift the text against the picture while playback continues.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(18.dp))
            Surface(
                color = MaterialTheme.colorScheme.surfaceContainerHighest,
                shape = MaterialTheme.shapes.large,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .padding(vertical = 18.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        text = SubtitleOffset.format(offset),
                        style = MaterialTheme.typography.displaySmall,
                        fontWeight = FontWeight.Bold,
                        color = if (offset == 0L) {
                            MaterialTheme.colorScheme.onSurface
                        } else {
                            MaterialTheme.colorScheme.primary
                        },
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = SubtitleOffset.describe(offset),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(Modifier.height(14.dp))
            Slider(
                value = offset.toFloat(),
                onValueChange = { onOffsetChange(SubtitleOffset.quantize(it.toLong())) },
                valueRange = -SubtitleOffset.RANGE_MS.toFloat()..SubtitleOffset.RANGE_MS.toFloat(),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    "-${SubtitleOffset.RANGE_MS / 1000}s",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "0",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "+${SubtitleOffset.RANGE_MS / 1000}s",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Spacer(Modifier.height(14.dp))
            Row(
                Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OffsetButton("-0.5s") { onOffsetChange(SubtitleOffset.shift(offset, -SubtitleOffset.COARSE_STEP_MS)) }
                OffsetButton("-0.1s") { onOffsetChange(SubtitleOffset.shift(offset, -SubtitleOffset.FINE_STEP_MS)) }
                ResetButton { onOffsetChange(SubtitleOffset.reset()) }
                OffsetButton("+0.1s") { onOffsetChange(SubtitleOffset.shift(offset, SubtitleOffset.FINE_STEP_MS)) }
                OffsetButton("+0.5s") { onOffsetChange(SubtitleOffset.shift(offset, SubtitleOffset.COARSE_STEP_MS)) }
            }

            Spacer(Modifier.height(14.dp))
            Text(
                text = if (hasCustomOverlay) {
                    "Applied live to the external subtitle file. The offset is kept for the rest of this viewing."
                } else {
                    "Applied live to the embedded track. If no text is showing yet, choose a subtitle in Subtitles first."
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun OffsetButton(label: String, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
private fun ResetButton(onClick: () -> Unit) {
    Button(
        onClick = onClick,
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
        ),
    ) {
        Text("RESET", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
    }
}
