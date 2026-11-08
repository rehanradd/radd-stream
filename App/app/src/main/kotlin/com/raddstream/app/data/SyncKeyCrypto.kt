package com.raddstream.app.data

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The sync key, encrypted at rest with a key the Android Keystore holds.
 *
 * The audit found the sync key in plain `preferencesDataStore` — readable by
 * anyone who can read the app's private files (a rooted device, a backup
 * image) — and included in Android Auto Backup. This is the fix: the value
 * stored under `sync_key` is `v1:` + hex(IV || AES-GCM ciphertext), and
 * the AES key never leaves the Keystore. The DataStore plumbing does not
 * change — the same key, the same Flow — only the bytes at rest do.
 *
 * The blob is hex, not base64, on purpose: `android.util.Base64` is a
 * framework stub on the JVM (plain unit tests cannot call it — that is
 * exactly why the first version's round-trip tests failed), and
 * `java.util.Base64` needs API 26 while this path serves API 23+. Hex is
 * pure Kotlin, identical on a phone and on the JVM, and the blob is short
 * enough (~88 chars) that the 2x size costs nothing.
 *
 * API 23+ only: the Keystore AES-GCM path needs Marshmallow. Below 23 the
 * key is stored as before, in plaintext, and the repository documents that
 * limitation on the card that creates it. A device that later upgrades past
 * 23 migrates the plaintext on its next read.
 *
 * Key loss is fail-closed, never fail-open: if the Keystore entry is gone
 * (a factory reset, a key invalidated by the system), decryption returns
 * null and the app treats the install as signed out. The ciphertext stays
 * where it is; the viewer re-enters their key and the new value is stored
 * encrypted under the fresh key.
 *
 * `encrypt` / `decrypt` take the key as a parameter so they are testable on
 * the JVM with a generated AES key — only [loadOrCreateKey] touches the
 * Android Keystore, and only it may return null.
 */
object SyncKeyCrypto {

    const val PREFIX = "v1:"
    private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
    private const val KEY_ALIAS = "radd_stream_sync_key"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val IV_BYTES = 12
    private const val TAG_BITS = 128

    fun isEncrypted(blob: String): Boolean = blob.startsWith(PREFIX)

    // ── hex codec (pure Kotlin — no platform Base64, see the class KDoc) ──
    private val HEX_CHARS = "0123456789abcdef".toCharArray()

    internal fun bytesToHex(bytes: ByteArray): String {
        val out = CharArray(bytes.size * 2)
        for (i in bytes.indices) {
            val v = bytes[i].toInt() and 0xFF
            out[i * 2] = HEX_CHARS[v ushr 4]
            out[i * 2 + 1] = HEX_CHARS[v and 0x0F]
        }
        return String(out)
    }

    internal fun hexToBytes(hex: String): ByteArray? {
        if (hex.length % 2 != 0) return null
        val out = ByteArray(hex.length / 2)
        for (i in out.indices) {
            val hi = HEX_CHARS.indexOf(hex[i * 2])
            val lo = HEX_CHARS.indexOf(hex[i * 2 + 1])
            if (hi < 0 || lo < 0) return null
            out[i] = ((hi shl 4) or lo).toByte()
        }
        return out
    }

    /**
     * Encrypt one key. A fresh random IV per call, prepended to the
     * ciphertext, so two encryptions of the same key never look alike and a
     * replayed blob is still only that one key's ciphertext.
     */
    fun encrypt(plaintext: String, key: SecretKey): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key)
        val iv = cipher.iv
        val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
        val combined = ByteArray(iv.size + ciphertext.size)
        iv.copyInto(combined)
        ciphertext.copyInto(combined, iv.size)
        return PREFIX + bytesToHex(combined)
    }

    /**
     * Decrypt one stored value, or null when it is not our ciphertext, the
     * key is wrong, or a byte was tampered with. Null is never an exception
     * here: a stored value the key cannot open is a signed-out install, not
     * a crash.
     */
    fun decrypt(blob: String, key: SecretKey): String? {
        if (!isEncrypted(blob)) return null
        return try {
            val combined = hexToBytes(blob.removePrefix(PREFIX)) ?: return null
            if (combined.size <= IV_BYTES) return null
            val iv = combined.copyOfRange(0, IV_BYTES)
            val ciphertext = combined.copyOfRange(IV_BYTES, combined.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, iv))
            String(cipher.doFinal(ciphertext), Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    /**
     * The Keystore AES key for the sync key, created on first use. Null
     * below API 23 (no Keystore AES-GCM) or when the Keystore itself refuses
     * — the caller then stores plaintext and documents it, rather than
     * failing a sign-in over storage.
     */
    fun loadOrCreateKey(context: Context): SecretKey? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return null
        return try {
            val store = KeyStore.getInstance(KEYSTORE_PROVIDER)
            store.load(null)
            val existing = store.getKey(KEY_ALIAS, null) as? SecretKey
            if (existing != null) return existing
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER)
            generator.init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generator.generateKey()
        } catch (_: Exception) {
            null
        }
    }
}
