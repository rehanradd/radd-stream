#!/usr/bin/env python3
"""
import_rareanimes.py — Dedicated staging importer and scraper for RareAnimes (https://www.rareanimes.mov).

Key Features:
  1. Dedicated staging SQLite database: rareanimes.db (strictly isolated from production fast_fetch.db).
  2. Complete WP REST API Synchronization: Paginates /wp-json/wp/v2/posts?per_page=100&_embed=1
     across all ~1,926+ anime & cartoon titles with rich embedded metadata (featured media, categories).
  3. Master Index Page Fallback: Extracts all 640+ movie posts from /all-anime-cartoon-movies-list/.
  4. Rich Anime Metadata Extraction:
     - Header info block: Full Name, Season, Episodes, Release Year, Genre, Audio Languages, Quality, Synopsis.
     - Featured image poster extraction (high-res WebP/PNG/JPG).
     - Clean canonical title key generation.
  5. Multi-Language Episode & Release Parsing:
     - Multi-audio breakdown per episode: Hindi, Tamil, Telugu, English, Japanese/Multi Audio.
     - Detects season number, episode number, and episode title.
  6. High-Speed Direct Stream Unwrapping:
     - DLBeta (PixelDrain): Direct unthrottled streaming URL via https://pixeldrain.com/api/file/<ID> (video/matroska).
     - HubCloud: Unwrapped to 10Gbps Cloudflare R2 direct stream (r2.cloudflarestorage.com) and 10G Fast Server.
     - Mega & Razorshell mirror capture.
  7. Resumable via sitemap_cache table in staging SQLite database.
  8. 100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_rareanimes.py --sync-api               # Ingest all 1,926 titles via WP REST API
    python Fast_Fetch/import_rareanimes.py --limit 10               # Scrape 10 pending titles
    python Fast_Fetch/import_rareanimes.py --workers 5 --delay 0.3 # Full background crawler
    python Fast_Fetch/import_rareanimes.py --status                 # Show staging DB metrics
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import signal
import sqlite3
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Add Fast_Fetch to sys.path
BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch

DEFAULT_BASE_URL = "https://www.rareanimes.mov"
WP_API_URL = f"{DEFAULT_BASE_URL}/wp-json/wp/v2/posts"
DEFAULT_DB_PATH = BASE_DIR / "rareanimes.db"
STATUS_FILE = BASE_DIR / "rareanimes_status.json"

STOP_REQUESTED = False


def _sigint_handler(signum, frame):
    global STOP_REQUESTED
    print("\n[!] Graceful shutdown requested... Finishing current requests.", flush=True)
    STOP_REQUESTED = True


signal.signal(signal.SIGINT, _sigint_handler)
signal.signal(signal.SIGTERM, _sigint_handler)


def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


MAX_SAFE_WORKERS = 6
MIN_REQUEST_DELAY = 0.3


class RareAnimesClient:
    """HTTP Client with rate limiting and retry handling for RareAnimes."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, request_interval: float = 0.3, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.request_interval = max(0.0, request_interval)
        self.retries = max(1, retries)
        self.ssl_ctx = get_ssl_context()
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def _wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next_request_at:
                time.sleep(self._next_request_at - now)
            self._next_request_at = time.monotonic() + self.request_interval

    def get_text(self, url: str, referer: str | None = None, timeout: int = 15) -> tuple[int, str, str]:
        headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        elif url.startswith(self.base_url):
            headers["Referer"] = self.base_url + "/"

        for attempt in range(self.retries):
            if STOP_REQUESTED:
                return 0, url, ""
            self._wait()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                    code = resp.status
                    final_url = resp.geturl()
                    charset = resp.headers.get_content_charset() or "utf-8"
                    raw = resp.read()
                    text = raw.decode(charset, errors="replace")
                    return code, final_url, text
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    return e.code, url, ""
                if attempt == self.retries - 1:
                    return e.code, url, ""
                time.sleep(1.0 * (attempt + 1))
            except Exception:
                if attempt == self.retries - 1:
                    return 0, url, ""
                time.sleep(1.0 * (attempt + 1))
        return 0, url, ""

    def get_json(self, url: str, referer: str | None = None, timeout: int = 15) -> tuple[int, dict | list | None, dict]:
        headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": "application/json, */*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer

        for attempt in range(self.retries):
            if STOP_REQUESTED:
                return 0, None, {}
            self._wait()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                    code = resp.status
                    raw = resp.read()
                    resp_headers = dict(resp.headers)
                    text = raw.decode("utf-8", errors="replace")
                    data = json.loads(text)
                    return code, data, resp_headers
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    return e.code, None, {}
                if attempt == self.retries - 1:
                    return e.code, None, {}
                time.sleep(1.0 * (attempt + 1))
            except Exception:
                if attempt == self.retries - 1:
                    return 0, None, {}
                time.sleep(1.0 * (attempt + 1))
        return 0, None, {}


def init_staging_db(db_path: Path):
    """Initializes RareAnimes staging SQLite database with isolated schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                site TEXT DEFAULT 'rareanimes',
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sm_scraped ON sitemap_cache(scraped);

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_key TEXT UNIQUE,
                title TEXT,
                original_title TEXT,
                year INTEGER,
                media_type TEXT,
                imdb_id TEXT,
                tmdb_id TEXT,
                poster_url TEXT,
                backdrop_url TEXT,
                synopsis TEXT,
                genres TEXT,
                rating REAL,
                site TEXT DEFAULT 'rareanimes',
                post_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_posts_canonical ON posts(canonical_key);

            CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER,
                label TEXT,
                quality TEXT,
                resolution TEXT,
                size_bytes INTEGER,
                season_number INTEGER,
                episode_number INTEGER,
                audio_languages TEXT,
                codec TEXT,
                bridge_url TEXT,
                FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_releases_post_id ON releases(post_id);

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
                FOREIGN KEY(release_id) REFERENCES releases(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_sources_release_id ON sources(release_id);
        """)
        conn.commit()


def clean_rareanimes_title(raw_title: str) -> tuple[str, int | None, int | None, str]:
    """
    Cleans raw title into (clean_title, year, season, canonical_key).
    Examples:
      'Blue Box Season 2 Hindi Episodes Download HD' -> ('Blue Box', 2026, 2, 'blue-box_s2')
      'The Iron Giant (1999) Movie Hindi Dubbed Download HD' -> ('The Iron Giant', 1999, None, 'the-iron-giant_1999')
    """
    t = html.unescape(raw_title).strip()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Detect Season
    season_m = re.search(r"\bSeason\s*(\d+)\b", t, re.IGNORECASE)
    season = int(season_m.group(1)) if season_m else None

    # Detect Year
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    year = int(year_m.group(1)) if year_m else None

    clean = t
    # Strip common suffixes
    clean = re.sub(
        r"\s*(?:Hindi\s*Dubbed|Hindi\s*Episodes|Hindi\s*Download|Episodes\s*Download|Full\s*Movie|Movie\s*Download|Download\s*HD|Download\s*FHD|Hindi|Tamil|Telugu|Dual\s*Audio|Multi\s*Audio|All\s*Episodes).*$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    # Strip Movie suffix
    clean = re.sub(r"\s+Movie\s*$", "", clean, flags=re.IGNORECASE).strip()
    # Strip Season
    clean = re.sub(r"\s*\(\s*Season\s*\d+\s*\)", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+Season\s*\d+", "", clean, flags=re.IGNORECASE)
    # Strip Year parentheses
    clean = re.sub(r"\s*\(\s*(?:19|20)\d{2}\s*\)", "", clean).strip()
    clean = re.sub(r"\s+Movie\s*$", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s+", " ", clean).strip(" -:|")

    canonical_key = fast_fetch.generate_canonical_key(clean, year)
    if season and not canonical_key.endswith(f"_s{season}"):
        canonical_key = f"{canonical_key}_s{season}"

    return clean, year, season, canonical_key


def parse_rareanimes_content(content_html: str) -> tuple[dict, list[dict]]:
    """
    Extracts post info block (Full Name, Season, Release Year, Genre, Synopsis)
    and all episode/movie download release blocks with mirrors.
    """
    info = {}
    for key, pattern in [
        ("full_name", r"Full Name:\s*<span[^>]*>(.*?)</span>"),
        ("season", r"Season:\s*<span[^>]*>(\d+)</span>"),
        ("episodes", r"Episodes:\s*<span[^>]*>(\d+)</span>"),
        ("year", r"Release Year:\s*<span[^>]*>(\d{4})</span>"),
        ("genre", r"Genre:\s*<span[^>]*>(.*?)</span>"),
        ("language", r"Language:\s*<span[^>]*>(.*?)</span>"),
        ("quality", r"Quality:\s*<span[^>]*>(.*?)</span>"),
        ("synopsis", r"Synopsis\s*</span>\s*<span[^>]*>(.*?)</span>"),
    ]:
        m = re.search(pattern, content_html, re.IGNORECASE | re.DOTALL)
        if m:
            info[key] = re.sub(r"<[^>]+>", "", m.group(1)).strip()

    releases = []
    seen_urls = set()

    # Pattern A: Episode blocks (e.g. Episode 01 – Deja Vu ... <p>Hindi – [DLBeta] [HubCloud]</p>)
    ep_matches = list(re.finditer(r"(Episode\s*(\d+)[^<]*)", content_html, re.IGNORECASE))
    if ep_matches:
        for i, em in enumerate(ep_matches):
            ep_heading = em.group(1).strip()
            ep_num = int(em.group(2))
            start_pos = em.start()
            end_pos = ep_matches[i + 1].start() if i + 1 < len(ep_matches) else start_pos + 1200
            block_html = content_html[start_pos:end_pos]

            # Find language lines within this episode block
            p_lines = re.findall(r"<p>(.*?)</p>", block_html, re.IGNORECASE | re.DOTALL)
            for pl in p_lines:
                # Detect language
                lang = "Hindi"
                lang_m = re.search(r"<span[^>]*>\s*([A-Za-z\s]+?)\s*</span>\s*–", pl, re.IGNORECASE)
                if lang_m:
                    lang = lang_m.group(1).strip()

                anchors = re.findall(r'<a[^>]+href=["\'](https?://[^\s"\'<>]+)["\'][^>]*>(.*?)</a>', pl, re.IGNORECASE | re.DOTALL)
                mirrors = []
                for u, txt in anchors:
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)
                    clean_txt = re.sub(r"<[^>]+>", "", txt).strip()
                    mirrors.append((clean_txt, u))

                if mirrors:
                    releases.append({
                        "label": f"Episode {ep_num} [{lang}]",
                        "episode_number": ep_num,
                        "season_number": int(info["season"]) if "season" in info else 1,
                        "audio_languages": json.dumps([lang]),
                        "quality": "720p",
                        "resolution": "720p",
                        "mirrors": mirrors,
                    })

    # Pattern B: Movie / Generic download blocks
    if not releases:
        # Look for headings like "Hindi – Download" or Quality headings
        h_sections = re.finditer(r"<h[3-5][^>]*>(.*?)</h[3-5]>(.*?)(?=<h[3-5]|<hr\s*/?>|<footer|$)", content_html, re.IGNORECASE | re.DOTALL)
        for hs in h_sections:
            h_text = re.sub(r"<[^>]+>", "", hs.group(1)).strip()
            b_html = hs.group(2)
            anchors = re.findall(r'<a[^>]+href=["\'](https?://[^\s"\'<>]+)["\'][^>]*>(.*?)</a>', b_html, re.IGNORECASE | re.DOTALL)
            mirrors = []
            for u, txt in anchors:
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                clean_txt = re.sub(r"<[^>]+>", "", txt).strip()
                mirrors.append((clean_txt, u))

            if mirrors:
                # Check quality in heading
                q_m = re.search(r"\b(2160p|4k|1080p|720p|480p)\b", h_text, re.IGNORECASE)
                quality = q_m.group(1).lower() if q_m else "720p"
                releases.append({
                    "label": h_text if h_text else "Full Movie [HD]",
                    "episode_number": None,
                    "season_number": None,
                    "audio_languages": json.dumps(["Hindi"]),
                    "quality": quality,
                    "resolution": quality,
                    "mirrors": mirrors,
                })

    # Pattern C: Fallback to all content download anchors
    if not releases:
        all_anchors = re.findall(r'<a[^>]+href=["\'](https?://[^\s"\'<>]+)["\'][^>]*>(.*?)</a>', content_html, re.IGNORECASE | re.DOTALL)
        mirrors = []
        for u, txt in all_anchors:
            clean_txt = re.sub(r"<[^>]+>", "", txt).strip()
            if any(h in u.lower() for h in ["pixeldrain.com", "hubcloud.ist", "mega.nz", "yournewdomain.com", "razorshell.space"]):
                if u not in seen_urls:
                    seen_urls.add(u)
                    mirrors.append((clean_txt, u))
        if mirrors:
            releases.append({
                "label": "Download Release",
                "episode_number": None,
                "season_number": None,
                "audio_languages": json.dumps(["Hindi"]),
                "quality": "720p",
                "resolution": "720p",
                "mirrors": mirrors,
            })

    return info, releases


def extract_post_data_rareanimes(
    post_url: str,
    raw_post_json: dict | None = None,
    page_html: str | None = None,
    resolve_direct: bool = True,
    timeout: int = 12,
) -> dict | None:
    """Extracts post metadata, releases, and unwrapped sources from a RareAnimes post record."""
    if not raw_post_json and not page_html:
        return None

    raw_title = ""
    content_html = ""
    poster_url = None
    categories = []

    if raw_post_json:
        raw_title = raw_post_json.get("title", {}).get("rendered", "")
        content_html = raw_post_json.get("content", {}).get("rendered", "")
        post_url = raw_post_json.get("link", post_url)

        # Extract poster from _embedded
        embedded = raw_post_json.get("_embedded", {})
        media_list = embedded.get("wp:featuredmedia", [])
        if media_list and isinstance(media_list, list):
            poster_url = media_list[0].get("source_url")

        # Extract categories
        for tg in embedded.get("wp:term", []):
            if isinstance(tg, list):
                for t in tg:
                    if t.get("name"):
                        categories.append(t["name"])
    elif page_html:
        t_m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.IGNORECASE | re.DOTALL)
        raw_title = t_m.group(1) if t_m else ""
        content_m = re.search(r'<div[^>]+class=["\'][^"\']*entry-content[^"\']*["\'][^>]*>(.*?)</div>', page_html, re.IGNORECASE | re.DOTALL)
        content_html = content_m.group(1) if content_m else page_html

    clean_title, year, season, canonical_key = clean_rareanimes_title(raw_title)

    info, parsed_releases = parse_rareanimes_content(content_html)
    if not parsed_releases:
        return None

    # Refine title and metadata from info block if available
    if info.get("full_name"):
        clean_title = info["full_name"]
    if info.get("year"):
        try:
            year = int(info["year"])
        except ValueError:
            pass
    if info.get("season"):
        try:
            season = int(info["season"])
        except ValueError:
            pass

    # Media type detection
    is_series = bool(season or any(r.get("episode_number") for r in parsed_releases) or "episodes" in raw_title.lower())
    media_type = "series" if is_series else "movie"

    # Process releases & unwrap mirrors
    releases_data = []
    for r in parsed_releases:
        sources = []
        bridge_url = None

        for label, u in r.get("mirrors", []):
            ulow = u.lower()

            # 1. PixelDrain Direct CDN
            if "pixeldrain.com" in ulow:
                pd_id_m = re.search(r"pixeldrain\.com/(?:u|d|api/file)/([A-Za-z0-9_-]+)", u)
                if pd_id_m:
                    pd_id = pd_id_m.group(1)
                    direct_pd = f"https://pixeldrain.com/api/file/{pd_id}"
                    bridge_url = bridge_url or u
                    sources.append({
                        "source_name": "⚡ PixelDrain [Direct CDN]",
                        "service": "pixeldrain",
                        "resource_id": pd_id,
                        "source_url": u,
                        "final_url": direct_pd,
                        "is_temporary": 0,
                        "quality": r.get("quality", "720p"),
                    })

            # 2. HubCloud Drive
            elif "hubcloud.ist" in ulow:
                bridge_url = bridge_url or u
                if resolve_direct:
                    try:
                        unwrapped = fast_fetch.unwrap_hubcloud_drive(u)
                    except Exception:
                        unwrapped = []
                    for src in unwrapped:
                        sources.append({
                            "source_name": src.get("source_name", "⚡ HubCloud Stream"),
                            "service": src.get("service", "hubcloud"),
                            "resource_id": src.get("resource_id", ""),
                            "source_url": u,
                            "final_url": src.get("final_url", u),
                            "is_temporary": src.get("is_temporary", 0),
                            "quality": r.get("quality", "720p"),
                        })
                else:
                    sources.append({
                        "source_name": "⚡ HubCloud Drive",
                        "service": "hubcloud",
                        "resource_id": u.rstrip("/").split("/")[-1],
                        "source_url": u,
                        "final_url": u,
                        "is_temporary": 0,
                        "quality": r.get("quality", "720p"),
                    })

            # 3. Mega.nz mirror
            elif "mega.nz" in ulow:
                bridge_url = bridge_url or u
                sources.append({
                    "source_name": "⚡ Mega Mirror",
                    "service": "mega",
                    "resource_id": u.rstrip("/").split("/")[-1],
                    "source_url": u,
                    "final_url": u,
                    "is_temporary": 0,
                    "quality": r.get("quality", "720p"),
                })

            # 4. Razorshell / MultiQuality
            elif "razorshell.space" in ulow or "multiquality" in ulow:
                bridge_url = bridge_url or u
                sources.append({
                    "source_name": "⚡ MultiQuality Fast DL",
                    "service": "razorshell",
                    "resource_id": u.rstrip("/").split("/")[-1],
                    "source_url": u,
                    "final_url": u,
                    "is_temporary": 0,
                    "quality": r.get("quality", "720p"),
                })

        if sources:
            releases_data.append({
                "label": r.get("label"),
                "quality": r.get("quality"),
                "resolution": r.get("resolution"),
                "size_bytes": None,
                "season_number": r.get("season_number"),
                "episode_number": r.get("episode_number"),
                "audio_languages": r.get("audio_languages"),
                "codec": "x264",
                "bridge_url": bridge_url or "",
                "sources": sources,
            })

    if not releases_data:
        return None

    return {
        "canonical_key": canonical_key,
        "title": clean_title,
        "original_title": html.unescape(raw_title).strip(),
        "year": year,
        "media_type": media_type,
        "imdb_id": None,
        "poster_url": poster_url,
        "genres": json.dumps(categories) if categories else None,
        "synopsis": info.get("synopsis"),
        "site": "rareanimes",
        "post_url": post_url,
        "releases": releases_data,
    }


def save_post_to_staging_db(db_path: Path, post_data: dict) -> bool:
    """Persists post metadata, releases, and direct sources into isolated staging database."""
    if not post_data or not post_data.get("releases"):
        return False

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()

        # 1. Upsert Post
        cur.execute(
            """
            INSERT INTO posts (
                canonical_key, title, original_title, year, media_type,
                imdb_id, poster_url, synopsis, genres, site, post_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                original_title = excluded.original_title,
                year = COALESCE(excluded.year, posts.year),
                media_type = excluded.media_type,
                poster_url = COALESCE(excluded.poster_url, posts.poster_url),
                synopsis = COALESCE(excluded.synopsis, posts.synopsis),
                genres = COALESCE(excluded.genres, posts.genres),
                post_url = excluded.post_url,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id;
            """,
            (
                post_data["canonical_key"],
                post_data["title"],
                post_data["original_title"],
                post_data["year"],
                post_data["media_type"],
                post_data.get("imdb_id"),
                post_data.get("poster_url"),
                post_data.get("synopsis"),
                post_data.get("genres"),
                post_data["site"],
                post_data["post_url"],
            ),
        )
        row = cur.fetchone()
        post_id = row[0] if row else None
        if not post_id:
            cur.execute("SELECT id FROM posts WHERE canonical_key = ?", (post_data["canonical_key"],))
            post_id = cur.fetchone()[0]

        # 2. Insert Releases & Sources
        for r in post_data["releases"]:
            cur.execute(
                """
                INSERT INTO releases (
                    post_id, label, quality, resolution, size_bytes,
                    season_number, episode_number, audio_languages, codec, bridge_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id;
                """,
                (
                    post_id,
                    r.get("label"),
                    r.get("quality", "720p"),
                    r.get("resolution", "720p"),
                    r.get("size_bytes"),
                    r.get("season_number"),
                    r.get("episode_number"),
                    r.get("audio_languages"),
                    r.get("codec", "x264"),
                    r.get("bridge_url", ""),
                ),
            )
            rel_row = cur.fetchone()
            release_id = rel_row[0] if rel_row else None
            if not release_id:
                continue

            for s in r.get("sources", []):
                cur.execute(
                    """
                    INSERT INTO sources (
                        release_id, source_name, service, resource_id,
                        source_url, final_url, is_temporary, quality
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        release_id,
                        s["source_name"],
                        s["service"],
                        s["resource_id"],
                        s["source_url"],
                        s["final_url"],
                        s["is_temporary"],
                        s["quality"],
                    ),
                )

        conn.commit()
    return True


def sync_wp_api_to_db(db_path: Path, per_page: int = 100) -> int:
    """Syncs the entire RareAnimes catalog via WP REST API (/wp/v2/posts) into sitemap_cache."""
    init_staging_db(db_path)
    client = RareAnimesClient()

    print(f"[*] Starting WP REST API sync from {WP_API_URL}...", flush=True)
    page = 1
    total_synced = 0
    total_found = None

    while not STOP_REQUESTED:
        query_url = f"{WP_API_URL}?per_page={per_page}&page={page}&_embed=1"
        t0 = time.time()
        code, posts, headers = client.get_json(query_url, timeout=15)
        dt = time.time() - t0

        if code != 200 or not posts or not isinstance(posts, list):
            print(f"[!] API page {page} returned status {code}. Stopping sync.", flush=True)
            break

        if total_found is None:
            total_found = int(headers.get("x-wp-total", 0)) if "x-wp-total" in headers else len(posts)
            print(f"[*] Total catalog size reported: {total_found:,} titles.", flush=True)

        records = []
        for post in posts:
            permalink = post.get("link")
            if not permalink:
                continue
            slug = post.get("slug")
            lastmod = post.get("modified") or post.get("date")
            raw_json_str = json.dumps(post)
            records.append((permalink, lastmod, slug, 0, "rareanimes", raw_json_str))

        if records:
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(loc) DO UPDATE SET
                        lastmod = excluded.lastmod,
                        slug = excluded.slug,
                        raw_json = excluded.raw_json;
                    """,
                    records,
                )
                conn.commit()

            total_synced += len(records)
            print(
                f"  [Page {page:2d}] Synced {len(records)} titles in {dt:.2f}s "
                f"({total_synced:,} / {total_found:,} total)",
                flush=True,
            )

        if len(posts) < per_page or total_synced >= (total_found or 0):
            break

        page += 1

    print(f"\n[✓] WP REST API sync finished: {total_synced:,} titles stored in {db_path.name}\n", flush=True)
    return total_synced


def sync_master_movies_index(db_path: Path) -> int:
    """Extra discovery channel: parses /all-anime-cartoon-movies-list/ to catch all movie links."""
    init_staging_db(db_path)
    client = RareAnimesClient()

    index_url = f"{DEFAULT_BASE_URL}/all-anime-cartoon-movies-list/"
    print(f"[*] Fetching master movies index: {index_url}...", flush=True)
    code, _, page_html = client.get_text(index_url)
    if code != 200 or not page_html:
        print(f"[!] Failed to fetch master movie list: HTTP {code}", flush=True)
        return 0

    movie_links = re.findall(r'href=["\'](https?://www\.rareanimes\.mov/[^\s"\'<>]+)["\']', page_html)
    filtered = [l for l in dict.fromkeys(movie_links) if not any(x in l for x in ["/category/", "/tag/", "/contact", "/page/"])]
    records = [(l, None, l.rstrip("/").split("/")[-1], 0, "rareanimes", None) for l in filtered]

    if records:
        with sqlite3.connect(str(db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(loc) DO NOTHING;
                """,
                records,
            )
            conn.commit()

    print(f"[✓] Synced {len(records):,} movie links from master index.\n", flush=True)
    return len(records)


def run_crawler(
    db_path: Path,
    workers: int = 5,
    delay: float = 0.3,
    limit: int | None = None,
    resolve_direct: bool = True,
):
    """Multi-threaded background crawler for RareAnimes with rate limiting and progress updates."""
    init_staging_db(db_path)
    client = RareAnimesClient(request_interval=delay)

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        query = "SELECT loc, raw_json FROM sitemap_cache WHERE scraped = 0 ORDER BY rowid ASC"
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        pending_rows = cur.fetchall()

    if not pending_rows:
        print("[*] No pending titles found in sitemap_cache. Run --sync-api first.", flush=True)
        return

    total_pending = len(pending_rows)
    print(f"[*] Starting RareAnimes crawler: {total_pending:,} titles queued | {workers} workers | delay {delay}s\n", flush=True)

    completed = 0
    failed = 0
    total_releases = 0
    total_sources = 0
    total_r2 = 0
    total_pd = 0
    start_time = time.time()

    def process_item(item):
        loc, raw_json_str = item
        raw_post_json = json.loads(raw_json_str) if raw_json_str else None

        page_html = None
        if not raw_post_json or not raw_post_json.get("content", {}).get("rendered"):
            code, _, page_html = client.get_text(loc, timeout=12)
            if code != 200 or not page_html:
                return loc, False, 0, 0, 0, 0

        post_data = extract_post_data_rareanimes(
            post_url=loc,
            raw_post_json=raw_post_json,
            page_html=page_html,
            resolve_direct=resolve_direct,
        )
        if not post_data or not post_data.get("releases"):
            return loc, False, 0, 0, 0, 0

        ok = save_post_to_staging_db(db_path, post_data)
        num_rels = len(post_data["releases"])
        num_srcs = sum(len(r.get("sources", [])) for r in post_data["releases"])
        r2_cnt = sum(1 for r in post_data["releases"] for s in r.get("sources", []) if s.get("service") == "fsl_r2")
        pd_cnt = sum(1 for r in post_data["releases"] for s in r.get("sources", []) if s.get("service") == "pixeldrain")
        return loc, ok, num_rels, num_srcs, r2_cnt, pd_cnt

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, MAX_SAFE_WORKERS)) as executor:
        futures = {executor.submit(process_item, row): row for row in pending_rows}

        for future in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED:
                break
            loc, ok, rel_cnt, src_cnt, r2_cnt, pd_cnt = future.result()

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "UPDATE sitemap_cache SET scraped = ? WHERE loc = ?",
                    (1 if ok else -1, loc),
                )
                conn.commit()

            if ok:
                completed += 1
                total_releases += rel_cnt
                total_sources += src_cnt
                total_r2 += r2_cnt
                total_pd += pd_cnt
            else:
                failed += 1

            if (completed + failed) % 10 == 0 or (completed + failed) == total_pending:
                elapsed = time.time() - start_time
                speed = (completed + failed) / elapsed if elapsed > 0 else 0.0
                rem = (total_pending - (completed + failed)) / speed if speed > 0 else 0
                eta_str = time.strftime("%H:%M:%S", time.gmtime(rem))
                print(
                    f"  [{completed + failed:,}/{total_pending:,}] "
                    f"releases={total_releases:,} sources={total_sources:,} "
                    f"failed={failed} speed={speed:.2f} t/s ETA: {eta_str}",
                    flush=True,
                )

                # Write status file
                status_payload = {
                    "completed": completed,
                    "failed": failed,
                    "total_pending": total_pending,
                    "total_releases": total_releases,
                    "total_sources": total_sources,
                    "r2_sources": total_r2,
                    "pixeldrain_sources": total_pd,
                    "speed": round(speed, 2),
                    "eta": eta_str,
                    "timestamp": time.time(),
                }
                try:
                    with open(STATUS_FILE, "w") as sf:
                        json.dump(status_payload, sf)
                except Exception:
                    pass

    print(f"\n[✓] Crawler finished: {completed:,} scraped, {failed} failed in {time.time() - start_time:.1f}s\n", flush=True)


def print_status(db_path: Path):
    """Prints current metrics and counts for RareAnimes staging database."""
    if not db_path.exists():
        print(f"[!] Database {db_path} does not exist.")
        return

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        total_cache = cur.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        scraped_cache = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0]
        pending_cache = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0").fetchone()[0]
        failed_cache = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0]

        total_posts = cur.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        total_releases = cur.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        total_sources = cur.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        r2_sources = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'fsl_r2'").fetchone()[0]
        pd_sources = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'pixeldrain'").fetchone()[0]
        mega_sources = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'mega'").fetchone()[0]

    pct = (scraped_cache / total_cache * 100) if total_cache > 0 else 0.0
    print(f"\n=======================================================")
    print(f" 📦 RareAnimes Staging Database Status ({db_path.name})")
    print(f"=======================================================")
    print(f" Sitemap Cache Total : {total_cache:,}")
    print(f" Scraped (Done)      : {scraped_cache:,} ({pct:.1f}%)")
    print(f" Pending             : {pending_cache:,}")
    print(f" Failed/Review       : {failed_cache:,}")
    print(f"-------------------------------------------------------")
    print(f" Catalog Posts       : {total_posts:,}")
    print(f" Releases Found      : {total_releases:,}")
    print(f" Direct Sources      : {total_sources:,}")
    print(f"   ⚡ PixelDrain CDN  : {pd_sources:,} (Instant Video/Matroska)")
    print(f"   ⚡ Cloudflare R2   : {r2_sources:,} (10Gbps direct stream)")
    print(f"   ⚡ Mega Mirrors    : {mega_sources:,}")
    print(f"=======================================================\n")


def main():
    parser = argparse.ArgumentParser(description="RareAnimes Dedicated Staging Importer & Crawler")
    parser.add_argument("--sync-api", action="store_true", help="Sync all titles via WP REST API")
    parser.add_argument("--sync-index", action="store_true", help="Sync all movies from master movie index page")
    parser.add_argument("--limit", type=int, help="Limit number of titles to scrape")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers (default 5)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests in seconds (default 0.3)")
    parser.add_argument("--no-resolve", action="store_true", help="Skip unwrapping HubCloud to direct links")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH), help="Path to staging SQLite database")
    parser.add_argument("--status", action="store_true", help="Show staging database status")

    args = parser.parse_args()
    db_path = Path(args.db_path)

    if args.status:
        print_status(db_path)
        return

    if args.sync_api:
        sync_wp_api_to_db(db_path)
        return

    if args.sync_index:
        sync_master_movies_index(db_path)
        return

    run_crawler(
        db_path=db_path,
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        resolve_direct=not args.no_resolve,
    )


if __name__ == "__main__":
    main()
