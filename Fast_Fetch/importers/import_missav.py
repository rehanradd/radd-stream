#!/usr/bin/env python3
"""
import_missav.py — missav.ws (Japanese adult video, JAV) into a dedicated staging vault.

ADULT CONTENT — SCRAPE ONLY, NEVER PUBLISH.
MissAV's whole catalog is 18+ adult video (JAV). Every row this importer writes
carries is_18_plus = 1, asserted here AND by site authority
(fast_fetch.ADULT_SOURCE_SITES contains "missav"), so no title parsing is needed
and none is trusted to do the job alone. Flagged rows must never appear on any
public surface (no listing, no play — the operator panel is the only exception,
NULL = PUBLIC). Do not add a publish path for this site; do not merge its staging
DB into the public catalog without the adult-flag hiding proof (the server-side
redact.adult_clause + the App never receiving is_18_plus at all).

Measured live 2026-11-11 from the hatch VM:

  * ``https://missav.ws/`` is Cloudflare-walled for HTML (403 "Just a moment...")
    from every fetch path tried (urllib, curl, the browser tool). The same wall
    stands on the mirrors ``missav.live`` and ``missav.com`` (the .com host now
    serves a ThisAV portal page, not a video catalog). A stdlib client cannot
    solve a JS challenge, and there is no approved bypass (FlareSolverr: 0).
  * The XML sitemap is NOT walled: ``/sitemap.xml`` (200, 81 KB) is a sitemap
    index with 559 sub-sitemaps — ``sitemap_items_1..520`` (the videos),
    ``sitemap_actresses_1..36``, plus pages/articles/tweets. Each items file
    holds up to ~13,000 video URLs (items_1 is 16 MB). The ``<url>`` entries
    carry no title/poster metadata, only ``<loc>`` plus ``xhtml:link``
    alternates — the English page is ``/dmNN/en/<code>``.
  * A video page (``https://missav.ws/dm32/en/qmill-001``) carries its metadata in
    OpenGraph tags (``og:title``, ``og:image``, ``og:video:release_date``,
    ``og:video:duration``, keywords) and its HLS playlist as an m3u8 URL
    reconstructed from obfuscated pipe-delimited JavaScript. The m3u8
    deobfuscation is NOT implemented here — it is a Phase C crack task (the
    page must be reachable first, and it is not from a walled host).

So this importer is sitemap-first by design. The default sync enumerates video
URLs + JAV codes from the sitemap and stages one post per video: the code is the
title (JAV titles are identified by code), the video page is the bridge source
(``playback_type "url"``, status ``unverified`` — never claimed playable), and
``is_18_plus = 1``. When a host CAN reach the video pages (the Oracle VM may —
its IP is not the flagged egress proxy), ``--enrich`` fetches each page and
upgrades the stub with the real OpenGraph title, poster, release date, duration
and keywords; a re-run with ``--enrich`` upserts the same canonical keys, so
enrichment is a later pass, not a second scrape. If a page 403s, the stub stands
and the failure is counted, never fatal.

Isolation is the whole point: this writes only to the vault named by ``--db``,
which defaults to ``/home/ubuntu/radd-stream-data/missav.db``. It never imports
the production ``fast_fetch.db``/merged catalog and never runs the unified
``save_scraped_data`` path. A later ``merge_catalogs.py`` run is the only thing
allowed to bring these rows into the unified catalog (where
``save_scraped_data`` preserves the flag — ``bool(incoming) or is_adult_title``
— and the upsert takes ``MAX(is_18_plus)``).

Stdlib only. Polite by default (sequential fetches, a 0.25 s floor between
request starts) because this runs on a one-core box. Sitemap files are large
(up to 16 MB); they are fetched one at a time and the run is resumable via
``sitemap_cache`` (a processed items file is never re-fetched).

Usage:
    python3 -S Fast_Fetch/importers/import_missav.py sync --limit 5
    python3 -S Fast_Fetch/importers/import_missav.py sync --limit 5 --db /tmp/missav.db
    python3 -S Fast_Fetch/importers/import_missav.py sync --limit 200 --enrich
    python3 -S Fast_Fetch/importers/import_missav.py verify
    python3 -S Fast_Fetch/importers/import_missav.py stats
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch  # noqa: E402  (path bootstrap must run first)

try:
    from domain_resolver import get_active_base_url, resolve_if_dead
except Exception:  # noqa: BLE001 - registry wiring is optional offline
    def get_active_base_url(site_name, fallback_default=None, registry_path=None):  # type: ignore
        return fallback_default or ""

    def resolve_if_dead(site_name, registry_path=None):  # type: ignore
        return ""

SITE = "missav"
SITE_NAME = "missav"
DEFAULT_BASE_URL = "https://missav.ws"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/missav.db")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = 30
SITEMAP_TIMEOUT = 60
DEFAULT_DELAY = 0.25

SERVICE = "missav"
SERVICE_TIER = 1
PLAYBACK_URL = "url"

# A video URL is https://missav.ws/dm32/en/qmill-001 (English) or
# https://missav.ws/dm32/qmill-001 (default language). The code is the last
# path segment: 2-6 letters, optional hyphen, 2-5 digits (JAV code shape).
CODE_RE = re.compile(r"([A-Za-z]{2,6}-?\d{2,5})$")
URL_BLOCK_RE = re.compile(r"<url>(.*?)</url>", re.S | re.I)
LOC_RE = re.compile(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", re.I)
EN_ALT_RE = re.compile(
    r"""<xhtml:link[^>]+rel=["']alternate["'][^>]+hreflang=["']en["'][^>]+href=["']([^"']+)["']""",
    re.I)
EN_ALT_RE2 = re.compile(
    r"""<xhtml:link[^>]+hreflang=["']en["'][^>]+href=["']([^"']+)["']""",
    re.I)
SITEMAP_LOC_RE = re.compile(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", re.I)

# OpenGraph tags on a video page (the metadata source when --enrich runs).
OG_RE = re.compile(
    r"""<meta[^>]+property=["']og:([^"']+)["'][^>]+content=["']([^"']*)["']""",
    re.I)
OG_RE2 = re.compile(
    r"""<meta[^>]+content=["']([^"']*)["'][^>]+property=["']og:([^"']+)["']""",
    re.I)
KEYWORDS_RE = re.compile(
    r"""<meta[^>]+name=["']keywords["'][^>]+content=["']([^"']*)["']""",
    re.I)


def log(message: str) -> None:
    print(message, flush=True)


def _clean_title(title: str | None) -> str:
    text = html_mod.unescape(str(title or "")).strip()
    text = re.sub(r"""\s+""", " ", text)
    return text


def http_get(url: str, timeout: int = PAGE_TIMEOUT) -> tuple:
    """One GET. Returns (status, text). Transport failure is (0, "")."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "ignore")
        except Exception:
            return e.code, ""
    except Exception:
        return 0, ""


def code_from_url(url: str) -> str | None:
    """The JAV code is the last path segment (``qmill-001``)."""
    path = urllib.parse.urlparse(url or "").path.rstrip("/")
    if not path:
        return None
    slug = path.split("/")[-1]
    m = CODE_RE.search(slug)
    return m.group(1).lower() if m else None


def parse_sitemap_index(xml: str) -> list:
    """Sitemap-index locs, items files first (the videos), then the rest."""
    locs = [m.group(1).strip() for m in SITEMAP_LOC_RE.finditer(xml or "")]
    items = [u for u in locs if "/sitemap_items_" in u]
    rest = [u for u in locs if "/sitemap_items_" not in u]
    return items + rest


def parse_items_sitemap(xml: str) -> list:
    """One items sitemap -> [(english video URL, code)] in document order.

    Each ``<url>`` block holds a default-language ``<loc>`` and an
    ``hreflang="en"`` alternate; the English page is the canonical video URL.
    A block with no usable code is skipped, never staged.
    """
    out = []
    seen = set()
    for block in URL_BLOCK_RE.finditer(xml or ""):
        body = block.group(1)
        loc_m = LOC_RE.search(body)
        if not loc_m:
            continue
        en_m = EN_ALT_RE.search(body) or EN_ALT_RE2.search(body)
        url = (en_m.group(1).strip() if en_m else loc_m.group(1).strip())
        code = code_from_url(url)
        if not code or code in seen:
            continue
        seen.add(code)
        out.append((url, code))
    return out


def parse_video_page(html: str) -> dict:
    """OpenGraph metadata off one video page (the --enrich source).

    Returns title, poster, release_date, duration (seconds, as text), keywords.
    Anything missing comes back None — the sitemap stub stands for it.
    """
    og: dict = {}
    for pattern in (OG_RE, OG_RE2):
        for m in pattern.finditer(html or ""):
            if pattern is OG_RE:
                key, value = m.group(1).lower(), m.group(2)
            else:
                value, key = m.group(1), m.group(2).lower()
            og.setdefault(key, value)
    kw_m = KEYWORDS_RE.search(html or "")
    keywords = _clean_title(kw_m.group(1)) if kw_m else None
    duration = og.get("video:duration")
    try:
        duration_s = int(float(duration)) if duration else None
    except (TypeError, ValueError):
        duration_s = None
    release = og.get("video:release_date") or og.get("article:published_time")
    year = None
    if release:
        ym = re.search(r"(\d{4})", release)
        year = int(ym.group(1)) if ym else None
    return {
        "title": _clean_title(og.get("title")) or None,
        "poster_url": og.get("image") or None,
        "release_date": (release or "")[:10] or None,
        "year": year,
        "duration": str(duration_s) if duration_s else None,
        "keywords": keywords,
    }


def build_record(url: str, code: str, enriched: dict | None = None) -> dict:
    """One post per video. The sitemap stub carries the code as its title;
    enrichment (when the page was reachable) upgrades it in place.

    is_18_plus is 1 unconditionally: the whole catalog is adult by site
    authority, not by title guessing. Nothing here may ever set it to 0.
    """
    enriched = enriched or {}
    title = enriched.get("title") or code.upper()
    return {
        "canonical_key": "missav-%s" % code,
        "title": title, "clean_title": title,
        "year": enriched.get("year"), "media_type": "movie",
        "poster_url": enriched.get("poster_url"), "backdrop_url": None,
        "backdrop_urls": None, "imdb_id": None, "tmdb_id": None,
        "imdb_rating": None, "synopsis": None,
        "genres": enriched.get("keywords"), "director": None,
        "cast_names": None,
        "duration": enriched.get("duration"),
        "release_date": enriched.get("release_date"),
        "languages": "Japanese", "industry": None, "country": "Japan",
        "seasons": None, "url": url, "slug": code,
        "is_18_plus": 1, "is_animated": 0, "source_site": SITE,
        "raw_meta": {"jav_code": code, "enriched": bool(enriched)},
        "releases": [{
            "label": "MissAV", "quality": None, "resolution": None,
            "size_bytes": None, "codec": None,
            "season": None, "episode": None, "audio": "Japanese",
            "bridge_url": url,
            "raw_meta": {"jav_code": code},
            "sources": [{
                "source_name": SERVICE, "service": SERVICE,
                "service_tier": SERVICE_TIER,
                "resource_id": code,
                "source_url": url, "final_url": url,
                "playback_type": PLAYBACK_URL,
                "status": "unverified", "is_temporary": 0, "quality": None,
                "mime_type": None,
                "last_checked": int(time.time()),
                "raw_meta": {"bridge_only": True},
            }],
        }],
    }


# ---------------------------------------------------------------------------
# Staging database (same shape as import_megacartoons / import_castle)
# ---------------------------------------------------------------------------

_SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS sitemap_cache (
    loc TEXT PRIMARY KEY,
    lastmod TEXT,
    slug TEXT,
    scraped INTEGER DEFAULT 0,
    raw_json TEXT,
    error_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS posts (
    canonical_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    clean_title TEXT NOT NULL,
    year INTEGER,
    media_type TEXT,
    poster_url TEXT,
    backdrop_url TEXT,
    backdrop_urls TEXT,
    imdb_id TEXT,
    tmdb_id TEXT,
    imdb_rating TEXT,
    synopsis TEXT,
    genres TEXT,
    director TEXT,
    cast_names TEXT,
    duration TEXT,
    release_date TEXT,
    languages TEXT,
    industry TEXT,
    country TEXT,
    seasons TEXT,
    url TEXT,
    slug TEXT,
    is_18_plus INTEGER DEFAULT 0,
    is_animated INTEGER DEFAULT 0,
    source_site TEXT DEFAULT 'missav',
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_meta TEXT
);

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_canonical_key TEXT NOT NULL,
    label TEXT,
    quality TEXT,
    resolution TEXT,
    size_bytes INTEGER,
    codec TEXT,
    season_number INTEGER,
    episode_number INTEGER,
    audio_languages TEXT,
    bridge_url TEXT,
    origin_url TEXT,
    raw_meta TEXT,
    FOREIGN KEY (post_canonical_key) REFERENCES posts(canonical_key)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    source_name TEXT,
    service TEXT,
    service_tier INTEGER DEFAULT 1,
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'url',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    mime_type TEXT,
    last_checked INTEGER,
    raw_meta TEXT,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_missav_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_missav_posts_key ON posts(canonical_key);
CREATE INDEX IF NOT EXISTS idx_missav_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_missav_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_missav_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_missav_sitemap_scraped ON sitemap_cache(scraped);
"""

POST_COLUMNS = (
    "canonical_key", "title", "clean_title", "year", "media_type", "poster_url",
    "backdrop_url", "backdrop_urls", "imdb_id", "tmdb_id", "imdb_rating",
    "synopsis", "genres", "director", "cast_names", "duration", "release_date",
    "languages", "industry", "country", "seasons", "url", "slug",
    "is_18_plus", "is_animated", "source_site", "raw_meta",
)
RELEASE_COLUMNS = (
    "post_canonical_key", "label", "quality", "resolution", "size_bytes",
    "codec", "season_number", "episode_number", "audio_languages",
    "bridge_url", "origin_url", "raw_meta",
)
SOURCE_COLUMNS = (
    "release_id", "source_name", "service", "service_tier", "resource_id",
    "source_url", "final_url", "playback_type", "status", "is_temporary",
    "quality", "mime_type", "last_checked", "raw_meta",
)
INTEGER_COLUMNS = {
    "year", "size_bytes", "season_number", "episode_number", "is_18_plus",
    "is_animated", "is_temporary", "last_checked", "service_tier",
}


def _add_missing_columns(conn: sqlite3.Connection, table: str, wanted) -> None:
    have = {c[1] for c in conn.execute(f"PRAGMA table_info({table});").fetchall()}
    for col in wanted:
        if col in have:
            continue
        decl = "INTEGER" if col in INTEGER_COLUMNS else "TEXT"
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl};")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_TABLES)
    _add_missing_columns(conn, "posts", POST_COLUMNS + ("scraped_at",))
    _add_missing_columns(conn, "releases", RELEASE_COLUMNS)
    _add_missing_columns(conn, "sources", SOURCE_COLUMNS)
    conn.executescript(_SCHEMA_INDEXES)


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=(),
                   conn: sqlite3.Connection | None = None) -> dict:
    """Upsert records; a re-export of one item replaces its releases+sources."""
    own = conn is None
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0}
    if own:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=60)
        conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        for post in posts or ():
            if not post or not post.get("clean_title") or not post.get("canonical_key"):
                totals["skipped"] += 1
                continue
            values = dict(post)
            values["source_site"] = SITE
            values["raw_meta"] = json.dumps(post.get("raw_meta") or {},
                                            ensure_ascii=False)
            columns = [c for c in POST_COLUMNS if c in values]
            updates = ", ".join(
                f"{c} = excluded.{c}" for c in columns
                if c not in ("canonical_key", "scraped_at", "is_18_plus", "is_animated"))
            conn.execute(
                f"INSERT INTO posts ({', '.join(columns)})"
                f" VALUES ({', '.join('?' for _ in columns)})"
                f" ON CONFLICT(canonical_key) DO UPDATE SET "
                "is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus), "
                "is_animated = MAX(posts.is_animated, excluded.is_animated), "
                f"{updates}",
                [values[c] for c in columns])
            conn.execute(
                "DELETE FROM sources WHERE release_id IN ("
                " SELECT id FROM releases WHERE post_canonical_key = ?"
                " AND COALESCE(origin_url,'') = COALESCE(?, ''))",
                (post["canonical_key"], post.get("url")))
            conn.execute(
                "DELETE FROM releases WHERE post_canonical_key = ?"
                " AND COALESCE(origin_url,'') = COALESCE(?, '')",
                (post["canonical_key"], post.get("url")))
            for rel in post.get("releases") or []:
                cur = conn.execute(
                    "INSERT INTO releases (post_canonical_key, label, quality,"
                    " resolution, size_bytes, codec, season_number, episode_number,"
                    " audio_languages, bridge_url, origin_url, raw_meta)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (post["canonical_key"], rel.get("label"), rel.get("quality"),
                     rel.get("resolution"), rel.get("size_bytes"), rel.get("codec"),
                     rel.get("season"), rel.get("episode"), rel.get("audio"),
                     rel.get("bridge_url"), post.get("url"),
                     json.dumps(rel.get("raw_meta") or {}, ensure_ascii=False)))
                totals["releases_written"] += 1
                for src in rel.get("sources") or []:
                    conn.execute(
                        "INSERT INTO sources (release_id, source_name, service,"
                        " service_tier, resource_id, source_url, final_url,"
                        " playback_type, status, is_temporary, quality, mime_type,"
                        " last_checked, raw_meta)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (cur.lastrowid, src.get("source_name") or SERVICE,
                         src.get("service") or SERVICE,
                         src.get("service_tier", SERVICE_TIER),
                         src.get("resource_id"), src.get("source_url"),
                         src.get("final_url"), src.get("playback_type")
                         or PLAYBACK_URL,
                         src.get("status") or "unverified",
                         src.get("is_temporary") or 0, src.get("quality"),
                         src.get("mime_type"), src.get("last_checked"),
                         json.dumps(src.get("raw_meta") or {}, ensure_ascii=False)))
                    totals["sources_written"] += 1
            totals["posts_written"] += 1
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return totals


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    """Count staging rows; the gate audit behind ``verify``."""
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        return {
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "sources_unverified": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE status = 'unverified'").fetchone()[0],
            "flagged_18_plus": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "posts_without_release": conn.execute(
                "SELECT COUNT(*) FROM posts p WHERE NOT EXISTS ("
                "SELECT 1 FROM releases r WHERE r.post_canonical_key = p.canonical_key)"
                ).fetchone()[0],
            "sources_without_final_url": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE final_url IS NULL OR final_url = ''"
                ).fetchone()[0],
            "sitemaps_done": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0],
        }
    finally:
        conn.close()


def verify_db(db_path: Path | str = DEFAULT_DB_PATH) -> tuple[bool, dict]:
    """Gate audit: every post has a release, every source a final URL, every
    post flagged 18+.

    An ``unverified`` source is not a failure — it is a bridge whose page the
    host could not reach (or whose m3u8 is still uncracked); it is stored,
    never claimed playable. An unflagged post IS a failure.
    """
    result = stats(db_path)
    ok = (result["posts_without_release"] == 0
          and result["sources_without_final_url"] == 0
          and result["flagged_18_plus"] == result["posts"]
          and result["posts"] > 0)
    return ok, result


# ---------------------------------------------------------------------------
# Sync (sitemap index -> items files -> stage; --enrich upgrades stubs)
# ---------------------------------------------------------------------------

def _mark_sitemap(conn: sqlite3.Connection, loc: str, scraped: int = 1) -> None:
    slug = loc.rstrip("/").split("/")[-1]
    conn.execute(
        "INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, ?)"
        " ON CONFLICT(loc) DO UPDATE SET scraped = excluded.scraped",
        (loc, slug, scraped))
    conn.commit()


def sync(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
         base_url: str | None = None, delay: float = DEFAULT_DELAY,
         registry_path: str | Path | None = None,
         fetcher=None, enrich: bool = False) -> dict:
    """Enumerate the sitemap and stage up to ``limit`` videos.

    ``fetcher`` is ``http_get`` by default; tests pass a fake. A video page
    fetch that fails (Cloudflare 403, timeout) keeps the sitemap stub — the
    failure is counted in ``pages_failed``, never fatal, and the video stays
    staged as a bridge-only ``unverified`` row. ``--enrich`` turns page
    fetching on; without it the sync is sitemap-only (fast, and the only mode
    that works from a challenged host).
    """
    fetch = fetcher or (lambda url, timeout=PAGE_TIMEOUT: http_get(url, timeout))
    base = (base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL,
                                            registry_path)).rstrip("/")
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0, "sitemaps_fetched": 0, "sitemaps_failed": 0,
              "pages_fetched": 0, "pages_failed": 0, "pages_enriched": 0,
              "base_url": base}
    limit = limit if limit is not None else 200

    def _run_once(base_url_: str) -> list:
        status, xml = fetch(base_url_ + "/sitemap.xml", SITEMAP_TIMEOUT)
        if status != 200 or not xml:
            return []
        return parse_sitemap_index(xml)

    item_sitemaps = _run_once(base)
    if not item_sitemaps and fetcher is None:
        fresh = resolve_if_dead(SITE_NAME, registry_path)
        if fresh and fresh.rstrip("/") != base:
            log("[i] tracker moved %s -> %s; retrying once" % (base, fresh))
            base = fresh.rstrip("/")
            totals["base_url"] = base
            item_sitemaps = _run_once(base)
    if not item_sitemaps:
        return totals

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        done = {r[0] for r in conn.execute(
            "SELECT loc FROM sitemap_cache WHERE scraped = 1").fetchall()}
        for loc in item_sitemaps:
            if totals["posts_written"] >= limit:
                break
            if loc in done:
                continue
            time.sleep(delay)
            status, xml = fetch(loc, SITEMAP_TIMEOUT)
            if status != 200 or not xml:
                totals["sitemaps_failed"] += 1
                continue
            totals["sitemaps_fetched"] += 1
            videos = parse_items_sitemap(xml)
            finished = True
            for url, code in videos:
                if totals["posts_written"] >= limit:
                    finished = False
                    break
                enriched = None
                if enrich:
                    time.sleep(delay)
                    totals["pages_fetched"] += 1
                    p_status, p_html = fetch(url)
                    if p_status != 200 or not p_html:
                        totals["pages_failed"] += 1
                    else:
                        enriched = parse_video_page(p_html)
                        totals["pages_enriched"] += 1
                record = build_record(url, code, enriched)
                written = export_staging(db_path, posts=[record], conn=conn)
                for key in ("posts_written", "releases_written",
                            "sources_written", "skipped"):
                    totals[key] += written[key]
            conn.commit()
            # Only a fully processed file is marked done: a run cut short by
            # --limit must re-walk it next time (upserts make that safe).
            if finished:
                _mark_sitemap(conn, loc, 1)
                done.add(loc)
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MissAV staging importer (18+ — scrape only)")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_cmd = sub.add_parser("sync", help="enumerate the sitemap + stage videos")
    sync_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync_cmd.add_argument("--limit", type=int, default=200)
    sync_cmd.add_argument("--base-url", default=None)
    sync_cmd.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    sync_cmd.add_argument("--registry", default=None)
    sync_cmd.add_argument("--enrich", action="store_true",
                          help="fetch each video page for OpenGraph title/poster "
                               "(only works from a host the site does not challenge)")

    verify_cmd = sub.add_parser("verify", help="gate-audit a staging database")
    verify_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))

    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "sync":
        totals = sync(db_path=args.db, limit=args.limit,
                      base_url=args.base_url, delay=args.delay,
                      registry_path=args.registry, enrich=args.enrich)
        print(json.dumps(totals, indent=2, ensure_ascii=False))
        return 0
    if args.command == "verify":
        ok, result = verify_db(args.db)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("[✓] verify OK" if ok else "[✗] verify FAILED")
        return 0 if ok else 1
    result = stats(args.db)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
