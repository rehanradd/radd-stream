package com.raddstream.app.ui.navigation

import java.net.URLDecoder
import java.nio.charset.StandardCharsets

/**
 * Another app asked us to open one of this device's video files; this is the route that plays
 * it.
 *
 * The rule is deliberately split from the Android code that reads the Intent. A VIEW intent
 * arrives at a cold start, at a warm start, from a file manager, from a mail attachment, from a
 * browser's download row, and it can be built by anything on the phone — so "what may this
 * intent make us play" is the kind of question that gets one owner and gets answered without
 * an emulator in the loop.
 *
 * Two refusals matter:
 *
 *  - **The scheme must be local.** Only `content` and `file` are accepted. The manifest filter
 *    says `video/` and a MIME wildcard, but a wildcard filter is an invitation, and an app that
 *    names `https://…` here would be asking our player to open an address that never went
 *    through the server's stream handle — no adult redaction, no provenance, no failover, no
 *    consent about which host the app talks to. That door stays shut: a remote address gets a
 *    handle from our API or it gets nothing.
 *  - **The thing must be a video we can read.** Either the resolved MIME says `video/`, or the
 *    name carries an extension the progressive reader knows. An arbitrary `content://` row is
 *    not a licence to play whatever it points at.
 *
 * What it produces is the existing finished-download route, not a new one: [Screen.PlayerLocal]
 * already plays a local URI through the same player, so a file opened from outside the app and a
 * file the app saved itself are the same thing with the same controls.
 */
data class LocalVideoOpen(val uri: String, val title: String, val nonce: Long) {

    /** The route this open plays on, encoded by the one codec that owns route arguments. */
    val route: String get() = Screen.PlayerLocal.createRoute(uri, title)

    companion object {

        private val localSchemes = setOf("content", "file")

        /**
         * Containers ExoPlayer's own extractors read from the bytes — so a name is enough to
         * accept the file, and no extension here needs to be complete: an unrecognised
         * extension with a `video/` MIME is still opened, because the MIME came from the
         * provider that owns the file and the reader sniffs anyway.
         */
        private val videoExtensions = setOf(
            "3gp", "avi", "flv", "m4v", "mkv", "mov", "mp4", "mpg", "mpeg", "ogv", "ts", "webm", "wmv",
        )

        /** A file the address cannot name. Never a blank: the player paints this over the controls. */
        private const val UNTITLED = "Local video"

        /**
         * The parts of an Intent, as strings, so the decision can be tested on a JVM:
         * [scheme] and [lastPathSegment] are the URI's own, [address] is the whole URI, and
         * [mimeType] is the intent's declared type with the content resolver's resolved type
         * behind it — the caller's job is to hand over both, this function's job is to decide.
         *
         * [nonce] makes two opens of the same file two requests: the route is built from the
         * URI and the title, so an identical file tapped twice would otherwise be an identical
         * key that a `LaunchedEffect` is free to ignore.
         */
        fun from(
            scheme: String?,
            address: String?,
            mimeType: String?,
            lastPathSegment: String?,
            nonce: Long,
        ): LocalVideoOpen? {
            val uri = address?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            val protocol = scheme?.lowercase() ?: return null
            if (protocol !in localSchemes) return null
            val extension = lastPathSegment?.substringAfterLast('.', "").orEmpty().lowercase()
            val isVideo = mimeType?.lowercase()?.startsWith("video/") == true || extension in videoExtensions
            if (!isVideo) return null
            return LocalVideoOpen(uri = uri, title = titleFrom(lastPathSegment), nonce = nonce)
        }

        /**
         * A display name out of whatever the address has to offer.
         *
         * A `file://` path hands over its last segment plainly. A documents-provider URI hands
         * over one segment that is a whole path with the separator percent-escaped inside it
         * (`primary%3AMovies%2Fclip.mp4`), so decoding is what turns it back into a name — and
         * the decode is guarded, because a stray percent-sign in a file name is legal and a
         * malformed escape is not a reason to lose the title.
         *
         * A MediaStore URI often carries no name at all, only the row id
         * (`content://media/external/video/media/42`). A title of "42" would be a lie about
         * having found a name, so an all-digit segment falls back to [UNTITLED]. Reading the
         * real display name out of the media provider is a query on the thread that is trying
         * to show the first frame; the name is not worth that.
         */
        private fun titleFrom(lastPathSegment: String?): String {
            val raw = lastPathSegment?.takeIf { it.isNotEmpty() } ?: return UNTITLED
            val decoded = try {
                URLDecoder.decode(raw, StandardCharsets.UTF_8.name())
            } catch (_: Exception) {
                raw
            }
            val name = decoded.substringAfterLast(':').substringAfterLast('/').substringBeforeLast('.')
            val cleaned = name.replace('_', ' ').filterNot { it.isISOControl() }.trim().take(80)
            return cleaned.takeIf { it.isNotEmpty() && !cleaned.all { ch -> ch.isDigit() } } ?: UNTITLED
        }
    }
}
