#!/usr/bin/env python3
"""
import_moviecok.py — isolated staging importer for https://moviecok.xyz

Writes ONLY to /home/ubuntu/radd-stream-data/moviecok.db. It never touches the
production catalog or another site's staging database; merge with
Fast_Fetch/merge_catalogs.py after operator review. Pure Python standard
library, zero pip packages.

The site's model, as verified live (October 2026):

    https://moviecok.xyz/                     WordPress front page ("Bollyflix"
                                              branding, og:site_name "HDHUB4U")
    /sitemap_index.xml                        Rank Math index
      -> post-sitemap1.xml … post-sitemap10.xml   ~200 posts each
      -> page-sitemap.xml, category-sitemap.xml   shelves, never posts
    /free-<slug>/                             one catalog page, e.g.
        .mv-top-title       "Free Babbar (2022) (Hindi + Punjabi) Dual Audio …"
        .mv-poster img      poster
        .mv-body-left       Genre / Duration / Release Date / Language /
                            Starcast / Size / Description spans
        .mv-screenshots     screenshot images
        .mv-download-box    one .mv-dl-btn per print:
            <a class="mv-dl-btn" href="https://10moviesz.mom/?id=f8512cf8">
                <span class="mv-btn-text">DOWNLOAD 1080P HEVC</span></a>
        .mv-related-*       other posts; never this post's metadata

The site publishes every quality button with the SAME 10moviesz.mom short-link
id (verified on the movie and series pages probed). That short link is the
bridge to the file host, and 10moviesz.mom answers the stdlib client with a
Cloudflare JS challenge:

    HTTP 403, Cf-Mitigated: challenge, body "<title>Just a moment...</title>"

Per the project's rules the challenge is NOT bypassed. A probed bridge is
recorded as `js_required` (or `blocked`/`dead`) and kept, so link health stays
auditable. Each quality tier is still stored as its own release with its own
bridge source, exactly as the catalog page publishes them.

Subtitles: any .srt/.vtt/.ass/.ssa anchor on a catalog page or on a reachable
bridge page becomes its own sources row with playback_type='subtitle', its
language preserved in source_name, and the full track list echoed in
raw_meta. No track is dropped for lacking a language guess.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html as html_mod
import http.cookiejar
import json
import os
import re
import signal
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://moviecok.xyz"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemap_index.xml"
SITEMAP_URL = f"{BASE_URL}/post-sitemap.xml"  # fallback if the index is missing
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/moviecok.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITE = "moviecok"

LEGAL_MEDIA_TYPES = ("movie", "series")
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC"
    % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

# Routes that are shelves or static pages, not catalog entries.
NON_POST_PREFIXES = ("/category/", "/tag/", "/author/", "/page/", "/feed",
                     "/contact", "/dmca", "/disclaimer", "/privacy")

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

# Host membership, label-anchored: the renamed site plus the two legacy names
# this family has used. A look-alike host is not the site.
SITE_HOST_RE = re.compile(
    r"""(?:^|\.)(?:moviecok\.[a-z]{2,}|bollyshares\.[a-z]{2,}|bollywood1\.[a-z]{2,})""",
    re.I)

TRACKER_HOST_RE = re.compile(
    r"""bit\.ly|tinyurl|short\.url|go\.links\.|doubleclick|googlesyndication"""
    r"""|google-analytics|googletagmanager|cloudflareinsights|histats"""
    r"""|scorecard|cnzz|hm\.baidu|recaptcha|pagead""",
    re.I)

# The short-link host that fronts every download button.
BRIDGE_HOST_RE = re.compile(r"""10movies?(?:z)?\.[a-z]{2,}""", re.I)

# Downstream hosts a reachable bridge can name (kept as mirrors, never dropped).
MIRROR_HOST_RE = re.compile(
    r"""hubcloud\.|hubdrive\.|gdflix\.|gdf lix|pixeldrain\.com|drive\.google\.com"""
    r"""|drive\.usercontent\.google\.com|gofile\.io|mega\.nz|megaup\.|1fichier\.com"""
    r"""|filepress\.|dropgalaxy\.|vikingfile\.|vcloud\.|fastdl\.|workers\.dev"""
    r"""|r2\.dev|storage\.googleapis\.com|video-downloads\.googleusercontent\.com"""
    r"""|streamtape\.|mixdrop\.|filemoon\.|dood\.|doodstream\.|streamhub\.|upcloud\.|playmogo\.""",
    re.I)

DIRECT_MEDIA_RE = re.compile(r"\.(?:mp4|mkv|webm|m3u8|mpd)(?:[?#]|$)", re.I)
SUBTITLE_RE = re.compile(r"\.(?:srt|vtt|ass|ssa)(?:[?#]|$)", re.I)

# Site branding that must not survive into a public display string. Kept to the
# names this family actually prints, so a real title is not eaten.
BRAND_TOKEN_RE = re.compile(
    r"""moviecok\w*|bollyshares\w*|bollywood1\w*|bollyflix\w*|bollyflex\w*"""
    r"""|hdhub4u\w*|10moviesz\w*|10moviez\w*|filmycab\w*|filmyfly\w*""",
    re.I)

# ---------------------------------------------------------------------------
# Text lexicons
# ---------------------------------------------------------------------------

ADULT_KEYWORDS = (
    "18+", "18 plus", "adult", "porn", "pornhub", "pornstar", "erotic", "xxx",
    "blue film", "bluefilm", "nude", "naked", "hentai", "onlyfans", "charmsukh",
    "gandii baat", "gandi baat", "hotshots", "kooku", "moodytapes", "ullu",
    "altbalaji", "alt balaji", "brazzers", "atrangii", "atrangi", "bablutv",
    "uucinema", "palang tod", "bhabhi", "milf", "uncensored", "softcore",
    "hardcore", "mms", "lust", "sensual", "sexy", "hot short film",
)

# Words that also appear in mainstream blurbs. A synopsis alone must never hide
# a title, because an 18+ row is hidden at every presentation surface.
AMBIGUOUS_ADULT_KEYWORDS = ("sexy", "lust", "sensual", "adult", "hot short film")

PROSE_ADULT_KEYWORDS = tuple(k for k in ADULT_KEYWORDS
                             if k not in AMBIGUOUS_ADULT_KEYWORDS)

AGE_CERT_RE = re.compile(
    r"[\(\[\{]\s*(?:18\s*\+|18\s*plus|u\s*/?\s*a|a\s*/\s*c|adult)\s*[\)\]\}]", re.I)

LANGUAGE_WORDS = (
    "hindi", "english", "tamil", "telugu", "malayalam", "kannada", "bengali",
    "marathi", "punjabi", "gujarati", "bhojpuri", "urdu", "nepali", "sinhala",
    "japanese", "korean", "chinese", "spanish", "french", "german", "italian",
    "russian", "arabic", "turkish", "thai", "vietnamese", "indonesian",
    "tagalog", "malaysian",
)

INDUSTRY_WORDS = (
    "bollywood", "hollywood", "tollywood", "kollywood", "mollywood", "pollywood",
    "south", "anime", "animated", "k-drama", "kdrama", "c-drama",
)

PLATFORM_WORDS = (
    "netflix", "amazon", "prime", "prime video", "hotstar", "jiohotstar", "jio",
    "voot", "sonyliv", "sony", "zee5", "hoichoi", "aha", "hulu", "disney",
    "colors", "star plus", "starplus", "altbalaji", "ullu", "mx player",
)

DESCRIPTOR_WORDS = LANGUAGE_WORDS + INDUSTRY_WORDS + PLATFORM_WORDS + (
    "dubbed", "dual audio", "multi audio", "esub", "subtitles", "episode",
    "episodes", "season", "web series", "tv show", "reality show",
)

QUALITY_RE = re.compile(r"\b(2160p|4k|uhd|1080p|720p|576p|480p|360p)\b", re.I)
CODEC_RE = re.compile(
    r"\b(HEVC|x265|x264|H265|H264|AV1|WEB-?DL|WEBRip|BluRay|BDrip|HDRip|"
    r"DVDScr|DVDRip|HDTC|HDCAM|HQCAM|PREDVD|CAM)\b", re.I)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SEASON_RE = re.compile(r"\bS(\d{1,2})\b|\bSeas[oe]n\s*(\d{1,2})\b", re.I)
EPISODE_RE = re.compile(
    r"\bS\d{1,2}\s*E(?:P)?\s*(\d{1,3})\b|\bEpisode\s*(\d{1,3})\b|\bEp\s*\.?\s*(\d{1,3})\b",
    re.I)
PART_RE = re.compile(r"\bPart\s*(\d{1,2})\b", re.I)
SIZE_TEXT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|KB|MB|PB)\b", re.I)
RATING_RE = re.compile(r"(?:imdb|rating)\D{0,8}(\d+(?:[.,]\d+)?)", re.I)
IMDB_ID_RE = re.compile(r"\b(tt\d{7,9})\b", re.I)

# A catalog page is /free-<slug>/ ; the slug is the stable handle.
POST_URL_RE = re.compile(r"^/free-(?P<slug>[^/?#]+?)/?$", re.I)
SHORT_ID_RE = re.compile(r"[?&]id=([A-Za-z0-9_\-]+)", re.I)

MV_CONTAINER_RE = re.compile(r"""<div\b[^>]*class=["'][^"']*\bmv-container\b[^"']*["']""",
                             re.I)
TOP_TITLE_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*\bmv-top-title\b[^"']*["'][^>]*>(?P<inner>.*?)</div>""",
    re.S | re.I)
INFO_NAME_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*\bmv-info-name\b[^"']*["'][^>]*>(?P<inner>.*?)</div>""",
    re.S | re.I)
POSTER_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*\bmv-poster\b[^"']*["'][^>]*>\s*<img\b[^>]*?src=["'](?P<src>[^"']+)["']""",
    re.S | re.I)
SCREENSHOTS_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*\bmv-screenshots\b[^"']*["'][^>]*>(?P<body>.*?)</div>""",
    re.S | re.I)
DOWNLOAD_BOX_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*\bmv-download-box\b[^"']*["'][^>]*>(?P<body>.*?)"""
    r"""(?=<div\b[^>]*class=["'][^"']*\bmv-related-(?:header|container)|$|\Z)""",
    re.S | re.I)
ANCHOR_RE = re.compile(
    r"""<a\b(?P<attrs>[^>]*)>(?P<inner>.*?)</a>""", re.S | re.I)
HREF_RE = re.compile(r"""\bhref=["'](?P<href>[^"']*)["']""", re.I)
CLASS_RE = re.compile(r"""\bclass=["'](?P<cls>[^"']*)["']""", re.I)
BTN_TEXT_RE = re.compile(
    r"""<span\b[^>]*class=["'][^"']*\bmv-btn-text\b[^"']*["'][^>]*>(?P<text>.*?)</span>""",
    re.S | re.I)
INFO_ROW_RE = re.compile(
    r"""<strong\b[^>]*class=["'][^"']*\blbl-(?P<key>[a-z0-9_\-]+)\b[^"']*["'][^>]*>"""
    r"""(?P<label>.*?)</strong>\s*<span\b[^>]*class=["'][^"']*\bval-[^"']*["'][^>]*>"""
    r"""(?P<val>.*?)</span>""",
    re.S | re.I)
META_RE = re.compile(
    r"""<meta\b[^>]*?(?:property|name)=["'](?P<key>[^"']+)["'][^>]*?content=["'](?P<val>[^"']*)["']"""
    r"""|<meta\b[^>]*?content=["'](?P<val2>[^"']*)["'][^>]*?(?:property|name)=["'](?P<key2>[^"']+)["']""",
    re.I)

INDUSTRY_COUNTRY = {
    "Tollywood": "India", "Bollywood": "India", "Pollywood": "India",
    "Kollywood": "India", "Mollywood": "India", "Hollywood": "USA",
    "Anime": "Japan", "K-Drama": "South Korea", "C-Drama": "China",
}
LANGUAGE_COUNTRY = {
    "hindi": "India", "tamil": "India", "telugu": "India", "malayalam": "India",
    "kannada": "India", "bengali": "Bangladesh", "marathi": "India",
    "punjabi": "India", "gujarati": "India", "bhojpuri": "India", "urdu": "Pakistan",
    "korean": "South Korea", "japanese": "Japan", "chinese": "China",
    "spanish": "Spain", "french": "France", "german": "Germany", "italian": "Italy",
    "russian": "Russia", "arabic": "Saudi Arabia", "turkish": "Turkey",
    "thai": "Thailand", "vietnamese": "Vietnam", "indonesian": "Indonesia",
    "tagalog": "Philippines", "english": "USA",
}

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

SSL_CONTEXT = ssl.create_default_context()
if os.environ.get("RADD_INSECURE_SSL") == "1":
    SSL_CONTEXT.check_hostname = False
    SSL_CONTEXT.verify_mode = ssl.CERT_NONE

_COOKIE_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=SSL_CONTEXT),
    urllib.request.HTTPCookieProcessor(_COOKIE_JAR),
    urllib.request.HTTPRedirectHandler(),
)
_OPENER.addheaders = [
    ("User-Agent", USER_AGENT),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "en-US,en;q=0.9"),
]


class _StopRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# A bridge's answer *is* its Location header, so the resolver needs a client
# that does not spend the redirect by following it silently.
_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=SSL_CONTEXT),
    urllib.request.HTTPCookieProcessor(_COOKIE_JAR),
    _StopRedirect(),
)
_NO_REDIRECT_OPENER.addheaders = [("User-Agent", USER_AGENT)]


def normalize_request_url(url: str | None) -> str:
    """
    The single URL normalisation the contract asks for: unescape the HTML
    entity layer, then percent-quote everything outside the HTTP reserved set.

    `quote(..., safe=":/?#[]@!$&'()*+,;=%")` preserves separators and existing
    escapes while turning spaces and non-ASCII into a request-safe URL.
    """
    raw = html_mod.unescape((url or "").strip())
    return urllib.parse.quote(raw, safe=":/?#[]@!$&'()*+,;=%")


def http_get(url: str, timeout: int = 30, retries: int = 3):
    """Returns (status_code, final_url, body) following redirects. Never raises."""
    target = normalize_request_url(url)
    last_status, last_url, last_body = 0, target, ""
    for attempt in range(1, retries + 1):
        try:
            resp = _OPENER.open(target, timeout=timeout)
            body = resp.read().decode("utf-8", "replace")
            return getattr(resp, "status", 200) or 200, resp.geturl(), body
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            try:
                last_body = exc.read().decode("utf-8", "replace")
            except Exception:
                last_body = ""
            if exc.code in (401, 403, 404, 410):
                return exc.code, target, last_body  # final — retrying a gate is rude
        except Exception as exc:
            last_status, last_body = 0, f"[network error] {exc}"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    return last_status, last_url, last_body


def http_get_once(url: str, referer: str | None = None, timeout: int = 25):
    """One request, redirects left alone: returns (status, location, body)."""
    target = normalize_request_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = normalize_request_url(referer)
    try:
        resp = _NO_REDIRECT_OPENER.open(
            urllib.request.Request(target, headers=headers), timeout=timeout)
        body = resp.read().decode("utf-8", "replace")
        status = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        resp = exc
    except Exception as exc:
        return 0, None, f"[network error] {exc}"
    location = None
    try:
        location = resp.headers.get("Location")
    except AttributeError:
        pass
    return status, location, body


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
    """Removes site branding and tag-spam from a display string."""
    if not text:
        return ""
    out = BRAND_TOKEN_RE.sub(" ", text)
    return re.sub(r"\s+", " ", out).strip(" -–\u00a7»|&,:;.")


def _adult_mark(text: str) -> bool:
    return bool(re.search(r"(?<!\d)18\s*\+|18\s*plus", text.lower()))


def _has_keyword(text: str, keywords) -> bool:
    padded = f" {re.sub(r'[^a-z ]+', ' ', text.lower())} "
    return any(f" {kw} " in padded for kw in keywords if kw not in ("18+", "18 plus"))


def is_adult_content(*labels: str | None, prose: tuple = ()) -> bool:
    """Flags adult material from titles, shelf categories and genre labels.

    A synopsis never flags on an ambiguous word: an 18+ row is hidden at every
    presentation surface, so hiding a mainstream title is the more expensive
    mistake.
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
    raw = _unescape((href or "").strip())
    if not raw or re.match(r"^(?:javascript|mailto|data):", raw, re.I):
        return ""
    return normalize_request_url(urllib.parse.urljoin(base, raw))


def _is_tracker(url: str) -> bool:
    return bool(TRACKER_HOST_RE.search(url or ""))


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc.lower().removeprefix("www.")


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _is_bridge_url(url: str) -> bool:
    return bool(BRIDGE_HOST_RE.search(_host_of(url)))


def _is_mirror_url(url: str) -> bool:
    return bool(MIRROR_HOST_RE.search(url or ""))


def _is_direct_media(url: str) -> bool:
    return bool(DIRECT_MEDIA_RE.search(urllib.parse.urlsplit(url or "").path))


def _is_subtitle_url(url: str) -> bool:
    return bool(SUBTITLE_RE.search(urllib.parse.urlsplit(url or "").path))


def _challenge_body(body: str | None) -> bool:
    head = (body or "")[:4000].lower()
    return ("just a moment" in head or "enable javascript" in head
            or "checking if you are" in head or "cf-mitigated" in head
            or "challenge-platform" in head)


def _is_temporary_url(url: str) -> int:
    """A signed/tokenised object expires; a bridge or plain host page does not."""
    parts = urllib.parse.urlsplit(url or "")
    query = parts.query.lower()
    if any(k in query for k in ("token=", "expires=", "signature=", "sig=", "x-amz-")):
        return 1
    host = _host_of(url)
    if "googleusercontent" in host or host.endswith("r2.dev") and query:
        return 1
    return 0


def parse_size_to_bytes(text: str | None) -> int | None:
    """
    '460Mb' / '1.2Gb' / '329.113 MB' -> bytes (binary units, catalog convention).

    A size below one megabyte is the site's placeholder, not a measurement, so
    it reads back as unknown rather than as a tier a file could never have.
    """
    if not text:
        return None
    m = SIZE_TEXT_RE.search(text)
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = m.group(2).upper()
    size = int(num * {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit])
    return size if size >= 1024 ** 2 else None


def _pretty_slug(slug: str) -> str:
    words = [w for w in re.split(r"[-_.]+", re.sub(r"[^\w\-_.]+", " ", slug or "")) if w]
    return " ".join(words).strip()


def normalize_quality(text: str | None) -> str | None:
    """Collapses the site's tier spellings to the catalog's four rungs."""
    blob = (text or "").lower()
    if re.search(r"\b(?:2160p|4k|uhd)\b", blob):
        return "4k"
    m = re.search(r"\b(1080p|720p|576p|480p|360p)\b", blob)
    return m.group(1) if m else None


def normalize_codec(text: str | None) -> str | None:
    m = CODEC_RE.search(text or "")
    if not m:
        return None
    codec = m.group(1).upper().replace("-", "")
    return {"WEBRIP": "WEBRip"}.get(codec, codec)


def _split_languages(text: str | None) -> list[str]:
    """Splits the site's 'Hindi + Punjabi' / 'Hindi & Korean' language cells."""
    out: list[str] = []
    for chunk in re.split(r"[+,/&|]|\band\b", text or ""):
        cleaned = re.sub(r"[^A-Za-z ]+", " ", chunk).strip().lower()
        if cleaned in LANGUAGE_WORDS:
            out.append(cleaned.title())
        elif cleaned:
            for word in LANGUAGE_WORDS:
                if re.search(rf"\b{word}\b", cleaned):
                    out.append(word.title())
    return list(dict.fromkeys(out))


def _languages_in(text: str | None) -> list[str]:
    padded = f" {re.sub(r'[^a-z ]+', ' ', (text or '').lower())} "
    return [w.title() for w in LANGUAGE_WORDS if f" {w} " in padded]


# ---------------------------------------------------------------------------
# Title / identity parsing
# ---------------------------------------------------------------------------

# Longest first so an alternation never leaves "dual" behind after "audio".
DESCRIPTOR_TITLES = tuple(sorted(
    set(LANGUAGE_WORDS + INDUSTRY_WORDS + PLATFORM_WORDS), key=len, reverse=True))

PACKAGING_TOKENS = frozenset({
    "free", "movie", "movies", "film", "films", "series", "web", "tv", "show",
    "reality", "hd", "hq", "sd", "esub", "esubbed", "dsub", "dub", "dubs",
    "hevc", "x264", "x265", "h264", "h265", "av1", "aac", "dd", "ddp",
    "uncut", "cut", "dual", "audio", "multi", "dubbed", "south", "southmovie",
    "completed", "complete", "latest", "new", "hdcam", "hqcam", "cam", "ts",
    "scr", "bluray", "blu", "ray", "bdrip", "brrip", "webdl", "webrip",
    "hdtc", "hdrip", "dvdrip", "dvdscr", "predvd", "dvd", "full", "download",
    "watch", "online", "official", "unrated", "extended", "episode",
    "episodes", "ep", "part", "season", "seasons", "hdr", "10bit", "8bit",
    "dts", "atmos", "4k", "uhd", "fhd", "hdtv", "original", "org", "added",
    "all", "mcu", "clean", "hdts", "hqhd", "hevc", "colors", "starplus",
    "plus", "today", "tonight",
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "september",
    "oct", "october", "nov", "november", "dec", "december",
}) | frozenset(DESCRIPTOR_TITLES) | frozenset(
    w.replace("-", "").replace(" ", "") for w in DESCRIPTOR_TITLES)

NUMBER_PREFIX_TOKENS = frozenset({"episode", "ep", "part", "season", "bonus", "add"})

MONTH_WORD = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
              r"(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember)?")


def _slug_title_base(slug: str) -> str:
    """
    Recovers the title part of a site slug by trimming packaging from the right.

    Right-hand trimming keeps numeric titles intact while dropping the trailing
    quality/language/date run this site appends to every URL.
    """
    text = re.sub(r"\.html?$", "", slug or "")
    text = re.sub(r"^free[-_]", "", text, flags=re.I)
    # Date runs, season/episode markers: removed before tokenisation so a bare
    # day number never survives beside the month name.
    text = re.sub(rf"\b\d{{1,2}}[-_]{MONTH_WORD}[-_]\d{{4}}\b", "-", text, flags=re.I)
    text = re.sub(rf"\b{MONTH_WORD}[-_]\d{{1,2}}[-_]\d{{4}}\b", "-", text, flags=re.I)
    text = re.sub(rf"\b{MONTH_WORD}[-_]\d{{4}}\b", "-", text, flags=re.I)
    text = re.sub(r"\bs\d{1,2}e\d{1,3}\b", "-", text, flags=re.I)
    text = re.sub(r"\bs\d{1,2}(?:[-_]s?\d{1,2})?\b", "-", text, flags=re.I)

    tokens = [t for t in re.split(r"[-_.\s]+|[()\[\]]", text) if t]
    while len(tokens) > 1:
        tail = tokens[-1].lower()
        if tail in PACKAGING_TOKENS:
            tokens.pop()
            continue
        # "TV Show" / "Reality Show" / "Web Series" are phrases, not titles.
        if (tail in ("show", "series") and len(tokens) > 1
                and tokens[-2].lower() in ("tv", "reality", "web")):
            tokens.pop()
            tokens.pop()
            continue
        if (re.fullmatch(r"(?:19|20)\d{2}", tail)
                or re.fullmatch(r"\d{3,4}p", tail)
                or re.fullmatch(r"s\d{1,2}(?:e\d{1,3})?", tail)):
            tokens.pop()
            continue
        if (re.fullmatch(r"\d{1,3}", tail) and len(tokens) > 2
                and tokens[-2].lower() in NUMBER_PREFIX_TOKENS):
            tokens.pop()
            continue
        break
    return "-".join(t.lower() for t in tokens if t).strip("-")


def build_canonical_key(clean_title: str, year: int | None, season: int | None,
                        episode: int | None, slug: str) -> str:
    """
    Slug-derived identity key.

    The slug is the stable handle for a page; a title-derived key would change
    every time the cleaner improves and strand the previous row.
    """
    base = (_slug_title_base(slug or "")
            or re.sub(r"[^a-z0-9]+", "-", (clean_title or "").lower()).strip("-"))
    key = f"{base}_{year}" if year else base
    if season:
        key += f"_s{season:02d}"
    if episode:
        key += f"_e{episode:02d}"
    return key or "unknown"


def _drop_packaging_brackets(title: str) -> tuple[str, list[str]]:
    """
    Returns the title without its packaging bracket groups, plus the groups.

    Brace groups are always packaging here. Parentheses are only dropped when
    they read as a language/quality/source note, so an alternate title like
    "(Naan Sigappu Manithan)" survives as the work's name.
    """
    groups: list[str] = []

    def brace(m: re.Match) -> str:
        groups.append(m.group(1))
        return " "

    def paren(m: re.Match) -> str:
        lowered = m.group(1).strip().lower()
        if (re.fullmatch(r"\d{5,}", lowered) or re.fullmatch(r"\d{4}", lowered)
                or any(w in lowered for w in DESCRIPTOR_WORDS)
                or QUALITY_RE.search(lowered) or CODEC_RE.search(lowered)
                or re.search(r"\b(?:clean|uncut|hd|hq|cam|dvd|predvd|org|"
                             r"multi\s?audio|dual\s?audio|esub|hevc|hdtc)\b", lowered)):
            groups.append(m.group(1))
            return " "
        return m.group(0)

    out = re.sub(r"\{([^\{\}]{1,80})\}", brace, title)
    out = re.sub(r"[\(\[]([^\(\)\[\]]{1,80})[\)\]]", paren, out)
    return out, groups


def parse_title(raw_title: str, slug: str = "", explicit_year: int | None = None) -> dict:
    """Derives clean title, year, season/episode, media type, languages and key."""
    raw = _clean_text(raw_title)
    # "<Title> - Bollyflix" tails: the brand is the site, never the work.
    raw = re.split(r"\s*[-–|»]\s*(?:bollyflix|bollyflex|moviecok|bollyshares|hdhub4u)\b.*$",
                   raw, maxsplit=1, flags=re.I)[0]
    # Every catalog heading is prefixed with one "Free " token. Removing exactly
    # one keeps a film actually named "Free Guy" intact ("Free Free Guy").
    raw = re.sub(r"^\s*free\s+", "", raw, count=1, flags=re.I)
    brandless = scrub_brand(raw) or raw
    brandless = re.sub(r"(?<!\d)18\s*\+", " ", brandless).strip()

    year = explicit_year
    if year is None:
        m = (re.search(r"[\(\[{]\s*((?:19|20)\d{2})\s*[\)\]}]", brandless)
             or YEAR_RE.search(brandless)
             or re.search(r"[-_ ]((?:19|20)\d{2})[-_ .]", slug or ""))
        year = int(m.group(1)) if m else None

    # The site writes "<Title> (YYYY) <descriptors>"; the bracketed year marks
    # where the work's name ends and its packaging begins.
    head = re.split(r"\s*[\(\[{]\s*(?:19|20)\d{2}\s*(?:[\)\]}]\s|(?=\s|$))",
                    brandless, maxsplit=1)[0]

    slug_text = _pretty_slug(slug or "")
    season_m = (SEASON_RE.search(head) or SEASON_RE.search(brandless)
                or SEASON_RE.search(slug_text))
    episode_m = (EPISODE_RE.search(head) or EPISODE_RE.search(brandless)
                 or EPISODE_RE.search(slug_text))
    season = int(next(g for g in season_m.groups() if g)) if season_m else None
    episode = int(next(g for g in episode_m.groups() if g)) if episode_m else None

    stripped, _groups = _drop_packaging_brackets(head)
    stripped = _strip_packaging(stripped)
    without_year = re.sub(r"\b(?:19|20)\d{2}\b", " ", stripped)
    # A work can be named for a year ("1922", "1917", "2018"), so the inline
    # year strip only runs when something survives it.
    if _bare(without_year):
        stripped = without_year
    stripped = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", stripped)
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        if stripped.count(opener) != stripped.count(closer):
            stripped = stripped.replace(opener, " ").replace(closer, " ")
    clean = _bare(stripped)
    if not clean:
        clean = (_bare(head) or _capitalize(scrub_brand(_pretty_slug(
            re.sub(r"^free[-_]", "", slug or "", flags=re.I)))) or brandless)

    lowered = f" {re.sub(r'[^a-z ]+', ' ', (brandless + ' ' + slug_text).lower())} "
    languages = [w.title() for w in LANGUAGE_WORDS if f" {w} " in lowered]
    media_type = "movie"
    if (season is not None or episode is not None
            or re.search(r"\bweb[\s\-]?series\b|\btv[\s\-]?show\b|\breality[\s\-]?show\b"
                         r"|\bseason\s*\d|\bseries\b", brandless, re.I)
            or re.search(r"web[_\-]?series|season[_\-]?\d|episodes?|tv[_\-]?show",
                         slug or "", re.I)):
        media_type = "series"

    return {
        "clean_title": clean,
        "year": year,
        "season_number": season,
        "episode_number": episode,
        "media_type": media_type,
        "languages": languages,
        "canonical_key": build_canonical_key(clean, year, season, episode, slug),
    }


def _bare(text: str) -> str:
    """Collapses the whitespace and separator litter a token strip leaves behind."""
    return re.sub(r"\s+", " ", text or "").strip(" -–:,,.\u00a7")


def _capitalize(text: str) -> str:
    return re.sub(r"(^|\s)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text or "")


_PACKAGING_RE = re.compile(
    r"""\b(?:480p|576p|720p|1080p|2160p|4k|uhd|fhd|hd|sd|hq|hdtc|hdts|hdcam|hqcam"""
    r"""|cam|predvd|dvdscr|dvd|web[- ]?dl|web[- ]?rip|blu[- ]?ray|bluray|bdrip|brrip"""
    r"""|hdrip|dvdrip|x264|x265|h264|h265|hevc|av1|aac|ddp|dd|10[- ]?bit|8[- ]?bit"""
    r"""|hdr|dts|atmos|esub|esubbed|d[- ]?sub|subtitles?|dual[- ]?audio|multi[- ]?audio"""
    r"""|org|original|uncut|unrated|extended|clean|completed|complete|latest|added"""
    r"""|download|watch|online|movie|film|web[- ]series|tv[- ]series|tv[- ]show"""
    r"""|reality[- ]show|series|episodes?|season|all|part|south|southmovie|mcu)\b""",
    re.I)
_PLATFORM_RE = re.compile(
    r"""\b(?:netflix|amazon\s*prime|prime\s*video|jio\s*hotstar|jiohotstar|hotstar"""
    r"""|voot\s*original|sonyliv|zee5|altbalaji|alt\s*balaji|hoichoi|aha|hulu|disney"""
    r"""|colors\s*tv|star\s*plus|ullu|mx\s*player)\b""", re.I)
_DATE_RE = re.compile(
    rf"""\b(?:\d{{1,2}}\s+{MONTH_WORD}\s+\d{{4}}|{MONTH_WORD}\s+\d{{1,2}},?\s+\d{{4}})\b""",
    re.I)
_SEASON_TOKEN_RE = re.compile(
    r"\bS\d{1,2}\s*[-–]\s*S?\d{1,2}\b|\bS\d{1,2}\s*E(?:P)?\s*\d{1,3}\b"
    r"|\bS\d{1,2}\b|\bSeas[oe]n\s*\d{1,2}\b|\b(?:Episode|Ep)\s*\.?\s*\d{1,3}\b", re.I)


def _strip_packaging(text: str) -> str:
    """Drops the release-descriptor run the site bolts onto its headings."""
    out = _DATE_RE.sub(" ", text or "")
    out = _SEASON_TOKEN_RE.sub(" ", out)
    # A work can be named for one of these words ("Dual", "Complete Unknown"),
    # so the leading token is masked out and put back afterwards.
    lead_m = re.match(r"\s*([^\W_]+)", out, re.U)
    lead = lead_m.group(1) if lead_m else ""
    if lead:
        out = out[:lead_m.start(1)] + "\x00" + out[lead_m.end(1):]
    for _ in range(3):
        out = _PACKAGING_RE.sub(" ", out)
        out = _PLATFORM_RE.sub(" ", out)
        # Languages are descriptors, but only when they stand as their own word.
        out = re.sub(r"\b(?:" + "|".join(LANGUAGE_WORDS) + r")\b", " ", out, flags=re.I)
        out = re.sub(r"\b(?:" + "|".join(INDUSTRY_WORDS) + r")\b", " ", out, flags=re.I)
    return out.replace("\x00", lead) if lead else out


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _meta_tags(html: str) -> dict:
    out: dict[str, str] = {}
    for m in META_RE.finditer(html or ""):
        key = (m.group("key") or m.group("key2") or "").strip()
        val = _clean_text(m.group("val") if m.group("val") is not None else m.group("val2"))
        if key and val:
            out.setdefault(key.lower(), val)
    return out


def _meaningful(text: str | None) -> str:
    """Blanks the site's own placeholder values so they never reach the catalog."""
    out = (text or "").strip()
    if re.fullmatch(r"(?:n/?a|na|not available|-+|tbd|to be updated)", out, re.I):
        return ""
    # The theme's auto meta description is the display name echoed back
    # ("Name: Free X (2022) ..."), which is branding, not a synopsis.
    if re.match(r"^(?:name|title)\s*:", out, re.I):
        return ""
    return out


def _info_block(html: str) -> dict:
    """Reads the "lbl-* / val-*" metadata grid plus the Name line."""
    fields: dict[str, str] = {}
    name_m = INFO_NAME_RE.search(html or "")
    if name_m:
        name = _meaningful(re.sub(r"^\s*Name\s*:\s*", "", _clean_text(name_m.group("inner")),
                                  flags=re.I))
        if name:
            fields["name"] = name
    for m in INFO_ROW_RE.finditer(html or ""):
        key = m.group("key").strip().lower()
        label = _clean_text(m.group("label")).rstrip(":").strip().lower()
        value = _meaningful(_clean_text(m.group("val")))
        if label:
            fields.setdefault(label, value)
        if key:
            fields.setdefault(key, value)
    return fields


def _anchors(html: str):
    """Yields (href, inner_text, class_attr) for every anchor in a fragment."""
    for m in ANCHOR_RE.finditer(html or ""):
        href_m = HREF_RE.search(m.group("attrs"))
        if not href_m:
            continue
        cls_m = CLASS_RE.search(m.group("attrs"))
        yield (_unescape(href_m.group("href")).strip(),
               _clean_text(m.group("inner")),
               (cls_m.group("cls") if cls_m else ""))


def _button_label(inner_html: str, fallback: str) -> str:
    m = BTN_TEXT_RE.search(inner_html or "")
    label = _clean_text(m.group("text")) if m else _clean_text(inner_html)
    label = re.sub(r"^[^\w]+|[^\w]+$", "", label or fallback).strip()
    # "DOWNLOAD 480P" names the action, not the print.
    return re.sub(r"^download\s+", "", label, flags=re.I).strip() or fallback


def harvest_download_buttons(html: str, page_url: str) -> list[dict]:
    """
    Reads every .mv-dl-btn in the post's download box.

    Each button is one print the site publishes. The live site points all of
    them at one 10moviesz short id; the print's identity is therefore the
    button label (480P / 720P / 720P HEVC / 1080P / 1080P 4K), not the URL.
    """
    box_m = DOWNLOAD_BOX_RE.search(html or "")
    fragment = box_m.group("body") if box_m else (html or "")
    buttons: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for href, inner, cls in _anchors(fragment):
        if "mv-main-site-btn" in cls:
            continue
        url = _abs_url(href, page_url)
        if not url or _is_tracker(url) or _is_site_url(url):
            continue
        is_dl = ("mv-dl-btn" in cls or re.search(r"\bdownload\b", inner, re.I)
                 or _is_bridge_url(url))
        if not is_dl:
            continue
        if _is_subtitle_url(url):
            continue  # collected separately, as its own sources row
        label = _button_label(inner, _host_of(url))
        dedupe = (url, label.lower())
        if dedupe in seen:
            continue
        seen.add(dedupe)
        quality = normalize_quality(label) or normalize_quality(
            urllib.parse.unquote(url))
        buttons.append({
            "url": url,
            "label": label,
            "quality": quality,
            "codec": normalize_codec(label) or normalize_codec(urllib.parse.unquote(url)),
            "short_id": (SHORT_ID_RE.search(url).group(1)
                         if SHORT_ID_RE.search(url) else None),
        })
    return buttons


def harvest_subtitles(html: str, base_url: str) -> list[dict]:
    """
    Collects every .srt/.vtt/.ass/.ssa track as an addressable subtitle row.

    The language is read from the link label first, then from the filename. A
    track whose language cannot be read is still kept, labelled "Unknown":
    dropping it would lose a language we merely failed to name.
    """
    tracks: list[dict] = []
    seen: set[str] = set()
    for href, inner, _cls in _anchors(html or ""):
        url = _abs_url(href, base_url)
        if not url or not _is_subtitle_url(url) or _is_tracker(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        filename = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
        languages = _split_languages(inner) or _languages_in(filename)
        language = ", ".join(languages) if languages else "Unknown"
        tracks.append({
            "url": url,
            "label": inner or filename,
            "language": language,
            "quality": normalize_quality(f"{inner} {filename}"),
            "ext": (SUBTITLE_RE.search(urllib.parse.urlsplit(url).path).group(0)
                    .lstrip(".").lower() if SUBTITLE_RE.search(
                        urllib.parse.urlsplit(url).path) else ""),
        })
    return tracks


def harvest_mirrors(html: str, base_url: str) -> list[dict]:
    """Reads downstream file-host links off a reachable bridge page."""
    out: list[dict] = []
    seen: set[str] = set()
    for href, inner, _cls in _anchors(html or ""):
        url = _abs_url(href, base_url)
        if not url or url in seen or _is_tracker(url) or _is_site_url(url):
            continue
        if _is_subtitle_url(url) or _is_bridge_url(url):
            continue
        host = _host_of(url)
        if "t.me" in host:
            continue
        direct = _is_direct_media(url)
        if not (direct or _is_mirror_url(url)):
            continue
        seen.add(url)
        service = _service_for(host)
        playback = "stream" if (direct and url.lower().split("?")[0].endswith(".m3u8")) else (
            "download" if direct else ("embed" if service in EMBED_SERVICES else "download"))
        quality = normalize_quality(f"{inner} {urllib.parse.unquote(url)}")
        out.append({
            "source_name": inner or service,
            "service": service,
            "resource_id": (SHORT_ID_RE.search(url).group(1)
                            if SHORT_ID_RE.search(url) else None),
            "source_url": url,
            "final_url": url,
            "playback_type": playback,
            "status": "active",
            "is_temporary": _is_temporary_url(url),
            "quality": quality,
        })
    return out


EMBED_SERVICES = ("streamtape", "mixdrop", "filemoon", "doodstream", "dood",
                  "upcloud", "playmogo", "streamhub", "hubcloud", "gdflix",
                  "filepress", "vcloud", "fastdl", "hubdrive")


def _service_for(host: str) -> str:
    for name in ("hubcloud", "hubdrive", "gdflix", "gdrive", "pixeldrain", "gofile",
                 "mega", "1fichier", "filepress", "dropgalaxy", "vikingfile",
                 "vcloud", "fastdl", "streamtape", "mixdrop", "filemoon",
                 "doodstream", "upcloud", "playmogo", "streamhub", "telegram"):
        if name in host:
            return "gdrive" if name == "gdrive" else name
    if "drive.google" in host:
        return "gdrive"
    if host.endswith("r2.dev") or "googleusercontent" in host:
        return "direct"
    if "workers.dev" in host:
        return "direct"
    return host or "unknown"


def _source_from_button(button: dict, quality: str | None) -> dict:
    return {
        "source_name": button["label"] or "Bridge",
        "service": "bridge" if _is_bridge_url(button["url"]) else _service_for(
            _host_of(button["url"])),
        "resource_id": button.get("short_id"),
        "source_url": button["url"],
        "final_url": None,
        "playback_type": "url",
        "status": "unknown",
        "is_temporary": _is_temporary_url(button["url"]),
        "quality": quality,
    }


def _attach_subtitles(releases: list[dict], tracks: list[dict],
                      raw_meta: dict) -> None:
    """Gives every subtitle track its own sources row, exactly once."""
    if not tracks:
        return
    existing = set()
    for rel in releases:
        for src in rel.get("sources") or []:
            if src.get("playback_type") == "subtitle":
                existing.add(src.get("source_url"))
    recorded = raw_meta.setdefault("subtitles", [])
    recorded_urls = {t.get("url") for t in recorded}

    for track in tracks:
        if track["url"] in recorded_urls:
            continue
        recorded.append({k: track.get(k) for k in ("url", "label", "language",
                                                   "quality", "ext")})
        recorded_urls.add(track["url"])
        if track["url"] in existing:
            continue
        target = None
        if track.get("quality"):
            target = next((r for r in releases if r.get("quality") == track["quality"]), None)
        if target is None and releases:
            target = releases[0]
        if target is None:
            target = {"label": "Subtitles", "quality": None, "codec": None,
                      "size_bytes": None, "audio_languages": None,
                      "season_number": None, "episode_number": None, "part": None,
                      "bridge_url": None, "download_id": None, "sources": []}
            releases.append(target)
        target.setdefault("sources", []).append({
            "source_name": f"{track['language']} subtitles",
            "service": "subtitle",
            "resource_id": None,
            "source_url": track["url"],
            "final_url": track["url"],
            "playback_type": "subtitle",
            "status": "active",
            "is_temporary": 0,
            "quality": track.get("quality") or target.get("quality"),
        })
        existing.add(track["url"])


def _assign_sizes(releases: list[dict], size_tokens: list[str]) -> None:
    """
    Applies the site's "Size: 460Mb 730Mb 1.2Gb …" cell without inventing.

    A positional map is only used when the token count matches the print count
    exactly; otherwise the tokens are kept in raw_meta and the rows stay null.
    """
    if not releases or not size_tokens:
        return
    if len(size_tokens) == len(releases):
        for rel, token in zip(releases, size_tokens):
            rel["size_bytes"] = parse_size_to_bytes(token)
        return
    qualities = list(dict.fromkeys(r.get("quality") for r in releases if r.get("quality")))
    if len(size_tokens) == len(qualities):
        by_quality = dict(zip(qualities, size_tokens))
        for rel in releases:
            rel["size_bytes"] = parse_size_to_bytes(by_quality.get(rel.get("quality")))


def parse_page(html_or_url: str, url: str | None = None) -> dict | None:
    """
    Extracts clean metadata, prints and bridges from one catalog page.

    Accepts a URL (fetched here) or a body plus its URL. Returns None when the
    page is not a catalog entry — including the site's front page, which is not
    a /free-…/ post.
    """
    return _parse_page(html_or_url, url)[0]


def _parse_page(html_or_url: str, url: str | None = None) -> tuple[dict | None, str]:
    """
    Same as parse_page, plus why it declined, so the crawler can park a page the
    site removed on the first sighting and retry only transport/parse failures.
    """
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

    # A catalog URL that now lands on a shelf/front page is a removed row, not
    # a markup change: the site redirects deleted posts to the home page.
    if requested and requested != page_url:
        requested_path = urllib.parse.urlsplit(requested).path
        final_path = urllib.parse.urlsplit(page_url).path
        if POST_URL_RE.search(requested_path) and not POST_URL_RE.search(final_path):
            return None, "removed"

    path = urllib.parse.urlsplit(page_url).path
    if any(path.startswith(p) for p in NON_POST_PREFIXES):
        return None, "not-a-post"
    post_m = POST_URL_RE.search(path)
    if not post_m:
        return None, "not-a-post"
    slug = urllib.parse.unquote(post_m.group("slug"))

    if not MV_CONTAINER_RE.search(body or ""):
        # A post URL that no longer renders the catalog template is either a
        # removed row that still answers 200 or a markup change. Only the first
        # is safe to park; the second must stay queued.
        title_probe = _clean_text((re.search(r"<title>(.*?)</title>", body or "",
                                             re.S | re.I) or [None, ""])[1])
        if re.search(r"bollyflix|moviecok|download free|your hub", title_probe, re.I):
            return None, "removed"
        return None, "parse-error"

    metas = _meta_tags(body)
    title_m = TOP_TITLE_RE.search(body or "")
    h1 = re.search(r"""<h1\b[^>]*>(.*?)</h1>""", body or "", re.S | re.I)
    title_tag = re.search(r"<title>(.*?)</title>", body or "", re.S | re.I)
    raw_title = _clean_text(title_m.group("inner")) if title_m else (
        _clean_text(h1.group(1)) if h1 else (
            metas.get("og:title") or (title_tag.group(1) if title_tag else "")))
    raw_title = re.split(r"\s+-\s+(?:Bollyflix|Moviecok|BollyShares?)\s*$",
                         raw_title, flags=re.I)[0].strip()
    if not raw_title or re.search(r"bollyflix|download free|your hub for bollywood",
                                  raw_title, re.I):
        return None, "removed"

    info = _info_block(body)
    release_date = info.get("release date") or info.get("release") or ""
    rd_year_m = YEAR_RE.search(release_date)
    identity = parse_title(raw_title, slug,
                           explicit_year=int(rd_year_m.group(1)) if rd_year_m else None)

    genres = [g.strip() for g in re.split(r",", info.get("genre", "")) if g.strip()]
    synopsis = _meaningful(scrub_brand(info.get("description")
                                       or metas.get("og:description")
                                       or metas.get("description") or ""))
    cast = info.get("starcast", "")
    duration = info.get("duration", "")
    size_cell = info.get("size", "")
    size_tokens = re.findall(r"\d+(?:[.,]\d+)?\s*(?:TB|GB|MB|KB)", size_cell, re.I)
    rating_m = RATING_RE.search(info.get("rating", ""))
    imdb_m = IMDB_ID_RE.search(synopsis or "")

    poster_m = POSTER_RE.search(body or "")
    poster = _abs_url(poster_m.group("src"), page_url) if poster_m else None
    if poster and _is_tracker(poster):
        poster = None

    shots_m = SCREENSHOTS_RE.search(body or "")
    screenshots = []
    if shots_m:
        for src in re.findall(r"""<img\b[^>]*?src=["']([^"']+)["']""",
                              shots_m.group("body"), re.I):
            url_shot = _abs_url(src, page_url)
            if url_shot and not _is_tracker(url_shot):
                screenshots.append(url_shot)

    language_cell = info.get("language", "")
    languages = _split_languages(language_cell) or identity["languages"]
    languages = list(dict.fromkeys(languages + identity["languages"]))
    if not languages:
        languages = _languages_in(raw_title)

    raw_meta: dict = {
        "info_block": {k: v for k, v in info.items()},
        "meta_tags": {k: v for k, v in metas.items()
                      if k.startswith("og:") or k in ("description", "keywords")},
        "screenshots": screenshots,
        "size_tokens": size_tokens,
        "download_buttons": [],
        "subtitles": [],
    }

    buttons = harvest_download_buttons(body, page_url)
    raw_meta["download_buttons"] = [
        {"label": b["label"], "quality": b["quality"], "codec": b["codec"],
         "url": b["url"]} for b in buttons]

    releases: list[dict] = []
    group_index: dict[tuple, dict] = {}
    for button in buttons:
        quality = button["quality"]
        codec = button["codec"]
        season = identity["season_number"]
        episode = identity["episode_number"]
        key = (quality, codec, season, episode)
        release = group_index.get(key)
        if release is None:
            release = {
                "label": button["label"] or (quality or "").upper() or "Download",
                "quality": quality,
                "codec": codec,
                "size_bytes": None,
                "audio_languages": ", ".join(_languages_in(button["label"])) or None,
                "season_number": season,
                "episode_number": episode,
                "part": (int(PART_RE.search(button["label"]).group(1))
                         if PART_RE.search(button["label"]) else None),
                "bridge_url": button["url"],
                "download_id": button.get("short_id"),
                "sources": [],
            }
            group_index[key] = release
            releases.append(release)
        release["sources"].append(_source_from_button(button, quality))

    _assign_sizes(releases, size_tokens)

    page_subtitles = harvest_subtitles(body, page_url)
    _attach_subtitles(releases, page_subtitles, raw_meta)

    if releases and len({(r["season_number"], r["episode_number"]) for r in releases
                         if r["episode_number"] is not None}) > 1:
        identity["media_type"] = "series"

    episodes_seen: dict[int, list[dict]] = {}
    for rel in releases:
        if rel.get("episode_number") is not None:
            episodes_seen.setdefault(rel.get("season_number") or 1, []).append(
                {"episode": rel["episode_number"], "title": rel.get("label")})
    seasons_json = json.dumps(
        [{"season": s, "episodes": sorted(v, key=lambda e: e["episode"])}
         for s, v in sorted(episodes_seen.items())], ensure_ascii=False) \
        if episodes_seen else None

    labels_for_adult = (raw_title, info.get("genre", ""),
                        metas.get("keywords", ""), metas.get("og:keywords", ""),
                        identity["clean_title"])
    if not genres:
        genres = [g.strip() for g in re.split(r",", info.get("genre", "")) if g.strip()]

    return {
        "url": page_url,
        "slug": slug,
        "post_id": slug,
        "title": scrub_brand(raw_title),
        "clean_title": identity["clean_title"],
        "year": identity["year"],
        "content_type": identity["media_type"] if identity["media_type"] in LEGAL_MEDIA_TYPES
                        else "movie",
        "season_number": identity["season_number"],
        "seasons": seasons_json,
        "poster_url": poster,
        "backdrop_urls": screenshots or None,
        "imdb_id": imdb_m.group(1) if imdb_m else None,
        "tmdb_id": None,
        "imdb_rating": rating_m.group(1).replace(",", ".") if rating_m else None,
        "genres": ", ".join(genres) if genres else None,
        "synopsis": synopsis or None,
        "cast_names": cast or None,
        "director": info.get("director") or None,
        "duration": duration or None,
        "release_date": release_date or None,
        "languages": ", ".join(languages) if languages else "Unknown",
        "category": info.get("category", ""),
        "is_18_plus": 1 if is_adult_content(*labels_for_adult,
                                            prose=(synopsis,)) else 0,
        "is_animated": 1 if looks_animated(raw_title, info.get("genre", ""),
                                           ", ".join(genres), slug) else 0,
        "source_site": SITE,
        "canonical_key": identity["canonical_key"],
        "releases": releases,
        "raw_meta": raw_meta,
    }, "ok"


# ---------------------------------------------------------------------------
# Public contract: resolve_links
# ---------------------------------------------------------------------------

def _classify_failure(status: int, body: str) -> str:
    if _challenge_body(body):
        return "js_required"
    if status in (404, 410):
        return "dead"
    if status in (401, 403, 503):
        return "blocked"
    return "error"


def _walk_bridge(url: str, referer: str | None, max_hops: int = 4):
    """
    Follows a bridge short link without spending the chain.

    Returns (outcome, final_url, body). A Cloudflare JS challenge is reported
    as `js_required`; it is never bypassed.
    """
    current = normalize_request_url(url)
    for _ in range(max_hops):
        status, location, body = http_get_once(current, referer=referer)
        if status in (301, 302, 303, 307, 308) and location:
            nxt = normalize_request_url(urllib.parse.urljoin(current, _unescape(location)))
            if not nxt or nxt == current:
                return "error", current, body
            current = nxt
            continue
        if status == 200:
            if _challenge_body(body):
                return "js_required", current, body
            return "ok", current, body
        return _classify_failure(status, body), current, body
    return "error", current, ""


def resolve_links(post_data: dict, probe: bool = True) -> dict:
    """
    Resolves each print's bridge into downstream mirrors.

    With ``probe=False`` no socket is opened: the parsed bridge rows are left
    exactly as parse_page produced them (status "unknown"), which is what the
    offline pipeline and the tests rely on.

    A bridge that answers with a Cloudflare challenge is recorded as
    `js_required` and kept. Every mirror found on a reachable bridge page is
    stored as a source on the print whose quality/codec it names; a mirror with
    no tier label is kept in raw_meta rather than falsely attached to a tier.
    """
    if not post_data:
        return post_data
    if not probe:
        return post_data

    referer = post_data.get("url")
    cache: dict[str, tuple] = {}
    bridge_mirrors: list[dict] = []
    extra_tracks: list[dict] = []
    raw_meta = post_data.setdefault("raw_meta", {})
    if not isinstance(raw_meta, dict):
        raw_meta = {}

    for release in post_data.get("releases") or []:
        new_sources: list[dict] = []
        for src in release.get("sources") or []:
            if src.get("playback_type") == "subtitle":
                new_sources.append(src)
                continue
            url = src.get("source_url") or ""
            if not url:
                new_sources.append(src)
                continue
            if url not in cache:
                cache[url] = _walk_bridge(url, referer)
            outcome, final_url, body = cache[url]
            mirrors = harvest_mirrors(body, final_url or url) if outcome == "ok" else []
            tracks = harvest_subtitles(body, final_url or url) if body else []
            extra_tracks.extend(tracks)

            matched = []
            for mirror in mirrors:
                if mirror.get("quality"):
                    if mirror["quality"] == release.get("quality"):
                        matched.append(mirror)
                elif mirror.get("service") and mirror.get("service") != "direct":
                    # Untiered mirror: auditable, but not claimed for this rung.
                    bridge_mirrors.append(dict(mirror, quality=release.get("quality")))
                else:
                    matched.append(mirror)
            for mirror in matched:
                new_sources.append(dict(mirror, quality=mirror.get("quality")
                                        or release.get("quality"),
                                        last_checked=int(time.time())))
            if not matched:
                kept = dict(src)
                kept["status"] = "active" if outcome == "ok" else outcome
                # A failed walk's "final" URL is the gate itself, not a file.
                if outcome == "ok":
                    kept["final_url"] = final_url or kept.get("final_url")
                kept["last_checked"] = int(time.time())
                new_sources.append(kept)
        release["sources"] = new_sources

    if bridge_mirrors:
        raw_meta.setdefault("bridge_mirrors", []).extend(bridge_mirrors)
    _attach_subtitles(post_data.get("releases") or [], extra_tracks, raw_meta)
    post_data["raw_meta"] = raw_meta
    return post_data


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(post_data: dict) -> dict:
    """Determines industry/language/country from the site's own labels."""
    blob = " ".join(filter(None, [
        post_data.get("clean_title"), post_data.get("title"),
        post_data.get("genres"), post_data.get("languages"),
        post_data.get("slug")]))
    lowered = blob.lower()
    industry = "Unknown"
    for word in ("bollywood", "hollywood", "tollywood", "kollywood", "mollywood",
                 "pollywood", "anime", "k-drama", "c-drama"):
        if word in lowered:
            industry = word.capitalize()
            break
    if industry == "Unknown":
        if "south" in lowered or "dubbed" in lowered:
            industry = "Tollywood"
        elif any(w in lowered for w in ("web series", "tv series", "season")):
            industry = "Web Series"
    country = INDUSTRY_COUNTRY.get(industry)
    if not country:
        for w in LANGUAGE_WORDS:
            if re.search(rf"\b{w}\b", lowered):
                country = LANGUAGE_COUNTRY.get(w)
                break
    languages = [w.title() for w in LANGUAGE_WORDS if re.search(rf"\b{w}\b", lowered)]
    return {
        "industry": industry,
        "country": country or "Unknown",
        "languages": ", ".join(dict.fromkeys(languages)) or post_data.get("languages"),
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
            source_site TEXT DEFAULT 'moviecok',
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

        CREATE INDEX IF NOT EXISTS idx_moviecok_posts_slug ON posts(slug);
        CREATE INDEX IF NOT EXISTS idx_moviecok_posts_year ON posts(year);
        CREATE INDEX IF NOT EXISTS idx_moviecok_sources_status ON sources(status);
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


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    """
    Commits parsed post dicts into the isolated staging database.

    Idempotent: a re-scraped page refreshes its own post row and replaces only
    the releases that page produced, so two pages of one title cannot delete
    each other's prints.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    stats_out = {"posts_written": 0, "releases_written": 0,
                 "sources_written": 0, "skipped": 0}

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
                "media_type": post.get("content_type") or "movie",
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
                            src.get("playback_type", "url"), src.get("status", "active"),
                            src.get("is_temporary", 0),
                            src.get("quality") or rel.get("quality"),
                            src.get("last_checked"),
                        ),
                    )
                    stats_out["sources_written"] += 1

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

def _urlset_locs(url: str):
    """Yields <loc> values from one sitemap file. Never raises."""
    status, _, body = http_get(url)
    if status != 200:
        print(f"[!] Sitemap {url} -> HTTP {status}", flush=True)
        return
    yield from (_unescape(v) for v in
                re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", body, re.I))


def _iter_catalog_locs():
    """
    Enumerates the catalog sitemap-by-sitemap.

    Rank Math publishes /sitemap_index.xml; /sitemap.xml itself is slow enough
    to time out on this host (verified live). If the index is missing, the
    unnumbered post sitemap is used as a fallback so the importer still runs.
    """
    status, _, body = http_get(SITEMAP_INDEX_URL)
    if status == 200 and "<sitemapindex" in (body or "").lower():
        for child in re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", body, re.I):
            child = _unescape(child)
            if "post-sitemap" not in urllib.parse.urlsplit(child).path.lower():
                continue  # page/category sitemaps are shelves
            yield from _urlset_locs(child)
        return
    yield from _urlset_locs(SITEMAP_URL)


def _post_slug_of(loc: str) -> str | None:
    path = urllib.parse.urlsplit(loc).path
    if any(path.startswith(p) for p in NON_POST_PREFIXES):
        return None
    m = POST_URL_RE.search(path)
    return urllib.parse.unquote(m.group("slug")) if m else None


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    """
    Enumerates the catalog from sitemap_index.xml into sitemap_cache.

    Returns the number of post URLs newly queued for scraping.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for loc in _iter_catalog_locs():
        slug = _post_slug_of(loc)
        if slug is None or loc in seen:
            continue
        seen.add(loc)
        records.append((loc, "", slug))
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
        # A page the site removed is known on the first sighting; three failed
        # reads is the budget for a transport problem, not for a vanished post.
        conn.execute(
            "UPDATE sitemap_cache SET scraped = -1 WHERE loc = ? AND (error_count >= 3 OR ?);",
            (loc, 1 if park_now else 0))
        conn.commit()
    finally:
        conn.close()


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 4, probe: bool = False, delay: float = 0.2,
                  batch_size: int = 10, verbose: bool = True) -> dict:
    """
    Fetches, parses and commits every queued sitemap entry.

    ``probe`` walks each print's bridge. Every quality button on this site
    shares one short id, so the walk is cached per URL inside resolve_links.
    """
    db_path = Path(db_path)
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
              "not_indexable": 0, "failed": 0}
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
        except Exception as exc:  # keep the catalog even if a chain walk dies
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
            if verbose and done % 100 == 0:
                print(f"    ... {done}/{len(rows)} pages, {totals['sources']} sources",
                      flush=True)
            if STOP_REQUESTED:
                break
        _flush(db_path, batch, totals)

    if verbose:
        print(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"not-indexable={totals['not_indexable']} failed={totals['failed']}",
              flush=True)
    return totals


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    if not batch:
        return
    written = export_staging(db_path, batch)
    totals["posts"] += written["posts_written"]
    totals["releases"] += written["releases_written"]
    totals["sources"] += written["sources_written"]
    totals["not_indexable"] += written["skipped"]
    batch.clear()


def get_stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        return {
            "queued": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0,2)").fetchone()[0],
            "indexed": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0],
            "parked": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "adult_flagged": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "animated": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_animated = 1").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "subtitles": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'subtitle'").fetchone()[0],
            "source_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
            "services": dict(conn.execute(
                "SELECT service, COUNT(*) FROM sources GROUP BY service ORDER BY COUNT(*) DESC")
                .fetchall()),
        }
    finally:
        conn.close()


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    """Compatibility alias; the documented contract name is get_stats."""
    return get_stats(db_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"moviecok staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single page URL for parse/resolve")
    parser.add_argument("--probe", action="store_true",
                        help="walk each print's bridge during crawl")
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
