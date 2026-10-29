#!/usr/bin/env python3
"""
import_9xmovies.py — High-Performance 9xmovies Scraper & Bridge Unwrapper for Radd-Stream

Scrapes catalog from 9xmovies (https://9xmovie.bayern) via WordPress REST API,
parses high-resolution posters, IMDb IDs, multi-tier releases (1080p, 720p, 480p),
and unwraps linksddr.com bridges into redundant 10Gbps Google CDN, HubCloud,
FilePress, GoFile, Streamtape, and Cloudflare R2 direct stream mirrors.

Constraints:
  - 100% Python standard library only (zero external pip/npm packages).
  - Strict staging database isolation: writes solely to /home/ubuntu/radd-stream-data/9xmovies.db.
  - Zero Data Loss: preserves all releases and fallback gateway links even if bridges timeout.
  - WAL mode SQLite concurrency with 60s busy timeout.
"""

from __future__ import annotations

import argparse
import contextlib
import http.cookiejar
import html
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

# --- Constants ---
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/9xmovies.db")
BASE_URL = "https://9xmovie.bayern"
WP_API_URL = "https://9xmovie.bayern/wp-json/wp/v2/posts"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

STOP_REQUESTED = False

# sitemap_cache.scraped state machine, shared by every staging importer and by
# fast_fetch's crawler: 0 = queued, 1 = indexed, -1 = tried but nothing was
# indexable (needs review/retry).  The retired value 2 ("skipped") was written
# but never drained, so skipped pages were lost; the skip path now writes -1 and
# the pending query still accepts legacy 2 rows so none can strand in that state.
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug, raw_json FROM sitemap_cache WHERE scraped IN (?, ?)"
)


def sig_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("\n[!] Graceful shutdown requested. Finishing active tasks...", flush=True)


signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)


# --- HTTP Client & Bridge Unwrapper ---
class NineXMoviesClient:
    """HTTP client with cookie management and bridge unwrapping capabilities."""

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

    def get_json(self, url: str, referer: str = BASE_URL, timeout: float = 15.0) -> tuple[int, any, dict]:
        """Performs GET request returning parsed JSON."""
        status, _, text, headers = self.get_text(url, referer=referer, timeout=timeout)
        if status == 200 and text:
            try:
                return status, json.loads(text), headers
            except Exception:
                return status, None, headers
        return status, None, headers

    def unwrap_linksddr(self, bridge_url: str) -> list[dict]:
        """
        Unwraps linksddr.com/view/<TOKEN> gateway into direct streaming/download mirrors.
        Uses session cookie + CSRF token POST submission.
        """
        sources = []
        try:
            # 1. Initial GET to retrieve cookies and CSRF token
            status, final_url, html_doc, _ = self.get_text(
                bridge_url, referer=BASE_URL, timeout=10.0
            )
            if status != 200 or not html_doc:
                return sources

            csrf_match = re.search(
                r'name=[\'"](_csrf_token_[^\'"]+)[\'"]\s+value=[\'"]([^\'"]+)[\'"]',
                html_doc,
            )
            if not csrf_match:
                csrf_match = re.search(
                    r'name=[\'"]([^\'"]*csrf[^\'"]*)[\'"]\s+value=[\'"]([^\'"]+)[\'"]',
                    html_doc,
                    re.I,
                )

            if not csrf_match:
                return sources

            token_name, token_val = csrf_match.groups()
            post_data = urllib.parse.urlencode(
                {token_name: token_val, "_token": token_val}
            ).encode("utf-8")

            # 2. POST to gateway with CSRF token
            self._rate_limit()
            post_req = urllib.request.Request(
                bridge_url,
                data=post_data,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": bridge_url,
                    "Origin": "https://linksddr.com",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            with self.opener.open(post_req, timeout=12.0) as post_resp:
                post_html = post_resp.read().decode("utf-8", errors="ignore")

            # 3. Parse direct source links
            all_hrefs = re.findall(r'href=[\'"]([^\'"]+)[\'"]', post_html)
            seen = set()

            for h in all_hrefs:
                if not h.startswith("http") or h in seen:
                    continue
                seen.add(h)

                h_low = h.lower()
                if any(
                    x in h_low
                    for x in [
                        "css",
                        "js",
                        "favicon",
                        "register",
                        "login",
                        "money",
                        "faqs",
                        "contact",
                        "linksddr.com",
                        "privacy",
                        "terms",
                        "dmca",
                    ]
                ):
                    continue

                # Service categorization
                service = "direct"
                name = "🔗 Direct Stream"
                if "hubcloud" in h_low:
                    service = "hubcloud"
                    name = "⚡ HubCloud 10Gbps CDN"
                elif "hubdrive" in h_low:
                    service = "hubdrive"
                    name = "⚡ HubDrive Fast Direct"
                elif "filepress" in h_low:
                    service = "filepress"
                    name = "🚀 FilePress Cloud Drive"
                elif "1fichier" in h_low:
                    service = "1fichier"
                    name = "📁 1Fichier High-Speed"
                elif "gofile" in h_low:
                    service = "gofile"
                    name = "⚡ GoFile Direct Stream"
                elif "streamtape" in h_low:
                    service = "streamtape"
                    name = "📺 StreamTape Embed"
                elif "voe" in h_low:
                    service = "voe"
                    name = "📺 VOE High-Bitrate"
                elif "multiup" in h_low:
                    service = "multiup"
                    name = "🌐 MultiUp Mirrors"
                elif "megaup" in h_low:
                    service = "megaup"
                    name = "⚡ MegaUp Direct"
                elif "uploadflix" in h_low:
                    service = "uploadflix"
                    name = "📦 UploadFlix Mirror"
                elif "vikingfile" in h_low:
                    service = "vikingfile"
                    name = "🛡️ VikingFile Mirror"
                elif "uploadhub" in h_low:
                    service = "uploadhub"
                    name = "📦 UploadHub Direct"
                elif "desiupload" in h_low:
                    service = "desiupload"
                    name = "🚀 DesiUpload Fast CDN"
                elif "send.now" in h_low or "sendcm" in h_low:
                    service = "sendnow"
                    name = "⚡ SendNow Cloud"
                elif "frdl" in h_low:
                    service = "frdl"
                    name = "⚡ FRDL Direct"
                elif "hexload" in h_low:
                    service = "hexload"
                    name = "⚡ HexLoad High-Speed"
                elif "dailyuploads" in h_low:
                    service = "dailyuploads"
                    name = "📁 DailyUploads"
                elif "clicknupload" in h_low:
                    service = "clicknupload"
                    name = "⚡ ClicknUpload"
                elif "indishare" in h_low:
                    service = "indishare"
                    name = "⚡ IndiShare CDN"
                elif "hidan" in h_low:
                    service = "hidan"
                    name = "⚡ Hidan Fast Mirror"
                elif "ranoz" in h_low:
                    service = "ranoz"
                    name = "⚡ Ranoz Cloud"
                elif "vinovo" in h_low:
                    service = "vinovo"
                    name = "📺 Vinovo Stream"
                elif "dsvplay" in h_low:
                    service = "dsvplay"
                    name = "📺 DSVPlay Stream"
                elif "luluvid" in h_low or "luluvido" in h_low or "lulustream" in h_low:
                    service = "lulustream"
                    name = "📺 LuluStream Embed"
                elif "savefiles" in h_low:
                    service = "savefiles"
                    name = "📁 SaveFiles Direct"

                resource_id = h.rstrip("/").split("/")[-1]

                sources.append(
                    {
                        "source_name": name,
                        "service": service,
                        "resource_id": resource_id,
                        "source_url": h,
                        "final_url": h,
                        "is_temporary": 0,
                    }
                )

        except Exception:
            pass

        return sources


# --- Adult Content Filter ---
ADULT_KEYWORDS = {
    "18+", "erotic", "hotshots", "ullu", "kooku", "primeplay", "rabbit",
    "flizmovies", "hunters", "boommovies", "neonx", "besharams", "gupchup",
    "sex", "sexy", "porn", "adult", "sensual", "lust"
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


# --- Parsing Helpers ---
def parse_size_string(size_str: str) -> int | None:
    """Parses human readable size like '2.6GB' or '650MB' into bytes."""
    if not size_str:
        return None
    cleaned = re.sub(r"[^\d\.kmgtbKMGTB]", "", size_str).strip()
    m = re.match(r"^([\d\.]+)\s*([kmgtKMGT]?b?)$", cleaned, re.I)
    if not m:
        return None
    try:
        val_str = m.group(1).rstrip(".")
        val = float(val_str)
        unit = m.group(2).upper()
        if "G" in unit:
            return int(val * (1024**3))
        if "M" in unit:
            return int(val * (1024**2))
        if "K" in unit:
            return int(val * 1024)
        if "T" in unit:
            return int(val * (1024**4))
        return int(val)
    except Exception:
        return None


def extract_wp_post_metadata(content_html: str) -> dict:
    """
    Extracts rich metadata (director, cast_names, genres, languages, synopsis, rating)
    from standard WordPress movie post HTML (9xmovies, 10xflix, SSRMovies, Bolly4u).
    Zero external dependencies. Stdlib only.
    """
    if not content_html:
        return {}

    text = html.unescape(content_html)

    # 1. Director
    director = None
    d_m = re.search(r'(?:Director|Directed\s*by)[s]?\s*:\s*([^<\n]+)', text, re.I)
    if d_m:
        clean_d = re.sub(r'<[^>]+>', '', d_m.group(1)).strip()
        if clean_d and len(clean_d) < 150:
            director = clean_d

    # 2. Cast / Stars
    cast_names = None
    c_m = re.search(r'(?:Stars?|Star\s*Cast|Cast|Starring)\s*:\s*([^<\n]+)', text, re.I)
    if c_m:
        clean_c = re.sub(r'<[^>]+>', '', c_m.group(1)).strip()
        if clean_c and len(clean_c) < 300:
            cast_names = clean_c

    # 3. Genres
    genres = None
    g_m = re.search(r'Genre[s]?\s*:\s*([^<\n]+)', text, re.I)
    if g_m:
        clean_g = re.sub(r'<[^>]+>', '', g_m.group(1)).strip()
        if clean_g:
            raw_genres = [re.sub(r'[^a-zA-Z0-9\s-]', '', g).strip() for g in re.split(r'[,\|/]', clean_g)]
            clean_list = [g for g in raw_genres if g and len(g) > 1 and len(g) < 40]
            if clean_list:
                genres = json.dumps(clean_list)

    # 4. Languages
    languages = None
    l_m = re.search(r'Language[s]?\s*:\s*([^<\n]+)', text, re.I)
    if l_m:
        clean_l = re.sub(r'<[^>]+>', '', l_m.group(1)).strip()
        if clean_l and len(clean_l) < 100:
            languages = clean_l

    # 5. Synopsis / Storyline
    synopsis = None
    s_m = re.search(
        r'<(?:strong|b|span|h\d)[^>]*>\s*(?:Film\s*Story|Story|Synopsis|Plot|Storyline)[^<]*</(?:strong|b|span|h\d)>\s*[:\-–]?\s*([^<\n]+)',
        text,
        re.I,
    )
    if not s_m:
        s_m = re.search(
            r'(?:^|>)\s*(?:Film\s*Story|Story|Synopsis|Plot|Storyline)\s*[:\-–]\s*([^<\n]+)',
            text,
            re.I,
        )
    if s_m:
        clean_s = re.sub(r'<[^>]+>', '', s_m.group(1)).strip()
        clean_s = re.sub(r'^[:\-–\s]+', '', clean_s)
        if len(clean_s) > 15:
            synopsis = clean_s

    # 6. IMDb Rating
    rating = None
    r_m = re.search(r'IMDb\s*(?:Ratings?|Rating)?\s*:\s*([0-9\.]+)(?:/10)?', text, re.I)
    if r_m:
        try:
            rating = float(r_m.group(1))
        except ValueError:
            rating = None

    return {
        "director": director,
        "cast_names": cast_names,
        "genres": genres,
        "languages": languages,
        "synopsis": synopsis,
        "rating": rating,
    }


def clean_9xmovies_title(raw_title: str) -> tuple[str, int | None, int | None, str, str]:
    """
    Cleans 9xmovies post title to extract canonical title, release year, season, media_type, and slug.
    Example: 'Star Wars: Episode IX – The Rise of Skywalker (2019) Hindi ORG Dual Audio 1080p | 720p | 480p BluRay ESubs Download'
             -> ('Star Wars Episode IX The Rise of Skywalker', 2019, None, 'movie', 'star-wars-episode-ix-the-rise-of-skywalker-2019')
    """
    t = html.unescape(raw_title).strip()

    # Media type & Season detection
    season_num = None
    episode_num = None
    media_type = "movie"

    se_m = re.search(r"\bS(\d{1,2})E(\d{1,3})\b", t, re.I)
    if se_m:
        season_num = int(se_m.group(1))
        episode_num = int(se_m.group(2))
        media_type = "series"
    else:
        s_m = re.search(r"\bS(?:eason\s*)?(\d{1,2})\b", t, re.I)
        if s_m:
            season_num = int(s_m.group(1))
            media_type = "series"
        ep_m = re.search(r"\bEpisode\s*(\d+)\b", t, re.I)
        if ep_m:
            episode_num = int(ep_m.group(1))
            media_type = "series"

    if re.search(r"\b(web\s*series|complete\s*series|all\s*episodes?)\b", t, re.I):
        media_type = "series"
    if re.search(r"\bmovie\b", t, re.I):
        media_type = "movie"

    # Year detection
    year = None
    y_m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if y_m:
        year = int(y_m.group(1))

    # Strip parenthetical annotations and format buzzwords
    t_clean = re.sub(r"\[.*?\]|\(.*?\)", " ", t)
    t_clean = re.sub(
        r"\b(movie|dual\s*audio|org|uncut|web-dl|bluray|hdtc|hdts|hdrip|hevc|webrip|x264|x265|1080p|720p|480p|2160p|4k|complete|esubs|download|hindi|english|tamil|telugu)\b.*$",
        "",
        t_clean,
        flags=re.IGNORECASE,
    )
    if year:
        t_clean = re.sub(rf"\b{year}\b.*$", "", t_clean)

    t_clean = re.sub(r"[-–—:|]+", " ", t_clean)
    t_clean = re.sub(r"\s+", " ", t_clean).strip()
    clean_title = t_clean or raw_title

    # Canonical slug key
    slug_base = re.sub(r"[^a-z0-9]+", "-", clean_title.lower()).strip("-")
    if year:
        canonical_key = f"{slug_base}-{year}"
    else:
        canonical_key = slug_base

    return clean_title, year, season_num, media_type, canonical_key


def parse_9xmovies_content(
    content_html: str, post_title: str
) -> tuple[str | None, str | None, list[dict]]:
    """
    Parses 9xmovies post HTML to extract IMDb ID, high-res poster, and releases with linksddr links.
    """
    # 1. IMDb ID
    imdb_id = None
    imdb_m = re.search(r"\b(tt\d{7,10})\b", content_html)
    if imdb_m:
        imdb_id = imdb_m.group(1)

    # 2. High-res poster
    poster_url = None
    poster_m = re.search(
        r'<img[^>]+src=["\'](https?://(?:blogger\.googleusercontent\.com/img/b/|.*?\.(?:jpg|jpeg|png|webp)))["\']',
        content_html,
        re.I,
    )
    if poster_m:
        poster_url = poster_m.group(1)
        if "blogger.googleusercontent.com" in poster_url:
            poster_url = re.sub(r"/s\d+/", "/s1600/", poster_url)

    # 3. Detect season for series
    _, year, season_num, media_type, _ = clean_9xmovies_title(post_title)

    # 4. Extract releases by parsing HTML blocks with linksddr.com
    releases = []
    blocks = [b.strip() for b in re.split(r"</?(?:p|h\d|div)>", content_html) if b.strip()]

    seen_bridges = set()
    for i, b in enumerate(blocks):
        if "linksddr." in b and "/view/" in b:
            bridge_m = re.search(
                r'href=[\'"](https?://linksddr\.[a-z]+/view/[A-Za-z0-9_-]+)[\'"]', b
            )
            if not bridge_m:
                continue
            raw_bridge_url = bridge_m.group(1)
            # Canonicalize to linksddr.com
            bridge_url = re.sub(r'https?://linksddr\.[a-z]+/', 'https://linksddr.com/', raw_bridge_url)
            if bridge_url in seen_bridges:
                continue
            seen_bridges.add(bridge_url)

            # Inspect previous block for resolution and size
            prev_block = blocks[i - 1] if i > 0 else ""
            clean_prev = re.sub(r"<[^>]+>", "", prev_block)

            # Quality detection
            q_m = re.search(r"\b(4K|2160p|1080p|720p|480p)\b", clean_prev, re.I)
            if not q_m:
                q_m = re.search(r"\b(4K|2160p|1080p|720p|480p)\b", b, re.I)
            quality = q_m.group(1).upper() if q_m else "720P"

            # Size detection
            size_m = re.search(r"\[([\d\.]+\s*(?:GB|MB|gb|mb))\]", clean_prev)
            size_bytes = parse_size_string(size_m.group(1)) if size_m else None

            # Codec
            codec = (
                "hevc"
                if any(x in clean_prev.lower() for x in ["hevc", "x265", "10bit"])
                else "x264"
            )

            releases.append(
                {
                    "label": f"{quality} {codec.upper()} {size_m.group(1) if size_m else ''}".strip(),
                    "quality": quality,
                    "resolution": quality.lower(),
                    "size_bytes": size_bytes,
                    "season_number": season_num,
                    "episode_number": None,
                    "audio_languages": "Hindi"
                    if "hindi" in post_title.lower()
                    else None,
                    "codec": codec,
                    "bridge_url": bridge_url,
                }
            )

    return imdb_id, poster_url, releases


# --- Database Layer ---
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


def init_staging_db(db_path: Path):
    """Initializes schema in dedicated isolated staging database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                site TEXT DEFAULT '9xmovies',
                raw_json TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_key TEXT UNIQUE,
                title TEXT NOT NULL,
                original_title TEXT,
                year INTEGER,
                media_type TEXT DEFAULT 'movie',
                imdb_id TEXT,
                tmdb_id INTEGER,
                poster_url TEXT,
                synopsis TEXT,
                genres TEXT,
                cast_names TEXT,
                director TEXT,
                languages TEXT,
                site TEXT DEFAULT '9xmovies',
                post_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_canonical_key TEXT,
                label TEXT,
                quality TEXT,
                resolution TEXT,
                size_bytes INTEGER,
                codec TEXT,
                season_number INTEGER,
                episode_number INTEGER,
                audio_languages TEXT,
                bridge_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_canonical_key) REFERENCES posts(canonical_key) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_9x_posts_key ON posts(canonical_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_9x_rels_post ON releases(post_canonical_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_9x_src_rel ON sources(release_id);")

        # Auto-migration for schema changes
        existing_cols = [c[1] for c in cur.execute("PRAGMA table_info(posts);").fetchall()]
        for col in ["cast_names", "director", "languages"]:
            if col not in existing_cols:
                try:
                    cur.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT;")
                except Exception:
                    pass
        if "is_18_plus" not in existing_cols:
            try:
                cur.execute("ALTER TABLE posts ADD COLUMN is_18_plus INTEGER DEFAULT 0;")
            except Exception:
                pass


def save_post_to_staging(db_path: Path, result: dict):
    """Atomically saves extracted post, releases, and direct sources to staging DB."""
    loc = result["loc"]
    if result.get("skipped"):
        with get_db_connection(db_path) as conn:
            conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ?;", (loc,))
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
            INSERT INTO posts (canonical_key, title, original_title, year, media_type, imdb_id, poster_url, synopsis, genres, cast_names, director, languages, is_18_plus, site, post_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title=excluded.title,
                original_title=excluded.original_title,
                year=COALESCE(excluded.year, posts.year),
                media_type=excluded.media_type,
                imdb_id=COALESCE(excluded.imdb_id, posts.imdb_id),
                poster_url=COALESCE(excluded.poster_url, posts.poster_url),
                synopsis=COALESCE(excluded.synopsis, posts.synopsis),
                genres=COALESCE(excluded.genres, posts.genres),
                cast_names=COALESCE(excluded.cast_names, posts.cast_names),
                director=COALESCE(excluded.director, posts.director),
                languages=COALESCE(excluded.languages, posts.languages),
                is_18_plus=MAX(posts.is_18_plus, excluded.is_18_plus),
                post_url=excluded.post_url,
                updated_at=CURRENT_TIMESTAMP;
            """,
            (
                p["canonical_key"],
                p["title"],
                p["original_title"],
                p["year"],
                p["media_type"],
                p["imdb_id"],
                p["poster_url"],
                p.get("synopsis"),
                p.get("genres"),
                p.get("cast_names"),
                p.get("director"),
                p.get("languages"),
                p.get("is_18_plus", 0),
                p["site"],
                p["post_url"],
            ),
        )

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
def scrape_post_item(
    item: tuple, client: NineXMoviesClient, unwrap_bridges: bool = True
) -> dict | None:
    """Processes a single 9xmovies post item, parsing releases and unwrapping linksddr bridges."""
    loc, lastmod, slug, raw_json_str = item
    try:
        if not raw_json_str:
            return None

        p_data = json.loads(raw_json_str)
        raw_title = p_data.get("title", {}).get("rendered", "")
        content_html = p_data.get("content", {}).get("rendered", "")

        if not raw_title or not content_html:
            return None

        is_adult = 1 if (is_adult_content(raw_title) or is_adult_content(slug)) else 0

        # Clean title & detect year
        clean_title, year, season_num, media_type, canonical_key = clean_9xmovies_title(
            raw_title
        )

        # Parse IMDb, poster, and releases
        imdb_id, poster_url, releases_data = parse_9xmovies_content(content_html, raw_title)
        if not releases_data:
            return {"loc": loc, "success": False, "reason": "no_releases"}

        # Unwrap bridge URLs
        resolved_releases = []
        for rel in releases_data:
            bridge_url = rel.get("bridge_url")
            sources = []

            if bridge_url and unwrap_bridges:
                sources = client.unwrap_linksddr(bridge_url)

            # Zero Data Loss: Preserve gateway mirror if unwrap yields 0 or unwrap is disabled
            if not sources and bridge_url:
                sources = [
                    {
                        "source_name": "🔗 LinksDDR Gateway",
                        "service": "linksddr",
                        "resource_id": bridge_url.split("/")[-1],
                        "source_url": bridge_url,
                        "final_url": bridge_url,
                        "is_temporary": 0,
                    }
                ]

            rel_copy = dict(rel)
            rel_copy["sources"] = sources
            resolved_releases.append(rel_copy)

        meta = extract_wp_post_metadata(content_html)

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
                "synopsis": meta.get("synopsis"),
                "genres": meta.get("genres"),
                "cast_names": meta.get("cast_names"),
                "director": meta.get("director"),
                "languages": meta.get("languages"),
                "site": "9xmovies",
                "post_url": loc,
                "is_18_plus": is_adult,
            },
            "releases": resolved_releases,
        }
    except Exception as e:
        return {"loc": loc, "success": False, "reason": str(e)}


# --- Bulk API Ingestion ---
def sync_api_catalog(
    client: NineXMoviesClient, db_path: Path, max_pages: int | None = None
) -> int:
    """
    Syncs full 9xmovies catalog into staging SQLite database via WordPress REST API.
    Uses per_page=100 bulk ingestion (~20.3k titles in ~204 requests).
    """
    init_staging_db(db_path)
    print(f"[*] Starting 9xmovies API sync (per_page=100) -> {db_path}...", flush=True)

    page = 1
    total_new = 0
    total_existing = 0
    total_adult = 0
    consecutive_empty_new = 0
    total_posts = 0

    with get_db_connection(db_path) as conn:
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
        code, posts, headers = client.get_json(url, timeout=15.0)

        if code != 200 or not posts or not isinstance(posts, list):
            if code == 400:
                print(f"[✓] End of WP REST API pagination reached at page {page - 1}.", flush=True)
            else:
                print(f"[!] WP REST API returned HTTP {code} on page {page}.", flush=True)
            break

        if page == 1:
            total_posts = int(headers.get("x-wp-total", 0) or 0)
            total_pages = int(headers.get("x-wp-totalpages", 0) or 0)
            print(
                f"[*] Total catalog size: {total_posts:,} posts across {total_pages:,} pages.",
                flush=True,
            )

        batch_records = []
        page_new = 0
        for p in posts:
            loc = p.get("link")
            lastmod = p.get("modified")
            slug = p.get("slug")
            raw_title = p.get("title", {}).get("rendered", "")
            raw_json_str = json.dumps(p)

            if not loc:
                continue

            if (slug and slug in existing_slugs) or (loc in existing_locs):
                total_existing += 1
                continue

            is_adult = is_adult_content(raw_title) or is_adult_content(slug or "")
            scraped_val = 0
            if is_adult:
                total_adult += 1
            page_new += 1
            total_new += 1

            batch_records.append((loc, lastmod, slug, scraped_val, "9xmovies", raw_json_str))
            if slug:
                existing_slugs.add(slug)
            existing_locs.add(loc)

        if batch_records:
            with get_db_connection(db_path) as conn:
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

        print(f"  [Page {page:3d}] Found {page_new} brand new, {total_adult} adult skipped, {len(posts) - page_new} existing (Cumulative New: {total_new:,})", flush=True)

        if page_new == 0:
            consecutive_empty_new += 1
            if max_pages is None and consecutive_empty_new >= 3:
                print(f"[*] 3 consecutive pages with 0 new titles reached. Database is fully up-to-date with live catalog. Stopping sync.", flush=True)
                break
        else:
            consecutive_empty_new = 0

        page += 1

    print(
        f"[✓] 9xmovies API sync finished: {total_new:,} brand new titles added to {db_path.name} ({total_existing:,} existing skipped, {total_adult:,} adult titles flagged and still queued).",
        flush=True,
    )
    return total_new


# --- Concurrent Crawler Engine ---
def run_crawler(
    db_path: Path,
    workers: int = 5,
    delay: float = 0.2,
    limit: int | None = None,
    unwrap_bridges: bool = True,
):
    """Multi-threaded concurrent crawler consuming pending titles from sitemap_cache."""
    init_staging_db(db_path)
    client = NineXMoviesClient(request_interval=delay)

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        query = PENDING_SELECT
        if limit:
            query += f" LIMIT {int(limit)}"
        cur.execute(query, QUEUED_SCRAPE_STATES)
        pending = cur.fetchall()

    if not pending:
        print("[✓] Zero pending titles to scrape in sitemap_cache.", flush=True)
        return

    print(
        f"[*] Starting 9xmovies crawler: {len(pending)} titles queued | {workers} workers | delay {delay}s | unwrap={unwrap_bridges}",
        flush=True,
    )
    t0 = time.time()
    scraped_count = 0
    failed_count = 0
    total_releases = 0
    total_sources = 0

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
    print(
        f"\n[✓] 9xmovies crawler finished: {scraped_count:,} scraped, {failed_count} failed in {elapsed:.1f}s",
        flush=True,
    )


def enrich_existing_metadata(db_path: Path):
    """
    Backfills/enriches metadata (director, cast_names, genres, languages, synopsis)
    for all existing posts in staging database from cached raw_json.
    Also re-classifies generic direct sources into specific file hosts.
    Runs 100% offline.
    """
    init_staging_db(db_path)
    print(f"[*] Starting offline metadata enrichment for {db_path}...", flush=True)
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT loc, raw_json FROM sitemap_cache WHERE raw_json IS NOT NULL;")
        rows = cur.fetchall()
        print(f"[*] Found {len(rows):,} cached post entries to process.", flush=True)

        updated = 0
        for loc, raw_json_str in rows:
            try:
                p_data = json.loads(raw_json_str)
                raw_title = p_data.get("title", {}).get("rendered", "")
                content_html = p_data.get("content", {}).get("rendered", "")
                if not content_html or not raw_title:
                    continue

                clean_title, year, season_num, media_type, canonical_key = clean_9xmovies_title(raw_title)
                meta = extract_wp_post_metadata(content_html)

                cur.execute(
                    """
                    UPDATE posts SET
                        synopsis = COALESCE(?, synopsis),
                        genres = COALESCE(?, genres),
                        cast_names = COALESCE(?, cast_names),
                        director = COALESCE(?, director),
                        languages = COALESCE(?, languages)
                    WHERE canonical_key = ?;
                    """,
                    (
                        meta.get("synopsis"),
                        meta.get("genres"),
                        meta.get("cast_names"),
                        meta.get("director"),
                        meta.get("languages"),
                        canonical_key,
                    ),
                )
                if cur.rowcount > 0:
                    updated += 1
            except Exception:
                continue

        # Re-classify generic direct sources into specific hosts
        source_rewrites = [
            ("%uploadhub%", "uploadhub", "📦 UploadHub Direct"),
            ("%desiupload%", "desiupload", "🚀 DesiUpload Fast CDN"),
            ("%send.now%", "sendnow", "⚡ SendNow Cloud"),
            ("%sendcm%", "sendnow", "⚡ SendNow Cloud"),
            ("%frdl.%", "frdl", "⚡ FRDL Direct"),
            ("%hexload%", "hexload", "⚡ HexLoad High-Speed"),
            ("%dailyuploads%", "dailyuploads", "📁 DailyUploads"),
            ("%indishare%", "indishare", "⚡ IndiShare CDN"),
            ("%hidan.%", "hidan", "⚡ Hidan Fast Mirror"),
            ("%ranoz.%", "ranoz", "⚡ Ranoz Cloud"),
            ("%clicknupload%", "clicknupload", "⚡ ClicknUpload"),
            ("%vinovo.%", "vinovo", "📺 Vinovo Stream"),
            ("%dsvplay.%", "dsvplay", "📺 DSVPlay Stream"),
            ("%luluvid%", "lulustream", "📺 LuluStream Embed"),
            ("%luluvido%", "lulustream", "📺 LuluStream Embed"),
            ("%savefiles.%", "savefiles", "📁 SaveFiles Direct"),
        ]
        src_updated = 0
        for pattern, srv, name in source_rewrites:
            cur.execute(
                "UPDATE sources SET service = ?, source_name = ? WHERE service = 'direct' AND source_url LIKE ?;",
                (srv, name, pattern),
            )
            src_updated += cur.rowcount

        print(f"[✓] Metadata enrichment complete: {updated:,} posts updated, {src_updated:,} sources re-classified.", flush=True)


# --- CLI Interface ---
def main():
    parser = argparse.ArgumentParser(description="9xmovies Importer & Bridge Unwrapper")
    parser.add_argument(
        "--sync-api", action="store_true", help="Sync WP REST API posts into sitemap_cache"
    )
    parser.add_argument(
        "--enrich-metadata",
        action="store_true",
        help="Enrich existing posts table with cast/director/genres/synopsis from cached raw_json",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Target SQLite staging database path",
    )
    parser.add_argument(
        "--workers", type=int, default=5, help="Concurrent worker threads (default: 5)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.2, help="Request rate delay in seconds (default: 0.2)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of posts to process"
    )
    parser.add_argument(
        "--max-pages", type=int, default=None, help="Max API pages to ingest during sync"
    )
    parser.add_argument(
        "--no-unwrap",
        action="store_true",
        help="Store bridge URLs without immediately unwrapping via HTTP POST",
    )

    args = parser.parse_args()

    client = NineXMoviesClient(request_interval=args.delay)

    if args.enrich_metadata:
        enrich_existing_metadata(args.db_path)
        return

    if args.sync_api:
        sync_api_catalog(client, args.db_path, max_pages=args.max_pages)

    run_crawler(
        args.db_path,
        workers=args.workers,
        delay=args.delay,
        limit=args.limit,
        unwrap_bridges=not args.no_unwrap,
    )


if __name__ == "__main__":
    main()
