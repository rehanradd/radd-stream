package com.raddstream.app.data.cache

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.di.CacheScope
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * The one live copy of the user's offline retention window, for the components that have no UI of
 * their own to re-read it from: the TTL sweep ([RoomCacheSweepStore.ttlHours]), the engine's expiry
 * maths ([OfflineCacheEngine]) and the Downloads list's expiry column.
 *
 * WHY THIS CLASS EXISTS AT ALL: [TtlHours] is an enum, so before this the DI graph had to hand out
 * one constant — `provideTtlHours() = TtlHours.SIX` — and the Settings screen's 3 h / 6 h control
 * only ever wrote a DataStore key that nothing read. A setting nobody consumes is a decoration; this
 * is the wire between the preference and the delete.
 *
 * WHY THIS SHAPE: it is the [com.raddstream.app.share.LanShareRunner] pattern, deliberately copied
 * rather than reinvented — a `@Singleton` the Application starts once, which collects a
 * [ServerSettingsRepository] flow on the app-lifetime [CacheScope] and mirrors the latest value into
 * a plain field. DataStore reads are suspend and must never happen inside a sweep or a
 * player-visible mapping, so the collectors keep a `@Volatile` snapshot warm and every consumer does
 * one non-blocking field read. The preference is the only channel: the UI never touches this, and
 * this never touches the UI.
 *
 * WHAT IS **NOT** PROTECTED: nothing here survives a process death on its own, and between process
 * start and the first emission this reports [DEFAULT], so the pre-seeding window is 3 hours rather
 * than whatever was last saved. That is safe in the only direction that matters — a sweep firing
 * that early deletes bytes belonging to ephemeral previews, which are the files the engine is
 * allowed to re-fetch, and it can never lengthen a window or delete a USER_KEEP (rule 1 of
 * [TtlPolicy] protects those regardless of what this returns).
 *
 * RETROACTIVE SHORTENING, stated plainly: [TtlPolicy.evaluate] ages a file against the window it is
 * handed, not against the window that was live when the file was written — and the per-file
 * `CacheFileEntity.ttlHours` column is never populated, so it is a record of nothing. The honest
 * reading is therefore that this setting is a standing statement about how long the app may hold
 * unwatched preview bytes, not a per-keep promise, and lowering it does make old previews eligible
 * sooner. The alternative — freezing the choice per file — would mean changing tested policy math to
 * read a column no writer fills in; that is a bigger lie, not a smaller one.
 */
@Singleton
class KeepTtlHolder @Inject constructor(
    private val settings: ServerSettingsRepository,
    @CacheScope private val scope: CoroutineScope,
) {

    private val started = AtomicBoolean(false)

    @Volatile
    private var current: TtlHours = DEFAULT

    /** The window to apply right now. Never suspends, never touches disk. */
    fun ttlHours(): TtlHours = current

    /**
     * Idempotent: begins observing the persisted choice. Safe to call from the Application before
     * the first read; until the first emission [ttlHours] answers [DEFAULT], which is the same 3
     * hours a fresh install has always had.
     */
    fun start() {
        if (!started.compareAndSet(false, true)) return
        scope.launch {
            settings.keepTtlHours.collect { hours -> current = TtlHours.fromHours(hours) }
        }
    }

    companion object {
        /** The no-choice-yet window: 3 hours, matching the repository's own default. */
        val DEFAULT: TtlHours = TtlHours.THREE
    }
}
