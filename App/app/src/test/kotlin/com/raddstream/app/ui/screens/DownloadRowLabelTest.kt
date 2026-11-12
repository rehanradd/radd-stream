package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.raddstream.app.data.downloads.DeviceDownload
import com.raddstream.app.data.downloads.DeviceDownloadState
import com.raddstream.app.ui.theme.RaddStreamTheme
import com.raddstream.app.viewmodel.KeepState
import com.raddstream.app.viewmodel.KeptItem
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Robo run 9: a failed-download card in Downloads spoke "Rank #1" twice —
 * the ATF flagged "Multiple items have the same description". The keep's
 * engine task had a blank title and a "Rank #1" print label (displayLabel's
 * fallback when a rendition carries no quality words), so toKeptItem fell
 * back to the print label for the title AND kept it as the print label, and
 * the row painted both. The row now paints the label only when it says
 * something the title does not, and the spoken label carries the title so
 * two cards sharing one rank label never speak identically (the run-6
 * printSpokenLabel pattern). The painted text stays the short label.
 *
 * Edge noted, not covered: two keeps with the SAME title and the same label
 * would still speak identically — that needs two untitled rank-1 keeps of
 * one title, a data edge the observed crawl did not have.
 *
 * Runs on the JVM under Robolectric because this project has no emulator
 * image. Requires an x86_64 runner (robolectric/robolectric#9166).
 */
@RunWith(RobolectricTestRunner::class)
class DownloadRowLabelTest {

    @get:Rule
    val compose = createComposeRule()

    private fun failedKeep(id: String, title: String, printLabel: String) = KeptItem(
        id = id,
        title = title,
        printLabel = printLabel,
        bytesDownloaded = 0L,
        bytesTotal = 0L,
        state = KeepState.FAILED,
        expiresAtMillis = null,
    )

    private fun failedFile(id: String, title: String, printLabel: String) = DeviceDownload(
        id = id,
        title = title,
        printLabel = printLabel,
        state = DeviceDownloadState.FAILED,
        bytesDownloaded = 0L,
        bytesTotal = 0L,
        localUri = null,
        mimeType = "video/mp4",
        fileName = "file-$id.mp4",
    )

    @Test
    fun rankLabelIdenticalToTitleIsPaintedOnce() {
        compose.setContent {
            RaddStreamTheme {
                KeptItemRow(
                    item = failedKeep("7", "Rank #1", "Rank #1"),
                    onPlay = {},
                    onCancel = {},
                    onRetry = {},
                )
            }
        }
        // The title speaks "Rank #1" once; the print label is not painted a
        // second time on the same card.
        compose.onAllNodes(hasText("Rank #1")).assertCountEquals(1)
        // The row still says what happened and offers the retry.
        compose.onNodeWithText("Download failed — retry to resume").assertIsDisplayed()
        compose.onNodeWithText("Retry").assertIsDisplayed()
    }

    @Test
    fun deviceRowRankLabelIdenticalToTitleIsPaintedOnce() {
        compose.setContent {
            RaddStreamTheme {
                DeviceDownloadRow(
                    item = failedFile("d7", "Rank #1", "Rank #1"),
                    onPlay = {},
                    onPause = {},
                    onResume = {},
                    onRemove = {},
                )
            }
        }
        compose.onAllNodes(hasText("Rank #1")).assertCountEquals(1)
    }

    @Test
    fun twoKeepsSharingARankLabelSpeakDifferently() {
        compose.setContent {
            RaddStreamTheme {
                Column {
                    KeptItemRow(
                        item = failedKeep("7", "Fall", "Rank #1"),
                        onPlay = {},
                        onCancel = {},
                        onRetry = {},
                    )
                    KeptItemRow(
                        item = failedKeep("8", "Dune", "Rank #1"),
                        onPlay = {},
                        onCancel = {},
                        onRetry = {},
                    )
                }
            }
        }
        // Both cards still paint the short "Rank #1" label …
        compose.onAllNodes(hasText("Rank #1")).assertCountEquals(2)
        // … but each speaks it with its own title, so no two nodes share a
        // speakable description, and no node speaks the bare rank label.
        compose.onNode(hasContentDescription("Fall — Rank #1")).assertIsDisplayed()
        compose.onNode(hasContentDescription("Dune — Rank #1")).assertIsDisplayed()
        compose.onAllNodes(hasContentDescription("Rank #1")).assertCountEquals(0)
    }

    @Test
    fun realQualityLabelStillPaintedAndSpoken() {
        compose.setContent {
            RaddStreamTheme {
                KeptItemRow(
                    item = failedKeep("7", "Fall", "1080p · High bitrate"),
                    onPlay = {},
                    onCancel = {},
                    onRetry = {},
                )
            }
        }
        compose.onNodeWithText("1080p · High bitrate").assertIsDisplayed()
        compose.onNode(hasContentDescription("Fall — 1080p · High bitrate")).assertIsDisplayed()
    }
}
