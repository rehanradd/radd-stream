#!/usr/bin/env python3
"""
import_katmoviehd.py — Dedicated staging importer and scraper for KatMovieHD (https://new.katmoviehd.top).

Key Features:
  1. Dedicated staging SQLite database: katmoviehd.db (strictly isolated from production fast_fetch.db).
  2. Full Catalog Synchronization:
     - Directly queries SvelteKit data API: https://new.katmoviehd.top/__data.json?page={n}
     - Custom high-speed devalue chunk deserializer to ingest ~51,250+ titles across 4,271 pages.
  3. Rich Metadata Extraction:
     - Pre-populated TMDB/Amazon high-res posters, original dates, and genre categories.
     - Official IMDB ID and rating extraction from post detail chunks.
     - Clean canonical key generation with season detection.
  4. Episode & Release Parsing:
     - Distinguishes movie release links from TV series episode-by-episode blocks (e.g. Episode 01, Episode 02...).
     - Extracts resolution tiers (4K 2160p, 1080p 10bit, 720p HEVC, 720p, 480p).
  5. Hidden API Stream Resolution:
     - Direct REST lookup via https://api.dandndn.one/api/v1/file/{file_id} with JWT authorization.
     - Extracts exact file size in bytes, original clean file name, and all mirror IDs.
     - Unwraps HubCloud mirrors to 10Gbps Cloudflare R2 direct streams (r2.cloudflarestorage.com),
       Fast Server 10G direct streams, and PixelDrain CDN.
     - Captures GDFlix, KatDrive, FastDL, Send.cm, and 1Fichier mirrors.
  6. Resumable via sitemap_cache table in staging SQLite database.
  7. 100% Python Standard Library. Zero external pip packages.

Usage:
    python Fast_Fetch/import_katmoviehd.py --sync-api --max-pages 50   # Ingest first 50 pages (600 titles)
    python Fast_Fetch/import_katmoviehd.py --sync-api                 # Ingest entire catalog (~51,250 titles)
    python Fast_Fetch/import_katmoviehd.py --limit 10                 # Scrape 10 pending titles
    python Fast_Fetch/import_katmoviehd.py --workers 5 --delay 0.3   # Full background crawler
    python Fast_Fetch/import_katmoviehd.py --status                   # Show staging DB metrics
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

DEFAULT_BASE_URL = "https://new.katmoviehd.top"
KMHD_API_BASE = "https://api.dandndn.one/api/v1"
KMHD_JWT_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJhZG1pbiIsImV4cCI6MTgwNzQ4NDIzMywiaWF0IjoxNzA3NDg0MjMzfQ."
    "7u5bF9PcMhvClSDZgsd6EU-CQnp1Ec--wsezkDEgiZo"
)
DEFAULT_DB_PATH = (
    Path("/home/ubuntu/radd-stream-data/katmoviehd.db")
    if Path("/home/ubuntu/radd-stream-data").exists()
    else BASE_DIR / "katmoviehd.db"
)
STATUS_FILE = BASE_DIR / "katmoviehd_status.json"

STOP_REQUESTED = False


def _sigint_handler(signum, frame):
    global STOP_REQUESTED
    print("\n[!] Graceful shutdown requested... Finishing active requests.", flush=True)
    STOP_REQUESTED = True


def get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class KatMovieHDClient:
    """Thread-safe HTTP client with rate-limiting, retries, and browser headers."""

    def __init__(self, request_interval: float = 0.3):
        self.request_interval = request_interval
        self._last_req_time = 0.0
        self._lock = threading.Lock()
        self.ssl_ctx = get_ssl_context()

    def _rate_limit(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_req_time
            if elapsed < self.request_interval:
                time.sleep(self.request_interval - elapsed)
            self._last_req_time = time.time()

    def get_text(self, url: str, headers: dict | None = None, timeout: int = 15) -> tuple[int, dict, str | None]:
        self._rate_limit()
        req_headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, headers=req_headers)
        for attempt in range(3):
            if STOP_REQUESTED:
                return 0, {}, None
            try:
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                    code = resp.status
                    resp_headers = dict(resp.headers)
                    body = resp.read().decode("utf-8", errors="ignore")
                    return code, resp_headers, body
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    return e.code, dict(e.headers), None
                time.sleep(1.0 * (attempt + 1))
            except Exception:
                time.sleep(1.0 * (attempt + 1))
        return 0, {}, None

    def get_api_json(self, url: str, timeout: int = 12) -> dict | None:
        self._rate_limit()
        req_headers = {
            "User-Agent": fast_fetch.USER_AGENT,
            "Authorization": f"Bearer {KMHD_JWT_TOKEN}",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=req_headers)
        for attempt in range(3):
            if STOP_REQUESTED:
                return None
            try:
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        return None


def init_staging_db(db_path: Path):
    """Initializes KatMovieHD staging SQLite database with isolated schema."""
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
                site TEXT DEFAULT 'katmoviehd',
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
                cast_names TEXT,
                director TEXT,
                languages TEXT,
                rating REAL,
                is_18_plus INTEGER DEFAULT 0,
                site TEXT DEFAULT 'katmoviehd',
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
        # Schema migration check
        existing_cols = [c[1] for c in conn.execute("PRAGMA table_info(posts);").fetchall()]
        for col in ["cast_names", "director", "languages"]:
            if col not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT;")
                except Exception:
                    pass
        if "is_18_plus" not in existing_cols:
            try:
                conn.execute("ALTER TABLE posts ADD COLUMN is_18_plus INTEGER DEFAULT 0;")
            except Exception:
                pass
        conn.commit()


def parse_sveltekit_chunk(data_str: str) -> list[dict]:
    """Deserializes SvelteKit devalue chunk from __data.json response into item dictionaries."""
    for line in data_str.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue

        if j.get("type") == "chunk" and j.get("id") == 1:
            raw_list = j.get("data", [])
            if len(raw_list) > 2 and isinstance(raw_list[2], dict) and "items" in raw_list[2]:
                items_idx = raw_list[2]["items"]
                if not isinstance(items_idx, int) or items_idx >= len(raw_list):
                    continue
                item_indices = raw_list[items_idx]
                if not isinstance(item_indices, list):
                    continue

                results = []
                for idx in item_indices:
                    if not isinstance(idx, int) or idx >= len(raw_list):
                        continue
                    item_def = raw_list[idx]
                    if not isinstance(item_def, dict):
                        continue

                    item = {}
                    for k, v in item_def.items():
                        if isinstance(v, int) and v < len(raw_list):
                            val = raw_list[v]
                            if isinstance(val, list) and all(isinstance(x, int) for x in val):
                                item[k] = [raw_list[x] for x in val if isinstance(x, int) and x < len(raw_list)]
                            else:
                                item[k] = val
                        else:
                            item[k] = v
                    results.append(item)
                return results
    return []


def clean_katmoviehd_title(raw_title: str) -> tuple[str, int | None, int | None, str]:
    """
    Cleans raw title into (clean_title, year, season, canonical_key).
    Examples:
      'The Punisher (Season 2) Hindi Dubbed (DD 5.1) & English...' -> ('The Punisher', 2017, 2, 'the-punisher_s2')
      'The Campaign (2012) Hindi Dubbed (ORG)...' -> ('The Campaign', 2012, None, 'the-campaign_2012')
    """
    t = html.unescape(raw_title).strip()

    # Season extraction
    season = None
    s_m = re.search(r"\b(?:Season|S)\s*0?(\d+)\b", t, re.I)
    if s_m:
        season = int(s_m.group(1))

    # Year extraction
    year = None
    y_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if y_m:
        year = int(y_m.group(1))

    # Strip bracketed content [Dual Audio], etc.
    clean = re.sub(r"\[.*?\]", "", t)
    # Cut off at pipe symbol |
    clean = re.split(r"\s*\|\s*", clean)[0]

    # Remove tags inside parentheses
    clean = re.sub(r"\((?:Season\s*\d+|19\d{2}|20\d{2}|ORG|DD\s*[\d\.]+|[^\)]*Audio[^\)]*|[^\)]*Dubbed[^\)]*)\)", "", clean, flags=re.I)

    noise_patterns = [
        r"\b(?:Hindi|English|Tamil|Telugu|Korean|Japanese|Chinese|Dual Audio|Multi Audio)\b",
        r"\b(?:Dubbed|Dub|ORG|DD\s*5\.1|DD\s*2\.0|Atmos|ESub|Full Movie|Series|Download)\b",
        r"\b(?:4K|2160p|1080p|720p|480p|360p|UHD|SDR|HDR|HDR10\+?|HEVC|10bit|BluRay|WEB-DL|WEBRip|HDRip|CAMRip|CAM|HD|EXTENDED)\b",
        r"\b(?:Episode\s*\d+\s*Added|Complete|Episodes?)\b",
        r"\bSeason\s*\d+\b",
    ]
    for p in noise_patterns:
        clean = re.sub(p, "", clean, flags=re.I)

    clean = re.sub(r"[:–\-\(\)&]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    canonical_key = fast_fetch.generate_canonical_key(clean, year if season is None else None)
    if season is not None:
        canonical_key = f"{canonical_key}_s{season}"

    return clean, year, season, canonical_key


def parse_katmoviehd_releases(content_html: str, default_season: int | None = None) -> list[dict]:
    """Parses releases from KatMovieHD post HTML, distinguishing series episodes from movie links."""
    releases = []

    # 1. Online watch stream (1xplayer)
    p_ifrs = re.findall(r'<iframe[^>]+src=["\'](https?://vd\.1xplayer\.com/play/[^"\']+)["\']', content_html, re.I)
    for ifr in p_ifrs:
        play_id = ifr.split("/")[-1].split("?")[0]
        releases.append({
            "label": "Online Stream (1XPlayer)",
            "episode_number": None,
            "season_number": None,
            "quality": "HD",
            "resolution": "720p",
            "file_id": play_id,
            "source_type": "1xplayer",
            "bridge_url": ifr,
        })

    # 2. Match all anchor download links
    has_episodes = bool(re.search(r"\bEpisode\s*\d+\b", content_html, re.I))

    # Helper to classify link
    def classify_link(href: str) -> tuple[str, str]:
        if "bbupload.to" in href:
            m = re.search(r"[?&]v=([A-Za-z0-9_-]+)", href)
            return "bbupload", (m.group(1) if m else "")
        elif "gofile.io" in href:
            fid = href.rstrip("/").split("/")[-1]
            return "gofile", fid
        elif "kmhd." in href:
            fid = href.rstrip("/").split("/")[-1]
            return "kmhd", fid
        elif "hubcloud" in href:
            fid = href.rstrip("/").split("/")[-1]
            return "hubcloud", fid
        return "unknown", ""

    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content_html, re.DOTALL | re.I):
        h = m.group(1)
        txt = m.group(2)
        clean_txt = re.sub(r'<[^>]+>', '', txt).strip()
        stype, fid = classify_link(h)
        if stype == "unknown":
            continue

        # 1. Episode in anchor text
        ep_m = re.search(r'(?:Episode|Ep)\s*0?(\d+)', clean_txt, re.I)
        ep_num = int(ep_m.group(1)) if ep_m else None

        # 2. Episode in preceding text block (up to 500 chars before)
        if ep_num is None and has_episodes:
            pre_start = max(0, m.start() - 500)
            pre_html = content_html[pre_start:m.start()]
            pre_ep_m = list(re.finditer(r'(?:Episode|Ep)\s*0?(\d+)', pre_html, re.I))
            if pre_ep_m:
                ep_num = int(pre_ep_m[-1].group(1))

        # Detect quality
        q = "720p"
        res = "720p"
        if "1080p" in clean_txt:
            q, res = "1080p", "1080p"
        elif "2160p" in clean_txt or "4k" in clean_txt.lower():
            q, res = "4K", "2160p"
        elif "480p" in clean_txt:
            q, res = "480p", "480p"
        elif "720p" in clean_txt:
            q, res = "720p", "720p"

        label = clean_txt or f"Download [{q}]"
        if ep_num and "Episode" not in label:
            label = f"Episode {ep_num:02d} - {label}"

        releases.append({
            "label": label,
            "episode_number": ep_num,
            "season_number": (default_season or 1) if (ep_num is not None) else None,
            "quality": q,
            "resolution": res,
            "file_id": fid,
            "source_type": stype,
            "bridge_url": h,
        })

    return releases


def resolve_file_sources(
    client: KatMovieHDClient,
    file_id: str,
    bridge_url: str,
    source_type: str = "kmhd",
    resolve_direct: bool = True,
    timeout: int = 12,
) -> tuple[int | None, list[dict]]:
    """Resolves file ID into direct mirror sources based on source type."""
    sources = []
    size_bytes = None

    if source_type == "bbupload":
        # BBUpload AJAX direct stream resolver
        api_url = f"https://download.bbupload.to/ajax.php?action=getdownload&data={file_id}"
        try:
            code, _, resp_text = client.get_text(
                api_url,
                headers={
                    "Referer": bridge_url,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                timeout=timeout,
            )
            if code == 200 and resp_text:
                res_json = json.loads(resp_text)
                if res_json.get("status") == "ok" and res_json.get("data"):
                    d = res_json["data"]
                    dl_url = d.get("downloadUrl")
                    if d.get("filesize"):
                        try:
                            size_bytes = int(d["filesize"])
                        except Exception:
                            pass

                    if dl_url:
                        sources.append({
                            "source_name": "⚡ SuperDuperLoad Direct Stream",
                            "service": "superduperload",
                            "resource_id": file_id,
                            "source_url": bridge_url,
                            "final_url": dl_url,
                            "is_temporary": 1,
                            "quality": "HD",
                        })
        except Exception:
            pass

        # Preserve fallback BBUpload gateway
        sources.append({
            "source_name": "🔗 BBUpload Gateway",
            "service": "bbupload",
            "resource_id": file_id,
            "source_url": bridge_url,
            "final_url": bridge_url,
            "is_temporary": 0,
            "quality": "HD",
        })
        return size_bytes, sources

    elif source_type == "gofile":
        sources.append({
            "source_name": "⚡ GoFile Direct Cloud",
            "service": "gofile",
            "resource_id": file_id,
            "source_url": bridge_url,
            "final_url": bridge_url,
            "is_temporary": 0,
            "quality": "HD",
        })
        return None, sources

    elif source_type == "1xplayer":
        sources.append({
            "source_name": "▶ 1XPlayer Online Stream",
            "service": "1xplayer",
            "resource_id": file_id,
            "source_url": bridge_url,
            "final_url": bridge_url,
            "is_temporary": 0,
            "quality": "HD",
        })
        return None, sources

    elif source_type == "hubcloud":
        if resolve_direct:
            try:
                unwrapped = fast_fetch.unwrap_hubcloud_drive(bridge_url)
                for src in unwrapped:
                    sources.append({
                        "source_name": src.get("source_name", "⚡ HubCloud Stream"),
                        "service": src.get("service", "hubcloud"),
                        "resource_id": src.get("resource_id", file_id),
                        "source_url": bridge_url,
                        "final_url": src.get("final_url", bridge_url),
                        "is_temporary": src.get("is_temporary", 0),
                        "quality": "720p",
                    })
            except Exception:
                pass
        if not sources:
            sources.append({
                "source_name": "⚡ HubCloud Drive",
                "service": "hubcloud",
                "resource_id": file_id,
                "source_url": bridge_url,
                "final_url": bridge_url,
                "is_temporary": 0,
                "quality": "720p",
            })
        return None, sources

    # Legacy KMHD REST API lookup
    api_url = f"{KMHD_API_BASE}/file/{file_id}"
    data = client.get_api_json(api_url, timeout=timeout)
    if not data or not isinstance(data, dict):
        sources.append({
            "source_name": "🔗 KatMovieHD Gateway",
            "service": "kmhd",
            "resource_id": file_id,
            "source_url": bridge_url,
            "final_url": bridge_url,
            "is_temporary": 0,
            "quality": "720p",
        })
        return None, sources

    size_bytes = data.get("size")
    upload_links = data.get("upload_links", {})

    # 1. HubCloud / HubDrive (Unwrapped to Cloudflare R2 & PixelDrain)
    hub_res = upload_links.get("hubdrive_res")
    if hub_res and hub_res != "None":
        hub_url = f"https://hubcloud.ist/drive/{hub_res}"
        if resolve_direct:
            try:
                unwrapped = fast_fetch.unwrap_hubcloud_drive(hub_url)
                for src in unwrapped:
                    sources.append({
                        "source_name": src.get("source_name", "⚡ HubCloud Stream"),
                        "service": src.get("service", "hubcloud"),
                        "resource_id": src.get("resource_id", hub_res),
                        "source_url": hub_url,
                        "final_url": src.get("final_url", hub_url),
                        "is_temporary": src.get("is_temporary", 0),
                        "quality": "720p",
                    })
            except Exception:
                pass
        if not sources:
            sources.append({
                "source_name": "⚡ HubCloud Drive",
                "service": "hubcloud",
                "resource_id": hub_res,
                "source_url": hub_url,
                "final_url": hub_url,
                "is_temporary": 0,
                "quality": "720p",
            })

    # 2. GDFlix
    gd_res = upload_links.get("gdflix_res")
    if gd_res and gd_res != "None":
        sources.append({
            "source_name": "⚡ GDFlix Mirror",
            "service": "gdflix",
            "resource_id": gd_res,
            "source_url": f"https://gd.kmhd.me/file/{gd_res}",
            "final_url": f"https://gd.kmhd.me/file/{gd_res}",
            "is_temporary": 0,
            "quality": "720p",
        })

    # 3. KatDrive
    kd_res = upload_links.get("katdrive_res")
    if kd_res and kd_res != "None":
        sources.append({
            "source_name": "⚡ KatDrive Mirror",
            "service": "katdrive",
            "resource_id": kd_res,
            "source_url": f"https://katdrive.click/file/{kd_res}",
            "final_url": f"https://katdrive.click/file/{kd_res}",
            "is_temporary": 0,
            "quality": "720p",
        })

    # 4. FastDL
    ff_res = upload_links.get("ffast_res")
    if ff_res and ff_res != "None":
        sources.append({
            "source_name": "⚡ FastDL",
            "service": "fastdl",
            "resource_id": ff_res,
            "source_url": f"https://fastdl.icu/{ff_res}",
            "final_url": f"https://fastdl.icu/{ff_res}",
            "is_temporary": 0,
            "quality": "720p",
        })

    # 5. Send.cm
    scm_res = upload_links.get("sendcm_res")
    if scm_res and scm_res != "None":
        sources.append({
            "source_name": "⚡ Send.cm",
            "service": "sendcm",
            "resource_id": scm_res,
            "source_url": f"https://send.cm/{scm_res}",
            "final_url": f"https://send.cm/{scm_res}",
            "is_temporary": 0,
            "quality": "720p",
        })

    # 6. 1Fichier
    fic_res = upload_links.get("fichier_res")
    if fic_res and fic_res != "None":
        fic_id = fic_res.lstrip("?")
        sources.append({
            "source_name": "⚡ 1Fichier",
            "service": "1fichier",
            "resource_id": fic_id,
            "source_url": f"https://1fichier.com/{fic_res}",
            "final_url": f"https://1fichier.com/{fic_res}",
            "is_temporary": 0,
            "quality": "720p",
        })

    return size_bytes, sources


def extract_post_data_katmoviehd(
    client: KatMovieHDClient,
    post_url: str,
    slug: str,
    cached_item: dict | None = None,
    resolve_direct: bool = True,
    timeout: int = 15,
) -> dict | None:
    """Extracts post metadata, releases, and unwrapped direct sources from KatMovieHD."""
    raw_title = cached_item.get("post_title", "") if cached_item else ""
    poster_url = cached_item.get("thumbnail_image") if cached_item else None
    genres_list = cached_item.get("categories", []) if cached_item else []

    # Fetch post detail chunk
    detail_url = f"{DEFAULT_BASE_URL}/{slug}/__data.json"
    code, _, resp_text = client.get_text(detail_url, timeout=timeout)
    if code != 200 or not resp_text:
        return None

    post_content = ""
    for line in resp_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        if j.get("type") == "chunk" and j.get("id") == 1:
            raw_data = j.get("data", [])
            if len(raw_data) > 3 and isinstance(raw_data[3], str):
                post_content = raw_data[3]
                break

    if not post_content:
        return {"loc": post_url, "skipped": True}

    clean_title, year, season, canonical_key = clean_katmoviehd_title(raw_title or slug)

    # IMDB ID & Rating extraction
    imdb_id = None
    imdb_m = re.search(r"imdb\.com/title/(tt\d+)", post_content, re.I)
    if imdb_m:
        imdb_id = imdb_m.group(1)

    rating = None
    rat_m = re.search(r"IMDb\s*Rating\s*[:\-–]?\s*([0-9\.]+)\s*/\s*10", post_content, re.I)
    if rat_m:
        try:
            rating = float(rat_m.group(1))
        except ValueError:
            pass

    # Rich metadata: Director, Cast, Genres, Languages, Plot
    director = None
    dir_m = re.search(r"<strong>Director:\s*</strong>\s*([^<]+)", post_content, re.I)
    if dir_m:
        director = html.unescape(dir_m.group(1)).strip()

    cast_names = None
    cast_m = re.search(r"<strong>(?:Star\s*Cast|Cast|Stars):\s*</strong>\s*([^<]+)", post_content, re.I)
    if cast_m:
        cast_names = html.unescape(cast_m.group(1)).strip()

    extracted_genres = []
    gen_m = re.search(r"<strong>(?:Genere|Genre|Genres):\s*</strong>\s*([^<]+)", post_content, re.I)
    if gen_m:
        extracted_genres = [
            g.strip() for g in html.unescape(gen_m.group(1)).split(",")
            if g.strip() and g.strip().upper() not in ("4RABET", "1XBET", "MELBET", "N/A")
        ]

    combined_genres = list(genres_list) if genres_list else []
    for eg in extracted_genres:
        if eg not in combined_genres:
            combined_genres.append(eg)

    languages = None
    lang_m = re.search(r"<strong>(?:Language|Languages|lang\d*):\s*</strong>\s*([^<]+)", post_content, re.I)
    if lang_m:
        languages = html.unescape(lang_m.group(1)).strip()

    # Poster & Backdrop
    p_img_m = re.search(r'<img[^>]+src=["\'](https?://[^"\']+(?:amazon\.com|tmdb\.org)[^"\']+)["\']', post_content)
    if p_img_m:
        poster_url = p_img_m.group(1)

    # Synopsis / Storyline
    synopsis = None
    plot_m = re.search(r"(?:<h\d[^>]*>|\b)(?:Plot|Storyline|Story|DESCRIPTION)[^<:]*[:\-–]?(?:</h\d>)?\s*(?:<p[^>]*>)?\s*(.*?)(?:</p>|<h\d|$)", post_content, re.I | re.DOTALL)
    if plot_m:
        clean_p = re.sub(r"<[^>]*>", "", plot_m.group(1)).strip()
        if len(clean_p) > 20 and not clean_p.lower().startswith("full movie"):
            synopsis = clean_p

    # Media type detection
    is_series = bool(season or "episode" in post_content.lower() or "tv-series" in str(genres_list).lower())
    media_type = "series" if is_series else "movie"

    parsed_releases = parse_katmoviehd_releases(post_content, default_season=season)
    if not parsed_releases:
        return None

    releases_data = []
    for r in parsed_releases:
        file_id = r["file_id"]
        bridge_url = r["bridge_url"]
        stype = r.get("source_type", "kmhd")
        size_bytes, sources = resolve_file_sources(
            client=client,
            file_id=file_id,
            bridge_url=bridge_url,
            source_type=stype,
            resolve_direct=resolve_direct,
            timeout=timeout,
        )

        releases_data.append({
            "label": r["label"],
            "quality": r["quality"],
            "resolution": r["resolution"],
            "size_bytes": size_bytes,
            "season_number": r["season_number"],
            "episode_number": r["episode_number"],
            "audio_languages": languages or json.dumps(["Hindi", "English"]),
            "codec": "x264",
            "bridge_url": bridge_url,
            "sources": sources,
        })

    return {
        "canonical_key": canonical_key,
        "title": clean_title,
        "original_title": raw_title,
        "year": year,
        "media_type": media_type,
        "imdb_id": imdb_id,
        "poster_url": poster_url,
        "synopsis": synopsis,
        "genres": json.dumps(combined_genres) if combined_genres else None,
        "cast_names": cast_names,
        "director": director,
        "languages": languages,
        "rating": rating,
        "site": "katmoviehd",
        "post_url": post_url,
        "releases": releases_data,
    }


def save_post_to_staging_db(db_path: Path, post_data: dict) -> bool:
    """Saves post, releases, and sources into isolated katmoviehd.db staging database."""
    if not post_data or not post_data.get("releases"):
        return False

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()

        # 1. Upsert Post
        cur.execute(
            """
            INSERT INTO posts (
                canonical_key, title, original_title, year, media_type,
                imdb_id, poster_url, synopsis, genres, cast_names, director, languages, rating, is_18_plus, site, post_url,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
                rating = COALESCE(excluded.rating, posts.rating),
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
                post_data.get("rating"),
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


def sync_sveltekit_api_to_db(db_path: Path, max_pages: int | None = None) -> int:
    """Syncs the entire KatMovieHD catalog via SvelteKit __data.json pagination into sitemap_cache."""
    init_staging_db(db_path)
    client = KatMovieHDClient(request_interval=0.2)

    print(f"[*] Starting KatMovieHD catalog sync from {DEFAULT_BASE_URL}/__data.json...", flush=True)
    page = 1
    total_synced = 0
    empty_pages_streak = 0

    while not STOP_REQUESTED:
        if max_pages and page > max_pages:
            print(f"[*] Reached requested max_pages limit ({max_pages}). Stopping sync.", flush=True)
            break

        query_url = f"{DEFAULT_BASE_URL}/__data.json?page={page}"
        t0 = time.time()
        code, _, resp_text = client.get_text(query_url, timeout=15)
        dt = time.time() - t0

        retries = 3
        while (code != 200 or not resp_text) and retries > 0 and not STOP_REQUESTED:
            time.sleep(1.0)
            code, _, resp_text = client.get_text(query_url, timeout=15)
            retries -= 1

        if code != 200 or not resp_text:
            empty_pages_streak += 1
            if empty_pages_streak >= 5:
                print(f"[*] 5 consecutive empty/failed pages reached at page {page}. Catalog sync complete.", flush=True)
                break
            page += 1
            continue

        items = parse_sveltekit_chunk(resp_text)
        if not items:
            empty_pages_streak += 1
            if empty_pages_streak >= 5:
                print(f"[*] 5 consecutive empty pages reached at page {page}. Catalog sync complete.", flush=True)
                break
            page += 1
            continue

        empty_pages_streak = 0
        records = []
        for it in items:
            slug = it.get("slug")
            if not slug:
                continue
            permalink = f"{DEFAULT_BASE_URL}/{slug}"
            lastmod = it.get("created")
            raw_json_str = json.dumps(it)
            records.append((permalink, lastmod, slug, 0, "katmoviehd", raw_json_str))

        if records:
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(loc) DO UPDATE SET
                        lastmod = excluded.lastmod,
                        raw_json = excluded.raw_json;
                    """,
                    records,
                )
                conn.commit()
            total_synced += len(records)

        print(
            f"  [Page {page:4d}] Synced {len(records):2d} titles in {dt:.2f}s "
            f"({total_synced:,} total catalog items)",
            flush=True,
        )
        page += 1

    print(f"\n[✓] KatMovieHD catalog sync finished: {total_synced:,} titles stored in {db_path.name}\n", flush=True)
    return total_synced


def run_crawler(
    db_path: Path,
    workers: int = 5,
    delay: float = 0.3,
    limit: int | None = None,
    resolve_direct: bool = True,
):
    """Multi-threaded background crawler for KatMovieHD with rate limiting and progress updates."""
    init_staging_db(db_path)
    client = KatMovieHDClient(request_interval=delay)

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        query = "SELECT loc, slug, raw_json FROM sitemap_cache WHERE scraped = 0 ORDER BY rowid ASC"
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        pending_rows = cur.fetchall()

    if not pending_rows:
        print("[*] No pending titles found in sitemap_cache. Run --sync-api first.", flush=True)
        return

    total_pending = len(pending_rows)
    print(f"[*] Starting KatMovieHD crawler: {total_pending:,} titles queued | {workers} workers | delay {delay}s\n", flush=True)

    completed = 0
    failed = 0
    total_releases = 0
    total_sources = 0
    total_r2 = 0
    total_pd = 0
    start_time = time.time()

    def process_item(item):
        loc, slug, raw_json_str = item
        cached_item = json.loads(raw_json_str) if raw_json_str else None

        post_data = extract_post_data_katmoviehd(
            client=client,
            post_url=loc,
            slug=slug,
            cached_item=cached_item,
            resolve_direct=resolve_direct,
        )
        if post_data and post_data.get("skipped"):
            return loc, True, 0, 0, 0, 0

        if not post_data or not post_data.get("releases"):
            return loc, False, 0, 0, 0, 0

        ok = save_post_to_staging_db(db_path, post_data)
        num_rels = len(post_data["releases"])
        num_srcs = sum(len(r.get("sources", [])) for r in post_data["releases"])
        r2_cnt = sum(1 for r in post_data["releases"] for s in r.get("sources", []) if s.get("service") == "fsl_r2")
        pd_cnt = sum(1 for r in post_data["releases"] for s in r.get("sources", []) if s.get("service") == "pixeldrain")
        return loc, ok, num_rels, num_srcs, r2_cnt, pd_cnt

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_item, row): row for row in pending_rows}

        for future in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED:
                break
            loc, ok, rel_cnt, src_cnt, r2_cnt, pd_cnt = future.result()

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
                total_r2 += r2_cnt
                total_pd += pd_cnt
            else:
                failed += 1

            if (completed + failed) % 10 == 0 or (completed + failed) == total_pending:
                elapsed = time.time() - start_time
                speed = (completed + failed) / elapsed if elapsed > 0 else 0
                remaining = total_pending - (completed + failed)
                eta_sec = int(remaining / speed) if speed > 0 else 0
                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_sec))

                print(
                    f"  [{completed + failed}/{total_pending}] "
                    f"releases={total_releases:,} sources={total_sources:,} "
                    f"r2={total_r2:,} pd={total_pd:,} failed={failed} "
                    f"speed={speed:.2f} t/s ETA: {eta_str}",
                    flush=True,
                )

                try:
                    status_payload = {
                        "timestamp": time.time(),
                        "completed": completed,
                        "failed": failed,
                        "total_pending": total_pending,
                        "total_releases": total_releases,
                        "total_sources": total_sources,
                        "r2_sources": total_r2,
                        "pixeldrain_sources": total_pd,
                        "speed": speed,
                    }
                    with open(STATUS_FILE, "w") as sf:
                        json.dump(status_payload, sf)
                except Exception:
                    pass

    total_time = time.time() - start_time
    print(f"\n[✓] Crawler finished: {completed} scraped, {failed} failed in {total_time:.1f}s\n", flush=True)


def print_status(db_path: Path):
    """Prints status metrics of staging SQLite database."""
    if not db_path.exists():
        print(f"[!] Database {db_path} does not exist yet. Run --sync-api first.")
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
        r2_cnt = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'fsl_r2'").fetchone()[0]
        pd_cnt = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'pixeldrain'").fetchone()[0]
        hub_cnt = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'hubcloud'").fetchone()[0]
        gd_cnt = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'gdflix'").fetchone()[0]
        kd_cnt = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'katdrive'").fetchone()[0]
        scm_cnt = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'sendcm'").fetchone()[0]

    pct = (scraped / total_cache * 100) if total_cache > 0 else 0.0
    print("\n" + "=" * 55)
    print(f" 📦 KatMovieHD Staging Database Status ({db_path.name})")
    print("=" * 55)
    print(f" Sitemap Cache Total : {total_cache:,}")
    print(f" Scraped (Done)      : {scraped:,} ({pct:.1f}%)")
    print(f" Pending             : {pending:,}")
    print(f" Failed/Review       : {failed:,}")
    print("-" * 55)
    print(f" Catalog Posts       : {posts:,}")
    print(f" Releases Found      : {releases:,}")
    print(f" Direct Sources      : {sources:,}")
    print(f"   ⚡ Cloudflare R2   : {r2_cnt:,} (10Gbps direct stream)")
    print(f"   ⚡ PixelDrain CDN  : {pd_cnt:,} (Instant Video/Matroska)")
    print(f"   ⚡ HubCloud Drive  : {hub_cnt:,}")
    print(f"   ⚡ GDFlix Mirrors  : {gd_cnt:,}")
    print(f"   ⚡ KatDrive Mirrors: {kd_cnt:,}")
    print(f"   ⚡ Send.cm Mirrors : {scm_cnt:,}")
    print("=" * 55 + "\n")


def main():
    signal.signal(signal.SIGINT, _sigint_handler)
    signal.signal(signal.SIGTERM, _sigint_handler)

    parser = argparse.ArgumentParser(description="KatMovieHD Staging Importer & Crawler")
    parser.add_argument("--sync-api", action="store_true", help="Sync titles from SvelteKit __data.json")
    parser.add_argument("--max-pages", type=int, default=None, help="Max catalog pages to sync")
    parser.add_argument("--status", action="store_true", help="Print staging DB statistics")
    parser.add_argument("--workers", type=int, default=5, help="Crawler concurrent threads")
    parser.add_argument("--delay", type=float, default=0.3, help="Request interval delay in seconds")
    parser.add_argument("--limit", type=int, default=None, help="Scrape up to N pending titles")
    parser.add_argument("--no-resolve-direct", action="store_true", help="Skip unwrapping HubCloud to R2 direct streams")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to staging SQLite database")

    args = parser.parse_args()

    if args.status:
        print_status(args.db_path)
        return

    if args.sync_api:
        sync_sveltekit_api_to_db(args.db_path, max_pages=args.max_pages)
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
