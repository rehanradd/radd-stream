package com.raddstream.app.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.data.VipPendingSubmission
import com.raddstream.app.network.models.DownloadCreditPrice
import com.raddstream.app.network.models.PassTier
import com.raddstream.app.network.models.VipRemoteStreak
import com.raddstream.app.ui.theme.PlayerChromeTheme
import com.raddstream.app.ui.theme.RaddCurrent500
import com.raddstream.app.ui.theme.RaddInk950
import com.raddstream.app.ui.theme.RaddSignalGold
import com.raddstream.app.viewmodel.RewardedVipPass
import com.raddstream.app.viewmodel.VipPlan
import com.raddstream.app.viewmodel.VipMethod
import com.raddstream.app.viewmodel.VipUiState
import com.raddstream.app.viewmodel.VipViewModel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The VIP upgrade flow, priced and routed entirely by the connected server.
 *
 * The screen has three honest states and never blurs them: prices/handles not loaded yet,
 * loaded (payment instructions plus the reference form), and a claim waiting on the operator.
 * Nothing here flips a premium flag locally — the reference is POSTed to the server's payment
 * ledger, which files it as `pending` at the price that server holds, and VIP arrives only when
 * a human approves that row and this device reads the entitlement back. A reference the server
 * could not be reached is the one case kept on the device, and it says so.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VipUpgradeScreen(
    onBackClick: () -> Unit,
    /** Session 123: the wallet here opens the coins screen, where the balance and the history live. */
    onOpenCoins: () -> Unit = {},
    viewModel: VipViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    var showCancelConfirmDialog by remember { mutableStateOf(false) }

    LaunchedEffect(state.statusMessage) {
        val message = state.statusMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
        viewModel.clearStatus()
    }

    if (showCancelConfirmDialog) {
        AlertDialog(
            onDismissRequest = { showCancelConfirmDialog = false },
            title = { Text("Cancel VIP Pass?") },
            text = {
                Text(
                    "No partial refunds. VIP access stays active until the expiry date, " +
                        "and no renewal reminders will be sent."
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showCancelConfirmDialog = false
                        viewModel.cancelVipPass()
                    }
                ) {
                    Text("Confirm Cancel")
                }
            },
            dismissButton = {
                TextButton(onClick = { showCancelConfirmDialog = false }) {
                    Text("Keep VIP")
                }
            },
        )
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("VIP Membership") },
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
            VipHero()
            EntitlementCard(
                state = state,
                onCancelClick = { showCancelConfirmDialog = true },
                onResumeClick = viewModel::resumePass,
            )
            RewardedVipSection(
                expiresAt = state.rewardedVipExpiresAt,
                onActivatePass = { viewModel.grantRewardedVip() },
            )
            // Session 123: the balance beside this pass is only a number —
            // the coins screen shows it with the history behind it.
            TextButton(onClick = onOpenCoins, modifier = Modifier.fillMaxWidth()) {
                Text("Coins and history")
            }
            if (state.streak.isConfigured) {
                StreakCard(
                    streak = state.streak,
                    count = state.streakCount,
                    balance = state.coinBalance,
                    ladder = state.streakLadder,
                    catalog = state.passCatalog,
                    signedIn = state.signedIn,
                    claimedToday = state.claimedToday,
                    isClaiming = state.isClaiming,
                    claimMessage = state.claimMessage,
                    onClaim = viewModel::claimDailyLogin,
                    isRedeeming = state.isRedeeming,
                    redeemMessage = state.redeemMessage,
                    onRedeem = viewModel::redeemPass,
                )
            }
            if (state.signedIn) {
                RequestMovieCard(
                    price = state.requestPrice,
                    balance = state.coinBalance,
                    isRequesting = state.isRequesting,
                    message = state.requestMessage,
                    onRequest = viewModel::requestMovie,
                )
                ThemeCard(
                    catalog = state.themeCatalog,
                    owned = state.ownedThemes,
                    selected = state.selectedTheme,
                    balance = state.coinBalance,
                    isBuying = state.isBuyingTheme,
                    message = state.themeMessage,
                    onBuy = viewModel::buyTheme,
                    onSelect = viewModel::selectTheme,
                )
            }

            when {
                state.isLoading -> LoadingCard()
                state.loadError != null -> LoadErrorCard(
                    message = state.loadError.orEmpty(),
                    onRetry = viewModel::loadConfig,
                )
                else -> {
                    PricingSection(state = state, onSelect = viewModel::selectPlan)
                    PaymentSection(
                        state = state,
                        onCopy = { label, value ->
                            clipboard.setText(AnnotatedString(value))
                            scope.launch { snackbarHostState.showSnackbar("$label copied") }
                        },
                    )
                    MethodSection(state = state, onSelect = viewModel::selectMethod)
                    val pending = state.pending
                    if (pending != null) {
                        PendingCard(
                            pending = pending,
                            currency = state.currency,
                            onCancel = viewModel::cancelPending,
                        )
                    } else {
                        VerificationSection(state = state, viewModel = viewModel)
                    }
                }
            }

            Text(
                "Payment accounts are published by the operator of the connected catalog. " +
                    "This app never sees your transfer: it sends only the reference you type " +
                    "here, to that operator's verification queue.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * What the server itself says about this account.
 *
 * Three sentences and no fourth: VIP confirmed with its expiry, a claim on file that nobody
 * has closed yet, or — when this device holds no account to attach a claim to — the one line
 * that explains why submitting here is not enough. An entitlement the app has never read is
 * not reported as "not VIP": the card simply does not raise a claim about a question nobody
 * asked. A rewarded pass is deliberately absent from this card; it lives on the device and the
 * operator's ledger has never heard of it.
 */
@Composable
private fun EntitlementCard(
    state: VipUiState,
    onCancelClick: () -> Unit,
    onResumeClick: () -> Unit,
) {
    val earned = state.entitlement ?: return
    val until = state.vipUntilMillis
    if (!earned.vip && !earned.pending) return

    val planName = "VIP Pass"

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Surface(
            color = if (earned.vip) {
                RaddSignalGold.copy(alpha = 0.14f)
            } else {
                MaterialTheme.colorScheme.surface
            },
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        if (earned.vip) Icons.Default.Check else Icons.Default.Info,
                        contentDescription = null,
                        tint = if (earned.vip) RaddSignalGold else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        if (earned.vip) planName else "Awaiting the operator's confirmation",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onBackground,
                    )
                }

                if (earned.vip) {
                    if (until > 0L) {
                        Text(
                            validThroughLabel(until),
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Medium,
                            color = MaterialTheme.colorScheme.onBackground,
                        )
                    }
                    Text(
                        "Prepaid — no auto-renew",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )

                    // Post-cancel state badge / notice
                    if (state.serverCancelled) {
                        Surface(
                            color = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.4f),
                            shape = RoundedCornerShape(8.dp),
                        ) {
                            Text(
                                cancelledUntilLabel(until),
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                            )
                        }
                    } else if (state.isCancelPending) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Surface(
                                color = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.5f),
                                shape = RoundedCornerShape(8.dp),
                            ) {
                                Text(
                                    "Cancellation pending",
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.SemiBold,
                                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                )
                            }
                            TextButton(onClick = onResumeClick) {
                                Text("Resume Pass")
                            }
                        }
                    }
                } else {
                    Text(
                        "A payment was filed and no decision has been recorded yet. " +
                            "VIP turns on here by itself once the operator approves it.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        // [Cancel VIP Pass] outlined button below the card
        if (earned.vip && !state.isCancelled) {
            OutlinedButton(
                onClick = onCancelClick,
                enabled = !state.isCancelling,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Cancel VIP Pass")
            }
        }
    }
}

/**
 * Which channel the payment was actually sent through. The server validates a reference
 * against the channel it came from, so this is not cosmetics: an EasyPaisa reference filed as
 * JazzCash is refused, and only the viewer knows which app they opened.
 */
@Composable
internal fun MethodSection(state: VipUiState, onSelect: (VipMethod) -> Unit) {
    val offered = state.offeredMethods
    if (offered.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionLabel("I paid through")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            offered.forEach { method ->
                val selected = state.selectedMethod == method
                Surface(
                    color = if (selected) {
                        RaddSignalGold.copy(alpha = 0.16f)
                    } else {
                        MaterialTheme.colorScheme.surface
                    },
                    shape = RoundedCornerShape(12.dp),
                    border = BorderStroke(
                        width = if (selected) 2.dp else 1.dp,
                        color = if (selected) RaddSignalGold else MaterialTheme.colorScheme.outlineVariant,
                    ),
                    modifier = Modifier.clickable { onSelect(method) },
                ) {
                    Text(
                        method.label,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                        color = MaterialTheme.colorScheme.onSurface,
                        // E-T6: the chip was ~40dp tall (label line + 10dp + 10dp).
                        // 14dp of vertical padding takes it to >= 48dp.
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 14.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun VipHero() {
    Surface(
        color = RaddSignalGold.copy(alpha = 0.12f),
        shape = RoundedCornerShape(20.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Star, contentDescription = null, tint = RaddSignalGold)
                Spacer(Modifier.width(10.dp))
                Text(
                    "Go VIP",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            Text(
                "Pick a plan, send the amount to one of the operator's accounts, then submit " +
                    "the transaction ID from your confirmation. JazzCash, EasyPaisa and Raast " +
                    "are all accepted.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * The 4-hour VIP pass: a live countdown when one is stored, otherwise the offer.
 *
 * Session 123 (VIP-4): the button used to read "Watch Ad for 4-Hour VIP Pass"
 * while no ad played at all — the tap activated the pass directly. The button
 * now says what it does. No ad plays in this build; a rewarded network, when
 * added, plays an ad first and then calls the same completion handler.
 *
 * The countdown is driven by a one-second ticker with a wall-clock deadline, so it
 * cannot drift while the screen sleeps and it shows the truth after a process death.
 * The pass is device-local; the paid plans below are the only thing the operator can
 * verify server-side.
 */
@Composable
private fun RewardedVipSection(expiresAt: Long, onActivatePass: () -> Unit) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(expiresAt) {
        if (expiresAt <= 0L) return@LaunchedEffect
        while (expiresAt > System.currentTimeMillis()) {
            now = System.currentTimeMillis()
            delay(1_000L)
        }
        now = System.currentTimeMillis()
    }
    val remaining = RewardedVipPass.remainingMs(expiresAt, now)
    val active = remaining > 0L

    Surface(
        color = RaddSignalGold.copy(alpha = 0.10f),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, RaddSignalGold.copy(alpha = 0.35f)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, tint = RaddSignalGold)
                Spacer(Modifier.width(10.dp))
                Text(
                    if (active) "VIP pass active" else "Try VIP for 4 hours",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            if (active) {
                Text(
                    "Expires in ${RewardedVipPass.formatRemaining(remaining)}",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = RaddSignalGold,
                )
                Text(
                    "This rewarded pass is stored on this device. A paid plan below keeps " +
                        "VIP after it lapses.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Text(
                    "Activate a four-hour VIP pass on this device — ad-free playback " +
                        "and direct downloads. No ad plays when you tap this.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(onClick = onActivatePass, modifier = Modifier.fillMaxWidth()) {
                    Icon(
                        Icons.Default.PlayArrow,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text("Activate 4-Hour VIP Pass")
                }
                Text(
                    "When a rewarded network is added, an ad will play first and then " +
                        "call the same completion handler.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * The login streak (plan §5 step 19) and the daily check-in that pays it: consecutive days
 * this device opened the app, against the operator's own plan (target days, reward coins).
 * The count is local — MainActivity records one open per day — and the coins are the
 * server's: the seven pills show the ladder the server will pay, the Claim button asks
 * the server for today's grant, and the balance is the ledger's own answer. A claim the
 * server already paid answers "already claimed" and pays nothing twice. Hidden entirely
 * when the operator never configured a streak, so an absent plan is never shown as a zero.
 */
@Composable
private fun StreakCard(
    streak: VipRemoteStreak,
    count: Int,
    balance: Int,
    ladder: Map<Int, Int>,
    catalog: Map<String, PassTier>,
    signedIn: Boolean,
    claimedToday: Boolean,
    isClaiming: Boolean,
    claimMessage: String?,
    onClaim: () -> Unit,
    isRedeeming: Boolean,
    redeemMessage: String?,
    onRedeem: (String) -> Unit,
) {
    val complete = count >= streak.days
    val today = (count + 1).coerceIn(1, streak.days)
    Surface(
        color = RaddCurrent500.copy(alpha = 0.10f),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, RaddCurrent500.copy(alpha = 0.35f)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.DateRange, contentDescription = null, tint = RaddCurrent500)
                Spacer(Modifier.width(10.dp))
                Text(
                    "Login streak",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            Text(
                if (complete) "${streak.days}-day streak complete."
                else "Day $count of ${streak.days} — open the app every day to keep it going.",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = RaddCurrent500,
            )
            LinearProgressIndicator(
                progress = { (count.toFloat() / streak.days).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
                color = RaddCurrent500,
            )
            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                for (day in 1..streak.days) {
                    val done = day <= count
                    val isToday = day == today && !complete
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .weight(1f)
                            .padding(vertical = 4.dp),
                    ) {
                        Surface(
                            color = when {
                                done -> RaddCurrent500.copy(alpha = 0.25f)
                                isToday -> RaddCurrent500.copy(alpha = 0.10f)
                                else -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                            },
                            shape = RoundedCornerShape(10.dp),
                            border = if (isToday) {
                                BorderStroke(1.dp, RaddCurrent500)
                            } else {
                                null
                            },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier.padding(vertical = 8.dp, horizontal = 2.dp),
                            ) {
                                Text(
                                    "Day $day",
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = if (isToday) FontWeight.Bold else FontWeight.Normal,
                                    color = MaterialTheme.colorScheme.onBackground,
                                    textAlign = TextAlign.Center,
                                )
                                Text(
                                    ladder[day]?.let { "$it coins" } ?: "",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    textAlign = TextAlign.Center,
                                )
                            }
                        }
                    }
                }
            }
            if (signedIn) {
                Text(
                    "Wallet: $balance coins.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Button(
                onClick = onClaim,
                enabled = signedIn && !claimedToday && !isClaiming,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (claimedToday) "Claimed today" else "Claim Today's Coins")
            }
            if (!signedIn) {
                Text(
                    "Sign in to claim your coins.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (claimMessage != null) {
                Text(
                    claimMessage,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (catalog.isNotEmpty()) {
                Text(
                    "Spend coins",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground,
                )
                for (plan in listOf("day", "weekend", "monthly_vip")) {
                    val tier = catalog[plan] ?: continue
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                when (plan) {
                                    "day" -> "24-hour VIP pass"
                                    "weekend" -> "Weekend VIP pass"
                                    "monthly_vip" -> "30-day VIP pass"
                                    else -> "VIP pass"
                                },
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onBackground,
                            )
                            Text(
                                "${tier.coins} coins",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Button(
                            onClick = { onRedeem(plan) },
                            enabled = signedIn && !isRedeeming && balance >= tier.coins,
                        ) {
                            Text("Redeem")
                        }
                    }
                }
                if (redeemMessage != null) {
                    Text(
                        redeemMessage,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (streak.rewardCoins > 0) {
                Text(
                    "Reward: ${streak.rewardCoins} coins when you reach ${streak.days} days.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "Counted on this device. The coins go to your wallet when the server pays them.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** A theme id in the viewer's words: the names are the server's. */
private fun themeLabel(theme: String): String = when (theme) {
    PlayerChromeTheme.MIDNIGHT -> "Midnight"
    PlayerChromeTheme.EMBER -> "Ember"
    else -> "Jade"
}

@Composable
private fun RequestMovieCard(
    price: Int,
    balance: Int,
    isRequesting: Boolean,
    message: String?,
    onRequest: (String) -> Unit,
) {
    var title by remember { mutableStateOf("") }
    // No form until the server publishes a price: a request with no price is a
    // promise this screen cannot keep.
    if (price <= 0) return
    Surface(
        color = RaddCurrent500.copy(alpha = 0.10f),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, RaddCurrent500.copy(alpha = 0.35f)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Movie, contentDescription = null, tint = RaddCurrent500)
                Spacer(Modifier.width(10.dp))
                Text(
                    "Request a movie",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            Text(
                "Missing a title? Spend $price coins and the team will look for it.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = title,
                onValueChange = { if (it.length <= 200) title = it },
                label = { Text("Movie name") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { onRequest(title) },
                enabled = title.isNotBlank() && !isRequesting && balance >= price,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (isRequesting) "Requesting…" else "Request — $price coins")
            }
            if (message != null) {
                Text(
                    message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ThemeCard(
    catalog: Map<String, DownloadCreditPrice>,
    owned: List<String>,
    selected: String,
    balance: Int,
    isBuying: Boolean,
    message: String?,
    onBuy: (String) -> Unit,
    onSelect: (String) -> Unit,
) {
    // Jade is the shipped look and is always owned; the catalog holds only the
    // themes coins can buy. No card until the server publishes a price.
    if (catalog.isEmpty()) return
    Surface(
        color = RaddCurrent500.copy(alpha = 0.10f),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, RaddCurrent500.copy(alpha = 0.35f)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Palette, contentDescription = null, tint = RaddCurrent500)
                Spacer(Modifier.width(10.dp))
                Text(
                    "Player themes",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            Text(
                "A skin for the player's chrome — the background, the plates, the rail. Never the accent that marks a selected control.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            for (theme in PlayerChromeTheme.IDS) {
                val isOwned = theme == PlayerChromeTheme.JADE || theme in owned
                val isSelected = theme == selected
                val cost = catalog[theme]?.coins ?: 0
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            themeLabel(theme) + if (isSelected) " — wearing" else "",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onBackground,
                        )
                        Text(
                            when {
                                theme == PlayerChromeTheme.JADE -> "The shipped look — free"
                                isOwned -> "Owned"
                                else -> "$cost coins"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Button(
                        onClick = { if (isOwned) onSelect(theme) else onBuy(theme) },
                        enabled = !isBuying && (isOwned || balance >= cost),
                    ) {
                        Text(
                            when {
                                isSelected -> "Wearing"
                                isOwned -> "Wear"
                                else -> "Buy — $cost"
                            },
                        )
                    }
                }
            }
            if (message != null) {
                Text(
                    message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
internal fun PricingSection(state: VipUiState, onSelect: (VipPlan) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionLabel("Choose your plan")
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            PlanCard(
                plan = VipPlan.MONTHLY,
                price = state.priceFor(VipPlan.MONTHLY),
                currency = state.currency,
                selected = state.selectedPlan == VipPlan.MONTHLY,
                badge = null,
                onSelect = onSelect,
                modifier = Modifier.weight(1f),
            )
            PlanCard(
                plan = VipPlan.YEARLY,
                price = state.priceFor(VipPlan.YEARLY),
                currency = state.currency,
                selected = state.selectedPlan == VipPlan.YEARLY,
                badge = yearlyBadge(state),
                onSelect = onSelect,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun PlanCard(
    plan: VipPlan,
    price: Int,
    currency: String,
    selected: Boolean,
    badge: String?,
    onSelect: (VipPlan) -> Unit,
    modifier: Modifier = Modifier,
) {
    val container = if (selected) {
        RaddSignalGold.copy(alpha = 0.16f)
    } else {
        MaterialTheme.colorScheme.surface
    }
    Surface(
        color = container,
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(
            width = if (selected) 2.dp else 1.dp,
            color = if (selected) RaddSignalGold else MaterialTheme.colorScheme.outlineVariant,
        ),
        modifier = modifier.clickable { onSelect(plan) },
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                plan.label,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                amountLabel(currency, price),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = if (selected) RaddSignalGold else MaterialTheme.colorScheme.onSurface,
            )
            Text(
                plan.period,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                if (price <= 0) "Not published by the server" else "Total incl. taxes",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (badge != null) {
                Surface(
                    color = RaddSignalGold,
                    shape = RoundedCornerShape(50),
                ) {
                    Text(
                        badge,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                        color = RaddInk950,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                    )
                }
            }
        }
    }
}

@Composable
internal fun PaymentSection(state: VipUiState, onCopy: (label: String, value: String) -> Unit) {
    val amount = amountLabel(state.currency, state.priceFor(state.selectedPlan))
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            SectionLabel("Send $amount to one of these accounts")
            if (!state.hasPaymentHandle) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        Icons.Default.Info,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "The operator has not published payment accounts yet, so there is " +
                            "nowhere to send a payment. Try again later.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            PaymentHandleRow(
                label = "JazzCash Merchant Till ID",
                value = state.jazzCashTillId,
                onCopy = onCopy,
            )
            PaymentHandleRow(
                label = "JazzCash Mobile Account",
                value = state.jazzCashMobileAccount,
                onCopy = onCopy,
            )
            PaymentHandleRow(
                label = "EasyPaisa Account",
                value = state.easyPaisaMobile,
                onCopy = onCopy,
            )
            PaymentHandleRow(
                label = "Raast Instant ID",
                value = state.raastInstantId,
                onCopy = onCopy,
            )
            Text(
                "Tap the copy icon, then paste the account into your banking app before " +
                    "sending. Check the name shown there before you confirm.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun PaymentHandleRow(
    label: String,
    value: String,
    onCopy: (label: String, value: String) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                value.ifBlank { "Not configured yet" },
                style = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
                fontWeight = if (value.isBlank()) FontWeight.Normal else FontWeight.SemiBold,
                color = if (value.isBlank()) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
            )
        }
        IconButton(
            onClick = { onCopy(label, value) },
            enabled = value.isNotBlank(),
        ) {
            Icon(
                Icons.Default.ContentCopy,
                contentDescription = "Copy $label",
                tint = if (value.isBlank()) {
                    MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f)
                } else {
                    RaddSignalGold
                },
            )
        }
    }
}

@Composable
private fun VerificationSection(state: VipUiState, viewModel: VipViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionLabel("Confirm your payment")
        Text(
            "After the transfer, copy the transaction ID (TID) from the confirmation SMS and " +
                "enter it below.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = state.transactionId,
            onValueChange = viewModel::onTransactionIdChanged,
            label = { Text("Transaction ID (TID)") },
            placeholder = { Text("e.g. 8123498172") },
            singleLine = true,
            isError = state.tidError != null,
            supportingText = if (state.tidError != null) {
                { Text(state.tidError) }
            } else {
                null
            },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Ascii,
                imeAction = ImeAction.Done,
            ),
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = viewModel::submitTransaction,
            enabled = state.canSubmit && state.transactionId.isNotBlank() &&
                state.selectedMethod != null,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (state.isSubmitting) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
                Spacer(Modifier.width(8.dp))
                Text("Sending…")
            } else {
                Text("Submit for verification")
            }
        }
        Text(
            if (!state.signedIn) {
                "This device is not signed in to an account, so a reference sent now is kept " +
                    "here and filed the moment you sign in on the Settings tab. The operator " +
                    "attaches a payment to an account, not to a phone."
            } else {
                "The reference goes to this server's verification queue. VIP turns on once the " +
                    "operator confirms the payment — nothing is activated by this app."
            },
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PendingCard(
    pending: VipPendingSubmission,
    currency: String,
    onCancel: () -> Unit,
) {
    val plan = VipPlan.fromStorage(pending.plan)
    Surface(
        color = MaterialTheme.colorScheme.primaryContainer,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Default.Info,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    "Not sent to the operator yet",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
            Text(
                "${plan.label} · ${amountLabel(currency, pending.amountPkr)}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Text(
                listOfNotNull(
                    "Reference ${pending.transactionId}",
                    VipMethod.fromWire(pending.method)?.label,
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            if (pending.submittedAt > 0L) {
                Text(
                    "Entered ${submittedLabel(pending.submittedAt)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
            Text(
                "This reference never reached the server, so it is held on this device and " +
                    "sent again the next time this screen loads with a connection. Removing it " +
                    "does not cancel a transfer you have already made.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            TextButton(onClick = onCancel) { Text("Remove request") }
        }
    }
}

@Composable
private fun LoadErrorCard(message: String, onRetry: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                "Payment details could not be loaded",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedButton(onClick = onRetry) {
                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Try again")
            }
        }
    }
}

@Composable
private fun LoadingCard() {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(24.dp),
            strokeWidth = 2.dp,
            color = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.width(12.dp))
        Text(
            "Loading plans and payment accounts…",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onBackground,
    )
}

/** Formatted currency amount like "$currency N,NNN", or the words for a server that has not priced the plan; never an invented figure. */
private fun amountLabel(currency: String, amount: Int): String =
    if (amount <= 0) "Not published by the server" else
        "$currency " + String.format(Locale.US, "%,d", amount)

/** The yearly card's savings, shown only when the server's two prices actually differ. */
private fun yearlyBadge(state: VipUiState): String? {
    // A missing price is not a cheap one: subtracting an unpublished zero from a published figure
    // would print a saving the server never offered.
    if (state.monthlyPkr <= 0 || state.yearlyPkr <= 0) return null
    val saving = state.monthlyPkr * 12 - state.yearlyPkr
    return if (saving > 0) "Save ${amountLabel(state.currency, saving)}" else null
}

private fun submittedLabel(epochMs: Long): String =
    SimpleDateFormat("d MMM yyyy, HH:mm", Locale.getDefault()).format(Date(epochMs))

/** The server's expiry, printed in the viewer's own calendar. It is a deadline, not a countdown. */
private fun expiryLabel(epochMs: Long): String =
    SimpleDateFormat("d MMM yyyy", Locale.getDefault()).format(Date(epochMs))

/** "Valid Through DD MMM YYYY" from vip_until */
private fun validThroughLabel(epochMs: Long): String =
    "Valid Through " + SimpleDateFormat("dd MMM yyyy", Locale.US).format(Date(epochMs))

private fun cancelledUntilLabel(epochMs: Long): String =
    "Cancelled — access remains active until " + SimpleDateFormat("dd MMM yyyy", Locale.US).format(Date(epochMs))
