package com.raddstream.app.network.models

import com.google.gson.Gson
import com.raddstream.app.player.AdCadenceLimits
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
              "ads": {"monetag_rewarded_zone_id": "zone"}
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
    fun `decodes feature flags and the ad-network slots`() {
        val config = gson.fromJson(
            """
            {
              "success": true,
              "feature_flags": {"downloads": false, "pure_cinema": true, "chromecast": false},
              "ads": {"monetag_rewarded_zone_id": "zone-1",
                      "adsterra_native_banner_id": "banner-1"}
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
    }

    /**
     * Link shorteners are retired: the app models no `link_shorteners`, and the byte paths that
     * would have consumed one are direct (`ApiProvider.streamRedirectUrl` → /api/v1/stream).
     * A deployment that still publishes the key is therefore not a broken client — this pins
     * that an unknown section is ignored instead of throwing, so retiring the field here can
     * never be the reason a phone fails to load pricing.
     */
    @Test
    fun `a body still publishing the retired link_shorteners key decodes unchanged`() {
        val config = gson.fromJson(
            """
            {
              "success": true,
              "vip": {"monthly_pkr": 250, "yearly_pkr": 1800},
              "payments": {"jazzcash": {"till_id": "998877"}},
              "link_shorteners": [
                {"network": "shrinkme", "configured": true},
                {"network": "droplink", "configured": false}
              ]
            }
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertEquals("an arbitrary wire price, passed through — this client holds none of its own", 250, config.vip.monthlyPkr)
        assertEquals("998877", config.payments.jazzcash.tillId)
        assertTrue(config.payments.hasAnyHandle)
        assertTrue(config.success)
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

    /**
     * The ad switch defaults the way `quality_gate` does and for the same reason: an ad is not a
     * surface the viewer already had, so a deployment that never published the key must keep
     * showing them nothing. An absent `ads` object is the older server this task has to survive.
     */
    @Test
    fun `ads are off and unbounded by nothing when the body never mentions them`() {
        val config = gson.fromJson("""{"success": true}""", VipRemoteConfig::class.java)

        assertFalse(config.ads.enabled)
        // Zero means "the operator never said", which the policy answers with the shipped cap.
        assertEquals(0, config.ads.prerollIntervalMinutes)
        assertEquals(0, config.ads.feedCardEveryPosters)
        assertEquals(0, config.ads.appOpenIntervalHours)
        assertEquals(0, config.ads.skippableAfterSeconds)
        assertFalse(config.ads.hasRewardedInventory)
        assertFalse(config.ads.hasNativeInventory)
    }

    @Test
    fun `decodes the cadence caps under either spelling`() {
        val primary = gson.fromJson(
            """
            {"ads": {"ads_enabled": true, "preroll_interval_minutes": 30,
                     "feed_card_posters": 15, "app_open_interval_hours": 6,
                     "ad_skip_after_seconds": 4}}
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )
        assertTrue(primary.ads.enabled)
        assertEquals(30, primary.ads.prerollIntervalMinutes)
        assertEquals(15, primary.ads.feedCardEveryPosters)
        assertEquals(6, primary.ads.appOpenIntervalHours)
        assertEquals(4, primary.ads.skippableAfterSeconds)

        val alternate = gson.fromJson(
            """
            {"ads": {"feature_ads": true, "pre_roll_interval_minutes": 45,
                     "native_card_every_posters": 20, "app_open_hours": 12,
                     "skippable_after_seconds": 2}}
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )
        assertTrue(alternate.ads.enabled)
        assertEquals(45, alternate.ads.prerollIntervalMinutes)
        assertEquals(20, alternate.ads.feedCardEveryPosters)
        assertEquals(12, alternate.ads.appOpenIntervalHours)
        assertEquals(2, alternate.ads.skippableAfterSeconds)
    }

    /**
     * The wallet and the streak are parsed and displayed nowhere: no screen in this build renders a
     * balance, and a number the app cannot explain is a number it must not invent. Both therefore
     * have to default inert, and `hasAnyEarningRule` has to be false for a body that only turned a
     * switch on without ever naming a payout.
     */
    @Test
    fun `an absent wallet and streak decode to the inert shape`() {
        val config = gson.fromJson("""{"success": true}""", VipRemoteConfig::class.java)

        assertFalse(config.wallet.enabled)
        assertEquals(0, config.wallet.coinsPerPreRoll)
        assertEquals(0, config.wallet.coinsPerStreak)
        assertEquals(0, config.wallet.dailyCoinCap)
        assertFalse(config.wallet.hasAnyEarningRule)

        assertFalse(config.streak.enabled)
        assertEquals(VipRemoteStreak.DEFAULT_DAYS, config.streak.days)
        assertEquals(0, config.streak.rewardCoins)
        assertFalse(config.streak.isConfigured)
    }

    @Test
    fun `a configured wallet and streak are honoured`() {
        val config = gson.fromJson(
            """
            {"wallet": {"wallet_enabled": true, "coin_reward_preroll": 5,
                        "coin_reward_streak": 40, "coin_daily_cap": 100},
             "streak": {"streak_enabled": true, "streak_days": 7, "streak_reward_coins": 40}}
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertTrue(config.wallet.enabled)
        assertEquals(5, config.wallet.coinsPerPreRoll)
        assertEquals(40, config.wallet.coinsPerStreak)
        assertEquals(100, config.wallet.dailyCoinCap)
        assertTrue(config.wallet.hasAnyEarningRule)

        assertTrue(config.streak.enabled)
        assertEquals(7, config.streak.days)
        assertEquals(40, config.streak.rewardCoins)
        assertTrue(config.streak.isConfigured)
    }

    @Test
    fun `a switch on with no payout rule is not a promise of coins`() {
        val wallet = gson.fromJson(
            """{"wallet": {"wallet_enabled": true}}""",
            VipRemoteConfig::class.java,
        ).wallet

        assertTrue(wallet.enabled)
        assertFalse("nothing earns, so a balance screen has nothing to show", wallet.hasAnyEarningRule)

        val streak = gson.fromJson(
            """{"streak": {"streak_enabled": true, "streak_days": 0}}""",
            VipRemoteConfig::class.java,
        ).streak
        assertFalse("a zero-day streak rewards nothing and must not be advertised", streak.isConfigured)
    }

    /**
     * A deployment that has not merged the monetization fields still has to decode: an unknown or
     * missing section is ignored, the rest of the body still lands, and nothing about the older
     * server reads as an error to the phone. This is the whole independence claim of the task.
     */
    @Test
    fun `an older deployment with no monetization sections still decodes fully`() {
        val config = gson.fromJson(
            """
            {
              "success": true,
              "currency": "PKR",
              "updated_at": 1730000000,
              "vip": {"monthly_pkr": 250, "yearly_pkr": 1800},
              "payments": {"jazzcash": {"till_id": "998877", "mobile_account": "03001234567"}},
              "feature_flags": {"downloads": true, "pure_cinema": true},
              "ads": {"monetag_rewarded_zone_id": "zone-1"}
            }
            """.trimIndent(),
            VipRemoteConfig::class.java,
        )

        assertTrue(config.success)
        assertEquals("an arbitrary wire price, passed through — this client holds none of its own", 250, config.vip.monthlyPkr)
        assertTrue(config.payments.hasAnyHandle)
        assertEquals("zone-1", config.ads.monetagRewardedZoneId)
        // Present but inert: the old body has no cadence, so the client's own caps stand.
        assertFalse(config.ads.enabled)
        assertEquals(AdCadenceLimits.SHIPPED, AdCadenceLimits.from(config.ads))
        assertFalse(config.wallet.enabled)
        assertFalse(config.streak.enabled)
    }
}
