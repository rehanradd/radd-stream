package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.raddstream.app.network.models.PanelDisclaimer
import com.raddstream.app.ui.components.RaddDialogTitle

/**
 * The operator's disclaimer, in full.
 *
 * The text is the operator's own words — or the shipped default when the
 * panel has published none — served by the panel; this dialog never
 * paraphrases it. The text scrolls: the panel allows up to 4000
 * characters, and a dialog that clips the terms it asks the viewer to
 * accept is not asking.
 *
 * Samsung RTL (v1.1.2, Issue 4): this used to be a Material3 alert dialog whose
 * text slot held an unbounded scrolling Column — the title, the text and
 * the buttons shared one unconstrained column, and on a phone screen the
 * long text ran over the buttons and clipped at the dialog's edge. The
 * layout here is structural instead of hopeful: a `Dialog` with a fixed
 * title, a scrollable text area that owns the middle by weight inside a
 * dialog capped at 85% of the screen height, and the buttons pinned in
 * their own row at the bottom. No text can reach the buttons, and the
 * buttons can never be pushed off the screen, however long the panel's
 * text is or however large the viewer's font scale is.
 *
 * Two uses, one dialog: on first run the confirm button is the
 * acknowledgement ("I understand") and the dialog cannot be dismissed
 * any other way — except by declining, which exits the app, because
 * using the app without agreeing is not an option; from Settings the
 * same button just closes it, because re-reading something already
 * accepted is not a new agreement.
 */
@Composable
internal fun DisclaimerDialog(
    disclaimer: PanelDisclaimer,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismissRequest: () -> Unit,
    dismissLabel: String? = null,
    onDecline: (() -> Unit)? = null,
) {
    // First run (a Decline exists) is not dismissable by back press or by
    // tapping outside: the only ways out are the two buttons. Re-reading
    // from Settings dismisses like any dialog.
    val firstRun = dismissLabel != null && onDecline != null
    Dialog(
        onDismissRequest = onDismissRequest,
        properties = DialogProperties(
            dismissOnBackPress = !firstRun,
            dismissOnClickOutside = !firstRun,
        ),
    ) {
        Surface(
            shape = RoundedCornerShape(28.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 6.dp,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .fillMaxHeight(0.85f)
                    .padding(24.dp),
            ) {
                // D-2: one dialog title style everywhere — display family,
                // semibold, 20sp.
                RaddDialogTitle("Disclaimer")
                Spacer(Modifier.height(16.dp))
                Column(
                    modifier = Modifier
                        .weight(1f, fill = true)
                        .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text(
                        disclaimer.text,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        "Version ${disclaimer.version}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (disclaimer.email.isNotBlank()) {
                        Text(
                            "Contact: ${disclaimer.email}",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
                Spacer(Modifier.height(16.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // First run only: declining is a real choice with a real
                    // consequence, so it gets its own button instead of hiding
                    // behind the back gesture, which stays disabled here.
                    val declineLabel = dismissLabel
                    val declineAction = onDecline
                    if (declineLabel != null && declineAction != null) {
                        TextButton(onClick = declineAction) {
                            Text(declineLabel)
                        }
                        Spacer(Modifier.width(8.dp))
                    }
                    Button(onClick = onConfirm) {
                        Text(confirmLabel)
                    }
                }
            }
        }
    }
}
