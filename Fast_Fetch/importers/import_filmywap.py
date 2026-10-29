#!/usr/bin/env python3
"""
import_filmywap.py — staging importer for the Filmywap family (https://filmywap.site).

Measured on 2026-10-29, domain by domain, before this file was written:

* `filmywap.com` redirects to a lander, `filmywap.biz` is a parked page, and
  `filmywap.wiki` / `filmywap.win` / `filmywap.online` all redirect to
  `wapfilmy.in`, whose `/sitemap.xml` is an `<iframe>` pointed at
  `airtel.in/court-orders` — a court-order interstitial, not a catalogue. This
  importer does not touch it and does not try to route around it.
* `filmywap.cloud`, `filmywap.run` and `filmywap.sbs` redirect to
  `filmstopia.com`, a different brand (FilmyFly). They are not this family.
* `filmywap.site` is the live Filmywap surface: a 1,584-URL `sitemap.xml` of
  which 1,522 are `/movie/<slug>-<id>` detail pages, plus listing/genre/year
  pages that are skipped here.

What a detail page publishes (server-rendered, no browser needed):

* one schema.org `Movie` or `TVSeries` JSON-LD block — name, description,
  image, datePublished, genre[], aggregateRating.ratingValue, actor[],
  countryOfOrigin, inLanguage. There is no duration and no imdb id in it.
* a public `/api/stream?slug=<slug>` JSON endpoint: `subjectId`, `isSeries`,
  `seasons[{se,episodes[]}]`, `allowDownload`, `vipLocked`, and `sources[]`
  with `resolution`, `size`, `duration`, `codec` and an MP4 `url`.

Series are episode-addressable only: the first API call returns every season's
episode numbers plus the sources of `se=1&ep=1`; each further episode needs its
own `&se=<n>&ep=<m>` call. Movies are one API call.

**The links expire, and this file says so.** Every MP4 URL carries
`?sign=<hex>&t=<epoch>`; the `t` value is a short-lived expiry, so each source
row is written `is_temporary = 1`, `status = 'unverified'`, `last_checked` NULL,
and its release keeps the durable `/api/stream?slug=…&se=…&ep=…` URL in
`bridge_url` for re-resolution. Nothing here mints a token of its own, and no
`active` status is claimed for a probe that did not happen.

Every failure is recorded per attempt in `sitemap_cache.raw_json.failures`
(kind, http status, final URL, detail), retryable below three attempts, parked
at `scraped = -1, status = 'dead'` with the reason kept at the cap. Stdlib only.
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

SITE = "filmywap"
BASE_URL = "https://filmywap.site"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/filmywap.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITEMAP_TIMEOUT = 45
PAGE_TIMEOUT = 60
# A stalled /api/stream costs a 60 s socket timeout per episode; stop walking
# the episode list once this many in a row fail and record the abort.
EPISODE_FAILURE_STREAK = 3
QUEUED_SCRAPE_STATES = (0, 2)
MAX_SCRAPE_ATTEMPTS = 3
FAILURE_LEDGER_LIMIT = 8
LEGAL_MEDIA_TYPES = ("movie", "series")
DEFAULT_SOURCE_STATUS = "unverified"
PLAYBACK_DOWNLOAD = "download"
SERVICE_PREFIX = "filmywap-mp4"
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
LANG_TAG_RE = re.compile(r"\[([^\]]+)\]")
KNOWN_LANGUAGES = {
    "hindi", "english", "tamil", "telugu", "malayalam", "kannada", "punjabi",
    "bengali", "marathi", "gujarati", "urdu", "bhojpuri", "korean", "japanese",
    "spanish", "french", "german", "dual audio", "multi audio",
}
LANGUAGE_CODES = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "ml": "Malayalam", "kn": "Kannada", "pa": "Punjabi", "bn": "Bengali",
    "mr": "Marathi", "gu": "Gujarati", "ur": "Urdu", "ko": "Korean",
    "ja": "Japanese", "es": "Spanish", "fr": "French", "de": "German",
}
MOVIE_URL_RE = re.compile(
    r"^https://filmywap\.site/movie/(?P<slug>[A-Za-z0-9][A-Za-z0-9._\-]*)$", re.I)
LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)


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
    """Certificate and hostname checks stay on; filmywap.site serves a valid chain."""
    return ssl.create_default_context()


_SSL_CONTEXT = _build_ssl_context()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # surface the 3xx instead of following it


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    _NoRedirectHandler(),
    urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
)
_TRANSPORT_ERROR = threading.local()


def transport_error() -> str:
    return getattr(_TRANSPORT_ERROR, "last", "")


def _open(request, timeout: int = PAGE_TIMEOUT):
    return urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT)


def _open_no_redirect(request, timeout: int = PAGE_TIMEOUT):
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


def _request(url: str, extra_headers: dict | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if extra_headers:
        headers.update(extra_headers)
    return urllib.request.Request(url, headers=headers)


def http_get(url: str, timeout: int = PAGE_TIMEOUT, retries: int = 2,
             follow_redirects: bool = True):
    """GET -> (status, final_url, text, headers). Transport failure -> status 0."""
    last_error = ""
    _TRANSPORT_ERROR.last = ""
    opener = _open if follow_redirects else _open_no_redirect
    for attempt in range(retries + 1):
        if STOP_REQUESTED:
            return 0, url, "", {}
        try:
            with opener(_request(url), timeout=timeout) as resp:
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
        except Exception as exc:  # URLError, timeout, reset
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
    """Returns (loc, lastmod) pairs, in document order, for /movie/ URLs only."""
    rows: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for block in re.findall(r"<url>(.*?)</url>", xml or "", re.S | re.I):
        loc_match = LOC_RE.search(block)
        if not loc_match:
            continue
        loc = html_mod.unescape(loc_match.group(1).strip())
        if not MOVIE_URL_RE.match(loc) or loc in seen:
            continue
        mod_match = LASTMOD_RE.search(block)
        rows.append((loc, mod_match.group(1).strip() if mod_match else None))
        seen.add(loc)
    return rows


def slug_from(loc: str) -> str:
    match = MOVIE_URL_RE.match((loc or "").strip())
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
        print(f"[*] [{SITE}] sitemap: {len(rows)} movie URLs", flush=True)

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


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_jsonld(html: str) -> dict | None:
    """The schema.org Movie/TVSeries block; breadcrumb lists are ignored."""
    for raw in LD_RE.findall(html or ""):
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            for node in _as_list(item.get("@graph")) or [item]:
                if not isinstance(node, dict):
                    continue
                if str(node.get("@type") or "").lower() in (
                        "movie", "tvseries", "tvshow"):
                    return node
    return None


def _image_url(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("url")
    if isinstance(value, str) and value.startswith("http"):
        return value
    return None


def _rating(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("ratingValue")
    if value in (None, ""):
        return None
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return str(value)


def _country(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    return str(value) if value else None


def languages_for(title: str | None, in_language) -> list[str]:
    """Bracketed tags the title publishes plus the schema language, never invented."""
    found: list[str] = []
    for tag in LANG_TAG_RE.findall(title or ""):
        for piece in re.split(r"[,/&+]|\band\b", tag):
            word = re.sub(r"\s+", " ", piece).strip()
            if word and word.lower() in KNOWN_LANGUAGES:
                found.append(word.title() if word.islower() else word)
    for code in _as_list(in_language):
        name = LANGUAGE_CODES.get(str(code).strip().lower())
        if name:
            found.append(name)
    seen: set[str] = set()
    deduped = []
    for name in found:
        if name.lower() not in seen:
            seen.add(name.lower())
            deduped.append(name)
    return deduped


def year_of(value: str | None) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", value or "")
    return int(match.group(0)) if match else None


def duration_text(seconds: int | None) -> str | None:
    if not seconds or seconds <= 0:
        return None
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def stream_api_url(slug: str, season: int | None = None,
                   episode: int | None = None) -> str:
    url = f"{BASE_URL}/api/stream?slug={urllib.parse.quote(slug)}"
    if season is not None and episode is not None:
        url += f"&se={int(season)}&ep={int(episode)}"
    return url


def fetch_stream(slug: str, season: int | None = None,
                 episode: int | None = None,
                 retries: int = 1) -> tuple[dict | None, str]:
    """Returns (payload, failure_kind). The endpoint is public JSON; no tokens."""
    status, final, text, _headers = http_get(
        stream_api_url(slug, season, episode), timeout=PAGE_TIMEOUT, retries=retries)
    if status != 200:
        return None, f"api-http-{status}" if status else "api-transport"
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, "api-no-json"
    if not isinstance(payload, dict):
        return None, "api-shape"
    return payload, ""


def _sources(stream: dict) -> list[dict]:
    return [s for s in (stream.get("sources") or []) if isinstance(s, dict)
            and (s.get("url") or s.get("directUrl"))]


def _expiry(url: str | None) -> int | None:
    match = re.search(r"[?&]t=(\d+)", url or "")
    return int(match.group(1)) if match else None


def releases_from_stream(stream: dict, title: str, origin_url: str,
                         season: int | None = None,
                         episode: int | None = None) -> list[dict]:
    """One release per published resolution, each carrying its signed MP4 source."""
    releases = []
    bridge = stream_api_url(stream.get("detailPath") or "",
                            season, episode) if stream.get("detailPath") else None
    for src in _sources(stream):
        resolution = src.get("resolution")
        quality = f"{int(resolution)}p" if resolution else None
        label = title
        if season is not None and episode is not None:
            label += f" S{int(season):02d}E{int(episode):02d}"
        if quality:
            label += f" [{quality}]"
        source_url = src.get("url") or src.get("directUrl")
        host = urllib.parse.urlsplit(source_url or "").hostname or ""
        releases.append({
            "label": label,
            "quality": quality,
            "resolution": quality,
            "size_bytes": src.get("size"),
            "codec": src.get("codec"),
            "season_number": season,
            "episode_number": episode,
            "bridge_url": bridge,
            "origin_url": origin_url,
            "raw_languages": None,
            "raw_meta": {
                "duration_seconds": src.get("duration"),
                "format": src.get("format"),
                "signed_expires_at": _expiry(source_url),
                "api_url": bridge,
            },
            "sources": [{
                "source_name": SITE,
                "service": host or SERVICE_PREFIX,
                "resource_id": str(src.get("id") or "") or None,
                "source_url": source_url,
                "final_url": source_url,
                "playback_type": PLAYBACK_DOWNLOAD,
                "status": DEFAULT_SOURCE_STATUS,
                "is_temporary": 1 if _expiry(source_url) else 0,
                "quality": quality,
                "last_checked": None,
            }],
        })
    return releases


def build_record(loc: str, html: str, stream: dict,
                 episode_streams: dict[tuple[int, int], dict] | None = None) -> dict | None:
    """
    Page JSON-LD + stream API -> one staging record.

    A page that lost its JSON-LD returns None (the caller parks it); a page with
    JSON-LD but no sources still becomes a catalog row, flagged `has_resource`.
    """
    ld = parse_jsonld(html)
    if ld is None:
        return None
    slug = slug_from(loc)
    if not slug:
        return None
    title = re.sub(r"\s+", " ", str(ld.get("name") or "")).strip()
    if not title:
        return None
    ld_type = str(ld.get("@type") or "").lower()
    media_type = "series" if "series" in ld_type or "show" in ld_type else "movie"
    genres = [str(g) for g in _as_list(ld.get("genre")) if g]
    poster = _image_url(ld.get("image"))
    release_date = ld.get("datePublished") or ld.get("startDate")
    languages = languages_for(title, ld.get("inLanguage"))

    episode_streams = episode_streams or {}
    releases: list[dict] = []
    episode_failures: list[str] = []
    seasons: list[int] = []
    if media_type == "series" and (stream.get("isSeries") or stream.get("seasons")):
        for season_row in stream.get("seasons") or []:
            season = int(season_row.get("se") or 0)
            if season:
                seasons.append(season)
            for ep in season_row.get("episodes") or []:
                episode = int(ep)
                key = (season, episode)
                payload = episode_streams.get(key)
                if payload is None:
                    if season == 1 and episode == 1:
                        payload = stream
                    else:
                        episode_failures.append(f"se{season}ep{episode}:missing")
                        continue
                releases.extend(releases_from_stream(
                    payload, title, loc, season, episode))
    else:
        releases.extend(releases_from_stream(stream, title, loc))

    for rel in releases:
        rel["audio_languages"] = (json.dumps(languages, ensure_ascii=False)
                                  if languages else None)

    durations = [r["raw_meta"].get("duration_seconds") for r in releases
                 if r["raw_meta"].get("duration_seconds")]
    duration = duration_text(max(durations)) if durations else None

    adult_text = " ".join([title] + genres)
    return {
        "canonical_key": slug,
        "title": title,
        "clean_title": title,
        "year": year_of(str(release_date or "")) or year_of(title),
        "media_type": media_type,
        "poster_url": poster,
        "backdrop_url": None,
        "backdrop_urls": None,
        "imdb_id": None,
        "tmdb_id": None,
        "imdb_rating": _rating(ld.get("aggregateRating")),
        "synopsis": (str(ld.get("description") or "").strip() or None),
        "genres": json.dumps(genres, ensure_ascii=False) if genres else None,
        "director": None,
        "cast_names": json.dumps(
            [a.get("name") for a in _as_list(ld.get("actor")) if isinstance(a, dict)]
            or [a for a in _as_list(ld.get("actor")) if isinstance(a, str)],
            ensure_ascii=False) or None,
        "duration": duration,
        "release_date": str(release_date) if release_date else None,
        "languages": json.dumps(languages, ensure_ascii=False) if languages else None,
        "industry": None,
        "country": _country(ld.get("countryOfOrigin")),
        "seasons": json.dumps(seasons) if seasons else None,
        "url": loc,
        "slug": slug,
        "is_18_plus": 1 if ADULT_RE.search(adult_text) else 0,
        "is_animated": 1 if any(g.lower() in ("animation", "anime") for g in genres) else 0,
        "releases": releases,
        "raw_meta": {
            "site": SITE,
            "sitemap_loc": loc,
            "ld_type": ld.get("@type"),
            "subject_id": stream.get("subjectId"),
            "stream_api": stream_api_url(slug),
            "has_resource": bool(stream.get("hasResource")),
            "is_series": bool(stream.get("isSeries")),
            "allow_download": stream.get("allowDownload"),
            "vip_locked": stream.get("vipLocked"),
            "limited": stream.get("limited"),
            "free_num": stream.get("freeNum"),
            "captions": stream.get("captions") or [],
            "episodes_without_stream": episode_failures,
            "link_source": ("public /api/stream?slug= JSON; MP4 URLs are signed "
                            "and short-lived, so sources are stored unverified and "
                            "temporary; bridge_url re-resolves them"),
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
    source_site TEXT DEFAULT 'filmywap',
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
CREATE INDEX IF NOT EXISTS idx_filmywap_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_filmywap_posts_type ON posts(media_type);
CREATE INDEX IF NOT EXISTS idx_filmywap_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_filmywap_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_filmywap_releases_post ON releases(post_canonical_key);
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
    """Writes parsed records into this site's staging DB and nothing else."""
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
                              if post.get("media_type") in LEGAL_MEDIA_TYPES
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
                             "subject_id": (post.get("raw_meta") or {}).get("subject_id")},
                            ensure_ascii=False)),
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
                  max_episodes: int | None = None, verbose: bool = True) -> dict:
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
              "failed_rows": 0, "parked": 0, "failed": 0, "episode_gaps": 0,
              "paused_rate_limit": False}
    if not rows:
        return totals

    def work(row):
        if STOP_REQUESTED or _RATE_LIMITED.is_set():
            return None
        time.sleep(delay)
        loc = row["loc"]
        status, final, page, headers = http_get(
            loc, timeout=PAGE_TIMEOUT, retries=0, follow_redirects=False)
        if STOP_REQUESTED and status == 0:
            return None  # aborted by the stop signal; do not spend an attempt
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
        if parse_jsonld(page) is None:
            return None, _failure("no-jsonld", status, final,
                                  "page has no schema.org Movie/TVSeries block")
        slug = slug_from(loc)
        stream, kind = fetch_stream(slug)
        if stream is None:
            return None, _failure(kind, status, final,
                                  f"stream API failed: {kind}")
        episode_streams: dict[tuple[int, int], dict] = {}
        gaps = 0
        streak = 0
        aborted = ""
        if stream.get("isSeries") or stream.get("seasons"):
            planned = 0
            for season_row in stream.get("seasons") or []:
                if aborted or STOP_REQUESTED:
                    break
                season = int(season_row.get("se") or 0)
                for ep in season_row.get("episodes") or []:
                    episode = int(ep)
                    if season == 1 and episode == 1:
                        continue
                    if max_episodes is not None and planned >= max_episodes:
                        break
                    planned += 1
                    if STOP_REQUESTED:
                        break
                    time.sleep(delay)
                    payload, ep_kind = fetch_stream(slug, season, episode, retries=0)
                    if payload is None:
                        gaps += 1
                        streak += 1
                        if streak >= EPISODE_FAILURE_STREAK:
                            aborted = ep_kind or "api-transport"
                            break
                    else:
                        streak = 0
                        episode_streams[(season, episode)] = payload
        record = build_record(loc, page, stream, episode_streams)
        if record is None:
            return None, _failure("no-record", status, final, "record build failed")
        if gaps:
            record["raw_meta"]["episode_gaps"] = gaps
        if aborted:
            record["raw_meta"]["episode_aborted"] = aborted
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
                park_now = (failure or {}).get("kind") in ("http-404", "http-410")
                totals["parked"] += int(park_now)
                _bump_error(db_path, queued["loc"], failure or _failure("unknown"),
                            park_now=park_now)
                if _RATE_LIMITED.is_set():
                    totals["paused_rate_limit"] = True
                    break
                continue
            totals["episode_gaps"] += int((post.get("raw_meta") or {}).get(
                "episode_gaps") or 0)
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
              f"failed={totals['failed']} episode_gaps={totals['episode_gaps']} "
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


def sample_page(url: str, max_episodes: int = 6) -> dict | None:
    status, final, page, _headers = http_get(url)
    if status != 200:
        print(f"[!] [{SITE}] {url} -> HTTP {status}")
        return None
    slug = slug_from(final) or slug_from(url)
    stream, kind = fetch_stream(slug)
    if stream is None:
        print(f"[!] [{SITE}] stream API -> {kind}")
        return None
    episode_streams: dict[tuple[int, int], dict] = {}
    planned = 0
    for season_row in stream.get("seasons") or []:
        season = int(season_row.get("se") or 0)
        if planned >= max_episodes:
            break
        for ep in season_row.get("episodes") or []:
            episode = int(ep)
            if (season, episode) == (1, 1):
                continue
            if planned >= max_episodes:
                break
            planned += 1
            payload, _kind = fetch_stream(slug, season, episode)
            if payload is not None:
                episode_streams[(season, episode)] = payload
    record = build_record(url, page, stream, episode_streams)
    if record is None:
        print(f"[!] [{SITE}] {url} -> no JSON-LD")
        return None
    return record


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
            "temporary_sources": one(
                "SELECT COUNT(*) FROM sources WHERE is_temporary = 1"),
            "active_sources": one("SELECT COUNT(*) FROM sources WHERE status = 'active'"),
            "18_plus": one("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1"),
            "animated": one("SELECT COUNT(*) FROM posts WHERE is_animated = 1"),
        }
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Filmywap staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="queue sitemap movie URLs")
    sync.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync.add_argument("--limit", type=int)

    crawl = sub.add_parser("crawl", help="fetch pending pages and write staging rows")
    crawl.add_argument("--db", default=str(DEFAULT_DB_PATH))
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--workers", type=int, default=1)
    crawl.add_argument("--delay", type=float, default=0.4)
    crawl.add_argument("--max-episodes", type=int, default=None,
                       help="per-series episode cap for a bounded probe")

    sample = sub.add_parser("sample", help="parse one URL without writing")
    sample.add_argument("url")
    sample.add_argument("--max-episodes", type=int, default=6,
                        help="episode calls to make for a series sample")

    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _install_signal_handlers()
    if args.command == "sync":
        count = sync_catalog(limit=args.limit, db_path=args.db)
        print(f"[✓] [{SITE}] queued {count} movie URLs -> {args.db}")
        return 0
    if args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=args.db, workers=args.workers,
                      delay=args.delay, max_episodes=args.max_episodes)
        return 0
    if args.command == "sample":
        record = sample_page(args.url, max_episodes=args.max_episodes)
        if record is None:
            return 1
        print(json.dumps({
            k: v for k, v in record.items() if k != "releases"
        }, indent=2, ensure_ascii=False))
        print(f"releases={len(record['releases'])} "
              f"sources={sum(len(r['sources']) for r in record['releases'])}")
        for rel in record["releases"][:6]:
            print("  ", rel["label"], rel["quality"], rel["size_bytes"],
                  rel["sources"][0]["source_url"][:80])
        return 0
    if args.command == "stats":
        print(json.dumps(stats(args.db), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
