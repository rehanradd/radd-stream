package com.raddstream.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.ui.theme.RaddBrandLockup
import com.raddstream.app.brand.Brand
import com.raddstream.app.viewmodel.SetupViewModel

@Composable
fun SetupScreen(
    onConnected: () -> Unit,
    viewModel: SetupViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    // UI-fix P0-4: the shipped server is probed once on arrival, with the
    // progress visible — a first-run user never meets a dead screen that
    // only asks for an address they do not have.
    LaunchedEffect(Unit) {
        if (!state.isConnected) viewModel.retryDefault()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .imePadding()
            .navigationBarsPadding()
            .padding(horizontal = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        // Restyle 2026-11-13: first run opens on the brand lockup — mark +
        // two-tone wordmark — instead of a bare name in headline type. The
        // tagline lives in the body copy below, so the lockup stays clean.
        RaddBrandLockup(
            markSize = 40.dp,
            onName = MaterialTheme.colorScheme.onBackground,
            onStream = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = "${Brand.name} connects automatically. If that fails, you can enter a different address — or continue offline with your saved titles.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(24.dp))

        // The address is never printed on first sight: Connect tests the
        // shipped server without displaying it, and the field below opens
        // only when the viewer explicitly asks for a different server.
        if (state.showUrlField) {
            OutlinedTextField(
                value = state.serverUrl,
                onValueChange = viewModel::onServerUrlChanged,
                label = { Text("Server URL") },
                placeholder = { Text("https://media.example.com:8080") },
                singleLine = true,
                enabled = !state.isChecking,
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Done,
                ),
            )
        }

        state.message?.let { message ->
            Spacer(Modifier.height(12.dp))
            Text(
                text = message,
                color = if (state.messageIsError) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
            )
        }

        Spacer(Modifier.height(20.dp))
        if (state.showUrlField) {
            OutlinedButton(
                onClick = viewModel::testConnection,
                enabled = !state.isChecking && state.serverUrl.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isChecking) {
                    CircularProgressIndicator(
                        modifier = Modifier.height(18.dp),
                        strokeWidth = 2.dp,
                    )
                } else {
                    Text("Test connection")
                }
            }
        } else {
            OutlinedButton(
                onClick = viewModel::retryDefault,
                enabled = !state.isChecking,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isChecking) {
                    CircularProgressIndicator(
                        modifier = Modifier.height(18.dp),
                        strokeWidth = 2.dp,
                    )
                } else {
                    Text("Connect")
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        Button(
            onClick = onConnected,
            enabled = state.isConnected && !state.isChecking,
            modifier = Modifier.fillMaxWidth().height(56.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary,
            ),
        ) {
            Text("Continue", style = MaterialTheme.typography.labelLarge)
        }

        // UI-fix P0-4: never strand the user. If the shipped server does not
        // answer, Home still opens — saved titles and the retry there — with
        // no address to type and no dead end.
        if (!state.isConnected) {
            Spacer(Modifier.height(8.dp))
            TextButton(onClick = onConnected) {
                Text("Continue offline — saved titles only")
            }
        }

        if (!state.showUrlField) {
            Spacer(Modifier.height(8.dp))
            TextButton(onClick = viewModel::revealUrlField) {
                Text("Use a different server")
            }
        }
    }
}
