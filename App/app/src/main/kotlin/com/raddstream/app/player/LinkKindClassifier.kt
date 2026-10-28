package com.raddstream.app.player

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
 * The single remaining rule lives in `LinkClassification.classify()` and every caller uses
 * it directly, so a candidate can never be "playable" to the catalog and "unusable" to the
 * player. What stays here is only the player's vocabulary — the two words it says out loud
 * about a link. A per-caller verdict type was removed once nothing asked for one.
 */

/**
 * What the app says, out loud, about a link it cannot present: a `download` or `none`
 * playability is offered for keeping and named honestly. There is no WebView path to fall
 * back to, and "nothing happened" is never the answer.
 */
const val NOT_PLAYABLE_HERE = "Not playable here"

/** The one presentation this product has. */
const val PLAYABLE_HERE = "Plays here"
