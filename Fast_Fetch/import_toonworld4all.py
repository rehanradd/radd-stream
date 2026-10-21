#!/usr/bin/env python3
"""
import_toonworld4all.py — Dedicated staging scraper for ToonWorld4All (Hindi anime).

Zero-dependency (stdlib-only) crawler for https://toonworld4all.me.

The site exposes an open WordPress REST API, so ingestion is API-driven
(same pattern as desicinemas/bolly4u):
  1. --sync-api    : /wp-json/wp/v2/posts pages cached raw into sitemap_cache
  2. crawl (default): parse cached docs; download links are obfuscated redirects
     through the site's own backend (backend.tw4all.workers.dev/redirect?data=...).
     Each token is stored as a bridge source; resolving the worker hop yields the
     gplinks.co short page, which is signup-gated today and healed via JIT later.

18+ titles are STORED with is_18_plus=1 (never skipped) per project rule.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import html
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

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch
from domain_resolver import get_active_base_url

DEFAULT_BASE_URL = "https://toonworld4all.me"
SITE_NAME = "toonworld4all"
DB_PATH = BASE_DIR.parent / "toonworld4all.db"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MIN_REQUEST_DELAY = 0.3
WORKER_RE = re.compile(
    r'href=["\'](https?://[A-Za-z0-9.-]*tw4all\.workers\.dev/redirect\?data=([A-Za-z0-9+/=]+))["\']',
    re.I,
)

STOP_REQUESTED = False


def sig_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("\n[!] Stop signal received. Finishing in-flight items...", flush=True)


signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)


def get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class ToonClient:
    """Rate-limited HTTP client with retries for ToonWorld4All."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, request_interval: float = 0.3, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.request_interval = max(MIN_REQUEST_DELAY, request_interval)
        self.retries = max(1, retries)
        self.ssl_ctx = get_ssl_context()
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def _wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next_request_at:
                time.sleep(self._next_request_at - now)
            self._next_request_at = time.monotonic() + self.request_interval

    def get_text(self, url: str, referer: str | None = None, timeout: int = 20) -> tuple[int, str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        for attempt in range(self.retries):
            if STOP_REQUESTED:
                return 0, url, ""
            self._wait()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return resp.status, resp.geturl(), resp.read().decode(charset, errors="replace")
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    return e.code, url, ""
                if attempt == self.retries - 1:
                    return e.code, url, ""
            except Exception:
                if attempt == self.retries - 1:
                    return 0, url, ""
        return 0, url, ""

    def get_json(self, url: str) -> tuple[int, object]:
        code, _, text = self.get_text(url)
        if code != 200 or not text:
            return code, None
        try:
            return code, json.loads(text)
        except json.JSONDecodeError:
            return code, None


def init_staging_db(db_path: Path):
    """Creates the isolated ToonWorld4All staging database (zero data loss schema)."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                site TEXT DEFAULT 'toonworld4all',
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sm_scraped ON sitemap_cache(scraped);

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_key TEXT UNIQUE,
                title TEXT,
                original_title TEXT,
                year INTEGER,
                media_type TEXT,
                imdb_id TEXT,
                tmdb_id TEXT,
                poster_url TEXT,
                backdrop_url TEXT,
                synopsis TEXT,
                genres TEXT,
                cast_names TEXT,
                director TEXT,
                languages TEXT,
                rating REAL,
                is_18_plus INTEGER DEFAULT 0,
                site TEXT DEFAULT 'toonworld4all',
                post_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_posts_canonical ON posts(canonical_key);

            CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER,
                label TEXT,
                quality TEXT,
                resolution TEXT,
                size_bytes INTEGER,
                season_number INTEGER,
                episode_number INTEGER,
                audio_languages TEXT,
                codec TEXT,
                bridge_url TEXT,
                FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_releases_post_id ON releases(post_id);

            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                release_id INTEGER,
                source_name TEXT,
                service TEXT,
                resource_id TEXT,
                source_url TEXT,
                final_url TEXT,
                is_temporary INTEGER DEFAULT 0,
                quality TEXT,
                FOREIGN KEY(release_id) REFERENCES releases(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_sources_release_id ON sources(release_id);
        """)
        conn.commit()


def clean_tw_title(raw_title: str) -> tuple[str, int | None, str]:
    """Cleans a ToonWorld4All post title into (clean_title, year, canonical_key)."""
    clean = html.unescape(raw_title or "")
    clean = re.sub(r"\s*[|\-–].*?(ESub|Multi Audio|Hindi Dubbed|BluRay|WEB-DL|Webrip|x264|HEVC|10bit|Dual Audio).*$", "", clean, flags=re.I)
    year = None
    y_m = re.search(r"\b(?:19|20)\d{2}\b", clean)
    if y_m:
        year = int(y_m.group(0))
    clean = re.sub(
        r"\s*(?:480p|720p|1080p|2160p|\[.*?\]|\(.*?\)|episodes?|season\s*\d+|hindi|dual audio|multi audio|bluray|web-?rip|web-?dl|hdtc|esubs?|x264|hevc|10bit)\b.*$",
        "",
        clean, flags=re.I,
    ).strip(" -:|·•&")
    clean = re.sub(r"[\(\[\{]\s*$", "", clean).strip(" -:|·•&")
    if not clean:
        clean = html.unescape(raw_title or "").strip()
    canonical_key = fast_fetch.generate_canonical_key(clean, year)
    return clean, year, canonical_key


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "").lower()
    except ValueError:
        return ""


def decode_worker_token(token_b64: str) -> str:
    """Best-effort inner decode of a worker redirect token (double base64 wrapper)."""
    try:
        p1 = base64.b64decode(token_b64 + "=" * (-len(token_b64) % 4)).decode("utf-8", "replace")
        try:
            p2 = base64.b64decode(p1 + "=" * (-len(p1) % 4))
            return repr(p2[:80])
        except Exception:
            return p1[:80]
    except Exception:
        return ""


EPISODE_HREF_RE = re.compile(
    r"""href=["'](https?://(?:www\.)?archive\.toonworld4all\.me)?(/episode/[^"'\s<>]+)["'][^>]*>""",
    re.I,
)


def _page_props(page_html: str) -> dict | None:
    """Extracts the window.__PROPS__ JSON object embedded in an archive page."""
    m = re.search(r"window\.__PROPS__\s*=\s*(\{.*?\});\s*(?:window\.|</script>)", page_html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def fetch_episode_data(client: ToonClient, episode_url: str) -> dict | None:
    """Fetches one archive episode page and returns its embedded __PROPS__ payload."""
    code, _, page = client.get_text(episode_url, referer=client.base_url + "/")
    if code != 200 or not page:
        return None
    props = _page_props(page)
    if not props:
        return None
    inner = (props.get("data") or {}).get("data")
    return inner if isinstance(inner, dict) else None


def build_episode_release(client: ToonClient, episode_url: str, ep_data: dict, resolve_redirects: bool) -> dict | None:
    """Converts one archive episode payload into a staging release dict."""
    meta = ep_data.get("metadata") or {}
    season = meta.get("season")
    episode = meta.get("episode")
    show = meta.get("show") or ""
    encodes = ep_data.get("encodes") or []
    streams = ep_data.get("streams") or []
    if not encodes and not streams:
        return None

    stream_sources = []
    for st in streams if isinstance(streams, list) else []:
        s_link = st.get("link") or st.get("url") or ""
        if not s_link:
            continue
        host = _host_of(s_link)
        stream_sources.append({
            "source_name": f"▶ {st.get('host', 'Stream')} [{host}]",
            "service": "stream",
            "resource_id": s_link.rstrip('/').split('/')[-1][:48],
            "source_url": s_link,
            "final_url": s_link,
            "is_temporary": 0,
            "quality": st.get("quality") or st.get("resolution") or "720p",
        })

    releases = []
    for enc in encodes:
        enc_sources = []
        quality = (enc.get("resolution") or "720p").lower()
        readable = enc.get("readable") or {}
        codec_raw = enc.get("codec") or "x264"
        codec = "HEVC" if re.search(r"hevc|x265|10\s?bit", codec_raw + str(enc.get("bit_depth", "")), re.I) else "x264"
        label = f"{show} {('S%02dE%02d' % (season, episode)) if season and episode else ''} {readable.get('codec', quality)}".strip()

        for f in enc.get("files") or []:
            link = f.get("link") or ""
            if not link:
                continue
            abs_link = link if link.startswith("http") else f"https://archive.toonworld4all.me{link}"
            hexid = link.rstrip("/").split("/")[-1]
            final_url = abs_link
            if resolve_redirects and "/redirect/" in abs_link:
                code, _, rpage = client.get_text(abs_link, referer=episode_url)
                props = _page_props(rpage) if code == 200 else None
                real = None
                if props:
                    lnk = props.get("link") or {}
                    if lnk.get("domain") and lnk.get("hidden"):
                        real = lnk["domain"].rstrip("/") + "/" + lnk["hidden"]
                    elif props.get("destination"):
                        real = props["destination"]
                if real:
                    final_url = real
            host = (f.get("short") or _host_of(final_url) or "unknown").lower()
            svc = host.split(".")[-2] if host.count(".") > 1 else host.split(".")[0]
            sources_rec = {
                "source_name": f"⚡ {f.get('host', 'Mirror')} [{host}]",
                "service": svc,
                "resource_id": hexid[:64],
                "source_url": abs_link,
                "final_url": final_url,
                "is_temporary": 0,
                "quality": quality,
            }
            enc_sources.append(sources_rec)

        releases.append({
            "label": label or f"{show} {quality}",
            "quality": quality,
            "resolution": quality,
            "size_bytes": enc.get("size"),
            "season_number": season if isinstance(season, int) else None,
            "episode_number": episode if isinstance(episode, int) else None,
            "codec": codec,
            "bridge_url": episode_url,
            "sources": enc_sources + (stream_sources if not releases else []),
        })

    if not releases and stream_sources:
        releases.append(_stream_only_release(episode_url, show, season, episode, stream_sources))

    return {"releases": releases, "meta": meta}


def _stream_only_release(episode_url: str, show: str, season, episode, stream_sources: list) -> dict:
    """Wraps bare watch streams into a single release when an episode has no encodes."""
    return {
        "label": f"{show} {('S%02dE%02d' % (season, episode)) if season and episode else 'Watch Online'}".strip(),
        "quality": "720p",
        "resolution": "720p",
        "size_bytes": None,
        "season_number": season if isinstance(season, int) else None,
        "episode_number": episode if isinstance(episode, int) else None,
        "codec": "x264",
        "bridge_url": episode_url,
        "sources": list(stream_sources),
    }


def parse_tw_post_doc(client: ToonClient, doc: dict, resolve_redirects: bool = False) -> dict | None:
    """Builds a staging post dict from one WP REST API document via its archive episodes."""
    raw_title = html.unescape(doc.get("title", {}).get("rendered", "")).strip()
    content = doc.get("content", {}).get("rendered", "") or ""
    link = doc.get("link", "")
    if not raw_title or not link:
        return None

    slug_path = link.rstrip("/").split("/")[-1]
    year = None
    y_m = re.search(r"\b(?:19|20)\d{2}\b", raw_title)
    if y_m:
        year = int(y_m.group(0))

    is_series = bool(re.search(r"\b(season\s*\d+|episodes|series)\b", raw_title, re.I))
    media_type = "series" if is_series else "movie"
    is_adult = fast_fetch.is_adult_title(raw_title, link)

    season_m = re.search(r"season\s*(\d+)", raw_title, re.I)
    season_no = int(season_m.group(1)) if season_m else None

    # Poster via featured media
    poster = None
    media_id = doc.get("featured_media")
    if media_id:
        code, media = client.get_json(f"{client.base_url}/wp-json/wp/v2/media/{media_id}")
        if code == 200 and isinstance(media, dict):
            poster = media.get("source_url")

    excerpt = re.sub(r"<[^>]+>", " ", html.unescape(doc.get("excerpt", {}).get("rendered", "")))
    synopsis = re.sub(r"\s+", " ", excerpt).strip() or None

    genres = [CATEGORY_CACHE.get(str(c), "") for c in (doc.get("categories") or [])]
    genres = [g for g in genres if g]

    # Episode links from content
    ep_seen = []
    for abs_pre, href in EPISODE_HREF_RE.findall(content):
        url = (abs_pre or "https://archive.toonworld4all.me") + href
        if url not in ep_seen:
            ep_seen.append(url)

    releases = []
    show_name = None
    first_meta = None
    for ep_url in ep_seen:
        ep_data = fetch_episode_data(client, ep_url)
        if not ep_data:
            continue
        built = build_episode_release(client, ep_url, ep_data, resolve_redirects)
        if not built:
            continue
        releases.extend(built["releases"])
        if not first_meta:
            first_meta = built["meta"]
            show_name = built["meta"].get("show")
        if not poster and built["meta"].get("poster"):
            poster = built["meta"]["poster"]

    # Workers-dev legacy tokens (old-style posts) recorded as bridges
    for url, tok in WORKER_RE.findall(content):
        releases.append({
            "label": "Legacy Worker Bridge",
            "quality": "720p",
            "resolution": "720p",
            "size_bytes": None,
            "season_number": season_no,
            "episode_number": None,
            "codec": "x264",
            "bridge_url": url,
            "sources": [{
                "source_name": "🔗 ToonWorld4All Worker Bridge",
                "service": "tw4all_worker",
                "resource_id": tok[:48],
                "source_url": url,
                "final_url": url,
                "is_temporary": 0,
                "quality": "720p",
            }],
        })

    if not releases:
        return None

    clean_title = html.unescape(show_name or raw_title)
    clean_title = re.sub(r"\s*[|\-–].*$", "", clean_title).strip()
    if season_no:
        clean_title = re.sub(r"\s*season\s*\d+.*$", "", clean_title, flags=re.I).strip()
    base_key = fast_fetch.generate_canonical_key(clean_title, year)
    canonical_key = f"{base_key}_s{season_no:02d}" if (season_no and media_type == "series") else base_key

    langs_m = re.findall(r"(Hindi|Tamil|Telugu|Malayalam|Bengali|English|Japanese|Kannada)", raw_title + " " + content[:1500], re.I)
    languages = json.dumps(sorted({l.title() for l in langs_m})) if langs_m else json.dumps(["Hindi"])

    return {
        "canonical_key": canonical_key,
        "title": clean_title or html.unescape(raw_title),
        "original_title": html.unescape(raw_title),
        "year": year or (int(first_meta.get("air", "0")[:4]) if first_meta and first_meta.get("air") else None),
        "media_type": media_type,
        "imdb_id": None,
        "tmdb_id": None,
        "poster_url": poster,
        "synopsis": synopsis,
        "genres": json.dumps(genres) if genres else None,
        "cast_names": None,
        "director": None,
        "languages": languages,
        "is_18_plus": is_adult,
        "site": SITE_NAME,
        "post_url": link,
        "releases": releases,
    }


CATEGORY_CACHE: dict[str, str] = {}


def load_category_cache(client: ToonClient):
    code, cats = client.get_json(f"{client.base_url}/wp-json/wp/v2/categories?per_page=100")
    if code == 200 and isinstance(cats, list):
        for c in cats:
            CATEGORY_CACHE[str(c.get("id"))] = c.get("name", "")


def save_post_to_staging_db(db_path: Path, post_data: dict) -> bool:
    if not post_data or not post_data.get("releases"):
        return False
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO posts (
                canonical_key, title, original_title, year, media_type,
                imdb_id, poster_url, synopsis, genres, cast_names, director,
                languages, is_18_plus, site, post_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                original_title = excluded.original_title,
                year = COALESCE(excluded.year, posts.year),
                media_type = excluded.media_type,
                poster_url = COALESCE(excluded.poster_url, posts.poster_url),
                synopsis = COALESCE(excluded.synopsis, posts.synopsis),
                genres = COALESCE(excluded.genres, posts.genres),
                languages = COALESCE(excluded.languages, posts.languages),
                is_18_plus = MAX(posts.is_18_plus, excluded.is_18_plus),
                post_url = excluded.post_url,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id;
            """,
            (
                post_data["canonical_key"], post_data["title"], post_data["original_title"],
                post_data["year"], post_data["media_type"], post_data.get("imdb_id"),
                post_data.get("poster_url"), post_data.get("synopsis"), post_data.get("genres"),
                post_data.get("cast_names"), post_data.get("director"), post_data.get("languages"),
                post_data.get("is_18_plus", 0), post_data["site"], post_data["post_url"],
            ),
        )
        row = cur.fetchone()
        post_id = row[0] if row else None
        if not post_id:
            cur.execute("SELECT id FROM posts WHERE canonical_key = ?", (post_data["canonical_key"],))
            post_id = cur.fetchone()[0]
            cur.execute("DELETE FROM releases WHERE post_id = ?", (post_id,))

        for r in post_data["releases"]:
            cur.execute(
                """
                INSERT INTO releases (
                    post_id, label, quality, resolution, size_bytes,
                    season_number, episode_number, codec, bridge_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id;
                """,
                (post_id, r["label"], r["quality"], r["resolution"], r["size_bytes"],
                 r["season_number"], r["episode_number"], r["codec"], r["bridge_url"]),
            )
            rel_row = cur.fetchone()
            release_id = rel_row[0] if rel_row else None
            if not release_id:
                continue
            for s in r.get("sources", []):
                cur.execute(
                    """
                    INSERT INTO sources (
                        release_id, source_name, service, resource_id,
                        source_url, final_url, is_temporary, quality
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (release_id, s["source_name"], s["service"], s["resource_id"],
                     s["source_url"], s["final_url"], s["is_temporary"], s["quality"]),
                )
        conn.commit()
    return True


def sync_api_to_db(db_path: Path, base_url: str, max_items: int | None = None) -> int:
    """Pages through the WP REST API caching raw post docs into sitemap_cache."""
    init_staging_db(db_path)
    client = ToonClient(base_url=base_url)
    per_page = 100
    page = 1
    total_new = 0
    with sqlite3.connect(str(db_path)) as conn:
        while not STOP_REQUESTED:
            url = f"{base_url}/wp-json/wp/v2/posts?per_page={per_page}&page={page}&_fields=id,link,title,excerpt,content,categories,tags,featured_media,date,modified"
            code, _, text = client.get_text(url, timeout=25)
            if code == 400:
                break
            if code != 200 or not text:
                print(f"[!] API page {page} failed (code {code})", file=sys.stderr)
                break
            try:
                docs = json.loads(text)
            except json.JSONDecodeError:
                break
            if not docs:
                break
            records = []
            for d in docs:
                link = d.get("link")
                if not link:
                    continue
                slug = link.rstrip("/").split("/")[-1]
                records.append((link, d.get("modified"), slug, 0, SITE_NAME, json.dumps(d)))
            conn.executemany(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(loc) DO UPDATE SET raw_json = excluded.raw_json, lastmod = excluded.lastmod;
                """,
                records,
            )
            conn.commit()
            total_new += len(records)
            print(f"  [ok] page {page}: {len(records)} posts (total {total_new:,})", flush=True)
            if max_items and total_new >= max_items:
                break
            if len(docs) < per_page:
                break
            page += 1
    print(f"[✓] Cached {total_new:,} post docs.", flush=True)
    return total_new


def run_crawler(db_path: Path, base_url: str, workers: int = 3, delay: float = 0.3, limit: int | None = None, resolve_redirects: bool = False):
    init_staging_db(db_path)
    client = ToonClient(base_url=base_url, request_interval=delay)
    load_category_cache(client)

    with sqlite3.connect(str(db_path)) as conn:
        q = "SELECT loc, raw_json FROM sitemap_cache WHERE scraped = 0 AND raw_json IS NOT NULL ORDER BY rowid ASC"
        if limit:
            q += f" LIMIT {int(limit)}"
        queue = conn.execute(q).fetchall()

    if not queue:
        print("[!] No pending cached posts. Run --sync-api first.", flush=True)
        return

    print(f"[*] Starting ToonWorld4All crawler: {len(queue):,} posts | {workers} workers", flush=True)
    done = failed = total_rels = total_srcs = 0
    started = time.monotonic()

    def process_item(item):
        loc, raw = item
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            return loc, False, 0, 0
        post = parse_tw_post_doc(client, doc, resolve_redirects=resolve_redirects)
        if not post:
            return loc, False, 0, 0
        ok = save_post_to_staging_db(db_path, post)
        return loc, ok, len(post["releases"]), sum(len(r.get("sources", [])) for r in post["releases"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_item, it): it[0] for it in queue}
        for fut in concurrent.futures.as_completed(futures):
            if STOP_REQUESTED:
                for f in futures:
                    f.cancel()
                break
            loc, ok, nrels, nsrcs = fut.result()
            done += 1
            failed += 0 if ok else 1
            total_rels += nrels
            total_srcs += nsrcs
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("UPDATE sitemap_cache SET scraped=? WHERE loc=?", (1 if ok else -1, loc))
                conn.commit()
            if done % 20 == 0 or done == len(queue):
                speed = done / max(0.01, time.monotonic() - started)
                eta = (len(queue) - done) / max(0.01, speed)
                print(
                    f"  [{done:,}/{len(queue):,}] releases={total_rels:,} sources={total_srcs:,} "
                    f"failed={failed:,} speed={speed:.2f} t/s ETA: {eta/3600:.2f}h",
                    flush=True,
                )

    print(f"\n[✓] Crawler finished: {done - failed:,} scraped, {failed:,} failed in {time.monotonic()-started:.1f}s", flush=True)


def print_status(db_path: Path):
    with sqlite3.connect(str(db_path)) as conn:
        posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        adult = conn.execute("SELECT COUNT(*) FROM posts WHERE is_18_plus=1").fetchone()[0]
        rels = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        srcs = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        pend = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped=0").fetchone()[0]
        fail = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped=-1").fetchone()[0]
    print(f"posts={posts:,} (adult-flagged={adult:,}) releases={rels:,} sources={srcs:,} pending={pend:,} failed={fail:,}")


def main():
    parser = argparse.ArgumentParser(description="ToonWorld4All staging scraper")
    parser.add_argument("--sync-api", action="store_true", help="Cache WP REST API posts")
    parser.add_argument("--max-items", type=int, default=None, help="Cap on synced posts")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent worker threads")
    parser.add_argument("--delay", type=float, default=0.3, help="Per-request delay seconds")
    parser.add_argument("--limit", type=int, default=None, help="Limit crawled posts this run")
    parser.add_argument("--status", action="store_true", help="Print staging DB metrics")
    parser.add_argument("--resolve", action="store_true", help="Unwrap /redirect/ bridges into final CDN URLs")
    parser.add_argument("--db-path", type=Path, default=DB_PATH, help="Staging DB path")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    base_url = get_active_base_url(SITE_NAME, DEFAULT_BASE_URL)

    if args.status:
        print_status(db_path)
        return
    if args.sync_api:
        sync_api_to_db(db_path, base_url, args.max_items)
        return
    run_crawler(db_path, base_url, workers=args.workers, delay=args.delay, limit=args.limit,
                resolve_redirects=args.resolve)


if __name__ == "__main__":
    main()
