package com.raddstream.app.images

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The pure half of the image pipeline: the enum-name width table (delegated to
 * [com.raddstream.app.viewmodel.UserPreferences.posterMaxWidthPx]) and the metered-data gate.
 * Asserted without Android or Coil because these are exactly the two decisions a decoration used to
 * pretend to make — so they are the two a reviewer can no longer hand-wave past on a device.
 */
class ImageSizingPolicyTest {

    @Test
    fun `a stored quality name maps to the width the settings row promises`() {
        assertEquals(640, ImageSizingPolicy.widthPxFor("HIGH", mobileDataAllowed = false))
        assertEquals(400, ImageSizingPolicy.widthPxFor("MEDIUM", mobileDataAllowed = true))
        assertEquals(240, ImageSizingPolicy.widthPxFor("LOW", mobileDataAllowed = true))
        // An explicit choice is the same size on either network: the mobile-data switch decides
        // whether a poster loads at all, never how big a quality the viewer already picked is.
        assertEquals(240, ImageSizingPolicy.widthPxFor("LOW", mobileDataAllowed = false))
    }

    @Test
    fun `auto picks the smaller width only once mobile data is permitted`() {
        // AUTO is the fresh-install default and must stay Wi-Fi-sized when the switch is off...
        assertEquals(640, ImageSizingPolicy.widthPxFor("AUTO", mobileDataAllowed = false))
        // ...and step down to the conservative size once the viewer opts into metered loading.
        assertEquals(400, ImageSizingPolicy.widthPxFor("AUTO", mobileDataAllowed = true))
    }

    @Test
    fun `an unrecognised quality name falls back to the auto default, never a crash`() {
        assertEquals(640, ImageSizingPolicy.widthPxFor("ULTRA_4K", mobileDataAllowed = false))
    }

    @Test
    fun `metered without permission is the only case that skips the request`() {
        // Metered + not allowed -> skip. This is the whole point of the switch.
        assertFalse(ImageSizingPolicy.decide(240, imagesAllowedOnMobileData = false, metered = true).shouldLoad)
        // Wi-Fi -> always load, so the default install is never blocked (what it renders today).
        assertTrue(ImageSizingPolicy.decide(240, imagesAllowedOnMobileData = false, metered = false).shouldLoad)
        // Metered but the viewer opted in -> load.
        assertTrue(ImageSizingPolicy.decide(640, imagesAllowedOnMobileData = true, metered = true).shouldLoad)
    }

    @Test
    fun `the decision carries the chosen width through to the request`() {
        assertEquals(240, ImageSizingPolicy.decide(240, imagesAllowedOnMobileData = false, metered = true).widthPx)
    }

    @Test
    fun `shouldLoad is the gate on its own`() {
        assertFalse(ImageSizingPolicy.shouldLoad(imagesAllowedOnMobileData = false, metered = true))
        assertTrue(ImageSizingPolicy.shouldLoad(imagesAllowedOnMobileData = false, metered = false))
        assertTrue(ImageSizingPolicy.shouldLoad(imagesAllowedOnMobileData = true, metered = true))
        assertTrue(ImageSizingPolicy.shouldLoad(imagesAllowedOnMobileData = true, metered = false))
    }
}
