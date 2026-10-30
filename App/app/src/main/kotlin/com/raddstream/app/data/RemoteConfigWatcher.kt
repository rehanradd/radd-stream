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

    private suspend fun refreshOnce() {
        val config = try {
            catalogRepository.getRemoteConfig()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return
        }
        if (!config.success) return
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
