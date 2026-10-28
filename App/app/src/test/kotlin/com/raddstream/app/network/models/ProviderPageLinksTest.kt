package com.raddstream.app.network.models

import com.raddstream.app.player.PROVIDER_PAGE_ONLY
import com.raddstream.app.player.QualityLadder
import com.raddstream.app.player.QualityOption
import com.raddstream.app.viewmodel.RankedLink
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A link the server calls a PAGE and not a file, in both of the words the two edges use for it.
 *
 * This suite exists because `external` used to be filed as a downloadable file: `keep` then handed
 * DownloadManager an HTML page and the Downloads row claimed a film had been kept. Every case below
 * is one half of that mistake — the word, the verdict it must produce, the offer it must NOT
 * produce, and the rank the server's own golden rows put on it.
 *
 * Nothing here reads a hostname or a URL shape. The two spellings are `viewer.py::link_view()`'s
 * `kind = "external"` and `catalog_v2.classify_link()`'s `kind = "embed", playability = "webview"`,
 * and both are server-sent words, which is the whole surface this app is allowed to key on.
 */
class ProviderPageLinksTest {

    private val redirector = "http://92.4.95.252/api/v1/stream?id=lh-1"

    // ── 1. the words ──────────────────────────────────────────────────────────

    @Test
    fun `both served page words name a page`() {
        assertTrue(ProviderPageLinks.isPageWord("external"))
        assertTrue(ProviderPageLinks.isPageWord("embed"))
        assertTrue(ProviderPageLinks.isPageWord(" EXTERNAL "))
    }

    @Test
    fun `a file word and an absent word are not a page`() {
        listOf("direct", "resolve", "download", "hls", "manifest", "", null).forEach { word ->
            assertFalse("'$word' is not a page word", ProviderPageLinks.isPageWord(word))
        }
    }

    @Test
    fun `a served webview verdict names a page without a page kind`() {
        assertTrue(
            ProviderPageLinks.isPageVerdict(kind = null, playability = Playability.WEBVIEW),
        )
    }

    @Test
    fun `a page needs our handle, our redirector and a link that is not gone`() {
        val page = ProviderPageLinks.isPageVerdict("external", Playability.WEBVIEW)
        assertTrue(page)
        assertFalse(
            ProviderPageLinks.isProviderPage("external", Playability.WEBVIEW, hasHandle = false,
                hasOurRedirector = true, isDead = false),
        )
        assertFalse(
            ProviderPageLinks.isProviderPage("external", Playability.WEBVIEW, hasHandle = true,
                hasOurRedirector = false, isDead = false),
        )
        assertFalse(
            ProviderPageLinks.isProviderPage("external", Playability.WEBVIEW, hasHandle = true,
                hasOurRedirector = true, isDead = true),
        )
    }

    /**
     * `ladder_link` — the rung projection the quality switch is built from — serves `kind` and no
     * `playability` at all. The rung verdict therefore has to answer from the kind word alone, or
     * every page rung of the ladder is silently a file.
     */
    @Test
    fun `the page verdict survives the ladder projection which carries only kind`() {
        assertTrue(
            ProviderPageLinks.isProviderPage("embed", playability = null, hasHandle = true,
                hasOurRedirector = true, isDead = false),
        )
    }

    // ── 2. the verdict, from each edge's spelling ─────────────────────────────

    private fun v1PageLink(status: String = "active") = SourceDetail(
        streamId = "lh-1",
        playUrl = redirector,
        kind = "external",
        playable = false,
        status = status,
    )

    private fun projectedPageLink() = SourceDetail(
        streamId = "lh-1",
        playUrl = redirector,
        kind = "embed",
        playability = "webview",
        protocol = "html",
        tier = 2,
        status = "active",
    )

    @Test
    fun `the v1 external spelling is a page and never a stream`() {
        val a = LinkClassification.classify(v1PageLink())
        assertEquals(Playability.WEBVIEW, a.playability)
        assertEquals(LinkKind.EMBED, a.kind)
        assertEquals(PlayProtocol.HTML, a.protocol)
        assertFalse("a page is not directly playable", a.canStream)
        assertFalse(a.playableHere)
        assertTrue(a.isProviderPage)
    }

    @Test
    fun `the projected embed spelling is the same page`() {
        val a = LinkClassification.classify(projectedPageLink())
        assertEquals(Playability.WEBVIEW, a.playability)
        assertEquals(LinkKind.EMBED, a.kind)
        assertEquals(PlayProtocol.HTML, a.protocol)
        assertTrue(a.isProviderPage)
    }

    /**
     * The word-level verdict on the served link object says "page" whatever the scrape status
     * says; it is the ROW-level rule (`ProviderPageLinks.isProviderPage`, which every offer reads)
     * that refuses to offer a dead one. Covered by the dead `RankedLink` case below.
     */
    @Test
    fun `a dead page keeps its page kind and its dead state`() {
        val a = LinkClassification.classify(v1PageLink(status = "dead"))
        assertEquals(LinkState.DEAD, a.state)
        assertEquals(LinkKind.EMBED, a.kind)
        assertEquals(Playability.WEBVIEW, a.playability)
        assertTrue("a dead page is not directly playable either", !a.canStream)
    }

    @Test
    fun `page words win over a downloadable claim`() {
        // `link_view()` sends `downloadable` for every link it has a handle for; a page word must
        // not be read back as "a file we can keep".
        val a = LinkClassification.classify(
            v1PageLink().copy(downloadable = true),
        )
        assertEquals(Playability.WEBVIEW, a.playability)
    }

    @Test
    fun `a download link is still a file and still not a page`() {
        val a = LinkClassification.classify(
            SourceDetail(streamId = "lh-2", playUrl = redirector, kind = "download",
                playable = false, downloadable = true, status = "active"),
        )
        assertEquals(Playability.DOWNLOAD, a.playability)
        assertEquals(LinkKind.DOWNLOAD_ONLY, a.kind)
        assertFalse(a.isProviderPage)
    }

    // ── 3. rank parity with the server's own vectors ──────────────────────────

    /**
     * `catalog_v2.classify_link()` puts an embed page at 280 and `GoldenVectors.LinkGoldenVectors`
     * pins that number for every page in the sampled set. Honouring `webview` is therefore parity,
     * not a regression: the client's derived score has to land on the server's.
     */
    @Test
    fun `every golden webview row ranks where the server ranked it`() {
        val pages = LinkGoldenVectors.all.filter { it.field("playability") == "webview" }
        assertTrue("the golden set must contain page rows for this test to mean anything",
            pages.isNotEmpty())
        pages.forEachIndexed { index, row ->
            val source = SourceDetail(
                streamId = "lh-$index",
                playUrl = redirector,
                kind = row.field("kind"),
                playability = row.field("playability"),
                protocol = row.field("protocol"),
                tier = row.intField("tier"),
                isTemporary = row.isTemporary,
                status = row.status,
            )
            val assessment = LinkClassification.classify(source)
            assertEquals("rank of golden page #$index", row.intField("rank"),
                LinkClassification.rankScore(assessment))
            assertEquals(LinkKind.EMBED, assessment.kind)
            assertTrue(assessment.isProviderPage)
            // With a published number, the client takes it and never re-derives one.
            assertEquals(row.intField("rank"),
                LinkClassification.rankOf(source.copy(rankScore = row.intField("rank"))))
        }
    }

    // ── 4. the detail row: what it offers and what it says ────────────────────

    private fun rankedLink(kind: String?, playability: Playability, dead: Boolean = false) =
        RankedLink(
            streamId = "lh-1",
            linkId = 7,
            health = if (dead) LinkState.DEAD else LinkState.ACTIVE,
            ephemeral = false,
            resumable = false,
            playUrl = redirector,
            label = "Standard",
            kind = kind,
            playability = playability,
            score = 280,
        )

    @Test
    fun `a page row is never keepable and never says download only`() {
        val page = rankedLink("external", Playability.WEBVIEW)
        assertTrue(page.isProviderPage)
        assertFalse("keeping a page would store HTML and call it a film", page.keepable)
        assertFalse(page.playableHere)
        val label = page.displayLabel()
        assertTrue("'$label'", label.contains(PROVIDER_PAGE_ONLY))
    }

    /**
     * Two questions, two answers, and neither one is health: a dead page is not something we can
     * open right now (`isProviderPage` false, so no "Open" offer), and it is still not a file
     * (`keepable` false, because a page never becomes keepable by going down). A dead FILE stays
     * keepable exactly as before — that is a link the ledger can heal, not a wrong category.
     */
    @Test
    fun `a dead page row is neither openable nor keepable`() {
        val dead = rankedLink("external", Playability.WEBVIEW, dead = true)
        assertFalse(dead.isProviderPage)
        assertTrue("the served word still calls it a page", dead.isPageLink)
        assertFalse("a dead page is still not a file to keep", dead.keepable)
        assertFalse(dead.playableHere)
    }

    @Test
    fun `a file row is still keepable`() {
        assertTrue(rankedLink("download", Playability.DOWNLOAD).keepable)
        assertTrue(rankedLink("resolve", Playability.STREAM).playableHere)
    }

    // ── 5. the ladder rung ────────────────────────────────────────────────────

    private fun rung(kind: String, playable: Boolean, status: String = "active") = QualityLadder.from(
        OptionGroup(
            tiers = listOf(
                LadderTier(
                    band = "720p",
                    quality = "720p",
                    label = "HD",
                    playable = playable,
                    copies = 1,
                    link = LadderLink(
                        streamId = "lh-1",
                        playUrl = redirector,
                        kind = kind,
                        playable = playable,
                        status = status,
                    ),
                ),
            ),
        ),
    ).options.single()

    @Test
    fun `a page rung is neither playable nor download-only`() {
        val option = rung("external", playable = false)
        assertFalse(option.playsHere)
        assertTrue(option.isProviderPage)
        assertFalse("a page is not a file to keep", option.downloadOnly)
        assertEquals(PROVIDER_PAGE_ONLY, option.detailLine)
    }

    /**
     * A rung whose only copy is a DOWN page: `playsHere` is already false from the health check,
     * and the page verdict must still come from the word, or the card offers to keep an HTML page
     * that happens to be offline.
     */
    @Test
    fun `a dead page rung is still not offered as a file`() {
        val option = rung("external", playable = false, status = "dead")
        assertFalse(option.playsHere)
        assertTrue(option.isProviderPage)
        assertFalse(option.downloadOnly)
    }

    @Test
    fun `a file rung keeps its download-only wording`() {
        val option = rung("download", playable = false)
        assertFalse(option.isProviderPage)
        assertTrue(option.downloadOnly)
        assertEquals(QualityOption.KEEPS_ONLY, option.detailLine)
    }
}
