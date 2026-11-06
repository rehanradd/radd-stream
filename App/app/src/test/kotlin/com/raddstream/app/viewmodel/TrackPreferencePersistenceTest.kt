package com.raddstream.app.viewmodel

import androidx.media3.common.Format
import androidx.media3.common.TrackGroup
import com.raddstream.app.player.TrackUiOption
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * JVM tests for the player step 1 of the redesign (2026-11-06): a subtitle/audio
 * pick made in the player writes the language back to Settings, so the next
 * episode (and the next visit) auto-applies the new pick instead of the old one.
 *
 * The rule being pinned: only a real language persists. Turning subtitles off is
 * viewing-scoped — it must not delete the stored language, or the next episode
 * would start silent for a viewer who wants Hindi. A track with no language tag
 * has nothing to persist either. The next-episode auto-apply itself is covered
 * by AudioTrackMatcherTest / SubtitleTrackPolicyTest (the matcher, given the new
 * language, picks the new track).
 */
class TrackPreferencePersistenceTest {

    private fun option(language: String?) = TrackUiOption(
        id = "g0-t0",
        group = TrackGroup(Format.Builder().setLanguage(language).build()),
        trackIndex = 0,
        label = "Hindi",
        language = language,
        supported = true,
        selected = false,
    )

    @Test
    fun `a picked track persists its language`() {
        assertEquals("hi", persistedLanguageFor(option("hi")))
        assertEquals("ur", persistedLanguageFor(option("ur")))
    }

    @Test
    fun `stray spaces around a language are trimmed`() {
        assertEquals("hi", persistedLanguageFor(option("  hi  ")))
    }

    @Test
    fun `turning subtitles off persists nothing`() {
        assertNull(persistedLanguageFor(null))
    }

    @Test
    fun `a track with no language tag persists nothing`() {
        assertNull(persistedLanguageFor(option(null)))
        assertNull(persistedLanguageFor(option("")))
        assertNull(persistedLanguageFor(option("   ")))
    }
}
