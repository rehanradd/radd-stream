package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.Telemetry
import com.raddstream.app.data.VipPendingSubmission
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.AccountEntitlement
import com.raddstream.app.network.models.DownloadCreditPrice
import com.raddstream.app.network.models.PassTier
import com.raddstream.app.ui.theme.PlayerChromeTheme
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.network.models.VipRemoteStreak
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
    val monthlyPkr: Int = VipViewModel.NO_PRICE_PUBLISHED,
    val yearlyPkr: Int = VipViewModel.NO_PRICE_PUBLISHED,
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
    /** The operator's streak plan (enabled, target days, reward coins) — parsed, never a promise. */
    val streak: VipRemoteStreak = VipRemoteStreak(),
    /** Consecutive days this device opened the app, counted locally (MainActivity records it). */
    val streakCount: Int = 0,
    /** This account's coin balance, read from the ledger — never invented here. */
    val coinBalance: Int = 0,
    /** The streak ladder the server will pay (day -> coins), empty until read. */
    val streakLadder: Map<Int, Int> = emptyMap(),
    /** The pass catalog the server publishes (plan -> coin price), empty until read. */
    val passCatalog: Map<String, PassTier> = emptyMap(),
    /** The player themes the server publishes (theme -> coin price), empty until read. */
    val themeCatalog: Map<String, DownloadCreditPrice> = emptyMap(),
    /** The movie-request price the server publishes (coins for one title), 0 until read. */
    val requestPrice: Int = 0,
    /** The player themes this account owns, always including `jade` (the shipped look). */
    val ownedThemes: List<String> = emptyList(),
    /** The player chrome theme this device wears — the pick, not the purchase. */
    val selectedTheme: String = PlayerChromeTheme.JADE,
    /** The last claim's answer in the viewer's own words, or null before any claim. */
    val claimMessage: String? = null,
    /** A claim is in flight, so the button cannot be pressed into a second claim. */
    val isClaiming: Boolean = false,
    /** Today is already claimed (paid or already-claimed answer), so the button rests. */
    val claimedToday: Boolean = false,
    /** The last redeem's answer in the viewer's own words, or null before any redeem. */
    val redeemMessage: String? = null,
    /** A redeem is in flight, so the button cannot be pressed into a second redeem. */
    val isRedeeming: Boolean = false,
    /** The last movie-request answer in the viewer's own words, or null before any request. */
    val requestMessage: String? = null,
    /** A request is in flight, so the button cannot be pressed into a second request. */
    val isRequesting: Boolean = false,
    /** The last theme purchase's answer in the viewer's own words, or null before any purchase. */
    val themeMessage: String? = null,
    /** A theme purchase is in flight, so the button cannot be pressed into a second purchase. */
    val isBuyingTheme: Boolean = false,
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
        observeStreak()
        observeAccount()
        observeTheme()
        loadConfig()
        loadWallet()
    }

    /** The chrome theme this device wears, collected so a pick on this screen reaches the player. */
    private fun observeTheme() {
        viewModelScope.launch {
            settingsRepository.playerTheme.collect { theme ->
                _uiState.update { it.copy(selectedTheme = theme) }
            }
        }
    }

    /** The wallet, the ladder and the pass catalog, read once the account is known. */
    private fun loadWallet() {
        viewModelScope.launch {
            val ladder = syncAccountRepository.loadStreakLadder()
            val catalog = syncAccountRepository.loadPassCatalog()
            val themes = syncAccountRepository.loadThemeCatalog()
            val requestPrice = syncAccountRepository.loadRequestPrice()
            val owned = syncAccountRepository.loadCoinThemes()
            val balance = syncAccountRepository.loadCoinBalance()
            _uiState.update {
                it.copy(
                    streakLadder = ladder.ifEmpty { it.streakLadder },
                    passCatalog = catalog.ifEmpty { it.passCatalog },
                    themeCatalog = themes.ifEmpty { it.themeCatalog },
                    requestPrice = if (requestPrice > 0) requestPrice else it.requestPrice,
                    ownedThemes = owned?.themes?.ifEmpty { it.ownedThemes } ?: it.ownedThemes,
                    coinBalance = balance ?: it.coinBalance,
                )
            }
        }
    }

    /**
     * Claim today's check-in. The server decides the grant: a fresh day pays the
     * ladder's coins for the new streak day, a second claim the same day pays nothing,
     * and an unreachable server is reported as exactly that — never as "already claimed".
     */
    fun claimDailyLogin() {
        val state = _uiState.value
        if (!state.signedIn || state.isClaiming || state.claimedToday) return
        viewModelScope.launch {
            _uiState.update { it.copy(isClaiming = true, claimMessage = null) }
            try {
                val earned = syncAccountRepository.claimDailyLogin()
                if (earned == null) {
                    _uiState.update {
                        it.copy(claimMessage = "Could not reach the server — try again later.")
                    }
                    return@launch
                }
                val balance = syncAccountRepository.loadCoinBalance()
                _uiState.update {
                    it.copy(
                        claimedToday = true,
                        coinBalance = balance ?: it.coinBalance,
                        claimMessage = when {
                            earned.status == "same_day_noop" -> "Already claimed today."
                            earned.currentStreak > 7 ->
                                "Streak day ${earned.currentStreak} — the 7-day ladder is complete."
                            earned.pass != null ->
                                "+${earned.coinsGranted} coins — Day ${earned.currentStreak} of 7, and a 24-hour pass."
                            earned.coinsGranted > 0 ->
                                "+${earned.coinsGranted} coins — Day ${earned.currentStreak} of 7."
                            else -> "Day ${earned.currentStreak} of 7."
                        },
                    )
                }
            } finally {
                _uiState.update { it.copy(isClaiming = false) }
            }
        }
    }

    /**
     * Spend coins on a VIP pass. The server decides the price and the debit; the
     * button is already guarded by the wallet the screen shows, so a refusal here
     * is a race, not a price the viewer was shown. A successful redeem refreshes
     * the entitlement, so the screen shows VIP at once instead of on the next launch.
     */
    fun redeemPass(plan: String) {
        val state = _uiState.value
        if (!state.signedIn || state.isRedeeming) return
        val cost = state.passCatalog[plan]?.coins ?: return
        viewModelScope.launch {
            if (state.coinBalance < cost) {
                _uiState.update {
                    it.copy(redeemMessage = "Not enough coins yet — keep checking in.")
                }
                return@launch
            }
            _uiState.update { it.copy(isRedeeming = true, redeemMessage = null) }
            try {
                val redeemed = syncAccountRepository.redeemPass(plan)
                if (redeemed == null) {
                    _uiState.update {
                        it.copy(redeemMessage = "Could not reach the server — try again later.")
                    }
                    return@launch
                }
                val balance = syncAccountRepository.loadCoinBalance()
                syncAccountRepository.refreshEntitlement(force = true)
                _uiState.update {
                    it.copy(
                        coinBalance = balance ?: it.coinBalance,
                        redeemMessage = when {
                            redeemed.alreadyApplied -> "You already have this pass."
                            else -> "VIP pass active for ${passDurationLabel(plan)} — ${redeemed.cost} coins."
                        },
                    )
                }
            } finally {
                _uiState.update { it.copy(isRedeeming = false) }
            }
        }
    }

    /**
     * Spend coins on one requested movie. The server decides the price and the
     * debit and queues the title for the operator; a replay answers
     * `already_applied` with the request it already filed, so a double tap
     * files one request, not two.
     */
    fun requestMovie(title: String) {
        val state = _uiState.value
        if (!state.signedIn || state.isRequesting) return
        val cost = state.requestPrice
        if (cost <= 0) return
        viewModelScope.launch {
            val clean = title.trim()
            if (clean.isEmpty()) {
                _uiState.update { it.copy(requestMessage = "Type the movie's name first.") }
                return@launch
            }
            if (state.coinBalance < cost) {
                _uiState.update { it.copy(requestMessage = "Not enough coins yet — keep checking in.") }
                return@launch
            }
            _uiState.update { it.copy(isRequesting = true, requestMessage = null) }
            try {
                val requested = syncAccountRepository.requestMovie(clean)
                if (requested == null) {
                    _uiState.update {
                        it.copy(requestMessage = "Could not reach the server — try again later.")
                    }
                    return@launch
                }
                val balance = syncAccountRepository.loadCoinBalance()
                _uiState.update {
                    it.copy(
                        coinBalance = balance ?: it.coinBalance,
                        requestMessage = if (requested.alreadyApplied) {
                            "That request is already in — no coins spent twice."
                        } else {
                            "Requested — ${requested.cost} coins. The team will look for it."
                        },
                    )
                }
            } finally {
                _uiState.update { it.copy(isRequesting = false) }
            }
        }
    }

    /**
     * Buy one player theme and wear it at once. A theme already owned costs
     * nothing — the route answers `already_applied` and no spend runs — and
     * wearing it is a local pick the player reads from the stored setting.
     */
    fun buyTheme(theme: String) {
        val state = _uiState.value
        if (!state.signedIn || state.isBuyingTheme) return
        if (theme !in PlayerChromeTheme.IDS || theme == PlayerChromeTheme.JADE) return
        val cost = state.themeCatalog[theme]?.coins ?: return
        viewModelScope.launch {
            if (theme in state.ownedThemes) {
                settingsRepository.savePlayerTheme(theme)
                _uiState.update {
                    it.copy(selectedTheme = theme, themeMessage = "Wearing ${themeLabel(theme)}.")
                }
                return@launch
            }
            if (state.coinBalance < cost) {
                _uiState.update { it.copy(themeMessage = "Not enough coins yet — keep checking in.") }
                return@launch
            }
            _uiState.update { it.copy(isBuyingTheme = true, themeMessage = null) }
            try {
                val bought = syncAccountRepository.redeemTheme(theme)
                if (bought == null) {
                    _uiState.update {
                        it.copy(themeMessage = "Could not reach the server — try again later.")
                    }
                    return@launch
                }
                val balance = syncAccountRepository.loadCoinBalance()
                settingsRepository.savePlayerTheme(theme)
                _uiState.update {
                    it.copy(
                        coinBalance = balance ?: it.coinBalance,
                        ownedThemes = bought.owned.ifEmpty { it.ownedThemes },
                        selectedTheme = theme,
                        themeMessage = if (bought.alreadyApplied) {
                            "You already own ${themeLabel(theme)}."
                        } else {
                            "${themeLabel(theme)} is yours — ${bought.cost} coins."
                        },
                    )
                }
            } finally {
                _uiState.update { it.copy(isBuyingTheme = false) }
            }
        }
    }

    /** Wear a theme this account already owns, without buying anything. */
    fun selectTheme(theme: String) {
        val state = _uiState.value
        if (!state.signedIn || theme !in PlayerChromeTheme.IDS) return
        if (theme !in state.ownedThemes && theme != PlayerChromeTheme.JADE) return
        viewModelScope.launch {
            settingsRepository.savePlayerTheme(theme)
            _uiState.update { it.copy(selectedTheme = theme, themeMessage = null) }
        }
    }

    /** A theme id in the viewer's words: the names are the server's. */
    private fun themeLabel(theme: String): String = when (theme) {
        PlayerChromeTheme.MIDNIGHT -> "Midnight"
        PlayerChromeTheme.EMBER -> "Ember"
        else -> "Jade"
    }

    /** What a pass tier buys, in the viewer's words: the plan names are the server's. */
    private fun passDurationLabel(plan: String): String = when (plan) {
        "day" -> "24 hours"
        "weekend" -> "the weekend"
        "monthly_vip" -> "30 days"
        else -> "its full length"
    }

    /**
     * The login streak (plan §5 step 19): consecutive days this device opened the app, counted
     * locally by MainActivity. This screen only reads the count — it never writes it — so a
     * streak is never earned by opening the VIP screen itself.
     */
    private fun observeStreak() {
        viewModelScope.launch {
            settingsRepository.loginStreakCount.collect { count ->
                _uiState.update { it.copy(streakCount = count) }
            }
        }
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
                if (signed) loadWallet()
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
            // Tracking A: the ad was watched and the pass granted — one
            // rewarded completion, counted. The server grants no coins on
            // this (that needs a network postback, which Monetag has not
            // confirmed for native Android); it only counts the completion.
            Telemetry.recordRewardedCompletion()
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
                // A degraded body is a shape guarantee, not the operator's
                // decision: its prices and payment handles are shipped
                // defaults. Showing them would quote a price the operator did
                // not set — keep the quoted defaults and say so instead.
                if (config.settingsUnavailable) {
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
        /**
         * This client ships no price. It used to carry PKR 200 monthly and PKR 1,500 yearly as a
         * fallback for a server that published neither, which quietly made the app the authority on
         * what a membership costs — and the server had already moved on (the monthly plan is
         * PKR 250 today). A number that can only be wrong in silence is not a fallback, so the
         * absence is now what the state holds, and `amountLabel` says so out loud.
         */
        const val NO_PRICE_PUBLISHED = 0
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
 * Fold the wire body into state. A price of zero means the operator never set one, and nothing
 * here replaces it: the server prices the plan (`payments.submit_payment` looks the amount up and
 * refuses a body that carries one), so a number this screen invented would be a quote nobody
 * authorized. An unpublished price renders as the words "Not published by the server", not as a
 * figure.
 */
private fun VipUiState.withConfig(config: VipRemoteConfig): VipUiState {
    val folded = copy(
        isLoading = false,
        loadError = null,
        currency = config.currency.trim().ifBlank { "PKR" },
        monthlyPkr = config.vip.monthlyPkr.takeIf { it > 0 } ?: VipViewModel.NO_PRICE_PUBLISHED,
        yearlyPkr = config.vip.yearlyPkr.takeIf { it > 0 } ?: VipViewModel.NO_PRICE_PUBLISHED,
        jazzCashTillId = config.payments.jazzcash.tillId.trim(),
        jazzCashMobileAccount = config.payments.jazzcash.mobileAccount.trim(),
        easyPaisaMobile = config.payments.easypaisa.mobileNumber.trim(),
        raastInstantId = config.payments.raast.instantId.trim(),
        streak = config.streak,
    )
    // A channel the viewer already picked stays picked; otherwise the first one the
    // operator actually published is chosen, so a submission never names a channel that
    // has no account behind it.
    val stillOffered = selectedMethod?.takeIf { folded.handleFor(it).isNotBlank() }
    return folded.copy(selectedMethod = stillOffered ?: folded.offeredMethods.firstOrNull())
}
