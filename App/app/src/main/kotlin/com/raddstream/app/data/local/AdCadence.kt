package com.raddstream.app.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import com.raddstream.app.player.AdCadenceState
import com.raddstream.app.player.AdSurface

/**
 * One ad surface's cadence facts, as they survive process death.
 *
 * Three rows, one per surface, because the alternative — one row per impression — grows with
 * every ad shown and buys a history nothing reads. The rule only ever needs the last impression
 * and, for the feed card, how many posters have gone by since it.
 *
 * `lastShownAtMs` is wall clock, not uptime: an `elapsedRealtime()` value written before a reboot
 * restarts at zero, which would make every viewer eligible again each time their device restarts.
 * Zero means "never shown", so a fresh install needs no special case.
 */
@Entity(tableName = "ad_cadence")
data class AdCadenceEntity(
    @PrimaryKey val surface: String,
    val lastShownAtMs: Long,
    /** Only the feed card uses this; the other two surfaces keep it at zero. */
    val postersScrolled: Int,
)

@Dao
interface AdCadenceDao {

    @Query("SELECT * FROM ad_cadence")
    suspend fun all(): List<AdCadenceEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(row: AdCadenceEntity)

    /**
     * Every stamp and counter, dropped. Called when the operator turns the ad surfaces off, so a
     * throttled viewer is not left throttled by a window nobody is enforcing any more.
     */
    @Query("DELETE FROM ad_cadence")
    suspend fun clear()
}

/**
 * The row<->state bridge, kept pure and total so the persistence contract is testable on a JVM.
 *
 * Room itself cannot be opened here — Robolectric has no native runtime on aarch64, so an
 * in-memory database test would be a test that never runs — which makes this mapping the part
 * worth pinning: a state that silently loses its stamps on the way to disk would look identical
 * on screen and only differ after a process death.
 */
object AdCadenceRows {

    fun toState(rows: List<AdCadenceEntity>, enabled: Boolean): AdCadenceState {
        val bySurface = rows.associateBy { it.surface }
        return AdCadenceState(
            enabled = enabled,
            preRollShownAtMs = bySurface[surfaceKey(AdSurface.PRE_ROLL)]?.lastShownAtMs ?: 0L,
            feedCardShownAtMs = bySurface[surfaceKey(AdSurface.FEED_CARD)]?.lastShownAtMs ?: 0L,
            postersSinceFeedCard = bySurface[surfaceKey(AdSurface.FEED_CARD)]?.postersScrolled ?: 0,
            appOpenShownAtMs = bySurface[surfaceKey(AdSurface.APP_OPEN)]?.lastShownAtMs ?: 0L,
        )
    }

    /**
     * The rows that describe [state]. A surface that has never shown and counted nothing is
     * written anyway — three rows, always — so a reader never has to guess whether an absent row
     * means "never" or "not migrated yet".
     */
    fun toRows(state: AdCadenceState): List<AdCadenceEntity> = listOf(
        AdCadenceEntity(surfaceKey(AdSurface.PRE_ROLL), state.preRollShownAtMs, 0),
        AdCadenceEntity(surfaceKey(AdSurface.FEED_CARD), state.feedCardShownAtMs, state.postersSinceFeedCard),
        AdCadenceEntity(surfaceKey(AdSurface.APP_OPEN), state.appOpenShownAtMs, 0),
    )

    /** The enum's own name, so renaming a surface is a compile error here rather than a silent key drift. */
    private fun surfaceKey(surface: AdSurface): String = surface.name
}
