#!/usr/bin/env python3
"""
import_hdhub4u.py — Dedicated staging importer and scraper for HDHub4u (https://new8.hdhub4u.cl).

Key Features:
  1. Dedicated staging SQLite database: hdhub4u.db (strictly isolated from production fast_fetch.db).
  2. Ultra-Fast Search API Sync: Paginates https://search.pingora.fyi/collections/post/documents/search
     at 250 items/page to index all 14,500+ titles in ~35 seconds with full metadata (IMDB ID, thumbnail, cast).
  3. XML Sitemap Sync Fallback: Paginates sitemap.xml and all post-sitemap*.xml sub-sitemaps.
  4. Dynamic Domain Tracking: Auto-resolves current active domain via https://h4.suncdn.org/host/.
  5. Clean Metadata Extraction:
     - Strips Material Icon glyphs and HTML entities.
     - Clean title, release year, canonical key, IMDB ID, TMDB poster, cast stars, director, categories.
  6. Multi-Tier Release & Episode Extraction:
     - 4K UHD, 1080p BluRay/WEB-DL, 720p HD/HEVC, 480p tiers with exact file sizes and codecs.
     - TV Series episode breakdown (EPiSODE 1, 2, ... with season & episode numbers).
  7. High-Speed Direct Stream Unwrapping (Greenmotors -> HubCloud -> Cloudflare R2 / PixelDrain):
     - Unpacks 4-layer payload (b64 -> b64 -> rot13 -> b64 -> json -> b64).
     - Resolves 10Gbps Cloudflare R2 (r2.cloudflarestorage.com), PixelDrain CDN, and HubCloud mirrors.
  8. Resumable via sitemap_cache table in staging SQLite database.
  9. 100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_hdhub4u.py --sync-api               # Ingest all 14,500+ titles via fast API
    python Fast_Fetch/import_hdhub4u.py --sync-sitemap           # Ingest all XML sitemaps
    python Fast_Fetch/import_hdhub4u.py --limit 10               # Scrape 10 pending titles
    python Fast_Fetch/import_hdhub4u.py --workers 5 --delay 0.3 # Full background crawler
    python Fast_Fetch/import_hdhub4u.py --status                 # Show staging DB metrics
"""

from __future__ import annotations

import argparse
import base64
import codecs
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

DEFAULT_BASE_URL = "https://new8.hdhub4u.cl"
HOST_RESOLVER_URL = "https://h4.suncdn.org/host/"
TYPESENSE_SEARCH_URL = "https://search.pingora.fyi/collections/post/documents/search"
DEFAULT_DB_PATH = BASE_DIR / "hdhub4u.db"
STATUS_FILE = BASE_DIR / "hdhub4u_status.json"

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


class HDHub4uClient:
    """HTTP Client with rate limiting, retry handling, and dynamic host detection for HDHub4u."""

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

    def resolve_live_host(self) -> str:
        """Queries central host resolver to get current active domain."""
        try:
            req = urllib.request.Request(
                HOST_RESOLVER_URL,
                headers={"User-Agent": fast_fetch.USER_AGENT},
            )
            with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                raw_c = data.get("c", "")
                if raw_c:
                    resolved = base64.b64decode(raw_c).decode("utf-8", "ignore").split("?")[0].rstrip("/")
                    if resolved.startswith("http"):
                        self.base_url = resolved
                        return resolved
        except Exception:
            pass
        return self.base_url

    def get_text(self, url: str, referer: str | None = None, origin: str | None = None, timeout: int = 15) -> tuple[int, str, str]:
        headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if origin:
            headers["Origin"] = origin
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

    def get_json(self, url: str, referer: str | None = None, origin: str | None = None, timeout: int = 15) -> tuple[int, dict | list | None]:
        code, final_url, text = self.get_text(url, referer=referer, origin=origin, timeout=timeout)
        if code != 200 or not text:
            return code, None
        try:
            data = json.loads(text)
            return code, data
        except Exception:
            return code, None


def init_staging_db(db_path: Path):
    """Initializes HDHub4u staging SQLite database with isolated schema."""
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
                site TEXT DEFAULT 'hdhub4u',
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
                site TEXT DEFAULT 'hdhub4u',
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


def decode_greenmotors_payload(payload_b64: str) -> str | None:
    """
    Decodes the 4-layer obfuscated greenmotors payload:
    b64 -> b64 -> rot_13 -> b64 -> JSON {'o': b64_dest} -> b64 -> dest_url
    """
    try:
        p1 = base64.b64decode(payload_b64).decode("utf-8", errors="replace")
        p2 = base64.b64decode(p1).decode("utf-8", errors="replace")
        p3 = codecs.decode(p2, "rot_13")
        p4 = base64.b64decode(p3).decode("utf-8", errors="replace")
        data = json.loads(p4)
        if isinstance(data, dict) and "o" in data:
            return base64.b64decode(data["o"]).decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def parse_size_to_bytes(size_str: str | None) -> int | None:
    if not size_str:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB)", size_str, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "GB":
        return int(val * 1024 * 1024 * 1024)
    elif unit == "MB":
        return int(val * 1024 * 1024)
    elif unit == "KB":
        return int(val * 1024)
    return None


def clean_hdhub4u_title(raw_title: str) -> tuple[str, int | None, str]:
    """
    Cleans raw HDHub4u heading/title into (clean_title, year, canonical_key).
    Strips Material Icons glyphs (like &#xE02C; or \ue02c), language tags, and quality suffixes.
    """
    t = html.unescape(raw_title)
    # Strip HTML tags
    t = re.sub(r"<[^>]+>", " ", t)
    # Strip Material Icons or unicode private use characters
    t = re.sub(r"[\ue000-\uf8ff]", "", t)
    t = re.sub(r"&#x[a-fA-F0-9]+;", "", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Extract Year
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    year = int(year_m.group(1)) if year_m else None

    # Clean title
    clean = re.sub(r"\s*\(\s*(?:19|20)\d{2}\s*\).*$", "", t)
    # Remove quality / audio / format suffixes
    clean = re.sub(
        r"\s*(?:1080p|720p|480p|2160p|4k|ds4k|web-dl|webrip|hdrip|bluray|hdtc|cleanhq|dvdrip|esubs|dual audio|multi audio|hindi|org|line|studio-dub|all episodes|completed|full movie).*$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    # Remove Season tags like (Season 2) or S02
    clean = re.sub(r"\s*\(\s*Season\s*\d+\s*\)", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+Season\s*\d+", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+", " ", clean).strip(" -:|")

    canonical_key = fast_fetch.generate_canonical_key(clean, year)
    return clean, year, canonical_key


def parse_hdhub4u_release_links(page_html: str) -> list[dict]:
    """
    Extracts all movie releases and TV series episode download links with quality, size, and greenmotors bridge.
    Handles:
      - Headings: 480p⚡[510MB], 720p x264 [1.3GB], 1080p BluRay [28.46GB]
      - Episode links: [EPiSODE 1], [EPiSODE 2], ...
    """
    releases = []
    seen_urls = set()

    # 1. Heading + Button pattern (standard movie and pack downloads)
    # e.g. <h4 ...>480p⚡[510MB]</h4> ... <a href="https://greenmotors.../?id=...">Download Links</a>
    section_matches = re.finditer(
        r"<h[3-6][^>]*>(.*?)</h[3-6]>(.*?)(?=<h[3-6]|<footer|$)",
        page_html,
        re.DOTALL | re.IGNORECASE,
    )

    for sm in section_matches:
        heading_text = re.sub(r"<[^>]+>", "", sm.group(1)).strip()
        body_html = sm.group(2)

        gm_links = re.findall(
            r'href=["\'](https?://[^\s"\'<>]*greenmotors[^\s"\'<>]*)["\']',
            body_html,
            re.IGNORECASE,
        )
        if not gm_links:
            continue

        # Extract quality
        q_m = re.search(r"\b(2160p|4k|1080p|720p|480p)\b", heading_text, re.IGNORECASE)
        quality = q_m.group(1).lower() if q_m else "720p"
        if quality == "4k":
            quality = "2160p"

        # Extract size
        size_m = re.search(r"(\d+(?:\.\d+)?\s*(?:GB|MB))", heading_text, re.IGNORECASE)
        size_str = size_m.group(1).upper() if size_m else None
        size_bytes = parse_size_to_bytes(size_str)

        # Extract codec
        codec = "x264"
        if re.search(r"\b(hevc|x265|10bit)\b", heading_text, re.IGNORECASE):
            codec = "HEVC"

        # Check if this section has individual episode buttons
        ep_buttons = re.findall(
            r'<a[^>]+href=["\'](https?://[^\s"\'<>]*greenmotors[^\s"\'<>]*)["\'][^>]*>(.*?)</a>',
            body_html,
            re.DOTALL | re.IGNORECASE,
        )

        has_episodes = False
        for gm_url, btn_text in ep_buttons:
            clean_btn = re.sub(r"<[^>]+>", "", btn_text).strip()
            ep_m = re.search(r"EP(?:iSODE)?\s*(\d+)", clean_btn, re.IGNORECASE)
            if ep_m:
                has_episodes = True
                ep_num = int(ep_m.group(1))
                if gm_url not in seen_urls:
                    seen_urls.add(gm_url)
                    releases.append({
                        "label": f"Episode {ep_num} - {quality.upper()}",
                        "quality": quality,
                        "resolution": quality,
                        "size": size_str,
                        "size_bytes": size_bytes,
                        "codec": codec,
                        "season_number": 1,
                        "episode_number": ep_num,
                        "bridge_url": gm_url,
                    })

        if not has_episodes:
            for gm_url in gm_links:
                if gm_url not in seen_urls:
                    seen_urls.add(gm_url)
                    label = heading_text if heading_text else f"{quality.upper()} Release"
                    releases.append({
                        "label": label,
                        "quality": quality,
                        "resolution": quality,
                        "size": size_str,
                        "size_bytes": size_bytes,
                        "codec": codec,
                        "season_number": None,
                        "episode_number": None,
                        "bridge_url": gm_url,
                    })

    # 2. Direct button scan fallback (if no headings matched)
    if not releases:
        all_gm_buttons = re.findall(
            r'<a[^>]+href=["\'](https?://[^\s"\'<>]*greenmotors[^\s"\'<>]*)["\'][^>]*>(.*?)</a>',
            page_html,
            re.DOTALL | re.IGNORECASE,
        )
        for gm_url, btn_text in all_gm_buttons:
            if gm_url in seen_urls:
                continue
            seen_urls.add(gm_url)
            clean_btn = re.sub(r"<[^>]+>", "", btn_text).strip()

            q_m = re.search(r"\b(2160p|4k|1080p|720p|480p)\b", clean_btn, re.IGNORECASE)
            quality = q_m.group(1).lower() if q_m else "720p"
            if quality == "4k":
                quality = "2160p"

            ep_m = re.search(r"EP(?:iSODE)?\s*(\d+)", clean_btn, re.IGNORECASE)
            ep_num = int(ep_m.group(1)) if ep_m else None

            releases.append({
                "label": clean_btn if clean_btn else f"{quality.upper()} Release",
                "quality": quality,
                "resolution": quality,
                "size": None,
                "size_bytes": None,
                "codec": "x264",
                "season_number": 1 if ep_num else None,
                "episode_number": ep_num,
                "bridge_url": gm_url,
            })

    return releases


def extract_post_data_hdhub4u(
    post_url: str,
    page_html: str,
    api_doc: dict | None = None,
    resolve_direct: bool = True,
    timeout: int = 12,
) -> dict | None:
    """
    Extracts full metadata, releases, and unwrapped sources from an HDHub4u post page,
    combining page HTML with pre-cached API document metadata.
    """
    # 1. Title & Heading
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.DOTALL | re.IGNORECASE)
    raw_title = h1_m.group(1) if h1_m else ""
    if not raw_title:
        title_tag_m = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE)
        raw_title = title_tag_m.group(1) if title_tag_m else ""

    clean_title, year, canonical_key = clean_hdhub4u_title(raw_title)

    # Cross-reference with API doc if available
    imdb_id = None
    poster_url = None
    categories = []
    stars = []
    director = None

    if api_doc:
        if not clean_title or len(clean_title) < 2:
            clean_title, year, canonical_key = clean_hdhub4u_title(api_doc.get("post_title", ""))
        imdb_id = api_doc.get("imdb_id")
        poster_url = api_doc.get("post_thumbnail")
        categories = api_doc.get("category", [])
        stars = api_doc.get("stars", [])
        dir_list = api_doc.get("director", [])
        director = dir_list[0] if dir_list else None

    # Fallback to HTML for IMDB ID
    if not imdb_id:
        imdb_m = re.search(r"imdb\.com/title/(tt\d+)", page_html, re.IGNORECASE)
        if imdb_m:
            imdb_id = imdb_m.group(1)

    # Fallback to HTML for poster
    if not poster_url:
        img_m = re.search(r'<img[^>]+class=["\'][^"\']*movie-cover[^"\']*["\'][^>]*src=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
        if not img_m:
            img_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
        if img_m:
            poster_url = img_m.group(1)

    # Media Type Detection
    is_series = bool(
        re.search(r"\b(season\s*\d+|series|episodes|s\d+)\b", raw_title, re.IGNORECASE)
        or any("series" in c.lower() for c in categories)
    )
    media_type = "series" if is_series else "movie"

    # 2. Extract Releases
    parsed_releases = parse_hdhub4u_release_links(page_html)
    if not parsed_releases:
        return None

    # 3. Stream Resolution
    releases_data = []
    for r in parsed_releases:
        sources = []
        bridge_url = r.get("bridge_url", "")
        if resolve_direct and bridge_url:
            unwrapped = fast_fetch.unwrap_greenmotors(bridge_url, timeout=timeout)
            for u in unwrapped:
                sources.append({
                    "source_name": u.get("source_name", "⚡ HDHub4u Stream"),
                    "service": u.get("service", "greenmotors"),
                    "resource_id": u.get("resource_id", ""),
                    "source_url": u.get("source_url", bridge_url),
                    "final_url": u.get("final_url", bridge_url),
                    "is_temporary": u.get("is_temporary", 0),
                    "quality": r.get("quality", "720p"),
                })
        else:
            sources.append({
                "source_name": "⚡ HDHub4u Bridge",
                "service": "greenmotors",
                "resource_id": bridge_url.split("?id=")[-1][:24] if "?id=" in bridge_url else "",
                "source_url": bridge_url,
                "final_url": bridge_url,
                "is_temporary": 0,
                "quality": r.get("quality", "720p"),
            })

        releases_data.append({
            "label": r.get("label"),
            "quality": r.get("quality"),
            "resolution": r.get("resolution"),
            "size_bytes": r.get("size_bytes"),
            "season_number": r.get("season_number"),
            "episode_number": r.get("episode_number"),
            "codec": r.get("codec"),
            "bridge_url": bridge_url,
            "sources": sources,
        })

    return {
        "canonical_key": canonical_key,
        "title": clean_title,
        "original_title": html.unescape(raw_title).strip(),
        "year": year,
        "media_type": media_type,
        "imdb_id": imdb_id,
        "poster_url": poster_url,
        "genres": json.dumps(categories) if categories else None,
        "director": director,
        "stars": json.dumps(stars) if stars else None,
        "site": "hdhub4u",
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
                imdb_id, poster_url, genres, site, post_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                original_title = excluded.original_title,
                year = excluded.year,
                media_type = excluded.media_type,
                imdb_id = COALESCE(excluded.imdb_id, posts.imdb_id),
                poster_url = COALESCE(excluded.poster_url, posts.poster_url),
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

        # 2. Insert Releases and Sources
        for r in post_data["releases"]:
            cur.execute(
                """
                INSERT INTO releases (
                    post_id, label, quality, resolution, size_bytes,
                    season_number, episode_number, codec, bridge_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id;
                """,
                (
                    post_id,
                    r["label"],
                    r["quality"],
                    r["resolution"],
                    r["size_bytes"],
                    r["season_number"],
                    r["episode_number"],
                    r["codec"],
                    r["bridge_url"],
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


def sync_fast_api_to_db(db_path: Path, per_page: int = 250) -> int:
    """
    Syncs the complete HDHub4u catalog from the Typesense JSON search API into sitemap_cache.
    Fetches 250 documents per page in ~0.6s.
    """
    init_staging_db(db_path)
    client = HDHub4uClient()

    print(f"[*] Starting ultra-fast catalog sync from {TYPESENSE_SEARCH_URL}...", flush=True)
    page = 1
    total_synced = 0
    total_found = None

    while not STOP_REQUESTED:
        query_url = (
            f"{TYPESENSE_SEARCH_URL}?"
            f"q=*&query_by=post_title,category,stars,director,imdb_id&"
            f"sort_by=sort_by_date:desc&limit={per_page}&page={page}"
        )
        t0 = time.time()
        code, data = client.get_json(
            query_url,
            referer=client.base_url + "/",
            origin=client.base_url,
            timeout=12,
        )
        dt = time.time() - t0

        if code != 200 or not data or not isinstance(data, dict):
            print(f"[!] API page {page} returned status {code}. Stopping sync.", flush=True)
            break

        if total_found is None:
            total_found = data.get("found", 0)
            print(f"[*] Total catalog size indexed by API: {total_found:,} titles.", flush=True)

        hits = data.get("hits", [])
        if not hits:
            break

        records = []
        for hit in hits:
            doc = hit.get("document", {})
            permalink = doc.get("permalink")
            if not permalink:
                continue
            slug = permalink.rstrip("/").split("/")[-1]
            lastmod = doc.get("post_date")
            raw_json_str = json.dumps(doc)
            records.append((permalink, lastmod, slug, 0, "hdhub4u", raw_json_str))

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
                f"  [Page {page:3d}] Synced {len(records)} titles in {dt:.2f}s "
                f"({total_synced:,} / {total_found:,} total)",
                flush=True,
            )

        if len(hits) < per_page or total_synced >= (total_found or 0):
            break

        page += 1

    print(f"\n[✓] Fast API sync finished: {total_synced:,} titles stored in {db_path.name}\n", flush=True)
    return total_synced


def sync_sitemaps_to_db(db_path: Path) -> int:
    """Fallback XML sitemap synchronizer for all post-sitemap*.xml files."""
    init_staging_db(db_path)
    client = HDHub4uClient()
    base_url = client.resolve_live_host()

    index_url = f"{base_url}/sitemap.xml"
    print(f"[*] Fetching sitemap index: {index_url}...", flush=True)
    code, _, xml_text = client.get_text(index_url)
    if code != 200 or not xml_text:
        print(f"[!] Failed to fetch sitemap index: HTTP {code}", flush=True)
        return 0

    sub_sitemaps = re.findall(r"<loc>(https?://[^<]*post-sitemap\d*\.xml)</loc>", xml_text)
    if not sub_sitemaps:
        # direct post links in sitemap.xml
        sub_sitemaps = [index_url]

    print(f"[*] Discovered {len(sub_sitemaps)} sub-sitemaps.", flush=True)
    total_added = 0

    for sub_url in sub_sitemaps:
        if STOP_REQUESTED:
            break
        c, _, sub_xml = client.get_text(sub_url)
        if c != 200 or not sub_xml:
            continue
        locs = re.findall(r"<loc>(https?://[^<]+)</loc>", sub_xml)
        records = [
            (loc, None, loc.rstrip("/").split("/")[-1], 0, "hdhub4u", None)
            for loc in locs
            if not loc.endswith(".xml")
        ]
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
            total_added += len(records)
            print(f"  [Sitemap] {sub_url.split('/')[-1]}: {len(records)} titles", flush=True)

    print(f"[✓] XML sitemap sync finished: {total_added:,} titles added.\n", flush=True)
    return total_added


def run_crawler(
    db_path: Path,
    workers: int = 5,
    delay: float = 0.3,
    limit: int | None = None,
    resolve_direct: bool = True,
):
    """Multi-threaded background crawler for HDHub4u with rate limiting and progress updates."""
    init_staging_db(db_path)
    client = HDHub4uClient(request_interval=delay)
    client.resolve_live_host()

    # Query pending rows
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
    print(f"[*] Starting HDHub4u crawler: {total_pending:,} titles queued | {workers} workers | delay {delay}s\n", flush=True)

    completed = 0
    failed = 0
    total_releases = 0
    total_sources = 0
    start_time = time.time()

    def process_item(item):
        loc, raw_json_str = item
        api_doc = json.loads(raw_json_str) if raw_json_str else None

        code, _, page_html = client.get_text(loc, timeout=12)
        if code != 200 or not page_html:
            return loc, False, 0, 0

        post_data = extract_post_data_hdhub4u(
            post_url=loc,
            page_html=page_html,
            api_doc=api_doc,
            resolve_direct=resolve_direct,
        )
        if not post_data or not post_data.get("releases"):
            return loc, False, 0, 0

        ok = save_post_to_staging_db(db_path, post_data)
        num_rels = len(post_data["releases"])
        num_srcs = sum(len(r.get("sources", [])) for r in post_data["releases"])
        return loc, ok, num_rels, num_srcs

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, MAX_SAFE_WORKERS)) as executor:
        futures = {executor.submit(process_item, row): row for row in pending_rows}

        for future in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED:
                break
            loc, ok, rel_cnt, src_cnt = future.result()

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

                # Update status file
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
    """Prints current metrics and counts for HDHub4u staging database."""
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
        pixeldrain_sources = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'pixeldrain'").fetchone()[0]

    pct = (scraped_cache / total_cache * 100) if total_cache > 0 else 0.0
    print(f"\n=======================================================")
    print(f" 📦 HDHub4u Staging Database Status ({db_path.name})")
    print(f"=======================================================")
    print(f" Sitemap Cache Total : {total_cache:,}")
    print(f" Scraped (Done)      : {scraped_cache:,} ({pct:.1f}%)")
    print(f" Pending             : {pending_cache:,}")
    print(f" Failed/Review       : {failed_cache:,}")
    print(f"-------------------------------------------------------")
    print(f" Catalog Posts       : {total_posts:,}")
    print(f" Releases Found      : {total_releases:,}")
    print(f" Direct Sources      : {total_sources:,}")
    print(f"   ⚡ Cloudflare R2   : {r2_sources:,} (10Gbps direct)")
    print(f"   ⚡ PixelDrain CDN  : {pixeldrain_sources:,}")
    print(f"=======================================================\n")


def main():
    parser = argparse.ArgumentParser(description="HDHub4u Dedicated Staging Importer & Crawler")
    parser.add_argument("--sync-api", action="store_true", help="Sync all titles via Typesense search API")
    parser.add_argument("--sync-sitemap", action="store_true", help="Sync all XML sitemaps")
    parser.add_argument("--limit", type=int, help="Limit number of titles to scrape")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers (default 5)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests in seconds (default 0.3)")
    parser.add_argument("--no-resolve", action="store_true", help="Skip unwrapping greenmotors to direct links")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH), help="Path to staging SQLite database")
    parser.add_argument("--status", action="store_true", help="Show staging database status")

    args = parser.parse_args()
    db_path = Path(args.db_path)

    if args.status:
        print_status(db_path)
        return

    if args.sync_api:
        sync_fast_api_to_db(db_path)
        return

    if args.sync_sitemap:
        sync_sitemaps_to_db(db_path)
        return

    # If neither sync requested, run crawler
    run_crawler(
        db_path=db_path,
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        resolve_direct=not args.no_resolve,
    )


if __name__ == "__main__":
    main()
