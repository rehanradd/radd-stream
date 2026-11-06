package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.WatchHistoryEntity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * One row of the Watch history screen, as the screen needs it.
 *
 * The rail's [ResumeTile] drops a finished title on purpose — there is nothing left to
 * resume — but a history is a record, not a to-do list, so this row keeps finished titles
 * and says so. Everything else is the same arithmetic the rail already pins
 * ([ContinueWatchingTile]): the scope label, the progress fraction and the time left are
 * derived here, never stored, so the history list and the rail can never disagree about
 * where a title stopped.
 */
data class HistoryRow(
    val postId: Int,
    val title: String,
    val posterUrl: String?,
    val scopeLabel: String?,
    val progressFraction: Float?,
    val progressLabel: String?,
    val finished: Boolean,
    val dateLabel: String,
) {
    /** A row the app cannot route to a work is a row that cannot be tapped. */
    val tappable: Boolean get() = postId > 0

    /** What the row says about progress: "Finished" outranks a time-left label. */
    val statusLabel: String?
        get() = if (finished) "Finished" else progressLabel
}

/**
 * The entity-to-row mapping, kept free of Android types so a JVM test can pin it: what a
 * stored position is worth calling finished, and what day it happened on.
 */
object WatchHistoryRow {

    fun of(row: WatchHistoryEntity): HistoryRow = HistoryRow(
        postId = row.postId,
        title = row.title,
        posterUrl = row.posterUrl,
        scopeLabel = ContinueWatchingTile.scopeLabel(row.seasonNumber, row.episodeNumber),
        progressFraction = ContinueWatchingTile.progressFraction(row.positionMs, row.durationMs),
        // A finished title has no time left to report: the rail's label would say
        // "Less than a minute left" for a row stopped inside the end-guard, and the
        // screen would show that next to "Finished". Null here keeps one truth.
        progressLabel = if (isFinished(row.positionMs, row.durationMs)) null
        else ContinueWatchingTile.progressLabel(row.positionMs, row.durationMs),
        finished = isFinished(row.positionMs, row.durationMs),
        dateLabel = dateLabel(row.updatedAt),
    )

    /**
     * Finished is the rail's end-guard read the other way: stopped within the last ten
     * seconds of a known duration. A row with no duration was never measured, so it is
     * never called finished — the screen draws no bar for it rather than inventing one.
     */
    fun isFinished(positionMs: Long, durationMs: Long): Boolean =
        durationMs > 0L && positionMs >= durationMs - WatchHistoryEntity.END_GUARD_MS

    /** The day it was last watched, in the same "d MMM yyyy" shape Settings uses. */
    fun dateLabel(epochMs: Long): String =
        SimpleDateFormat("d MMM yyyy", Locale.getDefault()).format(Date(epochMs))
}
