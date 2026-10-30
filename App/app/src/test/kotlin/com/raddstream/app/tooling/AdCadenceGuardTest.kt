package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The three rules the owner called non-negotiable, enforced against the source rather than argued
 * in a review comment: no ad may block playback, no ad may be unskippable past five seconds, and an
 * ad that cannot be filled must leave nothing on screen — no spinner, no gate, no retry storm.
 *
 * A text scan is the honest offline proof for the parts of that which are properties of a Compose
 * tree, because the suites that could render them (`ScreenSnapshotTest`, `PosterCardProvenanceTest`)
 * are excluded on aarch64 and cannot run on this host. Each refusal is therefore anchored to the
 * declaration it governs — read as a line range out of the real file, never as "the word is absent
 * from the repo" — and paired with a positive control naming a fact in the same range that must
 * still be true. That is the pattern `StatsHonestyTest` exists for: a scan whose only assertions
 * are refusals goes green when a file is renamed or a block is deleted.
 */
class AdCadenceGuardTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val appMain: File = File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app")

    private fun lines(path: String): List<String> {
        val file = File(appMain, path)
        assertTrue("the guard has nothing to read at $path", file.isFile)
        return file.readLines()
    }

    /**
     * The expression body that starts at the first line containing [start], up to the first blank
     * line. Blank-line-delimited because each declaration this form is used on is one expression
     * followed by a blank line, and a range that silently ran to end-of-file would be asserting
     * about the whole file rather than about the rule.
     */
    private fun List<String>.expressionBlock(start: String): List<String> {
        val from = indexOfFirst { start in it }
        assertTrue("no declaration containing \"$start\"", from >= 0)
        var to = from + 1
        while (to < size && this[to].isNotBlank()) to++
        return subList(from, to)
    }

    /** The whole `{ … }` body that opens on the first line containing [start], brace-matched. */
    private fun List<String>.declarationBlock(start: String): List<String> {
        val from = indexOfFirst { start in it }
        assertTrue("no declaration containing \"$start\"", from >= 0)
        var depth = 0
        var seenBody = false
        for (index in from until size) {
            val code = this[index].withoutLeadingComments()
            depth += code.count { it == '{' } - code.count { it == '}' }
            if (depth > 0) seenBody = true
            if (seenBody && depth == 0) return subList(from, index + 1)
        }
        error("the block opened by \"$start\" never closed")
    }

    private fun String.withoutLeadingComments(): String = trim().let {
        if (it.startsWith("*") || it.startsWith("//") || it.startsWith("/*") || it.startsWith("*/")) "" else this
    }

    // ── rule 1: an ad never blocks playback ───────────────────────────────────────

    @Test
    fun `the chrome-suppression flag is built without the ad slot`() {
        val block = lines("ui/screens/PlayerScreen.kt")
            .expressionBlock("private val PlayerUiState.dialogBlocking")
        assertFalse(
            "an interstitial that holds the tape is the gate the owner ruled out",
            block.any { "adBreak" in it },
        )
        // Positive control: this is still the real gate, and it still lists the sheets.
        assertTrue(block.any { "resumeOfferMs != null" in it })
        assertTrue(block.any { "subtitleOffsetSheetVisible" in it })
    }

    @Test
    fun `the sponsor slot is a card the viewer dismisses over a player that keeps running`() {
        val call = lines("ui/screens/PlayerScreen.kt")
            .filter { "SponsorBreakDialog(slot = state.adBreak" in it }
        assertTrue("the card is still rendered", call.isNotEmpty())
        assertTrue(
            "and it leaves on the viewer's press, never on a timer the app decided",
            call.single().contains("onDismiss"),
        )
    }

    // ── rule 2: nothing unskippable past five seconds ────────────────────────────

    @Test
    fun `five seconds is the ceiling and it is enforced where a decision is made`() {
        val cadence = lines("player/AdCadence.kt")
        val ceiling = cadence.expressionBlock("const val MAX_SKIP_MS")
        assertTrue("the ceiling is 5000 ms: $ceiling", ceiling.single().contains("5_000L"))

        val answer = cadence.expressionBlock("fun skippableAtMs")
        assertTrue(
            "capped at the answer as well as at the parse, so no path returns a longer one",
            answer.any { "MAX_SKIP_MS" in it },
        )
        // Positive control: the answer still reads the limits it was handed.
        assertTrue(answer.any { "skippableAfterMs" in it })
    }

    @Test
    fun `the wire cannot buy a longer skip than the ceiling allows`() {
        val from = lines("player/AdCadence.kt").expressionBlock("fun from(ads: VipRemoteAds, engagement")
        assertTrue(from.any { "coerceAtMost(MAX_SKIP_MS)" in it })
        // Positive controls: the other three caps are resolved in the same expression, each against
        // the shipped window it falls back to, so an absent body cannot read as an unlimited one.
        assertTrue(from.any { "PRE_ROLL_MINUTES" in it })
        assertTrue(from.any { "FEED_CARD_POSTERS" in it })
        assertTrue(from.any { "APP_OPEN_HOURS" in it })
    }

    @Test
    fun `the engagement cadence block outranks the ads block it was written beside`() {
        val from = lines("player/AdCadence.kt").expressionBlock("fun from(ads: VipRemoteAds, engagement")
        // One merge point for the two bodies, and it is the policy's — not a call site's opinion.
        assertTrue(
            "the engagement caps must be the first candidate at every field",
            from.count { "gapMinutes(server." in it } == 2,
        )
        assertTrue(from.any { "server.feedCardEveryPosters > 0" in it })
        // The unit trap, stated where it is converted: the server says minutes, the old key says
        // hours, and a key rename must never be allowed to read 240 minutes as 240 hours.
        assertTrue(from.any { "ads.appOpenIntervalHours.toLong() * 60L" in it })
        val cadence = lines("network/models/VipRemoteConfig.kt")
            .expressionBlock("data class VipRemoteAdCadence")
        assertTrue(
            "app-open hours must never be an alternate spelling of the server's minutes key",
            cadence.none { "app_open_interval_hours" in it },
        )
        // Positive control: the server's own spelling really is what this client reads.
        assertTrue(cadence.any { "\"ad_app_open_min_gap_minutes\"" in it })
    }

    // ── rule 3: an unfilled slot is nothing at all ────────────────────────────────

    @Test
    fun `a decision has no waiting state a screen could spin for`() {
        val sealed = lines("player/AdCadence.kt")
            .declarationBlock("sealed interface AdDecision")
            .map { it.withoutLeadingComments() }
            .joinToString("\n")
        listOf("Loading", "Pending", "Retrying", "Waiting").forEach { word ->
            assertFalse("no $word variant may exist: a state that waits is a state a UI spins for",
                word in sealed)
        }
        // Positive control: the two states that do exist are the refusal and the serve.
        assertTrue("None" in sealed)
        assertTrue("Serve" in sealed)
    }

    @Test
    fun `the production inventory says nothing can be filled`() {
        val binding = lines("player/AdCadence.kt").declarationBlock("class NoAdInventory")
        assertTrue(
            "canFill is a flat false",
            binding.single { "canFill" in it }.contains("= false"),
        )
        val module = lines("di/AdModule.kt")
        assertTrue("AdModule still declares the inventory provider", module.any { "fun provideAdInventory" in it })
        assertTrue("and binds exactly that class", module.any { "= NoAdInventory()" in it })
    }

    @Test
    fun `no file that owns the cadence can render a progress indicator`() {
        listOf(
            "player/AdCadence.kt",
            "player/AdCadenceGovernor.kt",
            "data/local/AdCadence.kt",
            "di/AdModule.kt",
        ).forEach { path ->
            val code = lines(path).map { it.withoutLeadingComments() }.joinToString("\n")
            assertFalse(
                "$path must not paint a wait: a spinner is the gate this directive forbids",
                "CircularProgressIndicator" in code || "LinearProgressIndicator" in code,
            )
        }
        // Positive control: the scan read the cadence files, not empty lists.
        assertTrue(lines("player/AdCadenceGovernor.kt").any { "AdDecision.None" in it })
        assertTrue(lines("player/AdCadence.kt").any { "interface AdInventory" in it })
    }

    // ── the wiring, so a guard cannot go green beside a feature nobody calls ───────

    @Test
    fun `each surface asks the governor rather than deciding for itself`() {
        assertTrue(
            "pre-roll",
            lines("viewmodel/PlayerViewModel.kt").any { "adCadence.offer(AdSurface.PRE_ROLL" in it },
        )
        val browse = lines("viewmodel/BrowseViewModel.kt")
        assertTrue("feed card", browse.any { "adCadence.offer(AdSurface.FEED_CARD" in it })
        assertTrue("and it reports the posters it passed", browse.any { "adCadence.onPostersScrolled(" in it })
        assertTrue(
            "app-open",
            lines("viewmodel/HomeViewModel.kt").any { "adCadence.offer(AdSurface.APP_OPEN" in it },
        )
    }

    @Test
    fun `the interstitial seam has a caller, and that caller holds its hand off`() {
        val player = lines("viewmodel/PlayerViewModel.kt")
        assertTrue(
            "the policy is asked somewhere real, not only by a test",
            player.any { "requestBetweenEpisodesBreak()" in it && "if (" in it },
        )
        assertTrue(
            "a granted break holds the successor instead of dropping it",
            player.any { "pendingCrossEpisode = action" in it },
        )
        val dismiss = player.expressionBlock("fun dismissAdBreak()")
        assertTrue("dismissal plays the held hand-off", dismiss.any { "advanceCrossEpisode(held)" in it })
        assertTrue("and takes nothing for a break that was never raised", dismiss.any { "?: return" in it })
        // Positive control: the hand-off itself is still the same single implementation, shared by
        // the ad path and the no-ad path.
        assertTrue(player.any { "private suspend fun advanceCrossEpisode(" in it })
    }

    @Test
    fun `the config poll publishes the caps and resets the windows when the switch goes off`() {
        val watcher = lines("data/RemoteConfigWatcher.kt")
        assertTrue("caps travel with the body", watcher.any { "publishLimits(config.ads, config.engagement)" in it })
        assertTrue("a disabled switch clears every stamp", watcher.any { "clearForDisabledSwitch()" in it })
        assertTrue("the switch is mirrored to storage", watcher.any { "adsEnabled = config.ads.enabled" in it })
    }

    @Test
    fun `the cadence lives in the rooms database and no new store was invented`() {
        val db = lines("data/local/AppDatabase.kt")
        assertTrue("registered as an entity", db.any { "AdCadenceEntity::class" in it })
        assertTrue("with a dao", db.any { "abstract fun adCadenceDao" in it })
        assertTrue("and a real migration", db.any { "MIGRATION_6_7" in it })
        val module = lines("di/DatabaseModule.kt")
        assertTrue("handed to the builder", module.any { "AppDatabase.MIGRATION_6_7" in it })
        assertTrue("and provided to its callers", module.any { "adCadenceDao()" in it })
    }
}
