package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.AccountEntitlement
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for the D1.2 VIP cancel contract and pricing locks.
 *
 * Plain JUnit4 on the JVM: no Robolectric, no Android runtime, no network.
 */
class VipCancelContractTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(File(dir, "Fast_Fetch"), "accounts_api.py").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("Fast_Fetch/accounts_api.py not found above ${File("").absolutePath}")
    }

    private val accountsApiSource: String by lazy {
        File(File(repoRoot, "Fast_Fetch"), "accounts_api.py").readText()
    }

    private val accountWireSource: String by lazy {
        File(
            File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/network/models"),
            "AccountWire.kt",
        ).readText()
    }

    private val vipUpgradeScreenSource: String by lazy {
        File(
            File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/ui/screens"),
            "VipUpgradeScreen.kt",
        ).readText()
    }

    @Test
    fun `initial VipUiState has no pending cancel and not cancelled`() {
        val state = VipUiState()
        assertFalse(state.isCancelPending)
        assertFalse(state.isCancelling)
        assertFalse(state.isCancelled)
        assertFalse(state.serverCancelled)
    }

    @Test
    fun `VipUiState with pending cancel reports isCancelled true and serverCancelled false`() {
        val state = VipUiState(
            entitlement = AccountEntitlement(vip = true, vipUntil = 1800000000.0),
            isCancelPending = true,
        )
        assertTrue(state.isVip)
        assertTrue(state.isCancelPending)
        assertTrue(state.isCancelled)
        assertFalse(state.serverCancelled)
    }

    @Test
    fun `VipUiState with server acked cancel reports serverCancelled true and isCancelled true`() {
        val state = VipUiState(
            entitlement = AccountEntitlement(
                vip = true,
                vipUntil = 1800000000.0,
                vipCancelledAt = 1750000000.0,
            ),
            isCancelPending = false,
        )
        assertTrue(state.isVip)
        assertFalse(state.isCancelPending)
        assertTrue(state.isCancelled)
        assertTrue(state.serverCancelled)
    }

    @Test
    fun `server cancel keys match request model`() {
        // accounts_api._CANCEL_KEYS = frozenset({"reason"})
        assertTrue(accountsApiSource.contains("_CANCEL_KEYS = frozenset({\"reason\"})"))
        assertTrue(accountWireSource.contains("data class AccountCancelRequest"))
        assertTrue(accountWireSource.contains("val reason: String? = null"))
    }

    @Test
    fun `server cancel response matches wire model`() {
        // POST /api/v2/account/cancel answers cancelled, vip_until, cancelled_at
        assertTrue(accountWireSource.contains("data class AccountCancelResponse"))
        assertTrue(accountWireSource.contains("val cancelled: Boolean"))
        assertTrue(accountWireSource.contains("val vipUntil: Double"))
        assertTrue(accountWireSource.contains("val cancelledAt: Double"))
    }

    @Test
    fun `no hardcoded PKR or Rs prices in VipUpgradeScreen`() {
        assertFalse(vipUpgradeScreenSource.contains("Rs."))
        assertFalse(vipUpgradeScreenSource.contains("Rs "))
        assertFalse(vipUpgradeScreenSource.contains("PKR 200"))
        assertFalse(vipUpgradeScreenSource.contains("PKR 1500"))
        assertFalse(vipUpgradeScreenSource.contains("PKR 1,500"))
    }

    @Test
    fun `taxes line references total incl taxes only when price published`() {
        assertTrue(vipUpgradeScreenSource.contains("Total incl. taxes"))
        assertTrue(vipUpgradeScreenSource.contains("Not published by the server"))
    }

    @Test
    fun `cancel dialog and active plan card strings present in VipUpgradeScreen`() {
        assertTrue(vipUpgradeScreenSource.contains("Cancel VIP Pass?"))
        assertTrue(vipUpgradeScreenSource.contains("No partial refunds"))
        assertTrue(vipUpgradeScreenSource.contains("Keep VIP"))
        assertTrue(vipUpgradeScreenSource.contains("Confirm Cancel"))
        assertTrue(vipUpgradeScreenSource.contains("Prepaid — no auto-renew"))
        assertTrue(vipUpgradeScreenSource.contains("Valid Through "))
        assertTrue(vipUpgradeScreenSource.contains("Cancelled — access remains active until "))
        assertTrue(vipUpgradeScreenSource.contains("Resume Pass"))
    }

    @Test
    fun `RaddStreamApi declares cancelVip on api v2 account cancel`() {
        val apiSource = File(
            File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/network"),
            "RaddStreamApi.kt",
        ).readText()
        assertTrue(apiSource.contains("@POST(\"api/v2/account/cancel\")"))
        assertTrue(apiSource.contains("suspend fun cancelVip("))
    }

    @Test
    fun `SyncAccountRepository declares cancelVipPass and retryPendingCancel`() {
        val repoSource = File(
            File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/sync"),
            "SyncAccountRepository.kt",
        ).readText()
        assertTrue(repoSource.contains("suspend fun cancelVipPass("))
        assertTrue(repoSource.contains("suspend fun retryPendingCancel("))
        assertTrue(repoSource.contains("suspend fun clearPendingCancel("))
    }
}
