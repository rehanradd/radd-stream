package com.raddstream.app.viewmodel

import com.google.gson.Gson
import com.raddstream.app.network.models.Post

/**
 * Gap A5 — cache-first Home: the last good Home, kept on disk as one JSON
 * string, so the page opens on real rows instantly and refreshes behind
 * them instead of opening on skeletons.
 *
 * The payload is the app's own cache file, not a wire format: plain Gson
 * field names, no versioning — a payload that fails to decode is dropped
 * and the network load proceeds, so a corrupt cache can never blank Home.
 * Panel-managed sections are never cached ([cachedSectionsOf] drops them):
 * their rows come with the remote config, and a restored copy would be
 * loaded through the posts route as if it were a built-in rail.
 */
internal data class CachedHomeSection(
    val key: String,
    val title: String,
    val type: String?,
    val sort: String?,
    val relatedWorkId: Int? = null,
    val items: List<Post> = emptyList(),
)

internal data class CachedHomePayload(
    val updatedAtMs: Long,
    val sections: List<CachedHomeSection> = emptyList(),
)

private val homeCacheGson = Gson()

internal fun cachedSectionsOf(sections: List<HomeSection>): List<CachedHomeSection> =
    sections.filterNot { it.panelManaged }.map { section ->
        CachedHomeSection(
            key = section.key,
            title = section.title,
            type = section.type,
            sort = section.sort,
            relatedWorkId = section.relatedWorkId,
            items = section.items,
        )
    }

internal fun encodeHomeCache(sections: List<HomeSection>, updatedAtMs: Long): String =
    homeCacheGson.toJson(CachedHomePayload(updatedAtMs = updatedAtMs, sections = cachedSectionsOf(sections)))

internal fun decodeHomeCache(json: String): CachedHomePayload? =
    runCatching {
        homeCacheGson.fromJson(json, CachedHomePayload::class.java)
    }.getOrNull()?.takeIf { it.sections.isNotEmpty() }

internal fun restoreHomeSections(payload: CachedHomePayload): List<HomeSection> =
    payload.sections.map { cached ->
        HomeSection(
            key = cached.key,
            title = cached.title,
            type = cached.type,
            items = cached.items,
            sort = cached.sort,
            relatedWorkId = cached.relatedWorkId,
            loading = false,
        )
    }
