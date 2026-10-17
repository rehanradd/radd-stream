#!/usr/bin/env python3
"""
scrape_multimovies_full.py — High-performance, clone-ready full scraper for MultiMovies.

Features:
  1. Isolated staging SQLite database: multimovies.db
  2. Phase 1: Rapid JSON API catalog ingestion (/api/catalog?page=1..328) for 10,484 titles with TMDB posters/backdrops.
  3. Phase 2: Sitemap episode discovery (61,995 episodes mapped into series roots).
  4. Phase 3: Multithreaded watch servers & download mirrors crawling with dead-link tracking.
  5. Progress monitoring, graceful Ctrl+C handling, and status reporting.

100% Python Standard Library. Zero external pip packages.
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
import import_multimovies

DEFAULT_BASE_URL = "https://m1.multimovies.courses"
DEFAULT_DB_PATH = BASE_DIR / "multimovies.db"
STATUS_FILE = BASE_DIR / "multimovies_status.json"

STOP_REQUESTED = False


def _sigint_handler(signum, frame):
    global STOP_REQUESTED
    print("\n[!] Graceful shutdown requested... Finishing active requests and saving state.", flush=True)
    STOP_REQUESTED = True


signal.signal(signal.SIGINT, _sigint_handler)
signal.signal(signal.SIGTERM, _sigint_handler)


def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def make_request(url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": fast_fetch.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
        "Referer": DEFAULT_BASE_URL + "/",
    }
    req = urllib.request.Request(url, headers=headers)
    ctx = get_ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def update_status_file(data: dict):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ── Phase 1: Rapid API Catalog Ingestion ──────────────────────────────────────────


def ingest_api_catalog(base_url: str, db_path: Path, max_pages: int | None = None, force: bool = False) -> int:
    print(f"\n{'='*70}\n[Phase 1] Rapid Catalog Ingestion via /api/catalog\n{'='*70}", flush=True)
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    if not force:
        try:
            with fast_fetch.get_db() as conn:
                existing = conn.execute("SELECT count(*) FROM posts WHERE source_site = 'multimovies'").fetchone()[0]
                if existing >= 10000:
                    print(f"[✓] Phase 1 already complete: {existing} titles found in {db_path.name}. Proceeding to streams.\n", flush=True)
                    return existing
        except Exception:
            pass

    total_titles_saved = 0
    page = 1
    total_pages = 328

    while not STOP_REQUESTED:
        if max_pages and page > max_pages:
            break
        catalog_url = f"{base_url}/api/catalog?page={page}"
        try:
            raw = make_request(catalog_url, timeout=12)
            data = json.loads(raw)
            items = data.get("items", [])
            total_pages = data.get("total_pages", total_pages)
            if not items:
                break

            with fast_fetch.get_db() as conn:
                for item in items:
                    raw_title = item.get("title", "")
                    clean_title = re.sub(
                        r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|bluray|hdrip|esubs|dual audio|hindi|org).*$",
                        "",
                        raw_title,
                        flags=re.IGNORECASE,
                    ).strip()
                    clean_title = re.sub(r"\s*\(\s*\d{4}\s*\).*$", "", clean_title).strip()
                    year = item.get("year")
                    c_type = "series" if item.get("type") == "tv" else "movie"
                    item_url = urllib.parse.urljoin(base_url, item.get("url", ""))
                    slug = item.get("slug") or item_url.rstrip("/").split("/")[-1]
                    canonical_key = fast_fetch.generate_canonical_key(clean_title, year)

                    conn.execute(
                        """
                        INSERT INTO posts
                            (url, slug, title, clean_title, year, content_type,
                             poster_url, backdrop_urls, imdb_rating, source_site,
                             language, canonical_key)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'multimovies', ?, ?)
                        ON CONFLICT(url) DO UPDATE SET
                            poster_url = COALESCE(excluded.poster_url, posts.poster_url),
                            backdrop_urls = COALESCE(excluded.backdrop_urls, posts.backdrop_urls),
                            imdb_rating = COALESCE(excluded.imdb_rating, posts.imdb_rating),
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (
                            item_url,
                            slug,
                            raw_title,
                            clean_title,
                            year,
                            c_type,
                            item.get("poster"),
                            item.get("backdrop"),
                            str(item.get("rating") or "") or None,
                            item.get("audio") or None,
                            canonical_key,
                        ),
                    )

                    conn.execute(
                        """
                        INSERT INTO sitemap_cache (loc, slug, scraped, site)
                        VALUES (?, ?, 0, 'multimovies')
                        ON CONFLICT(loc) DO UPDATE SET
                            slug = excluded.slug,
                            site = excluded.site;
                        """,
                        (item_url, slug),
                    )
                    total_titles_saved += 1

            if page % 10 == 0 or page == total_pages:
                print(f"  [Catalog] Page {page}/{total_pages} indexed ({total_titles_saved} titles in DB)", flush=True)

            if not data.get("has_more") or page >= total_pages:
                break
            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  [!] Error on catalog page {page}: {e}", flush=True)
            time.sleep(2)

    print(f"[✓] Phase 1 complete: {total_titles_saved} titles recorded in {db_path.name}\n", flush=True)
    return total_titles_saved


# ── Phase 2 & 3: Streams, Episodes, and Mirrors Crawling ────────────────────────


def run_full_scrape(
    base_url: str = DEFAULT_BASE_URL,
    db_path: Path = DEFAULT_DB_PATH,
    workers: int = 6,
    limit_roots: int | None = None,
    delay: float = 0.35,
):
    print(f"\n{'='*70}\n[Phase 2 & 3] Streaming & Download Mirrors Scraping\n{'='*70}", flush=True)
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    client = import_multimovies.SiteClient(base_url, request_interval=delay)
    print("[*] Inspecting site sitemaps for complete episode & title inventory...", flush=True)
    if hasattr(import_multimovies, "discover_sitemaps"):
        title_urls, episode_urls, episodes_by_root = import_multimovies.discover_sitemaps(client)
    else:
        title_urls, episode_urls = import_multimovies.fetch_sitemap_inventory(client)
        episodes_by_root = {}
        for ep in episode_urls:
            info = import_multimovies.series_root_for_episode(ep)
            if info:
                episodes_by_root.setdefault(info[0], []).append(ep)
        for root, urls in episodes_by_root.items():
            urls.sort(key=lambda u: (
                import_multimovies.series_root_for_episode(u)[1],
                import_multimovies.series_root_for_episode(u)[2],
            ))
    roots = import_multimovies._unique(title_urls + list(episodes_by_root))

    if limit_roots is not None:
        roots = roots[:max(0, limit_roots)]

    all_urls = import_multimovies._unique(title_urls + episode_urls + list(episodes_by_root))
    import_multimovies._cache_urls(all_urls)
    status_map = import_multimovies._cache_status()

    # Determine remaining roots
    pending_roots = [
        r for r in roots
        if status_map.get(r) not in (1, -1) or any(status_map.get(ep) not in (1, -1) for ep in episodes_by_root.get(r, []))
    ]

    print(f"[*] Total Roots: {len(roots)} | Pending: {len(pending_roots)} | Total Episode URLs: {len(episode_urls)}", flush=True)

    counters = {
        "total_roots": len(roots),
        "completed_roots": len(roots) - len(pending_roots),
        "pending_roots": len(pending_roots),
        "releases": 0,
        "sources": 0,
        "failed": 0,
        "start_time": time.time(),
    }

    thread_local = threading.local()

    def get_worker_client() -> import_multimovies.SiteClient:
        if not hasattr(thread_local, "client"):
            c = import_multimovies.SiteClient(base_url, request_interval=delay)
            c.robot_parser = client.robot_parser
            thread_local.client = c
        return thread_local.client

    def process_one_root(root_url: str) -> dict:
        if STOP_REQUESTED:
            return {"skipped": True}
        c = get_worker_client()
        episodes = episodes_by_root.get(root_url, [])
        path = urllib.parse.urlsplit(root_url).path
        try:
            if path.startswith("/movie/"):
                return import_multimovies._process_movie(c, root_url, c.host, dry_run=False)
            elif path.startswith("/series/"):
                return import_multimovies._process_series(c, root_url, episodes, c.host, dry_run=False)
            return {"skipped": True}
        except Exception as e:
            return {"failed": 1, "error": str(e), "url": root_url}

    # Parallel worker execution with connection pool
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_one_root, r): r for r in pending_roots}
        for future in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED:
                break
            res = future.result()
            counters["completed_roots"] += 1
            counters["releases"] += res.get("releases", 0)
            counters["sources"] += res.get("sources", 0)
            if res.get("failed"):
                counters["failed"] += 1

            if counters["completed_roots"] % 10 == 0 or counters["completed_roots"] == len(roots):
                elapsed = time.time() - counters["start_time"]
                speed = counters["completed_roots"] / max(1, elapsed)
                print(
                    f"[{counters['completed_roots']}/{len(roots)}] "
                    f"releases={counters['releases']} sources={counters['sources']} "
                    f"failed={counters['failed']} speed={speed:.2f} roots/sec",
                    flush=True,
                )
                update_status_file({
                    "completed_roots": counters["completed_roots"],
                    "total_roots": len(roots),
                    "releases": counters["releases"],
                    "sources": counters["sources"],
                    "failed": counters["failed"],
                    "percent": round(counters["completed_roots"] / len(roots) * 100, 2),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })

    print(f"\n[✓] MultiMovies full scrape finished: {counters}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="MultiMovies Full Clone & Ingestion Pipeline")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="MultiMovies origin")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite database")
    parser.add_argument("--workers", type=int, default=6, help="Parallel worker threads (default: 6)")
    parser.add_argument("--delay", type=float, default=0.35, help="Per-request delay per worker")
    parser.add_argument("--limit-roots", type=int, default=None, help="Limit number of roots to process")
    parser.add_argument("--catalog-only", action="store_true", help="Run only Phase 1 (rapid JSON catalog)")
    parser.add_argument("--streams-only", action="store_true", help="Run only Phase 2 & 3 (streams & mirrors)")
    parser.add_argument("--force-catalog", action="store_true", help="Force re-running Phase 1 even if posts exist")
    parser.add_argument("--status", action="store_true", help="Print current status JSON and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db_path).resolve()

    if args.status:
        if STATUS_FILE.exists():
            print(STATUS_FILE.read_text(encoding="utf-8"))
        else:
            print("No active status file found.")
        return

    print(f"🚀 Initializing MultiMovies Full Clone Pipeline")
    print(f"   Origin   : {args.base_url}")
    print(f"   Database : {db_path}")
    print(f"   Workers  : {args.workers}")

    if not args.streams_only:
        ingest_api_catalog(args.base_url, db_path, force=args.force_catalog)

    if not args.catalog_only and not STOP_REQUESTED:
        run_full_scrape(
            base_url=args.base_url,
            db_path=db_path,
            workers=args.workers,
            limit_roots=args.limit_roots,
            delay=args.delay,
        )


if __name__ == "__main__":
    main()
