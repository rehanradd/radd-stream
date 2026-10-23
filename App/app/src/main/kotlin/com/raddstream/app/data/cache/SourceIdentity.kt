package com.raddstream.app.data.cache

/**
 * Stable identity for "the same downloadable resource", deliberately independent of the raw
 * URL, because stream URLs rotate on every resolve (`is_temporary=1` / `ephemeral=1` sources
 * in `cat_links`, and `POST /api/v2/play` returns a fresh signed URL each session).
 *
 * The cache keys all byte ledgers, files and tasks by this identity so that when an
 * ephemeral source dies mid-download and the app re-resolves it and receives a *different*
 * URL for the *same* file, the bytes already on disk are adopted, not re-fetched.
 *
 * Identity ladder (mirrors `API_V2.md` §2 philosophy, applied to bytes not works):
 *  1. backend `resource_id` (a content hash some services expose) + release id — strongest
 *  2. `release_id` + `link_kind` + normalised URL path (query/fragment stripped) + size
 *  3. `release_id` + normalised URL path + size
 * A size is required when present so two different prints under one release never collide.
 */
data class SourceIdentity(
    val releaseId: Long,
    val resourceId: String?,
    val linkKind: String,
    val normalizedPath: String,
    val expectedSizeBytes: Long?,
) {
    /**
     * A compact, collision-resistant key. Deterministic across app restarts and across URL
     * rotations for the same underlying resource. Not reversible to the original URL.
     */
    fun key(): String {
        val sizePart = expectedSizeBytes?.toString() ?: "na"
        return if (!resourceId.isNullOrBlank()) {
            "rid|$releaseId|$linkKind|$resourceId|$sizePart"
        } else {
            "pth|$releaseId|$linkKind|$normalizedPath|$sizePart"
        }
    }

    /**
     * 64-bit FNV-1a fold of [key], used to build short, filesystem-safe file names. Not a
     * security hash — just a stable, well-distributed digest for local cache filenames.
     */
    fun digestHex(): String {
        var hash = 0xcbf29ce484222325UL
        val prime = 0x100000001b3UL
        for (b in key().encodeToByteArray()) {
            hash = hash xor b.toULong()
            hash = hash * prime
        }
        // fold to 16 hex chars
        return hash.toString(16).padStart(16, '0')
    }

    companion object {
        /**
         * Build an identity from whatever the resolver gave us. [url] is normalised by
         * dropping scheme, host, query and fragment so a rotating signed URL still maps to
         * the same path; when the backend provides a [resourceId] we prefer that entirely.
         */
        fun from(
            releaseId: Long,
            linkKind: String,
            url: String,
            resourceId: String? = null,
            expectedSizeBytes: Long? = null,
        ): SourceIdentity = SourceIdentity(
            releaseId = releaseId,
            resourceId = resourceId?.takeIf { it.isNotBlank() },
            linkKind = linkKind,
            normalizedPath = normalizePath(url),
            expectedSizeBytes = expectedSizeBytes?.takeIf { it > 0 },
        )

        /**
         * Reduce a URL to its path with no query/fragment and no host. `https://cdn-a/x/file.mp4?sig=1`
         * and `https://cdn-b/x/file.mp4?sig=99&exp=2` share the path `/x/file.mp4`, so they
         * are the same resource to us. Query params are exactly the part that rotates.
         */
        fun normalizePath(url: String): String {
            val withoutScheme = url.substringAfter("://", url)
            val hostSplit = withoutScheme.substringAfter("/", "")
            val path = if (withoutScheme.contains('/')) hostSplit else ""
            val noQuery = path.substringBefore('?')
            val noFragment = noQuery.substringBefore('#')
            return if (noFragment.isBlank()) "/" else "/${noFragment.trimStart('/')}"
        }
    }
}
