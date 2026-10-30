package com.raddstream.app.player

import com.raddstream.app.network.models.VipRemoteAdCadence
import com.raddstream.app.network.models.VipRemoteAds
import com.raddstream.app.network.models.VipRemoteEngagement
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The ad caps pinned to the server that enforces them, read off disk.
 *
 * `Fast_Fetch/engagement.py` is not documentation for this client — it is the other half of one
 * rule. `ad_grant()` answers a phone's ask by comparing its own `CAPS_DEFAULT` against its own
 * stamps, so the numbers are only honest while both sides mean the same three gaps. A rename on
 * either side is the drift this catches, and the failure it prevents is silent: a client obeying a
 * stale spelling falls back to its shipped window while the server, which read the new name, is
 * enforcing something else, and the viewer gets an ad the server had already refused or loses one
 * it had granted.
 *
 * The same file carries the sharper hazard: the server states app-open in MINUTES (`240`) and the
 * older `ads` block states it in HOURS (`4`). Case 2 is therefore the one that matters most — it
 * compares the server's raw number against the milliseconds this build actually enforces, so the
 * conversion cannot be flipped by whoever edits next.
 *
 * Plain JUnit4 on the JVM, in the `VipWireContractTest` pattern: no Robolectric, no network, and no
 * Python is executed — the source is read as text, the way `BrandDriftTest` reads `brand.properties`.
 */
class AdCadenceWireContractTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(File(dir, "Fast_Fetch"), "engagement.py").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("Fast_Fetch/engagement.py not found above ${File("").absolutePath}")
    }

    private val engagement: List<String> by lazy {
        File(File(repoRoot, "Fast_Fetch"), "engagement.py").readLines()
    }

    private val config: List<String> by lazy {
        File(
            File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/network/models"),
            "VipRemoteConfig.kt",
        ).readLines()
    }

    /**
     * The literal body of the Python dict assigned at [name], as `key -> first number on the line`.
     *
     * Only the first number, because `CAP_MAX` writes `24 * 60`: this file compares key sets and
     * default values, and a mini-expression evaluator would be a second owner for arithmetic that
     * belongs to the server.
     */
    private fun pythonDict(name: String): Map<String, Int> {
        val from = engagement.indexOfFirst { it.trim().startsWith("$name = {") }
        assertTrue("$name is no longer a dict literal in engagement.py", from >= 0)
        val body = engagement.subList(from + 1, engagement.size).takeWhile { !it.trim().startsWith("}") }
        val entries = body.mapNotNull { line ->
            val match = ENTRY.find(line.trim()) ?: return@mapNotNull null
            match.groupValues[1] to match.groupValues[2].toInt()
        }
        assertTrue("$name parsed to nothing — the dict shape changed", entries.isNotEmpty())
        return entries.toMap()
    }

    /** The primary `@SerializedName(value = "…")` keys of this clients cadence class. */
    private fun clientCadenceKeys(): List<String> {
        val from = config.indexOfFirst { "data class VipRemoteAdCadence" in it }
        assertTrue("the client no longer declares VipRemoteAdCadence", from >= 0)
        val body = config.subList(from + 1, config.size).takeWhile { !it.matches(UNINDENTED) }
        return body.mapNotNull { SERIALIZED.find(it)?.groupValues?.get(1) }
    }

    @Test
    fun `the three caps the server publishes are the three this client reads`() {
        val server = pythonDict("CAPS_DEFAULT").keys.sorted()
        val client = clientCadenceKeys().sorted()
        assertEquals(
            "a key renamed on one side is a cap silently un-enforced on the other",
            server,
            client,
        )
        // Positive control: the shared names really are the three surfaces, not an empty match.
        assertEquals(
            listOf(
                "ad_app_open_min_gap_minutes",
                "ad_native_card_every_posters",
                "ad_preroll_min_gap_minutes",
            ),
            server,
        )
        assertEquals(3, client.size)
    }

    @Test
    fun `the caps the server publishes are the windows this build ships`() {
        val server = pythonDict("CAPS_DEFAULT")
        val shipped = AdCadenceLimits.SHIPPED
        assertEquals(
            "pre-roll gap, minutes on both sides",
            server.getValue("ad_preroll_min_gap_minutes") * 60_000L,
            shipped.preRollIntervalMs,
        )
        assertEquals(
            "the native card cap is a poster count, not a duration",
            server.getValue("ad_native_card_every_posters"),
            shipped.feedCardEveryPosters,
        )
        assertEquals(
            "app-open is stated in minutes by the server and in hours by this client; the two only " +
                "agree once multiplied out to the same instant",
            server.getValue("ad_app_open_min_gap_minutes") * 60_000L,
            shipped.appOpenIntervalMs,
        )
    }

    @Test
    fun `a server that publishes no cadence still gets the capped behaviour`() {
        // The whole tolerant-decode promise, asserted as behaviour rather than as a default value:
        // no deployment sends this block today, so absence must never read as unlimited.
        assertEquals(AdCadenceLimits.SHIPPED, AdCadenceLimits.from(VipRemoteAds()))
        assertEquals(AdCadenceLimits.SHIPPED, AdCadenceLimits.from(VipRemoteAds(), VipRemoteEngagement()))
        // And a zero is the servers own way of saying "unanswered": `resolve_caps` keeps the default
        // for a non-positive override, and this client has to answer the same way or the two
        // enforcement points disagree at exactly the value that means "no limit" to nobody.
        val zeros = AdCadenceLimits.from(
            VipRemoteAds(),
            VipRemoteEngagement(
                cadence = VipRemoteAdCadence(
                    prerollGapMinutes = 0,
                    feedCardEveryPosters = 0,
                    appOpenGapMinutes = 0,
                ),
            ),
        )
        assertEquals(AdCadenceLimits.SHIPPED, zeros)
    }

    @Test
    fun `the server cadence outranks the older ads block, whose hours are converted not trusted`() {
        val fromServer = AdCadenceLimits.from(
            VipRemoteAds(prerollIntervalMinutes = 1, appOpenIntervalHours = 1),
            VipRemoteEngagement(
                cadence = VipRemoteAdCadence(
                    prerollGapMinutes = 40,
                    feedCardEveryPosters = 20,
                    appOpenGapMinutes = 300,
                ),
            ),
        )
        assertEquals(40 * 60_000L, fromServer.preRollIntervalMs)
        assertEquals(20, fromServer.feedCardEveryPosters)
        assertEquals(300 * 60_000L, fromServer.appOpenIntervalMs)

        // Only the old block, in its own units: 4 hours is 4 hours, neither 4 minutes nor 240 hours.
        val fromAds = AdCadenceLimits.from(VipRemoteAds(prerollIntervalMinutes = 30, appOpenIntervalHours = 4))
        assertEquals(30 * 60_000L, fromAds.preRollIntervalMs)
        assertEquals(4 * 3_600_000L, fromAds.appOpenIntervalMs)
    }

    @Test
    fun `the cadence is read from the projection the server actually names`() {
        // `remote_view()` is what the phone gets; its cadence key must be the object this client
        // decodes, and it must be reached through the `engagement` field, not somewhere invented.
        val from = engagement.indexOfFirst { "def remote_view" in it }
        assertTrue("remote_view() is gone from engagement.py", from >= 0)
        val body = engagement.subList(from + 1, engagement.size).takeWhile { !it.startsWith("def ") }
        assertTrue(
            "engagement.py no longer publishes a cadence block for a client to read",
            body.any { "\"cadence\"" in it },
        )
        assertTrue(
            "and this client reads it as VipRemoteConfig.engagement",
            config.any { "val engagement: VipRemoteEngagement" in it },
        )
    }

    @Test
    fun `this client has no ad surface the server has no slot for`() {
        val line = engagement.first { it.trim().startsWith("AD_SLOTS") }
        val slots = SLOT_SET.find(line)?.groupValues?.get(1)
            ?.split(",")
            ?.map { it.trim().trim('"', '\'') }
            ?.sorted()
        assertEquals(
            "the server enforces exactly three slots",
            listOf("app_open", "native_card", "preroll"),
            slots,
        )
        assertEquals(
            "and this client asks for exactly those three — a fourth surface would be an ad the " +
                "server cannot grant, and a mid-roll is the one placement this app has ruled out",
            slots,
            AdSurface.entries.map { SURFACES_TO_SLOTS.getValue(it) }.sorted(),
        )
    }

    @Test
    fun `every cap the server bounds is a cap this client decodes`() {
        // `CAP_MAX` is the servers bound on a bad admin save. The values cannot cross the wire in
        // either direction, but the key set can: a cap the server bounds and this client does not
        // read is a knob the operator turns against an empty room.
        assertEquals(
            pythonDict("CAPS_DEFAULT").keys.sorted(),
            pythonDict("CAP_MAX").keys.sorted(),
        )
        // The ceiling this side does own, and the one the owner called non-negotiable, still holds
        // against a body that asks for more.
        val unskippable = AdCadenceLimits.from(VipRemoteAds(skippableAfterSeconds = 120))
        assertEquals(AdCadenceLimits.MAX_SKIP_MS, unskippable.skippableAfterMs)
        assertEquals(AdCadenceLimits.MAX_SKIP_MS, AdCadence.skippableAtMs(unskippable))
    }

    private companion object {
        val ENTRY = Regex("\"([a-z_]+)\":\\s*([0-9]+)")
        val SERIALIZED = Regex("value = \"([a-z_]+)\"")
        val SLOT_SET = Regex("^AD_SLOTS = frozenset\\(\\{(.*)\\}\\)$")
        val UNINDENTED = Regex("^[^ ].*")

        /** The one place the two vocabularies are said to be the same three things. */
        val SURFACES_TO_SLOTS = mapOf(
            AdSurface.PRE_ROLL to "preroll",
            AdSurface.FEED_CARD to "native_card",
            AdSurface.APP_OPEN to "app_open",
        )
    }
}
