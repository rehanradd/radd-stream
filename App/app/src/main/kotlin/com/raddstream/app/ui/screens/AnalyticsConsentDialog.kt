package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.raddstream.app.brand.Brand

/**
 * The first-run question Tracking A asks before it counts anything.
 *
 * The text is this app's own plain-English draft — the operator has not
 * written analytics wording yet, the way he has not written the disclaimer
 * text either. What it promises is the design, not a slogan: totals only
 * (how many plays, how often playback fails, how often the app crashes),
 * never a name, a number, a location, a title, or a search, and no
 * per-person record anywhere. Both answers are real choices: "Share totals"
 * turns the counters on, "No thanks" leaves the app exactly as it was —
 * nothing is counted, nothing is sent, and nothing about the app changes.
 * The choice can be changed later in Settings. The dialog cannot be
 * dismissed any other way, because an unanswered question would leave the
 * app counting nothing forever without the viewer ever knowing it was asked.
 */
@Composable
internal fun AnalyticsConsentDialog(
    onAccept: () -> Unit,
    onDecline: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = {},
        title = { Text("Anonymous usage totals") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                Text(
                    "Help improve ${Brand.name} by sharing anonymous totals: " +
                        "how many times videos are played, how often playback " +
                        "fails, and how often the app crashes.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "We count totals only. We never collect your name, phone " +
                        "number, location, what you watch, or what you search " +
                        "for. There is no per-person record, and the totals " +
                        "cannot identify your phone.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "You can change this anytime in Settings. Saying no " +
                        "changes nothing about the app.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            Button(onClick = onAccept) {
                Text("Share totals")
            }
        },
        dismissButton = {
            TextButton(onClick = onDecline) {
                Text("No thanks")
            }
        },
    )
}
