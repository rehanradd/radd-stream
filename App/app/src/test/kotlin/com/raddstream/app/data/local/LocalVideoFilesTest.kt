package com.raddstream.app.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalVideoFilesTest {

    @Test
    fun relativePathSelectionFiltersMoviesAndDownloads() {
        val (selection, args) = localVideoSelection(useRelativePath = true)
        assertTrue(selection.contains("relative_path LIKE ?"))
        assertFalse(selection.contains("_data LIKE ?"))
        assertEquals("Movies%", args[0])
        assertEquals("Download%", args[1])
        assertEquals("video/mp4", args[2])
        assertEquals("video/x-matroska", args[3])
        assertEquals("video/webm", args[4])
        assertEquals("%.mp4", args[5])
        assertEquals("%.mkv", args[6])
        assertEquals("%.webm", args[7])
    }

    @Test
    fun dataPathSelectionFiltersMoviesAndDownloads() {
        val (selection, args) = localVideoSelection(useRelativePath = false)
        assertTrue(selection.contains("_data LIKE ?"))
        assertFalse(selection.contains("relative_path LIKE ?"))
        assertEquals("%/Movies/%", args[0])
        assertEquals("%/Download/%", args[1])
    }

    @Test
    fun titleStripsExtensionAndReadsUnderscoresAsSpaces() {
        assertEquals("my movie", localVideoTitle("my_movie.mp4"))
        assertEquals("clip", localVideoTitle("clip"))
        assertEquals("my.movie", localVideoTitle("my.movie.mp4"))
    }

    @Test
    fun titleFallsBackWhenTheNameCarriesNothing() {
        assertEquals(LOCAL_VIDEO_UNTITLED, localVideoTitle(null))
        assertEquals(LOCAL_VIDEO_UNTITLED, localVideoTitle("   "))
        assertEquals(LOCAL_VIDEO_UNTITLED, localVideoTitle("12345.mp4"))
        assertEquals(LOCAL_VIDEO_UNTITLED, localVideoTitle(".mp4"))
    }

    @Test
    fun folderNamesMoviesAndDownloadsFromEitherPathShape() {
        assertEquals("Movies", localVideoFolder("Movies/RaddStream/", null))
        assertEquals("Downloads", localVideoFolder("Download/", null))
        assertEquals("Movies", localVideoFolder(null, "/storage/emulated/0/Movies/clip.mp4"))
        assertEquals("Downloads", localVideoFolder(null, "/storage/emulated/0/Download/clip.mp4"))
        assertEquals("On this phone", localVideoFolder("Pictures/", null))
        assertEquals("On this phone", localVideoFolder(null, null))
    }

    @Test
    fun mimeOrExtensionDecidesTheContainer() {
        assertTrue(isLocalVideoFile("video/mp4", "clip.mp4"))
        assertTrue(isLocalVideoFile("video/x-matroska", "clip.mkv"))
        assertTrue(isLocalVideoFile(null, "clip.mkv"))
        assertTrue(isLocalVideoFile("video/mp2t", "clip.mp4"))
        assertFalse(isLocalVideoFile("text/html", "clip.jpg"))
        assertFalse(isLocalVideoFile(null, null))
        assertFalse(isLocalVideoFile(null, "clip"))
    }

    @Test
    fun rowMapsToAFileWithTitleAndFolder() {
        val file = localVideoFromRow(
            uri = "content://media/external/video/media/42",
            displayName = "my_movie.mp4",
            durationMs = 125_000L,
            sizeBytes = 245_000_000L,
            relativePath = "Movies/RaddStream/",
            dataPath = null,
            mimeType = "video/mp4",
            dateAddedMs = 1_700_000_000_000L,
        )
        assertEquals("content://media/external/video/media/42", file?.uri)
        assertEquals("my movie", file?.title)
        assertEquals("Movies", file?.folder)
        assertEquals(125_000L, file?.durationMs)
        assertEquals(1_700_000_000_000L, file?.dateAddedMs)
    }

    @Test
    fun nonVideoRowMapsToNull() {
        assertNull(
            localVideoFromRow(
                uri = "content://media/external/video/media/43",
                displayName = "photo.jpg",
                durationMs = 0L,
                sizeBytes = 100L,
                relativePath = "Movies/",
                dataPath = null,
                mimeType = "image/jpeg",
                dateAddedMs = 0L,
            ),
        )
    }
}
