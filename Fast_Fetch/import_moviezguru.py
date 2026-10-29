#!/usr/bin/env python3
"""
import_moviezguru.py — High-Performance MoviezGuru Scraper & 10Gbps Google CDN Resolver

Scrapes catalog from MoviezGuru (https://moviezguru.guru) via WordPress REST API,
parses high-resolution posters, IMDb IDs, multi-tier releases (1080p, 720p, 480p),
and resolves mzgserver.shop media links directly into 10Gbps Google CDN / Google Drive
streaming and download sources.

Constraints:
  - 100% Python standard library only (zero external pip/npm packages).
  - Strict staging database isolation: writes solely to /home/ubuntu/radd-stream-data/moviezguru.db.
  - Zero Data Loss: preserves all releases and fallback gateway links even if bridges timeout.
  - WAL mode SQLite concurrency with 60s busy timeout.
"""

from __future__ import annotations

import argparse
import contextlib
import http.cookiejar
import html
import json
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- Constants ---
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/moviezguru.db")
BASE_URL = "https://moviezguru.guru"
WP_API_URL = "https://moviezguru.guru/wp-json/wp/v2/posts"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# "rabbit" and "hunters" were removed on 2026-10-29 after sampling 12 live titles each in
# the production ledger: 0/12 adult for both — *Wallace & Gromit: The Curse of the
# Were-Rabbit*, *1001 Rabbit Tales*, *Rabbit School*, *Peter Rabbit*, *Jojo Rabbit*,
# *KPop Demon Hunters*, *Transformers Prime: Beast Hunters*. "adult" STAYED: 10/12 of its
# sampled rows are real product (the "… Adult Short Film" vault format), and deleting it
# would push Brazzers and TeamSkeet into a general-audience app. Judge a bare word by its
# live titles, never by the dictionary. See `fast_fetch.ADULT_TITLE_PATTERNS`.
ADULT_KEYWORDS = {
    "erotic", "hotshots", "ullu", "kooku", "primeplay",
    "flizmovies", "boommovies", "neonx", "besharams", "gupchup",
    "sex", "sexy", "porn", "adult", "sensual", "lust"
}

STOP_REQUESTED = False

# sitemap_cache.scraped state machine, shared by every staging importer and by
# fast_fetch's crawler: 0 = queued, 1 = indexed, -1 = tried but nothing was
# indexable (needs review/retry).  The retired value 2 ("skipped") was written
# but never drained, so skipped pages were lost; the skip path now writes -1 and
# the pending query still accepts legacy 2 rows so none can strand in that state.
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug, raw_json FROM sitemap_cache WHERE scraped IN (?, ?)"
)


def sig_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("\n[!] Graceful shutdown requested. Finishing active tasks...", flush=True)


signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)


def is_adult_content(text: str) -> bool:
    """Strictly checks if title, slug, or tags indicate adult / 18+ content."""
    if not text:
        return False
    t = text.lower()
    for kw in ADULT_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", t):
            return True
    return False


# --- HTTP Client & Google CDN Resolver ---
class MoviezGuruClient:
    """HTTP client with rate limiting and direct mzgserver -> Google Drive unwrap."""

    def __init__(self, request_interval: float = 0.2):
        self.request_interval = request_interval
        self._last_req_time = 0.0
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def _rate_limit(self):
        elapsed = time.time() - self._last_req_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_req_time = time.time()

    def get_text(
        self, url: str, referer: str = BASE_URL, timeout: float = 12.0
    ) -> tuple[int, str, str, dict]:
        """Performs GET request returning (status_code, final_url, html_text, headers)."""
        self._rate_limit()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": referer,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                status = resp.status
                final_url = resp.geturl()
                content = resp.read().decode("utf-8", errors="ignore")
                headers = dict(resp.headers)
                return status, final_url, content, headers
        except urllib.error.HTTPError as e:
            err_content = e.read().decode("utf-8", errors="ignore") if e.fp else ""
            return e.code, e.geturl(), err_content, dict(e.headers)
        except Exception:
            return 0, url, "", {}

    def get_json(
        self, url: str, referer: str = BASE_URL, timeout: float = 15.0
    ) -> tuple[int, any, dict]:
        """Performs GET request returning parsed JSON."""
        status, _, text, headers = self.get_text(url, referer=referer, timeout=timeout)
        if status == 200 and text:
            try:
                return status, json.loads(text), headers
            except Exception:
                return status, None, headers
        return status, None, headers

    def unwrap_mzgserver(self, mzg_url: str) -> list[dict]:
        """
        Unwraps mzgserver.shop/file/<ID> into 10Gbps Google Drive / Google CDN stream.
        1. Fetch file page -> find /dl/<TOKEN>
        2. GET /dl/<TOKEN> -> follow redirect to drive.usercontent.google.com
        3. Extract Google Drive file ID
        """
        sources = []
        try:
            status, final_url, html_text, _ = self.get_text(
                mzg_url, referer=BASE_URL, timeout=10.0
            )
            if status != 200 or not html_text:
                return sources

            dl_m = re.search(r'href=[\'"](?:\.\./dl/|/dl/)([a-f0-9]+)[\'"]', html_text)
            if not dl_m:
                return sources

            dl_token = dl_m.group(1)
            dl_url = f"https://mzgserver.shop/dl/{dl_token}"

            # Request dl endpoint to trigger redirect to Google Drive
            status2, redirect_url, _, _ = self.get_text(
                dl_url, referer=mzg_url, timeout=12.0
            )

            # Look for Google Drive ID in final redirected URL
            g_m = re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", redirect_url)
            if g_m:
                gdrive_id = g_m.group(1)
                sources.append(
                    {
                        "source_name": "⚡ Google CDN 10Gbps Direct",
                        "service": "google_drive",
                        "resource_id": gdrive_id,
                        "source_url": f"https://drive.usercontent.google.com/download?id={gdrive_id}&export=download",
                        "final_url": f"https://drive.usercontent.google.com/download?id={gdrive_id}&export=download",
                        "is_temporary": 0,
                    }
                )
                sources.append(
                    {
                        "source_name": "📁 Google Drive Direct Stream",
                        "service": "google_drive",
                        "resource_id": gdrive_id,
                        "source_url": f"https://drive.google.com/uc?id={gdrive_id}&export=download",
                        "final_url": f"https://drive.google.com/uc?id={gdrive_id}&export=download",
                        "is_temporary": 0,
                    }
                )
            elif redirect_url.startswith("http") and "mzgserver.shop" not in redirect_url:
                # Other direct mirror
                sources.append(
                    {
                        "source_name": "🔗 Direct Stream",
                        "service": "direct",
                        "resource_id": redirect_url.split("/")[-1],
                        "source_url": redirect_url,
                        "final_url": redirect_url,
                        "is_temporary": 0,
                    }
                )
        except Exception:
            pass

        return sources


# --- Parsing Helpers ---
def parse_size_string(size_str: str) -> int | None:
    """Parses human readable size like '1.3 GB' or '450 MB' into bytes."""
    if not size_str:
        return None
    cleaned = re.sub(r"[^\d\.kmgtbKMGTB]", "", size_str).strip()
    m = re.match(r"^([\d\.]+)\s*([kmgtKMGT]?b?)$", cleaned, re.I)
    if not m:
        return None
    try:
        val_str = m.group(1).rstrip(".")
        val = float(val_str)
        unit = m.group(2).upper()
        if "G" in unit:
            return int(val * (1024**3))
        if "M" in unit:
            return int(val * (1024**2))
        if "K" in unit:
            return int(val * 1024)
        if "T" in unit:
            return int(val * (1024**4))
        return int(val)
    except Exception:
        return None


def clean_moviezguru_title(raw_title: str) -> tuple[str, int | None, int | None, str, str]:
    """
    Cleans MoviezGuru post title into canonical metadata.
    Example: 'Romanchakam (2026) Full Movie NETFLIX ORG. Hindi Dubbed WEBRip ESubs 720p 480p Download'
             -> ('Romanchakam', 2026, None, 'movie', 'romanchakam-2026')
    """
    t = html.unescape(raw_title).strip()

    # Detect Year first
    year = None
    y_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if y_m:
        year = int(y_m.group(1))

    # Detect Season and Episode
    season_num = None
    episode_num = None
    media_type = "movie"

    se_m = re.search(r"\bS(\d{1,2})E(\d{1,3})\b", t, re.I)
    if se_m:
        season_num = int(se_m.group(1))
        episode_num = int(se_m.group(2))
        media_type = "series"
    else:
        s_m = re.search(r"\bS(?:eason\s*)?(\d{1,2})\b", t, re.I)
        if s_m and not re.search(r"\bEpisode\s+[IVXLCDM]+\b", t, re.I):
            season_num = int(s_m.group(1))
            media_type = "series"
        ep_m = re.search(r"\bEpisode\s*(\d+)\b", t, re.I)
        if ep_m:
            episode_num = int(ep_m.group(1))
            media_type = "series"

    if re.search(r"\b(web\s*series|complete\s*series|all\s*episodes?|tv\s*seasons?)\b", t, re.I):
        media_type = "series"
    if re.search(r"\bfull\s*movie\b", t, re.I):
        media_type = "movie"

    # Clean technical tags and buzzwords
    t_clean = re.sub(r"\[.*?\]|\(.*?\)", " ", t)
    t_clean = re.sub(
        r"\b(full\s*movie|org\.?|netflix|amzn|hotstar|zee5|sonyliv|jio|dual\s*audio|hindi\s*dubbed|original|webrip|bluray|hdtc|hdts|hdrip|hevc|x264|x265|1080p|720p|480p|2160p|4k|esubs|download|hindi|english|tamil|telugu)\b.*$",
        "",
        t_clean,
        flags=re.IGNORECASE,
    )
    if year:
        t_clean = re.sub(rf"\b{year}\b.*$", "", t_clean)

    t_clean = re.sub(r"[-–—:|]+", " ", t_clean)
    t_clean = re.sub(r"\s+", " ", t_clean).strip()
    clean_title = t_clean or raw_title

    # Canonical slug key
    slug_base = re.sub(r"[^a-z0-9]+", "-", clean_title.lower()).strip("-")
    if year:
        canonical_key = f"{slug_base}-{year}"
    else:
        canonical_key = slug_base

    if season_num:
        canonical_key = f"{canonical_key}-s{season_num}"

    return clean_title, year, season_num, media_type, canonical_key


def parse_moviezguru_content(
    content_html: str, post_title: str
) -> tuple[str | None, str | None, list[dict]]:
    """
    Parses MoviezGuru post HTML content to extract IMDb ID, high-res poster, and releases with mzgserver links.
    """
    # 1. IMDb ID
    imdb_id = None
    imdb_m = re.search(r"\b(tt\d{7,10})\b", content_html)
    if imdb_m:
        imdb_id = imdb_m.group(1)

    # 2. High-res poster
    poster_url = None
    poster_m = re.search(
        r'<img[^>]+src=["\'](https?://(?:moviezguru\.guru/wp-content/uploads/|blogger\.googleusercontent\.com/img/b/|.*?\.(?:jpg|jpeg|png|webp)))["\']',
        content_html,
        re.I,
    )
    if poster_m:
        poster_url = poster_m.group(1)

    # 3. Detect season for series
    _, year, season_num, media_type, _ = clean_moviezguru_title(post_title)

    # 4. Extract releases by parsing HTML blocks with mzgserver.shop links
    releases = []
    blocks = [b.strip() for b in re.split(r"</?(?:p|h\d|div)>", content_html) if b.strip()]

    seen_bridges = set()
    for b in blocks:
        if "mzgserver." in b and "/file/" in b:
            mzg_m = re.search(
                r'href=[\'"](https?://mzgserver\.[a-z]+/file/[A-Za-z0-9_-]+)[\'"]', b
            )
            if not mzg_m:
                continue
            bridge_url = mzg_m.group(1)
            if bridge_url in seen_bridges:
                continue
            seen_bridges.add(bridge_url)

            clean_b = re.sub(r"<[^>]+>", " ", b)

            # Quality detection
            q_m = re.search(r"\b(4K|2160p|1080p|720p|480p)\b", clean_b, re.I)
            quality = q_m.group(1).upper() if q_m else "720P"

            # Size detection (e.g. '(450 MB)' or '(1.3 GB)')
            size_m = re.search(r"\(([\d\.]+\s*(?:GB|MB|gb|mb))\)", clean_b)
            if not size_m:
                size_m = re.search(r"\[([\d\.]+\s*(?:GB|MB|gb|mb))\]", clean_b)
            size_bytes = parse_size_string(size_m.group(1)) if size_m else None

            # Codec
            codec = (
                "hevc"
                if any(x in clean_b.lower() for x in ["hevc", "x265", "10bit"])
                else "x264"
            )

            # Audio detection
            audio = None
            if "dual audio" in clean_b.lower():
                audio = "Dual Audio"
            elif "hindi" in clean_b.lower() or "hindi" in post_title.lower():
                audio = "Hindi"

            releases.append(
                {
                    "label": f"{quality} {codec.upper()} {size_m.group(1) if size_m else ''}".strip(),
                    "quality": quality,
                    "resolution": quality.lower(),
                    "size_bytes": size_bytes,
                    "season_number": season_num,
                    "episode_number": None,
                    "audio_languages": audio,
                    "codec": codec,
                    "bridge_url": bridge_url,
                }
            )

    return imdb_id, poster_url, releases


# --- Database Layer ---
@contextlib.contextmanager
def get_db_connection(db_path: Path, timeout: float = 60.0):
    """Context manager providing robust WAL-mode SQLite connection with busy timeout."""
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 60000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_staging_db(db_path: Path):
    """Initializes schema in dedicated isolated staging database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                site TEXT DEFAULT 'moviezguru',
                raw_json TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_key TEXT UNIQUE,
                title TEXT NOT NULL,
                original_title TEXT,
                year INTEGER,
                media_type TEXT DEFAULT 'movie',
                imdb_id TEXT,
                tmdb_id INTEGER,
                poster_url TEXT,
                synopsis TEXT,
                genres TEXT,
                is_18_plus INTEGER DEFAULT 0,
                site TEXT DEFAULT 'moviezguru',
                post_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _mp = {c[1] for c in cur.execute("PRAGMA table_info(posts);").fetchall()}
        if "is_18_plus" not in _mp:
            try:
                cur.execute("ALTER TABLE posts ADD COLUMN is_18_plus INTEGER DEFAULT 0;")
            except Exception:
                pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_canonical_key TEXT,
                label TEXT,
                quality TEXT,
                resolution TEXT,
                size_bytes INTEGER,
                codec TEXT,
                season_number INTEGER,
                episode_number INTEGER,
                audio_languages TEXT,
                bridge_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_canonical_key) REFERENCES posts(canonical_key) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                release_id INTEGER,
                source_name TEXT,
                service TEXT,
                resource_id TEXT,
                source_url TEXT,
                final_url TEXT,
                is_temporary INTEGER DEFAULT 0,
                quality TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mzg_posts_key ON posts(canonical_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mzg_rels_post ON releases(post_canonical_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mzg_src_rel ON sources(release_id);")


def save_post_to_staging(db_path: Path, result: dict):
    """Atomically saves extracted post, releases, and direct sources to staging DB."""
    loc = result["loc"]
    if result.get("skipped"):
        with get_db_connection(db_path) as conn:
            conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ?;", (loc,))
        return

    if not result.get("success"):
        with get_db_connection(db_path) as conn:
            conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ?;", (loc,))
        return

    p = result["post"]
    releases = result["releases"]

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO posts (canonical_key, title, original_title, year, media_type, imdb_id, poster_url, synopsis, genres, is_18_plus, site, post_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title=excluded.title,
                original_title=excluded.original_title,
                year=COALESCE(excluded.year, posts.year),
                media_type=excluded.media_type,
                imdb_id=COALESCE(excluded.imdb_id, posts.imdb_id),
                poster_url=COALESCE(excluded.poster_url, posts.poster_url),
                is_18_plus=MAX(posts.is_18_plus, excluded.is_18_plus),
                post_url=excluded.post_url,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                p["canonical_key"],
                p["title"],
                p["original_title"],
                p["year"],
                p["media_type"],
                p["imdb_id"],
                p["poster_url"],
                p["synopsis"],
                p["genres"],
                p.get("is_18_plus", 0),
                p["site"],
                p["post_url"],
            ),
        )

        for rel in releases:
            cur.execute(
                """
                INSERT INTO releases (post_canonical_key, label, quality, resolution, size_bytes, codec, season_number, episode_number, audio_languages, bridge_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    p["canonical_key"],
                    rel.get("label"),
                    rel.get("quality"),
                    rel.get("resolution"),
                    rel.get("size_bytes"),
                    rel.get("codec"),
                    rel.get("season_number"),
                    rel.get("episode_number"),
                    rel.get("audio_languages"),
                    rel.get("bridge_url"),
                ),
            )
            rel_id = cur.lastrowid

            for src in rel.get("sources", []):
                cur.execute(
                    """
                    INSERT INTO sources (release_id, source_name, service, resource_id, source_url, final_url, is_temporary, quality)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        rel_id,
                        src.get("source_name"),
                        src.get("service"),
                        src.get("resource_id"),
                        src.get("source_url"),
                        src.get("final_url"),
                        src.get("is_temporary", 0),
                        rel.get("quality"),
                    ),
                )

        cur.execute("UPDATE sitemap_cache SET scraped = 1 WHERE loc = ?;", (loc,))


# --- Scraper Worker ---
def scrape_post_item(
    item: tuple, client: MoviezGuruClient, unwrap_bridges: bool = True
) -> dict | None:
    """Processes a single MoviezGuru post item, parsing releases and unwrapping mzgserver bridges."""
    loc, lastmod, slug, raw_json_str = item
    try:
        if not raw_json_str:
            return None

        p_data = json.loads(raw_json_str)
        raw_title = p_data.get("title", {}).get("rendered", "")
        content_html = p_data.get("content", {}).get("rendered", "")

        if not raw_title or not content_html:
            return None

        # Adult content retained with is_18_plus flag; hidden only at presentation layer
        is_adult = 1 if (is_adult_content(raw_title) or is_adult_content(slug)) else 0

        # Clean title & detect year
        clean_title, year, season_num, media_type, canonical_key = clean_moviezguru_title(
            raw_title
        )

        # Parse IMDb, poster, and releases
        imdb_id, poster_url, releases_data = parse_moviezguru_content(content_html, raw_title)
        if not releases_data:
            return {"loc": loc, "success": False, "reason": "no_releases"}

        # Unwrap bridge URLs into 10Gbps Google CDN streams
        resolved_releases = []
        for rel in releases_data:
            bridge_url = rel.get("bridge_url")
            sources = []

            if bridge_url and unwrap_bridges:
                sources = client.unwrap_mzgserver(bridge_url)

            # Zero Data Loss: Preserve gateway mirror if unwrap yields 0 or unwrap is disabled
            if not sources and bridge_url:
                sources = [
                    {
                        "source_name": "🔗 MZG Server Gateway",
                        "service": "mzgserver",
                        "resource_id": bridge_url.split("/")[-1],
                        "source_url": bridge_url,
                        "final_url": bridge_url,
                        "is_temporary": 0,
                    }
                ]

            rel_copy = dict(rel)
            rel_copy["sources"] = sources
            resolved_releases.append(rel_copy)

        return {
            "loc": loc,
            "success": True,
            "post": {
                "canonical_key": canonical_key,
                "title": clean_title,
                "original_title": raw_title,
                "year": year,
                "media_type": media_type,
                "imdb_id": imdb_id,
                "poster_url": poster_url,
                "synopsis": None,
                "genres": None,
                "site": "moviezguru",
                "post_url": loc,
                "is_18_plus": is_adult,
            },
            "releases": resolved_releases,
        }
    except Exception as e:
        return {"loc": loc, "success": False, "reason": str(e)}


# --- Bulk API Ingestion ---
def sync_api_catalog(
    client: MoviezGuruClient, db_path: Path, max_pages: int | None = None
) -> int:
    """
    Syncs full MoviezGuru catalog into staging SQLite database via WordPress REST API.
    Uses per_page=100 bulk ingestion (~3.4k titles in ~34 requests).
    """
    init_staging_db(db_path)
    print(f"[*] Starting MoviezGuru API sync (per_page=100) -> {db_path}...", flush=True)

    page = 1
    total_synced = 0
    total_posts = 0

    while True:
        if STOP_REQUESTED:
            print("[!] API sync stopped by user.", flush=True)
            break
        if max_pages and page > max_pages:
            print(f"[*] Reached page limit ({max_pages}).", flush=True)
            break

        url = f"{WP_API_URL}?per_page=100&page={page}"
        code, posts, headers = client.get_json(url, timeout=15.0)

        if code != 200 or not posts or not isinstance(posts, list):
            if code == 400:
                print(f"[✓] End of WP REST API pagination reached at page {page - 1}.", flush=True)
            else:
                print(f"[!] WP REST API returned HTTP {code} on page {page}.", flush=True)
            break

        if page == 1:
            total_posts = int(headers.get("x-wp-total", 0) or 0)
            total_pages = int(headers.get("x-wp-totalpages", 0) or 0)
            print(
                f"[*] Total catalog size: {total_posts:,} posts across {total_pages:,} pages.",
                flush=True,
            )

        batch_records = []
        for p in posts:
            loc = p.get("link")
            lastmod = p.get("modified")
            slug = p.get("slug")
            raw_json_str = json.dumps(p)
            if loc:
                batch_records.append((loc, lastmod, slug, 0, "moviezguru", raw_json_str))

        if batch_records:
            with get_db_connection(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(loc) DO UPDATE SET
                        lastmod=excluded.lastmod,
                        raw_json=excluded.raw_json;
                    """,
                    batch_records,
                )

        total_synced += len(batch_records)
        print(
            f"  [Page {page}] Ingested {len(batch_records)} items (total: {total_synced:,}/{total_posts:,})",
            flush=True,
        )
        page += 1

    print(
        f"[✓] MoviezGuru API sync finished: {total_synced:,} titles ready for crawler.",
        flush=True,
    )
    return total_synced


# --- Concurrent Crawler Engine ---
def run_crawler(
    db_path: Path,
    workers: int = 5,
    delay: float = 0.2,
    limit: int | None = None,
    unwrap_bridges: bool = True,
):
    """Multi-threaded concurrent crawler consuming pending titles from sitemap_cache."""
    init_staging_db(db_path)
    client = MoviezGuruClient(request_interval=delay)

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        query = PENDING_SELECT
        if limit:
            query += f" LIMIT {int(limit)}"
        cur.execute(query, QUEUED_SCRAPE_STATES)
        pending = cur.fetchall()

    if not pending:
        print("[✓] Zero pending titles to scrape in sitemap_cache.", flush=True)
        return

    print(
        f"[*] Starting MoviezGuru crawler: {len(pending)} titles queued | {workers} workers | delay {delay}s | unwrap={unwrap_bridges}",
        flush=True,
    )
    t0 = time.time()
    scraped_count = 0
    failed_count = 0
    total_releases = 0
    total_sources = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(scrape_post_item, item, client, unwrap_bridges): item
            for item in pending
        }
        for future in as_completed(future_map):
            if STOP_REQUESTED:
                break
            try:
                res = future.result()
                if res:
                    save_post_to_staging(db_path, res)
                    if res.get("success"):
                        scraped_count += 1
                        for r in res.get("releases", []):
                            total_releases += 1
                            total_sources += len(r.get("sources", []))
                    elif not res.get("skipped"):
                        failed_count += 1
            except Exception:
                failed_count += 1

            total_done = scraped_count + failed_count
            if total_done % 10 == 0 or total_done == len(pending):
                elapsed = max(0.1, time.time() - t0)
                speed = total_done / elapsed
                remaining = len(pending) - total_done
                eta_sec = int(remaining / speed) if speed > 0 else 0
                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_sec))
                print(
                    f"  [{total_done}/{len(pending)}] releases={total_releases:,} sources={total_sources:,} failed={failed_count} speed={speed:.2f} t/s ETA: {eta_str}",
                    flush=True,
                )

    elapsed = max(0.1, time.time() - t0)
    print(
        f"\n[✓] MoviezGuru crawler finished: {scraped_count:,} scraped, {failed_count} failed in {elapsed:.1f}s",
        flush=True,
    )


# --- CLI Interface ---
def main():
    parser = argparse.ArgumentParser(description="MoviezGuru Importer & Google CDN Resolver")
    parser.add_argument(
        "--sync-api", action="store_true", help="Sync WP REST API posts into sitemap_cache"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Target SQLite staging database path",
    )
    parser.add_argument(
        "--workers", type=int, default=5, help="Concurrent worker threads (default: 5)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.2, help="Request rate delay in seconds (default: 0.2)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of posts to process"
    )
    parser.add_argument(
        "--max-pages", type=int, default=None, help="Max API pages to ingest during sync"
    )
    parser.add_argument(
        "--no-unwrap",
        action="store_true",
        help="Store bridge URLs without immediately unwrapping via HTTP GET",
    )

    args = parser.parse_args()

    client = MoviezGuruClient(request_interval=args.delay)

    if args.sync_api:
        sync_api_catalog(client, args.db_path, max_pages=args.max_pages)

    run_crawler(
        args.db_path,
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        unwrap_bridges=not args.no_unwrap,
    )


if __name__ == "__main__":
    main()
