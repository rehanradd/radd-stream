package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Resolution
import com.raddstream.app.player.LadderForScope
import java.util.Locale

/**
 * The paid tier's only quality promise: 4K and Full HD are part of VIP.
 *
 * Applied in two places, from the same rule: the detail screen never offers a premium source to
 * a viewer the ledger has not confirmed, and the player never stages one as a quality choice or
 * a binge look-ahead. The rewarded-ad pass is deliberately NOT consulted here — it buys
 * ad-free viewing, not a higher rung, and the VIP card says exactly that.
 *
 * Nothing is invented for a viewer who is entitled: [gate] returns the original object when the
 * answer is yes, so the happy path stays byte-for-byte what it was before this gate existed.
 */
object VipQualityGate {

    /** The sentence the detail screen shows when a tap hits a locked rung. */
    const val LOCKED_MESSAGE = "4K and 1080p sources are part of VIP. Upgrade to unlock them."

    private val PREMIUM_BANDS = setOf("2160p", "4k", "uhd", "1080p", "fullhd", "fhd")
    private val PREMIUM_LABEL_HINTS = listOf("2160", "1080", "4k", "uhd", "full hd", "fullhd", "fhd")

    fun isPremiumResolution(resolution: Resolution): Boolean =
        resolution == Resolution.R2160 || resolution == Resolution.R1080

    /** A canonical rung band (`2160p`, `1080p`) or the shorthand the switch may carry. */
    fun isPremiumBand(band: String?): Boolean {
        val key = band?.trim()?.lowercase(Locale.ROOT)?.replace(" ", "").orEmpty()
        return key.isNotEmpty() && key in PREMIUM_BANDS
    }

    /** The fallback when a rung has no canonical band: the server's own words for the picture. */
    fun isPremiumLabel(label: String?): Boolean {
        val key = label?.trim()?.lowercase(Locale.ROOT) ?: return false
        return key.isNotEmpty() && PREMIUM_LABEL_HINTS.any { it in key }
    }

    /**
     * Whether the top rungs are locked for this viewer at all. The operator decides: with the
     * `quality_gate` switch off nobody is restricted, because hiding 1080p and 4K from a free
     * viewer is a pricing decision and not this app's to make. Both ViewModels ask here rather
     * than restating the rule, so the detail page and the player can never disagree.
     */
    fun premiumAccess(gateEnabled: Boolean, isVip: Boolean): Boolean = isVip || !gateEnabled

    fun allowsBand(band: String?, isVip: Boolean): Boolean = isVip || !isPremiumBand(band)

    fun allowsResolution(resolution: Resolution, isVip: Boolean): Boolean =
        isVip || !isPremiumResolution(resolution)

    /**
     * The ladder a non-VIP viewer may actually choose from. A premium band disappears together
     * with its `auto` pointer and its download-only listing; when nothing is left the ladder is
     * empty, which is the honest answer — there is no free picture to offer on this scope.
     */
    fun gate(ladder: LadderForScope, isVip: Boolean): LadderForScope {
        if (isVip) return ladder
        val kept = ladder.options.filter { !isPremiumBand(it.band) && !isPremiumLabel(it.title) }
        if (kept.size == ladder.options.size) return ladder
        val bands = kept.mapTo(HashSet()) { it.band }
        return LadderForScope(
            options = kept,
            autoBand = ladder.autoBand?.takeIf { it in bands },
            downloadOnlyBands = ladder.downloadOnlyBands.filter { it in bands },
        )
    }

    /**
     * The release layout with premium prints removed. Episodes and seasons that lose every
     * print disappear with them, and the counters/capability chips are rebuilt from what is
     * left, so the header never advertises "4K" for a page that will not play it.
     */
    fun gate(layout: ReleaseLayout, isVip: Boolean): ReleaseLayout {
        if (isVip) return layout
        val workPrints = layout.workPrints.filterNot { isPremiumResolution(it.resolution) }
        val seasons = layout.seasons.mapNotNull { season ->
            val episodes = season.episodes.mapNotNull { episode ->
                val prints = episode.prints.filterNot { isPremiumResolution(it.resolution) }
                if (prints.isEmpty()) null else episode.copy(prints = prints)
            }
            val packedPrints = season.packedPrints.filterNot { isPremiumResolution(it.resolution) }
            if (episodes.isEmpty() && packedPrints.isEmpty()) null
            else season.copy(episodes = episodes, packedPrints = packedPrints)
        }
        val remaining = workPrints +
            seasons.flatMap { season -> season.episodes.flatMap { it.prints } + season.packedPrints }
        return layout.copy(
            seasons = seasons,
            workPrints = workPrints,
            capabilities = ReleaseLayoutBuilder.capabilitiesOf(remaining),
            officialPrintCount = remaining.count { it.isOfficialPrint },
            camPrintCount = remaining.count { it.isCam },
            totalPrints = remaining.size,
        )
    }

    /** True when the ungated content has at least one 4K/1080p source worth an upsell. */
    fun hasPremiumPrints(layout: ReleaseLayout): Boolean =
        (layout.workPrints +
            layout.seasons.flatMap { season -> season.episodes.flatMap { it.prints } + season.packedPrints })
            .any { isPremiumResolution(it.resolution) }
}
