package com.raddstream.app.network.models

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * The display-title rule is the app's thinnest provenance barrier: a catalog row's `title` is
 * whatever the source page wrote, and may carry the site's name, while `cleanTitle` is the
 * scrubbed one. [Post.displayTitle] and [PostDetail.displayTitle] are the canonical guards, but
 * several screens re-implement the same expression inline instead of calling them, so this also
 * pins the two forms to identical behaviour — drift on one surface alone is how a site name
 * reaches the screen without failing anything.
 *
 * Pure JVM: no Robolectric, no Android runtime, so it runs on this ARM host today.
 */
class DisplayTitleProvenanceTest {

    private data class Fixture(
        val raw: String,
        val clean: String?,
        val expected: String,
    )

    private val fixtures = listOf(
        Fixture("VegaMovies · Inception (2024) [1080p]", "Inception", "Inception"),
        Fixture("hdhub4u.org Download Kgf", "KGF", "KGF"),
        Fixture("BollyShares · Titular", "Titular", "Titular"),
        Fixture("Plain Title With No Cleaning", null, "Plain Title With No Cleaning"),
        Fixture("Title With Empty Cleaning", "", "Title With Empty Cleaning"),
        Fixture("Title With Whitespace Cleaning", "   ", "Title With Whitespace Cleaning"),
    )

    @Test
    fun `displayTitle prefers the cleaned title and never the raw page title`() {
        for (f in fixtures) {
            val post = Post(id = 1, title = f.raw, cleanTitle = f.clean)
            assertEquals("cleanTitle=${f.clean}", f.expected, post.displayTitle)
        }
    }

    @Test
    fun `PostDetail applies the identical rule`() {
        for (f in fixtures) {
            val detail = PostDetail(id = 1, title = f.raw, cleanTitle = f.clean)
            assertEquals("cleanTitle=${f.clean}", f.expected, detail.displayTitle)
        }
    }

    @Test
    fun `the inline copy used by screens stays identical to the canonical guard`() {
        for (f in fixtures) {
            val post = Post(id = 1, title = f.raw, cleanTitle = f.clean)
            val inline = f.clean?.takeIf { it.isNotBlank() } ?: f.raw
            assertEquals("inline drift for cleanTitle=${f.clean}", inline, post.displayTitle)
        }
    }

    @Test
    fun `a site name in the raw title never survives into displayTitle when cleaned`() {
        for (site in listOf("vegamovies", "hdhub4u", "bollyshares", "filmyzilla", "10xflix", "rogmovies")) {
            val post = Post(id = 1, title = "$site · Some Film", cleanTitle = "Some Film")
            assertFalse(
                "displayTitle leaked the source site name '$site'",
                post.displayTitle.contains(site, ignoreCase = true),
            )
        }
    }
}
