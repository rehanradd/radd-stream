#!/usr/bin/env python3
"""
import_pagalmovies.py — isolated staging importer for https://www.pagalmovies.fit

Writes ONLY to /home/ubuntu/radd-stream-data/pagalmovies.db. Never touches the
production catalog; merge with Fast_Fetch/merge_catalogs.py after operator review.
Pure Python standard library. Zero pip packages.

The site's own model, as verified live (the task spec's "protection layer: none"
is only half right — pages are plain HTTP, but the download endpoint refuses a
request without an on-site Referer):

    /movie/<post_id>/<slug>.html      the catalog page: information block,
                                      poster, and quality-headed groups
        <div class="pm-q-head"><span class="pm-q-badge">720p</span>
        <a class="fileName" href="/file/<file_id>/<name>.mp4.html">
            /file/<file_id>/...       one printable file (a quality tier, an
                                      episode, or a part of a disc)
                /server/<file_id>/...  the download page (lists the mirrors)
                    /download/<file_id>            -> 302 /download/<file_id>/vidcloud
                    /download/<file_id>/vidcloud   -> 302 five.vidcloud.quest/s/<TOKEN>
                        the VidCloud file page lists /d/<TOKEN>/<provider> for
                        watch_online, skydrop (10Gbps), gofile, buzzheavier,
                        sonicboom, transferit, vikingfile, telegram.

Provider chains resolve further with stdlib alone: watch_online hands back an
R2 object URL in its `videoUrl=` redirect (resumable, token-free) and skydrop
lands on a signed Google CDN attachment. Those are stored as `stream` /
`download` sources with the honest `is_temporary` flag; goFile and buzzheavier
need an account or a JS challenge and are kept as bridges, never dropped.
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

# The origin moves between country TLDs and 301s the old one to the new; both
# shapes stay accepted by SITE_HOST_RE, which is what decides site membership.
BASE_URL = "https://www.pagalmovies.casa"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/pagalmovies.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITE = "pagalmovies"

LEGAL_MEDIA_TYPES = ("movie", "series", "complete_season")
# Legacy rows some staging databases still carry a "2" for; keep accepting them.
QUEUED_SCRAPE_STATES = (0, 2)
MAX_SCRAPE_ATTEMPTS = 3
FAILURE_LEDGER_LIMIT = 8
# A parked row is not permanent until the cap: the shell cohort was parked at
# attempt 1, and "the site answered the homepage" is a measurement, not proof
# that the title never existed. Rows below the cap stay selectable.
PENDING_SELECT = (
    "SELECT loc, lastmod, slug FROM sitemap_cache"
    " WHERE scraped IN (%s) OR (scraped = -1 AND error_count < %d)"
    " ORDER BY rowid ASC"
    % (", ".join(["?"] * len(QUEUED_SCRAPE_STATES)), MAX_SCRAPE_ATTEMPTS)
)

# Listing routes that are shelves, not catalog entries.
NON_POST_PREFIXES = ("/movielist/", "/genre/", "/starcast/", "/services/",
                     "/pages/", "/contact", "/disclaimer")

# Verdicts that are the site's own answer, not our bad luck: a page it redirected
# off the post pattern, a shelf URL, or a hard 404/410. Those are terminal on the
# first sighting. Everything else — 5xx, timeout, connection reset — gets the
# three-read budget, because a first transport failure must never be terminal.
GONE_VERDICTS = ("removed", "not-a-post", "http-404", "http-410", "http-451",
                 "soft404_homepage_shell")

# Measured 2026-10-29: a stale sitemap id and a fabricated one both answer
# HTTP 200 with the byte-identical 24,953-byte homepage (md5 7a0efe789b1c…),
# while a live post is ~10 KB of real content. The server soft-404s stale ids;
# it does not prove the title is gone, so this verdict has its own name and the
# row stays retryable until the attempt cap.
SOFT404_SHELL = "soft404_homepage_shell"
SHELL_TITLE_RE = re.compile(r"pagalmovies\s*20\d{2}\s*-\s*download\s+bollywood", re.I)
SHELL_H1_RE = re.compile(r"best\s+free\s+movie\s+download\s+site", re.I)

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

# Hosts the site itself answers on (it rotates TLDs and mirrors its own name).
# Host membership, so label-anchored: a look-alike ("pagalmovies-copy.example.com")
# is not the site, and following its redirects would be following someone else.
SITE_HOST_RE = re.compile(r"""(?:^|\.)pagal\s?movies?\.[a-z]{2,}""", re.I)

# Ad / tracker / shortlink hosts that are never media, and whose names must not
# reach a client.
TRACKER_HOST_RE = re.compile(
    r"""aj\d+\.bid|agl\d+\.online|funnedravage|allmovieland|bit\.ly|tinyurl"""
    r"""|histats\.com|doubleclick|googlesyndication|google-analytics"""
    r"""|googletagmanager|cloudflareinsights|scorecard|cnzz|hm\.baidu|recaptcha"""
    r"""|pagead|go\.links\.|short\.url""",
    re.I,
)

# The mirror host that fronts every download on this site.
VIDCLOUD_HOST_RE = re.compile(r"""vidcloud\.[a-z]{2,}""", re.I)

# Hosts whose final object is directly playable/downloadable.
DIRECT_CDN_RE = re.compile(
    r"""pub-[0-9a-f]+\.r2\.dev|storage\.googleapis\.com|lh\d+\.googleusercontent\.com"""
    r"""|video-downloads\.googleusercontent\.com|dl\.[a-z0-9.\-]+\.workers\.dev""",
    re.I,
)

# Site branding that must not survive into a public display string. Only the
# names actually seen in this site's own markup, so no real title is eaten.
BRAND_TOKEN_RE = re.compile(
    r"""pagal[\s\-]*movies?\w*|filmyhit|coolmovie[sz]\d*|allmovieland\w*|mp4movie[sz]?""",
    re.I,
)

# ---------------------------------------------------------------------------
# Text lexicons
# ---------------------------------------------------------------------------

# "adult" stays: 10/12 sampled live titles carrying it are real product, and the two
# *Shin-chan: The Adult Empire Strikes Back* rows are the documented cost — a bare word is
# judged by sampling its titles, not by the dictionary. A bracketed age certificate still
# flags: `AGE_CERT_RE`, a label rather than a word.
ADULT_KEYWORDS = (
    "18+", "18 plus", "adult", "porn", "pornhub", "pornstar", "erotic", "blue film",
    "bluefilm", "nude", "naked", "hentai", "onlyfans", "charmsukh", "hotshots",
    "lust", "sensual", "jalebi", "palang tod", "bhabhi", "milf", "uncensored",
    "softcore", "hardcore", "mms", "brazzers", "atrangi", "atrangii", "bablutv",
    "sexy", "hot short film", "hotshortfilm", "moodytapes", "uucinema",
)

# Words that name adult material as a shelf label but also appear in mainstream
# blurbs; an 18+ row is hidden at every surface, so prose alone must not flag.
AMBIGUOUS_ADULT_KEYWORDS = ("sexy", "lust", "sensual", "adult", "hot short film")

PROSE_ADULT_KEYWORDS = tuple(k for k in ADULT_KEYWORDS
                             if k not in AMBIGUOUS_ADULT_KEYWORDS)

AGE_CERT_RE = re.compile(
    r"[\(\[\{]\s*(?:18\s*\+|18\s*plus|u\s*/?\s*a|a\s*/\s*c|adult)\s*[\)\]\}]", re.I)

LANGUAGE_WORDS = (
    "hindi", "english", "tamil", "telugu", "malayalam", "kannada", "bengali",
    "marathi", "punjabi", "gujarati", "bhojpuri", "japanese", "korean", "chinese",
    "spanish", "french", "german", "italian", "russian", "arabic", "turkish",
    "thai", "vietnamese", "indonesian", "tagalog", "taglog", "malaysian",
)

INDUSTRY_WORDS = (
    "bollywood", "hollywood", "tollywood", "kollywood", "mollywood", "pollywood",
    "south", "anime", "animated", "k-drama", "kdrama", "c-drama",
)

# OTT shelves the site names in its titles and slugs: packaging, never a title.
PLATFORM_WORDS = (
    "netflix", "amazon", "prime", "hotstar", "jiohotstar", "jio", "voot", "sonyliv",
    "sony", "zee5", "altpalicki", "hoichoi", "aha", "hulu", "disney", "uucinema",
    "bomju", "hosein", "ullu", "atrangii", "atrangi", "bablutv", "brazzers",
)

DESCRIPTOR_WORDS = LANGUAGE_WORDS + INDUSTRY_WORDS + PLATFORM_WORDS + (
    "dubbed", "dual audio", "multi audio", "esub", "subtitles", "episode", "episodes",
)

QUALITY_RE = re.compile(r"\b(2160p|4k|1080p|720p|576p|480p|360p)\b", re.I)
CODEC_RE = re.compile(
    r"\b(HEVC|x265|x264|AV1|WEB-?DL|WEBRip|BluRay|BDrip|HDCAM|HQCAM|HDRip|WEB-?Rip|DVDRip|CAM)\b",
    re.I)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SEASON_RE = re.compile(r"\bS(\d{1,2})\b|\bSeas[oe]n\s*(\d{1,2})\b", re.I)
EPISODE_RE = re.compile(r"\bE(?:p(?:sode|sodes)?)?\.?\s*(\d{1,3})\b", re.I)
PART_RE = re.compile(r"\bPart\s*(\d{1,2})\b", re.I)
SIZE_TEXT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|KB|MB|PB)\b", re.I)
SIDEBAR_LABEL_RE = re.compile(r"(?:updated|trending|recent|popular|random)\b"
                              r".*\b(?:web[\s\-]?series|series|movies?)\b")
RATING_RE = re.compile(r"(?:imdb|rating)\D{0,8}(\d+(?:[.,]\d+)?)", re.I)
IMDB_ID_RE = re.compile(r"\b(tt\d{7,9})\b", re.I)

POST_URL_RE = re.compile(r"""/movie/(\d{1,9})/([^"'<>\s]+?)(?:\.html?)""", re.I)
FILE_URL_RE = re.compile(r"""/file/(\d{1,9})/([^"'<>\s]+?)\.html?""", re.I)
PROVIDER_URL_RE = re.compile(
    r"""(?P<base>https?://[^"'\s<>]*?vidcloud\.[a-z]{2,})/d/(?P<token>[A-Za-z0-9_\-]+)/"""
    r"""(?P<provider>[a-z_][a-z0-9_\-]*)""", re.I)
BADGE_RE = re.compile(r"""pm-q-badge["']\s*>\s*(?P<q>[\dxpP]{2,6})\s*<""", re.I)
FILE_ANCHOR_RE = re.compile(
    r"""<a\b[^>]*?class=["'][^"']*fileName[^"']*["'][^>]*?href=["'](?P<href>[^"']+?)["']"""
    r"""[^>]*>(?P<inner>.*?)</a>""", re.S | re.I)
INFO_ROW_RE = re.compile(r"""<div\b[^>]*class=["']Fun["'][^>]*>(?P<body>.*?)</div>""",
                         re.S | re.I)
POSTER_RE = re.compile(r"""<img\b[^>]*?src=["'](?P<src>[^"']*?/files/images/[^"']+?)["']""",
                       re.I)
META_RE = re.compile(
    r"""<meta\b[^>]*?(?:property|name)=["'](?P<key>[^"']+)["'][^>]*?content=["'](?P<val>[^"']*)["']"""
    r"""|<meta\b[^>]*?content=["'](?P<val2>[^"']*)["'][^>]*?(?:property|name)=["'](?P<key2>[^"']+)["']""",
    re.I)
SCHEMA_JSON_RE = re.compile(
    r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(?P<body>.*?)</script>""",
    re.S | re.I)

INDUSTRY_COUNTRY = {
    "Tollywood": "India", "Bollywood": "India", "Pollywood": "India",
    "Kollywood": "India", "Mollywood": "India", "Hollywood": "USA",
    "Anime": "Japan", "K-Drama": "South Korea", "C-Drama": "China",
}
LANGUAGE_COUNTRY = {
    "hindi": "India", "tamil": "India", "telugu": "India", "malayalam": "India",
    "kannada": "India", "bengali": "Bangladesh", "marathi": "India",
    "punjabi": "India", "gujarati": "India", "bhojpuri": "India",
    "korean": "South Korea", "japanese": "Japan", "chinese": "China",
    "spanish": "Spain", "french": "France", "german": "Germany", "italian": "Italy",
    "russian": "Russia", "arabic": "Saudi Arabia", "turkish": "Turkey",
    "thai": "Thailand", "vietnamese": "Vietnam", "indonesian": "Indonesia",
    "tagalog": "Philippines", "english": "USA",
}

# Provider slugs on the mirror host, with the label the site shows for each.
PROVIDER_LABELS = {
    "watch_online": "Watch Online",
    "skydrop": "Skydrop (10Gbps)",
    "gofile": "GoFile",
    "buzzheavier": "Buzzheavier",
    "sonicboom": "SonicBoom",
    "transferit": "TransferIt",
    "vikingfile": "VikingFile",
    "telegram": "Telegram",
}
PLAYABLE_PROVIDERS = ("watch_online",)

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

SSL_CONTEXT = ssl.create_default_context()
if os.environ.get("RADD_INSECURE_SSL") == "1":
    # Escape hatch for CDNs with self-signed chains; off by default.
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


# The download endpoint's answer *is* the Location header, so the resolver needs
# a client that does not spend the redirect by following it silently.
_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=SSL_CONTEXT),
    urllib.request.HTTPCookieProcessor(_COOKIE_JAR),
    _StopRedirect(),
)
_NO_REDIRECT_OPENER.addheaders = [("User-Agent", USER_AGENT)]


def _requestable(url: str) -> str:
    """
    Percent-encode the path characters this site's server answers with 400.

    Measured: `Goal!_the_dream_begins_(2005)…` returns 400 as written and 200 once
    the `!` is sent as `%21`. Those rows looked like deleted pages and were parked;
    they were our own unencoded request. `loc` in the queue stays the site's
    spelling — only the bytes we send are normalised.
    """
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/&=?%()~:,;@$+-")
    query = urllib.parse.quote(parts.query, safe="&=?%/:;@+$,!")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query,
                                    parts.fragment))


def http_get(url: str, timeout: int = 30, retries: int = 3):
    """Returns (status_code, final_url, body) following redirects. Never raises."""
    url = _requestable(url)
    last_status, last_url, last_body = 0, url, ""
    for attempt in range(1, retries + 1):
        try:
            resp = _OPENER.open(url, timeout=timeout)
            body = resp.read().decode("utf-8", "replace")
            return getattr(resp, "status", 200) or 200, resp.geturl(), body
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            try:
                last_body = exc.read().decode("utf-8", "replace")
            except Exception:
                last_body = ""
            if exc.code in (401, 403, 404, 410):
                return exc.code, url, last_body  # final — retrying a gate is rude
        except Exception as exc:
            last_status, last_body = 0, f"[network error] {exc}"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    return last_status, last_url, last_body


def http_get_once(url: str, referer: str | None = None, timeout: int = 25):
    """One request, redirects left alone: returns (status, location, body)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    try:
        resp = _NO_REDIRECT_OPENER.open(
            urllib.request.Request(url, headers=headers), timeout=timeout)
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
    return re.sub(r"\s+", " ", out).strip(" -–\u00a7»|&,:")


def _adult_mark(text: str) -> bool:
    return bool(re.search(r"(?<!\d)18\s*\+|18\s*plus", text.lower()))


def _has_keyword(text: str, keywords) -> bool:
    padded = f" {re.sub(r'[^a-z ]+', ' ', text.lower())} "
    return any(f" {kw} " in padded for kw in keywords if kw not in ("18+", "18 plus"))


def is_adult_content(*labels: str | None, prose: tuple = ()) -> bool:
    """Flags adult material from titles, shelf categories and genre labels.

    This site names its adult shelf out loud ("Hot Short Films", genre "Erotic",
    platform "Brazzers"), so the labels carry the signal. A synopsis does not:
    hiding a mainstream title is the more expensive mistake.
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


def _is_tracker(url: str) -> bool:
    return bool(TRACKER_HOST_RE.search(url or ""))


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc.lower().replace("www.", "")


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _is_mirror_url(url: str) -> bool:
    return bool(VIDCLOUD_HOST_RE.search(_host_of(url)))


def _file_id(url: str) -> str | None:
    m = FILE_URL_RE.search(url or "")
    if m:
        return m.group(1)
    m = re.search(r"/download/(\d{1,9})", url or "")
    return m.group(1) if m else None


def parse_size_to_bytes(text: str | None) -> int | None:
    """
    '329.113 MB' / '105.67 mb' / '1.1Gb' -> bytes (binary units, catalog convention).

    The site's placeholder run ("-1.000 B", "0.000 MB", "1.499 KB") is the absence
    of a measurement, so anything under a megabyte reads back as unknown rather
    than as a tier the file could never have.
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


# ---------------------------------------------------------------------------
# Title / identity parsing
# ---------------------------------------------------------------------------

# Longest first so an alternation never leaves "dual" behind after matching "audio".
DESCRIPTOR_TITLES = tuple(sorted(
    set(LANGUAGE_WORDS + INDUSTRY_WORDS + PLATFORM_WORDS), key=len, reverse=True))

PACKAGING_TOKENS = frozenset({
    "movie", "movies", "film", "films", "series", "web", "tv", "hd", "hq", "sd",
    "esub", "esubbed", "dsub", "dub", "dubs", "hevc", "x264", "x265", "h264", "h265",
    "av1", "aac", "uncut", "cut", "dual", "audio", "multi", "dubbed", "south",
    "completed", "complete", "latest", "new", "hdcam", "hqcam", "cam", "ts", "scr",
    "bluray", "blu", "ray", "bdrip", "webdl", "webrip", "hdrip", "dvdrip", "full",
    "download", "free", "official", "unrated", "extended", "episode", "episodes",
    "ep", "part", "season", "seasons", "hdr", "10bit", "8bit", "dts", "atmos",
    "4k", "uhd", "fhd", "hdtv", "original", "hot", "short", "watch", "online", "mp4",
}) | frozenset(DESCRIPTOR_TITLES) | frozenset(
    w.replace("-", "").replace(" ", "") for w in DESCRIPTOR_TITLES)

# A bare number is packaging only after one of these counters, so "3 idiots"
# and "jailer 2" keep their names while "episode 04" does not.
NUMBER_PREFIX_TOKENS = frozenset({"episode", "ep", "part", "season", "bonus", "add"})


def _slug_title_base(slug: str) -> str:
    """
    Recovers the title part of a site slug by trimming packaging from the right.

    Right-hand trimming keeps numeric titles intact while dropping the trailing
    quality/language/platform run the site appends to every URL, so the same film
    published twice ("..._atrangi_..." and "..._atrangii_...") lands on one key.
    """
    tokens = [t for t in re.split(r"[-_.\s]+|[()\[\]]", re.sub(r"\.html?$", "", slug or ""))
              if t]
    while len(tokens) > 1:
        tail = tokens[-1].lower()
        if (tail in PACKAGING_TOKENS or re.fullmatch(r"(?:19|20)\d{2}", tail)
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

    The site's slug is the stable handle for a page; a title-derived key would
    change every time the cleaner improves and strand the previous row.
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

    Brace groups are always packaging on this site. Parentheses are only dropped
    when they read as a language or quality note, so an alternate title like
    "(Naan Sigappu Manithan)" survives as the work's name.
    """
    groups: list[str] = []

    def brace(m: re.Match) -> str:
        groups.append(m.group(1))
        return " "

    def paren(m: re.Match) -> str:
        lowered = m.group(1).strip().lower()
        # A bracketed digit run longer than a year ("Pagal Premi (20012)") is the
        # site mistyping its own packaging, never part of the work's name.
        if (re.fullmatch(r"\d{5,}", lowered)
                or any(w in lowered for w in DESCRIPTOR_WORDS) or QUALITY_RE.search(lowered)
                or re.search(r"\b(?:clear|hd|hq|cam|dvd|predvd|work\s?print|multi\s?audio)\b",
                             lowered)):
            groups.append(m.group(1))
            return " "
        return m.group(0)

    out = re.sub(r"\{([^\{\}]{1,80})\}", brace, title)
    out = re.sub(r"[\(\[]([^\(\)\[\]]{1,80})[\)\]]", paren, out)
    return out, groups


def parse_title(raw_title: str, slug: str = "", explicit_year: int | None = None) -> dict:
    """Derives clean title, year, season/episode, media type, languages and key."""
    brandless = scrub_brand(_clean_text(raw_title)) or _clean_text(raw_title)
    # "<Title> Download HD Movies" / "» PagalMovies 2026" tails, cut at the seam.
    brandless = re.split(r"\s*[-–|»]*\s*(?:download|watch)\s+(?:in\s+)?(?:hd\s+)?"
                         r"(?:movies?|movies?)?\b", brandless, maxsplit=1, flags=re.I)[0]
    brandless = re.sub(r"(?<!\d)18\s*\+", " ", brandless).strip()

    year = explicit_year
    if year is None:
        # A bracketed year is the packaging; a bare one can be the name ("1922"),
        # so the bracket is read first and the bare run only as a fallback.
        m = (re.search(r"[\(\[{]\s*((?:19|20)\d{2})\s*[\)\]}]", brandless)
             or YEAR_RE.search(brandless)
             or re.search(r"[\-_ ]((?:19|20)\d{2})[\-_.]", slug or ""))
        year = int(m.group(1)) if m else None

    # The site writes "<Title> (YYYY) <descriptors>", so the bracketed year marks
    # where the work's name ends and its packaging begins. Its own typo sometimes
    # drops the closing bracket ("Aladin 2 (1994 Hindi Dubbed Movie"), which is
    # still that seam.
    head = re.split(r"\s*[\(\[{]\s*(?:19|20)\d{2}\s*(?:[\)\]}]\s|(?=\s|$))",
                    brandless, maxsplit=1)[0]

    slug_text = _pretty_slug(slug or "")
    season_m = (SEASON_RE.search(head) or SEASON_RE.search(brandless)
                or SEASON_RE.search(slug_text))
    episode_m = (EPISODE_RE.search(head) or EPISODE_RE.search(brandless)
                 or EPISODE_RE.search(slug_text))
    season = int(next(g for g in season_m.groups() if g)) if season_m else None
    episode = int(episode_m.group(1)) if episode_m else None

    stripped, _groups = _drop_packaging_brackets(head)
    stripped = _strip_packaging(stripped)
    without_year = re.sub(r"\b(?:19|20)\d{2}\b", " ", stripped)
    # A work can be named for a year ("1922", "1917", "2018"), so the inline-year
    # strip only runs when something survives it.
    if _bare(without_year):
        stripped = without_year
    stripped = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", stripped)
    # The site sometimes forgets to close a bracket, which leaves an opener
    # holding nothing but the descriptors we just stripped.
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        if stripped.count(opener) != stripped.count(closer):
            stripped = stripped.replace(opener, " ").replace(closer, " ")
    clean = _bare(stripped)
    if not clean:
        # Nothing survived the descriptor run: trust the site's own words, in the
        # case it printed them, over the lowercased slug.
        clean = _bare(head) or _capitalize(scrub_brand(_pretty_slug(slug or ""))) or brandless

    lowered = f" {re.sub(r'[^a-z ]+', ' ', (brandless + ' ' + slug_text).lower())} "
    languages = [w for w in LANGUAGE_WORDS if f" {w} " in lowered or f"_{w}_" in f"_{slug_text.lower()}_"]
    media_type = "movie"
    if re.search(r"\bweb[\s\-]?series\b|\bs\d{1,2}\b|\bseason\s*\d", brandless, re.I) \
            or re.search(r"web[_\-]?series|season[_\-]?\d|episodes?", slug or "", re.I):
        media_type = "series"
    if re.search(r"\bcompleted\b|\ball\s+episodes\b|\bseason\s*\d", brandless, re.I):
        media_type = "complete_season"

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
    """Upper-cases each word's leading letter, leaving any inner case untouched."""
    return re.sub(r"(^|\s)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text or "")


def _strip_packaging(text: str) -> str:
    """Drops the release-descriptor run the site bolts onto its <h1>/<h2>."""
    out = text
    # A work can be named for one of these words ("Dual", "Complete Unknown",
    # "Movie"), so the leading token is masked out of the strip and put back
    # afterwards; nothing else in the string is allowed to match the sentinel.
    lead_m = re.match(r"\s*([^\W_]+)", out, re.U)
    lead = lead_m.group(1) if lead_m else ""
    if lead:
        out = out[:lead_m.start(1)] + "\x00" + out[lead_m.end(1):]
    for _ in range(2):
        out = re.sub(
            r"""\b(?:480p|576p|720p|1080p|2160p|4k|uhd|hd|sd|web-?dl|webrip|bluray|"""
            r"""bdrip|dvdrip|hdrip|hdcam|hqcam|ts|scr|hdtv|x264|x265|hevc|av1|aac|"""
            r"""10-?bit|8-?bit|hdr|dts|atmos|esub|esubbed|d-?sub|hardcoded|subtitles?|"""
            r"""dual[- ]audio|multi[- ]audio|un-?cut|uncensored|full[- ](?:movie|film)|"""
            r"""web[- ]series|tv[- ]series|series|movie|film|completed|complete|latest|"""
            r"""dubbed|dual|official|unrated|extended|episode[s]?|parts?|download)\b""",
            " ", out, flags=re.I)
        out = re.sub(r"\b(?:netflix|amazon\s*prime|prime\s*video|jio\s*hotstar|hotstar|"
                     r"voot\s*original|sonyliv|zee5|altpalicki|hoichoi|aha|hulu|brazzers|"
                     r"atrangi+i|bablu\s*tv|ullu\s*original|uucinema|bomju|jio)\b",
                     " ", out, flags=re.I)
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
    return "" if re.fullmatch(r"(?:n/?a|na|not available|-+|tbd|to be updated)",
                              out, re.I) else out


def _info_block(html: str) -> dict:
    """Reads the site's "<div class=\"Fun\"><b>Label:</b> value</div>" metadata grid."""
    fields: dict[str, str] = {}
    for m in INFO_ROW_RE.finditer(html or ""):
        raw = m.group("body")
        label_m = re.match(r"\s*<b>\s*([^:<]+?)\s*:?\s*</b>(.*)", raw, re.S | re.I)
        if not label_m:
            continue
        label = _clean_text(label_m.group(1)).lower()
        # The rolling "Updated Webseries" strip is the site advertising other
        # posts in this page's grid; it is not metadata about this work.
        if SIDEBAR_LABEL_RE.match(label):
            continue
        value_html = label_m.group(2)
        links = [(_meaningful(_clean_text(t)), href) for href, t in
                 re.findall(r"""<a\b[^>]*?href=["']([^"']+?)["'][^>]*>(.*?)</a>""",
                            value_html, re.S | re.I)]
        value = _meaningful(_clean_text(value_html))
        fields[label] = value
        if label.startswith("genre"):
            fields["__genres"] = [t for t, _ in links if t] or ([value] if value else [])
        if label.startswith("category"):
            fields["__category"] = value
            fields["__category_href"] = next((h for _, h in links if h), "")
    return fields


def harvest_files(page_url: str, body: str) -> list[dict]:
    """
    Reads the quality-headed file groups of a catalog page.

    Scans badges and file anchors in document order so each file inherits the
    tier heading printed above it, which is how the site publishes the same film
    at 480p/720p/1080p.
    """
    files: list[dict] = []
    current_quality: str | None = None
    events: list[tuple[int, str, re.Match]] = []
    for m in BADGE_RE.finditer(body or ""):
        events.append((m.start(), "badge", m))
    for m in FILE_ANCHOR_RE.finditer(body or ""):
        events.append((m.start(), "file", m))
    for _, kind, m in sorted(events):
        if kind == "badge":
            current_quality = m.group("q").lower()
            continue
        href = _abs_url(m.group("href"), page_url)
        if not FILE_URL_RE.search(href):
            continue
        inner = _clean_text(m.group("inner"))
        quality_m = QUALITY_RE.search(urllib.parse.unquote(href)) or QUALITY_RE.search(inner)
        files.append({
            "url": href,
            "file_id": _file_id(href),
            "quality": quality_m.group(1).lower() if quality_m else current_quality,
            "badge_quality": current_quality,
            "label": re.sub(r"\s*File Size.*$", "", inner, flags=re.I).strip(),
            "size_text": next(iter(re.findall(r"File Size[:\s]*(.+)$", inner, re.I)), None),
        })
    return files


def harvest_mirrors(html: str) -> list[dict]:
    """Reads watch embeds and mirror links off a page, keeping their link labels."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r"""<a\b[^>]*?href=["'](?P<href>[^"']+?)["'][^>]*>(?P<inner>.*?)</a>""",
                         html or "", re.S | re.I):
        url = _unescape(m.group("href")).strip()
        if _is_tracker(url):
            continue
        pm = PROVIDER_URL_RE.search(url)
        if not pm:
            continue
        provider = pm.group("provider").lower()
        key = f"{pm.group('token')}/{provider}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "url": url,
            "token": pm.group("token"),
            "provider": provider,
            "label": _clean_text(m.group("inner")) or PROVIDER_LABELS.get(provider, provider),
        })
    return out


def _is_homepage_shell(body: str) -> bool:
    """True when the body is the site's own homepage, not a catalog page."""
    title = re.search(r"<title>(.*?)</title>", body or "", re.S | re.I)
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", body or "", re.S | re.I)
    return bool(
        (title and SHELL_TITLE_RE.search(_clean_text(title.group(1))))
        or (h1 and SHELL_H1_RE.search(_clean_text(h1.group(1))))
    )


def parse_page(html_or_url: str, url: str | None = None) -> dict | None:
    """
    Extracts clean metadata, files and mirrors from one catalog page.

    Accepts a URL (fetched here) or a body plus its URL. Returns None when the
    page is not a catalog entry — including the site's habit of 302-ing a stale
    sitemap id back to its own homepage.
    """
    return _parse_page(html_or_url, url)[0]


def _parse_page(html_or_url: str, url: str | None = None,
                diag: dict | None = None) -> tuple[dict | None, str]:
    """
    Same as parse_page, plus why it declined: the crawler parks a page that is
    provably gone on the first sighting, and only retries a transport failure.

    ``diag`` (optional) is filled with what the request actually measured —
    status, final URL, body size — so the queue row can keep the evidence.
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
        if diag is not None:
            diag.update(http_status=status, final_url=final_url,
                        body_bytes=len(body or ""))
        if status != 200:
            # The status code is the measurement the operator asks for — "is this
            # row gone or merely unlucky" — so it is kept instead of collapsing
            # into one http-error bucket.
            return None, f"http-{status}"
        page_url = final_url or page_url
    elif diag is not None:
        diag.update(body_bytes=len(body))
    if not page_url:
        return None, "not-a-post"

    path = urllib.parse.urlsplit(page_url).path
    if any(path.startswith(p) for p in NON_POST_PREFIXES):
        return None, "not-a-post"
    post_m = POST_URL_RE.search(page_url)
    if not post_m:
        if POST_URL_RE.search(requested) and _is_homepage_shell(body):
            return None, SOFT404_SHELL
        return None, "removed" if POST_URL_RE.search(requested) else "not-a-post"

    metas = _meta_tags(body)
    h1 = re.search(r"""<h1\b[^>]*>(.*?)</h1>""", body or "", re.S | re.I)
    title_tag = re.search(r"<title>(.*?)</title>", body or "", re.S | re.I)
    raw_title = _clean_text(h1.group(1)) if h1 else (
        metas.get("og:title") or (title_tag.group(1) if title_tag else ""))

    # A stale sitemap id 302s back to the homepage, whose <h1> would otherwise be
    # filed as a movie called "PagalMovies 2026".
    if not raw_title or re.search(r"download\s+(?:bollywood|hollywood)"
                                  r"|best\s+free\s+movie", raw_title, re.I):
        return None, SOFT404_SHELL if _is_homepage_shell(body) else "removed"

    info = _info_block(body)
    release_date = info.get("release date", "")
    # The site's own Release Date field outranks the year in its SEO title, which
    # it copies wrong ("The 40 Year Old Virgin (1965)" released 2005).
    rd_year_m = YEAR_RE.search(release_date)
    identity = parse_title(raw_title, post_m.group(2),
                           explicit_year=int(rd_year_m.group(1)) if rd_year_m else None)
    genres = info.get("__genres") or []
    category = info.get("__category", "")
    synopsis = _meaningful(scrub_brand(info.get("description")
                                       or metas.get("og:description")
                                       or metas.get("description") or ""))
    cast = info.get("starcast", "")
    duration = info.get("duration", "")
    rating_m = RATING_RE.search(info.get("rating", ""))
    imdb_m = IMDB_ID_RE.search(synopsis or "")

    poster_m = POSTER_RE.search(body or "")
    poster = _abs_url(poster_m.group("src"), page_url) if poster_m else None
    if poster and _is_tracker(poster):
        poster = None

    files = harvest_files(page_url, body)
    releases: list[dict] = []
    episodes_seen: dict[int, list[dict]] = {}
    for entry in files:
        label = scrub_brand(entry["label"]) or _pretty_slug(
            FILE_URL_RE.search(entry["url"]).group(2) or "")
        text_for_ids = f"{label} {urllib.parse.unquote(entry['url'])}"
        season_m = SEASON_RE.search(text_for_ids)
        episode_m = EPISODE_RE.search(text_for_ids)
        part_m = PART_RE.search(text_for_ids)
        quality = (entry["quality"] or entry["badge_quality"] or "").lower() or None
        codec_m = CODEC_RE.search(text_for_ids)
        episode = int(episode_m.group(1)) if episode_m else None
        season = (int(next(g for g in season_m.groups() if g)) if season_m
                  else identity["season_number"])
        if episode is not None:
            episodes_seen.setdefault(season or 1, []).append(
                {"episode": episode, "title": label})
        releases.append({
            "label": label,
            "quality": quality,
            "codec": codec_m.group(1).upper() if codec_m else None,
            "size_bytes": parse_size_to_bytes(entry["size_text"] or label),
            "audio_languages": ", ".join(
                w for w in LANGUAGE_WORDS
                if re.search(rf"\b{w}\b", label, re.I)) or None,
            "season_number": season if episode is not None else None,
            "episode_number": episode,
            "part": int(part_m.group(1)) if part_m else None,
            "bridge_url": entry["url"],
            "download_id": entry["file_id"],
            "sources": [{
                "source_name": "Bridge",
                "service": "bridge",
                "resource_id": entry["file_id"],
                "source_url": f"{BASE_URL}/download/{entry['file_id']}"
                              if entry["file_id"] else entry["url"],
                "final_url": None,
                "playback_type": "url",
                "status": "unknown",
                "is_temporary": 0,
                "quality": quality,
            }] if entry["file_id"] else [],
        })

    media_type = identity["media_type"]
    if len({(r["season_number"], r["episode_number"]) for r in releases
            if r["episode_number"] is not None}) > 1:
        media_type = "complete_season"

    labels_for_adult = (raw_title, category, ", ".join(genres),
                        metas.get("keywords", ""), metas.get("og:keywords", ""),
                        identity["clean_title"])
    seasons_json = json.dumps(
        [{"season": s, "episodes": sorted(v, key=lambda e: e["episode"])}
         for s, v in sorted(episodes_seen.items())], ensure_ascii=False) \
        if episodes_seen else None

    return {
        "url": page_url,
        "slug": post_m.group(2),
        "post_id": post_m.group(1),
        "title": raw_title,
        "clean_title": identity["clean_title"],
        "year": identity["year"],
        "content_type": media_type,
        "season_number": identity["season_number"],
        "seasons": seasons_json,
        "poster_url": poster,
        "backdrop_urls": None,
        "imdb_id": imdb_m.group(1) if imdb_m else None,
        "tmdb_id": None,
        "imdb_rating": rating_m.group(1).replace(",", ".") if rating_m else None,
        "genres": ", ".join(genres) if genres else None,
        "synopsis": synopsis or None,
        "cast_names": cast or None,
        "director": info.get("director") or None,
        "duration": duration or None,
        "release_date": release_date or None,
        "languages": ", ".join(dict.fromkeys(
            identity["languages"]
            + [w for w in LANGUAGE_WORDS if re.search(rf"\b{w}\b", category, re.I)])) or "Unknown",
        "category": category,
        "is_18_plus": 1 if is_adult_content(*labels_for_adult,
                                            prose=(synopsis,)) else 0,
        "is_animated": 1 if looks_animated(raw_title, category, ", ".join(genres),
                                           post_m.group(2)) else 0,
        "source_site": SITE,
        "canonical_key": identity["canonical_key"],
        "releases": releases,
        "raw_meta": {
            "info_block": {k: v for k, v in info.items() if not k.startswith("__")},
            "meta_tags": {k: v for k, v in metas.items()
                          if k.startswith("og:") or k in ("description", "keywords")},
            "file_pages": [f["url"] for f in files],
        },
    }, "ok"


# ---------------------------------------------------------------------------
# Public contract: resolve_links
# ---------------------------------------------------------------------------

def _classify_failure(status: int, body: str) -> str:
    head = (body or "")[:600].lower()
    if "enable javascript" in head or "just a moment" in head or "checking if you are" in head:
        return "js_required"
    if status in (404, 410):
        return "dead"
    # The site answers a download id whose row is gone with its bare framework
    # error page; that is a dead link, not a wall we failed to get past.
    if status == 503 and "<title>error</title>" in head:
        return "dead"
    if status in (401, 403, 503):
        return "blocked"
    return "error"


def _walk_download(file_id: str, referer: str | None, max_hops: int = 4):
    """
    Follows /download/<file_id> to the mirror host without spending the chain.

    The site answers a request with no on-site Referer by bouncing to its own
    homepage, and a request for a file it no longer hosts with its framework
    error page. Neither is a link, so each is reported as what it is
    ("blocked" and "dead") rather than dropped.
    """
    url = f"{BASE_URL}/download/{file_id}"
    for _ in range(max_hops):
        status, location, body = http_get_once(url, referer=referer)
        if status == 200 and _is_mirror_url(url):
            return "ok", url, body
        if status == 200:
            return "error", url, body
        if status in (404, 410, 403, 503, 401) or not location:
            return _classify_failure(status, body), url, body
        nxt = urllib.parse.urljoin(url, _unescape(location))
        if _is_site_url(nxt) and urllib.parse.urlsplit(nxt).path.rstrip("/") in ("", "/"):
            # Bounced to the homepage: with no on-site Referer that is the gate
            # refusing us; with one, the download row itself is gone.
            return ("blocked" if not referer else "dead"), url, body
        if _is_mirror_url(nxt):
            status2, location2, body2 = http_get_once(nxt, referer=referer)
            if status2 in (301, 302) and location2:
                nxt = urllib.parse.urljoin(nxt, _unescape(location2))
            if not _is_mirror_url(nxt):
                return "error", nxt, body2
            status3, _, body3 = http_get_once(nxt, referer=referer)
            if status3 != 200:
                return _classify_failure(status3, body3), nxt, body3
            return "ok", nxt, body3
        url = nxt
    return "error", url, ""


def _final_cdn_target(url: str, referer: str | None, max_hops: int = 6):
    """
    Resolves a mirror link to the object behind it, when a redirect says so.

    Two shapes exist here: a hop whose query carries `videoUrl=` pointing at a
    CDN object (the embed hands back a playable), and a chain that ends on a
    signed CDN attachment. A chain that ends on an HTML page is a JS gate and is
    reported as one rather than silently kept as if it were direct.
    """
    if "watch_online" in url:
        status, _, body = http_get(url)
        if status == 200:
            m = re.search(r'window\.VIDEO_URL\s*=\s*["\'](https?://[^"\']+)["\']', body)
            if m:
                return "stream", m.group(1), "active"

    current = url
    status = 0
    for _ in range(max_hops):
        status, location, _body = http_get_once(current, referer=referer)
        if status in (404, 410):
            return None, current, "dead"
        if status in (401, 403, 503):
            return None, current, "js_required"
        if status not in (301, 302, 303, 307, 308) or not location:
            break
        current = urllib.parse.urljoin(current, _unescape(location))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(current).query)
        for param in ("videoUrl", "video", "url", "file", "link"):
            value = query.get(param)
            if value and DIRECT_CDN_RE.search(value[0]):
                return "stream", value[0], "active"
        if DIRECT_CDN_RE.search(_host_of(current)):
            return "download", current, "active"
    # The chain stopped on a page, not an object: the mirror link is still a
    # usable bridge, so the caller keeps it as it stands.
    return None, current, "none"


def resolve_links(post_data: dict, probe: bool = True, deep: bool = False) -> dict:
    """
    Resolves each file of a page into its mirror list on the downstream host.

    Without ``deep`` the mirror links themselves are stored: they are stable per
    file and a client can follow them. With ``deep`` the playables are unwrapped
    too (embed object, signed CDN attachment) and marked for what they are.
    """
    if not post_data:
        return post_data
    referer = post_data.get("url")
    for release in post_data.get("releases") or []:
        file_id = release.get("download_id") or _file_id(release.get("bridge_url") or "")
        if not file_id:
            continue
        release["download_id"] = file_id
        if not probe:
            continue
        outcome, page_url, body = _walk_download(file_id, referer)
        mirrors = harvest_mirrors(body) if outcome == "ok" else []
        sources: list[dict] = []
        for mirror in mirrors:
            provider = mirror["provider"]
            entry = {
                "source_name": mirror["label"],
                "service": provider,
                "resource_id": mirror["token"],
                "source_url": mirror["url"],
                "final_url": mirror["url"],
                "playback_type": "embed" if provider in PLAYABLE_PROVIDERS else "download",
                "status": "active",
                "is_temporary": 0,
                "quality": release.get("quality"),
                "last_checked": int(time.time()),
            }
            if deep:
                kind, target, endstate = _final_cdn_target(
                    mirror["url"].replace("/d/", "/go/"), referer)
                if kind:
                    entry["final_url"] = target
                    entry["playback_type"] = kind
                    # A signed CDN attachment expires with its token; a public
                    # object URL does not, and the catalog treats them differently.
                    entry["is_temporary"] = 1 if "?" in target or "googleusercontent" in target else 0
                elif endstate in ("dead", "js_required"):
                    entry["status"] = endstate
                    entry["final_url"] = None
            sources.append(entry)
        if not sources:
            sources = [{
                "source_name": "Bridge",
                "service": "bridge",
                "resource_id": file_id,
                "source_url": f"{BASE_URL}/download/{file_id}",
                "final_url": None,
                "playback_type": "url",
                "status": outcome if outcome != "ok" else "error",
                "is_temporary": 0,
                "quality": release.get("quality"),
                "last_checked": int(time.time()),
                "note": f"resolved via {page_url}" if page_url else None,
            }]
        release["sources"] = sources
    return post_data


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(post_data: dict) -> dict:
    """Determines industry/language/country from the site's own labels."""
    blob = " ".join(filter(None, [
        post_data.get("clean_title"), post_data.get("title"),
        post_data.get("genres"), post_data.get("category"),
        post_data.get("slug"), post_data.get("languages")]))
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
            source_site TEXT DEFAULT 'pagalmovies',
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

        CREATE INDEX IF NOT EXISTS idx_pagalmovies_posts_slug ON posts(slug);
        CREATE INDEX IF NOT EXISTS idx_pagalmovies_posts_year ON posts(year);
        CREATE INDEX IF NOT EXISTS idx_pagalmovies_sources_status ON sources(status);
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

    Idempotent: a re-scraped page refreshes its own post row and replaces the
    releases that page produced — never the whole site's, so a season page and an
    episode-pack page cannot delete each other's prints.
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

            # Replace this page's releases only (see the module docstring for why
            # a title can be printed on more than one page).
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

def _iter_sitemap_locs(root_url: str, depth: int = 0, max_depth: int = 3):
    """Yields <loc> values from a urlset, following sitemapindex children."""
    status, _, body = http_get(root_url)
    if status != 200:
        print(f"[!] Sitemap {root_url} -> HTTP {status}", flush=True)
        return
    locs = [_unescape(m) for m in re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", body, re.I)]
    if "<sitemapindex" in body.lower() and depth < max_depth:
        for child in locs:
            yield from _iter_sitemap_locs(child, depth + 1, max_depth)
        return
    yield from locs


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    """
    Enumerates the catalog from sitemap.xml into sitemap_cache.

    Returns the number of post URLs newly queued for scraping.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for loc in _iter_sitemap_locs(SITEMAP_URL):
        path = urllib.parse.urlsplit(loc).path
        if not path.startswith("/movie/") or not path.endswith(".html"):
            continue  # shelves and static pages are listings, not catalog entries
        # The site rotates hostnames between TLDs; the path is the post's
        # identity and the host is only the mirror. Keying on the full loc
        # duplicated the whole queue the day the sitemap switched hosts.
        if path in seen:
            continue
        seen.add(path)
        post_m = POST_URL_RE.search(loc)
        slug = post_m.group(2) if post_m else _slug_title_base(path)
        records.append((loc, "", slug))
        if limit and len(records) >= limit:
            break

    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        cached_paths = {urllib.parse.urlsplit(r[0]).path
                        for r in conn.execute("SELECT loc FROM sitemap_cache")}
        fresh = [r for r in records
                 if urllib.parse.urlsplit(r[0]).path not in cached_paths]
        before = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        conn.executemany(
            """
            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
            VALUES (?, ?, ?, 0, NULL, 0)
            ON CONFLICT(loc) DO UPDATE SET slug = excluded.slug;
            """,
            fresh,
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
    finally:
        conn.close()

    if verbose:
        if not fresh:
            print("[!] Sitemap yielded no new catalog entries; nothing queued.",
                  flush=True)
        else:
            print(f"[✓] [{SITE}] Queued {len(fresh)} post URLs "
                  f"({after - before} new, {after} total).", flush=True)
    return after - before


def _bump_error(db_path: Path, loc: str, note: str, park_now: bool = False,
                http_status: int | None = None, final_url: str | None = None,
                exception: str | None = None) -> None:
    """
    Record one failed read, with the measurement that caused it.

    The ledger (`raw_json.failures`) is what makes a parked row auditable:
    kind, HTTP status, final URL and exception class per attempt, never a bare
    note that erases the evidence of the previous attempt.
    """
    if not loc:
        return
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT error_count, raw_json FROM sitemap_cache WHERE loc = ?",
            (loc,)).fetchone()
        attempts = (row[0] if row else 0) + 1
        try:
            payload = json.loads(row[1]) if row and row[1] else {}
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        history = payload.get("failures")
        history = history if isinstance(history, list) else []
        attempt = {
            "at": int(time.time()),
            "attempt": attempts,
            "kind": note,
            "http_status": http_status,
            "final_url": final_url,
        }
        if exception:
            attempt["exception"] = exception
        payload["failures"] = (history + [attempt])[-FAILURE_LEDGER_LIMIT:]
        payload["last_note"] = note
        payload["status"] = ("dead" if attempts >= MAX_SCRAPE_ATTEMPTS
                             else "parked" if park_now else "retrying")
        conn.execute(
            "UPDATE sitemap_cache SET error_count = ?, raw_json = ? WHERE loc = ?;",
            (attempts, json.dumps(payload, ensure_ascii=False), loc))
        # A page the site has removed is parked on the first sighting; three
        # failed reads is the budget for a transport problem, not for a vanished
        # post. Parked rows below the cap stay selectable (see PENDING_SELECT).
        if attempts >= MAX_SCRAPE_ATTEMPTS or park_now:
            conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ?;",
                         (loc,))
        conn.commit()
    finally:
        conn.close()


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 4, probe: bool = False, deep: bool = False,
                  delay: float = 0.2, batch_size: int = 10,
                  verbose: bool = True) -> dict:
    """
    Fetches, parses and commits every queued sitemap entry.

    ``probe`` additionally walks each file's download chain. It costs four
    requests per file and the mirror host rate-limits at 30 per window, so it is
    opt-in rather than the crawl's default.
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
              f"(workers={workers}, probe={probe}, deep={deep}).", flush=True)

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "not_indexable": 0, "failed": 0, "declined_by_reason": {}}
    if not rows:
        return totals

    def work(loc: str):
        if STOP_REQUESTED:
            return None
        time.sleep(delay)
        diag: dict = {}
        post, verdict = _parse_page(loc, diag=diag)
        if post is None:
            return None, verdict, diag
        try:
            return resolve_links(post, probe=probe, deep=deep), verdict, diag
        except Exception as exc:  # keep the catalog even if a chain walk dies
            post["resolve_error"] = str(exc)
            return post, verdict, diag

    batch: list[dict] = []
    batch_locs: list[str] = []
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
                _bump_error(db_path, loc, f"exception: {exc}",
                            exception=type(exc).__name__)
                continue
            if outcome is None:
                continue
            post, verdict, diag = outcome
            if post is None:
                totals["not_indexable"] += 1
                totals["declined_by_reason"][verdict] = \
                    totals["declined_by_reason"].get(verdict, 0) + 1
                _bump_error(db_path, loc, verdict,
                            park_now=verdict in GONE_VERDICTS,
                            http_status=diag.get("http_status"),
                            final_url=diag.get("final_url"),
                            exception=diag.get("exception"))
                continue
            batch.append(post)
            batch_locs.append(loc)
            if len(batch) >= batch_size:
                _flush(db_path, batch, totals)
                _mark_scraped(db_path, batch_locs)
                batch = []
                batch_locs = []
            if verbose and done % 100 == 0:
                print(f"    ... {done}/{len(rows)} pages, {totals['sources']} sources",
                      flush=True)
            if STOP_REQUESTED:
                break
        _flush(db_path, batch, totals)
        _mark_scraped(db_path, batch_locs)

    if verbose:
        print(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"not-indexable={totals['not_indexable']} failed={totals['failed']}", flush=True)
        if totals["declined_by_reason"]:
            print(f"    [{SITE}] declined as: "
                  + ", ".join(f"{k}={v}" for k, v in
                              sorted(totals["declined_by_reason"].items(),
                                     key=lambda kv: -kv[1])), flush=True)
    return totals


def requeue_parked(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                   verbose: bool = True) -> int:
    """
    Put parked rows back in the queue so a later pass can re-measure them.

    A row is parked because some earlier run decided the page was gone; that
    decision is a claim about a moment in time, not a fact about the site. The
    state is written as 2 (queued, previously attempted) rather than 0 so the
    row keeps its history, and `error_count` is left alone: the three-read budget
    still applies to whatever this pass finds.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        rows = conn.execute("SELECT loc FROM sitemap_cache WHERE scraped = -1"
                            " ORDER BY rowid ASC").fetchall()
        if limit:
            rows = rows[:limit]
        conn.executemany("UPDATE sitemap_cache SET scraped = 2 WHERE loc = ?;",
                         [(r[0],) for r in rows])
        conn.commit()
    finally:
        conn.close()
    if verbose:
        print(f"[*] [{SITE}] requeued {len(rows)} parked URLs for a fresh verdict.",
              flush=True)
    return len(rows)


def relabel_homepage_shells(db_path: Path | str = DEFAULT_DB_PATH,
                            verbose: bool = True) -> int:
    """
    Rename the old `removed` cohort to the measured soft-404 shell verdict.

    Control probes on 2026-10-29 (a parked id and a fabricated id) both returned
    the same 24,953-byte homepage, so "removed" was the site's shell talking,
    not proof the title vanished. The budget is reset and each row is queued
    for re-measurement; a row that still answers the shell is parked again up
    to the cap, with the shell named as its own verdict.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT loc, raw_json FROM sitemap_cache WHERE scraped = -1").fetchall()
        updated = 0
        for loc, raw in rows:
            try:
                payload = json.loads(raw) if raw else {}
            except (ValueError, TypeError):
                payload = {}
            if not isinstance(payload, dict) or payload.get("last_note") != "removed":
                continue
            history = payload.get("failures")
            history = history if isinstance(history, list) else []
            history.append({
                "at": int(time.time()),
                "attempt": 0,
                "kind": SOFT404_SHELL,
                "http_status": 200,
                "final_url": None,
                "detail": ("relabeled from 'removed': control probes returned the "
                           "homepage shell (200, 24,953 bytes, md5 7a0efe789b1c)"),
            })
            payload["failures"] = history[-FAILURE_LEDGER_LIMIT:]
            payload["last_note"] = SOFT404_SHELL
            payload["status"] = "retrying"
            conn.execute(
                "UPDATE sitemap_cache SET scraped = 2, error_count = 0, "
                "raw_json = ? WHERE loc = ?;",
                (json.dumps(payload, ensure_ascii=False), loc))
            updated += 1
        conn.commit()
    finally:
        conn.close()
    if verbose:
        print(f"[✓] [{SITE}] relabeled {updated} parked rows as {SOFT404_SHELL}; "
              f"error_count reset, queued for re-measurement.", flush=True)
    return updated


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    if not batch:
        return
    written = export_staging(db_path, batch)
    totals["posts"] += written["posts_written"]
    totals["releases"] += written["releases_written"]
    totals["sources"] += written["sources_written"]
    totals["not_indexable"] += written["skipped"]
    batch.clear()


def _mark_scraped(db_path: Path, locs: list[str]) -> None:
    """
    Clears the queue row that produced a successful page.

    export_staging marks the URL the page ended on. When the site rotated hosts
    mid-fetch (.fit -> .casa) that is a different row, so the fetched loc would
    otherwise stay queued and be re-read on every pass.
    """
    if not locs:
        return
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.executemany(
            "UPDATE sitemap_cache SET scraped = 1, error_count = 0 WHERE loc = ?",
            [(loc,) for loc in locs])
        conn.commit()
    finally:
        conn.close()


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        return {
            "queued": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0,2)").fetchone()[0],
            "indexed": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0],
            "parked": conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "adult_flagged": conn.execute("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "animated": conn.execute("SELECT COUNT(*) FROM posts WHERE is_animated = 1").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "source_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
            "services": dict(conn.execute(
                "SELECT service, COUNT(*) FROM sources GROUP BY service ORDER BY COUNT(*) DESC")
                .fetchall()),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"pagalmovies staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats",
                                 "retry-parked", "relabel-shell"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single page URL for parse/resolve")
    parser.add_argument("--probe", action="store_true",
                        help="walk each file's download chain during crawl")
    parser.add_argument("--deep", action="store_true",
                        help="with --probe, also unwrap the embed/CDN object behind a mirror")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    db = Path(args.db)
    verbose = not args.quiet

    if args.command == "sync":
        sync_catalog(limit=args.limit, db_path=db, verbose=verbose)
    elif args.command == "retry-parked":
        requeue_parked(db, limit=args.limit, verbose=verbose)
        crawl_pending(db_path=db, workers=args.workers, probe=args.probe,
                      deep=args.deep, verbose=verbose)
    elif args.command == "relabel-shell":
        relabel_homepage_shells(db, verbose=verbose)
    elif args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=db, workers=args.workers,
                      probe=args.probe, deep=args.deep, verbose=verbose)
    elif args.command == "stats":
        print(json.dumps(stats(db), indent=2, ensure_ascii=False))
    else:
        if not args.url:
            parser.error(f"{args.command} requires --url")
        post = parse_page(args.url)
        if post is None:
            print("[!] Page is not a catalog entry.", file=sys.stderr)
            return 1
        if args.command == "resolve":
            resolve_links(post, probe=True, deep=args.deep)
        print(json.dumps(post, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
