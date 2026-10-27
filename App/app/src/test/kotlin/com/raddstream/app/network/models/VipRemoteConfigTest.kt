package com.raddstream.app.network.models

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VipRemoteConfigTest {

    private val gson = Gson()

    @Test
    fun `decodes the servers full payment projection`() {
        val config = gson.fromJson(
            """
            {
              "success": true,
              "currency": "PKR",
              "updated_at": 1729920000,
              "vip": {"monthly_pkr": 250, "yearly_pkr": 1800},
              "payments": {
                "jazzcash": {"till_id": "998877", "mobile_account": "03001234567"},
                "easypaisa": {"mobile_number": "03331234567"},
                "raast": {"instant_id": "0300XXXXXXX"}
              },
              "ads": {"monetag_rewarded_zone_id": "zone"},
              "link_shorteners": [{"network": "shrinkme", "configured": true}]
            }
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertTrue(config.success)
        assertEquals("PKR", config.currency)
        assertEquals(1729920000L, config.updatedAt)
        assertEquals(250, config.vip.monthlyPkr)
        assertEquals(1800, config.vip.yearlyPkr)
        assertEquals("998877", config.payments.jazzcash.tillId)
        assertEquals("03001234567", config.payments.jazzcash.mobileAccount)
        assertEquals("03331234567", config.payments.easypaisa.mobileNumber)
        assertEquals("0300XXXXXXX", config.payments.raast.instantId)
        assertTrue(config.payments.hasAnyHandle)
    }

    @Test
    fun `a server with no configured row still decodes to blank handles`() {
        val config = gson.fromJson(
            """
            {"success": true, "currency": "PKR", "updated_at": 0,
             "vip": {"monthly_pkr": 0, "yearly_pkr": 0},
             "payments": {"jazzcash": {"till_id": "", "mobile_account": ""},
                          "easypaisa": {"mobile_number": ""},
                          "raast": {"instant_id": ""}}}
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertEquals(0, config.vip.monthlyPkr)
        assertEquals("", config.payments.jazzcash.tillId)
        assertEquals("", config.payments.raast.instantId)
        assertFalse(config.payments.hasAnyHandle)
    }

    @Test
    fun `a partial body leaves absent sections at their honest defaults`() {
        val config = gson.fromJson("""{"success": true}""", VipRemoteConfig::class.java)

        assertTrue(config.success)
        assertEquals("PKR", config.currency)
        assertEquals(0L, config.updatedAt)
        assertEquals(0, config.vip.yearlyPkr)
        assertFalse(config.payments.hasAnyHandle)
    }

    @Test
    fun `decodes the published apk link and the maintenance switch`() {
        val config = gson.fromJson(
            """
            {"success": true, "maintenance_mode": true,
             "apk_update_url": "http://92.4.95.252/downloads/app.apk"}
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertTrue(config.maintenanceMode)
        assertEquals("http://92.4.95.252/downloads/app.apk", config.apkUpdateUrl)
    }

    @Test
    fun `no published build decodes to an empty string, not null`() {
        val config = gson.fromJson("""{"success": true}""", VipRemoteConfig::class.java)

        assertEquals("", config.apkUpdateUrl)
        assertFalse(config.maintenanceMode)
    }

    @Test
    fun `decodes feature flags, ads and configured shorteners`() {
        val config = gson.fromJson(
            """
            {
              "success": true,
              "feature_flags": {"downloads": false, "pure_cinema": true, "chromecast": false},
              "ads": {"monetag_rewarded_zone_id": "zone-1",
                      "adsterra_native_banner_id": "banner-1"},
              "link_shorteners": [
                {"network": "shrinkme", "configured": true},
                {"network": "droplink", "configured": false}
              ]
            }
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertFalse(config.featureFlags.downloads)
        assertTrue(config.featureFlags.pureCinema)
        assertFalse(config.featureFlags.chromecast)
        // A flags object that does not mention the restriction leaves it off.
        assertFalse(config.featureFlags.qualityGate)
        assertEquals("zone-1", config.ads.monetagRewardedZoneId)
        assertEquals("banner-1", config.ads.adsterraNativeBannerId)
        assertTrue(config.ads.hasRewardedInventory)
        assertEquals(2, config.linkShorteners.size)
        assertEquals("shrinkme", config.linkShorteners[0].network)
        assertTrue(config.linkShorteners[0].configured)
        assertFalse(config.linkShorteners[1].configured)
    }

    @Test
    fun `accepts the brief feature-flag aliases without losing the rest`() {
        val config = gson.fromJson(
            """
            {"success": true,
             "feature_flags": {"downloads_enabled": false,
                               "sharing_enabled": false,
                               "search_enabled": false}}
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertFalse(config.featureFlags.downloads)
        assertFalse(config.featureFlags.sharing)
        assertFalse(config.featureFlags.search)
        // A partial flag object keeps the enabled default for keys it did not mention.
        assertTrue(config.featureFlags.pureCinema)
        assertTrue(config.featureFlags.chromecast)
    }

    @Test
    fun `absent switches default to the historical app behaviour`() {
        val config = gson.fromJson("""{"success": true}""", VipRemoteConfig::class.java)

        assertTrue(config.featureFlags.downloads)
        assertTrue(config.featureFlags.pureCinema)
        assertTrue(config.featureFlags.chromecast)
        assertTrue(config.featureFlags.sharing)
        assertTrue(config.featureFlags.search)
        assertFalse(config.ads.hasRewardedInventory)
        assertTrue(config.linkShorteners.isEmpty())
    }

    @Test
    fun `one filled handle is enough to offer a submission`() {
        val payments = VipRemotePayments(
            jazzcash = VipRemoteJazzCash(tillId = "", mobileAccount = ""),
            easypaisa = VipRemoteEasyPaisa(mobileNumber = "03331234567"),
            raast = VipRemoteRaast(instantId = ""),
        )

        assertTrue(payments.hasAnyHandle)
    }

    /**
     * Both a server that answers `quality_gate: false` and one that never heard of the key
     * have to mean the same thing on the phone: nobody is restricted. A paywall that switched
     * itself on because a field was missing would be the worst possible default, so this pins
     * the direction rather than the value.
     */
    @Test
    fun `the quality gate stays off when the server says nothing about it`() {
        assertFalse(
            gson.fromJson("""{"success": true}""", VipRemoteConfig::class.java)
                .featureFlags.qualityGate,
        )
        val older = gson.fromJson(
            """{"feature_flags": {"downloads": true, "pure_cinema": true, "chromecast": true}}""",
            VipRemoteConfig::class.java,
        )
        assertFalse(older.featureFlags.qualityGate)
        assertTrue(
            gson.fromJson("""{"feature_flags": {"quality_gate": true}}""", VipRemoteConfig::class.java)
                .featureFlags.qualityGate,
        )
    }
}
