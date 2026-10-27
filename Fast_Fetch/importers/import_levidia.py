#!/usr/bin/env python3
"""
import_levidia.py — isolated staging importer for https://levidia.ch

Writes ONLY to /home/ubuntu/radd-stream-data/levidia.db. Never touches the
production catalog or another site's staging file; merge with
Fast_Fetch/merge_catalogs.py after operator review.
Pure Python standard library. Zero pip packages.

Site model, verified live on 2026-10-28:

    https://beta.levidia.ch/                    the front end; the apex
                                                https://levidia.ch presents a
                                                certificate valid only for
                                                beta.levidia.ch, so BASE_URL is
                                                the beta host and both names are
                                                accepted as site URLs.
    /?tab=top&v=all&page=N                      homepage pagination (shelves
                                                /levidia?v=movies|episodes)
    /movie.php?watch=<slug>                     a film
    /tv-episode.php?watch=<show>-sNeM-<title>   one episode
    /tv-show.php?watch=<show>&s=N               the episode index (not a post)
    /video-hosts.php?h=<id>                     host blurb; current ids 404

A watch page carries its metadata in the right sidebar (.minfo), the plot in
the first real `.plot`, genres as browse.php?nd=genre links, and one
`<li class="xxx0">` row per host copy. Each row names the host, a release
group (`spider`, `corintus`, `Fugitive`, `voxmaris`), an optional quality
(`DVDRip`) and a `/go.php?url=<encrypted-token>` player link. The token is
AES-encrypted client-side; `go.php` answered HTTP 404 to every stdlib request
we made (with and without the site's JS cookie, and with a token percent-
encoded), so the importer stores each link as an honest bridge and records the
probe verdict — dead when the site says 404 — instead of pretending it resolved.

The sampled pages publish no subtitle tracks. `harvest_subtitles()` still reads
`<track>`, `.vtt/.srt/.ass` anchors and JSON `file=` shapes, and every track it
finds becomes its own `sources` row with playback_type='subtitle'; a title with
no tracks simply has no subtitle rows.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html as html_mod
import http.cookiejar
import json
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

BASE_URL = "https://beta.levidia.ch"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/levidia.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITE = "levidia"
LEGAL_MEDIA_TYPES = ("movie", "series")
QUEUED_SCRAPE_STATES = (0, 2)
PENDING_SELECT = (
    "SELECT loc, lastmod, slug FROM sitemap_cache"
    " WHERE scraped IN (%s) ORDER BY rowid ASC"
    % ", ".join(["?"] * len(QUEUED_SCRAPE_STATES))
)

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

# Host membership: the beta host is the front end, the apex redirects to it and
# still appears in the site's own footer. Label-anchored so a look-alike is not
# mistaken for the site.
SITE_HOST_RE = re.compile(r"(?:^|\.)levidia\.ch$", re.I)

TRACKER_HOST_RE = re.compile(
    r"""doubleclick|googlesyndication|google-analytics|googletagmanager"""
    r"""|cloudflareinsights|scorecard|histats\.com|bit\.ly|tinyurl|go\.links\."""
    r"""|short\.url|pagead|recaptcha""",
    re.I,
)

# Site branding that must not survive into a public display string.
BRAND_TOKEN_RE = re.compile(r"""levidia(?:\.ch)?|piratenz(?:\.eu)?|pirate\s*nz""", re.I)

POST_URL_RE = re.compile(
    r"""/(?P<kind>movie|tv-episode|tv-show)\.php\?(?:[^#\s]*&)?watch="""
    r"""(?P<slug>[^"'<>\s&]+)""", re.I)
POST_PATH_RE = re.compile(r"""/(movie|tv-episode)\.php$""", re.I)
GO_URL_RE = re.compile(r"""go\.php\?url=(?P<token>[A-Za-z0-9+/=%_\-]+)""", re.I)
QUALITY_RE = re.compile(r"\b(2160p|4k|1080p|720p|576p|480p|360p|DVDRip|DVDrip|"
                        r"WEB-?DL|WEBRip|BluRay|BDRip|HDTV|HDCAM|CAM)\b", re.I)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SEASON_RE = re.compile(r"\bSeas[oe]n\s*(\d{1,2})\b|\bS(\d{1,2})E\d{1,3}\b", re.I)
EPISODE_RE = re.compile(r"\bEpisode\s*(\d{1,3})\b|\bS\d{1,2}E(\d{1,3})\b", re.I)
EPISODE_SLUG_RE = re.compile(
    r"^(?P<series>.+?)-s(?P<season>\d{1,2})e(?P<episode>\d{1,3})(?:-(?P<rest>.*))?$",
    re.I)
IMDB_ID_RE = re.compile(r"\b(tt\d{7,10})\b", re.I)
SIZE_TEXT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|KB|MB)\b", re.I)
SUBTITLE_EXT_RE = re.compile(r"\.(vtt|srt|ass)(?:[?#]|$)", re.I)
JS_GATE_MARKERS = ("just a moment", "enable javascript", "checking if you are")

LANGUAGE_CODES = {
    "en": "English", "eng": "English", "hi": "Hindi", "hin": "Hindi",
    "ur": "Urdu", "urd": "Urdu", "ta": "Tamil", "te": "Telugu",
    "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
    "pa": "Punjabi", "gu": "Gujarati", "ja": "Japanese", "jp": "Japanese",
    "ko": "Korean", "zh": "Chinese", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "ru": "Russian", "ar": "Arabic",
    "tr": "Turkish", "th": "Thai", "vi": "Vietnamese", "id": "Indonesian",
    "tl": "Tagalog", "fa": "Persian", "nl": "Dutch", "sv": "Swedish",
    "pl": "Polish", "pt": "Portuguese",
}
LANGUAGE_WORDS = tuple(sorted(set(LANGUAGE_CODES.values()), key=len, reverse=True))

ADULT_KEYWORDS = (
    "18+", "18 plus", "adult", "porn", "pornstar", "erotic", "hentai",
    "onlyfans", "nude", "naked", "hardcore", "softcore", "xxx", "brazzers",
    "milf", "uncensored", "sex tape", "sexscene",
)
AMBIGUOUS_ADULT_KEYWORDS = ("adult", "nude", "naked", "erotic")
PROSE_ADULT_KEYWORDS = tuple(k for k in ADULT_KEYWORDS if k not in AMBIGUOUS_ADULT_KEYWORDS)

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

# Verification stays on: the beta host serves a valid Let's Encrypt certificate.
SSL_CONTEXT = ssl.create_default_context()

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


def prepare_url(url: str) -> str:
    """html.unescape() first, then quote with the catalog's safe set."""
    return urllib.parse.quote(
        html_mod.unescape((url or "").strip()),
        safe=":/?#[]@!$&'()*+,;=%",
    )


def http_get(url: str, timeout: int = 30, retries: int = 3):
    """Returns (status_code, final_url, body) following redirects. Never raises."""
    url = prepare_url(url)
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
                return exc.code, url, last_body  # final; retrying a gate is rude
        except Exception as exc:
            last_status, last_body = 0, f"[network error] {exc}"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    return last_status, last_url, last_body


def http_get_once(url: str, referer: str | None = None, timeout: int = 25):
    """One request, redirects left alone: returns (status, location, body)."""
    url = prepare_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = prepare_url(referer)
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
    return html_mod.unescape(text or "")


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", _unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _bare(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" -–:,,.·|")


def _capitalize(text: str) -> str:
    return re.sub(r"(^|\s)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text or "")


def _slugify(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _unescape(text or "").lower()).strip("-")


def _pretty_slug(slug: str) -> str:
    words = [w for w in re.split(r"[-_.]+", re.sub(r"[^\w\-_.]+", " ", slug or "")) if w]
    return " ".join(words).strip()


def scrub_brand(text: str | None) -> str:
    if not text:
        return ""
    out = BRAND_TOKEN_RE.sub(" ", text)
    return re.sub(r"\s+", " ", out).strip(" -–§»|&,:.")


def _meaningful(text: str | None) -> str:
    out = (text or "").strip()
    return "" if re.fullmatch(r"(?:n/?a|na|not available|-+|tbd|unknown)",
                              out, re.I) else out


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc.lower().replace("www.", "")


def _is_site_url(url: str) -> bool:
    return bool(SITE_HOST_RE.search(_host_of(url)))


def _is_tracker(url: str) -> bool:
    return bool(TRACKER_HOST_RE.search(url or ""))


def _abs_url(href: str, base: str) -> str:
    return prepare_url(urllib.parse.urljoin(base, _unescape(href.strip())))


def _attr(tag: str, name: str) -> str:
    m = re.search(r"""\b%s\s*=\s*["']([^"']*)["']""" % re.escape(name), tag or "", re.I)
    return _unescape(m.group(1)).strip() if m else ""


def parse_size_to_bytes(text: str | None) -> int | None:
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


def is_adult_content(*labels: str | None, prose: tuple = ()) -> bool:
    """Flags adult material from the site's own shelf/genre labels."""
    head = " ".join(t for t in labels if t)
    padded = f" {re.sub(r'[^a-z0-9+ ]+', ' ', head.lower())} "
    if re.search(r"(?<!\d)18\s*\+|18\s*plus", head.lower()):
        return True
    if any(f" {kw} " in padded for kw in ADULT_KEYWORDS if kw not in ("18+", "18 plus")):
        return True
    body = " ".join(t for t in prose if t).lower()
    padded_body = f" {re.sub(r'[^a-z0-9+ ]+', ' ', body)} "
    return any(f" {kw} " in padded_body for kw in PROSE_ADULT_KEYWORDS)


def looks_animated(*texts: str | None) -> bool:
    joined = " ".join(t for t in texts if t).lower()
    return bool(re.search(r"\b(anime|animated|animation)\b", joined))


def _languages_in(*texts: str | None) -> list[str]:
    blob = " " + re.sub(r"[^a-z ]+", " ", " ".join(t for t in texts if t).lower()) + " "
    return [w for w in LANGUAGE_WORDS if f" {w.lower()} " in blob]


# ---------------------------------------------------------------------------
# Title / identity parsing
# ---------------------------------------------------------------------------

def _episode_parts(text: str, slug: str) -> tuple[str | None, int | None, int | None, str | None]:
    """Returns (series_from_slug, season, episode, episode_title)."""
    season = episode = None
    series_slug = None
    rest = None
    sm = EPISODE_SLUG_RE.match(slug or "")
    if sm:
        series_slug = sm.group("series")
        season = int(sm.group("season"))
        episode = int(sm.group("episode"))
        rest = sm.group("rest") or None
    season_m = SEASON_RE.search(text or "")
    episode_m = EPISODE_RE.search(text or "")
    if season_m:
        season = int(next(g for g in season_m.groups() if g))
    if episode_m:
        episode = int(next(g for g in episode_m.groups() if g))
    episode_title = None
    et = re.search(r"Episode\s*\d{1,3}\s*[:\-–]\s*(.+)$", text or "", re.I)
    if et:
        episode_title = _bare(et.group(1))
    elif rest:
        episode_title = _capitalize(_pretty_slug(rest))
    return series_slug, season, episode, episode_title


def parse_title(raw_title: str, slug: str = "", explicit_year: int | None = None,
                series_title: str | None = None) -> dict:
    """Derives clean title, year, season/episode, media type, languages and key."""
    brandless = _clean_text(raw_title)
    brandless = re.sub(r"^\s*watch\s+", "", brandless, flags=re.I)
    brandless = re.split(r"\s*\|\s*(?:piratenz|levidia).*$", brandless, flags=re.I)[0]
    brandless = re.sub(r"\s+online\s*$", "", brandless, flags=re.I)
    brandless = scrub_brand(brandless) or brandless
    brandless = re.sub(r"\s*\(?\s*(?<!\d)18\s*\+", " ", brandless).strip()

    year = explicit_year
    if year is None:
        m = (re.search(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]", brandless)
             or YEAR_RE.search(brandless)
             or re.search(r"-((?:19|20)\d{2})-?$", slug or ""))
        year = int(m.group(1)) if m else None

    series_slug, season, episode, episode_title = _episode_parts(brandless, slug)
    is_episode = bool(episode and (season or "episode" in brandless.lower()
                                   or EPISODE_SLUG_RE.match(slug or "")))

    if is_episode:
        if series_title:
            clean = scrub_brand(_clean_text(series_title))
        else:
            head_series = re.split(r"\bSeas[oe]n\s*\d|\bS\d{1,2}E\d{1,3}", brandless,
                                   maxsplit=1, flags=re.I)[0]
            clean = (_bare(head_series)
                     or _capitalize(_pretty_slug(series_slug or "")))
        clean = _bare(clean)
        base = _slugify(clean) or _slugify(series_slug) or "unknown"
        canonical = f"{base}_s{int(season or 1):02d}_e{int(episode):02d}"
        media_type = "series"
    else:
        head = re.split(r"\s*[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]", brandless, maxsplit=1)[0]
        clean = (_bare(re.sub(r"\b(?:19|20)\d{2}\b", " ", head))
                 or _bare(head) or _bare(brandless))
        # A work named for a year ("1917", "2012") keeps its name.
        base = _slugify(clean)
        canonical = f"{base}_{year}" if year else base
        media_type = "movie"
        season = episode = None

    lowered = " ".join(filter(None, [brandless, _pretty_slug(slug)]))
    return {
        "clean_title": clean or brandless or "Unknown",
        "year": year,
        "season_number": season,
        "episode_number": episode,
        "episode_title": episode_title,
        "media_type": media_type,
        "languages": _languages_in(lowered),
        "canonical_key": canonical or "unknown",
    }


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _sidebar_info(body: str) -> dict:
    """Reads the right sidebar's Labelled rows (Release, Director, Cast, …)."""
    fields: dict[str, str] = {}
    i = body.find('class="kiri minfo"')
    if i < 0:
        return fields
    j = body.find('<div class="aclear"', i)
    block = body[i:j if j > i else i + 8000]
    for m in re.finditer(r"<div[^>]*>\s*([A-Za-z][A-Za-z ]{2,20}):\s*(.*?)</div>",
                         block, re.S | re.I):
        label = _clean_text(m.group(1)).lower()
        value = _clean_text(m.group(2))
        if label and value:
            fields[label] = value
    return fields


def _plot(body: str) -> str:
    for m in re.finditer(r'<div class="plot(?P<cls>[^"]*)"[^>]*>(?P<body>.*?)</div>',
                         body or "", re.S | re.I):
        cls = m.group("cls").lower()
        if "instat" in cls or "mals" in cls:
            continue
        text = _clean_text(m.group("body"))
        if text:
            return text
    return ""


def _poster_url(body: str, page_url: str) -> str | None:
    for tag in re.findall(r"<img\b[^>]*>", body or "", re.I):
        if "mposter" in tag.lower():
            src = _attr(tag, "src")
            if src:
                url = _abs_url(src, page_url)
                return None if _is_tracker(url) else url
    return None


def _genres(body: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r'<div class="kanan genre"[^>]*>(.*?)</div>', body or "", re.S | re.I):
        for href, inner in re.findall(
                r"""<a\b[^>]*?href=["']([^"']+)["'][^>]*>(.*?)</a>""", m.group(1), re.S | re.I):
            if "nd=genre" not in _unescape(href).lower():
                continue
            label = _clean_text(inner)
            if label and label not in out:
                out.append(label)
    return out


def _cast(body: str) -> str:
    info = _sidebar_info(body)
    return info.get("cast", "")


def harvest_hosts(body: str) -> list[dict]:
    """Reads every `<li class="xxx0">` host row on a watch page."""
    rows: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'<li class="xxx0">(.*?)</li>', body or "", re.S | re.I):
        row = m.group(1)
        go_m = re.search(r"""href=["']([^"']*go\.php\?url=[^"']+)["']""", row, re.I)
        if not go_m:
            continue
        go_url = _unescape(go_m.group(1)).strip()
        if go_url in seen:
            continue
        seen.add(go_url)
        host_m = re.search(r'<span class="kiri xxx1[^"]*">(.*?)</span>', row, re.S | re.I)
        host = ""
        if host_m:
            b = re.search(r"<b>(.*?)</b>", host_m.group(1), re.S | re.I)
            host = _clean_text(b.group(1) if b else host_m.group(1))
        group_m = re.search(r'<span class="kanan xdt">(.*?)</span>', row, re.S | re.I)
        quality_m = re.search(r'<span class="kiri xxx3">(.*?)</span>', row, re.S | re.I)
        title_m = re.search(r"<h2[^>]*>(.*?)</h2>", row, re.S | re.I)
        quality = _clean_text(quality_m.group(1)) if quality_m else ""
        qm = QUALITY_RE.search(quality or "")
        rows.append({
            "page_url": go_url,
            "host": host or "Unknown",
            "group": _clean_text(group_m.group(1)) if group_m else "",
            "quality": (qm.group(1) if qm else quality) or None,
            "row_title": _clean_text(title_m.group(1)) if title_m else "",
            "token": (GO_URL_RE.search(go_url).group("token")
                      if GO_URL_RE.search(go_url) else None),
        })
    return rows


def harvest_subtitles(body: str, page_url: str) -> list[dict]:
    """Reads every subtitle track the page publishes, in every language."""
    tracks: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(raw_url: str, label: str = "", lang: str = "") -> None:
        url = _abs_url(raw_url, page_url)
        if _is_tracker(url) or not SUBTITLE_EXT_RE.search(urllib.parse.urlsplit(url).path):
            return
        fmt = SUBTITLE_EXT_RE.search(urllib.parse.urlsplit(url).path).group(1).lower()
        lang = (lang or "").strip().lower()
        key = (url, lang)
        if key in seen:
            return
        seen.add(key)
        tracks.append({
            "url": url,
            "label": label or LANGUAGE_CODES.get(lang, lang) or fmt.upper(),
            "language": lang or None,
            "format": fmt,
        })

    for tag in re.findall(r"<track\b[^>]*>", body or "", re.I):
        add(_attr(tag, "src"), _attr(tag, "label"), _attr(tag, "srclang"))
    for href, inner in re.findall(
            r"""<a\b[^>]*?href=["']([^"']+?)["'][^>]*>(.*?)</a>""", body or "", re.S | re.I):
        if SUBTITLE_EXT_RE.search(_unescape(href)):
            add(href, _clean_text(inner), "")
    for m in re.finditer(
            r"""["'](?:file|src|url)["']\s*:\s*["']([^"']+?\.(?:vtt|srt|ass))["']""",
            body or "", re.I):
        add(m.group(1))
    return tracks


def _source_from_row(row: dict, quality: str | None) -> dict:
    return {
        "source_name": row["host"],
        "service": _slugify(row["host"]) or "host",
        "resource_id": row["token"],
        "source_url": row["page_url"],
        "final_url": None,
        "playback_type": "embed",
        "status": "unknown",
        "is_temporary": 0,
        "quality": quality,
    }


def _subtitle_release(tracks: list[dict]) -> dict | None:
    if not tracks:
        return None
    return {
        "label": "Subtitles",
        "quality": None,
        "codec": None,
        "size_bytes": None,
        "audio_languages": None,
        "season_number": None,
        "episode_number": None,
        "part": None,
        "bridge_url": None,
        "download_id": None,
        "sources": [{
            "source_name": t["label"],
            "service": "subtitle",
            "resource_id": t["language"] or t["format"],
            "source_url": t["url"],
            "final_url": t["url"],
            "playback_type": "subtitle",
            "status": "active",
            "is_temporary": 0,
            "quality": None,
        } for t in tracks],
    }


def _episode_breadcrumb(body: str) -> dict:
    """Reads the show / season / episode links above the plot."""
    out: dict[str, str] = {}
    block_m = re.search(r'<div class="plot instat">(.*?)</div>', body or "", re.S | re.I)
    block = block_m.group(1) if block_m else ""
    show = re.search(r"""tv-show\.php\?watch=[^"']+["'][^>]*>(.*?)</a>""", block, re.S | re.I)
    if show:
        out["series_title"] = _clean_text(show.group(1))
    season = re.search(r"""Season\s*(\d{1,2})""", block, re.I)
    if season:
        out["season"] = season.group(1)
    episode = re.search(r"""Episode\s*(\d{1,3})\s*:\s*(.*?)</b>""", block, re.S | re.I)
    if episode:
        out["episode"] = episode.group(1)
        out["episode_title"] = _clean_text(episode.group(2))
    return out


def parse_page(html_or_url: str, url: str | None = None) -> dict | None:
    """Extracts clean metadata, host links and subtitles from one watch page."""
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

    post_m = POST_URL_RE.search(page_url)
    if not post_m:
        return None, "removed" if POST_URL_RE.search(requested) else "not-a-post"
    kind = post_m.group("kind").lower()
    if kind == "tv-show":
        return None, "not-a-post"  # the episode index is a container, not a post
    slug = urllib.parse.unquote(post_m.group("slug")).strip("/")

    h1_m = re.search(r"<h1\b[^>]*>(.*?)</h1>", body or "", re.S | re.I)
    h1 = _clean_text(h1_m.group(1)) if h1_m else ""
    title_tag = re.search(r"<title>(.*?)</title>", body or "", re.S | re.I)
    raw_title = (h1 or _clean_text(title_tag.group(1) if title_tag else "")
                 or _pretty_slug(slug))
    raw_title = re.sub(r"\(\s*((?:19|20)\d{2})\s*\)", r"(\1)", raw_title)
    if not h1 and re.search(r"best free movie|watch free movies", raw_title, re.I):
        return None, "removed"

    info = _sidebar_info(body)
    crumb = _episode_breadcrumb(body)
    release_date = info.get("air date") or info.get("release") or ""
    year_m = (re.search(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]", raw_title)
              or YEAR_RE.search(release_date)
              or re.search(r"-((?:19|20)\d{2})-?$", slug))
    explicit_year = int(year_m.group(1)) if year_m else None

    if kind == "tv-episode":
        identity = parse_title(raw_title, slug, explicit_year,
                               series_title=crumb.get("series_title"))
        if crumb.get("season"):
            identity["season_number"] = int(crumb["season"])
        if crumb.get("episode"):
            identity["episode_number"] = int(crumb["episode"])
        if identity["season_number"] and identity["episode_number"]:
            base = _slugify(identity["clean_title"])
            identity["canonical_key"] = (f"{base}_s{identity['season_number']:02d}"
                                         f"_e{identity['episode_number']:02d}")
        if crumb.get("episode_title"):
            identity["episode_title"] = crumb["episode_title"]
    else:
        identity = parse_title(raw_title, slug, explicit_year)
    identity["media_type"] = "series" if kind == "tv-episode" else "movie"

    genres = _genres(body)
    synopsis = _meaningful(scrub_brand(_plot(body)))
    cast = _cast(body)
    poster = _poster_url(body, page_url)
    imdb_m = IMDB_ID_RE.search(body or "")
    runtime = info.get("runtime", "")
    language_text = info.get("language", "")
    language_names: list[str] = []
    for token in re.split(r"[,/| ]+", language_text or ""):
        code = token.strip().lower()
        if code in LANGUAGE_CODES:
            language_names.append(LANGUAGE_CODES[code])
    language_names.extend(identity["languages"])
    languages = ", ".join(dict.fromkeys(language_names)) or "Unknown"

    hosts = harvest_hosts(body)
    subtitles = harvest_subtitles(body, page_url)
    languages_json = json.dumps(
        [{"language": l, "label": l} for l in dict.fromkeys(languages.split(", "))
         if l and l != "Unknown"], ensure_ascii=False)

    # One release per (quality, release group); every host copy stays a source.
    grouped: dict[tuple, list[dict]] = {}
    for row in hosts:
        key = (row["quality"], row["group"])
        grouped.setdefault(key, []).append(row)
    releases: list[dict] = []
    for (quality, group), rows in grouped.items():
        label = " · ".join(x for x in (quality, group) if x) or "Stream"
        releases.append({
            "label": label,
            "quality": quality,
            "codec": None,
            "size_bytes": None,
            "audio_languages": None if languages == "Unknown" else languages,
            "season_number": identity["season_number"] if kind == "tv-episode" else None,
            "episode_number": identity["episode_number"] if kind == "tv-episode" else None,
            "part": None,
            "bridge_url": rows[0]["page_url"],
            "download_id": rows[0]["token"],
            "sources": [_source_from_row(r, quality) for r in rows],
        })
    sub_release = _subtitle_release(subtitles)
    if sub_release:
        releases.append(sub_release)

    episodes = ([{
        "season": identity["season_number"],
        "episode": identity["episode_number"],
        "title": identity.get("episode_title"),
        "air_date": release_date or None,
    }] if kind == "tv-episode" else [])
    seasons_json = json.dumps(
        [{"season": identity["season_number"] or 1,
          "series": identity["clean_title"],
          "episodes": episodes}], ensure_ascii=False) if episodes else None

    labels_for_adult = (raw_title, ", ".join(genres), identity["clean_title"], slug)
    return {
        "url": page_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": identity["clean_title"],
        "year": identity["year"],
        "content_type": identity["media_type"],
        "season_number": identity["season_number"],
        "episode_number": identity["episode_number"],
        "episodes": episodes,
        "seasons": seasons_json,
        "poster_url": poster,
        "backdrop_urls": None,
        "imdb_id": imdb_m.group(1) if imdb_m else None,
        "tmdb_id": None,
        "imdb_rating": None,
        "genres": ", ".join(genres) if genres else None,
        "synopsis": synopsis or None,
        "cast_names": cast or None,
        "director": info.get("director") or None,
        "duration": runtime or None,
        "release_date": release_date or None,
        "languages": languages,
        "language_tracks": languages_json,
        "category": (genres[0] if genres else None),
        "is_18_plus": 1 if is_adult_content(*labels_for_adult, prose=(synopsis,)) else 0,
        "is_animated": 1 if looks_animated(raw_title, ", ".join(genres)) else 0,
        "source_site": SITE,
        "canonical_key": identity["canonical_key"],
        "releases": releases,
        "raw_meta": {
            "page_kind": kind,
            "sidebar": info,
            "host_rows": [{k: v for k, v in row.items() if k != "page_url"}
                          for row in hosts],
            "subtitle_tracks": subtitles,
            "episode_title": identity.get("episode_title"),
            "breadcrumb": crumb,
        },
    }, "ok"


# ---------------------------------------------------------------------------
# Public contract: resolve_links
# ---------------------------------------------------------------------------

def _classify_failure(status: int, body: str) -> str:
    head = (body or "")[:600].lower()
    if any(marker in head for marker in JS_GATE_MARKERS):
        return "js_required"
    if status in (404, 410):
        return "dead"
    if status in (401, 403, 503):
        return "blocked"
    return "error"


def _looks_playable(url: str) -> bool:
    if not url:
        return False
    host = _host_of(url)
    return bool(re.search(
        r"""(?:^|\.)(?:r2\.dev|googleapis\.com|googleusercontent\.com|workers\.dev"""
        r"""|cloudfront\.net|akamaized\.net|fastly\.net)$""", host, re.I)
        or bool(SUBTITLE_EXT_RE.search(urllib.parse.urlsplit(url).path))
        or bool(re.search(r"\.(?:mp4|m3u8|mkv|webm)$", urllib.parse.urlsplit(url).path, re.I)))


def _probe_source(source: dict, referer: str) -> dict:
    status, location, body = http_get_once(source.get("source_url") or "", referer=referer)
    if status in (301, 302, 303, 307, 308) and location:
        target = prepare_url(urllib.parse.urljoin(source["source_url"], _unescape(location)))
        if _is_site_url(target):
            # A bounce back to the site is a gate, never a resolved playable.
            source["status"] = "blocked"
            source["final_url"] = None
            return source
        source["final_url"] = target
        source["status"] = "active"
        source["playback_type"] = "stream" if _looks_playable(target) else "embed"
        source["is_temporary"] = 1 if ("?" in target or _looks_playable(target)) else 0
        return source
    if status == 200:
        head = (body or "")[:600].lower()
        if any(marker in head for marker in JS_GATE_MARKERS):
            source["status"] = "js_required"
            source["final_url"] = None
        else:
            source["status"] = "active"
            source["final_url"] = source.get("source_url")
        return source
    source["status"] = _classify_failure(status, body) if status else "error"
    source["final_url"] = None
    return source


def resolve_links(post_data: dict, probe: bool = True, deep: bool = False,
                  max_probes: int | None = None) -> dict:
    """
    Probes every host bridge on the page and records what the site answers.

    A subtitle row is already the track itself, so it is never re-probed and
    never rewritten. ``max_probes`` caps the requests a caller wants to spend;
    sources beyond the cap stay honestly 'unknown'.
    """
    if not post_data:
        return post_data
    referer = post_data.get("url")
    probed = 0
    for release in post_data.get("releases") or []:
        for source in release.get("sources") or []:
            if source.get("playback_type") == "subtitle":
                continue
            if not probe:
                continue
            if max_probes is not None and probed >= max_probes:
                continue
            probed += 1
            _probe_source(source, referer)
            source["last_checked"] = int(time.time())
    return post_data


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(post_data: dict) -> dict:
    blob = " ".join(filter(None, [
        post_data.get("clean_title"), post_data.get("title"),
        post_data.get("genres"), post_data.get("languages")]))
    lowered = blob.lower()
    animated = "animation" in lowered or "anime" in lowered
    country = "Unknown"
    for word, place in (("hindi", "India"), ("urdu", "Pakistan"), ("tamil", "India"),
                        ("telugu", "India"), ("korean", "South Korea"),
                        ("japanese", "Japan"), ("chinese", "China"),
                        ("spanish", "Spain"), ("french", "France")):
        if word in lowered:
            country = place
            break
    return {
        "industry": "Anime" if animated else "Unknown",
        "country": country,
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
            source_site TEXT DEFAULT 'levidia',
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

        CREATE INDEX IF NOT EXISTS idx_levidia_posts_slug ON posts(slug);
        CREATE INDEX IF NOT EXISTS idx_levidia_posts_year ON posts(year);
        CREATE INDEX IF NOT EXISTS idx_levidia_sources_status ON sources(status);
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
    """Commits parsed post dicts into the isolated staging database (idempotent)."""
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
                             "url", "slug", "source_site", "raw_meta")
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
# Discovery / public contract: sync_catalog
# ---------------------------------------------------------------------------

def _post_slug_from_loc(loc: str) -> str | None:
    m = POST_URL_RE.search(loc or "")
    return urllib.parse.unquote(m.group("slug")) if m else None


def _iter_sitemap_locs(root_url: str, depth: int = 0, max_depth: int = 2):
    status, _, body = http_get(root_url)
    if status != 200:
        return
    locs = [_unescape(m) for m in re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", body, re.I)]
    if "<sitemapindex" in body.lower() and depth < max_depth:
        for child in locs:
            yield from _iter_sitemap_locs(child, depth + 1, max_depth)
        return
    yield from locs


def _listing_links(body: str, page_url: str) -> list[str]:
    out: list[str] = []
    for href in re.findall(r"""<a\b[^>]*?href=["']([^"']+)["']""", body or "", re.I):
        url = _abs_url(href, page_url)
        if POST_URL_RE.search(url) and "/tv-show.php" not in url:
            out.append(url)
    return out


def _homepage_pages(max_pages: int):
    """Yields listing URLs: the homepage, then its top/all pagination."""
    yield f"{BASE_URL}/"
    for page in range(2, max_pages + 1):
        yield f"{BASE_URL}/?tab=top&v=all&page={page}"


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True, max_pages: int = 3) -> int:
    """
    Enumerates watch-page URLs into sitemap_cache.

    The site publishes no sitemap.xml (verified: HTTP 404), so discovery falls
    back to the homepage and its finite top/all pagination. It never walks the
    alphabet, genre or cast shelves — those are listings, not catalog entries.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for loc in _iter_sitemap_locs(SITEMAP_URL):
        slug = _post_slug_from_loc(loc)
        if not slug or "/tv-show.php" in loc or loc in seen:
            continue
        seen.add(loc)
        records.append((loc, "", slug))
        if limit and len(records) >= limit:
            break

    if not records:
        for listing in _homepage_pages(max_pages):
            status, final_url, body = http_get(listing)
            if status != 200:
                continue
            for loc in _listing_links(body, final_url or listing):
                slug = _post_slug_from_loc(loc)
                if not slug or loc in seen:
                    continue
                seen.add(loc)
                records.append((loc, "", slug))
                if limit and len(records) >= limit:
                    break
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
            print("[!] No watch pages discovered; nothing queued.", flush=True)
        else:
            print(f"[✓] [{SITE}] Queued {len(records)} watch pages "
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
        print(f"[*] [{SITE}] {len(rows)} pages pending (probe={probe}).", flush=True)

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
        except Exception as exc:
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
            "movies": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE media_type = 'movie'").fetchone()[0],
            "series_episodes": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE media_type = 'series'").fetchone()[0],
            "adult_flagged": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "animated": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_animated = 1").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "subtitle_sources": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE playback_type = 'subtitle'").fetchone()[0],
            "source_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
            "services": dict(conn.execute(
                "SELECT service, COUNT(*) FROM sources GROUP BY service"
                " ORDER BY COUNT(*) DESC").fetchall()),
        }
    finally:
        conn.close()


# Backwards-compatible alias used by earlier staging scripts.
stats = get_stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"levidia staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "resolve", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single page URL for parse/resolve")
    parser.add_argument("--probe", action="store_true",
                        help="probe each host bridge during crawl/resolve")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    db = Path(args.db)
    verbose = not args.quiet

    if args.command == "sync":
        sync_catalog(limit=args.limit, db_path=db, verbose=verbose,
                     max_pages=args.max_pages)
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
            print("[!] Page is not a watch page.", file=sys.stderr)
            return 1
        if args.command == "resolve":
            resolve_links(post, probe=True)
        print(json.dumps(post, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
