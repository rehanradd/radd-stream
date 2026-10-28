package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/**
 * The server's quality ladder, as the wire delivers it.
 *
 * WHY THE APP READS THIS AT ALL: the ledger holds up to six copies of the same
 * print on six servers, and only the server can say which one to start. This is
 * that verdict, already collapsed — one row per quality band, each holding
 * exactly one link. The app does not re-rank them and never shows a list of
 * copies, which is both the owner's "don't confuse the user" rule and the reason
 * one detail response cannot be used to lift our whole link inventory.
 *
 * Every key here is one the public edge already publishes (see
 * `Fast_Fetch/redact.py`'s `ladder_link` view): handles, our own copy, and how
 * the copy behaves. There is no field that could hold a site name or an
 * upstream address, so nothing can be displayed by accident.
 */

/** The single winner of one ladder rung: everything a player needs to start. */
data class LadderLink(
    @SerializedName("stream_id")
    val streamId: String? = null,
    /** OUR OWN `/api/v1/stream?id=<handle>` redirector, never somebody else's URL. */
    @SerializedName("play_url")
    val playUrl: String? = null,
    /** Ours: `direct | resolve | download | external`. */
    val kind: String? = null,
    val playable: Boolean = false,
    /** Server-written scrape status: `active | dead | expired`. */
    val status: String? = null,
    @SerializedName("expires_at")
    val expiresAt: String? = null,
    @SerializedName("is_resumable")
    val isResumable: Boolean? = null,
    @SerializedName("is_temporary")
    val isTemporary: Boolean? = null,
    @SerializedName("file_size_bytes")
    val fileSizeBytes: Long? = null,
    /** Ours: "Fast direct" | "Standard". */
    val label: String? = null,
) {
    val bestUrl: String? get() = playUrl?.trim()?.takeIf { WireText.isHttpUrl(it) }
    val isEphemeral: Boolean get() = isTemporary == true
    val isResumableLink: Boolean get() = isResumable == true
    val isDead: Boolean get() = status == "dead" || status == "expired"
}

/**
 * One rung of the ladder. [backupHandles] are the runner-ups of the *same* band,
 * as opaque handles only: the player may hop to one silently, at the exact
 * position, without another request and without ever learning who serves it.
 */
data class LadderTier(
    /** `2160p | 1080p | 720p | 480p | sd | unspecified` — the row key of the switch. */
    val band: String = "",
    /** What the rung is called for a viewer who has never heard our vocabulary. */
    val quality: String? = null,
    /** Our own copy: "4K Ultra HD · HEVC". Never a site or a server name. */
    val label: String? = null,
    /** `play` when this rung can start here, `download_only` when it cannot. */
    val mode: String? = null,
    val playable: Boolean = false,
    /** How many copies collapsed into this one row — scale, not provenance. */
    val copies: Int = 0,
    val link: LadderLink? = null,
    @SerializedName("backup_handles")
    val backupHandles: List<String> = emptyList(),
)

/** The ladder's own pointer: the rung `Auto` starts at, and the handle it uses. */
data class LadderAuto(
    val band: String? = null,
    /** `best` — the server's reason in its own words, never a server name. */
    val reason: String? = null,
    @SerializedName("stream_id")
    val streamId: String? = null,
)

/** One scope's ladder: a movie has a single group, a series one per episode. */
data class OptionGroup(
    /** Free TEXT from the ledger (`"1"`, `"Season 7"`, null) — not re-derived here. */
    val season: String? = null,
    val episode: String? = null,
    val tiers: List<LadderTier> = emptyList(),
    val auto: LadderAuto? = null,
    @SerializedName("download_only_bands")
    val downloadOnlyBands: List<String> = emptyList(),
)
