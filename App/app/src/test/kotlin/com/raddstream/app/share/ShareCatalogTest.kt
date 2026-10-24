package com.raddstream.app.share

import com.raddstream.app.data.cache.CacheFileEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure JVM coverage of [ShareCatalog] — the code that decides which committed cache files become
 * shareable, under what opaque token, and with what advertised content type. No sockets, no
 * Android: the whole "what is shareable and does it leak provenance" contract is nailed down here,
 * which is exactly the part that must be provably safe before [LanShareServer] ever binds a port.
 */
class ShareCatalogTest {

    private fun file(
        fileId: String,
        path: String,
        size: Long = 5_000L,
        complete: Boolean = true,
        temporary: Boolean = false,
    ) = CacheFileEntity(
        fileId = fileId,
        sourceKey = "src-$fileId",
        taskId = 1L,
        path = path,
        sizeBytes = size,
        isTemporary = temporary,
        isComplete = complete,
        createdElapsedRealtime = 0L,
        lastAccessElapsedRealtime = 0L,
    )

    @Test
    fun `committed complete file becomes a share target keyed by its own opaque id`() {
        val catalog = ShareCatalog.fromCommittedFiles(
            listOf(file("a1b2c3d4e5f60718", "/data/user/0/app/files/media_cache/a1b2c3d4e5f60718")),
        )
        val target = catalog["a1b2c3d4e5f60718"]
        assertTrue(target != null)
        assertEquals(5_000L, target!!.entry.sizeBytes)
        assertEquals("a1b2c3d4e5f60718", target.entry.fileName)
        assertTrue(target.entry.enabled)
        assertEquals("/data/user/0/app/files/media_cache/a1b2c3d4e5f60718", target.file.absolutePath)
    }

    @Test
    fun `temp partial and incomplete files are never shareable`() {
        val catalog = ShareCatalog.fromCommittedFiles(
            listOf(
                file("t1", "/x/t1.part", temporary = true),
                file("t2", "/x/t2", complete = false),
                file("t3", "/x/t3", size = 0L),
                file("ok", "/x/ok"),
            ),
        )
        assertEquals(setOf("ok"), catalog.keys)
    }

    @Test
    fun `a file id that is not one clean segment is refused`() {
        val catalog = ShareCatalog.fromCommittedFiles(
            listOf(
                file("bad/../name", "/x/a"),
                file("enc%2fcode", "/x/b"),
                file("has space", "/x/c"),
                file("clean123", "/x/d"),
            ),
        )
        assertEquals(setOf("clean123"), catalog.keys)
    }

    @Test
    fun `provenance never surfaces — a leaky path yields only an opaque id and a container type`() {
        // A hostile-looking path that embeds a source site / hoster / upstream URL in the directory
        // name must not leak: the surfaced fileName is our own fileId and the content type comes from
        // the container extension, never from the path's provenance-shaped text.
        val leakyPath = "/data/x/https___vegamovies_cdn_hoster99_show_s01e01"
        val catalog = ShareCatalog.fromCommittedFiles(listOf(file("opaque1234", leakyPath)))
        val entry = catalog.getValue("opaque1234").entry
        assertEquals("opaque1234", entry.fileName)
        val blob = "${entry.fileName}|${entry.contentType}".lowercase()
        assertFalse(blob.contains("vegamovies"))
        assertFalse(blob.contains("hoster"))
        assertFalse(blob.contains("http"))
        // Extension-less cache files advertise a generic byte stream, not a guessed source.
        assertEquals("application/octet-stream", entry.contentType)
    }

    @Test
    fun `content type is chosen from the container never the source`() {
        assertEquals("video/mp4", ShareCatalog.contentTypeFor("clip.mp4"))
        assertEquals("video/x-matroska", ShareCatalog.contentTypeFor("clip.MKV"))
        assertEquals("text/vtt", ShareCatalog.contentTypeFor("subs.vtt"))
        assertEquals("application/octet-stream", ShareCatalog.contentTypeFor("a1b2c3d4"))
    }

    @Test
    fun `address selection prefers a private ipv4 and ignores the rest`() {
        val picked = ShareCatalog.firstSiteLocalIpv4(
            listOf("127.0.0.1", "169.254.10.5", "fe80::1", "8.8.8.8", "192.168.1.42", "10.0.0.7"),
        )
        assertEquals("192.168.1.42", picked)
        // 172.16–31 is private; 172.32 is not.
        assertEquals("172.20.0.1", ShareCatalog.firstSiteLocalIpv4(listOf("172.20.0.1", "172.32.0.1")))
        assertNull(ShareCatalog.firstSiteLocalIpv4(listOf("127.0.0.1", "8.8.8.8")))
        assertFalse(ShareCatalog.isCleanToken(""))
    }
}
