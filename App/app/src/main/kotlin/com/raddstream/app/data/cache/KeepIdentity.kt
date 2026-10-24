package com.raddstream.app.data.cache

import java.net.URLDecoder

/**
 * The identity glue between an opaque redirector handle and the engine's byte-ledger key.
 *
 * WHY THIS EXISTS: [SourceIdentity] is the right primitive for a stable, URL-rotation-proof
 * identity, but its [SourceIdentity.key] is a pipe-joined string that the engine ALSO uses as an
 * on-disk file name (see [StorageGate.openForWrite]). A handle is base64-ish noise that can
 * contain `/`, which would corrupt that path. [SourceIdentity.digestHex] is explicitly the
 * filesystem-safe fold of that same key, so we key every keep task by the digest and keep the
 * exact handle in the task's `resourceId` column for the resolver to read back. Same identity,
 * safe name, no second state machine.
 *
 * There is deliberately nothing here that could hold a site, a hoster, or an upstream address:
 * the only address ever produced is our own redirector, rebuilt from the handle by
 * [com.raddstream.app.network.streamRedirectUrl].
 */
object KeepIdentity {

    /**
     * A fixed link-kind token used ONLY inside the identity key, so a keep's [sourceKeyFor] is
     * identical whether it was tapped on the detail screen or adopted by the player, regardless of
     * whether the eventual file turns out to be HLS or progressive. The task's own `linkKind`
     * column still records the real kind for the engine's fetch branch.
     */
    const val BOUNDARY_KIND = "media"

    /** releaseId is folded to a constant: the opaque handle is the whole identity of a keep. */
    const val KEEP_RELEASE_ID = 0L

    private const val STREAM_ROUTE = "/api/v1/stream"

    /**
     * The engine's join key + on-disk file name for an opaque handle. Deterministic across
     * restarts and across every URL rotation, because it folds only the handle.
     */
    fun sourceKeyFor(handle: String): String {
        val clean = handle.trim()
        val identity = SourceIdentity.from(
            releaseId = KEEP_RELEASE_ID,
            linkKind = BOUNDARY_KIND,
            // Any stable URL works here: with a non-blank resourceId the key never consults the
            // path, so the redirector address is supplied only to satisfy the API shape.
            url = STREAM_ROUTE,
            resourceId = clean,
            expectedSizeBytes = null,
        )
        return identity.digestHex()
    }

    /**
     * Recover the opaque handle from OUR OWN redirector address (`.../api/v1/stream?id=<handle>`),
     * url-decoded back to the exact string the server issued. Returns null for any address that is
     * not our stream route, so a non-redirector URL can never seed a keep.
     */
    fun handleFromRedirectorUrl(url: String?): String? {
        val trimmed = url?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        if (!trimmed.contains(STREAM_ROUTE)) return null
        val query = trimmed.substringAfter('?', "")
        if (query.isEmpty()) return null
        for (pair in query.split('&')) {
            val key = pair.substringBefore('=').trim()
            if (key != "id") continue
            val raw = pair.substringAfter('=', "")
            val decoded = runCatching { URLDecoder.decode(raw, "UTF-8") }.getOrNull() ?: return null
            return decoded.takeIf { it.isNotBlank() }
        }
        return null
    }

    /**
     * Map a resolved media type onto the engine's two fetch branches. Only the exact HLS
     * [CacheCoordinator.KIND_HLS] value routes to the segment buffer; everything else is treated
     * as a progressive byte-range file. Unknown or absent types are progressive, the safe default.
     */
    fun linkKindFor(mimeType: String?, playUrl: String?): String {
        val mime = mimeType?.lowercase().orEmpty()
        val urlPath = playUrl?.lowercase().orEmpty()
        val hls = mime.contains("mpegurl") || mime.contains("vnd.apple.mpegurl") || urlPath.contains(".m3u8")
        return if (hls) CacheCoordinator.KIND_HLS else KIND_PROGRESSIVE
    }

    /** The default progressive kind stored on a task when nothing marks it as HLS. */
    const val KIND_PROGRESSIVE = "progressive"
}
