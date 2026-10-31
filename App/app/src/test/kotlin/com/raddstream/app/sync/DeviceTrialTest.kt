package com.raddstream.app.sync

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The trial and the profile link are built on numbers that live on a machine this app does not
 * own, in a file (`Fast_Fetch/accounts.py`) that another lane edits. Every bound asserted here is
 * therefore read from that file as well as from this one: a client that outgrows the server's
 * grammar is a client that sends requests the server answers 400 to, and for a PIN a 400 that
 * charges the viewer's own attempt bucket is how a typo turns into a lockout.
 *
 * `SyncContractTest` covers the credential rules; nothing here duplicates it.
 */
class DeviceTrialTest {

    // ── the device id ────────────────────────────────────────────────────────────

    @Test
    fun `one device always derives the same id and two devices never do`() {
        val first = DeviceTrial.deviceId("android-id-aaaa", "qcom", "BUILD-1")
        val again = DeviceTrial.deviceId("android-id-aaaa", "qcom", "BUILD-1")
        assertEquals(
            "a reinstall must not look like a new device, or the ledger's whole purpose is lost",
            first,
            again,
        )
        assertNotNull(first)
        assertNotEquals(first, DeviceTrial.deviceId("android-id-bbbb", "qcom", "BUILD-1"))
        assertNotEquals(first, DeviceTrial.deviceId("android-id-aaaa", "qcom", "BUILD-2"))
        assertNotEquals(first, DeviceTrial.deviceId("android-id-aaaa", "mt6755", "BUILD-1"))
    }

    @Test
    fun `the id is 64 lowercase hex characters and always inside the server's device-id grammar`() {
        val id = DeviceTrial.deviceId("android-id-aaaa", "qcom", "BUILD-1")!!
        assertTrue("hex, not base64: $id", id.all { it in 'a'..'f' || it in '0'..'9' })
        assertEquals("SHA-256 rendered as hex is 64 characters", 64, id.length)
        assertTrue(
            "the derivation must be storable by the server it is sent to",
            DeviceTrial.isStorableDeviceId(id),
        )
    }

    @Test
    fun `a device that cannot name itself gets no id rather than a made-up one`() {
        assertNull(DeviceTrial.deviceId(null, "qcom", "BUILD-1"))
        assertNull(DeviceTrial.deviceId("", "qcom", "BUILD-1"))
        assertNull(DeviceTrial.deviceId("   ", "qcom", "BUILD-1"))
        // Surrounding spaces are the Android ROM's, not the viewer's: trim, then hash.
        assertEquals(
            DeviceTrial.deviceId("abc123", "qcom", "BUILD-1"),
            DeviceTrial.deviceId("  abc123  ", "qcom", "BUILD-1"),
        )
    }

    @Test
    fun `the shape checks match the bounds the server actually enforces`() {
        val server = Regex(
            """^(MIN_DEVICE_ID_CHARS|MAX_DEVICE_ID_CHARS|MIN_PIN_DIGITS|MAX_PIN_DIGITS|""" +
                """MIN_PHONE_DIGITS|MAX_PHONE_DIGITS|MAX_PROFILE_NAME_CHARS|DAY_SECONDS)""" +
                """\s*=\s*([0-9_.]+)""",
            RegexOption.MULTILINE,
        )
            .findAll(accountsSource())
            .associate { it.groupValues[1] to it.groupValues[2].replace("_", "").removeSuffix(".") }
        assertTrue(
            "positive control: the server file was parsed, not skipped",
            server.keys.containsAll(
                listOf(
                    "MIN_DEVICE_ID_CHARS", "MAX_DEVICE_ID_CHARS", "MIN_PIN_DIGITS", "MAX_PIN_DIGITS",
                    "MIN_PHONE_DIGITS", "MAX_PHONE_DIGITS", "MAX_PROFILE_NAME_CHARS", "DAY_SECONDS",
                ),
            ),
        )
        assertEquals(server["MIN_DEVICE_ID_CHARS"]!!.toInt(), DeviceTrial.MIN_DEVICE_ID_CHARS)
        assertEquals(server["MAX_DEVICE_ID_CHARS"]!!.toInt(), DeviceTrial.MAX_DEVICE_ID_CHARS)
        assertEquals(server["MIN_PIN_DIGITS"]!!.toInt(), DeviceTrial.MIN_PIN_DIGITS)
        assertEquals(server["MAX_PIN_DIGITS"]!!.toInt(), DeviceTrial.MAX_PIN_DIGITS)
        assertEquals(server["MIN_PHONE_DIGITS"]!!.toInt(), DeviceTrial.MIN_PHONE_DIGITS)
        assertEquals(server["MAX_PHONE_DIGITS"]!!.toInt(), DeviceTrial.MAX_PHONE_DIGITS)
        assertEquals(server["MAX_PROFILE_NAME_CHARS"]!!.toInt(), DeviceTrial.MAX_PROFILE_NAME_CHARS)
        assertEquals(server["DAY_SECONDS"]!!.toDouble(), DeviceTrial.DAY_SECONDS, 0.0)
    }

    @Test
    fun `a device id the server could not store is refused before it is sent`() {
        assertTrue(DeviceTrial.isStorableDeviceId("deadbeef"))
        assertTrue(DeviceTrial.isStorableDeviceId("a:b_c-d.e:f0"))
        assertFalse("too short for a primary key", DeviceTrial.isStorableDeviceId("deadbee"))
        assertFalse("over the row bound", DeviceTrial.isStorableDeviceId("x".repeat(129)))
        assertFalse("whitespace has no business in a key", DeviceTrial.isStorableDeviceId("dead beef"))
        assertFalse("a slash would break a path", DeviceTrial.isStorableDeviceId("dead/beef1"))
        assertFalse("a quote would break a header", DeviceTrial.isStorableDeviceId("dead\"beef1"))
        assertFalse("and a non-ASCII letter is not an installation id", DeviceTrial.isStorableDeviceId("deadbéef1"))
        assertFalse(DeviceTrial.isStorableDeviceId(null))
    }

    // ── the countdown ────────────────────────────────────────────────────────────

    @Test
    fun `the countdown is the server's seconds minus the time this device has held them`() {
        assertEquals(
            3_600.0,
            DeviceTrial.secondsRemaining(3_660.0, storedAtMs = 1_000L, nowMs = 61_000L),
            0.0,
        )
        assertEquals(
            "a clock that moved backwards while the app was closed must not buy time back",
            3_660.0,
            DeviceTrial.secondsRemaining(3_660.0, storedAtMs = 10_000L, nowMs = 1_000L),
            0.0,
        )
        assertEquals("a finished trial is zero, not a debt", 0.0, DeviceTrial.secondsRemaining(10.0, 0L, 60_000L), 0.0)
        assertEquals(0.0, DeviceTrial.secondsRemaining(-5.0, 0L, 60_000L), 0.0)
        assertEquals(0.0, DeviceTrial.secondsRemaining(Double.NaN, 0L, 60_000L), 0.0)
    }

    @Test
    fun `a partial day displays as a day and only a real zero displays as none`() {
        assertEquals(0, DeviceTrial.daysRemaining(0.0))
        assertEquals(1, DeviceTrial.daysRemaining(1.0))
        assertEquals(1, DeviceTrial.daysRemaining(86_400.0))
        assertEquals(2, DeviceTrial.daysRemaining(86_400.1))
        assertEquals(3, DeviceTrial.daysRemaining(259_200.0))
        // A negative input cannot reach this function — secondsRemaining clamps to 0 first — but
        // if one ever did, the answer must be "over", never a borrowed day the server did not grant.
        assertEquals(0, DeviceTrial.daysRemaining(-1.0))
        assertEquals(0, DeviceTrial.daysRemaining(Double.NaN))
    }

    /**
     * The clamp above is the unreachable branch, and this pins the reachable one:
     * the client must never be the thing that decides how long a trial is. The server's own note
     * (`accounts_api.py:494`) is that a client able to set its own trial length is a client able to
     * set its own price.
     */
    @Test
    fun `nothing on this side multiplies days into a clock to grant a trial`() {
        val repo = File("src/main/kotlin/com/raddstream/app")
        assertTrue("positive control: the source tree is where the test says it is", repo.isDirectory)
        val offenders = repo.walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .filter { file ->
                val text = stripComments(file.readText())
                Regex("""TRIAL_DAYS""").containsMatchIn(text) ||
                    Regex("""currentTimeMillis\(\)\s*\+\s*[0-9_]+\s*\*\s*86_?400""").containsMatchIn(text) ||
                    Regex("""secondsRemaining\s*=\s*[0-9_]+\s*\*""").containsMatchIn(text)
            }
            .map { it.name }
        assertTrue("a locally-granted day is a day nobody issued: $offenders", offenders.isEmpty())
    }

    @Test
    fun `a trial answer is only readable when the server actually sent a countdown`() {
        val usable: (String?) -> Boolean = { key -> key == "0123456789abcdef" }
        assertNull(DeviceTrial.trialAnswer(null, null, usable))
        assertNull("a non-finite countdown is not a zero-second trial", DeviceTrial.trialAnswer(Double.NaN, null, usable))
        assertNull("and a negative one is not a grant", DeviceTrial.trialAnswer(-1.0, null, usable))
        val expired = DeviceTrial.trialAnswer(0.0, null, usable)
        assertNotNull("an expired trial IS an answer, and re-asking it every launch buys nothing", expired)
        assertEquals(0.0, expired!!.secondsRemaining, 0.0)
        assertNull(expired.keyToReveal)
        assertEquals(
            "a minted key travels with the answer that minted it",
            "0123456789abcdef",
            DeviceTrial.trialAnswer(100.0, "0123456789abcdef", usable)?.keyToReveal,
        )
        assertNull(
            "a key too short to be one is dropped, not stored",
            DeviceTrial.trialAnswer(100.0, "tiny", usable)?.keyToReveal,
        )
    }

    // ── the profile fields ───────────────────────────────────────────────────────

    @Test
    fun `the name rule is the server's rule`() {
        assertNull(DeviceTrial.nameError("Rehan"))
        assertNull(DeviceTrial.nameError("  Ali  Khan  "))
        assertNotNull("an empty name is refused by accounts._check_profile_name, so it must be by us too", DeviceTrial.nameError("   "))
        assertNotNull(DeviceTrial.nameError(null))
        assertNotNull(DeviceTrial.nameError("x".repeat(DeviceTrial.MAX_PROFILE_NAME_CHARS + 1)))
        assertNull(DeviceTrial.nameError("x".repeat(DeviceTrial.MAX_PROFILE_NAME_CHARS)))
    }

    @Test
    fun `the phone rule counts digits and does not demand a Pakistani shape`() {
        assertNull(DeviceTrial.phoneError("03001234567"))
        assertNull(DeviceTrial.phoneError("+92 300-1234567"))
        assertNull("the server's grammar is 8..16 ASCII digits, so a foreign number can still link", DeviceTrial.phoneError("+1 555 0100"))
        assertNotNull("seven digits is under the floor", DeviceTrial.phoneError("555-010"))
        assertNotNull(DeviceTrial.phoneError("1".repeat(DeviceTrial.MAX_PHONE_DIGITS + 1)))
        assertNotNull(DeviceTrial.phoneError(null))
        assertNotNull("letters are not digits even when a keyboard typed them", DeviceTrial.phoneError("0300-ABCD"))
    }

    /**
     * The server checks a PIN against `[0-9]+`, not against Unicode's opinion of a digit
     * (`accounts.py:1303`), because two visually identical PINs must not become two digests.
     * `Char.isDigit()` would accept both of the strings below and hash them happily.
     */
    @Test
    fun `a PIN is ASCII digits and nothing that merely looks like a digit`() {
        assertNull(DeviceTrial.pinError("1234"))
        assertNull(DeviceTrial.pinError("12345678"))
        assertNotNull("three is below the floor", DeviceTrial.pinError("123"))
        assertNotNull(DeviceTrial.pinError("123456789"))
        assertNotNull(DeviceTrial.pinError("12a4"))
        assertNotNull(DeviceTrial.pinError("٣٣٣٣"))
        assertNotNull(DeviceTrial.pinError("²³²³"))
        assertNotNull(DeviceTrial.pinError(null))
    }

    // ── the 401 that is not a sign-out ───────────────────────────────────────────

    @Test
    fun `a wrong PIN is a wrong PIN and never a dead key`() {
        assertEquals(LinkRefusal.WRONG_PIN, DeviceTrial.profileLinkVerdict(401, "unauthorised"))
        assertEquals(LinkRefusal.DEAD_KEY, DeviceTrial.profileLinkVerdict(404, "not_found"))
        assertEquals(LinkRefusal.THROTTLED, DeviceTrial.profileLinkVerdict(429, "rate_limited"))
        assertEquals(LinkRefusal.BAD_INPUT, DeviceTrial.profileLinkVerdict(400, "invalid_request"))
        assertEquals(LinkRefusal.BAD_INPUT, DeviceTrial.profileLinkVerdict(400, "weak_pin"))
        assertEquals(LinkRefusal.OFFLINE, DeviceTrial.profileLinkVerdict(500, null))
        assertEquals(LinkRefusal.OFFLINE, DeviceTrial.profileLinkVerdict(0, null))

        // The control that makes this suite worth running: the shared table would sign the viewer
        // out on the same answer. If SyncContract's rule ever changes, this proves the difference
        // is still the one DeviceTrial exists to make.
        assertEquals(
            "the generic verdict reads this 401 as a dead credential — which is why profile-link " +
                "has its own table",
            ServerVerdict.SIGN_OUT,
            SyncContract.verdictOf(401, "unauthorised", hadWorkRef = false),
        )
    }

    // ── the sentences ────────────────────────────────────────────────────────────

    @Test
    fun `a one-day trial says day and not days`() {
        assertEquals("Free VIP days are running on this install — 1 day left.", AccountCardCopy.trialActive(1))
        assertTrue(AccountCardCopy.trialActive(2).endsWith("2 days left."))
        assertFalse(AccountCardCopy.trialActive(2).contains("1 day left"))
    }

    @Test
    fun `the link answers name the day and the account it was granted on`() {
        assertTrue(AccountCardCopy.linkSentence(true).contains("One free day was added"))
        assertTrue(
            "a 200 after a 201 is not a failure, and must not read like one",
            AccountCardCopy.linkSentence(false).contains("No free day was added"),
        )
        assertTrue(
            "a wrong PIN says the key survived, because the viewer needs to know they did not lose " +
                "their library",
            AccountCardCopy.linkRefusalSentence(LinkRefusal.WRONG_PIN).contains("still signed in"),
        )
    }

    /** Walks up from the Gradle module directory to the monorepo's backend source. */
    private fun accountsSource(): String {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            val candidate = File(dir, "Fast_Fetch/accounts.py")
            if (candidate.isFile) return candidate.readText()
            dir = dir.parentFile
        }
        error("no Fast_Fetch/accounts.py above ${File("").absolutePath}")
    }

    private fun stripComments(text: String): String {
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

    /** JUnit's Assert.assertNotEquals takes objects, and Kotlin's smart cast wants the call here. */
    private fun assertNotEquals(unexpected: String?, actual: String?) {
        assertFalse("the two values must differ: $actual", unexpected == actual)
    }
}
