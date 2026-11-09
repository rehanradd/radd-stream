package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.compose.runtime.collectAsState
import com.raddstream.app.viewmodel.AccountViewModel

/**
 * The standalone check-in screen. Session 123: the daily check-in lived
 * only inside the VIP screen, so a viewer who never opened VIP never saw
 * it — and the Home card could claim, but never show the week. This screen
 * shows the 7-day ladder the server will actually pay, the streak it counts
 * on the server (not the device's local open-count), and the one Claim button.
 * A day already claimed rests; a day beyond the ladder's seventh is the
 * ladder complete, not a new promise. Nothing here is a local count: the
 * ladder, the streak and the grant all come from the ledger, and the claim's
 * answer is the server's own.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CheckInScreen(
    onBackClick: () -> Unit,
    viewModel: AccountViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("Daily check-in") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (state.isLoading) {
                Text(
                    "Loading your check-in…",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "Claim every day to keep the streak going. The coins are the server's ladder — the same ladder the claim pays.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "${state.currentStreak} days in a row · best ${state.bestStreak}",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            // The ladder, one row per day. A day at or below the current
            // streak is claimed; the next day is today's; the rest wait.
            // A streak past day 7 has completed the ladder — the rows still
            // show, claimed, rather than pretending an eighth day pays.
            for (day in 1..7) {
                val coins = state.streakLadder[day]
                val claimed = day <= state.currentStreak
                val isToday = !state.claimedToday && day == state.currentStreak + 1
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = if (isToday) {
                            MaterialTheme.colorScheme.primaryContainer
                        } else {
                            MaterialTheme.colorScheme.surfaceVariant
                        },
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            "Day $day",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = if (isToday) FontWeight.Bold else FontWeight.Normal,
                        )
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (coins != null) {
                                Text(
                                    "+$coins coins",
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                            } else {
                                Text(
                                    "—",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            if (claimed) {
                                Icon(
                                    Icons.Default.Check,
                                    contentDescription = "Claimed",
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.padding(start = 8.dp),
                                )
                            }
                        }
                    }
                }
            }
            if (!state.signedIn) {
                Text(
                    "Sign in from Settings to claim your coins.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else if (state.claimedToday) {
                Text(
                    state.claimMessage ?: "Claimed for today — come back tomorrow.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            } else {
                Button(
                    onClick = { viewModel.claimDailyLogin() },
                    enabled = !state.isClaiming,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (state.isClaiming) "Claiming…" else "Claim today's coins")
                }
                state.claimMessage?.let { message ->
                    Text(
                        message,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            state.loadError?.let { error ->
                Text(
                    error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
