package com.raddstream.app.player
import com.raddstream.app.network.models.CoverageType

/**
 * Auto-advance across the coverage types the backend actually ships (API_V2.md §2.3 / §6
 * scenarios 4-7): per-episode files, `episode_range` batches (EP01-06 in one file),
 * `season_pack` (whole season in one file), and mixed availability.
 */

sealed class NextEpisodeAction {
    /** Next episode lives in THIS file at a known offset → seek, no new bundle needed. */
    data class InFileSeek(val positionMs: Long, val nextEpisode: Int, val fromLearned: Boolean) : NextEpisodeAction()

    /** Next episode lives in ANOTHER file → ask the app for a new PlayBundle. */
    data class NextBundleRequest(
        val workKey: String?,
        val postId: Int?,
        val season: Int,
        val nextEpisode: Int,
        val episodeId: Int?,
    ) : NextEpisodeAction()

    /** Packed file but the next episode's position is unknown → calibration prompt. */
    data class CalibrationNeeded(val nextEpisode: Int, val packWarning: String?) : NextEpisodeAction()

    /** Movie / part / nothing follows → let playback end. */
    object StopHere : NextEpisodeAction()

    /** No target coordinates at all (plain v1 link without episode identity). */
    object Unknown : NextEpisodeAction()
}

object EpisodeProgression {

    /**
     * @param positionMs where playback stopped (normally == durationMs).
     * @param durationMs duration of the active media item.
     */
    fun computeNext(
        bundle: PlaybackBundle,
        rendition: PlaybackRendition?,
        learned: LearnedOffsetStore,
        positionMs: Long,
        durationMs: Long,
    ): NextEpisodeAction {
        val target = bundle.target
        val coverage = rendition?.coverage ?: return NextEpisodeAction.Unknown
        val season = coverage.season.takeIf { it > 0 } ?: target.season
        val current = target.episode.takeIf { it > 0 } ?: coverage.ordinal
        if (current <= 0) return NextEpisodeAction.Unknown

        val nextEpisode = current + 1

        return when (coverage.type()) {
            CoverageType.SINGLE_EPISODE, CoverageType.WHOLE_WORK, CoverageType.PARTS,
            CoverageType.UNKNOWN,
            -> if (bundle.target.workType?.seriesLike() == true || target.episode > 0) {
                NextEpisodeAction.NextBundleRequest(
                    workKey = target.workKey,
                    postId = target.id.takeIf { it > 0 },
                    season = season,
                    nextEpisode = nextEpisode,
                    episodeId = null,
                )
            } else {
                NextEpisodeAction.StopHere // a movie finished
            }

            CoverageType.EPISODE_RANGE, CoverageType.SEASON_PACK -> {
                val inRange = coverage.type() == CoverageType.EPISODE_RANGE &&
                    nextEpisode in (coverage.firstEpisode..coverage.lastEpisode)
                val packMayContinue = coverage.type() == CoverageType.SEASON_PACK &&
                    (coverage.lastEpisode == 0 || nextEpisode <= coverage.lastEpisode)
                if (!inRange && !packMayContinue) {
                    return NextEpisodeAction.NextBundleRequest(
                        workKey = target.workKey,
                        postId = target.id.takeIf { it > 0 },
                        season = season,
                        nextEpisode = nextEpisode,
                        episodeId = null,
                    )
                }
                val learnedOffset = learned.lookup(
                    target.workKey, season, nextEpisode, rendition.print.label,
                )
                val serverOffset = coverage.episodes.firstOrNull { it.number == nextEpisode }?.offsetSeconds
                when {
                    learnedOffset != null ->
                        NextEpisodeAction.InFileSeek(learnedOffset * 1000L, nextEpisode, true)
                    serverOffset != null ->
                        NextEpisodeAction.InFileSeek(serverOffset * 1000L, nextEpisode, false)
                    positionMs > 0 ->
                        // No chapter data: batches are contiguous, so "end of this episode ==
                        // start of next". MX-style continuation; the user can re-calibrate.
                        NextEpisodeAction.InFileSeek(positionMs.coerceAtMost(durationMs), nextEpisode, false)
                    else -> NextEpisodeAction.CalibrationNeeded(nextEpisode, coverage.packWarning)
                }
            }
        }
    }

    /** `cat_works.work_type` values that have episodes at all (catalog_v2._SERIES_TYPES). */
    fun seriesLikeWorkType(workType: String?): Boolean =
        workType?.lowercase() in setOf("series", "anime", "miniseries", "complete_season", "ongoing_season")

    private fun String.seriesLike(): Boolean = seriesLikeWorkType(this)
}
