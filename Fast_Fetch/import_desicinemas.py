#!/usr/bin/env python3
"""
import_desicinemas.py — DesiCinemas Catalog Scraper & DooPlay/Peytonepre HLS Resolver.

Follows the Radd-Stream Manifesto:
- Dedicated Staging Database: /home/ubuntu/radd-stream-data/desicinemas.db
- Strict isolation: NEVER merges into production fast_fetch.db without explicit user confirmation.
- Zero external pip or npm packages (100% Python standard library only).
- Adult 18+ titles are stored with is_18_plus = 1 flag; hidden at presentation layer only.
- Zero Data Loss rule: All streams, embeds, and fallback gateways preserved.
"""

from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_URL = "https://www.desicinemas.pk"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemap_index.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/desicinemas.db")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Provenance stamp. This staging database only ever holds desicinemas pages, so
# every post it writes must say so; merge_catalogs reads `source_site`/`site`
# from staging rows and rows without a stamp used to land as 'unknown'.
SITE = "desicinemas"

# The catalog's only legal content types — parse_post_metadata() in fast_fetch.py
# never emits anything else, so a fifth value silently breaks every type filter.
LEGAL_MEDIA_TYPES = ("movie", "series", "complete_season", "ongoing_season")

# sitemap_cache.scraped state machine, shared with every other staging importer
# and with fast_fetch's crawler: 0 = queued, 1 = indexed, -1 = tried but not
# indexable (needs review). 2 ("skipped") is retired because nothing drained it;
# skipped pages now land on -1, while the pending query still accepts legacy 2
# rows so no page can strand in the dead state.
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC" % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

STOP_REQUESTED = False


def _sigint_handler(signum, frame):
    global STOP_REQUESTED
    print("\n[!] Graceful shutdown requested... Finishing current batch.", flush=True)
    STOP_REQUESTED = True


signal.signal(signal.SIGINT, _sigint_handler)
signal.signal(signal.SIGTERM, _sigint_handler)


# --- Adult Content Filter ---
# "rabbit" left on 2026-10-29 (0/12 sampled live titles are adult — *Wallace & Gromit*,
# *1001 Rabbit Tales*, *Jojo Rabbit*). "adult" stays: 10/12 of its sampled rows are real
# product, including this fleet's "… Adult Short Film" format, and the two false positives
# measured (*Shin-chan: The Adult Empire Strikes Back*) are the documented cost. Sampling
# live titles is the law; `fast_fetch.ADULT_TITLE_PATTERNS` carries the reasoning.
ADULT_KEYWORDS = {
    "18+", "erotic", "hotshots", "ullu", "kooku", "primeplay", "hentai",
    "uncensored", "sex", "porn", "adult", "lust", "sensual", "naked", "nude",
    "charmsukh", "palang tod", "rasmalai", "chull", "bhabhi", "jalebi"
}


def is_adult_content(text: str | None) -> bool:
    """Strictly checks if title or slug contains adult/18+ keywords."""
    if not text:
        return False
    clean = re.sub(r"[^a-zA-Z0-9\+]+", " ", text.lower()).strip()
    words = set(clean.split())
    if "18+" in clean or "18 plus" in clean:
        return True
    return bool(words & ADULT_KEYWORDS)


# --- Dean Edwards Packed JS Unpacker ---
def unpack_dean_edwards(packed_js: str) -> str:
    """
    Unpacks eval(function(p,a,c,k,e,d)...) JavaScript code (Dean Edwards packer).
    100% Python standard library.
    """
    m = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'(.*?)'\.split\('\|'\)",
        packed_js,
        re.DOTALL,
    )
    if not m:
        return ""

    payload = m.group(1)
    radix = int(m.group(2))
    count = int(m.group(3))
    syms = m.group(4).split("|")

    def base_n(num: int, b: int) -> str:
        chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if num == 0:
            return "0"
        res = []
        while num:
            res.append(chars[num % b])
            num //= b
        return "".join(reversed(res))

    lookup = {
        base_n(i, radix): syms[i] if i < len(syms) and syms[i] else base_n(i, radix)
        for i in range(count)
    }

    return re.sub(r"\b\w+\b", lambda match: lookup.get(match.group(0), match.group(0)), payload)


# --- Title & Metadata Normalizer ---
def normalize_media_type(media_type: str | None) -> str:
    """Clamps any scraper page label onto the four content types the catalog stores."""
    value = str(media_type or "movie").strip().lower()
    if value in LEGAL_MEDIA_TYPES:
        return value
    # Episode/season pages describe part of a series; anything unrecognised is
    # treated as a single film rather than inventing a fifth type.
    if any(token in value for token in ("episode", "season", "series", "batch", "pack")):
        return "series"
    return "movie"


def slug_from_url(url: str | None) -> str:
    """Stable slug for a page URL, derived exactly like merge_catalogs does."""
    return urllib.parse.urlsplit(url or "").path.strip("/").replace(".html", "")


def clean_desicinemas_title(raw_title: str, url: str = "") -> tuple[str, int | None, int | None, int | None, str | None, str | None, str, str]:
    """
    Cleans raw title from DesiCinemas.
    Returns: (clean_title, year, season_number, episode_number, quality, audio_languages, media_type, canonical_key)
    `media_type` is always one of LEGAL_MEDIA_TYPES; the page's own shape
    (movie / series / episode) still drives the canonical key.
    """
    if not raw_title:
        return "Unknown", None, None, None, None, None, "movie", "unknown"

    # Decode HTML entities
    text = html.unescape(raw_title).strip()
    text = re.sub(r"<[^>]*>", "", text)

    # Detect Quality
    quality = None
    q_match = re.search(r"\b(4k|2160p|1080p|720p|480p|HD|CAM|Pre-DVD|HQ|WEBRip|HDRip)\b", text, re.IGNORECASE)
    if q_match:
        quality = q_match.group(1).upper()

    # Detect Languages
    languages = None
    lang_match = re.search(r"\((Hindi|Punjabi|Tamil|Telugu|Malayalam|Kannada|Bengali|English|Dubbed)\)", text, re.IGNORECASE)
    if lang_match:
        languages = lang_match.group(1).title()

    # Detect Year
    year = None
    y_match = re.search(r"\b(19\d\d|20\d\d)\b", text)
    if y_match:
        year = int(y_match.group(1))

    # Detect Season & Episode
    season_num = None
    episode_num = None
    page_kind = "movie"

    # Season/Episode in title or URL
    se_match = re.search(r"Season\s*(\d+)\s*(?:Episode\s*(\d+))?", text, re.IGNORECASE)
    if not se_match:
        se_match = re.search(r"\bS(\d+)(?:E(\d+))?\b", text, re.IGNORECASE)

    ep_url_match = re.search(r"/episode/[^/]+-episode-(\d+)/", url, re.IGNORECASE)
    if not ep_url_match:
        ep_url_match = re.search(r"Episode\s*(\d+)", text, re.IGNORECASE)

    if "/episode/" in url or ep_url_match:
        page_kind = "episode"
        if ep_url_match:
            episode_num = int(ep_url_match.group(1))
        if se_match:
            season_num = int(se_match.group(1))
            if se_match.group(2) and episode_num is None:
                episode_num = int(se_match.group(2))
    elif "/series/" in url or "/season/" in url or "Season" in text:
        page_kind = "series"
        if se_match:
            season_num = int(se_match.group(1))

    # Clean title string
    cleaned = text
    # Remove tags like (HD), (CAM), (Punjabi), Season X Episode Y
    cleaned = re.sub(r"\((HD|CAM|Pre-DVD|HQ|Punjabi|Hindi|Tamil|Telugu|Malayalam|English|Dubbed)\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSeason\s*\d+\s*(?:Episode\s*\d+)?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bS\d+(?:E\d+)?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(HD|CAM|HQ|WEBRip|HDRip|Free Episodes?|Watch)\b", "", cleaned, flags=re.IGNORECASE)
    if year:
        cleaned = re.sub(rf"\b{year}\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[\-–:]\s*$", "", cleaned).strip()

    if not cleaned:
        cleaned = text.strip()

    # Generate canonical key
    slug_base = re.sub(r"[^a-z0-9]+", "-", cleaned.lower()).strip("-")
    if page_kind == "episode":
        s_part = f"s{season_num:02d}" if season_num else "s01"
        e_part = f"e{episode_num:02d}" if episode_num else "e01"
        canonical_key = f"{slug_base}-{s_part}{e_part}"
    elif page_kind == "series":
        s_part = f"-s{season_num:02d}" if season_num else ""
        canonical_key = f"{slug_base}{s_part}"
    else:
        y_part = f"-{year}" if year else ""
        canonical_key = f"{slug_base}{y_part}"

    # 'episode' was stored here before; it is not a catalog content type, and an
    # episode page describes a series, so the post is stamped series.
    media_type = "series" if page_kind in ("episode", "series") else "movie"

    return cleaned, year, season_num, episode_num, quality, languages, media_type, canonical_key


# --- DesiCinemas HTTP Client ---
class DesiCinemasClient:
    def __init__(self, request_interval: float = 0.2):
        self.request_interval = request_interval
        self._last_req_time = 0.0
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def _rate_limit(self):
        elapsed = time.time() - self._last_req_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_req_time = time.time()

    def get_text(self, url: str, referer: str = BASE_URL, timeout: float = 12.0) -> tuple[int, str, str, dict]:
        """Performs GET request returning (status_code, final_url, html_text, headers)."""
        self._rate_limit()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": referer,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                status = resp.status
                final_url = resp.geturl()
                content = resp.read().decode("utf-8", errors="ignore")
                headers = dict(resp.headers)
                return status, final_url, content, headers
        except urllib.error.HTTPError as e:
            err_content = e.read().decode("utf-8", errors="ignore") if e.fp else ""
            return e.code, e.geturl(), err_content, dict(e.headers)
        except Exception:
            return 0, url, "", {}

    def unwrap_trembed(self, trembed_url: str, referer: str = BASE_URL) -> list[dict]:
        """
        Unwraps DooPlay trembed iframe into stream sources:
        1. GET trembed iframe HTML
        2. Identify target player: peytonepre.com, vidsrcme.su, netu.ac, ok.ru, watchx.top, rpmplay.xyz, short.ink
        3. If peytonepre.com: unwrap Dean Edwards packed JS to obtain direct .m3u8 HLS stream
        """
        sources = []
        clean_trembed = trembed_url.replace("&#038;", "&")
        status, _, html_text, _ = self.get_text(clean_trembed, referer=referer, timeout=10.0)
        if status != 200 or not html_text:
            return sources

        # Find nested iframe URLs (case-insensitive)
        sub_iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE)

        for raw_ifr in sub_iframes:
            ifr = raw_ifr.strip()
            if not ifr or ifr.startswith("javascript:") or ifr.startswith("about:"):
                continue
            if ifr.startswith("//"):
                ifr = "https:" + ifr

            parsed = urllib.parse.urlparse(ifr)
            domain = parsed.netloc.lower()

            if "peytonepre.com" in domain:
                # Dean Edwards packed JWPlayer HLS stream
                p_status, _, p_html, _ = self.get_text(ifr, referer=clean_trembed, timeout=10.0)
                if p_status == 200 and p_html:
                    unpacked = unpack_dean_edwards(p_html)
                    # Extract m3u8
                    m3u8_links = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked)
                    for m3u8 in m3u8_links:
                        sources.append({
                            "source_name": "⚡ Peytonepre Direct HLS Stream",
                            "service": "peytonepre_hls",
                            "resource_id": parsed.path.split("/")[-1],
                            "source_url": ifr,
                            "final_url": m3u8,
                            "is_temporary": 1,
                        })

                # Fallback embed source
                sources.append({
                    "source_name": "▶ Peytonepre Player Embed",
                    "service": "peytonepre_embed",
                    "resource_id": parsed.path.split("/")[-1],
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

            elif "vidsrcme.su" in domain or "vidsrc" in domain:
                tmdb_m = re.search(r"tmdb=(\d+)", ifr)
                res_id = tmdb_m.group(1) if tmdb_m else parsed.path
                sources.append({
                    "source_name": "▶ VidSrc Me Player Embed",
                    "service": "vidsrc",
                    "resource_id": res_id,
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

            elif "netu.ac" in domain or "waaw.to" in domain:
                sources.append({
                    "source_name": "▶ Netu / Waaw Player Embed",
                    "service": "netu",
                    "resource_id": parsed.path.split("/")[-1],
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

            elif "ok.ru" in domain:
                sources.append({
                    "source_name": "▶ OK.ru Player Embed",
                    "service": "okru",
                    "resource_id": parsed.path.split("/")[-1],
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

            elif "watchx.top" in domain:
                sources.append({
                    "source_name": "▶ WatchX Player Embed",
                    "service": "watchx",
                    "resource_id": parsed.path.split("/")[-1],
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

            elif "rpmplay.xyz" in domain:
                hash_id = parsed.fragment or parsed.path
                sources.append({
                    "source_name": "▶ RPMPlay Player Embed",
                    "service": "rpmplay",
                    "resource_id": hash_id,
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

            elif "short.ink" in domain:
                sources.append({
                    "source_name": "🔗 Short.ink Gateway",
                    "service": "shortink",
                    "resource_id": parsed.path.split("/")[-1],
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

            else:
                sources.append({
                    "source_name": f"▶ {domain} Embed",
                    "service": "embed",
                    "resource_id": parsed.path.split("/")[-1] or domain,
                    "source_url": ifr,
                    "final_url": ifr,
                    "is_temporary": 0,
                })

        return sources


# --- HTML Content Extractor ---
def parse_desicinemas_content(content_html: str, url: str) -> tuple[str | None, str | None, str | None, str | None, str | None, list[str], list[str]]:
    """
    Parses DesiCinemas page HTML.
    Returns: (imdb_id, tmdb_id, poster_url, backdrop_url, synopsis, trembed_urls, direct_iframes)
    """
    imdb_id = None
    tmdb_id = None
    poster_url = None
    backdrop_url = None
    synopsis = None

    # IMDb ID
    imdb_m = re.search(r"imdb\.com/title/(tt\d+)", content_html, re.IGNORECASE)
    if imdb_m:
        imdb_id = imdb_m.group(1)

    # TMDB ID from vidsrc or links
    tmdb_m = re.search(r"tmdb=(\d+)", content_html)
    if tmdb_m:
        tmdb_id = tmdb_m.group(1)

    # TMDB Poster & Backdrop
    tmdb_imgs = re.findall(r'["\']((?:https?:)?//image\.tmdb\.org/t/p/[^"\']+)["\']', content_html)
    for raw_img in tmdb_imgs:
        img = ("https:" + raw_img) if raw_img.startswith("//") else raw_img
        if "/w1280/" in img or "backdrop" in img.lower():
            if not backdrop_url:
                backdrop_url = img
        elif not poster_url:
            poster_url = img

    # If poster is still empty but backdrop exists, or vice versa
    if tmdb_imgs and not poster_url:
        first = tmdb_imgs[0]
        poster_url = ("https:" + first) if first.startswith("//") else first

    # Fallback poster from local uploads
    if not poster_url:
        local_imgs = re.findall(r'<img[^>]+src=["\'](https://www.desicinemas.pk/wp-content/uploads/[^"\']+)["\']', content_html)
        if local_imgs:
            poster_url = local_imgs[0]

    # Synopsis
    desc_m = re.search(r'<div class="Description"><p[^>]*>(.*?)</p></div>', content_html, re.DOTALL)
    if desc_m:
        synopsis = re.sub(r"<[^>]*>", "", desc_m.group(1)).strip()

    # Director
    director = None
    dir_m = re.search(r'<p class="Director"><span>Director:</span>\s*(.*?)</p>', content_html, re.DOTALL | re.I)
    if dir_m:
        director = re.sub(r"<[^>]*>", "", dir_m.group(1)).strip()

    # Cast
    cast_names = None
    cast_m = re.search(r'<p class="Cast"><span>Cast:</span>\s*(.*?)</p>', content_html, re.DOTALL | re.I)
    if cast_m:
        cast_names = re.sub(r"<[^>]*>", "", cast_m.group(1)).strip()

    # Genres
    genres = None
    genre_m = re.search(r'<p class="Genre"><span>Genre:</span>\s*(.*?)</p>', content_html, re.DOTALL | re.I)
    if genre_m:
        genres = re.sub(r"<[^>]*>", "", genre_m.group(1)).strip()

    # Find DooPlay trembed iframes
    all_iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', content_html, re.IGNORECASE)
    trembed_urls = []
    direct_iframes = []

    for ifr in all_iframes:
        clean_ifr = ifr.replace("&#038;", "&").strip()
        if "trembed=" in clean_ifr:
            trembed_urls.append(clean_ifr)
        elif not clean_ifr.startswith("javascript:") and not clean_ifr.startswith("about:"):
            direct_iframes.append(clean_ifr)

    return imdb_id, tmdb_id, poster_url, backdrop_url, synopsis, director, cast_names, genres, trembed_urls, direct_iframes


# --- Database Layer ---
def _migrate_posts_provenance(conn: sqlite3.Connection) -> None:
    """Additive, idempotent repair of staging databases scraped before D1.

    The original posts table had no provenance columns at all, so 5,223 rows
    merged as source_site='unknown', and it stored the illegal media_type
    'episode'.  Only columns are added and empty values filled: canonical_key
    stays the primary key (SQLite cannot ALTER a primary key in, and
    merge_catalogs already reads rowid as the id), and raw_meta is left intact.
    """
    existing = {c[1] for c in conn.execute("PRAGMA table_info(posts);").fetchall()}
    for col in ("url", "slug", "source_site"):
        if col not in existing:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT;")

    # The scraper always wrote the page URL into raw_meta — reuse it as evidence.
    try:
        conn.execute(
            "UPDATE posts SET url = json_extract(raw_meta, '$.loc')"
            " WHERE (url IS NULL OR url = '') AND raw_meta IS NOT NULL"
            " AND json_valid(raw_meta) AND json_extract(raw_meta, '$.loc') IS NOT NULL;"
        )
    except sqlite3.Error:  # a SQLite build without the JSON extension
        for row_id, raw_meta in conn.execute(
            "SELECT rowid, raw_meta FROM posts WHERE (url IS NULL OR url = '') AND raw_meta IS NOT NULL;"
        ).fetchall():
            try:
                loc = (json.loads(raw_meta) or {}).get("loc")
            except (ValueError, TypeError):
                continue
            if loc:
                conn.execute("UPDATE posts SET url = ? WHERE rowid = ?;", (loc, row_id))
    for row_id, page_url in conn.execute(
        "SELECT rowid, url FROM posts WHERE (slug IS NULL OR slug = '') AND url IS NOT NULL AND url != '';"
    ).fetchall():
        conn.execute("UPDATE posts SET slug = ? WHERE rowid = ?;", (slug_from_url(page_url), row_id))
    conn.execute(
        "UPDATE posts SET source_site = ? WHERE source_site IS NULL OR source_site = '' OR source_site = 'unknown';",
        (SITE,),
    )
    for bad in [row[0] for row in conn.execute(
        "SELECT DISTINCT media_type FROM posts WHERE media_type IS NOT NULL;"
    ).fetchall()]:
        if bad in LEGAL_MEDIA_TYPES:
            continue
        conn.execute(
            "UPDATE posts SET media_type = ? WHERE media_type = ?;",
            (normalize_media_type(bad), bad),
        )


def init_staging_db(db_path: Path):
    """Initializes isolated SQLite staging database schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                raw_json TEXT,
                error_count INTEGER DEFAULT 0
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                canonical_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                clean_title TEXT NOT NULL,
                year INTEGER,
                media_type TEXT,
                poster_url TEXT,
                backdrop_url TEXT,
                imdb_id TEXT,
                tmdb_id TEXT,
                synopsis TEXT,
                genres TEXT,
                director TEXT,
                cast_names TEXT,
                languages TEXT,
                is_18_plus INTEGER DEFAULT 0,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                raw_meta TEXT,
                url TEXT,
                slug TEXT,
                source_site TEXT DEFAULT 'desicinemas'
            );
            """
        )
        # Migration check for existing databases
        existing_cols = [c[1] for c in conn.execute("PRAGMA table_info(posts);").fetchall()]
        for col in ["director", "cast_names", "genres", "languages"]:
            if col not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT;")
                except Exception:
                    pass
        _migrate_posts_provenance(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_canonical_key TEXT NOT NULL,
                label TEXT,
                quality TEXT,
                resolution TEXT,
                size_bytes INTEGER,
                codec TEXT,
                season_number INTEGER,
                episode_number INTEGER,
                audio_languages TEXT,
                bridge_url TEXT,
                FOREIGN KEY (post_canonical_key) REFERENCES posts(canonical_key)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                release_id INTEGER NOT NULL,
                source_name TEXT,
                service TEXT,
                resource_id TEXT,
                source_url TEXT,
                final_url TEXT,
                is_temporary INTEGER DEFAULT 0,
                quality TEXT,
                FOREIGN KEY (release_id) REFERENCES releases(id)
            );
            """
        )
        conn.commit()


def save_post_to_staging(db_path: Path, item_res: dict):
    """Atomically saves parsed post, releases, and resolved sources into staging SQLite DB."""
    loc = item_res.get("loc")
    if not loc:
        return

    with sqlite3.connect(str(db_path), timeout=30.0) as conn:
        cur = conn.cursor()

        if item_res.get("skipped"):
            # -1, never the retired 2: this page was visited but produced nothing,
            # and the pending query drains it again on the next run.
            cur.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ?;", (loc,))
            return

        if not item_res.get("success"):
            cur.execute(
                "UPDATE sitemap_cache SET error_count = error_count + 1 WHERE loc = ?;",
                (loc,),
            )
            return

        p = item_res["post"]
        page_url = p.get("url") or loc
        cur.execute(
            """
            INSERT INTO posts (canonical_key, title, clean_title, year, media_type, poster_url, backdrop_url, imdb_id, tmdb_id, synopsis, genres, director, cast_names, languages, is_18_plus, raw_meta, url, slug, source_site)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                clean_title = excluded.clean_title,
                year = COALESCE(excluded.year, posts.year),
                media_type = excluded.media_type,
                poster_url = COALESCE(excluded.poster_url, posts.poster_url),
                backdrop_url = COALESCE(excluded.backdrop_url, posts.backdrop_url),
                imdb_id = COALESCE(excluded.imdb_id, posts.imdb_id),
                tmdb_id = COALESCE(excluded.tmdb_id, posts.tmdb_id),
                synopsis = COALESCE(excluded.synopsis, posts.synopsis),
                genres = COALESCE(excluded.genres, posts.genres),
                director = COALESCE(excluded.director, posts.director),
                cast_names = COALESCE(excluded.cast_names, posts.cast_names),
                languages = COALESCE(excluded.languages, posts.languages),
                url = COALESCE(posts.url, excluded.url),
                slug = COALESCE(posts.slug, excluded.slug),
                source_site = excluded.source_site,
                scraped_at = CURRENT_TIMESTAMP;
            """,
            (
                p["canonical_key"],
                p["title"],
                p["clean_title"],
                p.get("year"),
                normalize_media_type(p.get("media_type")),
                p.get("poster_url"),
                p.get("backdrop_url"),
                p.get("imdb_id"),
                p.get("tmdb_id"),
                p.get("synopsis"),
                p.get("genres"),
                p.get("director"),
                p.get("cast_names"),
                p.get("languages"),
                p.get("is_18_plus", 0),
                json.dumps({"loc": loc}),
                page_url,
                p.get("slug") or slug_from_url(page_url),
                p.get("source_site") or SITE,
            ),
        )

        releases = item_res.get("releases", [])
        for rel in releases:
            cur.execute(
                """
                INSERT INTO releases (post_canonical_key, label, quality, resolution, size_bytes, codec, season_number, episode_number, audio_languages, bridge_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    p["canonical_key"],
                    rel.get("label"),
                    rel.get("quality"),
                    rel.get("resolution"),
                    rel.get("size_bytes"),
                    rel.get("codec"),
                    rel.get("season_number"),
                    rel.get("episode_number"),
                    rel.get("audio_languages"),
                    rel.get("bridge_url"),
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
                        rel_id,
                        src.get("source_name"),
                        src.get("service"),
                        src.get("resource_id"),
                        src.get("source_url"),
                        src.get("final_url"),
                        src.get("is_temporary", 0),
                        rel.get("quality"),
                    ),
                )

        cur.execute("UPDATE sitemap_cache SET scraped = 1 WHERE loc = ?;", (loc,))


# --- Scraper Worker ---
def scrape_post_item(item: tuple, client: DesiCinemasClient, unwrap_bridges: bool = True) -> dict | None:
    """Processes a single DesiCinemas item URL."""
    loc, lastmod, slug = item
    try:
        # Adult titles retained with is_18_plus flag; hidden only at presentation layer
        is_adult = 1 if is_adult_content(slug) else 0

        status, _, html_text, _ = client.get_text(loc, referer=BASE_URL, timeout=12.0)
        if status != 200 or not html_text:
            return {"loc": loc, "success": False, "reason": f"http_{status}"}

        # Extract title from <h1>
        title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL)
        raw_title = title_m.group(1).strip() if title_m else ""
        if not raw_title:
            return {"loc": loc, "success": False, "reason": "no_title"}

        if is_adult_content(raw_title):
            is_adult = 1

        # Normalize title
        clean_title, year, season_num, episode_num, quality, languages, media_type, canonical_key = clean_desicinemas_title(raw_title, loc)

        # Parse content
        imdb_id, tmdb_id, poster_url, backdrop_url, synopsis, director, cast_names, genres, trembed_urls, direct_iframes = parse_desicinemas_content(html_text, loc)

        # Resolve streams
        sources = []
        if unwrap_bridges:
            for tr_url in trembed_urls:
                sub_sources = client.unwrap_trembed(tr_url, referer=loc)
                sources.extend(sub_sources)

        for d_ifr in direct_iframes:
            sources.append({
                "source_name": "▶ Direct Page Embed",
                "service": "embed",
                "resource_id": d_ifr,
                "source_url": d_ifr,
                "final_url": d_ifr,
                "is_temporary": 0,
            })

        # Build release
        releases = []
        label = raw_title
        if quality:
            label = f"{clean_title} [{quality}]"

        releases.append({
            "label": label,
            "quality": quality or "HD",
            "resolution": "1080p" if quality == "1080P" else "720p",
            "size_bytes": None,
            "codec": None,
            "season_number": season_num,
            "episode_number": episode_num,
            "audio_languages": languages,
            "bridge_url": trembed_urls[0] if trembed_urls else (direct_iframes[0] if direct_iframes else None),
            "sources": sources,
        })

        return {
            "loc": loc,
            "success": True,
            "post": {
                "canonical_key": canonical_key,
                "title": raw_title,
                "clean_title": clean_title,
                "year": year,
                "media_type": media_type,
                "url": loc,
                "slug": slug_from_url(loc),
                "source_site": SITE,
                "poster_url": poster_url,
                "backdrop_url": backdrop_url,
                "imdb_id": imdb_id,
                "tmdb_id": tmdb_id,
                "synopsis": synopsis,
                "director": director,
                "cast_names": cast_names,
                "genres": genres,
                "languages": languages,
                "is_18_plus": is_adult,
            },
            "releases": releases,
        }
    except Exception as e:
        return {"loc": loc, "success": False, "reason": str(e)}


# --- Sitemap Ingestion ---
def sync_sitemaps(client: DesiCinemasClient, db_path: Path, max_sitemaps: int | None = None):
    """Discovers and caches movie, series, and episode URLs from DesiCinemas XML sitemaps."""
    print(f"[*] Fetching sitemap index -> {SITEMAP_INDEX_URL}...")
    status, _, index_xml, _ = client.get_text(SITEMAP_INDEX_URL, timeout=15.0)
    if status != 200 or not index_xml:
        print(f"[!] Failed to fetch sitemap index (HTTP {status})", flush=True)
        return

    sub_sitemaps = re.findall(r"<loc>(https://[^<]+-sitemap\d*\.xml)</loc>", index_xml)
    # Filter for movies, series, episodes
    target_sitemaps = [
        s for s in sub_sitemaps
        if any(k in s for k in ("movies-sitemap", "series-sitemap", "episodes-sitemap"))
    ]

    if max_sitemaps:
        target_sitemaps = target_sitemaps[:max_sitemaps]

    print(f"[*] Found {len(target_sitemaps)} relevant catalog sitemaps.", flush=True)

    init_staging_db(db_path)
    total_added = 0

    with sqlite3.connect(str(db_path)) as conn:
        for sitemap_url in target_sitemaps:
            print(f"  -> Ingesting {sitemap_url}...", flush=True)
            s_status, _, s_xml, _ = client.get_text(sitemap_url, referer=SITEMAP_INDEX_URL, timeout=15.0)
            if s_status != 200 or not s_xml:
                continue

            entries = re.findall(r"<loc>(https://[^<]+)</loc>(?:\s*<lastmod>([^<]*)</lastmod>)?", s_xml)
            for loc, lastmod in entries:
                # Exclude root index URLs
                if loc.rstrip("/").endswith(("/movies", "/series", "/episodes")):
                    continue

                slug = loc.rstrip("/").split("/")[-1]
                conn.execute(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped)
                    VALUES (?, ?, ?, 0)
                    ON CONFLICT(loc) DO UPDATE SET
                        lastmod = COALESCE(excluded.lastmod, sitemap_cache.lastmod);
                    """,
                    (loc, lastmod or None, slug),
                )
                total_added += 1
        conn.commit()

    print(f"[✓] Sitemap sync complete: {total_added:,} URLs queued in sitemap_cache.", flush=True)


# --- Crawler Execution Loop ---
def run_crawler(db_path: Path, workers: int = 4, delay: float = 0.25, limit: int | None = None, unwrap_bridges: bool = True):
    """Runs concurrent worker threads over pending sitemap items."""
    init_staging_db(db_path)

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        q = PENDING_SELECT
        if limit:
            q += f" LIMIT {int(limit)}"
        cur.execute(q, QUEUED_SCRAPE_STATES)
        pending = cur.fetchall()

    if not pending:
        print("[*] No pending items in sitemap_cache! Run with --sync-sitemaps first.", flush=True)
        return

    print(f"[*] Starting DesiCinemas crawler: {len(pending):,} queued | {workers} workers | delay {delay}s | unwrap={unwrap_bridges}", flush=True)

    client = DesiCinemasClient(request_interval=delay)
    scraped_count = 0
    failed_count = 0
    total_releases = 0
    total_sources = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(scrape_post_item, item, client, unwrap_bridges): item
            for item in pending
        }

        for future in as_completed(future_map):
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
                            total_sources += len(r.get("sources", []))
                    elif not res.get("skipped"):
                        failed_count += 1
            except Exception:
                failed_count += 1

            total_done = scraped_count + failed_count
            if total_done % 10 == 0 or total_done == len(pending):
                elapsed = max(0.1, time.time() - t0)
                speed = total_done / elapsed
                remaining = len(pending) - total_done
                eta_sec = int(remaining / speed) if speed > 0 else 0
                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_sec))
                print(
                    f"  [{total_done}/{len(pending)}] releases={total_releases:,} sources={total_sources:,} failed={failed_count} speed={speed:.2f} t/s ETA: {eta_str}",
                    flush=True,
                )

    elapsed = max(0.1, time.time() - t0)
    print(f"\n[✓] DesiCinemas crawler finished: {scraped_count:,} scraped, {failed_count} failed in {elapsed:.1f}s", flush=True)


# --- CLI Interface ---
def main():
    parser = argparse.ArgumentParser(description="DesiCinemas Scraper & DooPlay/Peytonepre HLS Resolver")
    parser.add_argument("--sync-sitemaps", action="store_true", help="Sync sitemap URLs into sitemap_cache")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Target SQLite staging database path")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent worker threads (default: 4)")
    parser.add_argument("--delay", type=float, default=0.25, help="Request rate delay in seconds (default: 0.25)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of posts to process")
    parser.add_argument("--max-sitemaps", type=int, default=None, help="Max sitemaps to ingest during sync")
    parser.add_argument("--no-unwrap", action="store_true", help="Store bridge URLs without immediately unwrapping")

    args = parser.parse_args()

    client = DesiCinemasClient(request_interval=args.delay)

    if args.sync_sitemaps:
        sync_sitemaps(client, args.db_path, max_sitemaps=args.max_sitemaps)

    run_crawler(
        args.db_path,
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        unwrap_bridges=not args.no_unwrap,
    )


if __name__ == "__main__":
    main()
