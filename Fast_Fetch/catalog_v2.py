#!/usr/bin/env python3
"""
catalog_v2.py — Canonical catalog projection over the per-site ingest ledger.

Layer 0 (posts / releases / download_sources / post_sources) stores what each site
said. This module derives Layer 1: works, seasons, episodes, prints (releases),
links, tracks and entitlements — structured, ranked and rebuildable.

The projection is idempotent: rebuilding it from an unchanged ledger produces the
same rows. Nothing here ever mutates Layer 0.

Standard Library only. Zero external pip packages.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

SCHEMA_VERSION = 1
MAX_ENUMERATED_EPISODES = 120

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
    source_site TEXT,
    service TEXT,
    source_name TEXT,
    kind TEXT NOT NULL DEFAULT 'unknown',
    url TEXT,
    final_url TEXT,
    resource_id TEXT,
    playability TEXT NOT NULL DEFAULT 'unknown',
    state TEXT NOT NULL DEFAULT 'active',
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

CREATE TABLE IF NOT EXISTS cat_entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER,
    release_id INTEGER,
    model TEXT NOT NULL DEFAULT 'free',
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

CREATE INDEX IF NOT EXISTS idx_cat_works_title ON cat_works(title, year);
CREATE INDEX IF NOT EXISTS idx_cat_works_type ON cat_works(work_type, is_18_plus);
CREATE INDEX IF NOT EXISTS idx_cat_works_browse ON cat_works(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_cat_releases_work ON cat_releases(work_id, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_cat_links_release ON cat_links(release_id, rank_score DESC);
CREATE INDEX IF NOT EXISTS idx_cat_links_state ON cat_links(state, playability);
CREATE INDEX IF NOT EXISTS idx_cat_episodes_work ON cat_episodes(work_id, number);
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
    conn.execute(
        "INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


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

    work_ids: dict[str, int] = {}
    for key, acc in works.items():
        head = acc.posts[0]
        title = _post_column(head, "clean_title", default="") or _post_column(head, "title", "Unknown")
        wtype = work_type_for(
            _post_column(head, "content_type", default="movie"),
            int(_post_column(head, "is_animated", default=0) or 0),
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
                int(_post_column(head, "is_animated", default=0) or 0),
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
                " VALUES (?, NULL, ?, ?, ?)",
                (work_id, alias, site, kind),
            )

    conn.commit()
    counters = _project_pages(conn, works, work_ids, release_descriptor, now)
    _finalize(conn, works, work_ids, now)

    summary = {
        "works": len(work_ids),
        "releases": counters["releases"],
        "links": counters["links"],
        "episodes": counters["episodes"],
        "seasons": counters["seasons"],
        "posts": post_count,
        "identity_suspect": counters["suspect"],
        "release_dups": counters["release_dups"],
        "unattributed_links": counters["unattributed"],
        "seconds": round(time.time() - started, 2),
    }
    for key, value in summary.items():
        conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES (?, ?)",
                     (key, str(value)))
    conn.execute("INSERT OR REPLACE INTO cat_projection_meta (key, value) VALUES ('projected_at', ?)",
                 (str(now),))
    conn.commit()
    if verbose:
        print(f"[✓] catalog v2 projected: {summary}", flush=True)
    return summary


def _project_pages(conn, works, work_ids, release_descriptor, now) -> dict:
    counters = {"releases": 0, "links": 0, "episodes": 0, "seasons": 0, "suspect": 0,
                "unattributed": 0, "release_dups": 0}
    episode_index: dict[tuple[int, int, int], int] = {}
    # (work_id, natural print key) -> release_id, so the same print mirrored by a
    # scraper that re-emitted a page collapses onto one row instead of two siblings.
    print_index: dict[tuple[int, tuple], int] = {}

    for key, acc in works.items():
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
                    if season_number == 0 and family == "series":
                        counters["suspect"] += 1
                        conn.execute(
                            "INSERT INTO cat_review_queue (kind, work_id, release_id, page_url, detail, raised_at)"
                            " VALUES ('season_unresolved', ?, NULL, ?, ?, ?)",
                            (work_id, page_url, json.dumps({"label": rel["release_title"],
                                                            "season": str(rel["season"] or "")}), now),
                        )
                    cur = conn.execute(
                        """
                        INSERT INTO cat_releases (work_id, season_number, label, source_site, origin_url,
                            coverage_type, episode_range, resolution, quality_label, source_tag, codec,
                            bit_depth, hdr, container, edition, print_version, release_group, size_bytes,
                            size_per_episode_bytes, audio_languages, audio_channels, audio_codecs,
                            dual_audio, subtitle_mode, subtitle_languages, watermarked, official_print,
                            quality_score, flags, descriptor_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            work_id, season_number or None, rel["release_title"],
                            rel_site, origin_url,
                            coverage, desc.get("episode_range") or "", desc.get("resolution") or "unknown",
                            desc.get("quality_label") or "", desc.get("source_tag") or "unknown",
                            desc.get("codec") or "unknown", int(desc.get("bit_depth") or 0),
                            json.dumps(desc.get("hdr") or []), desc.get("container") or "unknown",
                            desc.get("edition") or "unknown", int(desc.get("version") or 0),
                            "", int(desc.get("size_bytes") or 0),
                            int(desc.get("size_per_episode_bytes") or 0),
                            json.dumps((desc.get("audio") or {}).get("languages") or []),
                            (desc.get("audio") or {}).get("channel_layout") or "unknown",
                            json.dumps((desc.get("audio") or {}).get("codecs") or []),
                            1 if (desc.get("audio") or {}).get("dual_audio") else 0,
                            "hardcoded" if (desc.get("subtitles") or {}).get("hardcoded")
                            else ("external" if (desc.get("subtitles") or {}).get("available") else "none"),
                            json.dumps((desc.get("subtitles") or {}).get("langs") or []),
                            1 if desc.get("watermarked") else 0, 1 if desc.get("official_print") else 0,
                            int(desc.get("quality_score") or 0), json.dumps(_flags_of(desc)),
                            json.dumps(desc, default=str), now,
                        ),
                    )
                    release_id = cur.lastrowid
                    print_index[pkey] = release_id
                    counters["releases"] += 1

                    season_id = _season_id(conn, work_id, season_number, counters)
                    for ep_number in _covered_episodes(desc, coverage, ep_count):
                        ekey = (work_id, season_number, ep_number)
                        episode_id = episode_index.get(ekey)
                        if episode_id is None:
                            ecur = conn.execute(
                                "INSERT INTO cat_episodes (work_id, season_id, number) VALUES (?, ?, ?)",
                                (work_id, season_id, ep_number),
                            )
                            episode_id = ecur.lastrowid
                            episode_index[ekey] = episode_id
                            counters["episodes"] += 1
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
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO cat_links (release_id, work_id, source_site, service,
                            source_name, kind, url, final_url, resource_id, playability, state,
                            ephemeral, protocol, size_bytes, http_status, tier)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (release_id, work_id, rel_site,
                         src["service"], src["source_name"], kind, src["source_url"], src["final_url"],
                         src["resource_id"], playability, _pick_col(src, "status", "active"),
                         int(src["is_temporary"] or 0), _protocol_of(kind, playability),
                         _pick_col(src, "file_size_bytes", None), _pick_col(src, "http_status", None),
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


def _season_id(conn, work_id: int, season_number: int, counters: dict) -> int:
    number = int(season_number or 0)
    existing = conn.execute(
        "SELECT id FROM cat_seasons WHERE work_id = ? AND number = ? AND season_type = 'regular'",
        (work_id, number),
    ).fetchone()
    if existing:
        return existing[0]
    cur = conn.execute(
        "INSERT INTO cat_seasons (work_id, number, season_type) VALUES (?, ?, 'regular')",
        (work_id, number),
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


def _finalize(conn, works, work_ids, now) -> None:
    """Roll up counts, availability, best print per episode and default entitlements."""
    conn.execute(
        """
        UPDATE cat_releases SET
            link_count = (SELECT COUNT(*) FROM cat_links l WHERE l.release_id = cat_releases.id),
            streamable_count = (SELECT COUNT(*) FROM cat_links l WHERE l.release_id = cat_releases.id
                                 AND l.playability IN ('stream', 'both')),
            downloadable_count = (SELECT COUNT(*) FROM cat_links l WHERE l.release_id = cat_releases.id
                                  AND l.playability IN ('download', 'both', 'resolve_required'))
        """
    )
    conn.execute(
        """
        UPDATE cat_links SET rank_score = CASE
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
    conn.execute(
        """
        UPDATE cat_episodes SET best_release_id = (
            SELECT re.release_id FROM cat_release_episodes re
            JOIN cat_releases r ON r.id = re.release_id
            WHERE re.episode_id = cat_episodes.id
              AND r.coverage_type IN ('single_episode', 'episode_range')
              AND r.streamable_count > 0
            ORDER BY r.quality_score DESC, r.id ASC LIMIT 1
        ) WHERE EXISTS (
            SELECT 1 FROM cat_release_episodes re
            JOIN cat_releases r ON r.id = re.release_id
            WHERE re.episode_id = cat_episodes.id
              AND r.coverage_type IN ('single_episode', 'episode_range')
              AND r.streamable_count > 0
        )
        """
    )
    conn.execute(
        """
        UPDATE cat_seasons SET episode_count = (
            SELECT COUNT(*) FROM cat_episodes e WHERE e.season_id = cat_seasons.id)
        """
    )
    conn.execute(
        """
        UPDATE cat_works SET
            release_count = (SELECT COUNT(*) FROM cat_releases r WHERE r.work_id = cat_works.id),
            episode_count = (SELECT COUNT(*) FROM cat_episodes e WHERE e.work_id = cat_works.id),
            site_count = (SELECT COUNT(DISTINCT s.source_site) FROM cat_work_sites s WHERE s.work_id = cat_works.id),
            max_resolution = (
                SELECT r.resolution FROM cat_releases r WHERE r.work_id = cat_works.id
                  AND r.resolution <> 'unknown'
                ORDER BY r.quality_score DESC LIMIT 1),
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
        INSERT OR IGNORE INTO cat_entitlements (work_id, release_id, model, ownership, updated_at)
        SELECT id, NULL, 'free', 'permanent', ? FROM cat_works
        """,
        (now,),
    )
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
                  chapter_title: str | None = None) -> None:
    """Store a learned pack offset (or a chapter name) against stable identity.

    Repeated confirmations accumulate in `confirmed_by` so a single wrong report
    cannot silently shift everyone's playback.
    """
    now = time.time()
    conn.execute(
        """
        INSERT INTO cat_offsets (work_key, season_number, episode_number, release_label,
                                 offset_seconds, chapter_title, confirmed_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(work_key, season_number, episode_number, release_label) DO UPDATE SET
            offset_seconds = excluded.offset_seconds,
            chapter_title = COALESCE(excluded.chapter_title, cat_offsets.chapter_title),
            confirmed_by = cat_offsets.confirmed_by + 1,
            updated_at = excluded.updated_at
        """,
        (work_key, int(season_number or 0), int(episode_number), release_label or "",
         int(offset_seconds), chapter_title, now),
    )
    conn.commit()


def project_db(db_path: Path, *, rev: int | None = None, verbose: bool = True) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return project(conn, rev=rev, verbose=verbose)
    finally:
        conn.close()


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Project the ingest ledger into the catalog v2 tables.")
    parser.add_argument("db", help="Path to a merged catalog database (never a staging DB)")
    parser.add_argument("--rev", type=int, default=None, help="Source revision marker to stamp")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    summary = project_db(Path(args.db).resolve(), rev=args.rev)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
