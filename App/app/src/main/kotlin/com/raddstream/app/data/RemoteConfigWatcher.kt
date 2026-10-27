package com.raddstream.app.data

import com.raddstream.app.di.CacheScope
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
        val flags = config.featureFlags
        settings.saveRemoteFlags(
            maintenanceMode = config.maintenanceMode,
            downloadsEnabled = flags.downloads,
            sharingEnabled = flags.sharing,
            searchEnabled = flags.search,
            qualityGateEnabled = flags.qualityGate,
        )
    }

    companion object {
        /** Five minutes: fast enough to notice an operator switch, cheap enough to ignore. */
        const val REFRESH_INTERVAL_MS = 5L * 60_000L
    }
}
