package com.raddstream.app.viewmodel

import com.raddstream.app.network.buildRaddGson
import com.raddstream.app.network.models.LiveTvChannel

/**
 * App-design audit (2026-11-12, issue #13): the Live TV tab must show
 * something when the server is down — the last good channel list, saved
 * as plain JSON in SharedPreferences. Pure encode/decode, so the cache
 * round-trips in a unit test; the ViewModel only decides when to read it.
 */
object LiveTvCache {

    private val gson = buildRaddGson()

    private data class CachedList(
        val channels: List<LiveTvChannel> = emptyList(),
        val categories: List<String> = emptyList(),
    )

    fun encode(channels: List<LiveTvChannel>, categories: List<String>): String =
        gson.toJson(CachedList(channels, categories))

    fun decode(json: String?): Pair<List<LiveTvChannel>, List<String>>? {
        if (json.isNullOrBlank()) return null
        return runCatching {
            val cached = gson.fromJson(json, CachedList::class.java)
                ?: return null
            if (cached.channels.isEmpty()) null else cached.channels to cached.categories
        }.getOrNull()
    }
}
