#!/usr/bin/env python3
"""
import_ssrmovies.py — Dedicated staging importer and scraper for SSRMovies (https://ssrmovies.surf).

Key Features:
  1. Dedicated staging SQLite database: ssrmovies.db (isolated from production fast_fetch.db).
  2. Full WP REST API sync: Paginates https://ssrmovies.surf/wp-json/wp/v2/posts?per_page=100
     across all ~274 pages (27,362+ catalog titles).
  3. Clean Metadata Extraction:
     - Clean Title, Year, Audio/Language (Dual Audio, Hindi, Punjabi, South Dubbed, English).
     - Poster Image extraction (embedded CDN, TMDB, or OpenGraph).
     - Synopsis / Storyline text extraction.
  4. Precise Quality & File Size Parsing:
     - Extracts per-release button text: "Watch & Download in 1080p - 2.8GB",
       extracting exact quality tier (1080p, 720p, 480p, 4K) and file size.
  5. Multi-Mirror LinksZilla Bridge Resolution:
     - Direct Google CDN stream (lh3.googleusercontent.com)
     - Direct Cloudflare R2 10Gbps stream (r2.cloudflarestorage.com)
     - Watch-Online instant web player (watch-online.mom)
     - HubCloud Fast Server (pixel.hubcloud.ist) & PixelDrain CDN
     - GDFlix, 1fichier, Gofile, MegaUp, ClicknUpload mirrors
  6. Resumable via sitemap_cache table in staging SQLite database.
  7. 100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_ssrmovies.py --sync-api                 # Ingest all WP REST API post URLs
    python Fast_Fetch/import_ssrmovies.py --limit 10                 # Scrape 10 pending titles
    python Fast_Fetch/import_ssrmovies.py --workers 5 --delay 0.3   # Full background run
    python Fast_Fetch/import_ssrmovies.py --status                   # Show current database counts
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

DEFAULT_BASE_URL = "https://ssrmovies.surf"
DEFAULT_DB_PATH = BASE_DIR / "ssrmovies.db"
STATUS_FILE = BASE_DIR / "ssrmovies_status.json"

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


class SSRMoviesClient:
    """HTTP Client with rate limiting and retry handling for SSRMovies & LinksZilla."""

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

        req = urllib.request.Request(url, headers=headers)
        for attempt in range(self.retries):
            self._wait()
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_ctx) as resp:
                    code = resp.status
                    final_url = resp.geturl()
                    text = resp.read().decode("utf-8", errors="replace")
                    return code, final_url, text
            except urllib.error.HTTPError as e:
                if attempt == self.retries - 1:
                    return e.code, url, ""
                time.sleep(1.0)
            except Exception:
                if attempt == self.retries - 1:
                    return 0, url, ""
                time.sleep(1.0)
        return 0, url, ""

    def get_json(self, url: str, timeout: int = 20) -> tuple[int, dict | list | None, dict]:
        """Fetches JSON and returns (status_code, json_data, headers_dict)."""
        headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(self.retries):
            self._wait()
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_ctx) as resp:
                    code = resp.status
                    raw_headers = {k.lower(): v for k, v in resp.headers.items()}
                    body = resp.read().decode("utf-8", errors="replace")
                    data = json.loads(body)
                    return code, data, raw_headers
            except urllib.error.HTTPError as e:
                if attempt == self.retries - 1:
                    return e.code, None, {}
                time.sleep(1.0)
            except Exception:
                if attempt == self.retries - 1:
                    return 0, None, {}
                time.sleep(1.0)
        return 0, None, {}


def sync_api_to_db(client: SSRMoviesClient, db_path: Path, max_pages: int | None = None) -> int:
    """Fetches post URLs from SSRMovies WP REST API and populates sitemap_cache."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    print(f"[*] Probing SSRMovies WP REST API at {client.base_url}/wp-json/wp/v2/posts...", flush=True)
    probe_url = f"{client.base_url}/wp-json/wp/v2/posts?per_page=1"
    code, _, headers = client.get_json(probe_url)
    if code != 200:
        print(f"[!] Failed to connect to SSRMovies WP API (HTTP {code})", flush=True)
        return 0

    total_posts_str = headers.get("x-wp-total", "0")
    total_pages_str = headers.get("x-wp-totalpages", "0")
    try:
        total_posts = int(total_posts_str)
        total_pages = int(total_pages_str)
    except ValueError:
        total_posts, total_pages = 0, 0

    print(f"[✓] SSRMovies API reports {total_posts:,} total posts across {total_pages:,} pages.", flush=True)

    pages_to_fetch = total_pages
    if max_pages and max_pages < pages_to_fetch:
        pages_to_fetch = max_pages

    total_synced = 0
    records = []

    for page in range(1, pages_to_fetch + 1):
        if STOP_REQUESTED:
            break
        page_url = f"{client.base_url}/wp-json/wp/v2/posts?per_page=100&page={page}"
        print(f"    [{page}/{pages_to_fetch}] Fetching page {page}...", flush=True)
        p_code, p_data, _ = client.get_json(page_url)
        if p_code != 200 or not isinstance(p_data, list):
            print(f"    [!] Error fetching page {page} (HTTP {p_code})", flush=True)
            continue

        for item in p_data:
            post_url = item.get("link")
            if not post_url:
                continue
            slug = item.get("slug") or post_url.rstrip("/").split("/")[-1]
            modified = item.get("modified")
            records.append((post_url, modified, slug, 0, "ssrmovies"))

        if len(records) >= 1000:
            with fast_fetch._DB_WRITE_LOCK:
                with fast_fetch.get_db() as conn:
                    conn.executemany(
                        """
                        INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(loc) DO UPDATE SET
                            lastmod = COALESCE(excluded.lastmod, sitemap_cache.lastmod),
                            slug = COALESCE(excluded.slug, sitemap_cache.slug)
                        """,
                        records,
                    )
                    conn.commit()
            total_synced += len(records)
            records.clear()

    if records:
        with fast_fetch._DB_WRITE_LOCK:
            with fast_fetch.get_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(loc) DO UPDATE SET
                        lastmod = COALESCE(excluded.lastmod, sitemap_cache.lastmod),
                        slug = COALESCE(excluded.slug, sitemap_cache.slug)
                    """,
                    records,
                )
                conn.commit()
        total_synced += len(records)

    print(f"[✓] Successfully ingested {total_synced:,} post URLs into sitemap_cache.", flush=True)
    return total_synced


def parse_ssrmovies_release_button(btn_html: str, full_html: str = "") -> dict | None:
    """
    Parses a single LinksZilla download/watch anchor from SSRMovies post body.
    Example button:
      <a href="https://secure.linkszilla.top/view/-Zw8TA6H1r" ...>Watch &amp; Download in 1080p - 2.8GB</a>
    """
    m = re.search(r'href=["\'](https?://secure\.linkszilla\.top/view/[^"\']+)["\'][^>]*>(.*?)</a>', btn_html, re.I | re.S)
    if not m:
        return None

    lz_url = m.group(1).strip()
    raw_text = html.unescape(re.sub(r'<[^>]+>', '', m.group(2)).strip())

    # Quality extraction
    qual = "720p"
    qual_m = re.search(r'\b(2160p|4k|1080p|720p|480p)\b', raw_text, re.I)
    if qual_m:
        qual = qual_m.group(1).lower()
        if qual == "4k":
            qual = "2160p"

    # Size extraction (e.g. "2.8GB", "434MB", "1.2 GB")
    size = ""
    size_m = re.search(r'(\d+(?:\.\d+)?\s*(?:GB|MB))', raw_text, re.I)
    if size_m:
        size = size_m.group(1).replace(" ", "")

    # Codec extraction
    codec = "x264"
    if "hevc" in raw_text.lower() or "10bit" in raw_text.lower() or "x265" in raw_text.lower():
        codec = "hevc"

    # Season / Episode extraction if present
    season = None
    episode = None
    ep_m = re.search(r'\b(?:EP|Episode)\s*[-:]?\s*(\d+)\b', raw_text, re.I)
    if ep_m:
        episode = int(ep_m.group(1))
    s_m = re.search(r'\b(?:S|Season)\s*[-:]?\s*(\d+)\b', raw_text, re.I)
    if s_m:
        season = int(s_m.group(1))

    return {
        "url": lz_url,
        "button_text": raw_text,
        "quality": qual,
        "size": size,
        "codec": codec,
        "season": season,
        "episode": episode,
    }


def extract_post_data_ssrmovies_enhanced(
    post_url: str,
    page_html: str,
    client: SSRMoviesClient | None = None,
    resolve_direct: bool = True,
) -> dict | None:
    """
    Extracts complete, rich catalog metadata and LinksZilla releases from an SSRMovies post.
    """
    slug = post_url.rstrip("/").split("/")[-1]

    # 1. Clean Title and Year
    title_m = re.search(r"<title>(.*?)</title>", page_html, re.I)
    raw_title = title_m.group(1).split(" – SSRmovies")[0].split(" | ")[0].strip() if title_m else slug
    raw_title = html.unescape(raw_title)

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    # Strip year and trailing resolution/quality noise
    clean_title = re.sub(r"\s*[\(\[]?\b(19\d{2}|20\d{2})\b.*$", "", raw_title).strip()
    clean_title = re.sub(
        r"\s*(?:2160p|4k|1080p|720p|480p|web-dl|bluray|hdrip|hdtc|hdtv|esubs|dual audio|hindi|org|cleaned|hq|season\s*\d+|s\d+).*$",
        "",
        clean_title,
        flags=re.I,
    ).strip()
    if not clean_title:
        clean_title = slug.replace("-", " ").title()

    canonical_key = fast_fetch.generate_canonical_key(clean_title, year)

    # 2. Content Type (Movie vs Series)
    content_type = "movie"
    if re.search(r'\b(?:Season\s*\d+|S\d+|Complete\s+Series|Episodes?)\b', raw_title, re.I):
        content_type = "series"

    # 3. Poster URL
    poster_url = None
    # 3a. Imgurworld or CDN poster tag in <p class="poster">
    poster_m = re.search(r'<p\s+class=["\']poster["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']', page_html, re.I | re.S)
    if poster_m:
        poster_url = poster_m.group(1)
    else:
        # 3b. TMDB image
        tmdb_m = re.search(r'https?://image\.tmdb\.org/t/p/(?:original|w\d+)/[A-Za-z0-9_\-\.]+\.(?:jpg|jpeg|png|webp)', page_html, re.I)
        if tmdb_m:
            poster_url = tmdb_m.group(0)
        else:
            # 3c. OpenGraph image
            og_m = re.search(r'<meta property="og:image" content="([^"]+)"', page_html)
            if og_m:
                poster_url = og_m.group(1)

    # 4. Synopsis / Storyline
    synopsis = None
    desc_m = re.search(r'<meta name="description" content="([^"]+)"', page_html)
    if desc_m:
        synopsis = html.unescape(desc_m.group(1).strip())
    else:
        # Fallback to paragraph before the download links
        p_match = re.search(r'<p style=["\']text-align: center;["\']>(.*?enjoy the full movie.*?)</p>', page_html, re.I | re.S)
        if p_match:
            synopsis = html.unescape(re.sub(r'<[^>]+>', '', p_match.group(1)).strip())

    # 5. Language and Audio
    language = "Hindi"
    raw_lower = raw_title.lower()
    if "punjabi" in raw_lower:
        language = "Punjabi"
    elif "dual audio" in raw_lower:
        language = "Hindi + English"
    elif "multi audio" in raw_lower:
        language = "Multi Audio"
    elif "tamil" in raw_lower or "telugu" in raw_lower or "south" in raw_lower:
        language = "South Hindi Dubbed"
    elif "english" in raw_lower:
        language = "English"

    # 6. Extract Release Download Buttons (LinksZilla anchors)
    button_matches = re.findall(
        r'(<a\s+[^>]*href=["\']https?://secure\.linkszilla\.top/view/[^"\']+["\'][^>]*>.*?</a>)',
        page_html,
        re.I | re.S,
    )

    releases = []
    seen_lz_urls = set()

    for btn_html in button_matches:
        parsed = parse_ssrmovies_release_button(btn_html, page_html)
        if not parsed or parsed["url"] in seen_lz_urls:
            continue
        seen_lz_urls.add(parsed["url"])

        qual = parsed["quality"]
        size_label = f" [{parsed['size']}]" if parsed["size"] else ""
        rel_title = f"{clean_title} ({year or ''}) {qual.upper()}{size_label} WEB-DL"

        sources = []
        if resolve_direct:
            sources = fast_fetch.unwrap_linkszilla(parsed["url"])
        else:
            sources = [{
                "source_name": "LinksZilla Bridge",
                "service": "linkszilla",
                "resource_id": parsed["url"].rstrip("/").split("/")[-1],
                "source_url": parsed["url"],
                "final_url": parsed["url"],
                "is_temporary": 0,
            }]

        releases.append({
            "release_title": rel_title,
            "quality": qual,
            "codec": parsed["codec"],
            "size": parsed["size"],
            "languages": language,
            "season": parsed["season"],
            "episode": parsed["episode"],
            "intermediate_url": parsed["url"],
            "source_site": "ssrmovies",
            "sources": sources,
        })

    return {
        "url": post_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": content_type,
        "seasons": None,
        "poster_url": poster_url,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": json.dumps(["Action", "Drama"]) if "dual" in raw_title.lower() else None,
        "synopsis": synopsis,
        "is_18_plus": 0,
        "is_animated": 1 if "anime" in raw_lower or "animated" in raw_lower else 0,
        "source_site": "ssrmovies",
        "industry": "Bollywood" if language in ("Hindi", "Punjabi", "South Hindi Dubbed") else "Hollywood",
        "country": "India" if language in ("Hindi", "Punjabi", "South Hindi Dubbed") else "USA",
        "language": language,
        "canonical_key": canonical_key,
        "releases": releases,
    }


def write_status(data: dict):
    """Atomically updates STATUS_FILE."""
    try:
        tmp = STATUS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(STATUS_FILE)
    except Exception:
        pass


def get_db_stats(db_path: Path) -> dict:
    """Returns database summary counts."""
    if not db_path.exists():
        return {"exists": False}
    with sqlite3.connect(db_path) as conn:
        posts = conn.execute("SELECT count(*) FROM posts").fetchone()[0]
        releases = conn.execute("SELECT count(*) FROM releases").fetchone()[0]
        sources = conn.execute("SELECT count(*) FROM download_sources").fetchone()[0]
        sitemap_total = conn.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'ssrmovies'").fetchone()[0]
        sitemap_scraped = conn.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'ssrmovies' AND scraped = 1").fetchone()[0]
        direct_r2 = conn.execute("SELECT count(*) FROM download_sources WHERE final_url LIKE '%.r2.%'").fetchone()[0]
        gdirect = conn.execute("SELECT count(*) FROM download_sources WHERE service = 'google_cdn' OR final_url LIKE '%googleusercontent%'").fetchone()[0]
        stream_count = conn.execute("SELECT count(*) FROM download_sources WHERE service = 'stream' OR final_url LIKE '%watch-online%'").fetchone()[0]

    return {
        "exists": True,
        "posts": posts,
        "releases": releases,
        "sources": sources,
        "sitemap_total": sitemap_total,
        "sitemap_scraped": sitemap_scraped,
        "sitemap_pending": sitemap_total - sitemap_scraped,
        "direct_r2": direct_r2,
        "gdirect": gdirect,
        "streams": stream_count,
    }


def print_status(db_path: Path):
    """Displays terminal formatted status."""
    stats = get_db_stats(db_path)
    print("=" * 60)
    print(f" 📊 SSRMovies Staging DB Status ({db_path.name})")
    print("=" * 60)
    if not stats["exists"]:
        print(f" Database file not found at {db_path}")
        return

    print(f" Total Catalog Posts    : {stats['posts']:,}")
    print(f" Total Releases Found   : {stats['releases']:,}")
    print(f" Total Direct Sources   : {stats['sources']:,}")
    print(f" ⚡ Google CDN Streams   : {stats['gdirect']:,}")
    print(f" ⚡ Cloudflare R2 Streams: {stats['direct_r2']:,}")
    print(f" ▶  Watch-Online Streams : {stats['streams']:,}")
    print("-" * 60)
    print(f" Sitemap / API Cache    : {stats['sitemap_scraped']:,} / {stats['sitemap_total']:,} scraped ({stats['sitemap_pending']:,} pending)")
    print("=" * 60)


def scrape_ssrmovies_worker(
    post_url: str,
    client: SSRMoviesClient,
    resolve_direct: bool = True,
) -> tuple[bool, int, int]:
    """Worker task: fetches post, extracts releases & sources, persists to SQLite."""
    code, final_url, html_text = client.get_text(post_url)
    if code != 200 or not html_text:
        return False, 0, 0

    data = extract_post_data_ssrmovies_enhanced(
        post_url=final_url,
        page_html=html_text,
        client=client,
        resolve_direct=resolve_direct,
    )
    if not data or not data["releases"]:
        # Mark as scraped to avoid infinite loops on empty/removed posts
        with fast_fetch._DB_WRITE_LOCK:
            with fast_fetch.get_db() as conn:
                conn.execute("UPDATE sitemap_cache SET scraped = 1 WHERE loc = ? AND site = 'ssrmovies'", (post_url,))
                conn.commit()
        return True, 0, 0

    rel_count = len(data["releases"])
    src_count = sum(len(r.get("sources", [])) for r in data["releases"])

    with fast_fetch._DB_WRITE_LOCK:
        post_id = fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
        if post_id:
            with fast_fetch.get_db() as conn:
                conn.execute("UPDATE sitemap_cache SET scraped = 1 WHERE loc = ? AND site = 'ssrmovies'", (post_url,))
                conn.commit()

    return True, rel_count, src_count


def run_ssrmovies_scraper(
    client: SSRMoviesClient,
    db_path: Path,
    limit: int | None = None,
    workers: int = 5,
    delay: float = 0.3,
    resolve_direct: bool = True,
):
    """Runs concurrent multi-worker scraping of pending SSRMovies post URLs."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    with fast_fetch.get_db() as conn:
        q = "SELECT loc FROM sitemap_cache WHERE scraped = 0 AND site = 'ssrmovies' ORDER BY rowid ASC"
        if limit:
            q += f" LIMIT {int(limit)}"
        rows = conn.execute(q).fetchall()
        pending_urls = [r[0] for r in rows]

    total_pending = len(pending_urls)
    if total_pending == 0:
        print("[✓] No pending SSRMovies posts to scrape! Run --sync-api to ingest new posts.", flush=True)
        return

    print(f"[*] Starting SSRMovies scraping for {total_pending:,} titles with {workers} workers (delay: {delay}s)...", flush=True)
    start_time = time.time()
    completed = 0
    total_rel = 0
    total_src = 0
    failed = 0

    status_data = {
        "site": "ssrmovies",
        "total": total_pending,
        "completed": 0,
        "pending": total_pending,
        "releases": 0,
        "sources": 0,
        "failed": 0,
        "start_time": start_time,
        "speed": 0.0,
    }
    write_status(status_data)

    thread_local = threading.local()

    def get_thread_client():
        if not hasattr(thread_local, "client"):
            thread_local.client = SSRMoviesClient(base_url=client.base_url, request_interval=delay)
        return thread_local.client

    def task_fn(url):
        t_client = get_thread_client()
        return scrape_ssrmovies_worker(url, t_client, resolve_direct=resolve_direct)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(task_fn, url): url for url in pending_urls}
        for future in concurrent.futures.as_completed(future_map):
            if STOP_REQUESTED:
                print("\n[!] Cancelling pending tasks for graceful exit...", flush=True)
                executor.shutdown(wait=False, cancel_futures=True)
                break

            try:
                ok, rels, srcs = future.result()
                if ok:
                    completed += 1
                    total_rel += rels
                    total_src += srcs
                else:
                    failed += 1
            except Exception:
                failed += 1

            if (completed + failed) % 10 == 0 or (completed + failed) == total_pending:
                elapsed = max(0.1, time.time() - start_time)
                speed = (completed + failed) / elapsed
                rem = max(0, total_pending - (completed + failed))
                eta_s = rem / speed if speed > 0 else 0
                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_s))
                print(
                    f"    [{completed + failed}/{total_pending}] releases={total_rel:,} sources={total_src:,} failed={failed} "
                    f"speed={speed:.2f} titles/sec ETA: {eta_str}",
                    flush=True,
                )

                status_data.update({
                    "completed": completed,
                    "pending": rem,
                    "releases": total_rel,
                    "sources": total_src,
                    "failed": failed,
                    "speed": round(speed, 2),
                    "eta": eta_str,
                })
                write_status(status_data)

    print(f"\n[✓] SSRMovies scrape finished in {time.time() - start_time:.1f}s: {completed:,} completed, {total_rel:,} releases, {total_src:,} sources, {failed} failed.", flush=True)
    print_status(db_path)


def main():
    parser = argparse.ArgumentParser(description="Dedicated Staging Importer for SSRMovies")
    parser.add_argument("--sync-api", action="store_true", help="Ingest all post URLs from SSRMovies WP REST API")
    parser.add_argument("--max-pages", type=int, default=None, help="Maximum WP REST API pages to ingest")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of posts to scrape")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent scraper workers")
    parser.add_argument("--delay", type=float, default=0.3, help="Request rate-limit delay in seconds")
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL, help="Base domain for SSRMovies")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to staging SQLite database")
    parser.add_argument("--status", action="store_true", help="Print staging database stats and exit")
    parser.add_argument("--no-resolve-direct", action="store_true", help="Skip unwrapping LinksZilla mirrors")

    args = parser.parse_args()

    if args.status:
        print_status(args.db_path)
        return

    client = SSRMoviesClient(base_url=args.base_url, request_interval=args.delay)

    if args.sync_api:
        sync_api_to_db(client, args.db_path, max_pages=args.max_pages)
        if not args.limit:
            return

    run_ssrmovies_scraper(
        client=client,
        db_path=args.db_path,
        limit=args.limit,
        workers=args.workers,
        delay=args.delay,
        resolve_direct=not args.no_resolve_direct,
    )


if __name__ == "__main__":
    main()
