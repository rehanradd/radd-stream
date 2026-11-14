package com.raddstream.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.style.TextDecoration
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
                val scrollState = rememberScrollState()
                val uriHandler = LocalUriHandler.current
                Column(
                    modifier = Modifier
                        .weight(1f, fill = true)
                        .verticalScroll(scrollState),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    // F13 (Batch B): the text arrives as one block from the
                    // panel, and a wall of it is not read — each line break
                    // is a paragraph, and each paragraph gets its own block
                    // with air between them. A blank line is nothing to show.
                    disclaimer.text.split("\n").map { it.trim() }
                        .filter { it.isNotEmpty() }.forEach { paragraph ->
                            Text(
                                paragraph,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                    Text(
                        "Version ${disclaimer.version}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (disclaimer.email.isNotBlank()) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "Contact: ",
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            // F13 (Batch B): the address is a link, not a
                            // line to copy by hand — one tap opens the mail
                            // app addressed to it.
                            Text(
                                disclaimer.email,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.primary,
                                textDecoration = TextDecoration.Underline,
                                modifier = Modifier.clickable {
                                    uriHandler.openUri("mailto:${disclaimer.email}")
                                },
                            )
                        }
                    }
                }
                // F13 (Batch B): the scroll cue — a small line that says the
                // text goes on, shown only while there is more below. A
                // dialog that scrolls without saying so hides its own terms.
                if (scrollState.canScrollForward) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "Scroll for more",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Icon(
                            Icons.Default.KeyboardArrowDown,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
                Spacer(Modifier.height(16.dp))
                // F13 (Batch B): on first run the Decline is its own line
                // under the Accept button — the choice to walk away is
                // unmissable, not a small word beside the big button. On a
                // re-read there is no Decline at all: the terms are already
                // accepted, and re-reading is not a new agreement.
                if (firstRun) {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Button(
                            onClick = onConfirm,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(confirmLabel)
                        }
                        TextButton(onClick = onDecline ?: {}) {
                            Text(dismissLabel ?: "")
                        }
                    }
                } else {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Button(onClick = onConfirm) {
                            Text(confirmLabel)
                        }
                    }
                }
            }
        }
    }
}
