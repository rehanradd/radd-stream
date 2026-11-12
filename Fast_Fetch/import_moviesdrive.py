#!/usr/bin/env python3
"""
import_moviesdrive.py — Dedicated staging importer and scraper for MoviesDrive
(https://new3.moviesdrive.cyou), WordPress download catalog (Bollywood,
Hollywood Hindi-dubbed, South, web series; 480p–2160p/4K, ESub).

MEASURED LIVE FROM THE ORACLE VM, 2026-11-09 (Session 118):
  * GET /wp-json/wp/v2/posts?per_page=3 200 (34 KB): full post objects with
    title.rendered, slug, link, content.rendered (full HTML).
  * Post content carries 4 mdrive.lol/archive/<id>/ links (one per quality)
    plus noise: mirror links (moviesdrives.bid), t.me, imdb.com — the
    importer keeps ONLY mdrive.lol/archive/<id>/ links.
  * GET https://mdrive.lol/archive/25388/ 200 (36 KB): the archive page is
    itself a WP post; its <title> carries quality + size ("WWE Crown Jewel
    (2026) WEB-DL [Hindi (DD2.0) & English] 480p x264 [658.47 MB]") and its
    body links the file host: hubcloud.ist/drive/... (HubCloud, known family,
    current domain) and, on other posts, gdflix.vip/file/... (GDFlix).
  * Mirrors seen in discovery: moviesdrives.cfd/.bid, moviedrive.org,
    new4.moviesdrive.beer — the registry tracks them; the importer reads the
    live base from the registry like the other 19 sites. Domain rotated
    new1 -> new2 on 2026-11-10, then new2 -> new3 on 2026-11-12 (verified
    2026-11-13: new2 302s to new3 and DROPS the query string, so a stale
    base breaks wp-json paging — the registry, not the fallback, must carry
    the live base). A redirect that drops the query makes wp-json answer its
    default latest-posts list; the slug lookup below VERIFIES the returned
    post's slug before any save, and retries once against the live host the
    returned post links — taking found[0] unchecked once saved the site's
    newest post (Jailer 2) for 104 tasks in a row.

Shape: one post per WP post (title/year via fast_fetch.parse_post_metadata
on the WP title), one release per mdrive archive link (quality/size/codec
from the archive page title), one source per file-host anchor on the archive
page (service hubcloud/gdflix, playback_type "download", final_url the
anchor as-is — the resolver unwraps HubCloud/GDFlix at play time; neither
host is re-proven here, the archive page is the evidence the link exists).

100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_moviesdrive.py --sync-posts             # Sync wp-json post list
    python Fast_Fetch/import_moviesdrive.py --limit 10               # Scrape 10 pending posts
    python Fast_Fetch/import_moviesdrive.py --workers 3 --delay 0.5 # Full background run
    python Fast_Fetch/import_moviesdrive.py --status                 # Show current database counts
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
from config import staging_db_path
from domain_resolver import get_active_base_url, resolve_if_dead, update_site_registry

DEFAULT_BASE_URL = "https://new3.moviesdrive.cyou"
SITE_NAME = "moviesdrive"
DEFAULT_DB_PATH = staging_db_path("moviesdrive")
STATUS_FILE = BASE_DIR / "moviesdrive_status.json"
WP_PER_PAGE = 100

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


class MoviesDriveClient:
    """HTTP client with rate limiting and retry handling for MoviesDrive."""

    def __init__(self, base_url: str | None = None, request_interval: float = 0.3, retries: int = 3):
        # Session 106: the registry is the source of truth for the
        # live domain; an explicit base_url (CLI --base-url) still wins.
        self.base_url = (base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL)).rstrip("/")
        self.request_interval = max(0.0, request_interval)
        self.retries = max(1, retries)
        self.ssl_ctx = get_ssl_context()
        self._next_request_at = 0.0
        self._lock = threading.Lock()
        # Final URL after redirects, from the last request (urllib follows
        # 302s silently): the diagnostic that proves a stale base, since a
        # rotation redirect drops the query string.
        self.last_final_url: str | None = None

    def _wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next_request_at:
                time.sleep(self._next_request_at - now)
            self._next_request_at = time.monotonic() + self.request_interval

    def _get(self, url: str, accept: str, timeout: int = 20) -> tuple[int, dict, str]:
        """One GET. Returns (status, headers dict, body text)."""
        headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(self.retries):
            self._wait()
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_ctx) as resp:
                    self.last_final_url = resp.geturl()
                    return resp.status, dict(resp.headers), resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                try:
                    self.last_final_url = e.geturl()
                except Exception:
                    pass
                if attempt == self.retries - 1:
                    return e.code, dict(e.headers), ""
                time.sleep(1.0)
            except Exception:
                if attempt == self.retries - 1:
                    return 0, {}, ""
                time.sleep(1.0)
        return 0, {}, ""

    def get_text(self, url: str, referer: str | None = None, timeout: int = 20) -> tuple[int, str, str]:
        status, _, text = self._get(url, "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", timeout)
        return status, url, text


def _host_of_url(url: str | None) -> str:
    """Lowercased host of a URL, or '' when it has none."""
    if not url:
        return ""
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def lookup_post_by_slug(client: MoviesDriveClient, slug: str) -> tuple[dict | None, str | None, str | None]:
    """Fetch one WP post by slug and verify the answer really is that slug.

    Returns (post, error, returned_link). Exactly one of post/error is set.
    returned_link is the link of the post wp-json answered with, when any —
    on a slug mismatch it names the live host, which is the evidence a
    domain rotation (not a missing post) caused the mismatch.

    A redirect that drops the query string makes wp-json answer its default
    latest-posts list instead of the requested slug; taking found[0] unchecked
    then saves the site's newest post for every task (2026-11-12: 104 tasks
    all saved Jailer 2). Never trust found[0] here.
    """
    status, _, body = client._get(
        f"{client.base_url}/wp-json/wp/v2/posts?slug={urllib.parse.quote(slug)}",
        "application/json, */*;q=0.8",
    )
    if status != 200 or not body:
        return None, f"wp-json slug lookup failed (HTTP {status})", None
    try:
        found = json.loads(body)
    except json.JSONDecodeError:
        return None, "wp-json slug lookup returned unparsable JSON", None
    if not isinstance(found, list) or not found:
        return None, "post not found in wp-json", None
    post = found[0]
    got_slug = (post.get("slug") or "")
    if got_slug != slug:
        return None, (
            f"slug mismatch: asked {slug}, wp-json returned "
            f"{got_slug or post.get('link') or 'an unslugged post'}"
        ), (post.get("link") or "")
    return post, None, (post.get("link") or "")


def fetch_post_for_pending_url(
    client: MoviesDriveClient,
    slug: str,
    *,
    client_factory=None,
    registry_updater=None,
) -> tuple[dict | None, str | None]:
    """Slug lookup with one bounded retry when the base has rotated.

    Returns (post, error). On a slug mismatch, the post wp-json answered
    with links the live host, so the lookup is retried once against that
    host; a retry that also mismatches fails loudly. A successful retry
    updates the registry (best-effort) so the next run starts on the live
    base instead of paying a failed lookup per task.
    """
    post, error, returned_link = lookup_post_by_slug(client, slug)
    if post is not None:
        return post, None
    if error is None or not error.startswith("slug mismatch"):
        return None, error
    hint_host = _host_of_url(returned_link)
    base_host = _host_of_url(client.base_url)
    if not hint_host or hint_host == base_host:
        return None, error
    factory = client_factory or MoviesDriveClient
    retry_client = factory(f"https://{hint_host}", request_interval=client.request_interval)
    post2, error2, _ = lookup_post_by_slug(retry_client, slug)
    if post2 is None:
        return None, f"{error}; retry on {hint_host} also failed: {error2}"
    updater = registry_updater or update_site_registry
    try:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        updater(SITE_NAME, {
            "active_base_url": f"https://{hint_host}",
            "last_verified": now,
            "verified_by": "wp-json",
            "status": "active",
            "last_checked": now,
            "known_mirrors": [f"https://{hint_host}"],
        })
    except Exception:
        pass
    return post2, None

    def wp_posts_page(self, page: int = 1, per_page: int = WP_PER_PAGE) -> tuple[list, int]:
        """One wp-json posts page: (posts, total_pages from X-WP-TotalPages)."""
        url = (
            f"{self.base_url}/wp-json/wp/v2/posts"
            f"?per_page={per_page}&page={page}&_fields=id,slug,link,title,content,date"
        )
        status, headers, body = self._get(url, "application/json, */*;q=0.8")
        if status != 200 or not body:
            return [], 0
        try:
            posts = json.loads(body)
        except json.JSONDecodeError:
            return [], 0
        if not isinstance(posts, list):
            return [], 0
        try:
            total_pages = int(headers.get("X-WP-TotalPages", "1"))
        except ValueError:
            total_pages = 1
        return posts, total_pages


ARCHIVE_RE = re.compile(r"https?://mdrive\.lol/archive/(\d+)/?", re.I)
FILE_HOST_RES = (
    re.compile(r"hubcloud\.", re.I),
    re.compile(r"gdflix\.", re.I),
)
NOISE_RES = (
    re.compile(r"t\.me/", re.I),
    re.compile(r"imdb\.com", re.I),
    re.compile(r"moviesdrive", re.I),
    re.compile(r"mdrive\.lol", re.I),
)
LANG_WORDS = ("hindi", "english", "tamil", "telugu", "malayalam", "kannada",
              "punjabi", "bengali", "marathi", "gujarati", "urdu")


def extract_archive_links(post_content_html: str) -> list[str]:
    """Only the mdrive.lol/archive/<id>/ links in a WP post's content.

    Mirror links, Telegram, IMDb and the site's own domain are noise and are
    dropped here, not stored.
    """
    seen: dict[str, None] = {}
    for m in ARCHIVE_RE.finditer(post_content_html):
        url = f"https://mdrive.lol/archive/{m.group(1)}/"
        seen[url] = None
    return list(seen)


def extract_archive_sources(archive_html: str) -> list[dict]:
    """File-host anchors on an mdrive archive page (hubcloud / gdflix).

    Every other anchor (navigation, mirrors, Telegram, the archive itself)
    is noise. Returns one source dict per file-host anchor.
    """
    sources: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         archive_html, re.I | re.S):
        href = html.unescape(m.group(1).strip())
        if not href.startswith("http") or href in seen:
            continue
        host = urllib.parse.urlparse(href).netloc.lower()
        if not any(p.search(host) for p in FILE_HOST_RES):
            continue
        if any(p.search(href) for p in NOISE_RES):
            continue
        seen.add(href)
        service = "hubcloud" if "hubcloud" in host else "gdflix"
        label = html.unescape(re.sub(r"<[^>]+>", "", m.group(2)).strip())
        sources.append({
            "source_name": label or f"{service.title()} Download",
            "service": service,
            "resource_id": href.rstrip("/").split("/")[-1],
            "source_url": href,
            "final_url": href,
            "playback_type": "download",
        })
    return sources


def languages_from_title(title: str) -> str:
    """'Hindi', 'Hindi + English', ... from the words present in a title."""
    found = [w.title() for w in LANG_WORDS if re.search(rf"\b{w}\b", title, re.I)]
    return " + ".join(found)


def extract_post_data_moviesdrive(
    post: dict,
    archive_pages: dict[str, str],
) -> dict | None:
    """Builds one post record from a wp-json post + its archive pages.

    archive_pages maps archive URL -> fetched archive HTML. A post with no
    archive link, or whose archives carry no file-host anchor, yields None.
    """
    link = (post.get("link") or "").strip()
    title_obj = post.get("title") or {}
    raw_title = html.unescape(str(title_obj.get("rendered") or "").strip())
    if not link or not raw_title:
        return None

    # Reuse the shared title parser on the WP title (year, content type,
    # clean title, seasons); the source_site is then asserted to this site.
    meta = fast_fetch.parse_post_metadata(
        link, f"<title>{html.escape(raw_title)}</title>"
    )
    clean_title = meta["clean_title"]
    year = meta["year"]
    content_type = meta["content_type"]
    seasons = meta["seasons"]

    content_html = ((post.get("content") or {}).get("rendered") or "")
    archive_links = extract_archive_links(content_html)
    if not archive_links:
        return None

    languages = languages_from_title(raw_title)
    releases = []
    for arch_url in archive_links:
        arch_html = archive_pages.get(arch_url)
        if not arch_html:
            continue
        sources = extract_archive_sources(arch_html)
        if not sources:
            continue
        title_m = re.search(r"<title>(.*?)</title>", arch_html, re.S | re.I)
        arch_title = html.unescape(title_m.group(1).strip()) if title_m else raw_title
        rel = fast_fetch.parse_release_info(arch_title)
        rel["intermediate_url"] = arch_url
        rel["source_site"] = SITE_NAME
        rel["languages"] = languages or rel.get("languages", "")
        rel["sources"] = sources
        releases.append(rel)

    if not releases:
        return None

    return {
        "url": link,
        "slug": post.get("slug") or link.rstrip("/").split("/")[-1],
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": content_type,
        "seasons": seasons,
        "poster_url": meta.get("poster_url"),
        "backdrop_urls": meta.get("backdrop_urls"),
        "synopsis": meta.get("synopsis"),
        "genres": meta.get("genres"),
        "language": languages or meta.get("language"),
        "source_site": SITE_NAME,
        "is_18_plus": meta.get("is_18_plus", 0),
        "canonical_key": fast_fetch.generate_canonical_key(clean_title, year),
        "releases": releases,
    }


def sync_posts_to_db(client: MoviesDriveClient, db_path: Path) -> int:
    """Walks the wp-json post list into sitemap_cache (resumable)."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    total = 0
    page = 1
    total_pages = 1
    while page <= total_pages:
        posts, total_pages = client.wp_posts_page(page)
        if not posts:
            break
        records = [
            (p["link"], None, p.get("slug") or p["link"].rstrip("/").split("/")[-1], 0, SITE_NAME)
            for p in posts if p.get("link")
        ]
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
        print(f"[*] wp-json page {page}/{total_pages}: {len(records)} posts.", flush=True)
        page += 1
        if STOP_REQUESTED:
            break
    print(f"[✓] Discovered {total} posts.", flush=True)
    return total


def save_post_record(data: dict, db_path: Path, queue_loc: str | None = None) -> int:
    """Atomically saves a post and marks its queue row scraped.

    queue_loc is the sitemap_cache loc that queued this page — the row to
    mark. It is NOT necessarily data["url"]: a domain rotation makes the
    fetched URL live on the new host while the queue row still carries the
    old host, so marking by fetched URL leaves the queue row pending forever
    (MoviesDrive, 2026-11-12). Defaults to data["url"] when the caller does
    not know the queue loc.
    """
    fast_fetch.DB_PATH = db_path
    post_id = fast_fetch.save_scraped_data(
        data,
        enrich_metadata=False,
        ensure_db=False,
        queue_loc=queue_loc,
    )
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE sitemap_cache SET scraped = 1 WHERE loc = ? AND site = 'moviesdrive'",
                (queue_loc or data["url"],),
            )
    return post_id


def dedupe_duplicate_releases(db_path: Path) -> dict:
    """Delete older-domain duplicate releases left by past rotations.

    Prior rotations (new1 -> new2) left 60 (post_id, release_title) pairs
    carrying 2 distinct origin_urls across 15 posts: the refresh DELETE then
    keyed on the exact origin_url, so a re-save from the new domain INSERTed
    a second copy instead of replacing the first. For each such group, keep
    the newest row (highest id) and delete the rest, with their sources.
    Only runs when the operator passes --dedupe-releases; scraping never
    mutates history on its own.
    """
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()
    stats = {"groups": 0, "releases_deleted": 0, "sources_deleted": 0}
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            groups = conn.execute(
                """
                SELECT post_id, release_title, COUNT(*) AS n,
                       COUNT(DISTINCT origin_url) AS hosts, MAX(id) AS keep_id
                FROM releases
                WHERE source_site = 'moviesdrive'
                GROUP BY post_id, release_title
                HAVING n > 1 AND hosts > 1
                """
            ).fetchall()
            for post_id, release_title, _n, _hosts, keep_id in groups:
                doomed = conn.execute(
                    "SELECT id FROM releases WHERE post_id = ? AND release_title = ? AND id != ?",
                    (post_id, release_title, keep_id),
                ).fetchall()
                doomed_ids = [r[0] for r in doomed]
                if not doomed_ids:
                    continue
                stats["groups"] += 1
                placeholders = ",".join("?" * len(doomed_ids))
                stats["sources_deleted"] += conn.execute(
                    f"DELETE FROM download_sources WHERE release_id IN ({placeholders})",
                    doomed_ids,
                ).rowcount
                stats["releases_deleted"] += conn.execute(
                    f"DELETE FROM releases WHERE id IN ({placeholders})",
                    doomed_ids,
                ).rowcount
    return stats


def run_moviesdrive_scraper(
    base_url: str = DEFAULT_BASE_URL,
    db_path: Path = DEFAULT_DB_PATH,
    limit: int | None = None,
    workers: int = 3,
    delay: float = 0.5,
):
    """Worker pool orchestrator for scraping MoviesDrive posts."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    client = MoviesDriveClient(base_url, request_interval=delay)

    with fast_fetch.get_db() as conn:
        cursor = conn.execute(
            "SELECT loc FROM sitemap_cache WHERE site = 'moviesdrive' AND scraped = 0 ORDER BY rowid ASC"
        )
        pending_urls = [row["loc"] for row in cursor]

    if not pending_urls:
        print("[*] No pending posts in sitemap_cache. Syncing wp-json first...", flush=True)
        sync_posts_to_db(client, db_path)
        with fast_fetch.get_db() as conn:
            cursor = conn.execute(
                "SELECT loc FROM sitemap_cache WHERE site = 'moviesdrive' AND scraped = 0 ORDER BY rowid ASC"
            )
            pending_urls = [row["loc"] for row in cursor]

    if limit is not None:
        pending_urls = pending_urls[:max(0, limit)]

    total_tasks = len(pending_urls)
    print(f"\n{'='*70}")
    print("🚀 MoviesDrive Staging Ingestion Pipeline (wp-json -> mdrive archive -> file host)")
    print(f"   Database       : {db_path.name}")
    print(f"   Pending Posts  : {total_tasks:,}")
    print(f"   Workers        : {workers} | Delay: {delay}s")
    print(f"{'='*70}\n", flush=True)

    counters = {"completed": 0, "releases": 0, "sources": 0, "failed": 0,
                "start_time": time.time()}
    # Distinct posts actually written. The old counters counted
    # len(data["releases"]) per task, which looked healthy (54 completed /
    # 540 releases) while 104 tasks had all overwritten one row.
    distinct_post_ids: set[int] = set()
    thread_local = threading.local()

    def get_thread_client() -> MoviesDriveClient:
        if not hasattr(thread_local, "client"):
            thread_local.client = MoviesDriveClient(base_url, request_interval=delay)
        return thread_local.client

    def process_one_url(url: str) -> dict:
        if STOP_REQUESTED:
            return {"skipped": True}
        c = get_thread_client()
        # The WP post is re-read by slug from wp-json (one post per call);
        # the slug is the last path segment of the pending URL.
        slug = url.rstrip("/").split("/")[-1]
        post, error = fetch_post_for_pending_url(c, slug)
        if post is None:
            return {"failed": True, "error": error or "post not found in wp-json", "url": url}

        content_html = ((post.get("content") or {}).get("rendered") or "")
        archive_links = extract_archive_links(content_html)
        archive_pages: dict[str, str] = {}
        for arch_url in archive_links:
            if STOP_REQUESTED:
                break
            a_code, _, a_html = c.get_text(arch_url, referer=url)
            if a_code == 200 and a_html:
                archive_pages[arch_url] = a_html

        data = extract_post_data_moviesdrive(post, archive_pages)
        if not data or not data.get("releases"):
            with fast_fetch._DB_WRITE_LOCK:
                with fast_fetch.get_db() as conn:
                    conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ?", (url,))
            return {"skipped": True, "reason": "no_releases"}

        post_id = save_post_record(data, db_path, queue_loc=url)
        return {
            "completed": True,
            "post_id": post_id,
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
                if res.get("post_id"):
                    distinct_post_ids.add(res["post_id"])
            elif res.get("failed"):
                counters["failed"] += 1

            if counters["completed"] % 10 == 0 or counters["completed"] == total_tasks:
                elapsed = time.time() - counters["start_time"]
                speed = counters["completed"] / max(1, elapsed)
                print(
                    f"[{counters['completed']}/{total_tasks}] "
                    f"posts={len(distinct_post_ids)} "
                    f"releases={counters['releases']} sources={counters['sources']} "
                    f"failed={counters['failed']} speed={speed:.2f} posts/sec",
                    flush=True,
                )
                try:
                    with open(STATUS_FILE, "w", encoding="utf-8") as sf:
                        json.dump({
                            "completed": counters["completed"],
                            "distinct_posts": len(distinct_post_ids),
                            "total": total_tasks,
                            "releases": counters["releases"],
                            "sources": counters["sources"],
                            "failed": counters["failed"],
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }, sf, indent=2)
                except Exception:
                    pass

    counters["distinct_posts"] = len(distinct_post_ids)
    print(f"\n[✓] MoviesDrive scraping finished: {counters}", flush=True)


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
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'moviesdrive' AND scraped = 1")
    scraped = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'moviesdrive' AND scraped = 0")
    pending = c.fetchone()[0]
    conn.close()

    print("\n" + "=" * 55)
    print(f" 📊 MoviesDrive Staging Database Status ({db_path.name})")
    print("=" * 55)
    print(f" Catalog Posts   : {posts:,}")
    print(f" Releases Found  : {releases:,}")
    print(f" Sources Mapped  : {sources:,}")
    print(f" Scraped Posts   : {scraped:,}")
    print(f" Pending Posts   : {pending:,}")
    print("=" * 55 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="MoviesDrive Staging Importer (wp-json)")
    parser.add_argument("--base-url", default=None, help="Base origin URL (default: registry live domain)")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite staging database")
    parser.add_argument("--sync-posts", action="store_true", help="Sync the wp-json post list to the database")
    parser.add_argument("--dedupe-releases", action="store_true",
                        help="Delete older-domain duplicate releases left by past rotations, then exit")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of posts to scrape")
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

    if args.dedupe_releases:
        stats = dedupe_duplicate_releases(db_path)
        print(f"[✓] MoviesDrive release dedupe: {stats}", flush=True)
        return

    # Session 106: an explicit --base-url wins; otherwise the registry's
    # live domain (the client's None default resolves it the same way).
    base_url = args.base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL)
    client = MoviesDriveClient(base_url, request_interval=args.delay)

    if args.sync_posts:
        count = sync_posts_to_db(client, db_path)
        if count == 0:
            # Empty sync: retry once on the chain's verdict, and only then.
            new_base = resolve_if_dead(SITE_NAME)
            if new_base:
                print(f"[!] MoviesDrive: sync found 0 posts and the cached domain is dead; chain found {new_base}; retrying once", flush=True)
                client = MoviesDriveClient(new_base, request_interval=args.delay)
                sync_posts_to_db(client, db_path)
        return

    run_moviesdrive_scraper(
        base_url=base_url,
        db_path=db_path,
        limit=args.limit,
        workers=args.workers,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
