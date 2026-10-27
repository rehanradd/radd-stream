package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.raddstream.app.brand.Brand

/**
 * The full-screen notice shown while the operator's `maintenance_mode` switch is on.
 *
 * It replaces the whole navigation graph rather than sitting on top of it, so no screen
 * keeps polling the catalog or holding a player behind a banner. There is deliberately no
 * dismiss control that returns to the catalog: an app that could be dismissed back into the
 * catalog would not be in maintenance at all. The flag is re-read on the watcher's own clock,
 * so the notice clears by itself once the operator turns the switch off.
 *
 * [onChangeServer] is the one exit, and the master spec asks for it ("all navigation blocked
 * EXCEPT Settings"): without it a viewer pointed at a server that is stuck, or wrongly set, to
 * maintenance can never reach the server-address screen to point the app somewhere else. The
 * notice would be a brick with a nice message on it.
 */
@Composable
fun MaintenanceScreen(
    onChangeServer: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = Icons.Default.Info,
            contentDescription = null,
            modifier = Modifier.size(56.dp),
            tint = MaterialTheme.colorScheme.primary,
        )
        Spacer(modifier = Modifier.height(20.dp))
        Text(
            text = "Under maintenance",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center,
        )
        Spacer(modifier = Modifier.height(10.dp))
        Text(
            text = "${Brand.name} is being updated right now. Please check back in a little while.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        if (onChangeServer != null) {
            Spacer(modifier = Modifier.height(24.dp))
            TextButton(onClick = onChangeServer) {
                Text("Use a different server")
            }
        }
    }
}
