#!/usr/bin/env python3
"""
import_kuttymovies.py — staging importer for KuttyMovies (https://kuttymovies.wiki).

Measured on 2026-10-29 before this file existed:

* Domain rotation, probed in this order: `kuttymovies.cc` answers 403 on
  robots.txt and every sitemap path; `kuttymovies.com` serves a "Loading"
  doorway; `kuttymovies.download` is a WordPress landing page whose only
  sitemap is a two-URL `page-sitemap.xml` and whose REST API holds one
  `hello-world` post — a doorway, not the catalogue; `.today/.life/.cyou/
  .quest/.icu/.top` are NXDOMAIN; `kuttymovies.vip` redirects to
  `kutty-movie.com`, whose Rank Math index lists only `page-sitemap.xml`.
  `kuttymovies.wiki` is the live catalogue and the only surface this importer
  uses. No challenge was bypassed anywhere.
* Its Yoast `post-sitemap.xml` carries 906 `<loc>` entries with lastmods: the
  homepage plus 905 post permalinks. Every post slug ends in a resolution
  token (`-1080p-720p-480p`, or a subset); the homepage is the only URL the
  filter drops. The WordPress REST API reports `X-WP-Total: 905`, and the
  sitemap slug set and the REST slug set are identical (verified on both
  sides), so the queue is complete.
* `wp-json/wp/v2/posts?slug=<slug>` returns the post with `content.rendered`
  and `yoast_head_json.og_image` in one small JSON body, which is what this
  importer reads. The HTML page carries the same content plus a Yoast
  `@graph`, so nothing is lost by using REST.
* Post titles follow `Name (Year) [SxxEyy[Tzz]] Format Languages Type 1080p |
  720p | 480p`. All 905 titles carry a parenthesised year (including
  `WWE Monday Night Raw (26th October 2026)`); 444 are series-shaped
  (`Sxx`, "Web Series", "TV Show", "Reality Show"). The body repeats the
  metadata as labelled lines (`IMDB Ratings:`, `Directed:`, `Genres:`,
  `Languages:`, `Film Stars:`, `Storyline :`, `Release date:`), absent on some
  rows — measured presence across all 905: ratings/genres/languages 905,
  stars/size 826, director 761, storyline 690.
* The download section is a sequence of `<h3>` headings, each followed by one
  anchor per quality: `1080p [2.9GB]`. All 2,548 anchors on all 905 posts point
  at `linkshub.website/url.php?id=<7-hex>`; no other download host appears and
  no post lacks links. Series posts either repeat the title in the heading
  (`Download Bigg Boss (2026) S20E48 ... Links`) or use a bare range
  (`Download S01E01T05 Links`, meaning episodes 1 through 5).
* The linkshub URL is a 30-second countdown followed by a "click to prove you
  are not a robot" gate whose unlock target is assembled by page script. This
  importer stores that bridge as an **unverified** download source, does not
  follow it, does not run the page's script and does not attempt the gate; the
  bridge URL stays on the release as the durable route for a later resolver.

Each release therefore carries `season_number` / `episode_number` (range start)
and keeps the range end and heading text in `raw_meta`. Failures are recorded
per attempt in `sitemap_cache.raw_json.failures`, retried below a three-attempt
cap and parked at the cap with the reason kept. Stdlib only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html as html_mod
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SITE = "kuttymovies"
BASE_URL = "https://kuttymovies.wiki"
SITEMAP_URL = f"{BASE_URL}/post-sitemap.xml"
REST_URL = f"{BASE_URL}/wp-json/wp/v2/posts"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/kuttymovies.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITEMAP_TIMEOUT = 60
PAGE_TIMEOUT = 60
QUEUED_SCRAPE_STATES = (0, 2)
MAX_SCRAPE_ATTEMPTS = 3
FAILURE_LEDGER_LIMIT = 8
DEFAULT_SOURCE_STATUS = "unverified"
PLAYBACK_DOWNLOAD = "download"
SERVICE_BRIDGE = "linkshub"
STOP_REQUESTED = False
RATE_LIMIT_STATUS = 429
_RATE_LIMITED = threading.Event()

PENDING_SELECT = (
    "SELECT loc, lastmod, slug, raw_json, scraped, error_count FROM sitemap_cache "
    "WHERE scraped IN (?, ?) OR (scraped = -1 AND error_count < ?) ORDER BY loc;"
)

POST_COLUMNS = (
    "canonical_key", "title", "clean_title", "year", "media_type", "poster_url",
    "backdrop_url", "backdrop_urls", "imdb_id", "tmdb_id", "imdb_rating",
    "synopsis", "genres", "director", "cast_names", "duration", "release_date",
    "languages", "industry", "country", "seasons", "url", "slug",
    "is_18_plus", "is_animated", "source_site", "raw_meta",
)
RELEASE_COLUMNS = (
    "post_canonical_key", "label", "quality", "resolution", "size_bytes",
    "codec", "season_number", "episode_number", "audio_languages",
    "bridge_url", "origin_url", "raw_meta",
)
SOURCE_COLUMNS = (
    "release_id", "source_name", "service", "resource_id", "source_url",
    "final_url", "playback_type", "status", "is_temporary", "quality",
    "last_checked",
)
INTEGER_COLUMNS = {
    "year", "size_bytes", "season_number", "episode_number", "is_18_plus",
    "is_animated", "is_temporary", "last_checked",
}

ADULT_RE = re.compile(
    r"\b(?:xxx|hentai|porn\w*|erotic|nsfw|adult|onlyfans|brazzers|bangbros|milf"
    r"|hardcore|blowjobs?|threesome|orgasm|sex)\b"
    r"|step(?:sis|mom|dad|bro|sister|brother|daughter|son)"
    r"|f[-\s]?ck(?:ed|ing)?",
    re.I)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)
DETAIL_RE = re.compile(
    r"^https://kuttymovies\.wiki/(?P<slug>[A-Za-z0-9][A-Za-z0-9._\-]*?"
    r"-(?:480p|720p|1080p|2160p))/?$",
    re.I)
ANCHOR_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<text>.*?)</a>', re.S | re.I)
H3_RE = re.compile(r"<h3[^>]*>(?P<text>.*?)</h3>", re.S | re.I)
TOKEN_RE = re.compile(
    r'(?P<h3><h3[^>]*>.*?</h3>)'
    r'|(?P<a><a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<label>.*?)</a>)',
    re.S | re.I)
BRIDGE_RE = re.compile(
    r"^https://linkshub\.website/url\.php\?id=(?P<id>[0-9a-f]{5,10})$", re.I)
SIZE_RE = re.compile(r"(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>TB|GB|MB|KB)", re.I)
QUALITY_RE = re.compile(r"(?P<q>2160p|1080p|720p|480p|360p|4k)", re.I)
FORMAT_RE = re.compile(r"\b(MKV|MP4|AVI|HEVC|x264|x265|WEB[- ]?DL|HDRip|BluRay)\b",
                       re.I)
YEAR_PAREN_RE = re.compile(
    r"^(?P<name>.+?)\s*\((?:[^()]*?)(?P<year>(?:19|20)\d{2})[^()]*\)\s*(?P<rest>.*)$",
    re.S)
FORMAT_TOKEN_RE = re.compile(
    r"\s*\b(?:HQ|HDTS|HDTC|HDRip|HDCam|BluRay|WEB[- ]?DL|WEBRip|DVDRip|DVDScr"
    r"|PreDVD|CAMRip|CAM|1080p|720p|480p|360p|2160p|4K)\b",
    re.I)
SEASON_EP_RE = re.compile(
    r"\bS(?P<s>\d{1,2})(?:E(?P<e>\d{1,2})(?:T(?P<t>\d{1,2}))?)?\b", re.I)
TYPE_RE = re.compile(r"\b(?:web\s+series|series|tv\s+show|reality\s+show|show)\b",
                     re.I)
META_LINE_RE = re.compile(
    r"^\s*(?P<key>IMDB\s+Ratings|Directed|Release[sd]?\s+Date|Genres|Languages"
    r"|Film\s+Stars|Movie\s+Quality|File\s+Size|Storyline)\s*:\s*(?P<value>.*)$",
    re.I)
LANGUAGE_NAMES = ("Hindi", "English", "Tamil", "Telugu", "Malayalam", "Kannada",
                  "Punjabi", "Bengali", "Marathi", "Gujarati", "Korean",
                  "Japanese", "Urdu")


def _signal_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"\n[!] [{SITE}] signal {signum}: finishing the row in flight, then "
          f"stopping. Run again to resume.", flush=True)


def _install_signal_handlers() -> bool:
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _build_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


_SSL_CONTEXT = _build_ssl_context()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    _NoRedirectHandler(),
    urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
)
_TRANSPORT_ERROR = threading.local()


def transport_error() -> str:
    return getattr(_TRANSPORT_ERROR, "last", "")


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })


def http_get(url: str, timeout: int = PAGE_TIMEOUT, retries: int = 2,
             follow_redirects: bool = True):
    last_error = ""
    _TRANSPORT_ERROR.last = ""
    opener = (urllib.request.urlopen if follow_redirects else _NO_REDIRECT_OPENER.open)
    for attempt in range(retries + 1):
        if STOP_REQUESTED:
            return 0, url, "", {}
        try:
            kwargs = {"timeout": timeout}
            if follow_redirects:
                kwargs["context"] = _SSL_CONTEXT
            with opener(_request(url), **kwargs) as resp:
                body = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return (resp.status, resp.geturl(),
                        body.decode(charset, "replace"), dict(resp.headers))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read()
            except Exception:
                body = b""
            charset = (exc.headers.get_content_charset() if exc.headers else None) or "utf-8"
            return exc.code, url, body.decode(charset, "replace"), dict(exc.headers or {})
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    _TRANSPORT_ERROR.last = last_error
    print(f"[!] [{SITE}] {url} -> transport failure ({last_error})", flush=True)
    return 0, url, "", {}


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------


def parse_sitemap(xml: str) -> list[tuple[str, str | None]]:
    rows: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for block in re.findall(r"<url>(.*?)</url>", xml or "", re.S | re.I):
        loc_match = LOC_RE.search(block)
        if not loc_match:
            continue
        loc = html_mod.unescape(loc_match.group(1).strip())
        if not DETAIL_RE.match(loc) or loc in seen:
            continue
        mod_match = LASTMOD_RE.search(block)
        rows.append((loc, mod_match.group(1).strip() if mod_match else None))
        seen.add(loc)
    return rows


def slug_from(loc: str) -> str:
    match = DETAIL_RE.match((loc or "").strip())
    return match.group("slug") if match else ""


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    status, _final, xml, _headers = http_get(SITEMAP_URL, timeout=SITEMAP_TIMEOUT)
    if status != 200:
        print(f"[!] [{SITE}] sitemap -> HTTP {status}", flush=True)
        return 0
    rows = parse_sitemap(xml)
    if limit:
        rows = rows[:limit]
    if verbose:
        print(f"[*] [{SITE}] sitemap: {len(rows)} post URLs", flush=True)

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
            VALUES (?, ?, ?, 0, '{}', 0)
            ON CONFLICT(loc) DO UPDATE SET
                lastmod = excluded.lastmod, slug = excluded.slug;
            """,
            [(loc, mod, slug_from(loc)) for loc, mod in rows],
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def rest_url(slug: str) -> str:
    query = (
        f"slug={urllib.parse.quote(slug)}"
        "&_fields=id,slug,link,date,title,content,yoast_head_json,categories"
    )
    return f"{REST_URL}?{query}"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _text(fragment: str) -> str:
    """Tags to spaces, block closers to newlines, entities decoded."""
    text = re.sub(r"<br\s*/?>|</p>|</h[1-6]>|</div>|</li>", "\n", fragment or "",
                  flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines())


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", _text(fragment)).strip()


def split_title(raw: str | None) -> tuple[str, int | None, str]:
    """`Toxic (2026) V2 HQ HDTS ...` -> ("Toxic", 2026, "V2 HQ HDTS ...")."""
    text = re.sub(r"\s+", " ", html_mod.unescape(raw or "")).strip()
    match = YEAR_PAREN_RE.match(text)
    if match:
        name = match.group("name").strip()
        year = int(match.group("year"))
        rest = match.group("rest").strip()
    else:
        cut = FORMAT_TOKEN_RE.search(text)
        name = text[:cut.start()] if cut else text
        rest = text[cut.start():].strip() if cut else ""
        year = None
    name = re.sub(
        r"\s+(?:full\s+)?(?:movie|series|web\s+series|tv\s+show"
        r"|reality\s+show|show)\s*$", "", name, flags=re.I)
    return name.strip(" -|:,"), year, rest


def season_episode_of(text: str | None) -> tuple[int | None, int | None, int | None]:
    match = SEASON_EP_RE.search(text or "")
    if not match:
        return None, None, None
    season = int(match.group("s"))
    episode = int(match.group("e")) if match.group("e") else None
    end = int(match.group("t")) if match.group("t") else None
    return season, episode, end


def quality_of(text: str | None) -> str | None:
    match = QUALITY_RE.search(text or "")
    if not match:
        return None
    value = match.group("q").lower()
    return "2160p" if value == "4k" else value


def size_bytes(text: str | None) -> int | None:
    match = SIZE_RE.search(text or "")
    if not match:
        return None
    unit = match.group("unit").upper()
    factor = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit]
    return int(float(match.group("size")) * factor)


def format_of(*texts) -> str | None:
    for text in texts:
        match = FORMAT_RE.search(text or "")
        if match:
            return re.sub(r"\s+", "-", match.group(1).upper())
    return None


def meta_lines(content: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in _text(content).splitlines():
        match = META_LINE_RE.match(line)
        if not match:
            continue
        key = re.sub(r"\s+", " ", match.group("key")).lower()
        key = key.replace("released date", "release date")
        value = match.group("value").strip()
        if value and key not in found:
            found[key] = value
    return found


def languages_for(*texts) -> list[str]:
    found: list[str] = []
    for text in texts:
        for name in LANGUAGE_NAMES:
            if re.search(r"\b" + name + r"\b", text or "", re.I):
                if name not in found:
                    found.append(name)
    return found


def split_names(value: str | None) -> list[str]:
    return [p.strip() for p in re.split(r",|\s+and\s+", value or "") if p.strip()]


def screenshots(content: str, poster: str | None, limit: int = 10) -> list[str]:
    marker = re.search(r"\bScreenshot(?:s)?\b", content or "", re.I)
    section = content[marker.end():] if marker else ""
    cut = re.search(r"<h[23][^>]*>\s*Download", section, re.I)
    if cut:
        section = section[:cut.start()]
    urls: list[str] = []
    for match in re.finditer(r'<img[^>]+src="(?P<src>[^"]+)"', section, re.I):
        src = html_mod.unescape(match.group("src").strip())
        if not src.startswith("http") or src == poster or src in urls:
            continue
        urls.append(src)
        if len(urls) >= limit:
            break
    return urls


def poster_for(payload: dict, content: str) -> str | None:
    yoast = payload.get("yoast_head_json") or {}
    images = yoast.get("og_image") or []
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and image.get("url"):
                return str(image["url"])
    if isinstance(yoast.get("og_image"), str):
        return yoast["og_image"]
    match = re.search(r'<img[^>]+src="(?P<src>https?://[^"]+)"', content or "", re.I)
    return html_mod.unescape(match.group("src")) if match else None


def releases_from_content(content: str, title: str, title_season: int | None,
                          title_episode: int | None, loc: str,
                          languages: list[str]) -> list[dict]:
    """
    Walk the download section heading by heading; every linkshub anchor is one
    release. The heading decides the season/episode range, the anchor decides
    the quality and size.
    """
    releases: list[dict] = []
    seen: set[str] = set()
    heading = ""
    for match in TOKEN_RE.finditer(content or ""):
        if match.group("h3"):
            heading = _plain(match.group("h3"))
            continue
        href = html_mod.unescape((match.group("href") or "").strip())
        bridge = BRIDGE_RE.match(href)
        if not bridge or href in seen:
            continue
        seen.add(href)
        text = _plain(match.group("label"))
        quality = quality_of(text) or quality_of(heading)
        if quality is None:
            continue
        season, episode, end = season_episode_of(heading)
        if season is None:
            season, episode, end = title_season, title_episode, None
        descriptor = ""
        if season is not None and episode is not None:
            descriptor = f" S{season:02d}E{episode:02d}"
            if end is not None:
                descriptor += f"-E{end:02d}"
        elif season is not None:
            descriptor = f" S{season:02d}"
        label = f"{title}{descriptor} [{quality}]"
        releases.append({
            "label": label,
            "quality": quality,
            "resolution": quality,
            "size_bytes": size_bytes(text),
            "codec": format_of(text, heading),
            "season_number": season,
            "episode_number": episode,
            "audio_languages": json.dumps(languages, ensure_ascii=False)
            if languages else None,
            "bridge_url": href,
            "origin_url": loc,
            "raw_meta": {
                "heading": heading,
                "label_text": text,
                "episode_end": end,
                "bridge_host": "linkshub.website",
                "bridge_gate": ("30s countdown + robot check; not followed"),
            },
            "sources": [{
                "source_name": SITE,
                "service": SERVICE_BRIDGE,
                "resource_id": bridge.group("id"),
                "source_url": href,
                # Not followed: the unlock target is assembled by the gate's
                # page script and the gate is a human check.
                "final_url": None,
                "playback_type": PLAYBACK_DOWNLOAD,
                "status": DEFAULT_SOURCE_STATUS,
                "is_temporary": 0,
                "quality": quality,
                "last_checked": None,
                "label": text,
            }],
        })
    return releases


def build_record(loc: str, payload: dict) -> dict | None:
    slug = slug_from(loc) or str(payload.get("slug") or "")
    title_node = payload.get("title") or {}
    raw_name = title_node.get("rendered") if isinstance(title_node, dict) else title_node
    raw_name = _plain(str(raw_name or ""))
    title, year, rest = split_title(raw_name)
    if not slug or not title:
        return None

    content_node = payload.get("content") or {}
    content = content_node.get("rendered") if isinstance(content_node, dict) else content_node
    content = str(content or "")
    meta = meta_lines(content)

    title_season, title_episode, title_end = season_episode_of(rest)
    if title_season is None:
        title_season, title_episode, title_end = season_episode_of(slug)
    media_type = "series" if (title_season is not None
                              or TYPE_RE.search(raw_name)
                              or TYPE_RE.search(slug.replace("-", " "))) else "movie"
    if media_type != "series":
        title_season = title_episode = title_end = None

    languages = languages_for(meta.get("languages"), raw_name)
    genres = split_names(meta.get("genres"))
    cast = split_names(meta.get("film stars"))
    poster = poster_for(payload, content)
    shots = screenshots(content, poster)
    releases = releases_from_content(content, title, title_season, title_episode,
                                     loc, languages)
    rating_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10",
                             meta.get("imdb ratings") or "")
    story = meta.get("storyline")

    return {
        "canonical_key": slug,
        "title": title,
        "clean_title": title,
        "year": year,
        "media_type": media_type,
        "poster_url": poster,
        "backdrop_url": shots[0] if shots else None,
        "backdrop_urls": json.dumps(shots, ensure_ascii=False) if shots else None,
        "imdb_id": None,
        "tmdb_id": None,
        "imdb_rating": rating_match.group(1) if rating_match else None,
        "synopsis": story or None,
        "genres": json.dumps(genres, ensure_ascii=False) if genres else None,
        "director": meta.get("directed"),
        "cast_names": json.dumps(cast, ensure_ascii=False) if cast else None,
        "duration": None,
        "release_date": meta.get("release date"),
        "languages": json.dumps(languages, ensure_ascii=False) if languages else None,
        "industry": None,
        "country": None,
        "seasons": json.dumps(sorted({rel["season_number"]
                                      for rel in releases
                                      if rel["season_number"] is not None}))
        if media_type == "series" else None,
        "url": loc,
        "slug": slug,
        "is_18_plus": 1 if ADULT_RE.search(title + " " + " ".join(genres)) else 0,
        "is_animated": 1 if any(g.lower() in ("animation", "anime")
                                for g in genres) else 0,
        "releases": releases,
        "raw_meta": {
            "site": SITE,
            "sitemap_loc": loc,
            "rest_id": payload.get("id"),
            "wp_post_date": payload.get("date"),
            "raw_title": raw_name,
            "rest_title_suffix": rest or None,
            "episode_range_end": title_end,
            "link_source": ("post content anchors -> linkshub.website/url.php; "
                            "stored unverified, gate not attempted"),
        },
    }


# ---------------------------------------------------------------------------
# Staging database
# ---------------------------------------------------------------------------

_SCHEMA_TABLES = """
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
    source_site TEXT DEFAULT 'kuttymovies',
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
    raw_meta TEXT,
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
    playback_type TEXT DEFAULT 'download',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_kuttymovies_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_kuttymovies_posts_type ON posts(media_type);
CREATE INDEX IF NOT EXISTS idx_kuttymovies_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_kuttymovies_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_kuttymovies_releases_post ON releases(post_canonical_key);
"""


def _add_missing_columns(conn: sqlite3.Connection, table: str, wanted) -> None:
    have = {c[1] for c in conn.execute(f"PRAGMA table_info({table});").fetchall()}
    for col in wanted:
        if col in have:
            continue
        decl = "INTEGER" if col in INTEGER_COLUMNS else "TEXT"
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl};")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_TABLES)
    _add_missing_columns(conn, "posts", POST_COLUMNS + ("scraped_at",))
    _add_missing_columns(conn, "releases", RELEASE_COLUMNS)
    _add_missing_columns(conn, "sources", SOURCE_COLUMNS)
    conn.executescript(_SCHEMA_INDEXES)


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0}
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        for post in posts or ():
            if not post or not post.get("clean_title") or not post.get("canonical_key"):
                totals["skipped"] += 1
                continue
            releases = post.get("releases") or []
            row = {
                "canonical_key": post["canonical_key"],
                "title": post["title"],
                "clean_title": post["clean_title"],
                "year": post.get("year"),
                "media_type": post.get("media_type")
                              if post.get("media_type") in ("movie", "series")
                              else "movie",
                "poster_url": post.get("poster_url"),
                "backdrop_url": post.get("backdrop_url"),
                "backdrop_urls": post.get("backdrop_urls"),
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
                "industry": post.get("industry"),
                "country": post.get("country"),
                "seasons": post.get("seasons"),
                "url": post.get("url"),
                "slug": post.get("slug"),
                "is_18_plus": int(post.get("is_18_plus") or 0),
                "is_animated": int(post.get("is_animated") or 0),
                "source_site": SITE,
                "raw_meta": json.dumps(post.get("raw_meta") or {}, ensure_ascii=False),
            }
            placeholders = ", ".join(f":{c}" for c in POST_COLUMNS)
            updates = ", ".join(
                f"{c} = COALESCE(excluded.{c}, posts.{c})"
                for c in POST_COLUMNS
                if c not in ("canonical_key", "title", "clean_title", "url", "slug",
                             "source_site", "raw_meta", "media_type", "year",
                             "is_18_plus", "is_animated"))
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
                    year = COALESCE(excluded.year, posts.year),
                    is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus),
                    is_animated = MAX(posts.is_animated, excluded.is_animated),
                    {updates},
                    scraped_at = CURRENT_TIMESTAMP;
                """,
                row,
            )
            totals["posts_written"] += 1

            stale = [r["id"] for r in conn.execute(
                "SELECT id FROM releases WHERE post_canonical_key = ?;",
                (post["canonical_key"],)).fetchall()]
            if stale:
                conn.executemany("DELETE FROM sources WHERE release_id = ?;",
                                 [(i,) for i in stale])
                conn.executemany("DELETE FROM releases WHERE id = ?;",
                                 [(i,) for i in stale])

            for rel in releases:
                cur = conn.execute(
                    f"INSERT INTO releases ({', '.join(RELEASE_COLUMNS)})"
                    f" VALUES ({', '.join('?' * len(RELEASE_COLUMNS))});",
                    (post["canonical_key"], rel.get("label"), rel.get("quality"),
                     rel.get("resolution"), rel.get("size_bytes"), rel.get("codec"),
                     rel.get("season_number"), rel.get("episode_number"),
                     rel.get("audio_languages"), rel.get("bridge_url"),
                     rel.get("origin_url"),
                     json.dumps(rel.get("raw_meta") or {}, ensure_ascii=False)),
                )
                totals["releases_written"] += 1
                for src in rel.get("sources") or []:
                    conn.execute(
                        f"INSERT INTO sources ({', '.join(SOURCE_COLUMNS)})"
                        f" VALUES ({', '.join('?' * len(SOURCE_COLUMNS))});",
                        (cur.lastrowid, src.get("source_name"), src.get("service"),
                         src.get("resource_id"), src.get("source_url"),
                         src.get("final_url") or src.get("source_url"),
                         src.get("playback_type", PLAYBACK_DOWNLOAD),
                         src.get("status", DEFAULT_SOURCE_STATUS),
                         int(src.get("is_temporary") or 0),
                         src.get("quality") or rel.get("quality"),
                         src.get("last_checked")),
                    )
                    totals["sources_written"] += 1

            conn.execute(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                VALUES (?, NULL, ?, 1, ?, 0)
                ON CONFLICT(loc) DO UPDATE SET
                    scraped = 1, slug = excluded.slug,
                    raw_json = excluded.raw_json, error_count = 0;
                """,
                (post["url"], row["slug"],
                 json.dumps({"slug": row["slug"], "status": "ok",
                             "releases": len(releases)}, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Queue and crawl
# ---------------------------------------------------------------------------


def _failure(kind: str, http_status: int | None = None, final_url: str | None = None,
             detail: str = "", exception: str | None = None) -> dict:
    return {"kind": kind, "http_status": http_status, "final_url": final_url,
            "detail": detail, "exception": exception}


def _bump_error(db_path: Path, loc: str, failure: dict, park_now: bool = False) -> None:
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT raw_json, error_count, slug FROM sitemap_cache WHERE loc = ?;",
            (loc,)).fetchone()
        attempts = (row[1] if row and row[1] is not None else 0) + 1
        try:
            payload = json.loads(row[0]) if row and row[0] else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("slug", (row[2] if row else None) or slug_from(loc))
        history = payload.get("failures")
        history = history if isinstance(history, list) else []
        attempt = {
            "at": int(time.time()),
            "attempt": attempts,
            "kind": failure.get("kind") or "error",
            "http_status": failure.get("http_status"),
            "final_url": failure.get("final_url"),
            "detail": (failure.get("detail") or "")[:400],
        }
        if failure.get("exception"):
            attempt["exception"] = failure["exception"]
        payload["failures"] = (history + [attempt])[-FAILURE_LEDGER_LIMIT:]
        terminal = attempts >= MAX_SCRAPE_ATTEMPTS or park_now
        payload["status"] = "dead" if terminal else "retrying"
        payload["attempts"] = attempts
        payload["last_error"] = attempt["detail"] or attempt["kind"]
        conn.execute(
            "UPDATE sitemap_cache SET error_count = ?, scraped = ?, raw_json = ? "
            "WHERE loc = ?;",
            (attempts, -1 if terminal else 2,
             json.dumps(payload, ensure_ascii=False), loc))
        conn.commit()
    finally:
        conn.close()


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = 1, delay: float = 0.4, batch_size: int = 20,
                  verbose: bool = True) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        rows = conn.execute(
            PENDING_SELECT, (*QUEUED_SCRAPE_STATES, MAX_SCRAPE_ATTEMPTS)).fetchall()
    finally:
        conn.close()
    if limit:
        rows = rows[:limit]
    _RATE_LIMITED.clear()
    if verbose:
        print(f"[*] [{SITE}] {len(rows)} titles pending "
              f"(workers={workers}, delay={delay}s).", flush=True)

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "failed_rows": 0, "parked": 0, "failed": 0,
              "paused_rate_limit": False}
    if not rows:
        return totals

    def work(row):
        if STOP_REQUESTED or _RATE_LIMITED.is_set():
            return None
        time.sleep(delay)
        loc = row["loc"]
        slug = row["slug"] or slug_from(loc)
        url = rest_url(slug)
        status, final, body, headers = http_get(
            url, timeout=PAGE_TIMEOUT, retries=0, follow_redirects=False)
        if STOP_REQUESTED and status == 0:
            return None
        if status == RATE_LIMIT_STATUS:
            _RATE_LIMITED.set()
            return None, _failure("rate-limited", status, final,
                                  "http-429: site-wide rate limit, crawl paused")
        if 300 <= status < 400:
            location = headers.get("Location") or headers.get("location") or ""
            return None, _failure("redirect", status, location or final,
                                  f"http-{status} -> {location or final}")
        if status != 200:
            if status == 0:
                detail = transport_error() or "transport failure"
                return None, _failure("transport", 0, final, detail,
                                      exception=detail.split(":", 1)[0])
            return None, _failure(f"http-{status}", status, final, f"http-{status}")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return None, _failure("bad-json", status, final,
                                  "REST body is not JSON")
        if not isinstance(payload, list):
            return None, _failure("rest-error", status, final,
                                  str(payload)[:200])
        if not payload:
            return None, _failure("rest-empty", status, final,
                                  "slug not returned by the REST API")
        post = payload[0] if isinstance(payload[0], dict) else {}
        record = build_record(loc, post)
        if record is None:
            return None, _failure("no-content", status, final,
                                  "post has no usable title or content")
        if not record["releases"]:
            return None, _failure("no-links", status, final,
                                  "post content carries no linkshub anchor")
        return record, None

    batch: list[dict] = []
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_to_row = {pool.submit(work, r): r for r in rows}
        done = 0
        for fut in concurrent.futures.as_completed(future_to_row):
            queued = future_to_row[fut]
            done += 1
            try:
                outcome = fut.result()
            except Exception as exc:
                totals["failed"] += 1
                _bump_error(db_path, queued["loc"], _failure(
                    "exception", None, None, f"{type(exc).__name__}: {exc}",
                    exception=type(exc).__name__))
                continue
            if outcome is None:
                continue
            totals["pages"] += 1
            post, failure = outcome
            if post is None:
                totals["failed_rows"] += 1
                park_now = (failure or {}).get("kind") in (
                    "http-404", "http-410", "rest-empty")
                totals["parked"] += int(park_now)
                _bump_error(db_path, queued["loc"], failure or _failure("unknown"),
                            park_now=park_now)
                if _RATE_LIMITED.is_set():
                    totals["paused_rate_limit"] = True
                    break
                continue
            batch.append(post)
            if len(batch) >= batch_size:
                _flush(db_path, batch, totals)
                batch = []
            if verbose and (done == len(rows) or done % 25 == 0):
                print(f"    ... {done}/{len(rows)} pages, {totals['posts']} posts, "
                      f"{totals['sources']} sources, {time.time() - started:.0f}s",
                      flush=True)
            if STOP_REQUESTED:
                break
        _flush(db_path, batch, totals)

    if verbose:
        paused = " paused=rate-limited" if totals["paused_rate_limit"] else ""
        print(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"failed_rows={totals['failed_rows']} parked={totals['parked']} "
              f"failed={totals['failed']} "
              f"in {time.time() - started:.0f}s{paused}", flush=True)
    return totals


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    if not batch:
        return
    result = export_staging(db_path, batch)
    totals["posts"] += result["posts_written"]
    totals["releases"] += result["releases_written"]
    totals["sources"] += result["sources_written"]
    batch.clear()


# ---------------------------------------------------------------------------
# Sample / stats
# ---------------------------------------------------------------------------


def sample_page(url: str) -> dict | None:
    slug = slug_from(url) or url.rstrip("/").rsplit("/", 1)[-1]
    status, final, body, _headers = http_get(rest_url(slug))
    if status != 200:
        print(f"[!] [{SITE}] {slug} -> REST HTTP {status}")
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        print(f"[!] [{SITE}] {slug} -> REST body is not JSON")
        return None
    if not isinstance(payload, list) or not payload:
        print(f"[!] [{SITE}] {slug} -> no REST record")
        return None
    return build_record(url if DETAIL_RE.match(url) else
                        f"{BASE_URL}/{slug}/", payload[0])


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    db_path = Path(db_path)
    if not db_path.exists():
        return {"db": str(db_path), "exists": False}
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)

        def one(sql: str, *params):
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

        return {
            "db": str(db_path),
            "exists": True,
            "sitemap_rows": one("SELECT COUNT(*) FROM sitemap_cache"),
            "scraped": one("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1"),
            "retryable": one("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 2"),
            "dead": one("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1"),
            "pending": one("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0"),
            "posts": one("SELECT COUNT(*) FROM posts"),
            "movies": one("SELECT COUNT(*) FROM posts WHERE media_type = 'movie'"),
            "series": one("SELECT COUNT(*) FROM posts WHERE media_type = 'series'"),
            "releases": one("SELECT COUNT(*) FROM releases"),
            "sources": one("SELECT COUNT(*) FROM sources"),
            "unverified_sources": one(
                "SELECT COUNT(*) FROM sources WHERE status = 'unverified'"),
            "active_sources": one("SELECT COUNT(*) FROM sources WHERE status = 'active'"),
            "18_plus": one("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1"),
            "animated": one("SELECT COUNT(*) FROM posts WHERE is_animated = 1"),
        }
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"KuttyMovies staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="queue sitemap post URLs")
    sync.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync.add_argument("--limit", type=int)

    crawl = sub.add_parser("crawl", help="fetch pending posts and write staging rows")
    crawl.add_argument("--db", default=str(DEFAULT_DB_PATH))
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--workers", type=int, default=1)
    crawl.add_argument("--delay", type=float, default=0.4)

    sample = sub.add_parser("sample", help="parse one URL without writing")
    sample.add_argument("url")

    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _install_signal_handlers()
    if args.command == "sync":
        count = sync_catalog(limit=args.limit, db_path=args.db)
        print(f"[✓] [{SITE}] queued {count} post URLs -> {args.db}")
        return 0
    if args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=args.db, workers=args.workers,
                      delay=args.delay)
        return 0
    if args.command == "sample":
        record = sample_page(args.url)
        if record is None:
            return 1
        print(json.dumps({k: v for k, v in record.items() if k != "releases"},
                         indent=2, ensure_ascii=False))
        print(f"releases={len(record['releases'])} "
              f"sources={sum(len(r['sources']) for r in record['releases'])}")
        for rel in record["releases"]:
            print("  ", rel["label"], rel["quality"], rel["size_bytes"],
                  rel["season_number"], rel["episode_number"],
                  rel["raw_meta"].get("episode_end"))
        return 0
    if args.command == "stats":
        print(json.dumps(stats(args.db), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
