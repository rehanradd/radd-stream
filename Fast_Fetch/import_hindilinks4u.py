#!/usr/bin/env python3
"""
import_hindilinks4u.py — Dedicated staging scraper for Hindilinks4u.

Zero-dependency (stdlib-only) crawler for https://www.hindilinks4u.zip
(the .pink mirror sits behind a Cloudflare JS challenge and is not used).

Pipeline:
  1. --sync-sitemap  : sitemap_index.xml -> post-sitemap*.xml -> sitemap_cache
  2. crawl (default) : fetch each post page, extract metadata + video_tabs
                       watch servers + any download mirrors, store into the
                       isolated hindilinks4u.db staging database.

18+ titles are STORED with is_18_plus=1 (never skipped) per project rule;
presentation surfaces filter them out.
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

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch
from config import staging_db_path
from domain_resolver import get_active_base_url

DEFAULT_BASE_URL = "https://www.hindilinks4u.zip"
SITE_NAME = "hindilinks4u"
DB_PATH = staging_db_path("hindilinks4u")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MIN_REQUEST_DELAY = 0.3
# One core, and the API server shares it: wait for the writer lock instead of
# raising "database is locked" and taking the whole crawl down with it.
SQLITE_BUSY_TIMEOUT = 30

EMBED_HOSTS = (
    "playmogo", "mixdrop", "streamtape", "upcloud", "vidcloud", "vodstream",
    "superplay", "hdvhls", "jhlink", "dailyupload", "vidbom", "vidhide",
    "filemoon", "doodstream", "embay", "mcloud", "hitlink", "smoov",
    "rabbitstream", "journeywatchers", "vidsrc", "openload", "fmovies",
    # Added 2026-10-23: hosts used by the site's pre-`video_tabs` layout.
    # Old posts point every "Server N" button at these two hosts, and the
    # generic sweep below silently dropped them (see the 3,673-row failure
    # audit in Fast_Fetch/CONTINUITY.md).
    "filmshowonline", "dailymotion",
)
SOCIAL_HOSTS = (
    "facebook", "twitter", "instagram", "t.me", "telegram", "whatsapp",
    "pinterest", "linkedin", "youtube", "google", "gstatic", "gravatar",
    "wordpress", "gmpg", "w3.org", "doubleclick",
)
# Site-wide advertising block that every Hindilinks4u post carries. None of
# these hosts is a watch/download source for the title on the page.
PORN_SPAM_HOSTS = (
    "mydesi", "eromhub", "thotsking", "urdesi", "sexarebe", "egyzeb",
    "erome", "bokepking", "okxxx7", "fapello", "xnxxxhd", "bokepasar",
    "desi_leaked", "pakiyan", "bangbros",
)

# Marker strings of an interstitial bot-check page. We only RECORD that we were
# served one (cause "blocked: challenge") — we never try to solve or bypass it.
CHALLENGE_MARKERS = (
    "just a moment", "cf-browser-verification", "attention-required",
    "checking your browser", "cf_chl_", "turnstile", "you have been blocked",
    "error 1020", "enable javascript and cookies to continue",
)

# Failure vocabulary, layered on the SHARED core in fast_fetch.py so the crawler
# and the operator read ONE classification everywhere. This site used to park
# every failure at scraped=-1 forever and call "page has no links yet" permanent;
# a re-drain then re-marked the same recoverable parser-gap pages -1 for good.
# The live probes say otherwise: sampled -1 URLs answer HTTP 200 with content the
# legacy-layout extractor recovers, so those pages are TRANSIENT, not dead.
#
# PERMANENT = the PAGE itself says it will never work (gone upstream, not a post
# at all). Parked on the first sighting via fast_fetch.crawl_attempt_state().
PERMANENT_CAUSES = frozenset(fast_fetch.PERMANENT_CRAWL_CAUSES) | {
    "skipped: not_a_post",   # site spelling of the core 'not_a_post' skip
}

# TRANSIENT = our bad luck or a parser gap a later pass can heal: transport /
# timeout / 403 / 429 / 5xx / an interstitial bot-check, a title we failed to
# parse, or a live post whose watch links have not been published yet. These
# spend the shared retry budget (fast_fetch.MAX_CRAWL_ATTEMPTS) and stay
# selectable by crawl_queue() until that budget runs out. http_403_forbidden and
# blocked_challenge are already in the core transient set; the names below are
# the ones this site actually emits.
TRANSIENT_CAUSES = frozenset(fast_fetch.TRANSIENT_CRAWL_CAUSES) | {
    "no_sources_on_page",    # title parsed, upstream published no link *yet*
    "parse_no_title",        # page drifted shape — recover on a re-crawl
    "blocked: challenge",    # site spelling of the core 'blocked_challenge'
    # _http_cause() emits the per-code spelling, not the core 'http_5xx' bucket:
    "http_500_upstream_error",
    "http_502_upstream_error",
    "http_503_upstream_error",
    "http_504_upstream_error",
    # booking/save problems are OUR contention, never a statement about the page:
    "sqlite_locked",
    "sqlite_error",
    "save_rejected",
    "worker_exception",
}

# Consecutive host-refused / transport failures that end a pass early. Without a
# fuse a single dark-host run manufactures fresh -1s at full speed (one observed
# pass produced 1,324 in a row) instead of stopping while the domain is down.
SITE_DARK_THRESHOLD = 25

STOP_REQUESTED = False


def sig_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("\n[!] Stop signal received. Finishing in-flight items...", flush=True)


signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)


def get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class Hindilinks4uClient:
    """Rate-limited HTTP client with retries for the Hindilinks4u WordPress site."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, request_interval: float = 0.3, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.request_interval = max(MIN_REQUEST_DELAY, request_interval)
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
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        elif url.startswith(self.base_url):
            headers["Referer"] = self.base_url + "/"

        for attempt in range(self.retries):
            if STOP_REQUESTED:
                return 0, url, ""
            self._wait()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return resp.status, resp.geturl(), resp.read().decode(charset, errors="replace")
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    return e.code, url, ""
                if attempt == self.retries - 1:
                    return e.code, url, ""
            except Exception:
                if attempt == self.retries - 1:
                    return 0, url, ""
        return 0, url, ""


def init_staging_db(db_path: Path):
    """Creates the isolated staging database schema for Hindilinks4u (zero data loss)."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                site TEXT DEFAULT 'hindilinks4u',
                raw_json TEXT,
                attempts INTEGER DEFAULT 0,
                last_attempt REAL DEFAULT NULL,
                last_cause TEXT DEFAULT NULL
            );

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
                site TEXT DEFAULT 'hindilinks4u',
                post_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

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
        """)
        # Why a row failed and how many times we asked. These are plain ADD
        # COLUMNs, guarded by PRAGMA so the migration is idempotent and never
        # raises on a DB that already has them. Every CREATE INDEX that could
        # reference one of these columns runs AFTER this block (the project's
        # known defect class: an index pointing at a column a later ALTER adds).
        sm_cols = {c[1] for c in conn.execute("PRAGMA table_info(sitemap_cache);").fetchall()}
        if "attempts" not in sm_cols:
            conn.execute("ALTER TABLE sitemap_cache ADD COLUMN attempts INTEGER DEFAULT 0")
        if "last_attempt" not in sm_cols:
            conn.execute("ALTER TABLE sitemap_cache ADD COLUMN last_attempt REAL DEFAULT NULL")
        if "last_cause" not in sm_cols:
            conn.execute("ALTER TABLE sitemap_cache ADD COLUMN last_cause TEXT DEFAULT NULL")

        # Index creation happens last, once every column they touch is present.
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_sm_scraped ON sitemap_cache(scraped);
            CREATE INDEX IF NOT EXISTS idx_sm_retry ON sitemap_cache(scraped, attempts);
            CREATE INDEX IF NOT EXISTS idx_posts_canonical ON posts(canonical_key);
            CREATE INDEX IF NOT EXISTS idx_releases_post_id ON releases(post_id);
            CREATE INDEX IF NOT EXISTS idx_sources_release_id ON sources(release_id);
        """)
        conn.commit()


def parse_size_to_bytes(size_str: str | None) -> int | None:
    if not size_str:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB)", size_str, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    factor = {"GB": 1024**3, "MB": 1024**2, "KB": 1024}[unit]
    return int(val * factor)


_HL4U_NOISE = (
    r"1080p|720p|480p|2160p|4k|web-dl|webrip|bluray|hdrip|dvdrip|hdtc|un-?cut|"
    r"dual audio|multi audio|hindi dubbed|hindi|english|tamil|telugu|kannada|malayalam|"
    r"punjabi|marathi|all episodes|complete|full movie|season \d+|s\d+|ep\s*\d+|"
    r"episode\s*\d+|grand premiere|zee5|netflix|amazon prime|amzn|hotstar|jio|disney\+?|"
    r"hd\b|4k\b|dubbing|"
    r"realitykings|tushy|vixen|blacked|wankz|lustery|moodyz|iuliian|primeplay|kooku|hotshots|originals"
)


def clean_hl4u_title(raw_title: str) -> tuple[str, int | None, str]:
    """Cleans a Hindilinks4u page title into (clean_title, year, canonical_key)."""
    clean = html.unescape(raw_title or "")
    clean = re.split(r"\s*[-|–]\s*Hindi[Ll]inks", clean)[0]
    clean = re.sub(r"\s*Watch Free Movies.*$", "", clean, flags=re.I).strip()

    year = None
    y_m = re.search(r"\b(19|20)\d{2}\b", clean)
    if y_m:
        year = int(y_m.group(0))
        # Drop the year with its brackets even when the closing bracket never
        # arrives (site truncates long titles mid-parenthesis).
        clean = re.sub(r"[\(\[\{]\s*" + str(year) + r"\s*[\)\]\}]?", " ", clean)
        clean = re.sub(r"[\(\[\{]\s*" + str(year) + r"\s*$", " ", clean)
        clean = re.sub(r"\s*\b" + str(year) + r"\b\s*", " ", clean)

    clean = re.sub(r"(?<![A-Za-z0-9])\b(?:" + _HL4U_NOISE + r")\b.*$", "", clean, flags=re.I)
    clean = re.sub(r"[\(\[\]\{\}<>&]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -:|·•")
    if not clean:
        clean = html.unescape(raw_title or "").strip()

    canonical_key = fast_fetch.generate_canonical_key(clean, year)
    return clean, year, canonical_key


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "").lower()
    except ValueError:
        return ""


def looks_blocked(page: str) -> bool:
    """True when the body is an interstitial bot-check instead of the post.

    Detection only: the crawler records the cause and moves on. It never
    attempts to solve, spoof, or otherwise bypass the check.
    """
    if not page:
        return False
    head = page[:12000].lower()
    return any(m in head for m in CHALLENGE_MARKERS)


def is_post_url(loc: str) -> bool:
    """False for queued rows that are not a title page (site root, feeds, taxonomy)."""
    path = urllib.parse.urlparse(loc).path
    if path in ("", "/"):
        return False
    return not any(seg in path for seg in ("/category/", "/tag/", "/author/", "/feed/", "/page/"))


_LEGACY_LABEL_RE = re.compile(
    r"<strong>\s*((?:Server|Episode|Part)\s*[0-9IVX]+[^<]{0,60})", re.I
)
# Regions of the post body that are never this title's own sources.
_LEGACY_STOP_MARKERS = ('<div id="extras"', "You may also like", "Click Here")


def extract_hl4u_legacy_servers(entry_html: str) -> list[dict]:
    """
    Recovers the site's pre-`video_tabs` layout, which the tab parser cannot see:

        <p><strong>Server 1 – Youtube</strong></p>
        <p><a href="http://www.filmshowonline.net/videos/192588/">Watch Full Movie</a></p>

    Those embed hosts are not in the tab list and the generic sweep drops them
    with the social/spam anchors, so every old post used to be filed as a
    scrape failure. Added 2026-10-23 after auditing the 3,673 `scraped=-1` rows.
    """
    if not entry_html:
        return []
    body = entry_html
    for stop in _LEGACY_STOP_MARKERS:
        cut = body.find(stop)
        if cut > 0:
            body = body[:cut]

    labels = list(_LEGACY_LABEL_RE.finditer(body))
    if not labels:
        return []

    releases: list[dict] = []
    seen: set[str] = set()
    for idx, m in enumerate(labels):
        start = m.end()
        stop = labels[idx + 1].start() if idx + 1 < len(labels) else len(body)
        segment = body[start:min(stop, start + 1500)]
        label_text = re.sub(r"<[^>]+>", " ", m.group(1))
        label_text = re.sub(r"\s+", " ", html.unescape(label_text)).strip(" -–\t")
        for href, anchor_html in re.findall(
            r'<a[^>]+href=["\']([^"\'\s<>]+)["\'][^>]*>(.*?)</a>', segment, re.S | re.I
        ):
            href = html.unescape(href.strip())
            if not href.startswith("http") or href in seen:
                continue
            host = _host_of(href)
            if not host or "hindilinks4u" in host or any(s in host for s in PORN_SPAM_HOSTS):
                continue
            anchor_text = re.sub(r"<[^>]+>", "", anchor_html).strip() or "Watch"
            full_label = label_text if anchor_text.lower() in ("watch full movie", "watch") \
                else f"{label_text} · {anchor_text}"
            seen.add(href)
            q_m = re.search(r"\b(2160p|1080p|720p|480p)\b", full_label, re.I)
            releases.append({
                "label": full_label[:80],
                "quality": (q_m.group(1).lower() if q_m else "720p"),
                "resolution": (q_m.group(1).lower() if q_m else "720p"),
                "size_bytes": None,
                "season_number": None,
                "episode_number": None,
                "codec": "x264",
                "bridge_url": href,
                "service": host.split(".")[0],
                "source_name": f"▶ {full_label[:60]} [{host}]",
            })
    return releases


def extract_hl4u_servers(entry_html: str, post_url: str) -> list[dict]:
    """
    Extracts watch/download sources from the post content:
      - the legacy <strong>Server N – Host</strong> + anchor block layout
      - <ul id="video_tabs"> Server N tabs (primary embeds)
      - any remaining external anchors on known embed/download hosts
    """
    releases = extract_hl4u_legacy_servers(entry_html)
    seen = {r["bridge_url"] for r in releases}

    tabs_ul = re.search(r'<ul[^>]+id=["\']video_tabs["\'][^>]*>(.*?)</ul>', entry_html, re.S | re.I)
    if tabs_ul:
        for href, label in re.findall(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', tabs_ul.group(1), re.S | re.I
        ):
            clean_label = re.sub(r"<[^>]+>", "", label).strip() or "Server"
            href = html.unescape(href)
            if not href.startswith("http") or href in seen:
                continue
            seen.add(href)
            host = _host_of(href)
            q_m = re.search(r"\b(2160p|1080p|720p|480p)\b", clean_label, re.I)
            releases.append({
                "label": clean_label,
                "quality": (q_m.group(1).lower() if q_m else "720p"),
                "resolution": (q_m.group(1).lower() if q_m else "720p"),
                "size_bytes": None,
                "season_number": None,
                "episode_number": None,
                "codec": "x264",
                "bridge_url": href,
                "service": host.split(".")[0],
                "source_name": f"▶ {clean_label} [{host}]",
            })

    for href in re.findall(r'href=["\'](https?://[^"\'\s<>]+)["\']', entry_html):
        href = html.unescape(href)
        if href in seen:
            continue
        host = _host_of(href)
        if not host or any(s in host for s in SOCIAL_HOSTS) or "hindilinks4u" in host:
            continue
        if any(s in host for s in PORN_SPAM_HOSTS):
            continue
        if not any(e in host for e in EMBED_HOSTS) and "download" not in href.lower() and not re.search(r"\.(mkv|mp4)(\.|$)", host + href, re.I):
            continue
        seen.add(href)
        fname_m = re.search(r"/([^/]+\.(?:mkv|mp4))", urllib.parse.unquote(href))
        fname = fname_m.group(1) if fname_m else host
        q_m = re.search(r"(2160p|1080p|720p|480p)", href, re.I)
        releases.append({
            "label": f"Mirror ({host})",
            "quality": (q_m.group(1).lower() if q_m else "720p"),
            "resolution": (q_m.group(1).lower() if q_m else "720p"),
            "size_bytes": None,
            "season_number": None,
            "episode_number": None,
            "codec": "x264",
            "bridge_url": href,
            "service": host.split(".")[0],
            "source_name": f"🌐 {fname[:60]} [{host}]",
        })

    return releases


def parse_filmy_page(client: Hindilinks4uClient, post_url: str) -> dict | None:
    """Fetches and parses one Hindilinks4u post page into a staging post dict.

    Thin wrapper over parse_filmy_page_detailed() for callers that only want the
    dict; the crawler uses the detailed form so the reason is never lost.
    """
    post, _cause = parse_filmy_page_detailed(client, post_url)
    return post


def parse_filmy_page_detailed(
    client: Hindilinks4uClient, post_url: str
) -> tuple[dict | None, dict]:
    """Fetches and parses one post page, returning (post_or_None, failure_cause).

    `sitemap_cache.scraped=-1` alone conflated five different outcomes, which is
    why the backlog looked like an 80% failure wall. The cause dict says which,
    and PERMANENT_CAUSES vs TRANSIENT_CAUSES (both layered on the shared core in
    fast_fetch.py) says whether it is parked or re-queued:

        http_404_gone / http_410_gone     parked (PERMANENT): page died upstream
        skipped: not_a_post               parked (PERMANENT): not a title page
        http_403_forbidden / http_429     retryable (transient): host / our rate
        blocked: challenge                retryable: interstitial bot-check
        transport_error                   retryable: connection/timeout/empty
        parse_no_title                    retryable: page drifted shape
        no_sources_on_page                retryable: upstream published no link
                                          *yet* — the legacy-layout extractor
                                          recovers these on a later pass
        ok                                releases found
    """
    if not is_post_url(post_url):
        return None, _cause("skipped: not_a_post", post_url=post_url)

    code, final_url, page = client.get_text(post_url)
    if code != 200 or not page:
        cause = _http_cause(code)
        return None, _cause(cause, http=code, post_url=post_url)

    if looks_blocked(page):
        return None, _cause("blocked: challenge", http=code, post_url=post_url,
                            marker=next((m for m in CHALLENGE_MARKERS
                                         if m in page[:12000].lower()), ""))

    t_m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    raw_title = html.unescape(t_m.group(1)).strip() if t_m else ""
    raw_title = re.sub(r"\s*[-–|]\s*Watch Free Movies.*$", "", raw_title, flags=re.I).strip()
    if not raw_title:
        return None, _cause("parse_no_title", http=code, post_url=post_url,
                            page_bytes=len(page))

    clean_title, year, canonical_key = clean_hl4u_title(raw_title)
    if not clean_title:
        return None, _cause("parse_no_title", http=code, post_url=post_url,
                            raw_title=raw_title[:80])

    poster = None
    p_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', page, re.I)
    if p_m:
        poster = p_m.group(1)

    synopsis = None
    s_m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', page, re.I)
    if s_m:
        synopsis = html.unescape(s_m.group(1)).strip()

    imdb_id = None
    i_m = re.search(r"imdb\.com/title/(tt\d+)", page, re.I)
    if i_m:
        imdb_id = i_m.group(1)

    genres = []
    for tag in re.findall(r"tag(?:s|:)\s*content=[\"']([^\"'>]+)[\"']", page)[:8]:
        g = re.sub(r"^tag[-_]?", "", tag).replace("-", " ").strip().title()
        if g and len(g) < 40:
            genres.append(g)

    is_series = bool(re.search(r"\b(season\s*\d+|episodes?|complete|series)\b", raw_title, re.I))
    media_type = "series" if is_series else "movie"
    is_adult = fast_fetch.is_adult_title(raw_title, post_url)

    entry_m = re.search(r'<div[^>]+class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>\s*(?:<footer|<div id="respond)', page, re.S | re.I)
    entry_html = entry_m.group(1) if entry_m else page

    releases = extract_hl4u_servers(entry_html, final_url)
    if not releases:
        # The post is live and readable but the tab parser found no watch link
        # this pass — the embed block may not be published yet, or a later layout
        # revision (the legacy <strong>Server N</strong> form) needs re-reading.
        # A re-crawl can recover these, so it is TRANSIENT and spends the shared
        # retry budget rather than parking the row forever.
        return None, _cause("no_sources_on_page", http=code, post_url=post_url,
                            raw_title=raw_title[:80], entry_found=bool(entry_m),
                            page_bytes=len(page))

    lang_m = re.search(r"(Hindi|Tamil|Telugu|Kannada|Malayalam|English)[^<]{0,80}", raw_title, re.I)
    languages = json.dumps([lang_m.group(1).title()]) if lang_m else json.dumps(["Hindi"])

    post = {
        "canonical_key": canonical_key,
        "title": clean_title,
        "original_title": raw_title,
        "year": year,
        "media_type": media_type,
        "imdb_id": imdb_id,
        "tmdb_id": None,
        "poster_url": poster,
        "synopsis": synopsis,
        "genres": json.dumps(genres) if genres else None,
        "cast_names": None,
        "director": None,
        "languages": languages,
        "is_18_plus": is_adult,
        "site": SITE_NAME,
        "post_url": final_url,
        "releases": [{**r, "sources": [{
            "source_name": r["source_name"],
            "service": r["service"],
            "resource_id": r["bridge_url"].rstrip("/").split("/")[-1][:48],
            "source_url": r["bridge_url"],
            "final_url": r["bridge_url"],
            "is_temporary": 0,
            "quality": r["quality"],
        }]} for r in releases],
    }
    return post, _cause("ok", http=code, releases=len(releases))


def _cause(name: str, **info) -> dict:
    """Builds a failure/success cause record; `permanent` drives requeue triage."""
    payload = {"cause": name, "permanent": name in PERMANENT_CAUSES, "ts": int(time.time())}
    payload.update({k: v for k, v in info.items() if v not in (None, "")})
    return payload


def _http_cause(code: int) -> str:
    if code in (404, 410):
        return f"http_{code}_gone"
    if code == 403:
        return "http_403_forbidden"
    if code == 429:
        return "http_429_rate_limited"
    if code in (500, 502, 503, 504):
        return f"http_{code}_upstream_error"
    return "transport_error"


def record_cause(
    db_path: Path,
    loc: str,
    scraped: int,
    cause: dict | None,
    *,
    attempts: int | None = None,
    write_attempts: int = 4,
) -> bool:
    """Books one crawl outcome, retrying a busy database instead of dying on it.

    The 2026-10-23 backlog drain lost a whole pass to a single
    `sqlite3.OperationalError: database is locked` on the booking write — the
    merge writer holds these staging files, so a lock is expected weather, not a
    fatal error and definitely not a statement about the page. Bounded retries
    (fast_fetch.retry_backoff) absorb it; on exhaustion we return False and leave
    the row UNCHANGED so it stays in the queue. A crashed crawl is worse than a
    deferred one.

    `attempts` is the value computed by fast_fetch.crawl_attempt_state() (park vs
    retry budget). Passing it writes the attempts/last_attempt/last_cause columns;
    omitting it keeps the old raw_json-only behaviour so existing callers still
    work. `cause=None` stores NULL, which is how a success clears the earlier note.
    """
    payload = None if cause is None else json.dumps(cause, ensure_ascii=False)[:2000]
    last_cause = None if cause is None else cause.get("cause")
    if attempts is None:
        sql = "UPDATE sitemap_cache SET scraped=?, raw_json=?, last_cause=? WHERE loc=?"
        params: tuple = (scraped, payload, last_cause, loc)
    else:
        sql = ("UPDATE sitemap_cache SET scraped=?, raw_json=?, last_cause=?,"
               " attempts=?, last_attempt=? WHERE loc=?")
        params = (scraped, payload, last_cause, int(attempts), time.time(), loc)

    last_exc: Exception | None = None
    for i in range(max(1, write_attempts)):
        try:
            with sqlite3.connect(str(db_path), timeout=SQLITE_BUSY_TIMEOUT) as conn:
                conn.execute(sql, params)
                conn.commit()
            return True
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                print(f"[!] could not book {loc}: {exc}", file=sys.stderr, flush=True)
                return False
            last_exc = exc
            time.sleep(fast_fetch.retry_backoff(i + 1, base=0.25, cap=5.0))
        except sqlite3.Error as exc:
            print(f"[!] could not record cause for {loc}: {exc}", file=sys.stderr, flush=True)
            return False
    print(f"[!] database stayed locked for {loc}: {last_exc}", file=sys.stderr, flush=True)
    return False


def cause_breakdown(db_path: Path) -> dict:
    """Counts recorded failure causes; rows from older runs report 'unrecorded'."""
    counts: dict[str, int] = {}
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=SQLITE_BUSY_TIMEOUT) as conn:
        for scraped, raw in conn.execute("SELECT scraped, raw_json FROM sitemap_cache WHERE scraped<>1"):
            try:
                name = json.loads(raw)["cause"] if raw else "unrecorded"
            except (ValueError, KeyError, TypeError):
                name = "unrecorded"
            counts[name] = counts.get(name, 0) + 1
    return counts


def _save_post_once(db_path: Path, post_data: dict) -> bool:
    """One non-retried write of a post + its releases/sources into the staging DB.

    May raise sqlite3.OperationalError on a lock; save_post_to_staging_db() is the
    lock-tolerant wrapper callers should use.
    """
    with sqlite3.connect(str(db_path), timeout=SQLITE_BUSY_TIMEOUT) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO posts (
                canonical_key, title, original_title, year, media_type,
                imdb_id, poster_url, synopsis, genres, cast_names, director,
                languages, is_18_plus, site, post_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                original_title = excluded.original_title,
                year = COALESCE(excluded.year, posts.year),
                media_type = excluded.media_type,
                imdb_id = COALESCE(excluded.imdb_id, posts.imdb_id),
                poster_url = COALESCE(excluded.poster_url, posts.poster_url),
                synopsis = COALESCE(excluded.synopsis, posts.synopsis),
                genres = COALESCE(excluded.genres, posts.genres),
                languages = COALESCE(excluded.languages, posts.languages),
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
                post_data.get("is_18_plus", 0),
                post_data["site"],
                post_data["post_url"],
            ),
        )
        row = cur.fetchone()
        post_id = row[0] if row else None
        if not post_id:
            cur.execute("SELECT id FROM posts WHERE canonical_key = ?", (post_data["canonical_key"],))
            post_id = cur.fetchone()[0]
            cur.execute("DELETE FROM releases WHERE post_id = ?", (post_id,))

        for r in post_data["releases"]:
            cur.execute(
                """
                INSERT INTO releases (
                    post_id, label, quality, resolution, size_bytes,
                    season_number, episode_number, codec, bridge_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id;
                """,
                (
                    post_id, r["label"], r["quality"], r["resolution"],
                    r["size_bytes"], r["season_number"], r["episode_number"],
                    r["codec"], r["bridge_url"],
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
                        release_id, s["source_name"], s["service"], s["resource_id"],
                        s["source_url"], s["final_url"], s["is_temporary"], s["quality"],
                    ),
                )
        conn.commit()
    return True


def save_post_to_staging_db(db_path: Path, post_data: dict, *, write_attempts: int = 4) -> bool:
    """Persists a post, retrying a busy database instead of dying on it.

    Same lock-tolerance ported from import_katmoviehd._book_attempt: the merge
    writer shares these staging files, so a transient `database is locked` is
    weather, not a bad page. We back off (fast_fetch.retry_backoff) and re-write;
    on exhaustion we return False and leave the row untouched so it stays in the
    queue for a later pass. A crashed crawl is worse than a deferred one.
    Non-lock SQLite errors still propagate so the caller can classify them.
    """
    if not post_data or not post_data.get("releases"):
        return False
    last_exc: Exception | None = None
    for i in range(max(1, write_attempts)):
        try:
            return _save_post_once(db_path, post_data)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            last_exc = exc
            time.sleep(fast_fetch.retry_backoff(i + 1, base=0.25, cap=5.0))
    print(f"[!] database stayed locked while saving "
          f"{post_data.get('post_url', '?')}: {last_exc}", file=sys.stderr, flush=True)
    return False
    """Pulls all post-sitemap*.xml entries into sitemap_cache."""
    init_staging_db(db_path)
    client = Hindilinks4uClient(base_url=base_url)

    code, _, index_xml = client.get_text(f"{base_url}/sitemap_index.xml", timeout=20)
    if code != 200 or not index_xml:
        print("[!] Failed to fetch sitemap_index.xml", file=sys.stderr)
        return 0

    sub_maps = re.findall(r"<loc>(https?://[^<]*post-sitemap[^<]*\.xml)</loc>", index_xml)
    print(f"[*] {len(sub_maps)} post-sitemaps found.", flush=True)

    total = 0
    with sqlite3.connect(str(db_path)) as conn:
        for sm_url in sub_maps:
            if STOP_REQUESTED:
                break
            code, _, sm_xml = client.get_text(sm_url, timeout=25)
            if code != 200 or not sm_xml:
                print(f"[!] sub-sitemap failed: {sm_url}", file=sys.stderr)
                continue
            locs = re.findall(r"<loc>(https?://[^<]+)</loc>", sm_xml)
            records = []
            for loc in locs:
                if loc.rstrip("/").rstrip(".xml").endswith(("/category", "/tag", "/author")):
                    continue
                if any(seg in loc for seg in ("/category/", "/tag/", "/author/", "/feed/")):
                    continue
                if not is_post_url(loc):
                    # WordPress sitemaps list the site root on some mirrors; it is
                    # not a title page and can never yield releases.
                    continue
                slug = loc.rstrip("/").split("/")[-1]
                records.append((loc, None, slug, 0, SITE_NAME, None))
            conn.executemany(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(loc) DO NOTHING;
                """,
                records,
            )
            total += len(records)
            print(f"  [ok] {sm_url}: {len(records)} urls", flush=True)
            if max_items and total >= max_items:
                break
        conn.commit()
    print(f"[✓] Synced {total:,} URLs into sitemap_cache.", flush=True)
    return total


def crawl_queue(db_path: Path, limit: int | None = None) -> list:
    """Rows worth crawling now: never-tried first, then failures inside the budget.

    The old `SELECT loc FROM sitemap_cache WHERE scraped = 0` abandoned every
    failed page forever — the requeue put a row back at 0, one lock or one
    interstitial threw it to -1, and nothing selected it again. Now a -1 row
    re-enters the queue while COALESCE(attempts, 0) < fast_fetch.MAX_CRAWL_ATTEMPTS.
    A permanent cause is parked by fast_fetch.crawl_attempt_state() (which sets
    attempts to the max on the first sighting), so it drops out here without this
    query needing to know the cause vocabulary. Returns (loc, prior_attempts).
    """
    where = (
        "scraped = 0 OR (scraped = -1 AND COALESCE(attempts, 0) < "
        f"{fast_fetch.MAX_CRAWL_ATTEMPTS})"
    )
    query = (
        f"SELECT loc, COALESCE(attempts, 0) FROM sitemap_cache WHERE {where}"
        " ORDER BY scraped DESC, rowid ASC"
    )
    params: tuple = ()
    if limit:
        query += " LIMIT ?"
        params = (int(limit),)
    with sqlite3.connect(str(db_path), timeout=SQLITE_BUSY_TIMEOUT) as conn:
        return conn.execute(query, params).fetchall()


def run_crawler(
    db_path: Path,
    base_url: str,
    workers: int = 4,
    delay: float = 0.3,
    limit: int | None = None,
    client: "Hindilinks4uClient | None" = None,
    dark_threshold: int = SITE_DARK_THRESHOLD,
):
    init_staging_db(db_path)
    if client is None:
        client = Hindilinks4uClient(base_url=base_url, request_interval=delay)

    queue = crawl_queue(db_path, limit)

    if not queue:
        print("[!] No pending titles. Run --sync-sitemap first.", flush=True)
        return

    print(f"[*] Starting Hindilinks4u crawler: {len(queue):,} titles | {workers} workers", flush=True)
    done = failed = total_rels = total_srcs = 0
    started = time.monotonic()
    # Dark-host fuse: a whole run of transport/403/429/5xx/challenge failures is
    # a site we cannot crawl, not a backlog to grind to -1. Stop spending
    # requests and leave the rest of the queue untouched.
    fuse = fast_fetch.ConsecutiveFailureFuse(threshold=dark_threshold)

    def process_item(item):
        loc = item[0]
        prior_attempts = int(item[1] or 0)
        post, cause = parse_filmy_page_detailed(client, loc)
        if not post:
            return loc, prior_attempts, False, 0, 0, cause
        try:
            ok = save_post_to_staging_db(db_path, post)
        except sqlite3.Error as exc:
            # A locked or full DB is a retryable transport problem, not a bad
            # page: say so, and never let it look like upstream died.
            return loc, prior_attempts, False, 0, 0, _cause(
                "sqlite_locked" if "locked" in str(exc).lower() else "sqlite_error",
                error=str(exc)[:160], post_url=loc)
        nrels = len(post["releases"])
        nsrcs = sum(len(r.get("sources", [])) for r in post["releases"])
        if not ok:
            # save_post_to_staging_db returned False: a deferred (locked) write,
            # never a statement about the page — retryable.
            return loc, prior_attempts, False, 0, 0, _cause("save_rejected", post_url=loc)
        return loc, prior_attempts, True, nrels, nsrcs, _cause("ok", releases=nrels)

    causes: dict[str, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_item, item): item for item in queue}
        for fut in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED or fuse.tripped:
                for f in futures:
                    f.cancel()
                break
            try:
                loc, prior_attempts, ok, nrels, nsrcs, cause = fut.result()
            except Exception as exc:  # a worker crash must not abort the crawl
                item = futures[fut]
                loc, prior_attempts = item[0], int(item[1] or 0)
                ok, nrels, nsrcs = False, 0, 0
                cause = _cause("worker_exception", error=f"{type(exc).__name__}: {exc}"[:160],
                               post_url=loc)
            done += 1
            total_rels += nrels
            total_srcs += nsrcs
            name = cause.get("cause", "unrecorded")
            causes[name] = causes.get(name, 0) + 1
            if ok:
                scraped = 1
                attempts = prior_attempts + 1
                # Success clears any earlier failure note for the same page.
                record_cause(db_path, loc, 1, None, attempts=attempts)
            else:
                failed += 1
                # Park-vs-retry is delegated to the shared core, not decided
                # here: a permanent cause parks on the first sighting (attempts
                # -> MAX, so crawl_queue stops selecting it); anything else spends
                # one unit of the budget and stays selectable for a later pass.
                scraped, attempts = fast_fetch.crawl_attempt_state(
                    name, prior_attempts=prior_attempts, permanent=PERMANENT_CAUSES)
                record_cause(db_path, loc, -1, cause, attempts=attempts)
                fuse.record(name)
            if done % 10 == 0 or done == len(queue):
                speed = done / max(0.01, time.monotonic() - started)
                eta = (len(queue) - done) / max(0.01, speed)
                print(
                    f"  [{done:,}/{len(queue):,}] releases={total_rels:,} sources={total_srcs:,} "
                    f"failed={failed:,} speed={speed:.2f} t/s ETA: {eta/3600:.2f}h",
                    flush=True,
                )

    if fuse.tripped:
        left = len(queue) - done
        print(
            f"\n[!] Site-dark fuse tripped: {fuse.streak} consecutive failures "
            f"({fuse.trip_reason}). The domain is refusing or unreachable — that is a "
            f"fetch-layer problem, not {left:,} dead pages. Stopping; the remaining "
            f"{left:,} rows keep their queue position untouched.",
            flush=True,
        )

    print(f"\n[✓] Crawler finished: {done - failed:,} scraped, {failed:,} failed in {time.monotonic()-started:.1f}s", flush=True)
    if causes:
        print("[i] this run's outcome breakdown (parked = we stop asking, retryable = budget left):", flush=True)
        for name, cnt in sorted(causes.items(), key=lambda kv: -kv[1]):
            # A lock or a worker crash says nothing about the PAGE, so it is never
            # "permanent" — it is retryable, parked only for genuine page causes.
            tag = " parked" if name in PERMANENT_CAUSES else (" retryable" if name != "ok" else "")
            print(f"      {name:26s} {cnt:6,}{tag}", flush=True)


def print_status(db_path: Path):
    with sqlite3.connect(str(db_path)) as conn:
        posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        adult = conn.execute("SELECT COUNT(*) FROM posts WHERE is_18_plus=1").fetchone()[0]
        rels = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        srcs = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        pend = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped=0").fetchone()[0]
        fail = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped=-1").fetchone()[0]
    print(f"posts={posts:,} (adult-flagged={adult:,}) releases={rels:,} sources={srcs:,} pending={pend:,} failed={fail:,}")
    breakdown = cause_breakdown(db_path)
    if breakdown:
        print("failure causes (recorded by this scraper; 'unrecorded' = attempt predates the bookkeeping):")
        for name, cnt in sorted(breakdown.items(), key=lambda kv: -kv[1]):
            print(f"  {name:26s} {cnt:6,}")


def main():
    parser = argparse.ArgumentParser(description="Hindilinks4u staging scraper (hindilinks4u.zip)")
    parser.add_argument("--sync-sitemap", action="store_true", help="Sync post URLs from sitemaps")
    parser.add_argument("--max-items", type=int, default=None, help="Cap on synced URLs")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent worker threads")
    parser.add_argument("--delay", type=float, default=0.3, help="Per-request delay seconds")
    parser.add_argument("--limit", type=int, default=None, help="Limit crawled titles this run")
    parser.add_argument("--status", action="store_true", help="Print staging DB metrics")
    parser.add_argument("--db-path", type=Path, default=DB_PATH, help="Staging DB path")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    base_url = get_active_base_url(SITE_NAME, DEFAULT_BASE_URL)

    if args.status:
        print_status(db_path)
        return
    if args.sync_sitemap:
        sync_sitemap_to_db(db_path, base_url, args.max_items)
        return
    run_crawler(db_path, base_url, workers=args.workers, delay=args.delay, limit=args.limit)


if __name__ == "__main__":
    main()
