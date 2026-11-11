package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.FavoritePost
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Gap A5: the sync/status line says what is true — how fresh the rows are,
 * and whether anything is still waiting to sync — and nothing when there
 * is nothing to date.
 */
class SyncStatusTest {

    @Test
    fun `relative time buckets`() {
        assertEquals("just now", relativeTimeAgo(epochMs = 1_000L, nowMs = 30_000L))
        assertEquals("1 min ago", relativeTimeAgo(epochMs = 1_000L, nowMs = 61_000L))
        assertEquals("2 min ago", relativeTimeAgo(epochMs = 1_000L, nowMs = 121_000L))
        assertEquals("1 hour ago", relativeTimeAgo(epochMs = 0L, nowMs = 3_600_000L))
        assertEquals("3 hours ago", relativeTimeAgo(epochMs = 0L, nowMs = 3 * 3_600_000L))
        assertEquals("1 day ago", relativeTimeAgo(epochMs = 0L, nowMs = 86_400_000L))
        assertEquals("2 days ago", relativeTimeAgo(epochMs = 0L, nowMs = 2 * 86_400_000L))
        assertEquals("just now", relativeTimeAgo(epochMs = 9_999L, nowMs = 1_000L))
    }

    @Test
    fun `home line is null until home has loaded`() {
        assertNull(homeSyncLine(lastUpdatedAtMs = null, isOffline = false, nowMs = 1_000L))
    }

    @Test
    fun `home line names the age, and offline says so`() {
        assertEquals("Updated 2 min ago", homeSyncLine(1_000L, isOffline = false, nowMs = 121_000L))
        assertEquals(
            "Offline — showing saved Home from 2 min ago",
            homeSyncLine(1_000L, isOffline = true, nowMs = 121_000L),
        )
    }

    private fun favorite(id: Int, workRef: String? = "work-$id", syncedAt: Long? = null) =
        FavoritePost(id = id, title = "Title $id", workRef = workRef, syncedAt = syncedAt)

    @Test
    fun `my list line is null for an empty list`() {
        assertNull(myListSyncLine(emptyList(), signedIn = true, nowMs = 1_000L))
    }

    @Test
    fun `signed out list is saved on this device`() {
        assertEquals(
            "Saved on this device",
            myListSyncLine(listOf(favorite(1)), signedIn = false, nowMs = 1_000L),
        )
    }

    @Test
    fun `rows without a handle never count as waiting`() {
        assertEquals(
            "Saved on this device",
            myListSyncLine(listOf(favorite(1, workRef = null)), signedIn = true, nowMs = 1_000L),
        )
    }

    @Test
    fun `unsynced syncable rows are named`() {
        assertEquals(
            "2 titles not synced yet",
            myListSyncLine(
                listOf(favorite(1), favorite(2), favorite(3, syncedAt = 500L)),
                signedIn = true,
                nowMs = 121_000L,
            ),
        )
        assertEquals(
            "1 title not synced yet",
            myListSyncLine(listOf(favorite(1)), signedIn = true, nowMs = 121_000L),
        )
    }

    @Test
    fun `fully synced list names the last sync`() {
        assertEquals(
            "Synced 2 min ago",
            myListSyncLine(
                listOf(favorite(1, syncedAt = 1_000L), favorite(2, syncedAt = 60_000L)),
                signedIn = true,
                nowMs = 181_000L,
            ),
        )
    }
}
