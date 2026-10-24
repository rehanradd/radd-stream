package com.raddstream.app.data.cache

import com.raddstream.app.di.CacheScope
import com.raddstream.app.player.CacheEngineHolder
import com.raddstream.app.player.PlayerSessionStore
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The single owner of the offline engine's coroutine lifecycle. Started once from the Application,
 * it publishes [OfflineCacheEngine] onto the player boundary, pumps the scheduler [CacheCoordinator.tick]
 * on a fixed cadence, runs the existing [CacheSweeper] (TTL auto-delete + low-storage eviction, never a
 * new timer) periodically, and forwards the player's playhead into [CacheCoordinator.onPlayheadAdvanced].
 *
 * Everything it calls already exists and is unit-tested; this class only sequences them against the
 * app-lifetime [CacheScope] so bytes move and stale keeps age out while the process is alive. It is
 * idempotent: [start] runs its loops exactly once no matter how many times the host calls it.
 */
@Singleton
class CacheEngineRunner @Inject constructor(
    private val coordinator: CacheCoordinator,
    private val sweepStore: RoomCacheSweepStore,
    private val engine: OfflineCacheEngine,
    private val clock: UptimeClock,
    @CacheScope private val scope: CoroutineScope,
) {

    private val started = AtomicBoolean(false)

    fun start() {
        if (!started.compareAndSet(false, true)) return
        CacheEngineHolder.engine = engine

        scope.launch {
            while (isActive) {
                runCatching { coordinator.tick() }
                delay(TICK_MILLIS)
            }
        }

        scope.launch {
            // Run one sweep shortly after boot to clear anything that aged out while the app was
            // closed, then on the periodic cadence.
            delay(SWEEP_STARTUP_DELAY_MILLIS)
            while (isActive) {
                runCatching { CacheSweeper(sweepStore, clock).sweep() }
                delay(SWEEP_MILLIS)
            }
        }

        scope.launch {
            PlayerSessionStore.Instance.playhead.collect { tick ->
                runCatching { engine.pumpPlayhead(tick) }
            }
        }
    }

    companion object {
        private const val TICK_MILLIS = 3_000L
        private const val SWEEP_MILLIS = 5L * 60_000L
        private const val SWEEP_STARTUP_DELAY_MILLIS = 15_000L
    }
}
