#!/usr/bin/env python3
"""
import_10xflix.py — Dedicated staging importer and scraper for 10xflix (https://10xflix.bond).

Key Features:
  1. Dedicated staging SQLite database: 10xflix.db (strictly isolated from fast_fetch.db).
  2. Full WP REST API Synchronization:
     - Ingests all ~17,604 titles across 177 pages via /wp-json/wp/v2/posts?per_page=100&_embed=1.
     - Captures featured media posters, categories, slugs, and timestamps.
  3. Clean Title & Media Metadata Normalization:
     - Detects season (S01..S99) and episode (E01..E99) from title/slug.
     - Generates clean canonical keys for deduplication.
  4. MobileJSR Multi-Mirror Link Resolution:
     - Extracts resolution tiers (4K 2160p, 1080p, 720p, 480p) and exact file sizes (e.g. 2.02GB, 997MB).
     - Unwraps MobileJSR gateway links into direct streaming sources:
       * HubCloud 10Gbps Fast Server (gpdl*.hubcloud.ist)
       * HubDrive Cloud mirrors
       * FilePress Google Drive direct CDN
       * 1fichier High-Speed mirrors
       * GoFile Cloud storage
       * Stream Player streams (Voe, Streamtape)
  5. Resumable via sitemap_cache table in staging SQLite database.
  6. 100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_10xflix.py --sync-api --max-pages 5       # Ingest first 5 pages (500 titles)
    python Fast_Fetch/import_10xflix.py --sync-api                     # Ingest entire catalog (~17,604 titles)
    python Fast_Fetch/import_10xflix.py --limit 10                     # Scrape 10 pending titles
    python Fast_Fetch/import_10xflix.py --workers 5 --delay 0.3        # Full background crawler
    python Fast_Fetch/import_10xflix.py --status                       # Show staging DB metrics
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

DEFAULT_BASE_URL = "https://10xflix.bond"
WP_API_URL = f"{DEFAULT_BASE_URL}/wp-json/wp/v2/posts"
DEFAULT_DB_PATH = (
    Path("/home/ubuntu/radd-stream-data/10xflix.db")
    if Path("/home/ubuntu/radd-stream-data").exists()
    else BASE_DIR / "10xflix.db"
)
STATUS_FILE = BASE_DIR / "10xflix_status.json"

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


class TenXFlixClient:
    """HTTP Client with rate limiting and retry handling for 10xflix."""

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

    def get_text(self, url: str, referer: str | None = None, timeout: int = 15) -> tuple[int, str, str, dict]:
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
                return 0, url, "", {}
            self._wait()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_ctx) as resp:
                    code = resp.status
                    final_url = resp.geturl()
                    resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                    text = resp.read().decode("utf-8", errors="replace")
                    return code, final_url, text, resp_headers
            except urllib.error.HTTPError as e:
                if attempt == self.retries - 1:
                    return e.code, url, "", {}
                time.sleep(1.0)
            except Exception:
                if attempt == self.retries - 1:
                    return 0, url, "", {}
                time.sleep(1.0)
        return 0, url, "", {}

    def get_json(self, url: str, referer: str | None = None, timeout: int = 15) -> tuple[int, any, dict]:
        code, final_url, text, resp_headers = self.get_text(url, referer=referer, timeout=timeout)
        if code != 200 or not text:
            return code, None, resp_headers
        try:
            return code, json.loads(text), resp_headers
        except Exception:
            return code, None, resp_headers


def init_staging_db(db_path: Path):
    """Initializes schema in dedicated isolated staging database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                site TEXT DEFAULT '10xflix',
                raw_json TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_10xflix_scraped ON sitemap_cache(scraped);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_key TEXT UNIQUE,
                title TEXT,
                original_title TEXT,
                year INTEGER,
                media_type TEXT,
                imdb_id TEXT,
                poster_url TEXT,
                synopsis TEXT,
                genres TEXT,
                cast_names TEXT,
                director TEXT,
                languages TEXT,
                is_18_plus INTEGER DEFAULT 0,
                site TEXT DEFAULT '10xflix',
                post_url TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _xcols = {c[1] for c in cur.execute("PRAGMA table_info(posts);").fetchall()}
        if "is_18_plus" not in _xcols:
            try:
                cur.execute("ALTER TABLE posts ADD COLUMN is_18_plus INTEGER DEFAULT 0;")
            except Exception:
                pass
        cur.execute("CREATE INDEX IF NOT EXISTS idx_10xflix_canonical ON posts(canonical_key);")

        # Auto-migration for schema changes
        existing_cols = [c[1] for c in cur.execute("PRAGMA table_info(posts);").fetchall()]
        for col in ["cast_names", "director", "languages"]:
            if col not in existing_cols:
                try:
                    cur.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT;")
                except Exception:
                    pass

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                label TEXT,
                quality TEXT,
                resolution TEXT,
                size_bytes INTEGER,
                season_number INTEGER,
                episode_number INTEGER,
                audio_languages TEXT,
                codec TEXT,
                bridge_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_10xflix_rel_post ON releases(post_id);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_10xflix_src_rel ON sources(release_id);")
        conn.commit()


def parse_size_string(size_str: str) -> int | None:
    """Converts size strings like '2.02GB' or '997MB' to integer bytes."""
    if not size_str:
        return None
    m = re.search(r"([0-9\.]+)\s*(GB|MB|KB)", size_str, re.IGNORECASE)
    if not m:
        return None
    raw_num = m.group(1).strip().rstrip(".")
    try:
        val = float(raw_num)
    except (ValueError, TypeError):
        return None
    unit = m.group(2).upper()
    if unit == "GB":
        return int(val * 1024 * 1024 * 1024)
    elif unit == "MB":
        return int(val * 1024 * 1024)
    elif unit == "KB":
        return int(val * 1024)
    return None


def extract_wp_post_metadata(content_html: str) -> dict:
    """
    Extracts rich metadata (director, cast_names, genres, languages, synopsis, rating)
    from standard WordPress movie post HTML. Zero external dependencies. Stdlib only.
    """
    if not content_html:
        return {}

    text = html.unescape(content_html)

    # 1. Director
    director = None
    d_m = re.search(r'(?:Director|Directed\s*by)[s]?\s*:\s*([^<\n]+)', text, re.I)
    if d_m:
        clean_d = re.sub(r'<[^>]+>', '', d_m.group(1)).strip()
        if clean_d and len(clean_d) < 150:
            director = clean_d

    # 2. Cast / Stars
    cast_names = None
    c_m = re.search(r'(?:Stars?|Star\s*Cast|Cast|Starring)\s*:\s*([^<\n]+)', text, re.I)
    if c_m:
        clean_c = re.sub(r'<[^>]+>', '', c_m.group(1)).strip()
        if clean_c and len(clean_c) < 300:
            cast_names = clean_c

    # 3. Genres
    genres = None
    g_m = re.search(r'Genre[s]?\s*:\s*([^<\n]+)', text, re.I)
    if g_m:
        clean_g = re.sub(r'<[^>]+>', '', g_m.group(1)).strip()
        if clean_g:
            raw_genres = [re.sub(r'[^a-zA-Z0-9\s-]', '', g).strip() for g in re.split(r'[,\|/]', clean_g)]
            clean_list = [g for g in raw_genres if g and len(g) > 1 and len(g) < 40]
            if clean_list:
                genres = json.dumps(clean_list)

    # 4. Languages
    languages = None
    l_m = re.search(r'Language[s]?\s*:\s*([^<\n]+)', text, re.I)
    if l_m:
        clean_l = re.sub(r'<[^>]+>', '', l_m.group(1)).strip()
        if clean_l and len(clean_l) < 100:
            languages = clean_l

    # 5. Synopsis / Storyline
    synopsis = None
    s_m = re.search(
        r'<(?:strong|b|span|h\d)[^>]*>\s*(?:Film\s*Story|Story|Synopsis|Plot|Storyline)[^<]*</(?:strong|b|span|h\d)>\s*[:\-–]?\s*([^<\n]+)',
        text,
        re.I,
    )
    if not s_m:
        s_m = re.search(
            r'(?:^|>)\s*(?:Film\s*Story|Story|Synopsis|Plot|Storyline)\s*[:\-–]\s*([^<\n]+)',
            text,
            re.I,
        )
    if s_m:
        clean_s = re.sub(r'<[^>]+>', '', s_m.group(1)).strip()
        clean_s = re.sub(r'^[:\-–\s]+', '', clean_s)
        if len(clean_s) > 15:
            synopsis = clean_s

    # 6. IMDb Rating
    rating = None
    r_m = re.search(r'IMDb\s*(?:Ratings?|Rating)?\s*:\s*([0-9\.]+)(?:/10)?', text, re.I)
    if r_m:
        try:
            rating = float(r_m.group(1))
        except ValueError:
            rating = None

    # 7. IMDb ID
    imdb_id = None
    imdb_m = re.search(r'\b(tt\d{7,10})\b', text)
    if imdb_m:
        imdb_id = imdb_m.group(1)

    return {
        "director": director,
        "cast_names": cast_names,
        "genres": genres,
        "languages": languages,
        "synopsis": synopsis,
        "rating": rating,
        "imdb_id": imdb_id,
    }


def clean_10xflix_title(raw_title: str) -> tuple[str, int | None, int | None, int | None, str]:
    """
    Cleans raw 10xflix title into canonical metadata.
    Example:
      'Street Fighter (2026) Hindi (Cleaned) Movie HQ HDTC | 1080p | 720p | 480p'
      -> ('Street Fighter', 2026, None, None, 'street-fighter_2026')
      'Sa Re Ga Ma Pa (2026) Hindi ORG S01E10 Series HDRip | 1080p | 720p | 480p'
      -> ('Sa Re Ga Ma Pa', 2026, 1, 10, 'sa-re-ga-ma-pa_2026_s1_e10')
    """
    t = html.unescape(raw_title).strip()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Detect Season and Episode (e.g. S01E10 or Season 1 Episode 10)
    season = None
    episode = None
    se_m = re.search(r"\bS(\d{1,2})E(\d{1,3})\b", t, re.IGNORECASE)
    if se_m:
        season = int(se_m.group(1))
        episode = int(se_m.group(2))
    else:
        s_m = re.search(r"\bSeason\s*(\d+)\b", t, re.IGNORECASE)
        if s_m:
            season = int(s_m.group(1))
        ep_m = re.search(r"\bEpisode\s*(\d+)\b", t, re.IGNORECASE)
        if ep_m:
            episode = int(ep_m.group(1))

    # Detect Year
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    year = int(year_m.group(1)) if year_m else None

    # Strip resolution bars and suffixes
    clean = re.sub(r"\|.*$", "", t).strip()

    # Strip common technical tags
    clean = re.sub(
        r"\s*(?:Hindi|English|Tamil|Telugu|Dual\s*Audio|ORG|Cleaned|CLEAN|Movie|Series|HQ\s*HDTC|HDTC|HDRip|WEB-DL|BluRay|ESubs|Multi\s*Audio).*$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()

    # Strip S01E01 tokens
    clean = re.sub(r"\bS\d+E\d+\b", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s*\(\s*(?:19|20)\d{2}\s*\)", "", clean).strip()
    clean = re.sub(r"\s+", " ", clean).strip(" -:|")

    canonical_key = fast_fetch.generate_canonical_key(clean, year)
    if season:
        canonical_key = f"{canonical_key}_s{season}"
    if episode:
        canonical_key = f"{canonical_key}_e{episode}"

    return clean, year, season, episode, canonical_key


def parse_10xflix_releases(content_html: str, post_title: str) -> list[dict]:
    """
    Parses MobileJSR download buttons and resolution/size labels from post content.
    Example button:
      <a href="https://mobilejsr.com/view/heZxR9W5aL">1080p [2.02GB]</a>
    """
    releases = []
    anchors = re.findall(
        r'<a\s+[^>]*href=["\'](https?://mobilejsr\.com/view/[a-zA-Z0-9_\-]+)["\'][^>]*>(.*?)</a>',
        content_html,
        re.IGNORECASE | re.DOTALL,
    )

    seen_urls = set()
    for href, txt in anchors:
        if href in seen_urls:
            continue
        seen_urls.add(href)

        clean_txt = re.sub(r"<[^>]+>", "", txt).strip()
        # Quality detection
        q_m = re.search(r"\b(2160p|4k|1080p|720p|480p)\b", clean_txt, re.IGNORECASE)
        quality = q_m.group(1).lower() if q_m else "720p"

        # Size detection
        sz_m = re.search(r"\[([0-9\.]+\s*(?:GB|MB|KB))\]", clean_txt, re.IGNORECASE)
        size_bytes = parse_size_string(sz_m.group(1)) if sz_m else None

        releases.append({
            "label": clean_txt if clean_txt else f"{quality.upper()} Release",
            "quality": quality,
            "resolution": quality,
            "size_bytes": size_bytes,
            "bridge_url": href,
        })

    return releases


def extract_post_data_10xflix(
    raw_post_json: dict,
    resolve_direct: bool = True,
) -> dict | None:
    """Extracts post metadata, releases, and unwrapped sources from a 10xflix post record."""
    if not raw_post_json:
        return None

    raw_title = raw_post_json.get("title", {}).get("rendered", "")
    content_html = raw_post_json.get("content", {}).get("rendered", "")
    post_url = raw_post_json.get("link", "")

    # Extract poster from _embedded
    poster_url = None
    embedded = raw_post_json.get("_embedded", {})
    media_list = embedded.get("wp:featuredmedia", [])
    if media_list and isinstance(media_list, list):
        poster_url = media_list[0].get("source_url")

    # Extract categories
    categories = []
    for tg in embedded.get("wp:term", []):
        if isinstance(tg, list):
            for t in tg:
                if t.get("name"):
                    categories.append(t["name"])

    clean_title, year, season, episode, canonical_key = clean_10xflix_title(raw_title)

    # Detect media type
    is_series = bool(season is not None or "series" in raw_title.lower() or "web series" in str(categories).lower())
    media_type = "series" if is_series else "movie"

    # Extract releases
    parsed_releases = parse_10xflix_releases(content_html, raw_title)
    if not parsed_releases:
        return None

    releases_data = []
    for r in parsed_releases:
        bridge_url = r["bridge_url"]
        sources = []

        if resolve_direct:
            try:
                unwrapped = fast_fetch.unwrap_mobilejsr(bridge_url)
                for s in unwrapped:
                    sources.append({
                        "source_name": s.get("source_name", "⚡ Mirror Link"),
                        "service": s.get("service", "mobilejsr"),
                        "resource_id": s.get("resource_id", ""),
                        "source_url": s.get("source_url", bridge_url),
                        "final_url": s.get("final_url", bridge_url),
                        "is_temporary": s.get("is_temporary", 0),
                        "quality": r["quality"],
                    })
            except Exception:
                pass

        if not sources:
            sources.append({
                "source_name": "⚡ MobileJSR Gateway",
                "service": "mobilejsr",
                "resource_id": bridge_url.rstrip("/").split("/")[-1],
                "source_url": bridge_url,
                "final_url": bridge_url,
                "is_temporary": 0,
                "quality": r["quality"],
            })

        releases_data.append({
            "label": r["label"],
            "quality": r["quality"],
            "resolution": r["resolution"],
            "size_bytes": r["size_bytes"],
            "season_number": season,
            "episode_number": episode,
            "audio_languages": json.dumps(["Hindi"]),
            "codec": "x264",
            "bridge_url": bridge_url,
            "sources": sources,
        })

    meta = extract_wp_post_metadata(content_html)

    return {
        "canonical_key": canonical_key,
        "title": clean_title,
        "original_title": html.unescape(raw_title).strip(),
        "year": year,
        "media_type": media_type,
        "imdb_id": meta.get("imdb_id"),
        "poster_url": poster_url,
        "genres": meta.get("genres") or (json.dumps(categories) if categories else None),
        "synopsis": meta.get("synopsis"),
        "director": meta.get("director"),
        "cast_names": meta.get("cast_names"),
        "languages": meta.get("languages"),
        "site": "10xflix",
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
                imdb_id, poster_url, synopsis, genres, cast_names, director, languages, is_18_plus, site, post_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                original_title = excluded.original_title,
                year = COALESCE(excluded.year, posts.year),
                media_type = excluded.media_type,
                imdb_id = COALESCE(excluded.imdb_id, posts.imdb_id),
                poster_url = COALESCE(excluded.poster_url, posts.poster_url),
                synopsis = COALESCE(excluded.synopsis, posts.synopsis),
                genres = COALESCE(excluded.genres, posts.genres),
                cast_names = COALESCE(excluded.cast_names, posts.cast_names),
                director = COALESCE(excluded.director, posts.director),
                languages = COALESCE(excluded.languages, posts.languages),
                is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus),
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
                post_data.get("cast_names"),
                post_data.get("director"),
                post_data.get("languages"),
                fast_fetch.is_adult_title(post_data["title"], post_data.get("original_title")),
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


def sync_wp_api_to_db(db_path: Path, max_pages: int | None = None, per_page: int = 100) -> int:
    """Syncs the entire 10xflix catalog via WP REST API (/wp/v2/posts) into sitemap_cache."""
    init_staging_db(db_path)
    client = TenXFlixClient()

    print(f"[*] Starting 10xflix WP REST API sync from {WP_API_URL}...", flush=True)
    page = 1
    total_new = 0
    total_existing = 0
    consecutive_empty_new = 0
    total_found = None

    with sqlite3.connect(str(db_path)) as conn:
        existing_slugs = set(
            row[0] for row in conn.execute(
                "SELECT slug FROM sitemap_cache WHERE slug IS NOT NULL"
            ).fetchall()
        )
        existing_locs = set(
            row[0] for row in conn.execute(
                "SELECT loc FROM sitemap_cache WHERE loc IS NOT NULL"
            ).fetchall()
        )

    print(f"[*] Pre-loaded {len(existing_slugs):,} existing slugs and {len(existing_locs):,} existing locs from {db_path.name}.", flush=True)

    while not STOP_REQUESTED:
        query_url = f"{WP_API_URL}?per_page={per_page}&page={page}&_embed=1"
        t0 = time.time()
        code, posts, headers = client.get_json(query_url, timeout=15)
        dt = time.time() - t0

        if code != 200 or not posts or not isinstance(posts, list):
            print(f"[!] API page {page} returned status {code}. Stopping sync.", flush=True)
            break

        if total_found is None:
            if "x-wp-total" in headers:
                total_found = int(headers["x-wp-total"])
                print(f"[*] Total catalog size reported: {total_found:,} titles.", flush=True)
            else:
                total_found = None
                print("[*] Total catalog size header not present; paginating dynamically...", flush=True)

        new_records = []
        updated_records = []
        for post in posts:
            permalink = post.get("link")
            if not permalink:
                continue
            slug = post.get("slug")
            lastmod = post.get("modified") or post.get("date")
            raw_json_str = json.dumps(post)

            is_known = (slug and slug in existing_slugs) or (permalink in existing_locs)
            if is_known:
                updated_records.append((lastmod, raw_json_str, slug or permalink))
                total_existing += 1
            else:
                new_records.append((permalink, lastmod, slug, 0, "10xflix", raw_json_str))
                if slug:
                    existing_slugs.add(slug)
                existing_locs.add(permalink)
                total_new += 1

        with sqlite3.connect(str(db_path)) as conn:
            if new_records:
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(loc) DO NOTHING;
                    """,
                    new_records,
                )
            if updated_records:
                conn.executemany(
                    """
                    UPDATE sitemap_cache
                    SET lastmod = ?, raw_json = ?
                    WHERE slug = ? OR loc = ?;
                    """,
                    [(r[0], r[1], r[2], r[2]) for r in updated_records],
                )
            conn.commit()

        found_str = f"{total_found:,}" if total_found else "..."
        print(
            f"  [Page {page:3d}] Found {len(new_records)} brand new, {len(updated_records)} existing titles in {dt:.2f}s "
            f"(Cumulative New: {total_new:,} | Total API: {found_str})",
            flush=True,
        )

        if not new_records:
            consecutive_empty_new += 1
            if max_pages is None and consecutive_empty_new >= 3:
                print(f"[*] 3 consecutive pages with 0 new titles reached. Database is fully up-to-date with live catalog. Stopping sync.", flush=True)
                break
        else:
            consecutive_empty_new = 0

        if max_pages and page >= max_pages:
            print(f"[*] Reached requested max_pages limit ({max_pages}). Stopping sync.", flush=True)
            break

        if len(posts) < per_page:
            break

        page += 1

    print(f"\n[✓] 10xflix catalog sync finished: {total_new:,} brand new titles added to {db_path.name} (already had {total_existing:,})\n", flush=True)
    return total_new


def run_crawler(
    db_path: Path,
    workers: int = 5,
    delay: float = 0.3,
    limit: int | None = None,
    resolve_direct: bool = True,
):
    """Multi-threaded background crawler for 10xflix with rate limiting and progress updates."""
    init_staging_db(db_path)

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
    print(f"[*] Starting 10xflix crawler: {total_pending:,} titles queued | {workers} workers | delay {delay}s\n", flush=True)

    completed = 0
    failed = 0
    total_releases = 0
    total_sources = 0
    start_time = time.time()

    def process_item(item):
        loc, raw_json_str = item
        try:
            raw_post_json = json.loads(raw_json_str) if raw_json_str else None
            if not raw_post_json:
                return loc, False, 0, 0

            post_data = extract_post_data_10xflix(
                raw_post_json=raw_post_json,
                resolve_direct=resolve_direct,
            )
            if not post_data or not post_data.get("releases"):
                return loc, False, 0, 0

            ok = save_post_to_staging_db(db_path, post_data)
            num_rels = len(post_data["releases"])
            num_srcs = sum(len(r.get("sources", [])) for r in post_data["releases"])
            return loc, ok, num_rels, num_srcs
        except Exception as e:
            return loc, False, 0, 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, MAX_SAFE_WORKERS)) as executor:
        futures = {executor.submit(process_item, row): row for row in pending_rows}

        for future in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED:
                break
            try:
                loc, ok, rel_cnt, src_cnt = future.result()
            except Exception as e:
                item_row = futures.get(future)
                loc = item_row[0] if item_row else "unknown"
                ok = False
                rel_cnt, src_cnt = 0, 0

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
    """Prints current metrics and counts for 10xflix staging database."""
    if not db_path.exists():
        print(f"[!] Database {db_path} does not exist.")
        return

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        total_cache = cur.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        scraped = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0]
        pending = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0").fetchone()[0]
        failed = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0]

        posts = cur.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        releases = cur.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        sources = cur.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        hub_10g = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'hubcloud_10g'").fetchone()[0]
        filepress = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'filepress'").fetchone()[0]

    pct = (scraped / total_cache * 100) if total_cache > 0 else 0.0
    print("\n" + "=" * 55)
    print(f" 📦 10xflix Staging Database Status ({db_path.name})")
    print("=" * 55)
    print(f" Sitemap Cache Total : {total_cache:,}")
    print(f" Scraped (Done)      : {scraped:,} ({pct:.1f}%)")
    print(f" Pending             : {pending:,}")
    print(f" Failed/Review       : {failed:,}")
    print("-" * 55)
    print(f" Catalog Posts       : {posts:,}")
    print(f" Releases Found      : {releases:,}")
    print(f" Direct Sources      : {sources:,}")
    print(f"   ⚡ HubCloud 10G    : {hub_10g:,}")
    print(f"   ⚡ FilePress GDrive: {filepress:,}")
    print("=" * 55 + "\n")


def enrich_existing_metadata(db_path: Path):
    """
    Backfills/enriches metadata (director, cast_names, genres, languages, synopsis, imdb_id)
    for all existing posts in 10xflix staging database from cached raw_json.
    Runs 100% offline.
    """
    init_staging_db(db_path)
    print(f"[*] Starting offline metadata enrichment for {db_path}...", flush=True)
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT loc, raw_json FROM sitemap_cache WHERE raw_json IS NOT NULL;")
        rows = cur.fetchall()
        print(f"[*] Found {len(rows):,} cached post entries to process.", flush=True)

        updated = 0
        for loc, raw_json_str in rows:
            try:
                p_data = json.loads(raw_json_str)
                raw_title = p_data.get("title", {}).get("rendered", "")
                content_html = p_data.get("content", {}).get("rendered", "")
                if not content_html or not raw_title:
                    continue

                clean_title, year, season, episode, canonical_key = clean_10xflix_title(raw_title)
                meta = extract_wp_post_metadata(content_html)

                cur.execute(
                    """
                    UPDATE posts SET
                        synopsis = COALESCE(?, synopsis),
                        genres = COALESCE(?, genres),
                        cast_names = COALESCE(?, cast_names),
                        director = COALESCE(?, director),
                        languages = COALESCE(?, languages),
                        imdb_id = COALESCE(?, imdb_id)
                    WHERE canonical_key = ?;
                    """,
                    (
                        meta.get("synopsis"),
                        meta.get("genres"),
                        meta.get("cast_names"),
                        meta.get("director"),
                        meta.get("languages"),
                        meta.get("imdb_id"),
                        canonical_key,
                    ),
                )
                if cur.rowcount > 0:
                    updated += 1
            except Exception:
                continue

        print(f"[✓] Metadata enrichment complete: {updated:,} posts updated.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="10xflix Staging Importer & Crawler")
    parser.add_argument("--sync-api", action="store_true", help="Sync posts via WP REST API")
    parser.add_argument("--enrich-metadata", action="store_true", help="Enrich existing posts table with cast/director/genres/synopsis from cached raw_json")
    parser.add_argument("--max-pages", type=int, default=None, help="Max catalog pages to sync")
    parser.add_argument("--status", action="store_true", help="Print staging DB statistics")
    parser.add_argument("--workers", type=int, default=5, help="Crawler concurrent threads")
    parser.add_argument("--delay", type=float, default=0.3, help="Request interval delay in seconds")
    parser.add_argument("--limit", type=int, default=None, help="Scrape up to N pending titles")
    parser.add_argument("--no-resolve-direct", action="store_true", help="Skip unwrapping MobileJSR to final direct streams")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to staging SQLite database")

    args = parser.parse_args()

    if args.status:
        print_status(args.db_path)
        return

    if args.enrich_metadata:
        enrich_existing_metadata(args.db_path)
        return

    if args.sync_api:
        sync_wp_api_to_db(args.db_path, max_pages=args.max_pages)
        return

    run_crawler(
        db_path=args.db_path,
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        resolve_direct=not args.no_resolve_direct,
    )


if __name__ == "__main__":
    main()
