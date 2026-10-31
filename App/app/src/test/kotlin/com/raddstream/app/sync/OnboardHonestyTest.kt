package com.raddstream.app.sync

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * OnboardHonestyTest — the census over the trial and profile-link surfaces.
 *
 * The rules below are not style preferences; each one is a defect that the compiler cannot see
 * and a device test on this host cannot run. They are all answerable from source text, so they
 * are answered from source text, and every refusal is paired with a positive control, because a
 * scan whose file moved or whose marker was renamed is green by accident — the exact failure mode
 * that let a `setSeekParameters` line vanish from a shipped player.
 *
 * What it protects, in order of how much it would cost a viewer:
 *  1. a request body that grew a `trial_days` or an `account_id` field, which the server would
 *     either ignore (so the app believes it granted something) or 400 (so a free trial becomes an
 *     error screen);
 *  2. copy that promises a protection the transport does not provide — this deployment is plain
 *     HTTP, and a modal that says "secure" while sending a 4-digit PIN in the clear is the harm;
 *  3. an identifier or a PIN reaching a log, a crash message or a committed fixture.
 *
 * Every parse here matches parentheses instead of cutting at the first closer. `substringBefore`
 * with one closer stops inside `@SerializedName("device_id")` and inside
 * `System.currentTimeMillis()`, which silently turns a census into a check of the first token of
 * a body — a guard that passes because it read nothing.
 */
class OnboardHonestyTest {

    private val wire = source("network", "models", "AccountWire.kt")
    private val api = source("network", "RaddStreamApi.kt")
    private val repository = source("sync", "SyncAccountRepository.kt")
    private val identity = source("data", "DeviceIdentity.kt")
    private val trialRules = source("sync", "DeviceTrial.kt")
    private val settingsStore = source("data", "ServerSettingsRepository.kt")

    /** 1: the trial request is one field, and it is the field the route reads. */
    @Test
    fun `the anonymous request carries device_id and has no way to ask for days`() {
        val body = modelBody("DeviceTrialRequest", wire)
        assertEquals(
            "device_id is the whole body; a client that sets its own trial length sets its own price",
            listOf("device_id"),
            WireField.findAll(body).map { it.groupValues[1] }.toList(),
        )
        assertFalse("no knob for the trial length may come back", body.contains("trial_days"))
        // Positive control: the payment body still carries its three fields, so the extractor is
        // reading whole request bodies and not returning the first line of each.
        assertEquals(
            listOf("plan", "method", "tid"),
            WireField.findAll(modelBody("PaymentRequest", wire)).map { it.groupValues[1] }.toList(),
        )
    }

    /** 2: nothing in the app may name the account it is writing to. */
    @Test
    fun `no request body carries an account_id`() {
        val code = codeOf(wire)
        val requestNames = Regex("""data class (\w*Request)\(""").findAll(code).map { it.groupValues[1] }.toList()
        assertTrue("positive control: request bodies were found: $requestNames", requestNames.size >= 5)
        val offenders = requestNames.filter { name ->
            val body = argsOf(code, "data class $name(")
            body.contains("account_id") || body.contains("accountId")
        }
        assertTrue(
            "the bearer key is what names the account; a body id is ignored server-side, so sending " +
                "one would be a claim that it does something: $offenders",
            offenders.isEmpty(),
        )
    }

    /** 3: the two new routes exist, and each is authenticated exactly as the server requires. */
    @Test
    fun `anonymous needs no bearer and profile-link cannot be called without one`() {
        val anonymous = argsOf(api, "suspend fun startDeviceTrial(")
        assertTrue("positive control: the trial route was parsed", anonymous.isNotBlank())
        assertFalse(
            "the route is unauthenticated by construction, and a client that sends a bearer here " +
                "would be describing the trial as a credential",
            anonymous.contains("Authorization"),
        )
        val link = argsOf(api, "suspend fun linkProfile(")
        assertTrue(
            "profile-link must present the key this server minted",
            link.contains("""@Header("Authorization") authorization: String?"""),
        )
        val call = argsOf(repository, ".linkProfile(")
        assertTrue(
            "and it is called with the stored key, never with an empty header: $call",
            call.contains("bearerHeader(key)"),
        )
    }

    /**
     * 4: the copy law, applied to the trial and link sentences the contract governs — the whole of
     * `AccountCardCopy` and the whole of the link dialog.
     *
     * It deliberately does NOT scan every string in `SettingsScreen.kt`: that file already carries
     * `Connection: … "secured with TLS."` on the branch that only composes when the server address
     * starts with `https`, which is a true sentence about a different subject, and a guard that
     * flags true copy is a guard the next lane deletes. The trial and the link never get to be
     * conditional about this: this deployment has no TLS.
     */
    @Test
    fun `the trial and link copy promises nothing the transport cannot keep`() {
        val banned = listOf(
            "secure", "secured", "securely", "encrypted", "encryption", "private",
            "only you can", "only you have", "device locked", "locked to your", "locked to this",
            "cannot be forged", "verified device", "proof of ownership", "hackers",
        )
        val scope = codeOf(source("viewmodel", "SettingsViewModel.kt"))
            .substringAfter("object AccountCardCopy {")
            .substringBefore("\n}") +
            codeOf(source("ui", "screens", "SettingsScreen.kt"))
                .substringAfter("internal fun ProfileLinkDialog(")
        assertTrue("positive control: the copy owner and the dialog were both located", scope.length > 2_000)
        val literals = StringLiteral.findAll(scope).map { it.groupValues[1] }.toList()
        assertTrue(
            "positive control: sentences were actually read — found ${literals.size}",
            literals.size >= 15 && literals.any { it.contains("Link and claim the day") },
        )
        val offenders = literals.filter { literal ->
            val lower = literal.lowercase()
            banned.any { lower.contains(it) }
        }
        assertTrue(
            "a wrong claim here is a viewer handing a PIN to a wire-tap because a sentence told " +
                "them not to worry: $offenders",
            offenders.isEmpty(),
        )
        // And the sentences the law exists to keep honest must say the true thing, not merely avoid
        // the false one. A guard that only bans words is satisfied by silence. Matching runs of
        // literals joined in source order, because a sentence that is long enough to say all of
        // this is written across concatenated fragments.
        val joined = literals.joinToString("")
        assertTrue(
            "the modal must say the number and PIN cross this host in the clear",
            joined.contains("in the clear"),
        )
        assertTrue(
            "and the trial must be described as a count per install, not as a lock or an identity",
            joined.contains("per install") && joined.contains("not a lock"),
        )
        assertTrue(
            "the pre-existing honest sentence about a phone number stays true here too",
            joined.contains("can already derive the same sync key"),
        )
        assertTrue(
            "a wrongly-flagged deployment keeps its escape hatch, as the maintenance notice does",
            joined.contains("Server card"),
        )
        assertTrue(
            "and the limiter, not the app, is what stands between a 4-digit PIN and a guesser",
            joined.contains("Do not enter a PIN you also use somewhere else."),
        )
    }

    /** The census above must be capable of failing, so it is shown one word to catch. */
    @Test
    fun `the copy census sees a banned word in a string and ignores one in a comment`() {
        val forbidden = "sec" + "ure"
        val sample = "val claim = \"Your key is " + forbidden + "\" " +
            "// a comment may say " + forbidden + " all it likes\n"
        val hits = StringLiteral.findAll(codeOf(sample)).map { it.groupValues[1] }.toList()
            .filter { it.lowercase().contains(forbidden) }
        assertEquals("exactly the string literal is copy: $hits", 1, hits.size)
        assertEquals("Your key is " + forbidden, hits.first())
    }

    /** 5: a device id and a PIN are never written down anywhere this app runs. */
    @Test
    fun `no identifier or credential reaches a log`() {
        val logging = Regex("""(?i)\b(Log\.\w|android\.util\.Log|System\.out|System\.err|printLine)""")
        val files = listOf(
            "DeviceIdentity.kt" to identity,
            "SyncAccountRepository.kt" to repository,
            "DeviceTrial.kt" to trialRules,
            "ServerSettingsRepository.kt" to settingsStore,
        )
        val offenders = files.map { (name, text) ->
            name to logging.findAll(codeOf(text)).map { match -> match.value }.toList()
        }.filter { entry -> entry.second.isNotEmpty() }
        assertTrue(
            "no path in the trial or account layer may print a value: ${offenders.map { entry -> entry.first }}",
            offenders.isEmpty(),
        )
        assertFalse("and nothing imports a logger at all", identity.contains("android.util.Log"))

        // The identifier's own containment: the raw ANDROID_ID is read once and goes straight into
        // the hash, with nothing else to do with it.
        val collector = identity.substringAfter("fun trialDeviceId(")
        assertEquals(
            "positive control: exactly one Settings.Secure read, and it feeds the hash",
            1,
            Regex("""Settings\.Secure\.getString""").findAll(collector).count(),
        )
        assertTrue(collector.contains("DeviceTrial.deviceId("))
        assertFalse(
            "the plaintext identifier must never be returned, stored or compared on its own",
            Regex("""return\s+androidId""").containsMatchIn(collector),
        )
    }

    /**
     * 6: the countdown is stored from the server's answer and nowhere recomputed. This is the one
     * place the app could quietly invent days, so it is pinned as text: [saveDeviceTrial] takes the
     * value the wire model carried and the clock only stamps WHEN it was read.
     */
    @Test
    fun `the stored countdown is the number from the server, not one this device multiplied`() {
        val args = argsOf(repository, "settingsRepository.saveDeviceTrial(")
        val parts = args.split(",").map { it.trim() }
        assertEquals("exactly two arguments: $args", 2, parts.size)
        assertEquals("the seconds the server said, or nothing", "read.secondsRemaining", parts[0])
        assertEquals(
            "with the instant they were read, so the countdown is a subtraction and not a grant",
            "System.currentTimeMillis()",
            parts[1],
        )
        assertTrue(
            "and the trial's own key arrives only with the answer that minted it",
            repository.contains("settingsRepository.saveSyncKey(key)"),
        )
    }

    /** 7: a trial that outlived its credential must not outlive the badge either. */
    @Test
    fun `signing out drops the trial clock with the key`() {
        val signOut = blockOf(repository, "private suspend fun signOutLocally() {")
        assertTrue("positive control: signOutLocally was parsed", signOut.contains("saveSyncKey(null)"))
        assertTrue(
            "a countdown with no key to spend it on is a claim about an entitlement the app cannot " +
                "reach",
            signOut.contains("clearDeviceTrial()"),
        )
        val clear = blockOf(settingsStore, "suspend fun clearDeviceTrial() {")
        assertTrue(
            "and the one-shot reveal flag goes too, so a later sign-in cannot re-show a key",
            listOf("TRIAL_SECONDS_REMAINING_KEY", "TRIAL_RECORDED_AT_MS_KEY", "TRIAL_KEY_UNSEEN_KEY")
                .all { clear.contains(it) },
        )
    }

    /** 8: the pure half stays pure — the rules this suite reads are testable without a device. */
    @Test
    fun `the trial rules import no Android`() {
        val imports = Regex("""^import (.*)$""", RegexOption.MULTILINE)
            .findAll(trialRules)
            .map { it.groupValues[1] }
            .toList()
        assertTrue("positive control: the rule file has imports", imports.isNotEmpty())
        val android = imports.filter { it.startsWith("android") || it.startsWith("androidx") }
        assertTrue("the rule file must run on this host's JVM: $android", android.isEmpty())
        assertTrue(
            "positive control: the Android-coupled reader is a different file",
            identity.contains("android.provider.Settings"),
        )
    }

    // ── helpers ─────────────────────────────────────────────────────────────────

    private fun source(vararg path: String): String {
        val parts = listOf("src/main/kotlin/com/raddstream/app") + path
        val file = File(parts.joinToString("/"))
        assertTrue("${file.path} is gone — this guard has been looking at nothing", file.isFile)
        return file.readText()
    }

    /** The field list of one wire model, comments stripped so a KDoc word cannot match. */
    private fun modelBody(name: String, text: String): String {
        val code = codeOf(text)
        val body = argsOf(code, "data class $name(")
        assertTrue("positive control: $name is still declared where the test expects", body.isNotBlank())
        return body
    }

    /**
     * Everything between the parentheses of the first call written as [marker] — where [marker]
     * itself ends in the opening paren — with the nesting matched. A test that cannot say which
     * closer belongs to the call it is reading has no business refusing a body.
     */
    private fun argsOf(text: String, marker: String): String {
        val at = text.indexOf(marker)
        assertTrue("positive control: `$marker` is still in this file", at >= 0)
        val out = StringBuilder()
        var depth = 1
        var i = at + marker.length
        while (i < text.length && depth > 0) {
            when (val c = text[i]) {
                '(' -> { depth++; out.append(c) }
                ')' -> {
                    depth--
                    if (depth > 0) out.append(c)
                }
                else -> out.append(c)
            }
            i++
        }
        assertEquals("positive control: the text after `$marker` closes its paren", 0, depth)
        return out.toString()
    }

    /**
     * The body of the first block written as [marker], where [marker] ends in the opening brace.
     * Same rule as [argsOf] and why: reading to the first closer would stop at the end of the first
     * nested lambda and call that the whole function.
     */
    private fun blockOf(text: String, marker: String): String {
        val at = text.indexOf(marker)
        assertTrue("positive control: `$marker` is still in this file", at >= 0)
        val out = StringBuilder()
        var depth = 1
        var i = at + marker.length
        while (i < text.length && depth > 0) {
            val c = text[i]
            when (c) {
                '{' -> { depth++; out.append(c) }
                '}' -> {
                    depth--
                    if (depth > 0) out.append(c)
                }
                else -> out.append(c)
            }
            i++
        }
        assertEquals("positive control: the block after `$marker` closes", 0, depth)
        return out.toString()
    }

    /**
     * String literals from Kotlin code with comments removed. Comments are excluded on purpose:
     * this test is about what a viewer reads, and a KDoc that names a banned word to forbid it
     * (as several do here) must not make the census red.
     */
    private fun codeOf(text: String): String {
        val out = StringBuilder()
        var i = 0
        var inLine = false
        var blockDepth = 0
        var inString = false
        while (i < text.length) {
            val c = text[i]
            val next = text.getOrNull(i + 1)
            when {
                inLine -> if (c == '\n') { inLine = false; out.append(c) }
                blockDepth > 0 -> when {
                    c == '/' && next == '*' -> { blockDepth++; i++ }
                    c == '*' && next == '/' -> { blockDepth--; i++ }
                }
                inString -> {
                    out.append(c)
                    if (c == '\\') { out.append(next ?: ' '); i++ } else if (c == '"') inString = false
                }
                c == '/' && next == '/' -> inLine = true
                c == '/' && next == '*' -> { blockDepth = 1; i++ }
                c == '"' -> { inString = true; out.append(c) }
                else -> out.append(c)
            }
            i++
        }
        return out.toString()
    }

    private companion object {
        /** One `@SerializedName("wire")` annotation, read for the name it stamps. */
        val WireField = Regex("""@SerializedName\("([^"]+)"\)""")

        /** One ordinary (non-raw) Kotlin string literal, read for what it says. */
        val StringLiteral = Regex("\"([^\"]*)\"")
    }
}
