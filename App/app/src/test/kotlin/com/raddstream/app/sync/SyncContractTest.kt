package com.raddstream.app.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The one way a viewer can sign in on this card — a key the server minted, presented unchanged —
 * and the rule that key obeys: the same key opens the same library on every device, and nothing
 * re-derives it into a different one. Plus the phone number, which is a label and nothing more.
 *
 * The number used to be a second sign-in path. It is pinned here as NOT one, because that is the
 * defect this file exists to keep from coming back: deriving a credential from
 * `SHA-256("phone-sync/v1|03XXXXXXXXX")` made knowing somebody's mobile number sufficient to open
 * their library, and the 16-character result cleared the server's own entropy floor.
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

    /**
     * The retired attack, stated as a refusal. Every spelling of one number, and the number that
     * a whole country's worth of viewers wrote down, must open NOTHING. A single line here that
     * returns a String would mean the derivation is back.
     */
    @Test
    fun `a mobile number is never a credential, in any spelling`() {
        assertNull(SyncContract.quickLoginKey("03001234567"))
        assertNull(SyncContract.quickLoginKey("0300-1234567"))
        assertNull(SyncContract.quickLoginKey("+92 300 1234567"))
        assertNull(SyncContract.quickLoginKey("923001234567"))
        assertNull(SyncContract.quickLoginKey("00923001234567"))
        assertNull(SyncContract.quickLoginKey("3001234567"))
        assertFalse(SyncContract.isQuickLoginInput("03001234567"))
        // And no fixed answer exists for it either: this is not "the same key every time", it is
        // no key at all.
        assertNull(SyncContract.quickLoginKey("03001234567 "))
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

    /**
     * Path (a) of the two that remain: a key this server minted is the credential, and two
     * different keys are two different accounts. Nothing about a person — a number, a name —
     * is an input to which library opens.
     */
    @Test
    fun `distinct keys open distinct accounts and nothing else`() {
        val first = SyncContract.quickLoginKey("ABCD1234EFGH5678")
        val second = SyncContract.quickLoginKey("ABCD1234EFGH5679")

        assertNotNull(first)
        assertNotNull(second)
        assertNotEquals(first, second)
        assertEquals("ABCD1234EFGH5678", first)
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
        assertTrue(SyncContract.isQuickLoginInput("ABCD1234EFGH5678"))
        assertTrue(SyncContract.isQuickLoginInput("a".repeat(43)))
        assertFalse(SyncContract.isQuickLoginInput("03001234567"))
        assertFalse(SyncContract.isQuickLoginInput("0300123"))
        assertFalse(SyncContract.isQuickLoginInput(""))
    }

    /**
     * The number's only remaining job. It canonicalizes like [normalizePakistaniMobile] so the
     * card reads one way however it was typed, keeps anything that is not a number as written,
     * and caps at the length a card row can paint.
     */
    @Test
    fun `a label is display text, canonical for numbers and as-written otherwise`() {
        assertEquals("03001234567", SyncContract.accountLabel("0300-123-4567"))
        assertEquals("03001234567", SyncContract.accountLabel("+92 300 1234567"))
        assertEquals("Rehan", SyncContract.accountLabel("  Rehan  "))
        assertEquals("My dad's phone", SyncContract.accountLabel("My dad's phone"))
        assertNull(SyncContract.accountLabel("   "))
        assertNull(SyncContract.accountLabel(null))
        assertEquals(
            SyncContract.MAX_LABEL_CHARS,
            SyncContract.accountLabel("n".repeat(200))!!.length,
        )
    }

    /**
     * The boundary the whole task is about, pinned as a value rather than only as a scan: the
     * label and the credential are functions of the same text and must never be functions of each
     * other. A label is not a key, and typing a key into the label box produces a label — not a
     * sign-in.
     */
    @Test
    fun `a label is never a key and a key is never a label-only path`() {
        val number = "03001234567"
        assertEquals(number, SyncContract.accountLabel(number))
        assertNull(SyncContract.quickLoginKey(number))
        assertNull(SyncContract.accountLabel(SyncContract.quickLoginKey(number)))

        val key = "ABCD1234EFGH5678"
        assertEquals(key, SyncContract.quickLoginKey(key))
        assertEquals(key, SyncContract.accountLabel(key))
    }

    @Test
    fun `the key band mirrors the new sixteen-character server floor`() {
        assertEquals(16, SyncContract.MIN_SYNC_KEY_CHARS)
        assertTrue(SyncContract.isUsableSyncKey("a".repeat(16)))
        assertFalse(SyncContract.isUsableSyncKey("a".repeat(15)))
    }
}
