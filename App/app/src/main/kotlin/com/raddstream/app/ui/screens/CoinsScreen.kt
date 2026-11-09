package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * What a ledger row's reason means, in the viewer's words. The reasons are
 * the server's closed vocabulary (`engagement.LEDGER_REASONS`); a reason
 * this build has never seen is shown as itself, never guessed at.
 */
internal fun humanCoinReason(reason: String): String = when (reason) {
    "streak_day" -> "Daily check-in"
    "rewarded_ad" -> "Rewarded ad"
    "share" -> "Shared a title"
    "finish_watch" -> "Finished watching"
    "admin_grant" -> "Top-up"
    "refund" -> "Refund"
    "redeem_pass" -> "VIP pass"
    "redeem_download" -> "Direct download"
    "redeem_theme" -> "Player theme"
    "redeem_request" -> "Title request"
    else -> reason
}

/** One ledger instant, as a short date. The ledger's timestamps are epoch seconds. */
internal fun formatCoinDay(epochSeconds: Double): String {
    if (epochSeconds <= 0.0) return ""
    return SimpleDateFormat("d MMM yyyy", Locale.getDefault())
        .format(Date((epochSeconds * 1_000).toLong()))
}

/**
 * The coin screen: the balance, the passes the coins buy, and the history of
 * every coin that moved. Session 123: the app had no coin screen at all — the
 * balance was a number inside the VIP screen and the history did not exist
 * anywhere a viewer could see it, even though the server has served
 * `coins/history` all along. A redeem spends through the ledger's own guarded
 * debit, at the price the server publishes; the button is guarded by the
 * wallet the screen shows, and a refusal is reported in the viewer's own
 * words with the balance re-read either way.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CoinsScreen(
    onBackClick: () -> Unit,
    viewModel: AccountViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("Coins") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { contentPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (state.isLoading) {
                item {
                    Text(
                        "Loading your coins…",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Balance", style = MaterialTheme.typography.labelLarge)
                        Text(
                            "${state.coinBalance} coins",
                            style = MaterialTheme.typography.headlineMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            "Earn coins by checking in every day. Coins never expire and cannot be bought with money here.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            if (state.passCatalog.isNotEmpty()) {
                item {
                    Text(
                        "Spend coins on a VIP pass",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
                items(state.passCatalog.entries.sortedBy { it.value.coins }) { (plan, tier) ->
                    Card(
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            Modifier.padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column {
                                Text(plan, style = MaterialTheme.typography.titleMedium)
                                Text(
                                    "${tier.coins} coins",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Button(
                                onClick = { viewModel.redeemPass(plan) },
                                enabled = state.signedIn &&
                                    state.redeemingPlan == null &&
                                    state.coinBalance >= tier.coins,
                            ) {
                                Text(
                                    if (state.redeemingPlan == plan) "Redeeming…" else "Redeem",
                                )
                            }
                        }
                    }
                }
                state.redeemMessage?.let { message ->
                    item {
                        Text(
                            message,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            item {
                Text(
                    "History",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            if (state.history.isEmpty()) {
                item {
                    Text(
                        "No coin movements yet — check in tomorrow and the first one appears here.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                items(state.history) { entry ->
                    Row(
                        Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column {
                            Text(
                                humanCoinReason(entry.reason),
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            val day = formatCoinDay(entry.createdAt)
                            if (day.isNotEmpty()) {
                                Text(
                                    day,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        Text(
                            (if (entry.delta >= 0) "+" else "") + "${entry.delta}",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold,
                            color = if (entry.delta >= 0) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            },
                        )
                    }
                }
            }
            state.loadError?.let { error ->
                item {
                    Text(
                        error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
