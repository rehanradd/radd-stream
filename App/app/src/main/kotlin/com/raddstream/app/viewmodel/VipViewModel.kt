package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.VipPendingSubmission
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.AccountEntitlement
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.sync.PaymentFiled
import com.raddstream.app.sync.Refusal
import com.raddstream.app.sync.SyncAccountRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import java.util.Locale
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The two plans the remote config prices. [days] is what a confirmed payment buys. */
enum class VipPlan(
    val storageName: String,
    /** The name the server's own price table sells this plan under (`payments.PLAN_DEFAULTS`). */
    val wireName: String,
    val label: String,
    val period: String,
    val days: Int,
) {
    MONTHLY("MONTHLY", "vip_monthly", "Monthly VIP", "30 days", 30),
    YEARLY("YEARLY", "vip_yearly", "Yearly VIP", "365 days", 365);

    companion object {
        /**
         * A plan name read back from storage or from the wire. Both forms have to work:
         * drafts written before this screen could talk to a server hold `MONTHLY`, and the
         * ledger's own rows hold `vip_monthly`. Unknown names answer [MONTHLY] because that is
         * what an unreadable plan costs, never because guessing a plan is acceptable.
         */
        fun fromStorage(name: String?): VipPlan {
            val key = name?.trim()?.uppercase(Locale.ROOT)
            return entries.firstOrNull {
                it.storageName == key || it.wireName == name?.trim()?.lowercase(Locale.ROOT)
            } ?: MONTHLY
        }

        /** Null for a name this build does not sell; the caller must not guess a plan. */
        fun fromWire(name: String?): VipPlan? = entries.firstOrNull { it.wireName == name }
    }
}

/**
 * The three payment channels the operator's guide names, in the order the server accepts
 * them (`payments.METHODS`). Each has its own reference shape on the server, which is why
 * the channel is part of a submission and not just a label beside one.
 */
enum class VipMethod(val wireName: String, val label: String) {
    JAZZCASH("jazzcash", "JazzCash"),
    EASYPAISA("easypaisa", "EasyPaisa"),
    RAAST("raast", "Raast");

    companion object {
        /** Null for a name this build does not sell: the caller must not guess a channel. */
        fun fromWire(name: String?): VipMethod? =
            entries.firstOrNull { it.wireName == name?.trim()?.lowercase(Locale.ROOT) }
    }
}

/**
 * The arithmetic and wording of the rewarded-ad pass. Pure functions with an explicit
 * clock, so the countdown can be unit-tested without waiting four hours.
 */
object RewardedVipPass {
    const val DEFAULT_HOURS = ServerSettingsRepository.DEFAULT_REWARDED_VIP_HOURS

    fun remainingMs(expiresAt: Long, now: Long = System.currentTimeMillis()): Long =
        (expiresAt - now).coerceAtLeast(0L)

    fun isActive(expiresAt: Long, now: Long = System.currentTimeMillis()): Boolean =
        remainingMs(expiresAt, now) > 0L

    /** `3h 59m 58s`, or `59m 58s` under an hour. Rounds up so it never shows 0s early. */
    fun formatRemaining(remainingMs: Long): String {
        val totalSeconds = (remainingMs.coerceAtLeast(0L) + 999L) / 1000L
        val hours = totalSeconds / 3600
        val minutes = (totalSeconds % 3600) / 60
        val seconds = totalSeconds % 60
        return if (hours > 0) "${hours}h ${minutes}m ${seconds}s" else "${minutes}m ${seconds}s"
    }

    /**
     * Whether this viewer may be shown a sponsor slot at all, from the two facts that can
     * silence one. Both promises are already on screen in words — the paid card says VIP is
     * what removes sponsor cards, the rewarded card says four hours ad-free — so honouring
     * either is keeping a sentence the app printed, and deciding it in two places is how one
     * of them drifts. A server capability — a higher rung behind the operator's quality gate,
     * a download marked VIP — is NOT decided here: only `vip` from the ledger can buy that,
     * and this function has no say over it.
     */
    fun isAdFree(
        serverVip: Boolean,
        rewardedExpiresAt: Long,
        now: Long = System.currentTimeMillis(),
    ): Boolean = serverVip || isActive(rewardedExpiresAt, now)
}

/**
 * The transaction reference a viewer copies out of a JazzCash / EasyPaisa / Raast
 * confirmation SMS. Validation is deliberately about SHAPE only — the app cannot know
 * whether a reference was actually paid, and pretending otherwise would be the same lie
 * as activating an account client-side.
 */
object VipTid {
    const val MIN_LENGTH = 6
    const val MAX_LENGTH = 24

    /** Spaces and dashes people paste from an SMS are noise; the letters are canonical. */
    fun normalize(raw: String): String =
        raw.filter { it.isLetterOrDigit() }.uppercase(Locale.ROOT)

    fun validationError(value: String): String? = when {
        value.isEmpty() ->
            "Enter the transaction ID from your payment confirmation."
        value.length < MIN_LENGTH ->
            "A transaction ID is at least $MIN_LENGTH characters."
        value.length > MAX_LENGTH ->
            "A transaction ID is at most $MAX_LENGTH characters."
        else -> null
    }

    fun isValid(value: String): Boolean = validationError(value) == null
}

data class VipUiState(
    val isLoading: Boolean = true,
    val loadError: String? = null,
    val currency: String = "PKR",
    val monthlyPkr: Int = VipViewModel.DEFAULT_MONTHLY_PKR,
    val yearlyPkr: Int = VipViewModel.DEFAULT_YEARLY_PKR,
    val jazzCashTillId: String = "",
    val jazzCashMobileAccount: String = "",
    val easyPaisaMobile: String = "",
    val raastInstantId: String = "",
    val selectedPlan: VipPlan = VipPlan.MONTHLY,
    val selectedMethod: VipMethod? = null,
    val transactionId: String = "",
    val tidError: String? = null,
    val pending: VipPendingSubmission? = null,
    val statusMessage: String? = null,
    val rewardedVipExpiresAt: Long = 0L,
    /** Whether this device holds a sync key — the only thing the ledger can attach a claim to. */
    val signedIn: Boolean = false,
    /** The server's own answer, or null while it has never been read on this device. */
    val entitlement: AccountEntitlement? = null,
    /** A submission is in flight, so the button cannot be pressed into a second claim. */
    val isSubmitting: Boolean = false,
) {
    fun priceFor(plan: VipPlan): Int =
        if (plan == VipPlan.MONTHLY) monthlyPkr else yearlyPkr

    /** A payment destination must exist before a reference can mean anything. */
    val hasPaymentHandle: Boolean
        get() = jazzCashTillId.isNotBlank() || jazzCashMobileAccount.isNotBlank() ||
            easyPaisaMobile.isNotBlank() || raastInstantId.isNotBlank()

    /** Submit is live only for a loaded screen that has somewhere to pay. */
    val canSubmit: Boolean
        get() = !isLoading && loadError == null && hasPaymentHandle &&
            pending == null && !isSubmitting

    /** The handle for one channel, blank when the operator has not published that one. */
    fun handleFor(method: VipMethod): String = when (method) {
        VipMethod.JAZZCASH -> listOf(jazzCashTillId, jazzCashMobileAccount)
            .firstOrNull { it.isNotBlank() }.orEmpty()
        VipMethod.EASYPAISA -> easyPaisaMobile
        VipMethod.RAAST -> raastInstantId
    }

    /** The channels this server can actually be paid through, in the guide's order. */
    val offeredMethods: List<VipMethod>
        get() = VipMethod.entries.filter { handleFor(it).isNotBlank() }

    /** Server-side membership only. A rewarded device pass is deliberately not VIP here. */
    val isVip: Boolean get() = entitlement?.vip == true

    /** When [AccountEntitlement.vipUntil] is in the future; otherwise no date is shown. */
    val vipUntilMillis: Long
        get() {
            val until = entitlement?.vipUntil ?: return 0L
            return if (until > 0.0) (until * 1000.0).toLong() else 0L
        }
}

@HiltViewModel
class VipViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
    private val settingsRepository: ServerSettingsRepository,
    private val syncAccountRepository: SyncAccountRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(VipUiState())
    val uiState = _uiState.asStateFlow()

    init {
        observePending()
        observeRewardedVip()
        observeAccount()
        loadConfig()
    }

    private fun observePending() {
        viewModelScope.launch {
            settingsRepository.vipPendingSubmission.collect { pending ->
                _uiState.update { it.copy(pending = pending) }
            }
        }
    }

    private fun observeRewardedVip() {
        viewModelScope.launch {
            settingsRepository.rewardedVipExpiresAt.collect { expiresAt ->
                _uiState.update { it.copy(rewardedVipExpiresAt = expiresAt) }
            }
        }
    }

    /**
     * The account this app talks to, and what that account is entitled to. Both are pushed,
     * not polled here: [SyncAccountRepository] refreshes at launch and on its own interval,
     * so opening this screen only has to ask for a fresh read once, not own a timer.
     */
    private fun observeAccount() {
        viewModelScope.launch {
            syncAccountRepository.signedIn.collect { signed ->
                _uiState.update { it.copy(signedIn = signed) }
            }
        }
        viewModelScope.launch {
            syncAccountRepository.entitlement.collect { earned ->
                _uiState.update { it.copy(entitlement = earned) }
            }
        }
        viewModelScope.launch {
            syncAccountRepository.refreshEntitlement()
        }
    }

    /**
     * Called when a rewarded ad reports completion. The pass is stored on this device
     * only; no server entitlement is implied, and the card says so. Watching again
     * while a pass is live extends it rather than restarting the four hours.
     */
    fun grantRewardedVip(hours: Int = RewardedVipPass.DEFAULT_HOURS) {
        val safeHours = hours.coerceIn(1, ServerSettingsRepository.MAX_REWARDED_VIP_HOURS)
        viewModelScope.launch {
            settingsRepository.grantRewardedVip(safeHours)
            _uiState.update {
                it.copy(statusMessage = "$safeHours-hour VIP pass activated on this device.")
            }
        }
    }

    /** The state the screen renders, evaluated against the current wall clock. */
    fun isRewardedVipActive(now: Long = System.currentTimeMillis()): Boolean =
        RewardedVipPass.isActive(_uiState.value.rewardedVipExpiresAt, now)

    /** Fetches live prices and handles. A failure keeps the quoted defaults and offers retry. */
    fun loadConfig() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, loadError = null) }
            try {
                val config = catalogRepository.getRemoteConfig()
                if (!config.success) {
                    _uiState.update {
                        it.copy(isLoading = false, loadError = "Payment details are unavailable right now.")
                    }
                    return@launch
                }
                _uiState.update { current -> current.withConfig(config) }
                resubmitStoredDraft()
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        loadError = friendlyNetworkError(ex, "Could not load payment details."),
                    )
                }
            }
        }
    }

    /**
     * A reference kept on this device that never reached the ledger is the one case where
     * local persistence is not a lie: it says "this was typed and it was not sent". So the
     * next load that can reach the server files it, and a claim the server already holds
     * clears the draft instead of duplicating it.
     */
    private suspend fun resubmitStoredDraft() {
        val current = _uiState.value
        val draft = current.pending ?: return
        if (!current.signedIn) return
        val method = VipMethod.fromWire(draft.method) ?: return
        val plan = VipPlan.fromWire(draft.plan) ?: return
        if (current.entitlement?.pending == true) {
            // The operator's queue already has this claim; the draft is a filing that landed
            // while the app was dying. Keep the one copy that has a receipt behind it.
            settingsRepository.clearVipPendingSubmission()
            return
        }
        _uiState.update { it.copy(isSubmitting = true) }
        val filed = syncAccountRepository.submitPayment(plan.wireName, method.wireName, draft.transactionId)
        _uiState.update { it.copy(isSubmitting = false) }
        if (filed is PaymentFiled.Accepted) {
            settingsRepository.clearVipPendingSubmission()
            _uiState.update { it.copy(statusMessage = VipSubmission.outcome(filed).message) }
        }
    }

    fun selectPlan(plan: VipPlan) {
        _uiState.update { it.copy(selectedPlan = plan) }
    }

    fun selectMethod(method: VipMethod) {
        _uiState.update { it.copy(selectedMethod = method, tidError = null) }
    }

    fun onTransactionIdChanged(value: String) {
        _uiState.update { it.copy(transactionId = value, tidError = null) }
    }

    /**
     * Send the reference to the operator's ledger.
     *
     * The claim goes to the server, which stores it as `pending` beside the price IT charges
     * for that plan; nothing here flips a VIP flag, and a reference the server refuses is not
     * quietly kept as a "success" on the device. Only an unreachable server leaves a draft
     * behind, and the message says which of those happened.
     */
    fun submitTransaction() {
        val current = _uiState.value
        val tid = VipTid.normalize(current.transactionId)
        val error = VipTid.validationError(tid)
        if (error != null) {
            _uiState.update { it.copy(tidError = error) }
            return
        }
        if (!current.canSubmit) return
        val method = current.selectedMethod ?: current.offeredMethods.firstOrNull()
        if (method == null) {
            _uiState.update { it.copy(statusMessage = "The operator has not published a payment account yet.") }
            return
        }
        val plan = current.selectedPlan
        viewModelScope.launch {
            if (!current.signedIn) {
                // The ledger keys a claim to an account, so a signed-out submission has
                // nowhere to arrive. Keeping the reference here is not a fake success: the
                // message says it was not sent, and the next load files it once there is a key.
                settingsRepository.saveVipPendingSubmission(
                    draftOf(current, plan, method, tid),
                )
                _uiState.update {
                    it.copy(
                        transactionId = "",
                        tidError = null,
                        statusMessage = VipSubmission.outcome(PaymentFiled.Refused(Refusal.SIGNED_OUT)).message,
                    )
                }
                return@launch
            }
            _uiState.update { it.copy(isSubmitting = true) }
            val filed = syncAccountRepository.submitPayment(plan.wireName, method.wireName, tid)
            val outcome = VipSubmission.outcome(filed)
            _uiState.update { it.copy(isSubmitting = false) }
            if (filed is PaymentFiled.Accepted) {
                settingsRepository.clearVipPendingSubmission()
            } else if (outcome.keepDraft) {
                settingsRepository.saveVipPendingSubmission(draftOf(current, plan, method, tid))
            }
            _uiState.update {
                it.copy(
                    transactionId = if (outcome.clearField) "" else it.transactionId,
                    tidError = outcome.tidError,
                    statusMessage = outcome.message,
                )
            }
            syncAccountRepository.refreshEntitlement(force = filed is PaymentFiled.Accepted)
        }
    }

    fun cancelPending() {
        viewModelScope.launch {
            settingsRepository.clearVipPendingSubmission()
            _uiState.update {
                it.copy(statusMessage = "Verification request removed from this device.")
            }
        }
    }

    fun clearStatus() {
        _uiState.update { it.copy(statusMessage = null) }
    }

    /** Re-run the remote-config fetch after a transient failure. */
    fun retry() = loadConfig()

    private fun draftOf(
        current: VipUiState,
        plan: VipPlan,
        method: VipMethod,
        tid: String,
    ) = VipPendingSubmission(
        transactionId = tid,
        plan = plan.wireName,
        method = method.wireName,
        amountPkr = current.priceFor(plan),
        submittedAt = System.currentTimeMillis(),
    )

    companion object {
        /** The prices the operator specification ships; the server may price them differently. */
        const val DEFAULT_MONTHLY_PKR = 200
        const val DEFAULT_YEARLY_PKR = 1_500
    }
}

/**
 * The one sentence each filing attempt deserves, decided apart from the ViewModel so it can
 * be tested without a network, a Hilt graph or a device.
 *
 * [keepDraft] is the whole difference between a failure that loses a reference and one that
 * does not: an unreachable server keeps what the viewer typed, everything else does not,
 * because a draft that survives a refusal invites a resubmit of a claim the operator already
 * has in front of them.
 */
object VipSubmission {
    data class Outcome(
        val message: String,
        val keepDraft: Boolean,
        val clearField: Boolean,
        val tidError: String? = null,
    )

    fun outcome(filed: PaymentFiled): Outcome = when (filed) {
        is PaymentFiled.Accepted -> Outcome(
            message = "Reference filed. The operator confirms the payment, then VIP turns on " +
                "by itself — no reinstall and nothing to send again.",
            keepDraft = false,
            clearField = true,
        )
        is PaymentFiled.Refused -> when (filed.reason) {
            Refusal.OFFLINE, Refusal.NO_SERVER -> Outcome(
                message = "Could not reach the server, so the reference was kept on this device and " +
                    "will be sent again when you are online.",
                keepDraft = true,
                clearField = true,
            )
            Refusal.REJECTED, Refusal.WEAK_KEY -> Outcome(
                message = "The server did not accept that reference for the channel you chose. " +
                    "Check the transaction ID in your confirmation SMS and send it again.",
                keepDraft = false,
                clearField = false,
                tidError = "That reference does not match this channel's format.",
            )
            Refusal.THROTTLED -> Outcome(
                message = "A reference was already filed for this account a moment ago. Wait a few " +
                    "minutes before sending another.",
                keepDraft = false,
                clearField = true,
            )
            Refusal.SIGNED_OUT -> Outcome(
                message = "Sign in on the Settings tab first: the operator attaches a reference to " +
                    "your account, and this device has no account to attach it to. The reference is " +
                    "kept here and sent once you are signed in.",
                keepDraft = true,
                clearField = true,
            )
        }
    }
}

/**
 * Fold the wire body into state. A price of zero means the operator never set one, so the
 * documented PKR defaults stand rather than printing a free plan.
 */
private fun VipUiState.withConfig(config: VipRemoteConfig): VipUiState {
    val folded = copy(
        isLoading = false,
        loadError = null,
        currency = config.currency.trim().ifBlank { "PKR" },
        monthlyPkr = config.vip.monthlyPkr.takeIf { it > 0 } ?: VipViewModel.DEFAULT_MONTHLY_PKR,
        yearlyPkr = config.vip.yearlyPkr.takeIf { it > 0 } ?: VipViewModel.DEFAULT_YEARLY_PKR,
        jazzCashTillId = config.payments.jazzcash.tillId.trim(),
        jazzCashMobileAccount = config.payments.jazzcash.mobileAccount.trim(),
        easyPaisaMobile = config.payments.easypaisa.mobileNumber.trim(),
        raastInstantId = config.payments.raast.instantId.trim(),
    )
    // A channel the viewer already picked stays picked; otherwise the first one the
    // operator actually published is chosen, so a submission never names a channel that
    // has no account behind it.
    val stillOffered = selectedMethod?.takeIf { folded.handleFor(it).isNotBlank() }
    return folded.copy(selectedMethod = stillOffered ?: folded.offeredMethods.firstOrNull())
}
