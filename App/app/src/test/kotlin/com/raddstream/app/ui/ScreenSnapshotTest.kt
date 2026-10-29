package com.raddstream.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.ui.components.AudioBadge
import com.raddstream.app.ui.components.HdrBadge
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.components.PrintQualityBadge
import com.raddstream.app.ui.components.PrintSourceBadge
import com.raddstream.app.ui.components.SubtitleBadge
import com.raddstream.app.ui.screens.MaintenanceScreen
import com.raddstream.app.ui.screens.MethodSection
import com.raddstream.app.ui.screens.PaymentSection
import com.raddstream.app.ui.screens.PricingSection
import com.raddstream.app.ui.theme.RaddInk950
import com.raddstream.app.ui.theme.RaddStreamTheme
import com.raddstream.app.viewmodel.ReleaseLayoutBuilder
import com.raddstream.app.viewmodel.VipMethod
import com.raddstream.app.viewmodel.VipPlan
import com.raddstream.app.viewmodel.VipUiState
import java.io.File
import java.io.FileOutputStream
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

/**
 * Off-screen pixel snapshots of the surfaces that are hardest to eyeball without a phone.
 *
 * Every capture renders the REAL composable the app ships — never a hand-written stand-in —
 * so a snapshot that looks right is evidence about the app rather than about this file. Where
 * a screen is driven by server state (payment handles, the maintenance escape) both honest
 * states are captured.
 *
 * PNGs land in `App/app/build/reports/screenshots/`, inside the `ci-reports` artifact ci.yml
 * already uploads. Robolectric's native graphics runtime has no Linux/aarch64 build
 * (robolectric/robolectric#9166) and it dies while the runner boots, so this class is excluded
 * on ARM hosts in `app/build.gradle.kts`: it compiles here, it renders on x86_64 CI.
 *
 * **The bitmap comes from a software draw of the view hosting the composition, because
 * `captureToImage()` cannot ever produce one here.** That call path (androidx ui-test 1.6.8
 * `WindowCapture.captureRegionToImage`) asks
 * for a fresh frame by `view.handler.post { … }` and then blocks the calling thread in
 * `waitUntil(mainClock, 2000ms)` until the redraw lands. Under Robolectric the test thread *is*
 * the main looper's thread, so the posted frame can never run while that wait holds it, and every
 * capture died at the same 2000 ms `ComposeTimeoutException` — robolectric/robolectric#8071 calls
 * this out as unsupported rather than as a timing bug, so no lengthening of the timeout and no
 * idle-wait would ever fix it. `view.draw(Canvas(bitmap))` runs the same display list through a
 * software canvas with no frame scheduling at all, which is also what makes these snapshots
 * independent of wall-clock: the only waiting left is `waitForIdle()`, i.e. composition and
 * layout having finished, not a duration.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ScreenSnapshotTest {

    @get:Rule
    val compose = createComposeRule()

    private val outputDir = File("build/reports/screenshots").absoluteFile

    /** The view hosting the last [shot] composition — the thing a snapshot is taken of. */
    private var renderSurface: View? = null

    private fun capture(name: String) {
        compose.waitForIdle()
        val view = renderSurface ?: error("capture($name) ran before any shot() composed a view")
        assertTrue(
            "$name laid out a ${view.width}x${view.height} surface — nothing to snapshot",
            view.width > 0 && view.height > 0,
        )
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
        view.draw(Canvas(bitmap))
        outputDir.mkdirs()
        val file = File(outputDir, "$name.png")
        FileOutputStream(file).use { out -> bitmap.compress(Bitmap.CompressFormat.PNG, 100, out) }
        assertTrue("${file.name} was written but holds no bytes", file.length() > 0)
        // A blank canvas compresses to real bytes, so "the file is non-empty" proves only that
        // the write worked. Two different paints inside the frame is what proves the tree drew.
        assertTrue("$name is a flat bitmap — nothing painted itself", bitmap.paintedSomething())
    }

    /**
     * Sampled, not exhaustive: a step of 4 keeps this a couple of thousand reads on a
     * window-sized frame, and any two distinct paints answer the question just as well as a
     * full scan would.
     */
    private fun Bitmap.paintedSomething(): Boolean {
        val first = getPixel(0, 0)
        var y = 0
        while (y < height) {
            var x = 0
            while (x < width) {
                if (getPixel(x, y) != first) return true
                x += 4
            }
            y += 4
        }
        return false
    }

    private fun shot(content: @Composable () -> Unit) {
        renderSurface = null
        compose.setContent {
            val view = LocalView.current
            SideEffect { renderSurface = view }
            RaddStreamTheme(darkTheme = true) {
                Surface(modifier = Modifier.fillMaxSize(), color = RaddInk950) {
                    content()
                }
            }
        }
    }

    // ── Maintenance ──────────────────────────────────────────────────────────

    @Test
    fun maintenanceLockedNotice() {
        shot {
            Box(Modifier.fillMaxSize()) { MaintenanceScreen() }
        }
        assertTrue(
            "the notice without an escape still offered a server switch",
            compose.onAllNodes(hasText("Use a different server", substring = true))
                .fetchSemanticsNodes().isEmpty(),
        )
        capture("01_maintenance_locked")
    }

    @Test
    fun maintenanceWithServerChangeButton() {
        shot {
            Box(Modifier.fillMaxSize()) { MaintenanceScreen(onChangeServer = {}) }
        }
        assertTrue(
            "the escape hatch a wrongly-flagged deployment depends on is gone",
            compose.onAllNodes(hasText("Use a different server", substring = true))
                .fetchSemanticsNodes().isNotEmpty(),
        )
        capture("02_maintenance_server_switch")
    }

    // ── Poster cards ─────────────────────────────────────────────────────────

    @Test
    fun posterCards() {
        val cleaned = Post(
            id = 101,
            title = "PagalMovies · Jawan (2023) Hindi 1080p WebRip",
            cleanTitle = "Jawan",
            year = 2023,
            contentType = "movie",
            imdbRating = "7.9",
            language = "Hindi + Tamil + Telugu",
        )
        val noArtwork = Post(
            id = 102,
            title = "Oppenheimer",
            cleanTitle = "Oppenheimer",
            year = 2023,
            contentType = "movie",
            posterUrl = null,
            imdbRating = "8.9",
        )
        val longTitle = Post(
            id = 103,
            title = "Baahubali",
            cleanTitle = "Baahubali: The Beginning — The Final Chapter (Extended Director's Cut)",
            year = 2015,
            contentType = "series",
            posterUrl = null,
        )

        shot {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("Trending Releases", style = MaterialTheme.typography.titleLarge)
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    // Three tiles, three shapes the app can actually build. A "#N" overlay used to
                    // be here too; no screen ever passed a rank, because the list route sends no
                    // ordering field to rank from, so the renderer was deleted rather than
                    // snapshotted. A ranked rail needs a server-supplied rank first.
                    PosterCard(post = cleaned, modifier = Modifier.width(180.dp))
                    PosterCard(post = noArtwork, modifier = Modifier.width(180.dp))
                }
                PosterCard(post = longTitle, modifier = Modifier.width(372.dp))
            }
        }
        capture("03_poster_cards")
    }

    // ── Quality badges ───────────────────────────────────────────────────────

    @OptIn(ExperimentalLayoutApi::class)
    @Test
    fun qualityBadgeStrip() {
        // The detail screen's own path: wire release rows in, ranked prints out. Building a
        // PrintDescriptor by hand would snapshot a print the server could never send.
        val prints = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                ReleaseDetail(
                    id = 1,
                    releaseTitle = "Inception (2010) 2160p UHD BluRay x265 HDR10+ Dolby Vision " +
                        "[Hindi English] AC3 Subtitles",
                    size = "15.2GB",
                ),
                ReleaseDetail(
                    id = 2,
                    releaseTitle = "Inception (2010) 1080p WEB-DL AAC [English]",
                    quality = "1080p",
                    size = "4.1GB",
                ),
            ),
        ).workPrints
        assertTrue("the label grammar produced no print, so the badge strip would be blank", prints.isNotEmpty())

        shot {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                prints.forEach { print ->
                    Text(print.rawTitle.orEmpty(), style = MaterialTheme.typography.titleSmall)
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        PrintQualityBadge(print = print)
                        HdrBadge(print = print)
                        PrintSourceBadge(print = print)
                        AudioBadge(print = print)
                        SubtitleBadge(print = print)
                    }
                }
            }
        }
        capture("04_quality_badges")
    }

    // ── VIP upgrade ──────────────────────────────────────────────────────────

    private fun vipState(
        till: String = "",
        mobile: String = "",
        easyPaisa: String = "",
        raast: String = "",
    ) = VipUiState(
        isLoading = false,
        currency = "PKR",
        monthlyPkr = 200,
        yearlyPkr = 1500,
        jazzCashTillId = till,
        jazzCashMobileAccount = mobile,
        easyPaisaMobile = easyPaisa,
        raastInstantId = raast,
        selectedPlan = VipPlan.MONTHLY,
        selectedMethod = VipMethod.JAZZCASH,
    )

    @Test
    fun vipPaymentInstructions() {
        val state = vipState(
            till = "7019882",
            mobile = "0300-1234567",
            easyPaisa = "0345-7654321",
            raast = "raddstream@hbl",
        )
        shot {
            Column(
                Modifier.fillMaxWidth().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                PricingSection(state = state) {}
                PaymentSection(state = state) { _, _ -> }
                MethodSection(state = state) {}
            }
        }
        assertTrue(
            "a published JazzCash till never reached the screen",
            compose.onAllNodes(hasText("7019882", substring = false)).fetchSemanticsNodes().isNotEmpty(),
        )
        capture("05_vip_payment_instructions")
    }

    @Test
    fun vipPaymentNotConfigured() {
        val state = vipState()
        shot {
            Column(
                Modifier.fillMaxWidth().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                PricingSection(state = state) {}
                PaymentSection(state = state) { _, _ -> }
            }
        }
        capture("06_vip_payment_unconfigured")
    }
}
