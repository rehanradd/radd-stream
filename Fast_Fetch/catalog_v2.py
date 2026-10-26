#!/usr/bin/env python3
"""
catalog_v2.py — Canonical catalog projection over the per-site ingest ledger.

Layer 0 (posts / releases / download_sources / post_sources) stores what each site
said. This module derives Layer 1: works, seasons, episodes, prints (releases),
links, tracks and entitlements — structured, ranked and rebuildable.

The projection is idempotent: rebuilding it from an unchanged ledger produces the
same rows. Nothing here ever mutates Layer 0.

`apply_evidence()` closes the other half: it folds measured probe samples — the
`cat_link_evidence` journal and/or `link_health.ProbeResult`s handed in by the
operator — onto the owning `cat_links` row as a rolling EWMA blend, so a link's
`state`, timings and `rank_score` can be healed without re-projecting the catalog.
It reads the journal and writes the projection; it never opens a socket.

Standard Library only. Zero external pip packages.
"""

from __future__ import annotations

import json
import os
import re
import dataclasses
import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

#: A full rebuild of the production catalog runs for hours on this one-CPU box and
#: printed nothing until it finished, so an operator could not tell progress from a
#: hang. Setting `RADD_PROJECT_PROGRESS=N` reports each stage and a work counter
#: every N works; unset means silent, which keeps the test output clean.
PROGRESS_EVERY = int(os.environ.get("RADD_PROJECT_PROGRESS") or 0)


def _progress(message: str) -> None:
    if PROGRESS_EVERY:
        print(f"[.] {message}", flush=True)


def _stage(conn: sqlite3.Connection, label: str) -> None:
    """Commit one finalize stage and push the WAL back into the database file.

    Finalize used to run as one transaction, so a full rebuild grew the write-ahead log
    past 3 GB and then every read SQLite performed had to consult that log — the
    roll-ups slowed to a crawl precisely because earlier roll-ups had filled the journal.
    Committing per stage bounds the log, and it means a failure costs one stage instead of
    the whole projection. A checkpoint is advisory: an in-memory or busy database simply
    keeps its journal, which is correct and must not abort the rebuild.
    """
    conn.commit()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    _progress(f"finalize: {label}")

#: v2 -> the link-state vocabulary changed under `link_state.py`: `cat_links.state`
#: now defaults to 'unchecked' (never probed) instead of claiming 'active', and every
#: projected link carries `ledger_link_id` so a verdict can reach it without a rebuild.
SCHEMA_VERSION = 2
MAX_ENUMERATED_EPISODES = 120

#: The four §16.2 version groups, exactly as `api_v2.py` folds them into an ETag.
#: Stored in `cat_projection_meta` under `catalog_rev` / `health` / `offsets_rev`
#: / `entitlements_rev`; `projection_versions()` republishes the health group
#: under its wire name `health_rev` so a consumer never has to know which meta
#: key happened to be written first.
REVISION_KEYS = ("catalog_rev", "health_rev", "offsets_rev", "entitlements_rev")
_HEALTH_META_KEY = "health"

#: §11.2's interim display ordering, now materialized in
#: `cat_entitlements.display_priority` (lower shown first).
DISPLAY_PRIORITY = {"free": 10, "ads": 20, "flatrate": 30, "rental": 40, "purchase": 50}
_ENTITLEMENT_MODELS = tuple(sorted(DISPLAY_PRIORITY))

#: Reports for one pack offset must reach this many votes before a *different*
#: report can be refused as a minority (§4.3: "a single wrong report cannot
#: silently shift everyone's playback"). Below the quorum the newest report still
#: wins so an early misreport stays cheap to correct.
OFFSET_QUORUM = 3

_SERIES_TYPES = {"series", "complete_season", "ongoing_season", "anime", "miniseries"}

_WORK_TYPE_BY_CONTENT = {
    "movie": "movie",
    "series": "series",
    "complete_season": "series",
    "ongoing_season": "series",
    "anime": "anime",
    "documentary": "documentary",
    "sport_event": "sport_event",
    "music_video": "music_video",
}

_DOWNLOAD_ONLY_SERVICES = {
    "mega", "1fichier", "megaup", "mediafire", "katfile", "direct_download",
    "clicknupload", "multiup", "ddownload", "desiupload", "userscloud", "hexload",
    "uptobox", "send", "uploadbuzz", "uploadever", "drop", "uploadhub", "sharer",
    "dl6", "dl9", "vikingfile", "hubfiles", "uptomega", "bbupload", "mobilejsr",
    "9xupload", "ww", "rapidgator", "nitroflare", "turboBit", "filecore",
}
# Player iframes: the app shows them in a WebView, never in ExoPlayer.
_EMBED_SERVICES = {
    "cineverse", "vidrift", "vidout", "vidbolt", "filmu", "gd-mirror", "gdmirror",
    "1xplayer", "iqsmart", "screenscape", "nxstream", "vidzee-mirror", "vidsrc",
    "rpmplay", "doodstream", "streamtape", "vidoza", "videobin", "stream",
    "userscloud_stream", "mixdrop", "updown", "fembed", "mystream", "vididyar",
    "filepress_embed", "openload", "nosvideo", "vshare", "daplay", "vidlink",
    "netu", "okru", "mixdrop", "dood", "ibb", "vidcloud", "vidsrcme", "vid2cloud",
    "razerstream", "razorcloud", "streambd", "bunnystream", "fslspace", "hubcloud_page",
    "jsmwatch", "streamwish", "filemoon", "voxcdn", "swishstream",
}
_BRIDGE_SERVICES = {
    "shortink", "shortlink", "linkvertise", "ezylink", "vlink", "shrinkme", "urlshort",
    "gpdl", "hubcloud_bridge", "linkrit", "conlinks", "rokss", "kutt",
}
# Services whose final_url is a real byte endpoint (no page, no token hop).
_FILE_SERVICES = {
    "google_cdn", "fsl_r2", "pixeldrain", "hubcloud_10g", "fastdl", "dl-fastdlserver-site",
    "vegadrive", "superduperload", "razorshell", "direct_cloud",
}

_HLS_MARKERS = (".m3u8", "mpegurl", "playlist", "/hls/", ".mpd")
_MEDIA_MARKERS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".m3u8")
_FILE_HOST_MARKERS = (
    "cloudflarestorage", "video-downloads.googleusercontent", "r2.dev", "backblazeb2",
    "/api/file/", "/direct/", "/raw/", "/stream/", ".drive.google.com/uc",
)
_ARCHIVE_MARKERS = (".zip", ".rar", ".7z", ".tar", ".gz", "/download?", "?download=")
_BRIDGE_MARKERS = ("/redirect", "linkrit", "?id=", "gpdl.", "/get/", "/token/", "shortur")
_EMBED_HOST_RE = re.compile(r"https?://(?:embed|players?|watches?|streamers?|vd)[0-9]*\.[^/]+")


def _looks_like_file(url: str) -> bool:
    low = (url or "").lower()
    path = low.split("?", 1)[0]
    return path.endswith(_MEDIA_MARKERS) or any(m in low for m in _FILE_HOST_MARKERS)


DDL = """
CREATE TABLE IF NOT EXISTS cat_works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_key TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    work_type TEXT NOT NULL DEFAULT 'unknown',
    is_animated INTEGER NOT NULL DEFAULT 0,
    is_18_plus INTEGER NOT NULL DEFAULT 0,
    synopsis TEXT,
    genres TEXT,
    languages TEXT,
    country TEXT,
    industry TEXT,
    imdb_rating REAL,
    imdb_id TEXT,
    tmdb_id INTEGER,
    tvdb_id TEXT,
    runtime_minutes INTEGER,
    poster_url TEXT,
    backdrop_urls TEXT,
    site_count INTEGER NOT NULL DEFAULT 1,
    release_count INTEGER NOT NULL DEFAULT 0,
    episode_count INTEGER NOT NULL DEFAULT 0,
    max_resolution TEXT,
    best_quality_score INTEGER NOT NULL DEFAULT 0,
    available_stream INTEGER NOT NULL DEFAULT 0,
    available_download INTEGER NOT NULL DEFAULT 0,
    identity_suspect INTEGER NOT NULL DEFAULT 0,
    entitlement_model TEXT NOT NULL DEFAULT 'free',
    first_seen_at REAL,
    updated_at REAL NOT NULL,
    source_rev INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cat_work_aliases (
    work_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    locale TEXT,
    source_site TEXT,
    kind TEXT NOT NULL DEFAULT 'aka',
    PRIMARY KEY (work_id, alias, source_site)
);

CREATE TABLE IF NOT EXISTS cat_work_sites (
    work_id INTEGER NOT NULL,
    source_site TEXT NOT NULL,
    post_id INTEGER NOT NULL,
    page_url TEXT NOT NULL,
    page_title TEXT,
    page_content_type TEXT,
    last_seen_at REAL,
    PRIMARY KEY (work_id, page_url)
);

CREATE TABLE IF NOT EXISTS cat_seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    season_type TEXT NOT NULL DEFAULT 'regular',
    title TEXT,
    episode_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (work_id, number, season_type)
);

CREATE TABLE IF NOT EXISTS cat_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    absolute_number INTEGER,
    title TEXT,
    air_date TEXT,
    runtime_minutes INTEGER,
    best_release_id INTEGER,
    UNIQUE (season_id, number)
);

CREATE TABLE IF NOT EXISTS cat_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    title TEXT,
    UNIQUE (work_id, number)
);

CREATE TABLE IF NOT EXISTS cat_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    season_number INTEGER,
    part_number INTEGER,
    label TEXT,
    source_site TEXT,
    origin_url TEXT,
    coverage_type TEXT NOT NULL DEFAULT 'whole_work',
    episode_range TEXT,
    resolution TEXT,
    quality_label TEXT,
    source_tag TEXT,
    codec TEXT,
    bit_depth INTEGER NOT NULL DEFAULT 0,
    hdr TEXT,
    container TEXT,
    edition TEXT,
    print_version INTEGER NOT NULL DEFAULT 0,
    release_group TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    size_per_episode_bytes INTEGER NOT NULL DEFAULT 0,
    audio_languages TEXT,
    audio_channels TEXT,
    audio_codecs TEXT,
    dual_audio INTEGER NOT NULL DEFAULT 0,
    subtitle_mode TEXT,
    subtitle_languages TEXT,
    watermarked INTEGER NOT NULL DEFAULT 0,
    official_print INTEGER NOT NULL DEFAULT 0,
    quality_score INTEGER NOT NULL DEFAULT 0,
    identity_suspect INTEGER NOT NULL DEFAULT 0,
    link_count INTEGER NOT NULL DEFAULT 0,
    streamable_count INTEGER NOT NULL DEFAULT 0,
    downloadable_count INTEGER NOT NULL DEFAULT 0,
    flags TEXT,
    descriptor_json TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_release_episodes (
    release_id INTEGER NOT NULL,
    episode_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    offset_seconds INTEGER,
    chapter_title TEXT,
    PRIMARY KEY (release_id, episode_id)
);

CREATE TABLE IF NOT EXISTS cat_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    work_id INTEGER NOT NULL,
    ledger_link_id INTEGER,
    source_site TEXT,
    service TEXT,
    source_name TEXT,
    kind TEXT NOT NULL DEFAULT 'unknown',
    url TEXT,
    final_url TEXT,
    resource_id TEXT,
    playability TEXT NOT NULL DEFAULT 'unknown',
    -- 'unchecked' is the honest default: a link nobody has knocked on has no
    -- verdict. 'active' must be EARNED by link_state.propagate(), never inherited
    -- from a scraper's guess (HANDOFF_audit.md defect D7).
    state TEXT NOT NULL DEFAULT 'unchecked',
    resumable INTEGER NOT NULL DEFAULT 0,
    accepts_ranges INTEGER NOT NULL DEFAULT 0,
    cors_open INTEGER NOT NULL DEFAULT 0,
    ephemeral INTEGER NOT NULL DEFAULT 0,
    expires_at REAL,
    protocol TEXT,
    content_type TEXT,
    size_bytes INTEGER,
    latency_ms INTEGER,
    speed_mbps REAL,
    http_status INTEGER,
    last_evidence_at REAL,
    rank_score INTEGER NOT NULL DEFAULT 0,
    tier INTEGER NOT NULL DEFAULT 2,
    UNIQUE (release_id, url)
);

CREATE TABLE IF NOT EXISTS cat_link_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL,
    probed_at REAL NOT NULL,
    ok INTEGER NOT NULL,
    protocol TEXT,
    http_status INTEGER,
    content_type TEXT,
    size_bytes INTEGER,
    latency_ms INTEGER,
    speed_mbps REAL,
    accepts_ranges INTEGER,
    error TEXT
);

-- Ordered by (link_id, probed_at) because `apply_evidence()` folds one link's
-- journal in time order on every run. Both columns are original, so this index
-- is safe inside the script above -- never put an index on a column a later
-- migration adds here (that is what broke site upgrades once: the script would
-- fail on a column that only exists after the ALTER pass has run).
CREATE INDEX IF NOT EXISTS idx_cat_link_evidence_link
    ON cat_link_evidence(link_id, probed_at);

CREATE TABLE IF NOT EXISTS cat_entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER,
    release_id INTEGER,
    model TEXT NOT NULL DEFAULT 'free',
    display_priority INTEGER NOT NULL DEFAULT 10,
    price_minor INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'INR',
    region TEXT,
    geo_allow TEXT,
    geo_deny TEXT,
    valid_from REAL,
    valid_until REAL,
    rental_hours INTEGER,
    ownership TEXT NOT NULL DEFAULT 'permanent',
    requires_account INTEGER NOT NULL DEFAULT 0,
    requires_age_gate INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    UNIQUE (work_id, release_id, model, region)
);

CREATE TABLE IF NOT EXISTS cat_review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    work_id INTEGER,
    release_id INTEGER,
    page_url TEXT,
    detail TEXT,
    raised_at REAL NOT NULL,
    resolved_at REAL
);

CREATE TABLE IF NOT EXISTS cat_projection_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Learned pack offsets live here, NOT in cat_release_episodes, because the
-- projection rewrites that table on every rebuild. Keyed by stable identity.
CREATE TABLE IF NOT EXISTS cat_offsets (
    work_key TEXT NOT NULL,
    season_number INTEGER NOT NULL DEFAULT 0,
    episode_number INTEGER NOT NULL,
    release_label TEXT NOT NULL DEFAULT '',
    offset_seconds INTEGER NOT NULL,
    chapter_title TEXT,
    confirmed_by INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (work_key, season_number, episode_number, release_label)
);

-- Every competing offset ever reported for one (work, season, episode, label), so
-- `record_offset()` can pick a majority instead of trusting the last writer
-- (API_V2.md §4.3). Durable like `cat_offsets`: never in `_reset()`.
CREATE TABLE IF NOT EXISTS cat_offset_votes (
    work_key TEXT NOT NULL,
    season_number INTEGER NOT NULL DEFAULT 0,
    episode_number INTEGER NOT NULL,
    release_label TEXT NOT NULL DEFAULT '',
    offset_seconds INTEGER NOT NULL,
    votes INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL,
    PRIMARY KEY (work_key, season_number, episode_number, release_label, offset_seconds)
);

-- Admin-written entitlement offers, keyed by stable identity (work_key, not the
-- churning `cat_works.id`) exactly like `cat_offsets`, so a paid row survives a
-- rebuild and is re-applied onto `cat_entitlements` by `_finalize()`.
CREATE TABLE IF NOT EXISTS cat_entitlement_rules (
    work_key TEXT NOT NULL,
    release_label TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL,
    price_minor INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'INR',
    region TEXT NOT NULL DEFAULT '',
    geo_allow TEXT,
    geo_deny TEXT,
    valid_from REAL,
    valid_until REAL,
    rental_hours INTEGER,
    ownership TEXT NOT NULL DEFAULT 'permanent',
    requires_account INTEGER NOT NULL DEFAULT 0,
    requires_age_gate INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (work_key, release_label, model, region)
);

-- old `cat_*` row id -> new one for the rebuild that replaced it, by stable key
-- (work_key / natural print tuple / url). Traceability for caches that persisted
-- numeric ids (API_V2.md §3); append-only across revs, never in `_reset()`.
CREATE TABLE IF NOT EXISTS cat_id_map (
    kind TEXT NOT NULL,
    old_id INTEGER NOT NULL,
    new_id INTEGER NOT NULL,
    rev INTEGER NOT NULL,
    PRIMARY KEY (kind, rev, old_id)
);

-- Durable "a human already decided this" record for the review queue, keyed by
-- (kind, work_key, signature) instead of the churning queue row id, so a
-- resolution survives `_reset()` re-minting the same row on every rebuild.
CREATE TABLE IF NOT EXISTS cat_review_resolutions (
    kind TEXT NOT NULL,
    work_key TEXT NOT NULL,
    signature TEXT NOT NULL,
    resolved_at REAL NOT NULL,
    PRIMARY KEY (kind, work_key, signature)
);

CREATE INDEX IF NOT EXISTS idx_cat_works_title ON cat_works(title, year);
CREATE INDEX IF NOT EXISTS idx_cat_works_type ON cat_works(work_type, is_18_plus);
CREATE INDEX IF NOT EXISTS idx_cat_works_browse ON cat_works(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_cat_releases_work ON cat_releases(work_id, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_cat_links_release ON cat_links(release_id, rank_score DESC);
CREATE INDEX IF NOT EXISTS idx_cat_links_state ON cat_links(state, playability);
CREATE INDEX IF NOT EXISTS idx_cat_links_ledger ON cat_links(ledger_link_id);
CREATE INDEX IF NOT EXISTS idx_cat_episodes_work ON cat_episodes(work_id, number);

-- The two join directions the roll-ups and Layer-2 reads actually ask about, which the
-- composite primary keys do not lead with. `cat_release_episodes` is keyed
-- (release_id, episode_id), so "which prints cover this episode" — asked once per episode
-- by `best_release_id` — scanned the whole table every time; `cat_review_queue` had no
-- index at all, so stamping `identity_suspect` scanned it once per print. With 1.3M prints
-- and a million episode links that is not slow, it is endless: a rebuild spent over two
-- hours in `UPDATE cat_releases` and never committed. All four columns are original, so
-- these belong in the script, not in the ALTER pass.
CREATE INDEX IF NOT EXISTS idx_cat_release_episodes_episode
    ON cat_release_episodes(episode_id, release_id);
CREATE INDEX IF NOT EXISTS idx_cat_review_queue_work
    ON cat_review_queue(work_id, resolved_at);
CREATE INDEX IF NOT EXISTS idx_cat_review_queue_release
    ON cat_review_queue(release_id, resolved_at);
"""


#: The playability ladder, as one expression, so the projector, `link_state`'s
#: incremental sync and the API cannot drift into three different scores.
#: A link we have never verified scores 0 on liveness; a link a probe marked dead
#: loses 450 — which is what keeps a dead server off the top of the shelf.
RANK_SCORE_EXPR = """
    CASE
        WHEN playability IN ('stream', 'both') THEN 500
        WHEN playability = 'download' THEN 250
        WHEN playability = 'resolve_required' THEN 120
        WHEN playability = 'webview' THEN 80
        ELSE 0 END
        + CASE WHEN tier = 1 THEN 150 ELSE 0 END
        + CASE WHEN ephemeral = 0 THEN 100 ELSE 0 END
        + CASE WHEN accepts_ranges = 1 THEN 50 ELSE 0 END
        + CASE WHEN state = 'active' THEN 100
               WHEN state IN ('unknown', 'unchecked') THEN 0
               ELSE -450 END
"""


# ── Identity ─────────────────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    text = (title or "").casefold()
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def work_type_for(content_type: str, is_animated: int, title: str = "") -> str:
    ctype = (content_type or "").strip().casefold()
    base = _WORK_TYPE_BY_CONTENT.get(ctype, "unknown")
    if is_animated or ctype == "anime":
        return "anime" if base in ("series", "unknown") else base
    return base


def work_family(work_type: str) -> str:
    """Movies and series never collapse into each other, whatever the title says."""
    return "series" if work_type in _SERIES_TYPES else "movie"


def work_key_for(title: str, year, work_type: str, imdb_id: str = "", tmdb_id=None) -> str:
    if imdb_id:
        return f"imdb:{imdb_id}"
    if tmdb_id not in (None, "", 0):
        return f"tmdb:{tmdb_id}"
    norm = normalize_title(title) or "unknown"
    return f"{work_family(work_type)}:{norm}:{year or 'ny'}"


# ── Link classification ──────────────────────────────────────────────────────

def classify_link(service: str, source_url: str, final_url: str,
                  playback_type: str, is_temporary: int) -> tuple[str, str]:
    """Returns (kind, playability) from what the URL actually is.

    Only a file or a manifest may be called 'stream'. Everything else keeps its true
    kind (page, bridge, embed) so the API can never promise the player a URL it cannot
    open. `cloud_page` + `resolve_required` means "run the JIT resolver first" — it is
    the honest default for a hoster page, not a failure.
    """
    svc = (service or "").strip().casefold()
    target = final_url or source_url or ""
    lowered = target.lower()

    if not target or lowered.startswith(("magnet:", "torrent:")) or lowered.endswith(".torrent"):
        return ("download_only", "download") if lowered else ("dead_end", "none")
    path = lowered.split("?", 1)[0].split("#", 1)[0]
    last_seg = path.rsplit("/", 1)[-1]
    if any(marker in lowered for marker in _HLS_MARKERS):
        return "hls_manifest", "stream"
    if _looks_like_file(lowered):
        if svc in _EMBED_SERVICES:
            return "embed", "webview"
        return ("cdn_direct", "both" if (playback_type or "").lower() == "download" else "stream")
    if path.endswith(_ARCHIVE_MARKERS) or svc in _DOWNLOAD_ONLY_SERVICES:
        return "download_only", "download"
    if svc in _BRIDGE_SERVICES or any(marker in lowered for marker in _BRIDGE_MARKERS):
        return "bridge", "none"
    if (svc in _EMBED_SERVICES or "embed" in svc or "embed" in last_seg
            or path.endswith("/e") or "/e/" in path or _EMBED_HOST_RE.search(lowered)):
        return "embed", "webview"
    if (playback_type or "").lower() == "download":
        return "cloud_page", "download"
    if lowered.endswith((".html", ".php", "/drive/")) or "drive" in lowered:
        return "cloud_page", "resolve_required" if is_temporary else "download"
    return "cloud_page", "resolve_required"


# ── Projection ───────────────────────────────────────────────────────────────

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    _migrate_link_state(conn)
    _migrate_evidence_journal(conn)
    _migrate_projection_columns(conn)
    conn.execute(
        "INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def _migrate_projection_columns(conn: sqlite3.Connection) -> None:
    """Add the v2.1 columns to tables built by an older projection.

    `identity_suspect` (per-print review marker) and `display_priority` (§11.2's
    stored ordering) are deliberately NOT indexed inside the DDL script — an index
    over a migrated column breaks every database built before this ALTER existed.
    """
    if _has_table(conn, "cat_releases") and "identity_suspect" not in _columns(conn, "cat_releases"):
        conn.execute("ALTER TABLE cat_releases ADD COLUMN identity_suspect INTEGER NOT NULL DEFAULT 0")
    if _has_table(conn, "cat_entitlements") and "display_priority" not in _columns(conn, "cat_entitlements"):
        conn.execute("ALTER TABLE cat_entitlements ADD COLUMN display_priority"
                     " INTEGER NOT NULL DEFAULT 10")


# ── Version groups (§16.2) ───────────────────────────────────────────────────

def _as_rev(value) -> int:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return int(number) if number > 0 else 0


def _read_rev(conn, key: str) -> int:
    if not _has_table(conn, "cat_projection_meta"):
        return 0
    row = conn.execute("SELECT value FROM cat_projection_meta WHERE key = ?", (key,)).fetchone()
    return _as_rev(row[0] if row else None)


def _bump_rev(conn, key: str) -> int:
    """Monotonic +1 on one `cat_projection_meta` revision key."""
    nxt = _read_rev(conn, key) + 1
    conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES (?, ?)",
                 (key, str(nxt)))
    return nxt


def projection_versions(conn) -> dict:
    """The four §16.2 version groups as one dict — all keys always present, `0`
    when the database has never carried one. This is the ETag/`/sync` read
    contract for Layer 2; nothing here mutates the database.

    The health group is stored under the original `health` meta key (advanced by
    `apply_evidence()`) and republished as `health_rev` to match the wire name.
    """
    out = {key: 0 for key in REVISION_KEYS}
    if not _has_table(conn, "cat_projection_meta"):
        return out
    stored = {str(row[0]): row[1] for row in
              conn.execute("SELECT key, value FROM cat_projection_meta")}
    out["catalog_rev"] = _as_rev(stored.get("catalog_rev"))
    out["offsets_rev"] = _as_rev(stored.get("offsets_rev"))
    out["entitlements_rev"] = _as_rev(stored.get("entitlements_rev"))
    out["health_rev"] = _as_rev(stored.get("health_rev") or stored.get(_HEALTH_META_KEY))
    return out


def _migrate_link_state(conn: sqlite3.Connection) -> None:
    """Add the link-state columns to a `cat_links` table built by an older version.

    `CREATE TABLE IF NOT EXISTS` cannot change an existing table, and a v1 projection
    (catalog_full.db) has no `ledger_link_id` and still defaults `state` to 'active'.
    The column is added here; the *default* stays a v1 artifact, because a rebuild
    rewrites every row through `_link_state_of()` anyway — and per the zero-data-loss
    rule we never recreate a 3.2 GB table to fix a default nobody reads."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cat_links)")}
    if not existing:
        return
    if "ledger_link_id" not in existing:
        conn.execute("ALTER TABLE cat_links ADD COLUMN ledger_link_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cat_links_ledger"
                 " ON cat_links(ledger_link_id)")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set:
    if not _has_table(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_evidence_journal(conn: sqlite3.Connection) -> None:
    """Give ``cat_link_evidence`` the URL each sample was taken against.

    The journal is keyed by ``cat_links.id``, and ``project(reset=True)`` hands
    out fresh ids — so a row written before a rebuild can silently point at a
    different link afterwards. Storing the probed URL makes the association
    re-checkable (and self-healing) without touching the sample itself. Added
    with its own ``ALTER`` statement, deliberately NOT indexed inside the DDL
    script: an index on a migrated column would fail on any database built
    before this column existed. Rows written by older code keep ``url`` NULL and
    are trusted by ``link_id`` alone, exactly as before.
    """
    if not _has_table(conn, "cat_link_evidence"):
        return
    if "url" not in _columns(conn, "cat_link_evidence"):
        conn.execute("ALTER TABLE cat_link_evidence ADD COLUMN url TEXT")


def _reset(conn: sqlite3.Connection) -> None:
    for table in ("cat_works", "cat_work_aliases", "cat_work_sites", "cat_seasons",
                  "cat_episodes", "cat_parts", "cat_releases", "cat_release_episodes",
                  "cat_links", "cat_entitlements", "cat_review_queue"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM sqlite_sequence WHERE name LIKE 'cat_%'")


def _json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return [text]
    return parsed if isinstance(parsed, list) else [parsed]


def _post_column(post, *names, default=None):
    keys = post.keys()
    for name in names:
        if name in keys and post[name] not in (None, ""):
            return post[name]
    return default


class _WorkAccumulator:
    """One work across every site page that claims it."""

    __slots__ = ("key", "posts", "best", "aliases", "suspect")

    def __init__(self, key: str):
        self.key = key
        self.posts: list[sqlite3.Row] = []
        self.best: dict = {}
        self.aliases: set[tuple[str, str, str]] = set()
        self.suspect = 0

    def absorb(self, post: sqlite3.Row) -> None:
        self.posts.append(post)
        pairs = {
            "synopsis": _post_column(post, "synopsis"),
            "genres": _post_column(post, "genres"),
            "imdb_rating": _post_column(post, "imdb_rating"),
            "poster_url": _post_column(post, "poster_url"),
            "backdrop_urls": _post_column(post, "backdrop_urls"),
            "tmdb_id": _post_column(post, "tmdb_id"),
            "imdb_id": _post_column(post, "imdb_id"),
            "country": _post_column(post, "country"),
            "industry": _post_column(post, "industry"),
            "language": _post_column(post, "language"),
        }
        for field, value in pairs.items():
            if value not in (None, "") and self.best.get(field) in (None, ""):
                self.best[field] = value
        title = _post_column(post, "title")
        site = _post_column(post, "source_site", default="unknown")
        if title:
            self.aliases.add((str(title), site, "aka"))


def _parse_range(text: str) -> tuple[int, int]:
    m = re.search(r"(\d+)\s*-\s*(\d+)", text or "")
    if not m:
        return 0, 0
    lo, hi = int(m.group(1)), int(m.group(2))
    if hi < lo or hi - lo > 500:
        return lo, lo
    return lo, hi


def _hint_int(value) -> int:
    """Scrapers write 'S01', 'Season 2', '1', 'Batch', '' into the same column.

    Take the first integer that appears; anything without one is 0 (unknown),
    never a crash — a dirty page must not abort a whole projection run.
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else 0


# ── Facts recoverable from label/page text (§4.2 unpopulated columns) ────────
# Every rule below extracts only what the ledger text literally says; anything a
# label does not name stays NULL. Inventing an air date or an episode count is
# worse than the honest 🛠 marker.

#: Tokens that end an episode-title tail: everything after one of these is
#: presentation metadata, not the episode's name.
_EPISODE_TAIL_STOP_RE = re.compile(
    r"\b(?:\d{3,4}[pi]\b|\d{3,4}p\b|4k|uhd|hd|sd|x[\s.-]*26[45]|h[\s.-]*26[45]|hevc|avc|av1"
    r"|xvid|mpeg ?2|10\s*bit|8\s*bit|hdr ?\d*\+?|dolby ?vision|dovi|esubs?\b|hsubs?\b|subs?\b"
    r"|web[\s.-]?(?:dl|rip)|bluray|bdrip|dvdrip|hd ?tv|telesync|hdtc|telecine|cam(?:rip)?"
    r"|dual|multi[\s-]?audio|audio|hindi|tamil|telugu|english|tollywood|bollywood|hollywood"
    r"|subbed|dubbed|unrated|extended|remastered|restored|director'?s ?cut|imax|uncut"
    r"|complete|batch|pack|full|movie|dvd|ddp?\d*|ac[\s.-]?3|aac|opus|flac|atmos|truehd"
    r"|dts[\s.-]?hd|5\.1|7\.1|2\.0|stereo|mkv|mp4|m4v|avi|ts|fps|ntsc|pal|[vV]\d{1,3})\b|"
    r"\b\d+(?:\.\d+)?\s*(?:gb|mb|tb)\b|\b\d{2,4}[-/.]\d{2}(?:[-/.]\d{2})?\b",
    re.IGNORECASE)
_EPISODE_MARK_RE = re.compile(
    r"\bs\d{1,2}\s*e\d{1,4}\b|\be(?:p(?:isod(?:e)?)?)?\s*\.?\s*\d{1,4}\b(?![\s.-]*(?:\d))",
    re.IGNORECASE)
_AIR_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RUNTIME_RE = re.compile(r"\b(\d{2,3})\s*(?:min|mins|minutes)\b", re.IGNORECASE)
_SEASON_TITLE_RE = re.compile(
    r"\bseason\s*\d{1,3}\s*[:\-–—]\s*([A-Za-z][A-Za-z0-9' ]{2,60})", re.IGNORECASE)
_SPECIAL_RE = re.compile(r"\bs00\b|\bs0*0\b|(?<![a-z])specials?(?:\s*[:\-]|$)|\bspecials\b",
                         re.IGNORECASE)
_PACK_EP_COUNT_RE = re.compile(r"\b(\d{1,3})\s*(?:eps?\b|episodes?\b|\be\b)", re.IGNORECASE)
_PACK_EP_RANGE_RE = re.compile(
    r"\b(?:ep(?:s(?:odes?)?)?|episode)\s*[\(\[\{]?\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*[\)\]\}]?",
    re.IGNORECASE)
_PART_RE = re.compile(r"\b(?:part|chapter|disc|disk)\s*\.?\s*(\d{1,2})\b", re.IGNORECASE)


def _episode_tail_facts(label: str) -> tuple:
    """(episode_title, air_date, runtime_minutes) recovered from one print label.

    Only the text AFTER an SxxExx/E-number marker is considered; it is cut at the
    first presentation token and refused when it still carries digits (a stray
    "1080" is a resolution, not a name). All three return values are NULL when the
    label does not literally name them.
    """
    text = (label or "").replace("_", " ")
    air_m = _AIR_DATE_RE.search(text)
    air_date = air_m.group(0) if air_m else None
    if air_date and not (1 <= int(air_date[5:7]) <= 12 and 1 <= int(air_date[8:10]) <= 31):
        air_date = None
    rt_m = _RUNTIME_RE.search(text)
    runtime = int(rt_m.group(1)) if rt_m and 5 <= int(rt_m.group(1)) <= 600 else None
    title = None
    mark = _EPISODE_MARK_RE.search(text)
    if mark:
        tail = text[mark.end():]
        stop = _EPISODE_TAIL_STOP_RE.search(tail)
        if stop:
            tail = tail[:stop.start()]
        words = tail.strip(" -:.·|,()[]").split()
        if 1 <= len(words) <= 8 and not any(re.search(r"\d", w) for w in words) \
                and any(c.isalpha() for c in "".join(words)):
            title = " ".join(words)[:80] or None
    return title, air_date, runtime


def _season_title_from_label(label: str) -> str | None:
    """`Season 2: Exams` → 'Exams'; a label that only numbers the season stays NULL."""
    m = _SEASON_TITLE_RE.search(label or "")
    if not m:
        return None
    words = m.group(1).strip(" -:.·|,").split()
    stop = _EPISODE_TAIL_STOP_RE.search(" ".join(words))
    if stop:
        words = words[:len(" ".join(words)[:stop.start()].split())]
    text = " ".join(words).strip(" -:.·|,")
    return text[:80] or None


def _looks_special(season_text: str, label: str) -> bool:
    """S00 / 'Specials' naming in the season column or the label — specials are a
    real season type the ledger carries, not an unresolved season number."""
    blob = f"{season_text or ''} {label or ''}"
    return bool(_SPECIAL_RE.search(blob))


def _pack_span(label: str) -> tuple[int, int] | None:
    """(lo, hi) an explicit `EP(01-12)` range or `12EP`/`12 Episodes` count names on
    a pack label; None when the label says nothing about how many episodes it holds.
    """
    text = label or ""
    m = _PACK_EP_RANGE_RE.search(text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= hi and hi - lo + 1 <= MAX_ENUMERATED_EPISODES:
            return lo, hi
    m = _PACK_EP_COUNT_RE.search(text)
    if m:
        count = int(m.group(1))
        if 1 <= count <= MAX_ENUMERATED_EPISODES:
            return 1, count
    return None


def _part_number(label: str) -> int:
    """Digit a `Part n` / `Chapter n` / `Disc n` marker names, or 0."""
    m = _PART_RE.search(label or "")
    return int(m.group(1)) if m else 0


def _release_coverage(desc: dict, season_hint, work_family: str) -> tuple[str, int, int]:
    """(coverage_type, season_number, episode_count_covered) for one print."""
    scope = desc.get("scope") or "unknown"
    season = int(desc.get("season") or 0) or _hint_int(season_hint)
    episode = int(desc.get("episode") or 0)
    lo, hi = _parse_range(desc.get("episode_range") or "")

    if work_family == "movie" and not episode and not season:
        return "whole_work", 0, 0
    if episode and not lo:
        return "single_episode", season, 1
    if lo and hi > lo:
        return "episode_range", season, hi - lo + 1
    if desc.get("is_pack") or scope in ("season_pack", "miniseries", "multi_season"):
        return "season_pack", season, 0
    if scope == "episode":
        return "single_episode", season, episode or 1
    if season and not episode:
        return "season_pack", season, 0
    return "whole_work", season, 0


def project(conn: sqlite3.Connection, *, rev: int | None = None, reset: bool = True,
             verbose: bool = True) -> dict:
    """Rebuild the canonical catalog from the ingest ledger in `conn`.

    Idempotent: the same ledger produces the same rows. Returns counters so a caller
    (and the tests) can prove nothing was dropped.
    """
    import release_descriptor

    started = time.time()
    ensure_schema(conn)
    # A rebuild re-allocates every cat_* id; snapshot the stable keys first so the
    # churn can be recorded in cat_id_map afterwards (§3 id stability).
    before = _stable_id_lists(conn) if reset else None
    catalog_rev = _bump_rev(conn, "catalog_rev")
    if reset:
        _reset(conn)

    ledger = conn.execute(
        """
        SELECT p.id AS post_id, p.*
        FROM posts p
        ORDER BY p.id
        """
    )
    works: dict[str, _WorkAccumulator] = {}
    now = time.time()
    post_count = 0
    for row in ledger:
        post_count += 1
        clean_title = _post_column(row, "clean_title", default="") or _post_column(
            row, "title", default="") or "Unknown"
        year = _post_column(row, "year")
        wtype = work_type_for(
            _post_column(row, "content_type", default="movie"),
            int(_post_column(row, "is_animated", default=0) or 0),
            clean_title,
        )
        key = work_key_for(
            clean_title, year, wtype,
            _post_column(row, "imdb_id", default=""), _post_column(row, "tmdb_id"),
        )
        works.setdefault(key, _WorkAccumulator(key)).absorb(row)

    _progress(f"ledger read: {post_count} posts -> {len(works)} works "
              f"({time.time() - started:.0f}s)")

    work_ids: dict[str, int] = {}
    for key, acc in works.items():
        head = acc.posts[0]
        title = _post_column(head, "clean_title", default="") or _post_column(head, "title", "Unknown")
        # Rolled up over every page in the work, exactly like `is_18_plus`: the head
        # post is the richest record, not a statement about the medium, and a show
        # carried by an anime-only page alongside a general one is animation either
        # way. Reading the head alone made both the `anime` work type and the Anime
        # facet depend on which site won the merge.
        is_animated = 1 if any(int(_post_column(p, "is_animated", default=0) or 0)
                               for p in acc.posts) else 0
        wtype = work_type_for(
            _post_column(head, "content_type", default="movie"),
            is_animated,
            title,
        )
        year = _post_column(head, "year")
        rating = acc.best.get("imdb_rating")
        try:
            rating = float(rating) if rating not in (None, "") else None
        except (TypeError, ValueError):
            rating = None
        cur = conn.execute(
            """
            INSERT INTO cat_works (work_key, title, original_title, year, work_type,
                is_animated, is_18_plus, synopsis, genres, languages, country, industry,
                imdb_rating, imdb_id, tmdb_id, poster_url, backdrop_urls, site_count,
                entitlement_model, first_seen_at, updated_at, source_rev)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'free', ?, ?, ?)
            """,
            (
                key, title, _post_column(head, "title", default=title), year, wtype,
                is_animated,
                1 if any(int(_post_column(p, "is_18_plus", default=0) or 0) for p in acc.posts) else 0,
                acc.best.get("synopsis"), acc.best.get("genres"),
                _post_column(head, "language", default=""), _post_column(head, "country", default="Unknown"),
                _post_column(head, "industry", default="Unknown"), rating,
                acc.best.get("imdb_id"), acc.best.get("tmdb_id"),
                acc.best.get("poster_url"), acc.best.get("backdrop_urls"),
                len({str(_post_column(p, "source_site", default="unknown")) for p in acc.posts}),
                min((p["created_at"] for p in acc.posts if p["created_at"]), default=now),
                now, rev or 0,
            ),
        )
        work_id = cur.lastrowid
        work_ids[key] = work_id
        for alias, site, kind in acc.aliases:
            conn.execute(
                "INSERT OR IGNORE INTO cat_work_aliases (work_id, alias, locale, source_site, kind)"
                " VALUES (?, ?, NULL, ?, ?)",
                (work_id, alias, site, kind),
            )

    conn.commit()
    _progress(f"works written: {len(work_ids)} ({time.time() - started:.0f}s)")
    counters = _project_pages(conn, works, work_ids, release_descriptor, now)
    _progress(f"pages/prints done: {counters['releases']} prints, {counters['links']} links "
              f"({time.time() - started:.0f}s)")
    _finalize(conn, works, work_ids, now, counters)
    _progress(f"finalized ({time.time() - started:.0f}s)")

    mapped = _record_id_map(conn, before, catalog_rev) if before else 0
    summary = {
        "works": len(work_ids),
        "releases": counters["releases"],
        "links": counters["links"],
        "episodes": counters["episodes"],
        "seasons": counters["seasons"],
        "parts": counters["parts"],
        "posts": post_count,
        "identity_suspect": counters["suspect"],
        "release_dups": counters["release_dups"],
        "unattributed_links": counters["unattributed"],
        "catalog_rev": catalog_rev,
        "seconds": round(time.time() - started, 2),
    }
    summary["id_mapped"] = mapped
    conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('id_map_rows', ?)",
                 (str(mapped),))
    for key, value in summary.items():
        conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES (?, ?)",
                     (key, str(value)))
    conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('projected_at', ?)",
                 (str(now),))
    # How much of the projected catalog has actually been knocked on. Recorded every
    # rebuild so ops can see the honest coverage number in the same table that says
    # when the projection was made — a 100%-active catalog with coverage 0.0 is the
    # defect this exists to expose (HANDOFF_audit.md D7).
    by_state = {str(row[0]): int(row[1]) for row in
                conn.execute("SELECT state, COUNT(*) FROM cat_links GROUP BY state")}
    conn.execute(
        "INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('links_by_state', ?)",
        (json.dumps(by_state, sort_keys=True),))
    conn.execute(
        "INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('link_coverage', ?)",
        (str(round(by_state.get("active", 0) / sum(by_state.values()), 4)
             if by_state else 0.0),))
    summary["links_by_state"] = by_state
    conn.commit()
    if verbose:
        print(f"[✓] catalog v2 projected: {summary}", flush=True)
    return summary


def _project_pages(conn, works, work_ids, release_descriptor, now) -> dict:
    counters = {"releases": 0, "links": 0, "episodes": 0, "seasons": 0, "suspect": 0,
                "unattributed": 0, "release_dups": 0, "parts": 0}
    episode_index: dict[tuple[int, int, int], int] = {}
    # (work_id, natural print key) -> release_id, so the same print mirrored by a
    # scraper that re-emitted a page collapses onto one row instead of two siblings.
    print_index: dict[tuple[int, tuple], int] = {}

    seen = 0
    for key, acc in works.items():
        seen += 1
        if PROGRESS_EVERY and seen % PROGRESS_EVERY == 0:
            _progress(f"projects {seen}/{len(works)} works: {counters['releases']} prints, "
                      f"{counters['links']} links")
        work_id = work_ids[key]
        family = work_family(str(conn.execute(
            "SELECT work_type FROM cat_works WHERE id = ?", (work_id,)).fetchone()[0]))
        pages = {}
        for page in acc.posts:
            if page["url"]:
                pages[str(page["url"])] = (
                    _post_column(page, "source_site", default="unknown"), int(page["post_id"]),
                    _post_column(page, "title", default=""), _post_column(page, "content_type"))
        for post_id in {int(p["post_id"]) for p in acc.posts}:
            for extra in conn.execute(
                "SELECT source_site, url, source_title FROM post_sources WHERE post_id = ?",
                (post_id,)).fetchall():
                if extra["url"] and str(extra["url"]) not in pages:
                    pages[str(extra["url"])] = (
                        extra["source_site"] or "unknown", post_id, extra["source_title"] or "", None)
        for page_url, (page_site, page_post, page_title, page_ctype) in sorted(pages.items()):
            conn.execute(
                """
                INSERT OR IGNORE INTO cat_work_sites
                    (work_id, source_site, post_id, page_url, page_title, page_content_type, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (work_id, page_site, page_post, page_url, page_title, page_ctype, now),
            )

        for page in acc.posts:
            page_url = page["url"] or ""
            page_site = _post_column(page, "source_site", default="") or ""
            for rel in conn.execute(
                "SELECT * FROM releases WHERE post_id = ? ORDER BY id", (page["post_id"],)
            ).fetchall():
                desc = release_descriptor.describe(
                    rel["release_title"] or "", rel["quality"] or "", rel["codec"] or "",
                    rel["size"] or "", rel["season"] or "", rel["episode"] or "",
                    rel["languages"] or "", page_site,
                )
                coverage, season_number, ep_count = _release_coverage(desc, rel["season"], family)
                rel_site = rel["source_site"] or page_site
                origin_url = (rel["origin_url"] if "origin_url" in rel.keys() else None) or page_url
                pkey = (
                    work_id, str(rel["release_title"] or "").strip().casefold(), rel_site,
                    origin_url, coverage, season_number, desc.get("resolution"),
                    desc.get("source_tag"), desc.get("codec"),
                    int(desc.get("size_bytes") or 0), desc.get("episode_range") or "",
                )
                release_id = print_index.get(pkey)
                if release_id is not None:
                    # Same print re-emitted by a second scraper pass: keep one row,
                    # its links are still attached below.
                    counters["release_dups"] += 1
                else:
                    raw_season = str(rel["season"] or "")
                    is_special = (season_number == 0 and family == "series"
                                  and _looks_special(raw_season, rel["release_title"] or ""))
                    suspect = 1 if (season_number == 0 and family == "series"
                                    and not is_special) else 0
                    if suspect:
                        counters["suspect"] += 1
                    cur = conn.execute(
                        """
                        INSERT INTO cat_releases (work_id, season_number, label, source_site, origin_url,
                            coverage_type, episode_range, resolution, quality_label, source_tag, codec,
                            bit_depth, hdr, container, edition, print_version, release_group, size_bytes,
                            size_per_episode_bytes, audio_languages, audio_channels, audio_codecs,
                            dual_audio, subtitle_mode, subtitle_languages, watermarked, official_print,
                            quality_score, identity_suspect, flags, descriptor_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            work_id, season_number or None, rel["release_title"],
                            rel_site, origin_url,
                            coverage, desc.get("episode_range") or "", desc.get("resolution") or "unknown",
                            desc.get("quality_label") or "", desc.get("source_tag") or "unknown",
                            desc.get("codec") or "unknown", int(desc.get("bit_depth") or 0),
                            json.dumps(desc.get("hdr") or []), desc.get("container") or "unknown",
                            desc.get("edition") or "unknown", int(desc.get("version") or 0),
                            str(desc.get("release_group") or ""),
                            int(desc.get("size_bytes") or 0),
                            int(desc.get("size_per_episode_bytes") or 0),
                            json.dumps((desc.get("audio") or {}).get("languages") or []),
                            (desc.get("audio") or {}).get("channel_layout") or "unknown",
                            json.dumps((desc.get("audio") or {}).get("codecs") or []),
                            1 if (desc.get("audio") or {}).get("dual_audio") else 0,
                            "hardcoded" if (desc.get("subtitles") or {}).get("hardcoded")
                            else ("external" if (desc.get("subtitles") or {}).get("available") else "none"),
                            json.dumps((desc.get("subtitles") or {}).get("langs") or []),
                            1 if desc.get("watermarked") else 0, 1 if desc.get("official_print") else 0,
                            int(desc.get("quality_score") or 0), suspect, json.dumps(_flags_of(desc)),
                            json.dumps(desc, default=str), now,
                        ),
                    )
                    release_id = cur.lastrowid
                    if suspect:
                        _raise_review(
                            conn, kind="season_unresolved", work_id=work_id,
                            work_key=key, release_id=release_id, page_url=page_url,
                            now=now, detail={"label": rel["release_title"],
                                             "season": raw_season})
                    print_index[pkey] = release_id
                    counters["releases"] += 1

                    season_id = _season_id(conn, work_id, season_number, counters,
                                           season_type="special" if is_special else "regular")
                    ep_facts = (_episode_tail_facts(str(rel["release_title"] or ""))
                                if coverage == "single_episode" else (None, None, None))
                    for ep_number in _covered_episodes(desc, coverage, ep_count):
                        ekey = (work_id, season_number, ep_number)
                        episode_id = episode_index.get(ekey)
                        if episode_id is None:
                            ecur = conn.execute(
                                "INSERT INTO cat_episodes (work_id, season_id, number,"
                                " title, air_date, runtime_minutes) VALUES (?, ?, ?, ?, ?, ?)",
                                (work_id, season_id, ep_number) + ep_facts,
                            )
                            episode_id = ecur.lastrowid
                            episode_index[ekey] = episode_id
                            counters["episodes"] += 1
                        elif any(ep_facts):
                            conn.execute(
                                "UPDATE cat_episodes SET title = COALESCE(title, ?),"
                                " air_date = COALESCE(air_date, ?),"
                                " runtime_minutes = COALESCE(runtime_minutes, ?) WHERE id = ?",
                                ep_facts + (episode_id,),
                            )
                        conn.execute(
                            "INSERT OR IGNORE INTO cat_release_episodes"
                            " (release_id, episode_id, ordinal) VALUES (?, ?, ?)",
                            (release_id, episode_id, ep_number),
                        )

                for src in conn.execute(
                    "SELECT * FROM download_sources WHERE release_id = ? ORDER BY id", (rel["id"],)
                ).fetchall():
                    kind, playability = classify_link(
                        src["service"], src["source_url"], src["final_url"],
                        _pick_col(src, "playback_type", "url"), int(src["is_temporary"] or 0),
                    )
                    if kind == "dead_end":
                        counters["unattributed"] += 1
                    state = _link_state_of(src)
                    measured = _measured_evidence(src)
                    counters["link_state_" + state] = counters.get("link_state_" + state, 0) + 1
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO cat_links (release_id, work_id, ledger_link_id,
                            source_site, service,
                            source_name, kind, url, final_url, resource_id, playability, state,
                            resumable, accepts_ranges, cors_open,
                            ephemeral, protocol, content_type, size_bytes, latency_ms, speed_mbps,
                            http_status, last_evidence_at, tier)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (release_id, work_id, src["id"], rel_site,
                         src["service"], src["source_name"], kind, src["source_url"], src["final_url"],
                         src["resource_id"], playability, state,
                         measured["resumable"], measured["accepts_ranges"], measured["cors_open"],
                         int(src["is_temporary"] or 0), _protocol_of(kind, playability),
                         measured["content_type"],
                         _pick_col(src, "file_size_bytes", None),
                         measured["latency_ms"], measured["speed_mbps"],
                         _pick_col(src, "http_status", None), measured["checked_at"],
                         1 if _is_tier1(src["service"]) else 2),
                    )
                    counters["links"] += 1

    conn.commit()
    counters["_episode_index"] = episode_index
    return counters


def _flags_of(desc: dict) -> list[str]:
    flags = []
    if desc.get("watermarked"):
        flags.append("watermarked")
    if not desc.get("official_print"):
        flags.append("unofficial")
    if desc.get("is_pack"):
        flags.append("pack")
    if (desc.get("edition") or "") in ("director_cut", "extended", "unrated", "remastered", "restored"):
        flags.append("alternate_edition")
    return flags


def _season_id(conn, work_id: int, season_number: int, counters: dict,
               season_type: str = "regular") -> int:
    number = int(season_number or 0)
    existing = conn.execute(
        "SELECT id FROM cat_seasons WHERE work_id = ? AND number = ? AND season_type = ?",
        (work_id, number, season_type),
    ).fetchone()
    if existing:
        return existing[0]
    cur = conn.execute(
        "INSERT INTO cat_seasons (work_id, number, season_type) VALUES (?, ?, ?)",
        (work_id, number, season_type),
    )
    counters["seasons"] += 1
    return cur.lastrowid


def _covered_episodes(desc: dict, coverage: str, ep_count: int) -> list[int]:
    """Concrete episodes one print stands for, capped so a 1000-episode batch
    label cannot fabricate a thousand catalog rows. Longer spans stay described by
    `coverage_type` + `episode_range` and are resolved when played."""
    if coverage == "whole_work":
        return []
    single = int(desc.get("episode") or 0)
    if coverage == "single_episode":
        return [single] if single else []
    lo, hi = _parse_range(desc.get("episode_range") or "")
    if coverage == "episode_range" and lo:
        if hi - lo + 1 > MAX_ENUMERATED_EPISODES:
            return []
        return list(range(lo, hi + 1)) if hi >= lo else [lo]
    if coverage == "season_pack":
        return []
    return [single] if single else []


def _pick_col(row, name, default):
    return row[name] if name in row.keys() and row[name] is not None else default


def _link_state_of(src) -> str:
    """What the ledger's `status` *means*, in projection vocabulary.

    The authority is `link_state`: a scraper wrote 'active' into every row at ingest
    and nothing verified it (HANDOFF_audit.md D7), so an 'active' with no probe
    evidence behind it projects as 'unchecked' — which scores 0 on liveness here and
    is a legal value on the v2 wire (api_v2.py §filters). A row that was measured, or
    explicitly marked dead/expired by a scraper or the healer, keeps its state.
    """
    status = str(_pick_col(src, "status", "") or "").strip().lower()
    if status not in ("", "active"):
        return status
    verified = any(_pick_col(src, name, None) not in (None, "", 0)
                   for name in ("checked_at", "last_checked_at", "http_status"))
    if status == "active" and verified:
        return "active"
    return "unchecked"


def _measured_evidence(src) -> dict:
    """The probe facts a ledger row carries, shaped for `cat_links`.

    Everything defaults to "unknown" (0/None) so an unprobed link cannot win a rank
    on a field nobody filled in."""
    checked_at = _pick_col(src, "checked_at", None)
    if checked_at in (None, ""):
        stamp = _pick_col(src, "last_checked_at", None)
        checked_at = None
        if stamp:
            try:
                import datetime as _dt
                parsed = _dt.datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
                checked_at = parsed.replace(tzinfo=_dt.timezone.utc).timestamp()
            except (ValueError, TypeError):
                checked_at = None
    ranges = 1 if int(_pick_col(src, "is_resumable", 0) or 0) else 0
    return {
        "resumable": ranges,
        "accepts_ranges": ranges,
        "cors_open": int(_pick_col(src, "cors_open", 0) or 0),
        "content_type": _pick_col(src, "mime_type", None),
        "speed_mbps": _pick_col(src, "speed_mbps", None),
        "latency_ms": _pick_col(src, "latency_ms", None),
        "checked_at": checked_at,
    }


def _protocol_of(kind: str, playability: str) -> str:
    if kind == "hls_manifest":
        return "hls"
    if playability in ("stream", "download", "both"):
        return "progressive"
    if kind in ("embed", "cloud_page", "bridge"):
        return "html"
    return "unknown"


def _is_tier1(service) -> bool:
    return str(service or "").strip().casefold() in {
        "pixeldrain", "vegadrive", "hubcloud_10g", "fsl_r2", "google_cdn", "fastdl", "hubcdn",
    }


# ── Review queue (S13 / A9) ──────────────────────────────────────────────────

def _raise_review(conn, *, kind: str, work_id, work_key: str, detail: dict,
                  release_id=None, page_url=None, now: float):
    """Insert one queue row, honouring a durable admin resolution.

    Resolutions live in `cat_review_resolutions` keyed by (kind, work_key,
    detail-signature) because `_reset()` re-mints the queue — and the numeric
    ids behind it — on every rebuild. A resolved rule therefore STAYS resolved
    across rebuilds, and only re-opens when the underlying label/identity data
    actually changes the signature.
    """
    signature = json.dumps(detail, sort_keys=True, default=str)
    resolved = conn.execute(
        "SELECT resolved_at FROM cat_review_resolutions"
        " WHERE kind = ? AND work_key = ? AND signature = ?",
        (kind, str(work_key), signature)).fetchone()
    conn.execute(
        "INSERT INTO cat_review_queue (kind, work_id, release_id, page_url, detail,"
        " raised_at, resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, work_id, release_id, page_url, signature, now,
         float(resolved[0]) if resolved else None))
    return bool(resolved)


def _expand_season_packs(conn, counters, now) -> None:
    """Materialize the episodes a season pack stands for (G-2), so a pack-only
    season is enumerable and `best_release_id` can point at the pack.

    The span must come from data the ledger actually carries: an `EP(01-12)` or
    `12EP`/`12 Episodes` figure on the pack's own label, or the highest episode
    number already projected in that season from per-episode prints. When neither
    names a span the season honestly keeps zero episodes and every unresolvable
    pack raises `season_pack_span_unresolved` for a human.
    """
    for pack in _select_dicts(
            conn,
            """
            SELECT r.id AS id, r.work_id AS work_id, w.work_key AS work_key,
                   r.season_number AS season_number, r.label AS label, s.id AS season_id
            FROM cat_releases r
            JOIN cat_works w ON w.id = r.work_id
            JOIN cat_seasons s ON s.work_id = r.work_id AND s.number = r.season_number
            WHERE r.coverage_type = 'season_pack' AND r.season_number IS NOT NULL
            ORDER BY r.id
            """):
        hint = _pack_span(str(pack["label"] or ""))
        max_known = int(conn.execute(
            "SELECT COALESCE(MAX(number), 0) FROM cat_episodes WHERE season_id = ?",
            (int(pack["season_id"]),)).fetchone()[0])
        lo, hi = hint if hint else (1, max_known)
        if hint and max_known > hi:
            hi = max_known
        if hi < lo or hi > MAX_ENUMERATED_EPISODES:
            _raise_review(
                conn, kind="season_pack_span_unresolved", work_id=int(pack["work_id"]),
                work_key=str(pack["work_key"]), release_id=int(pack["id"]), now=now,
                detail={"label": pack["label"], "season": pack["season_number"]})
            continue
        known = {int(row[0]): int(row[1]) for row in conn.execute(
            "SELECT number, id FROM cat_episodes WHERE season_id = ?", (int(pack["season_id"]),))}
        for number in range(lo, hi + 1):
            episode_id = known.get(number)
            if episode_id is None:
                cur = conn.execute(
                    "INSERT INTO cat_episodes (work_id, season_id, number) VALUES (?, ?, ?)",
                    (int(pack["work_id"]), int(pack["season_id"]), number))
                episode_id = int(cur.lastrowid)
                known[number] = episode_id
                counters["episodes"] += 1
            conn.execute(
                "INSERT OR IGNORE INTO cat_release_episodes (release_id, episode_id, ordinal)"
                " VALUES (?, ?, ?)", (int(pack["id"]), episode_id, number))


def _raise_identity_reviews(conn, now) -> None:
    """Review kinds the projector can raise from projected data alone (§4.1/A9).

    `year_conflict`: same family + normalized title, years within 2, no external
    id (a real merge candidate the key refused to guess). `external_id_conflict`:
    an external-id merge whose site titles share no word at all — probably one
    wrong tmdb/imdb id on a scraper page. Both are informational: they mark the
    works suspect; they never merge, split or hide anything.
    """
    by_base: dict = {}
    for row in conn.execute(
            "SELECT id, work_key, year FROM cat_works"
            " WHERE (imdb_id IS NULL OR imdb_id = '') AND tmdb_id IS NULL"
            " AND work_key NOT LIKE 'imdb:%' AND work_key NOT LIKE 'tmdb:%'"
            " ORDER BY id"):
        base, _, year_text = str(row["work_key"]).rpartition(":")
        try:
            year = int(year_text)
        except (TypeError, ValueError):
            continue
        by_base.setdefault(base, []).append((int(row["id"]), str(row["work_key"]), year))
    for base, entries in sorted(by_base.items()):
        for index in range(len(entries)):
            work_id, work_key, year = entries[index]
            for other_id, other_key, other_year in entries[index + 1:]:
                gap = abs(year - other_year)
                if 0 < gap <= 2:
                    for wid, wkey, sib, sib_key in ((work_id, work_key, other_id, other_key),
                                                    (other_id, other_key, work_id, work_key)):
                        _raise_review(
                            conn, kind="year_conflict", work_id=wid, work_key=wkey, now=now,
                            detail={"base": base, "sibling_work_key": sib_key,
                                    "sibling_work_id": sib, "years": sorted([year, other_year])})

    for work in conn.execute(
            "SELECT id, work_key, title FROM cat_works"
            " WHERE work_key LIKE 'imdb:%' OR work_key LIKE 'tmdb:%' ORDER BY id"):
        own = {t for t in normalize_title(str(work["title"] or "")).split() if not t.isdigit()}
        if not own:
            continue
        seen: set = set()
        for alias in conn.execute(
                "SELECT DISTINCT alias FROM cat_work_aliases WHERE work_id = ? ORDER BY alias",
                (int(work["id"]),)):
            tokens = {t for t in normalize_title(str(alias[0] or "")).split() if not t.isdigit()}
            fingerprint = tuple(sorted(tokens))
            if not tokens or fingerprint in seen:
                continue
            seen.add(fingerprint)
            if not (tokens & own):
                _raise_review(
                    conn, kind="external_id_conflict", work_id=int(work["id"]),
                    work_key=str(work["work_key"]), now=now,
                    detail={"alias": alias[0], "title": work["title"],
                            "work_key": work["work_key"]})


def _derive_season_titles(conn) -> None:
    """`Season 2: Exams` names the season; a label that only numbers it leaves NULL."""
    titles: dict = {}
    for row in conn.execute(
            "SELECT work_id, season_number, label FROM cat_releases"
            " WHERE season_number IS NOT NULL AND label IS NOT NULL ORDER BY id"):
        title = _season_title_from_label(str(row["label"] or ""))
        if title:
            titles.setdefault((int(row["work_id"]), int(row["season_number"])), title)
    for (work_id, number), title in titles.items():
        conn.execute(
            "UPDATE cat_seasons SET title = COALESCE(title, ?) WHERE work_id = ? AND number = ?",
            (title, work_id, number))


def _derive_work_runtimes(conn) -> None:
    """Runtime exists here only when a label literally says `120min`; the first
    print that names one wins, everything else honestly stays NULL."""
    runtimes: dict = {}
    for row in conn.execute(
            "SELECT work_id, label FROM cat_releases WHERE label IS NOT NULL ORDER BY id"):
        m = _RUNTIME_RE.search(str(row["label"] or ""))
        if m and 5 <= int(m.group(1)) <= 600:
            runtimes.setdefault(int(row["work_id"]), int(m.group(1)))
    for work_id, minutes in runtimes.items():
        conn.execute("UPDATE cat_works SET runtime_minutes = ?"
                     " WHERE id = ? AND runtime_minutes IS NULL", (minutes, work_id))


def _derive_parts(conn, counters) -> None:
    """`cat_parts` is per-work structure, not per-label trivia: parts materialize
    only when ONE work carries at least two distinct Part/Chapter/Disc numbers on
    its prints (§S4), which proves the site split the work across parts. A lone
    `Krrish Part 3` title is a sequel work, not a part of one — never a row here.
    """
    per_work: dict = {}
    for row in conn.execute(
            "SELECT id, work_id, label FROM cat_releases WHERE label IS NOT NULL ORDER BY id"):
        part = _part_number(str(row["label"] or ""))
        if part:
            per_work.setdefault(int(row["work_id"]), []).append((int(row["id"]), part, row["label"]))
    for work_id, hits in sorted(per_work.items()):
        numbers = sorted({part for _, part, _ in hits})
        if len(numbers) < 2:
            continue
        for part in numbers:
            label = next(label for _, hit_part, label in hits if hit_part == part)
            m = _PART_RE.search(str(label or ""))
            title = m.group(0).title() if m else f"Part {part}"
            conn.execute("INSERT OR IGNORE INTO cat_parts (work_id, number, title) VALUES (?, ?, ?)",
                         (work_id, part, title))
            counters["parts"] += 1
        for release_id, part, _label in hits:
            conn.execute("UPDATE cat_releases SET part_number = ? WHERE id = ?",
                         (part, release_id))


# ── Id stability across rebuilds (§3 / A2) ───────────────────────────────────

_RELEASE_KEY_SQL = (
    "SELECT r.id AS id, w.work_key AS work_key, r.label AS label,"
    " r.source_site AS source_site, r.origin_url AS origin_url,"
    " r.coverage_type AS coverage_type, r.season_number AS season_number,"
    " r.episode_range AS episode_range, r.resolution AS resolution,"
    " r.source_tag AS source_tag, r.codec AS codec, r.size_bytes AS size_bytes"
    " FROM cat_releases r JOIN cat_works w ON w.id = r.work_id ORDER BY r.id")


def _stable_id_lists(conn) -> dict:
    """{kind: {stable key: [row ids in id order]}} for the current projection."""
    works: dict = {}
    releases: dict = {}
    links: dict = {}
    if _has_table(conn, "cat_works"):
        for row in conn.execute("SELECT id, work_key FROM cat_works ORDER BY id"):
            works.setdefault(str(row["work_key"]), []).append(int(row["id"]))
    if _has_table(conn, "cat_releases"):
        for row in _select_dicts(conn, _RELEASE_KEY_SQL):
            key = (str(row["work_key"]), str(row["label"] or "").strip(),
                   str(row["source_site"] or ""), str(row["origin_url"] or ""),
                   str(row["coverage_type"]), row["season_number"],
                   str(row["episode_range"] or ""), str(row["resolution"] or ""),
                   str(row["source_tag"] or ""), str(row["codec"] or ""),
                   int(row["size_bytes"] or 0))
            releases.setdefault(key, []).append(int(row["id"]))
    if _has_table(conn, "cat_links"):
        for row in conn.execute(
                "SELECT id, COALESCE(NULLIF(url, ''), final_url) AS target"
                " FROM cat_links ORDER BY id"):
            if row[0] is not None and row[1]:
                links.setdefault(str(row[1]), []).append(int(row[0]))
    return {"work": works, "release": releases, "link": links}


def _record_id_map(conn, before: dict, rev: int) -> int:
    """Write (kind, old_id -> new_id, rev) for every row a rebuild renumbered.

    The delete+insert projector stays honest (ids still churn); what the churn
    loses, this journal wins: a caller that persisted numeric ids can resolve
    them once against the new projection instead of guessing. Duplicate stable
    keys (the same url on two prints) are paired in id order.
    """
    after = _stable_id_lists(conn)
    written = 0
    for kind, old_lists in before.items():
        new_lists = after.get(kind) or {}
        for key, old_ids in old_lists.items():
            new_ids = new_lists.get(key)
            if not new_ids:
                continue
            for index, old_id in enumerate(old_ids):
                if index >= len(new_ids):
                    break
                new_id = new_ids[index]
                if new_id != old_id:
                    conn.execute(
                        "INSERT OR REPLACE INTO cat_id_map (kind, old_id, new_id, rev)"
                        " VALUES (?, ?, ?, ?)", (kind, old_id, new_id, rev))
                    written += 1
    return written


def _finalize(conn, works, work_ids, now, counters) -> None:
    """Roll up counts, availability, best print per episode and default entitlements."""
    # One grouped pass over the links, not three correlated COUNT subqueries per print.
    # The old shape probed the link index three times for each of 1.3M prints; grouping
    # once by release_id reads every link a single time and leaves prints with no links
    # at their NOT NULL DEFAULT 0, which is the same answer.
    conn.execute(
        """
        UPDATE cat_releases SET
            link_count = agg.total,
            streamable_count = agg.streamable,
            downloadable_count = agg.downloadable
        FROM (
            SELECT release_id,
                   COUNT(*) AS total,
                   SUM(playability IN ('stream', 'both')) AS streamable,
                   SUM(playability IN ('download', 'both', 'resolve_required')) AS downloadable
            FROM cat_links
            GROUP BY release_id
        ) agg
        WHERE agg.release_id = cat_releases.id
        """
    )
    _stage(conn, "link counts")
    conn.execute(f"UPDATE cat_links SET rank_score = {RANK_SCORE_EXPR}")
    _stage(conn, "rank scores")
    _expand_season_packs(conn, counters, now)
    _raise_identity_reviews(conn, now)
    _stage(conn, "season packs expanded, identity reviews raised")
    # A durable resolution clears the print's suspect flag even though the label
    # data still re-raises the (now-resolved) queue row on every rebuild.
    conn.execute(
        """
        UPDATE cat_releases SET identity_suspect = COALESCE((
            SELECT 1 FROM cat_review_queue q
            WHERE q.release_id = cat_releases.id AND q.resolved_at IS NULL), 0)
        """
    )
    conn.execute("UPDATE cat_episodes SET absolute_number = NULL")
    conn.execute(
        """
        WITH ordered AS (
            SELECT e.id, ROW_NUMBER() OVER (PARTITION BY w.id ORDER BY s.number, e.number) AS rn
            FROM cat_episodes e
            JOIN cat_seasons s ON s.id = e.season_id
            JOIN cat_works w ON w.id = e.work_id
        )
        UPDATE cat_episodes SET absolute_number = (SELECT rn FROM ordered WHERE ordered.id = cat_episodes.id)
        """
    )
    _stage(conn, "suspect flags and absolute episode numbers")
    # Best print per episode: quality first, then the fresher capture (a REPACK or
    # v2 wins its tie against v1 — §5.2), then the later-projected row. An expanded
    # season pack may win when it is the streamable covering print. Prints with an
    # unresolved identity review are excluded (S13).
    conn.execute(
        """
        UPDATE cat_episodes SET best_release_id = (
            SELECT re.release_id FROM cat_release_episodes re
            JOIN cat_releases r ON r.id = re.release_id
            WHERE re.episode_id = cat_episodes.id
              AND r.coverage_type IN ('single_episode', 'episode_range', 'season_pack')
              AND r.streamable_count > 0 AND r.identity_suspect = 0
            ORDER BY r.quality_score DESC, r.print_version DESC, r.id DESC LIMIT 1
        ) WHERE EXISTS (
            SELECT 1 FROM cat_release_episodes re
            JOIN cat_releases r ON r.id = re.release_id
            WHERE re.episode_id = cat_episodes.id
              AND r.coverage_type IN ('single_episode', 'episode_range', 'season_pack')
              AND r.streamable_count > 0 AND r.identity_suspect = 0
        )
        """
    )
    conn.execute(
        """
        UPDATE cat_seasons SET episode_count = (
            SELECT COUNT(*) FROM cat_episodes e WHERE e.season_id = cat_seasons.id)
        """
    )
    _stage(conn, "best print per episode, season counts")
    _derive_season_titles(conn)
    _derive_work_runtimes(conn)
    _derive_parts(conn, counters)
    _stage(conn, "season titles, runtimes, parts")
    conn.execute(
        """
        UPDATE cat_works SET
            release_count = (SELECT COUNT(*) FROM cat_releases r WHERE r.work_id = cat_works.id),
            episode_count = (SELECT COUNT(*) FROM cat_episodes e WHERE e.work_id = cat_works.id),
            site_count = (SELECT COUNT(DISTINCT s.source_site) FROM cat_work_sites s WHERE s.work_id = cat_works.id),
            max_resolution = (
                SELECT r.resolution FROM cat_releases r WHERE r.work_id = cat_works.id
                  AND r.resolution <> 'unknown'
                ORDER BY r.quality_score DESC, r.print_version DESC, r.id DESC LIMIT 1),
            best_quality_score = COALESCE(
                (SELECT MAX(r.quality_score) FROM cat_releases r WHERE r.work_id = cat_works.id), 0),
            available_stream = COALESCE((
                SELECT 1 FROM cat_releases r WHERE r.work_id = cat_works.id AND r.streamable_count > 0), 0),
            available_download = COALESCE((
                SELECT 1 FROM cat_releases r WHERE r.work_id = cat_works.id AND r.downloadable_count > 0), 0),
            identity_suspect = COALESCE((
                SELECT 1 FROM cat_review_queue q WHERE q.work_id = cat_works.id AND q.resolved_at IS NULL), 0),
            updated_at = ?
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO cat_entitlements (work_id, release_id, model,
                                                display_priority, ownership, updated_at)
        SELECT id, NULL, 'free', 10, 'permanent', ? FROM cat_works
        """,
        (now,),
    )
    _reapply_entitlement_rules(conn, now)
    _stage(conn, "work roll-ups and entitlements")
    # Re-apply the durable offset ledger onto the freshly built episode links.
    conn.execute(
        """
        UPDATE cat_release_episodes SET offset_seconds = (
            SELECT o.offset_seconds FROM cat_offsets o
            JOIN cat_releases r ON r.id = cat_release_episodes.release_id
            JOIN cat_works w ON w.id = r.work_id
            JOIN cat_episodes e ON e.id = cat_release_episodes.episode_id
            WHERE o.work_key = w.work_key AND o.season_number = COALESCE(r.season_number, 0)
              AND o.episode_number = e.number
              AND (o.release_label = '' OR o.release_label = r.label)
            ORDER BY o.updated_at DESC LIMIT 1
        ), chapter_title = COALESCE(cat_release_episodes.chapter_title, (
            SELECT o.chapter_title FROM cat_offsets o
            JOIN cat_releases r ON r.id = cat_release_episodes.release_id
            JOIN cat_works w ON w.id = r.work_id
            JOIN cat_episodes e ON e.id = cat_release_episodes.episode_id
            WHERE o.work_key = w.work_key AND o.season_number = COALESCE(r.season_number, 0)
              AND o.episode_number = e.number
              AND (o.release_label = '' OR o.release_label = r.label)
            ORDER BY o.updated_at DESC LIMIT 1
        ))
        WHERE EXISTS (
            SELECT 1 FROM cat_offsets o
            JOIN cat_releases r ON r.id = cat_release_episodes.release_id
            JOIN cat_works w ON w.id = r.work_id
            JOIN cat_episodes e ON e.id = cat_release_episodes.episode_id
            WHERE o.work_key = w.work_key AND o.season_number = COALESCE(r.season_number, 0)
              AND o.episode_number = e.number
              AND (o.release_label = '' OR o.release_label = r.label)
        )
        """
    )
    conn.commit()


def record_offset(conn, *, work_key: str, episode_number: int, offset_seconds: int,
                  season_number: int = 0, release_label: str = "",
                  chapter_title: str | None = None) -> dict:
    """Store a learned pack offset (or a chapter name) against stable identity.

    Every report is counted in `cat_offset_votes` first; the value published to
    `cat_offsets` is the vote winner, so a single wrong report cannot silently
    shift everyone's playback once an offset has `OFFSET_QUORUM` confirmations.
    A fresh position needs a strict plurality; ties keep the incumbent. Returns
    the published row's `{offset_seconds, confirmed_by, offsets_rev, quorum}`.
    """
    ensure_schema(conn)
    now = time.time()
    season_number = int(season_number or 0)
    episode_number = int(episode_number)
    release_label = release_label or ""
    offset_seconds = int(offset_seconds)
    conn.execute(
        """
        INSERT INTO cat_offset_votes (work_key, season_number, episode_number,
                                      release_label, offset_seconds, votes, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(work_key, season_number, episode_number, release_label, offset_seconds)
        DO UPDATE SET votes = cat_offset_votes.votes + 1, updated_at = excluded.updated_at
        """,
        (work_key, season_number, episode_number, release_label, offset_seconds, now),
    )
    current = conn.execute(
        """
        SELECT offset_seconds, confirmed_by FROM cat_offsets
        WHERE work_key = ? AND season_number = ? AND episode_number = ? AND release_label = ?
        """, (work_key, season_number, episode_number, release_label)).fetchone()
    # A pre-majority offset had no vote ledger; seed its stored confirmations so
    # history is not discarded when the first new report arrives.
    if current is not None and not conn.execute(
        """
        SELECT 1 FROM cat_offset_votes WHERE work_key = ? AND season_number = ?
          AND episode_number = ? AND release_label = ? AND offset_seconds = ?
        """, (work_key, season_number, episode_number, release_label,
              int(current[0]))).fetchone():
        conn.execute(
            """
            INSERT OR REPLACE INTO cat_offset_votes (work_key, season_number, episode_number,
                                                     release_label, offset_seconds, votes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (work_key, season_number, episode_number, release_label,
             int(current[0]), max(int(current[1] or 0), 1), now),
        )
    voted = conn.execute(
        """
        SELECT offset_seconds, votes FROM cat_offset_votes
        WHERE work_key = ? AND season_number = ? AND episode_number = ? AND release_label = ?
        ORDER BY votes DESC, offset_seconds ASC
        """, (work_key, season_number, episode_number, release_label)).fetchall()
    winner, votes = int(voted[0][0]), int(voted[0][1])
    incumbent = int(current[0]) if current is not None else None
    if incumbent is not None and incumbent != winner:
        inc_votes = next((int(v) for o, v in voted if int(o) == incumbent), 0)
        if inc_votes >= votes:
            winner, votes = incumbent, inc_votes
    changed = current is None or int(current[0]) != winner or bool(chapter_title)
    conn.execute(
        """
        INSERT INTO cat_offsets (work_key, season_number, episode_number, release_label,
                                 offset_seconds, chapter_title, confirmed_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(work_key, season_number, episode_number, release_label) DO UPDATE SET
            offset_seconds = excluded.offset_seconds,
            chapter_title = COALESCE(excluded.chapter_title, cat_offsets.chapter_title),
            confirmed_by = excluded.confirmed_by,
            updated_at = excluded.updated_at
        """,
        (work_key, season_number, episode_number, release_label,
         winner, chapter_title, votes, now),
    )
    offsets_rev = _bump_rev(conn, "offsets_rev") if changed else _read_rev(conn, "offsets_rev")
    conn.commit()
    return {"offset_seconds": winner, "confirmed_by": votes,
            "offsets_rev": offsets_rev, "quorum": OFFSET_QUORUM}


# ── Entitlements (A12) ───────────────────────────────────────────────────────

def derive_display_priority(model: str, price_minor: int = 0) -> int:
    """Offer sort weight (§11.2): free first, purchase last; unknown models last."""
    return DISPLAY_PRIORITY.get(str(model or "").strip().casefold(), 100)


def _upsert_entitlement(conn, *, work_id: int, release_id, model: str,
                        price_minor: int, currency: str, region, geo_allow, geo_deny,
                        valid_from, valid_until, rental_hours, ownership,
                        requires_account: int, requires_age_gate: int, now: float) -> None:
    """Write one offer row, NULL-safely.

    `UNIQUE (work_id, release_id, model, region)` cannot enforce uniqueness while
    `region` is NULL (SQLite treats NULLs as distinct), so the conflict search is
    done by hand instead of relying on the constraint.
    """
    found = conn.execute(
        "SELECT id FROM cat_entitlements WHERE work_id = ? AND release_id IS ?"
        " AND model = ? AND region IS ?",
        (work_id, release_id, model, region)).fetchone()
    if found is not None:
        conn.execute(
            """
            UPDATE cat_entitlements SET price_minor = ?, currency = ?, geo_allow = ?,
                geo_deny = ?, valid_from = ?, valid_until = ?, rental_hours = ?,
                ownership = ?, requires_account = ?, requires_age_gate = ?,
                display_priority = ?, updated_at = ?
            WHERE id = ?
            """,
            (price_minor, currency, geo_allow, geo_deny, valid_from, valid_until,
             rental_hours, ownership, int(requires_account), int(requires_age_gate),
             derive_display_priority(model), now, int(found[0])),
        )
    else:
        conn.execute(
            """
            INSERT INTO cat_entitlements (work_id, release_id, model, display_priority,
                price_minor, currency, region, geo_allow, geo_deny, valid_from, valid_until,
                rental_hours, ownership, requires_account, requires_age_gate, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (work_id, release_id, model, derive_display_priority(model), price_minor,
             currency, region, geo_allow, geo_deny, valid_from, valid_until, rental_hours,
             ownership, int(requires_account), int(requires_age_gate), now),
        )


def set_entitlement(conn, *, work_key: str, model: str, release_label: str = "",
                    region: str = "", price_minor: int = 0, currency: str = "INR",
                    valid_from=None, valid_until=None, rental_hours=None,
                    ownership: str = "permanent", requires_account: int = 0,
                    requires_age_gate: int = 0, geo_allow=None, geo_deny=None,
                    now: float | None = None, commit: bool = True) -> dict:
    """Write a paid/free offer for one work (or one specific print of it).

    The offer is stored twice: as a durable `cat_entitlement_rules` row keyed by
    `work_key` (so it survives every rebuild and is re-applied by `_finalize()`),
    and — when that work is currently projected — straight onto `cat_entitlements`
    so the API serves it without waiting for the next projection. Bumps
    `entitlements_rev` and nothing else.
    """
    ensure_schema(conn)
    model = str(model or "").strip().casefold()
    if model not in _ENTITLEMENT_MODELS:
        raise ValueError(f"unknown entitlement model {model!r}; "
                         f"expected one of {', '.join(_ENTITLEMENT_MODELS)}")
    now = time.time() if now is None else float(now)
    release_label = str(release_label or "")
    region_value = str(region or "")
    conn.execute(
        """
        INSERT INTO cat_entitlement_rules (work_key, release_label, model, price_minor,
            currency, region, geo_allow, geo_deny, valid_from, valid_until, rental_hours,
            ownership, requires_account, requires_age_gate, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(work_key, release_label, model, region) DO UPDATE SET
            price_minor = excluded.price_minor, currency = excluded.currency,
            geo_allow = excluded.geo_allow, geo_deny = excluded.geo_deny,
            valid_from = excluded.valid_from, valid_until = excluded.valid_until,
            rental_hours = excluded.rental_hours, ownership = excluded.ownership,
            requires_account = excluded.requires_account,
            requires_age_gate = excluded.requires_age_gate, updated_at = excluded.updated_at
        """,
        (work_key, release_label, model, int(price_minor or 0), currency or "INR",
         region_value, geo_allow, geo_deny, valid_from, valid_until, rental_hours,
         ownership or "permanent", int(requires_account or 0),
         int(requires_age_gate or 0), now),
    )
    applied = _apply_entitlement_rule(conn, {
        "work_key": work_key, "release_label": release_label, "model": model,
        "price_minor": int(price_minor or 0), "currency": currency or "INR",
        "region": region_value, "geo_allow": geo_allow, "geo_deny": geo_deny,
        "valid_from": valid_from, "valid_until": valid_until,
        "rental_hours": rental_hours, "ownership": ownership or "permanent",
        "requires_account": int(requires_account or 0),
        "requires_age_gate": int(requires_age_gate or 0),
    }, now)
    entitlements_rev = _bump_rev(conn, "entitlements_rev")
    if commit:
        conn.commit()
    return {"work_key": work_key, "model": model, "applied": bool(applied),
            "display_priority": derive_display_priority(model),
            "entitlements_rev": entitlements_rev}


def _rule_target(conn, rule: dict):
    """(work_id, release_id) for one durable rule, or None when nothing matches yet."""
    work = conn.execute("SELECT id FROM cat_works WHERE work_key = ?",
                        (str(rule["work_key"]),)).fetchone()
    if work is None:
        return None
    work_id = int(work[0])
    label = str(rule.get("release_label") or "")
    if not label:
        return work_id, None
    rel = conn.execute(
        "SELECT id FROM cat_releases WHERE work_id = ? AND label = ? ORDER BY id LIMIT 1",
        (work_id, label)).fetchone()
    if rel is None:
        return None
    return work_id, int(rel[0])


def _apply_entitlement_rule(conn, rule: dict, now: float) -> bool:
    target = _rule_target(conn, rule)
    if target is None:
        return False
    work_id, release_id = target
    region = str(rule.get("region") or "") or None
    if str(rule["model"]) != "free" and release_id is None and region is None:
        # A work-level paid offer replaces the projector's automatic free default
        # at the same scope; per-print offers sit alongside it.
        conn.execute(
            "DELETE FROM cat_entitlements WHERE work_id = ? AND model = 'free'"
            " AND release_id IS NULL AND region IS NULL", (work_id,))
    _upsert_entitlement(
        conn, work_id=work_id, release_id=release_id, model=str(rule["model"]),
        price_minor=int(rule.get("price_minor") or 0),
        currency=str(rule.get("currency") or "INR"), region=region,
        geo_allow=rule.get("geo_allow"), geo_deny=rule.get("geo_deny"),
        valid_from=rule.get("valid_from"), valid_until=rule.get("valid_until"),
        rental_hours=rule.get("rental_hours"), ownership=str(rule.get("ownership") or "permanent"),
        requires_account=int(rule.get("requires_account") or 0),
        requires_age_gate=int(rule.get("requires_age_gate") or 0), now=now)
    if release_id is None and str(rule["model"]) != "free":
        conn.execute("UPDATE cat_works SET entitlement_model = ? WHERE id = ?",
                     (str(rule["model"]), work_id))
    return True


def _reapply_entitlement_rules(conn, now: float) -> int:
    """Re-project every durable offer onto the fresh `cat_entitlements` rows.

    Runs inside `_finalize()`, after the automatic free defaults: it does NOT bump
    `entitlements_rev`, because the rebuild already bumped `catalog_rev` and the
    offers themselves have not been edited.
    """
    applied = 0
    for rule in _select_dicts(
            conn, "SELECT * FROM cat_entitlement_rules ORDER BY work_key, release_label, model, region"):
        if _apply_entitlement_rule(conn, rule, now):
            applied += 1
    return applied


# ── Review resolution (S13) ──────────────────────────────────────────────────

def resolve_reviews(conn, *, review_ids=(), kind: str | None = None,
                    work_id: int | None = None, now: float | None = None,
                    commit: bool = True) -> int:
    """Mark queue rows resolved, remember the decision durably, refresh flags.

    The durable copy in `cat_review_resolutions` is keyed by (kind, work_key,
    detail-signature) so the same finding stays settled through every future
    rebuild; after stamping, release/work suspect flags and episode best prints
    are recomputed so a cleared suspect can win `best_release_id` immediately.
    """
    ensure_schema(conn)
    now = time.time() if now is None else float(now)
    ids = [int(i) for i in review_ids or ()]
    clauses, params = [], []
    if ids:
        clauses.append("id IN (%s)" % ",".join("?" * len(ids)))
        params.extend(ids)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if work_id is not None:
        clauses.append("work_id = ?")
        params.append(int(work_id))
    if not clauses:
        raise ValueError("resolve_reviews needs review_ids, kind or work_id")
    rows = _select_dicts(
        conn,
        "SELECT id, kind, work_id, release_id, detail FROM cat_review_queue"
        " WHERE resolved_at IS NULL AND " + " AND ".join(clauses) + " ORDER BY id",
        tuple(params))
    count = 0
    for row in rows:
        conn.execute("UPDATE cat_review_queue SET resolved_at = ? WHERE id = ?",
                     (now, int(row["id"])))
        work_key = ""
        if row.get("work_id") is not None:
            found = conn.execute("SELECT work_key FROM cat_works WHERE id = ?",
                                 (int(row["work_id"]),)).fetchone()
            work_key = str(found[0]) if found else ""
        elif row.get("release_id") is not None:
            found = conn.execute(
                """
                SELECT w.work_key FROM cat_releases r
                JOIN cat_works w ON w.id = r.work_id WHERE r.id = ?
                """, (int(row["release_id"]),)).fetchone()
            work_key = str(found[0]) if found else ""
        conn.execute(
            "INSERT OR REPLACE INTO cat_review_resolutions (kind, work_key, signature, resolved_at)"
            " VALUES (?, ?, ?, ?)",
            (str(row["kind"]), work_key, str(row["detail"] or ""), float(now)))
        count += 1
    conn.execute(
        """
        UPDATE cat_releases SET identity_suspect = COALESCE((
            SELECT 1 FROM cat_review_queue q
            WHERE q.release_id = cat_releases.id AND q.resolved_at IS NULL), 0)
        """
    )
    conn.execute(
        """
        UPDATE cat_works SET identity_suspect = COALESCE((
            SELECT 1 FROM cat_review_queue q
            WHERE q.work_id = cat_works.id AND q.resolved_at IS NULL), 0)
        """
    )
    conn.execute(
        """
        UPDATE cat_episodes SET best_release_id = (
            SELECT re.release_id FROM cat_release_episodes re
            JOIN cat_releases r ON r.id = re.release_id
            WHERE re.episode_id = cat_episodes.id
              AND r.coverage_type IN ('single_episode', 'episode_range', 'season_pack')
              AND r.streamable_count > 0 AND r.identity_suspect = 0
            ORDER BY r.quality_score DESC, r.print_version DESC, r.id DESC LIMIT 1
        ) WHERE EXISTS (
            SELECT 1 FROM cat_release_episodes re
            JOIN cat_releases r ON r.id = re.release_id
            WHERE re.episode_id = cat_episodes.id
              AND r.coverage_type IN ('single_episode', 'episode_range', 'season_pack')
              AND r.streamable_count > 0 AND r.identity_suspect = 0
        )
        """
    )
    if commit:
        conn.commit()
    return count


# ── Measured evidence write-back (API_V2.md §6.2, gap G-7) ──────────────────

#: The newest sample's share in the rolling blend — `link_health`'s documented
#: EWMA weight, named here too so the write-back and §6.3 cannot drift apart.
EVIDENCE_EWMA_WEIGHT = 0.4

#: Link ids per read batch. Keeps the `IN (...)` lists bounded on the merged
#: catalog, which is millions of links on a one-CPU VM.
EVIDENCE_BATCH = 500

_EVIDENCE_INSERT_SQL = """
INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, http_status,
    content_type, size_bytes, latency_ms, speed_mbps, accepts_ranges, error, url)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _link_health():
    """Import the prober lazily, exactly the way `project()` imports the descriptor."""
    try:
        import link_health
    except ImportError:  # pragma: no cover - package-relative fallback
        from Fast_Fetch import link_health  # type: ignore
    return link_health


def _result_to_journal(item) -> dict:
    """One measurement (ProbeResult or dict) -> journal column values.

    `cors_open` is not a journal column (`cat_link_evidence` predates it), so it
    travels in this dict as an extra key and is written straight to `cat_links`.
    """
    lh = _link_health()
    sample = item if isinstance(item, lh.ProbeResult) else lh.evidence_result(
        item if isinstance(item, dict) else dict(item))
    row = item if isinstance(item, dict) else {}
    link_id = row.get("link_id") or row.get("cat_link_id")
    try:
        link_id = int(link_id) if link_id not in (None, "") else None
    except (TypeError, ValueError):
        link_id = None
    checked = float(getattr(sample, "checked_at", 0.0) or row.get("probed_at") or 0.0)
    # `evidence_result()` has to answer with *some* protocol, so a client report that
    # never names one comes back as "unusable". That default is a measurement claim
    # we did not make: keep the journal honest with NULL and let `_blend_link()`
    # treat the sample as a verdict + timings only (see its docstring).
    protocol = str(getattr(sample, "protocol", "") or "")
    if isinstance(item, dict) and not str(row.get("protocol") or "").strip():
        protocol = ""
    return {
        "link_id": link_id,
        "url": str(row.get("url") or getattr(sample, "url", "") or ""),
        "match_urls": [str(value) for value in
                       (getattr(sample, "url", ""), getattr(sample, "redirects_to", ""),
                        row.get("final_url")) if value],
        "probed_at": checked,
        "ok": 1 if getattr(sample, "ok", False) else 0,
        "protocol": protocol,
        "http_status": int(getattr(sample, "http_status", 0) or 0),
        "content_type": str(getattr(sample, "content_type", "") or ""),
        "size_bytes": int(getattr(sample, "size_bytes", 0) or 0),
        "latency_ms": int(getattr(sample, "latency_ms", 0) or 0),
        "speed_mbps": float(getattr(sample, "download_speed_mbps", 0.0) or 0.0),
        "accepts_ranges": 1 if getattr(sample, "accepts_ranges", False) else 0,
        "error": str(getattr(sample, "error", "") or ""),
        "cors_open": bool(getattr(sample, "cors_open", False)),
    }


def _resolve_link_id(conn, values: dict):
    """The `cat_links.id` a measurement belongs to, or None when nothing matches.

    An explicit id wins (that is how `link_state` addresses a row after a rebuild);
    otherwise the probed URL has to name a projected link. We never insert a
    catalog row behind the projector's back — an unknown URL is reported, not created.
    """
    if values.get("link_id") is not None:
        found = conn.execute("SELECT id FROM cat_links WHERE id = ?",
                             (int(values["link_id"]),)).fetchone()
        if found is not None:
            return int(found[0])
    for candidate in values.get("match_urls") or []:
        found = conn.execute(
            "SELECT id FROM cat_links WHERE url = ? OR final_url = ? ORDER BY id DESC LIMIT 1",
            (candidate, candidate)).fetchone()
        if found is not None:
            return int(found[0])
    return None


def _value_differs(old, new) -> bool:
    """Numeric-tolerant inequality, so replaying an unchanged journal is a real no-op.

    NULL is a different fact from a number: a column nobody filled in becoming 0
    or 120 counts as a change, while ``1`` versus ``1.0`` versus ``True`` does not.
    """
    if old is None or new is None:
        return not (old is None and new is None)
    if isinstance(old, bool) or isinstance(new, bool):
        return bool(old) != bool(new)
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(float(old) - float(new)) > 1e-9
    return str(old) != str(new)


def _select_dicts(conn, sql: str, params=()) -> list:
    """``SELECT`` result as plain dicts, whatever the caller's ``row_factory`` is.

    `apply_evidence` reads whole `cat_links` / `cat_link_evidence` rows and must
    work both on a `sqlite3.Row` connection (the projector's own) and on a default
    tuple one (a bare `sqlite3.connect(path)`), so it goes through the cursor
    description instead of assuming either.
    """
    cursor = conn.execute(sql, params)
    names = [column[0] for column in (cursor.description or ())]
    out = []
    for raw in cursor.fetchall():
        if isinstance(raw, dict):
            out.append(dict(raw))
            continue
        values = tuple(raw)
        out.append({name: (values[index] if index < len(values) else None)
                    for index, name in enumerate(names)})
    return out


def _blend_link(link, rows, *, weight: float = EVIDENCE_EWMA_WEIGHT, cors_fact=None):
    """Fold one link's ordered evidence journal into the columns to write.

    Pure: it reads nothing from the database and writes nothing. Returns
    ``(values, measured)`` where ``values`` holds only `cat_links` columns and
    ``measured`` says whether the score in it came from `link_health.score_link`.

    The rules, all of them chosen so a replay of an unchanged journal produces
    the same answer:

    * ``state`` is the NEWEST verdict — `active`, or `dead`/`expired` for a
      measured failure (401/403 is token rot, i.e. `expired`). Nothing here looks
      at a sample's age, and nothing touches a link with no verdict in the
      journal, so an old link is never silently marked dead.
    * ``latency_ms`` / ``speed_mbps`` are the EWMA blend of every verdict in the
      journal (`merge_evidence_journal`, newest share ``weight``), and only when
      a sample actually measured them — an unmeasured timing stays NULL instead
      of being faked as 0 (§7.1).
    * the facts a probe observed — ``http_status``, ``content_type``, ``size_bytes``
      — come from the newest *probe-shaped* row (one that names a protocol),
      whatever its verdict, because they are simply the last thing we saw.
      ``accepts_ranges`` and ``resumable`` (ranges + a file the client can keep)
      come from the row the score is built from, so the two always agree.
      Client reports (`POST /links/{id}/report` appends an `ok` plus a client-side
      latency and no protocol) move state and timings but cannot invent a
      protocol, and they never switch a link onto the measured scale.
    * ``rank_score`` is `link_health.score_link` on that blended sample whenever
      the journal holds a probe that agrees with the newest verdict — so a
      measured-dead link scores 0 and drops below every live peer. A link the
      client says works but that has never had a *successful* probe keeps the
      structural prior instead: prior 0..900 and measured 0..1000 are the two
      documented scales of §6.3 and mixing a guess with a measurement is exactly
      the conflation this layer exists to stop.
    """
    lh = _link_health()
    verdicts = [row for row in rows
                if not lh.is_no_verdict(_pick_col(row, "error", "") or "")]
    if not verdicts:
        return {}, False
    newest = verdicts[-1]
    newest_ok = bool(int(_pick_col(newest, "ok", 0) or 0))
    newest_error = str(_pick_col(newest, "error", "") or "")
    probes = [row for row in verdicts if str(_pick_col(row, "protocol", "") or "")]
    probes_ok = [row for row in probes if int(_pick_col(row, "ok", 0) or 0)]
    record = lh.merge_evidence_journal(verdicts, weight=weight)

    values: dict = {}
    state = lh.verdict_state(newest_ok, error=newest_error,
                             http_status=int(_pick_col(newest, "http_status", 0) or 0))
    if state:
        values["state"] = state
    if record["latency_ms_ema"]:
        values["latency_ms"] = int(record["latency_ms_ema"])
    if record["speed_mbps_ema"]:
        values["speed_mbps"] = round(float(record["speed_mbps_ema"]), 4)
    if record["last_checked"]:
        values["last_evidence_at"] = float(record["last_checked"])

    if probes:
        observed = probes[-1]
        status = int(_pick_col(observed, "http_status", 0) or 0)
        if status:
            values["http_status"] = status
        content_type = str(_pick_col(observed, "content_type", "") or "")
        if content_type:
            values["content_type"] = content_type
        size_bytes = int(_pick_col(observed, "size_bytes", 0) or 0)
        if size_bytes:
            values["size_bytes"] = size_bytes

    # the sample the score is built from: a probe that matches the newest verdict.
    # A link the client says works but that has never had a successful probe has
    # no measurement to score on, so it keeps the structural prior.
    if newest_ok:
        fact_row = probes_ok[-1] if probes_ok else None
    else:
        fact_row = probes[-1] if probes else None
    cors_open = cors_fact if cors_fact is not None else bool(
        _pick_col(link, "cors_open", 0) or 0)
    if cors_fact is not None:
        values["cors_open"] = 1 if cors_fact else 0

    if fact_row is None:
        # nothing but client reports measured this link: keep the structural prior
        return values, False
    sample = lh.evidence_result(fact_row)
    ranges = _pick_col(fact_row, "accepts_ranges", None)
    if ranges is not None:
        values["accepts_ranges"] = 1 if int(ranges or 0) else 0
    if not newest_ok:
        # the newest verdict failed: the endpoint is not playable right now,
        # whatever an older sample said about its protocol
        sample = dataclasses.replace(sample, ok=False, streamable=False,
                                     downloadable=False, resumable=False,
                                     error=newest_error or sample.error)
    sample = dataclasses.replace(
        sample,
        latency_ms=int(record["latency_ms_ema"] or sample.latency_ms),
        download_speed_mbps=float(record["speed_mbps_ema"] or sample.download_speed_mbps),
        cors_open=cors_open)
    values["resumable"] = 1 if sample.resumable else 0
    values["rank_score"] = lh.score_link(
        sample,
        playback_type=str(_pick_col(link, "playability", "") or ""),
        is_temporary=int(_pick_col(link, "ephemeral", 0) or 0),
        service_tier=int(_pick_col(link, "tier", 2) or 2))
    return values, True


def _refresh_state_rollup(conn, now: float) -> dict:
    """Recompute the coverage counters `project()` writes, after a state change."""
    if not _has_table(conn, "cat_projection_meta") or not _has_table(conn, "cat_links"):
        return {}
    by_state = {str(row[0]): int(row[1]) for row in
                conn.execute("SELECT state, COUNT(*) FROM cat_links GROUP BY state")}
    total = sum(by_state.values())
    conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('links_by_state', ?)",
                 (json.dumps(by_state, sort_keys=True),))
    conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('link_coverage', ?)",
                 (str(round(by_state.get("active", 0) / total, 4) if total else 0.0),))
    return by_state


def apply_evidence(conn, results=(), *, link_ids=None, limit=None,
                   weight: float = EVIDENCE_EWMA_WEIGHT, now=None,
                   commit: bool = True) -> dict:
    """Write measured probe truth back onto `cat_links` — no re-projection needed.

    This is the write-back API_V2.md §6.2 and gap G-7 said did not exist: probe
    samples (from `link_health.probe` / `probe_many`, or already journalled in
    `cat_link_evidence`) land on the owning link's own row, so a v2 server can
    publish a *measured* `score_scale` for links it projected hours ago, and
    `/api/v1/stats` liveness stops being a scrape-time guess.

    Args:
        conn: an open connection to a database that already has the `cat_*`
            projection. Nothing is created here except the `url` column on the
            evidence journal (see `_migrate_evidence_journal`).
        results: measurements to append to the journal first — `ProbeResult`
            objects, or dicts shaped like one (an extra ``link_id`` key addresses
            a projected link directly, which survives a rebuild). Empty means
            "apply the evidence we already have", which is what the CLI does and
            what makes this safe to run at any cadence.
        link_ids: restrict the write-back to these `cat_links.id`s.
        limit: at most this many links this call (batched by `EVIDENCE_BATCH`).
        weight: newest sample's EWMA share, forwarded to `merge_health_history`.
        now: wall clock stamped into `health_at` only when something changed.
        commit: False lets a caller fold this into its own transaction.

    Idempotent by construction: every value is re-derived from the whole journal
    for the link, never incremented, and a measurement already in the journal is
    not re-appended (same ``link_id`` + ``probed_at``). Rows are only UPDATEd,
    never deleted — a link that measured dead stays in the catalog with
    `state='dead'` and a score of 0, behind every live peer (Zero Data Loss).

    It also does NOT probe: no socket is opened here. The operator (or a test)
    hands in measurements; `link_state.propagate` remains the only thing that
    knocks on endpoints, and nothing in any HTTP route calls this function.

    Returns counters — including `health_rev`, the value now in
    `cat_projection_meta.health` (§16.2's `health` version group) — so the caller
    can prove what moved.
    """
    if not _has_table(conn, "cat_links"):
        raise ValueError("apply_evidence() needs the cat_* projection; "
                         "run catalog_v2.project() first")
    if not _has_table(conn, "cat_link_evidence"):
        raise ValueError("apply_evidence() needs cat_link_evidence; "
                         "run catalog_v2.project() first")
    clock = time.time() if now is None else float(now)
    _migrate_evidence_journal(conn)
    link_columns = _columns(conn, "cat_links")

    # ── 1. append the supplied measurements (replaying one is a no-op) ──────
    added = 0
    unresolved = 0
    cors_facts: dict[int, tuple] = {}
    touched: list[int] = []
    for item in (results or ()):
        values = _result_to_journal(item)
        link_id = _resolve_link_id(conn, values)
        if link_id is None:
            unresolved += 1
            continue
        seen = conn.execute("SELECT 1 FROM cat_link_evidence"
                            " WHERE link_id = ? AND probed_at = ? LIMIT 1",
                            (link_id, values["probed_at"])).fetchone()
        if seen is None:
            conn.execute(_EVIDENCE_INSERT_SQL,
                         (link_id, values["probed_at"], values["ok"], values["protocol"],
                          values["http_status"], values["content_type"],
                          values["size_bytes"], values["latency_ms"], values["speed_mbps"],
                          values["accepts_ranges"], values["error"] or None,
                          values["url"] or None))
            added += 1
        touched.append(link_id)
        stamp = cors_facts.get(link_id, (-1.0, None))
        if values["probed_at"] >= stamp[0]:
            cors_facts[link_id] = (values["probed_at"], bool(values["cors_open"]))

    # ── 2. who has evidence ────────────────────────────────────────────────
    if link_ids is not None:
        queue = [int(value) for value in link_ids]
    else:
        queue = [int(row[0]) for row in conn.execute(
            "SELECT DISTINCT l.id FROM cat_links l"
            " JOIN cat_link_evidence e ON e.link_id = l.id ORDER BY l.id")]
        for link_id in touched:
            if link_id not in queue:
                queue.append(link_id)
    if limit is not None:
        queue = queue[:max(int(limit), 0)]
    pending: list[int] = []
    for link_id in queue:
        if link_id not in pending:
            pending.append(link_id)
    seen_ids: set[int] = set()
    scanned = updated = measured = repointed = orphaned = 0
    prior_refresh: list[int] = []
    state_changes: dict[str, int] = {}

    # ── 3. fold, batch by batch ────────────────────────────────────────────
    while pending:
        chunk: list[int] = []
        while pending and len(chunk) < EVIDENCE_BATCH:
            link_id = int(pending.pop(0))
            if link_id not in seen_ids:
                seen_ids.add(link_id)
                chunk.append(link_id)
        if not chunk:
            continue
        marks = ",".join("?" * len(chunk))
        links = {int(link["id"]): link for link in _select_dicts(
            conn, f"SELECT * FROM cat_links WHERE id IN ({marks}) ORDER BY id", tuple(chunk))}
        urls: dict[str, int] = {}
        owned: dict[int, set] = {}
        for link_id, row in links.items():
            names = owned.setdefault(link_id, set())
            for key in ("url", "final_url"):
                if row.get(key):
                    value = str(row[key])
                    names.add(value)
                    urls.setdefault(value, link_id)
        url_marks = ",".join("?" * len(urls)) if urls else ""
        rows = _select_dicts(
            conn,
            f"SELECT * FROM cat_link_evidence WHERE link_id IN ({marks})"
            + (f" OR (url IS NOT NULL AND url IN ({url_marks}))" if urls else "")
            + " ORDER BY link_id, probed_at, id",
            tuple(chunk) + tuple(urls))
        buckets: dict[int, list] = {link_id: [] for link_id in links}
        deferred: set[int] = set()
        for row in rows:
            raw_id = row.get("link_id")
            link_id = int(raw_id) if raw_id is not None else None
            url = str(row["url"]) if row.get("url") else ""
            if url and not (link_id is not None and url in owned.get(link_id, ())):
                # the pointer no longer agrees with the URL it was taken against:
                # re-own the sample by the URL, which is the durable half
                owner = urls.get(url)
                if owner is None:
                    # the sample names a link this batch does not hold: look it up
                    found = conn.execute(
                        "SELECT id FROM cat_links WHERE url = ? OR final_url = ?"
                        " ORDER BY id DESC LIMIT 1", (url, url)).fetchone()
                    owner = int(found[0]) if found else None
                    if owner is not None:
                        urls.setdefault(url, owner)
                if owner is None:
                    orphaned += 1         # a sample of a link we do not have
                    continue
                if link_id is not None and owner != link_id:
                    # a rebuild renumbered the links; heal the pointer, never the sample
                    conn.execute("UPDATE cat_link_evidence SET link_id = ? WHERE id = ?",
                                 (owner, int(row["id"])))
                    repointed += 1
                link_id = owner
            if link_id is None:
                orphaned += 1
                continue
            if link_id not in buckets:
                # its journal belongs to another batch: read it all there, not here
                if link_id not in seen_ids:
                    deferred.add(int(link_id))
                else:
                    orphaned += 1
                continue
            buckets[link_id].append(row)
        for value in sorted(deferred - set(links)):
            pending.append(int(value))
        for link_id, journal in buckets.items():
            link = links.get(link_id)
            if link is None or not journal:
                continue
            scanned += 1
            values, is_measured = _blend_link(
                link, journal, weight=weight,
                cors_fact=cors_facts.get(link_id, (None, None))[1])
            if not values:
                continue
            if is_measured:
                measured += 1
            else:
                prior_refresh.append(link_id)
            changes = {key: value for key, value in values.items()
                       if key in link_columns
                       and _value_differs(_pick_col(link, key, None), value)}
            if not changes:
                continue
            if "state" in changes:
                state_changes[changes["state"]] = state_changes.get(changes["state"], 0) + 1
            names = sorted(changes)
            conn.execute(f"UPDATE cat_links SET {', '.join(f'{name} = ?' for name in names)}"
                         f" WHERE id = ?", tuple(changes[name] for name in names) + (link_id,))
            updated += 1

    # ── 4. unmeasured links keep the structural prior (§6.3) ───────────────
    if prior_refresh:
        marks = ",".join(str(int(value)) for value in prior_refresh)
        conn.execute(f"UPDATE cat_links SET rank_score = {RANK_SCORE_EXPR}"
                     f" WHERE id IN ({marks})")

    # ── 5. the `health` version group (§16.2) ──────────────────────────────
    journal_rows = int(conn.execute("SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0])
    stored = None
    if _has_table(conn, "cat_projection_meta"):
        row = conn.execute("SELECT value FROM cat_projection_meta WHERE key = 'health'").fetchone()
        stored = str(row[0]) if row and row[0] is not None else None
    health_bumped = updated > 0 or added > 0 or stored != str(journal_rows)
    if health_bumped and _has_table(conn, "cat_projection_meta"):
        conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value)"
                     " VALUES ('health', ?)", (str(journal_rows),))
        conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value)"
                     " VALUES ('health_at', ?)", (str(clock),))
        _refresh_state_rollup(conn, clock)
    if commit:
        conn.commit()
    return {
        "links_scanned": scanned,
        "links_updated": updated,
        "measured_links": measured,
        "evidence_added": added,
        "evidence_rows": journal_rows,
        "evidence_repointed": repointed,
        "evidence_orphaned": orphaned,
        "results_unresolved": unresolved,
        "state_changes": state_changes,
        "health_rev": journal_rows,
        "health_bumped": bool(health_bumped),
        "weight": float(weight),
    }


def project_db(db_path: Path, *, rev: int | None = None, verbose: bool = True) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return project(conn, rev=rev, verbose=verbose)
    finally:
        conn.close()


def apply_evidence_db(db_path: Path, *, link_ids=None, limit=None,
                      weight: float = EVIDENCE_EWMA_WEIGHT, verbose: bool = True) -> dict:
    """Fold the evidence already recorded in *db_path* back onto its links.

    Deliberately offline: this opens no socket. It applies the `cat_link_evidence`
    journal the health sweep and the client reports have written; probing stays
    in `link_state.propagate`, which the operator runs on their own schedule on
    this one-CPU box.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        summary = apply_evidence(conn, (), link_ids=link_ids, limit=limit,
                                 weight=weight)
    finally:
        conn.close()
    if verbose:
        print(f"[✓] evidence applied to {summary['links_updated']} of "
              f"{summary['links_scanned']} links: {summary['measured_links']} measured, "
              f"health rev {summary['health_rev']}", flush=True)
    return summary


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Project the ingest ledger into the catalog v2 tables.")
    parser.add_argument("db", help="Path to a merged catalog database (never a staging DB)")
    parser.add_argument("--rev", type=int, default=None, help="Source revision marker to stamp")
    parser.add_argument("--apply-evidence", action="store_true",
                        help="skip the rebuild and only fold existing cat_link_evidence "
                             "into cat_links (state, EWMA latency/speed, measured "
                             "rank_score, health rev). Never probes the network.")
    parser.add_argument("--link-id", type=int, action="append", default=None,
                        dest="link_ids", help="with --apply-evidence: restrict to these cat_links ids")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --apply-evidence: at most this many links per run")
    parser.add_argument("--ewma-weight", type=float, default=EVIDENCE_EWMA_WEIGHT,
                        help="newest sample's share of the rolling blend (default 0.4)")
    parser.add_argument("--set-entitlement", metavar="WORK_KEY", default=None,
                        help="write an entitlement offer for one work_key and exit")
    parser.add_argument("--model", default="free",
                        help="with --set-entitlement: free|ads|flatrate|rental|purchase")
    parser.add_argument("--price", type=int, default=0,
                        help="with --set-entitlement: price in minor units (default 0)")
    parser.add_argument("--currency", default="INR", help="with --set-entitlement: ISO code")
    parser.add_argument("--region", default="",
                        help="with --set-entitlement: offer region, empty = global")
    parser.add_argument("--release-label", default="",
                        help="with --set-entitlement: bind the offer to one print label")
    parser.add_argument("--rental-hours", type=int, default=None,
                        help="with --set-entitlement: rental window in hours")
    parser.add_argument("--valid-from", type=float, default=None,
                        help="with --set-entitlement: offer start (unix seconds)")
    parser.add_argument("--valid-until", type=float, default=None,
                        help="with --set-entitlement: offer end (unix seconds)")
    parser.add_argument("--ownership", default="permanent",
                        help="with --set-entitlement: permanent|rental|timered")
    parser.add_argument("--requires-account", action="store_true",
                        help="with --set-entitlement: viewer must be signed in")
    parser.add_argument("--requires-age-gate", action="store_true",
                        help="with --set-entitlement: viewer must pass the 18+ gate")
    parser.add_argument("--resolve-review", type=int, action="append", default=None,
                        dest="review_ids", help="mark these cat_review_queue ids resolved and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    db_path = Path(args.db).resolve()
    if args.set_entitlement:
        conn = sqlite3.connect(db_path)
        try:
            summary = set_entitlement(
                conn, work_key=args.set_entitlement, model=args.model,
                release_label=args.release_label, region=args.region,
                price_minor=args.price, currency=args.currency,
                valid_from=args.valid_from, valid_until=args.valid_until,
                rental_hours=args.rental_hours, ownership=args.ownership,
                requires_account=1 if args.requires_account else 0,
                requires_age_gate=1 if args.requires_age_gate else 0)
        finally:
            conn.close()
    elif args.review_ids:
        conn = sqlite3.connect(db_path)
        try:
            count = resolve_reviews(conn, review_ids=args.review_ids)
        finally:
            conn.close()
        summary = {"resolved_reviews": count}
    elif args.apply_evidence:
        summary = apply_evidence_db(db_path, link_ids=args.link_ids, limit=args.limit,
                                    weight=args.ewma_weight)
    else:
        summary = project_db(db_path, rev=args.rev)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
