package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.CoverageType
import com.raddstream.app.network.models.PrintDescriptor
import com.raddstream.app.network.models.ReleaseLabelParsing
import com.raddstream.app.network.models.Resolution
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The paid-quality gate, tested without a player, a screen or a server: given a ladder or a
 * release layout and the ledger's answer, what may a viewer see and choose?
 */
class VipQualityGateTest {

    private fun descriptor(quality: String?): PrintDescriptor =
        ReleaseLabelParsing.describe(releaseTitle = "A Movie", quality = quality)

    private fun print(releaseId: Int, quality: String?) = RankedPrint(
        releaseId = releaseId,
        rawTitle = "$quality copy",
        descriptor = descriptor(quality),
        languages = emptyList(),
        sizeBytes = null,
        coverage = CoverageType.WHOLE_WORK,
        season = null,
        episodeFrom = null,
        episodeTo = null,
        links = emptyList(),
    )

    private fun option(band: String, title: String = band) = QualityOption(
        band = band,
        title = title,
        streamId = "h-$band",
        playUrl = "http://example.invalid/$band",
        sizeBytes = 1_000L,
        backupHandles = emptyList(),
        playsHere = true,
        resumable = true,
        copies = 1,
    )

    @Test
    fun `premium bands and resolutions are recognised, everything else passes`() {
        assertTrue(VipQualityGate.isPremiumBand("2160p"))
        assertTrue(VipQualityGate.isPremiumBand(" 1080P "))
        assertTrue(VipQualityGate.isPremiumBand("4K"))
        assertFalse(VipQualityGate.isPremiumBand("720p"))
        assertFalse(VipQualityGate.isPremiumBand("sd"))
        assertFalse(VipQualityGate.isPremiumBand(null))

        assertTrue(VipQualityGate.isPremiumResolution(Resolution.R2160))
        assertTrue(VipQualityGate.isPremiumResolution(Resolution.R1080))
        assertFalse(VipQualityGate.isPremiumResolution(Resolution.R720))
        assertFalse(VipQualityGate.isPremiumResolution(Resolution.UNKNOWN))
    }

    @Test
    fun `a free viewer gets the free rungs and a fresh auto pointer`() {
        val ladder = LadderForScope(
            options = listOf(option("2160p"), option("1080p"), option("720p")),
            autoBand = "1080p",
            downloadOnlyBands = listOf("2160p", "720p"),
        )

        val gated = VipQualityGate.gate(ladder, isVip = false)

        assertEquals(listOf("720p"), gated.options.map { it.band })
        assertNull("the auto pointer must not keep naming a locked rung", gated.autoBand)
        assertEquals(listOf("720p"), gated.downloadOnlyBands)
    }

    @Test
    fun `a vip viewer keeps the ladder object untouched`() {
        val ladder = LadderForScope(
            options = listOf(option("2160p"), option("1080p"), option("720p")),
            autoBand = "2160p",
            downloadOnlyBands = listOf("1080p"),
        )

        assertSame(ladder, VipQualityGate.gate(ladder, isVip = true))
    }

    @Test
    fun `a labelled 4K rung is caught even without a canonical band`() {
        val ladder = LadderForScope(
            options = listOf(option("unspecified", title = "4K Ultra HD · HEVC"), option("720p")),
            autoBand = "unspecified",
            downloadOnlyBands = emptyList(),
        )

        val gated = VipQualityGate.gate(ladder, isVip = false)

        assertEquals(listOf("720p"), gated.options.map { it.band })
        assertNull(gated.autoBand)
    }

    @Test
    fun `the layout loses premium prints and rebuilds its counters and chips`() {
        val layout = ReleaseLayout(
            isSeriesLike = false,
            seasons = emptyList(),
            workPrints = listOf(print(1, "2160p"), print(2, "1080p"), print(3, "720p")),
            capabilities = listOf("4K", "1080p", "Official prints"),
            officialPrintCount = 3,
            camPrintCount = 0,
            totalPrints = 3,
        )

        val gated = VipQualityGate.gate(layout, isVip = false)

        assertEquals(listOf(3), gated.workPrints.map { it.releaseId })
        assertEquals(1, gated.totalPrints)
        assertEquals(1, gated.officialPrintCount)
        assertFalse(gated.capabilities.contains("4K"))
        assertFalse(gated.capabilities.contains("1080p"))
        assertTrue(VipQualityGate.hasPremiumPrints(layout))
        assertFalse(VipQualityGate.hasPremiumPrints(gated))
    }

    @Test
    fun `a season with only premium prints disappears instead of becoming an empty row`() {
        val premium = print(10, "1080p")
        val free = print(11, "720p")
        val layout = ReleaseLayout(
            isSeriesLike = true,
            seasons = listOf(
                SeasonGroup(
                    number = 1,
                    episodes = listOf(
                        EpisodeGroup(season = 1, numberWithinSeason = 1, absoluteNumber = 1, title = null, prints = listOf(premium)),
                        EpisodeGroup(season = 1, numberWithinSeason = 2, absoluteNumber = 2, title = null, prints = listOf(free)),
                    ),
                    packedPrints = emptyList(),
                ),
                SeasonGroup(
                    number = 2,
                    episodes = listOf(
                        EpisodeGroup(season = 2, numberWithinSeason = 1, absoluteNumber = 1, title = null, prints = listOf(premium)),
                    ),
                    packedPrints = emptyList(),
                ),
            ),
            workPrints = emptyList(),
            capabilities = listOf("1080p"),
            officialPrintCount = 3,
            camPrintCount = 0,
            totalPrints = 3,
        )

        val gated = VipQualityGate.gate(layout, isVip = false)

        assertEquals(listOf(1), gated.seasons.map { it.number })
        assertEquals(listOf(2), gated.seasons.single().episodes.map { it.numberWithinSeason })
        assertEquals(1, gated.totalPrints)
    }

    /**
     * The switch decides whether membership is required at all. Off is what a deployment ships
     * with, and a viewer who has never heard of VIP must not lose a rung over a price the
     * operator never chose to charge — so the same ladder that is gated above is handed back
     * whole here, identity included.
     */
    @Test
    fun `a deployment that never turned gating on restricts nobody`() {
        assertTrue(VipQualityGate.premiumAccess(gateEnabled = false, isVip = false))
        assertTrue(VipQualityGate.premiumAccess(gateEnabled = false, isVip = true))
        assertTrue(VipQualityGate.premiumAccess(gateEnabled = true, isVip = true))
        assertFalse(
            "only the operator's switch plus a non-member locks a rung",
            VipQualityGate.premiumAccess(gateEnabled = true, isVip = false),
        )

        val ladder = LadderForScope(
            options = listOf(option("1080p"), option("720p")),
            autoBand = "1080p",
            downloadOnlyBands = emptyList(),
        )
        assertSame(ladder, VipQualityGate.gate(ladder, VipQualityGate.premiumAccess(false, false)))
        assertEquals(
            listOf("720p"),
            VipQualityGate.gate(ladder, VipQualityGate.premiumAccess(true, false)).options.map { it.band },
        )
    }
}
