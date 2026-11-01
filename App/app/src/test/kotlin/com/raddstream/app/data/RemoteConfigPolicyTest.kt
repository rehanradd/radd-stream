package com.raddstream.app.data

import com.google.gson.Gson
import com.raddstream.app.network.models.VipRemoteConfig
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The watcher's failure policy, pinned one body at a time.
 *
 * Before this suite the cache-last-good rule lived only inside `RemoteConfigWatcher.refreshOnce()`,
 * which is reachable only by driving a five-minute coroutine loop with a DataStore behind it, so
 * nothing in the tree said what happens when the endpoint answers `{"success": false}` — and a
 * future edit could invert it (write the defaults, dropping a catalog out of maintenance during
 * the outage that caused the switch) with every existing test still green.
 *
 * Bodies come from [Gson] rather than from a hand-built model, because the rule is about what the
 * wire can actually contain: an absent key, an explicit false, a key this client does not mirror.
 */
class RemoteConfigPolicyTest {

    private val gson = Gson()

    private fun body(json: String): VipRemoteConfig =
        gson.fromJson(json, VipRemoteConfig::class.java)

    /** The write a body earns, or a failure that prints the body it was given. */
    private fun written(json: String): RemoteFlagWrite =
        requireNotNull(RemoteConfigPolicy.flagsFor(body(json))) { "expected a write from: $json" }

    @Test
    fun `a body the server itself disowns writes nothing`() {
        val refused = RemoteConfigPolicy.flagsFor(
            body("""{"success": false, "maintenance_mode": true, "feature_flags": {"downloads": false}}"""),
        )
        assertNull("an unauthoritative body must not touch the stored switches", refused)
        assertNotNull(
            "the guard needs a guard: the same body, believed, does write",
            RemoteConfigPolicy.flagsFor(
                body("""{"success": true, "maintenance_mode": true, "feature_flags": {"downloads": false}}"""),
            ),
        )
    }

    @Test
    fun `a body with no success field is a body the server did not vouch for`() {
        assertNull(RemoteConfigPolicy.flagsFor(body("""{"maintenance_mode": true}""")))
    }

    @Test
    fun `a degraded body keeps the last good config and writes nothing at all`() {
        // The exact shape the server publishes when its own settings read fails
        // (`Fast_Fetch/admin_panel.py`, UPD-1a / [Q3-MUSE-P1]): success true, well-formed, and the
        // shipped defaults — maintenance off, every surface on. The operator may have flipped
        // exactly those switches, so acting on this is a remote control failing open.
        val write = RemoteConfigPolicy.flagsFor(
            body(
                """{"success": true, "settings_unavailable": true, "maintenance_mode": false,
                    "feature_flags": {"downloads": true, "sharing": true, "search": true,
                                      "pure_cinema": true}}""",
            ),
        )
        assertNull("unknown is not a false", write)
        assertNotNull(
            "the same body believed is a write: the marker is the only difference",
            RemoteConfigPolicy.flagsFor(
                body(
                    """{"success": true, "settings_unavailable": false, "maintenance_mode": false,
                        "feature_flags": {"downloads": true, "sharing": true, "search": true,
                                          "pure_cinema": true}}""",
                ),
            ),
        )
    }

    @Test
    fun `a degraded body is refused whole rather than half`() {
        // No reader may treat the marker as applying only to the fields it happens to dislike:
        // `maintenance_mode: true` beside the marker is still a value the server did not read.
        assertNull(
            RemoteConfigPolicy.flagsFor(
                body("""{"success": true, "settings_unavailable": true, "maintenance_mode": true}"""),
            ),
        )
        assertTrue(
            written("""{"success": true, "settings_unavailable": false, "maintenance_mode": true}""")
                .maintenanceMode,
        )
    }

    @Test
    fun `a body that never heard of the marker is believed, as it always was`() {
        val write = written("""{"success": true, "maintenance_mode": true}""")

        // Absent means the deployment predates the field, and a client that read silence as
        // "degraded" would go permanently cache-last-good against a body that said nothing wrong.
        assertFalse(body("""{"success": true}""").settingsUnavailable)
        assertTrue(write.maintenanceMode)
    }

    @Test
    fun `the seven switches a believed body carries arrive in the order the store takes them`() {
        val write = written(
            """{"success": true, "maintenance_mode": true,
                "feature_flags": {"downloads": false, "sharing": false, "search": false,
                                  "pure_cinema": false, "quality_gate": true, "chromecast": false},
                "ads": {"ads_enabled": true}}""",
        )

        // Destructured, not read by name, because the watcher hands these to saveRemoteFlags
        // positionally-by-key: two switches swapped is the defect this catches.
        val (maintenance, downloads, sharing, search, pureCinema, qualityGate, ads) = write
        assertTrue(maintenance)
        assertFalse(downloads)
        assertFalse(sharing)
        assertFalse(search)
        assertFalse(pureCinema)
        assertTrue(qualityGate)
        assertTrue(ads)
    }

    @Test
    fun `a board nobody has switched writes the app as it shipped`() {
        val write = written("""{"success": true}""")

        assertFalse(write.maintenanceMode)
        assertTrue(write.downloadsEnabled)
        assertTrue(write.sharingEnabled)
        assertTrue(write.searchEnabled)
        assertTrue(write.pureCinemaEnabled)
        // The two that default the other way: a gate that restricts content and a surface that
        // spends an impression. Neither is something the viewer already had, so neither may be
        // switched on by a body that never mentioned it.
        assertFalse(write.qualityGateEnabled)
        assertFalse(write.adsEnabled)
    }

    @Test
    fun `a switch this app does not mirror costs the other six nothing`() {
        val write = written("""{"success": true, "feature_flags": {"chromecast": false}}""")

        // There is no cast UI in this build, so `chromecast` has no feature to take away and no
        // stored key to land in. What must not happen is the whole board being refused because
        // one key is unmirrored — that would strand every switch the operator really moved.
        assertTrue(write.downloadsEnabled)
        assertTrue(write.sharingEnabled)
        assertTrue(write.searchEnabled)
        assertTrue(write.pureCinemaEnabled)
        assertFalse(write.maintenanceMode)
        assertFalse(write.qualityGateEnabled)
        assertFalse(write.adsEnabled)
    }
}
