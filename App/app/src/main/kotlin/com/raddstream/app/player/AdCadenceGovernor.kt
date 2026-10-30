package com.raddstream.app.player

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.local.AdCadenceDao
import com.raddstream.app.data.local.AdCadenceRows
import com.raddstream.app.network.models.VipRemoteAds
import com.raddstream.app.network.models.VipRemoteEngagement
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first

/**
 * The operator's ad switch, read from wherever the app keeps it.
 *
 * A seam rather than a direct [com.raddstream.app.data.ServerSettingsRepository] dependency for
 * one reason: the governor is the class that decides whether a viewer sees an ad, and a decision
 * that cannot be driven from a JVM test is a decision that has not been tested. The production
 * binding reads DataStore, where the remote-config watcher mirrors the body's `ads_enabled`; the
 * test binding is a boolean. A binding is allowed to fail — a torn preferences file throws — and
 * [AdCadenceGovernor] is what turns any failure into a refusal, so no future binding can be the
 * reason an ad shows when nobody could read the switch.
 */
interface AdSwitch {
    suspend fun adsEnabled(): Boolean
}

/** The production binding: the mirrored operator switch, read once per ask. */
class DataStoreAdSwitch @Inject constructor(
    private val settings: ServerSettingsRepository,
) : AdSwitch {
    override suspend fun adsEnabled(): Boolean = settings.adsEnabled.first()
}

/**
 * The one owner of "may this viewer see an ad, and when did they last see one".
 *
 * Three things make this a class rather than a call site: the caps come from the operator's body
 * and default to the shipped numbers when it says nothing, the timestamps live in Room so a killed
 * process does not buy the viewer a fresh pre-roll, and every refusal is the same answer as every
 * other refusal — [AdDecision.None], which renders nothing. A surface cannot tell "not due yet"
 * from "the switch is off" from "no network filled this", and that is deliberate: the only thing a
 * caller can do with those three is show something, and showing something is exactly what the
 * owner ruled out.
 *
 * The impression is recorded inside [offer], not handed back for the caller to record. A cap an
 * ad SDK can forget to log is not a cap.
 */
@Singleton
class AdCadenceGovernor @Inject constructor(
    private val dao: AdCadenceDao,
    private val clock: AdWallClock,
    private val inventory: AdInventory,
    private val switch: AdSwitch,
) {

    private val _state = MutableStateFlow(AdCadenceState())

    /** Read-only view of the cadence facts, for a diagnostics surface or a test double. */
    val state: StateFlow<AdCadenceState> = _state.asStateFlow()

    private var limits: AdCadenceLimits = AdCadenceLimits.SHIPPED

    /**
     * Publish the operator's caps the moment a remote-config body lands. Until this is called —
     * a first install, a server that has never answered — [SHIPPED] is what is enforced, so
     * absence is the capped behaviour and never the uncapped one.
     *
     * Both blocks arrive because they can name the same cap in different units and from different
     * deploys; [engagement] wins where it speaks, and a body that carries neither leaves this
     * enforcing the shipped windows rather than nothing at all.
     */
    fun publishLimits(ads: VipRemoteAds, engagement: VipRemoteEngagement = VipRemoteEngagement()) {
        limits = AdCadenceLimits.from(ads, engagement)
    }

    /** Reload the persisted stamps. Called on start and whenever the switch or caps change. */
    suspend fun refresh() {
        _state.value = AdCadenceRows.toState(dao.all(), enabled = currentSwitch())
    }

    /**
     * Ask for [surface]. `Serve` means the slot is legal by cadence, the viewer is not ad-free,
     * the network filled it, and the impression is already recorded; anything else means show
     * nothing, and there is no third answer that could be mistaken for a loading state.
     *
     * [adFree] is a parameter rather than something read here because the rule that answers it —
     * a server membership or a rewarded device pass — belongs to
     * [com.raddstream.app.viewmodel.RewardedVipPass], and this package does not import that layer.
     * Making every surface name the viewer's status out loud is also the safer shape: a caller that
     * forgets it has to say so, and cannot inherit a silent default that shows a paid viewer an ad.
     */
    suspend fun offer(surface: AdSurface, adFree: Boolean): AdDecision {
        val enabled = currentSwitch() && !adFree
        val current = _state.value.copy(enabled = enabled)
        if (!enabled) return AdDecision.None
        if (!AdCadence.due(current, surface, limits, clock.nowMs())) return AdDecision.None
        // An ad that cannot be filled is not an ad; it is a hole in the layout where one waited.
        if (!inventory.canFill(surface)) return AdDecision.None

        val now = clock.nowMs()
        val next = AdCadence.shown(current, surface, now)
        _state.value = next
        persist(next)
        return AdDecision.Serve(surface = surface, skippableAtMs = AdCadence.skippableAtMs(limits))
    }

    /**
     * The feed card's cap counts posters, not minutes, so this is the only way that counter moves.
     * A negative or zero report is not a scroll and changes nothing; a screen reporting the same
     * index twice is a caller bug this cannot detect, which is why the value saturates at the cap
     * instead of accumulating forever.
     *
     * An ad-free viewer's counter does not advance. Left to fill up during a rewarded four hours,
     * it would spend itself the second that pass expired, and a card owed for posters they were
     * never eligible to see is a debt this app should not have.
     */
    suspend fun onPostersScrolled(count: Int, adFree: Boolean) {
        if (count <= 0) return
        if (!currentSwitch() || adFree) return
        val next = AdCadence.scrolled(_state.value, count, limits)
        if (next.postersSinceFeedCard == _state.value.postersSinceFeedCard) return
        _state.value = next
        persist(next)
    }

    /**
     * The operator turned the surfaces off: every stamp and counter goes. Idempotent, because the
     * remote-config watcher calls it on each five-minute poll that still reads disabled.
     */
    suspend fun clearForDisabledSwitch() {
        dao.clear()
        _state.value = AdCadence.cleared()
    }

    private suspend fun persist(state: AdCadenceState) {
        AdCadenceRows.toRows(state).forEach { dao.put(it) }
    }

    /**
     * The switch is read on every ask rather than cached here. A viewer who turns ads off in
     * `/admin` must not stay inside a four-hour window that the app remembered from when the
     * surface was on, and one store read is cheaper than a second owner for that fact. A read that
     * cannot be answered is a refusal, here and not in the binding, so the rule holds for whatever
     * binding a future build installs.
     */
    private suspend fun currentSwitch(): Boolean = try {
        switch.adsEnabled()
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        false
    }
}
