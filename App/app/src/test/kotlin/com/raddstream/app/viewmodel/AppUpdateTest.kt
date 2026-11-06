package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.VipRemoteConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The dialog's whole decision. A published, http(s) APK link is an update notice;
 * anything else is silence. When the operator published a version code, the
 * notice compares it: a code at or below this build means this build already
 * has it. When the operator set a minimum above this build, the notice is
 * required, not optional.
 */
class AppUpdateTest {

    private val url = "http://92.4.95.252/downloads/app.apk"

    @Test
    fun `a published http link becomes the notice`() {
        val update = AppUpdate.from(
            VipRemoteConfig(apkUpdateUrl = " http://92.4.95.252/downloads/app.apk ", updatedAt = 1729920000L),
        )

        assertEquals("http://92.4.95.252/downloads/app.apk", update?.url)
        assertEquals(1729920000L, update?.publishedAt)
        assertEquals(false, update?.required)
    }

    @Test
    fun `a published code newer than this build becomes the notice`() {
        val update = AppUpdate.from(
            VipRemoteConfig(apkUpdateUrl = url, apkUpdateVersionCode = 214),
            currentVersionCode = 213,
        )

        assertEquals(url, update?.url)
        assertEquals(false, update?.required)
    }

    @Test
    fun `a published code at or below this build means silence`() {
        assertNull(
            AppUpdate.from(
                VipRemoteConfig(apkUpdateUrl = url, apkUpdateVersionCode = 213),
                currentVersionCode = 213,
            ),
        )
        assertNull(
            AppUpdate.from(
                VipRemoteConfig(apkUpdateUrl = url, apkUpdateVersionCode = 200),
                currentVersionCode = 213,
            ),
        )
    }

    @Test
    fun `a build below the operator minimum is a required notice`() {
        val update = AppUpdate.from(
            VipRemoteConfig(
                apkUpdateUrl = url,
                apkUpdateVersionCode = 214,
                minVersionCode = 214,
            ),
            currentVersionCode = 213,
        )

        assertEquals(url, update?.url)
        assertEquals(true, update?.required)
    }

    @Test
    fun `a build at or above the minimum is optional`() {
        val update = AppUpdate.from(
            VipRemoteConfig(
                apkUpdateUrl = url,
                apkUpdateVersionCode = 215,
                minVersionCode = 214,
            ),
            currentVersionCode = 214,
        )

        assertEquals(url, update?.url)
        assertEquals(false, update?.required)
    }

    @Test
    fun `a minimum without a download link is silence, not a dead end`() {
        assertNull(
            AppUpdate.from(
                VipRemoteConfig(minVersionCode = 999),
                currentVersionCode = 213,
            ),
        )
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
