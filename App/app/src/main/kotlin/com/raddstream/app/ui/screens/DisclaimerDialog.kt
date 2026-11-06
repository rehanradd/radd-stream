package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.raddstream.app.network.models.PanelDisclaimer

/**
 * The operator's disclaimer, in full.
 *
 * The text is the operator's own words, served by the panel — this dialog
 * never paraphrases it, and it never shows when the text is empty, because
 * an empty disclaimer is "nothing published", not a disclaimer to agree
 * to. The text scrolls: the panel allows up to 4000 characters, and a
 * dialog that clips the terms it asks the viewer to accept is not asking.
 *
 * Two uses, one dialog: on first run the confirm button is the
 * acknowledgement ("I understand") and the dialog cannot be dismissed
 * any other way; from Settings the same button just closes it, because
 * re-reading something already accepted is not a new agreement.
 */
@Composable
internal fun DisclaimerDialog(
    disclaimer: PanelDisclaimer,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismissRequest: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismissRequest,
        title = { Text("Disclaimer") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                Text(
                    disclaimer.text,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "Version ${disclaimer.version}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            Button(onClick = onConfirm) {
                Text(confirmLabel)
            }
        },
    )
}
