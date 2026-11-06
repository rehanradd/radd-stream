package com.raddstream.app.ui.navigation

import com.raddstream.app.data.UserRegion
import com.raddstream.app.network.models.PanelBroadcast
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The broadcast audience, decided on the phone. These pin the filter, not
 * the network: the server sends every live broadcast, and this is the only
 * place that decides who sees one.
 */
class BroadcastTargetingTest {

    private fun broadcast(target: String, detail: String = "") =
        PanelBroadcast(id = 1, title = "T", body = "B", target = target, targetDetail = detail)

    @Test
    fun `all reaches everyone, even before the tier loads`() {
        assertTrue(BroadcastTargeting.visible(broadcast("all"), UserRegion.DESI_DUBS, null, "1.0.4"))
    }

    @Test
    fun `free shows only to a known free viewer`() {
        assertTrue(BroadcastTargeting.visible(broadcast("free"), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("free"), UserRegion.DESI_DUBS, true, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("free"), UserRegion.DESI_DUBS, null, "1.0.4"))
    }

    @Test
    fun `vip shows only to a known VIP`() {
        assertTrue(BroadcastTargeting.visible(broadcast("vip"), UserRegion.DESI_DUBS, true, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("vip"), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("vip"), UserRegion.DESI_DUBS, null, "1.0.4"))
    }

    @Test
    fun `region maps the panel country to the viewer card`() {
        // Pakistan and India share the Desi card: a broadcast addressed to
        // one reaches both, by design and by the panel's own wording.
        assertTrue(BroadcastTargeting.visible(broadcast("region", "pakistan"), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertTrue(BroadcastTargeting.visible(broadcast("region", "india"), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("region", "pakistan"), UserRegion.EAST_ASIAN, false, "1.0.4"))
        assertTrue(BroadcastTargeting.visible(broadcast("region", "asia"), UserRegion.EAST_ASIAN, false, "1.0.4"))
        assertTrue(BroadcastTargeting.visible(broadcast("region", "international"), UserRegion.INTERNATIONAL, false, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("region", "europe"), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("region", ""), UserRegion.DESI_DUBS, false, "1.0.4"))
    }

    @Test
    fun `version matches exactly, never by prefix`() {
        assertTrue(BroadcastTargeting.visible(broadcast("version", "1.0.4"), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("version", "1.0.4"), UserRegion.DESI_DUBS, false, "1.0.40"))
        assertFalse(BroadcastTargeting.visible(broadcast("version", "1.0"), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertFalse(BroadcastTargeting.visible(broadcast("version", ""), UserRegion.DESI_DUBS, false, "1.0.4"))
    }

    @Test
    fun `an unknown target hides the broadcast`() {
        assertFalse(BroadcastTargeting.visible(broadcast("everyone"), UserRegion.DESI_DUBS, false, "1.0.4"))
    }

    @Test
    fun `target and detail are case and space tolerant`() {
        assertTrue(BroadcastTargeting.visible(broadcast(" Region ", " Pakistan "), UserRegion.DESI_DUBS, false, "1.0.4"))
        assertTrue(BroadcastTargeting.visible(broadcast("VERSION", "1.0.4"), UserRegion.DESI_DUBS, false, " 1.0.4 "))
    }
}
