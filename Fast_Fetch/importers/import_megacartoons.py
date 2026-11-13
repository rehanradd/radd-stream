#!/usr/bin/env python3
"""
import_megacartoons.py — megacartoons.net (classic + modern Western
cartoons) into a dedicated staging vault.

MegaCartoons is a WordPress site whose posts are single cartoon episodes.
Measured live 2026-11-10 from the Oracle VM:

  * ``https://megacartoons.net/`` 301s to ``https://www.megacartoons.net/``
    (200, title "MegaCartoons.net - Watch Online Cartoons").
  * ``/wp-json/wp/v2/posts`` works (200, real posts: "Woo-oo!",
    "Daytrip of Doom!"). Each post carries a ``video-series`` taxonomy
    term id (e.g. 123 = DuckTales) resolvable via
    ``/wp-json/wp/v2/video-series?include=<ids>``.
  * ``/sitemap_index.xml`` lists post-sitemap 1-3 + video-sitemap 1-3
    (400 locs each) + video-series-sitemap (31 series).
  * The video itself is NOT in wp-json content (synopsis only). The post
    page HTML carries it twice: a JW Player setup
    (``file: "https://ww.megacartoons.net/cartoons/ducktales/woo-oo.mp4"``)
    and a JSON-LD ``VideoObject`` ``contentUrl`` — direct self-hosted
    .mp4, no signing, no login. The episode poster is the page's
    ``og:image`` (``wp-content/uploads/DuckTales-Woo-oo.jpg``).

One post per series (media_type "series", ``is_animated=1``), one release
per episode (season 1, episode N = the post's date-ascending position
inside its series — the site publishes no S/E numbers, so the position
is recorded in raw_meta with the wp post id for a later numbering pass),
one source per release: source_url is the post page, final_url is the
.mp4, playback_type "direct". The play gate is the legal-catalog gate:
Range 206 + video/mp4 AND ffprobe (video stream + audio stream +
duration > 0). A file that passes Range but not ffprobe is stored
``unverified``, never ``active``; a missing ffprobe binary fails closed
the same way.

Isolation is the whole point: this writes only to the vault named by
``--db``, which defaults to ``/home/ubuntu/radd-stream-data/megacartoons.db``.
It never imports the production ``fast_fetch.db``/merged catalog and never
runs the unified ``save_scraped_data`` path. A later ``merge_catalogs.py``
run is the only thing allowed to bring these rows into the unified catalog.

Stdlib only. Polite by default (sequential fetches, a 0.25 s floor between
request starts) because this runs on a one-core box.

Usage:
    python3 -S Fast_Fetch/importers/import_megacartoons.py sync --limit 200
    python3 -S Fast_Fetch/importers/import_megacartoons.py sync --limit 20 --db /tmp/megacartoons.db
    python3 -S Fast_Fetch/importers/import_megacartoons.py sync --limit 20 --no-ffprobe
    python3 -S Fast_Fetch/importers/import_megacartoons.py verify
    python3 -S Fast_Fetch/importers/import_megacartoons.py stats
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sqlite3
import subprocess
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

SITE = "megacartoons"
SITE_NAME = "megacartoons"
DEFAULT_BASE_URL = "https://www.megacartoons.net"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/megacartoons.db")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = 30
JSON_TIMEOUT = 20
RANGE_TIMEOUT = 15
FFPROBE_TIMEOUT = 15
DEFAULT_DELAY = 0.25
PER_PAGE = 100

SERVICE = "megacartoons"
SERVICE_TIER = 1
PLAYBACK_DIRECT = "direct"

MP4_RE = re.compile(
    r"""https://ww\.megacartoons\.net/cartoons/[^"'<> ]+\.mp4""")
OG_IMAGE_RE = re.compile(
    r"""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']""",
    re.I)
OG_IMAGE_RE2 = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']""",
    re.I)


def log(message: str) -> None:
    print(message, flush=True)


def _clean_title(title: str | None) -> str:
    text = html_mod.unescape(str(title or "")).strip()
    text = re.sub(r"""\s+""", " ", text)
    return text


def _strip_tags(text: str | None) -> str:
    return _clean_title(re.sub(r"""<[^>]+>""", " ", str(text or "")))


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


def http_get_json(url: str, timeout: int = JSON_TIMEOUT) -> object:
    """GET a JSON document. Raises on transport failure; caller decides."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def probe_range(url: str, opener=None) -> dict:
    """Range-probe one .mp4: expect 206 + video/* (200 + video/* + a
    Content-Length also counts — a direct file, not a redirect)."""
    if opener is None:
        opener = urllib.request.urlopen
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-4095"})
    try:
        with opener(req, timeout=RANGE_TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
            headers = getattr(resp, "headers", None)
            content_type = (headers.get("Content-Type", "") or "") if headers else ""
            length = (headers.get("Content-Length", "") or "") if headers else ""
            ok = (status == 206 and content_type.lower().startswith("video/")) or (
                status == 200 and content_type.lower().startswith("video/")
                and length not in ("", "0"))
            return {"ok": ok, "status": status, "content_type": content_type}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "content_type": ""}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": 0, "content_type": "", "error": str(exc)}


def _run_ffprobe(url: str):
    return subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "stream=codec_type,codec_name,width,height",
         "-show_entries", "format=duration",
         "-of", "json", url],
        capture_output=True, text=True, timeout=FFPROBE_TIMEOUT)


def probe_ffprobe(url: str, runner=None) -> dict | None:
    """ffprobe one URL: video stream + audio stream + duration > 0, or None.

    A missing binary fails closed (None) — the item is stored unverified,
    never marked playable on the Range result alone.
    """
    if runner is None:
        runner = _run_ffprobe
    try:
        proc = runner(url)
    except FileNotFoundError:
        return None
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    streams = data.get("streams") or []
    video = next((s for s in streams
                  if s.get("codec_type") == "video" and s.get("width")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if video is None or audio is None or duration <= 0:
        return None
    return {
        "width": int(video["width"]),
        "height": int(video.get("height") or 0),
        "codec": video.get("codec_name"),
        "duration": duration,
        "has_audio": True,
    }


def parse_post_page(html: str) -> dict:
    """Direct .mp4 + poster off one cartoon post page."""
    mp4_m = MP4_RE.search(html or "")
    poster = None
    for pattern in (OG_IMAGE_RE, OG_IMAGE_RE2):
        poster_m = pattern.search(html or "")
        if poster_m:
            poster = poster_m.group(1)
            break
    return {"mp4_url": mp4_m.group(0) if mp4_m else None,
            "poster_url": poster}


def fetch_series_names(base: str, term_ids: list,
                       json_get=None) -> dict:
    """wp-json video-series term id -> (slug, name). Empty when unresolvable."""
    json_get = json_get or http_get_json
    ids = sorted({int(t) for t in term_ids if t})
    if not ids:
        return {}
    url = ("%s/wp-json/wp/v2/video-series?include=%s&per_page=100"
           "&_fields=id,slug,name" % (base, ",".join(str(i) for i in ids)))
    try:
        data = json_get(url)
    except Exception:
        return {}
    out = {}
    if isinstance(data, list):
        for term in data:
            if isinstance(term, dict) and term.get("id") is not None:
                out[int(term["id"])] = (term.get("slug") or "",
                                        _clean_title(term.get("name")))
    return out


def build_series_records(posts: list, series_names: dict,
                         range_probe=probe_range,
                         ffprobe_probe=probe_ffprobe,
                         use_ffprobe: bool = True) -> list:
    """Group wp-json posts by series; one record per series.

    ``posts`` are wp-json post dicts (already enriched with ``_mp4_url`` and
    ``_poster_url`` from their pages). Episode N is the post's
    date-ascending position inside its series. A post with no usable series
    term becomes its own one-episode series named by its title.
    """
    by_series: dict = {}
    for post in posts:
        terms = post.get("video-series") or []
        term_id = terms[0] if terms else None
        if term_id is not None and term_id in series_names:
            slug, name = series_names[term_id]
        else:
            slug = post.get("slug") or str(post.get("id"))
            name = _clean_title((post.get("title") or {}).get("rendered"))
        key = "megacartoons-%s" % slug
        by_series.setdefault(key, {"slug": slug, "name": name,
                                   "episodes": []})
        by_series[key]["episodes"].append(post)
    records = []
    for key, series in by_series.items():
        eps = sorted(series["episodes"],
                     key=lambda p: (str(p.get("date") or ""), str(p.get("id") or "")))
        releases = []
        poster = None
        first_date = None
        for n, post in enumerate(eps, start=1):
            mp4_url = post.get("_mp4_url")
            if not mp4_url:
                continue
            if poster is None and post.get("_poster_url"):
                poster = post["_poster_url"]
            if first_date is None and post.get("date"):
                first_date = str(post["date"])[:10]
            ranged = range_probe(mp4_url)
            ff = ffprobe_probe(mp4_url) if use_ffprobe else None
            proven = ranged["ok"] and ff is not None
            status = "active" if proven else "unverified"
            title = _clean_title((post.get("title") or {}).get("rendered"))
            releases.append({
                "label": "Episode %d" % n, "quality": None, "resolution": None,
                "size_bytes": None,
                "codec": (ff or {}).get("codec") if ff else None,
                "season": 1, "episode": n, "audio": None,
                "bridge_url": post.get("link"),
                "raw_meta": {"wp_post_id": post.get("id"),
                             "wp_title": title,
                             "ffprobe": ff,
                             "range_status": ranged.get("status")},
                "sources": [{
                    "source_name": SERVICE, "service": SERVICE,
                    "service_tier": SERVICE_TIER,
                    "resource_id": post.get("slug"),
                    "source_url": post.get("link"), "final_url": mp4_url,
                    "playback_type": PLAYBACK_DIRECT,
                    "status": status, "is_temporary": 0, "quality": None,
                    "mime_type": "video/mp4",
                    "last_checked": int(time.time()),
                    "raw_meta": {"ffprobe_proven": proven},
                }],
            })
        if not releases:
            continue
        records.append({
            "canonical_key": key,
            "title": series["name"], "clean_title": series["name"],
            "year": None, "media_type": "series",
            "poster_url": poster, "backdrop_url": None,
            "backdrop_urls": None, "imdb_id": None, "tmdb_id": None,
            "imdb_rating": None, "synopsis": None,
            "genres": None, "director": None, "cast_names": None,
            "duration": None, "release_date": first_date,
            "languages": None, "industry": None, "country": None,
            "seasons": "1", "url": eps[0].get("link"),
            "slug": series["slug"],
            "is_18_plus": fast_fetch.is_adult_title(
                series["name"], source_site=SITE),
            "is_animated": 1, "source_site": SITE,
            "raw_meta": {"series_slug": series["slug"],
                         "episode_count": len(releases)},
            "releases": releases,
        })
    return records


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
    source_site TEXT DEFAULT 'megacartoons',
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
CREATE INDEX IF NOT EXISTS idx_megacartoons_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_megacartoons_posts_key ON posts(canonical_key);
CREATE INDEX IF NOT EXISTS idx_megacartoons_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_megacartoons_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_megacartoons_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_megacartoons_sitemap_scraped ON sitemap_cache(scraped);
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

    An ``unverified`` source is not a failure — it is a file the Range
    probe could not prove (or ffprobe could not confirm); it is stored,
    never claimed playable.
    """
    result = stats(db_path)
    ok = (result["posts_without_release"] == 0
          and result["sources_without_final_url"] == 0
          and result["posts"] > 0)
    return ok, result


# ---------------------------------------------------------------------------
# Sync (wp-json enumerate -> page fetch -> probe -> group -> stage)
# ---------------------------------------------------------------------------

def sync(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
         base_url: str | None = None, delay: float = DEFAULT_DELAY,
         registry_path: str | Path | None = None,
         json_get=None, fetcher=None,
         range_probe=probe_range, ffprobe_probe=probe_ffprobe,
         use_ffprobe: bool = True) -> dict:
    """Walk wp-json pages and stage up to ``limit`` cartoon episodes.

    On a 0-post sync, ``resolve_if_dead`` runs the domain-tracker chain
    once and the sync is retried on the verified base only (Session 106
    wiring). ``ffprobe_probe`` here is the module-level ``probe_ffprobe``
    (runner=None inside it means the real binary); tests pass a fake.
    """
    json_get = json_get or http_get_json
    fetch = fetcher or (lambda url: http_get(url)[0:2])
    base = (base_url or get_active_base_url(SITE_NAME, DEFAULT_BASE_URL,
                                            registry_path)).rstrip("/")
    totals = {"posts_written": 0, "releases_written": 0, "sources_written": 0,
              "skipped": 0, "pages_fetched": 0, "pages_failed": 0,
              "base_url": base}
    limit = limit if limit is not None else 200

    def _run_once(base_url_: str) -> list:
        collected: list = []
        page = 1
        while len(collected) < limit:
            url = ("%s/wp-json/wp/v2/posts?per_page=%d&page=%d"
                   "&orderby=date&order=desc&_fields=id,slug,link,title,date,"
                   "video-series" % (base_url_, PER_PAGE, page))
            try:
                data = json_get(url)
            except Exception:
                break
            if not isinstance(data, list) or not data:
                break
            collected.extend(data)
            if len(data) < PER_PAGE:
                break
            page += 1
            time.sleep(delay)
        return collected[:limit]

    wp_posts = _run_once(base)
    if not wp_posts and fetcher is None and json_get is http_get_json:
        fresh = resolve_if_dead(SITE_NAME, registry_path)
        if fresh and fresh.rstrip("/") != base:
            log("[i] tracker moved %s -> %s; retrying once" % (base, fresh))
            base = fresh.rstrip("/")
            totals["base_url"] = base
            wp_posts = _run_once(base)
    if not wp_posts:
        return totals
    term_ids = []
    for post in wp_posts:
        term_ids.extend(post.get("video-series") or [])
    series_names = fetch_series_names(base, term_ids, json_get=json_get)
    for post in wp_posts:
        time.sleep(delay)
        totals["pages_fetched"] += 1
        status, html = fetch(post.get("link") or "")
        if status != 200 or not html:
            totals["pages_failed"] += 1
            continue
        parsed = parse_post_page(html)
        post["_mp4_url"] = parsed["mp4_url"]
        post["_poster_url"] = parsed["poster_url"]
        if not parsed["mp4_url"]:
            totals["pages_failed"] += 1
    records = build_series_records(
        [p for p in wp_posts if p.get("_mp4_url")], series_names,
        range_probe=range_probe, ffprobe_probe=ffprobe_probe,
        use_ffprobe=use_ffprobe)
    for record in records:
        written = export_staging(db_path, posts=[record])
        for key in ("posts_written", "releases_written", "sources_written",
                    "skipped"):
            totals[key] += written[key]
    return totals


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MegaCartoons staging importer")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_cmd = sub.add_parser("sync", help="enumerate + stage cartoon episodes")
    sync_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync_cmd.add_argument("--limit", type=int, default=200)
    sync_cmd.add_argument("--base-url", default=None)
    sync_cmd.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    sync_cmd.add_argument("--registry", default=None)
    sync_cmd.add_argument("--no-ffprobe", action="store_true",
                          help="skip the ffprobe half of the play gate")

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
                      registry_path=args.registry,
                      use_ffprobe=not args.no_ffprobe)
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
