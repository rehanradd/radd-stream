package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The line this product will not cross, pinned to the one file that could cross it.
 *
 * A visible WebView is easy to turn into a resolver: add `shouldInterceptRequest`, read the
 * response headers, look for `.m3u8` or `video/mp4`, keep the page off-screen, and hand the bare
 * file to ExoPlayer. That is what a provider's player gate exists to prevent, and root `AGENTS.md`
 * ("Not a DRM circumventer") and `DISCLAIMER.md` §2 rule it out. A compile-time check cannot express
 * "this feature must never be built", so the check is on the file: the screen may show a page, and
 * the four calls that would turn showing into taking are not allowed to appear in it.
 *
 * The positive controls matter as much as the refusals — a scan of an empty or renamed file is
 * green by accident.
 */
class ProviderPageScreenTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val screensDir = "App/app/src/main/kotlin/com/raddstream/app/ui/screens"

    private val screen: File by lazy {
        File(repoRoot, "$screensDir/EmbedWebViewScreen.kt").also {
            assertTrue("the provider-page screen is missing at ${it.path}", it.isFile)
        }
    }

    private val viewModel: File by lazy {
        File(
            repoRoot,
            "App/app/src/main/kotlin/com/raddstream/app/viewmodel/EmbedWebViewModel.kt",
        ).also { assertTrue("its resolver is missing at ${it.path}", it.isFile) }
    }

    /**
     * The file with its comments gone, code untouched. The screen's own doc comment NAMES the four
     * calls it refuses — a reader of this file has to be told where the line is — so a scan over
     * prose would fail on documentation instead of on code. `codeOf` removes only comments: every
     * positive control below still has to be findable in what is left, which is what stops a
     * comment-stripper from turning the guard into a no-op.
     */
    private fun codeOf(text: String): String {
        val out = StringBuilder(text.length)
        var blockDepth = 0
        var i = 0
        while (i < text.length) {
            val c = text[i]
            when {
                blockDepth > 0 -> when {
                    text.startsWith(OPEN, i) -> {
                        blockDepth++
                        i += 2
                    }
                    text.startsWith(CLOSE, i) -> {
                        blockDepth--
                        i += 2
                    }
                    else -> {
                        if (c == '\n') out.append(c)
                        i++
                    }
                }

                text.startsWith(OPEN, i) -> {
                    blockDepth++
                    i += 2
                }

                text.startsWith(LINE, i) -> {
                    while (i < text.length && text[i] != '\n') i++
                }

                c == '"' -> {
                    val end = if (text.startsWith(TRIPLE, i)) {
                        var j = i + TRIPLE.length
                        while (j < text.length && !text.startsWith(TRIPLE, j)) j++
                        minOf(j + TRIPLE.length, text.length)
                    } else {
                        var j = i + 1
                        while (j < text.length && text[j] != '"' && text[j] != '\n') {
                            if (text[j] == '\\') j++
                            j++
                        }
                        minOf(j + 1, text.length)
                    }
                    out.append(text, i, end)
                    i = end
                }

                else -> {
                    out.append(c)
                    i++
                }
            }
        }
        return out.toString()
    }

    private companion object {
        // Assembled, not written: this file has to satisfy CommentBalanceTest too.
        val OPEN = "/" + "*"
        val CLOSE = "*" + "/"
        val LINE = "/" + "/"
        val TRIPLE = "\"\"\""
    }

    @Test
    fun `the file under guard is really a web page view`() {
        val code = codeOf(screen.readText())
        assertTrue("positive control: the screen builds no WebView", code.contains("WebView(ctx)"))
        assertTrue("positive control: nothing loads a URL", code.contains("loadUrl("))
        assertTrue(
            "positive control: the screen has no navigation policy at all",
            code.contains("shouldOverrideUrlLoading"),
        )
    }

    @Test
    fun `the screen never inspects what the page asks for`() {
        val code = codeOf(screen.readText())
        // Traffic sniffing, in either of its two API shapes.
        assertFalse(code.contains("shouldInterceptRequest"))
        assertFalse(code.contains("WebResourceResponse"))
        // The other way out of a page: a media URL offered to a downloader instead of a player.
        assertFalse(code.contains("setDownloadListener"))
        assertFalse(code.contains("DownloadListener"))
        // The provider's own name for its page, which is a hoster name.
        assertFalse(code.contains("onReceivedTitle"))
    }

    @Test
    fun `nothing the page itself reports is ever handed on`() {
        val code = codeOf(screen.readText())
        // The browser hand-off takes the address this app built, never whatever the WebView
        // navigated to: the page's own report is not ours to trust.
        assertFalse(code.contains("webView.url"))
        assertFalse(code.contains("webView?.url"))
        assertFalse(code.contains("view.url"))
        // And nothing here reaches into a player: showing the page is the end of this path.
        assertFalse(code.contains("ExoPlayer"))
        assertFalse(code.contains("MediaItem"))
    }

    @Test
    fun `the only address the screen can load is our own redirector`() {
        val code = codeOf(viewModel.readText())
        assertTrue(
            "the ViewModel must rebuild our redirector rather than receive an address",
            code.contains("streamRedirectUrl("),
        )
        assertTrue("and it must obey the same-origin rule", code.contains("isSameOriginAsServer("))
        // It resolves an address; it does not hold a browser to load one into.
        assertFalse(code.contains("android.webkit"))
        assertFalse(code.contains("loadUrl("))
    }
}
