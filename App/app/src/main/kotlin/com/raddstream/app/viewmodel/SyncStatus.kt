package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.FavoritePost

/**
 * Gap A5 — the sync/status line: one honest sentence about how fresh what
 * is on screen is, and whether anything is still waiting to sync.
 *
 * All three functions are pure so the wording is pinned by a test; the
 * ViewModels only supply the facts (a timestamp, a row list, a sign-in
 * flag) and the current time.
 */

/** "just now" / "1 min ago" / "N min ago" / "1 hour ago" / "N hours ago" / "N days ago". */
internal fun relativeTimeAgo(epochMs: Long, nowMs: Long): String {
    val diffMs = (nowMs - epochMs).coerceAtLeast(0L)
    val minutes = diffMs / 60_000L
    return when {
        minutes < 1L -> "just now"
        minutes < 60L -> if (minutes == 1L) "1 min ago" else "$minutes min ago"
        minutes < 60L * 24L -> {
            val hours = minutes / 60L
            if (hours == 1L) "1 hour ago" else "$hours hours ago"
        }
        else -> {
            val days = minutes / (60L * 24L)
            if (days == 1L) "1 day ago" else "$days days ago"
        }
    }
}

/**
 * The Home status line. Null when Home has never loaded (nothing to date).
 * Offline says so plainly and names the age of the saved rows on screen,
 * so a stale cache never passes as fresh.
 */
internal fun homeSyncLine(lastUpdatedAtMs: Long?, isOffline: Boolean, nowMs: Long): String? {
    val atMs = lastUpdatedAtMs ?: return null
    val age = relativeTimeAgo(atMs, nowMs)
    return if (isOffline) "Offline — showing saved Home from $age" else "Updated $age"
}

/**
 * The My List status line. Null for an empty list (nothing to sync, nothing
 * to date). Rows without a work handle can never be named to the server, so
 * they are local-only by design and never counted as "waiting": only a
 * syncable row with no `syncedAt` is waiting. A signed-out install keeps
 * everything on this device, and says so instead of promising a sync.
 */
internal fun myListSyncLine(favorites: List<FavoritePost>, signedIn: Boolean, nowMs: Long): String? {
    if (favorites.isEmpty()) return null
    if (!signedIn) return "Saved on this device"
    val syncable = favorites.filter { it.syncable }
    if (syncable.isEmpty()) return "Saved on this device"
    val pending = syncable.count { it.syncedAt == null }
    if (pending > 0) {
        return if (pending == 1) "1 title not synced yet" else "$pending titles not synced yet"
    }
    val lastSynced = syncable.mapNotNull { it.syncedAt }.maxOrNull() ?: return "Saved on this device"
    return "Synced ${relativeTimeAgo(lastSynced, nowMs)}"
}
