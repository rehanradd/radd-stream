#!/usr/bin/env python3
"""
import_5movierulz.py — isolated staging importer for https://www.5movierulz.green

Writes ONLY to /home/ubuntu/radd-stream-data/5movierulz.db. Never touches the
production catalog; merge with Fast_Fetch/merge_catalogs.py after operator review.
Pure Python standard library. Zero pip packages.

Site model, verified live (2026-10-28, 6 requests):

    /<slug>-<post_id>.html            one catalog page
    /year/<YYYY>[/page/<N>]           year shelf, paginated
        page 1 of /year/2026 advertises "page/62": year shelves are the only
        complete enumeration this site exposes.
    /sitemap.xml                      HTTP 404 (no sitemap)
    /wp-json/wp/v2/posts              HTTP 404 (WordPress front end, REST closed)

    A catalog page carries:
      <h2 class="entry-title">        "The Paradise (2026) HDRip [Telugu]"
      div.movie-info-block            Directed by / Written by / Starring by /
                                      Genres / Categories / Country / Language /
                                      Quality
      div.synopsis-section            prose
      div.torrent-section             one magnet per quality tier; the visible
                                      btn-size text is "27.3 gb 4k 2160p"
      div.streaming-section           mirror-link-card cards: Streamlare,
                                      Uperbox, Easysyncr (x2), Streamwish,
                                      Filelions
      var locations = [...]           Player 1 / Player 2 embeds (a superset of
                                      the Streamlare card, plus Streamvin)

No Cloudflare wall, no JS challenge, no account gate: every page above returned
HTTP 200 to a plain stdlib GET. The mirror hosts themselves are third parties and
are recorded as what they are (embed/download bridges), with an honest
active/dead/blocked status once probed; nothing is invented or unwrapped here.
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

BASE_URL = "https://www.5movierulz.green"
# Documented for parity with the other importers; this origin answers 404 for it.
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/5movierulz.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITE = "5movierulz"
FIRST_YEAR = 2004
LAST_YEAR = time.gmtime().tm_year
MAX_LISTING_PAGES = 500

LEGAL_MEDIA_TYPES = ("movie", "series")
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC"
    % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

# Shelf / taxonomy routes that are listings, never catalog entries.
NON_POST_PREFIXES = ("/year/", "/category/", "/genre/", "/actor/", "/director/",
                     "/writer/", "/language/", "/quality/", "/country/",
                     "/page/", "/about", "/contact", "/privacy", "/dmca")

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

# Host membership, label-anchored: a look-alike ("movierulz-copy.example.com")
# is not this site. The brand rotates digits ("5movierulz", "1movierulz").
SITE_HOST_RE = re.compile(r"""(?:^|\.)\d*\s*movie\s*rulz\.[a-z]{2,}""", re.I)

TRACKER_HOST_RE = re.compile(
    r"""bit\.ly|tinyurl|googlesyndication|doubleclick|google-analytics"""
    r"""|googletagmanager|cloudflareinsights|histats|scorecard|recaptcha"""
    r"""|pagead|go\.links\.|short\.url""",
    re.I,
)

# Branding that must not survive into a public display string. Only this site's
# own names, so no real title is eaten ("The Paradise" is untouched).
BRAND_TOKEN_RE = re.compile(
    r"""(?:\d+\s*)?movie\s*rulz(?:\.(?:company|green|com|net|org|watch|studio|ws"""
    r"""|to|life|dev|me|xyz|info|tv|cash|one|io|in|co))?[\w.]*""",
    re.I,
)

# ---------------------------------------------------------------------------
# Text lexicons
# ---------------------------------------------------------------------------

# "xxx" left this list on 2026-10-29: 62 rows were hidden by it alone and this catalog holds
# the *xXx* films, so one hit is a suggestion, not a hide. "adult" stays (in the ambiguous,
# label-only tier below) — 10/12 sampled live titles carrying it are real product, the
# "… Adult Short Film" vault format, and the two *Shin-chan: The Adult Empire Strikes Back*
# rows are the documented cost. A bracketed age certificate still counts: `AGE_CERT_RE`.
ADULT_KEYWORDS = (
    "18+", "18 plus", "adult", "porn", "pornhub", "pornstar", "erotic",
    "blue film", "bluefilm", "nude", "naked", "hentai", "onlyfans", "charmsukh",
    "hotshots", "lust", "sensual", "jalebi", "palang tod", "bhabhi", "milf",
    "uncensored", "softcore", "hardcore", "mms", "brazzers", "atrangi",
    "bablutv", "sexy", "hot short film", "hot short films", "hotshortfilm",
    "moodytapes",
)

# Words that also appear in mainstream blurbs; prose alone must not delete a
# title from every display surface, so these only count when they are labels.
AMBIGUOUS_ADULT_KEYWORDS = ("sexy", "lust", "sensual", "adult", "erotic", "nude",
                            "sex", "hot short film", "hot short films")
PROSE_ADULT_KEYWORDS = tuple(k for k in ADULT_KEYWORDS
                             if k not in AMBIGUOUS_ADULT_KEYWORDS)

AGE_CERT_RE = re.compile(
    r"[\(\[\{]\s*(?:18\s*\+|18\s*plus|a\s*/\s*c|adult)\s*[\)\]\}]", re.I)

LANGUAGE_WORDS = (
    "hindi", "english", "tamil", "telugu", "malayalam", "kannada", "bengali",
    "marathi", "punjabi", "gujarati", "bhojpuri", "japanese", "korean", "chinese",
    "spanish", "french", "german", "italian", "russian", "arabic", "turkish",
    "thai", "vietnamese", "indonesian", "tagalog",
)

# Magnet display names abbreviate the audio tracks in a bracket.
LANGUAGE_ABBREVIATIONS = {
    "tel": "Telugu", "tam": "Tamil", "hin": "Hindi", "mal": "Malayalam",
    "kan": "Kannada", "eng": "English", "mar": "Marathi", "ben": "Bengali",
    "pun": "Punjabi", "guj": "Gujarati", "bho": "Bhojpuri", "jap": "Japanese",
    "kor": "Korean", "chi": "Chinese", "spa": "Spanish", "fre": "French",
    "ger": "German", "ita": "Italian", "rus": "Russian", "ara": "Arabic",
    "tur": "Turkish", "tha": "Thai", "vie": "Vietnamese", "ind": "Indonesian",
    "tag": "Tagalog", "urd": "Urdu",
}

INDUSTRY_WORDS = (
    "bollywood", "hollywood", "tollywood", "kollywood", "mollywood",
    "pollywood", "south", "anime", "animated", "k-drama", "kdrama", "c-drama",
)

PLATFORM_WORDS = (
    "netflix", "amazon", "prime", "hotstar", "jiohotstar", "jio", "voot",
    "sonyliv", "zee5", "aha", "hulu", "disney", "ullu", "hoichoi",
)

DESCRIPTOR_WORDS = LANGUAGE_WORDS + INDUSTRY_WORDS + PLATFORM_WORDS + (
    "dubbed", "dual audio", "multi audio", "esub", "subtitles", "episode",
    "episodes", "web series", "tv series",
)

QUALITY_RE = re.compile(r"\b(2160p|1080p|720p|576p|480p|360p|320p|240p)\b", re.I)
CODEC_RE = re.compile(r"\b(HEVC|x265|x264|AVC|AV1|H\.?264|H\.?265)\b", re.I)
HDR_RE = re.compile(
    r"(?<![A-Za-z0-9])(HDR10\+?|HDR|Dolby\s*Vision|DV)(?![A-Za-z0-9])", re.I)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SEASON_RE = re.compile(r"\bseason\s*(\d{1,2})\b|\bs(\d{1,2})\b", re.I)
EPISODE_RE = re.compile(r"\bE(?:p(?:sode|sodes)?)?\.?\s*(\d{1,3})\b", re.I)
PART_RE = re.compile(r"\bPart\s*(\d{1,2})\b", re.I)
SIZE_TEXT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|KB|MB|PB)\b", re.I)
RATING_RE = re.compile(r"(?:imdb|rating)\D{0,8}(\d+(?:[.,]\d+)?)", re.I)
IMDB_ID_RE = re.compile(r"\b(tt\d{7,9})\b", re.I)

# Root-level "<title>-<id>.html" is the whole post namespace on this site.
POST_PATH_RE = re.compile(
    r"^/(?P<slug>[a-z0-9][a-z0-9._\-]*)-(?P<post_id>\d{1,7})\.html?$", re.I)

TITLE_RE = re.compile(
    r"""<h[12]\b[^>]*class=["'][^"']*entry-title[^"']*["'][^>]*>(?P<inner>.*?)</h[12]>""",
    re.S | re.I)
ANCHOR_RE = re.compile(
    r"""<a\b[^>]*?href=["'](?P<href>[^"']+?)["'][^>]*>(?P<inner>.*?)</a>""",
    re.S | re.I)
INFO_P_RE = re.compile(
    r"""<p\b[^>]*>\s*<strong>(?P<label>.*?)</strong>(?P<body>.*?)</p>""",
    re.S | re.I)
SYNOPSIS_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*synopsis-section[^"']*["'][^>]*>(?P<body>.*?)</div>""",
    re.S | re.I)
POSTER_WRAP_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*movie-poster-wrapper[^"']*["'][^>]*>(?P<body>.*?)</div>""",
    re.S | re.I)
POSTER_IMG_RE = re.compile(r"""<img\b[^>]*?src=["'](?P<src>[^"']+?)["']""", re.I)
TORRENT_ANCHOR_RE = re.compile(
    r"""<a\b(?P<attrs>[^>]*)>(?P<inner>.*?)</a>""", re.S | re.I)
BTN_SIZE_RE = re.compile(r"""class=["'][^"']*btn-size[^"']*["'][^>]*>(?P<val>.*?)</span>""",
                         re.S | re.I)
PLATFORM_RE = re.compile(
    r"""class=["'][^"']*platform-name[^"']*["'][^>]*>(?P<val>.*?)</span>""", re.S | re.I)
LOCATIONS_RE = re.compile(r"""var\s+locations\s*=\s*\[(?P<body>.*?)\]\s*;""", re.S)
QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
SUBTITLE_RE = re.compile(
    r"""(?:href|src)=["'](?P<url>[^"']+?\.(?:vtt|srt|ass)(?:\?[^"']*)?)["']""",
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
    "punjabi": "India", "gujarati": "India", "bhojpuri": "India",
    "korean": "South Korea", "japanese": "Japan", "chinese": "China",
    "spanish": "Spain", "french": "France", "german": "Germany", "italian": "Italy",
    "russian": "Russia", "arabic": "Saudi Arabia", "turkish": "Turkey",
    "thai": "Thailand", "vietnamese": "Vietnam", "indonesian": "Indonesia",
    "tagalog": "Philippines", "english": "USA", "urdu": "Pakistan",
}

PROVIDER_LABELS = {
    "streamlare": "Streamlare",
    "streamvin": "Streamvin (Player)",
    "uperbox": "Uperbox",
    "easysyncr": "Easysyncr",
    "streamwish": "Streamwish",
    "filelions": "Filelions",
}
PROVIDER_BY_HOST = (
    ("vcdnlare", "streamlare"),
    ("streamvin", "streamvin"),
    ("uperbox", "uperbox"),
    ("easysyncr", "easysyncr"),
    ("hglink", "streamwish"),
    ("minochinos", "filelions"),
)

# ---------------------------------------------------------------------------
# HTTP layer — every URL is unescaped, whitespace-stripped and percent-quoted
# before it reaches urllib, so a Unicode slug can never crash the request.
# ---------------------------------------------------------------------------

URL_SAFE = ":/?#[]@!$&'()*+,;=%"

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


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=SSL_CONTEXT),
    urllib.request.HTTPCookieProcessor(_COOKIE_JAR),
    _StopRedirect(),
)
_NO_REDIRECT_OPENER.addheaders = [("User-Agent", USER_AGENT)]


def normalize_url(raw: str | None) -> str:
    """html.unescape -> drop the site's newline-wrapped hrefs -> percent-quote.

    The site wraps several mirror hrefs across lines ("https://host/a/\\nID"), and
    quoting only after unescaping keeps an already-encoded token ("%20") intact.
    """
    if not raw:
        return ""
    url = html_mod.unescape(str(raw)).strip()
    url = re.sub(r"\s+", "", url)
    return urllib.parse.quote(url, safe=URL_SAFE)


def http_get(url: str, timeout: int = 30, retries: int = 3):
    """Returns (status_code, final_url, body) following redirects. Never raises."""
    url = normalize_url(url)
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
    url = normalize_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = normalize_url(referer)
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
    """Removes this site's branding and leftover "www." noise from a display string."""
    if not text:
        return ""
    out = BRAND_TOKEN_RE.sub(" ", text)
    out = re.sub(r"\bwww\.\s*", " ", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip(" -–\u00a7»|&,:.")


def _adult_mark(text: str) -> bool:
    return bool(re.search(r"(?<!\d)18\s*\+|18\s*plus", text.lower()))


def _has_keyword(text: str, keywords) -> bool:
    padded = f" {re.sub(r'[^a-z ]+', ' ', text.lower())} "
    return any(f" {kw} " in padded for kw in keywords if kw not in ("18+", "18 plus"))


def is_adult_content(*labels: str | None, prose: tuple = ()) -> bool:
    """Flags adult material from titles, shelf categories and genre labels.

    The site publishes adult shelves and genre labels ("Erotic") out loud, so a
    label is the signal. A synopsis is not: an 18+ row is hidden from every
    surface, so a mainstream blurb must never hide a title.
    """
    head = " ".join(t for t in labels if t)
    if _adult_mark(head) or _has_keyword(head, ADULT_KEYWORDS):
        return True
    body = " ".join(t for t in prose if t)
    return bool(body) and (_adult_mark(body) or _has_keyword(body, PROSE_ADULT_KEYWORDS))


def looks_animated(*texts: str | None) -> bool:
    joined = " ".join(t for t in texts if t).lower()
    return bool(re.search(r"\b(anime|animated|animation)\b", joined))


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc.lower().replace("www.", "")


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _is_tracker(url: str) -> bool:
    return bool(TRACKER_HOST_RE.search(url or ""))


def _post_match(url: str) -> re.Match | None:
    try:
        path = urllib.parse.urlsplit(url or "").path
    except ValueError:
        return None
    return POST_PATH_RE.match(path or "")


def _abs_url(href: str, base: str) -> str:
    return normalize_url(urllib.parse.urljoin(base, _unescape(href.strip())))


def parse_size_to_bytes(text: str | None) -> int | None:
    """'27.3 gb' / '450 mb' / '1.6GB' -> bytes (binary units, catalog convention)."""
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
    return int(num * {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3,
                      "TB": 1024 ** 4, "PB": 1024 ** 5}[unit])


def _quality(text: str | None) -> str | None:
    """Normalizes the site's tier words; 4K and 2160p are one tier."""
    text = text or ""
    if re.search(r"\b(4k|2160p|uhd)\b", text, re.I):
        return "4K"
    m = QUALITY_RE.search(text)
    return m.group(1).lower() if m else None


def _codec(text: str | None) -> str | None:
    m = CODEC_RE.search(text or "")
    if not m:
        return None
    token = m.group(1).upper().replace(".", "")
    return "HEVC" if token in ("HEVC", "X265", "H265") else (
        "AVC" if token in ("AVC", "X264", "H264") else token)


def _pretty_slug(slug: str) -> str:
    words = [w for w in re.split(r"[-_.]+", re.sub(r"[^\w\-_.]+", " ", slug or "")) if w]
    return " ".join(words).strip()


def _languages_in(text: str | None) -> list[str]:
    """Full language words plus the magnet bracket's Tel/Tam/Hin abbreviations."""
    blob = (text or "").lower()
    found: list[str] = []
    for word in LANGUAGE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", blob):
            found.append(word)
    for group in re.findall(r"\[([^\]]{2,80})\]", text or ""):
        for token in re.split(r"[+/&,]", group):
            key = re.sub(r"[^a-z]", "", token.lower())
            word = LANGUAGE_ABBREVIATIONS.get(key)
            if word:
                found.append(word.lower())
    if "urdu" in blob and "urdu" not in found:
        found.append("urdu")
    ordered: list[str] = []
    for word in found:
        title = word.title()
        if title not in ordered:
            ordered.append(title)
    return ordered


def _is_temporary_url(url: str) -> int:
    """Signed/session URLs expire; plain provider file pages do not."""
    try:
        parts = urllib.parse.urlsplit(url or "")
    except ValueError:
        return 0
    query = urllib.parse.parse_qs(parts.query)
    if any(k.lower() in ("sid", "expires", "expire", "token", "signature", "sig",
                         "auth", "key") for k in query):
        return 1
    return 1 if parts.path.lower().endswith(".m3u8") else 0


# ---------------------------------------------------------------------------
# Title / identity parsing
# ---------------------------------------------------------------------------

# Longest first so an alternation never leaves "dual" behind after matching "audio".
DESCRIPTOR_TITLES = tuple(sorted(
    set(LANGUAGE_WORDS + INDUSTRY_WORDS + PLATFORM_WORDS), key=len, reverse=True))

PACKAGING_TOKENS = frozenset({
    "movie", "movies", "film", "films", "series", "web", "tv", "hd", "hq", "sd",
    "esub", "esubbed", "dsub", "dub", "dubs", "hevc", "x264", "x265", "h264", "h265",
    "avc", "aac", "ddp", "dd", "atmos", "dts", "uncut", "cut", "dual", "audio",
    "multi", "dubbed", "south", "completed", "complete", "latest", "new",
    "hdcam", "hqcam", "cam", "ts", "scr", "bluray", "blu", "ray", "bdrip",
    "webdl", "webrip", "hdrip", "dvdrip", "predvd", "dvdscr", "full", "download",
    "free", "official", "unrated", "extended", "episode", "episodes", "ep", "part",
    "seasons", "hdr", "hdr10", "10bit", "8bit", "4k", "2160p", "1080p", "720p",
    "576p", "480p", "360p", "320p", "240p", "uhd", "fhd", "hdtv", "original",
    "watch", "online", "mp4", "mkv", "xvid", "divx",
}) | frozenset(DESCRIPTOR_TITLES) | frozenset(
    w.replace("-", "").replace(" ", "") for w in DESCRIPTOR_TITLES)

# Words that only strip from the right of a slug, to recover the title base.
SLUG_TRIM_TOKENS = PACKAGING_TOKENS | frozenset({"rip", "dubbed", "quality"})


def _drop_packaging_brackets(title: str) -> tuple[str, list[str]]:
    """Drops bracket groups that read as packaging; keeps alternate titles."""
    groups: list[str] = []

    def brace(m: re.Match) -> str:
        groups.append(m.group(1))
        return " "

    def paren(m: re.Match) -> str:
        body = m.group(1).strip()
        lowered = body.lower()
        if (re.fullmatch(r"\d{5,}", lowered)
                or any(w in lowered for w in DESCRIPTOR_WORDS)
                or QUALITY_RE.search(lowered) or CODEC_RE.search(lowered)
                or HDR_RE.search(lowered)
                or re.search(r"\b(?:19|20)\d{2}\b", lowered)
                or re.search(r"\b(?:clear|hd|hq|cam|dvd|predvd|web|hdr|multi)\b",
                             lowered)):
            groups.append(body)
            return " "
        return m.group(0)

    out = re.sub(r"\{([^\{\}]{1,80})\}", brace, title or "")
    out = re.sub(r"[\(\[]([^\(\)\[\]]{1,80})[\)\]]", paren, out)
    return out, groups


def _bare(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" -–:,,.\u00a7|")


def _capitalize(text: str) -> str:
    return re.sub(r"(^|\s)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text or "")


def _strip_packaging(text: str) -> str:
    """Drops the release-descriptor run the site bolts onto its title."""
    out = text or ""
    # A work can be named for one of these words ("Movie", "HD"); mask the
    # leading token out of the strip and put it back afterwards.
    lead_m = re.match(r"\s*([^\W_]+)", out, re.U)
    lead = lead_m.group(1) if lead_m else ""
    if lead:
        out = out[:lead_m.start(1)] + "\x00" + out[lead_m.end(1):]
    for _ in range(2):
        out = re.sub(
            r"""\b(?:480p|576p|720p|1080p|2160p|4k|uhd|hd|sd|web-?dl|webrip|bluray|"""
            r"""bdrip|dvdrip|dvdscr|hdrip|hdcam|hqcam|predvd|ts|scr|hdtv|x264|x265|"""
            r"""hevc|avc|av1|aac|ddp?|atmos|dts|10-?bit|8-?bit|hdr10?|esub|esubbed|"""
            r"""d-?sub|hardcoded|subtitles?|dual[- ]audio|multi[- ]audio|un-?cut|"""
            r"""uncensored|full[- ](?:movie|film)|web[- ]series|tv[- ]series|series|"""
            r"""movie|film|completed|complete|latest|dubbed|dual|official|unrated|"""
            r"""extended|episode[s]?|parts?|download|rip|quality)\b""",
            " ", out, flags=re.I)
        out = re.sub(r"\b(?:netflix|amazon\s*prime|prime\s*video|jio\s*hotstar|"
                     r"hotstar|sonyliv|zee5|aha|hulu|disney|jio)\b",
                     " ", out, flags=re.I)
    return out.replace("\x00", lead) if lead else out


def parse_title(raw_title: str, slug: str = "", explicit_year: int | None = None) -> dict:
    """Derives clean title, year, season, media type, languages and identity key."""
    brandless = scrub_brand(_clean_text(raw_title)) or _clean_text(raw_title)
    # "<Title> | MovieRulz" tails and "… Download" seams.
    brandless = re.split(r"\s*[-–|»]*\s*(?:download|watch)\s+(?:in\s+)?(?:hd\s+)?"
                         r"(?:movies?|movies?)?\b", brandless, maxsplit=1, flags=re.I)[0]
    brandless = re.sub(r"(?<!\d)18\s*\+", " ", brandless).strip()

    year = explicit_year
    if year is None:
        m = (re.search(r"[\(\[{]\s*((?:19|20)\d{2})\s*[\)\]}]", brandless)
             or YEAR_RE.search(brandless)
             or re.search(r"(?:^|[-_ ])((?:19|20)\d{2})(?:[-_.]|$)", slug or ""))
        year = int(m.group(1)) if m else None

    # The bracketed year marks where the work's name ends and packaging begins.
    head = re.split(r"\s*[\(\[{]\s*(?:19|20)\d{2}\s*(?:[\)\]}]\s|(?=\s|$))",
                    brandless, maxsplit=1)[0]
    head, _groups = _drop_packaging_brackets(head)
    stripped = _strip_packaging(head)
    without_year = re.sub(r"\b(?:19|20)\d{2}\b", " ", stripped)
    if _bare(without_year):
        stripped = without_year
    stripped = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", stripped)
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        if stripped.count(opener) != stripped.count(closer):
            stripped = stripped.replace(opener, " ").replace(closer, " ")
    clean = _bare(stripped)
    if not clean:
        clean = _bare(head) or _capitalize(scrub_brand(_pretty_slug(slug))) or brandless

    slug_text = _pretty_slug(slug or "")
    season_m = (SEASON_RE.search(brandless) or SEASON_RE.search(slug_text))
    episode_m = (EPISODE_RE.search(brandless) or EPISODE_RE.search(slug_text))
    season = int(next(g for g in season_m.groups() if g)) if season_m else None
    episode = int(episode_m.group(1)) if episode_m else None

    media_type = "movie"
    if (re.search(r"\bseason\s*\d+|\bweb[\s\-]?series\b|\bseries\b", brandless, re.I)
            or re.search(r"season-\d+|web-series|\bseries\b", slug or "", re.I)):
        media_type = "series"

    languages = _languages_in(f"{brandless} {slug_text}")
    return {
        "clean_title": clean,
        "year": year,
        "season_number": season,
        "episode_number": episode,
        "media_type": media_type,
        "languages": languages,
        "canonical_key": build_canonical_key(clean, year, season, episode, slug),
    }


def _slug_base(slug: str) -> str:
    tokens = [t for t in re.split(r"[-_.\s]+", re.sub(r"\.html?$", "", slug or "")) if t]
    while len(tokens) > 1:
        tail = tokens[-1].lower()
        if tail in SLUG_TRIM_TOKENS or re.fullmatch(r"\d{3,4}p", tail):
            tokens.pop()
            continue
        break
    return "-".join(t.lower() for t in tokens if t).strip("-")


def build_canonical_key(clean_title: str, year: int | None, season: int | None,
                        episode: int | None, slug: str) -> str:
    """Slug-derived identity key, stable across language/quality reprints."""
    base = _slug_base(slug or "") or re.sub(
        r"[^a-z0-9]+", "-", (clean_title or "").lower()).strip("-")
    if year and not re.search(rf"(?:^|-){year}$", base):
        base = f"{base}-{year}"
    if season and not re.search(
            rf"(?:^|-)season-0?{season}(?:-|$)|(?:^|-)s0?{season}(?:-|$)", base):
        base += f"-s{season:02d}"
    if episode and not re.search(rf"(?:^|-)(?:e|episode-?)0?{episode}(?:-|$)", base):
        base += f"-e{episode:02d}"
    return base or "unknown"


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
    out = (text or "").strip()
    return "" if re.fullmatch(r"(?:n/?a|na|not available|-+|tbd|to be updated)",
                              out, re.I) else out


def _info_block(html: str) -> dict:
    """Reads the "<p><strong>Label:</strong> value</p>" metadata grid."""
    fields: dict[str, str] = {}
    for m in INFO_P_RE.finditer(html or ""):
        label = _clean_text(m.group("label")).rstrip(":").lower()
        body = m.group("body")
        links = [_clean_text(t) for h, t in ANCHOR_RE.findall(body)]
        links = [t for t in links if t]
        value = _meaningful(_clean_text(body))
        fields[label] = value
        if label.startswith("genre"):
            fields["__genres"] = links or [v for v in re.split(r"[,/]", value) if v.strip()]
        elif label.startswith("categor"):
            fields["__categories"] = links or [v for v in re.split(r"[,/]", value) if v.strip()]
        elif label.startswith("starring") or label.startswith("cast"):
            fields["__cast"] = links or [v for v in re.split(r",", value) if v.strip()]
        elif label.startswith("directed"):
            fields["__director"] = (links[0] if links else value) or ""
    return fields


def _synopsis(html: str, metas: dict) -> str:
    m = SYNOPSIS_RE.search(html or "")
    if m:
        text = _clean_text(m.group("body"))
        text = re.sub(r"^synopsis\b[:\s]*", "", text, flags=re.I).strip()
        if text:
            return text
    return _meaningful(scrub_brand(metas.get("og:description")
                                   or metas.get("description") or ""))


def _poster(html: str, metas: dict) -> str | None:
    wrap = POSTER_WRAP_RE.search(html or "")
    candidate = None
    if wrap:
        img = POSTER_IMG_RE.search(wrap.group("body"))
        if img:
            candidate = img.group("src")
    if not candidate:
        candidate = metas.get("og:image") or metas.get("twitter:image")
    if not candidate:
        return None
    url = normalize_url(candidate)
    return None if _is_tracker(url) else url


def _hdr_token(text: str | None) -> str | None:
    """Prefers a precise HDR10/HDR10+ token over a bare HDR word in a name."""
    found = [m.group(1) for m in HDR_RE.finditer(text or "")]
    if not found:
        return None
    rank = {"hdr10+": 4, "hdr10": 3, "dolby vision": 2, "hdr": 1, "dv": 0}
    return max(found, key=lambda t: rank.get(re.sub(r"\s+", " ", t.lower()), 0))


def harvest_torrents(html: str) -> list[dict]:
    """Reads every magnet button as one quality tier."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in TORRENT_ANCHOR_RE.finditer(html or ""):
        attrs = m.group("attrs") or ""
        if "torrent-btn" not in attrs:
            continue
        href_m = re.search(r"""href=["'](?P<href>magnet:[^"']+)["']""", attrs, re.I)
        if not href_m:
            continue
        magnet = normalize_url(href_m.group("href"))
        btih = re.search(r"btih:([A-Za-z0-9]+)", magnet)
        key = btih.group(1).lower() if btih else magnet
        if key in seen:
            continue
        seen.add(key)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(magnet).query)
        display = (query.get("dn") or [""])[0]
        size_m = BTN_SIZE_RE.search(m.group("inner"))
        size_text = _clean_text(size_m.group("val")) if size_m else ""
        text_for_tier = f"{display} {size_text}"
        out.append({
            "magnet": magnet,
            "btih": btih.group(1) if btih else None,
            "display_name": display,
            "size_text": size_text,
            "quality": _quality(text_for_tier),
            "codec": _codec(display),
            "hdr": _hdr_token(display),
            "languages": _languages_in(display),
        })
    return out


def harvest_streams(html: str, page_url: str) -> list[dict]:
    """Reads mirror-link cards plus the player `locations` embeds, deduped by URL."""
    cards: list[dict] = []
    seen: set[str] = set()

    def add(url: str, label: str, playback: str) -> None:
        url = normalize_url(url)
        if not url or url in seen or _is_tracker(url):
            return
        seen.add(url)
        service = next((svc for host, svc in PROVIDER_BY_HOST if host in _host_of(url)),
                       _host_of(url).split(".")[0] or "mirror")
        cards.append({
            "url": url,
            "label": _meaningful(scrub_brand(label)) or PROVIDER_LABELS.get(
                service, service.title()),
            "service": service,
            "playback_type": playback,
        })

    for chunk in (html or "").split('<div class="mirror-link-card"')[1:]:
        platform = PLATFORM_RE.search(chunk)
        anchor = ANCHOR_RE.search(chunk)
        if not anchor:
            continue
        label = _clean_text(platform.group("val")) if platform else ""
        playback = "download" if label.strip().lower().startswith("download") else "embed"
        add(urllib.parse.urljoin(page_url, _unescape(anchor.group("href"))), label, playback)

    loc_m = LOCATIONS_RE.search(html or "")
    if loc_m:
        for idx, raw in enumerate(QUOTED_RE.findall(loc_m.group("body")), start=1):
            loc = _unescape(raw.replace("\\/", "/"))
            add(urllib.parse.urljoin(page_url, loc), f"Player {idx}", "embed")
    return cards


def harvest_subtitles(html: str, page_url: str) -> list[dict]:
    """Every .vtt/.srt/.ass URL the page actually publishes, with its label."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(url: str, label: str) -> None:
        url = _abs_url(url, page_url)
        path = urllib.parse.urlsplit(url).path
        if not re.search(r"\.(?:vtt|srt|ass)$", path, re.I) or url in seen:
            return
        seen.add(url)
        ext = path.rsplit(".", 1)[-1].lower()
        out.append({
            "url": url,
            "label": _meaningful(scrub_brand(label)) or urllib.parse.unquote(
                path.rsplit("/", 1)[-1]),
            "ext": ext,
        })

    for m in ANCHOR_RE.finditer(html or ""):
        add(m.group("href"), _clean_text(m.group("inner")))
    for m in SUBTITLE_RE.finditer(html or ""):
        add(m.group("url"), "")
    return out


def _post_links(body: str, page_url: str) -> list[tuple[str, str, str]]:
    """(absolute_url, slug, post_id) for catalog entries linked by a shelf page."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for m in ANCHOR_RE.finditer(body or ""):
        url = _abs_url(m.group("href"), page_url)
        pm = _post_match(url)
        if not pm or url in seen:
            continue
        path = urllib.parse.urlsplit(url).path
        if any(path.startswith(p) for p in NON_POST_PREFIXES):
            continue
        seen.add(url)
        out.append((url, pm.group("slug"), pm.group("post_id")))
    return out


def parse_page(html_or_url: str, url: str | None = None) -> dict | None:
    """
    Extracts clean metadata, torrent tiers, streams and subtitles from one page.

    Accepts a URL (fetched here) or a body plus its URL. Returns None when the
    page is not a catalog entry (a shelf, a static page, or a 404).
    """
    return _parse_page(html_or_url, url)[0]


def _parse_page(html_or_url: str, url: str | None = None) -> tuple[dict | None, str]:
    """Same as parse_page, plus why it declined, so the crawler can park a gone page."""
    body = html_or_url or ""
    page_url = url
    if page_url is None and re.match(r"^https?://", body.strip()):
        page_url, body = body.strip(), ""
    requested = page_url or ""
    if page_url and not POST_PATH_RE.match(urllib.parse.urlsplit(page_url).path or ""):
        return None, "not-a-post"
    if not body:
        if not page_url:
            return None, "not-a-post"
        status, final_url, body = http_get(page_url)
        if status != 200:
            return None, "http-error"
        page_url = final_url or page_url
    if not page_url:
        return None, "not-a-post"

    post_m = POST_PATH_RE.match(urllib.parse.urlsplit(page_url).path or "")
    if not post_m:
        return None, "removed" if _post_match(requested) else "not-a-post"

    metas = _meta_tags(body)
    title_m = TITLE_RE.search(body or "")
    title_tag = re.search(r"<title>(.*?)</title>", body or "", re.S | re.I)
    raw_title = _clean_text(title_m.group("inner")) if title_m else (
        metas.get("og:title") or (title_tag.group(1) if title_tag else ""))
    raw_title = scrub_brand(raw_title)

    # A shelf or an error page that landed here is not this post.
    if (not raw_title
            or re.search(r"latest\s+(?:indian\s+)?movies|error\s+404|"
                         r"download\s+(?:bollywood|hollywood)|best\s+free\s+movie",
                         raw_title, re.I)):
        return None, "removed"

    info = _info_block(body)
    genres = [g for g in info.get("__genres", []) if _meaningful(g)]
    categories = [c for c in info.get("__categories", []) if _meaningful(c)]
    category = ", ".join(categories)
    synopsis = _meaningful(scrub_brand(_synopsis(body, metas)))
    cast = ", ".join(info.get("__cast", [])) or None
    director = info.get("__director") or None
    languages_field = info.get("language", "")

    identity = parse_title(raw_title, post_m.group("slug"))
    languages = list(dict.fromkeys(identity["languages"]
                                   + _languages_in(languages_field)
                                   + _languages_in(category)))

    torrents = harvest_torrents(body)
    streams = harvest_streams(body, page_url)
    subtitles = harvest_subtitles(body, page_url)

    releases: list[dict] = []
    for tier in torrents:
        label = scrub_brand(tier["display_name"]) or (
            f"{identity['clean_title']} {tier['size_text']}".strip())
        releases.append({
            "label": label,
            "quality": tier["quality"],
            "codec": tier["codec"],
            "hdr": tier["hdr"],
            "size_bytes": parse_size_to_bytes(tier["size_text"] or label),
            "audio_languages": ", ".join(tier["languages"]) or None,
            "season_number": identity["season_number"],
            "episode_number": identity["episode_number"],
            "bridge_url": tier["magnet"],
            "download_id": tier["btih"],
            "origin_url": page_url,
            "sources": [{
                "source_name": "Torrent (Magnet)",
                "service": "torrent",
                "resource_id": tier["btih"],
                "source_url": tier["magnet"],
                "final_url": tier["magnet"],
                "playback_type": "download",
                "status": "active",
                "is_temporary": 0,
                "quality": tier["quality"],
                "last_checked": None,
            }],
        })

    if streams or subtitles:
        watch_sources: list[dict] = []
        for stream in streams:
            watch_sources.append({
                "source_name": stream["label"],
                "service": stream["service"],
                "resource_id": urllib.parse.urlsplit(stream["url"]).path.strip("/").split("/")[-1],
                "source_url": stream["url"],
                "final_url": stream["url"],
                "playback_type": stream["playback_type"],
                "status": "unknown",
                "is_temporary": _is_temporary_url(stream["url"]),
                "quality": None,
                "last_checked": None,
            })
        for sub in subtitles:
            watch_sources.append({
                "source_name": sub["label"],
                "service": "subtitle",
                "resource_id": urllib.parse.unquote(
                    urllib.parse.urlsplit(sub["url"]).path.rsplit("/", 1)[-1]),
                "source_url": sub["url"],
                "final_url": sub["url"],
                "playback_type": "subtitle",
                "status": "active",
                "is_temporary": _is_temporary_url(sub["url"]),
                "quality": None,
                "last_checked": None,
            })
        releases.append({
            "label": "Watch Online / Mirrors" if streams else "Subtitles",
            "quality": None,
            "codec": None,
            "hdr": None,
            "size_bytes": None,
            "audio_languages": ", ".join(languages) or None,
            "season_number": identity["season_number"],
            "episode_number": identity["episode_number"],
            "bridge_url": streams[0]["url"] if streams else None,
            "download_id": None,
            "origin_url": page_url,
            "sources": watch_sources,
        })

    labels_for_adult = (raw_title, category, ", ".join(genres),
                        metas.get("keywords", ""), metas.get("og:keywords", ""),
                        identity["clean_title"])
    poster = _poster(body, metas)

    return {
        "url": page_url,
        "slug": post_m.group("slug"),
        "post_id": post_m.group("post_id"),
        "title": raw_title,
        "clean_title": identity["clean_title"],
        "year": identity["year"],
        "content_type": identity["media_type"],
        "season_number": identity["season_number"],
        "seasons": (json.dumps([{"season": identity["season_number"]}])
                    if identity["media_type"] == "series"
                    and identity["season_number"] else None),
        "poster_url": poster,
        "backdrop_urls": None,
        "imdb_id": (IMDB_ID_RE.search(synopsis or "").group(1)
                    if IMDB_ID_RE.search(synopsis or "") else None),
        "tmdb_id": None,
        "imdb_rating": (RATING_RE.search(info.get("rating", "")).group(1).replace(",", ".")
                        if RATING_RE.search(info.get("rating", "")) else None),
        "genres": ", ".join(genres) or None,
        "synopsis": synopsis or None,
        "cast_names": cast,
        "director": director,
        "duration": info.get("duration") or None,
        "release_date": info.get("release date") or None,
        "languages": ", ".join(languages) or "Unknown",
        "category": category,
        "is_18_plus": 1 if is_adult_content(*labels_for_adult,
                                            prose=(synopsis,)) else 0,
        "is_animated": 1 if looks_animated(raw_title, category, ", ".join(genres),
                                           post_m.group("slug")) else 0,
        "source_site": SITE,
        "canonical_key": identity["canonical_key"],
        "releases": releases,
        "raw_meta": {
            "info_block": {k: v for k, v in info.items() if not k.startswith("__")},
            "meta_tags": {k: v for k, v in metas.items()
                          if k.startswith("og:") or k in ("description", "keywords")},
            "categories": categories,
            "torrents": [{
                "label": scrub_brand(t["display_name"]),
                "quality": t["quality"],
                "codec": t["codec"],
                "hdr": t["hdr"],
                "size": t["size_text"],
                "languages": t["languages"],
                "magnet": t["magnet"],
            } for t in torrents],
            "streams": [{
                "label": s["label"],
                "service": s["service"],
                "playback_type": s["playback_type"],
                "url": s["url"],
            } for s in streams],
            "subtitles": subtitles,
        },
    }, "ok"


# ---------------------------------------------------------------------------
# Public contract: resolve_links
# ---------------------------------------------------------------------------

def _classify_failure(status: int, body: str) -> str:
    head = (body or "")[:600].lower()
    if ("enable javascript" in head or "just a moment" in head
            or "checking if you are" in head or "cf-chl" in head):
        return "js_required"
    if status in (404, 410):
        return "dead"
    if status in (401, 403, 429, 451, 503):
        return "blocked"
    if status in (0,) or status >= 500:
        return "error"
    return "error"


def _probe_source(source: dict, referer: str | None) -> None:
    """Marks one mirror active/dead/blocked; the row itself is never removed."""
    status, _location, body = http_get_once(source.get("source_url"), referer=referer)
    if status in (200, 201, 202, 204, 301, 302, 303, 307, 308):
        verdict = "active"
        head = (body or "")[:600].lower()
        if "just a moment" in head or "enable javascript" in head:
            verdict = "js_required"
    else:
        verdict = _classify_failure(status, body)
    source["status"] = verdict
    source["last_checked"] = int(time.time())
    if verdict != "active":
        source["final_url"] = None


def resolve_links(post_data: dict, probe: bool = True) -> dict:
    """
    Probes every watch/download mirror and records its honest status.

    Torrents and subtitle files are published as final URIs, so they are not
    probed. With ``probe=False`` nothing touches the network and stream mirrors
    keep the honest "unknown" status parse_page gave them.
    """
    if not post_data:
        return post_data
    referer = post_data.get("url")
    for release in post_data.get("releases") or []:
        for source in release.get("sources") or []:
            if not probe:
                continue
            if source.get("service") in ("torrent", "subtitle"):
                continue
            if source.get("playback_type") == "subtitle":
                continue
            _probe_source(source, referer)
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
# Staging database (same tables/columns as import_pagalmovies.py)
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
            source_site TEXT DEFAULT '5movierulz',
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

        CREATE INDEX IF NOT EXISTS idx_5movierulz_posts_slug ON posts(slug);
        CREATE INDEX IF NOT EXISTS idx_5movierulz_posts_year ON posts(year);
        CREATE INDEX IF NOT EXISTS idx_5movierulz_sources_status ON sources(status);
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
    the releases that page produced, so the Telugu and Tamil prints of one film
    (same canonical key, different origin_url) cannot delete each other.
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
                        rel.get("audio_languages"), rel.get("bridge_url"),
                        rel.get("origin_url") or page_url,
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

def _max_listing_page(body: str) -> int:
    pages = [int(n) for n in re.findall(r"/year/\d{4}/page/(\d+)", body or "")]
    return max(pages) if pages else 1


def _iter_year_posts(year: int):
    """Yields (url, slug, post_id) from /year/<YYYY> and its /page/<N> pages."""
    page, max_page = 1, 1
    while page <= min(max_page, MAX_LISTING_PAGES):
        url = f"{BASE_URL}/year/{year}" + (f"/page/{page}" if page > 1 else "")
        status, final_url, body = http_get(url)
        if status != 200:
            return
        if page == 1:
            max_page = _max_listing_page(body)
        links = _post_links(body, final_url or url)
        if not links:
            return
        yield from links
        page += 1


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    """
    Enumerates the catalog from the year shelves into sitemap_cache.

    This origin has no sitemap (HTTP 404) and its WordPress REST API is closed
    (404), so /year/<YYYY>[/page/<N>] is the only complete enumeration. Newest
    years first; stops as soon as ``limit`` post URLs are collected.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for year in range(LAST_YEAR, FIRST_YEAR - 1, -1):
        if limit and len(records) >= limit:
            break
        for loc, slug, _post_id in _iter_year_posts(year):
            if loc in seen:
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
            print("[!] Year shelves yielded no catalog entries; nothing queued.",
                  flush=True)
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
                  workers: int = 4, probe: bool = False, delay: float = 0.2,
                  batch_size: int = 10, verbose: bool = True) -> dict:
    """Fetches, parses and commits every queued sitemap entry."""
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
        except Exception as exc:  # keep the catalog even if a probe dies
            post["resolve_error"] = str(exc)
            return post, verdict

    batch: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_to_loc = {pool.submit(work, r["loc"]): r["loc"] for r in rows}
        for fut in concurrent.futures.as_completed(future_to_loc):
            loc = future_to_loc[fut]
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
            "content_types": dict(conn.execute(
                "SELECT media_type, COUNT(*) FROM posts GROUP BY media_type").fetchall()),
        }
    finally:
        conn.close()


# Alias kept for callers used to import_pagalmovies.stats().
stats = get_stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"5movierulz staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single page URL for parse/resolve")
    parser.add_argument("--probe", action="store_true",
                        help="probe each mirror during crawl")
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
