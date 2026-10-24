package com.raddstream.app.data.cache

import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.streamRedirectUrl
import com.raddstream.app.repository.CatalogRepository
import javax.inject.Inject
import javax.inject.Singleton

/**
 * One keep, reduced to everything the engine needs to start driving it — all of it derived from
 * OUR OWN opaque handle. It cannot carry a site, a hoster, or an upstream address because the only
 * address here is [redirectUrl], our redirector, rebuilt by
 * [com.raddstream.app.network.streamRedirectUrl].
 */
data class KeepSeed(
    val sourceKey: String,
    val handle: String,
    val redirectUrl: String,
    val linkKind: String,
    val releaseId: Long,
    val totalSizeBytes: Long,
)

/**
 * Turns an opaque handle into a [KeepSeed] (at enqueue) and refreshes a rotted one (at re-resolve).
 * Split from the engine's [SourceResolver] so the repository can seed a brand-new keep without a
 * task row existing yet, while the engine re-resolves an already-stored one. The production
 * implementation is [RedirectorSourceResolver]; tests inject a fake that answers from memory.
 */
interface KeepSourceFactory {
    /** Build the first seed for a handle the user just asked to keep. Null if it cannot be ours. */
    suspend fun seedForKeep(handle: String, sizeBytes: Long?, resumable: Boolean): KeepSeed?

    /** Rebuild our redirector address for a handle after its bytes rotted. Null when unknown. */
    suspend fun refreshUrl(handle: String): String?
}

/**
 * The single wiring seam between the cache engine and the app's existing network layer.
 *
 * Re-resolution always goes back through OUR OWN redirector (`/api/v1/stream?id=<handle>`, the same
 * pattern [com.raddstream.app.player.PlayBundle] plays from): the engine hands this class a
 * sourceKey, it recovers the handle from the task's persisted `resourceId`, asks the redirector
 * about the handle with `redirect=0` (metadata only — never a location), and rebuilds our address.
 * No upstream host ever leaves the server, so nothing stored here is ever a hoster URL.
 *
 * It implements both the engine's [SourceResolver] and the repository's [KeepSourceFactory] so a
 * new keep and a mid-download re-resolve share exactly one address builder and one identity rule —
 * the same handle always maps to the same [KeepIdentity.sourceKeyFor] key, which is what lets a
 * resumed download adopt its existing bytes instead of re-fetching from zero.
 */
@Singleton
class RedirectorSourceResolver @Inject constructor(
    private val apiProvider: ApiProvider,
    private val catalogRepository: CatalogRepository,
    private val taskDao: CacheTaskDao,
) : SourceResolver, KeepSourceFactory {

    /** The engine's seam: given a sourceKey, recover the handle and hand back a fresh address. */
    override suspend fun reResolve(sourceKey: String, releaseId: Long): ResolvedSource? {
        val task = taskDao.getBySourceKey(sourceKey) ?: return null
        val handle = task.resourceId ?: KeepIdentity.handleFromRedirectorUrl(task.currentUrl) ?: return null
        val url = refreshUrl(handle) ?: return null
        return ResolvedSource(
            releaseId = releaseId,
            linkKind = task.linkKind,
            url = url,
            resourceId = handle,
            sizeBytes = task.totalSizeBytes.takeIf { it > 0 },
        )
    }

    override suspend fun seedForKeep(handle: String, sizeBytes: Long?, resumable: Boolean): KeepSeed? {
        val clean = handle.trim().takeIf { it.isNotEmpty() } ?: return null
        val url = refreshUrl(clean) ?: return null
        // Best-effort metadata refresh; if the server gives us nothing we still have a size from
        // the ladder and a progressive kind, so a keep is never blocked by a metadata round trip.
        val meta = runCatching { catalogRepository.resolveStream(clean) }.getOrNull()
        val knownSize = sizeBytes?.takeIf { it > 0 }
            ?: meta?.fileSizeBytes?.takeIf { it > 0 }
            ?: 0L
        val kind = KeepIdentity.linkKindFor(meta?.mimeType, null)
        return KeepSeed(
            sourceKey = KeepIdentity.sourceKeyFor(clean),
            handle = clean,
            redirectUrl = url,
            linkKind = kind,
            releaseId = KeepIdentity.KEEP_RELEASE_ID,
            totalSizeBytes = knownSize,
        )
    }

    override suspend fun refreshUrl(handle: String): String? {
        val baseUrl = runCatching { apiProvider.currentBaseUrl() }.getOrNull() ?: return null
        return streamRedirectUrl(baseUrl, handle).takeIf { it.contains("/api/v1/stream") }
    }
}
