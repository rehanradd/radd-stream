package com.raddstream.app

import android.app.Application
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.cache.CacheEngineRunner
import com.raddstream.app.data.cache.KeepTtlHolder
import com.raddstream.app.images.ImageSizingHolder
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

    @Inject
    lateinit var keepTtlHolder: KeepTtlHolder

    @Inject
    lateinit var imageSizingHolder: ImageSizingHolder

    override fun onCreate() {
        super.onCreate()
        // Swap in the runtime brand snapshot before any screen composes. Until this runs,
        // every Brand getter falls back to its compiled BuildConfig constant, so this call
        // can only make the brand *more* current, never blank it.
        Brand.load(this)
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
    }
}
