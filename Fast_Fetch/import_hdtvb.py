#!/usr/bin/env python3
"""
import_hdtvb.py — Dedicated staging importer and scraper for HDTVB (https://hdtvb.net / https://hdutv.com).
The site republishes the HDHub4u catalog under its own domains, but its staging
rows belong to the `hdtvb` site key — never to `hdhub4u`.

Key Features:
  1. Dedicated staging database isolation: hdtvb.db (prevents SQLite locking contention).
  2. Full sitemap synchronization (5,692+ movie and series titles in sitemap.xml).
  3. Rich metadata extraction: Clean title, year, audio languages, resolution, size, poster.
  4. Full quality tier mapping: 480p-HEVC, 720p-HEVC, 720p-HD, 1080p-HD, 1080p-WEB-DL, 2160p (4K UHD).
  5. HubCDN gateway & Cloudflare R2 direct stream resolution (/l.php redirect).
  6. Resumable via sitemap_cache (scraped status tracking).
  7. 100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_hdtvb.py --sync-sitemap              # Sync all titles from sitemap.xml
    python Fast_Fetch/import_hdtvb.py --limit 10                  # Scrape 10 pending titles
    python Fast_Fetch/import_hdtvb.py --resolve-direct --limit 5  # Scrape with direct R2 stream resolution
    python Fast_Fetch/import_hdtvb.py --status                    # Show current database counts
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

# This staging database holds hdtvb.net only; the site key was copy-pasted from
# the hdhub4u importer, which made every hdtvb post claim to be a hdhub4u page.
SITE_KEY = "hdtvb"

DEFAULT_BASE_URL = "https://hdutv.com"
DEFAULT_DB_PATH = (
    Path("/home/ubuntu/radd-stream-data/hdtvb.db")
    if Path("/home/ubuntu/radd-stream-data").exists()
    else BASE_DIR / "hdtvb.db"
)
STATUS_FILE = BASE_DIR / "hdtvb_status.json"

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


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HDTVBClient:
    """HTTP Client with rate limiting and retry handling for hdtvb.net and hubcdn.io."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, request_interval: float = 0.3, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.request_interval = max(0.0, request_interval)
        self.retries = max(1, retries)
        self.ssl_ctx = get_ssl_context()
        self._next_request_at = 0.0
        self._lock = threading.Lock()
        self.redirect_opener = urllib.request.build_opener(
            NoRedirectHandler,
            urllib.request.HTTPSHandler(context=self.ssl_ctx),
        )

    def _wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next_request_at:
                time.sleep(self._next_request_at - now)
            self._next_request_at = time.monotonic() + self.request_interval

    def get_text(self, url: str, referer: str | None = None) -> tuple[int, str, str]:
        headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
                with urllib.request.urlopen(req, timeout=15, context=self.ssl_ctx) as resp:
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

    def resolve_hubcdn_direct(self, cloud_url: str) -> dict[str, str]:
        """Resolves hubcdn.io/cloud/ URL into direct Cloudflare R2 link and alternative mirrors."""
        res: dict[str, str] = {"cloud_url": cloud_url}
        code, final_u, page_html = self.get_text(cloud_url, referer=self.base_url + "/")
        if code != 200 or not page_html:
            return res

        # 1. Direct Cloudflare R2 link via cf_route
        cf_match = re.search(r'href=["\'](/l\.php\?[^"\']*cf_route=[^"\']*)["\']', page_html)
        if cf_match:
            cf_url = urllib.parse.urljoin("https://hubcdn.io", html.unescape(cf_match.group(1)))
            req = urllib.request.Request(cf_url, headers={
                "User-Agent": fast_fetch.USER_AGENT,
                "Referer": cloud_url,
            })
            try:
                self._wait()
                self.redirect_opener.open(req, timeout=12)
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308):
                    r2_loc = e.headers.get("Location")
                    if r2_loc:
                        res["direct_r2"] = r2_loc
            except Exception:
                pass

        # 2. Extract alternative mirror links from page
        all_l_links = re.findall(r'href=["\'](/l\.php\?[^"\']+)["\'][^>]*>(.*?)</a>', page_html, re.S)
        for rel_link, label in all_l_links:
            lbl_clean = re.sub(r'<[^>]+>', '', label).strip().lower()
            abs_l_url = urllib.parse.urljoin("https://hubcdn.io", html.unescape(rel_link))
            if "pixeldrain" in lbl_clean:
                res["pixeldrain"] = abs_l_url
            elif "gofile" in lbl_clean:
                res["gofile"] = abs_l_url
            elif "hubcloud" in lbl_clean:
                res["hubcloud"] = abs_l_url
            elif "gdflix" in lbl_clean:
                res["gdflix"] = abs_l_url

        return res


def parse_sitemap_urls(xml_text: str) -> list[str]:
    """Extracts post .html URLs from sitemap XML."""
    locs = re.findall(r'<loc>(https?://[^<]+)</loc>', xml_text)
    # Filter only post .html pages (ignore categories or home)
    post_urls = [l.strip() for l in locs if l.strip().endswith(".html")]
    # Deduplicate while preserving order
    return list(dict.fromkeys(post_urls))


def sync_sitemap_to_db(client: HDTVBClient, db_path: Path) -> int:
    """Fetches hdtvb.net/sitemap.xml and populates sitemap_cache table in staging DB."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    sitemap_url = f"{client.base_url}/sitemap.xml"
    print(f"[*] Fetching sitemap from {sitemap_url}...", flush=True)
    status, _, xml_text = client.get_text(sitemap_url)
    if status != 200 or not xml_text:
        raise RuntimeError(f"Failed to fetch sitemap: HTTP {status}")

    post_urls = parse_sitemap_urls(xml_text)
    print(f"[*] Discovered {len(post_urls):,} post URLs in sitemap.", flush=True)

    records = [
        (url, None, url.rstrip("/").split("/")[-1].replace(".html", ""), 0, SITE_KEY)
        for url in post_urls
    ]

    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            for start in range(0, len(records), 2000):
                chunk = records[start:start + 2000]
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(loc) DO UPDATE SET
                        slug = excluded.slug,
                        site = excluded.site;
                    """,
                    chunk,
                )

    print(f"[✓] Successfully populated {len(records):,} URLs into sitemap_cache in {db_path.name}\n", flush=True)
    return len(records)


def extract_post_data_hdtvb(
    post_url: str,
    page_html: str,
    client: HDTVBClient | None = None,
    resolve_direct: bool = False,
) -> dict | None:
    """Parses full media metadata, releases, and sources from an hdtvb.net post page."""
    slug = post_url.rstrip("/").split("/")[-1].replace(".html", "")

    # 1. Title extraction
    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', page_html, re.I | re.S)
    if not title_m:
        title_m = re.search(r'<title>(.*?)</title>', page_html, re.I)
    if not title_m:
        return None

    raw_title = title_m.group(1).split('&raquo;')[0].split('»')[0].strip()
    raw_title = re.sub(r'&#x[A-Za-z0-9]+;', '', raw_title)  # Remove icon entities
    raw_title = re.sub(r'<[^>]+>', '', raw_title).strip()
    raw_title = html.unescape(raw_title)

    # 2. Year & Clean Title
    year_m = re.search(r'\b(19\d{2}|20\d{2})\b', raw_title)
    year = int(year_m.group(1)) if year_m else None
    clean_title = re.sub(r'\s*\(\s*\d{4}\s*\).*$', '', raw_title)
    clean_title = re.sub(
        r'\s*(?:1080p|720p|480p|2160p|4k|web-dl|webrip|hdrip|bluray|esubs|dual audio|hindi|org|season\s*\d+|s\d+|all episodes|completed|web series|hollywood|bollywood|south).*$',
        '',
        clean_title,
        flags=re.I,
    ).strip()
    clean_title = re.sub(r'\s+', ' ', clean_title).strip(' -+')
    canonical_key = fast_fetch.generate_canonical_key(clean_title, year)

    # 3. Content Type & Seasons
    is_series = bool(re.search(r'\b(season|s\d+|episode|series|complete|batch)\b', raw_title, re.I))
    content_type = "series" if is_series else "movie"
    season_m = re.search(r'\b(Season\s*\d+(?:\s*[-&]\s*\d+)?|S\d+)\b', raw_title, re.I)
    seasons = season_m.group(1) if season_m else None

    # 4. Poster Image
    poster_url = None
    cover_m = re.search(r'<img[^>]+class=["\'][^"\']*movie-cover[^"\']*["\'][^>]*>', page_html, re.I | re.S)
    if cover_m:
        tag_str = re.sub(r'onerror=["\'][^"\']*["\']', '', cover_m.group(0))
        src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', tag_str)
        if src_m:
            poster_url = urllib.parse.urljoin("https://hdtvb.net/", src_m.group(1))

    # 4b. Genres, Synopsis, and Language
    genres = None
    genre_m = re.search(r'class=["\']info-genre["\'][^>]*>(.*?)</span>', page_html, re.I | re.S)
    if genre_m:
        g_text = re.sub(r'<[^>]+>', '', genre_m.group(1)).strip()
        g_list = [g.strip() for g in g_text.split(',') if g.strip()]
        if g_list:
            genres = json.dumps(g_list)

    synopsis = None
    desc_m = re.search(r'class=["\']hdh-text["\'][^>]*>(.*?)</div>', page_html, re.I | re.S)
    if desc_m:
        synopsis = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
        synopsis = html.unescape(synopsis)
    elif '<meta name="description"' in page_html:
        m = re.search(r'<meta name="description" content="([^"]+)"', page_html)
        if m:
            synopsis = html.unescape(m.group(1).strip())

    language = "Hindi"
    lang_m = re.search(r'class=["\']info-language["\'][^>]*>(.*?)</span>', page_html, re.I | re.S)
    if lang_m:
        language = re.sub(r'<[^>]+>', '', lang_m.group(1)).strip()
    elif "dual audio" in raw_title.lower():
        language = "Hindi + English"

    # 5. Extract Releases & HubCDN Links
    releases = []
    hubcdn_matches = re.findall(
        r'<a[^>]+href=["\'](https?://hubcdn\.io/cloud/[^"\']+)["\'][^>]*>(.*?)</a>',
        page_html,
        re.I | re.S,
    )

    for cloud_url, btn_label in hubcdn_matches:
        lbl_clean = re.sub(r'<[^>]+>', '', btn_label).strip()
        qual_m = re.search(r'\{(.*?)\}', lbl_clean)
        quality = qual_m.group(1) if qual_m else "HD"
        size_m = re.search(r'Download\s+([0-9\.]+\s*(?:Mb|Gb|MB|GB))', lbl_clean, re.I)
        size_str = size_m.group(1) if size_m else ""

        rel_title = f"{clean_title}"
        if year:
            rel_title += f" ({year})"
        if seasons:
            rel_title += f" {seasons}"
        rel_title += f" {quality}"
        if size_str:
            rel_title += f" [{size_str}]"

        sources = []

        # If direct resolution is requested, resolve R2 link and mirrors
        if resolve_direct and client:
            hub_data = client.resolve_hubcdn_direct(cloud_url)
            if hub_data.get("direct_r2"):
                sources.append({
                    "source_name": f"⚡ Cloudflare R2 Direct (10Gbps) [{quality}]",
                    "service": "cloudflare_r2",
                    "source_url": hub_data["direct_r2"],
                    "final_url": hub_data["direct_r2"],
                    "playback_type": "direct",
                })
            if hub_data.get("pixeldrain"):
                sources.append({
                    "source_name": f"PixelDrain [{quality}]",
                    "service": "pixeldrain",
                    "source_url": hub_data["pixeldrain"],
                    "final_url": hub_data["pixeldrain"],
                    "playback_type": "download",
                })
            if hub_data.get("gofile"):
                sources.append({
                    "source_name": f"GoFile [{quality}]",
                    "service": "gofile",
                    "source_url": hub_data["gofile"],
                    "final_url": hub_data["gofile"],
                    "playback_type": "download",
                })

        # Always include the HubCDN Gateway source
        sources.append({
            "source_name": f"HubCDN Cloud Gateway [{quality}]",
            "service": "hubcdn",
            "source_url": cloud_url,
            "final_url": cloud_url,
            "playback_type": "url",
        })

        releases.append({
            "release_title": rel_title,
            "quality": quality,
            "codec": "hevc" if "hevc" in quality.lower() else "x264",
            "size": size_str,
            "languages": "Hindi + English Dual Audio" if "dual audio" in raw_title.lower() else "Hindi",
            "season": seasons,
            "episode": None,
            "intermediate_url": cloud_url,
            "source_site": SITE_KEY,
            "sources": sources,
        })

    return {
        "url": post_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": content_type,
        "poster_url": poster_url,
        "genres": genres,
        "synopsis": synopsis,
        "language": language,
        "source_site": SITE_KEY,
        "canonical_key": canonical_key,
        "releases": releases,
    }


def save_post_record(data: dict, db_path: Path) -> int:
    """Atomically saves media post record and marks URL as scraped in sitemap_cache."""
    fast_fetch.DB_PATH = db_path
    post_id = fast_fetch.save_scraped_data(
        data,
        enrich_metadata=False,
        ensure_db=False,
    )
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE sitemap_cache SET scraped = 1 WHERE loc = ? AND site = ?",
                (data["url"], SITE_KEY),
            )
    return post_id


def run_hdtvb_scraper(
    base_url: str = DEFAULT_BASE_URL,
    db_path: Path = DEFAULT_DB_PATH,
    limit: int | None = None,
    workers: int = 5,
    delay: float = 0.3,
    resolve_direct: bool = False,
):
    """Main worker pool orchestrator for scraping hdtvb.net titles into staging DB."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    client = HDTVBClient(base_url, request_interval=delay)

    # Check pending URLs in sitemap_cache
    with fast_fetch.get_db() as conn:
        cursor = conn.execute(
            "SELECT loc FROM sitemap_cache WHERE site = ? AND scraped = 0 ORDER BY rowid ASC",
            (SITE_KEY,),
        )
        pending_urls = [row["loc"] for row in cursor]

    if not pending_urls:
        print("[*] No pending URLs in sitemap_cache. Syncing sitemap first...", flush=True)
        sync_sitemap_to_db(client, db_path)
        with fast_fetch.get_db() as conn:
            cursor = conn.execute(
                "SELECT loc FROM sitemap_cache WHERE site = ? AND scraped = 0 ORDER BY rowid ASC",
                (SITE_KEY,),
            )
            pending_urls = [row["loc"] for row in cursor]

    if limit is not None:
        pending_urls = pending_urls[:max(0, limit)]

    total_tasks = len(pending_urls)
    print(f"\n{'='*70}")
    print(f"🚀 HDTVB (hdtvb.net) Staging Ingestion Pipeline")
    print(f"   Database       : {db_path.name}")
    print(f"   Pending Titles : {total_tasks:,}")
    print(f"   Workers        : {workers} | Delay: {delay}s | Direct R2: {resolve_direct}")
    print(f"{'='*70}\n", flush=True)

    counters = {
        "completed": 0,
        "releases": 0,
        "sources": 0,
        "failed": 0,
        "start_time": time.time(),
    }

    thread_local = threading.local()

    def get_thread_client() -> HDTVBClient:
        if not hasattr(thread_local, "client"):
            thread_local.client = HDTVBClient(base_url, request_interval=delay)
        return thread_local.client

    def process_one_url(url: str) -> dict:
        if STOP_REQUESTED:
            return {"skipped": True}
        c = get_thread_client()
        code, final_url, html_text = c.get_text(url)
        if code != 200 or not html_text:
            return {"failed": True, "error": f"HTTP {code}", "url": url}

        data = extract_post_data_hdtvb(final_url, html_text, client=c, resolve_direct=resolve_direct)
        if not data or not data.get("releases"):
            # Mark as scraped or restricted so we don't loop endlessly
            with fast_fetch._DB_WRITE_LOCK:
                with fast_fetch.get_db() as conn:
                    conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ?", (url,))
            return {"skipped": True, "reason": "no_releases"}

        save_post_record(data, db_path)
        return {
            "completed": True,
            "title": data["clean_title"],
            "releases": len(data["releases"]),
            "sources": sum(len(r["sources"]) for r in data["releases"]),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_one_url, u): u for u in pending_urls}
        for future in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED:
                break
            res = future.result()
            counters["completed"] += 1
            counters["releases"] += res.get("releases", 0)
            counters["sources"] += res.get("sources", 0)
            if res.get("failed"):
                counters["failed"] += 1

            if counters["completed"] % 10 == 0 or counters["completed"] == total_tasks:
                elapsed = time.time() - counters["start_time"]
                speed = counters["completed"] / max(1, elapsed)
                print(
                    f"[{counters['completed']}/{total_tasks}] "
                    f"releases={counters['releases']} sources={counters['sources']} "
                    f"failed={counters['failed']} speed={speed:.2f} titles/sec",
                    flush=True,
                )
                try:
                    with open(STATUS_FILE, "w", encoding="utf-8") as sf:
                        json.dump({
                            "completed": counters["completed"],
                            "total": total_tasks,
                            "releases": counters["releases"],
                            "sources": counters["sources"],
                            "failed": counters["failed"],
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }, sf, indent=2)
                except Exception:
                    pass

    print(f"\n[✓] HDTVB scraping finished: {counters}", flush=True)


def get_status_summary(db_path: Path):
    """Outputs current stats for the staging database."""
    if not db_path.exists():
        print(f"Database {db_path} does not exist yet.")
        return
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM posts")
    posts = c.fetchone()[0]
    c.execute("SELECT count(*) FROM releases")
    releases = c.fetchone()[0]
    c.execute("SELECT count(*) FROM download_sources")
    sources = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = ? AND scraped = 1", (SITE_KEY,))
    scraped = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = ? AND scraped = 0", (SITE_KEY,))
    pending = c.fetchone()[0]
    conn.close()

    print("\n" + "=" * 55)
    print(f" 📊 HDTVB Staging Database Status ({db_path.name})")
    print("=" * 55)
    print(f" Catalog Posts   : {posts:,}")
    print(f" Releases Found  : {releases:,}")
    print(f" Sources Mapped  : {sources:,}")
    print(f" Scraped Titles  : {scraped:,}")
    print(f" Pending Titles  : {pending:,}")
    print("=" * 55 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="HDTVB (hdtvb.net) Staging Importer")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base origin URL")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite staging database")
    parser.add_argument("--sync-sitemap", action="store_true", help="Download and sync sitemap.xml to database")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of titles to scrape")
    parser.add_argument("--workers", type=int, default=5, help="Worker threads (default: 5)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests per worker (s)")
    parser.add_argument("--resolve-direct", action="store_true", help="Resolve HubCDN into direct Cloudflare R2 links")
    parser.add_argument("--status", action="store_true", help="Print database counts and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db_path).resolve()

    if args.status:
        get_status_summary(db_path)
        return

    client = HDTVBClient(args.base_url, request_interval=args.delay)

    if args.sync_sitemap:
        sync_sitemap_to_db(client, db_path)
        return

    run_hdtvb_scraper(
        base_url=args.base_url,
        db_path=db_path,
        limit=args.limit,
        workers=args.workers,
        delay=args.delay,
        resolve_direct=args.resolve_direct,
    )


if __name__ == "__main__":
    main()
