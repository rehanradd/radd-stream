#!/usr/bin/env python3
"""
import_humtv.py — hum.tv (official HUM TV) into a dedicated staging vault.

Licensing, measured 2026-10-29: hum.tv is the broadcaster's own WordPress site,
its robots.txt allows everything except /wp-admin/, its WP REST catalog is open
(5,625 posts), and every episode page plays from the official HUM TV YouTube
channel (@HUMTV) — oEmbed for the embedded video returns author_name "HUM TV",
author_url https://www.youtube.com/@HUMTV. There are no download mirrors on the
site; the only source links stored here are those official embeds. This is the
licensed catalog pointing at the rightsholder's own player, not a second copy of
someone else's pirated metadata.

Stdlib only. Usage:
    python3 -S Fast_Fetch/importers/import_humtv.py sync
    python3 -S Fast_Fetch/importers/import_humtv.py crawl --workers 1 --delay 0.5
    python3 -S Fast_Fetch/importers/import_humtv.py verify --limit 200
    python3 -S Fast_Fetch/importers/import_humtv.py stats
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch

SITE = "humtv"
BASE_URL = "https://hum.tv"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/humtv_staging.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

REST_URL = f"{BASE_URL}/wp-json/wp/v2/posts"
REST_PER_PAGE = 100
SITEMAP_TIMEOUT = 30
PAGE_TIMEOUT = 30
QUEUED_SCRAPE_STATES = (0, 2)
MAX_SCRAPE_ATTEMPTS = 3
FAILURE_LEDGER_LIMIT = 8
DEFAULT_SOURCE_STATUS = "unverified"
RATE_LIMIT_STATUS = 429
PLAYBACK_IFRAME = "iframe"
YOUTUBE_OEMBED = "https://www.youtube.com/oembed"

# The directive's hard floor: stop before the box thrashes.
MIN_MEM_AVAILABLE_MB = 2500
MIN_SWAP_FREE_MB = 800

STOP_REQUESTED = False
_RATE_LIMITED = threading.Event()

PENDING_SELECT = (
    "SELECT loc, lastmod, slug, raw_json, scraped, error_count FROM sitemap_cache "
    "WHERE scraped IN (?, ?) OR (scraped = -1 AND error_count < ?) ORDER BY loc;"
)

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
    "release_id", "source_name", "service", "resource_id", "source_url",
    "final_url", "playback_type", "status", "is_temporary", "quality",
    "last_checked",
)
INTEGER_COLUMNS = {
    "year", "size_bytes", "season_number", "episode_number", "is_18_plus",
    "is_animated", "is_temporary", "last_checked",
}

OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']',
    re.I)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']*)["\']',
    re.I)
IFRAME_RE = re.compile(r"<iframe\b[^>]*>", re.I | re.S)
EMBED_SRC_RE = re.compile(
    r"""src\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:embed/|watch\?v=|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})", re.I)
VIMEO_RE = re.compile(r"(?:player\.)?vimeo\.com/(?:video/)?(\d+)", re.I)
EPISODE_RE = re.compile(
    r"(?:\s*[–—\-:|]\s*|\s+)(?:S(\d{1,2})\s*[–—\-]\s*)?Episode\s*"
    r"(?:[–—\-:]\s*)?(\d{1,4})\s*$",
    re.I)
SLUG_SEASON_RE = re.compile(r"(?:^|-)(?:s|season-?)(\d{1,2})(?:-|$)", re.I)
SLUG_EPISODE_RE = re.compile(r"(?:^|-)episode-?(\d{1,4})(?:-|$)", re.I)


class RateLimited(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def _request(url: str, accept: str | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def http_get(url: str, timeout: int = PAGE_TIMEOUT, retries: int = 1,
             debug: dict | None = None) -> tuple[int, str, str]:
    """Returns (status, final_url, body). Status 0 means transport failure."""
    last = (0, url, "")
    for attempt in range(max(0, retries) + 1):
        if attempt:
            time.sleep(0.9 * attempt)
        try:
            with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                return resp.status, resp.geturl(), body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            last = (exc.code, url, body)
            if exc.code != RATE_LIMIT_STATUS:
                return last
        except Exception as exc:  # URLError, timeout, reset, bad TLS
            last = (0, url, "")
            if debug is not None:
                debug.setdefault("transport_error", f"{type(exc).__name__}: {exc}")
    return last


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _year_from_date(value: str | None) -> int | None:
    match = re.match(r"(\d{4})-", value or "")
    return int(match.group(1)) if match else None


def series_base(slug: str | None) -> str:
    """'ishq-murshid-s2-episode-07' -> 'ishq-murshid' (one work, many episodes)."""
    base = re.sub(r"-(?:s\d{1,2}-)?episode-\d{1,4}$", "", (slug or "").strip("-"))
    return base or (slug or "")


def series_year_map(rows) -> dict[str, int]:
    """First publication year per series base.

    A drama that starts in December and runs into January must stay one work;
    keying each page on its own post date would split it into two canonical keys.
    """
    years: dict[str, int] = {}
    for row in rows:
        slug = row["slug"] or row["loc"].rstrip("/").rsplit("/", 1)[-1]
        year = _year_from_date(row["lastmod"])
        if year is None:
            continue
        base = series_base(slug)
        if base not in years or year < years[base]:
            years[base] = year
    return years


def _clean_title(raw: str) -> str:
    title = re.sub(r"\s*[–—\-]\s*Hum TV\s*$", "", raw or "", flags=re.I)
    return re.sub(r"\s+", " ", title).strip()


def parse_title(raw: str, slug: str) -> dict:
    """Splits "Meesni – Episode 01" into a work title plus season/episode."""
    title = _clean_title(raw)
    season = episode = None
    match = EPISODE_RE.search(title)
    if match:
        season = int(match.group(1)) if match.group(1) else None
        episode = int(match.group(2))
        title = title[: match.start()].strip(" -–—:|")
    else:
        m = SLUG_EPISODE_RE.search(slug)
        if m:
            episode = int(m.group(1))
    if season is None:
        m = SLUG_SEASON_RE.search(slug)
        if m:
            season = int(m.group(1))
    return {"title": title or _clean_title(raw), "season": season,
            "episode": episode}


def parse_page(html: str, loc: str, year: int | None) -> dict | None:
    """Returns the staging record for one catalog page, or None without a player."""
    title_match = OG_TITLE_RE.search(html)
    # WordPress emits og:title with numeric entities (&#8211; for an en dash).
    raw_title = html_mod.unescape(title_match.group(1)) if title_match else ""
    parsed = parse_title(raw_title, loc.rstrip("/").rsplit("/", 1)[-1])
    title = parsed["title"]
    if not title:
        return None
    sources = []
    seen = set()
    for tag in IFRAME_RE.findall(html):
        src_match = EMBED_SRC_RE.search(tag)
        if not src_match:
            continue
        src = (src_match.group(1) or src_match.group(2) or src_match.group(3) or "")
        src = html_mod.unescape(src).strip()
        youtube = YOUTUBE_RE.search(src)
        if youtube:
            video_id = youtube.group(1)
            url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            vimeo = VIMEO_RE.search(src)
            if not vimeo:
                continue
            video_id = vimeo.group(1)
            url = f"https://vimeo.com/{video_id}"
        if (video_id, url) in seen:
            continue
        seen.add((video_id, url))
        sources.append({"video_id": video_id, "url": url})
    if not sources:
        return None
    poster_match = OG_IMAGE_RE.search(html)
    poster = html_mod.unescape(poster_match.group(1)) if poster_match else None
    slug = loc.rstrip("/").rsplit("/", 1)[-1]
    # One release per published episode; the embed is its watch link.
    label = title
    if parsed["episode"] is not None:
        label += f" Episode {parsed['episode']:02d}"
    release_meta = {
        "page_kind": "episode" if parsed["episode"] is not None else "feature",
        "season": parsed["season"],
        "episode": parsed["episode"],
        "embed_hosts": [urllib.parse.urlsplit(s["url"]).netloc for s in sources],
    }
    record = {
        "canonical_key": fast_fetch.generate_canonical_key(title, year),
        "title": title,
        "clean_title": title,
        "year": year,
        "media_type": "series",
        "poster_url": poster,
        "synopsis": None,
        "seasons": json.dumps([parsed["season"]]) if parsed["season"] else None,
        "url": loc,
        "slug": slug,
        "is_18_plus": fast_fetch.is_adult_title(title, slug),
        "is_animated": fast_fetch.looks_animated(title),
        "releases": [{
            "label": label,
            "quality": None,
            "resolution": None,
            "season": parsed["season"],
            "episode": parsed["episode"],
            "raw_meta": release_meta,
            "sources": [{
                "source_name": SITE,
                "service": "youtube" if "youtube" in s["url"] else "vimeo",
                "resource_id": s["video_id"],
                "source_url": s["url"],
                "playback_type": PLAYBACK_IFRAME,
                "status": DEFAULT_SOURCE_STATUS,
                "is_temporary": 0,
                "quality": None,
            } for s in sources],
        }],
    }
    return record


def sync_catalog(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                 verbose: bool = True) -> dict:
    """Seeds sitemap_cache from the open WP REST catalog (gives a post date)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    totals = {"pages": 0, "inserted": 0, "updated": 0, "errors": 0}
    try:
        ensure_schema(conn)
        status, _final, body = http_get(
            f"{REST_URL}?per_page=1&_fields=id", timeout=SITEMAP_TIMEOUT)
        if status != 200:
            log(f"[!] [{SITE}] REST probe -> HTTP {status}")
            return totals
        total = 0
        page = 1
        while True:
            if STOP_REQUESTED:
                break
            url = (f"{REST_URL}?per_page={REST_PER_PAGE}&page={page}"
                   "&_fields=date,slug,link,title")
            status, _final, body = http_get(url, timeout=SITEMAP_TIMEOUT)
            if status == RATE_LIMIT_STATUS:
                log(f"[!] [{SITE}] REST page {page} -> 429, stopping sync")
                break
            if status != 200:
                if page == 1:
                    totals["errors"] += 1
                    log(f"[!] [{SITE}] REST page {page} -> HTTP {status}")
                break
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                totals["errors"] += 1
                break
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                link = item.get("link")
                if not link:
                    continue
                row = conn.execute(
                    "SELECT loc FROM sitemap_cache WHERE loc = ?", (link,)).fetchone()
                if row:
                    totals["updated"] += 1
                    continue
                conn.execute(
                    "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json,"
                    " error_count) VALUES (?, ?, ?, 0, '{}', 0)",
                    (link, item.get("date"), item.get("slug")))
                totals["inserted"] += 1
            conn.commit()
            totals["pages"] += 1
            total += len(payload)
            if verbose and (page == 1 or page % 10 == 0):
                log(f"    sync page {page}: {total} posts queued")
            if limit and total >= limit:
                break
            page += 1
            time.sleep(0.3)
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Staging database
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
    source_site TEXT DEFAULT 'humtv',
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
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'iframe',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_humtv_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_humtv_posts_key ON posts(canonical_key);
CREATE INDEX IF NOT EXISTS idx_humtv_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_humtv_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_humtv_releases_post ON releases(post_canonical_key);
"""


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


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0}
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
                if c != "canonical_key" and c != "scraped_at")
            conn.execute(
                f"INSERT INTO posts ({', '.join(columns)})"
                f" VALUES ({', '.join('?' for _ in columns)})"
                f" ON CONFLICT(canonical_key) DO UPDATE SET {updates}",
                [values[c] for c in columns])
            for rel in post.get("releases") or []:
                conn.execute(
                    "DELETE FROM sources WHERE release_id IN ("
                    " SELECT id FROM releases WHERE post_canonical_key = ?"
                    " AND COALESCE(origin_url,'') = COALESCE(?, ''))",
                    (post["canonical_key"], post.get("url")))
                conn.execute(
                    "DELETE FROM releases WHERE post_canonical_key = ?"
                    " AND COALESCE(origin_url,'') = COALESCE(?, '')",
                    (post["canonical_key"], post.get("url")))
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
                        " resource_id, source_url, final_url, playback_type, status,"
                        " is_temporary, quality, last_checked)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (cur.lastrowid, src.get("source_name"), src.get("service"),
                         src.get("resource_id"), src.get("source_url"),
                         src.get("final_url"), src.get("playback_type"),
                         src.get("status") or DEFAULT_SOURCE_STATUS,
                         src.get("is_temporary") or 0, src.get("quality"),
                         src.get("last_checked")))
                    totals["sources_written"] += 1
            totals["posts_written"] += 1
        conn.commit()
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def _failure(kind: str, http_status: int | None = None, final_url: str | None = None,
             detail: str | None = None, exception: str | None = None) -> dict:
    return {"kind": kind, "http_status": http_status, "final_url": final_url,
            "detail": detail, "exception": exception, "at": int(time.time())}


def _bump_error(db_path: Path, loc: str, failure: dict, park_now: bool = False) -> None:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT scraped, raw_json, error_count FROM sitemap_cache WHERE loc = ?",
            (loc,)).fetchone()
        errors = int((row["error_count"] if row else 0) or 0) + 1
        try:
            ledger = json.loads(row["raw_json"] or "{}") if row else {}
        except json.JSONDecodeError:
            ledger = {}
        failures = ledger.get("failures") or []
        failures.append(failure)
        ledger["failures"] = failures[-FAILURE_LEDGER_LIMIT:]
        ledger["last_note"] = failure.get("detail") or failure.get("kind")
        scraped = 1 if park_now else (-1 if errors >= MAX_SCRAPE_ATTEMPTS else 2)
        conn.execute(
            "UPDATE sitemap_cache SET scraped = ?, error_count = ?, raw_json = ?"
            " WHERE loc = ?",
            (scraped, errors, json.dumps(ledger, ensure_ascii=False), loc))
        conn.commit()
    finally:
        conn.close()


def _mark_scraped(db_path: Path, locs) -> None:
    if not locs:
        return
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.executemany(
            "UPDATE sitemap_cache SET scraped = 1, error_count = 0 WHERE loc = ?",
            [(loc,) for loc in locs])
        conn.commit()
    finally:
        conn.close()


def memory_ok(meminfo: str | None = None) -> tuple[bool, str]:
    """Reads /proc/meminfo; the directive's floor is 2,500 MB free / 800 MB swap."""
    text = meminfo
    if text is None:
        try:
            text = Path("/proc/meminfo").read_text()
        except OSError:
            return True, "meminfo unavailable"
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0].rstrip(":")] = int(parts[1]) // 1024
    available = values.get("MemAvailable", 10 ** 9)
    swap_free = values.get("SwapFree", 10 ** 9)
    if available < MIN_MEM_AVAILABLE_MB:
        return False, f"MemAvailable {available} MB < {MIN_MEM_AVAILABLE_MB} MB"
    if swap_free < MIN_SWAP_FREE_MB:
        return False, f"SwapFree {swap_free} MB < {MIN_SWAP_FREE_MB} MB"
    return True, f"MemAvailable {available} MB, SwapFree {swap_free} MB"


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 1, delay: float = 0.5, batch_size: int = 20,
                  verbose: bool = True) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if workers != 1:
        log(f"[!] [{SITE}] workers={workers} refused: this fleet runs one worker per site.")
        workers = 1
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        rows = conn.execute(
            PENDING_SELECT, (*QUEUED_SCRAPE_STATES, MAX_SCRAPE_ATTEMPTS)).fetchall()
        year_map = series_year_map(conn.execute(
            "SELECT loc, lastmod, slug FROM sitemap_cache").fetchall())
    finally:
        conn.close()
    if limit:
        rows = rows[:limit]
    _RATE_LIMITED.clear()
    ok, reason = memory_ok()
    if not ok:
        log(f"[!] [{SITE}] refusing to start: {reason}")
        return {"stopped_for_memory": True, "pages": 0, "posts": 0, "releases": 0,
                "sources": 0, "failed_rows": 0, "parked": 0, "failed": 0,
                "paused_rate_limit": False, "no_playable": 0, "skipped_after_stop": 0}
    if verbose:
        log(f"[*] [{SITE}] {len(rows)} pages pending "
            f"(workers={workers}, delay={delay}s).")

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "failed_rows": 0, "parked": 0, "failed": 0,
              "paused_rate_limit": False, "stopped_for_memory": False,
              "no_playable": 0, "skipped_after_stop": 0}
    if not rows:
        return totals

    def flush(batch, locs):
        flushed = export_staging(db_path, batch)
        totals["posts"] += flushed["posts_written"]
        totals["releases"] += flushed["releases_written"]
        totals["sources"] += flushed["sources_written"]
        _mark_scraped(db_path, locs)
        batch.clear()
        locs.clear()

    batch: list[dict] = []
    batch_locs: list[str] = []
    started = time.time()
    for index, row in enumerate(rows, 1):
        if STOP_REQUESTED:
            totals["skipped_after_stop"] += len(rows) - index + 1
            break
        if _RATE_LIMITED.is_set():
            totals["paused_rate_limit"] = True
            totals["skipped_after_stop"] += len(rows) - index + 1
            break
        time.sleep(delay)
        loc = row["loc"]
        slug = row["slug"] or loc.rstrip("/").rsplit("/", 1)[-1]
        year = year_map.get(series_base(slug)) or _year_from_date(row["lastmod"])
        status, final, body = http_get(loc, timeout=PAGE_TIMEOUT, retries=1)
        totals["pages"] += 1
        if status == RATE_LIMIT_STATUS:
            # Leave the row queued; a throttle is not this page's fault.
            _RATE_LIMITED.set()
            totals["paused_rate_limit"] = True
            log(f"[!] [{SITE}] HTTP 429 at {loc}: queue paused, row stays queued.")
            break
        if status != 200:
            totals["failed_rows"] += 1
            if status == 0:
                failure = _failure("transport", 0, final, "transport failure")
            elif 300 <= status < 400:
                failure = _failure("redirect", status, final, f"http-{status}")
            else:
                failure = _failure(f"http-{status}", status, final, f"http-{status}")
            park_now = status in (404, 410, 451)
            totals["parked"] += int(park_now)
            _bump_error(db_path, loc, failure, park_now=park_now)
            continue
        record = parse_page(body, loc, year)
        if record is None:
            totals["failed_rows"] += 1
            totals["no_playable"] += 1
            _bump_error(db_path, loc, _failure(
                "no-playable-object", status, final,
                "page has no YouTube/Vimeo player"))
            continue
        batch.append(record)
        batch_locs.append(loc)
        if len(batch) >= batch_size:
            flush(batch, batch_locs)
            ok, reason = memory_ok()
            if not ok:
                totals["stopped_for_memory"] = True
                log(f"[!] [{SITE}] STOP: {reason}")
                totals["skipped_after_stop"] += len(rows) - index
                break
        if verbose and (index == len(rows) or index % 100 == 0):
            log(f"    ... {index}/{len(rows)} pages, {totals['posts']} posts, "
                f"{totals['sources']} sources, {time.time() - started:.0f}s")
    if batch:
        flush(batch, batch_locs)

    if verbose:
        paused = " paused=rate-limited" if totals["paused_rate_limit"] else ""
        stopped = " stopped=memory" if totals["stopped_for_memory"] else ""
        log(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
            f"releases={totals['releases']} sources={totals['sources']} "
            f"failed_rows={totals['failed_rows']} parked={totals['parked']} "
            f"failed={totals['failed']} no_playable={totals['no_playable']} "
            f"in {time.time() - started:.0f}s{paused}{stopped}")
    return totals


# ---------------------------------------------------------------------------
# Verify (active vs dead)
# ---------------------------------------------------------------------------

def verify_sources(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                   delay: float = 0.4, verbose: bool = True) -> dict:
    """Probes each unverified embed with YouTube oEmbed; never follows a file."""
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    totals = {"checked": 0, "active": 0, "dead": 0, "unknown": 0,
              "paused_rate_limit": False}
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT id, service, resource_id, source_url FROM sources"
            " WHERE status = 'unverified' AND service = 'youtube'"
            " ORDER BY id").fetchall()
        if limit:
            rows = rows[:limit]
        if verbose:
            log(f"[*] [{SITE}] {len(rows)} embeds to verify.")
        for row in rows:
            if STOP_REQUESTED:
                break
            time.sleep(delay)
            url = (f"{YOUTUBE_OEMBED}?url=https%3A%2F%2Fwww.youtube.com%2Fwatch"
                   f"%3Fv%3D{urllib.parse.quote(row['resource_id'] or '')}"
                   "&format=json")
            status, _final, _body = http_get(url, timeout=PAGE_TIMEOUT, retries=0)
            if status == RATE_LIMIT_STATUS:
                totals["paused_rate_limit"] = True
                break
            if status == 200:
                state = "active"
            elif status in (401, 403, 404, 410):
                state = "dead"
            else:
                state = "unknown"
            if state == "unknown":
                totals["unknown"] += 1
                continue
            conn.execute(
                "UPDATE sources SET status = ?, last_checked = ? WHERE id = ?",
                (state, int(time.time()), row["id"]))
            conn.commit()
            totals[state] += 1
            totals["checked"] += 1
            if verbose and totals["checked"] % 100 == 0:
                log(f"    ... {totals['checked']} checked, {totals['active']} active,"
                    f" {totals['dead']} dead")
    finally:
        conn.close()
    if verbose:
        log(f"[✓] [{SITE}] verify checked={totals['checked']} "
            f"active={totals['active']} dead={totals['dead']} "
            f"unknown={totals['unknown']}")
    return totals


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
        result = {
            "works": q("SELECT COUNT(*) FROM posts"),
            "releases": q("SELECT COUNT(*) FROM releases"),
            "watch_links": q("SELECT COUNT(*) FROM sources WHERE playback_type = ?",
                             PLAYBACK_IFRAME),
            "download_links": q("SELECT COUNT(*) FROM sources WHERE playback_type = ?",
                                "download"),
            "sources_unverified": q("SELECT COUNT(*) FROM sources WHERE status = 'unverified'"),
            "sources_active": q("SELECT COUNT(*) FROM sources WHERE status = 'active'"),
            "sources_dead": q("SELECT COUNT(*) FROM sources WHERE status = 'dead'"),
            "adult_posts": q("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1"),
            "queued": q("SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0, 2)"),
            "parked": q("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1"),
            "crawled": q("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1"),
            "sitemap_rows": q("SELECT COUNT(*) FROM sitemap_cache"),
            "release_less_posts": q(
                "SELECT COUNT(*) FROM posts p WHERE NOT EXISTS ("
                " SELECT 1 FROM releases r WHERE r.post_canonical_key = p.canonical_key)"),
        }
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _install_signals() -> None:
    def _stop(signum, _frame):
        global STOP_REQUESTED
        STOP_REQUESTED = True
        log(f"[!] [{SITE}] signal {signum}: finishing the page in flight, then stopping.")
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _stop)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="hum.tv staging importer")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="queue the REST catalog")
    sync.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync.add_argument("--limit", type=int)
    crawl = sub.add_parser("crawl", help="fetch queued pages")
    crawl.add_argument("--db", default=str(DEFAULT_DB_PATH))
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--workers", type=int, default=1)
    crawl.add_argument("--delay", type=float, default=0.5)
    verify = sub.add_parser("verify", help="probe unverified embeds")
    verify.add_argument("--db", default=str(DEFAULT_DB_PATH))
    verify.add_argument("--limit", type=int)
    verify.add_argument("--delay", type=float, default=0.4)
    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _install_signals()
    if args.command == "sync":
        totals = sync_catalog(args.db, limit=args.limit)
    elif args.command == "crawl":
        totals = crawl_pending(limit=args.limit, db_path=args.db,
                               workers=args.workers, delay=args.delay)
    elif args.command == "verify":
        totals = verify_sources(db_path=args.db, limit=args.limit, delay=args.delay)
    else:
        totals = stats(args.db)
    print(json.dumps(totals, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
