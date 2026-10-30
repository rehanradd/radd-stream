package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The player's responsiveness settings and the in-player keep are pinned as text, for the same
 * reason `AdultListingGuardTest` is: `PlaybackService` needs an Android `Context` to build an
 * `ExoPlayer`, so nothing on this aarch64 host can construct one and read back what it was
 * configured with — and the Robolectric suites that could are excluded
 * (`app/build.gradle.kts`, robolectric/robolectric#9166). A one-line revert here is invisible to
 * every other gate this repository has.
 *
 * So this scan asserts the things `App/docs/PLAYER_AND_CACHE_DIRECTIVE.md` asks for are set at the
 * one place each is settable, that the keep tapped in the player reaches the coordinator's
 * handoff rather than stopping at the enqueue, and that no shortener call path came back.
 *
 * Every refusal is paired with a positive control, because a scan whose file moved or whose marker
 * string was renamed would otherwise be green by accident.
 */
class InstantStartGuardTest {

    private val srcRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            val candidate = File(dir, "App/app/src/main/kotlin/com/raddstream/app")
            if (candidate.isDirectory) return@lazy candidate
            dir = dir.parentFile
        }
        error("no app source tree above ${File("").absolutePath}")
    }

    private fun source(vararg path: String): String {
        val file = File(srcRoot, path.joinToString("/"))
        assertTrue("${file.path} is gone — this guard has been looking at nothing", file.isFile)
        return file.readText()
    }

    private fun playerService(): String {
        val service = source("player", "PlaybackService.kt")
        val built = service.substringAfter("ExoPlayer.Builder(this)").substringBefore(".build()")
        assertTrue("positive control: the player is still built in PlaybackService", built.isNotBlank())
        return service
    }

    @Test
    fun `start waits for half a second of media, not the default 2500 ms`() {
        val service = playerService()
        assertTrue(
            "the load control must be handed to the builder, or the tuning does nothing",
            service.contains(".setLoadControl(instantStartLoadControl())"),
        )
        val helper = service.substringAfter("private fun instantStartLoadControl()")
            .substringBefore("companion object")
        assertTrue("positive control: the load-control body was parsed", helper.isNotBlank())
        assertTrue(
            "both start thresholds are arguments of setBufferDurationsMs, by name",
            helper.contains("/* bufferForPlaybackMs = */ START_BUFFER_MS") &&
                helper.contains("/* bufferForPlaybackAfterRebufferMs = */ REBUFFER_START_BUFFER_MS"),
        )
        assertTrue("500 ms is the ask", service.contains("private const val START_BUFFER_MS = 500"))
        assertTrue(
            "and the after-rebuffer window is wider, or one slow second re-starts the stall loop",
            service.contains("private const val REBUFFER_START_BUFFER_MS = 1_000"),
        )
        // min/max are Media3's own shipped defaults on purpose; changing those is another decision.
        assertTrue(service.contains("DEFAULT_MIN_BUFFER_MS = 50_000"))
        assertTrue(service.contains("DEFAULT_MAX_BUFFER_MS = 100_000"))
    }

    @Test
    fun `seeking lands on the nearest sync frame and redirects still cross protocols`() {
        val service = playerService()
        assertTrue(
            "a scrub must not decode forward from the previous I-frame",
            service.contains("exo.setSeekParameters(SeekParameters.CLOSEST_SYNC)"),
        )
        // The resolver's 302s are the normal path on this backend; losing this loses every stream.
        assertTrue(service.contains(".setAllowCrossProtocolRedirects(true)"))
    }

    /**
     * `SeekParameters` is `androidx.media3.exoplayer.SeekParameters`, not a `common` type — and the
     * wrong import was written here once, which `:app:compileDebugKotlin` caught but no text scan
     * would have. The package is pinned because the directive's own wording invites the mistake.
     */
    @Test
    fun `the seek parameter type is imported from the package that actually ships it`() {
        val service = source("player", "PlaybackService.kt")
        assertTrue(service.contains("import androidx.media3.exoplayer.SeekParameters"))
        assertFalse(
            "there is no androidx.media3.common.SeekParameters at Media3 1.3.1",
            service.contains("import androidx.media3.common.SeekParameters"),
        )
    }

    @Test
    fun `the keep tapped in the player is handed to the coordinator, not just enqueued`() {
        val engine = source("data", "cache", "OfflineCacheEngine.kt")
        val adopt = engine.substringAfter("override suspend fun adopt(request: AdoptRequest)")
            .substringBefore("override suspend fun cancelKeep")
        assertTrue("positive control: adopt() was parsed", adopt.isNotBlank())
        assertTrue(
            "keepNow is the promote-and-adopt call the directive names",
            adopt.contains("coordinator.keepNow(sourceKey)"),
        )
        assertTrue(
            "a null handoff is a refusal — it may never be reported to the UI as a keep",
            adopt.contains("handoff == null ->") && adopt.contains("KeepResult.Failed"),
        )
        // The player screen's chip still goes through the ViewModel, so the boundary stays one
        // call deep and no Composable reaches into the data layer.
        val viewModel = source("viewmodel", "PlayerViewModel.kt")
        assertTrue(viewModel.contains("engine.adopt(request)"))
        val screen = source("ui", "screens", "PlayerScreen.kt")
        assertTrue("the chip still calls the ViewModel", screen.contains("vm.keepCurrent()"))
        assertFalse("no screen may call the cache layer directly", screen.contains("cacheCoordinator"))
    }

    @Test
    fun `a promoted keep is never described by an expiry it does not have`() {
        val engine = source("data", "cache", "OfflineCacheEngine.kt")
        assertTrue(
            "a user keep has no window, so the engine reports null instead of a number",
            engine.contains("ttlSeconds = null"),
        )
        val viewModel = source("viewmodel", "PlayerViewModel.kt")
        assertFalse(
            "TTL unknown was the old honest lie for permanent: a null window means the file is " +
                "never auto-deleted, and the chip must say nothing rather than guess",
            viewModel.contains("TTL unknown"),
        )
        assertTrue(
            "the window is printed only when one exists",
            viewModel.contains("result.ttlSeconds?.let"),
        )
    }

    /**
     * The universal player's other half: the rule itself lives in `UniversalSourceTest`, and this
     * asserts the rule is actually *applied* to the `MediaItem`. A correct `manifestMimeType` that
     * nothing feeds to the builder changes nothing at playback time, and no JVM test here can build
     * a `MediaItem` to notice.
     */
    @Test
    fun `the media item carries the manifest declaration the wire named`() {
        val factory = source("player", "PlaybackMediaItemFactory.kt")
        assertTrue(
            "positive control: the factory still builds the item from the rendition",
            factory.contains("MediaItem.Builder()"),
        )
        assertTrue(
            "the declaration must reach the builder — setMimeType is what Media3 1.3.1 reads",
            factory.contains("builder.setMimeType(manifestMime)"),
        )
        assertTrue(
            "and it comes from the rule, not from a literal",
            factory.contains("manifestMimeType(rendition.playback)"),
        )
        // Progressive stays undeclared on purpose; asserting the branch keeps that honest.
        assertTrue(
            "MP4/MKV must keep the sniffed path",
            factory.substringAfter("fun manifestMimeType(playback: PlaybackInfo)")
                .contains("else -> null"),
        )
        // One data-source factory carries the cross-protocol redirect setting to HLS and DASH too,
        // because the same factory is what the media-source factory is built from.
        val service = source("player", "PlaybackService.kt")
        assertTrue(
            "HLS/DASH must read through the redirect-permitting factory, not a fresh one",
            service.contains("DefaultMediaSourceFactory(dataFactory)"),
        )
        assertTrue(service.contains("val dataFactory = DefaultDataSource.Factory(this, httpFactory)"))
    }

    @Test
    fun `no shortener call path survives in this app`() {
        val callPattern = Regex("(?i)shorten|shrinkme|droplink|adfly")
        val files = srcRoot.walkTopDown().filter { it.isFile && it.extension == "kt" }.toList()
        assertTrue("positive control: Kotlin sources were found", files.size > 100)
        val offenders = files.filter { callPattern.containsMatchIn(codeOf(it.readText())) }.map { it.name }
        assertTrue("every byte path must be ours and direct — found: $offenders", offenders.isEmpty())

        // The stripper is what makes that claim mean anything: a comment may name the retired call,
        // code may not. Prove the stripper removes the comment and keeps the call.
        val sample = listOf(
            "// wrapWithShortener is retired, see PARITY_BACKEND_BLOCKED.md",
            "/* It used to call shorten_download_url() */",
            "val url = streamRedirectUrl(baseUrl, handle)",
        ).joinToString("\n")
        assertFalse("a commented-out call must not read as code", codeOf(sample).contains("Shortener"))
        assertFalse("and a doc mention must not either", codeOf(sample).contains("shorten_download_url"))
        assertTrue(
            "positive control: real code survives the strip",
            codeOf(sample).contains("streamRedirectUrl(baseUrl, handle)"),
        )
    }

    /**
     * Comments stripped, string literals kept — the rule `ProviderPageScreenTest` uses, so a KDoc
     * that merely *names* the retired call cannot make this green while real code calls it.
     */
    private fun codeOf(text: String): String {
        val out = StringBuilder()
        var i = 0
        var inLine = false
        var blockDepth = 0
        var inString = false
        while (i < text.length) {
            val c = text[i]
            val next = text.getOrNull(i + 1)
            when {
                inLine -> if (c == '\n') { inLine = false; out.append(c) }
                blockDepth > 0 -> when {
                    c == '/' && next == '*' -> { blockDepth++; i++ }
                    c == '*' && next == '/' -> { blockDepth--; i++ }
                }
                inString -> {
                    out.append(c)
                    if (c == '\\') { out.append(next ?: ' '); i++ } else if (c == '"') inString = false
                }
                c == '/' && next == '/' -> inLine = true
                c == '/' && next == '*' -> { blockDepth = 1; i++ }
                c == '"' -> { inString = true; out.append(c) }
                else -> out.append(c)
            }
            i++
        }
        return out.toString()
    }
}
