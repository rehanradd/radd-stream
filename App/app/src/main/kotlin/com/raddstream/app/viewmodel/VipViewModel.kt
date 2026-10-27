package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.VipPendingSubmission
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import java.util.Locale
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The two plans the remote config prices. [days] is what a confirmed payment buys. */
enum class VipPlan(val storageName: String, val label: String, val period: String, val days: Int) {
    MONTHLY("MONTHLY", "Monthly VIP", "30 days", 30),
    YEARLY("YEARLY", "Yearly VIP", "365 days", 365);

    companion object {
        fun fromStorage(name: String?): VipPlan =
            entries.firstOrNull { it.storageName == name } ?: MONTHLY
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
    val transactionId: String = "",
    val tidError: String? = null,
    val pending: VipPendingSubmission? = null,
    val statusMessage: String? = null,
    val rewardedVipExpiresAt: Long = 0L,
) {
    fun priceFor(plan: VipPlan): Int =
        if (plan == VipPlan.MONTHLY) monthlyPkr else yearlyPkr

    /** A payment destination must exist before a reference can mean anything. */
    val hasPaymentHandle: Boolean
        get() = jazzCashTillId.isNotBlank() || jazzCashMobileAccount.isNotBlank() ||
            easyPaisaMobile.isNotBlank() || raastInstantId.isNotBlank()

    /** Submit is live only for a loaded screen that has somewhere to pay. */
    val canSubmit: Boolean
        get() = !isLoading && loadError == null && hasPaymentHandle && pending == null
}

@HiltViewModel
class VipViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
    private val settingsRepository: ServerSettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(VipUiState())
    val uiState = _uiState.asStateFlow()

    init {
        observePending()
        observeRewardedVip()
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

    fun selectPlan(plan: VipPlan) {
        _uiState.update { it.copy(selectedPlan = plan) }
    }

    fun onTransactionIdChanged(value: String) {
        _uiState.update { it.copy(transactionId = value, tidError = null) }
    }

    /**
     * Keep the reference for verification. There is no payment-collection endpoint on this
     * server, so the app neither POSTs it nor flips a VIP flag: it stores the reference
     * beside the plan and amount it was quoted for and reports the state as pending.
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
        viewModelScope.launch {
            val submission = VipPendingSubmission(
                transactionId = tid,
                plan = current.selectedPlan.storageName,
                amountPkr = current.priceFor(current.selectedPlan),
                submittedAt = System.currentTimeMillis(),
            )
            settingsRepository.saveVipPendingSubmission(submission)
            _uiState.update {
                it.copy(
                    transactionId = "",
                    tidError = null,
                    statusMessage = "Reference saved on this device. Keep it for follow-up with the operator.",
                )
            }
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

    companion object {
        /** The prices the operator specification ships; the server may price them differently. */
        const val DEFAULT_MONTHLY_PKR = 200
        const val DEFAULT_YEARLY_PKR = 1_500
    }
}

/**
 * Fold the wire body into state. A price of zero means the operator never set one, so the
 * documented PKR defaults stand rather than printing a free plan.
 */
private fun VipUiState.withConfig(config: VipRemoteConfig): VipUiState = copy(
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
