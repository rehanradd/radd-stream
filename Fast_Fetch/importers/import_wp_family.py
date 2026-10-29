#!/usr/bin/env python3
"""
import_wp_family.py — staging importer for four WordPress-family catalogs.

Each site is configured in SITES; the code path is shared because the measured
page shape is shared: WordPress permalinks, a Yoast/Rank-Math sitemap, an
og:* block, one to four iframes, and quality-labelled download anchors.

Measured on 2026-10-29 (see /tmp/new_site_candidates_20261028.json):

* moviesmela.com — open WP REST, X-WP-Total 20,888, four post sitemaps,
  iframe embeds (pkembed.site, do7go.com, dd133.com, mxdrop.to).
* moviehax.run — WordPress + Dooplay; the catalogue lives in the movies CPT,
  so posts sitemaps are tiny and movies-sitemap.xml is the catalog surface.
  "18+ ... Adult" titles share the same catalogue, so the adult rule runs here.
* thebollyflix.gen.in — WP, X-WP-Total 17,827, one bflixcdn.xyz iframe per post;
  the family hops domains, so identity is title+year, never the host.
* animeworld.live — WP, 596 posts, Hindi-dub episode pages; the player is
  injected by page script, so only server-rendered iframes/anchors are stored.

Every source row is written `status='unverified'` with `is_temporary=0` unless
the site itself says otherwise: nothing here probes or activates a link. The
first HTTP 429 records `kind=rate-limited` and pauses the run without spending
attempts on the remaining rows, as the other importers do.

Stdlib only.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch  # noqa: E402

DATA_DIR = Path("/home/ubuntu/radd-stream-data")
PAGE_TIMEOUT = 30
RATE_LIMIT_STATUS = 429
MAX_SCRAPE_ATTEMPTS = 3
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

_RATE_LIMITED = threading.Event()
STOP_REQUESTED = False

ADULT_KEYWORDS = {
    "18+", "erotic", "hotshots", "ullu", "kooku", "rabbit", "primeplay", "hentai",
    "uncensored", "sex", "porn", "adult", "lust", "sensual", "naked", "nude",
    "charmsukh", "palang tod", "rasmalai", "chull", "bhabhi", "jalebi",
}

QUALITY_RE = re.compile(r"\b(2160p|1440p|1080p|720p|480p|360p|240p|4k)\b", re.I)
SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mb|gb)\b", re.I)
DOWNLOAD_WORD_RE = re.compile(r"\bdownload\b", re.I)
BRACKET_RE = re.compile(r"\[[^\]]*\]?")
PAREN_PACKAGING_RE = re.compile(
    r"\((?:[^)]*\b(?:\d{3,4}p|4k|hd|uhd|web-?dl|bluray|hevc|10bit|esub|dual|multi)\b[^)]*)\)",
    re.I)
_TRAILING_JUNK = (r"(?:480p|720p|1080p|2160p|4k|hd|uhd|hdrip|web-?dl|webrip|"
                  r"bluray|blu-ray|10bit|hevc|x264|x265|esub|dual\s+audio|"
                  r"multi\s+audio|full\s+movie|movie|film)")
TRAILING_JUNK_RE = re.compile(
    r"(?:(?:[\s,]+|[\s,]*&[\s,]*)" + _TRAILING_JUNK + r")+$", re.I)
SERIES_RE = re.compile(
    r"(?:^|[\s\-_\[\(])(?:s\d{1,2}(?:e\d{1,3})?|season\s*\d+|episode\s*\d+|"
    r"ep\s*\d+|complete\s+series|web\s*series|tv\s*series)(?:$|[\s\-_\]\)])",
    re.I)
SEASON_RE = re.compile(r"(?:season\s*(\d+)|s(\d{1,2})(?:e\d{1,3})?)", re.I)
EPISODE_RE = re.compile(r"(?:episode\s*(\d+)|e(\d{1,3}))", re.I)
YEAR_RE = re.compile(r"\((19\d{2}|20\d{2})\)")
LANGUAGE_WORDS = ("hindi", "tamil", "telugu", "malayalam", "kannada", "punjabi",
                  "bengali", "marathi", "gujarati", "english", "korean", "turkish",
                  "chinese", "japanese", "urdu")
ANIMATED_WORDS = ("anime", "animation", "animated", "cartoon")

IFRAME_TAG_RE = re.compile(r"<iframe\b[^>]*>", re.I)
SRC_ATTR_RE = re.compile(
    r"\b(?:data-litespeed-src|data-lazy-src|data-src|src)=[\"']([^\"']+)[\"']", re.I)
ANCHOR_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
OG_RE = r"<meta[^>]+property=[\"']og:{name}[\"'][^>]+content=[\"']([^\"']*)[\"']"
META_RE = r"<meta[^>]+name=[\"']{name}[\"'][^>]+content=[\"']([^\"']*)[\"']"
TAG_RE = re.compile(r"<a\b[^>]*rel=[\"']tag[\"'][^>]*>(.*?)</a>", re.I | re.S)
AD_HOSTS = ("doubleclick.net", "googlesyndication.com", "googleadservices.com",
            "adservice.google.com", "amazon-adsystem.com", "googletagmanager.com",
            "googletagservices.com", "google-analytics.com")

SITES = {
    "moviehax": {
        "base": "https://moviehax.run",
        "db": DATA_DIR / "moviehax.db",
        "sitemaps": ["https://moviehax.run/sitemap_index.xml"],
        "display_names": ["Moviehax"],
        # Dooplay prints server buttons, not embeds; each button answers through
        # the theme's own POST action (measured: doo_player_ajax -> embed_url).
        "dooplay": True,
        "exclude": r"/(?:category|tag|author|page|genre|about|contact|dmca|"
                   r"privacy|disclaimer|request|how-to|feed|wp-json|sitemap|"
                   r"movies|tv-shows)/?$",
    },
    "bollyflix": {
        "base": "https://thebollyflix.gen.in",
        "db": DATA_DIR / "bollyflix.db",
        # The published sitemaps are pages/categories only (measured 2026-10-29),
        # so the post list comes from the open WP REST route.
        "sitemaps": [],
        "rest": "https://thebollyflix.gen.in/wp-json/wp/v2/posts",
        "display_names": ["Bollyflix"],
        "generic_titles": ["bollyflix"],
        "internal_hosts": ["bollyflix.co.za"],
        "exclude": r"/(?:category|tag|author|page|genre|about|contact|dmca|"
                   r"privacy|disclaimer|request|how-to|feed|wp-json|sitemap)",
    },
    "animeworld": {
        "base": "https://animeworld.live",
        "db": DATA_DIR / "animeworld.db",
        "sitemaps": ["https://animeworld.live/sitemap_index.xml"],
        "display_names": ["Anime World"],
        "exclude": r"/(?:category|tag|author|page|genre|about|contact|dmca|"
                   r"privacy|disclaimer|request|how-to|feed|wp-json|sitemap)",
    },
    "hindidubbedmovies": {
        "base": "https://hindidubbedmovies.pk",
        "db": DATA_DIR / "hindidubbedmovies.db",
        "sitemaps": [
            "https://hindidubbedmovies.pk/wp-sitemap-posts-movies-1.xml",
            "https://hindidubbedmovies.pk/wp-sitemap-posts-series-1.xml",
        ],
        "display_names": ["Hindi Dubbed Movies"],
        "exclude": r"/(?:category|tag|author|page|about|contact|dmca|privacy|"
                   r"disclaimer|feed|wp-json|sitemap|episodes/|letters/|cast/)",
    },
    "hindianimeszone": {
        "base": "https://hindianimeszone.com",
        "db": DATA_DIR / "hindianimeszone.db",
        "sitemaps": [],
        "rest": "https://hindianimeszone.com/wp-json/wp/v2/posts",
        "display_names": ["Hindi Anime Zone"],
        # The theme prints the abscloud player URL as text, not inside <iframe>.
        "player_hosts": ["abscloud.org"],
        "always_animated": True,
        "exclude": r"/(?:category|tag|author|page|about|contact|dmca|privacy|"
                   r"disclaimer|feed|wp-json|sitemap)",
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sitemap_cache (
    loc TEXT PRIMARY KEY,
    lastmod TEXT,
    slug TEXT,
    scraped INTEGER DEFAULT 0,
    raw_json TEXT,
    error_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS posts (
    canonical_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    clean_title TEXT NOT NULL,
    year INTEGER,
    media_type TEXT,
    poster_url TEXT,
    backdrop_url TEXT,
    backdrop_urls TEXT,
    imdb_id TEXT,
    tmdb_id TEXT,
    imdb_rating TEXT,
    synopsis TEXT,
    genres TEXT,
    director TEXT,
    cast_names TEXT,
    duration TEXT,
    release_date TEXT,
    languages TEXT,
    industry TEXT,
    country TEXT,
    seasons TEXT,
    url TEXT,
    slug TEXT,
    is_18_plus INTEGER DEFAULT 0,
    is_animated INTEGER DEFAULT 0,
    source_site TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_meta TEXT
);
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
    origin_url TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    source_name TEXT,
    service TEXT,
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'url',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER
);
CREATE INDEX IF NOT EXISTS idx_wp_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_wp_releases_key ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_wp_sources_release ON sources(release_id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _http_get_full(url: str, timeout: int = PAGE_TIMEOUT, retries: int = 2):
    """GET -> (status, final_url, text, headers). Transport failure -> status 0."""
    last = ""
    for attempt in range(retries + 1):
        if STOP_REQUESTED:
            return 0, url, "", {}
        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return resp.status, resp.geturl(), body.decode(charset, "replace"), headers
        except urllib.error.HTTPError as exc:
            if exc.code == RATE_LIMIT_STATUS:
                return exc.code, url, "", {}
            if 400 <= exc.code < 500:
                return exc.code, url, "", {}
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))
    return 0, url, last, {}


def http_get(url: str, timeout: int = PAGE_TIMEOUT, retries: int = 2):
    """GET -> (status, final_url, text). Transport failure -> status 0."""
    return _http_get_full(url, timeout=timeout, retries=retries)[:3]


class RateLimited(Exception):
    """Raised mid-page when the site starts answering 429."""


def _http_post(url: str, data: dict, referer: str = "",
               timeout: int = PAGE_TIMEOUT) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, "" if exc.code == RATE_LIMIT_STATUS else str(exc)
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


DOOPLAY_OPTION_RE = re.compile(r"<li\b[^>]*dooplay_player_option[^>]*>", re.I)
DOOPLAY_ATTR_RE = re.compile(r"data-([a-z]+)=[\"']?([^\"'\s>]+)", re.I)
TRAILER_HOSTS = ("youtube.com", "youtu.be", "dailymotion.com")


def _dooplay_player_sources(html: str, page_url: str, cfg: dict) -> list[dict]:
    """Asks the theme's own player action for each server button it printed."""
    options = []
    for tag in DOOPLAY_OPTION_RE.findall(html):
        attrs = dict(DOOPLAY_ATTR_RE.findall(tag))
        if attrs.get("post") and attrs.get("nume") and attrs.get("type"):
            options.append(attrs)
    host = urllib.parse.urlsplit(cfg.get("base") or page_url).hostname
    out: list[dict] = []
    for attrs in options[:6]:
        status, body = _http_post(
            f"https://{host}/wp-admin/admin-ajax.php",
            {"action": "doo_player_ajax", "post": attrs["post"],
             "nume": attrs["nume"], "type": attrs["type"]},
            referer=page_url,
        )
        if status == RATE_LIMIT_STATUS:
            raise RateLimited()
        if status != 200 or not body.strip():
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        embed = payload.get("embed_url") or ""
        if "<iframe" in embed:
            m = SRC_ATTR_RE.search(embed)
            embed = m.group(1) if m else ""
        embed = html_mod.unescape(embed).strip()
        if not embed.startswith(("http://", "https://")):
            continue
        if any(h in embed for h in AD_HOSTS + TRAILER_HOSTS):
            continue
        service = urllib.parse.urlsplit(embed).hostname or "embed"
        out.append({
            "release_title": "Watch online",
            "quality": None,
            "playback_type": "iframe",
            "source_name": service,
            "service": service,
            "resource_id": attrs.get("nume"),
            "source_url": embed,
            "final_url": None,
        })
    return out


def _meta(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.I)
    return html_mod.unescape(m.group(1)).strip() if m else ""


def _strip_tags(text: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def _is_generic(title: str, cfg: dict) -> bool:
    names = {n.casefold() for n in
             cfg.get("display_names", []) + cfg.get("generic_titles", [])}
    return (title or "").strip().casefold() in names


def _title_from_html(html: str, site: str, cfg: dict) -> str:
    """og:title wins unless it is just the site name; then the post body does."""
    og = _meta(html, OG_RE.format(name="title"))
    if og and not _is_generic(og, cfg):
        return og
    for m in re.finditer(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S):
        text = _strip_tags(m.group(1))
        if text:
            return text
    tag = _meta(html, r"<title[^>]*>(.*?)</title>")
    if tag and not _is_generic(tag, cfg):
        return tag
    # Bollyflix-style themes repeat the site name in every title tag; the post
    # title opens og:description, terminated by the first "Title:" label.
    desc = _meta(html, OG_RE.format(name="description")) or \
        _meta(html, META_RE.format(name="description"))
    if desc:
        head = re.split(r"\s+(?:Title|Released Date|Release Date|Genres?|Stars|"
                        r"Quality|Plot)\s*:", desc, maxsplit=1)[0]
        if head.strip():
            return head
    return ""


def _clean_title(raw: str, site: str) -> str:
    cfg = SITES.get(site, {})
    title = _strip_tags(raw)
    title = title.split("|")[0].strip()
    for name in cfg.get("display_names", []):
        title = re.sub(r"\s*[|–-]\s*" + re.escape(name) + r"\s*$", "", title, flags=re.I)
    title = re.sub(r"^\s*(?:download|watch)\s+", "", title, flags=re.I)
    title = re.sub(
        r"\s+(?:watch online|free download|full movie|full episode|download)\b.*$",
        "", title, flags=re.I)
    title = BRACKET_RE.sub(" ", title)
    title = PAREN_PACKAGING_RE.sub(" ", title)
    # "Jai Jawaan Jai Kisaan Movie (2015)": the label sits before the year, so
    # the trailing-junk pass would stop at the parentheses.
    title = re.sub(r"\s+(?:full\s+movie|movie|film)\s*(?=\((?:19|20)\d{2}\))",
                   "", title, flags=re.I)
    while True:
        cleaned = TRAILING_JUNK_RE.sub("", title)
        cleaned = re.sub(r"[\s,|–-]+$", "", cleaned)
        if cleaned == title:
            break
        title = cleaned
    return re.sub(r"\s+", " ", title).strip(" -–|")


def _year_of(text: str, slug: str) -> int | None:
    for source in (text, slug):
        m = YEAR_RE.search(source or "")
        if m:
            return int(m.group(1))
    for source in (slug or "",):
        m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", source)
        if m:
            return int(m.group(1))
    return None


def _int_or_none(regex: re.Pattern, text: str) -> int | None:
    m = regex.search(text or "")
    if not m:
        return None
    for group in m.groups():
        if group:
            return int(group)
    return None


def _is_adult(*texts: str) -> bool:
    clean = re.sub(r"[^a-zA-Z0-9\+]+", " ", " ".join(t or "" for t in texts).lower())
    if "18+" in clean or "18 plus" in clean:
        return True
    return bool(set(clean.split()) & ADULT_KEYWORDS)


def _slug_of(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.strip("/")
    return path.rsplit("/", 1)[-1]


def _sources_from_html(html: str, page_url: str,
                       cfg: dict | None = None) -> list[dict]:
    """Server-rendered players first, then quality-labelled download anchors."""
    cfg = cfg or {}
    base_host = urllib.parse.urlsplit(cfg.get("base", "")).hostname or ""
    internal_hosts = set(cfg.get("internal_hosts") or [])
    if base_host:
        internal_hosts.add(base_host)
    out: list[dict] = []
    seen: set[str] = set()

    def _add_embed(src: str) -> None:
        src = html_mod.unescape(src).strip()
        if not src or src in ("about:blank", "#"):
            return
        if not src.startswith(("http://", "https://", "//")):
            return
        if src.startswith("//"):
            src = "https:" + src
        if any(host in src for host in AD_HOSTS) or src in seen:
            return
        seen.add(src)
        host = urllib.parse.urlsplit(src).hostname or "embed"
        out.append({
            "release_title": "Watch online",
            "quality": None,
            "playback_type": "iframe",
            "source_name": host,
            "service": host,
            "resource_id": None,
            "source_url": src,
            "final_url": None,
        })

    for tag in IFRAME_TAG_RE.findall(html):
        for src in SRC_ATTR_RE.findall(tag):
            _add_embed(src)
    # Some themes drop the player URL into the body text with no <iframe> at all.
    for host in cfg.get("player_hosts") or []:
        for m in re.finditer(
                r"https?://[a-z0-9.-]*" + re.escape(host) + r"[^\s\"'<>]*", html, re.I):
            _add_embed(m.group(0))
    for href, inner in ANCHOR_RE.findall(html):
        href = html_mod.unescape(href).strip()
        text = _strip_tags(inner)
        if not href.startswith(("http://", "https://")):
            continue
        # Quality must be announced in the link label; a quality token that only
        # appears in the URL is how category shelves get mistaken for downloads.
        quality = QUALITY_RE.search(text)
        size = SIZE_RE.search(text)
        host = urllib.parse.urlsplit(href).hostname or ""
        is_internal = any(host == h or host.endswith("." + h) for h in internal_hosts)
        # A first-party "Download" button that carries its own download route is
        # a real mirror; other internal links are navigation or sibling posts.
        if is_internal and not ("download" in href.lower()
                                and DOWNLOAD_WORD_RE.match(text.strip())):
            continue
        if not (quality or size) and not is_internal:
            continue
        if href in seen:
            continue
        seen.add(href)
        q = quality.group(1).lower() if quality else None
        out.append({
            "release_title": text[:120] or (q or "Download"),
            "quality": q,
            "playback_type": "download",
            "source_name": urllib.parse.urlsplit(href).hostname or "download",
            "service": urllib.parse.urlsplit(href).hostname or "download",
            "resource_id": None,
            "source_url": href,
            "final_url": None,
            "size_text": size.group(0) if size else None,
        })
    return out


def _size_bytes(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s?(mb|gb)", text, re.I)
    if not m:
        return None
    value = float(m.group(1))
    return int(value * (1024 ** 3 if m.group(2).lower() == "gb" else 1024 ** 2))


def parse_page(html: str, page_url: str, site: str) -> dict | None:
    """Maps a server-rendered detail page onto the staging post shape."""
    cfg = SITES.get(site, {})
    title_raw = _title_from_html(html, site, cfg)
    title = _clean_title(title_raw, site)
    slug = _slug_of(page_url)
    if not title:
        return None
    year = _year_of(title, slug)
    searchable = f"{title} {slug}"
    season = _int_or_none(SEASON_RE, searchable)
    episode = _int_or_none(EPISODE_RE, searchable)
    is_series = bool(SERIES_RE.search(searchable)) or bool(season or episode)
    clean_title = re.sub(r"\s+", " ", YEAR_RE.sub("", title)).strip(" -–|")
    canonical_key = fast_fetch.generate_canonical_key(clean_title, year)
    if not canonical_key or canonical_key == "unknown":
        return None
    synopsis = _meta(html, OG_RE.format(name="description")) or \
        _meta(html, META_RE.format(name="description"))
    poster = _meta(html, OG_RE.format(name="image"))
    genres = [g.strip() for g in TAG_RE.findall(html) if g.strip()]
    genres = list(dict.fromkeys(_strip_tags(g) for g in genres))[:8]
    languages = [w.title() for w in LANGUAGE_WORDS
                 if re.search(rf"\b{w}\b", searchable, re.I)]
    sources = _sources_from_html(html, page_url, cfg)
    if cfg.get("dooplay"):
        known = {s["source_url"] for s in sources}
        sources.extend(s for s in _dooplay_player_sources(html, page_url, cfg)
                       if s["source_url"] not in known)
    if not sources:
        return None
    releases: dict[tuple, dict] = {}
    for src in sources:
        key = (src["quality"], src["playback_type"])
        rel = releases.setdefault(key, {
            "label": src["release_title"] if key not in releases else None,
            "quality": src["quality"],
            "resolution": src["quality"],
            "size_bytes": _size_bytes(src.get("size_text")),
            "season": season if is_series else None,
            "episode": episode if is_series else None,
            "sources": [],
        })
        if rel["label"] is None:
            rel["label"] = src["release_title"]
        rel["sources"].append({
            "source_name": src["source_name"],
            "service": src["service"],
            "resource_id": src["resource_id"],
            "source_url": src["source_url"],
            "final_url": src["final_url"],
            "playback_type": src["playback_type"],
            "is_temporary": 0,
            "status": "unverified",
        })
    return {
        "url": page_url,
        "slug": slug,
        "title": title,
        "clean_title": clean_title,
        "year": year,
        "content_type": "series" if is_series else "movie",
        "season_number": season if is_series else None,
        "seasons": json.dumps([{"season": season, "episodes": []}])
        if is_series and season else None,
        "poster_url": poster or None,
        "genres": ", ".join(genres) if genres else None,
        "synopsis": synopsis or None,
        "languages": ", ".join(languages) if languages else "Unknown",
        "industry": "Unknown",
        "country": "Unknown",
        "is_18_plus": 1 if _is_adult(title, slug, synopsis) else 0,
        "is_animated": 1 if cfg.get("always_animated") or
        any(w in searchable.lower() for w in ANIMATED_WORDS) else 0,
        "source_site": site,
        "canonical_key": canonical_key,
        "releases": [dict(rel) for rel in releases.values()],
    }


def export_staging(db_path: Path | str, site: str, posts: list[dict]) -> dict:
    out = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
           "skipped": 0}
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        for post in posts:
            if not post or not post.get("clean_title") or not post.get("canonical_key"):
                out["skipped"] += 1
                continue
            conn.execute(
                """
                INSERT INTO posts (
                    canonical_key, title, clean_title, year, media_type, poster_url,
                    imdb_rating, synopsis, genres, cast_names, duration,
                    release_date, languages, industry, country, seasons, url, slug,
                    is_18_plus, is_animated, source_site, raw_meta
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, NULL, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_key) DO UPDATE SET
                    title = excluded.title,
                    clean_title = excluded.clean_title,
                    year = excluded.year,
                    media_type = excluded.media_type,
                    poster_url = COALESCE(excluded.poster_url, posts.poster_url),
                    synopsis = COALESCE(excluded.synopsis, posts.synopsis),
                    genres = COALESCE(excluded.genres, posts.genres),
                    languages = COALESCE(excluded.languages, posts.languages),
                    seasons = COALESCE(excluded.seasons, posts.seasons),
                    url = excluded.url,
                    slug = excluded.slug,
                    is_18_plus = MAX(excluded.is_18_plus, posts.is_18_plus),
                    is_animated = MAX(excluded.is_animated, posts.is_animated),
                    scraped_at = CURRENT_TIMESTAMP
                """,
                (post["canonical_key"], post["title"], post["clean_title"],
                 post.get("year"), post.get("content_type") or "movie",
                 post.get("poster_url"), post.get("synopsis"), post.get("genres"),
                 post.get("languages"), post.get("industry") or "Unknown",
                 post.get("country") or "Unknown", post.get("seasons"),
                 post["url"], post.get("slug"), post.get("is_18_plus", 0),
                 post.get("is_animated", 0), site,
                 json.dumps({"sitemap_loc": post["url"]})),
            )
            out["posts_written"] += 1
            conn.execute(
                "DELETE FROM releases WHERE post_canonical_key = ? AND origin_url = ?",
                (post["canonical_key"], post["url"]),
            )
            for rel in post.get("releases") or []:
                cur = conn.execute(
                    """
                    INSERT INTO releases (
                        post_canonical_key, label, quality, resolution, size_bytes,
                        season_number, episode_number, audio_languages, bridge_url,
                        origin_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (post["canonical_key"], rel.get("label"), rel.get("quality"),
                     rel.get("resolution"), rel.get("size_bytes"), rel.get("season"),
                     rel.get("episode"), post.get("languages"), post["url"]),
                )
                out["releases_written"] += 1
                for src in rel.get("sources") or []:
                    conn.execute(
                        """
                        INSERT INTO sources (
                            release_id, source_name, service, resource_id,
                            source_url, final_url, playback_type, status,
                            is_temporary, quality
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (cur.lastrowid, src["source_name"], src["service"],
                         src["resource_id"], src["source_url"], src["final_url"],
                         src["playback_type"], src["status"],
                         src["is_temporary"], rel.get("quality")),
                    )
                    out["sources_written"] += 1
            conn.execute(
                """
                INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 1)
                ON CONFLICT(loc) DO UPDATE SET scraped = 1, error_count = 0
                """,
                (post["url"], post.get("slug")),
            )
        conn.commit()
    finally:
        conn.close()
    return out


def parse_sitemap(text: str) -> list[tuple[str, str | None]]:
    out = []
    for loc, lastmod in re.findall(
            r"<loc>\s*(.*?)\s*</loc>(?:\s*<lastmod>\s*(.*?)\s*</lastmod>)?",
            text or "", re.I | re.S):
        out.append((_unwrap_cdata(loc.strip()), _unwrap_cdata(lastmod.strip()) or None))
    return out


def _unwrap_cdata(value: str) -> str:
    """All-in-One-SEO wraps <loc> in CDATA; Yoast does not."""
    m = re.fullmatch(r"<!\[CDATA\[(.*?)\]\]>", value or "", re.S)
    return html_mod.unescape(m.group(1) if m else value)


def sync_catalog(site: str, db_path: Path | str, config: dict | None = None,
                 verbose: bool = True) -> int:
    cfg = config or SITES[site]
    exclude = re.compile(cfg["exclude"], re.I)
    pending = list(cfg["sitemaps"])
    seen: set[str] = set()
    locs: list[tuple[str, str | None]] = []
    depth = 0
    while pending and depth < 3:
        nxt = []
        for url in pending:
            status, final, text = http_get(url)
            if status != 200:
                if verbose:
                    print(f"[!] [{site}] sitemap {url} -> {status}", flush=True)
                continue
            entries = parse_sitemap(text)
            children = [loc for loc, _ in entries if loc.lower().endswith((".xml", ".xml.gz"))]
            if children:
                nxt.extend(children)
                continue
            for loc, lastmod in entries:
                if loc in seen or loc.rstrip("/") == cfg["base"].rstrip("/"):
                    continue
                if exclude.search(loc):
                    continue
                seen.add(loc)
                locs.append((loc, lastmod))
        pending = nxt
        depth += 1
    rest_seeded = _seed_rest(cfg, exclude, seen, locs, site, verbose)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        known = {r[0] for r in conn.execute("SELECT loc FROM sitemap_cache")}
        fresh = [(loc, lm) for loc, lm in locs if loc not in known]
        conn.executemany(
            "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped) VALUES (?, ?, ?, 0)",
            [(loc, lm, _slug_of(loc)) for loc, lm in fresh])
        conn.commit()
    finally:
        conn.close()
    if verbose:
        print(f"[*] [{site}] catalog total={len(locs)} new={len(fresh)}"
              f" rest={rest_seeded}", flush=True)
    return len(fresh)


def _seed_rest(cfg: dict, exclude: re.Pattern, seen: set[str],
               locs: list[tuple[str, str | None]], site: str,
               verbose: bool) -> int:
    """Seeds the queue from the open WP REST route when no post sitemap exists."""
    rest = cfg.get("rest")
    if not rest:
        return 0
    url = f"{rest}?per_page=100&page=1&_fields=link"
    status, _final, text, headers = _http_get_full(url)
    if status != 200:
        if verbose:
            print(f"[!] [{site}] REST {rest} -> {status}", flush=True)
        return 0
    try:
        pages = int(headers.get("x-wp-totalpages") or 1)
    except ValueError:
        pages = 1
    added = 0
    for page in range(1, pages + 1):
        if page > 1:
            time.sleep(0.3)
            status, _final, text, _headers = _http_get_full(
                f"{rest}?per_page=100&page={page}&_fields=link")
            if status != 200:
                if verbose:
                    print(f"[!] [{site}] REST page {page} -> {status}", flush=True)
                break
        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            break
        for item in items if isinstance(items, list) else []:
            loc = (item or {}).get("link")
            if not loc or loc in seen or exclude.search(loc):
                continue
            seen.add(loc)
            locs.append((loc, None))
            added += 1
    return added


def _bump(db_path: Path, loc: str, note: str, *, park: bool = False) -> None:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT scraped, error_count, raw_json FROM sitemap_cache WHERE loc = ?",
            (loc,)).fetchone()
        count = (row[1] or 0) + 1 if row else 1
        scraped = -1 if park or count >= MAX_SCRAPE_ATTEMPTS else (
            2 if row and row[0] in (0, 2) else 0)
        payload = {}
        if row and row[2]:
            try:
                payload = json.loads(row[2])
            except (json.JSONDecodeError, TypeError):
                payload = {}
        payload.setdefault("failures", []).append({"attempt": count, "kind": note})
        payload["last_note"] = note
        conn.execute(
            "UPDATE sitemap_cache SET scraped = ?, error_count = ?, raw_json = ?"
            " WHERE loc = ?", (scraped, count, json.dumps(payload), loc))
        conn.commit()
    finally:
        conn.close()


def crawl(site: str, db_path: Path | str, limit: int | None = None,
          delay: float = 0.5, verbose: bool = True) -> dict:
    global STOP_REQUESTED
    STOP_REQUESTED = False
    _RATE_LIMITED.clear()
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT loc FROM sitemap_cache WHERE scraped IN (0, 2)"
            " OR (scraped = -1 AND error_count < ?) ORDER BY rowid",
            (MAX_SCRAPE_ATTEMPTS,)).fetchall()
    finally:
        conn.close()
    if limit:
        rows = rows[:limit]
    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "not_indexable": 0, "failed": 0, "paused_rate_limit": 0,
              "declined_by_reason": {}}
    if verbose:
        print(f"[*] [{site}] {len(rows)} pages pending", flush=True)
    for (loc,) in rows:
        if STOP_REQUESTED:
            break
        if _RATE_LIMITED.is_set():
            totals["paused_rate_limit"] += 1
            continue
        time.sleep(delay)
        status, final, body = http_get(loc)
        totals["pages"] += 1
        if status == RATE_LIMIT_STATUS:
            _RATE_LIMITED.set()
            _bump(db_path, loc, "rate-limited")
            totals["failed"] += 1
            continue
        if status == 0:
            _bump(db_path, loc, "transport")
            totals["failed"] += 1
            continue
        if status in (404, 410, 451):
            _bump(db_path, loc, f"http-{status}", park=True)
            totals["not_indexable"] += 1
            totals["declined_by_reason"][f"http-{status}"] = \
                totals["declined_by_reason"].get(f"http-{status}", 0) + 1
            continue
        if status != 200:
            _bump(db_path, loc, f"http-{status}")
            totals["failed"] += 1
            continue
        try:
            post = parse_page(body, final or loc, site)
        except RateLimited:
            _RATE_LIMITED.set()
            _bump(db_path, loc, "rate-limited")
            totals["failed"] += 1
            continue
        if post is None:
            _bump(db_path, loc, "no-playable-object", park=True)
            totals["not_indexable"] += 1
            totals["declined_by_reason"]["no-playable-object"] = \
                totals["declined_by_reason"].get("no-playable-object", 0) + 1
            continue
        written = export_staging(db_path, site, [post])
        totals["posts"] += written["posts_written"]
        totals["releases"] += written["releases_written"]
        totals["sources"] += written["sources_written"]
        if verbose and totals["pages"] % 20 == 0:
            print(f"    ... {totals['pages']} pages, {totals['posts']} posts,"
                  f" {totals['sources']} sources", flush=True)
    if verbose:
        paused = " paused=rate-limited" if _RATE_LIMITED.is_set() else ""
        print(f"[✓] [{site}] pages={totals['pages']} posts={totals['posts']}"
              f" releases={totals['releases']} sources={totals['sources']}"
              f" not-indexable={totals['not_indexable']}"
              f" failed={totals['failed']}{paused}", flush=True)
        if totals["declined_by_reason"]:
            print(f"    [{site}] declined as: " + ", ".join(
                f"{k}={v}" for k, v in totals["declined_by_reason"].items()),
                flush=True)
    return totals


def stats(site: str, db_path: Path | str) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        return {
            "sitemap": conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0],
            "queued": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0, 2)").fetchone()[0],
            "parked": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "adult": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        }
    finally:
        conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WordPress-family staging importer")
    parser.add_argument("site", choices=sorted(SITES))
    parser.add_argument("command", choices=("sync", "crawl", "stats"))
    parser.add_argument("--db", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db = Path(args.db) if args.db else SITES[args.site]["db"]
    if args.command == "sync":
        sync_catalog(args.site, db, verbose=not args.quiet)
    elif args.command == "crawl":
        crawl(args.site, db, limit=args.limit, delay=args.delay,
              verbose=not args.quiet)
    else:
        print(json.dumps(stats(args.site, db), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
