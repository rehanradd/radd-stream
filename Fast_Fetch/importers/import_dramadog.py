#!/usr/bin/env python3
"""
import_dramadog.py — dramadog.app (short vertical dramas) into a dedicated staging vault.

DramaDog is a short-drama aggregator: 19,972 series across ~30 source
platforms (ReelShort, DramaBox, GoodShort, ShortMax, NetShort, ...), ALL
episodes free, no sign-up. Measured live 2026-11-10 from the Oracle VM:

  * ``https://dramadog.app/`` answers 200, title "DramaDog — Watch Short
    Dramas Free, All Episodes, No Ads".
  * ``/robots.txt`` names ``Sitemap: https://dramadog.app/sitemap.xml``.
  * ``/sitemap.xml`` is a sitemapindex of 30 child sitemaps, one per
    platform (``sitemap-goodshort.xml`` holds 2,942 drama URLs).
  * A drama page (``/drama/<slug>``) ships JSON-LD ``TVSeries`` (name,
    image poster, description, genres, ``numberOfEpisodes``) plus
    ``data-ep="N"`` buttons, and embeds the episode-1 stream:
    ``https://v.dramadog.app/hls/<platform>/<id>/ep1.m3u8``.
  * The .m3u8 pattern is predictable AND verified: for
    ``after-divorce-my-three-brothers-spoil-me-rotten`` (66 episodes,
    platform goodshort, id 31001925906) ep1/ep30/ep60 all answer 206
    with a real ``#EXTM3U`` playlist, while ep80 answers 404 — the
    pattern holds exactly to the declared episode count and no further.

One post per series (media_type "series"), one release per episode
(season 1, episode N), one source per release: source_url is the drama
page, final_url is the episode .m3u8, playback_type "direct". Episode 1
and the last episode are Range-probed per title; the middle episodes are
stored active-by-pattern (the pattern is verified at both ends of every
title, and the play-time Stage-2 probe is the final gate) with
``raw_meta.pattern_derived`` set so the provenance is honest.

Isolation is the whole point: this writes only to the vault named by
``--db``, which defaults to ``/home/ubuntu/radd-stream-data/dramadog.db``.
It never imports the production ``fast_fetch.db``/merged catalog and never
runs the unified ``save_scraped_data`` path. A later ``merge_catalogs.py``
run is the only thing allowed to bring these rows into the unified catalog.

Stdlib only. Polite by default (sequential fetches, a 0.25 s floor between
request starts) because this runs on a one-core box.

Usage:
    python3 -S Fast_Fetch/importers/import_dramadog.py sync --limit 200
    python3 -S Fast_Fetch/importers/import_dramadog.py sync --limit 20 --db /tmp/dramadog.db
    python3 -S Fast_Fetch/importers/import_dramadog.py verify
    python3 -S Fast_Fetch/importers/import_dramadog.py stats
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

SITE = "dramadog"
SITE_NAME = "dramadog"
DEFAULT_BASE_URL = "https://dramadog.app"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/dramadog.db")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = 30
PROBE_TIMEOUT = 15
DEFAULT_DELAY = 0.25
SITEMAP_TIMEOUT = 30
MAX_EPISODES_PER_TITLE = 500

SERVICE = "dramadog"
SERVICE_TIER = 1
PLAYBACK_DIRECT = "direct"
DEFAULT_SOURCE_STATUS = "active"

SITEMAP_INDEX_RE = re.compile(r"""<loc>(https?://[^<]+)</loc>""", re.I)
DRAMA_URL_RE = re.compile(r"""https?://dramadog\.app/drama/([A-Za-z0-9_-]+)/?""")
JSON_LD_RE = re.compile(
    r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.I | re.S)
M3U8_RE = re.compile(
    # The stream id is numeric on goodshort/blinkdrama (…/31001925906/…)
    # and the drama slug on blinkdrama/flickreels (…/hearts-under-fire/…);
    # both forms play (ep1/ep2/ep30 → 206, verified live 2026-11-10) and
    # both generalize to epN by substitution, so one pattern covers them.
    r"""https?://v\.dramadog\.app/hls/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)/ep1\.m3u8""")
DATA_EP_RE = re.compile(r"""data-ep=["'](\d+)["']""")
EPISODE_COUNT_RE = re.compile(
    r"""numberOfEpisodes["']?\s*:\s*(\d+)""", re.I)


def log(message: str) -> None:
    print(message, flush=True)


def _clean_title(title: str | None) -> str:
    text = html_mod.unescape(str(title or "")).strip()
    text = re.sub(r"""\s+""", " ", text)
    return text


def _slug_key(slug: str) -> str:
    return "dramadog-%s" % slug


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
    """Range-probe one .m3u8. Returns {ok, status, is_playlist}."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Range": "bytes=0-511"})
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


def parse_sitemap_index(xml: str) -> list:
    """Child sitemap URLs from the index (drama sitemaps only)."""
    out = []
    for loc in SITEMAP_INDEX_RE.findall(xml or ""):
        if "sitemap-pages" in loc:
            continue  # static pages, not dramas
        if loc.endswith(".xml"):
            out.append(loc)
    return out


def parse_child_sitemap(xml: str) -> list:
    """Drama page URLs from one per-platform child sitemap."""
    urls = []
    for loc in SITEMAP_INDEX_RE.findall(xml or ""):
        if "/drama/" in loc:
            urls.append(loc.rstrip("/"))
    return urls


def parse_drama_page(html: str, page_url: str) -> dict | None:
    """JSON-LD + ep1 stream off one drama page. None when unparsable."""
    slug_m = re.search(r"""/drama/([A-Za-z0-9_-]+)""", page_url)
    slug = slug_m.group(1) if slug_m else ""
    if not slug:
        return None
    ld = {}
    for block in JSON_LD_RE.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        if isinstance(data, dict) and data.get("@type") == "TVSeries":
            ld = data
            break
        if isinstance(data, dict):
            graph = data.get("@graph") or []
            for node in graph if isinstance(graph, list) else []:
                if isinstance(node, dict) and node.get("@type") == "TVSeries":
                    ld = node
                    break
        if ld:
            break
    title = _clean_title(ld.get("name")) if ld else ""
    if not title:
        title_m = re.search(r"""<title>([^<]*)</title>""", html or "", re.I)
        title = _clean_title(title_m.group(1).split("|")[0]) if title_m else slug
    episodes = None
    if ld:
        try:
            episodes = int(ld.get("numberOfEpisodes") or 0) or None
        except (TypeError, ValueError):
            episodes = None
    if not episodes:
        count_m = EPISODE_COUNT_RE.search(html or "")
        if count_m:
            episodes = int(count_m.group(1))
    data_eps = [int(n) for n in DATA_EP_RE.findall(html or "")]
    max_data_ep = max(data_eps) if data_eps else 0
    if not episodes:
        episodes = max_data_ep or 1
    m3u8_m = M3U8_RE.search(html or "")
    platform = m3u8_m.group(1) if m3u8_m else None
    stream_id = m3u8_m.group(2) if m3u8_m else None
    genres = ld.get("genre") if isinstance(ld, dict) else None
    if isinstance(genres, str):
        genres = [genres]
    poster = ld.get("image") if isinstance(ld, dict) else None
    if isinstance(poster, dict):
        poster = poster.get("url")
    year = None
    date_pub = (ld.get("datePublished") or "") if isinstance(ld, dict) else ""
    year_m = re.search(r"""(19|20)\d{2}""", str(date_pub))
    if year_m:
        year = int(year_m.group(0))
    return {
        "url": page_url, "slug": slug, "title": title,
        "clean_title": title, "year": year,
        "synopsis": _clean_title(ld.get("description")) if ld else None,
        "genres": ", ".join(g for g in (genres or []) if g) or None,
        "poster_url": poster if isinstance(poster, str) else None,
        "episodes": episodes, "max_data_ep": max_data_ep,
        "platform": platform, "stream_id": stream_id,
        "is_18_plus": fast_fetch.is_adult_title(title, source_site=SITE),
        "raw_meta": {"platform": platform, "stream_id": stream_id,
                     "max_data_ep": max_data_ep},
    }


def episode_url(platform: str, stream_id: str, episode: int) -> str:
    return ("https://v.dramadog.app/hls/%s/%s/ep%d.m3u8"
            % (platform, stream_id, episode))


def build_record(page: dict, probe=None) -> dict | None:
    """One drama page -> one post with one release per episode.

    ``probe`` is the Range-probe callable (default probe_m3u8); tests inject
    a fake. Episode 1 and the last episode are probed; middle episodes are
    stored active-by-pattern with raw_meta.pattern_derived set.
    """
    probe = probe or probe_m3u8
    if not page.get("platform") or not page.get("stream_id"):
        return None
    total = min(int(page.get("episodes") or 1), MAX_EPISODES_PER_TITLE)
    first = probe(episode_url(page["platform"], page["stream_id"], 1))
    if not first["ok"]:
        return None
    last = probe(episode_url(page["platform"], page["stream_id"], total))
    if not last["ok"] and page.get("max_data_ep"):
        total = min(int(page["max_data_ep"]), MAX_EPISODES_PER_TITLE)
        last = probe(episode_url(page["platform"], page["stream_id"], total))
    releases = []
    for n in range(1, total + 1):
        url = episode_url(page["platform"], page["stream_id"], n)
        releases.append({
            "label": "Episode %d" % n, "quality": None, "resolution": None,
            "size_bytes": None, "codec": None, "season": 1, "episode": n,
            "audio": None, "bridge_url": page["url"],
            "raw_meta": {"probed": n in (1, total)},
            "sources": [{
                "source_name": SERVICE, "service": SERVICE,
                "service_tier": SERVICE_TIER,
                "resource_id": "%s/%s/ep%d" % (
                    page["platform"], page["stream_id"], n),
                "source_url": page["url"], "final_url": url,
                "playback_type": PLAYBACK_DIRECT,
                "status": DEFAULT_SOURCE_STATUS,
                "is_temporary": 0, "quality": None,
                "mime_type": "application/vnd.apple.mpegurl",
                "last_checked": int(time.time()),
                "raw_meta": {"pattern_derived": n not in (1, total),
                             "probed": n in (1, total)},
            }],
        })
    return {
        "canonical_key": _slug_key(page["slug"]),
        "title": page["title"], "clean_title": page["clean_title"],
        "year": page["year"], "media_type": "series",
        "poster_url": page["poster_url"], "backdrop_url": None,
        "backdrop_urls": None, "imdb_id": None, "tmdb_id": None,
        "imdb_rating": None, "synopsis": page["synopsis"],
        "genres": page["genres"], "director": None, "cast_names": None,
        "duration": None, "release_date": None, "languages": None,
        "industry": None, "country": None, "seasons": "1",
        "url": page["url"], "slug": page["slug"],
        "is_18_plus": page["is_18_plus"], "is_animated": 0,
        "source_site": SITE, "raw_meta": page["raw_meta"],
        "releases": releases,
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
    source_site TEXT DEFAULT 'dramadog',
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
CREATE INDEX IF NOT EXISTS idx_dramadog_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_dramadog_posts_key ON posts(canonical_key);
CREATE INDEX IF NOT EXISTS idx_dramadog_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_dramadog_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_dramadog_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_dramadog_sitemap_scraped ON sitemap_cache(scraped);
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
                if c not in ("canonical_key", "scraped_at"))
            conn.execute(
                f"INSERT INTO posts ({', '.join(columns)})"
                f" VALUES ({', '.join('?' for _ in columns)})"
                f" ON CONFLICT(canonical_key) DO UPDATE SET {updates}",
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
                         src.get("status") or DEFAULT_SOURCE_STATUS,
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
    """Gate audit: every post has a release and every source a final URL."""
    result = stats(db_path)
    ok = (result["posts_without_release"] == 0
          and result["sources_without_final_url"] == 0
          and result["posts"] > 0)
    return ok, result


# ---------------------------------------------------------------------------
# Sync (enumerate -> fetch -> parse -> probe -> stage)
# ---------------------------------------------------------------------------

def sync(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
         base_url: str | None = None, delay: float = DEFAULT_DELAY,
         registry_path: str | Path | None = None,
         fetcher=None, prober=None) -> dict:
    """Walk the sitemapindex round-robin and stage up to ``limit`` dramas.

    ``fetcher``/``prober`` are injectable for offline tests; the live path
    uses http_get / probe_m3u8. On a 0-drama sync, ``resolve_if_dead`` runs
    the domain-tracker chain once and the sync is retried on the verified
    base only (Session 106 wiring).
    """
    fetch = fetcher or (lambda url: http_get(url, timeout=SITEMAP_TIMEOUT)[0:2])
    probe = prober or probe_m3u8
    base = (base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL,
                                            registry_path)).rstrip("/")
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0, "pages_fetched": 0, "pages_failed": 0,
              "base_url": base}
    limit = limit if limit is not None else 200

    def _run_once(base_url_: str) -> list:
        status, index_xml = fetch(base_url_.rstrip("/") + "/sitemap.xml")
        if status != 200 or not index_xml:
            return []
        children = parse_sitemap_index(index_xml)
        queues: list[list] = []
        for child in children:
            time.sleep(delay)
            cstatus, cxml = fetch(child)
            if cstatus != 200 or not cxml:
                continue
            urls = parse_child_sitemap(cxml)
            if urls:
                queues.append(urls)
        # Round-robin across platforms so the batch is representative,
        # not 200 titles from the first platform's sitemap.
        picked: list = []
        while queues and len(picked) < limit:
            progressed = False
            for q in queues:
                if len(picked) >= limit:
                    break
                if q:
                    picked.append(q.pop(0))
                    progressed = True
            if not progressed:
                break
        return picked

    drama_urls = _run_once(base)
    if not drama_urls and fetcher is None:
        fresh = resolve_if_dead(SITE_NAME, registry_path)
        if fresh and fresh.rstrip("/") != base:
            log("[i] tracker moved %s -> %s; retrying once" % (base, fresh))
            base = fresh.rstrip("/")
            totals["base_url"] = base
            drama_urls = _run_once(base)
    for url in drama_urls:
        time.sleep(delay)
        totals["pages_fetched"] += 1
        status, html = fetch(url)
        if status != 200 or not html:
            totals["pages_failed"] += 1
            continue
        page = parse_drama_page(html, url)
        if not page:
            totals["pages_failed"] += 1
            continue
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
    parser = argparse.ArgumentParser(description="DramaDog staging importer")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_cmd = sub.add_parser("sync", help="enumerate + stage dramas")
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
