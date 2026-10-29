package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Nothing in this app may turn a phone number into a credential.
 *
 * Why a scan and not a behaviour test: the derivation this refuses produced a *correct* answer.
 * `base64url(SHA-256("phone-sync/v1|03XXXXXXXXX"))[:16]` opened the library it named, on every
 * device, deterministically — which is precisely the defect, because a Pakistani mobile number is
 * public information about a person and `POST /api/v2/account` reopens whatever account a presented
 * key names. Sixteen characters also happens to be the server's own `MIN_SYNC_KEY_CHARS`, so the
 * shape check written to reject weak keys could not tell this one from a random token. No amount of
 * driving that function from a JVM test says "this is unsafe": the only test that can is one that
 * refuses the code shape itself.
 *
 * The rule is therefore a refusal over `app/src/main`, plus the two controls that make the refusal
 * mean something:
 *  - the detector is run against the retired derivation, held here as text, and it MUST report a
 *    violation. Without that, a scanner that matches nothing — a bad regex, an empty file list, a
 *    comment stripper that ate every source — is green forever, which is the failure mode this
 *    repo has been bitten by before.
 *  - the same detector is run over a comment that merely *names* `MessageDigest`, and must report
 *    nothing, so prose about what was deleted (which this app now carries in three files) is not
 *    mistaken for the thing itself.
 *
 * What is deliberately NOT here: any device identifier. `ANDROID_ID`, an advertising id, Play
 * Integrity or any attestation is absent from this app on purpose — a self-reported id cannot gate
 * anything an installer can forge, and shipping a gate that is known-bypassable while describing it
 * as a guarantee is worse than shipping none. See `docs/IDENTITY_AND_TRIAL_ABUSE.md`.
 */
class PhoneCredentialGuardTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val mainSources: List<File> by lazy {
        File(repoRoot, "App/app/src/main/kotlin")
            .walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .toList()
            .also { assertTrue("the scan read no Kotlin at all: $it", it.isNotEmpty()) }
    }

    // ── the refusal ───────────────────────────────────────────────────────────

    @Test
    fun `no code path in the app derives a credential from a phone number`() {
        val findings = mainSources.flatMap { violations(it.readText(), it.name) }
        assertEquals(
            "a phone number must never be an input to a credential. Found:\n" +
                findings.joinToString("\n"),
            0,
            findings.size,
        )
    }

    @Test
    fun `the sync key is only ever a key the server minted`() {
        val contract = File(
            repoRoot,
            "App/app/src/main/kotlin/com/raddstream/app/sync/SyncContract.kt",
        )
        assertTrue("the sign-in rules moved away from SyncContract.kt", contract.isFile)
        val code = withoutComments(contract.readText())

        val body = functionBody(code, "quickLoginKey")
        assertTrue("quickLoginKey disappeared — the card would be signing in with something", body != null)
        val text = body!!
        assertFalse(
            "a credential must not be normalized from a number: quickLoginKey calls " +
                "normalizePakistaniMobile again",
            text.contains("normalizePakistaniMobile"),
        )
        assertFalse("quickLoginKey must send a key, not a hash", text.contains("MessageDigest"))
        assertFalse("quickLoginKey must not encode bytes into a key", text.contains("base64Url"))
        // Both surviving paths, named so a rewrite that silently drops one is caught here: the
        // server-minted 16-character key, and the 43-character key older releases minted.
        assertTrue("the 16-character minted key path is gone", text.contains("isShortSyncKey"))
        assertTrue("the legacy 43-character key path is gone", text.contains("LEGACY_SYNC_KEY_CHARS"))
    }

    @Test
    fun `the public namespace that made the phone space enumerable is gone`() {
        val findings = mainSources.flatMap { file ->
            withoutComments(file.readText())
                .lines()
                .filter { PHONE_NAMESPACE in it }
                .map { "${file.name}: $it" }
        }
        assertEquals(
            "PHONE_KEY_NAMESPACE ships in the APK and authenticated nobody. It must not come back:\n" +
                findings.joinToString("\n"),
            0,
            findings.size,
        )
    }

    /**
     * The number's remaining job, pinned where it must be: it is a label. It is written to the
     * app's own preferences and to no request, and the account card says so instead of warning
     * about a derivation that no longer exists.
     */
    @Test
    fun `a phone number reaches the device only as a label`() {
        val contract = File(
            repoRoot,
            "App/app/src/main/kotlin/com/raddstream/app/sync/SyncContract.kt",
        ).readText()
        val labelBody = functionBody(withoutComments(contract), "accountLabel")
        assertTrue("accountLabel is the only place a number may go", labelBody != null)
        assertTrue(
            "a label must canonicalize the number it is shown for",
            labelBody!!.contains("normalizePakistaniMobile"),
        )
        assertFalse("a label is not a hash input", labelBody.contains("MessageDigest"))

        val settings = File(
            repoRoot,
            "App/app/src/main/kotlin/com/raddstream/app/data/ServerSettingsRepository.kt",
        ).readText()
        assertTrue(
            "the label is stored as plain display data",
            withoutComments(settings).contains("stringPreferencesKey(\"account_label\")"),
        )

        val screen = File(
            repoRoot,
            "App/app/src/main/kotlin/com/raddstream/app/ui/screens/SettingsScreen.kt",
        ).readText()
        // The obsolete warning was honest while the feature existed. Keeping it would describe a
        // derivation this build cannot perform, so a reader of the card would look for a key that
        // is computed from their number and never find one.
        assertFalse(
            "the card still warns about a derivation this app deleted",
            screen.contains("can derive the same key"),
        )
        assertTrue(
            "the card must still say the key is what the account is worth",
            withoutComments(screen).contains("only as strong as"),
        )
    }

    // ── the controls: a refusal that cannot fire is not a guard ───────────────

    /**
     * The retired code, verbatim in shape, as the detector's own input. If this stops reporting a
     * violation, the guard above has gone blind — a broken stripper, a typo in a marker, or sources
     * that moved out of the walked directory — and would stay green forever.
     */
    @Test
    fun `the detector does report the derivation this task deleted`() {
        val retired = """
            object SyncContract {
                const val PHONE_KEY_NAMESPACE = "phone-sync/v1"
                fun quickLoginKey(raw: String?): String? {
                    val text = raw?.trim() ?: return null
                    normalizePakistaniMobile(text)?.let { phone ->
                        val digest = MessageDigest.getInstance("SHA-256")
                            .digest(("phone-sync/v1|" + phone).toByteArray(Charsets.UTF_8))
                        return base64Url(digest.copyOf(12))
                    }
                    if (isShortSyncKey(text)) return text
                    return null
                }
            }
        """.trimIndent()

        val findings = violations(retired, "retired.kt")
        assertTrue(
            "the guard must refuse the phone-to-credential derivation it exists to refuse",
            findings.isNotEmpty(),
        )
        assertTrue(
            "and say which function did it, so the reader is not hunting",
            findings.any { "quickLoginKey" in it },
        )
    }

    /** The other half of the same control: prose is not code, and must not trip the detector. */
    @Test
    fun `the detector does not report a comment that only names the derivation`() {
        val prose = """
            /**
             * It used to: base64url(SHA-256("phone-sync/v1|03XXXXXXXXX"))[:16]. That derivation
             * is deleted, not disabled.
             */
            object SyncContract {
                fun quickLoginKey(raw: String?): String? = raw
            }
        """.trimIndent()

        assertTrue(
            "the stripper must actually strip: MessageDigest survived into the scanned text",
            !withoutComments(prose).contains("MessageDigest"),
        )
        assertEquals(
            "documenting the retired defect is not the defect",
            0,
            violations(prose, "prose.kt").size,
        )
    }

    @Test
    fun `positive controls — the markers are findable in the real sources`() {
        // Without these, every assertion above could go green because the scan read nothing: a
        // moved file, a renamed rule, a stripper that returns an empty string.
        val contract = File(
            repoRoot,
            "App/app/src/main/kotlin/com/raddstream/app/sync/SyncContract.kt",
        ).readText()
        val code = withoutComments(contract)
        assertTrue("normalizePakistaniMobile must still exist as a display rule", code.contains("normalizePakistaniMobile"))
        assertTrue("the card must still have a credential path", code.contains("isShortSyncKey"))
        assertTrue(
            "the account label must still be written by the settings store",
            code.isNotEmpty() && withoutComments(
                File(
                    repoRoot,
                    "App/app/src/main/kotlin/com/raddstream/app/data/ServerSettingsRepository.kt",
                ).readText(),
            ).contains("saveAccountLabel"),
        )
        assertTrue(
            "the walked source tree must still contain the file the rule is about",
            mainSources.any { it.name == "SyncContract.kt" },
        )
    }

    // ── the scanner ───────────────────────────────────────────────────────────

    /**
     * Termination, asserted at the primitive. The first version of `literalEnd` could return the
     * index it was given — a `"` is legal *inside* a Kotlin string, so an interpolated
     * `"…${ string("x") }…` desynced the walk into a phantom string that reached a newline and
     * advanced nothing. Every caller is a `while`, so the symptom was a test task that never
     * finished, and the only thing CI had to say about it was the job timeout: two runs of this
     * branch died at 45 minutes with zero tests executed. A hang is indistinguishable from a slow
     * build, so the guard has to be a return value rather than a passing test.
     */
    @Test
    fun `the literal scanner strictly advances on every quote in every real source`() {
        val offenders = mutableListOf<String>()
        mainSources.forEach { file ->
            val text = file.readText()
            for (i in text.indices) {
                val c = text[i]
                if (c != '"' && c != '\'') continue
                val end = literalEnd(text, i, c)
                if (end <= i) offenders += "${file.name}:$i made no progress"
            }
        }
        assertEquals(
            "literalEnd must consume at least one character or every walk over it can spin:\n" +
                offenders.take(20).joinToString("\n"),
            0,
            offenders.size,
        )
        // Positive control for the control: the scan is only meaningful if real sources were
        // actually scanned and they really do contain quotes.
        assertTrue(
            "no source contained a single quote — the scan above proved nothing",
            mainSources.any { it.readText().contains('"') },
        )
    }

    @Test
    fun `an unterminated double quote closes at the newline rather than at the end of the file`() {
        val line = "val suffix = \"network.user_agent"
        val text = line + "\nfun quickLoginKey(raw: String?): String? {\n    return raw\n}\n"
        val at = text.indexOf('"')
        val end = literalEnd(text, at, '"')
        assertTrue("the scan must advance", end > at)
        assertTrue(
            "and it must stop at the line break, not swallow the rest of the file",
            end <= line.length + 1,
        )
        // The declaration on the following lines must still be walked. A scanner that ate to EOF
        // would leave the stripped text intact but attribute nothing to anybody — a guard that
        // quietly stops seeing functions reports zero violations on a file full of them.
        val found = functions(withoutComments(text)).map { it.first }
        assertTrue("the declarations after that line were not walked: $found", found.contains("quickLoginKey"))
    }

    @Test
    fun `a raw string closes at the last three quotes of the run, not the first three`() {
        // Kotlin: three opening quotes, x, then FOUR closing quotes is a raw string whose content
        // is x plus one quote. Closing at the first three returns control to code context one
        // quote early, and that stray quote opens the next phantom literal — the same class of bug
        // CommentBalanceTest documents for the stripper.
        val src = TRIPLE + "x" + TRIPLE + "\""
        assertEquals(src.length, literalEnd(src, 0, '"'))
        // One and two quotes inside a raw string are content, not a terminator.
        val inner = TRIPLE + "a" + "\"" + "b" + TRIPLE
        assertEquals(inner.length, literalEnd(inner, 0, '"'))
    }

    @Test
    fun `the scanner walks the interpolated quoting shape that hung the runner`() {
        // Brand.kt lines 140-142 are the construct that hung both runs: a double-quoted string
        // whose interpolation calls string("…") and closes on the NEXT line, so line 141 carries an
        // odd number of quotes and the naive walk opens a phantom literal there. Scanning the real
        // file must return — and return with code left in it, not with the file eaten as a string.
        val brand = File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/brand/Brand.kt")
        assertTrue("Brand.kt moved — the regression this case guards is no longer represented", brand.isFile)
        val stripped = withoutComments(brand.readText())
        val declared = functions(stripped).map { it.first }
        assertTrue(
            "the walk lost Brand.kt's own declarations, so it mis-scanned its literals: $declared",
            declared.contains("load"),
        )
        assertTrue(
            "only comments may be removed; a code token must still be present",
            stripped.contains("BuildConfig"),
        )
    }

    /**
     * Every place in [code] where a digest is computed inside a function that also handles a
     * phone, plus every live use of the public namespace. Reported as `file: function: evidence`.
     *
     * The check is per-function rather than per-file on purpose: a file may legitimately import a
     * hashing primitive for a cache key and also mention a phone number in a label. What is
     * forbidden is the two meeting inside one decision — which is exactly the shape the retired
     * derivation had.
     */
    private fun violations(code: String, fileLabel: String): List<String> {
        val stripped = withoutComments(code)
        val findings = mutableListOf<String>()
        functions(stripped).forEach { (name, body) ->
            if (!body.mentionsAny(DIGEST_MARKERS)) return@forEach
            val phoneEvidence = PHONE_MARKERS.firstOrNull { body.contains(it, ignoreCase = true) }
            if (phoneEvidence != null) {
                findings += "$fileLabel: function '$name' hashes a value derived from '$phoneEvidence'"
            }
        }
        stripped.lines().forEach { line ->
            if (line.contains(PHONE_NAMESPACE) && line.contains("MessageDigest")) {
                findings += "$fileLabel: $line"
            }
        }
        return findings
    }

    /** Line and block comments gone; code, string literals and char literals untouched. */
    private fun withoutComments(text: String): String {
        val out = StringBuilder(text.length)
        var i = 0
        var inBlock = false
        while (i < text.length) {
            val c = text[i]
            when {
                inBlock -> {
                    if (text.startsWith(CLOSE, i)) {
                        inBlock = false
                        i += 2
                    } else {
                        if (text[i] == '\n') out.append('\n')
                        i++
                    }
                }

                text.startsWith(OPEN, i) -> {
                    inBlock = true
                    i += 2
                }

                text.startsWith(LINE, i) -> {
                    while (i < text.length && text[i] != '\n') i++
                }

                c == '"' || c == '\'' -> {
                    val end = literalEnd(text, i, c)
                    out.append(text, i, end)
                    i = end
                }

                else -> {
                    out.append(c)
                    i++
                }
            }
        }
        return out.toString()
    }

    /**
     * Index just past the literal starting at [start], tolerant of an unterminated one.
     *
     * Two properties, both load-bearing, and neither was true of the first version of this
     * function — which cost two hosted CI runs their entire 45-minute budget:
     *  - **It always advances.** `end > start` for every input, so no caller's `while` can spin.
     *    The old version returned `j` unchanged for a `"` that reached a newline, and a double
     *    quote is *legal* inside a Kotlin string, so an interpolated `…"${ string("x") }…`
     *    desynced the walk into a phantom string at end of line and hung the test task forever.
     *  - **A single-quoted literal never crosses a newline.** Kotlin will not compile a `"…` with
     *    a raw break in it, so stopping at the newline is at worst one line of mis-scan; the
     *    alternative is swallowing the rest of the file, and after it, every function boundary.
     *    This is the same terminating shape `ProviderPageScreenTest.codeOf` already uses.
     */
    private fun literalEnd(text: String, start: Int, quote: Char): Int {
        val end = scanLiteralEnd(text, start, quote)
        check(end > start) {
            "literal scanner made no progress at index $start of " +
                text.substring(start, minOf(start + 40, text.length))
        }
        return end
    }

    private fun scanLiteralEnd(text: String, start: Int, quote: Char): Int {
        if (quote == '"' && text.startsWith(TRIPLE, start)) {
            var j = start + TRIPLE.length
            while (j < text.length) {
                if (text[j] != '"') {
                    j++
                    continue
                }
                // Kotlin closes a raw string at the LAST three quotes of a maximal run, so
                // """x"""" is a raw string holding `x"`. Closing at the first three leaks a quote
                // back into "code" context — the exact bug `CommentBalanceTest` records — and one
                // or two quotes are content, not a terminator.
                var run = j
                while (run < text.length && text[run] == '"') run++
                if (run - j >= TRIPLE.length) return run
                j = run
            }
            return text.length
        }
        var j = start + 1
        while (j < text.length) {
            val c = text[j]
            if (c == '\\') {
                j += 2
                continue
            }
            if (c == quote || c == '\n') return minOf(j + 1, text.length)
            j++
        }
        return text.length
    }

    /** Top-level `fun name` declarations, as (name, body-with-braces) pairs. */
    private fun functions(code: String): List<Pair<String, String>> {
        val found = mutableListOf<Pair<String, String>>()
        var i = 0
        while (i < code.length) {
            if (!code.startsWith("fun ", i) || !isDeclarationPosition(code, i)) {
                i++
                continue
            }
            val nameStart = i + 4
            val open = code.indexOf('(', nameStart).takeIf { it >= 0 } ?: return found
            val nameEnd = code.substring(nameStart, open)
                .indexOfFirst { !(it.isLetterOrDigit() || it == '_' || it == ' ') }
                .let { if (it < 0) open else nameStart + it }
            val name = code.substring(nameStart, nameEnd).trim()
            val close = matchingParen(code, open) ?: return found
            // A body is the first `{` after the signature. An interface or abstract member has
            // none, so a `fun` (or a `;`) seen first means this declaration is bodyless and the
            // next brace belongs to somebody else — reading it as this one's would attribute a
            // violation to the wrong declaration, which is worse than missing it.
            var k = close + 1
            var bodyAt = -1
            while (k < code.length) {
                val c = code[k]
                if (c == '{') {
                    bodyAt = k
                    break
                }
                if (c == ';' || (code.startsWith("fun ", k) && isDeclarationPosition(code, k))) break
                k++
            }
            if (bodyAt < 0) {
                i = close + 1
                continue
            }
            val bodyEnd = matchingBrace(code, bodyAt) ?: return found
            found += name to code.substring(bodyAt, bodyEnd + 1)
            i = bodyEnd + 1
        }
        return found
    }

    /** Index of the paren matching the one at [openAt], skipping string and char literals. */
    private fun matchingParen(code: String, openAt: Int): Int? {
        var depth = 0
        var i = openAt
        while (i < code.length) {
            val c = code[i]
            when {
                c == '"' || c == '\'' -> i = literalEnd(code, i, c)
                c == '(' -> {
                    depth++
                    i++
                }

                c == ')' -> {
                    depth--
                    if (depth == 0) return i
                    i++
                }

                else -> i++
            }
        }
        return null
    }

    /** A `fun` is a declaration only when it is not a fragment of a longer identifier. */
    private fun isDeclarationPosition(code: String, at: Int): Boolean {
        val before = if (at == 0) ' ' else code[at - 1]
        return !(before.isLetterOrDigit() || before == '_' || before == '.')
    }

    private fun matchingBrace(code: String, openAt: Int): Int? {
        var depth = 0
        var i = openAt
        while (i < code.length) {
            val c = code[i]
            when {
                c == '"' || c == '\'' -> i = literalEnd(code, i, c)
                c == '{' -> {
                    depth++
                    i++
                }

                c == '}' -> {
                    depth--
                    if (depth == 0) return i
                    i++
                }

                else -> i++
            }
        }
        return null
    }

    /** The body of the function named [name], or null when no such function is declared. */
    private fun functionBody(code: String, name: String): String? =
        functions(code).firstOrNull { it.first == name }?.second

    private fun String.mentionsAny(markers: List<String>): Boolean =
        markers.any { contains(it) }

    private companion object {
        const val OPEN = "/*"
        const val CLOSE = "*/"
        const val LINE = "//"
        const val TRIPLE = "\"\"\""

        /** The public domain separator the retired derivation hashed with. */
        const val PHONE_NAMESPACE = "phone-sync/v1"

        val DIGEST_MARKERS = listOf("MessageDigest", "getDigestInstance", "SHA-256", "SHA-1")

        /**
         * Anything that says "this digest is being fed a phone". `normalizePakistaniMobile` is the
         * one that matters — it is the only normalizer this app has, so a derivation can only reach
         * a digest through it — and the rest are the words that appear in that function's own
         * signature and output, kept because a rewrite could rename the normalizer and still do
         * the same thing.
         */
        val PHONE_MARKERS = listOf(
            "normalizePakistaniMobile",
            "PHONE_KEY_NAMESPACE",
            PHONE_NAMESPACE,
            "phone",
            "mobile",
        )
    }
}
