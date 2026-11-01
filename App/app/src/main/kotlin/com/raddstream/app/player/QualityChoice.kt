package com.raddstream.app.player

import java.util.Locale

/**
 * The viewer's picture-quality decision, in one place: what a brand-new install plays, which
 * bands a title actually offers, what happens when the saved band is missing, and which copy
 * inside the chosen band is the best one to start.
 *
 * WHY THIS IS ITS OWN FILE. Every one of those four answers used to be implicit in a different
 * layer — the ladder's `resolvedFor` fell back to Auto, [com.raddstream.app.viewmodel.DetailViewModel]
 * defaulted `selectedBand` to `auto`, and the "best copy" decision was made once, server-side,
 * per band. The owner's spec asks for something narrower and stricter: a *saved viewer choice*
 * that survives a restart, `720p` as the first-ever default, and a nearest-lower-then-higher
 * fallback that says out loud which picture the viewer actually got. That is a rule with four
 * branches and a sentence, and a rule with a sentence is a rule a test can pin. Nothing here
 * touches Android types, so it runs on the JVM.
 *
 * WHAT IT DOES NOT OWN. The grammar that turns a release label into a band
 * ([com.raddstream.app.network.models.ReleaseLabelParsing]), the server's collapse of one band
 * into one winner ([QualityLadder]), the print ranking and the CAM rule
 * ([com.raddstream.app.viewmodel.ReleaseLayoutBuilder]), and who may see 1080p/4K
 * ([com.raddstream.app.viewmodel.VipQualityGate]). This file reads the bands those owners
 * publish; it never re-derives one from a title and never decides eligibility.
 */
object QualityChoice {

    /**
     * The band a first-ever play uses. `720p` is the owner's approved default (spec, Play,
     * "First time ever: 720p") and sits at the top of what a free viewer may play under the
     * existing policy, so the default and the cap agree without either one special-casing the
     * other. A title with no 720p print is handled by [fallbackFrom], not by changing this.
     */
    const val FIRST_RUN_BAND = "720p"

    /**
     * The ladder's own band vocabulary, cheapest first. `sd` and `unspecified` are the two words
     * [QualityOption] documents for a rung the server could not measure. Every entry here is a
     * *folded* word: [canonical] maps the shorthands onto the resolution they mean, so the ladder
     * that spells its top rung `4K`, `UHD` or `2160p` (`VipQualityGate.PREMIUM_BANDS` accepts all
     * three) sorts identically and, more importantly, so a saved `4K` preference still matches a
     * title whose band is spelled `2160p` instead of becoming a silent substitution.
     * Anything not listed ranks as "unknown height" and is only ever chosen when nothing else
     * is, never as a *higher* fallback — inventing a step up from a word this file does not
     * understand is exactly the guess the spec's plain note is meant to replace.
     */
    private val BAND_HEIGHT: List<String> = listOf(
        "unspecified",
        "sd",
        "360p",
        "480p",
        "720p",
        "1080p",
        "2160p",
    )

    /**
     * Spellings the switch uses for one picture, folded to the resolution they name. Folding is
     * why [bandsPresent] can promise "one entry per picture" without a second dedupe pass, and
     * why the height order above needs only seven rungs.
     */
    private val BAND_SYNONYMS = mapOf(
        "fhd" to "1080p",
        "fullhd" to "1080p",
        "uhd" to "2160p",
        "4k" to "2160p",
    )

    /**
     * A band, as this file keys it: trimmed, blank-as-null, lower-cased, spaces removed, and
     * folded to the resolution the word names. `null` for absent-or-blank, so "never saved" and
     * "saved as empty" are the same answer to [planFor].
     */
    fun canonical(band: String?): String? {
        val key = band?.trim()?.lowercase(Locale.ROOT)?.replace(" ", "")?.takeIf { it.isNotEmpty() }
            ?: return null
        return BAND_SYNONYMS[key] ?: key
    }

    /**
     * The only bands a title can be offered in, in the order a menu shows them: cheapest first,
     * each listed once, and never a band the title does not have.
     *
     * A menu that paints 360p/480p/720p/1080p/2160p for a title that only has 480p is the bug
     * this refuses — the viewer picks a picture that cannot exist, and the app either falls back
     * silently or fails. Spec: "Quality menu: only bands that exist for this title."
     */
    fun bandsPresent(bands: List<String?>): List<String> {
        val present = bands.mapNotNull { canonical(it) }.toSet()
        val known = BAND_HEIGHT.filter { it in present }
        // A band word this file has never seen is still a band the title has: it goes last, in
        // the order the ladder carried it, rather than being dropped from the menu.
        val unknown = bands.mapNotNull { canonical(it) }.distinct().filterNot { BAND_HEIGHT.contains(it) }
        return known + unknown
    }

    /**
     * Where a band sits in [BAND_HEIGHT]. Unknown words sit below every known one, which is what
     * stops an unrecognised label from being offered as a step UP in [fallbackFrom].
     */
    private fun heightOf(band: String?): Int {
        val key = canonical(band) ?: return -1
        val at = BAND_HEIGHT.indexOf(key)
        return if (at < 0) -1 else at
    }

    /**
     * The band the app will actually play, and whether it is the one that was asked for.
     *
     * [requested] is the viewer's saved choice (or [FIRST_RUN_BAND] when nothing was ever
     * saved); [present] is [bandsPresent] of this title's ladder. When the requested band is
     * there, it wins. When it is not, the rule is the spec's: **nearest lower first, then
     * nearest higher** — a viewer who asked for 1080p and lands on 720p gets less data and no
     * buffering stall, while a silent jump to 2160p spends bandwidth on a connection the viewer
     * already proved is not holding the picture they chose. Because [canonical] folds height
     * shorthands onto the resolution they name, two spellings of one picture are never two
     * candidates, so "nearest" is always a real step and never a synonym.
     *
     * An empty [present] answers `null`: no band, no promise, and the caller says so instead of
     * inventing a picture.
     */
    fun fallbackFrom(requested: String?, present: List<String>): QualityPlan {
        val wanted = canonical(requested)
        val options = present.mapNotNull { canonical(it) }
        if (options.isEmpty()) return QualityPlan(null, null, null)
        if (wanted != null && options.contains(wanted)) {
            return QualityPlan(wanted, wanted, null)
        }
        val wantedHeight = heightOf(wanted)
        // Every band we can place, so a lower candidate is measurable. An unplaceable wanted
        // word (null, or a word from an older build) has no lower and no higher: take the
        // middle of what exists rather than the top, which is the honest "no preference".
        if (wantedHeight < 0) {
            val middle = options.firstOrNull { it == FIRST_RUN_BAND } ?: options[midPoint(options)]
            return QualityPlan(middle, wanted, null)
        }
        val lower = options
            .filter { heightOf(it) in 0 until wantedHeight }
            .maxByOrNull { heightOf(it) }
        val chosen = lower
            ?: options.filter { heightOf(it) > wantedHeight }.minByOrNull { heightOf(it) }
            ?: options[midPoint(options)]
        val direction = when {
            chosen == wanted -> null
            heightOf(chosen) < wantedHeight -> Step.LOWER
            heightOf(chosen) > wantedHeight -> Step.HIGHER
            else -> null
        }
        return QualityPlan(chosen, wanted, direction)
    }

    /** The middle band of a non-empty list, by index, for the no-preference case. */
    private fun midPoint(options: List<String>): Int = options.size / 2

    /** Which way the app had to move from what the viewer asked for. */
    enum class Step { LOWER, HIGHER }

    /**
     * What the app decided: the band to play, the band that was asked for, and whether those
     * differ. [substituted] is the only case that earns an explanation — a note about a
     * substitution that did not happen is noise, and noise on a play tap reads like an error.
     */
    data class QualityPlan(
        val band: String?,
        val requested: String?,
        val step: Step?,
    ) {
        /** The substitution never happened (or there is nothing to play at all). */
        val isExact: Boolean get() = step == null

        /** The viewer got a different picture than they asked for, and must be told which. */
        val substituted: Boolean get() = step != null

        /**
         * The two halves of the sentence the screens paint, ready for
         * [com.raddstream.app.R.string.detail_quality_note] — `Playing in %1$s — %2$s is not
         * available for this title.` They are produced as LABELS and never as a sentence, so the
         * English itself stays in `res/values/` where a locale folder can reach it, exactly like
         * the player's chrome vocabulary. This file owns WHICH two words go in the blanks; the
         * resource owns how the sentence reads. `null` (either half) means say nothing.
         */
        val playedLabel: String? get() = if (substituted) QualityChoice.labelOf(band) else null

        /** The band that was asked for and does not exist here. See [playedLabel]. */
        val missingLabel: String? get() = if (substituted) QualityChoice.labelOf(requested) else null
    }

    /**
     * A band word in the viewer's words: `4K`, `SD`, `360p`…`1080p` as spelled.
     *
     * Deliberately NOT [com.raddstream.app.network.models.ReleaseLabelParsing]'s `QUALITY_LABELS`
     * ("HD", "Full HD"): those are marketing names for a PRINT, and the spec's own sentence names
     * the rung the viewer picked — a viewer who chose `720p` must read `720p` back, not `HD`.
     * `unspecified` answers null: a picture this file cannot name is a picture it must not
     * describe, and the no-note branch is the honest one.
     */
    fun labelOf(band: String?): String? {
        val key = canonical(band) ?: return null
        return when (key) {
            "unspecified" -> null
            "2160p" -> "4K"
            "sd" -> "SD"
            "360p", "480p", "720p", "1080p" -> key
            else -> key.uppercase(Locale.ROOT)
        }
    }

    /**
     * The band a play tap uses, start to finish: the saved choice if there is one, else the
     * first-run default, resolved against what this title actually has. One function so the
     * detail screen, the player and Settings cannot each re-implement the order and disagree.
     */
    fun planFor(savedBand: String?, present: List<String>): QualityPlan =
        fallbackFrom(savedBand?.takeIf { !it.isNullOrBlank() } ?: FIRST_RUN_BAND, present)

    /**
     * The rung a band decision points at, matched the way this file matches bands — folded, so a
     * plan that resolved to `2160p` finds the rung the ladder spelled `4K`. [LadderForScope.optionFor]
     * compares the served words, and a synonym would silently fall through to Auto: the viewer's
     * saved 4K choice would play the server's default picture and no note would explain why.
     */
    fun rungFor(options: List<QualityOption>, band: String?): QualityOption? {
        val key = canonical(band) ?: return null
        return options.firstOrNull { canonical(it.band) == key }
    }

    /**
     * Which copy inside one band to start, from the copies the band holds.
     *
     * The server already collapsed a print to one winner per band, so this is deliberately a
     * small, stable score over the fields the wire actually carries — a live link that can
     * resume and whose size is known is a copy this app can start and restart, which is exactly
     * what the spec asks for ("alive, fast, resumable … recent link-health"). Speed and the
     * server's own rank break a tie; an ephemeral address is worth less because it rots, and a
     * CAM copy sorts last per the standing rule, which [sortedForFailover] keeps true for the
     * whole runner-up list rather than only the winner.
     *
     * Returns null for an empty list. It never re-scores a print: `camCopy` is the layout
     * builder's verdict handed in, not re-derived from a label here.
     */
    fun bestCopy(copies: List<CopyCandidate>): CopyCandidate? =
        copies.maxWithOrNull(CopyCandidate.ByLiveCopy)

    /**
     * The silent failover order inside one band: the winner first, then every remaining copy by
     * the same score. The player walks this list and never mentions it, which is why the spec
     * can promise "Never show failed attempts" — the order is data, not chrome.
     *
     * The two sorts read one score, in opposite directions: [ByLiveCopy] is the ascending one
     * [bestCopy] compares against, [ByLiveCopyDescending] is this list. Kotlin's
     * `compareByDescending` is used instead of the Java `reversed()` default method because the
     * app runs on every device back to API 21, where that comparator method does not exist.
     * Both sorts are stable, so equal scores keep the order the server ranked the ladder in.
     */
    fun sortedForFailover(copies: List<CopyCandidate>): List<CopyCandidate> =
        copies.sortedWith(CopyCandidate.ByLiveCopyDescending)

    /**
     * One copy of one band, in the only terms this decision reads. Every field maps straight
     * onto a served one ([QualityOption.resumable], [QualityOption.playsHere],
     * [QualityOption.sizeBytes], [com.raddstream.app.network.models.LinkAssessment.speedMbps],
     * [com.raddstream.app.network.models.LinkAssessment.ephemeral],
     * [com.raddstream.app.network.models.LinkClassification.rankOf]) — no key is invented.
     */
    data class CopyCandidate(
        val handle: String,
        val alive: Boolean,
        val resumable: Boolean,
        val sizeKnown: Boolean,
        val ephemeral: Boolean,
        val speedMbps: Double?,
        val rankScore: Int,
        val camCopy: Boolean,
    ) {
        /**
         * The score behind [ByLiveCopy], public so a test can assert one number's meaning
         * instead of asserting an ordering and inferring the rule from it.
         */
        val liveScore: Int
            get() {
                var score = 0
                if (alive) score += 100_000
                if (resumable) score += 10_000
                if (sizeKnown) score += 1_000
                if (!ephemeral) score += 100
                if (!camCopy) score += 10
                val speed = speedMbps?.takeIf { it.isFinite() && it > 0.0 }
                score += (speed?.toInt()?.coerceIn(0, 9) ?: 0)
                score += (rankScore / 1000).coerceIn(0, 9)
                return score
            }

        companion object {
            /**
             * The one score the band decision ranks copies by, written in one place so [bestCopy]
             * and [sortedForFailover] can never rank two copies two different ways. Nothing after
             * it: [maxWithOrNull] answers with the first maximum, so a tie keeps the order the
             * server already ranked the ladder in. A second key here would re-shuffle equal copies
             * and make the failover trail impossible to read against the response it came from.
             */
            internal val ByLiveCopy: Comparator<CopyCandidate> = compareBy { it.liveScore }

            /**
             * The same score, read the other way round, for the list that starts with the winner.
             * Written with Kotlin's `compareByDescending` rather than Java's `reversed()` because
             * `reversed()` is a default method on `java.util.Comparator` added in API 24 and this
             * app runs down to API 21 — a lint `NewApi` error, not a warning.
             */
            internal val ByLiveCopyDescending: Comparator<CopyCandidate> =
                compareByDescending { it.liveScore }
        }
    }
}
