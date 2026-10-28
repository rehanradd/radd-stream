#!/usr/bin/env python3
"""
import_filmyhit.py — staging importer for FilmyHit (https://filmyhit.mobile).

Measured on 2026-10-29 before this file existed:

* `filmyhit.link` is NXDOMAIN; `filmyhit.com` and `filmyhit.mobile` both serve
  the same catalogue (robots.txt on .com points at .mobile); `filmyhit.best` is
  behind a Cloudflare 403 on every sitemap path. This importer uses
  `filmyhit.mobile` and never attempts a challenge.
* `/sitemap.xml` is one 20,997-URL `urlset` with 20,265 lastmods. 16,913 are
  detail pages ending in `-free-download` (16,624 plain, 289 `-<id>-` numbered);
  the rest are `?page=N` pagination (2,250), `/cat/<id>` categories (1,777) and
  static pages. Only detail pages are queued.
* A detail page publishes a schema.org `Movie` / `TVSeries` node inside
  `@graph`: name, description, image[], dateCreated, datePublished, ISO
  `duration`, `inLanguage`, `sameAs` (the IMDb URL), genre[] and actor[].
* Its download section lists one anchor per file:
  `480p 522.26 MB · MKV` -> `/all-format-downloads-<slug>-480-full-hd-<id>`.
  That bridge page then lists six `/d/<movie>/<file>/server-<n>` endpoints.
* Those endpoints are a mixed bag and this importer does not pretend otherwise:
  sampled on 2026-10-29, `server-19` and `server-20` answered Cloudflare 502,
  while `server-24` redirected to a third-party host serving a
  "Verify to Continue" interstitial. The endpoints are stored as **unverified**
  download sources with no follow and no challenge bypass; `final_url` stays
  unresolved, and the bridge page keeps the durable route for a later resolver.

Series are season packs on this site (`Tyson (2026) S01 ...`), so a series row
carries `season_number` and no invented episode split.

Failures are recorded per attempt in `sitemap_cache.raw_json.failures`, retried
below a three-attempt cap and parked at the cap with the reason kept. Stdlib only.
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

SITE = "filmyhit"
BASE_URL = "https://filmyhit.mobile"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/filmyhit.db")
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
SERVICE_SERVER = "filmyhit-server"
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
LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)
DETAIL_RE = re.compile(
    r"^https://filmyhit\.mobile/(?P<slug>[A-Za-z0-9][A-Za-z0-9._\-]*-free-download)$",
    re.I)
BRIDGE_RE = re.compile(
    r"^/all-format-downloads-[A-Za-z0-9._\-]+$", re.I)
SERVER_RE = re.compile(r"^/d/[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+/server-\d+$", re.I)
ANCHOR_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<text>.*?)</a>', re.S | re.I)
SIZE_RE = re.compile(r"(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>TB|GB|MB|KB)", re.I)
QUALITY_RE = re.compile(r"(?P<q>2160p|1080p|720p|480p|360p|4k)", re.I)
FORMAT_RE = re.compile(r"\b(MKV|MP4|AVI|HEVC|x264|x265)\b", re.I)
SEASON_RE = re.compile(r"\bS(?:eason\s*)?(\d{1,2})\b", re.I)
ISO_DURATION_RE = re.compile(
    r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$", re.I)


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
        "User-Agent": USER_AGENT, "Accept": "*/*",
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
        print(f"[*] [{SITE}] sitemap: {len(rows)} detail URLs", flush=True)

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
                if isinstance(node, dict) and str(node.get("@type") or "").lower() in (
                        "movie", "tvseries", "tvshow"):
                    return node
    return None


def clean_title(name: str | None) -> str:
    """Drops the site's trailing `Movie`/`Series` label, keeps dub/season tags."""
    text = re.sub(r"\s+", " ", urllib.parse.unquote(name or "")).strip()
    text = re.sub(r"\s+(?:full\s+)?(?:movie|film|series|web\s+series)\s*$", "",
                  text, flags=re.I)
    return text.strip(" -|:,")


def year_of(*values) -> int | None:
    for value in values:
        match = re.search(r"(?:19|20)\d{2}", str(value or ""))
        if match:
            return int(match.group(0))
    return None


def iso_duration_text(value: str | None) -> str | None:
    match = ISO_DURATION_RE.match((value or "").strip())
    if not match:
        return None
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    if not (hours or minutes or seconds):
        return None
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def size_bytes(text: str | None) -> int | None:
    match = SIZE_RE.search(text or "")
    if not match:
        return None
    unit = match.group("unit").upper()
    factor = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit]
    return int(float(match.group("size")) * factor)


def quality_of(text: str | None) -> str | None:
    match = QUALITY_RE.search(text or "")
    if not match:
        return None
    value = match.group("q").lower()
    return "2160p" if value == "4k" else value


def season_of(*texts) -> int | None:
    for text in texts:
        match = SEASON_RE.search(text or "")
        if match:
            return int(match.group(1))
    return None


def languages_for(in_language) -> list[str]:
    found = []
    for value in _as_list(in_language):
        text = str(value or "")
        for name in ("Hindi", "English", "Tamil", "Telugu", "Punjabi", "Marathi",
                     "Gujarati", "Malayalam", "Kannada", "Bengali", "Urdu"):
            if re.search(r"\b" + name + r"\b", text, re.I):
                found.append(name)
        if not found and text.strip():
            found.append(text.strip())
    seen: set[str] = set()
    deduped = []
    for name in found:
        if name.lower() not in seen:
            seen.add(name.lower())
            deduped.append(name)
    return deduped


def releases_from_page(html: str, loc: str, title: str,
                       season: int | None) -> list[dict]:
    """
    One release per `/all-format-downloads-...` anchor. The anchor label carries
    the quality, size and container; the URL is the file's own id.
    """
    releases: dict[str, dict] = {}
    for match in ANCHOR_RE.finditer(html or ""):
        href = html_mod.unescape(match.group("href").strip())
        if not BRIDGE_RE.match(href):
            continue
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group("text"))).strip()
        quality = quality_of(text) or quality_of(href)
        entry = releases.get(href)
        if entry is None:
            entry = {"href": href, "quality": quality, "size": size_bytes(text),
                     "format": (FORMAT_RE.search(text).group(1).upper()
                                if FORMAT_RE.search(text) else None),
                     "label_text": text}
            releases[href] = entry
        else:
            entry["quality"] = entry["quality"] or quality
            entry["size"] = entry["size"] or size_bytes(text)
            entry["format"] = entry["format"] or (
                FORMAT_RE.search(text).group(1).upper() if FORMAT_RE.search(text)
                else None)
            entry["label_text"] = entry["label_text"] or text

    out = []
    for entry in releases.values():
        label = title
        if season is not None and not re.search(
                r"\bS(?:eason\s*)?\d{1,2}\b", title, re.I):
            label += f" S{int(season):02d}"
        if entry["quality"]:
            label += f" [{entry['quality']}]"
        out.append({
            "label": label,
            "quality": entry["quality"],
            "resolution": entry["quality"],
            "size_bytes": entry["size"],
            "codec": entry["format"],
            "season_number": season,
            "episode_number": None,
            "bridge_url": urllib.parse.urljoin(BASE_URL, entry["href"]),
            "origin_url": loc,
            "audio_languages": None,
            "raw_meta": {"bridge_path": entry["href"], "label_text": entry["label_text"]},
            "sources": [],
        })
    return out


def server_sources(bridge_html: str, quality: str | None) -> list[dict]:
    """The `/d/.../server-N` endpoints the bridge page publishes, unfollowed."""
    found: dict[str, dict] = {}
    for match in ANCHOR_RE.finditer(bridge_html or ""):
        href = html_mod.unescape(match.group("href").strip())
        if not SERVER_RE.match(href):
            continue
        if href in found:
            continue
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group("text"))).strip()
        found[href] = {
            "source_name": SITE,
            "service": SERVICE_SERVER,
            "resource_id": href.rstrip("/").rsplit("/", 1)[-1],
            "source_url": urllib.parse.urljoin(BASE_URL, href),
            # Not followed: the redirect target is a third-party host, and one
            # sampled endpoint answered a JS "Verify to Continue" interstitial.
            "final_url": None,
            "playback_type": PLAYBACK_DOWNLOAD,
            "status": DEFAULT_SOURCE_STATUS,
            "is_temporary": 0,
            "quality": quality,
            "last_checked": None,
            "label": text,
        }
    return list(found.values())


def build_record(loc: str, html: str) -> dict | None:
    ld = parse_jsonld(html)
    if ld is None:
        return None
    slug = slug_from(loc)
    if not slug:
        return None
    raw_name = str(ld.get("name") or "").strip()
    title = clean_title(raw_name)
    if not title:
        return None
    lowered = (title + " " + slug).lower()
    media_type = "series" if (str(ld.get("@type")).lower() != "movie"
                              or re.search(r"\bseries\b|\bs\d{1,2}\b", lowered)
                              or re.search(r"-s\d{2}-|-season-\d", slug, re.I)) else "movie"
    season = season_of(title, slug) if media_type == "series" else None
    genres = [str(g) for g in _as_list(ld.get("genre")) if g]
    imdb_id = None
    same_as = ld.get("sameAs")
    for value in _as_list(same_as):
        match = re.search(r"imdb\.com/title/(tt\d+)", str(value))
        if match:
            imdb_id = match.group(1)
            break
    images = [i for i in _as_list(ld.get("image")) if isinstance(i, str)]
    languages = languages_for(ld.get("inLanguage"))
    releases = releases_from_page(html, loc, title, season)

    return {
        "canonical_key": slug,
        "title": title,
        "clean_title": title,
        "year": year_of(ld.get("dateCreated"), ld.get("datePublished"), title),
        "media_type": media_type,
        "poster_url": images[0] if images else None,
        "backdrop_url": None,
        "backdrop_urls": None,
        "imdb_id": imdb_id,
        "tmdb_id": None,
        "imdb_rating": None,
        "synopsis": (str(ld.get("description") or "").strip() or None),
        "genres": json.dumps(genres, ensure_ascii=False) if genres else None,
        "director": None,
        "cast_names": json.dumps(
            [a.get("name") for a in _as_list(ld.get("actor")) if isinstance(a, dict)],
            ensure_ascii=False) or None,
        "duration": iso_duration_text(ld.get("duration")),
        "release_date": str(ld.get("datePublished") or "") or None,
        "languages": json.dumps(languages, ensure_ascii=False) if languages else None,
        "industry": None,
        "country": None,
        "seasons": json.dumps([season]) if season else None,
        "url": loc,
        "slug": slug,
        "is_18_plus": 1 if ADULT_RE.search(title + " " + " ".join(genres)) else 0,
        "is_animated": 1 if any(g.lower() in ("animation", "anime") for g in genres) else 0,
        "releases": releases,
        "raw_meta": {
            "site": SITE,
            "sitemap_loc": loc,
            "ld_type": ld.get("@type"),
            "ld_name": raw_name,
            "imdb_url": next((str(v) for v in _as_list(same_as)
                              if "imdb.com" in str(v)), None),
            "bridge_pages": len(releases),
            "link_source": ("detail anchors -> /all-format-downloads bridge -> "
                            "/d/ server endpoints; endpoints are stored unverified "
                            "and were not followed"),
        },
    }


def annotate_sources(record: dict, bridge_html: dict[str, str],
                     bridge_errors: dict[str, str]) -> None:
    for rel in record.get("releases") or []:
        bridge = rel["bridge_url"]
        meta = rel.setdefault("raw_meta", {})
        error = bridge_errors.get(bridge)
        if error:
            meta["bridge_error"] = error
            continue
        sources = server_sources(bridge_html.get(bridge, ""), rel.get("quality"))
        rel["sources"] = sources
        meta["server_count"] = len(sources)
        meta["bridge_fetched"] = True


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
    source_site TEXT DEFAULT 'filmyhit',
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
CREATE INDEX IF NOT EXISTS idx_filmyhit_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_filmyhit_posts_type ON posts(media_type);
CREATE INDEX IF NOT EXISTS idx_filmyhit_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_filmyhit_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_filmyhit_releases_post ON releases(post_canonical_key);
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
                  workers: int = 1, delay: float = 0.4, batch_size: int = 10,
                  max_bridges: int | None = None, verbose: bool = True) -> dict:
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
              "failed_rows": 0, "parked": 0, "failed": 0, "bridge_errors": 0,
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
        record = build_record(loc, page)
        if record is None:
            return None, _failure("no-jsonld", status, final,
                                  "page has no schema.org Movie/TVSeries node")
        bridge_html: dict[str, str] = {}
        bridge_errors: dict[str, str] = {}
        bridges = [rel["bridge_url"] for rel in record["releases"]]
        if max_bridges is not None:
            bridges = bridges[:max_bridges]
        for bridge in bridges:
            if STOP_REQUESTED:
                break
            time.sleep(delay)
            b_status, b_final, b_body, _h = http_get(
                bridge, timeout=PAGE_TIMEOUT, retries=0, follow_redirects=False)
            if STOP_REQUESTED and b_status == 0:
                break
            if b_status == 200:
                bridge_html[bridge] = b_body
            else:
                bridge_errors[bridge] = f"http-{b_status}" if b_status else "transport"
        annotate_sources(record, bridge_html, bridge_errors)
        if bridge_errors:
            record["raw_meta"]["bridge_errors"] = bridge_errors
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
            totals["bridge_errors"] += len(
                (post.get("raw_meta") or {}).get("bridge_errors") or {})
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
              f"bridge_errors={totals['bridge_errors']} "
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


def sample_page(url: str, max_bridges: int = 3) -> dict | None:
    status, final, page, _headers = http_get(url)
    if status != 200:
        print(f"[!] [{SITE}] {url} -> HTTP {status}")
        return None
    record = build_record(url, page)
    if record is None:
        print(f"[!] [{SITE}] {url} -> no JSON-LD")
        return None
    bridge_html: dict[str, str] = {}
    bridge_errors: dict[str, str] = {}
    for rel in record["releases"][:max_bridges]:
        bridge = rel["bridge_url"]
        b_status, _f, body, _h = http_get(bridge)
        if b_status == 200:
            bridge_html[bridge] = body
        else:
            bridge_errors[bridge] = f"http-{b_status}"
    annotate_sources(record, bridge_html, bridge_errors)
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
        description=f"FilmyHit staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="queue sitemap detail URLs")
    sync.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync.add_argument("--limit", type=int)

    crawl = sub.add_parser("crawl", help="fetch pending pages and write staging rows")
    crawl.add_argument("--db", default=str(DEFAULT_DB_PATH))
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--workers", type=int, default=1)
    crawl.add_argument("--delay", type=float, default=0.4)
    crawl.add_argument("--max-bridges", type=int, default=None,
                       help="per-title bridge cap for a bounded probe")

    sample = sub.add_parser("sample", help="parse one URL without writing")
    sample.add_argument("url")
    sample.add_argument("--max-bridges", type=int, default=3)

    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _install_signal_handlers()
    if args.command == "sync":
        count = sync_catalog(limit=args.limit, db_path=args.db)
        print(f"[✓] [{SITE}] queued {count} detail URLs -> {args.db}")
        return 0
    if args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=args.db, workers=args.workers,
                      delay=args.delay, max_bridges=args.max_bridges)
        return 0
    if args.command == "sample":
        record = sample_page(args.url, max_bridges=args.max_bridges)
        if record is None:
            return 1
        print(json.dumps({k: v for k, v in record.items() if k != "releases"},
                         indent=2, ensure_ascii=False))
        print(f"releases={len(record['releases'])} "
              f"sources={sum(len(r['sources']) for r in record['releases'])}")
        for rel in record["releases"]:
            print("  ", rel["label"], rel["quality"], rel["size_bytes"],
                  rel["codec"], len(rel["sources"]), "servers")
        return 0
    if args.command == "stats":
        print(json.dumps(stats(args.db), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
