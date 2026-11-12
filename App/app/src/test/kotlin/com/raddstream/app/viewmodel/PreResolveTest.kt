package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption
import java.io.IOException
import java.net.SocketTimeoutException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/**
 * Gap A2: the pre-resolve warms exactly the link Play would press, and a
 * cached bundle is reused only for its own print inside a short window.
 */
class PreResolveTest {

    private fun movieLayout(): ReleaseLayout {
        val low = ReleaseDetail(id = 11, quality = "480p")
        val high = ReleaseDetail(id = 22, quality = "1080p")
        return ReleaseLayoutBuilder.build("movie", listOf(low, high))
    }

    @Test
    fun `best print is the highest ranked print`() {
        val best = bestPrintOf(movieLayout())

        assertEquals(22, best?.releaseId)
    }

    @Test
    fun `no layout means no best print`() {
        assertNull(bestPrintOf(null))
    }

    @Test
    fun `fresh cache for the same print is reused`() {
        assertTrue(isPreresolveFresh(cachedReleaseId = 22, cachedAtMs = 1_000L, releaseId = 22, nowMs = 60_000L))
    }

    @Test
    fun `cache for another print is never reused`() {
        assertFalse(isPreresolveFresh(cachedReleaseId = 11, cachedAtMs = 1_000L, releaseId = 22, nowMs = 2_000L))
    }

    @Test
    fun `stale cache is never reused`() {
        assertFalse(
            isPreresolveFresh(
                cachedReleaseId = 22,
                cachedAtMs = 1_000L,
                releaseId = 22,
                nowMs = 1_000L + PRERESOLVE_FRESH_MS + 1L,
            ),
        )
    }

    @Test
    fun `no cached time means nothing cached`() {
        assertFalse(isPreresolveFresh(cachedReleaseId = 22, cachedAtMs = null, releaseId = 22, nowMs = 2_000L))
    }

    // ── Gap A2 follow-up: the scope warm ─────────────────────────────────────

    private fun rung(band: String, handle: String, playsHere: Boolean) = QualityOption(
        band = band,
        title = band,
        streamId = handle,
        playUrl = "https://raddstream.duckdns.org/api/v1/stream?id=$handle",
        sizeBytes = null,
        backupHandles = emptyList(),
        playsHere = playsHere,
        resumable = true,
        copies = 1,
        isProviderPage = false,
    )

    @Test
    fun `scope warm takes the auto rung handle`() {
        val ladder = LadderForScope(
            options = listOf(rung("720p", "h720", true), rung("480p", "h480", true)),
            autoBand = "720p",
            downloadOnlyBands = emptyList(),
        )

        assertEquals("h720", scopeWarmHandle(ladder))
    }

    @Test
    fun `scope warm skips a download-only auto rung`() {
        val ladder = LadderForScope(
            options = listOf(rung("1080p", "h1080", false)),
            autoBand = "1080p",
            downloadOnlyBands = listOf("1080p"),
        )

        assertNull(scopeWarmHandle(ladder))
    }

    @Test
    fun `scope warm is null for an empty ladder`() {
        assertNull(scopeWarmHandle(LadderForScope.EMPTY))
    }

    // ── Gap A2 follow-up: the fallback's runner-ups ──────────────────────────

    private fun streamSource(handle: String) = SourceDetail(
        streamId = handle,
        playUrl = "https://raddstream.duckdns.org/api/v1/stream?id=$handle",
        playability = "stream",
        status = "active",
        kind = "direct",
    )

    private fun onePrintWithCopies(vararg handles: String): RankedPrint {
        val release = ReleaseDetail(
            id = 22,
            quality = "720p",
            sources = handles.map { streamSource(it) },
        )
        val layout = ReleaseLayoutBuilder.build("movie", listOf(release))
        return bestPrintOf(layout)!!
    }

    private fun pageLink(handle: String) = RankedLink(
        streamId = handle,
        linkId = null,
        health = LinkState.ACTIVE,
        ephemeral = false,
        resumable = false,
        playUrl = "https://raddstream.duckdns.org/api/v1/stream?id=$handle",
        label = "Page",
        kind = "external",
        playability = Playability.WEBVIEW,
        score = 0,
    )

    private fun deadLink(handle: String) = RankedLink(
        streamId = handle,
        linkId = null,
        health = LinkState.DEAD,
        ephemeral = false,
        resumable = false,
        playUrl = "https://raddstream.duckdns.org/api/v1/stream?id=$handle",
        label = "Standard",
        kind = "direct",
        playability = Playability.STREAM,
        score = 0,
    )

    @Test
    fun `sibling backups are the print's other playable copies`() {
        val print = onePrintWithCopies("h1", "h2", "h3")
        val chosen = print.links.first { it.streamId == "h1" }

        assertEquals(listOf("h2", "h3"), siblingBackupHandles(print, chosen))
    }

    @Test
    fun `sibling backups never include a page or a dead copy`() {
        val print = onePrintWithCopies("h1", "h2")
            .copy(links = onePrintWithCopies("h1", "h2").links + listOf(pageLink("hp"), deadLink("hd")))
        val chosen = print.links.first { it.streamId == "h1" }

        assertEquals(listOf("h2"), siblingBackupHandles(print, chosen))
    }

    @Test
    fun `sibling backups dedupe and cap at five`() {
        val print = onePrintWithCopies("h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8")
        val chosen = print.links.first { it.streamId == "h1" }

        assertEquals(listOf("h2", "h3", "h4", "h5", "h6"), siblingBackupHandles(print, chosen))
    }

    @Test
    fun `sibling backups are empty for a lone copy`() {
        val print = onePrintWithCopies("h1")
        val chosen = print.links.first()

        assertTrue(siblingBackupHandles(print, chosen).isEmpty())
    }

    // Appetize FAILED 2 (2026-11-12): the first detail load failed transiently
    // and a manual Retry always loaded fully, so the load retries itself —
    // but only for failures a retry can cure.

    private fun httpError(code: Int): HttpException =
        HttpException(Response.error<Any>(code, "x".toResponseBody("text/plain".toMediaType())))

    @Test
    fun `transient detail errors are IO failures and retryable HTTP statuses`() {
        assertTrue(isTransientDetailError(IOException("connection reset")))
        assertTrue(isTransientDetailError(SocketTimeoutException("timed out")))
        assertTrue(isTransientDetailError(httpError(429)))
        assertTrue(isTransientDetailError(httpError(500)))
        assertTrue(isTransientDetailError(httpError(503)))
    }

    @Test
    fun `deterministic detail errors never retry`() {
        assertFalse(isTransientDetailError(httpError(400)))
        assertFalse(isTransientDetailError(httpError(403)))
        assertFalse(isTransientDetailError(httpError(404)))
        assertFalse(isTransientDetailError(IllegalStateException("bad state")))
    }

    @Test
    fun `detail backoff is short then settles`() {
        assertEquals(600L, detailLoadBackoffMs(1))
        assertEquals(1_500L, detailLoadBackoffMs(2))
        assertEquals(1_500L, detailLoadBackoffMs(3))
    }

    @Test
    fun `detail load retries at most three times with one null retry`() {
        assertEquals(3, DETAIL_LOAD_MAX_ATTEMPTS)
        assertEquals(1, DETAIL_LOAD_NULL_RETRIES)
    }

    @Test
    fun `playV2 ceilings give the server room under load`() {
        assertEquals(10_000L, PRERESOLVE_TIMEOUT_MS)
        assertEquals(6_000L, PLAY_V2_TIMEOUT_MS)
        assertTrue(PLAY_V2_TIMEOUT_MS < PRERESOLVE_TIMEOUT_MS)
    }

    // ── Salaar (2026-11-12): step down from a gated print ───────────────────

    @Test
    fun `step-down picks the best allowed print after a gated one fails`() {
        val layout = movieLayout()
        val failed = bestPrintOf(layout)!!

        assertEquals(22, failed.releaseId)
        assertEquals(11, stepDownPrint(layout, failed, premiumAccess = false, freeQualityCap = "720p")?.releaseId)
    }

    @Test
    fun `step-down is null when no allowed print remains`() {
        val layout = ReleaseLayoutBuilder.build(
            "movie",
            listOf(ReleaseDetail(id = 22, quality = "1080p")),
        )
        val failed = bestPrintOf(layout)!!

        assertNull(stepDownPrint(layout, failed, premiumAccess = false, freeQualityCap = "720p"))
    }

    @Test
    fun `step-down never runs for a premium caller`() {
        val layout = movieLayout()
        val failed = bestPrintOf(layout)!!

        assertNull(stepDownPrint(layout, failed, premiumAccess = true, freeQualityCap = "720p"))
    }

    @Test
    fun `step-down under a 480p cap demotes 720p too`() {
        val layout = ReleaseLayoutBuilder.build(
            "movie",
            listOf(
                ReleaseDetail(id = 31, quality = "720p"),
                ReleaseDetail(id = 11, quality = "480p"),
            ),
        )
        val failed = bestPrintOf(layout)!!

        assertEquals(31, failed.releaseId)
        assertEquals(11, stepDownPrint(layout, failed, premiumAccess = false, freeQualityCap = "480p")?.releaseId)
    }

    // ── Salaar (2026-11-12): never start on a server-gated rung ─────────────

    private fun pageRung(band: String, handle: String) = QualityOption(
        band = band,
        title = band,
        streamId = handle,
        playUrl = "https://raddstream.duckdns.org/api/v1/stream?id=$handle",
        sizeBytes = null,
        backupHandles = emptyList(),
        playsHere = true,
        resumable = true,
        copies = 1,
        isProviderPage = true,
    )

    @Test
    fun `playStartPrint passes a free print through unchanged`() {
        val layout = movieLayout()
        val free = bestPrintOf(ReleaseLayoutBuilder.build("movie", listOf(ReleaseDetail(id = 11, quality = "480p"))))!!

        assertEquals(11, playStartPrint(layout, free, premiumAccess = false, freeQualityCap = "720p")?.releaseId)
    }

    @Test
    fun `playStartPrint steps a locked best print down to the free one`() {
        // Salaar: the best print is 1080p (gated for a free viewer) and the layout
        // also carries a 480p print — Play must start on the 480p, never mint the
        // 1080p and never show the VIP lock.
        val layout = movieLayout()
        val best = bestPrintOf(layout)!!
        assertEquals(22, best.releaseId)

        assertEquals(11, playStartPrint(layout, best, premiumAccess = false, freeQualityCap = "720p")?.releaseId)
    }

    @Test
    fun `playStartPrint returns null when the lock leaves nothing free`() {
        val layout = ReleaseLayoutBuilder.build("movie", listOf(ReleaseDetail(id = 22, quality = "1080p")))
        val best = bestPrintOf(layout)!!

        assertNull(playStartPrint(layout, best, premiumAccess = false, freeQualityCap = "720p"))
    }

    @Test
    fun `playStartPrint never steps a premium viewer down`() {
        val layout = movieLayout()
        val best = bestPrintOf(layout)!!

        assertEquals(22, playStartPrint(layout, best, premiumAccess = true, freeQualityCap = "720p")?.releaseId)
    }

    @Test
    fun `stepDownRung takes the best free rung that plays here`() {
        val ladder = LadderForScope(
            options = listOf(
                rung("2160p", "h2160", true),
                rung("1080p", "h1080", true),
                rung("720p", "h720", true),
                rung("480p", "h480", true),
            ),
            autoBand = "2160p",
            downloadOnlyBands = emptyList(),
        )

        assertEquals("720p", stepDownRung(ladder, failed = rung("2160p", "h2160", true), premiumAccess = false, freeQualityCap = "720p")?.band)
    }

    @Test
    fun `stepDownRung skips provider pages and download-only rungs`() {
        val ladder = LadderForScope(
            options = listOf(
                pageRung("720p", "h720page"),
                rung("1080p", "h1080", false),
                rung("480p", "h480", true),
            ),
            autoBand = "2160p",
            downloadOnlyBands = listOf("1080p"),
        )

        assertEquals("480p", stepDownRung(ladder, failed = rung("2160p", "h2160", true), premiumAccess = false, freeQualityCap = "720p")?.band)
    }

    @Test
    fun `stepDownRung is null when no free rung plays here`() {
        val ladder = LadderForScope(
            options = listOf(rung("2160p", "h2160", true), rung("1080p", "h1080", true)),
            autoBand = "2160p",
            downloadOnlyBands = emptyList(),
        )

        assertNull(stepDownRung(ladder, failed = rung("2160p", "h2160", true), premiumAccess = false, freeQualityCap = "720p"))
    }

    @Test
    fun `stepDownRung is null for a premium caller`() {
        val ladder = LadderForScope(
            options = listOf(rung("720p", "h720", true), rung("480p", "h480", true)),
            autoBand = "2160p",
            downloadOnlyBands = emptyList(),
        )

        assertNull(stepDownRung(ladder, failed = rung("2160p", "h2160", true), premiumAccess = true, freeQualityCap = "720p"))
    }
}
