package com.raddstream.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.ui.theme.AccentGreen
import com.raddstream.app.ui.theme.AccentPrimary
import com.raddstream.app.ui.theme.AccentRed
import com.raddstream.app.ui.theme.BackgroundDark
import com.raddstream.app.ui.theme.OnBackground
import com.raddstream.app.ui.theme.OnSurfaceMuted
import com.raddstream.app.viewmodel.SetupViewModel

@Composable
fun SetupScreen(
    onConnected: () -> Unit,
    viewModel: SetupViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BackgroundDark)
            .imePadding()
            .padding(horizontal = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("RADD Stream", style = MaterialTheme.typography.headlineLarge, color = OnBackground)
        Spacer(Modifier.height(8.dp))
        Text(
            text = "Connect to a catalog server you operate or are authorized to use.",
            style = MaterialTheme.typography.bodyMedium,
            color = OnSurfaceMuted,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(24.dp))

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

        state.message?.let { message ->
            Spacer(Modifier.height(12.dp))
            Text(
                text = message,
                color = if (state.messageIsError) AccentRed else AccentGreen,
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
            )
        }

        Spacer(Modifier.height(20.dp))
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

        Spacer(Modifier.height(12.dp))
        Button(
            onClick = onConnected,
            enabled = state.isConnected && !state.isChecking,
            modifier = Modifier.fillMaxWidth().height(52.dp),
            colors = ButtonDefaults.buttonColors(containerColor = AccentPrimary),
        ) {
            Text("Continue", style = MaterialTheme.typography.labelLarge)
        }
    }
}
