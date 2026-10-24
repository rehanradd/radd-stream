package com.raddstream.app

import android.app.Application
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.cache.CacheEngineRunner
import com.raddstream.app.share.LanShareRunner
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

/**
 * Application class — Hilt entry point.
 * Referenced in AndroidManifest.xml as android:name=".RaddStreamApplication"
 */
@HiltAndroidApp
class RaddStreamApplication : Application() {

    @Inject
    lateinit var cacheEngineRunner: CacheEngineRunner

    @Inject
    lateinit var lanShareRunner: LanShareRunner

    override fun onCreate() {
        super.onCreate()
        // Swap in the runtime brand snapshot before any screen composes. Until this runs,
        // every Brand getter falls back to its compiled BuildConfig constant, so this call
        // can only make the brand *more* current, never blank it.
        Brand.load(this)
        // The one owner that drives the offline engine for the whole process: wires the player's
        // keep boundary, pumps the scheduler, and ages out ephemeral keeps via the existing sweep.
        cacheEngineRunner.start()
        // The one owner of the LAN share socket: it only binds once the persisted opt-in is on, so
        // starting it here is safe — a fresh install never exposes a share. It reads its preference,
        // never the UI, so this is the only place the server is ever constructed.
        lanShareRunner.start()
    }
}
