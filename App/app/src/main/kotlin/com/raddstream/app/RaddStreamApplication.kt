package com.raddstream.app

import android.app.Application
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.cache.CacheEngineRunner
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

    override fun onCreate() {
        super.onCreate()
        // Swap in the runtime brand snapshot before any screen composes. Until this runs,
        // every Brand getter falls back to its compiled BuildConfig constant, so this call
        // can only make the brand *more* current, never blank it.
        Brand.load(this)
        // The one owner that drives the offline engine for the whole process: wires the player's
        // keep boundary, pumps the scheduler, and ages out ephemeral keeps via the existing sweep.
        cacheEngineRunner.start()
    }
}
