package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import com.raddstream.app.viewmodel.SettingsViewModel

/**
 * The one screen a viewer cannot walk past with a credential they never read.
 *
 * The silent trial mints a sync key on the process scope at launch
 * (`SyncAccountRepository.startDeviceTrial`), while no card is open, and that plaintext
 * never exists again: the server keeps a one-way digest and says so about itself at
 * `Fast_Fetch/accounts.py:1200-1208` ("a device that lost it cannot be given it back"),
 * and this app has no recovery route to contradict that. Until now the only place the key
 * was painted was the Account card in Settings — so an install that went straight to the
 * catalog had already spent its one reveal, and the viewer found out only when they wanted
 * their list on a second device.
 *
 * That is what this dialog is for, and it is the reason the key may be masked at rest
 * ([com.raddstream.app.sync.SyncContract.keyPreview] now shows a fingerprint and no slice of
 * the secret): masking a credential whose one and only display can be missed is not a
 * security fix, it is a loss made less visible. The two changes are one change.
 *
 * The dismiss path is the whole design. `onDismissRequest` is a no-op, and every way out of
 * a Material3 dialog — the back button, a tap outside, the scrim — arrives at that lambda,
 * so there is none; the only route is [onAcknowledge], which clears the unseen flag and can
 * never put the key back on a screen afterwards. Nothing here times out, scrolls away, or
 * offers "later": a gate a viewer can walk past is the card they already ignored.
 */
@Composable
fun TrialKeyRevealDialog(
    key: String,
    onAcknowledge: () -> Unit,
) {
    val clipboard = LocalClipboardManager.current
    AlertDialog(
        onDismissRequest = {},
        title = { Text("Write your sync key down") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "This device just got its own account, and the line below is the only " +
                        "credential it will ever have. Copy it somewhere now.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                OutlinedTextField(
                    value = key,
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("Your sync key") },
                    textStyle = MaterialTheme.typography.bodySmall,
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        TextButton(onClick = { clipboard.setText(AnnotatedString(key)) }) {
                            Text("Copy")
                        }
                    },
                )
                // The same sentence the Account card uses, from the same constant, so the two
                // screens cannot disagree about what losing this costs.
                Text(
                    SettingsViewModel.REVEAL_WARNING,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error,
                )
                Text(
                    "There is no reset and no way to show this again. Once it is copied, " +
                        "confirm below and the app will not ask a second time.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            Button(onClick = onAcknowledge) { Text("I have written it down") }
        },
    )
}
