package com.raddstream.app.ui.components

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * UI-layer half of the Robo run-3 a11y fix (Session 131): two rungs at different
 * qualities used to announce identically — every tier pill said bare "Standard"
 * and every subtext said bare "Plays here" — so a screen reader could not tell
 * the 720p rung from the 1080p one. Each rung now carries its quality in its
 * spoken name ("Standard tier, HD - X264", "HD - X264: Plays here"). Runs on
 * the JVM under Robolectric because this project has no emulator image.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64
 * build (robolectric/robolectric#9166) and it fails while the runner boots, so
 * the exclusion for ARM hosts lives in app/build.gradle.kts rather than here.
 */
@RunWith(RobolectricTestRunner::class)
class QualityRungCardTest {

    @get:Rule
    val compose = createComposeRule()

    private fun option(band: String, title: String, audioLanguages: List<String> = emptyList()) = QualityOption(
        band = band,
        title = title,
        streamId = "h-$band",
        playUrl = "http://127.0.0.1:8080/api/v1/stream?id=h-$band",
        sizeBytes = null,
        backupHandles = emptyList(),
        playsHere = true,
        resumable = false,
        copies = 1,
        isProviderPage = false,
        audioLanguages = audioLanguages,
    )

    private fun showCard() {
        val scope = LadderForScope(
            options = listOf(option("720p", "HD - X264"), option("1080p", "Full HD · X264")),
            autoBand = "1080p",
            downloadOnlyBands = emptyList(),
        )
        compose.setContent {
            RaddStreamTheme {
                QualityRungCard(
                    ladder = scope,
                    selectedBand = null,
                    onPlayRung = {},
                    onKeepRung = {},
                    tierLabel = { "Standard" },
                )
            }
        }
    }

    @Test
    fun tierPillsSpeakTheirRung() {
        showCard()
        compose.onAllNodes(hasContentDescription("Standard tier, HD - X264"))
            .assertCountEquals(1)
        compose.onAllNodes(hasContentDescription("Standard tier, Full HD · X264"))
            .assertCountEquals(1)
    }

    @Test
    fun detailLinesSpeakTheirRung() {
        showCard()
        compose.onAllNodes(hasContentDescription("HD - X264: Plays here"))
            .assertCountEquals(1)
        compose.onAllNodes(hasContentDescription("Full HD · X264: Plays here"))
            .assertCountEquals(1)
    }

    @Test
    fun factsLinesSpeakTheirRung() {
        // Robo run 7: all four rungs said the same "Hindi + English audio"
        // — the facts line carries its rung now, so a screen reader can
        // tell the 4K row from the 480p one. The painted text stays the
        // short facts line, the same pattern as the detail lines above.
        val scope = LadderForScope(
            options = listOf(
                option("2160p", "4K Ultra HD", audioLanguages = listOf("Hindi", "English")),
                option("1080p", "Full HD", audioLanguages = listOf("Hindi", "English")),
                option("720p", "HD", audioLanguages = listOf("Hindi", "English")),
                option("480p", "480p", audioLanguages = listOf("Hindi", "English")),
            ),
            autoBand = "2160p",
            downloadOnlyBands = emptyList(),
        )
        compose.setContent {
            RaddStreamTheme {
                QualityRungCard(
                    ladder = scope,
                    selectedBand = null,
                    onPlayRung = {},
                    onKeepRung = {},
                    tierLabel = { "Standard" },
                )
            }
        }
        // The facts line carries its rung AND its data estimate (audit #11):
        // the spoken line is "<title>: <audio> · <estimate>".
        compose.onAllNodes(hasContentDescription("4K Ultra HD: Hindi + English audio · ≈ 7–11 GB/hour"))
            .assertCountEquals(1)
        compose.onAllNodes(hasContentDescription("Full HD: Hindi + English audio · ≈ 3 GB/hour"))
            .assertCountEquals(1)
        compose.onAllNodes(hasContentDescription("HD: Hindi + English audio · ≈ 1.5 GB/hour"))
            .assertCountEquals(1)
        compose.onAllNodes(hasContentDescription("480p: Hindi + English audio · ≈ 700 MB/hour"))
            .assertCountEquals(1)
    }

    @Test
    fun autoPillSurvivesTheGateNullingTheServerPointer() {
        // D-1: Salaar, free user — the gate keeps 720p and nulls autoBand, but
        // Auto is still the default and Play presses 720p, so the card must
        // still mark the 720p row Auto. Before the fix the pill rendered
        // nowhere, because nothing matched the null pointer.
        val gated = LadderForScope(
            options = listOf(option("720p", "HD - X264"), option("480p", "480p")),
            autoBand = null,
            downloadOnlyBands = emptyList(),
        )
        compose.setContent {
            RaddStreamTheme {
                QualityRungCard(
                    ladder = gated,
                    selectedBand = LadderForScope.AUTO,
                    onPlayRung = {},
                    onKeepRung = {},
                    tierLabel = { "Standard" },
                )
            }
        }
        compose.onAllNodesWithText("Auto").assertCountEquals(1)
    }

    @Test
    fun autoPillStaysOnTheServerPointerWhenNothingIsGated() {
        // Ungated: the pill sits on the server's auto rung, as before — the
        // effective band is the server pointer when the gate kept everything.
        val scope = LadderForScope(
            options = listOf(option("720p", "HD - X264"), option("1080p", "Full HD · X264")),
            autoBand = "1080p",
            downloadOnlyBands = emptyList(),
        )
        compose.setContent {
            RaddStreamTheme {
                QualityRungCard(
                    ladder = scope,
                    selectedBand = LadderForScope.AUTO,
                    onPlayRung = {},
                    onKeepRung = {},
                    tierLabel = { "Standard" },
                )
            }
        }
        compose.onAllNodesWithText("Auto").assertCountEquals(1)
    }
}
