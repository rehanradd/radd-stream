#!/usr/bin/env python3
"""
import_castle.py — bulwik.com ("Castle": Hindi-dubbed movies, web series,
anime, reality + short shows) into a dedicated staging vault.

Measured live 2026-11-10 from the Oracle VM:

  * ``https://www.bulwik.com/`` answers 200, title "Hindi Dubbed Movies &
    Series, Free Streaming | Castle"; ``/robots.txt`` names
    ``Sitemap: https://www.bulwik.com/sitemap.xml``.
  * ``/sitemap.xml`` is a sitemapindex of 204 child sitemaps:
    ``/movies/sitemap/1..100.xml`` (100 locs each, ~10,000 movies) and
    ``/series/sitemap/1..100.xml`` (100 locs each, ~10,000 series season
    pages). The "1 lakh+ titles" claim is inflated; ~20,000 is measured.
  * A movie page (``/movie/<slug>/<id>``) ships JSON-LD ``Movie`` (name,
    image poster, description, genre, datePublished, duration ``PT123M``,
    contentRating) and a signed HLS master on one of two tlnob hosts:
    ``https://img01.tlnob.com/video/<hash>/index_401.m3u8`` or
    ``https://img1.tlnob.com/video/<hash>/index_365.m3u8`` (same
    ``?auth_key=...&expire=...`` signing; the img1 form serves ~30% of
    titles — measured 2026-11-10 on a 53-title skip re-fetch: 16 of 53
    carried the img1 form and were skipped by the img01-only regex).
    The URL is JSON-escaped in the page (``\\u0026`` for ``&``) and must be
    unescaped before use — a truncated URL (no expire param) 403s.
  * The signed-URL block is flaky per request: on the same 53-title
    re-fetch 15 titles that showed no signed URL the first time served
    a fresh img01 URL the second time, so a page with no signed URL is
    re-fetched once before it is skipped. The remaining no-stream pages
    are mostly unreleased titles (datePublished 2026, no .m3u8 of any
    kind on the page) and are correctly skipped.
  * One sitemap loc carries a zero-width space in its slug
    (``roma\\u200bnchakam``) which makes the fetch fail; sitemap locs
    are sanitized (U+200B and the literal ``\\u200b`` text stripped)
    before use.
  * The signature lives ~3h from minting, and the page itself may be
    CDN-cached with an already-expired signature (a URL minted ~13h
    before its page fetch 403d while a fresh one 200d with a real
    ``#EXTM3U``). So the importer NEVER stores a signed URL as durable:
    source_url is the movie page, final_url is the signed .m3u8 with
    ``is_temporary=1``, and the resolver re-extracts a fresh signature
    from the live page on every press (``unwrap_castle``). A signature
    already expired at scrape time is stored ``unverified``, never
    ``active``.
  * Series season pages (``/series/<slug>-season-N/<id>``) carry JSON-LD
    ``TVSeries`` (name, cast, numberOfEpisodes) and the full episode
    list (id, number, duration, resolutions, audio tracks, subtitles)
    in the Next.js RSC payload — but NO per-episode stream URL anywhere
    in static HTML or in any discoverable endpoint. The ONE signed
    .m3u8 on the page is the ``trailerUrl``, not an episode stream.
    Episode play goes through an encrypted handoff: the page fetches a
    player config from ``api.hbzws.com`` (``/film-api/v0.1/
    configurationitem/get``, encrypted AES-CBC response, appCode
    ``CaslteWeb``) holding a ``playerUrl``, then opens
    ``playerUrl/<AES-CBC-encrypted {movieId, episodeId}>`` in a new
    tab and the external player resolves the video itself. There is no
    endpoint that returns a per-episode .m3u8, so series import is NOT
    implemented — staging a series post with no playable source would
    violate the verify gate. The JS-bundle analysis behind this is in
    the follow-up checkpoint; do not fake a series stream.

One post per movie (media_type "movie"), one release, one source.
``contentRating`` + the adult-title check set ``is_18_plus``.

Isolation is the whole point: this writes only to the vault named by
``--db``, which defaults to ``/home/ubuntu/radd-stream-data/castle.db``.
It never imports the production ``fast_fetch.db``/merged catalog and never
runs the unified ``save_scraped_data`` path. A later ``merge_catalogs.py``
run is the only thing allowed to bring these rows into the unified catalog.

Stdlib only. Polite by default (sequential fetches, a 0.25 s floor between
request starts) because this runs on a one-core box.

Usage:
    python3 -S Fast_Fetch/importers/import_castle.py sync --limit 200
    python3 -S Fast_Fetch/importers/import_castle.py sync --limit 20 --db /tmp/castle.db
    python3 -S Fast_Fetch/importers/import_castle.py verify
    python3 -S Fast_Fetch/importers/import_castle.py stats
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch  # noqa: E402  (path bootstrap must run first)

try:
    from domain_resolver import get_active_base_url, resolve_if_dead
except Exception:  # noqa: BLE001 - registry wiring is optional offline
    def get_active_base_url(site_name, fallback_default=None, registry_path=None):  # type: ignore
        return fallback_default or ""

    def resolve_if_dead(site_name, registry_path=None):  # type: ignore
        return ""

SITE = "castle"
SITE_NAME = "castle"
DEFAULT_BASE_URL = "https://www.bulwik.com"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/castle.db")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = 30
PROBE_TIMEOUT = 15
DEFAULT_DELAY = 0.25
SITEMAP_TIMEOUT = 30

SERVICE = "castle"
SERVICE_TIER = 1
PLAYBACK_DIRECT = "direct"
#: A signature with less than this many seconds left is treated as stale.
STALE_SIGNATURE_SECONDS = 600

SITEMAP_LOC_RE = re.compile(r"""<loc>(https?://[^<]+)</loc>""", re.I)
MOVIE_URL_RE = re.compile(
    r"""https?://www\.bulwik\.com/movie/([A-Za-z0-9_-]+)/(\d+)/?""")
JSON_LD_RE = re.compile(
    r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.I | re.S)
SIGNED_M3U8_RE = re.compile(
    # Two tlnob hosts serve the signed master: img01 (index_401) and
    # img1 (index_365). The img1 form serves ~30% of titles; the old
    # img01-only pattern skipped all of them (measured 2026-11-10).
    r"""https://img0?1\.tlnob\.com/video/[^\s"'<>]+""", re.I)
DURATION_RE = re.compile(
    r"""PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?""")
EXPIRE_RE = re.compile(r"""[?&]expire=(\d+)""")


def log(message: str) -> None:
    print(message, flush=True)


def _clean_title(title: str | None) -> str:
    text = html_mod.unescape(str(title or "")).strip()
    text = re.sub(r"""\s+""", " ", text)
    return text


def unescape_page_url(raw: str) -> str:
    """JSON-unescape a URL as embedded in page JSON (\\u0026 -> &, \\/ -> /).

    The page sometimes carries the URL up to an escaped closing quote
    (``...expire=1234\\``), so a trailing backslash is stripped first —
    without that, the JSON parse fails and the caller gets a truncated
    URL that the CDN 403s.
    """
    raw = raw.rstrip("\\")
    try:
        return json.loads('"%s"' % raw.replace('"', '\\"'))
    except Exception:
        return raw.replace("\\u0026", "&").replace("\\/", "/")


def clean_sitemap_loc(loc: str) -> str:
    """Strip junk out of a sitemap loc before it is fetched.

    One live loc carries a zero-width space inside its slug
    (``roma\\u200bnchakam`` — the sitemap literally contains the
    U+200B character, and some mirrors carry the six-character escape
    text instead), which makes the page fetch fail outright. Both
    forms strip to the real slug.
    """
    return (loc or "").replace("\u200b", "").replace("\\u200b", "").strip()


def parse_duration_iso(text: str | None) -> int | None:
    """PT1H30M -> 90 (minutes). None when unparsable."""
    if not text:
        return None
    m = DURATION_RE.fullmatch(str(text).strip())
    if not m:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in m.groups())
    total = hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return total or None


def http_get(url: str, timeout: int = PAGE_TIMEOUT) -> tuple:
    """One GET. Returns (status, text). Transport failure is (0, "")."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "ignore")
        except Exception:
            return e.code, ""
    except Exception:
        return 0, ""


def probe_m3u8(url: str, timeout: int = PROBE_TIMEOUT) -> dict:
    """Plain-GET probe of a signed .m3u8. Returns {ok, status, is_playlist}."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            head = resp.read(512)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            ok = resp.status in (200, 206) and (
                "mpegurl" in ctype or "m3u8" in ctype
                or head[:7] == b"#EXTM3U")
            return {"ok": ok, "status": resp.status,
                    "is_playlist": head[:7] == b"#EXTM3U"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "is_playlist": False}
    except Exception:
        return {"ok": False, "status": 0, "is_playlist": False}


def parse_movie_page(html: str, page_url: str, now_ms: int | None = None) -> dict | None:
    """JSON-LD Movie + signed .m3u8 off one movie page. None when unparsable."""
    slug_m = MOVIE_URL_RE.search(page_url)
    if not slug_m:
        return None
    slug, work_id = slug_m.group(1), slug_m.group(2)
    ld = {}
    for block in JSON_LD_RE.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        nodes = []
        if isinstance(data, dict):
            if data.get("@type") == "Movie":
                nodes = [data]
            elif isinstance(data.get("@graph"), list):
                nodes = data["@graph"]
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "Movie":
                ld = node
                break
        if ld:
            break
    title = _clean_title(ld.get("name")) if ld else ""
    if not title:
        title_m = re.search(r"""<title>([^<]*)</title>""", html or "", re.I)
        title = _clean_title(title_m.group(1).split("|")[0]) if title_m else slug
    year = None
    date_pub = str(ld.get("datePublished") or "") if ld else ""
    year_m = re.search(r"""(19|20)\d{2}""", date_pub)
    if year_m:
        year = int(year_m.group(0))
    genres = ld.get("genre") if isinstance(ld, dict) else None
    if isinstance(genres, str):
        genres = [genres]
    poster = ld.get("image") if isinstance(ld, dict) else None
    if isinstance(poster, dict):
        poster = poster.get("url")
    duration = parse_duration_iso(ld.get("duration")) if ld else None
    rating = str(ld.get("contentRating") or "") if ld else ""
    signed = None
    expire_ms = None
    for raw in SIGNED_M3U8_RE.findall(html or ""):
        url = unescape_page_url(raw)
        if "index_" in url and ".m3u8" in url:
            signed = url
            break
    if signed:
        expire_m = EXPIRE_RE.search(signed)
        if expire_m:
            expire_ms = int(expire_m.group(1))
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    stale = bool(expire_ms is not None
                 and expire_ms < now + STALE_SIGNATURE_SECONDS * 1000)
    is_adult = fast_fetch.is_adult_title(title, source_site=SITE)
    if rating.strip().upper() in ("18+", "R18", "X", "ADULT"):
        is_adult = 1
    return {
        "url": page_url, "slug": slug, "work_id": work_id,
        "title": title, "clean_title": title, "year": year,
        "synopsis": _clean_title(ld.get("description")) if ld else None,
        "genres": ", ".join(g for g in (genres or []) if g) or None,
        "poster_url": poster if isinstance(poster, str) else None,
        "duration": str(duration) if duration else None,
        "content_rating": rating or None,
        "signed_url": signed, "expire_ms": expire_ms, "stale": stale,
        "is_18_plus": is_adult,
        "raw_meta": {"work_id": work_id, "content_rating": rating or None,
                     "expire_ms": expire_ms, "signature_stale": stale},
    }


def build_record(page: dict, probe=None) -> dict | None:
    """One movie page -> one post with one release and one source.

    The signed URL is stored ``is_temporary=1``. Fresh + probed -> status
    ``active``; expired at scrape time (or unprobed) -> ``unverified``.
    The resolver re-extracts a fresh signature on every press either way.
    """
    probe = probe or probe_m3u8
    if not page.get("signed_url"):
        return None
    if page.get("stale"):
        status = "unverified"
    else:
        status = "active" if probe(page["signed_url"])["ok"] else "unverified"
    return {
        "canonical_key": "castle-%s" % page["slug"],
        "title": page["title"], "clean_title": page["clean_title"],
        "year": page["year"], "media_type": "movie",
        "poster_url": page["poster_url"], "backdrop_url": None,
        "backdrop_urls": None, "imdb_id": None, "tmdb_id": None,
        "imdb_rating": None, "synopsis": page["synopsis"],
        "genres": page["genres"], "director": None, "cast_names": None,
        "duration": page["duration"], "release_date": None,
        "languages": None, "industry": None, "country": None,
        "seasons": None, "url": page["url"], "slug": page["slug"],
        "is_18_plus": page["is_18_plus"], "is_animated": 0,
        "source_site": SITE, "raw_meta": page["raw_meta"],
        "releases": [{
            "label": page["title"], "quality": None, "resolution": None,
            "size_bytes": None, "codec": None, "season": None, "episode": None,
            "audio": None, "bridge_url": page["url"],
            "raw_meta": {"content_rating": page["content_rating"]},
            "sources": [{
                "source_name": SERVICE, "service": SERVICE,
                "service_tier": SERVICE_TIER,
                "resource_id": page["work_id"],
                "source_url": page["url"], "final_url": page["signed_url"],
                "playback_type": PLAYBACK_DIRECT,
                "status": status, "is_temporary": 1, "quality": None,
                "mime_type": "application/vnd.apple.mpegurl",
                "last_checked": int(time.time()),
                "raw_meta": {"expire_ms": page["expire_ms"],
                             "signature_stale": page["stale"]},
            }],
        }],
    }


# ---------------------------------------------------------------------------
# Staging database (same shape as import_archive / import_themoviebox)
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
    source_site TEXT DEFAULT 'castle',
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
    service_tier INTEGER DEFAULT 1,
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'direct',
    status TEXT DEFAULT 'active',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    mime_type TEXT,
    last_checked INTEGER,
    raw_meta TEXT,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_castle_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_castle_posts_key ON posts(canonical_key);
CREATE INDEX IF NOT EXISTS idx_castle_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_castle_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_castle_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_castle_sitemap_scraped ON sitemap_cache(scraped);
"""

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
    "release_id", "source_name", "service", "service_tier", "resource_id",
    "source_url", "final_url", "playback_type", "status", "is_temporary",
    "quality", "mime_type", "last_checked", "raw_meta",
)
INTEGER_COLUMNS = {
    "year", "size_bytes", "season_number", "episode_number", "is_18_plus",
    "is_animated", "is_temporary", "last_checked", "service_tier",
}


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


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=(),
                   conn: sqlite3.Connection | None = None) -> dict:
    """Upsert records; a re-export of one item replaces its releases+sources."""
    own = conn is None
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0}
    if own:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=60)
        conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        for post in posts or ():
            if not post or not post.get("clean_title") or not post.get("canonical_key"):
                totals["skipped"] += 1
                continue
            values = dict(post)
            values["source_site"] = SITE
            values["raw_meta"] = json.dumps(post.get("raw_meta") or {},
                                            ensure_ascii=False)
            columns = [c for c in POST_COLUMNS if c in values]
            updates = ", ".join(
                f"{c} = excluded.{c}" for c in columns
                if c not in ("canonical_key", "scraped_at", "is_18_plus", "is_animated"))
            conn.execute(
                f"INSERT INTO posts ({', '.join(columns)})"
                f" VALUES ({', '.join('?' for _ in columns)})"
                f" ON CONFLICT(canonical_key) DO UPDATE SET "
                "is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus), "
                "is_animated = MAX(posts.is_animated, excluded.is_animated), "
                f"{updates}",
                [values[c] for c in columns])
            conn.execute(
                "DELETE FROM sources WHERE release_id IN ("
                " SELECT id FROM releases WHERE post_canonical_key = ?"
                " AND COALESCE(origin_url,'') = COALESCE(?, ''))",
                (post["canonical_key"], post.get("url")))
            conn.execute(
                "DELETE FROM releases WHERE post_canonical_key = ?"
                " AND COALESCE(origin_url,'') = COALESCE(?, '')",
                (post["canonical_key"], post.get("url")))
            for rel in post.get("releases") or []:
                cur = conn.execute(
                    "INSERT INTO releases (post_canonical_key, label, quality,"
                    " resolution, size_bytes, codec, season_number, episode_number,"
                    " audio_languages, bridge_url, origin_url, raw_meta)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (post["canonical_key"], rel.get("label"), rel.get("quality"),
                     rel.get("resolution"), rel.get("size_bytes"), rel.get("codec"),
                     rel.get("season"), rel.get("episode"), rel.get("audio"),
                     rel.get("bridge_url"), post.get("url"),
                     json.dumps(rel.get("raw_meta") or {}, ensure_ascii=False)))
                totals["releases_written"] += 1
                for src in rel.get("sources") or []:
                    conn.execute(
                        "INSERT INTO sources (release_id, source_name, service,"
                        " service_tier, resource_id, source_url, final_url,"
                        " playback_type, status, is_temporary, quality, mime_type,"
                        " last_checked, raw_meta)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (cur.lastrowid, src.get("source_name") or SERVICE,
                         src.get("service") or SERVICE,
                         src.get("service_tier", SERVICE_TIER),
                         src.get("resource_id"), src.get("source_url"),
                         src.get("final_url"), src.get("playback_type")
                         or PLAYBACK_DIRECT,
                         src.get("status") or "unverified",
                         src.get("is_temporary") or 0, src.get("quality"),
                         src.get("mime_type"), src.get("last_checked"),
                         json.dumps(src.get("raw_meta") or {}, ensure_ascii=False)))
                    totals["sources_written"] += 1
            totals["posts_written"] += 1
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return totals


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    """Count staging rows; the gate audit behind ``verify``."""
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        return {
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "sources_active": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE status = 'active'").fetchone()[0],
            "sources_unverified": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE status = 'unverified'").fetchone()[0],
            "flagged_18_plus": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "posts_without_release": conn.execute(
                "SELECT COUNT(*) FROM posts p WHERE NOT EXISTS ("
                "SELECT 1 FROM releases r WHERE r.post_canonical_key = p.canonical_key)"
                ).fetchone()[0],
            "sources_without_final_url": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE final_url IS NULL OR final_url = ''"
                ).fetchone()[0],
        }
    finally:
        conn.close()


def verify_db(db_path: Path | str = DEFAULT_DB_PATH) -> tuple[bool, dict]:
    """Gate audit: every post has a release and every source a final URL.

    An ``unverified`` source is not a failure — it is a movie whose
    signature was already stale at scrape time; the resolver re-extracts
    a fresh one on every press.
    """
    result = stats(db_path)
    ok = (result["posts_without_release"] == 0
          and result["sources_without_final_url"] == 0
          and result["posts"] > 0)
    return ok, result


# ---------------------------------------------------------------------------
# Sync (movies sitemaps -> fetch -> parse -> probe -> stage)
# ---------------------------------------------------------------------------

def sync(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
         base_url: str | None = None, delay: float = DEFAULT_DELAY,
         registry_path: str | Path | None = None,
         fetcher=None, prober=None) -> dict:
    """Walk /movies/sitemap/N.xml in order and stage up to ``limit`` movies.

    Series are deliberately out of scope here: a season page carries no
    per-episode stream URL anywhere (the one signed .m3u8 is the
    trailer; episode play is an encrypted handoff to an external
    player — see the module docstring). Pages that show no signed URL
    are re-fetched once before being skipped. On a 0-movie sync,
    ``resolve_if_dead`` runs the domain-tracker chain once and the sync
    is retried on the verified base only (Session 106 wiring).
    """
    fetch = fetcher or (lambda url: http_get(url, timeout=SITEMAP_TIMEOUT)[0:2])
    probe = prober or probe_m3u8
    base = (base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL,
                                            registry_path)).rstrip("/")
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0, "pages_fetched": 0, "pages_failed": 0,
              "pages_retried": 0, "retry_recovered": 0,
              "base_url": base}
    limit = limit if limit is not None else 200

    def _run_once(base_url_: str) -> list:
        picked: list = []
        n = 1
        while len(picked) < limit:
            url = "%s/movies/sitemap/%d.xml" % (base_url_, n)
            status, xml = fetch(url)
            if status != 200 or not xml:
                break
            locs = [clean_sitemap_loc(loc) for loc in SITEMAP_LOC_RE.findall(xml)
                    if "/movie/" in loc]
            if not locs:
                break
            picked.extend(loc.rstrip("/") for loc in locs)
            n += 1
            time.sleep(delay)
        return picked[:limit]

    movie_urls = _run_once(base)
    if not movie_urls and fetcher is None:
        fresh = resolve_if_dead(SITE_NAME, registry_path)
        if fresh and fresh.rstrip("/") != base:
            log("[i] tracker moved %s -> %s; retrying once" % (base, fresh))
            base = fresh.rstrip("/")
            totals["base_url"] = base
            movie_urls = _run_once(base)
    for url in movie_urls:
        time.sleep(delay)
        totals["pages_fetched"] += 1
        status, html = fetch(url)
        if status != 200 or not html:
            totals["pages_failed"] += 1
            continue
        page = parse_movie_page(html, url)
        if not page:
            totals["pages_failed"] += 1
            continue
        if not page.get("signed_url"):
            # The signed-URL block is flaky per request (measured: 15 of
            # 53 first-pass skips served a fresh signed URL on re-fetch),
            # so one retry before the title is skipped as sourceless.
            time.sleep(delay)
            totals["pages_retried"] += 1
            rstatus, rhtml = fetch(url)
            if rstatus == 200 and rhtml:
                totals["pages_fetched"] += 1
                rpage = parse_movie_page(rhtml, url)
                if rpage and rpage.get("signed_url"):
                    page = rpage
                    totals["retry_recovered"] += 1
        record = build_record(page, probe=probe)
        if not record:
            totals["skipped"] += 1
            continue
        written = export_staging(db_path, posts=[record])
        for key in ("posts_written", "releases_written", "sources_written",
                    "skipped"):
            totals[key] += written[key]
    return totals


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Castle (bulwik.com) staging importer")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_cmd = sub.add_parser("sync", help="enumerate + stage movies")
    sync_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync_cmd.add_argument("--limit", type=int, default=200)
    sync_cmd.add_argument("--base-url", default=None)
    sync_cmd.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    sync_cmd.add_argument("--registry", default=None)

    verify_cmd = sub.add_parser("verify", help="gate-audit a staging database")
    verify_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))

    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "sync":
        totals = sync(db_path=args.db, limit=args.limit,
                      base_url=args.base_url, delay=args.delay,
                      registry_path=args.registry)
        print(json.dumps(totals, indent=2, ensure_ascii=False))
        return 0
    if args.command == "verify":
        ok, result = verify_db(args.db)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("[✓] verify OK" if ok else "[✗] verify FAILED")
        return 0 if ok else 1
    result = stats(args.db)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
