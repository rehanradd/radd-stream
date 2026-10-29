#!/usr/bin/env python3
"""
import_dramacool.py — isolated staging importer for https://dramacool.li

Writes ONLY to /home/ubuntu/radd-stream-data/dramacool.db. Never touches the
production catalog; merge with Fast_Fetch/merge_catalogs.py after operator review.
Pure Python standard library. Zero pip packages.

The site's own model, as verified live (11 requests, 2026-10-28):

    sitemap.xml                    -> sitemap_index.xml
        post-sitemap1..3.xml       one <loc> per work (~600 works total), e.g.
            /<slug>-watch-full-episodes-eng-sub/   series with all episodes
            /<slug>-watch-full-movie-eng-sub/      a film
            /<thai-slug>/                          WordPress slug, percent-encoded
        series-sitemap1..3.xml     /series/<slug>/ metadata pages (same works)
        category/genres/cast/...   shelves, not catalog entries

    A watch page carries everything this importer can read without JavaScript:
        <h1>The Glory Fades – Watch Full Episodes Eng Sub</h1>
        <h2>The Glory Fades (2026)</h2>            <- work title + year
        <span class="alter">繁华落尽, ...</span>     <- alternate titles
        <div class="spe"><span><b>Status:</b> Completed</span>
            <b>Network:</b> Tencent Video / <b>Released:</b> Jan 30, 2026 - ...
            <b>Duration:</b> 20 min. / <b>Country:</b> China / <b>Type:</b> Drama
            <b>Episodes:</b> 34 / <b>Casts:</b> <a href="/cast/jin-han/">Jin Han</a>
        <div class="genxed">Chinese Drama Mystery Thriller</div>
        <div class="desc mindes">...synopsis...</div>
        <meta property="og:image" content="https://i0.wp.com/...webp">
        <div id="cs-player" data-post-id="6244683910894099581"></div>

    Episodes are NOT separate URLs: one WordPress post owns the whole series, and
    the current episode is published as ``tsMediaEpNow = "32"`` / ``/ 34`` on the
    page while the player (CS Player v1.0.0, served obfuscated from
    /wp-content/konmijoyma/css.js) indexes them by that 19-digit post id.

SUBTITLE / VIDEO REALITY (read before trusting a count):

    The player's configuration declares seven subtitle languages and calls
    ``subtitles.baseUrl`` / ``videoBaseUrl`` — but the shipped values are the
    literals ``https://sub.example.com`` and ``https://vse.example.com``; the real
    hosts are decrypted at runtime from the player licence, and there are no
    matching DNS names under dramacool.li. No .vtt/.srt/.ass URL, no <track> tag
    and no m3u8 appears anywhere in the server HTML. That means this importer can
    and does persist the full *metadata* and the player bridge per episode, but a
    stdlib crawl cannot enumerate the per-language subtitle tracks on this site
    without executing the player's obfuscated JavaScript. Nothing is invented to
    paper over that: when a track URL is not published, it is recorded as a
    declared language (raw_meta.subtitle_config), never as a fake source row.

    ``harvest_subtitles()`` is deliberately general so the same code captures
    tracks the moment a page/JSON/manifest exposes them: <track> tags, anchor
    links ending .vtt/.srt/.ass/.ssa, JSON track maps ("subtitles"/"tracks"/
    "captions"), HLS #EXT-X-MEDIA subtitle renditions, and a non-placeholder
    CS Player subtitles.baseUrl. Every track becomes its own sources row with
    playback_type='subtitle'; duplicates (two English tracks, forced vs full)
    are kept.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html as html_mod
import json
import re
import signal
import sqlite3
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://dramacool.li"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/dramacool.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITE = "dramacool"

LEGAL_MEDIA_TYPES = ("movie", "series", "complete_season")
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC"
    % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

# Paths that are shelves, search pages or WordPress furniture, never a work.
NON_POST_PREFIXES = (
    "/genres/", "/genre/", "/country/", "/network/", "/cast/",
    "/tag/", "/az-list/", "/page/", "/schedule/", "/bookmark/", "/wp-json/",
    "/wp-admin/", "/wp-content/", "/feed", "/sitemap", "/category/",
    "/director/", "/?s=", "/comments/",
)

# The sitemap index lists post sitemaps (works) and series sitemaps (the same
# works, metadata-only). Only the post sitemaps are queued so one work cannot be
# filed twice; direct parse_page() calls still accept a /series/ page.
POST_SITEMAP_RE = re.compile(r"/post-sitemap\d*\.xml$", re.I)
SERIES_SITEMAP_RE = re.compile(r"/series-sitemap\d*\.xml$", re.I)

PLAYER_ID_RE = re.compile(r'id=["\']cs-player["\'][^>]*?data-post-id=["\'](\d+)["\']'
                          r'|data-post-id=["\'](\d+)["\'][^>]*?id=["\']cs-player["\']', re.I)
PLAYER_SCRIPT_RE = re.compile(
    r"""<script[^>]*src=["']([^"']*?/wp-content/konmijoyma/[^"']+\.js[^"']*)["']""", re.I)

STOP_REQUESTED = False


def _signal_handler(signum, frame):  # pragma: no cover - signal path
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"[!] [{SITE}] {signum} received; draining in-flight pages…", flush=True)


for _sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sig, _signal_handler)
    except (ValueError, OSError):
        pass

# ---------------------------------------------------------------------------
# URL / provenance filters
# ---------------------------------------------------------------------------

SITE_HOST_RE = re.compile(r"""(?:^|\.)drama\s?cool(?:9)?\.[a-z]{2,}""", re.I)
TRACKER_HOST_RE = re.compile(
    r"""doubleclick|googlesyndication|google-analytics|googletagmanager"""
    r"""|cloudflareinsights|scorecard|histats|adsterra|bicea\.org|bit\.ly|tinyurl""",
    re.I,
)
DIRECT_MEDIA_RE = re.compile(r"\.(?:m3u8|mp4|mkv|webm)(?:[?#]|$)", re.I)
SUBTITLE_EXT_RE = re.compile(r"\.(vtt|srt|ass|ssa)(?:[?#]|$)", re.I)

# Site branding that must not survive into a public display string.
BRAND_TOKEN_RE = re.compile(r"""drama\s?cool(?:9|\.li|\.asia|\.sh|\.dev)?\b""", re.I)

# "– Watch Full Episodes Eng Sub" / "| Dramacool" packaging tails on <h1>.
PACKAGING_TAIL_RE = re.compile(
    r"""\s*(?:[|»]|[-–—:]{1,2})\s*(?:watch\s+full\s+(?:episodes?|movie|series)"""
    r"""|full\s+(?:episodes?|movie)|eng(?:lish)?\s*sub(?:titles?)?|download|dramacool)\b.*$""",
    re.I)

# ---------------------------------------------------------------------------
# Text lexicons
# ---------------------------------------------------------------------------

# "xxx" left on 2026-10-29: 62 rows were hidden by it alone and the catalog holds the
# *xXx* films, so one hit is a suggestion, not a hide. "adult" stays — 10/12 sampled live
# titles carrying it are real product; the two *Shin-chan: The Adult Empire Strikes Back*
# rows are the documented cost. `AGE_CERT_RE` still flags a bracketed certificate.
ADULT_KEYWORDS = ("18+", "18 plus", "adult", "erotic", "hentai", "porn",
                  "pornstar", "uncensored", "softcore", "hardcore")
# Only the unambiguous markers may flag from prose; an 18+ row is hidden at every
# surface, so a mainstream blurb must not delete a title.
PROSE_ADULT_KEYWORDS = ("18+", "18 plus", "hentai", "erotic", "porn", "pornstar")
AGE_CERT_RE = re.compile(
    r"[\(\[\{]\s*(?:18\s*\+|18\s*plus|adult|xxx)\s*[\)\]\}]", re.I)

QUALITY_RE = re.compile(r"\b(2160p|4k|1440p|1080p|720p|576p|480p|360p)\b", re.I)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SEASON_RE = re.compile(r"\bSeason\s*(\d{1,2})\b|\bS(\d{1,2})\b", re.I)
EPISODE_RE = re.compile(r"\b(?:Episode|Ep|E)\.?\s*(\d{1,4})\b", re.I)
HLS_EPISODE_RE = re.compile(r"(?:episode|ep|e)[-_]?(\d{1,4})\b", re.I)
EPNOW_RE = re.compile(r'tsMediaEpNow\s*=\s*["\'](\d{1,4})["\']')
EPNOW_CLASS_RE = re.compile(r'<em[^>]*class=["\'][^"\']*epnow[^"\']*["\'][^>]*>(\d{1,4})</em>', re.I)
EPS_TEXT_RE = re.compile(r"\bEps?\s*(\d{1,4})\b", re.I)
EP_COUNT_SLASH_RE = re.compile(r'<em[^>]*class=["\'][^"\']*epnow[^"\']*["\'][^>]*>[^<]*</em>\s*/\s*(\d{1,4})', re.I)
RATING_RE = re.compile(r"(?:imdb|rating)\D{0,8}(\d+(?:[.,]\d+)?)", re.I)
IMDB_ID_RE = re.compile(r"\b(tt\d{7,9})\b", re.I)

SPE_RE = re.compile(r"""<div\b[^>]*class=["'][^"']*\bspe\b[^"']*["'][^>]*>(.*?)</div>""", re.S | re.I)
INFO_ROW_RE = re.compile(r"<b>\s*([^<:]+?)\s*:?\s*</b>(.*?)(?=<b>|$)", re.S | re.I)
GENRES_RE = re.compile(r"""<div\b[^>]*class=["'][^"']*\bgenxed\b[^"']*["'][^>]*>(.*?)</div>""", re.S | re.I)
SYNOPSIS_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*\bdesc\b[^"']*["'][^>]*>(.*?)(?:<span\b[^>]*class=["']colap|<div\b|</div>)""",
    re.S | re.I)
ALTER_RE = re.compile(r"""<span\b[^>]*class=["'][^"']*\balter\b[^"']*["'][^>]*>(.*?)</span>""", re.S | re.I)
H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.S | re.I)
H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.S | re.I)
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
META_RE = re.compile(
    r"""<meta\b[^>]*?(?:property|name)=["'](?P<key>[^"']+)["'][^>]*?content=["'](?P<val>[^"']*)["']"""
    r"""|<meta\b[^>]*?content=["'](?P<val2>[^"']*)["'][^>]*?(?:property|name)=["'](?P<key2>[^"']+)["']""",
    re.I)
ANCHOR_RE = re.compile(r"""<a\b[^>]*?href=["'](?P<href>[^"']+?)["'][^>]*>(?P<inner>.*?)</a>""", re.S | re.I)
TRACK_TAG_RE = re.compile(r"<track\b[^>]*>", re.I)
ATTR_RE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*["']([^"']*)["']""")
CSPLAYER_CONFIG_RE = re.compile(r"csPlayerConfig\s*=\s*\{(.*?)\}\s*;", re.S)
CS_BASE_RE = re.compile(r"""["']?baseUrl["']?\s*:\s*["']([^"']+)["']""", re.I)
CS_LANGS_RE = re.compile(r"""["']?languages["']?\s*:\s*\{(.*?)\}""", re.S)
CS_LANG_PAIR_RE = re.compile(
    r"""["']?([A-Za-z][\w-]*)["']?\s*:\s*["']([A-Za-z-]{2,8})["']""")
HLS_STREAM_INF_RE = re.compile(r"#EXT-X-STREAM-INF:([^\r\n]+)", re.I)
HLS_MEDIA_RE = re.compile(r"#EXT-X-MEDIA:([^\r\n]+)", re.I)
HLS_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', re.I)

LANGUAGE_CODES = {
    "en": "English", "eng": "English", "english": "English",
    "ar": "Arabic", "ara": "Arabic", "arabic": "Arabic",
    "km": "Khmer", "khm": "Khmer", "khmer": "Khmer",
    "tl": "Filipino", "fil": "Filipino", "filipino": "Filipino", "tagalog": "Filipino",
    "hi": "Hindi", "hin": "Hindi", "hindi": "Hindi",
    "id": "Indonesian", "ind": "Indonesian", "indonesian": "Indonesian",
    "ms": "Malay", "msa": "Malay", "malay": "Malay",
    "ko": "Korean", "kor": "Korean", "korean": "Korean",
    "zh": "Chinese", "chi": "Chinese", "zho": "Chinese", "chinese": "Chinese",
    "ja": "Japanese", "jpn": "Japanese", "japanese": "Japanese",
    "th": "Thai", "tha": "Thai", "thai": "Thai",
    "vi": "Vietnamese", "vie": "Vietnamese", "vietnamese": "Vietnamese",
    "es": "Spanish", "spa": "Spanish", "spanish": "Spanish",
    "fr": "French", "fre": "French", "french": "French",
    "de": "German", "ger": "German", "german": "German",
    "pt": "Portuguese", "por": "Portuguese", "portuguese": "Portuguese",
    "ru": "Russian", "rus": "Russian", "russian": "Russian",
}

COUNTRY_LANGUAGE = {
    "china": "Chinese", "south korea": "Korean", "korea": "Korean",
    "japan": "Japanese", "thailand": "Thai", "philippines": "Filipino",
    "taiwan": "Mandarin", "hong kong": "Cantonese", "usa": "English",
    "united states": "English", "uk": "English", "united kingdom": "English",
    "india": "Hindi", "vietnam": "Vietnamese", "indonesia": "Indonesian",
    "malaysia": "Malay", "singapore": "Mandarin", "turkey": "Turkish",
}

GENRE_INDUSTRY = (
    ("korean drama", "K-Drama"), ("k-drama", "K-Drama"),
    ("chinese drama", "C-Drama"), ("c-drama", "C-Drama"),
    ("jdrama", "J-Drama"), ("japanese drama", "J-Drama"),
    ("thai drama", "Thai Drama"), ("lakorn", "Thai Drama"),
    ("anime", "Anime"), ("animation", "Anime"),
)

PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "localhost",
                     "your-domain.com", "domain.com")

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

SSL_CONTEXT = ssl.create_default_context()

_OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=SSL_CONTEXT),
    urllib.request.HTTPRedirectHandler(),
)
_OPENER.addheaders = [
    ("User-Agent", USER_AGENT),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "en-US,en;q=0.9"),
]


def _quote_url(url: str) -> str:
    """
    The one URL gate: HTML-unescape first, then percent-quote the Unicode.

    A Thai or Chinese slug copied out of a WordPress sitemap is a mix of literal
    '%e0%b9...' escapes and raw characters; quoting again would double-encode the
    escapes and urllib would raise on the raw ones. This is the exact bug fixed
    here: unescape, then quote with every reserved URL character left alone.
    """
    return urllib.parse.quote(html_mod.unescape(url or ""),
                              safe=":/?#[]@!$&'()*+,;=%")


def http_get(url: str, timeout: int = 30, retries: int = 2):
    """Returns (status_code, final_url, body). Never raises."""
    url = _quote_url(url)
    last_status, last_url, last_body = 0, url, ""
    for attempt in range(1, retries + 1):
        try:
            resp = _OPENER.open(url, timeout=timeout)
            data = resp.read()
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            return (getattr(resp, "status", 200) or 200, resp.geturl(),
                    data.decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            try:
                last_body = exc.read().decode("utf-8", "replace")
            except Exception:
                last_body = ""
            if exc.code in (401, 403, 404, 410):
                return exc.code, url, last_body
        except Exception as exc:
            last_status, last_body = 0, f"[network error] {exc}"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    return last_status, last_url, last_body


def probe_source(url: str, referer: str | None = None, timeout: int = 20):
    """
    One bounded GET for a single source URL. Returns (status, body-prefix).

    status: active | dead | blocked | js_required | error. A dead link is kept by
    the caller with that status — it is health information, not a reason to drop
    the row. Only the first 8 KiB is read: enough for an m3u8 header, a <track>
    page or a Cloudflare wall, not enough to pull a movie.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(_quote_url(url), headers=headers)
    try:
        resp = _OPENER.open(req, timeout=timeout)
        data = resp.read(8192)
        status = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as exc:
        data = b""
        status = exc.code
        try:
            data = exc.read(8192)
        except Exception:
            pass
    except Exception as exc:
        return "error", f"[network error] {exc}"
    body = data.decode("utf-8", "replace")
    head = body[:800].lower()
    if "just a moment" in head or "enable javascript" in head or "cf-chl" in head:
        return "js_required", body
    if status in (404, 410):
        return "dead", body
    if status in (401, 403, 503):
        return "blocked", body
    if status in (200, 206):
        return "active", body
    return "error", body


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _unescape(text: str | None) -> str:
    return html_mod.unescape(html_mod.unescape(text or ""))


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", _unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def scrub_brand(text: str | None) -> str:
    """Removes site branding and 'Watch Full Episodes' packaging from a string."""
    if not text:
        return ""
    out = BRAND_TOKEN_RE.sub(" ", text)
    out = PACKAGING_TAIL_RE.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip(" -–—:,,.|»\u00a7")


def _adult_mark(text: str) -> bool:
    return bool(re.search(r"(?<!\d)18\s*\+|18\s*plus", text.lower())) \
        or bool(AGE_CERT_RE.search(text or ""))


def _has_keyword(text: str, keywords) -> bool:
    padded = f" {re.sub(r'[^a-z ]+', ' ', text.lower())} "
    return any(f" {kw} " in padded for kw in keywords if kw not in ("18+", "18 plus"))


def is_adult_content(*labels: str | None, prose: tuple = ()) -> bool:
    """
    Flags adult material from titles, genres, tags and site type labels.

    Prose is checked only for unambiguous markers: hiding an 18+ row is cheap,
    but hiding a mainstream drama because its blurb says "adult themes" is not.
    """
    head = " ".join(t for t in labels if t)
    if _adult_mark(head) or _has_keyword(head, ADULT_KEYWORDS):
        return True
    body = " ".join(t for t in prose if t)
    return bool(body) and (_adult_mark(body) or _has_keyword(body, PROSE_ADULT_KEYWORDS))


def looks_animated(*texts: str | None) -> bool:
    joined = " ".join(t for t in texts if t).lower()
    return bool(re.search(r"\b(anime|animated|animation)\b", joined))


def _abs_url(href: str, base: str) -> str:
    return urllib.parse.urljoin(base, _unescape(href.strip()))


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc.lower().replace("www.", "")


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _is_tracker(url: str) -> bool:
    return bool(TRACKER_HOST_RE.search(url or ""))


def _is_placeholder_url(url: str) -> bool:
    host = _host_of(url)
    return not host or any(host == p or host.endswith("." + p) for p in PLACEHOLDER_HOSTS)


def _meaningful(text: str | None) -> str:
    out = (text or "").strip()
    return "" if re.fullmatch(r"(?:n/?a|na|not available|-+|tbd|to be updated)", out, re.I) else out


def _pretty_slug(slug: str) -> str:
    words = [w for w in re.split(r"[-_.]+", re.sub(r"[^\w\-_.]+", " ", slug or "")) if w]
    return " ".join(words).strip()


def _capitalize(text: str) -> str:
    return re.sub(r"(^|\s)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text or "")


def _ascii_key(text: str) -> str:
    """ASCII fold; a Thai/CJK-only title folds to '' and the caller hashes it."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _parse_attrs(text: str) -> dict:
    return {k.lower(): v for k, v in ATTR_RE.findall(text or "")}


def _parse_hls_attrs(text: str) -> dict:
    """HLS attributes are often unquoted (BANDWIDTH=6000000,RESOLUTION=...)."""
    out: dict[str, str] = {}
    for key, value in HLS_ATTR_RE.findall(text or ""):
        out[key.strip().lower()] = value.strip().strip('"\'')
    return out


# ---------------------------------------------------------------------------
# Title / identity parsing
# ---------------------------------------------------------------------------

def parse_title(raw_title: str, slug: str = "", explicit_year: int | None = None) -> dict:
    """Derives clean title, year, season and media type from a page title."""
    brandless = scrub_brand(_clean_text(raw_title)) or _clean_text(raw_title)
    brandless = re.sub(r"(?<!\d)18\s*\+", " ", brandless).strip()

    year = explicit_year
    if year is None:
        m = (re.search(r"[\(\[\{]\s*((?:19|20)\d{2})\s*[\)\]}]", brandless)
             or YEAR_RE.search(brandless)
             or re.search(r"[-_ ]((?:19|20)\d{2})[-_/]?$", slug or ""))
        year = int(m.group(1)) if m else None

    # The work's name ends where the bracketed year starts.
    head = re.split(r"\s*[\(\[\{]\s*(?:19|20)\d{2}\s*(?:[\)\]}]|$)",
                    brandless, maxsplit=1)[0]
    head = re.sub(r"\s*[\(\[]\s*[\)\]]\s*", " ", head)
    clean = re.sub(r"\s+", " ", head).strip(" -–—:,,.|»\u00a7")
    clean = re.sub(r"\s*[\(\[]\s*$", "", clean).strip()
    if not clean:
        clean = _capitalize(scrub_brand(_pretty_slug(slug))) or brandless
    # A work can be named for a year ("1987"); only strip the inline year when
    # something survives it.
    without_year = re.sub(r"\b(?:19|20)\d{2}\b", " ", clean)
    if without_year.strip(" -–—:,"):
        clean = re.sub(r"\s+", " ", without_year).strip(" -–—:,")

    season_m = SEASON_RE.search(head) or SEASON_RE.search(brandless)
    season = int(next(g for g in season_m.groups() if g)) if season_m else None
    if season:
        clean = SEASON_RE.sub(" ", clean)
        clean = re.sub(r"\s+", " ", clean).strip(" -–—:,")

    return {
        "clean_title": clean or brandless or "Unknown",
        "year": year,
        "season_number": season,
        "canonical_key": build_canonical_key(clean or brandless, year, season, slug),
    }


def build_canonical_key(clean_title: str, year: int | None, season: int | None,
                        slug: str) -> str:
    """
    Title-derived identity key, with an ASCII fold and a hash fallback.

    The WordPress slug is not stable across re-publishings and the Thai slugs are
    percent-encoded prose, so the key is built from the display title. A title
    with no Latin characters at all (Thai/CJK) hashes to a short stable handle
    instead of collapsing to "unknown".
    """
    base = _ascii_key(clean_title)
    if not base:
        digest = hashlib.sha1((clean_title or slug or "unknown").encode("utf-8")).hexdigest()
        base = f"drama-{digest[:12]}"
    key = f"{base}_{year}" if year else base
    if season:
        key += f"_s{season:02d}"
    return key or "unknown"


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _meta_tags(html: str) -> dict:
    out: dict[str, str] = {}
    for m in META_RE.finditer(html or ""):
        key = (m.group("key") or m.group("key2") or "").strip().lower()
        val = _clean_text(m.group("val") if m.group("val") is not None else m.group("val2"))
        if key and val:
            out.setdefault(key, val)
    return out


def _info_block(html: str) -> dict:
    """Reads the <div class="spe"><b>Label:</b> value</div> metadata grid."""
    fields: dict[str, str] = {}
    links_by_label: dict[str, list[tuple[str, str]]] = {}
    spe = SPE_RE.search(html or "")
    if not spe:
        return fields
    # Split on spans so a nested <span class="split"> cannot swallow its neighbour.
    for chunk in re.split(r"<span\b", spe.group(1)):
        m = INFO_ROW_RE.search(chunk)
        if not m:
            continue
        label = _clean_text(m.group(1)).lower()
        value_html = m.group(2)
        links = [(_meaningful(_clean_text(inner)), href) for href, inner
                 in ANCHOR_RE.findall(value_html)]
        value = _meaningful(_clean_text(value_html))
        if label and value:
            fields.setdefault(label, value)
        if links:
            links_by_label.setdefault(label, links)
    fields["__links"] = links_by_label
    return fields


def _series_title(body: str, metas: dict) -> str:
    """
    Prefers an <h1> that carries the year, then a bracketed-year <h2>.

    The watch page's <h1> is packaging ("– Watch Full Episodes Eng Sub") while
    its <h2> is the work; the /series/ page is the other way round.
    """
    h1 = H1_RE.search(body or "")
    h1_text = _clean_text(h1.group(1)) if h1 else ""
    if h1_text and re.search(r"[\(\[\{]\s*(?:19|20)\d{2}\s*[\)\]}]", h1_text):
        return h1_text
    for m in H2_RE.finditer(body or ""):
        text = _clean_text(m.group(1))
        if text and re.search(r"[\(\[\{]\s*(?:19|20)\d{2}\s*[\)\]}]", text):
            return text
    return h1_text or metas.get("og:title") or ""


def _episode_count(body: str, info: dict, content_type: str) -> tuple[int | None, int | None]:
    """Returns (available_episodes, declared_episodes)."""
    declared = None
    m = re.search(r"\d{1,4}", info.get("episodes", "") or "")
    if m:
        declared = int(m.group(0))

    available = None
    for pattern in (EPNOW_RE, EPNOW_CLASS_RE, EPS_TEXT_RE):
        hit = pattern.search(body or "")
        if hit:
            available = int(hit.group(1))
            break
    if content_type == "movie":
        return 1, 1
    if available is None:
        available = declared
    if available is not None:
        available = max(1, available)
    return available, declared


def _language_label(code_or_name: str | None) -> str | None:
    if not code_or_name:
        return None
    raw = code_or_name.strip()
    key = raw.lower()
    if key in LANGUAGE_CODES:
        return LANGUAGE_CODES[key]
    # "English (Forced)" / "Chinese - Simplified" still carry a language.
    base = re.split(r"[\s(\[（\-/]+", key, maxsplit=1)[0]
    if base in LANGUAGE_CODES:
        return LANGUAGE_CODES[base]
    return raw.title() or None


def _language_from_filename(url: str) -> str | None:
    path = urllib.parse.unquote(urllib.parse.urlsplit(url or "").path).lower()
    # .en.vtt / _arabic.srt / eng.ass
    for token in reversed(re.split(r"[._\-/]+", path)):
        if token in LANGUAGE_CODES:
            return LANGUAGE_CODES[token]
    return None


def _episode_from_url(url: str) -> int | None:
    path = urllib.parse.unquote(urllib.parse.urlsplit(url or "").path)
    m = re.search(r"(?:episode|ep)[-_]?(\d{1,4})(?=[._\-/]|$)", path, re.I)
    return int(m.group(1)) if m else None


def _track(source_url: str, language: str | None, code: str | None, fmt: str | None,
           label: str | None, origin: str, **extra) -> dict:
    lang = _meaningful(language)
    if lang:
        lang = _language_label(lang) or lang
    else:
        lang = _language_from_filename(source_url) or "Unknown"
    return {
        "source_url": source_url,
        "language": lang,
        "language_code": (code or "").lower() or None,
        "format": (fmt or (SUBTITLE_EXT_RE.search(source_url or "") or [None])[0] or "").lower() or None,
        "label": _meaningful(label) or None,
        "origin": origin,
        "episode_number": _episode_from_url(source_url),
        **extra,
    }


def _tracks_from_json(node, base_url: str) -> list[dict]:
    """Walks a JSON track map into track dicts, keeping duplicate languages."""
    out: list[dict] = []

    def add(url_or_lang, value, label=None):
        if isinstance(url_or_lang, str) and isinstance(value, str) \
                and not url_or_lang.lower().startswith(("http", "/", ".", "//")):
            # {"English": "https://.../en.vtt"}
            out.append(_track(_abs_url(value, base_url), _language_label(url_or_lang),
                              url_or_lang, None, label, "json-map"))
        elif isinstance(url_or_lang, str) and url_or_lang.lower().startswith(("http", "/", "//")):
            out.append(_track(_abs_url(url_or_lang, base_url), _language_label(value),
                              value, None, label, "json-list"))

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, str):
            # A bare list of subtitle URLs with no per-track language.
            if obj.lower().startswith(("http", "/", "//", "./", "../")) \
                    and SUBTITLE_EXT_RE.search(obj):
                out.append(_track(_abs_url(obj, base_url), None, None, None,
                                  None, "json-url"))
        elif isinstance(obj, dict):
            # {"English": "https://cdn/en.vtt", "ar": "https://cdn/ar.vtt"}
            for key, value in obj.items():
                if isinstance(value, str) and value.lower().startswith(
                        ("http", "/", "//", "./", "../")) \
                        and SUBTITLE_EXT_RE.search(value):
                    add(key, value)
            url = None
            for key in ("url", "src", "file", "link", "uri", "path", "vtt", "srt", "ass"):
                if isinstance(obj.get(key), str):
                    url = obj[key]
                    break
            if url and (SUBTITLE_EXT_RE.search(url) or "subtitle" in json.dumps(obj).lower()):
                lang = obj.get("language") or obj.get("lang") or obj.get("srclang") \
                    or obj.get("locale") or obj.get("name") or obj.get("label")
                label = obj.get("label") or obj.get("name")
                code = lang if isinstance(lang, str) and len(str(lang)) <= 8 else None
                out.append(_track(_abs_url(url, base_url), _language_label(lang) or lang,
                                  code, None, label, "json-object",
                                  is_default=bool(obj.get("default") or obj.get("is_default")),
                                  is_forced=bool(obj.get("forced") or obj.get("is_forced"))))
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(node)
    return out


def _json_track_blocks(body: str, base_url: str) -> list[dict]:
    """Finds JSON/JS track maps without requiring a full DOM parser."""
    tracks: list[dict] = []
    decoded = html_mod.unescape(body or "")

    # Whole <script type="application/json"> payloads.
    for m in re.finditer(r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>',
                         decoded, re.S | re.I):
        try:
            tracks.extend(_tracks_from_json(json.loads(m.group(1)), base_url))
        except (json.JSONDecodeError, TypeError):
            continue

    # Inline "subtitles": [...] / "tracks": [...] / "captions": {...} fragments.
    for key in ("subtitles", "tracks", "captions", "subs", "cc"):
        for m in re.finditer(rf'["\']?{key}["\']?\s*:\s*', decoded, re.I):
            start = m.end()
            if start >= len(decoded) or decoded[start] not in "[{":
                continue
            try:
                node, _end = json.JSONDecoder().raw_decode(decoded[start:])
            except json.JSONDecodeError:
                continue
            tracks.extend(_tracks_from_json(node, base_url))
    return tracks


def _hls_subtitles(text: str, base_url: str) -> list[dict]:
    tracks = []
    for m in HLS_MEDIA_RE.finditer(text or ""):
        attrs = _parse_hls_attrs(m.group(1))
        if attrs.get("type", "").upper() != "SUBTITLES" or not attrs.get("uri"):
            continue
        tracks.append(_track(_abs_url(attrs["uri"], base_url),
                             _language_label(attrs.get("language")) or attrs.get("name"),
                             attrs.get("language"), None, attrs.get("name"),
                             "hls-media", is_default=attrs.get("default") == "YES",
                             is_forced=attrs.get("forced") == "YES"))
    return tracks


def _player_subtitle_config(body: str) -> dict:
    """
    Reads `csPlayerConfig.subtitles` from a page or player script body.

    The shipped config names seven languages but points baseUrl at the literal
    https://sub.example.com, and the real host is decrypted at runtime. A
    placeholder is therefore recorded as declared_languages only — no URL is
    synthesized, because a fabricated track row is worse than an honest gap.
    """
    m = CSPLAYER_CONFIG_RE.search(body or "")
    if not m:
        return {}
    blob = m.group(1)
    base_m = CS_BASE_RE.search(blob)
    base_url = base_m.group(1) if base_m else None
    langs: dict[str, str] = {}
    langs_m = CS_LANGS_RE.search(blob)
    if langs_m:
        for name, code in CS_LANG_PAIR_RE.findall(langs_m.group(1)):
            langs[name] = code.lower()
    return {
        "base_url": base_url if base_url and not _is_placeholder_url(base_url) else None,
        "declared_base_url": base_url,
        "declared_languages": langs,
        "usable": bool(base_url and not _is_placeholder_url(base_url)),
    }


def harvest_subtitles(body: str, page_url: str = BASE_URL) -> list[dict]:
    """
    Every discoverable subtitle track, one dict per track.

    Sources, in order: <track> tags, download anchors, JSON track maps, HLS
    #EXT-X-MEDIA renditions. Deduplication is per (URL, language, label) — two
    English tracks (full and forced) are two tracks and must both survive.
    """
    tracks: list[dict] = []

    for tag in TRACK_TAG_RE.findall(body or ""):
        attrs = _parse_attrs(tag)
        url = attrs.get("src")
        if not url:
            continue
        tracks.append(_track(
            _abs_url(url, page_url),
            _language_label(attrs.get("srclang")) or attrs.get("label"),
            attrs.get("srclang"), None, attrs.get("label"), "track-tag",
            is_default=attrs.get("default") in ("", "default", "true"),
        ))

    for m in ANCHOR_RE.finditer(body or ""):
        href = m.group("href")
        if not SUBTITLE_EXT_RE.search(href):
            continue
        label = _clean_text(m.group("inner"))
        tracks.append(_track(_abs_url(href, page_url), label, None, None, label, "anchor"))

    tracks.extend(_json_track_blocks(body, page_url))
    tracks.extend(_hls_subtitles(body, page_url))

    seen: set[tuple] = set()
    unique: list[dict] = []
    for track in tracks:
        if not track.get("source_url") or _is_tracker(track["source_url"]):
            continue
        key = (track["source_url"], track.get("language"), track.get("label"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(track)
    return unique


def parse_hls_master(text: str, base_url: str = BASE_URL) -> dict:
    """Reads quality variants and subtitle renditions out of an HLS master."""
    variants: list[dict] = []
    lines = [ln.strip() for ln in (text or "").splitlines()]
    for i, line in enumerate(lines):
        m = HLS_STREAM_INF_RE.match(line)
        if not m:
            continue
        attrs = _parse_hls_attrs(m.group(1))
        uri = next((ln for ln in lines[i + 1:] if ln and not ln.startswith("#")), None)
        if not uri:
            continue
        height = None
        res_m = re.search(r"(\d{2,5})x(\d{2,5})", attrs.get("resolution", ""))
        if res_m:
            height = int(res_m.group(2))
        quality = None
        for prefix, height_val in (("2160", 2160), ("1440", 1440), ("1080", 1080),
                                   ("720", 720), ("576", 576), ("480", 480), ("360", 360)):
            if height and height >= height_val:
                quality = f"{prefix}p"
                break
        if not quality:
            quality_m = QUALITY_RE.search(attrs.get("name", "") + " " + uri)
            quality = quality_m.group(1).lower() if quality_m else None
        variants.append({"url": _abs_url(uri, base_url), "quality": quality,
                         "bandwidth": attrs.get("bandwidth")})
    return {"variants": variants, "subtitles": _hls_subtitles(text, base_url)}


def parse_page(html_or_url: str, url: str | None = None) -> dict | None:
    """
    Extracts clean metadata, episodes, subtitle tracks and the player bridge.

    Accepts a URL (fetched here) or a body plus its URL. Returns None for a
    shelf/search page, a 404, or the site's homepage.
    """
    return _parse_page(html_or_url, url)[0]


def _parse_page(html_or_url: str, url: str | None = None) -> tuple[dict | None, str]:
    body = html_or_url or ""
    page_url = url
    if page_url is None and re.match(r"^https?://", body.strip()):
        page_url, body = body.strip(), ""
    requested = page_url or ""
    if not body:
        if not page_url:
            return None, "not-a-post"
        status, final_url, body = http_get(page_url)
        if status != 200:
            return None, "http-error"
        page_url = final_url or page_url
    if not page_url:
        return None, "not-a-post"

    path = urllib.parse.urlsplit(page_url).path
    if path in ("", "/") or any(path.startswith(p) for p in NON_POST_PREFIXES):
        return None, "not-a-post"
    if not re.match(r"^/(?:series/)?[^/]+/?$", path):
        return None, "not-a-post"

    metas = _meta_tags(body)
    raw_title = _clean_text(H1_RE.search(body).group(1)) if H1_RE.search(body) else ""
    raw_title = raw_title or metas.get("og:title") or \
        (_clean_text(TITLE_TAG_RE.search(body).group(1)) if TITLE_TAG_RE.search(body) else "")
    if not raw_title:
        return None, "removed"

    series_h2 = _series_title(body, metas)
    info = _info_block(body)
    info_links = info.get("__links", {})
    genres = [_meaningful(_clean_text(t)) for _h, t in
              ANCHOR_RE.findall(GENRES_RE.search(body).group(1))] if GENRES_RE.search(body) else []
    genres = [g for g in genres if g]
    category = info.get("type", "")
    country = info.get("country", "")
    status_label = info.get("status", "")
    network = info.get("network", "")
    released = info.get("released", "")
    duration = info.get("duration", "")
    episode_field = info.get("episodes", "")

    # Identity: the <h2> with the year outranks the watch-page <h1>, which is
    # packaging ("– Watch Full Episodes Eng Sub").
    identity_source = series_h2 or raw_title
    released_year_m = YEAR_RE.search(released)
    slug = urllib.parse.unquote(urllib.parse.urlsplit(page_url).path.strip("/").split("/")[-1])
    identity = parse_title(identity_source, slug)
    if identity["year"] is None and released_year_m:
        identity["year"] = int(released_year_m.group(1))
        identity["canonical_key"] = build_canonical_key(
            identity["clean_title"], identity["year"], identity["season_number"], slug)
    if identity["year"] is None and re.search(r"(?:19|20)\d{2}", raw_title):
        identity["year"] = int(YEAR_RE.search(raw_title).group(1))
        identity["canonical_key"] = build_canonical_key(
            identity["clean_title"], identity["year"], identity["season_number"], slug)

    lowered = f"{raw_title} {series_h2} {slug} {category}".lower()
    is_movie = bool(re.search(r"watch\s+full\s+movie|-watch-full-movie\b", lowered)) \
        or category.strip().lower() == "movie"
    available, declared = _episode_count(body, info, "movie" if is_movie else "series")

    content_type = "movie" if is_movie else ("complete_season" if status_label.lower().startswith("complet")
                                             else "series")

    cast = info.get("casts", "")
    if not cast:
        cast = ", ".join(_clean_text(t) for _h, t in info_links.get("casts", []))
    poster = ""
    thumb_m = re.search(r"""<div\b[^>]*class=["'][^"']*\bthumb\b[^"']*["'][^>]*>\s*<img\b[^>]*src=["']([^"']+)["']""",
                        body, re.S | re.I)
    if thumb_m:
        poster = _abs_url(thumb_m.group(1), page_url)
    poster = poster or metas.get("og:image") or ""
    backdrop = metas.get("og:image") or ""
    synopsis = _meaningful(_clean_text(SYNOPSIS_RE.search(body).group(1))) if SYNOPSIS_RE.search(body) else ""
    synopsis = _meaningful(synopsis) or _meaningful(metas.get("og:description", ""))
    alt_titles = [t.strip() for t in _clean_text(ALTER_RE.search(body).group(1)).split(",")
                  if t.strip()] if ALTER_RE.search(body) else []

    player_m = PLAYER_ID_RE.search(body)
    player_id = (player_m.group(1) or player_m.group(2)) if player_m else None
    player_script_m = PLAYER_SCRIPT_RE.search(body)
    player_script = _abs_url(player_script_m.group(1), page_url) if player_script_m else None
    subtitle_config = _player_subtitle_config(body)
    subtitle_tracks = harvest_subtitles(body, page_url)

    # Direct playables published on the page, if any (the page rarely has them).
    direct_media: list[str] = []
    for m in re.finditer(r"""(?:src|href|file|url)=["']([^"']+?\.(?:m3u8|mp4|mkv|webm)(?:[?#][^"']*)?)["']""",
                         body, re.I):
        candidate = _abs_url(m.group(1), page_url)
        if not _is_tracker(candidate) and candidate not in direct_media:
            direct_media.append(candidate)

    language = COUNTRY_LANGUAGE.get(country.strip().lower()) or "Unknown"

    episode_numbers: list[int | None]
    if is_movie:
        episode_numbers = [None]
    else:
        episode_numbers = list(range(1, (available or 0) + 1)) or [None]

    tracks_by_episode: dict[int | None, list[dict]] = {}
    for track in subtitle_tracks:
        ep = track.get("episode_number")
        tracks_by_episode.setdefault(ep, []).append(track)

    releases: list[dict] = []
    for ep in episode_numbers:
        label = "Movie" if ep is None else f"Episode {ep}"
        sources: list[dict] = []
        if player_id:
            sources.append({
                "source_name": "CS Player",
                "service": "csplayer",
                "resource_id": player_id,
                "source_url": page_url,
                "final_url": page_url,
                "playback_type": "embed",
                "status": "unknown",
                "is_temporary": 0,
                "quality": None,
            })
        for media_url in direct_media:
            sources.append({
                "source_name": "Direct",
                "service": "direct",
                "resource_id": player_id,
                "source_url": media_url,
                "final_url": media_url,
                "playback_type": "stream" if media_url.endswith(".m3u8") else "download",
                "status": "unknown",
                "is_temporary": 1 if urllib.parse.urlsplit(media_url).query else 0,
                "quality": (QUALITY_RE.search(media_url) or [None])[0],
            })
        release_tracks = list(tracks_by_episode.get(ep, []))
        if not is_movie and ep is None:
            release_tracks = subtitle_tracks
        for track in release_tracks:
            quality_m = QUALITY_RE.search(track["source_url"])
            sources.append({
                "source_name": f"Subtitle: {track['language']}"
                               + (f" ({track['label']})" if track.get("label") else ""),
                "service": "subtitle",
                "resource_id": track.get("language_code") or track["language"],
                "source_url": track["source_url"],
                "final_url": track["source_url"],
                "playback_type": "subtitle",
                "status": "unknown",
                "is_temporary": 0,
                "quality": quality_m.group(1).lower() if quality_m else None,
                "language": track["language"],
                "format": track.get("format"),
            })
        releases.append({
            "label": label,
            "quality": None,
            "codec": None,
            "size_bytes": None,
            "audio_languages": language if language != "Unknown" else None,
            "season_number": identity["season_number"],
            "episode_number": ep,
            "bridge_url": page_url,
            "sources": sources,
        })

    seasons_json = None
    if not is_movie and any(r["episode_number"] is not None for r in releases):
        season = identity["season_number"] or 1
        seasons_json = json.dumps([{
            "season": season,
            "episodes": [{"episode": r["episode_number"], "title": r["label"]}
                         for r in releases if r["episode_number"] is not None],
        }], ensure_ascii=False)

    labels_for_adult = (raw_title, series_h2, ", ".join(genres), category,
                        ", ".join(alt_titles), " ".join(
                            t for t in (metas.get("keywords", ""),) if t))
    subtitles_map = [dict(t) for t in subtitle_tracks]
    if not subtitle_config.get("usable"):
        # Keep the declared languages visible, but explicitly mark them as
        # non-addressable so no consumer mistakes them for track URLs.
        subtitle_config["tracks_published"] = False

    return {
        "url": page_url,
        "slug": slug,
        "post_id": player_id,
        "title": series_h2 or scrub_brand(raw_title) or raw_title,
        "clean_title": identity["clean_title"],
        "year": identity["year"],
        "content_type": content_type,
        "season_number": identity["season_number"],
        "seasons": seasons_json,
        "poster_url": poster or None,
        "backdrop_urls": [backdrop] if backdrop else None,
        "imdb_id": (IMDB_ID_RE.search(synopsis or "") or [None])[0]
        if IMDB_ID_RE.search(synopsis or "") else None,
        "tmdb_id": None,
        "imdb_rating": (RATING_RE.search(info.get("rating", "")) or [None])[0]
        if RATING_RE.search(info.get("rating", "")) else None,
        "genres": ", ".join(dict.fromkeys(genres)) if genres else None,
        "synopsis": synopsis or None,
        "cast_names": cast or None,
        "director": info.get("director") or None,
        "duration": duration or None,
        "release_date": released or None,
        "languages": language,
        "category": category or None,
        "is_18_plus": 1 if is_adult_content(*labels_for_adult, prose=(synopsis,)) else 0,
        "is_animated": 1 if looks_animated(raw_title, series_h2, ", ".join(genres), slug) else 0,
        "source_site": SITE,
        "canonical_key": identity["canonical_key"],
        "releases": releases,
        "raw_meta": {
            "info": {k: v for k, v in info.items() if not k.startswith("__")},
            "alternate_titles": alt_titles,
            "network": network,
            "status": status_label,
            "episodes_declared": declared,
            "episodes_available": available,
            "player_post_id": player_id,
            "player_script": player_script,
            "subtitles": subtitles_map,
            "subtitle_config": subtitle_config,
            "meta_tags": {k: v for k, v in metas.items()
                          if k.startswith("og:") or k in ("description", "keywords")},
        },
    }, "ok"


# ---------------------------------------------------------------------------
# Public contract: resolve_links
# ---------------------------------------------------------------------------

MAX_PROBES_PER_POST = 24


def resolve_links(post_data: dict, probe: bool = True) -> dict:
    """
    Probes every distinct source URL once and expands HLS masters.

    probe=False is a hard no-network path (a test asserts it). A dead link is
    kept with status='dead'; the catalog records link health rather than losing
    the row. A player bridge that has no published stream/subtitle URL stays an
    honest 'embed' row: the page is reachable, the playable is JS-only.
    """
    if not post_data:
        return post_data
    if not probe:
        return post_data

    referer = post_data.get("url")
    probed: dict[str, tuple[str, str]] = {}
    budget = MAX_PROBES_PER_POST

    for release in post_data.get("releases") or []:
        sources = list(release.get("sources") or [])
        expanded: list[dict] = []
        for src in sources:
            url = src.get("source_url")
            if not url:
                continue
            if url not in probed and budget > 0:
                probed[url] = probe_source(url, referer=referer)
                budget -= 1
            status, body = probed.get(url, ("error", ""))
            if src.get("playback_type") == "embed" and status == "active":
                # The bridge page must still contain the player container.
                if "cs-player" not in (body or "").lower() and "<iframe" not in (body or "").lower():
                    status = "error"
            src["status"] = status
            src["last_checked"] = int(time.time())
            if src.get("final_url") is None:
                src["final_url"] = url

            if status == "active" and url.lower().split("?")[0].endswith(".m3u8"):
                master = parse_hls_master(body, url)
                for variant in master["variants"]:
                    expanded.append({
                        "source_name": f"Variant {variant.get('quality') or 'auto'}",
                        "service": "hls",
                        "resource_id": src.get("resource_id"),
                        "source_url": variant["url"],
                        "final_url": variant["url"],
                        "playback_type": "stream",
                        "status": "unknown",
                        "is_temporary": 1 if urllib.parse.urlsplit(variant["url"]).query else 0,
                        "quality": variant.get("quality"),
                    })
                for track in master["subtitles"]:
                    expanded.append({
                        "source_name": f"Subtitle: {track['language']}"
                                       + (f" ({track['label']})" if track.get("label") else ""),
                        "service": "subtitle",
                        "resource_id": track.get("language_code") or track["language"],
                        "source_url": track["source_url"],
                        "final_url": track["source_url"],
                        "playback_type": "subtitle",
                        "status": "unknown",
                        "is_temporary": 0,
                        "quality": None,
                        "language": track["language"],
                        "format": track.get("format"),
                    })
        if expanded:
            seen = {(s.get("source_url"), s.get("language")) for s in sources}
            for extra in expanded:
                key = (extra.get("source_url"), extra.get("language"))
                if key not in seen:
                    seen.add(key)
                    sources.append(extra)
        release["sources"] = sources
    return post_data


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(post_data: dict) -> dict:
    blob = " ".join(filter(None, [post_data.get("clean_title"), post_data.get("genres"),
                                  post_data.get("category"), post_data.get("slug")])).lower()
    industry = "Asian Drama"
    for needle, label in GENRE_INDUSTRY:
        if needle in blob:
            industry = label
            break
    if post_data.get("content_type") == "movie":
        industry = "Asian Movie"
    return {
        "industry": industry,
        "country": post_data.get("country") or (
            "South Korea" if "korean" in blob else "China" if "chinese" in blob
            else "Japan" if "japanese" in blob else "Thailand" if "thai" in blob
            else "Unknown"),
        "languages": post_data.get("languages") or "Unknown",
    }


# ---------------------------------------------------------------------------
# Staging database
# ---------------------------------------------------------------------------

POST_COLUMNS = (
    "canonical_key", "title", "clean_title", "year", "media_type", "poster_url",
    "backdrop_url", "backdrop_urls", "imdb_id", "tmdb_id", "imdb_rating", "synopsis",
    "genres", "director", "cast_names", "duration", "release_date", "languages",
    "industry", "country", "seasons", "url", "slug", "is_18_plus", "is_animated",
    "source_site", "raw_meta",
)

STAGING_NAME = "dramacool.db"


def _guard_db_path(db_path: Path | str) -> Path:
    """Refuses anything that is not this site's isolated staging file."""
    path = Path(db_path)
    name = path.name.lower()
    if name == "fast_fetch.db" or name.startswith("merged_catalog_") \
            or name.endswith("_merged.db"):
        raise ValueError(f"refusing to write production catalog: {path}")
    return path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
            source_site TEXT DEFAULT 'dramacool',
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
            origin_url TEXT,
            FOREIGN KEY (post_canonical_key) REFERENCES posts(canonical_key)
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
            status TEXT DEFAULT 'active',
            is_temporary INTEGER DEFAULT 0,
            quality TEXT,
            last_checked INTEGER,
            FOREIGN KEY (release_id) REFERENCES releases(id)
        );

        CREATE INDEX IF NOT EXISTS idx_dramacool_posts_slug ON posts(slug);
        CREATE INDEX IF NOT EXISTS idx_dramacool_posts_year ON posts(year);
        CREATE INDEX IF NOT EXISTS idx_dramacool_sources_type ON sources(playback_type);
        CREATE INDEX IF NOT EXISTS idx_dramacool_sources_status ON sources(status);
        """
    )
    existing = {c[1] for c in conn.execute("PRAGMA table_info(posts);").fetchall()}
    for col, decl in (("industry", "TEXT"), ("country", "TEXT"), ("duration", "TEXT"),
                      ("release_date", "TEXT"), ("imdb_rating", "TEXT"),
                      ("backdrop_urls", "TEXT"), ("seasons", "TEXT")):
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE posts ADD COLUMN {col} {decl};")
            except sqlite3.OperationalError:
                pass
    rel_cols = {c[1] for c in conn.execute("PRAGMA table_info(releases);").fetchall()}
    if "origin_url" not in rel_cols:
        try:
            conn.execute("ALTER TABLE releases ADD COLUMN origin_url TEXT;")
        except sqlite3.OperationalError:
            pass


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    """Creates the isolated staging schema (idempotent). Returns the path."""
    path = _guard_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    try:
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    """
    Commits parsed post dicts into the isolated staging database.

    Idempotent per page: a re-scraped page replaces the releases that same page
    produced (matched by origin_url), never another page's.
    """
    db_path = _guard_db_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    stats_out = {"posts_written": 0, "releases_written": 0,
                 "sources_written": 0, "subtitle_sources": 0, "skipped": 0}

    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        for post in posts or ():
            if not post or not post.get("clean_title") or not post.get("canonical_key"):
                stats_out["skipped"] += 1
                continue
            rels = post.get("releases") or []
            if not rels:
                stats_out["skipped"] += 1
                continue

            backdrops = post.get("backdrop_urls")
            if backdrops and not isinstance(backdrops, str):
                backdrops = json.dumps(backdrops, ensure_ascii=False)
            backdrop_list: list[str] = []
            if backdrops:
                try:
                    parsed = json.loads(backdrops)
                    backdrop_list = parsed if isinstance(parsed, list) else [str(parsed)]
                except (json.JSONDecodeError, TypeError):
                    backdrop_list = [backdrops]
            raw_meta = post.get("raw_meta")
            if not isinstance(raw_meta, str):
                raw_meta = json.dumps(raw_meta or {}, ensure_ascii=False)
            cls = classify(post)

            row = {
                "canonical_key": post["canonical_key"],
                "title": post.get("title") or post["clean_title"],
                "clean_title": post["clean_title"],
                "year": post.get("year"),
                "media_type": post.get("content_type") or "series",
                "poster_url": post.get("poster_url"),
                "backdrop_url": backdrop_list[0] if backdrop_list else None,
                "backdrop_urls": backdrops,
                "imdb_id": post.get("imdb_id"),
                "tmdb_id": post.get("tmdb_id"),
                "imdb_rating": post.get("imdb_rating"),
                "synopsis": post.get("synopsis"),
                "genres": post.get("genres"),
                "director": post.get("director"),
                "cast_names": post.get("cast_names"),
                "duration": post.get("duration"),
                "release_date": post.get("release_date"),
                "languages": post.get("languages") or cls["languages"],
                "industry": cls["industry"],
                "country": cls["country"],
                "seasons": post.get("seasons"),
                "url": post.get("url"),
                "slug": post.get("slug"),
                "is_18_plus": int(post.get("is_18_plus") or 0),
                "is_animated": int(post.get("is_animated") or 0),
                "source_site": SITE,
                "raw_meta": raw_meta,
            }
            placeholders = ", ".join(f":{c}" for c in POST_COLUMNS)
            updates = ", ".join(
                f"{c} = COALESCE(excluded.{c}, posts.{c})"
                for c in POST_COLUMNS
                if c not in ("canonical_key", "title", "clean_title", "media_type",
                             "url", "slug", "source_site", "raw_meta",
                             "is_18_plus", "is_animated")
            )
            conn.execute(
                f"""
                INSERT INTO posts ({", ".join(POST_COLUMNS)}) VALUES ({placeholders})
                ON CONFLICT(canonical_key) DO UPDATE SET
                    title = excluded.title,
                    clean_title = excluded.clean_title,
                    media_type = excluded.media_type,
                    url = excluded.url,
                    slug = excluded.slug,
                    source_site = excluded.source_site,
                    raw_meta = excluded.raw_meta,
                    is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus),
                    is_animated = MAX(posts.is_animated, excluded.is_animated),
                    {updates},
                    scraped_at = CURRENT_TIMESTAMP;
                """,
                row,
            )
            stats_out["posts_written"] += 1

            page_url = row["url"]
            stale = [r["id"] for r in conn.execute(
                "SELECT id FROM releases WHERE post_canonical_key = ?"
                " AND (origin_url = ? OR origin_url IS NULL)",
                (post["canonical_key"], page_url)).fetchall()]
            if stale:
                conn.executemany("DELETE FROM sources WHERE release_id = ?;",
                                 [(i,) for i in stale])
                conn.executemany("DELETE FROM releases WHERE id = ?;",
                                 [(i,) for i in stale])

            for rel in rels:
                cur = conn.execute(
                    """
                    INSERT INTO releases (post_canonical_key, label, quality, resolution,
                        size_bytes, codec, season_number, episode_number,
                        audio_languages, bridge_url, origin_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        post["canonical_key"], rel.get("label"), rel.get("quality"),
                        rel.get("quality"), rel.get("size_bytes"), rel.get("codec"),
                        rel.get("season_number"), rel.get("episode_number"),
                        rel.get("audio_languages"), rel.get("bridge_url"), page_url,
                    ),
                )
                stats_out["releases_written"] += 1
                for src in rel.get("sources", []):
                    conn.execute(
                        """
                        INSERT INTO sources (release_id, source_name, service, resource_id,
                            source_url, final_url, playback_type, status, is_temporary,
                            quality, last_checked)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            cur.lastrowid, src.get("source_name"), src.get("service"),
                            src.get("resource_id"), src.get("source_url"),
                            src.get("final_url") or src.get("source_url"),
                            src.get("playback_type", "url"), src.get("status", "unknown"),
                            src.get("is_temporary", 0),
                            src.get("quality") or rel.get("quality"),
                            src.get("last_checked"),
                        ),
                    )
                    stats_out["sources_written"] += 1
                    if src.get("playback_type") == "subtitle":
                        stats_out["subtitle_sources"] += 1

            if row["url"]:
                conn.execute(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                    VALUES (?, ?, ?, 1, ?, 0)
                    ON CONFLICT(loc) DO UPDATE SET scraped = 1, slug = excluded.slug;
                    """,
                    (row["url"], post.get("lastmod"), row["slug"], raw_meta),
                )
        conn.commit()
    finally:
        conn.close()
    return stats_out


# ---------------------------------------------------------------------------
# Public contract: sync_catalog (+ crawl driver)
# ---------------------------------------------------------------------------

def _iter_sitemap_locs(root_url: str, depth: int = 0, max_depth: int = 3):
    """Yields (loc, lastmod) from a urlset, following post-sitemap children."""
    status, _, body = http_get(root_url)
    if status != 200:
        print(f"[!] Sitemap {root_url} -> HTTP {status}", flush=True)
        return
    entries = re.findall(
        r"<url>\s*<loc>\s*(https?://[^<\s]+)\s*</loc>\s*(?:<lastmod>\s*([^<\s]*)\s*</lastmod>)?",
        body, re.I)
    if not entries:
        entries = [(loc, "") for loc in
                   re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", body, re.I)]
    if "<sitemapindex" in body.lower() and depth < max_depth:
        for child, _lm in entries:
            # Works live in post sitemaps; series/category/genre sitemaps are
            # metadata shelves and would file the same work twice.
            if POST_SITEMAP_RE.search(child):
                yield from _iter_sitemap_locs(child, depth + 1, max_depth)
        return
    for loc, lastmod in entries:
        yield loc, lastmod


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    """Queues catalog pages from sitemap.xml into sitemap_cache."""
    db_path = _guard_db_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for loc, lastmod in _iter_sitemap_locs(SITEMAP_URL):
        path = urllib.parse.urlsplit(loc).path
        if path in ("", "/") or any(path.startswith(p) for p in NON_POST_PREFIXES):
            continue
        if not re.match(r"^/[^/]+/?$", path):
            continue
        if loc in seen:
            continue
        seen.add(loc)
        records.append((loc, lastmod or "", urllib.parse.unquote(path.strip("/"))))
        if limit and len(records) >= limit:
            break

    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        before = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        conn.executemany(
            """
            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
            VALUES (?, ?, ?, 0, NULL, 0)
            ON CONFLICT(loc) DO UPDATE SET slug = excluded.slug;
            """,
            records,
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
    finally:
        conn.close()

    if verbose:
        if not records:
            print("[!] Sitemap yielded no catalog entries; nothing queued.", flush=True)
        else:
            print(f"[✓] [{SITE}] Queued {len(records)} post URLs "
                  f"({after - before} new, {after} total).", flush=True)
    return after - before


def _bump_error(db_path: Path, loc: str, note: str, park_now: bool = False) -> None:
    if not loc:
        return
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        conn.execute(
            "UPDATE sitemap_cache SET error_count = error_count + 1, raw_json = ? WHERE loc = ?;",
            (json.dumps({"last_note": note, "at": int(time.time())}), loc))
        conn.execute(
            "UPDATE sitemap_cache SET scraped = -1 WHERE loc = ? AND (error_count >= 3 OR ?);",
            (loc, 1 if park_now else 0))
        conn.commit()
    finally:
        conn.close()


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 3, probe: bool = False,
                  delay: float = 0.2, batch_size: int = 10,
                  verbose: bool = True) -> dict:
    """Fetches, parses and commits every queued sitemap entry."""
    db_path = _guard_db_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        rows = conn.execute(PENDING_SELECT, QUEUED_SCRAPE_STATES).fetchall()
    finally:
        conn.close()
    if limit:
        rows = rows[:limit]
    if verbose:
        print(f"[*] [{SITE}] {len(rows)} pages pending "
              f"(workers={workers}, probe={probe}).", flush=True)

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "subtitle_sources": 0, "not_indexable": 0, "failed": 0}
    if not rows:
        return totals

    def work(loc: str):
        if STOP_REQUESTED:
            return None
        time.sleep(delay)
        post, verdict = _parse_page(loc)
        if post is None:
            return None, verdict
        try:
            return resolve_links(post, probe=probe), verdict
        except Exception as exc:  # keep the catalog even if a probe dies
            post["resolve_error"] = str(exc)
            return post, verdict

    batch: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_to_loc = {pool.submit(work, r["loc"]): r["loc"] for r in rows}
        done = 0
        for fut in concurrent.futures.as_completed(future_to_loc):
            loc = future_to_loc[fut]
            done += 1
            totals["pages"] += 1
            try:
                outcome = fut.result()
            except Exception as exc:
                totals["failed"] += 1
                _bump_error(db_path, loc, f"exception: {exc}")
                continue
            if outcome is None:
                continue
            post, verdict = outcome
            if post is None:
                totals["not_indexable"] += 1
                _bump_error(db_path, loc, verdict,
                            park_now=verdict in ("removed", "not-a-post"))
                continue
            batch.append(post)
            if len(batch) >= batch_size:
                _flush(db_path, batch, totals)
                batch = []
            if verbose and done % 50 == 0:
                print(f"    ... {done}/{len(rows)} pages, {totals['sources']} sources",
                      flush=True)
            if STOP_REQUESTED:
                break
        _flush(db_path, batch, totals)

    if verbose:
        print(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"subtitle={totals['subtitle_sources']} "
              f"not-indexable={totals['not_indexable']} failed={totals['failed']}", flush=True)
    return totals


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    if not batch:
        return
    written = export_staging(db_path, batch)
    totals["posts"] += written["posts_written"]
    totals["releases"] += written["releases_written"]
    totals["sources"] += written["sources_written"]
    totals["subtitle_sources"] += written["subtitle_sources"]
    batch.clear()


def get_stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        return {
            "queued": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0,2)").fetchone()[0],
            "indexed": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0],
            "parked": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "adult_flagged": conn.execute("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "subtitle_sources": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'subtitle'").fetchone()[0],
            "stream_sources": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'stream'").fetchone()[0],
            "download_sources": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'download'").fetchone()[0],
            "embed_sources": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'embed'").fetchone()[0],
            "source_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
            "services": dict(conn.execute(
                "SELECT service, COUNT(*) FROM sources GROUP BY service ORDER BY COUNT(*) DESC")
                .fetchall()),
            "subtitle_languages": dict(conn.execute(
                "SELECT resource_id, COUNT(*) FROM sources WHERE playback_type = 'subtitle'"
                " GROUP BY resource_id ORDER BY COUNT(*) DESC").fetchall()),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"dramacool staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single page URL for parse/resolve")
    parser.add_argument("--probe", action="store_true",
                        help="probe source URLs (and expand HLS) during crawl/resolve")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    db = Path(args.db)
    verbose = not args.quiet

    if args.command == "sync":
        sync_catalog(limit=args.limit, db_path=db, verbose=verbose)
    elif args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=db, workers=args.workers,
                      probe=args.probe, verbose=verbose)
    elif args.command == "stats":
        print(json.dumps(get_stats(db), indent=2, ensure_ascii=False))
    else:
        if not args.url:
            parser.error(f"{args.command} requires --url")
        post = parse_page(args.url)
        if post is None:
            print("[!] Page is not a catalog entry.", file=sys.stderr)
            return 1
        if args.command == "resolve":
            resolve_links(post, probe=True)
        print(json.dumps(post, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
