package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.WatchHistoryEntity
import com.raddstream.app.network.models.Post

/**
 * One row of the Continue watching rail, as the tile needs it.
 *
 * The rail used to hand `HomeScreen` a bare [Post] and drop the position on the floor, so a
 * viewer saw a poster that looked exactly like any other poster and had to tap into the work,
 * find the episode and press play before learning whether this was the one they stopped
 * halfway through. Where viewing stopped is the whole point of the row, so it travels with it.
 *
 * Every label here is derived, never stored: [WatchHistoryEntity] already holds the timestamps
 * and the merge that produced this row already decided it is worth showing.
 */
data class ResumeTile(
    val post: Post,
    val season: Int,
    val episode: Int,
    val positionMs: Long,
    val durationMs: Long,
) {
    val progressFraction: Float? get() = ContinueWatchingTile.progressFraction(positionMs, durationMs)
    val progressLabel: String? get() = ContinueWatchingTile.progressLabel(positionMs, durationMs)
    val scopeLabel: String? get() = ContinueWatchingTile.scopeLabel(season, episode)

    /** What the tile says out loud, in the one node TalkBack reads for the whole card. */
    val resumeLabel: String?
        get() = listOfNotNull(scopeLabel, progressLabel).joinToString(" · ")
            .takeIf { it.isNotBlank() }

    companion object {
        /** A row the app cannot route to a work is a row that cannot be tapped. */
        fun of(row: WatchHistoryEntity): ResumeTile? {
            if (row.postId <= 0) return null
            return ResumeTile(
                post = Post(
                    id = row.postId,
                    title = row.title,
                    cleanTitle = row.title,
                    posterUrl = row.posterUrl,
                ),
                season = row.seasonNumber,
                episode = row.episodeNumber,
                positionMs = row.positionMs,
                durationMs = row.durationMs,
            )
        }
    }
}

/**
 * The arithmetic of a resume tile, kept free of Android types so a JVM test can pin it: what
 * fraction of a title is gone, what to call that in words, and what a season/episode scope is
 * worth saying at all.
 */
object ContinueWatchingTile {

    private const val MINUTE_MS = 60_000L

    /**
     * 0f..1f watched, or null when the file never reported a duration. A missing duration is
     * not 100 % and not 0 %: the tile paints no bar rather than inventing one.
     */
    fun progressFraction(positionMs: Long, durationMs: Long): Float? {
        if (durationMs <= 0L || positionMs < 0L) return null
        return (positionMs.toFloat() / durationMs.toFloat()).coerceIn(0f, 1f)
    }

    /**
     * "S2:E5" for an episode, null for a whole work. A movie row carries 0/0 and a bare
     * "S0:E0" would be a lie about a thing that has no seasons.
     */
    fun scopeLabel(season: Int, episode: Int): String? =
        if (season > 0 && episode > 0) "S$season:E$episode" else null

    /**
     * "23 min left", "1 h 40 m left", "2 h left", "Less than a minute left" — or null when the
     * duration is unknown or the row has run past its own end, because then there is nothing
     * honest to promise about what remains.
     */
    fun progressLabel(positionMs: Long, durationMs: Long): String? {
        if (durationMs <= 0L || positionMs < 0L) return null
        val remaining = durationMs - positionMs
        if (remaining <= 0L) return null
        if (remaining < MINUTE_MS) return "Less than a minute left"
        val minutes = remaining / MINUTE_MS
        if (minutes < 60L) return "$minutes min left"
        val hours = minutes / 60
        val rest = minutes % 60
        return if (rest == 0L) "$hours h left" else "$hours h $rest m left"
    }
}
