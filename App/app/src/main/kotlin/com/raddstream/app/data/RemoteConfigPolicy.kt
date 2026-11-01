package com.raddstream.app.data

import com.raddstream.app.network.models.VipRemoteConfig

/**
 * One poll's worth of persisted switches, in the order
 * [ServerSettingsRepository.saveRemoteFlags] takes them.
 *
 * It exists instead of a bare `Map` because the thing under test is a set of named switches: a
 * test that asserted against keys-by-string would pass even if two of them were swapped in the
 * watcher, which is the defect this type cannot express.
 */
data class RemoteFlagWrite(
    val maintenanceMode: Boolean,
    val downloadsEnabled: Boolean,
    val sharingEnabled: Boolean,
    val searchEnabled: Boolean,
    val pureCinemaEnabled: Boolean,
    val qualityGateEnabled: Boolean,
    val adsEnabled: Boolean,
)

/**
 * What one remote-config body is allowed to change, decided apart from any I/O.
 *
 * The rule itself is the whole failure policy of [RemoteConfigWatcher]: null means "write
 * nothing", so the last good answer stays on disk and every screen keeps reading it. It is a
 * separate object because the watcher's collaborators are concrete constructor-injected classes
 * and this tree carries no mocking library, so before this extraction the only way to reach the
 * rule was the five-minute coroutine loop — which no JVM test can drive. Nothing here changes
 * what the watcher wrote before; it makes the decision reachable to name and to pin.
 */
object RemoteConfigPolicy {

    /**
     * True when the server stands behind this body — the one question every reader of
     * `/remote-config` has to ask before it uses an answer.
     *
     * Two refusals, and the second is the one the server just added a field for
     * (`Fast_Fetch/admin_panel.py`, UPD-1a / [Q3-MUSE-P1]):
     *
     *  - `success` is the server's own statement that this response is authoritative. A body that
     *    decodes cleanly while saying it is not — an error page that happens to be JSON — cannot
     *    overwrite what the app already has.
     *  - `settings_unavailable` says the read behind the body failed. The body is still well-formed
     *    and still carries the shipped defaults: `maintenance_mode: false` with every feature flag
     *    on, while the operator may have flipped exactly those. Acting on it is how a remote
     *    control fails open, and "unknown" is not a `false`.
     */
    fun isAuthoritative(config: VipRemoteConfig): Boolean =
        config.success && !config.settingsUnavailable

    /**
     * Null for anything [isAuthoritative] refuses, the seven switches for a body it accepts.
     *
     * `feature_flags.chromecast` is deliberately absent from the result. This build has no cast UI,
     * so there is no feature for that switch to take away and storing it would be a dead key.
     */
    fun flagsFor(config: VipRemoteConfig): RemoteFlagWrite? {
        if (!isAuthoritative(config)) return null
        val flags = config.featureFlags
        return RemoteFlagWrite(
            maintenanceMode = config.maintenanceMode,
            downloadsEnabled = flags.downloads,
            sharingEnabled = flags.sharing,
            searchEnabled = flags.search,
            pureCinemaEnabled = flags.pureCinema,
            qualityGateEnabled = flags.qualityGate,
            adsEnabled = config.ads.enabled,
        )
    }
}
