package com.raddstream.app.data

import com.raddstream.app.di.CacheScope
import com.raddstream.app.player.AdCadenceGovernor
import com.raddstream.app.repository.CatalogRepository
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * The one owner that turns the operator's remote-config body into persisted app switches.
 *
 * Before this existed [com.raddstream.app.network.models.VipRemoteConfig.maintenanceMode] was
 * decoded and then dropped: only the VIP screen ever asked for the body, so a catalog under
 * maintenance stayed fully reachable until someone happened to open that screen. The watcher
 * polls the public endpoint on the app's own clock and writes the answer through
 * [ServerSettingsRepository], which is what every screen observes.
 *
 * Failure policy: a failed or malformed poll leaves the last good answer in place. That is
 * deliberate — a server being restarted is exactly when it cannot serve `/remote-config`
 * either, and flipping the app out of maintenance on a network error would defeat the
 * switch. Only a successful, fully decoded body overwrites stored flags.
 */
@Singleton
class RemoteConfigWatcher @Inject constructor(
    private val catalogRepository: CatalogRepository,
    private val settings: ServerSettingsRepository,
    private val adCadence: AdCadenceGovernor,
    @CacheScope private val scope: CoroutineScope,
) {

    private val started = AtomicBoolean(false)

    /** Coalesces tap-spam on a manual refresh: one in-flight re-read at a time. */
    private val refreshing = AtomicBoolean(false)

    /** Idempotent: the Application calls this once, before any screen composes. */
    fun start() {
        if (!started.compareAndSet(false, true)) return
        scope.launch {
            while (isActive) {
                refreshOnce()
                delay(REFRESH_INTERVAL_MS)
            }
        }
    }

    /**
     * One immediate re-read of `/remote-config`, outside the five-minute loop — the
     * maintenance screen's Retry button. A tap while a refresh is already running is a
     * no-op rather than a second network call; the loop's own tick is not guarded by
     * this flag, so a manual refresh racing the tick can still double-fetch once —
     * harmless, both writes derive from the same endpoint and land the same values.
     * A failed or malformed poll leaves the last good answer in place, exactly like
     * the loop's: a server being restarted cannot serve `/remote-config` either, and
     * flipping the app out of maintenance on a network error would defeat the switch.
     */
    fun refreshNow() {
        if (!refreshing.compareAndSet(false, true)) return
        scope.launch {
            try {
                refreshOnce()
            } finally {
                refreshing.set(false)
            }
        }
    }

    private suspend fun refreshOnce() {
        val config = try {
            catalogRepository.getRemoteConfig()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return
        }
        if (!config.success) return
        // A degraded body is a shape guarantee, not the operator's decision:
        // the settings row could not be read, so every switch, price and cap
        // in it is a shipped default. Saving any of it would overwrite the
        // operator's real values with defaults — the fail-open the server's
        // own docstring warns about. Keep the last good config instead.
        if (config.settingsUnavailable) return
        // `flags.chromecast` is deliberately not mirrored: this build has no cast UI at all, so
        // there is no feature for that switch to take away. Storing it would be a dead key.
        val flags = config.featureFlags
        settings.saveRemoteFlags(
            maintenanceMode = config.maintenanceMode,
            downloadsEnabled = flags.downloads,
            sharingEnabled = flags.sharing,
            searchEnabled = flags.search,
            pureCinemaEnabled = flags.pureCinema,
            qualityGateEnabled = flags.qualityGate,
            adsEnabled = config.ads.enabled,
        )
        // The theme rides the same successful body: a failed poll leaves the
        // last good theme in place, exactly like the switches above.
        settings.saveTheme(config.theme)
        // The tabs ride the same body, under the same rule: a failed poll
        // leaves the last good order in place, and a body that carries no
        // tabs (an older deployment) leaves the bar on its own four.
        settings.saveTabs(config.tabs)
        // The disclaimer rides the same body, under the same rule as the
        // tabs: a failed poll leaves the last good text in place, and a
        // body that carries no disclaimer (an older deployment, or the
        // operator retracting it) stores empty — and empty means "nothing
        // published", so the dialog never opens on it.
        settings.saveDisclaimer(config.disclaimer)
        // The free quality cap rides the same body, under the same rule: a
        // failed poll leaves the last good cap in place, and a body that
        // carries no cap (an older deployment) stores the shipped "720p".
        settings.saveFreeQualityCap(config.freeQualityCap)
        // The caps travel with the switch, and only a body that carries them overrides what this
        // build already enforces — a partial body leaves the shipped 25/12/4 windows in force
        // rather than resetting them to something the operator never asked for.
        //
        // Two bodies can name a cap: the `ads` block this app has always read, and the server's own
        // `engagement.cadence`, which is what `engagement.ad_grant()` enforces server-side. Both
        // are handed over so the policy has one merge point for them rather than every call site
        // picking a favourite.
        //
        // The whole cadence block is guarded because it is the only part of a poll that writes to
        // Room: a locked or half-migrated database must cost the viewer an ad window, not the app.
        // An uncaught throw here would kill the process on the next five-minute tick.
        try {
            adCadence.publishLimits(config.ads, config.engagement)
            if (!config.ads.enabled) {
                // The operator turned the surfaces off, so every window they were enforcing goes
                // with them. Idempotent: a deployment that has never enabled ads costs one DELETE
                // per poll.
                adCadence.clearForDisabledSwitch()
            } else {
                adCadence.refresh()
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            // The governor keeps enforcing whatever it already had loaded. Refusing to update the
            // windows is the conservative direction: it cannot invent an impression.
        }
    }

    companion object {
        /** Five minutes: fast enough to notice an operator switch, cheap enough to ignore. */
        const val REFRESH_INTERVAL_MS = 5L * 60_000L
    }
}
