package com.raddstream.app.network

import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.network.models.V1CatalogMapper
import com.raddstream.app.network.models.PrintGoldenVectors
import com.raddstream.app.viewmodel.ReleaseLayoutBuilder
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The client half of the provenance rule. The public edge stopped *serving* site names, hoster
 * names and upstream addresses; this app must not model or render them either, or one future
 * `Text(...)` re-opens the leak.
 *
 *  1. no wire or view class may declare a provenance field — a field that does not exist
 *     cannot be rendered by accident;
 *  2. every String any mapped object can produce says nothing about where the file came from.
 */
class ProvenanceWireTest {

    /** Site slugs and bridge names harvested from `domain_registry.json` and the old rules body. */
    private val needles: List<String> = listOf(
        "vegamovies", "hdhub4u", "multimovies", "9xmovies", "world4ufree", "katmoviehd",
        "desicinemas", "7starhd", "10xflix", "toonworld4all", "hindilinks4u",
        "pixeldrain", "vegadrive", "gamerxyt", "direct-cloud", "greenmotors",
        "hubcloud", "filesforever", "cineverse", "gofile",
    ) + PrintGoldenVectors.all.mapNotNull { it.sourceSite.takeIf(String::isNotBlank) }
        .map { it.lowercase() }

    private val forbiddenFieldNames = setOf(
        "sourcesite", "source_name", "sourcename", "service", "originurl", "origin_url",
        "intermediateurl", "intermediate_url", "pageurl", "page_url", "sourceurl", "source_url",
        "finalurl", "final_url", "url", "loc", "slug", "sourceslug", "resource_id", "resourceid",
            )

    private val modelClasses = listOf(
        Post::class.java, PostDetail::class.java, ReleaseDetail::class.java,
        SourceDetail::class.java,
    )

    @Test
    fun `no model class declares a provenance field`() {
        val offenders = modelClasses.flatMap { klass ->
            klass.declaredFields
                .filter { field ->
                    field.name.lowercase() in forbiddenFieldNames ||
                        field.annotations.filterIsInstance<com.google.gson.annotations.SerializedName>()
                            .any { it.value.lowercase() in forbiddenFieldNames }
                }
                .map { "${klass.simpleName}.${it.name}" }
        }
        assertTrue("provenance fields present in the wire models: $offenders", offenders.isEmpty())
    }

    @Test
    fun `a mapped print and its links carry no provenance string`() {
        val print = printWith("s7", "Fast direct", "direct")
        val links = print.links.map { it.copy(playUrl = OUR_ORIGIN + it.streamId) }

        val rendered = buildList {
            add(print.qualityLabel)
            add(print.detailLine)
            add(print.bestOptionLabel.orEmpty())
            add(print.rawTitle.orEmpty())
            links.forEach { add(it.displayLabel()) }
        }
        val leaked = rendered.filter { line -> needles.any { line.lowercase().contains(it) } }
        assertTrue("provenance reached a rendered label: $leaked", leaked.isEmpty())
    }

    @Test
    fun `the only playable address the app can hold is our own redirector`() {
        val print = printWith("s7", "Fast direct", "direct")
        print.links.forEach { link ->
            assertTrue(
                "link address is not ours: ${link.playUrl}",
                link.playUrl == null || link.playUrl.startsWith(OUR_ORIGIN),
            )
        }
        val downloadOnly = printWith("s8", "Standard", "download")
        assertTrue(downloadOnly.links.first().playability != Playability.STREAM)
    }

    @Test
    fun `the v2 link view keeps its handle and drops everything else`() {
        val link = V1CatalogMapper.toLink(source("s7", "Fast direct", "direct"))
        val rendered = link.javaClass.declaredFields
            .onEach { it.isAccessible = true }
            .mapNotNull { field -> runCatching { field.get(link) as? String }.getOrNull() }
        val leaked = rendered.filter { value -> needles.any { value.lowercase().contains(it) } }
        assertTrue("mapper output contains provenance: $leaked", rendered.isNotEmpty() && leaked.isEmpty())
    }

    private fun printWith(streamId: String, label: String, kind: String) =
        ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                ReleaseDetail(
                    id = 3,
                    postId = 12,
                    releaseTitle = "Example Film 1080p WEB-DL",
                    quality = "1080p WEB-DL",
                    codec = "x265",
                    size = "2.4GB",
                    languages = "Hindi",
                    sources = listOf(source(streamId, label, kind)),
                ),
            ),
        ).workPrints.first()

    private fun source(streamId: String, label: String, kind: String) = SourceDetail(
        streamId = streamId,
        linkId = 7,
        releaseId = 3,
        playUrl = OUR_ORIGIN + streamId,
        label = label,
        kind = kind,
        status = "active",
    )

    private companion object {
        const val OUR_ORIGIN = "http://127.0.0.1:8080/api/v1/stream?id="
    }
}
