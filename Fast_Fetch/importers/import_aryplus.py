#!/usr/bin/env python3
"""
import_aryplus.py — staging importer for ARY Plus (https://aryplus.tv).

Everything below was measured on 2026-10-28, not assumed:

* `sitemap.xml` is an index of 1,019 sub-sitemaps plus `sitemap-genres.xml`;
  each hex sub-sitemap carries exactly one `/title/<24-hex>` URL.
* A stale title id answers HTTP 200 with a 5,208-byte app shell and no JSON-LD.
  That is a dead catalog row, so this importer parks it instead of inventing one.
* A live title page is server-rendered: a schema.org `TVSeries`/`Movie` JSON-LD
  block, and a Next.js RSC payload holding `episodes[]`, `bannerUrl`, `logoUrl`
  and a series-level `videoUrl`.
* Every episode publishes a public HLS master playlist on `vod.aryzap.com`
  (`adp.10.m3u8`, 240p–1080p variants, no `EXT-X-KEY`, `drmEnabled:false` on
  every measured row). The master answers 200 `application/vnd.apple.mpegurl`
  to a plain request — no Referer, no cookies, no token.

Two shapes need different treatment and the site does not label them:

* series — `episodes[]` is the playable unit; the series-level `videoUrl` is the
  trailer (it equals the JSON-LD `trailer.contentUrl`), stored as a trailer.
* single video (telefilm, podcast, OST) — no episodes. The site still calls the
  URL a `trailer`, but its JSON-LD duration is the full runtime (01:18:02 for
  Jahez Mubarak), so the URL is stored as the full release, not a trailer.

Sources are stored as the durable unsigned master URL. Nothing here mints a
play-time URL, so there is no per-play token to leak or persist.
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
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SITE = "aryplus"
BASE_URL = "https://aryplus.tv"
SITEMAP_INDEX = f"{BASE_URL}/sitemap.xml"
IMAGE_HOST = "https://images.aryplus.tv/"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/aryplus.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SITEMAP_TIMEOUT = 45
PAGE_TIMEOUT = 60
VERIFY_TIMEOUT = 25
SITEMAP_WORKERS = 4
QUEUED_SCRAPE_STATES = (0, 2)
MAX_SCRAPE_ATTEMPTS = 3
FAILURE_LEDGER_LIMIT = 8
LEGAL_MEDIA_TYPES = ("movie", "series")
DEFAULT_SOURCE_STATUS = "unverified"
SERVICE_HLS = "aryzap-vod"
PLAYBACK_HLS = "hls"
# The only host a row may name as a stream. Measured: every playable master
# playlist of every sampled title lives here; nothing else was ever a player.
ALLOWED_SOURCE_HOST_RE = re.compile(r"^vod\.aryzap\.com$", re.I)
STOP_REQUESTED = False

# A parked row is not terminal until the attempt cap. The first crawl parked
# 538 rows at error_count=1 with no recorded reason; those are eligible again.
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
    "bridge_url", "origin_url",
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


def _signal_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"\n[!] [{SITE}] signal {signum}: finishing the rows already in flight, "
          f"then stopping. Run again to resume.", flush=True)


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


def _build_ssl_context(insecure: bool = True) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


_SSL_CONTEXT = _build_ssl_context()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # surface the 3xx as HTTPError instead of following it


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    _NoRedirectHandler(),
    urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
)
_TRANSPORT_ERROR = threading.local()


def transport_error() -> str:
    """The last transport error seen by this thread, e.g. 'OSError: ...'."""
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

LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
HEX_SITEMAP_RE = re.compile(r"/sitemap/([0-9a-f]{24})\.xml$", re.I)
TITLE_URL_RE = re.compile(r"^https://aryplus\.tv/title/(?P<id>[0-9a-f]{24})$", re.I)


def parse_locs(xml: str) -> list[str]:
    return [html_mod.unescape(loc.strip()) for loc in LOC_RE.findall(xml or "")]


def title_id(url: str | None) -> str:
    match = TITLE_URL_RE.match((url or "").strip())
    return match.group("id") if match else ""


def sync_catalog(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                 verbose: bool = True) -> int:
    """
    Reads the sitemap index, then each hex sub-sitemap, and queues its one
    title URL. The sub-sitemap fetch is deliberate: it proves the mapping
    instead of assuming id equality, at one small request per title.
    """
    status, _final, index_xml, _headers = http_get(SITEMAP_INDEX, timeout=SITEMAP_TIMEOUT)
    if status != 200:
        print(f"[!] [{SITE}] sitemap index -> HTTP {status}", flush=True)
        return 0
    subs = [loc for loc in parse_locs(index_xml) if HEX_SITEMAP_RE.search(loc)]
    if verbose:
        print(f"[*] [{SITE}] sitemap index: {len(subs)} title sitemaps", flush=True)
    if limit:
        subs = subs[:limit]

    titles: list[tuple[str, str]] = []
    seen: set[str] = set()

    def work(sub: str):
        sub_status, _f, sub_xml, _h = http_get(sub, timeout=SITEMAP_TIMEOUT)
        if sub_status != 200:
            return sub, []
        return sub, [loc for loc in parse_locs(sub_xml) if title_id(loc)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=SITEMAP_WORKERS) as pool:
        for sub, locs in pool.map(work, subs):
            if STOP_REQUESTED:
                break
            if not locs:
                print(f"[!] [{SITE}] {sub} carried no title URL", flush=True)
                continue
            for loc in locs:
                if loc in seen:
                    continue
                seen.add(loc)
                titles.append((loc, title_id(loc)))

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        before = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        for loc, tid in titles:
            conn.execute(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                VALUES (?, NULL, ?, 0, ?, 0)
                ON CONFLICT(loc) DO UPDATE SET slug = excluded.slug;
                """,
                (loc, tid, json.dumps({"id": tid}, ensure_ascii=False)),
            )
        conn.execute("UPDATE sitemap_cache SET scraped = 0 WHERE scraped = 2;")
        after = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    if verbose:
        print(f"[✓] [{SITE}] queued {len(titles)} titles "
              f"({after - before} new, {after} total).", flush=True)
    return after - before


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
NEXT_PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
# Measured shape of the series banner object in the RSC payload.
SERIES_OBJ_RE = re.compile(
    r'\{"_id":"(?P<id>[0-9a-f]{24})","year":"(?P<year>[^"]*)",'
    r'"bannerUrl":"(?P<banner>[^"]+)","videoUrl":"(?P<video>[^"]+)",'
    r'"title":"(?P<title>(?:[^"\\]|\\.)*)","logoUrl":"(?P<logo>[^"]+)"')
META_KEYWORDS_RE = re.compile(
    r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']*)["\']', re.I)
META_DESCRIPTION_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.I)
HLS_URL_RE = re.compile(r"https://[^\s\"'<>\\]+\.m3u8(?:\?[^\s\"'<>\\]*)?", re.I)


def rsc_payload(html: str) -> str:
    """Joins the `self.__next_f.push` flight strings into one readable stream."""
    parts: list[str] = []
    for match in NEXT_PUSH_RE.finditer(html or ""):
        try:
            arr = json.loads(match.group(1))
        except Exception:
            continue
        if isinstance(arr, list) and len(arr) > 1 and isinstance(arr[1], str):
            parts.append(arr[1])
    return "".join(parts)


def json_array_after(text: str, key: str) -> list | None:
    """First `"key": [ ... ]` that parses as a JSON array, bracket-matched."""
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*:\s*\[')
    start = 0
    while True:
        match = pattern.search(text, start)
        if not match:
            return None
        begin = match.end() - 1
        depth = 0
        in_str = False
        escaped = False
        pos = begin
        while pos < len(text):
            char = text[pos]
            if in_str:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_str = False
            elif char == '"':
                in_str = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    break
            pos += 1
        try:
            value = json.loads(text[begin:pos + 1])
        except Exception:
            start = match.end()
            continue
        if isinstance(value, list):
            return value
        start = match.end()


def parse_ld(html: str) -> dict | None:
    """The catalog JSON-LD block, i.e. the one that names the title."""
    for match in LD_JSON_RE.finditer(html or ""):
        try:
            data = json.loads(match.group(1))
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for cand in candidates:
            if isinstance(cand, dict) and cand.get("name") and cand.get("@type") in (
                    "TVSeries", "Movie", "TVEpisode", "VideoObject"):
                return cand
    return None


def find_episodes(rsc: str) -> list[dict]:
    for key in ("episodes", "episodesList", "videos"):
        rows = json_array_after(rsc, key)
        if rows and isinstance(rows[0], dict) and "videoSource" in rows[0]:
            return [r for r in rows if isinstance(r, dict)]
    return []


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html_mod.unescape(str(value))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_hms(text: str | None) -> int | None:
    if not text:
        return None
    match = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.\d+)?$", str(text).strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return (int(hours or 0) * 3600) + (int(minutes) * 60) + int(seconds)


def year_from(value: str | None) -> int | None:
    match = re.search(r"(19|20)\d{2}", value or "")
    return int(match.group(0)) if match else None


def is_adult_rating(rating: str | None) -> int:
    return 1 if (rating or "").strip().upper() in {"18+", "18", "A", "R", "TV-MA"} else 0


def media_type_for(ld: dict) -> str:
    return "series" if ld.get("@type") == "TVSeries" else "movie"


def host_allowed(url: str | None) -> bool:
    match = re.match(r"^https?://([^/:]+)", (url or "").strip(), re.I)
    return bool(match and ALLOWED_SOURCE_HOST_RE.match(match.group(1)))


def image_url(path: str | None) -> str:
    value = (path or "").strip()
    if not value or value == "$undefined":
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return IMAGE_HOST + value.lstrip("/")


def subtitle_tracks(episode: dict) -> list[dict]:
    rows = episode.get("subtitles")
    if not isinstance(rows, list):
        return []
    tracks = []
    for row in rows:
        if isinstance(row, str):
            tracks.append({"url": image_url(row), "language": ""})
        elif isinstance(row, dict):
            url = row.get("url") or row.get("src") or row.get("file") or row.get("link")
            if url:
                tracks.append({
                    "url": image_url(url),
                    "language": row.get("language") or row.get("lang") or row.get("label") or "",
                })
    return tracks


def build_record(ld: dict, rsc: str, html: str, url: str) -> dict:
    tid = title_id(url)
    title = clean_text(ld.get("name"))
    genres = ld.get("genre") or []
    if isinstance(genres, str):
        genres = [genres]
    genres = [clean_text(g) for g in genres if clean_text(g)]
    actors = [clean_text(a.get("name")) for a in (ld.get("actors") or [])
              if isinstance(a, dict) and clean_text(a.get("name"))]
    directors = [clean_text(d.get("name")) for d in (ld.get("directors") or [])
                 if isinstance(d, dict) and clean_text(d.get("name"))]
    trailer = ld.get("trailer") if isinstance(ld.get("trailer"), dict) else {}
    series_obj = SERIES_OBJ_RE.search(rsc)
    banner = series_obj.group("banner") if series_obj else ""
    logo = series_obj.group("logo") if series_obj else ""
    series_video = series_obj.group("video") if series_obj else ""
    for field, pattern in (("bannerUrl", r'"bannerUrl":"([^"]+)"'),
                           ("logoUrl", r'"logoUrl":"([^"]+)"'),
                           ("videoUrl", r'"videoUrl":"([^"]+)"')):
        if (banner if field == "bannerUrl" else logo if field == "logoUrl"
                else series_video):
            continue
        found = re.search(pattern, rsc)
        if not found:
            continue
        if field == "bannerUrl":
            banner = found.group(1)
        elif field == "logoUrl":
            logo = found.group(1)
        else:
            series_video = found.group(1)
    if series_video == "$undefined":
        series_video = ""
    if not series_video:
        series_video = clean_text(trailer.get("contentUrl"))
    rating = clean_text(ld.get("contentRating"))
    episodes = find_episodes(rsc)
    published = [e for e in episodes if str(e.get("status", "published")).lower() == "published"
                 and str(e.get("published", "true")).lower() != "false"]
    media_type = media_type_for(ld)
    year = year_from(ld.get("dateCreated") or ld.get("startDate") or ld.get("uploadDate"))
    if year is None and series_obj:
        year = year_from(series_obj.group("year"))
    meta_description = META_DESCRIPTION_RE.search(html or "")
    description = clean_text(ld.get("description")) or clean_text(
        meta_description.group(1) if meta_description else "")
    meta_keywords = META_KEYWORDS_RE.search(html or "")
    keywords = [clean_text(k) for k in (
        (meta_keywords.group(1) if meta_keywords else "").split(",")) if clean_text(k)]

    releases, counts = releases_for(
        published, episodes, title, series_video, trailer, media_type)

    record = {
        "canonical_key": f"{SITE}:{tid}",
        "title": title,
        "clean_title": title,
        "year": year,
        "media_type": media_type if media_type in LEGAL_MEDIA_TYPES else "series",
        "poster_url": image_url(ld.get("image")),
        "backdrop_url": image_url(banner) or image_url(ld.get("image")),
        "backdrop_urls": json.dumps(
            [u for u in (image_url(banner), image_url(ld.get("image"))) if u],
            ensure_ascii=False),
        "synopsis": description,
        "genres": ", ".join(genres),
        "director": ", ".join(directors),
        "cast_names": ", ".join(actors),
        "duration": clean_text(trailer.get("duration")) if media_type == "movie" else None,
        "release_date": clean_text(ld.get("dateCreated") or ld.get("startDate")) or None,
        "languages": "Urdu",
        "industry": "Pakistani",
        "country": "PK",
        "seasons": ld.get("numberOfSeasons"),
        "url": url,
        "slug": tid,
        "is_18_plus": is_adult_rating(rating),
        "is_animated": 0,
        "releases": releases,
        "raw_meta": {
            "title_id": tid,
            "content_rating": rating,
            "logo_url": image_url(logo),
            "banner_url": image_url(banner),
            "series_video_url": series_video,
            "trailer": {
                "name": clean_text(trailer.get("name")),
                "url": clean_text(trailer.get("contentUrl")),
                "duration": clean_text(trailer.get("duration")),
                "thumbnail": image_url(trailer.get("thumbnailUrl")),
                "upload_date": clean_text(trailer.get("uploadDate")),
            },
            "episodes_total": len(episodes),
            "episodes_published": len(published),
            "episodes_without_stream": counts["no_stream"],
            "episodes_rejected_host": counts["bad_host"],
            "episodes_drm": counts["drm"],
            "episode_seconds_total": counts["seconds"],
            "subtitles_tracks": counts["subtitles"],
            "subtitle_tracks": counts["tracks"],
            "keywords": keywords[:40],
            "schema_type": ld.get("@type"),
            "parser": "aryplus.v1",
        },
    }
    return record


def releases_for(published: list[dict], all_episodes: list[dict], show_title: str,
                 series_video: str, trailer: dict, media_type: str) -> tuple[list[dict], dict]:
    """Episodes for a series; one full release for a single video."""
    counts = {"no_stream": 0, "bad_host": 0, "drm": 0, "seconds": 0,
              "subtitles": 0, "tracks": []}
    releases: list[dict] = []
    seen_urls: set[str] = set()

    for episode in published:
        source_url = (episode.get("videoSource") or "").strip()
        if not source_url or not HLS_URL_RE.match(source_url):
            counts["no_stream"] += 1
            continue
        if not host_allowed(source_url):
            counts["bad_host"] += 1
            continue
        drm = bool(episode.get("drmEnabled"))
        number = episode.get("videoEpNumber")
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = None
        season = episode.get("seasonNumber") or episode.get("videoSeasonNumber") or 1
        try:
            season = int(season)
        except (TypeError, ValueError):
            season = 1
        length = episode.get("videoLength")
        try:
            length = int(length)
        except (TypeError, ValueError):
            length = None
        if length:
            counts["seconds"] += length
        tracks = subtitle_tracks(episode)
        counts["subtitles"] += len(tracks)
        for track in tracks:
            if len(counts["tracks"]) < 500:
                counts["tracks"].append({"episode": number, **track})
        label = clean_text(episode.get("title")) or (
            f"Episode {number}" if number else "Episode")
        seen_urls.add(source_url)
        releases.append({
            "label": label,
            "quality": "auto",
            "resolution": None,
            "size_bytes": None,
            "codec": None,
            "season_number": season,
            "episode_number": number,
            "audio_languages": "Urdu",
            "sources": [{
                "source_name": f"{show_title} — {label}",
                "service": SERVICE_HLS,
                "resource_id": episode.get("_id"),
                "source_url": source_url,
                "final_url": source_url,
                "playback_type": PLAYBACK_HLS,
                "status": "blocked" if drm else DEFAULT_SOURCE_STATUS,
                "is_temporary": 0,
                "quality": "auto",
                "subtitles": tracks,
                "duration_seconds": length,
            }],
        })
        if drm:
            counts["drm"] += 1

    if releases and series_video and host_allowed(series_video) \
            and series_video not in seen_urls:
        releases.insert(0, {
            "label": "Trailer",
            "quality": "auto",
            "resolution": None,
            "size_bytes": None,
            "codec": None,
            "season_number": None,
            "episode_number": 0,
            "audio_languages": "Urdu",
            "sources": [{
                "source_name": f"{show_title} — Trailer",
                "service": SERVICE_HLS,
                "resource_id": title_id_for_trailer(series_video),
                "source_url": series_video,
                "final_url": series_video,
                "playback_type": PLAYBACK_HLS,
                "status": DEFAULT_SOURCE_STATUS,
                "is_temporary": 0,
                "quality": "auto",
                "subtitles": [],
                "duration_seconds": parse_hms(trailer.get("duration")),
            }],
        })

    # A page with episodes is a series: a rejected episode never turns the
    # series-level URL into a "full" release. Only a page without episodes is
    # a single video, where the site labels the full runtime a "trailer".
    if media_type == "movie" or not all_episodes:
        single = series_video or clean_text(trailer.get("contentUrl"))
        if single and HLS_URL_RE.match(single):
            if not host_allowed(single):
                counts["bad_host"] += 1
            else:
                seconds = parse_hms(trailer.get("duration"))
                counts["seconds"] += seconds or 0
                releases.append({
                    "label": "Full",
                    "quality": "auto",
                    "resolution": None,
                    "size_bytes": None,
                    "codec": None,
                    "season_number": None,
                    "episode_number": None,
                    "audio_languages": "Urdu",
                    "sources": [{
                        "source_name": f"{show_title} — Full",
                        "service": SERVICE_HLS,
                        "resource_id": title_id_for_trailer(single),
                        "source_url": single,
                        "final_url": single,
                        "playback_type": PLAYBACK_HLS,
                        "status": DEFAULT_SOURCE_STATUS,
                        "is_temporary": 0,
                        "quality": "auto",
                        "subtitles": [],
                        "duration_seconds": seconds,
                    }],
                })
        elif not all_episodes:
            counts["no_stream"] += 1
    return releases, counts


TRAILER_ID_RE = re.compile(r"/([0-9a-f]{20,})(?:/adp)?", re.I)


def title_id_for_trailer(url: str) -> str:
    match = TRAILER_ID_RE.search(url or "")
    return match.group(1)[:40] if match else ""


def parse_title_page(html: str, url: str) -> dict | None:
    """A live title page -> record; a stale app shell -> None."""
    ld = parse_ld(html)
    if ld is None:
        return None
    return build_record(ld, rsc_payload(html), html, url)


def classify(post: dict) -> dict:
    return {"industry": post.get("industry") or "Pakistani",
            "country": post.get("country") or "PK"}


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
    source_site TEXT DEFAULT 'aryplus',
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
    playback_type TEXT DEFAULT 'hls',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_aryplus_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_aryplus_posts_type ON posts(media_type);
CREATE INDEX IF NOT EXISTS idx_aryplus_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_aryplus_sources_playback ON sources(playback_type);
CREATE INDEX IF NOT EXISTS idx_aryplus_releases_post ON releases(post_canonical_key);
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
            cls = classify(post)
            row = {
                "canonical_key": post["canonical_key"],
                "title": post["title"],
                "clean_title": post["clean_title"],
                "year": post.get("year"),
                "media_type": post.get("media_type")
                              if post.get("media_type") in LEGAL_MEDIA_TYPES
                              else "series",
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
                "industry": cls["industry"],
                "country": cls["country"],
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

            page_url = post.get("url")
            for rel in releases:
                cur = conn.execute(
                    f"INSERT INTO releases ({', '.join(RELEASE_COLUMNS)})"
                    f" VALUES ({', '.join('?' * len(RELEASE_COLUMNS))});",
                    (post["canonical_key"], rel.get("label"), rel.get("quality"),
                     rel.get("resolution"), rel.get("size_bytes"), rel.get("codec"),
                     rel.get("season_number"), rel.get("episode_number"),
                     rel.get("audio_languages"), rel.get("bridge_url"), page_url),
                )
                totals["releases_written"] += 1
                for src in rel.get("sources") or []:
                    conn.execute(
                        f"INSERT INTO sources ({', '.join(SOURCE_COLUMNS)})"
                        f" VALUES ({', '.join('?' * len(SOURCE_COLUMNS))});",
                        (cur.lastrowid, src.get("source_name"), src.get("service"),
                         src.get("resource_id"), src.get("source_url"),
                         src.get("final_url") or src.get("source_url"),
                         src.get("playback_type", PLAYBACK_HLS),
                         src.get("status", DEFAULT_SOURCE_STATUS),
                         int(src.get("is_temporary") or 0),
                         src.get("quality") or rel.get("quality"),
                         src.get("last_checked")),
                    )
                    totals["sources_written"] += 1

            if page_url:
                conn.execute(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, raw_json, error_count)
                    VALUES (?, NULL, ?, 1, ?, 0)
                    ON CONFLICT(loc) DO UPDATE SET
                        scraped = 1, slug = excluded.slug,
                        raw_json = excluded.raw_json, error_count = 0;
                    """,
                    (page_url, row["slug"],
                     json.dumps(post.get("queue_payload") or {}, ensure_ascii=False)),
                )
        conn.commit()
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Queue and crawl
# ---------------------------------------------------------------------------


def _parse_record(loc: str, raw_json: str | None, page_html: str) -> tuple[dict | None, str]:
    if not (page_html or "").strip():
        return None, "empty-page"
    record = parse_title_page(page_html, loc)
    if record is None:
        return None, "no-jsonld"
    try:
        payload = json.loads(raw_json) if raw_json else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["status"] = "ok"
    record["queue_payload"] = payload
    return record, ""


def _failure(kind: str, http_status: int | None = None, final_url: str | None = None,
             detail: str = "", exception: str | None = None) -> dict:
    return {"kind": kind, "http_status": http_status, "final_url": final_url,
            "detail": detail, "exception": exception}


def _bump_error(db_path: Path, loc: str, failure: dict, park_now: bool = False) -> None:
    """
    One failed attempt -> one ledger entry in raw_json. Stays retryable (state 2)
    until the attempt cap, then parks as state -1 with status=dead and the
    reason kept. park_now is reserved for hard HTTP verdicts (404/410).
    """
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
        payload.setdefault("id", (row[2] if row else None) or title_id(loc))
        history = payload.get("failures")
        history = history if isinstance(history, list) else []
        if not history and attempts > 1:
            # The first crawl parked the row without recording why. Keep the
            # count honest rather than pretending the attempt never happened.
            history = [{
                "at": None, "attempt": 1, "kind": "legacy-unrecorded",
                "http_status": None, "final_url": None,
                "detail": "first attempt predates failure logging; reason unavailable",
            }]
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
    if verbose:
        print(f"[*] [{SITE}] {len(rows)} titles pending "
              f"(workers={workers}, delay={delay}s).", flush=True)

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "dead_ids": 0, "failed": 0}
    if not rows:
        return totals

    def work(row):
        if STOP_REQUESTED:
            return None
        time.sleep(delay)
        # One request per attempt: retries live in the sitemap_cache state
        # machine, so a bad row never blocks the queue with hidden sleeps.
        status, final, page, headers = http_get(
            row["loc"], timeout=PAGE_TIMEOUT, retries=0, follow_redirects=False)
        if STOP_REQUESTED and status == 0:
            return None  # aborted by the stop signal; do not spend an attempt
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
        record, verdict = _parse_record(row["loc"], row["raw_json"], page)
        if record is None:
            if final and final.rstrip("/") != row["loc"].rstrip("/"):
                return None, _failure("redirect", status, final, f"landed on {final}")
            return None, _failure(verdict, status, final, verdict)
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
                totals["dead_ids"] += 1
                _bump_error(db_path, queued["loc"], failure or _failure("unknown"),
                            park_now=(failure or {}).get("kind") in
                            ("http-404", "http-410"))
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
        print(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
              f"releases={totals['releases']} sources={totals['sources']} "
              f"dead={totals['dead_ids']} failed={totals['failed']} "
              f"in {time.time() - started:.0f}s", flush=True)
    return totals


def _flush(db_path: Path, batch: list[dict], totals: dict) -> None:
    if not batch:
        return
    written = export_staging(db_path, batch)
    totals["posts"] += written["posts_written"]
    totals["releases"] += written["releases_written"]
    totals["sources"] += written["sources_written"]
    totals["dead_ids"] += written["skipped"]
    batch.clear()


def parse_page(url: str, verify: bool = False) -> dict | None:
    status, _final, page, _headers = http_get(url)
    if status != 200:
        print(f"[!] [{SITE}] {url} -> HTTP {status}", flush=True)
        return None
    record = parse_title_page(page, url)
    if record and verify:
        for rel in record.get("releases") or []:
            for src in rel.get("sources") or []:
                verdict = verify_hls(src["source_url"])
                src["status"] = verdict["status"]
                src["last_checked"] = int(time.time())
                src["verify_detail"] = verdict
    return record


# ---------------------------------------------------------------------------
# Verification: one bounded request per source, no retries
# ---------------------------------------------------------------------------


def verify_hls(url: str, timeout: int = VERIFY_TIMEOUT) -> dict:
    """
    One GET, first bytes only. A 200 with `#EXTM3U` is active; an encrypted
    playlist (`EXT-X-KEY` whose METHOD is not NONE) is blocked; a 200 that is
    not a playlist is dead; a transport failure is unverified and never retried.
    """
    verdict = {"status": DEFAULT_SOURCE_STATUS, "http_status": None,
               "content_type": "", "is_hls": False, "drm": False,
               "variants": 0, "best_resolution": ""}
    if not url:
        return verdict
    try:
        request = _request(url, {"Range": "bytes=0-8191"})
        with _open(request, timeout=timeout) as resp:
            verdict["http_status"] = resp.status
            verdict["content_type"] = resp.headers.get("content-type", "")
            text = resp.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        verdict["http_status"] = exc.code
        verdict["status"] = ("blocked" if exc.code in (401, 403, 451)
                             else "dead" if exc.code in (404, 410) else DEFAULT_SOURCE_STATUS)
        return verdict
    except Exception:
        return verdict

    body = text.lstrip("\ufeff \r\n\t")
    verdict["is_hls"] = body.startswith("#EXTM3U")
    if verdict["is_hls"]:
        keys = re.findall(r"#EXT-X-KEY:([^\r\n]+)", text)
        verdict["drm"] = any(
            re.search(r"METHOD=(?!NONE)\w+", key, re.I) for key in keys)
        variants = re.findall(r"RESOLUTION=(\d+x\d+)", text)
        verdict["variants"] = len(variants)
        if variants:
            verdict["best_resolution"] = max(
                variants, key=lambda v: int(v.split("x")[0]) * int(v.split("x")[1]))
    verdict["status"] = (
        "blocked" if (verdict["drm"] or verdict["http_status"] in (401, 403, 451))
        else "active" if (verdict["http_status"] == 200 and verdict["is_hls"])
        else "dead" if (verdict["http_status"] in (404, 410)
                        or (verdict["http_status"] == 200 and not verdict["is_hls"]))
        else DEFAULT_SOURCE_STATUS)
    return verdict


def sample_verified(rows: int = 15, db_path: Path | str = DEFAULT_DB_PATH,
                    verbose: bool = True, write: bool = True) -> dict:
    """Round-robin across posts so one series cannot fill the sample."""
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    report = {"checked": 0, "rows": [], "statuses": {}, "http": {},
              "content_types": {}, "resolutions": {}, "variants": []}
    try:
        ensure_schema(conn)
        picks = conn.execute(
            """SELECT s.id AS source_id, s.source_url, s.service, s.status,
                      r.label, r.episode_number, p.clean_title
               FROM sources s
               JOIN releases r ON r.id = s.release_id
               JOIN posts p ON p.canonical_key = r.post_canonical_key
               WHERE s.status = ?
               ORDER BY p.canonical_key, r.episode_number;""",
            (DEFAULT_SOURCE_STATUS,)).fetchall()
        round_robin: list = []
        queues: dict[str, list] = {}
        order: list[str] = []
        for pick in picks:
            show = pick["clean_title"]
            if show not in queues:
                queues[show] = []
                order.append(show)
            queues[show].append(pick)
        while len(round_robin) < len(picks):
            for show in order:
                if queues[show]:
                    round_robin.append(queues[show].pop(0))
        chosen = round_robin[:max(0, rows)]
        for pick in chosen:
            if STOP_REQUESTED:
                break
            verdict = verify_hls(pick["source_url"])
            status = str(verdict["status"])
            report["rows"].append({
                "post": pick["clean_title"], "label": pick["label"],
                "episode": pick["episode_number"], "status": status,
                "http_status": verdict["http_status"],
                "content_type": verdict["content_type"],
                "best_resolution": verdict["best_resolution"],
                "variants": verdict["variants"], "drm": verdict["drm"],
                "url": pick["source_url"],
            })
            report["checked"] += 1
            report["statuses"][status] = report["statuses"].get(status, 0) + 1
            key = str(verdict["http_status"])
            report["http"][key] = report["http"].get(key, 0) + 1
            ctype = str(verdict["content_type"] or "")
            report["content_types"][ctype] = report["content_types"].get(ctype, 0) + 1
            if verdict["best_resolution"]:
                res = verdict["best_resolution"]
                report["resolutions"][res] = report["resolutions"].get(res, 0) + 1
            report["variants"].append(verdict["variants"])
            if write:
                conn.execute(
                    "UPDATE sources SET status = ?, last_checked = ? WHERE id = ?;",
                    (status if status in ("active", "dead", "blocked") else
                     DEFAULT_SOURCE_STATUS, int(time.time()), pick["source_id"]))
        if write:
            conn.commit()
    finally:
        conn.close()
    if verbose:
        print(json.dumps({k: v for k, v in report.items() if k != "rows"},
                         indent=2, ensure_ascii=False), flush=True)
        for line in report["rows"]:
            print(f"  {line['status']:<11} {str(line['http_status']):<5} "
                  f"{line['best_resolution']:<10} v={line['variants']:<2} "
                  f"{line['post'][:30]:30} {str(line['label'])[:26]}", flush=True)
    return report


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
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
            "retryable": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1 "
                "AND error_count < ?", (MAX_SCRAPE_ATTEMPTS,)).fetchone()[0],
            "dead": conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1 "
                "AND error_count >= ?", (MAX_SCRAPE_ATTEMPTS,)).fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "adult_flagged": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "with_synopsis": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE synopsis IS NOT NULL").fetchone()[0],
            "with_year": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE year IS NOT NULL").fetchone()[0],
            "with_poster": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE poster_url IS NOT NULL").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "source_status": dict(conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()),
            "playback_types": dict(conn.execute(
                "SELECT playback_type, COUNT(*) FROM sources GROUP BY playback_type")
                .fetchall()),
            "histogram": [f"{a}|{b}|{c} = {n}" for a, b, c, n in conn.execute(
                "SELECT service, playback_type, status, COUNT(*) FROM sources "
                "GROUP BY service, playback_type, status "
                "ORDER BY COUNT(*) DESC").fetchall()],
            "media_types": dict(conn.execute(
                "SELECT media_type, COUNT(*) FROM posts GROUP BY media_type").fetchall()),
            "episodes": conn.execute(
                "SELECT COUNT(*) FROM releases WHERE episode_number > 0").fetchone()[0],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_aryplus.py",
        description=f"ARY Plus staging importer ({BASE_URL} -> {DEFAULT_DB_PATH})")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "crawl", "parse", "sample", "stats"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rows", type=int, default=15)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--batch-size", type=int, default=20, dest="batch_size")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--url", help="single title URL for parse")
    parser.add_argument("--no-write", action="store_true", dest="no_write",
                        help="with sample: report the verdicts, store none of them")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    db = Path(args.db)
    verbose = not args.quiet

    if args.command == "sync":
        sync_catalog(limit=args.limit, db_path=db, verbose=verbose)
    elif args.command == "crawl":
        crawl_pending(limit=args.limit, db_path=db, workers=args.workers,
                      delay=args.delay, batch_size=args.batch_size, verbose=verbose)
    elif args.command == "sample":
        sample_verified(rows=args.rows, db_path=db, verbose=verbose,
                        write=not args.no_write)
    elif args.command == "stats":
        print(json.dumps(stats(db), indent=2, ensure_ascii=False))
        return 0
    else:
        if not args.url:
            parser.error(f"{args.command} requires --url")
        record = parse_page(args.url, verify=False)
        if record is None:
            print("[!] Page is not a catalog entry.", file=sys.stderr)
            return 1
        print(json.dumps(record, indent=2, ensure_ascii=False, default=str))
    return 0


_install_signal_handlers()

if __name__ == "__main__":
    sys.exit(main())
