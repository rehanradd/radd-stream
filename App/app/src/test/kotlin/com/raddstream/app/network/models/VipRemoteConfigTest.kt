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
    fun `one filled handle is enough to offer a submission`() {
        val payments = VipRemotePayments(
            jazzcash = VipRemoteJazzCash(tillId = "", mobileAccount = ""),
            easypaisa = VipRemoteEasyPaisa(mobileNumber = "03331234567"),
            raast = VipRemoteRaast(instantId = ""),
        )

        assertTrue(payments.hasAnyHandle)
    }
}
