package com.raddstream.app.player

/**
 * Data Saver and Wi-Fi-only downloads — the two switches that decide what
 * mobile data may carry.
 *
 * Data Saver is a start, not a lock: on mobile data a title *starts* at 480p
 * and the server is asked for its data-saving copy, but the viewer can still
 * switch up in the quality sheet. Wi-Fi-only is a gate: a download does not
 * start on mobile data at all while it is on. Both are off on Wi-Fi, where
 * nothing needs saving.
 */
object DataSaver {

    /** The `prefer` value /api/v2/play understands for a data-saving order. */
    const val PREFER_DATA_SAVER = "data_saver"

    /** The band mobile-data playback starts at while Data Saver is on. */
    const val CAP_BAND = "480p"

    private val BAND_RANKS = mapOf("480p" to 0, "720p" to 1, "1080p" to 2, "2160p" to 3)

    /**
     * The band a title starts on. Data Saver on mobile data pulls anything
     * above 480p down to 480p — but only when 480p is actually on this
     * ladder; a ladder with no 480p rung keeps its own band rather than
     * naming a rung that does not exist.
     */
    fun capBand(band: String, rungBands: List<String>, dataSaver: Boolean, onWifi: Boolean): String {
        if (!dataSaver || onWifi) return band
        val capRank = BAND_RANKS[CAP_BAND] ?: return band
        val bandRank = BAND_RANKS[band.trim().lowercase()] ?: return band
        if (bandRank <= capRank) return band
        return if (rungBands.any { it.trim().equals(CAP_BAND, ignoreCase = true) }) CAP_BAND else band
    }

    /**
     * What /api/v2/play is asked to prefer, or null to leave the caller's
     * own default alone. The server already orders by quality unless told
     * otherwise; this only overrides it on mobile data.
     */
    fun playPrefer(dataSaver: Boolean, onWifi: Boolean): String? =
        if (dataSaver && !onWifi) PREFER_DATA_SAVER else null

    /** Whether a download may start on this network while Wi-Fi-only is on. */
    fun wifiOnlyBlocks(wifiOnly: Boolean, onWifi: Boolean): Boolean = wifiOnly && !onWifi
}
