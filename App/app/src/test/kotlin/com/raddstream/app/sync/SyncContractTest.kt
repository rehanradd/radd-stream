package com.raddstream.app.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The two ways a viewer can sign in on this card — a Pakistani mobile number or a key the
 * server minted — and the one rule both must obey: the same input opens the same library on
 * every device, while a key the viewer already holds is never re-derived into a different one.
 */
class SyncContractTest {

    @Test
    fun `pakistani mobile numbers normalize to one canonical form`() {
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("03001234567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("0300-1234567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("0300 123 4567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("(0300) 123-4567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("+92 300 1234567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("+923001234567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("923001234567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("00923001234567"))
        assertEquals("03001234567", SyncContract.normalizePakistaniMobile("3001234567"))
        assertNull(SyncContract.normalizePakistaniMobile("02001234567"))
        assertNull(SyncContract.normalizePakistaniMobile("0300123456"))
        assertNull(SyncContract.normalizePakistaniMobile("030012345678"))
        assertNull(SyncContract.normalizePakistaniMobile("+443001234567"))
        assertNull(SyncContract.normalizePakistaniMobile("not a number"))
        assertNull(SyncContract.normalizePakistaniMobile(""))
        assertNull(SyncContract.normalizePakistaniMobile(null))
    }

    @Test
    fun `a short sync key is exactly sixteen url-safe characters and keeps its case`() {
        assertTrue(SyncContract.isShortSyncKey("ABCD1234EFGH5678"))
        assertTrue(SyncContract.isShortSyncKey("  abcd1234efgh5678  "))
        assertTrue(SyncContract.isShortSyncKey("abcd-1234_efgh56"))
        assertFalse(SyncContract.isShortSyncKey("ABCD1234EFGH567"))
        assertFalse(SyncContract.isShortSyncKey("ABCD1234EFGH56789"))
        assertFalse(SyncContract.isShortSyncKey("ABCD 1234 EFGH56"))
        assertFalse(SyncContract.isShortSyncKey("ABCD1234EFGH56é"))
        assertFalse(SyncContract.isShortSyncKey(""))
        assertFalse(SyncContract.isShortSyncKey(null))
    }

    @Test
    fun `a phone number derives the same sixteen-character key from every spelling`() {
        val fromLocal = SyncContract.quickLoginKey("0300-1234567")
        val fromInternational = SyncContract.quickLoginKey("+92 300 1234567")
        val fromCountryCode = SyncContract.quickLoginKey("923001234567")

        assertEquals(fromLocal, fromInternational)
        assertEquals(fromLocal, fromCountryCode)
        assertNotNull(fromLocal)
        assertEquals(SyncContract.SHORT_SYNC_KEY_CHARS, fromLocal!!.length)
        assertTrue(SyncContract.isShortSyncKey(fromLocal))
        assertTrue(SyncContract.isUsableSyncKey(fromLocal))
        // The number never travels as itself.
        assertFalse(fromLocal.contains("03001234567"))
        assertFalse(fromLocal.contains("3001234567"))
    }

    @Test
    fun `different numbers and a literal key never collide`() {
        val first = SyncContract.quickLoginKey("03001234567")
        val second = SyncContract.quickLoginKey("03011234567")
        val literal = SyncContract.quickLoginKey("ABCD1234EFGH5678")

        assertNotEquals(first, second)
        assertNotEquals(first, literal)
        assertEquals("ABCD1234EFGH5678", literal)
    }

    @Test
    fun `a key the viewer already holds is sent unchanged, never re-derived`() {
        // Case is part of the credential: folding it would open a different account.
        assertEquals("abcd1234efgh5678", SyncContract.quickLoginKey("  abcd1234efgh5678  "))
        assertEquals("abcd-1234_efgh56", SyncContract.quickLoginKey("abcd-1234_efgh56"))

        // An older, 43-character key keeps working instead of being "helpfully" remade.
        val legacy = "a".repeat(SyncContract.LEGACY_SYNC_KEY_CHARS)
        assertEquals(legacy, SyncContract.quickLoginKey(legacy))
    }

    @Test
    fun `input that is neither a mobile nor a complete key signs in to nothing`() {
        assertNull(SyncContract.quickLoginKey("0300123"))
        assertNull(SyncContract.quickLoginKey("toolong1234567890"))       // 17: a typo
        assertNull(SyncContract.quickLoginKey("short"))
        assertNull(SyncContract.quickLoginKey("has space in it 1234"))
        assertNull(SyncContract.quickLoginKey(""))
        assertNull(SyncContract.quickLoginKey(null))
    }

    @Test
    fun `quick login classification matches the credential it would send`() {
        assertTrue(SyncContract.isQuickLoginInput("03001234567"))
        assertTrue(SyncContract.isQuickLoginInput("ABCD1234EFGH5678"))
        assertFalse(SyncContract.isQuickLoginInput("0300123"))
        assertFalse(SyncContract.isQuickLoginInput(""))
    }

    @Test
    fun `the key band mirrors the new sixteen-character server floor`() {
        assertEquals(16, SyncContract.MIN_SYNC_KEY_CHARS)
        assertTrue(SyncContract.isUsableSyncKey("a".repeat(16)))
        assertFalse(SyncContract.isUsableSyncKey("a".repeat(15)))
    }
}
