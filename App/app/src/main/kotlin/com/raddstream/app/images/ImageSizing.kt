package com.raddstream.app.images

import com.raddstream.app.viewmodel.ImageQuality
import com.raddstream.app.viewmodel.UserPreferences

/**
 * The whole image-sizing decision as one immutable value, so every poster in the app answers
 * the same two questions the same way — "how wide may I be" and "may I load on this network" —
 * read from Home, Browse, Search, My List and the detail header without re-deriving per screen.
 *
 * [posterMaxWidthPx] is the pixel cap the Settings "Image quality" row promises. It is computed
 * once from the stored enum name by [ImageSizingPolicy.widthPxFor] and nothing else may invent a
 * width. [imagesAllowedOnMobileData] is the persisted mirror of the mobile-data switch: standing
 * permission to move poster bytes when the connection is metered.
 */
data class ImageSizing(
    val posterMaxWidthPx: Int,
    val imagesAllowedOnMobileData: Boolean,
)

/** The answer a Coil call site acts on: the width to request, and whether to bother at all. */
data class ImageRequestDecision(val widthPx: Int, val shouldLoad: Boolean)

/**
 * The pure rules behind [ImageSizing] and the load gate. Deliberately free of Android and Coil
 * types so the width table and the metered-data gate are assertable in a plain JVM test — the way
 * [com.raddstream.app.data.cache.SchedulerPolicy] is — rather than behind a device.
 *
 * The enum-to-pixel mapping is NOT restated here: it delegates to [UserPreferences.posterMaxWidthPx],
 * the one table the Settings row already computes. That delegation is the entire reason this object
 * exists. Six AsyncImage call sites each picking a size is how a "Battery saver" install quietly
 * keeps pulling 640px; one shared function, which every request and every test both go through, is
 * how the number cannot drift from what the setting claims.
 */
object ImageSizingPolicy {

    /** The widest poster to request for a stored quality name plus the mobile-data permission. */
    fun widthPxFor(qualityName: String, mobileDataAllowed: Boolean): Int =
        UserPreferences(
            imageQuality = ImageQuality.valueOfOrDefault(qualityName),
            downloadOnMobileData = mobileDataAllowed,
        ).posterMaxWidthPx

    /**
     * May a poster load on the network we are actually on? Loading is skipped only when the
     * connection is metered AND the viewer never granted mobile-data loading. Every other case —
     * unmetered Wi-Fi, or an explicit opt-in — loads, so a default install is unchanged: images
     * are never blocked on Wi-Fi, and the switch is off until the person flips it.
     */
    fun shouldLoad(imagesAllowedOnMobileData: Boolean, metered: Boolean): Boolean =
        !metered || imagesAllowedOnMobileData

    /** The single decision a call site turns into a request. Width is carried through, not recomputed. */
    fun decide(widthPx: Int, imagesAllowedOnMobileData: Boolean, metered: Boolean): ImageRequestDecision =
        ImageRequestDecision(widthPx, shouldLoad(imagesAllowedOnMobileData, metered))
}
