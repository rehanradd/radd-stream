package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.VipRemoteConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The dialog's whole decision. Remote config carries no version code, so the rule is:
 * a published, http(s) APK link is an update notice; anything else is silence.
 */
class AppUpdateTest {

    @Test
    fun `a published http link becomes the notice`() {
        val update = AppUpdate.from(
            VipRemoteConfig(apkUpdateUrl = " http://92.4.95.252/downloads/app.apk ", updatedAt = 1729920000L),
        )

        assertEquals("http://92.4.95.252/downloads/app.apk", update?.url)
        assertEquals(1729920000L, update?.publishedAt)
    }

    @Test
    fun `an empty or absent link means no notice`() {
        assertNull(AppUpdate.from(null))
        assertNull(AppUpdate.from(VipRemoteConfig()))
        assertNull(AppUpdate.from(VipRemoteConfig(apkUpdateUrl = "   ")))
    }

    @Test
    fun `a scheme that is not http is never offered to ACTION_VIEW`() {
        assertNull(AppUpdate.from(VipRemoteConfig(apkUpdateUrl = "javascript:alert(1)")))
        assertNull(AppUpdate.from(VipRemoteConfig(apkUpdateUrl = "file:///sdcard/app.apk")))
        assertNull(AppUpdate.from(VipRemoteConfig(apkUpdateUrl = "ftp://example.com/app.apk")))
    }
}
