package com.raddstream.app.share

import com.raddstream.app.data.cache.CacheFileEntity
import java.io.File

/**
 * Builds the servable [ShareTarget] catalog from the cache engine's own committed-file listing,
 * and holds the pure decisions that go with it: which rows qualify, what opaque token each gets,
 * what content type it advertises, and which local address a share URL may name.
 *
 * Why this is a separate pure object (no sockets, no Android): the whole "what is shareable right
 * now" question is answered here, so the [LanShareServer] is never the thing deciding what exists.
 * The servable set is fixed by our catalog — a client can only ever pick a token that this listing
 * produced, and everything it does not produce is structurally unshareable.
 *
 * PROVENANCE (root AGENTS.md, `Fast_Fetch/API_V2.md` §16.9): nothing emitted from here names a
 * site, a hoster, or an upstream URL. The only identifier is [CacheFileEntity.fileId] — our own
 * opaque digest-named handle — and the only content-type is chosen from the container, never from
 * a source. A row that cannot be described without provenance is simply not made shareable.
 */
object ShareCatalog {

    /**
     * The honest "shareable" predicate, matching [com.raddstream.app.data.cache.OfflineCacheEngine]'s
     * playable rule exactly: a file is servable only when it is complete and no longer a temp
     * partial. Auto-preview, in-flight, and TTL-swept rows are excluded — you can never share a
     * byte that our own player would not open.
     */
    fun fromCommittedFiles(files: List<CacheFileEntity>): Map<String, ShareTarget> {
        val out = LinkedHashMap<String, ShareTarget>()
        for (f in files) {
            if (!f.isComplete || f.isTemporary) continue
            if (f.sizeBytes <= 0L) continue
            if (f.path.isBlank()) continue
            // The token IS our on-disk file id; if it is not one clean path segment it could not be
            // looked up by the server anyway, so refuse to advertise it rather than half-support it.
            val token = f.fileId
            if (!isCleanToken(token)) continue
            out[token] = ShareTarget(
                entry = ShareEntry(
                    fileName = token,
                    sizeBytes = f.sizeBytes,
                    contentType = contentTypeFor(f.path),
                    enabled = true,
                ),
                file = File(f.path),
            )
        }
        return out
    }

    /**
     * Maps a container extension onto the content type we advertise. Unknown or extensionless
     * names (which is what our own cache files have) fall back to the generic byte-stream type —
     * an honest "this is opaque bytes" rather than a guessed container a player might mishandle,
     * and crucially never derived from where the bytes came from.
     */
    fun contentTypeFor(fileName: String): String =
        when (fileName.substringAfterLast('.', "").lowercase()) {
            "mp4", "m4v" -> "video/mp4"
            "mkv", "mka" -> "video/x-matroska"
            "webm" -> "video/webm"
            "ts", "m2ts" -> "video/mp2t"
            "mp3" -> "audio/mpeg"
            "m4a" -> "audio/mp4"
            "srt" -> "application/x-subrip"
            "vtt" -> "text/vtt"
            else -> "application/octet-stream"
        }

    /**
     * A token is shareable only if it is a single clean path segment: non-blank and free of any
     * separator, traversal marker, or percent escape. Same shape rule the server and protocol
     * already enforce on inbound paths, applied here to outbound catalog keys so a malformed file
     * id can never produce a URL that 404s on its own token.
     */
    fun isCleanToken(token: String): Boolean =
        token.isNotBlank() &&
            token.none { it == '/' || it == '\\' || it == '%' || it.isWhitespace() } &&
            !token.contains("..")

    /**
     * Picks the address a LAN peer is actually meant to reach: the first private (RFC 1918) IPv4
     * candidate. Loopback and link-local (169.254/16, the "no DHCP" address) are skipped because a
     * peer on the network cannot use either; if nothing qualifies the caller shows a state without a
     * concrete address rather than inventing one. Pure over a list of dotted-quad strings so it is
     * JVM-testable with no network present.
     */
    fun firstSiteLocalIpv4(candidates: List<String>): String? = candidates.firstOrNull { isPrivateIpv4(it) }

    private fun isPrivateIpv4(address: String): Boolean {
        val octets = address.split('.')
        if (octets.size != 4) return false
        val nums = octets.map { it.toIntOrNull() ?: return false }
        if (nums.any { it !in 0..255 }) return false
        return when {
            nums[0] == 10 -> true
            nums[0] == 172 && nums[1] in 16..31 -> true
            nums[0] == 192 && nums[1] == 168 -> true
            else -> false
        }
    }
}
