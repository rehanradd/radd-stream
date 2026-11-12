#!/usr/bin/env python3
"""
import_movienestbd.py — Dedicated staging importer and scraper for MovieNestBD
(https://movienestbd.best), Bangladeshi + Bollywood/South/Hollywood/Korean
watch + download catalog behind a public no-key JSON API.

MEASURED LIVE FROM THE ORACLE VM, 2026-11-09 (Session 118):
  * GET /api/v1/search/suggest?q=ramayana 200:
    {"success": true, "data": [{"title", "slug", "year"}]}.
  * GET /api/v1/search?q=ramayana 200:
    {"count": 3, "data": [{id, slug, title, poster, ...}]}.
  * GET /api/v1/search?q=a&page=2 200: 18 rows/page, keys count / data /
    has_next / has_prev / page / total_pages / success; count 16,341 for "a".
    Pagination works via ?page=N. /api/v1/movies and /api/v1/trending are
    404 HTML — search is the ONLY catalog enumeration surface.
  * GET /api/v1/movie/ramayana-rise-of-a-legend 200 (3,113 B): full detail —
    id, slug, title, poster, cover, year, quality ("PreDvD"), rating (8.9),
    description, casts, director, is_series (false), is_adult (false),
    watch (player.jiofiles.pics/...), categories[], genres[].
  * Series detail (legends-of-the-ramayana-with-amish-s1, 2,272 B):
    is_series true, episodes null (one row per season slug, e.g. "...S1"),
    links[] per quality: {id, link: embed.jiofiles.pics/..., quality: {name:
    "480P"}, movie_id} — one watch link per quality.
  * The title-page URL pattern is NOT /movie/<slug> (404) — scrape via the
    API, never HTML. No download field was seen in detail JSON; the watch /
    links URLs are embeds (playback_type "url", service "jiofiles"), stored
    as-is for the resolver to unwrap later — jiofiles is a NEW host, not yet
    cracked, so these rows are catalog + bridge, not proven playable.

Catalog enumeration: search one letter at a time (a-z, plus 0-9) and paginate
each letter until has_next is false. A letter's count is the ceiling; the
full catalog is ~16k+ titles for "a" alone, so a full run is a long gated
job — --limit caps titles, --letters restricts the sweep.

100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_movienestbd.py --sync-search --letters ab --limit 20
    python Fast_Fetch/import_movienestbd.py --limit 50                # Scrape 50 pending titles
    python Fast_Fetch/import_movienestbd.py --workers 3 --delay 0.5  # Full background run
    python Fast_Fetch/import_movienestbd.py --status                  # Show current database counts
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import signal
import sqlite3
import ssl
import string
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
from config import staging_db_path
from domain_resolver import get_active_base_url, resolve_if_dead

DEFAULT_BASE_URL = "https://movienestbd.best"
SITE_NAME = "movienestbd"
DEFAULT_DB_PATH = staging_db_path("movienestbd")
STATUS_FILE = BASE_DIR / "movienestbd_status.json"
SEARCH_PAGE_SIZE = 18  # measured: the API returns 18 rows per page
DEFAULT_LETTERS = string.ascii_lowercase + string.digits

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


class MovieNestBDClient:
    """HTTP client with rate limiting and retry handling for MovieNestBD."""

    def __init__(self, base_url: str | None = None, request_interval: float = 0.3, retries: int = 3):
        # Session 106: the registry is the source of truth for the
        # live domain; an explicit base_url (CLI --base-url) still wins.
        self.base_url = (base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL)).rstrip("/")
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

    def get_json(self, url: str, timeout: int = 15) -> tuple[int, dict]:
        headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": "application/json, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(self.retries):
            self._wait()
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_ctx) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    try:
                        return resp.status, json.loads(body)
                    except json.JSONDecodeError:
                        return resp.status, {}
            except urllib.error.HTTPError as e:
                if attempt == self.retries - 1:
                    return e.code, {}
                time.sleep(1.0)
            except Exception:
                if attempt == self.retries - 1:
                    return 0, {}
                time.sleep(1.0)
        return 0, {}

    def search_page(self, query: str, page: int = 1) -> dict:
        """One /api/v1/search page: {data, count, has_next, total_pages}."""
        url = (
            f"{self.base_url}/api/v1/search?"
            f"q={urllib.parse.quote(query)}&page={page}"
        )
        status, payload = self.get_json(url)
        if status != 200 or not payload.get("success", True):
            return {"data": [], "count": 0, "has_next": False, "total_pages": 0}
        return payload

    def movie_detail(self, slug: str) -> dict | None:
        """Full detail JSON for one slug, or None on failure."""
        url = f"{self.base_url}/api/v1/movie/{urllib.parse.quote(slug)}"
        status, payload = self.get_json(url)
        if status != 200:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None


def normalize_quality(raw: str | None) -> str:
    """'480P' -> '480p'; 'PreDvD'/'WEB-DL' pass through lowercased only when
    they name a resolution, otherwise the raw label is kept as-is."""
    if not raw:
        return "unknown"
    raw = raw.strip()
    m = re.search(r"\b(2160p|1440p|1080p|720p|480p|360p|4k)\b", raw, re.I)
    if m:
        q = m.group(1).lower()
        return "2160p" if q == "4k" else q
    return raw


def season_from_slug(slug: str) -> str | None:
    """'legends-of-the-ramayana-with-amish-s1' -> 'S01'."""
    m = re.search(r"[._\- ]s(\d{1,2})$", slug, re.I)
    return f"S{int(m.group(1)):02d}" if m else None


def extract_title_data_movienestbd(detail: dict) -> dict | None:
    """Maps one /api/v1/movie/<slug> detail object to a post record.

    Series are one row per season slug (episodes is null in the API); the
    season comes from the slug suffix. Every links[] entry becomes one
    source on a single release; the main watch URL is added when it is not
    already among the links. is_adult from the API is the 18+ authority.
    """
    if not detail or not detail.get("slug") or not detail.get("title"):
        return None

    slug = detail["slug"]
    title = html.unescape(str(detail["title"]).strip())
    year = detail.get("year")
    year = int(year) if isinstance(year, (int, float)) or (isinstance(year, str) and year.isdigit()) else None
    is_series = bool(detail.get("is_series"))
    season = season_from_slug(slug) if is_series else None
    content_type = "series" if is_series else "movie"

    genres = [g.get("name") for g in (detail.get("genres") or []) if g.get("name")]
    categories = [c.get("name") for c in (detail.get("categories") or []) if c.get("name")]
    all_genres = list(dict.fromkeys(genres + [c for c in categories if c not in genres]))
    casts = detail.get("casts") or ""
    director = detail.get("director") or ""
    synopsis = html.unescape(str(detail.get("description") or "").strip()) or None

    sources: list[dict] = []
    seen_links: set[str] = set()
    for link in detail.get("links") or []:
        href = (link.get("link") or "").strip()
        if not href.startswith("http") or href in seen_links:
            continue
        seen_links.add(href)
        q = normalize_quality((link.get("quality") or {}).get("name"))
        sources.append({
            "source_name": f"MovieNestBD Watch [{q}]",
            "service": "jiofiles",
            "resource_id": href.rstrip("/").split("/")[-1],
            "source_url": href,
            "final_url": href,
            "playback_type": "url",
        })
    main_watch = (detail.get("watch") or "").strip()
    if main_watch.startswith("http") and main_watch not in seen_links:
        seen_links.add(main_watch)
        sources.append({
            "source_name": "MovieNestBD Watch",
            "service": "jiofiles",
            "resource_id": main_watch.rstrip("/").split("/")[-1],
            "source_url": main_watch,
            "final_url": main_watch,
            "playback_type": "url",
        })
    if not sources:
        return None

    quality = normalize_quality(detail.get("quality"))
    if quality in ("unknown",) and sources:
        quality = "720p"
    release_title = title
    if season:
        release_title = f"{title}"

    return {
        "url": f"{DEFAULT_BASE_URL}/api/v1/movie/{slug}",
        "slug": slug,
        "title": title,
        "clean_title": title,
        "year": year,
        "content_type": content_type,
        "seasons": season,
        "poster_url": detail.get("poster") or detail.get("cover") or None,
        "backdrop_urls": json.dumps([detail["cover"]]) if detail.get("cover") and detail.get("cover") != detail.get("poster") else None,
        "synopsis": synopsis,
        "genres": json.dumps(all_genres) if all_genres else None,
        "language": None,
        "source_site": SITE_NAME,
        "is_18_plus": 1 if detail.get("is_adult") else 0,
        "canonical_key": fast_fetch.generate_canonical_key(title, year),
        "releases": [{
            "release_title": release_title,
            "quality": quality,
            "codec": "",
            "size": "",
            "languages": "",
            "season": season,
            "episode": None,
            "intermediate_url": f"{DEFAULT_BASE_URL}/api/v1/movie/{slug}",
            "source_site": SITE_NAME,
            "sources": sources,
        }],
    }


def sync_search_to_db(client: MovieNestBDClient, db_path: Path,
                      letters: str = DEFAULT_LETTERS, limit: int | None = None) -> int:
    """Enumerates the catalog via /api/v1/search (one letter, paginated)
    and stores discovered slugs in sitemap_cache (resumable)."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    total = 0
    for letter in letters:
        page = 1
        while True:
            if STOP_REQUESTED:
                return total
            payload = client.search_page(letter, page)
            items = payload.get("data") or []
            if not items:
                break
            records = []
            for it in items:
                slug = (it.get("slug") or "").strip()
                if not slug:
                    continue
                url = f"{client.base_url}/api/v1/movie/{slug}"
                records.append((url, None, slug, 0, SITE_NAME))
            with fast_fetch._DB_WRITE_LOCK:
                with fast_fetch.get_db() as conn:
                    conn.executemany(
                        """
                        INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(loc) DO UPDATE SET
                            slug = excluded.slug,
                            site = excluded.site;
                        """,
                        records,
                    )
            total += len(records)
            if limit is not None and total >= limit:
                print(f"[*] Letter sweep capped at --limit {limit}.", flush=True)
                return total
            if not payload.get("has_next"):
                break
            page += 1
            if page > (payload.get("total_pages") or page):
                break
        print(f"[*] Letter '{letter}': swept {page} page(s).", flush=True)
    print(f"[✓] Discovered {total} title slugs.", flush=True)
    return total


def save_post_record(data: dict, db_path: Path) -> int:
    """Atomically saves a title post and marks its URL scraped."""
    fast_fetch.DB_PATH = db_path
    post_id = fast_fetch.save_scraped_data(
        data,
        enrich_metadata=False,
        ensure_db=False,
    )
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE sitemap_cache SET scraped = 1 WHERE loc = ? AND site = 'movienestbd'",
                (data["url"],),
            )
    return post_id


def run_movienestbd_scraper(
    base_url: str = DEFAULT_BASE_URL,
    db_path: Path = DEFAULT_DB_PATH,
    limit: int | None = None,
    workers: int = 3,
    delay: float = 0.5,
    letters: str = DEFAULT_LETTERS,
):
    """Worker pool orchestrator for scraping MovieNestBD titles."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    client = MovieNestBDClient(base_url, request_interval=delay)

    with fast_fetch.get_db() as conn:
        cursor = conn.execute(
            "SELECT loc FROM sitemap_cache WHERE site = 'movienestbd' AND scraped = 0 ORDER BY rowid ASC"
        )
        pending_urls = [row["loc"] for row in cursor]

    if not pending_urls:
        print("[*] No pending titles in sitemap_cache. Sweeping search first...", flush=True)
        sync_search_to_db(client, db_path, letters=letters, limit=limit)
        with fast_fetch.get_db() as conn:
            cursor = conn.execute(
                "SELECT loc FROM sitemap_cache WHERE site = 'movienestbd' AND scraped = 0 ORDER BY rowid ASC"
            )
            pending_urls = [row["loc"] for row in cursor]

    if limit is not None:
        pending_urls = pending_urls[:max(0, limit)]

    total_tasks = len(pending_urls)
    print(f"\n{'='*70}")
    print("🚀 MovieNestBD Staging Ingestion Pipeline (public JSON API, no key)")
    print(f"   Database       : {db_path.name}")
    print(f"   Pending Titles : {total_tasks:,}")
    print(f"   Workers        : {workers} | Delay: {delay}s")
    print(f"{'='*70}\n", flush=True)

    counters = {"completed": 0, "releases": 0, "sources": 0, "failed": 0,
                "start_time": time.time()}
    thread_local = threading.local()

    def get_thread_client() -> MovieNestBDClient:
        if not hasattr(thread_local, "client"):
            thread_local.client = MovieNestBDClient(base_url, request_interval=delay)
        return thread_local.client

    def process_one_url(url: str) -> dict:
        if STOP_REQUESTED:
            return {"skipped": True}
        c = get_thread_client()
        slug = url.rstrip("/").split("/")[-1]
        detail = c.movie_detail(slug)
        if not detail:
            return {"failed": True, "error": "detail fetch failed", "url": url}

        data = extract_title_data_movienestbd(detail)
        if not data or not data.get("releases"):
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
        future_map = {executor.submit(process_one_url, u): u for u in pending_urls}
        for future in concurrent.futures.as_completed(future_map):
            if STOP_REQUESTED:
                break
            try:
                res = future.result()
            except Exception as e:
                res = {"failed": True, "error": str(e)}

            if res.get("completed"):
                counters["completed"] += 1
                counters["releases"] += res.get("releases", 0)
                counters["sources"] += res.get("sources", 0)
            elif res.get("failed"):
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

    print(f"\n[✓] MovieNestBD scraping finished: {counters}", flush=True)


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
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'movienestbd' AND scraped = 1")
    scraped = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'movienestbd' AND scraped = 0")
    pending = c.fetchone()[0]
    conn.close()

    print("\n" + "=" * 55)
    print(f" 📊 MovieNestBD Staging Database Status ({db_path.name})")
    print("=" * 55)
    print(f" Catalog Titles  : {posts:,}")
    print(f" Releases Found  : {releases:,}")
    print(f" Sources Mapped  : {sources:,}")
    print(f" Scraped Titles  : {scraped:,}")
    print(f" Pending Titles  : {pending:,}")
    print("=" * 55 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="MovieNestBD Staging Importer (public JSON API)")
    parser.add_argument("--base-url", default=None, help="Base origin URL (default: registry live domain)")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite staging database")
    parser.add_argument("--sync-search", action="store_true", help="Sweep /api/v1/search into sitemap_cache")
    parser.add_argument("--letters", default=DEFAULT_LETTERS, help="Letters/digits to sweep (default: a-z0-9)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of titles to scrape")
    parser.add_argument("--workers", type=int, default=3, help="Worker threads (default: 3)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests per worker (s)")
    parser.add_argument("--status", action="store_true", help="Print database counts and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db_path).resolve()

    if args.status:
        get_status_summary(db_path)
        return

    # Session 106: an explicit --base-url wins; otherwise the registry's
    # live domain (the client's None default resolves it the same way).
    base_url = args.base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL)
    client = MovieNestBDClient(base_url, request_interval=args.delay)

    if args.sync_search:
        count = sync_search_to_db(client, db_path, letters=args.letters, limit=args.limit)
        if count == 0:
            # Empty sync: retry once on the chain's verdict, and only then.
            new_base = resolve_if_dead(SITE_NAME)
            if new_base:
                print(f"[!] MovieNestBD: sync found 0 titles and the cached domain is dead; chain found {new_base}; retrying once", flush=True)
                client = MovieNestBDClient(new_base, request_interval=args.delay)
                sync_search_to_db(client, db_path, letters=args.letters, limit=args.limit)
        return

    run_movienestbd_scraper(
        base_url=base_url,
        db_path=db_path,
        limit=args.limit,
        workers=args.workers,
        delay=args.delay,
        letters=args.letters,
    )


if __name__ == "__main__":
    main()
