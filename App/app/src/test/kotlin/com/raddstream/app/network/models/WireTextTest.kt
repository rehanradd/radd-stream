package com.raddstream.app.network.models

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `WireText.listOf` is the only reader for the three v1 columns that are TEXT but hold a
 * list, so every presentation surface (genres chips, language pills, backdrop art) stands
 * or falls on it. These cases are the wire shapes verified against the live ledger, plus
 * the one that a self-referencing `listOf` call used to turn into a StackOverflowError on
 * any value that was not a JSON array.
 */
class WireTextTest {

    @Test
    fun readsCsvColumns() {
        assertEquals(
            listOf("Action", "Adventure", "Drama", "Fantasy"),
            WireText.listOf("Action, Adventure, Drama, Fantasy"),
        )
        assertEquals(listOf("Drama"), WireText.listOf("Drama"))
    }

    @Test
    fun readsTheOtherSeparatorsTheScrapersLeaveBehind() {
        assertEquals(listOf("Hindi", "English", "Japanese"), WireText.listOf("Hindi + English + Japanese"))
        assertEquals(listOf("Tamil", "Telugu"), WireText.listOf("Tamil / Telugu"))
        assertEquals(listOf("A", "B"), WireText.listOf("A;B"))
        assertEquals(listOf("A", "B"), WireText.listOf("A|B"))
    }

    @Test
    fun readsJsonArrayStringsAndBareUrls() {
        assertEquals(
            listOf("https://a.jpg", "https://b.jpg"),
            WireText.listOf("[\"https://a.jpg\", \"https://b.jpg\"]"),
        )
        assertEquals(listOf("https://a.jpg"), WireText.listOf("https://a.jpg"))
        // A half-written array still has to read as items, not as one broken string.
        assertEquals(listOf("Action", "Drama"), WireText.listOf("[Action, Drama"))
        assertEquals(listOf("Sci-Fi", "Noir"), WireText.listOf("Sci-Fi / Noir"))
    }

    @Test
    fun answersAnEmptyListForNothingAndForMalformedJson() {
        assertTrue(WireText.listOf(null).isEmpty())
        assertTrue(WireText.listOf("").isEmpty())
        assertTrue(WireText.listOf("   ").isEmpty())
        assertTrue(WireText.listOf("[]").isEmpty())
        assertTrue(WireText.listOf("[null]").isEmpty())
        assertEquals(listOf("a", "b"), WireText.listOf("[\"a\", \"\", \"b\"]"))
    }

    @Test
    fun dropsBlanksAndDuplicatesFromAnyShape() {
        assertEquals(listOf("English", "Hindi"), WireText.listOf("English,,  , Hindi, English"))
    }

    @Test
    fun splitOnAnySplitsEveryGivenSeparatorAtOnce() {
        assertEquals(listOf("a", "b", "c", "d"), WireText.splitOnAny("a,b c;d", ",", " ", ";"))
        assertTrue(WireText.splitOnAny(null, ",").isEmpty())
        assertTrue(WireText.splitOnAny("  ", ",").isEmpty())
    }

    /**
     * The APK digest is compared, never printed, so a wrong length or a stray character stores
     * fine as free text and then fails silently against a correctly downloaded file. These are
     * the shapes the admin form is supposed to refuse and the client must refuse too.
     */
    @Test
    fun apkDigestIsExactlySixtyFourLowercaseHex() {
        assertTrue(WireText.isApkDigest("a".repeat(64)))
        assertTrue("a real digest mixes digits and letters",
            WireText.isApkDigest("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcde0"))
        assertFalse("63 characters is a paste", WireText.isApkDigest("a".repeat(63)))
        assertFalse("65 characters is not a digest either", WireText.isApkDigest("a".repeat(65)))
        assertFalse("uppercase never matches what the form wrote", WireText.isApkDigest("A".repeat(64)))
        assertFalse("a prefix tag is not a bare digest", WireText.isApkDigest("sha256:" + "a".repeat(64)))
        assertFalse("an inner space breaks it", WireText.isApkDigest("a".repeat(32) + " " + "a".repeat(32)))
        assertFalse("a non-hex character anywhere is refused", WireText.isApkDigest("a".repeat(63) + "g"))
        assertFalse(WireText.isApkDigest(""))
        assertFalse(WireText.isApkDigest(null))
    }

    /**
     * Loopback is the device's own wire; everything else in cleartext is a network path an APK
     * travels down unverified, because `ACTION_VIEW` hands the file over without asking for the
     * install permission this app would need to check it.
     */
    @Test
    fun apkDownloadsAreHttpsAnywhereOrCleartextOnlyOnLoopback() {
        assertTrue(WireText.isVerifiableDownloadUrl("https://dl.example.com/app.apk"))
        assertTrue(WireText.isVerifiableDownloadUrl("  https://dl.example.com/app.apk  "))
        assertTrue(WireText.isVerifiableDownloadUrl("http://127.0.0.1:8080/app.apk"))
        assertTrue(WireText.isVerifiableDownloadUrl("http://localhost/app.apk"))
        assertTrue(WireText.isVerifiableDownloadUrl("http://[::1]:8080/app.apk"))
        assertTrue(WireText.isVerifiableDownloadUrl("http://127.3.4.5/app.apk"))
        assertFalse("cleartext across a network is refused",
            WireText.isVerifiableDownloadUrl("http://92.4.95.252/downloads/app.apk"))
        assertFalse("a name that only starts like loopback is a host on the internet",
            WireText.isVerifiableDownloadUrl("http://127.example.com/app.apk"))
        assertFalse(WireText.isVerifiableDownloadUrl("ftp://example.com/app.apk"))
        assertFalse(WireText.isVerifiableDownloadUrl("file:///sdcard/app.apk"))
        assertFalse(WireText.isVerifiableDownloadUrl("javascript:alert(1)"))
        assertFalse(WireText.isVerifiableDownloadUrl("http://"))
        assertFalse(WireText.isVerifiableDownloadUrl(""))
        assertFalse(WireText.isVerifiableDownloadUrl(null))
    }

    /**
     * The refusals that must sit beside the IPv6 case above. The cheap way to make a bracketed
     * loopback pass is "any bracketed host is the device's own wire", and that is an opening, not
     * a fail-closed mistake: a routable v6 address in cleartext is a network path like any other,
     * so only the loopback literal may keep the cleartext exception.
     */
    @Test
    fun anIPv6LiteralIsLoopbackOnlyWhenItIsTheLoopbackAddress() {
        assertTrue("loopback without a port", WireText.isVerifiableDownloadUrl("http://[::1]/app.apk"))
        assertTrue("loopback with a port", WireText.isVerifiableDownloadUrl("http://[::1]:8080/app.apk"))
        assertFalse("a routable v6 host is not the device's own wire",
            WireText.isVerifiableDownloadUrl("http://[2606:4700:4005::66]/app.apk"))
        assertFalse("a routable v6 host with a port is still a network host",
            WireText.isVerifiableDownloadUrl("http://[2606:4700:4005::66]:8080/app.apk"))
        assertFalse("the next address after loopback is not loopback",
            WireText.isVerifiableDownloadUrl("http://[::2]/app.apk"))
        assertFalse("an empty bracket is not an address",
            WireText.isVerifiableDownloadUrl("http://[]/app.apk"))
    }
}
