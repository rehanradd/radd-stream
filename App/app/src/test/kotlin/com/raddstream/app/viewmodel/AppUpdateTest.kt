package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.VipRemoteConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The dialog's whole decision, as a truth table.
 *
 * The rule used to be "a non-empty http(s) URL is an update notice", because the published body
 * carried nothing else to reason about. UPD-1a gave the operator a digest, a size and a version
 * code, so the app can now refuse an offer it cannot honestly describe — and the refusal is the
 * point: `openDownload` fires `ACTION_VIEW` and never asks `REQUEST_INSTALL_PACKAGES`, so nothing
 * downstream can tell the viewer the bytes were the bytes promised.
 *
 * Every refusal below has a positive control beside it, because a gate that answers null for
 * everything is green by accident.
 */
class AppUpdateTest {

    private fun published(
        url: String = "https://dl.example.com/app.apk",
        digest: String = DIGEST,
        versionCode: Int = 12,
        updatedAt: Long = 1729920000L,
        success: Boolean = true,
    ) = VipRemoteConfig(
        success = success,
        updatedAt = updatedAt,
        apkUpdateUrl = url,
        apkUpdateSha256 = digest,
        apkUpdateVersionCode = versionCode,
    )

    @Test
    fun `a published digested newer https build is the notice`() {
        val update = AppUpdate.from(published(url = " https://dl.example.com/app.apk "), 11)

        assertEquals("https://dl.example.com/app.apk", update?.url)
        assertEquals(1729920000L, update?.publishedAt)
    }

    @Test
    fun `loopback may stay cleartext and a network may not`() {
        assertEquals(
            "http://127.0.0.1:8080/app.apk",
            AppUpdate.from(published(url = "http://127.0.0.1:8080/app.apk"), 0)?.url,
        )
        assertNull(
            "the live host serves plain HTTP today, so its link no longer earns a banner",
            AppUpdate.from(published(url = "http://92.4.95.252/downloads/app.apk"), 0),
        )
    }

    @Test
    fun `no digest means no banner, never an unchecked one`() {
        assertNull(AppUpdate.from(published(digest = ""), 0))
        assertNull(AppUpdate.from(published(digest = "a".repeat(63)), 0))
        assertNull(AppUpdate.from(published(digest = "A".repeat(64)), 0))
        assertNull(AppUpdate.from(published(digest = "sha256:" + "a".repeat(64)), 0))
        assertNotNull(AppUpdate.from(published(digest = "a".repeat(64)), 0))
    }

    @Test
    fun `newer stops being a guess`() {
        assertNull("same code is not an update", AppUpdate.from(published(versionCode = 12), 12))
        assertNull("an older code is not an update", AppUpdate.from(published(versionCode = 12), 13))
        assertNull("a published 0 is no version at all", AppUpdate.from(published(versionCode = 0), 11))
        assertNull(AppUpdate.from(published(versionCode = -1), 0))
        assertNotNull(AppUpdate.from(published(versionCode = 12), 11))
    }

    @Test
    fun `a body the server itself marks unsuccessful publishes nothing`() {
        assertNull(AppUpdate.from(published(success = false), 0))
        assertNotNull(AppUpdate.from(published(), 0))
    }

    @Test
    fun `an empty or absent link means no notice`() {
        assertNull(AppUpdate.from(null, 0))
        assertNull(AppUpdate.from(VipRemoteConfig(), 0))
        assertNull(AppUpdate.from(published(url = "   "), 0))
    }

    @Test
    fun `a scheme that is not http is never offered to ACTION_VIEW`() {
        assertNull(AppUpdate.from(published(url = "javascript:alert(1)"), 0))
        assertNull(AppUpdate.from(published(url = "file:///sdcard/app.apk"), 0))
        assertNull(AppUpdate.from(published(url = "ftp://example.com/app.apk"), 0))
        assertNull(AppUpdate.from(published(url = "content://media/external/1"), 0))
    }

    companion object {
        private const val DIGEST =
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
}
