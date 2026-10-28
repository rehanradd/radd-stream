package com.raddstream.app.data

/**
 * The operator's feature board, as ONE snapshot of what this app is allowed to offer.
 *
 * Why a single type instead of four flows: the switches are written by
 * [com.raddstream.app.data.RemoteConfigWatcher] in one atomic DataStore edit, but a screen that
 * reads them one at a time can still catch two different refreshes — the tab bar hiding Search
 * while the Offline card still offers Downloads. Collecting this one object makes the whole board
 * arrive together, so every entry point on a screen answers to the same server answer.
 *
 * What this is NOT: a preference. The viewer's own switches (`share over LAN`, dynamic colour,
 * Ghost mode) live beside it and are ANDed with it — an operator switch can only take a feature
 * away, never grant one the viewer did not ask for. `quality_gate` is deliberately absent: it
 * withholds content rather than offering a feature, and
 * [com.raddstream.app.viewmodel.VipQualityGate] is already its only reader.
 */
data class RemoteFeatures(
    val downloads: Boolean = true,
    val sharing: Boolean = true,
    val search: Boolean = true,
    val pureCinema: Boolean = true,
)
