"""Subtitle tracks harvested server-side, served as `tracks[]` in the v2 bundle.

Gap A3 (M8 / G-1): no subtitle URL existed anywhere in the catalog. The
player's subtitle picker only ever saw tracks embedded in the stream, while
the resolvers were already extracting subtitle URLs (`host_resolvers` returns
`"subtitles": [{"language", "url"}]`) and some importers were capturing them
in staging `raw_meta` — and both were dropped on the floor.

This module is the durable half: it normalises a subtitle entry to the wire
shape the app already parses (`SubtitleTrackInfo`: lang/kind/url/format/
default/forced), stores it keyed by the ledger link id, and reads it back
for the bundle. Two writers feed it:

* resolve-time — `record_resolver_subtitles` persists the verdict's
  subtitles the moment a press unwraps a video. The next bundle for that
  release then carries them. First plays have no tracks (nothing has been
  unwrapped yet); every press after the first does.
* import-time — `harvest_from_staging` reads a staging DB's `raw_meta`
  `"subtitles"` entries and maps them onto ledger `download_sources` rows
  by `source_url`. A tested function; wiring it into the merge is a
  follow-up, not part of this change.

The table lives in the live DB (not the projection): it is keyed by the
stable ledger link id, so a projection rebuild never loses it, and the
bundle builder reads it with one batched SELECT. Like `resolved_cache`,
every statement runs WITHOUT committing — the caller's transaction owns it.
"""

from __future__ import annotations

import re
import sqlite3
import time
import urllib.parse

#: Wire kind for every harvested track. The app distinguishes subtitles from
#: other text tracks by this value (`SubtitleTrackInfo.kind`, default
#: "subtitles").
KIND_SUBTITLES = "subtitles"

#: Subtitle formats the app can hand to Media3 natively, keyed by file
#: extension. Anything else keeps `format=None` — the track is still
#: served (the player falls back to its own parser), it just carries no
#: format hint.
_FORMAT_BY_EXTENSION = {
    "vtt": "vtt",
    "srt": "srt",
    "ass": "ass",
    "ssa": "ssa",
    "ttml": "ttml",
}

#: Spoken-language names the scrapers print, mapped to the BCP-47 code the
#: app's language picker matches on. Anything already a code is lowercased
#: and kept as-is; an unknown name is kept as-is (lowercased) so the track
#: is never dropped for a label we did not expect.
_LANGUAGE_BY_NAME = {
    "english": "en",
    "eng": "en",
    "hindi": "hi",
    "hin": "hi",
    "urdu": "ur",
    "urd": "ur",
    "punjabi": "pa",
    "pan": "pa",
    "bengali": "bn",
    "bangla": "bn",
    "ben": "bn",
    "tamil": "ta",
    "tam": "ta",
    "telugu": "te",
    "tel": "te",
    "malayalam": "ml",
    "mal": "ml",
    "marathi": "mr",
    "mar": "mr",
    "gujarati": "gu",
    "guj": "gu",
    "kannada": "kn",
    "kan": "kn",
    "arabic": "ar",
    "ara": "ar",
    "french": "fr",
    "fra": "fr",
    "fre": "fr",
    "spanish": "es",
    "spa": "es",
    "german": "de",
    "deu": "de",
    "ger": "de",
    "portuguese": "pt",
    "por": "pt",
    "russian": "ru",
    "rus": "ru",
    "japanese": "ja",
    "jpn": "ja",
    "korean": "ko",
    "kor": "ko",
    "chinese": "zh",
    "zho": "zh",
    "chi": "zh",
    "italian": "it",
    "ita": "it",
    "dutch": "nl",
    "nld": "nl",
    "turkish": "tr",
    "tur": "tr",
    "subs": "subs",
    "subtitle": "subs",
    "subtitles": "subs",
}

#: One statement per entry — NEVER conn.executescript(): it issues an
#: implicit COMMIT first, which would hijack whatever the calling
#: transaction had pending on this shared connection (the same contract
#: `resolved_cache` documents).
_DDL_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS subtitle_tracks (
        link_id     INTEGER NOT NULL,               -- download_sources.id
        lang        TEXT NOT NULL DEFAULT '',
        url         TEXT NOT NULL,
        format      TEXT,
        kind        TEXT NOT NULL DEFAULT 'subtitles',
        is_default  INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
        is_forced   INTEGER NOT NULL DEFAULT 0 CHECK (is_forced IN (0, 1)),
        source      TEXT NOT NULL DEFAULT 'resolve'
                      CHECK (source IN ('resolve', 'import')),
        updated_at  REAL NOT NULL,
        PRIMARY KEY (link_id, lang, url)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_subtitle_tracks_link "
    "ON subtitle_tracks(link_id)",
)


def init_subtitle_tracks(conn: sqlite3.Connection) -> None:
    """Create the table and its index, one statement per `execute`.

    Deliberately NOT `executescript` — that commits the caller's pending
    transaction first. Every statement is IF NOT EXISTS.
    """
    for statement in _DDL_STATEMENTS:
        conn.execute(statement)


def format_for_url(url: str) -> str | None:
    """Subtitle format from a URL's extension, or None when unknown."""
    path = urllib.parse.urlsplit(url or "").path or ""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    return _FORMAT_BY_EXTENSION.get(ext)


def normalize_language(language) -> str:
    """A scraper's language label to the code the app matches on."""
    raw = str(language or "").strip().lower()
    if not raw:
        return ""
    # "en-US" / "pt-BR" style tags keep their primary subtag.
    primary = raw.split("-")[0].split("_")[0].strip()
    return _LANGUAGE_BY_NAME.get(primary, primary)


def normalize_track(entry) -> dict | None:
    """One raw subtitle entry to the wire shape, or None when unusable.

    Accepts the resolver shape (`{"language", "url"}`), the wire shape
    (`{"lang", "subtitle_url", "format", ...}`), and a bare URL string (language
    unknown). A track is unusable when it has no https URL: a relative
    path, an http URL, or an empty string can never be handed to the
    player, so it is dropped here rather than served and failed on.

    The wire key is deliberately `subtitle_url`, not `url`: `url` is a
    PROVENANCE key (`redact.PROVENANCE`), and the `public_edge` scrub
    drops every PROVENANCE key from a v2 response — a track filed under
    `url` would arrive at the app with no file to fetch. Same convention
    as the link's `play_url`: a URL the client is meant to use gets a
    publishable name.
    """
    if isinstance(entry, str):
        entry = {"url": entry}
    if not isinstance(entry, dict):
        return None
    url = str(entry.get("url") or entry.get("subtitle_url") or "").strip()
    if not url.lower().startswith("https://"):
        return None
    lang = normalize_language(entry.get("lang", entry.get("language", "")))
    fmt = entry.get("format") or format_for_url(url)
    fmt = str(fmt).lower().strip() if fmt else None
    kind = str(entry.get("kind") or KIND_SUBTITLES).strip().lower() or KIND_SUBTITLES
    return {
        "lang": lang,
        "kind": kind,
        "subtitle_url": url,
        "format": fmt,
        "default": bool(entry.get("default", False)),
        "forced": bool(entry.get("forced", False)),
    }


def normalize_tracks(entries) -> list[dict]:
    """Normalise a list of raw entries, dropping the unusable, deduped by
    (lang, url) in first-seen order."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for entry in entries or []:
        track = normalize_track(entry)
        if track is None:
            continue
        key = (track["lang"], track["subtitle_url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(track)
    return out


def extract_from_raw_meta(blob) -> list:
    """The subtitle entries a staging `raw_meta` blob carries, if any.

    Importers stash them under the `"subtitles"` key as a list of dicts
    (`{"language", "url"}`) or bare URL strings; a single dict or string
    is accepted too. Anything else yields [] — a blob that never carried
    subtitles is not an error.
    """
    if not isinstance(blob, dict):
        return []
    subtitles = blob.get("subtitles")
    if subtitles is None:
        return []
    if isinstance(subtitles, (dict, str)):
        return [subtitles]
    if isinstance(subtitles, list):
        return list(subtitles)
    return []


def upsert_tracks(conn: sqlite3.Connection, link_id: int, tracks,
                  source: str = "resolve") -> int:
    """Store normalised tracks for one ledger link. Returns how many were
    written. Does NOT commit — the caller's transaction owns it. A later
    upsert for the same (link, lang, url) replaces the row, so a
    re-resolve refreshes rather than duplicates."""
    if source not in ("resolve", "import"):
        source = "resolve"
    init_subtitle_tracks(conn)
    now = time.time()
    count = 0
    for track in normalize_tracks(tracks):
        conn.execute(
            """
            INSERT INTO subtitle_tracks
                (link_id, lang, url, format, kind, is_default, is_forced,
                 source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link_id, lang, url) DO UPDATE SET
                format = excluded.format,
                kind = excluded.kind,
                is_default = excluded.is_default,
                is_forced = excluded.is_forced,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (int(link_id), track["lang"], track["subtitle_url"], track["format"],
             track["kind"], 1 if track["default"] else 0,
             1 if track["forced"] else 0, source, now),
        )
        count += 1
    return count


def tracks_for_links(conn: sqlite3.Connection, link_ids) -> dict[int, list[dict]]:
    """The stored tracks for a batch of ledger link ids, wire-shaped.

    One SELECT for the whole batch. Links with no stored tracks are
    absent from the result (the caller defaults them to []). Tracks come
    back ordered by language then URL, so the bundle is deterministic.
    """
    ids = [int(link_id) for link_id in (link_ids or []) if link_id is not None]
    if not ids:
        return {}
    # Read-only: never CREATE the table here — this runs on the bundle
    # read path, which may hold a read-only connection. No table means
    # no tracks were ever stored, so the answer is {}.
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table'"
        " AND name = 'subtitle_tracks' LIMIT 1").fetchone()
    if table is None:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT link_id, lang, url, format, kind, is_default, is_forced
        FROM subtitle_tracks WHERE link_id IN ({placeholders})
        ORDER BY link_id, lang, url
        """,
        ids,
    ).fetchall()
    out: dict[int, list[dict]] = {}
    for row in rows:
        link_id, lang, url, fmt, kind, is_default, is_forced = row
        out.setdefault(int(link_id), []).append({
            "lang": lang or "",
            "kind": kind or KIND_SUBTITLES,
            "subtitle_url": url,
            "format": fmt,
            "default": bool(is_default),
            "forced": bool(is_forced),
        })
    return out


def record_resolver_subtitles(conn: sqlite3.Connection, link_id: int,
                              verdict) -> int:
    """Persist a resolver verdict's subtitles for one ledger link.

    Returns how many tracks were stored (0 when the verdict carried none
    or was unusable). Never raises — a subtitle write must never change
    the resolve answer the caller is about to serve.
    """
    try:
        if not isinstance(verdict, dict):
            return 0
        subtitles = verdict.get("subtitles")
        if not subtitles:
            return 0
        return upsert_tracks(conn, int(link_id), subtitles, source="resolve")
    except Exception:  # noqa: BLE001 - subtitle persistence is best-effort
        return 0


def harvest_from_staging(staging_conn: sqlite3.Connection,
                         live_conn: sqlite3.Connection,
                         *, limit: int = 0) -> dict:
    """Harvest staging `raw_meta` subtitles onto ledger link rows.

    Reads staging `posts` rows (their `raw_meta` `"subtitles"` entries)
    and the staging `sources` table (`post_canonical_key` -> `source_url`),
    then upserts tracks for the ledger `download_sources` row whose
    `source_url` matches. A staging source with no ledger row is skipped
    (it was never merged); a staging post with no subtitles is skipped.
    Returns counts: scanned / with_subtitles / matched / tracks.
    """
    counts = {"scanned": 0, "with_subtitles": 0, "matched": 0, "tracks": 0}
    try:
        staging_conn.row_factory = sqlite3.Row
    except Exception:  # noqa: BLE001 - row factory is a convenience only
        pass
    try:
        posts = staging_conn.execute(
            "SELECT post_canonical_key, raw_meta FROM posts "
            "WHERE raw_meta IS NOT NULL AND raw_meta != '' "
            + ("LIMIT ?" if limit else ""),
            (int(limit),) if limit else (),
        ).fetchall()
    except Exception:  # noqa: BLE001 - no posts table, nothing to harvest
        return counts
    import json as _json
    for post in posts:
        counts["scanned"] += 1
        try:
            blob = _json.loads(post["raw_meta"])
        except (ValueError, TypeError):
            continue
        entries = extract_from_raw_meta(blob)
        if not entries:
            continue
        counts["with_subtitles"] += 1
        try:
            sources = staging_conn.execute(
                "SELECT source_url FROM sources WHERE post_canonical_key = ?",
                (post["post_canonical_key"],),
            ).fetchall()
        except Exception:  # noqa: BLE001 - no sources table for this post
            continue
        tracks = normalize_tracks(entries)
        if not tracks:
            continue
        for source in sources:
            url = source["source_url"] if isinstance(source, sqlite3.Row) else source[0]
            row = live_conn.execute(
                "SELECT id FROM download_sources WHERE source_url = ? LIMIT 1",
                (url,),
            ).fetchone()
            if row is None:
                continue
            link_id = row[0] if not isinstance(row, sqlite3.Row) else row["id"]
            counts["matched"] += 1
            counts["tracks"] += upsert_tracks(
                live_conn, int(link_id), tracks, source="import")
    return counts
