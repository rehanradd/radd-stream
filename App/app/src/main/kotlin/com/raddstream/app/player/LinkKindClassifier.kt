package com.raddstream.app.player

import com.raddstream.app.network.models.LinkAssessment
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.LinkKind
import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.SourceDetail

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  THE PLAYER'S VIEW OF A LINK — one rule, taken from the server, not guessed
 * ─────────────────────────────────────────────────────────────────────────────
 * This file used to be a 1:1 Kotlin port of `catalog_v2.py::classify_link()`: tables of
 * hoster slugs (`EMBED_SERVICES`, `BRIDGE_SERVICES`, `DOWNLOAD_ONLY_SERVICES`, `_TIER1`)
 * plus URL-shape heuristics, so the player could work out from a raw `source_url` /
 * `final_url` whether it was looking at an iframe page, a countdown page or a file.
 *
 * That whole apparatus is GONE, and it is not a loss:
 *  1. the public API stopped serving those inputs. A link object now carries our opaque
 *     `stream_id`, our own `play_url` and OUR classification words (`kind`, `playable`,
 *     `label`), because `Fast_Fetch/viewer.py::link_view()` does the classifying on the
 *     server side, where the ledger columns still exist;
 *  2. a port of a hoster list is itself a provenance surface — a table of names a rebrand
 *     can never wash out and a screenshot can never show — so keeping it "for parity" would
 *     reintroduce exactly what the redaction removed;
 *  3. the classification the player needs is now strictly better than the guess it
 *     replaced: measured (`http_status`, `mime_type`, `file_size_bytes`, `speed_mbps`) and
 *     authoritative (`playable`), instead of pattern-matched from a URL string.
 *
 * The single remaining rule lives in [LinkClassification.classify] and both sides of the
 * app call it, so a candidate can never be "playable" to the catalog and "unusable" to the
 * player. What stays here is the player's vocabulary: the honest label for a link it cannot
 * present, and the tiny adapter that turns a candidate into an assessment.
 */

/**
 * What the app says, out loud, about a link it cannot present: [Playability.DOWNLOAD] and
 * [Playability.NONE] candidates are offered for keeping and named honestly. There is no
 * WebView path to fall back to, and "nothing happened" is never the answer.
 */
const val NOT_PLAYABLE_HERE = "Not playable here"

/** The one presentation this product has. */
const val PLAYABLE_HERE = "Plays here"

/** Player-side verdict for one served link, from the server's own fields. */
data class PlayerLinkVerdict(
    val kind: LinkKind,
    val playability: Playability,
    val protocolWire: String,
    /** True when Media3 may be pointed at `play_url` as it stands. */
    val playableHere: Boolean,
    /** The honest sentence for anything not [playableHere]. */
    val label: String,
)

/**
 * Classify one link for the player. [playUrl] must be our own redirector address; the inputs
 * are the served fields and nothing else, so no host name can influence the verdict.
 */
fun classifyForPlayer(
    streamId: String,
    playUrl: String,
    kind: String? = null,
    playability: String? = null,
    protocol: String? = null,
    label: String? = null,
    mimeType: String? = null,
    status: String? = null,
    playable: Boolean? = null,
    downloadable: Boolean? = null,
    resumable: Boolean = false,
    ephemeral: Boolean = false,
    tier: Int? = null,
    httpStatus: Int? = null,
): PlayerLinkVerdict {
    val assessment = LinkClassification.classify(
        SourceDetail(
            streamId = streamId,
            playUrl = playUrl,
            label = label,
            kind = kind,
            playability = playability,
            protocol = protocol,
            mimeType = mimeType,
            status = status,
            playable = playable,
            downloadable = downloadable,
            isResumable = resumable,
            isTemporary = ephemeral,
            tier = tier,
            httpStatus = httpStatus,
        ),
    )
    return assessment.toPlayerVerdict()
}

fun LinkAssessment.toPlayerVerdict(): PlayerLinkVerdict = PlayerLinkVerdict(
    kind = kind,
    playability = playability,
    protocolWire = protocol.wire,
    playableHere = playability.isDirectlyPlayable,
    label = if (playability.isDirectlyPlayable) PLAYABLE_HERE else NOT_PLAYABLE_HERE,
)

/** Same verdict, read straight off a served row. */
fun classifyForPlayer(source: SourceDetail): PlayerLinkVerdict =
    LinkClassification.classify(source).toPlayerVerdict()
