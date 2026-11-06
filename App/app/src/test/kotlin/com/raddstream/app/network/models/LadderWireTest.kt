package com.raddstream.app.network.models

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Session 71: the ladder wire carries the honest source facts — the winning
 * print's audio languages on the tier, the winner copy's probe-measured MIME
 * on the link. Both are optional on the wire: an older server sends neither,
 * and the app must read that as "unknown", never as a guessed value.
 */
class LadderWireTest {

    private val gson = Gson()

    @Test
    fun `a ladder tier carries its print's audio languages and its copy's mime`() {
        val tier = gson.fromJson(
            """
            {"band":"1080p","quality":"1080p","label":"Full HD","mode":"play","playable":true,
             "copies":2,"audio_languages":["Hindi","English"],
             "link":{"stream_id":"lh-1","play_url":"http://127.0.0.1:8080/api/v1/stream?id=lh-1",
             "kind":"direct","playable":true,"status":"active",
             "mime_type":"application/vnd.apple.mpegurl","file_size_bytes":1400000000,
             "is_resumable":true,"label":"Fast direct"},
             "backup_handles":[]}
            """.trimIndent(),
            LadderTier::class.java,
        )
        assertEquals(listOf("Hindi", "English"), tier.audioLanguages)
        assertEquals("application/vnd.apple.mpegurl", tier.link?.mimeType)
    }

    @Test
    fun `missing audio languages and mime read as absent, never as a guess`() {
        val tier = gson.fromJson(
            """{"band":"720p","link":{"stream_id":"lh-2"}}""",
            LadderTier::class.java,
        )
        assertEquals(emptyList<String>(), tier.audioLanguages)
        assertNull(tier.link?.mimeType)
    }
}
