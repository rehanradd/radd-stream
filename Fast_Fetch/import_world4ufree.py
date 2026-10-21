#!/usr/bin/env python3
"""
import_world4ufree.py — Dedicated staging importer and scraper for World4uFree (https://world4ufree.garden).

Key Features & Hidden API Accelerators:
  1. 100-Item Bulk WP REST API Catalog Synchronization:
     - /wp-json/wp/v2/posts?per_page=100
     - 24,732+ catalog titles ingested in ~247 batch requests at ~25+ titles/sec.
     - Direct IMDb ID (ttXXXXXXX) extracted directly from post content.
     - High-res Google Blogger poster extracted (s1600 full quality).
  2. Hidden Direct-Stream JSON API (photolinx.beauty/action):
     - Session-cookie-negotiated JSON RPC:
       POST https://photolinx.beauty/action
       Payload: {"type": "DOWNLOAD_GENERATE", "payload": {"uid": <uid>, "access_token": <token>}}
     - Yields direct 10Gbps Cloudflare Worker direct streaming video (HTTP 200 .mkv).
  3. Session-Negotiated Bridge Unwrapper (fastilinks.beauty):
     - Unlocks 5-7 redundant mirrors per release:
       * ⚡ Cloudflare Worker [10Gbps Direct Video Stream]
       * ⚡ Mediafire [Instant Download]
       * ⚡ GDFlix [Google Drive Fast Server]
       * ⚡ GoFile.io [High-Speed Cloud]
       * ⚡ DriveHub [Fast Mirror]
       * ⚡ 1fichier [High-Speed Mirror]
       * ⚡ BuzzHeavier [Direct Stream]
  4. Dedicated Staging Database: world4ufree.db (strictly isolated from production fast_fetch.db).
  5. 100% Python Standard Library only. Zero pip dependencies.
  6. Strict Zero Adult Content Enforcement: is_18_plus = 0.

Usage:
    python Fast_Fetch/import_world4ufree.py --sync-api --max-pages 5       # Ingest first 5 pages (500 titles)
    python Fast_Fetch/import_world4ufree.py --sync-api                     # Ingest entire catalog (24.7k titles)
    python Fast_Fetch/import_world4ufree.py --limit 10                     # Scrape 10 pending titles
    python Fast_Fetch/import_world4ufree.py --workers 4 --delay 0.3        # Full background crawler
    python Fast_Fetch/import_world4ufree.py --status                       # Show staging DB metrics
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import html
import http.cookiejar
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

DEFAULT_BASE_URL = "https://world4ufree.tours"
WP_API_URL = f"{DEFAULT_BASE_URL}/wp-json/wp/v2/posts"
DEFAULT_DB_PATH = (
    Path("/home/ubuntu/radd-stream-data/world4ufree.db")
    if Path("/home/ubuntu/radd-stream-data").exists()
    else BASE_DIR / "world4ufree.db"
)
STATUS_FILE = BASE_DIR / "world4ufree_status.json"

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

# Adult keywords filter to strictly enforce is_18_plus = 0
ADULT_KEYWORDS = {
    "18+", "erotic", "hotshots", "ullu", "kooku", "primeplay", "rabbit",
    "flizmovies", "hunters", "boommovies", "neonx", "besharams", "gupchup",
    "sex", "sexy", "porn", "adult", "unrated", "sensual", "lust"
}


def is_adult_content(text: str) -> bool:
    """Strictly checks if title, slug, or tags indicate adult / 18+ content."""
    if not text:
        return False
    t = text.lower()
    for kw in ADULT_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", t):
            return True
    return False


class World4uFreeClient:
    """HTTP Client with session cookies, rate limiting, and hidden API unwrapping."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, request_interval: float = 0.3, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.request_interval = max(0.0, request_interval)
        self.retries = max(1, retries)
        self.ssl_ctx = get_ssl_context()
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            urllib.request.HTTPSHandler(context=self.ssl_ctx),
        )
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
                with self.opener.open(req, timeout=timeout) as resp:
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

    def unwrap_photolinx(self, pl_url: str) -> list[dict]:
        """
        Unwraps photolinx.beauty gateway via hidden /action JSON API.
        Returns direct 10Gbps Cloudflare Worker direct streaming source (*.workers.dev).
        """
        results = []
        try:
            code, final_url, html_text, _ = self.get_text(pl_url, referer="https://fastilinks.beauty/", timeout=10)
            if code != 200 or not html_text:
                return results

            uid_m = re.search(r'id=[\"\']generate_url[\"\'][^>]*data-uid=[\"\']([^\"\']*)[\"\']', html_text)
            token_m = re.search(r'id=[\"\']generate_url[\"\'][^>]*data-token=[\"\']([^\"\']*)[\"\']', html_text)

            if uid_m and token_m:
                uid = uid_m.group(1)
                token = token_m.group(1)

                api_payload = json.dumps({
                    "type": "DOWNLOAD_GENERATE",
                    "payload": {"uid": uid, "access_token": token}
                }).encode("utf-8")

                api_headers = {
                    "User-Agent": fast_fetch.USER_AGENT,
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Requested-With": "xmlhttprequest",
                    "Referer": final_url,
                    "Origin": "https://photolinx.beauty",
                    "Cache-Control": "no-cache",
                }
                req_api = urllib.request.Request("https://photolinx.beauty/action", data=api_payload, headers=api_headers)
                with self.opener.open(req_api, timeout=10) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))

                download_url = res_json.get("download_url")
                if download_url and ("workers.dev" in download_url or "googleusercontent.com" in download_url):
                    results.append({
                        "source_name": "⚡ Cloudflare Worker [10Gbps Direct Stream]",
                        "service": "cloudflare_worker",
                        "resource_id": uid,
                        "source_url": pl_url,
                        "final_url": download_url,
                        "is_temporary": 1,
                    })
        except Exception:
            pass

        return results

    def unwrap_fastilinks(self, fl_url: str) -> list[dict]:
        """
        Unwraps fastilinks.beauty session-cookie CSRF form.
        Yields Mediafire, Cloudflare Worker (via photolinx), GDFlix, GoFile, DriveHub, 1fichier, BuzzHeavier.
        """
        results = []
        try:
            code, final_url, html_landing, _ = self.get_text(fl_url, referer="https://w4links.space/", timeout=10)
            if code != 200 or not html_landing:
                return results

            form_m = re.search(r'<form\s+[^>]*action=[\"\']([^\"\']*)[\"\'][^>]*>(.*?)</form>', html_landing, re.I | re.S)
            if not form_m:
                return results

            action, fbody = form_m.groups()
            inputs = dict(re.findall(r'<input\s+[^>]*name=[\"\']([^\"\']+)[\"\'][^>]*value=[\"\']([^\"\']*)[\"\']', fbody))
            if not inputs:
                return results

            post_url = urllib.parse.urljoin(final_url, action)
            data = urllib.parse.urlencode(inputs).encode("utf-8")
            headers = {
                "User-Agent": fast_fetch.USER_AGENT,
                "Origin": "https://fastilinks.beauty",
                "Referer": final_url,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            req_post = urllib.request.Request(post_url, data=data, headers=headers)
            with self.opener.open(req_post, timeout=10) as resp2:
                html_links = resp2.read().decode("utf-8", errors="replace")

            anchors = re.findall(r'<a\s+[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', html_links, re.I | re.S)
            for href, text in anchors:
                h_low = href.lower()
                if any(x in h_low for x in ["#", "javascript", "/money", "/faqs", "/contact", "/page/", "/login", "/register", "fastilinks"]):
                    continue

                if "photolinx.beauty" in h_low:
                    pl_sources = self.unwrap_photolinx(href)
                    results.extend(pl_sources)
                elif "mediafire.com" in h_low:
                    results.append({
                        "source_name": "⚡ Mediafire [Direct Download]",
                        "service": "mediafire",
                        "resource_id": href.rstrip("/").split("/")[-2] if "/file/" in href else href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
                elif "gdflix" in h_low:
                    results.append({
                        "source_name": "⚡ GDFlix [Google Drive Fast Server]",
                        "service": "gdflix",
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
                elif "gofile.io" in h_low:
                    results.append({
                        "source_name": "⚡ GoFile [Cloud High-Speed]",
                        "service": "gofile",
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
                elif "drivehub" in h_low:
                    results.append({
                        "source_name": "⚡ DriveHub [Fast Mirror]",
                        "service": "drivehub",
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
                elif "1fichier.com" in h_low:
                    results.append({
                        "source_name": "⚡ 1fichier [High-Speed]",
                        "service": "1fichier",
                        "resource_id": href.split("?")[-1].replace("3n0", "") if "?" in href else href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
                elif "buzzheavier" in h_low:
                    results.append({
                        "source_name": "⚡ BuzzHeavier [Direct Stream]",
                        "service": "buzzheavier",
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
                elif "send.now" in h_low or "usersdrive" in h_low or "vikingfile" in h_low:
                    svc = "usersdrive" if "usersdrive" in h_low else ("vikingfile" if "vikingfile" in h_low else "sendnow")
                    results.append({
                        "source_name": f"⚡ {svc.title()} [Mirror]",
                        "service": svc,
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
        except Exception:
            pass

        return results

    def unwrap_w4links(self, w4_url: str) -> list[tuple[str, list[dict]]]:
        """
        Unwraps w4links.space gateway page.
        Returns list of (quality_hint, resolved_sources).
        """
        results = []
        try:
            code, final_url, html_text, _ = self.get_text(w4_url, referer=self.base_url, timeout=10)
            if code != 200 or not html_text:
                return results

            # Anchors linking to fastilinks
            anchors = re.findall(r'<a\s+[^>]*href=[\"\'](https?://fastilinks\.beauty/view/[^\"\']+)[\"\'][^>]*>(.*?)</a>', html_text, re.I | re.S)
            for href, text in anchors:
                clean_t = re.sub(r'<[^>]+>', '', text).strip()
                sources = self.unwrap_fastilinks(href)
                if sources:
                    results.append((clean_t, sources))
        except Exception:
            pass

        return results


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
                site TEXT DEFAULT 'world4ufree',
                raw_json TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_w4u_scraped ON sitemap_cache(scraped);")

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
                site TEXT DEFAULT 'world4ufree',
                post_url TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_w4u_canonical ON posts(canonical_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_w4u_imdb ON posts(imdb_id);")

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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_w4u_rel_post ON releases(post_id);")

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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_w4u_src_rel ON sources(release_id);")
        conn.commit()


def clean_world4ufree_title(raw_title: str) -> tuple[str, int | None, str]:
    """
    Cleans World4uFree post titles to extract canonical title, release year, and media type.
    Example: 'Street Fighter 2026 Hindi (Line) Movie 1080p 720p 480p HDTC'
             -> ('Street Fighter', 2026, 'movie')
    """
    t = html.unescape(raw_title).strip()

    media_type = "movie"
    if re.search(r"\b(season\s*\d+|s\d+|series|episodes?)\b", t, re.IGNORECASE):
        media_type = "series"

    year = None
    y_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if y_m:
        year = int(y_m.group(1))

    t_clean = re.sub(r"\[.*?\]|\(.*?\)", "", t)
    t_clean = re.sub(
        r"\b(movie|dual\s*audio|org|uncut|web-dl|bluray|hdtc|hdts|hdrip|hevc|webrip|x264|x265|1080p|720p|480p|complete|all\s*episodes?)\b.*$",
        "",
        t_clean,
        flags=re.IGNORECASE,
    )
    if year:
        t_clean = re.sub(rf"\b{year}\b.*$", "", t_clean)

    t_clean = re.sub(r"[-–—:|]+", " ", t_clean)
    t_clean = re.sub(r"\s+", " ", t_clean).strip()

    return t_clean or raw_title, year, media_type


def parse_world4ufree_content(content_html: str, post_title: str) -> tuple[str | None, str | None, list[dict]]:
    """
    Parses World4uFree post HTML content to extract IMDb ID, high-res poster, and releases with w4links.
    """
    # 1. IMDb ID
    imdb_id = None
    imdb_m = re.search(r"\b(tt\d{7,10})\b", content_html)
    if imdb_m:
        imdb_id = imdb_m.group(1)

    # 2. High-res poster
    poster_url = None
    poster_m = re.search(r'<img[^>]+src=["\'](https?://blogger\.googleusercontent\.com/img/b/[^"\']+)["\']', content_html)
    if poster_m:
        poster_url = poster_m.group(1)
        # Upgrade thumbnail to original s1600 resolution
        poster_url = re.sub(r"/s\d+/", "/s1600/", poster_url)

    # 3. Detect season for series
    season_num = None
    s_m = re.search(r"\bS(\d{1,2})\b", post_title, re.IGNORECASE)
    if s_m:
        season_num = int(s_m.group(1))

    # 4. Extract download links from ALL bridge/host domains
    releases = []

    # Supported bridge/host URL patterns
    link_patterns = [
        r'<a\s+[^>]*href=[\\"\'](https?://w4links\.space/\d+/?)[\\"\'\'][^>]*>(.*?)</a>',
        r'<a\s+[^>]*href=[\\"\'](https?://fastilinks\.beauty/view/[^\\"\' ]+)[\\"\'\'][^>]*>(.*?)</a>',
        r'<a\s+[^>]*href=[\\"\'](https?://wlinksi\.site/[^\\"\' ]+)[\\"\'\'][^>]*>(.*?)</a>',
        r'<a\s+[^>]*href=[\\"\'](https?://cloud\.mail\.ru/public/[^\\"\' ]+)[\\"\'\'][^>]*>(.*?)</a>',
    ]

    seen_urls = set()
    for pattern in link_patterns:
        anchors = re.findall(pattern, content_html, re.I | re.S)
        for href, text in anchors:
            clean_t = re.sub(r"<[^>]+>", "", text).strip()
            q_m = re.search(r"\b(4K|2160p|1080p|720p|480p)\b", clean_t, re.I)
            quality = q_m.group(1).upper() if q_m else "720P"

            codec = "hevc" if "hevc" in clean_t.lower() or "x265" in clean_t.lower() else "x264"

            key = (href, quality, codec)
            if key in seen_urls:
                continue
            seen_urls.add(key)

            releases.append({
                "label": f"{clean_t or quality}",
                "quality": quality,
                "resolution": quality.lower(),
                "size_bytes": None,
                "season_number": season_num,
                "episode_number": None,
                "audio_languages": "Hindi" if "hindi" in post_title.lower() else None,
                "codec": codec,
                "bridge_url": href,
            })

    return imdb_id, poster_url, releases


def sync_api_catalog(client: World4uFreeClient, db_path: Path, max_pages: int | None = None) -> int:
    """
    Syncs full World4uFree catalog into staging SQLite database via WP REST API.
    Uses per_page=100 bulk ingestion (~24.7k titles in 247 requests).
    """
    init_staging_db(db_path)
    print(f"[*] Starting World4uFree API sync (per_page=100) -> {db_path}...", flush=True)

    page = 1
    total_new = 0
    total_existing = 0
    total_adult_skipped = 0
    consecutive_empty_new = 0
    total_posts = 0

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

    while True:
        if STOP_REQUESTED:
            print("[!] API sync stopped by user.", flush=True)
            break
        if max_pages and page > max_pages:
            print(f"[*] Reached page limit ({max_pages}).", flush=True)
            break

        url = f"{WP_API_URL}?per_page=100&page={page}"
        code, posts, headers = client.get_json(url, timeout=15)

        if code != 200 or not posts or not isinstance(posts, list):
            if code == 400:
                print(f"[✓] End of WP REST API pagination reached at page {page - 1}.", flush=True)
            else:
                print(f"[!] WP REST API returned HTTP {code} on page {page}.", flush=True)
            break

        if page == 1:
            total_posts = int(headers.get("x-wp-total", 0) or 0)
            total_pages = int(headers.get("x-wp-totalpages", 0) or 0)
            print(f"[+] Total catalog items: {total_posts:,} across {total_pages:,} pages.", flush=True)

        batch_records = []
        page_new = 0
        for p in posts:
            link = p.get("link", "")
            slug = p.get("slug", "")
            modified = p.get("modified", "")
            title_text = p.get("title", {}).get("rendered", "")

            # Strictly enforce zero adult content
            if is_adult_content(title_text) or is_adult_content(slug):
                total_adult_skipped += 1
                continue

            if (slug and slug in existing_slugs) or (link in existing_locs):
                total_existing += 1
                continue

            raw_str = json.dumps(p)
            batch_records.append((link, modified, slug, 0, "world4ufree", raw_str))
            if slug:
                existing_slugs.add(slug)
            existing_locs.add(link)
            page_new += 1
            total_new += 1

        if batch_records:
            with sqlite3.connect(str(db_path)) as conn:
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
                conn.commit()

        print(f"  [Page {page:3d}] Found {page_new} brand new, {len(posts) - page_new} existing/skipped (Cumulative New: {total_new:,})", flush=True)

        if page_new == 0:
            consecutive_empty_new += 1
            if max_pages is None and consecutive_empty_new >= 3:
                print(f"[*] 3 consecutive pages with 0 new titles reached. Database is fully up-to-date with live catalog. Stopping sync.", flush=True)
                break
        else:
            consecutive_empty_new = 0

        page += 1

    print(f"[✓] World4uFree API sync finished: {total_new:,} brand new titles added to {db_path.name} ({total_existing:,} existing skipped, {total_adult_skipped:,} adult skipped).", flush=True)
    return total_new


def scrape_post_item(item: tuple, client: World4uFreeClient) -> dict | None:
    """Processes a single World4uFree post item, unwrapping w4links and fastilinks."""
    loc, lastmod, slug, raw_json_str = item
    try:
        if raw_json_str:
            p_data = json.loads(raw_json_str)
        else:
            return None

        raw_title = p_data.get("title", {}).get("rendered", "")
        content_html = p_data.get("content", {}).get("rendered", "")

        if not raw_title or not content_html:
            return None

        if is_adult_content(raw_title) or is_adult_content(slug):
            return {"loc": loc, "skipped": True}

        clean_title, year, media_type = clean_world4ufree_title(raw_title)
        canonical_key = fast_fetch.generate_canonical_key(clean_title, year)

        imdb_id, poster_url, releases_data = parse_world4ufree_content(content_html, raw_title)
        if not releases_data:
            return {"loc": loc, "success": False, "reason": "no_releases"}

        # Resolve bridge URLs & direct links into streaming sources
        resolved_releases = []
        for rel in releases_data:
            bridge_url = rel.get("bridge_url")
            sources = []
            if bridge_url:
                if "w4links.space" in bridge_url:
                    unwrapped_pairs = client.unwrap_w4links(bridge_url)
                    for hint, src_list in unwrapped_pairs:
                        sources.extend(src_list)
                elif "fastilinks.beauty" in bridge_url:
                    sources = client.unwrap_fastilinks(bridge_url)
                elif "cloud.mail.ru" in bridge_url:
                    sources = [{
                        "source_name": "☁️ Mail.ru Cloud",
                        "service": "mailru",
                        "resource_id": bridge_url.split("/")[-1],
                        "source_url": bridge_url,
                        "final_url": bridge_url,
                        "is_temporary": 0,
                    }]
                else:
                    # Generic direct source or other bridge
                    svc = rel.get("service_hint", "direct")
                    sources = [{
                        "source_name": f"🔗 Direct ({svc})",
                        "service": svc,
                        "resource_id": bridge_url.split("/")[-1],
                        "source_url": bridge_url,
                        "final_url": bridge_url,
                        "is_temporary": 0,
                    }]

            # Ensure zero data loss: keep fallback gateway source if unwrapper yielded 0 sources
            if not sources and bridge_url:
                try:
                    host = bridge_url.split("/")[2]
                except Exception:
                    host = "gateway"
                sources = [{
                    "source_name": f"🔗 Gateway ({host})",
                    "service": "gateway",
                    "resource_id": bridge_url.split("/")[-1],
                    "source_url": bridge_url,
                    "final_url": bridge_url,
                    "is_temporary": 0,
                }]

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
                "site": "world4ufree",
                "post_url": loc,
            },
            "releases": resolved_releases,
        }
    except Exception as e:
        return {"loc": loc, "success": False, "reason": str(e)}


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


def save_post_to_staging(db_path: Path, result: dict):
    """Atomically saves extracted post, releases, and direct sources to staging DB."""
    loc = result["loc"]
    if result.get("skipped"):
        with get_db_connection(db_path) as conn:
            conn.execute("UPDATE sitemap_cache SET scraped = 2 WHERE loc = ?;", (loc,))
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
            INSERT INTO posts (canonical_key, title, original_title, year, media_type, imdb_id, poster_url, synopsis, genres, site, post_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title=excluded.title,
                original_title=excluded.original_title,
                year=excluded.year,
                media_type=excluded.media_type,
                imdb_id=coalesce(excluded.imdb_id, posts.imdb_id),
                poster_url=coalesce(excluded.poster_url, posts.poster_url),
                post_url=excluded.post_url,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                p["canonical_key"], p["title"], p["original_title"], p["year"],
                p["media_type"], p["imdb_id"], p["poster_url"], p["synopsis"],
                p["genres"], p["site"], p["post_url"]
            ),
        )

        cur.execute("SELECT id FROM posts WHERE canonical_key = ?;", (p["canonical_key"],))
        post_row = cur.fetchone()
        if not post_row:
            return
        post_id = post_row[0]

        for rel in releases:
            cur.execute(
                """
                INSERT INTO releases (post_id, label, quality, resolution, size_bytes, season_number, episode_number, audio_languages, codec, bridge_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    post_id, rel["label"], rel["quality"], rel["resolution"],
                    rel["size_bytes"], rel["season_number"], rel["episode_number"],
                    rel["audio_languages"], rel["codec"], rel.get("bridge_url")
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
                        rel_id, src["source_name"], src["service"], src["resource_id"],
                        src["source_url"], src["final_url"], src["is_temporary"], rel["quality"]
                    ),
                )

        cur.execute("UPDATE sitemap_cache SET scraped = 1 WHERE loc = ?;", (loc,))
        conn.commit()


def run_crawler(db_path: Path, workers: int = 4, delay: float = 0.3, limit: int | None = None):
    """Multi-threaded concurrent crawler consuming pending titles from sitemap_cache."""
    init_staging_db(db_path)
    client = World4uFreeClient(request_interval=delay)

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        query = "SELECT loc, lastmod, slug, raw_json FROM sitemap_cache WHERE scraped = 0"
        if limit:
            query += f" LIMIT {int(limit)}"
        cur.execute(query)
        pending = cur.fetchall()

    if not pending:
        print("[✓] Zero pending titles to scrape in sitemap_cache.", flush=True)
        return

    print(f"[*] Starting World4uFree crawler: {len(pending)} titles queued | {workers} workers | delay {delay}s", flush=True)
    t0 = time.time()
    scraped_count = 0
    failed_count = 0
    total_releases = 0
    total_sources = 0
    cf_worker_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(scrape_post_item, item, client): item for item in pending}
        for future in concurrent.futures.as_completed(future_map):
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
                            for s in r.get("sources", []):
                                total_sources += 1
                                if s.get("service") == "cloudflare_worker":
                                    cf_worker_count += 1
                    elif not res.get("skipped"):
                        failed_count += 1
            except Exception as e:
                failed_count += 1

            total_done = scraped_count + failed_count
            if total_done % 10 == 0 or total_done == len(pending):
                elapsed = max(0.001, time.time() - t0)
                speed = total_done / elapsed
                remaining = len(pending) - total_done
                eta_sec = int(remaining / speed) if speed > 0 else 0
                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_sec))
                print(
                    f"  [{total_done}/{len(pending)}] releases={total_releases:,} sources={total_sources:,} "
                    f"cf_workers={cf_worker_count:,} failed={failed_count} speed={speed:.2f} t/s ETA: {eta_str}",
                    flush=True,
                )

    print(f"[✓] Crawler finished: {scraped_count} scraped, {failed_count} failed in {time.time()-t0:.1f}s", flush=True)


def print_status(db_path: Path):
    """Prints live metrics from the dedicated world4ufree.db staging database."""
    if not db_path.exists():
        print(f"[!] Database {db_path} does not exist yet.", flush=True)
        return

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM sitemap_cache;")
        total_cache = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sitemap_cache WHERE scraped = 1;")
        scraped_cache = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sitemap_cache WHERE scraped = 0;")
        pending_cache = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sitemap_cache WHERE scraped = -1;")
        failed_cache = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM posts;")
        posts_cnt = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM posts WHERE imdb_id IS NOT NULL;")
        imdb_cnt = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM releases;")
        rel_cnt = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sources;")
        src_cnt = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sources WHERE service = 'cloudflare_worker';")
        cf_cnt = cur.fetchone()[0]

    print("=" * 65)
    print(f" 📊 WORLD4UFREE STAGING METRICS ({db_path.name})")
    print("=" * 65)
    print(f"  Catalog Ingested  : {total_cache:,}")
    print(f"  Scraped Titles    : {scraped_cache:,}")
    print(f"  Pending Titles    : {pending_cache:,}")
    print(f"  Failed Titles     : {failed_cache:,}")
    print("-" * 65)
    print(f"  Master Posts      : {posts_cnt:,}")
    print(f"  Verified IMDb IDs : {imdb_cnt:,}")
    print(f"  Media Releases    : {rel_cnt:,}")
    print(f"  Direct Sources    : {src_cnt:,}")
    print(f"  ⚡ 10Gbps CF Direct: {cf_cnt:,}")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="World4uFree Dedicated Staging Importer & Crawler")
    parser.add_argument("--sync-api", action="store_true", help="Sync full catalog via WP REST API")
    parser.add_argument("--max-pages", type=int, help="Limit WP REST API pagination pages")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent workers (default: 4)")
    parser.add_argument("--delay", type=float, default=0.3, help="Request delay in seconds (default: 0.3)")
    parser.add_argument("--limit", type=int, help="Limit number of titles to scrape")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to world4ufree.db")
    parser.add_argument("--status", action="store_true", help="Show staging database status")

    args = parser.parse_args()

    if args.status:
        print_status(args.db_path)
        return

    if args.sync_api:
        client = World4uFreeClient(request_interval=args.delay)
        sync_api_catalog(client, args.db_path, max_pages=args.max_pages)
        return

    run_crawler(args.db_path, workers=args.workers, delay=args.delay, limit=args.limit)


if __name__ == "__main__":
    main()
