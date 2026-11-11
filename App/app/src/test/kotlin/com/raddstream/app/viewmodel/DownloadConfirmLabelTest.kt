package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Test

/** App-design audit (2026-11-12, issues #10/#11): one primary action, size tied to the choice. */
class DownloadConfirmLabelTest {

    @Test
    fun namesPrintAndSizeTogether() {
        assertEquals(
            "Download 480p · 730.0 MB",
            downloadConfirmLabel("480p", 730_000_000L),
        )
    }

    @Test
    fun unknownSizeSaysSo() {
        assertEquals("Download 720p", downloadConfirmLabel("720p", null))
        assertEquals("Download 720p", downloadConfirmLabel("720p", 0L))
    }

    @Test
    fun blankLabelFallsBackToVersion() {
        assertEquals("Download this version · 730.0 MB", downloadConfirmLabel("", 730_000_000L))
    }
}
