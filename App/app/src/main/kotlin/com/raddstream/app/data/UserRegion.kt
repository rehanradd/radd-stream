package com.raddstream.app.data

/**
 * The viewer's regional-dub preference, stored by
 * [ServerSettingsRepository.userRegion] under the wire names below.
 *
 * Only [DESI_DUBS] changes presentation today: it asks the detail screen to lead with
 * Hindi, Urdu and dual-audio prints so a Pakistani or Indian viewer does not have to
 * scroll past English originals to find the dub. The other two values are accepted and
 * stored unchanged so a viewer's choice is never silently rewritten; no list is
 * re-ranked for them, because the catalog publishes no equivalent priority to apply.
 *
 * An unreadable stored value falls back to [DEFAULT] rather than to a guess.
 */
object UserRegion {
    const val DESI_DUBS = "desi_dubs"
    const val EAST_ASIAN = "east_asian"
    const val INTERNATIONAL = "international"

    /** The shipped default: Pakistan/India first, per the product's audience. */
    const val DEFAULT = DESI_DUBS

    val ALL: List<String> = listOf(DESI_DUBS, EAST_ASIAN, INTERNATIONAL)

    /** Trim, case-fold, and fall back to [DEFAULT] for anything not in [ALL]. */
    fun normalize(raw: String?): String =
        raw?.trim()?.lowercase()?.takeIf { it in ALL } ?: DEFAULT
}
