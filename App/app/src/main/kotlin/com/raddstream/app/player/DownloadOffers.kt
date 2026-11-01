package com.raddstream.app.player

/**
 * Which of a title's rungs may be OFFERED as a Download, and what the sheet says about each one.
 *
 * The download sheet's whole job is a promise: tap this and the file is on the device later. Three
 * kinds of row break that promise, and the app has shipped all three — a link the switch already
 * knows is dead, the same file listed twice under two labels, and a PROVIDER PAGE (a web page or a
 * playlist pointer, not a video at all) offered as if it were downloadable. The spec's rule is
 * blunt: dead links, duplicate copies and page-only links are NEVER offered as Download, and the
 * rows that are offered show a quality and a size and nothing else — no "Download only", no
 * protocol, no codec.
 *
 * This is the filter and the row model, kept away from the sheet so the three exclusions can be
 * tested without a device, a cache database or a network. The rung vocabulary it reads is the
 * ladder's own ([QualityOption]) — it invents no new field and re-derives nothing the server
 * already decided.
 */
object DownloadOffers {

    /**
     * One row of the sheet. [label] is the band in the viewer's words ("720p", "4K") and [size] is
     * the served byte count already formatted by the ladder's own owner, or null when nobody
     * measured it. A row is deliberately NOT given the handle: the sheet hands the whole
     * [Offer] back to the ViewModel, which plays and keeps by handle the way it already does —
     * a UI that could receive a URL is a UI that will one day paint one.
     */
    data class Offer(
        val label: String,
        val size: String?,
        val option: QualityOption,
    )

    /**
     * The rows the sheet may show, cheapest picture first — the same order the quality menu uses,
     * so a viewer reading "720p" at the top of one list is not surprised to find it at the bottom
     * of the other.
     *
     * Excluded, in the order the rule asks about them:
     *  - a provider page ([QualityOption.isProviderPage]): a page is not a file. This is the
     *    classification the app already owns ([com.raddstream.app.network.models.ProviderPageLinks])
     *    and the ladder already carries per rung; here it is simply not eligible.
     *  - a rung with no winner: a blank `streamId` is what the ladder documents for "this band had
     *    no link at all", and a dead or unverified address looks exactly the same from here —
     *    there is nothing to fetch, so there is nothing to promise.
     *  - a file that cannot resume: the switch says so per link (`isResumable`), and a download
     *    that restarts from zero after a dropped connection is not the download this sheet sells.
     *  - a duplicate: two rungs whose winner is the SAME handle are one file wearing two labels,
     *    and two rungs folded to the same band (see [QualityChoice.canonical], `4K` and `2160p`)
     *    are one picture. First served row wins, because the ladder arrives already ranked.
     */
    fun eligible(options: List<QualityOption>): List<Offer> {
        val seenHandles = mutableSetOf<String>()
        val seenBands = mutableSetOf<String>()
        val kept = mutableListOf<QualityOption>()
        for (option in options) {
            if (option.isProviderPage) continue
            if (option.streamId.isBlank()) continue
            if (!option.resumable) continue
            if (!seenHandles.add(option.streamId)) continue
            // A band this file cannot fold (a word from a future switch) is not a duplicate of
            // anything: keep it, but never let two spellings of one picture through.
            val band = QualityChoice.canonical(option.band)
            if (band != null && !seenBands.add(band)) continue
            kept += option
        }
        val cheapestFirst = QualityChoice.bandsPresent(kept.map { it.band })
        val ordered = kept.sortedBy { rankIn(cheapestFirst, it.band) }
        return ordered.map { option ->
            Offer(
                label = QualityChoice.labelOf(option.band) ?: option.title,
                size = option.sizeLine,
                option = option,
            )
        }
    }

    /**
     * Where a band sits in a [QualityChoice.bandsPresent] list. An unplaced band sorts after every
     * placed one, which is the same rule the menu uses, so the two lists can never disagree.
     */
    private fun rankIn(order: List<String>, band: String?): Int {
        val key = QualityChoice.canonical(band) ?: return order.size
        val at = order.indexOf(key)
        return if (at < 0) order.size else at
    }

    /**
     * Whether the Download button may exist at all for this scope. With nothing eligible the
     * button has no honest action, and the spec's answer is to not show it — never to show it and
     * toast a failure.
     */
    fun canOffer(options: List<QualityOption>): Boolean = eligible(options).isNotEmpty()
}
