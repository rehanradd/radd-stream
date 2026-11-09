package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.models.AccountEntitlement
import com.raddstream.app.network.models.CoinLedgerEntry
import com.raddstream.app.network.models.PassTier
import com.raddstream.app.sync.SyncAccountRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Whether the server's `last_counted_day` is today, in the streak's own
 * terms: the civil day of (now minus the boundary hour) in the streak's
 * timezone. The server counts a day from 04:00 PKT, so 02:00 on day D still
 * belongs to D-1 and 05:00 belongs to D — the same rule `engagement.py`
 * `_day_bucket` enforces, restated here so the check-in screen can read
 * "already claimed" from the overview without spending a claim to learn it.
 * A null or blank last day is never claimed; an unreadable timezone falls
 * back to the streak's own default, Asia/Karachi.
 */
fun claimedTodayFor(
    lastCountedDay: String?,
    tz: String,
    boundaryHour: Int,
    nowMillis: Long,
): Boolean {
    if (lastCountedDay.isNullOrBlank()) return false
    val zone = try {
        ZoneId.of(tz)
    } catch (_: Exception) {
        ZoneId.of("Asia/Karachi")
    }
    val hour = boundaryHour.coerceIn(0, 23)
    val today = LocalDateTime.ofInstant(Instant.ofEpochMilli(nowMillis), zone)
        .minusHours(hour.toLong()).toLocalDate()
    return lastCountedDay == today.toString()
}

/**
 * Everything the account screens show, in one state. Session 123: the app
 * had no profile, no dashboard, no standalone check-in and no coin screen —
 * the check-in lived only inside the VIP screen, and the wallet could only
 * be read by claiming a day. These screens read what the server already
 * publishes (`overview`, `coins/caps`, `coins/history`, `entitlement`,
 * `account`) and write nothing except through the ledger's own claim and
 * redeem calls. The balance is the ledger's `SUM(delta)`; the streak is the
 * server's count, not the device's local open-count.
 */
data class AccountUiState(
    val isLoading: Boolean = false,
    val signedIn: Boolean = false,
    val loadError: String? = null,
    /** This account's coin balance, read from the ledger — never invented here. */
    val coinBalance: Int = 0,
    /** Consecutive claimed days, from the server — not the device's open-count. */
    val currentStreak: Int = 0,
    val bestStreak: Int = 0,
    /** The civil day the last claim counted for, or null when never claimed. */
    val lastCountedDay: String? = null,
    /** The streak ladder the server will pay (day -> coins), empty until read. */
    val streakLadder: Map<Int, Int> = emptyMap(),
    /** The pass catalog the server publishes (plan -> coin price), empty until read. */
    val passCatalog: Map<String, PassTier> = emptyMap(),
    /** The account's own ledger rows, newest first — empty until read. */
    val history: List<CoinLedgerEntry> = emptyList(),
    /** True when the server says this account holds a live membership. */
    val isVip: Boolean = false,
    /** The membership's end, on the server's clock (epoch seconds). */
    val vipUntil: Double = 0.0,
    /** When this account was created, on the server's clock — null when unread. */
    val createdAt: Double? = null,
    val lastSeenAt: Double? = null,
    /** The last claim's answer in the viewer's own words, or null before any claim. */
    val claimMessage: String? = null,
    /** A claim is in flight, so the button cannot be pressed into a second claim. */
    val isClaiming: Boolean = false,
    /** Today is already claimed (paid or already-claimed answer), so the button rests. */
    val claimedToday: Boolean = false,
    /** The last redeem's answer in the viewer's own words, or null before any redeem. */
    val redeemMessage: String? = null,
    /** The plan a redeem is in flight for, or null when none is. */
    val redeemingPlan: String? = null,
)

@HiltViewModel
class AccountViewModel @Inject constructor(
    private val syncAccountRepository: SyncAccountRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(AccountUiState())
    val uiState = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            syncAccountRepository.signedIn.collect { signedIn ->
                _uiState.update { it.copy(signedIn = signedIn) }
                // A guest has nothing to read, so the screens must not sit
                // on "loading" forever waiting for a read that never comes.
                if (signedIn) refresh() else _uiState.update { it.copy(isLoading = false) }
            }
        }
    }

    /** One read of everything the account screens show. A failure leaves the last good values standing and says so, never zeroes them. */
    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, loadError = null) }
            try {
                val overview = syncAccountRepository.loadAccountOverview()
                val ladder = syncAccountRepository.loadStreakLadder()
                val catalog = syncAccountRepository.loadPassCatalog()
                val history = syncAccountRepository.loadCoinHistory()
                val entitlement: AccountEntitlement? = syncAccountRepository.refreshEntitlement()
                val info = syncAccountRepository.loadAccountInfo()
                val now = System.currentTimeMillis()
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        coinBalance = overview?.balance ?: it.coinBalance,
                        currentStreak = overview?.streak?.currentStreak ?: it.currentStreak,
                        bestStreak = overview?.streak?.bestStreak ?: it.bestStreak,
                        lastCountedDay = overview?.streak?.lastCountedDay ?: it.lastCountedDay,
                        claimedToday = if (overview != null) {
                            claimedTodayFor(
                                overview.streak.lastCountedDay,
                                overview.streak.tz,
                                overview.streak.dayBoundaryHour,
                                now,
                            )
                        } else {
                            it.claimedToday
                        },
                        streakLadder = ladder.ifEmpty { it.streakLadder },
                        passCatalog = catalog.ifEmpty { it.passCatalog },
                        history = history.ifEmpty { it.history },
                        isVip = entitlement?.vip ?: it.isVip,
                        vipUntil = entitlement?.vipUntil ?: it.vipUntil,
                        createdAt = info?.createdAt ?: it.createdAt,
                        lastSeenAt = info?.lastSeenAt ?: it.lastSeenAt,
                    )
                }
            } catch (_: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        loadError = "Could not reach the server — showing what was last read.",
                    )
                }
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
                val overview = syncAccountRepository.loadAccountOverview()
                _uiState.update {
                    it.copy(
                        claimedToday = true,
                        coinBalance = overview?.balance ?: it.coinBalance,
                        currentStreak = earned.currentStreak,
                        bestStreak = earned.bestStreak,
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
     * is reported in the viewer's own words and the balance is re-read either way.
     */
    fun redeemPass(plan: String) {
        val state = _uiState.value
        if (!state.signedIn || state.redeemingPlan != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(redeemingPlan = plan, redeemMessage = null) }
            try {
                val redeemed = syncAccountRepository.redeemPass(plan)
                val overview = syncAccountRepository.loadAccountOverview()
                val entitlement = syncAccountRepository.refreshEntitlement(force = true)
                _uiState.update {
                    it.copy(
                        coinBalance = overview?.balance ?: it.coinBalance,
                        isVip = entitlement?.vip ?: it.isVip,
                        vipUntil = entitlement?.vipUntil ?: it.vipUntil,
                        redeemMessage = when {
                            redeemed == null -> "Could not reach the server — no coins were spent."
                            redeemed.alreadyApplied -> "Already applied — no coins were spent twice."
                            else -> "Pass active — ${redeemed.cost} coins for ${redeemed.reward}."
                        },
                    )
                }
            } finally {
                _uiState.update { it.copy(redeemingPlan = null) }
            }
        }
    }

    /** Sign out on this device: the key is dropped locally and the server is told to revoke it. */
    fun signOut() {
        viewModelScope.launch {
            syncAccountRepository.signOut()
            _uiState.update {
                AccountUiState(signedIn = false)
            }
        }
    }
}
