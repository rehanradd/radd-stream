#!/usr/bin/env python3
"""
import_harpalgeo.py — Dedicated staging importer and scraper for HarPal Geo
(https://www.harpalgeo.tv), Geo Entertainment's official drama site.

MEASURED LIVE FROM THE ORACLE VM, 2026-11-09 (Session 118):
  * Homepage 200 (321 KB): program links /program/<Title>, 31 distinct on the
    homepage; NO .m3u8 on the homepage itself.
  * Program page /program/Bano 200 (306 KB): 12 episode links
    /program/Bano/<id>, titles carry "Episode N" + air date
    ("Bano Episode 26 | ... - 8th Nov 2026").
  * Episode page /program/Bano/26866 200 (302 KB): videojs player, <video>
    present, exactly ONE .m3u8 in the HTML, on Geo's official CDN:
    <5centscdn host>/mp4/raw/..._combined.smil/playlist.m3u8.
  * That playlist fetches 200 (830 B): valid HLS master, 720p / 480p / 240p
    variants (h264 + aac); ffprobe confirms format_name=hls. NO crack needed.
  * /sitemap.xml 307s away — there is no sitemap; the catalog surface is the
    homepage program list + each program page's episode list.
  * Teaser pages exist alongside full episodes ("Episode 26 Teaser - 7th
    November 2026") — the importer skips any episode link whose label says
    "teaser"; a teaser is not a playable episode.

Shape: one post per PROGRAM (content_type series, language Urdu, country
Pakistan), one release per full episode (E##, quality 720p — the master
playlist's top variant), one source per release: the direct .m3u8 as
final_url (playback_type "direct", service "5centscdn"), source_url the
episode page. Nothing here probes a playlist at import time beyond the
episode-page fetch; the live-play proof is the Session 118 probe above.

100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_harpalgeo.py --sync-programs           # List programs into sitemap_cache
    python Fast_Fetch/import_harpalgeo.py --limit 5                 # Scrape 5 pending programs
    python Fast_Fetch/import_harpalgeo.py --workers 3 --delay 0.5   # Full background run
    python Fast_Fetch/import_harpalgeo.py --status                  # Show current database counts
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
from domain_resolver import get_active_base_url, resolve_if_dead

DEFAULT_BASE_URL = "https://www.harpalgeo.tv"
SITE_NAME = "harpalgeo"
DEFAULT_DB_PATH = (
    Path("/home/ubuntu/radd-stream-data/harpalgeo.db")
    if Path("/home/ubuntu/radd-stream-data").exists()
    else BASE_DIR / "harpalgeo.db"
)
STATUS_FILE = BASE_DIR / "harpalgeo_status.json"

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


class HarPalGeoClient:
    """HTTP client with rate limiting and retry handling for HarPal Geo."""

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

    def get_text(self, url: str, referer: str | None = None, timeout: int = 15) -> tuple[int, str, str]:
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


# Matches /program/<Title> (program index) and /program/<Title>/<id> (episode).
PROGRAM_RE = re.compile(r'href=["\']([^"\']*/program/([A-Za-z0-9\-]+)/?)["\']', re.I)
EPISODE_RE = re.compile(r'href=["\']([^"\']*/program/([A-Za-z0-9\-]+)/(\d+)/?)["\']', re.I)
M3U8_RE = re.compile(r'https?://[^\s"\'<>]+\.m3u8(?:[^\s"\'<>]*)', re.I)
EP_NUM_RE = re.compile(r"\bEpisode\s*(\d+)\b", re.I)
AIR_DATE_RE = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2})\b",
    re.I,
)


def extract_program_links(homepage_html: str) -> list[str]:
    """All /program/<Title> links on the homepage (episode links excluded)."""
    seen: dict[str, None] = {}
    for m in PROGRAM_RE.finditer(homepage_html):
        url = m.group(1)
        # An episode link has a numeric tail; a program link does not.
        if re.search(r"/program/[A-Za-z0-9\-]+/\d+/?$", url):
            continue
        seen[urllib.parse.urljoin(DEFAULT_BASE_URL, url)] = None
    return list(seen)


def extract_episode_links(program_html: str) -> list[dict]:
    """Episode links on a program page: url + label; teasers dropped.

    The label is the anchor's own text/title where present; a link whose
    label says "teaser" is a promo, not a playable episode.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']*/program/[A-Za-z0-9\-]+/\d+/?)["\'][^>]*>(.*?)</a>',
                         program_html, re.I | re.S):
        url, inner = m.group(1), m.group(2)
        label = html.unescape(re.sub(r"<[^>]+>", "", inner).strip())
        # The "Teaser" marker usually sits on an <img> title attribute
        # INSIDE the anchor, not on the <a> itself — scan the whole anchor.
        title_attrs = " ".join(
            html.unescape(t) for t in re.findall(r'title=["\']([^"\']+)["\']', m.group(0), re.I)
        )
        full_label = f"{label} {title_attrs}".strip()
        if "teaser" in full_label.lower():
            continue
        abs_url = urllib.parse.urljoin(DEFAULT_BASE_URL, url)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append({"url": abs_url, "label": full_label})
    # Fallback: bare hrefs with no anchor text at all (JS-free pages sometimes
    # link episodes from <img> wrappers, not <a> text).
    if not out:
        for m in EPISODE_RE.finditer(program_html):
            abs_url = urllib.parse.urljoin(DEFAULT_BASE_URL, m.group(1))
            if abs_url not in seen:
                seen.add(abs_url)
                out.append({"url": abs_url, "label": ""})
    return out


def extract_episode_stream(episode_html: str) -> str | None:
    """The single direct .m3u8 on an episode page, or None."""
    found = M3U8_RE.findall(episode_html)
    if not found:
        return None
    # Prefer the 5centscdn playlist (Geo's official CDN); any .m3u8 otherwise.
    for url in found:
        if "5centscdn" in url.lower():
            return html.unescape(url)
    return html.unescape(found[0])


def parse_episode_title(episode_html: str, episode_url: str) -> dict:
    """Episode number + air date from the episode page <title>.

    Measured shape: "Bano Episode 26 | Haris Waheed ... - 8th Nov 2026 -
    Watch Online". Falls back to the URL id when the title carries no number.
    """
    m = re.search(r"<title>(.*?)</title>", episode_html, re.S | re.I)
    raw = html.unescape(m.group(1).strip()) if m else ""
    ep_m = EP_NUM_RE.search(raw)
    ep_num = int(ep_m.group(1)) if ep_m else None
    date_m = AIR_DATE_RE.search(raw)
    air_date = date_m.group(1) if date_m else None
    if ep_num is None:
        id_m = re.search(r"/(\d+)/?$", episode_url.rstrip("/"))
        ep_num = int(id_m.group(1)) if id_m else None
    return {"title": raw, "episode": ep_num, "air_date": air_date}


def extract_program_data_harpalgeo(
    program_url: str,
    program_html: str,
    episode_pages: dict[str, str],
) -> dict | None:
    """Builds one series post (one release per full episode) for a program.

    episode_pages maps episode URL -> fetched episode HTML. A program with
    no playable episode yields None (nothing to store).
    """
    slug = program_url.rstrip("/").split("/")[-1]
    program_name = urllib.parse.unquote(slug).replace("-", " ").strip()
    if not program_name:
        return None

    og_m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                     program_html, re.I)
    poster_url = og_m.group(1).strip() if og_m else None
    title_m = re.search(r"<title>(.*?)</title>", program_html, re.S | re.I)
    raw_title = html.unescape(title_m.group(1).strip()) if title_m else program_name
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    releases = []
    for ep in extract_episode_links(program_html):
        ep_html = episode_pages.get(ep["url"])
        if not ep_html:
            continue
        stream = extract_episode_stream(ep_html)
        if not stream:
            continue
        info = parse_episode_title(ep_html, ep["url"])
        ep_num = info["episode"]
        ep_code = f"E{ep_num:02d}" if isinstance(ep_num, int) else None
        releases.append({
            "release_title": f"{program_name} Episode {ep_num}" if ep_num else program_name,
            "quality": "720p",
            "codec": "x264",
            "size": "",
            "languages": "Urdu",
            "season": "S01",
            "episode": ep_code,
            "intermediate_url": ep["url"],
            "source_site": SITE_NAME,
            "air_date": info["air_date"],
            "sources": [{
                "source_name": "HarPal Geo HLS [720p]",
                "service": "5centscdn",
                "resource_id": stream.rstrip("/").split("/")[-2] if "/" in stream else stream,
                "source_url": ep["url"],
                "final_url": stream,
                "playback_type": "direct",
            }],
        })

    if not releases:
        return None
    releases.sort(key=lambda r: (r["episode"] or ""))
    years = [y for y in (parse_episode_title(episode_pages[u], u)["air_date"]
                         for u in episode_pages) if y]
    if year is None and years:
        y_m = re.search(r"20\d{2}", years[-1])
        year = int(y_m.group(0)) if y_m else None

    return {
        "url": program_url,
        "slug": slug,
        "title": program_name,
        "clean_title": program_name,
        "year": year,
        "content_type": "series",
        "seasons": "S01",
        "poster_url": poster_url,
        "backdrop_urls": None,
        "synopsis": None,
        "genres": json.dumps(["Drama"]),
        "language": "Urdu",
        "source_site": SITE_NAME,
        "is_18_plus": 0,
        "canonical_key": fast_fetch.generate_canonical_key(program_name, year),
        "releases": releases,
    }


def sync_programs_to_db(client: HarPalGeoClient, db_path: Path) -> int:
    """Fetches the homepage program list into sitemap_cache (resumable)."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    home_url = f"{client.base_url}/"
    print(f"[*] Fetching homepage program list from {home_url}...", flush=True)
    status, _, home_html = client.get_text(home_url)
    if status != 200 or not home_html:
        print(f"[!] HarPal Geo homepage HTTP {status}; 0 programs.", flush=True)
        return 0

    programs = extract_program_links(home_html)
    print(f"[✓] Discovered {len(programs)} programs.", flush=True)
    records = [
        (url, None, url.rstrip("/").split("/")[-1], 0, SITE_NAME)
        for url in programs
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
    return len(records)


def save_post_record(data: dict, db_path: Path) -> int:
    """Atomically saves a program post and marks its URL scraped."""
    fast_fetch.DB_PATH = db_path
    post_id = fast_fetch.save_scraped_data(
        data,
        enrich_metadata=False,
        ensure_db=False,
    )
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE sitemap_cache SET scraped = 1 WHERE loc = ? AND site = 'harpalgeo'",
                (data["url"],),
            )
    return post_id


def run_harpalgeo_scraper(
    base_url: str = DEFAULT_BASE_URL,
    db_path: Path = DEFAULT_DB_PATH,
    limit: int | None = None,
    workers: int = 3,
    delay: float = 0.5,
):
    """Worker pool orchestrator for scraping HarPal Geo programs."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    client = HarPalGeoClient(base_url, request_interval=delay)

    with fast_fetch.get_db() as conn:
        cursor = conn.execute(
            "SELECT loc FROM sitemap_cache WHERE site = 'harpalgeo' AND scraped = 0 ORDER BY rowid ASC"
        )
        pending_urls = [row["loc"] for row in cursor]

    if not pending_urls:
        print("[*] No pending programs in sitemap_cache. Syncing homepage first...", flush=True)
        sync_programs_to_db(client, db_path)
        with fast_fetch.get_db() as conn:
            cursor = conn.execute(
                "SELECT loc FROM sitemap_cache WHERE site = 'harpalgeo' AND scraped = 0 ORDER BY rowid ASC"
            )
            pending_urls = [row["loc"] for row in cursor]

    if limit is not None:
        pending_urls = pending_urls[:max(0, limit)]

    total_tasks = len(pending_urls)
    print(f"\n{'='*70}")
    print("🚀 HarPal Geo Staging Ingestion Pipeline (official Geo dramas, direct HLS)")
    print(f"   Database       : {db_path.name}")
    print(f"   Pending Programs: {total_tasks:,}")
    print(f"   Workers        : {workers} | Delay: {delay}s")
    print(f"{'='*70}\n", flush=True)

    counters = {"completed": 0, "releases": 0, "sources": 0, "failed": 0,
                "start_time": time.time()}
    thread_local = threading.local()

    def get_thread_client() -> HarPalGeoClient:
        if not hasattr(thread_local, "client"):
            thread_local.client = HarPalGeoClient(base_url, request_interval=delay)
        return thread_local.client

    def process_one_url(url: str) -> dict:
        if STOP_REQUESTED:
            return {"skipped": True}
        c = get_thread_client()
        code, _, prog_html = c.get_text(url)
        if code != 200 or not prog_html:
            return {"failed": True, "error": f"HTTP {code}", "url": url}

        episode_pages: dict[str, str] = {}
        for ep in extract_episode_links(prog_html):
            if STOP_REQUESTED:
                break
            e_code, _, e_html = c.get_text(ep["url"], referer=url)
            if e_code == 200 and e_html:
                episode_pages[ep["url"]] = e_html

        data = extract_program_data_harpalgeo(url, prog_html, episode_pages)
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
                    f"failed={counters['failed']} speed={speed:.2f} programs/sec",
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

    print(f"\n[✓] HarPal Geo scraping finished: {counters}", flush=True)


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
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'harpalgeo' AND scraped = 1")
    scraped = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'harpalgeo' AND scraped = 0")
    pending = c.fetchone()[0]
    conn.close()

    print("\n" + "=" * 55)
    print(f" 📊 HarPal Geo Staging Database Status ({db_path.name})")
    print("=" * 55)
    print(f" Catalog Programs: {posts:,}")
    print(f" Releases Found  : {releases:,}")
    print(f" Sources Mapped  : {sources:,}")
    print(f" Scraped Programs: {scraped:,}")
    print(f" Pending Programs: {pending:,}")
    print("=" * 55 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="HarPal Geo Staging Importer (official Geo dramas)")
    parser.add_argument("--base-url", default=None, help="Base origin URL (default: registry live domain)")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite staging database")
    parser.add_argument("--sync-programs", action="store_true", help="Sync the homepage program list to the database")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of programs to scrape")
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
    client = HarPalGeoClient(base_url, request_interval=args.delay)

    if args.sync_programs:
        count = sync_programs_to_db(client, db_path)
        if count == 0:
            # Empty sync: retry once on the chain's verdict, and only then.
            new_base = resolve_if_dead(SITE_NAME)
            if new_base:
                print(f"[!] HarPal Geo: sync found 0 programs and the cached domain is dead; chain found {new_base}; retrying once", flush=True)
                client = HarPalGeoClient(new_base, request_interval=args.delay)
                sync_programs_to_db(client, db_path)
        return

    run_harpalgeo_scraper(
        base_url=base_url,
        db_path=db_path,
        limit=args.limit,
        workers=args.workers,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
