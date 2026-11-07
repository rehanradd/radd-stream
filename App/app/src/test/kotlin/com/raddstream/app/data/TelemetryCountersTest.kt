package com.raddstream.app.data

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The phone-side half of Tracking A, on the JVM: no Android runtime, no
 * DataStore, no network — the counters are pure logic over a store, and the
 * device class is a pure function of RAM.
 *
 * The contract with the server is pinned the same way `VipWireContractTest`
 * pins the payment vocabulary: the field names are read out of
 * `Fast_Fetch/usage_stats.py` on disk, so a server-side rename fails here
 * instead of silently becoming a counter the operator never sees.
 */
class TelemetryCountersTest {

    private class FakeStore : UsageCounterStore {
        private val counts = mutableMapOf<String, Int>()

        override fun add(field: String, count: Int) {
            counts[field] = (counts[field] ?: 0) + count
        }

        override fun snapshot(): Map<String, Int> =
            counts.filterValues { it > 0 }

        override fun subtract(sent: Map<String, Int>) {
            sent.forEach { (field, count) ->
                counts[field] = ((counts[field] ?: 0) - count).coerceAtLeast(0)
            }
        }
    }

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(File(dir, "Fast_Fetch"), "usage_stats.py").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("Fast_Fetch/usage_stats.py not found above ${File("").absolutePath}")
    }

    private fun serverClientFields(): Set<String> {
        val source = File(File(repoRoot, "Fast_Fetch"), "usage_stats.py").readText()
        val block = source.substringAfter("CLIENT_FIELDS = {").substringBefore("}")
        return Regex("\"([a-z_]+)\"\\s*:").findAll(block).map { it.groupValues[1] }.toSet()
    }

    @Test
    fun `the counters the app can send are exactly the fields the server accepts`() {
        val server = serverClientFields()
        assertTrue("usage_stats.py defines no CLIENT_FIELDS — this reader broke", server.isNotEmpty())
        assertEquals(server, Telemetry.USAGE_FIELDS)
        assertEquals(server, UsageCounters.FIELDS)
    }

    @Test
    fun `a count lands and reads back`() {
        val counters = UsageCounters(FakeStore()) { true }
        counters.record("crashes")
        counters.record("crashes", 2)
        counters.record("playback_attempts", 5)
        assertEquals(mapOf("crashes" to 3, "playback_attempts" to 5), counters.snapshot())
    }

    @Test
    fun `an unknown field name is ignored at the door`() {
        val counters = UsageCounters(FakeStore()) { true }
        counters.record("cooler_metric", 5000)
        counters.record("sql", 1)
        assertEquals(emptyMap<String, Int>(), counters.snapshot())
    }

    @Test
    fun `nothing is recorded while consent is off`() {
        var consented = false
        val counters = UsageCounters(FakeStore()) { consented }
        counters.record("crashes", 3)
        assertEquals(emptyMap<String, Int>(), counters.snapshot())
        consented = true
        counters.record("crashes", 1)
        assertEquals(mapOf("crashes" to 1), counters.snapshot())
    }

    @Test
    fun `acknowledging subtracts exactly what was sent and keeps later increments`() {
        val counters = UsageCounters(FakeStore()) { true }
        counters.record("crashes", 5)
        val sent = counters.snapshot()
        counters.record("crashes", 1)
        counters.acknowledge(sent)
        assertEquals(mapOf("crashes" to 1), counters.snapshot())
    }

    @Test
    fun `acknowledging an unknown field changes nothing`() {
        val counters = UsageCounters(FakeStore()) { true }
        counters.record("crashes", 2)
        counters.acknowledge(mapOf("cooler_metric" to 99))
        assertEquals(mapOf("crashes" to 2), counters.snapshot())
    }

    @Test
    fun `a zero or negative record is ignored`() {
        val counters = UsageCounters(FakeStore()) { true }
        counters.record("crashes", 0)
        counters.record("crashes", -3)
        assertEquals(emptyMap<String, Int>(), counters.snapshot())
    }

    @Test
    fun `device class is RAM only, with the documented thresholds`() {
        val gib = 1024L * 1024L * 1024L
        assertEquals("low", deviceClassFor(0L))
        assertEquals("low", deviceClassFor(2 * gib))
        assertEquals("mid", deviceClassFor(3 * gib))
        assertEquals("mid", deviceClassFor(5 * gib))
        assertEquals("high", deviceClassFor(6 * gib))
        assertEquals("high", deviceClassFor(16 * gib))
    }

    @Test
    fun `two minted install ids differ and both parse as UUIDs`() {
        val first = newInstallUuid()
        val second = newInstallUuid()
        assertNotEquals(first, second)
        assertTrue(first.matches(Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")))
        assertTrue(second.matches(Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")))
        assertFalse(first.contains(" "))
    }
}
