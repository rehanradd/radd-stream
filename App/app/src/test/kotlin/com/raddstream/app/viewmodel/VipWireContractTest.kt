package com.raddstream.app.viewmodel

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the app's VIP vocabulary to the server that actually answers it.
 *
 * This is the drift that costs money: the plan name, the channel name and the receipt fields
 * are written by `Fast_Fetch/payments.py` and `Fast_Fetch/redact.py`, and a Kotlin enum that
 * invents its own spelling is a payment refused with a 400 — a viewer who paid and sees
 * nothing. So the names are not restated from a design note here; they are read out of the
 * Python source on disk, the way `BrandDriftTest` reads `brand.properties`.
 *
 * Plain JUnit4 on the JVM: no Robolectric, no Android runtime, no network.
 */
class VipWireContractTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(File(dir, "Fast_Fetch"), "payments.py").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("Fast_Fetch/payments.py not found above ${File("").absolutePath}")
    }

    private val paymentsSource: String by lazy {
        File(File(repoRoot, "Fast_Fetch"), "payments.py").readText()
    }

    private val redactSource: String by lazy {
        File(File(repoRoot, "Fast_Fetch"), "redact.py").readText()
    }

    private val accountWire: String by lazy {
        File(
            File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/network/models"),
            "AccountWire.kt",
        ).readText()
    }

    /** `val monthlyPkr: Int = …` — the two places a price could be baked into this client. */
    private val priceDefaults = Regex(
        """val\s+(monthlyPkr|yearlyPkr)\s*:\s*Int\s*=\s*([A-Za-z0-9_.\-]+)""",
    )

    private val vipViewModelSource: String by lazy {
        File(
            File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/viewmodel"),
            "VipViewModel.kt",
        ).readText()
    }

    /** Every price default that is not the no-price marker, described so a failure reads. */
    private fun bakedPrices(source: String): List<String> =
        priceDefaults.findAll(source)
            .filterNot { it.groupValues[2] == "VipViewModel.NO_PRICE_PUBLISHED" }
            .map { "${it.groupValues[1]} = ${it.groupValues[2]}" }
            .toList()

    /** `PLAN_DEFAULTS = { "vip_monthly": (200, 30), … }` → name to (amount, days). */
    private fun serverPlans(): Map<String, Pair<Int, Int>> {
        val block = paymentsSource.substringAfter("PLAN_DEFAULTS = {").substringBefore("}")
        return Regex(""""([^"]+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)""")
            .findAll(block)
            .associate { it.groupValues[1] to (it.groupValues[2].toInt() to it.groupValues[3].toInt()) }
    }

    /** `METHODS = ("jazzcash", "easypaisa", "raast")` — the channels a claim can name. */
    private fun serverMethods(): List<String> {
        val block = paymentsSource.substringAfter("METHODS = (").substringBefore(")")
        return Regex("\"([a-z]+)\"").findAll(block).map { it.groupValues[1] }.toList()
    }

    /** The one `frozenset({...})` block redact.py writes for a projection name. */
    private fun serverAllowlist(view: String): Set<String> {
        val entry = redactSource.indexOf("\"$view\":")
        check(entry >= 0) { "$view is not in redact.py's VIEWS at all" }
        val open = redactSource.indexOf("frozenset({", entry)
        check(open >= 0) { "$view does not declare a frozenset" }
        val close = redactSource.indexOf("})", open)
        check(close > open) { "$view's frozenset is never closed" }
        // A one-field list sits on one line; the payment projections are wrapped, so the
        // block is read between the braces rather than by cutting the declaration line.
        val body = redactSource.substring(open + "frozenset({".length, close)
        return Regex("\"([a-z_]+)\"").findAll(body).map { it.groupValues[1] }.toSet()
    }

    /** The wire names one data class in AccountWire.kt actually declares. */
    private fun modeledWireNames(className: String): Set<String> {
        // The body runs to the closing paren that starts its own line, not to the first
        // `)` — `@SerializedName("...")` carries one of those, and stopping there hid
        // every field declared after the first annotated one.
        val body = Regex("""data class $className\((.*?)\n\)""", RegexOption.DOT_MATCHES_ALL)
            .find(accountWire)?.groupValues?.get(1)
            ?: error("$className is not declared the way this test reads it")
        val annotated = Regex("""@SerializedName\("([^"]+)"\)\s+val\s+\w+""")
            .findAll(body).map { it.groupValues[1] }.toSet()
        val bare = Regex("""val\s+(\w+)\s*:""", RegexOption.MULTILINE)
            .findAll(body)
            .map { it.groupValues[1] }
            .filterNot { name -> Regex("""@SerializedName\("[^"]+"\)\s+val\s+$name\b""").containsMatchIn(body) }
            .toSet()
        return annotated + bare
    }

    @Test
    fun `the plans this app sells are exactly the plans the server prices`() {
        val server = serverPlans()
        assertTrue("payments.py defines no plans — this reader broke, not the server", server.isNotEmpty())
        assertEquals(
            server.keys.toSortedSet(),
            VipPlan.entries.map { it.wireName }.toSortedSet(),
        )
    }

    @Test
    fun `each plan buys the days the server table says`() {
        val server = serverPlans()
        VipPlan.entries.forEach { plan ->
            assertEquals("${plan.wireName} duration", server.getValue(plan.wireName).second, plan.days)
        }
    }

    @Test
    fun `this app carries no price of its own`() {
        assertEquals(
            "the reader saw no price defaults — it broke, not the app",
            2,
            priceDefaults.findAll(vipViewModelSource).count(),
        )
        assertEquals(
            "the server prices the plan and sends no amount to the phone; a number this client " +
                "invents is a quote nobody authorized",
            emptyList<String>(),
            bakedPrices(vipViewModelSource),
        )
        assertEquals(VipViewModel.NO_PRICE_PUBLISHED, VipUiState().monthlyPkr)
        assertEquals(VipViewModel.NO_PRICE_PUBLISHED, VipUiState().yearlyPkr)
        assertEquals(
            "the marker is the absence itself, so no screen can arithmetic it into a saving",
            0,
            VipViewModel.NO_PRICE_PUBLISHED,
        )
    }

    /** Positive control: the same detector, pointed at the shape this task deleted. */
    @Test
    fun `the detector does report a price baked into the client`() {
        val retired = "data class VipUiState(\n" +
            "    val monthlyPkr: Int = 200,\n" +
            "    val yearlyPkr: Int = 1_500,\n" +
            ")"
        assertEquals(listOf("monthlyPkr = 200", "yearlyPkr = 1_500"), bakedPrices(retired))
    }

    @Test
    fun `the channels this app names are the channels the server accepts`() {
        assertEquals(
            serverMethods().toSortedSet(),
            VipMethod.entries.map { it.wireName }.toSortedSet(),
        )
    }

    @Test
    fun `a plan name reads back from either spelling and never from a stranger`() {
        assertEquals(VipPlan.MONTHLY, VipPlan.fromStorage("MONTHLY"))
        assertEquals(VipPlan.YEARLY, VipPlan.fromStorage("vip_yearly"))
        assertEquals(VipPlan.MONTHLY, VipPlan.fromStorage("vip_monthly"))
        // An unreadable name falls back to the cheapest real plan rather than inventing one.
        assertEquals(VipPlan.MONTHLY, VipPlan.fromStorage("vip_forever"))
        assertNull(VipPlan.fromWire("vip_forever"))
    }

    @Test
    fun `a channel name is only recognised in the server spelling`() {
        assertEquals(VipMethod.JAZZCASH, VipMethod.fromWire("JazzCash"))
        assertEquals(VipMethod.EASYPAISA, VipMethod.fromWire(" easypaisa "))
        assertNull("an unknown channel must not be guessed", VipMethod.fromWire("paypal"))
        assertNull(VipMethod.fromWire(null))
    }

    @Test
    fun `the receipt the app parses is the projection the server may emit`() {
        assertEquals(serverAllowlist("account_payment"), modeledWireNames("PaymentReceipt"))
    }

    @Test
    fun `the entitlement the app parses is the projection the server may emit`() {
        assertEquals(serverAllowlist("account_entitlement"), modeledWireNames("AccountEntitlement"))
    }

    @Test
    fun `nothing the server answers can carry a transaction id to this screen`() {
        // The ledger keeps the TID and every projection drops it. If the server ever started
        // echoing it, this fails here instead of quietly becoming a field the app reads.
        assertFalse(serverAllowlist("account_payment").contains("tid"))
        assertFalse(modeledWireNames("PaymentReceipt").contains("tid"))
        assertFalse(modeledWireNames("AccountEntitlement").contains("tid"))
    }
}
