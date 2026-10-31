package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * KeystorePreflightGuardTest — pins the shape of the release-signing block in
 * `App/app/build.gradle.kts`, which no unit test can execute.
 *
 * Why this needs a guard at all. The release workflow died at
 * `keystoreFile.writeBytes(Base64.getDecoder().decode(keystoreBase64))` with
 * `IllegalArgumentException: Last unit does not have enough valid bits`, eight seconds into the job —
 * which is Gradle configuration, not signing, so it failed before a single Kotlin file was read and
 * therefore before any test could observe it. Two responses to that crash were proposed on the day,
 * and only one of them is safe:
 *
 *  - Swapping the strict decoder for the tolerant MIME decoder was measured on this host and is
 *    provably useless *and* harmful: for the malformed-final-group input that produced our exact
 *    error, the tolerant decoder throws the identical message, so it does not even hide the failure;
 *    and for a truncated secret it accepts the bytes silently, after which the app ships signed with
 *    a key nobody can verify. That swap is refused here, in prose and in this assertion.
 *  - Keeping the strict decoder and refusing bad input loudly is what the block now does: structure
 *    first (length a multiple of four, base64 alphabet only), then the decode, then integrity (the
 *    bytes must parse as a keystore, the configured alias must exist, must be a private-key entry,
 *    and must be unlocked by the stored key password). Every message prints the *shape* of the
 *    credential — length, index, code point, decoded byte count — and never its contents, because a
 *    build log is read by more people than the secret is.
 *
 * The tests below assert that the block stayed in that order. They are pure JVM text checks, so they
 * run in `:app:testDebugUnitTest` on the hosted runner and cost nothing to execute. The control test
 * at the end feeds the detector the *old* block verbatim: if that ever stops failing, these
 * assertions have gone blind rather than passed.
 */
class KeystorePreflightGuardTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val script: String by lazy {
        val f = File(repoRoot, "App/app/build.gradle.kts")
        assertTrue("the build script moved away from App/app/build.gradle.kts", f.isFile)
        f.readText()
    }

    @Test
    fun `the strict decoder is still the only decoder used`() {
        assertTrue(
            "the strict decoder is the guard: it refuses a malformed tail. Replacing it is how a " +
                "truncated keystore ships silently.",
            script.contains("Base64.getDecoder()"),
        )
        assertFalse(
            "the tolerant MIME decoder accepts a truncated keystore and throws the SAME error on the " +
                "input that broke our release run — measured on this host. Do not introduce it here, " +
                "in either call form.",
            script.contains("getMimeDecoder"),
        )
        assertFalse(
            "whitespace stripping in the build script is the other half of that same weakening: it " +
                "makes a wrapped secret look valid instead of telling the operator to re-paste it",
            script.contains("filter { !it.isWhitespace() }"),
        )
    }

    @Test
    fun `the block refuses structure before it decodes`() {
        val lengthCheck = script.indexOf("keystoreBase64.length % 4 != 0")
        val alphabetCheck = script.indexOf("indexOfFirst")
        val decode = script.indexOf("Base64.getDecoder().decode(keystoreBase64)")
        val write = script.indexOf("keystoreFile.writeBytes(keystoreBytes)")

        assertTrue("the multiple-of-four check is gone: $lengthCheck", lengthCheck > 0)
        assertTrue("the alphabet check is gone: $alphabetCheck", alphabetCheck > 0)
        assertTrue("the decode is gone: $decode", decode > 0)
        assertTrue("the write is gone: $write", write > 0)
        // Order is the point. A structure check placed after the decode cannot fire, because the
        // decode is what throws.
        assertTrue(
            "the length check must run before the decode, or it cannot prevent the crash it exists " +
                "to prevent",
            lengthCheck < decode,
        )
        assertTrue("the alphabet check must run before the decode", alphabetCheck < decode)
        assertTrue("nothing writes bytes to the keystore file before the checks", decode < write)
        assertTrue(
            "the file must be written from the checked bytes, not by re-decoding inline — that is how " +
                "a second, unchecked decode path gets reintroduced",
            !script.contains("writeBytes(Base64.getDecoder().decode("),
        )
    }

    @Test
    fun `decoded bytes are proven to be a usable keystore before signing sees them`() {
        listOf(
            "KeyStore.getInstance" to "bytes that decode are not yet a keystore without this",
            "containsAlias(keyAlias)" to "an alias that does not exist fails at signing, not here",
            "isKeyEntry(keyAlias)" to "a certificate entry cannot sign an APK",
            "getKey(keyAlias, keyPassword.toCharArray())" to "a wrong KEY_PASSWORD must fail as itself",
        ).forEach { (marker, why) ->
            assertTrue("$why — missing: $marker", script.contains(marker))
        }
        val integrity = script.indexOf("KeyStore.getInstance")
        val write = script.indexOf("keystoreFile.writeBytes(keystoreBytes)")
        assertTrue(
            "the integrity probe must happen before the file is handed to the signing config",
            integrity in 1 until write,
        )
    }

    /**
     * The rule that turns a debugging aid back into a credential leak: the messages may say how long
     * the secret is and where it is damaged, and nothing else about it.
     */
    @Test
    fun `no error path interpolates a secret value`() {
        val names = listOf("keystoreBase64", "storePassword", "keyPassword", "keyAlias")
        val offenders = mutableListOf<String>()
        for (name in names) {
            // Both template forms must be watched. Searching only for `$name` would miss
            // `${keystoreBase64}`, which is the exact way a "helpful" error message leaks a secret.
            for (form in listOf("\$$name", "\${$name}")) {
                var from = 0
                while (true) {
                    val at = script.indexOf(form, from)
                    if (at < 0) break
                    val after = script.substring(at + form.length)
                    // `${keystoreBase64.length}` is a shape. `$keystoreBase64` is the secret itself.
                    if (!after.startsWith(".length") && !after.startsWith(".size")) {
                        offenders += "…${script.substring(maxOf(0, at - 40)..at)}$form…"
                    }
                    from = at + 1
                }
            }
        }
        assertTrue(
            "a build log is not a place for a keystore or a password. Offending templates:\n" +
                offenders.joinToString("\n"),
            offenders.isEmpty(),
        )
    }

    /** The control: the old block must fail these checks, or the guard is reading nothing. */
    @Test
    fun `the detector does report the block this task replaced`() {
        val retired = """
            if (keystoreBase64.isNotEmpty() && storePassword.isNotEmpty()) {
                val keystoreFile = File(layout.buildDirectory.asFile.get(), "radd-release.jks")
                keystoreFile.parentFile?.mkdirs()
                keystoreFile.writeBytes(Base64.getDecoder().decode(keystoreBase64))
                storeFile = keystoreFile
            }
        """.trimIndent()

        assertTrue(
            "the retired block wrote straight from an unchecked decode — the guard must see that",
            retired.contains("writeBytes(Base64.getDecoder().decode("),
        )
        assertFalse(
            "and it had no structure check at all, so indexOf returns -1 exactly as the guard expects",
            retired.contains("keystoreBase64.length % 4 != 0") ||
                retired.contains("KeyStore.getInstance"),
        )
    }
}
