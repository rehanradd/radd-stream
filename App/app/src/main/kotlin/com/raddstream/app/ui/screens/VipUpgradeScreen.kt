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
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.data.VipPendingSubmission
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
    viewModel: VipViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(state.statusMessage) {
        val message = state.statusMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
        viewModel.clearStatus()
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
            EntitlementCard(state = state)
            RewardedVipSection(
                expiresAt = state.rewardedVipExpiresAt,
                onWatchAd = { viewModel.grantRewardedVip() },
            )

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
private fun EntitlementCard(state: VipUiState) {
    val earned = state.entitlement
    val until = state.vipUntilMillis
    val title = when {
        earned == null -> return
        earned.vip -> "VIP is active"
        earned.pending -> "Awaiting the operator's confirmation"
        else -> return
    }
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
                    title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            Text(
                when {
                    earned.vip && until > 0L -> "Confirmed through ${expiryLabel(until)}."
                    earned.vip -> "Confirmed by the operator."
                    else -> "A payment was filed and no decision has been recorded yet. " +
                        "VIP turns on here by itself once the operator approves it."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * Which channel the payment was actually sent through. The server validates a reference
 * against the channel it came from, so this is not cosmetics: an EasyPaisa reference filed as
 * JazzCash is refused, and only the viewer knows which app they opened.
 */
@Composable
private fun MethodSection(state: VipUiState, onSelect: (VipMethod) -> Unit) {
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
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
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
 * The rewarded-ad pass: a live countdown when one is stored, otherwise the offer.
 *
 * The countdown is driven by a one-second ticker with a wall-clock deadline, so it
 * cannot drift while the screen sleeps and it shows the truth after a process death.
 * The pass is device-local; the paid plans below are the only thing the operator can
 * verify server-side.
 */
@Composable
private fun RewardedVipSection(expiresAt: Long, onWatchAd: () -> Unit) {
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
                    "Watch a short sponsored clip to unlock four hours of ad-free, direct " +
                        "downloads on this device.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(onClick = onWatchAd, modifier = Modifier.fillMaxWidth()) {
                    Icon(
                        Icons.Default.PlayArrow,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text("Watch Ad for 4-Hour VIP Pass")
                }
                Text(
                    "This build has no ad player yet, so the button activates the pass " +
                        "directly. A rewarded network, when added, must call the same " +
                        "completion handler.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun PricingSection(state: VipUiState, onSelect: (VipPlan) -> Unit) {
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
private fun PaymentSection(state: VipUiState, onCopy: (label: String, value: String) -> Unit) {
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

/** `PKR 1,500`; the currency comes from the server, never assumed here. */
private fun amountLabel(currency: String, amount: Int): String =
    "$currency " + String.format(Locale.US, "%,d", amount)

/** The yearly card's savings, shown only when the server's two prices actually differ. */
private fun yearlyBadge(state: VipUiState): String? {
    val saving = state.monthlyPkr * 12 - state.yearlyPkr
    return if (saving > 0) "Save ${amountLabel(state.currency, saving)}" else null
}

private fun submittedLabel(epochMs: Long): String =
    SimpleDateFormat("d MMM yyyy, HH:mm", Locale.getDefault()).format(Date(epochMs))

/** The server's expiry, printed in the viewer's own calendar. It is a deadline, not a countdown. */
private fun expiryLabel(epochMs: Long): String =
    SimpleDateFormat("d MMM yyyy", Locale.getDefault()).format(Date(epochMs))
