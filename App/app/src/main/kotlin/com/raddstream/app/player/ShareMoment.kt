package com.raddstream.app.player

import com.raddstream.app.viewmodel.formatTime

/**
 * SC.24: share a moment from the player. The shared text is a plain sentence with
 * the title, the timestamp, and the app's own deep link — never a host name or a
 * raw file URL, and never a bare handle: the link is `DeepLinks.streamUri`, the
 * same `radd://stream/...` the app itself routes, so the recipient opens the
 * title in the app instead of a browser tab full of someone else's page. Pure
 * text building, JVM-testable; the Compose side only hands it to the share sheet.
 */
object ShareMoment {

    /**
     * "Title — 12:34\nradd://stream/<id>/Title" — the timestamp is the position the
     * viewer was at when they tapped share, formatted the same way the player shows
     * time everywhere else. A blank title falls back to "this moment" so the text is
     * never an empty sentence.
     */
    fun shareText(title: String, positionMs: Long, deepLink: String): String {
        val safeTitle = title.trim().ifBlank { "this moment" }
        return "$safeTitle — ${positionMs.coerceAtLeast(0L).formatTime()}\n$deepLink"
    }
}
