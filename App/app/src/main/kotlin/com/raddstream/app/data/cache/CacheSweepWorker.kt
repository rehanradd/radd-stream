package com.raddstream.app.data.cache

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject

/**
 * The closed-app sweep. The in-process runner already runs this same
 * [CacheSweeper] every 5 minutes while the app is alive; this worker runs
 * it once a day while the app is closed, so bytes that aged out overnight
 * are gone before the next launch instead of waiting for it. TTL
 * auto-delete + low-storage eviction only — never a download, never a
 * network call.
 *
 * A failure never retries: the next period, or the in-process sweep on
 * launch, covers it. The sweep itself refuses to delete a file a running
 * task owns, so a worker racing a launch cannot take a live download.
 */
@HiltWorker
class CacheSweepWorker @AssistedInject constructor(
    @Assisted appContext: Context,
    @Assisted workerParams: WorkerParameters,
    private val sweepStore: RoomCacheSweepStore,
    private val clock: UptimeClock,
) : CoroutineWorker(appContext, workerParams) {

    override suspend fun doWork(): Result = runCatching {
        CacheSweeper(sweepStore, clock).sweep()
    }.fold(
        onSuccess = { Result.success() },
        onFailure = { Result.success() },
    )

    companion object {
        const val UNIQUE_NAME = "cache-sweep"
    }
}
