package com.raddstream.app.player

import com.raddstream.app.data.local.AdCadenceDao
import com.raddstream.app.data.local.AdCadenceEntity
import com.raddstream.app.network.models.VipRemoteAds
import com.raddstream.app.network.models.VipRemoteAdCadence
import com.raddstream.app.network.models.VipRemoteEngagement
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The governor drives the whole feature — the switch, the caps, the persisted stamps, the
 * inventory answer, and the ad-free exemption — so it is the class worth testing against fakes
 * rather than a text scan. Every dependency it has is an interface or a fun interface precisely so
 * this file can exist: [AdCadenceDao] is a map, [AdSwitch] is a boolean, [AdInventory] is a set,
 * and [AdWallClock] is a number a test turns.
 */
class AdCadenceGovernorTest {

    private class FakeDao : AdCadenceDao {
        val rows = LinkedHashMap<String, AdCadenceEntity>()
        var clearCalls = 0

        override suspend fun all(): List<AdCadenceEntity> = rows.values.toList()

        override suspend fun put(row: AdCadenceEntity) {
            rows[row.surface] = row
        }

        override suspend fun clear() {
            rows.clear()
            clearCalls++
        }
    }

    private class FakeSwitch(var enabled: Boolean = true) : AdSwitch {
        override suspend fun adsEnabled(): Boolean = enabled
    }

    private class FakeInventory(
        private val surfaces: Set<AdSurface> = AdSurface.entries.toSet(),
    ) : AdInventory {
        var asks = 0
        override fun canFill(surface: AdSurface): Boolean {
            asks++
            return surface in surfaces
        }
    }

    private fun governor(
        dao: FakeDao,
        clock: FixedAdWallClock,
        switch: AdSwitch,
        inventory: AdInventory,
    ) = AdCadenceGovernor(dao, clock, inventory, switch)

    @Test
    fun `a first ask serves the pre-roll and records the impression itself`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
        subject.refresh()

        val decision = subject.offer(AdSurface.PRE_ROLL, adFree = false) as AdDecision.Serve

        assertEquals(AdSurface.PRE_ROLL, decision.surface)
        assertEquals(5_000L, decision.skippableAtMs)
        // Recorded inside offer, not handed back for an SDK to remember to log.
        assertEquals(START, dao.rows.getValue("PRE_ROLL").lastShownAtMs)
        assertEquals(START, subject.state.value.preRollShownAtMs)
    }

    @Test
    fun `the second pre-roll inside twenty-five minutes is refused`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
        subject.refresh()

        assertTrue(subject.offer(AdSurface.PRE_ROLL, adFree = false) is AdDecision.Serve)
        clock.advance(24 * MINUTE_MS)
        assertEquals(AdDecision.None, subject.offer(AdSurface.PRE_ROLL, adFree = false))
        clock.advance(MINUTE_MS)
        assertTrue(subject.offer(AdSurface.PRE_ROLL, adFree = false) is AdDecision.Serve)
    }

    /** A cap that reset when the process died would be a cap only while the app stayed open. */
    @Test
    fun `a killed process does not buy a fresh pre-roll`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val first = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
        first.refresh()
        assertTrue(first.offer(AdSurface.PRE_ROLL, adFree = false) is AdDecision.Serve)

        clock.advance(10 * MINUTE_MS)
        val afterDeath = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
        afterDeath.refresh()

        assertEquals("the stamp survived the restart", START, afterDeath.state.value.preRollShownAtMs)
        assertEquals(AdDecision.None, afterDeath.offer(AdSurface.PRE_ROLL, adFree = false))
    }

    @Test
    fun `the counter for the feed card is persisted too`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.FEED_CARD)))
        subject.refresh()

        subject.onPostersScrolled(7, adFree = false)
        assertEquals(7, dao.rows.getValue("FEED_CARD").postersScrolled)
        assertEquals(AdDecision.None, subject.offer(AdSurface.FEED_CARD, adFree = false))

        subject.onPostersScrolled(5, adFree = false)
        assertTrue(subject.offer(AdSurface.FEED_CARD, adFree = false) is AdDecision.Serve)
        assertEquals("a card spends the twelve posters", 0, dao.rows.getValue("FEED_CARD").postersScrolled)
    }

    @Test
    fun `an ad-free viewer neither sees a card nor spends its budget`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val inventory = FakeInventory()
        val subject = governor(dao, clock, FakeSwitch(), inventory)
        subject.refresh()

        subject.onPostersScrolled(50, adFree = true)
        assertEquals("the counter never moved", 0, subject.state.value.postersSinceFeedCard)
        assertEquals(AdDecision.None, subject.offer(AdSurface.PRE_ROLL, adFree = true))
        assertEquals(AdDecision.None, subject.offer(AdSurface.FEED_CARD, adFree = true))
        assertEquals(AdDecision.None, subject.offer(AdSurface.APP_OPEN, adFree = true))
        assertEquals("an ineligible ask never reaches the network", 0, inventory.asks)
        assertTrue("nothing was recorded", dao.rows.isEmpty())
    }

    @Test
    fun `a switched-off operator refuses all three surfaces and asks no network`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val inventory = FakeInventory()
        val subject = governor(dao, clock, FakeSwitch(enabled = false), inventory)
        subject.refresh()

        AdSurface.entries.forEach { surface ->
            assertEquals("$surface", AdDecision.None, subject.offer(surface, adFree = false))
        }
        subject.onPostersScrolled(100, adFree = false)
        assertEquals(0, subject.state.value.postersSinceFeedCard)
        assertEquals(0, inventory.asks)
    }

    @Test
    fun `an unfilled slot is nothing at all rather than a wait`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), NoAdInventory())
        subject.refresh()

        AdSurface.entries.forEach { surface ->
            assertEquals("$surface", AdDecision.None, subject.offer(surface, adFree = false))
        }
        // The refusal must not have spent the budget: a dead network is not an impression.
        assertTrue("no stamp written for an ad nobody saw", dao.rows.isEmpty())
        assertEquals(AdCadenceState(enabled = true), subject.state.value)
        assertTrue(
            "still eligible once inventory exists",
            governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
                .let { it.refresh(); it.offer(AdSurface.PRE_ROLL, adFree = false) } is AdDecision.Serve,
        )
    }

    @Test
    fun `flipping the switch off clears every stamp and counter`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory())
        subject.refresh()
        subject.offer(AdSurface.PRE_ROLL, adFree = false)
        subject.offer(AdSurface.APP_OPEN, adFree = false)
        subject.onPostersScrolled(6, adFree = false)
        assertTrue(dao.rows.isNotEmpty())

        subject.clearForDisabledSwitch()

        assertEquals(1, dao.clearCalls)
        assertTrue(dao.rows.isEmpty())
        assertEquals(AdCadenceState(), subject.state.value)
        // Idempotent: the watcher calls this on every five-minute poll that still reads disabled.
        subject.clearForDisabledSwitch()
        assertEquals(2, dao.clearCalls)
    }

    @Test
    fun `the operator caps published from a remote body replace the shipped ones`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
        subject.refresh()

        subject.publishLimits(VipRemoteAds(prerollIntervalMinutes = 10))

        subject.offer(AdSurface.PRE_ROLL, adFree = false)
        clock.advance(10 * MINUTE_MS)
        assertTrue("the shorter window the operator asked for is obeyed",
            subject.offer(AdSurface.PRE_ROLL, adFree = false) is AdDecision.Serve)

        subject.publishLimits(VipRemoteAds(prerollIntervalMinutes = 90))
        clock.advance(60 * MINUTE_MS)
        assertEquals("and a later body tightens it without a restart", AdDecision.None,
            subject.offer(AdSurface.PRE_ROLL, adFree = false))
    }

    /**
     * The same publish through the two bodies the server writes: `ads` and `engagement`. Which one
     * wins is not academic — the enforcement side reads `engagement`, so a client that let the
     * older block decide would enforce a window the operator has since changed.
     */
    @Test
    fun `the engagement block is the window the governor enforces`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
        subject.publishLimits(
            VipRemoteAds(prerollIntervalMinutes = 5),
            VipRemoteEngagement(VipRemoteAdCadence(prerollGapMinutes = 30)),
        )
        subject.refresh()

        subject.offer(AdSurface.PRE_ROLL, adFree = false)
        clock.advance(5 * MINUTE_MS)
        assertEquals(
            "the five-minute `ads` window is not the one in force",
            AdDecision.None,
            subject.offer(AdSurface.PRE_ROLL, adFree = false),
        )
        clock.advance(25 * MINUTE_MS)
        assertTrue(subject.offer(AdSurface.PRE_ROLL, adFree = false) is AdDecision.Serve)
    }

    @Test
    fun `a skip ask above five seconds cannot reach a caller`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.PRE_ROLL)))
        subject.publishLimits(VipRemoteAds(skippableAfterSeconds = 120))
        subject.refresh()

        val decision = subject.offer(AdSurface.PRE_ROLL, adFree = false)
        assertTrue(decision is AdDecision.Serve)
        val served = decision as AdDecision.Serve
        assertEquals(AdCadenceLimits.MAX_SKIP_MS, served.skippableAtMs)
        assertTrue(served.skippableAtMs <= AdCadenceLimits.MAX_SKIP_MS)
    }

    /**
     * The switch is read on every ask, so an operator flipping it mid-session takes effect on the
     * next surface rather than on the next app start — and flipping it back on does not hand the
     * viewer the window they were already inside.
     */
    @Test
    fun `a mid-session flip refuses at once and does not restart the window`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val switch = FakeSwitch(enabled = true)
        val subject = governor(dao, clock, switch, FakeInventory(setOf(AdSurface.PRE_ROLL)))
        subject.refresh()

        assertTrue(subject.offer(AdSurface.PRE_ROLL, adFree = false) is AdDecision.Serve)

        clock.advance(10 * MINUTE_MS)
        switch.enabled = false
        assertEquals(AdDecision.None, subject.offer(AdSurface.PRE_ROLL, adFree = false))

        switch.enabled = true
        // The stamp from before the flip is still the reference point, so no fresh pre-roll is
        // bought by turning the feature off and on again.
        assertEquals(AdDecision.None, subject.offer(AdSurface.PRE_ROLL, adFree = false))
        clock.advance(15 * MINUTE_MS)
        assertTrue(subject.offer(AdSurface.PRE_ROLL, adFree = false) is AdDecision.Serve)
    }

    @Test
    fun `a switch that throws is a refusal and writes nothing`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val broken = object : AdSwitch {
            override suspend fun adsEnabled(): Boolean = throw IllegalStateException("torn preferences")
        }
        val inventory = FakeInventory()
        val subject = governor(dao, clock, broken, inventory)

        // offer() must fail closed on its own, because the governor — not whichever binding
        // happens to be installed — is the owner of "a switch nobody could read is not permission".
        AdSurface.entries.forEach { surface ->
            assertEquals("$surface", AdDecision.None, subject.offer(surface, adFree = false))
        }
        subject.onPostersScrolled(50, adFree = false)
        assertTrue("an unreadable switch records nothing", dao.rows.isEmpty())
        assertEquals("and never reaches a network", 0, inventory.asks)
    }

    @Test
    fun `scrolling reports nothing that was not scrolled`() = runBlocking {
        val dao = FakeDao()
        val clock = FixedAdWallClock(START)
        val subject = governor(dao, clock, FakeSwitch(), FakeInventory(setOf(AdSurface.FEED_CARD)))
        subject.refresh()

        subject.onPostersScrolled(0, adFree = false)
        subject.onPostersScrolled(-4, adFree = false)
        assertTrue(dao.rows.isEmpty())
        assertFalse(subject.state.value.postersSinceFeedCard > 0)
    }

    companion object {
        private const val MINUTE_MS = 60_000L
        private const val START = 1_730_000_000_000L
    }
}
