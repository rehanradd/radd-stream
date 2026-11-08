package com.raddstream.app.data

import java.io.File
import javax.crypto.KeyGenerator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * SyncKeyCryptoTest — the sync key's encryption at rest, on the JVM.
 *
 * Plain JUnit4, no Robolectric: `encrypt` / `decrypt` take the key as a
 * parameter, so they run against a generated AES key. Only `loadOrCreateKey`
 * touches the Android Keystore, and it is not exercised here — a JVM has no
 * Keystore to load from, and the repository treats its null as "store
 * plaintext below API 23", which is the documented limitation.
 *
 * The last test is a source scan, in the PhoneCredentialGuardTest pattern:
 * the guarantee "no plaintext sync key remains in prefs" is about the
 * repository's write path, and the only thing that proves it without a
 * device is reading that path.
 */
class SyncKeyCryptoTest {

    private fun freshKey() = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    @Test
    fun `encrypt then decrypt returns the key`() {
        val key = freshKey()
        val blob = SyncKeyCrypto.encrypt("abcdefghijklmnop", key)
        assertEquals("abcdefghijklmnop", SyncKeyCrypto.decrypt(blob, key))
    }

    @Test
    fun `two encryptions of one key never look alike`() {
        val key = freshKey()
        assertNotEquals(
            SyncKeyCrypto.encrypt("abcdefghijklmnop", key),
            SyncKeyCrypto.encrypt("abcdefghijklmnop", key),
        )
    }

    @Test
    fun `a blob under the wrong key opens to nothing`() {
        val blob = SyncKeyCrypto.encrypt("abcdefghijklmnop", freshKey())
        assertNull(SyncKeyCrypto.decrypt(blob, freshKey()))
    }

    @Test
    fun `garbage tampered and legacy values decrypt to nothing`() {
        val key = freshKey()
        assertNull(SyncKeyCrypto.decrypt("not-a-blob", key))
        assertNull(SyncKeyCrypto.decrypt("v1:not-base64!!", key))
        val blob = SyncKeyCrypto.encrypt("abcdefghijklmnop", key)
        val tampered = blob.dropLast(4) + "AAAA"
        assertNull(SyncKeyCrypto.decrypt(tampered, key))
        assertNull(SyncKeyCrypto.decrypt("abcdefghijklmnop", key))
    }

    @Test
    fun `an encrypted blob is marked and a plaintext one is not`() {
        val key = freshKey()
        assertTrue(SyncKeyCrypto.isEncrypted(SyncKeyCrypto.encrypt("abcdefghijklmnop", key)))
        assertTrue(!SyncKeyCrypto.isEncrypted("abcdefghijklmnop"))
    }

    // ── the repository's write path ──────────────────────────────────────
    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private fun mainSource(relative: String): String =
        File(repoRoot, "App/app/src/main/$relative").readText()

    @Test
    fun `the repository encrypts the sync key before storing it`() {
        // The documented exception is a missing Keystore key (below API 23 or a
        // Keystore refusal): then the fallback stores plaintext and the account
        // card says so. What this pins is that the write path never stores the
        // clean key when a key exists to encrypt with.
        val repository = mainSource("kotlin/com/raddstream/app/data/ServerSettingsRepository.kt")
        assertTrue(
            "saveSyncKey must encrypt before it stores",
            repository.contains("SyncKeyCrypto.encrypt(clean, it)"),
        )
        assertTrue(
            "the read path must decrypt what it stored",
            repository.contains("SyncKeyCrypto.decrypt(stored, key)"),
        )
        assertTrue(
            "a legacy plaintext value must be migrated, not left",
            repository.contains("migrateLegacySyncKey"),
        )
        assertTrue(
            "the stored value must never be the clean key itself",
            !repository.contains("preferences[SYNC_KEY_KEY] = clean"),
        )
    }

    @Test
    fun `auto backup stays off so the key never leaves the device in a backup`() {
        val manifest = mainSource("AndroidManifest.xml")
        assertTrue(
            "allowBackup must be false: the sync key must not travel in a backup image",
            manifest.contains("android:allowBackup=\"false\""),
        )
    }
}
