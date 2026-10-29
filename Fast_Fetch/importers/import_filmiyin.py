#!/usr/bin/env python3
"""
import_filmiyin.py — filmiy.in catalog scraper and staging importer.

Follows the Radd-Stream Manifesto:
- Dedicated Staging Database: /home/ubuntu/radd-stream-data/filmiyin.db
- Strict isolation: NEVER merges into production fast_fetch.db without explicit
  operator confirmation (use merge_catalogs.py once the staging DB is verified).
- Zero external pip packages (100% Python standard library only).
- Adult 18+ titles are stored with is_18_plus = 1; hidden at the presentation layer.
- Zero Data Loss rule: every discovered bridge, embed and mirror is recorded with
  its own health status; nothing is silently discarded.
- Provenance stops at the staging edge: display strings (clean_title, synopsis,
  genres, cast) are scrubbed of site branding, tag-spam and tracker noise. The
  unmodified values stay available to the operator inside posts.raw_meta.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
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

BASE_URL = "https://filmiy.in"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/filmiyin.db")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SITE = "filmiyin"

# The catalog's only legal content types — the unified ledger rejects anything else.
LEGAL_MEDIA_TYPES = ("movie", "series", "complete_season", "ongoing_season")

# sitemap_cache.scraped state machine, shared with every other staging importer:
# 0 = queued, 1 = indexed, -1 = tried but not indexable (needs review).
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC" % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

# Discovery noise: informational pages that are not catalog entries.
NON_POST_PAGES = ("page-how-to-download", "feedback", "rss")

STOP_REQUESTED = False


def _signal_handler(signum, frame):
    global STOP_REQUESTED
    print("\n[!] Graceful shutdown requested... finishing the current batch.", flush=True)
    STOP_REQUESTED = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ---------------------------------------------------------------------------
# Domain knowledge
# ---------------------------------------------------------------------------

# Bridge hosters used by the site. `filesdl.co` sits behind a Cloudflare
# JavaScript challenge ("Just a moment..."), which urllib cannot clear, so the
# bridge is stored verbatim with an honest status — the greenmotors.cc precedent.
BRIDGE_PATTERNS = (
    re.compile(r"""https?://(?:new\d+\.)?filesdl\.[a-z]+/cloud/[A-Za-z0-9+/=_\-\.]+""", re.I),
    re.compile(r"""https?://[a-z0-9.\-]*film(?:dom|my)?[a-z0-9.\-]*/(?:cloud|file|d|genxfm)/[A-Za-z0-9+/=_\-\.]+""", re.I),
)

# Direct-file hosts that are playable without another hop.
DIRECT_HOST_RE = re.compile(
    r"""^https?://("""
    r"""video-downloads\.googleusercontent\.com|"""
    r"""[a-z0-9\-]+\.r2\.dev|"""
    r"""[a-z0-9\-]+\.workers\.dev|"""
    r"""firebasestorage\.googleapis\.com|"""
    r"""[a-z0-9\-]+\.cloudflare\.net"""
    r""")/""",
    re.I,
)

# Analytics / tracker pixels are never media and never reach the ledger.
TRACKER_HOST_RE = re.compile(
    r"""histats\.com|doubleclick|googlesyndication|facebook\.net|analytics|"""
    r"""scorecard|cloudflareinsights|cnzz|hm\.baidu|recaptcha""",
    re.I,
)

# Site branding that must not survive into a public display string.
BRAND_TOKEN_RE = re.compile(r"""filmy\s*\w*|filmy4\w*|filmyfly\w*|bolly\s*\w*""", re.I)

# "adult" stays: 10/12 sampled live titles carrying it are real product (this fleet's
# "… Adult Short Film" vault format), and the measured cost — two *Shin-chan: The Adult
# Empire Strikes Back* rows — is documented, not silently paid. Judge a bare word by its
# live titles. `AGE_CERT_RE` separately flags a bracketed certificate.
ADULT_KEYWORDS = (
    "18+", "18 plus", "adult", "porn", "pornhub", "pornstar", "erotic", "blue film",
    "bluefilm", "nude", "naked", "hentai", "onlyfans", "charmsukh", "hotshots",
    "lust", "sensual", "jalebi", "palang tod", "bhabhi", "milf", "uncensored",
    "softcore", "hardcore", "mms", "bold",
)

# Words the site uses as an adult shelf label but that mainstream prose also uses
# in passing ("a bold, glamorous couple"). Checked against titles, tags and genre
# labels only — never a synopsis.
AMBIGUOUS_ADULT_KEYWORDS = ("bold", "lust", "sensual")

PROSE_ADULT_KEYWORDS = tuple(k for k in ADULT_KEYWORDS
                             if k not in AMBIGUOUS_ADULT_KEYWORDS)

# Age certificates the site writes as a bracketed suffix — a 18+ flag, not a title.
AGE_CERT_RE = re.compile(r"[\(\[\{]\s*(?:18\s*\+|18\s*plus|u\s*/?\s*a|a\s*/\s*c|adult)\s*[\)\]\}]", re.I)

LANGUAGE_WORDS = (
    "hindi", "english", "tamil", "telugu", "malayalam", "kannada", "bengali",
    "marathi", "punjabi", "gujarati", "japanese", "korean", "chinese", "spanish",
    "french", "german", "italian", "russian", "arabic", "turkish", "thai",
    "vietnamese", "indonesian", "indonesia", "malaysian", "malaysia",
)

# Shelf labels the site bolts onto titles; packaging, never part of a work's name.
INDUSTRY_WORDS = (
    "bollywood", "hollywood", "tollywood", "kollywood", "mollywood", "pollywood",
    "south", "anime", "animated", "animation", "k-drama", "kdrama", "c-drama",
)

DESCRIPTOR_WORDS = LANGUAGE_WORDS + INDUSTRY_WORDS + (
    "dubbed", "dual audio", "multi audio", "esub", "subtitles", "episode", "episodes",
)

# Longest first so alternation never leaves "dual" behind after matching "audio".
DESCRIPTOR_TITLES = tuple(sorted(set(LANGUAGE_WORDS + INDUSTRY_WORDS), key=len, reverse=True))

# Release-descriptor tokens that are packaging, not title.
NOISE_TOKEN_RE = re.compile(
    r"""\b(?:480p|576p|720p|900p|1080p|2160p|4k|uhd|hd|sd|fhd|web-?dl|webrip|web-?rip|"""
    r"""bluray|blu-?ray|bdrip|brrip|dvdrip|dvdscr|hdcam|hq-?cam|hd-?ts|pdvd|screener|"""
    r"""hdtv|ppvrip|telesync|cam|hdr|10-?bit|8-?bit|dts|atmos|"""
    r"""x264|x265|hevc|h264|h265|av1|aac|esub|esubbed|d-?sub|hardcoded|subtitles?|"""
    r"""multi-?audio|dual-?audio|un-?cut|full[- ]?movie|full[- ]?film|movie|film|"""
    r"""web[- ]series|tv[- ]series|series|completed|complete|latest|hq|dual|audio|"""
    r"""hevc-?esub|south|dubbed|org|official|unrated|extended|episode[s]?|extras?|"""
    r"""bonus|un-?aired|pre-?dvd|dvd-?clear|work-?print|hd-?rip|web-?hdrip)\b""",
    re.I,
)

QUALITY_RE = re.compile(r"\b(2160p|4k|1080p|720p|576p|480p)\b", re.I)
CODEC_RE = re.compile(
    r"\b(HEVC|x265|x264|AV1|WEB-?DL|WEBRip|BluRay|BDrip|HDCAM|DVDSCR|CAM)\b", re.I)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SEASON_RE = re.compile(r"\bS(\d{1,2})\b|\bSeason\s*(\d{1,2})\b", re.I)
EPISODE_RE = re.compile(r"\bE(?:p(?:sode)?)?\.?\s*(\d{1,3})\b", re.I)
SIZE_TEXT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|Gb|KB|MB|Mb|kB)\b")
RATING_RE = re.compile(r"(?:imdb|rating)\D{0,8}(\d+(?:[.,]\d+)?)", re.I)

ANCHOR_RE = re.compile(
    r"""<a\b[^>]*?href=["'](?P<href>[^"']+?)["'][^>]*>(?P<inner>.*?)</a>""",
    re.S | re.I,
)
IFRAME_RE = re.compile(r"""<iframe\b[^>]*?src=["'](?P<src>[^"']+)["']""", re.I)
IMG_RE = re.compile(r"""<img\b[^>]*?src=["'](?P<src>[^"']+?)["']""", re.I)
META_RE = re.compile(
    r"""<meta\b[^>]*?(?:property|name)=["'](?P<key>[^"']+)["'][^>]*?content=["'](?P<val>[^"']*)["']"""
    r"""|<meta\b[^>]*?content=["'](?P<val2>[^"']*)["'][^>]*?(?:property|name)=["'](?P<key2>[^"']+)["']""",
    re.I,
)
FNAME_RE = re.compile(
    r"""<div\b[^>]*class=["'][^"']*fname[^"']*["'][^>]*>\s*<strong>(?P<key>[^:<]+):?</strong>"""
    r"""(?P<val>.*?)</div>""",
    re.S | re.I,
)

INDUSTRY_COUNTRY = {
    "Tollywood": "India", "Bollywood": "India", "Pollywood": "India",
    "Kollywood": "India", "Mollywood": "India", "Hollywood": "USA",
    "Anime": "Japan", "K-Drama": "South Korea", "C-Drama": "China",
}

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


def http_get(url: str, timeout: int = 30, retries: int = 3):
    """Returns (status_code, final_url, body). Never raises to the caller."""
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
        except Exception as exc:  # URLError, socket timeout, malformed status line
            last_status, last_body = 0, f"[network error] {exc}"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    return last_status, last_url, last_body


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    stripped = _unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", stripped).strip()


def _unescape(text: str) -> str:
    return html_mod.unescape(html_mod.unescape(text or ""))


def scrub_brand(text: str | None) -> str:
    """Removes site branding and tag-spam from a display string."""
    if not text:
        return ""
    out = BRAND_TOKEN_RE.sub(" ", text)
    return re.sub(r"\s+", " ", out).strip(" -–\u00a7»|&")


def _adult_mark(text: str) -> bool:
    return bool(re.search(r"(?<!\d)18\s*\+|18\s*plus", text.lower()))


def _has_keyword(text: str, keywords) -> bool:
    padded = f" {re.sub(r'[^a-z ]+', ' ', text.lower())} "
    return any(f" {kw} " in padded for kw in keywords
               if kw not in ("18+", "18 plus"))


def is_adult_content(*labels: str | None, prose: tuple = ()) -> bool:
    """Flags adult material from titles, shelf labels and tags.

    An 18+ row is hidden at every display surface, so a false positive deletes a
    mainstream title from the catalog. Blurbs use bold/lust/sensual in passing,
    so those count only where the site writes them as its own labels.
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


def _slug_of(url: str) -> str:
    tail = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]
    return re.sub(r"\.html?$", "", tail)


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower().replace("www.", "")


def parse_size_to_bytes(text: str | None) -> int | None:
    """'440Mb' / '1.1Gb' / '8.8GB' -> byte count (binary units, catalog convention)."""
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
    return int(num * {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit])


def _pretty_slug(slug: str) -> str:
    noise = {"hevc", "x264", "x265", "esub", "dsub", "dual", "audio", "uncut", "hd",
             "movie", "movies", "series", "web", "hq", "bluray", "html", "completed",
             "full", "hdcam", "cam", "dubbed", "south", "hindi", "english"}
    words = [w for w in re.split(r"[-_.]+", slug or "")
             if w and w.lower() not in noise and not re.fullmatch(r"(?:19|20)\d{2}", w)
             and not re.fullmatch(r"\d+p", w)]
    return " ".join(words).strip()


# ---------------------------------------------------------------------------
# Title / identity parsing
# ---------------------------------------------------------------------------

def _strip_descriptor_brackets(title: str) -> tuple[str, list[str]]:
    """
    Drops packaging groups and returns them for language capture.

    Brace groups are always packaging on this site ({Hindi + Telugu}, {480p-HEVC},
    {Episode -04 add}). Parentheses are only dropped when they read as a language
    or quality note, so an alternate title like "(Naan Sigappu Manithan)" survives.
    """
    groups: list[str] = []

    def keep_brace(m: re.Match) -> str:
        groups.append(m.group(1))
        return " "

    def check_paren(m: re.Match) -> str:
        inner = m.group(1)
        lowered = inner.lower()
        if any(w in lowered for w in DESCRIPTOR_WORDS) or QUALITY_RE.search(inner):
            groups.append(inner)
            return " "
        return m.group(0)

    out = re.sub(r"\{([^\{\}]{1,80})\}", keep_brace, title)
    out = re.sub(r"[\(\[]([^\(\)\[\]]{1,80})[\)\]]", check_paren, out)
    return out, groups


# Tokens that appear in the site's own URLs as packaging. Used to recover the
# title part of a slug (see _slug_title_base).
PACKAGING_TOKENS = frozenset({
    "movie", "movies", "film", "films", "series", "web", "tv", "hd", "hq", "sd",
    "esub", "esubbed", "dsub", "dub", "dubs", "hevc", "x264", "x265", "h264", "h265",
    "av1", "aac", "uncut", "cut", "dual", "audio", "multi", "dubbed", "south",
    "completed", "complete", "latest", "new", "hdcam", "hqcam", "cam", "ts", "scr",
    "bluray", "blu", "ray", "bdrip", "webdl", "webrip", "full", "official",
    "unofficial", "unrated", "extended", "episode", "episodes", "ep", "add", "extras",
    "extra", "bonus", "unseen", "part", "hdr", "bit", "10bit", "8bit", "dts", "atmos",
    "4k", "uhd", "fhd", "dualaudio", "multiaudio", "esubs", "esubbed", "sub", "subs",
    "subtitle", "subtitles", "hd", "dual", "multi", "audio", "x26", "hevc", "18",
    "predvd", "pre", "dvd", "dvdclear", "clear", "hdrip", "webrip", "workprint", "print",
}) | frozenset(DESCRIPTOR_TITLES) | frozenset(
    w.replace("-", "") for w in DESCRIPTOR_TITLES)


NUMBER_PREFIX_TOKENS = frozenset({"episode", "ep", "part", "extras", "unseen", "bonus", "add"})


def _slug_title_base(slug: str) -> str:
    """
    Recovers the title part of a site slug by trimming packaging from the right.

    A right-hand trim keeps numeric titles ("3-idiots") and sequels ("jailer-2")
    intact while dropping the trailing quality/language/dubbing run the site
    appends to every URL.
    """
    tokens = [t for t in re.split(r"[-_.]+", slug or "") if t]
    while len(tokens) > 1:
        tail = tokens[-1].lower()
        if (tail in PACKAGING_TOKENS or re.fullmatch(r"(?:19|20)\d{2}", tail)
                or re.fullmatch(r"\d{3,4}p", tail) or re.fullmatch(r"s\d{1,2}(?:e\d{1,3})?", tail)
                or re.fullmatch(r"\d{1,2}x", tail)):
            tokens.pop()
            continue
        # A bare number is packaging only as an episode/part counter.
        if (re.fullmatch(r"\d{1,3}", tail) and len(tokens) > 2
                and tokens[-2].lower() in NUMBER_PREFIX_TOKENS):
            tokens.pop()
            continue
        break
    return "-".join(tokens).strip("-")


def build_canonical_key(clean_title: str, year: int | None, season: int | None,
                        episode: int | None, slug: str) -> str:
    """
    Slug-derived identity key.

    The site's slug is the stable handle for a page; a title-derived key would
    change every time the cleaner improves and strand the previous row.
    """
    base = _slug_title_base(slug or "") or re.sub(r"[^a-z0-9]+", "-", (clean_title or "").lower()).strip("-")
    key = f"{base}_{year}" if year else base
    if season:
        key += f"_s{season:02d}"
    if episode:
        key += f"_e{episode:02d}"
    return key or "unknown"


def parse_title(raw_title: str, slug: str = "", explicit_year: int | None = None) -> dict:
    """Derives clean title, year, season/episode, media type, languages and canonical key."""
    brandless = _clean_text(raw_title)
    # <title> carries a "» FilmyFly 2026 – ..." suffix the <h2> does not.
    brandless = re.split(r"\s*[»|]\s*filmy", brandless, maxsplit=1, flags=re.I)[0]
    brandless = scrub_brand(brandless) or brandless
    brandless = re.sub(r"(?<!\d)18\s*\+", " ", brandless)

    # The site always writes "<Title> (YYYY) <descriptors...>", so the bracketed
    # year is the seam between the work's name and its packaging.
    head = re.split(r"\s*[\(\[{]\s*(?:19|20)\d{2}\s*[\)\]}]\s", brandless, maxsplit=1)[0]

    year = explicit_year
    if year is None:
        year_m = YEAR_RE.search(brandless) or re.search(r"[-_ ]((?:19|20)\d{2})[-_.]", slug or "")
        year = int(year_m.group(1)) if year_m else None

    season_m = SEASON_RE.search(brandless) or SEASON_RE.search(_slug_to_text(slug))
    season_number = int(next(g for g in season_m.groups() if g)) if season_m else None
    episode_m = EPISODE_RE.search(brandless)
    episode_number = int(episode_m.group(1)) if episode_m else None

    stripped, dropped = _strip_descriptor_brackets(head)
    stripped = SEASON_RE.sub(" ", stripped)
    stripped = NOISE_TOKEN_RE.sub(" ", stripped)
    stripped = re.sub(r"\b(?:19|20)\d{2}\b", " ", stripped)
    # "Hindi Dubbed" / "Tamil Movie" anywhere, then a trailing descriptor run.
    desc_alt = "|".join(DESCRIPTOR_TITLES)
    stripped = re.sub(rf"\b(?:{desc_alt})\s+(?:dubbed|audio|movie|movies|film|series)\b",
                      " ", stripped, flags=re.I)
    stripped = re.sub(r"[\(\{\[]\s*[\)\}\]]", " ", stripped)
    clean_title = re.sub(r"\s+", " ", re.sub(r"\s*[-–:,_]+\s*", " ", stripped)).strip(" .-–:,_(")
    clean_title = re.sub(rf"(?:\s+(?:{desc_alt}))*\s*$", "", clean_title, flags=re.I).strip(" .-–:,_(")
    if len(clean_title) < 2:
        clean_title = _pretty_slug(slug) or brandless or "untitled"

    lowered = f"{brandless} {slug}".lower()
    is_series = bool(season_number or episode_number
                     or re.search(r"web[-_ ]series|tv[-_ ]series|\bseries\b|\bs0\d\b|\bepisod", lowered))
    if is_series:
        completed = bool(re.search(r"complet|all[-_ ]?episod|finished", lowered))
        media_type = "complete_season" if completed or season_number else "ongoing_season"
    else:
        media_type = "movie"
    if media_type not in LEGAL_MEDIA_TYPES:
        media_type = "movie"

    title_languages: list[str] = []
    for group in dropped:
        for word in re.split(r"[+,/&]|\band\b", group, flags=re.I):
            word = word.strip().lower()
            if word in LANGUAGE_WORDS and word not in title_languages:
                title_languages.append(word)

    return {
        "clean_title": clean_title,
        "year": year,
        "season_number": season_number,
        "episode_number": episode_number,
        "media_type": media_type,
        "title_languages": title_languages,
        "canonical_key": build_canonical_key(clean_title, year, season_number,
                                             episode_number, slug),
    }


def _slug_to_text(slug: str) -> str:
    return re.sub(r"[-_.]+", " ", slug or "")


# ---------------------------------------------------------------------------
# Link harvesting
# ---------------------------------------------------------------------------

def _resource_id(url: str) -> str:
    """Stable id for an opaque bridge token (never the token itself)."""
    return hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:20]


def harvest_links(page_url: str, body: str) -> dict:
    """Splits every anchor/iframe into watch embeds and download bridges."""
    embeds: list[dict] = []
    bridges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    page_slug = _slug_of(page_url)
    page_host = _host_of(page_url)

    def consider(url: str, label: str) -> dict | None:
        if _is_tracker(url):
            return None
        # Same-site links are navigation and related-post cards, never media:
        # a shelf title like "Run Raja Run ... HEVC ESub" otherwise masquerades
        # as a download link and multiplies the release count.
        if _host_of(url) == page_host:
            return None
        if _slug_of(url) == page_slug:
            return None
        is_bridge = any(p.search(url) for p in BRIDGE_PATTERNS)
        is_direct = bool(DIRECT_HOST_RE.match(url))
        lowered = label.lower()
        is_watch = bool(re.search(r"watch|play|stream|server|embed|online", lowered))
        is_download = bool(re.search(r"download|mirror|\d{3,4}p\W|\d+\s*(mb|gb)|hevc|x26[45]", lowered))
        if not (is_bridge or is_direct or is_watch or is_download):
            return None
        quality_m = QUALITY_RE.search(label or "") or QUALITY_RE.search(url)
        codec_m = CODEC_RE.search(label or "")
        return {
            "url": url,
            "label": label or ("bridge" if is_bridge else "direct"),
            "is_bridge": is_bridge,
            "is_direct": is_direct and not is_bridge,
            "is_watch": is_watch and not is_bridge and not is_direct,
            "quality": quality_m.group(1).lower() if quality_m else None,
            "codec": codec_m.group(1).upper().replace(" ", "").replace("-", "") if codec_m else None,
            "size_bytes": parse_size_to_bytes(label) if is_download else None,
        }

    for m in IFRAME_RE.finditer(body):
        entry = consider(_abs_url(m.group("src"), page_url), "embed")
        if entry:
            entry["is_watch"] = True
            embeds.append(entry)

    for m in ANCHOR_RE.finditer(body):
        href = m.group("href")
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        entry = consider(_abs_url(href, page_url), _clean_text(m.group("inner")))
        if not entry:
            continue
        key = (entry["url"].lower(), entry["label"].lower())
        if key in seen:
            continue
        seen.add(key)
        (embeds if entry["is_watch"] else bridges).append(entry)

    return {"embeds": embeds, "bridges": bridges}


def _source_from_link(link: dict) -> dict:
    """One harvested link -> one ledger source row, with its honest status."""
    is_embed = link.get("is_watch") and not link["is_direct"]
    return {
        "source_name": link["label"],
        "service": _host_of(link["url"]),
        "resource_id": _resource_id(link["url"]),
        "source_url": link["url"],
        "final_url": link["url"] if (link["is_direct"] or is_embed) else None,
        "playback_type": "embed" if is_embed else "url",
        "status": "active" if (link["is_direct"] or is_embed) else "unknown",
        "is_temporary": 0 if is_embed else 1,
        "quality": link.get("quality"),
    }


# ---------------------------------------------------------------------------
# Public contract: parse_page
# ---------------------------------------------------------------------------

def parse_page(html_or_url: str, url: str | None = None,
               diagnostics: dict | None = None) -> dict | None:
    """
    Extracts clean metadata, watch embeds and download bridges from filmiy.in.

    Accepts either a page body or a bare URL (which is then fetched). Returns a
    staging-shaped post_data dict, or None when the page is not a catalog entry.
    When a `diagnostics` dict is passed, the reason for a refusal is written to
    `diagnostics["reason"]` — a parked queue row has to say *why* it was parked,
    or the next operator cannot tell a deleted page from a parse miss.
    """
    def decline(reason: str):
        if diagnostics is not None:
            diagnostics["reason"] = reason
        return None

    body = html_or_url or ""
    page_url = url
    if page_url is None and re.match(r"^https?://", body.strip()):
        page_url, body = body.strip(), ""
    if not body:
        if not page_url:
            return decline("no-url")
        status, final_url, body = http_get(page_url)
        if status != 200:
            return decline(f"http-{status}")
        page_url = final_url or page_url
    if not page_url:
        return decline("no-url")
    body = _unescape(body)

    slug = _slug_of(page_url)
    if not page_url.rstrip("/").endswith(".html") or any(n in slug for n in NON_POST_PAGES):
        return decline("not-a-post-page")

    h2_m = re.search(r"(?s)<h2\b[^>]*>(.*?)</h2>", body, re.I)
    title_m = re.search(r"(?s)<title[^>]*>(.*?)</title>", body, re.I)
    raw_title = _clean_text(h2_m.group(1)) if h2_m else _clean_text(title_m.group(1) if title_m else "")
    raw_title = re.split(r"\s*[»|]\s*filmy", raw_title, maxsplit=1, flags=re.I)[0].strip()
    if not raw_title:
        return decline("no-title")

    metas: dict[str, str] = {}
    for m in META_RE.finditer(body):
        key = (m.group("key") or m.group("key2") or "").lower()
        val = m.group("val") if m.group("val") is not None else m.group("val2")
        if key and key not in metas:
            metas[key] = _clean_text(val)

    file_info: dict[str, str] = {}
    for m in FNAME_RE.finditer(body):
        key = _clean_text(m.group("key")).rstrip(":").strip().lower()
        val = _clean_text(m.group("val"))
        if key and val and key not in file_info:
            file_info[key] = val

    release_date = file_info.get("release date") or file_info.get("released") or ""
    rd_year_m = YEAR_RE.search(release_date)
    identity = parse_title(raw_title, slug,
                           explicit_year=int(rd_year_m.group(1)) if rd_year_m else None)

    poster = metas.get("og:image") or ""
    poster = _abs_url(poster, page_url) if poster else ""
    screenshots: list[str] = []
    for m in IMG_RE.finditer(body):
        src = _abs_url(m.group("src"), page_url)
        if _is_tracker(src) or "/uploads/posts/" not in src:
            continue
        name = _slug_of(src)
        if "cover" in src and not poster:
            poster = src
        # imagecloud_* thumbnails belong to related posts, not to this title.
        elif "screenshot" in src and (not name or slug in name or name in slug):
            if src not in screenshots:
                screenshots.append(src)

    synopsis = scrub_brand(file_info.get("description")
                           or metas.get("og:description") or metas.get("description") or "")

    language_field = file_info.get("language") or ""
    languages: list[str] = []
    for token in re.split(r"[+,/&]|\band\b", language_field, flags=re.I):
        token = token.strip()
        if token and token.lower() not in {"dual", "multi", "audio", "hd", ""} and token not in languages:
            languages.append(token)
    for token in identity["title_languages"]:
        pretty = token.title()
        if pretty not in languages:
            languages.append(pretty)
    if not languages:
        languages = ["Hindi"]

    rating_m = RATING_RE.search(" ".join([raw_title, *file_info.values()]))
    imdb_m = re.search(r"\b(tt\d{7,8})\b", body, re.I)

    categories: list[str] = []
    for m in re.finditer(
            r"""href=["']https?://filmiy\.in/[a-z0-9\-]+/["'][^>]*>([^<]{3,60})<""", body, re.I):
        name = _clean_text(m.group(1))
        if name and name.lower() not in {"home", "homepage", "filmyfly home page"} \
                and name not in categories:
            categories.append(name)

    links = harvest_links(page_url, body)
    if not links["bridges"] and not links["embeds"]:
        # nothing playable — not a catalog entry we can serve
        return decline("no-playable-links")

    releases: list[dict] = []
    for link in links["bridges"]:
        releases.append({
            "label": link["label"],
            "quality": link["quality"],
            "codec": link["codec"],
            "size_bytes": link["size_bytes"],
            "season_number": identity["season_number"],
            "episode_number": identity["episode_number"],
            "audio_languages": ", ".join(languages),
            "bridge_url": None if link["is_direct"] else link["url"],
            "sources": [_source_from_link(link)],
        })
    if links["embeds"]:
        # Watch servers describe the title, not one print: they get their own
        # release instead of being pasted onto every quality tier.
        releases.append({
            "label": "Watch",
            "quality": None,
            "codec": None,
            "size_bytes": None,
            "season_number": identity["season_number"],
            "episode_number": identity["episode_number"],
            "audio_languages": ", ".join(languages),
            "bridge_url": None,
            "sources": [_source_from_link(e) for e in links["embeds"]],
        })

    adult_labels = (raw_title, " ".join(categories), metas.get("keywords", ""),
                    file_info.get("genre", ""))
    return {
        "url": page_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": identity["clean_title"],
        "year": identity["year"],
        "content_type": identity["media_type"],
        "season_number": identity["season_number"],
        "seasons": json.dumps([{"season": identity["season_number"], "episodes": []}])
                   if identity["season_number"] else None,
        "poster_url": poster or None,
        "backdrop_urls": screenshots or None,
        "imdb_id": imdb_m.group(1) if imdb_m else None,
        "tmdb_id": None,
        "imdb_rating": (rating_m.group(1).replace(",", ".") if rating_m else None),
        "genres": file_info.get("genre") or None,
        "synopsis": synopsis or None,
        "cast_names": file_info.get("starcast") or file_info.get("cast") or None,
        "director": file_info.get("director") or None,
        "duration": file_info.get("duration") or None,
        "release_date": release_date or None,
        "languages": ", ".join(languages),
        "categories": categories,
        "is_18_plus": 1 if is_adult_content(*adult_labels, prose=(synopsis,)) else 0,
        "is_animated": 1 if looks_animated(raw_title, " ".join(categories), slug) else 0,
        "source_site": SITE,
        "canonical_key": identity["canonical_key"],
        "releases": releases,
        "raw_meta": {
            "file_info": file_info,
            "meta_tags": {k: v for k, v in metas.items()
                          if k.startswith("og:") or k in ("description", "keywords")},
            "page_title": _clean_text(title_m.group(1)) if title_m else raw_title,
            "categories": categories,
            "sizes_text": file_info.get("size"),
            "embed_count": len(links["embeds"]),
            "bridge_count": len(links["bridges"]),
        },
    }


# ---------------------------------------------------------------------------
# Public contract: resolve_links
# ---------------------------------------------------------------------------

def _classify_probe(status: int, body: str, final_url: str) -> tuple[str, str | None]:
    """Maps a probe outcome onto an honest ledger status."""
    head = (body or "")[:4000].lower()
    if "enable javascript" in head or "just a moment" in head \
            or "cf-browser-verification" in head or "checking your browser" in head:
        return "js_required", None
    if status in (404, 410):
        return "dead", None
    if status in (401, 403):
        return "blocked", None
    if status in (200, 206, 301, 302) and final_url:
        return "active", final_url
    return "error", None


def resolve_links(post_data: dict, probe: bool = True) -> dict:
    """
    Resolves each release's downstream CDN mirror and stamps its health.

    Bridges behind a JavaScript challenge are kept verbatim and marked
    `js_required` so a JIT resolver can heal them later. Nothing is discarded
    for failing to resolve. Mutates and returns `post_data`.
    """
    for rel in post_data.get("releases", []):
        for src in rel.get("sources", []):
            if src.get("status") == "active" or src.get("playback_type") == "embed":
                src["final_url"] = src.get("final_url") or src["source_url"]
                src["status"] = src.get("status") or "active"
                continue
            if not probe:
                src["final_url"] = src["final_url"] or src["source_url"]
                src["status"] = "unprobed"
                continue
            status, final_url, body = http_get(src["source_url"], timeout=20, retries=1)
            resolved_status, resolved_url = _classify_probe(status, body, final_url)
            src["status"] = resolved_status
            src["final_url"] = resolved_url or src["source_url"]
            src["last_checked"] = int(time.time())
            if resolved_status in ("js_required", "blocked"):
                # Persistent bridge: the opaque token outlives the gate, so it is
                # not a temporary link and must never be pruned as dead.
                src["is_temporary"] = 0
    return post_data


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(post_data: dict) -> dict:
    """Derives industry/country from the page's own language and shelf labels."""
    blob = " ".join(filter(None, [
        post_data.get("clean_title", ""), _slug_to_text(post_data.get("slug", "")),
        " ".join(post_data.get("categories") or []), post_data.get("languages", ""),
    ])).lower()

    if re.search(r"\banime|animation|japanese\b", blob):
        industry = "Anime"
    elif re.search(r"\bpunjabi|pollywood", blob):
        industry = "Pollywood"
    elif re.search(r"\btelugu|tollywood", blob):
        industry = "Tollywood"
    elif re.search(r"\btamil|kollywood", blob):
        industry = "Kollywood"
    elif re.search(r"\bmalayalam|mollywood", blob):
        industry = "Mollywood"
    elif re.search(r"\bk-?drama|korean\b", blob):
        industry = "K-Drama"
    elif re.search(r"\bc-?drama|chinese\b", blob):
        industry = "C-Drama"
    elif re.search(r"\bhollywood|english\b", blob):
        industry = "Hollywood"
    elif re.search(r"\bbollywood|bengali|marathi|gujarati|hindi|south\b", blob):
        industry = "Bollywood"
    else:
        industry = "Unknown"
    return {"industry": industry, "country": INDUSTRY_COUNTRY.get(industry, "Unknown")}


# ---------------------------------------------------------------------------
# Public contract: export_staging
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
            source_site TEXT DEFAULT 'filmiyin',
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

        CREATE INDEX IF NOT EXISTS idx_filmiyin_posts_slug ON posts(slug);
        CREATE INDEX IF NOT EXISTS idx_filmiyin_posts_year ON posts(year);
        CREATE INDEX IF NOT EXISTS idx_filmiyin_sources_status ON sources(status);
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
    releases that page produced (never the whole site's, so a season page and an
    episode-pack page cannot delete each other). Returns per-run counts.
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
                "languages": post.get("languages"),
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

            # Replace this page's releases only. One title can be published on
            # several pages (a season page and an episode-pack page); replacing
            # per canonical key would delete the earlier page's prints.
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
                            src.get("is_temporary", 0), src.get("quality") or rel.get("quality"),
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
# Public contract: sync_catalog  (+ crawl driver)
# ---------------------------------------------------------------------------

def _iter_sitemap_locs(root_url: str, depth: int = 0, max_depth: int = 3):
    """Yields <loc> values from a urlset, following sitemapindex children."""
    status, _, body = http_get(root_url)
    if status != 200:
        print(f"[!] Sitemap {root_url} -> HTTP {status}", flush=True)
        return
    locs = re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", body, re.I)
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
        if not urllib.parse.urlsplit(loc).path.endswith(".html"):
            continue  # shelf/category pages are listings, not catalog entries
        slug = _slug_of(loc)
        if any(noise in slug for noise in NON_POST_PAGES) or loc in seen:
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


def _bump_error(db_path: Path, loc: str, note: str) -> None:
    if not loc:
        return
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        # The note joins whatever the row already carried instead of replacing it:
        # a queue row that stored a sitemap snippet must not lose it to an error.
        stored = conn.execute("SELECT raw_json FROM sitemap_cache WHERE loc = ?",
                              (loc,)).fetchone()
        try:
            merged = json.loads(stored[0]) if stored and stored[0] else {}
        except (json.JSONDecodeError, TypeError):
            merged = {"previous_raw_json": stored[0] if stored else None}
        if not isinstance(merged, dict):
            merged = {"previous_raw_json": merged}
        merged.update({"last_note": note, "at": int(time.time())})
        conn.execute(
            "UPDATE sitemap_cache SET error_count = error_count + 1, raw_json = ? WHERE loc = ?;",
            (json.dumps(merged), loc))
        # Three failed reads means the page is gone or was never a post: park it.
        conn.execute("UPDATE sitemap_cache SET scraped = -1 WHERE loc = ? AND error_count >= 3;",
                     (loc,))
        conn.commit()
    finally:
        conn.close()


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 4, probe: bool = True, delay: float = 0.15,
                  batch_size: int = 10, verbose: bool = True) -> dict:
    """Fetches, parses, resolves and commits every queued sitemap entry."""
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
        # Returns (post, reason). `post is None` is a decline with a reason;
        # `post is None and reason is None` means the page was never fetched,
        # which must not be charged to the page's three-strike budget.
        if STOP_REQUESTED:
            return None, None
        time.sleep(delay)
        diagnostics: dict = {}
        post = parse_page(loc, diagnostics=diagnostics)
        if post is None:
            return None, diagnostics.get("reason") or "not-indexable"
        try:
            return resolve_links(post, probe=probe), ""
        except Exception as exc:  # keep the catalog even if a bridge probe dies
            post["resolve_error"] = str(exc)
            return post, ""

    batch: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_to_loc = {pool.submit(work, r["loc"]): r["loc"] for r in rows}
        done = 0
        declined: dict[str, int] = {}
        for fut in concurrent.futures.as_completed(future_to_loc):
            loc = future_to_loc[fut]
            done += 1
            try:
                post, reason = fut.result()
            except Exception as exc:
                totals["failed"] += 1
                _bump_error(db_path, loc, f"exception: {exc}")
                continue
            if post is None and reason is None:
                continue  # stop requested before this page was fetched
            totals["pages"] += 1
            if post is None:
                totals["not_indexable"] += 1
                declined[reason] = declined.get(reason, 0) + 1
                _bump_error(db_path, loc, reason)
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
    totals["declined_by_reason"] = declined

    if verbose:
        print(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"not-indexable={totals['not_indexable']} failed={totals['failed']}", flush=True)
        if declined:
            print(f"    [{SITE}] declined as: "
                  + ", ".join(f"{k}={v}" for k, v in
                              sorted(declined.items(), key=lambda kv: -kv[1])),
                  flush=True)
    return totals


def requeue_parked(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                   verbose: bool = True) -> int:
    """
    Put parked rows back in the queue so a later pass can name why each is dead.

    A parked row is that earlier run's verdict, not the site's. Re-sighting them
    costs one request each and buys the only number an operator can act on —
    which of them are 404s, which are pages that simply stopped publishing a
    playable link, and whether any of them came back at all.
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


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    if not batch:
        return
    written = export_staging(db_path, batch)
    totals["posts"] += written["posts_written"]
    totals["releases"] += written["releases_written"]
    totals["sources"] += written["sources_written"]
    totals["not_indexable"] += written["skipped"]
    batch.clear()


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
        }
    finally:
        conn.close()


get_stats = stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"filmiy.in staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats",
                                 "retry-parked"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single page URL for parse/resolve")
    parser.add_argument("--no-probe", action="store_true",
                        help="skip bridge probing during crawl (status = unprobed)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    db = Path(args.db)
    verbose = not args.quiet

    if args.command == "sync":
        sync_catalog(limit=args.limit, db_path=db, verbose=verbose)
    elif args.command == "retry-parked":
        # No probing here: this pass exists to re-measure why a page declined,
        # and a bridge probe would spend requests the verdict does not need.
        requeue_parked(db, limit=args.limit, verbose=verbose)
        crawl_pending(db_path=db, workers=args.workers, probe=False, verbose=verbose)
    elif args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=db, workers=args.workers,
                      probe=not args.no_probe, verbose=verbose)
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
            resolve_links(post)
        print(json.dumps(post, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
