package com.raddstream.app.images

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.cache.ConnectivityProbe
import com.raddstream.app.di.CacheScope
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * The one live copy of the image-sizing decision, for the components that have no UI of their own
 * to re-read it from: every poster and detail-header image across Home, Browse, Search, My List and
 * Detail (see [com.raddstream.app.ui.components.CatalogImage]).
 *
 * WHY THIS CLASS EXISTS: the Settings "Image quality" row and the mobile-data switch wrote two
 * DataStore keys that nothing read, and `UserPreferences.posterMaxWidthPx` had zero consumers — two
 * controls that were pure decoration. This holder is the wire between those preferences and the
 * pixels actually requested, the same role [com.raddstream.app.data.cache.KeepTtlHolder] plays for the
 * retention window.
 *
 * WHY THIS SHAPE: it is the [com.raddstream.app.share.LanShareRunner] / [KeepTtlHolder] pattern,
 * copied on purpose — a `@Singleton` the Application starts once, which collects
 * [ServerSettingsRepository] flows on the app-lifetime [CacheScope] rather than opening a second
 * scope. The one deliberate difference is the snapshot type: those holders expose a plain field
 * because their consumers are non-UI code doing a one-off read, whereas a poster must *recompose* the
 * instant the width changes, so the latest value is mirrored into a [StateFlow] and collected with
 * `collectAsState`. DataStore reads are suspend and belong on the app scope, never in a composition.
 *
 * WHAT IS **NOT** PROTECTED: nothing here survives process death on its own, and between process
 * start and the first emission [sizing] answers the AUTO / not-allowed seed (640px, images not
 * blocked) — exactly the pre-existing behaviour, so a slow or corrupt store can only delay the switch
 * taking effect, never blank art or block a Wi-Fi load. Metered-ness is not observed here at all: it
 * is read live per request via [isMetered], so an image already on screen stays up if the network
 * flips to metered while you scroll — only the next request obeys.
 */
@Singleton
class ImageSizingHolder @Inject constructor(
    private val settings: ServerSettingsRepository,
    private val connectivity: ConnectivityProbe,
    @CacheScope private val scope: CoroutineScope,
) {

    private val started = AtomicBoolean(false)

    // The seed is the documented storage default, so an install that never opens Settings, and a
    // first frame before the DataStore answers, both behave exactly as the app did before this class.
    private val _sizing = MutableStateFlow(
        ImageSizing(
            posterMaxWidthPx = ImageSizingPolicy.widthPxFor(ServerSettingsRepository.DEFAULT_IMAGE_QUALITY, false),
            imagesAllowedOnMobileData = false,
        ),
    )

    /** The current persisted sizing decision. Collected, never sampled, so a tap shows up live. */
    val sizing: StateFlow<ImageSizing> = _sizing.asStateFlow()

    /** Idempotent: begins observing the two preferences. Mirrors [com.raddstream.app.share.LanShareRunner.start]. */
    fun start() {
        if (!started.compareAndSet(false, true)) return
        scope.launch {
            combine(settings.imageQualityChoice, settings.mobileDataAllowed) { name, allowed ->
                ImageSizing(ImageSizingPolicy.widthPxFor(name, allowed), allowed)
            }.collect { _sizing.value = it }
        }
    }

    /**
     * Is the active network metered? Delegates to the connectivity owner the app already has; it
     * fails open (returns false) when the platform refuses the query, so a locked-down API level
     * or a transient failure never blanks art on a network we could not read.
     */
    fun isMetered(): Boolean = connectivity.isMetered()
}
