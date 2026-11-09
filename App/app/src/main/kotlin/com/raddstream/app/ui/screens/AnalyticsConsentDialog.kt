package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.raddstream.app.ui.theme.RaddTokens

/**
 * The first-run question Tracking A asks before it counts anything.
 *
 * Session 123 (D-1): it used to arrive as a 10-line paragraph in a dialog
 * over a black void — the first impression of the product was a terms page.
 * It is now a bottom sheet over a loaded Home (MainActivity already waits
 * for Home and for the disclaimer to settle), with the promise structured
 * as three check-marked reassurances instead of a paragraph. What it
 * promises is the design, not a slogan: totals only (how many plays, how
 * often playback fails, how often the app crashes), never a name, a number,
 * a location, a title, or a search, and no per-person record anywhere.
 * Both answers are real choices: "Share totals" turns the counters on,
 * "No thanks" leaves the app exactly as it was — nothing is counted,
 * nothing is sent, and nothing about the app changes. The choice can be
 * changed later in Settings. The sheet cannot be dismissed any other way,
 * because an unanswered question would leave the app counting nothing
 * forever without the viewer ever knowing it was asked.
 *
 * The operator has not written analytics wording yet, the way he has not
 * written the disclaimer text either — this is this app's own plain-English
 * draft.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AnalyticsConsentDialog(
    onAccept: () -> Unit,
    onDecline: () -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = {},
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = RaddTokens.Space.Lg),
        ) {
            Text(
                "Anonymous usage totals",
                style = RaddTokens.Type.Headline,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(RaddTokens.Space.Md))
            Reassurance("Totals only — how many plays, failures, and crashes.")
            Reassurance("Never your name, phone, location, titles, or searches.")
            Reassurance("No per-person record — totals cannot identify your phone.")
            Spacer(Modifier.height(RaddTokens.Space.Md))
            Button(onClick = onAccept, modifier = Modifier.fillMaxWidth()) {
                Text("Share totals")
            }
            TextButton(onClick = onDecline, modifier = Modifier.fillMaxWidth()) {
                Text("No thanks")
            }
            Text(
                "You can change this anytime in Settings. Saying no changes nothing about the app.",
                style = RaddTokens.Type.BodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(RaddTokens.Space.Lg))
        }
    }
}

@Composable
private fun Reassurance(text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
            Icons.Default.Check,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.width(RaddTokens.Space.Sm))
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
    Spacer(Modifier.height(RaddTokens.Space.Sm))
}
