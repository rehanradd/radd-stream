package com.raddstream.app.player

import com.raddstream.app.network.models.WirePlayCoverage

/**
 * The /api/v2/play coverage block as the player's own [Coverage] (plan §5 step 13).
 * This lives in `player` because `network/models` never imports `player` — the
 * direction is one-way, and the wire model stays free of the player types.
 *
 * The v1 detail never serves the episode offsets, only this call does: the
 * enumerated episodes are the chapter data step 11's ticks read, and the overlay
 * (`offset_seconds` / `chapter_title` / `ordinal`) is where THIS episode starts
 * inside a packed file. A coverage block with no enumerated episodes is a
 * single-episode file, and its ticks are honestly empty.
 */
fun WirePlayCoverage.toPlayerCoverage(): Coverage = Coverage(
    typeWire = type,
    season = seasonNumber ?: 0,
    ordinal = ordinal ?: 0,
    offsetSeconds = offsetSeconds,
    needsOffsetCalibration = needsOffsetCalibration == true,
    packWarning = packWarning,
    firstEpisode = episodeFirst ?: 0,
    lastEpisode = episodeLast ?: 0,
    episodes = enumeratedEpisodes.map {
        EpisodeCoverage(
            number = it.number ?: 0,
            offsetSeconds = it.offsetSeconds,
            chapterTitle = it.chapterTitle,
            episodeId = it.episodeId,
        )
    },
)
