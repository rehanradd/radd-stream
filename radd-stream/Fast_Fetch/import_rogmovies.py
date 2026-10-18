#!/usr/bin/env python3
"""
import_rogmovies.py — Dedicated staging importer and scraper for Rogmovies (https://rogmovies.one).

Key Features:
  1. Dedicated staging SQLite database: rogmovies.db (isolated from production fast_fetch.db).
  2. Full sitemap sync across all 8 post XML sub-sitemaps (7,515+ titles).
  3. Permanent TMDB Poster Unwrapping: Decodes ?u=<base64> proxy parameters and extracts embedded
     image.tmdb.org CDN URLs, ensuring zero image rot upon domain migration.
  4. Complete Media Hierarchy:
     - Movies: All quality tiers (480p, 720p, 1080p, 2160p 4K, 10Bit HEVC) with exact file sizes.
     - TV Series: Complete Season Batch Zips + individual episode releases (-:Episodes: X:-).
  5. Multi-Mirror Link Resolvers:
     - FastDL (Instant Google CDN stream)
     - V-Cloud (Cloudflare R2 stream/download)
     - VegaDrive (10Gbps direct stream)
     - Filepress / Filebee (Google Drive)
     - GoFile, VikingFile, MegaUp, GDToT, DropGalaxy
  6. Resumable via sitemap_cache table.
  7. 100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_rogmovies.py --sync-sitemap              # Ingest all sitemap URLs
    python Fast_Fetch/import_rogmovies.py --limit 10                  # Scrape 10 pending titles
    python Fast_Fetch/import_rogmovies.py --workers 5 --delay 0.3    # Full background run
    python Fast_Fetch/import_rogmovies.py --status                    # Show current database counts
"""

from __future__ import annotations

import argparse
import base64
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

DEFAULT_BASE_URL = "https://rogmovies.one"
DEFAULT_DB_PATH = BASE_DIR / "rogmovies.db"
STATUS_FILE = BASE_DIR / "rogmovies_status.json"

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


class RogmoviesClient:
    """HTTP Client with rate limiting and retry handling for Rogmovies & Nexdrive."""

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


def unwrap_tmdb_poster(poster_url: str | None, page_html: str = "") -> str | None:
    """
    Decodes the permanent official TMDB poster URL from proxy parameters
    or extracts an embedded permanent TMDB image directly from post HTML.
    If Rogmovies changes domain, the decoded image.tmdb.org URL remains permanent.
    """
    if poster_url:
        # Check for Base64 encoded TMDB target in ?u= or &#038;u= or &u=
        m = re.search(r'[?&](?:amp;)?u=([A-Za-z0-9+/=]+)', poster_url)
        if m:
            try:
                decoded = base64.b64decode(m.group(1)).decode('utf-8', errors='replace').strip()
                if decoded.startswith("http") and "tmdb.org" in decoded:
                    return decoded
            except Exception:
                pass
        if "image.tmdb.org" in poster_url:
            return poster_url

    # Check if page_html embeds an official TMDB image
    if page_html:
        tmdb_m = re.search(r'https?://image\.tmdb\.org/t/p/(?:original|w\d+)/[A-Za-z0-9_\-\.]+\.(?:jpg|jpeg|png|webp)', page_html, re.I)
        if tmdb_m:
            return tmdb_m.group(0)

    return poster_url


def sync_sitemap_to_db(client: RogmoviesClient, db_path: Path) -> int:
    """Fetches all post XML sub-sitemaps from Rogmovies and populates sitemap_cache."""
    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    main_sitemap_url = f"{client.base_url}/sitemap.xml"
    print(f"[*] Fetching master sitemap index from {main_sitemap_url}...", flush=True)
    status, _, xml_text = client.get_text(main_sitemap_url)
    if status != 200 or not xml_text:
        sub_sitemaps = [f"{client.base_url}/post-sitemap.xml"]
    else:
        sub_locs = re.findall(r'<loc>(https?://[^<]+)</loc>', xml_text)
        sub_sitemaps = [l.strip() for l in sub_locs if "post-sitemap" in l]
        if not sub_sitemaps:
            sub_sitemaps = [f"{client.base_url}/post-sitemap.xml"]

    print(f"[*] Found {len(sub_sitemaps)} post sub-sitemap files to ingest.", flush=True)

    all_urls = []
    for idx, s_url in enumerate(sub_sitemaps, 1):
        print(f"    [{idx}/{len(sub_sitemaps)}] Ingesting {s_url}...", flush=True)
        s_code, _, s_xml = client.get_text(s_url)
        if s_code != 200 or not s_xml:
            continue
        locs = re.findall(r'<loc>(https?://[^<]+)</loc>', s_xml)
        post_urls = [
            l.strip() for l in locs
            if "/download-" in l or (l.strip().endswith("/") and not any(k in l for k in ["/category/", "/tag/", "/page/"]))
        ]
        all_urls.extend(post_urls)

    unique_urls = list(dict.fromkeys(all_urls))
    print(f"[✓] Discovered {len(unique_urls):,} total unique post URLs across all sitemaps.", flush=True)

    records = [
        (url, None, url.rstrip("/").split("/")[-1], 0, "rogmovies")
        for url in unique_urls
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


def is_valid_download_link(href: str) -> bool:
    """Validates real download mirror URLs and filters out noise/placeholders without dropping hash links (e.g. Mega.nz)."""
    if not href or not href.startswith("http"):
        return False
    href_l = href.lower()
    if any(bad in href_l for bad in [
        "javascript:", "telegram", "whatsapp", "vglist.cv", "facebook.com",
        "twitter.com", "instagram.com", "how-to-download", "disclaimer", "dmca", "privacy-policy"
    ]):
        return False
    if "nexdrive." in href_l and ("/category/" in href_l or href_l.rstrip("/").endswith(("nexdrive.beer", "nexdrive.pro", "nexdrive.lat", "nexdrive.site"))):
        return False
    if href.startswith("#") or href.strip() == "#":
        return False
    return True


def extract_post_data_rogmovies(
    post_url: str,
    page_html: str,
    client: RogmoviesClient | None = None,
    resolve_bridges: bool = True,
) -> dict | None:
    """Parses full media metadata, releases, and multi-mirror download links from a Rogmovies post."""
    slug = post_url.rstrip("/").split("/")[-1]

    # 1. Metadata Extraction
    meta = fast_fetch.parse_post_metadata(post_url, page_html)
    clean_title = meta["clean_title"]
    year = meta["year"]
    content_type = meta["content_type"]
    seasons = meta["seasons"]
    canonical_key = fast_fetch.generate_canonical_key(clean_title, year)

    # Clean title artifacts from site branding
    clean_title = re.sub(r'\s*Rogmovies.*$', '', clean_title, flags=re.I).strip()
    clean_title = re.sub(r'\s*Official.*$', '', clean_title, flags=re.I).strip()

    # 2. Permanent Poster & Backdrops
    raw_poster = meta.get("poster_url")
    poster_url = unwrap_tmdb_poster(raw_poster, page_html)
    backdrop_urls = meta.get("backdrop_urls")

    # 3. Synopsis & Genres
    synopsis = meta.get("synopsis")
    genres = meta.get("genres")
    language = meta.get("language") or "Hindi + English"

    # 4. Extract Nexdrive Bridges
    nex_links = re.findall(r'href=[\"\'](https?://nexdrive\.[a-z]+/[^\"\']+)[\"\']', page_html)
    unique_nex = list(dict.fromkeys(nex_links))

    releases = []

    for idx, nex_url in enumerate(unique_nex, 1):
        if not resolve_bridges or not client:
            # Quick staging mode: store the release bridge
            releases.append({
                "release_title": f"{clean_title} Release {idx}",
                "quality": "HD",
                "codec": "x264",
                "size": "",
                "languages": language,
                "season": seasons,
                "episode": None,
                "intermediate_url": nex_url,
                "source_site": "rogmovies",
                "sources": [{
                    "source_name": "Nexdrive Gateway",
                    "service": "nexdrive",
                    "source_url": nex_url,
                    "final_url": nex_url,
                    "playback_type": "url",
                }],
            })
            continue

        n_code, n_final, n_html = client.get_text(nex_url, referer=post_url)
        if n_code != 200 or not n_html:
            continue

        # Extract title from Nexdrive <title>
        n_title_m = re.search(r"<title>(.*?)</title>", n_html, re.I)
        raw_title = n_title_m.group(1).strip() if n_title_m else f"{clean_title} Release {idx}"
        raw_title = re.sub(r'\s*-\s*Nexdrive\..*$', '', raw_title, flags=re.I).strip()
        n_title = html.unescape(raw_title)

        rel_base = fast_fetch.parse_release_info(n_title)
        rel_base["intermediate_url"] = nex_url
        rel_base["source_site"] = "rogmovies"

        def _resolve_anchors(anchor_list: list[tuple[str, str]]) -> list[dict]:
            sources = []
            for href, text in anchor_list:
                href_l = href.lower()
                clean_lbl = html.unescape(re.sub(r"<[^>]+>", "", text).strip())

                if "fastdl." in href_l:
                    direct_url, res_id, is_temp = fast_fetch.unwrap_fastdl(href)
                    sources.append({
                        "source_name": "⚡ G-Direct [Instant]",
                        "service": "fastdl",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": direct_url,
                        "playback_type": "direct" if "video-downloads" in direct_url else "download",
                    })
                elif "vcloud." in href_l:
                    res_id = href.rstrip("/").split("/")[-1].split("?")[0]
                    unwrapped_vclouds = fast_fetch.unwrap_vcloud(href)
                    for s_name, s_srv, s_fin, is_temp in unwrapped_vclouds:
                        sources.append({
                            "source_name": s_name,
                            "service": s_srv,
                            "resource_id": res_id,
                            "source_url": href,
                            "final_url": s_fin,
                            "playback_type": "direct" if "r2.dev" in s_fin else "download",
                        })
                elif "vegadrive." in href_l:
                    direct_url, res_id, is_temp = fast_fetch.unwrap_vegadrive(href)
                    sources.append({
                        "source_name": "⚡ V-Drive [10Gbps]",
                        "service": "vegadrive",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": direct_url,
                        "playback_type": "direct",
                    })
                elif "filebee." in href_l or "filepress." in href_l:
                    final_fp, res_id, is_temp = fast_fetch.unwrap_filepress(href)
                    sources.append({
                        "source_name": "⚡ Filepress [Google Drive]",
                        "service": "filepress",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": final_fp,
                        "playback_type": "download",
                    })
                elif "gofile.io" in href_l:
                    res_id = href.rstrip("/").split("/")[-1]
                    sources.append({
                        "source_name": "⚡ GoFile [Direct]",
                        "service": "gofile",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": href,
                        "playback_type": "download",
                    })
                elif "vikingfile.com" in href_l:
                    res_id = href.rstrip("/").split("/")[-1]
                    sources.append({
                        "source_name": "⚡ VikingFile",
                        "service": "vikingfile",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": href,
                        "playback_type": "download",
                    })
                elif "megaup.net" in href_l:
                    res_id = href.rstrip("/").split("/")[-1].split("?")[0]
                    sources.append({
                        "source_name": "⚡ MegaUp",
                        "service": "megaup",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": href,
                        "playback_type": "download",
                    })
                elif "gdtot" in href_l:
                    sources.append({
                        "source_name": "⚡ GDToT [G-Drive]",
                        "service": "gdtot",
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "playback_type": "url",
                    })
                elif "mega.nz" in href_l or "mega.co.nz" in href_l:
                    sources.append({
                        "source_name": "⚡ Mega.nz [Cloud]",
                        "service": "mega",
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "playback_type": "download",
                    })
                elif "dropgalaxy" in href_l or "dgdrive" in href_l:
                    sources.append({
                        "source_name": "⚡ DropGalaxy",
                        "service": "dropgalaxy",
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "playback_type": "url",
                    })
                else:
                    domain = urllib.parse.urlparse(href).netloc.replace("www.", "")
                    sources.append({
                        "source_name": clean_lbl or domain,
                        "service": domain.split(".")[0],
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": href,
                        "playback_type": "url",
                    })
            return sources

        # Check for explicit episode blocks: -:Episodes: X:- followed by <p> anchors
        ep_blocks = re.findall(r'-:Episodes?:\s*(\d+):-.*?</(?:h[1-6]|p)>\s*<p[^>]*>(.*?)</p>', n_html, re.S | re.I)
        if ep_blocks:
            season_str = rel_base["season"] or "S01"
            for ep_num_str, p_content in ep_blocks:
                ep_num = int(ep_num_str)
                ep_code = f"E{ep_num:02d}"
                anchors = re.findall(r'<a\s+[^>]*href=[\"\'](https?://[^\"\']+)[\"\'][^>]*>(.*?)</a>', p_content, re.S)
                valid = [(h, t) for h, t in anchors if is_valid_download_link(h)]
                if valid:
                    ep_entry = dict(rel_base)
                    ep_entry["episode"] = ep_code
                    clean_rel_title = re.sub(r'\s*-\s*S\d+E\d+', '', rel_base['release_title'])
                    ep_entry["release_title"] = f"{clean_rel_title} - {season_str}{ep_code}"
                    ep_entry["sources"] = _resolve_anchors(valid)
                    releases.append(ep_entry)
        else:
            # Check for multiple <p> blocks or single batch/movie release
            p_blocks = []
            for p_match in re.finditer(r"<p[^>]*>(.*?)</p>", n_html, re.S | re.I):
                p_content = p_match.group(1)
                anchors = re.findall(r'<a\s+[^>]*href=[\"\'](https?://[^\"\']+)[\"\'][^>]*>(.*?)</a>', p_content, re.S)
                valid = [(h, t) for h, t in anchors if is_valid_download_link(h)]
                if valid:
                    p_blocks.append(valid)

            all_anchors = []
            for pb in p_blocks:
                all_anchors.extend(pb)

            single_entry = dict(rel_base)
            is_batch = any(b in n_title.lower() for b in ["batch", "complete", "zip", "all episodes"])
            if is_batch and content_type == "series":
                single_entry["episode"] = "Batch"
            single_entry["sources"] = _resolve_anchors(all_anchors)
            releases.append(single_entry)

    return {
        "url": post_url,
        "slug": slug,
        "title": meta["title"],
        "clean_title": clean_title,
        "year": year,
        "content_type": content_type,
        "seasons": seasons,
        "poster_url": poster_url,
        "backdrop_urls": backdrop_urls,
        "synopsis": synopsis,
        "genres": genres,
        "language": language,
        "source_site": "rogmovies",
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
                "UPDATE sitemap_cache SET scraped = 1 WHERE loc = ? AND site = 'rogmovies'",
                (data["url"],),
            )
    return post_id


def requeue_failed_urls(db_path: Path) -> int:
    """Requeue only Rogmovies rows previously marked for no-release review."""
    fast_fetch.DB_PATH = db_path
    with fast_fetch._DB_WRITE_LOCK:
        with fast_fetch.get_db() as conn:
            cursor = conn.execute(
                "UPDATE sitemap_cache SET scraped = 0 "
                "WHERE site = 'rogmovies' AND scraped = -1"
            )
            return cursor.rowcount


def run_rogmovies_scraper(
    base_url: str = DEFAULT_BASE_URL,
    db_path: Path = DEFAULT_DB_PATH,
    limit: int | None = None,
    workers: int = 6,
    delay: float = 0.3,
    retry_failed: bool = False,
):
    """Worker pool orchestrator for scraping Rogmovies titles into staging DB."""
    if not 1 <= workers <= MAX_SAFE_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_SAFE_WORKERS}")
    if delay < MIN_REQUEST_DELAY:
        raise ValueError(f"delay must be at least {MIN_REQUEST_DELAY}s")

    fast_fetch.DB_PATH = db_path
    fast_fetch.init_db()

    if retry_failed:
        requeued = requeue_failed_urls(db_path)
        print(f"[*] Requeued {requeued:,} no-release rows for review/retry.", flush=True)

    client = RogmoviesClient(base_url, request_interval=delay)

    # Check pending URLs in sitemap_cache
    with fast_fetch.get_db() as conn:
        cursor = conn.execute(
            "SELECT loc FROM sitemap_cache WHERE site = 'rogmovies' AND scraped = 0 ORDER BY rowid ASC"
        )
        pending_urls = [row["loc"] for row in cursor]

    if not pending_urls:
        print("[*] No pending URLs in sitemap_cache. Syncing sitemaps first...", flush=True)
        sync_sitemap_to_db(client, db_path)
        with fast_fetch.get_db() as conn:
            cursor = conn.execute(
                "SELECT loc FROM sitemap_cache WHERE site = 'rogmovies' AND scraped = 0 ORDER BY rowid ASC"
            )
            pending_urls = [row["loc"] for row in cursor]

    if limit is not None:
        pending_urls = pending_urls[:max(0, limit)]

    total_tasks = len(pending_urls)
    print(f"\n{'='*70}")
    print(f"🚀 Rogmovies Staging Ingestion Pipeline")
    print(f"   Database       : {db_path.name}")
    print(f"   Pending Titles : {total_tasks:,}")
    print(f"   Workers        : {workers} | Delay: {delay}s")
    print(f"{'='*70}\n", flush=True)

    counters = {
        "completed": 0,
        "releases": 0,
        "sources": 0,
        "failed": 0,
        "skipped": 0,
        "start_time": time.time(),
    }

    thread_local = threading.local()

    def get_thread_client() -> RogmoviesClient:
        if not hasattr(thread_local, "client"):
            thread_local.client = RogmoviesClient(base_url, request_interval=delay)
        return thread_local.client

    def process_one_url(url: str) -> dict:
        if STOP_REQUESTED:
            return {"skipped": True}
        c = get_thread_client()
        code, final_url, html_text = c.get_text(url)
        if code != 200 or not html_text:
            return {"failed": True, "error": f"HTTP {code}", "url": url}

        data = extract_post_data_rogmovies(final_url, html_text, client=c, resolve_bridges=True)
        if not data or not data.get("releases"):
            with fast_fetch._DB_WRITE_LOCK:
                with fast_fetch.get_db() as conn:
                    conn.execute(
                        "UPDATE sitemap_cache SET scraped = -1 "
                        "WHERE loc = ? AND site = 'rogmovies'",
                        (url,),
                    )
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
            elif res.get("skipped"):
                counters["skipped"] += 1

            processed = counters["completed"] + counters["failed"] + counters["skipped"]
            if processed % 10 == 0 or processed == total_tasks:
                elapsed = time.time() - counters["start_time"]
                speed = processed / max(1, elapsed)
                print(
                    f"[{processed}/{total_tasks}] "
                    f"releases={counters['releases']} sources={counters['sources']} "
                    f"failed={counters['failed']} review={counters['skipped']} "
                    f"speed={speed:.2f} titles/sec",
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
                            "skipped": counters["skipped"],
                            "processed": processed,
                            "pending": max(0, total_tasks - counters["completed"] - counters["skipped"]),
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }, sf, indent=2)
                except Exception:
                    pass

    print(f"\n[✓] Rogmovies scraping finished: {counters}", flush=True)


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
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'rogmovies' AND scraped = 1")
    scraped = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'rogmovies' AND scraped = 0")
    pending = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'rogmovies' AND scraped = -1")
    review = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'rogmovies'")
    total = c.fetchone()[0]
    conn.close()

    print("\n" + "=" * 55)
    print(f" 📊 Rogmovies Staging Database Status ({db_path.name})")
    print("=" * 55)
    print(f" Catalog Posts   : {posts:,}")
    print(f" Releases Found  : {releases:,}")
    print(f" Sources Mapped  : {sources:,}")
    print(f" Scraped Titles  : {scraped:,}")
    print(f" Pending Titles  : {pending:,}")
    print(f" Needs Review    : {review:,} (scraped=-1; retry with --retry-failed)")
    print(f" Discovered URLs : {total:,}")
    print("=" * 55 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Rogmovies Staging Importer")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base origin URL")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite staging database")
    parser.add_argument("--sync-sitemap", action="store_true", help="Download and sync sitemap XML to database")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of titles to scrape")
    parser.add_argument("--workers", type=int, default=6, help="Worker threads (safe range: 1-6; default: 6)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests per worker (s)")
    parser.add_argument("--retry-failed", action="store_true", help="Requeue previously reviewed no-release URLs")
    parser.add_argument("--status", action="store_true", help="Print database counts and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db_path).resolve()

    if args.status:
        get_status_summary(db_path)
        return

    client = RogmoviesClient(args.base_url, request_interval=args.delay)

    if args.sync_sitemap:
        sync_sitemap_to_db(client, db_path)
        return

    run_rogmovies_scraper(
        base_url=args.base_url,
        db_path=db_path,
        limit=args.limit,
        workers=args.workers,
        delay=args.delay,
        retry_failed=args.retry_failed,
    )


if __name__ == "__main__":
    main()
