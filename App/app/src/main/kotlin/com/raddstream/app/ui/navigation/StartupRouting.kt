package com.raddstream.app.ui.navigation

/**
 * Where a cold start lands, as a pure rule — no store, no network, no clock.
 *
 * A fresh install never sees the Setup form when the shipped server answers: the
 * caller probes the shipped default once, in the background, and passes the
 * answer in as [defaultServerReachable]. The rule is fail-closed on purpose — a
 * default that was never probed, or one that did not answer, is Setup, never a
 * silent guess at Home. An install that already chose a server skips the probe
 * entirely ([defaultServerReachable] is null) and goes by the region answer.
 *
 * `savedUrl` is the [com.raddstream.app.data.ServerSettingsRepository.serverUrl]
 * flow's value, which already falls back to the brand default when nothing is
 * saved — so a blank value here means "no server anywhere", i.e. an unbranded
 * build with no default to probe.
 */
enum class StartDestination {
    Setup,
    Region,
    Home,
}

fun resolveStartDestination(
    savedUrl: String?,
    hasSavedServerUrl: Boolean,
    defaultServerReachable: Boolean?,
    regionUnanswered: Boolean,
): StartDestination = when {
    savedUrl.isNullOrBlank() -> StartDestination.Setup
    !hasSavedServerUrl && defaultServerReachable != true -> StartDestination.Setup
    regionUnanswered -> StartDestination.Region
    else -> StartDestination.Home
}
