package com.raddstream.app.share

/**
 * The observable state of the LAN share feature, surfaced to Settings. It reports what is really
 * happening on the socket, never what the toggle asked for: a share that was enabled but could not
 * bind the port shows as [Failed] rather than pretending a URL works, and [Listening] carries the
 * concrete address and the count of files currently servable so the row can show the truth.
 */
sealed interface LanShareStatus {
    /** Sharing is off; nothing is bound and nothing is readable over the network. */
    data object Off : LanShareStatus

    /** The socket is listening. [address] is null when the device has no private IPv4 to name. */
    data class Listening(
        val port: Int,
        val address: String?,
        /** How many kept files this catalog currently exposes. */
        val servableCount: Int,
        /**
         * The session token this start minted. It is carried here so the UI can build
         * the share URL ([LanShareProtocol.shareUrl]) for the peer the viewer chose;
         * it is never rendered in a status line or a log, and a restart mints a new one.
         */
        val sessionToken: String = "",
    ) : LanShareStatus

    /** The user turned it on but the server could not start (almost always the port is busy). */
    data object Failed : LanShareStatus
}
