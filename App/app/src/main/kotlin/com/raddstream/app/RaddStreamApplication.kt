package com.raddstream.app

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.util.DebugLogger
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.DeviceIdentity
import com.raddstream.app.data.RemoteConfigWatcher
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.Telemetry
import com.raddstream.app.data.cache.CacheEngineRunner
import com.raddstream.app.data.cache.CacheSweepWorker
import com.raddstream.app.data.cache.KeepTtlHolder
import com.raddstream.app.data.downloads.DeviceDownloadsRepository
import com.raddstream.app.images.ImageSizingHolder
import com.raddstream.app.images.PosterDiagEventListener
import com.raddstream.app.share.LanShareRunner
import com.raddstream.app.sync.SyncAccountRepository
import dagger.hilt.android.HiltAndroidApp
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Application class — Hilt entry point.
 * Referenced in AndroidManifest.xml as android:name=".RaddStreamApplication"
 */
@HiltAndroidApp
class RaddStreamApplication : Application(), Configuration.Provider, ImageLoaderFactory {

    @Inject
    lateinit var cacheEngineRunner: CacheEngineRunner

    @Inject
    lateinit var lanShareRunner: LanShareRunner

    @Inject
    lateinit var keepTtlHolder: KeepTtlHolder

    @Inject
    lateinit var imageSizingHolder: ImageSizingHolder

    @Inject
    lateinit var syncAccountRepository: SyncAccountRepository

    @Inject
    lateinit var settingsRepository: ServerSettingsRepository

    @Inject
    lateinit var remoteConfigWatcher: RemoteConfigWatcher

    @Inject
    lateinit var deviceDownloadsRepository: DeviceDownloadsRepository

    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    // The manifest removes WorkManager's default initializer, so this is the
    // only factory that can build a worker — and the only one that can build
    // a @HiltWorker at all.
    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()

    /**
     * DIAGNOSTIC ONLY (poster-diag build, 2026-11-13): the app's Coil loader, built with
     * Coil's own defaults — same OkHttp client, same timeouts, same caches as the
     * default singleton this replaces — plus a Debug logger and the [PosterDiagEventListener]
     * that logs every request's start/success/error with its URL and elapsed time.
     * Nothing about loading behaviour changes; the BrowserStack poster experiment
     * (20:49–21:00 PKT 13 Nov) proved Coil never fired a request on device, and this
     * is the only way to see why. Remove this whole override to go back to the
     * untouched default loader.
     */
    override fun newImageLoader(): ImageLoader =
        ImageLoader.Builder(this)
            .logger(DebugLogger())
            .eventListener(PosterDiagEventListener)
            .build()

    override fun onCreate() {
        super.onCreate()
        // Swap in the runtime brand snapshot before any screen composes. Until this runs,
        // every Brand getter falls back to its compiled BuildConfig constant, so this call
        // can only make the brand *more* current, never blank it.
        Brand.load(this)
        // Tracking A: the counters exist from the first lines of the process,
        // and the crash handler with them — a crash before this point is a
        // crash before the app did anything worth counting. The snapshot
        // refresh reads the viewer's answers from DataStore on a background
        // scope, so a slow store never holds up the first frame; a store
        // that throws simply leaves the snapshot at "not consented".
        Telemetry.init(this)
        Telemetry.installCrashHandler()
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            runCatching { Telemetry.refresh(settingsRepository) }
        }
        // Seed the retention window before anything can read it: the sweep's first pass is seconds
        // away, and until this collector's first emission the answer is the 3-hour default rather
        // than the viewer's saved choice. Started here — not lazily by the sweep — because a
        // preference a background component must obey is collected once, at the top, exactly like
        // the LAN share opt-in below.
        keepTtlHolder.start()
        // Seed the image-sizing decision before the first poster composes. The Settings "Image
        // quality" row and the mobile-data switch both write DataStore that nothing else reads; this
        // holder is that reader, so the collectors here are the wire between those two controls and
        // every AsyncImage. Until the first emission the holder answers its own AUTO / Wi-Fi default
        // (640px, nothing blocked), so a cold install renders exactly what it did before this existed.
        imageSizingHolder.start()
        // The one owner that drives the offline engine for the whole process: wires the player's
        // keep boundary, pumps the scheduler, and ages out ephemeral keeps via the existing sweep.
        cacheEngineRunner.start()
        // The one owner of the LAN share socket: it only binds once the persisted opt-in is on, so
        // starting it here is safe — a fresh install never exposes a share. It reads its preference,
        // never the UI, so this is the only place the server is ever constructed.
        lanShareRunner.start()
        // Membership is the server's fact, not this device's, so it is read at launch and then on a
        // 6-hour interval for as long as this process lives. Nothing starts when there is no account
        // key to ask with, and an app that was simply closed re-reads on the next launch — which is
        // why the expiry lives on the ledger and never as a countdown here.
        syncAccountRepository.startEntitlementWatch()
        // The free three days are granted by the server's trial ledger, keyed on a device id this
        // install reports about itself — a gate against the uninstall-reinstall case, not an
        // attestation, and the card copy says so. Asked once per launch, and only by a device with
        // no key and no trial record, so a returning viewer sends nothing here.
        syncAccountRepository.ensureDeviceTrialAtLaunch { DeviceIdentity.trialDeviceId(this) }
        // The operator's switches are process state, not a screen's private fetch: this is the
        // only reader of `/remote-config` that runs before any UI, and it is what makes
        // maintenance mode cover the whole app instead of only a screen someone opened.
        remoteConfigWatcher.start()
        // Resume any public downloads that were interrupted while the app was closed.
        deviceDownloadsRepository.autoResumeInterrupted()
        // The closed-app sweep: the same TTL auto-delete + low-storage eviction
        // the in-process runner runs every 5 minutes, once a day while the app
        // is closed. KEEP means a reinstall of this line never duplicates the
        // work; a failure never retries, the next day or the next launch
        // covers it.
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            CacheSweepWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<CacheSweepWorker>(1, TimeUnit.DAYS).build(),
        )
    }
}
