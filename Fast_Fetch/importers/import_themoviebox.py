#!/usr/bin/env python3
"""
import_themoviebox.py — themoviebox.xyz into a dedicated staging vault.

The site is a Nuxt 3 SSR app: every page ships its whole render payload in a
single ``<script id="__NUXT_DATA__">`` block. That payload is *not* plain JSON —
Nuxt serialises it with `devalue`, a flat pool of values where every object and
array member is an integer index back into the pool. This module unflattens that
pool (``unflatten``) and then walks the hydrated graph for the works it holds,
pulling:

  * identity   — title, release date / year, duration, genres, dubs, cast
  * artwork    — poster / backdrop, blurHash, avgHueLight, avgHueDark
  * structure  — seasons and episodes (a series page is one work, many releases)
  * media      — the direct CDN streams on ``macdn.aoneroom.com`` (``-ld``/``-sd``
                 /``-hd`` mp4 variants), recorded as ``direct`` sources

Isolation is the whole point: this writes only to the vault named by ``--db``,
which defaults to ``/home/ubuntu/radd-stream-data/themoviebox.db``. It never
imports the production ``fast_fetch.db``/merged catalog and never runs the
unified ``save_scraped_data`` path. A later ``merge_catalogs.py`` run is the only
thing allowed to bring these rows into the unified catalog.

Stdlib only. Polite by default (two fetch workers, a 0.3 s floor between request
starts, batched commits, a memory floor) because this runs on a one-core box.

Usage:
    python3 -S Fast_Fetch/importers/import_themoviebox.py sync
    python3 -S Fast_Fetch/importers/import_themoviebox.py sync --seed https://themoviebox.xyz/movie/foo
    python3 -S Fast_Fetch/importers/import_themoviebox.py crawl --workers 2 --delay 0.3
    python3 -S Fast_Fetch/importers/import_themoviebox.py verify --limit 200
    python3 -S Fast_Fetch/importers/import_themoviebox.py stats
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch  # noqa: E402  (path bootstrap must run first)

SITE = "themoviebox"
BASE_URL = "https://themoviebox.xyz"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/themoviebox.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

#: Service recorded on every source row this importer writes. Kept in one place
#: so the projection's tier lookup and the merge can both name it.
SERVICE = "themoviebox"
#: The site fronts its media on its own CDN with a stable edge, so it is recorded
#: as a tier-1 (low-latency, direct) source rather than an unresolved embed.
SERVICE_TIER = 1
PLAYBACK_DIRECT = "direct"
DEFAULT_SOURCE_STATUS = "active"

#: Politeness defaults. The task's hard floor: two workers, a third of a second
#: between request starts. Both are CLI-overridable downward, never upward past
#: the ceiling below.
DEFAULT_WORKERS = 2
DEFAULT_DELAY = 0.3
MAX_WORKERS = 4
BATCH_SIZE = 20
SITEMAP_TIMEOUT = 30
PAGE_TIMEOUT = 30
MAX_CHILD_SITEMAPS = 40
RATE_LIMIT_STATUS = 429
MAX_SCRAPE_ATTEMPTS = 3
FAILURE_LEDGER_LIMIT = 8

#: The directive's hard floor: stop before the box thrashes.
MIN_MEM_AVAILABLE_MB = 2500
MIN_SWAP_FREE_MB = 800

#: Hosts this site serves its own media and art from. A direct stream is only
#: trusted when it lives on one of these; anything else in the payload is an ad
#: or a trailer and is dropped rather than staged.
MEDIA_HOST_HINTS = ("aoneroom.com",)
ART_HOST_HINTS = ("aoneroom.com",)

STOP_REQUESTED = False
_RATE_LIMITED = threading.Event()

NUXT_SCRIPT_RE = re.compile(
    r'<script[^>]*\bid\s*=\s*["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
    re.I | re.S)
MEDIA_URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?\.(?:mp4|m3u8)(?:\?[^\s\"'<>\\]*)?", re.I)
LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)
LASTMOD_RE = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.I | re.S)
YEAR_RE = re.compile(r"(19|20)\d{2}")

TITLE_KEYS = ("title", "name", "originalTitle", "original_title", "cleanTitle")
DATE_KEYS = ("releaseDate", "release_date", "airDate", "firstAirDate", "date")
SYNOPSIS_KEYS = ("synopsis", "overview", "description", "plot", "summary")
GENRE_KEYS = ("genres", "genre")
POSTER_KEYS = ("posterUrl", "poster_url", "poster", "image", "cover", "thumbnail")
BACKDROP_KEYS = ("backdropUrl", "backdrop_url", "backdrop", "banner")
DURATION_KEYS = ("duration", "runtime")
EPISODE_KEYS = ("episodeNumber", "episode_number", "episode")
SEASON_KEYS = ("seasonNumber", "season_number", "season")
CAST_KEYS = ("cast", "staffList", "staff", "actors")
DUB_KEYS = ("dubs", "languages", "audio")
RATING_KEYS = ("rating", "imdbRating", "imdb_rating", "voteAverage")
ADULT_FLAG_KEYS = ("isPornographic", "is_pornographic", "isAdult", "is_adult",
                   "porn")
HIGH_RISK_KEYS = ("webHighRisk", "web_high_risk", "highRisk", "isRestricted",
                  "restricted")

# ---------------------------------------------------------------------------
# devalue / __NUXT_DATA__ unflattening
# ---------------------------------------------------------------------------

class _Hole:
    """Array hole marker (devalue's -2). Drop it rather than store a sentinel."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<hole>"


_HOLE = _Hole()
_NI = object()  # "not an index" sentinel


def _special(value: int):
    return {
        -1: None,
        -2: _HOLE,
        -3: float("nan"),
        -4: float("inf"),
        -5: float("-inf"),
        -6: -0.0,
    }.get(value, _NI)


def unflatten(pool):
    """Hydrate a devalue flat pool back into ordinary Python containers.

    Nuxt's ``__NUXT_DATA__`` is ``devalue.stringify`` output: a JSON *array* where
    every container lives at an integer slot and every member is an integer index
    back into that array. Negative indices are devalue's out-of-band values
    (``undefined``, hole, ``NaN``, ``±Infinity``, ``-0``). A payload that is
    already plain JSON (an object, or a scalar) is returned unchanged so the same
    reader tolerates sites that ship either form.
    """
    if not isinstance(pool, list) or not pool:
        return pool

    cache: dict = {}

    def typed(slot: list):
        tag = slot[0]
        if tag == "Date":
            raw = slot[1] if len(slot) > 1 else None
            value = hydrate(raw) if isinstance(raw, int) else raw
            return str(value) if value is not None else None
        if tag == "Set":
            return [hydrate(x) for x in slot[1:]]
        if tag == "Map":
            out = {}
            pairs = slot[1:]
            for i in range(0, len(pairs) - 1, 2):
                out[str(hydrate(pairs[i]))] = hydrate(pairs[i + 1])
            return out
        # RegExp / BigInt / anything else: keep the hydrated payload as a string.
        raw = slot[1] if len(slot) > 1 else None
        return str(hydrate(raw) if isinstance(raw, int) else raw)

    def hydrate(index):
        if isinstance(index, bool) or not isinstance(index, int):
            return index  # a literal string/float/bool sits inline
        if index < 0:
            special = _special(index)
            return None if special is _NI else special
        if index >= len(pool):
            return None
        if index in cache:
            return cache[index]
        value = pool[index]
        if isinstance(value, list):
            if value and isinstance(value[0], str) and value[0] in ("Date", "Set",
                                                                    "Map", "RegExp",
                                                                    "BigInt"):
                out = typed(value)
                cache[index] = out
                return out
            out = []
            cache[index] = out  # cache before filling so cycles terminate
            for ref in value:
                item = hydrate(ref)
                if item is not _HOLE:
                    out.append(item)
            return out
        if isinstance(value, dict):
            out = {}
            cache[index] = out
            for key, ref in value.items():
                out[key] = hydrate(ref)
            return out
        cache[index] = value
        return value

    return hydrate(0)


def extract_nuxt_payload(html: str):
    """Returns the hydrated ``__NUXT_DATA__`` graph, or None when the page has none."""
    match = NUXT_SCRIPT_RE.search(html or "")
    if not match:
        return None
    raw = match.group(1).strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return unflatten(parsed)


# ---------------------------------------------------------------------------
# Generic graph helpers
# ---------------------------------------------------------------------------

def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = html_mod.unescape(value).strip()
        return text or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _join_labels(value) -> str | None:
    """Normalises a genre/cast/dub list (strings or ``{name}`` objects) to text."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                return _join_labels(json.loads(text))
            except json.JSONDecodeError:
                return text or None
        return text or None
    if isinstance(value, dict):
        for key in ("name", "title", "label", "language", "value"):
            text = _as_text(value.get(key))
            if text:
                return text
        return None
    if isinstance(value, (list, tuple)):
        parts = [p for p in (_join_labels(v) for v in value) if p]
        return ", ".join(parts) or None
    return None


def _first_text(node, keys) -> str | None:
    if not isinstance(node, dict):
        return None
    for key in keys:
        text = _as_text(node.get(key))
        if text:
            return text
    return None


def _lookup(item: dict, ancestors: list, keys) -> str | None:
    """First non-empty value for ``keys`` on the item, then its nearest ancestor."""
    text = _first_text(item, keys)
    if text:
        return text
    for node in reversed(ancestors):
        text = _first_text(node, keys)
        if text:
            return text
    return None


def _lookup_raw(item: dict, ancestors: list, keys):
    for node in [item] + list(reversed(ancestors)):
        if not isinstance(node, dict):
            continue
        for key in keys:
            if node.get(key) is not None:
                return node.get(key)
    return None


def _year_of(value) -> int | None:
    text = _as_text(value)
    if not text:
        return None
    match = YEAR_RE.search(text)
    return int(match.group(0)) if match else None


def _direct_media_urls(node: dict) -> list[str]:
    """Video URLs a dict holds *directly* (own string members or one-level lists).

    Nested containers are skipped on purpose: the graph walk visits them anyway,
    so a parent never claims a child's streams. Non-CDN video URLs are dropped so
    a stray ad/trailer in the payload cannot be staged as this work's media.
    """
    found: list[str] = []

    def add(value):
        if isinstance(value, str):
            found.extend(MEDIA_URL_RE.findall(value))

    for value in node.values():
        if isinstance(value, str):
            add(value)
        elif isinstance(value, (list, tuple)):
            for element in value:
                add(element)
    if not found:
        return []
    if any(host in url for url in found for host in MEDIA_HOST_HINTS):
        found = [u for u in found if any(h in u for h in MEDIA_HOST_HINTS)]
    seen, ordered = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _collect_candidates(root):
    """(dict, ancestors) for every dict that directly holds a media URL."""
    out = []

    def walk(node, ancestors):
        if isinstance(node, dict):
            if _direct_media_urls(node):
                out.append((node, list(ancestors)))
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value, ancestors + [node])
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value, ancestors)

    walk(root, [])
    return out


def _is_episode(node: dict) -> bool:
    if not isinstance(node, dict):
        return False
    return any(node.get(k) is not None for k in EPISODE_KEYS) or \
        any(node.get(k) is not None for k in SEASON_KEYS)


def _work_anchor(item: dict, ancestors: list) -> dict:
    """The nearest dict that names a work, skipping episode/season containers.

    For a movie page that is the item itself. For a series page the media sits on
    the episode dict, so the work identity is the enclosing series object.
    """
    for node in [item] + list(reversed(ancestors)):
        if isinstance(node, dict) and not _is_episode(node) \
                and _first_text(node, TITLE_KEYS):
            return node
    for node in [item] + list(reversed(ancestors)):
        if isinstance(node, dict) and _first_text(node, TITLE_KEYS):
            return node
    return item


def _quality_from_url(url: str) -> str | None:
    suffix = re.search(r"-(ld|sd|hd)\.mp4", url, re.I)
    if suffix:
        return suffix.group(1).upper()
    for token, label in (("2160", "4K"), ("1080", "1080p"), ("720", "720p"),
                         ("480", "480p")):
        if token in url:
            return label
    return None


def _mime_type(url: str) -> str:
    return "application/vnd.apple.mpegurl" if ".m3u8" in url.lower() else "video/mp4"


def _episode_number(item: dict, ancestors: list) -> int | None:
    raw = _lookup_raw(item, ancestors, EPISODE_KEYS)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _season_number(item: dict, ancestors: list) -> int | None:
    raw = _lookup_raw(item, ancestors, SEASON_KEYS)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        # A season dict may carry its number on a `number` field.
        for node in [item] + list(reversed(ancestors)):
            if isinstance(node, dict) and node.get("number") is not None:
                try:
                    return int(str(node.get("number")).strip())
                except (TypeError, ValueError):
                    return None
        return None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def _flag(item: dict, ancestors: list, keys) -> bool:
    for node in [item] + list(reversed(ancestors)):
        if isinstance(node, dict) and any(_truthy(node.get(k)) for k in keys):
            return True
    return False


def _is_adult(item: dict, ancestors: list, page_url: str, title: str,
              slug: str) -> bool:
    if _flag(item, ancestors, ADULT_FLAG_KEYS):
        return True
    if _flag(item, ancestors, HIGH_RISK_KEYS):
        return True
    if "/web/midnight" in (page_url or "").lower():
        return True
    return bool(fast_fetch.is_adult_title(title or "", slug or ""))


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _sources_from_urls(urls: list[str]) -> list[dict]:
    sources = []
    for url in urls:
        name = url.rsplit("/", 1)[-1].split("?", 1)[0] or url
        sources.append({
            "source_name": SERVICE,
            "service": SERVICE,
            "service_tier": SERVICE_TIER,
            "resource_id": name,
            "source_url": url,
            "final_url": url,
            "playback_type": PLAYBACK_DIRECT,
            "status": DEFAULT_SOURCE_STATUS,
            "is_temporary": 0,
            "quality": _quality_from_url(url),
            "mime_type": _mime_type(url),
            "last_checked": None,
            "raw_meta": {"url": url, "quality_token": _quality_from_url(url)},
        })
    return sources


def _build_releases(item: dict, ancestors: list, work_title: str) -> list[dict]:
    """One release per quality variant so ``release.quality`` stays honest downstream.

    The page lists the same print at ``-ld``/``-sd``/``-hd``. Each is a separate
    quality tier in the unified model, so each becomes its own release carrying a
    single direct source; grouping them would make one release claim three
    resolutions.
    """
    urls = _direct_media_urls(item)
    if not urls:
        return []
    season = _season_number(item, ancestors)
    episode = _episode_number(item, ancestors)
    episode_title = _first_text(item, TITLE_KEYS)
    base_label = work_title
    if episode_title and episode_title.casefold() != work_title.casefold():
        base_label = f"{work_title} — {episode_title}"
    if season is not None:
        base_label += f" S{season:02d}"
    if episode is not None:
        base_label += f"E{episode:02d}" if season is not None \
            else f" Episode {episode:02d}"
    base_label = base_label.strip()
    audio = _join_labels(_lookup_raw(item, ancestors, DUB_KEYS))

    releases = []
    for url in urls:
        quality = _quality_from_url(url)
        releases.append({
            "label": f"{base_label} {quality}".strip() if quality else base_label,
            "quality": quality,
            "resolution": None,
            "size_bytes": None,
            "codec": None,
            "season": season,
            "episode": episode,
            "audio": audio,
            "bridge_url": None,
            "raw_meta": {"page_url": None, "quality_token": quality},
            "sources": _sources_from_urls([url]),
        })
    return releases


def _build_record(anchor: dict, candidates: list, page_url: str) -> dict | None:
    title = _first_text(anchor, TITLE_KEYS) or ""
    if not title:
        return None
    release_date = _lookup(anchor, [], DATE_KEYS)
    year = _year_of(release_date) or _year_of(_lookup(anchor, [], ("year",)))
    slug = page_url.rstrip("/").rsplit("/", 1)[-1] if page_url else ""

    releases = []
    for item, ancestors in candidates:
        for release in _build_releases(item, ancestors, title):
            release["raw_meta"]["page_url"] = page_url
            releases.append(release)
    if not releases:
        return None

    seasons = sorted({r["season"] for r in releases if r["season"] is not None})
    content_type = "series" if (seasons or any(r["episode"] is not None
                                               for r in releases)) else "movie"
    all_ancestors = [anc for _item, anc in candidates for anc in anc]
    is_adult = any(_is_adult(item, anc, page_url, title, slug)
                   for item, anc in candidates)

    backdrop = _lookup(anchor, [], BACKDROP_KEYS)
    record = {
        "canonical_key": fast_fetch.generate_canonical_key(title, year),
        "title": title,
        "clean_title": title,
        "year": year,
        "media_type": content_type,
        "poster_url": _lookup(anchor, [], POSTER_KEYS),
        "backdrop_url": backdrop,
        "backdrop_urls": json.dumps([backdrop]) if backdrop else None,
        "imdb_id": None,
        "tmdb_id": None,
        "imdb_rating": _lookup(anchor, [], RATING_KEYS),
        "synopsis": _lookup(anchor, [], SYNOPSIS_KEYS),
        "genres": _join_labels(_lookup_raw(anchor, [], GENRE_KEYS)),
        "director": None,
        "cast_names": _join_labels(_lookup_raw(anchor, all_ancestors, CAST_KEYS)),
        "duration": _lookup(anchor, [], DURATION_KEYS),
        "release_date": release_date,
        "languages": _join_labels(_lookup_raw(anchor, [], DUB_KEYS)),
        "industry": None,
        "country": None,
        "seasons": json.dumps(seasons) if seasons else None,
        "url": page_url,
        "slug": slug,
        "is_18_plus": 1 if is_adult else 0,
        "is_animated": int(bool(fast_fetch.looks_animated(title))),
        "source_site": SITE,
        "raw_meta": {
            "page_url": page_url,
            "blurHash": _lookup(anchor, [], ("blurHash", "blur_hash")),
            "avgHueLight": _lookup(anchor, [], ("avgHueLight", "avg_hue_light")),
            "avgHueDark": _lookup(anchor, [], ("avgHueDark", "avg_hue_dark")),
            "dubs": _join_labels(_lookup_raw(anchor, [], DUB_KEYS)),
            "isPornographic": _flag(anchor, all_ancestors, ADULT_FLAG_KEYS) or None,
            "webHighRisk": _flag(anchor, all_ancestors, HIGH_RISK_KEYS) or None,
        },
        "releases": releases,
    }
    return record


def parse_page(html: str, page_url: str) -> list[dict]:
    """Returns every staging record the page's Nuxt payload names, deduplicated.

    A normal detail page yields exactly one; a listing payload that happens to
    carry several works yields one per work. Returns an empty list on a page with
    no ``__NUXT_DATA__``, no media, or no title.
    """
    data = extract_nuxt_payload(html)
    if data is None:
        return []
    candidates = _collect_candidates(data)
    if not candidates:
        return []

    # Group candidate media under its work anchor, preserving discovery order.
    groups: dict[int, dict] = {}
    order: list[int] = []
    for item, ancestors in candidates:
        anchor = _work_anchor(item, ancestors)
        key = id(anchor)
        if key not in groups:
            groups[key] = {"anchor": anchor, "candidates": []}
            order.append(key)
        groups[key]["candidates"].append((item, ancestors))

    records, seen = [], set()
    for key in order:
        group = groups[key]
        record = _build_record(group["anchor"], group["candidates"], page_url)
        if not record:
            continue
        dedupe = record["canonical_key"] or record["url"]
        if dedupe in seen:
            continue
        seen.add(dedupe)
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class RateLimited(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def _request(url: str, method: str | None = None,
             accept: str | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers, method=method)


def http_get(url: str, timeout: int = PAGE_TIMEOUT, retries: int = 1,
             debug: dict | None = None) -> tuple[int, str, str]:
    """Returns (status, final_url, body). Status 0 means transport failure."""
    last = (0, url, "")
    for attempt in range(max(0, retries) + 1):
        if attempt:
            time.sleep(0.9 * attempt)
        try:
            with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                return resp.status, resp.geturl(), body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            last = (exc.code, url, body)
            if exc.code != RATE_LIMIT_STATUS:
                return last
        except Exception as exc:  # URLError, timeout, reset, bad TLS
            last = (0, url, "")
            if debug is not None:
                debug.setdefault("transport_error", f"{type(exc).__name__}: {exc}")
    return last


def http_head(url: str, timeout: int = PAGE_TIMEOUT) -> int:
    """A HEAD probe for a direct file. Returns the status, 0 on transport failure."""
    try:
        with urllib.request.urlopen(_request(url, method="HEAD"),
                                    timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


#: A process-wide floor between request *starts*, shared across worker threads.
_THROTTLE_LOCK = threading.Lock()
_LAST_START = [0.0]


def _throttle(delay: float) -> None:
    if delay <= 0:
        return
    with _THROTTLE_LOCK:
        wait_for = _LAST_START[0] + delay - time.monotonic()
        if wait_for > 0:
            time.sleep(wait_for)
        _LAST_START[0] = time.monotonic()


# ---------------------------------------------------------------------------
# Discovery (sync)
# ---------------------------------------------------------------------------

def _sitemap_entries(xml: str) -> list[tuple[str, str | None]]:
    entries = []
    for match in re.finditer(r"<(?:url|sitemap)\b[^>]*>.*?</(?:url|sitemap)>",
                             xml, re.I | re.S):
        block = match.group(0)
        loc = LOC_RE.search(block)
        if not loc:
            continue
        lastmod = LASTMOD_RE.search(block)
        entries.append((html_mod.unescape(loc.group(1)).strip(),
                        lastmod.group(1).strip() if lastmod else None))
    if not entries:
        entries = [(html_mod.unescape(m).strip(), None)
                   for m in LOC_RE.findall(xml)]
    return entries


def _looks_like_sitemap(loc: str) -> bool:
    path = loc.split("?", 1)[0].lower()
    return path.endswith(".xml") or path.endswith(".xml.gz")


def sync_catalog(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                 seeds=(), verbose: bool = True) -> dict:
    """Queues detail pages found in ``/sitemap.xml`` (and, if seeded, explicit URLs)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    totals = {"pages": 0, "queued": 0, "duplicates": 0, "errors": 0,
              "sitemaps": 0}
    try:
        ensure_schema(conn)

        def queue(loc, lastmod):
            slug = loc.rstrip("/").rsplit("/", 1)[-1] or None
            cur = conn.execute(
                "INSERT OR IGNORE INTO sitemap_cache (loc, lastmod, slug, scraped,"
                " raw_json, error_count) VALUES (?, ?, ?, 0, '{}', 0)",
                (loc, lastmod, slug))
            if cur.rowcount:
                totals["queued"] += 1
            else:
                totals["duplicates"] += 1

        for seed in seeds or ():
            if seed:
                queue(seed, None)

        status, _final, body = http_get(f"{BASE_URL}/sitemap.xml",
                                        timeout=SITEMAP_TIMEOUT)
        if status != 200:
            log(f"[!] [{SITE}] sitemap -> HTTP {status}")
            totals["errors"] += 1
            conn.commit()
            return totals
        entries = _sitemap_entries(body)
        totals["sitemaps"] += 1
        child_sitemaps = [loc for loc, _lm in entries if _looks_like_sitemap(loc)]
        page_entries = [(loc, lm) for loc, lm in entries
                        if not _looks_like_sitemap(loc)]

        for child in child_sitemaps[:MAX_CHILD_SITEMAPS]:
            if STOP_REQUESTED:
                break
            status, _final, child_body = http_get(child, timeout=SITEMAP_TIMEOUT)
            totals["sitemaps"] += 1
            if status != 200:
                totals["errors"] += 1
                continue
            page_entries.extend(
                (loc, lm) for loc, lm in _sitemap_entries(child_body)
                if not _looks_like_sitemap(loc))

        for loc, lastmod in page_entries:
            queue(loc, lastmod)
            totals["pages"] += 1
            if limit and totals["queued"] >= limit:
                break
        conn.commit()
    finally:
        conn.close()
    if verbose:
        log(f"[✓] [{SITE}] sync queued={totals['queued']} "
            f"duplicates={totals['duplicates']} sitemaps={totals['sitemaps']} "
            f"errors={totals['errors']}")
    return totals


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
    source_site TEXT DEFAULT 'themoviebox',
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
CREATE INDEX IF NOT EXISTS idx_themoviebox_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_themoviebox_posts_key ON posts(canonical_key);
CREATE INDEX IF NOT EXISTS idx_themoviebox_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_themoviebox_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_themoviebox_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_themoviebox_sitemap_scraped ON sitemap_cache(scraped);
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


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=()) -> dict:
    """Upserts parsed records; a re-export of one page replaces its releases+sources."""
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
            # Clear this page's previous releases (and their sources) exactly once,
            # before inserting the new set. Doing it per release would delete the
            # releases already written earlier in this same loop — a page has many
            # quality variants here, so that would leave only the last one.
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
        conn.commit()
    finally:
        conn.close()
    return totals


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

PENDING_SELECT = (
    "SELECT loc, lastmod, slug, raw_json, scraped, error_count FROM sitemap_cache "
    "WHERE scraped IN (0, 2) ORDER BY loc;"
)


def _failure(kind: str, http_status: int | None = None, final_url: str | None = None,
             detail: str | None = None) -> dict:
    return {"kind": kind, "http_status": http_status, "final_url": final_url,
            "detail": detail, "at": int(time.time())}


def _bump_error(db_path: Path, loc: str, failure: dict, park_now: bool = False) -> None:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT scraped, raw_json, error_count FROM sitemap_cache WHERE loc = ?",
            (loc,)).fetchone()
        errors = int((row["error_count"] if row else 0) or 0) + 1
        try:
            ledger = json.loads(row["raw_json"] or "{}") if row else {}
        except json.JSONDecodeError:
            ledger = {}
        failures = ledger.get("failures") or []
        failures.append(failure)
        ledger["failures"] = failures[-FAILURE_LEDGER_LIMIT:]
        ledger["last_note"] = failure.get("detail") or failure.get("kind")
        # 0 queued · 2 retryable · -1 parked (permanent or retries exhausted) · 1 crawled.
        # A gone page is parked at once; a transient one is retried until the cap.
        scraped = -1 if (park_now or errors >= MAX_SCRAPE_ATTEMPTS) else 2
        conn.execute(
            "UPDATE sitemap_cache SET scraped = ?, error_count = ?, raw_json = ?"
            " WHERE loc = ?",
            (scraped, errors, json.dumps(ledger, ensure_ascii=False), loc))
        conn.commit()
    finally:
        conn.close()


def _mark_scraped(db_path: Path, locs) -> None:
    unique = sorted(set(locs))
    if not unique:
        return
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.executemany(
            "UPDATE sitemap_cache SET scraped = 1, error_count = 0 WHERE loc = ?",
            [(loc,) for loc in unique])
        conn.commit()
    finally:
        conn.close()


def memory_ok(meminfo: str | None = None) -> tuple[bool, str]:
    """Reads /proc/meminfo; the floor is 2,500 MB free / 800 MB swap."""
    text = meminfo
    if text is None:
        try:
            text = Path("/proc/meminfo").read_text()
        except OSError:
            return True, "meminfo unavailable"
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0].rstrip(":")] = int(parts[1]) // 1024
    available = values.get("MemAvailable", 10 ** 9)
    swap_free = values.get("SwapFree", 10 ** 9)
    if available < MIN_MEM_AVAILABLE_MB:
        return False, f"MemAvailable {available} MB < {MIN_MEM_AVAILABLE_MB} MB"
    if swap_free < MIN_SWAP_FREE_MB:
        return False, f"SwapFree {swap_free} MB < {MIN_SWAP_FREE_MB} MB"
    return True, f"MemAvailable {available} MB, SwapFree {swap_free} MB"


def _clamp_workers(workers: int) -> int:
    # None means "unspecified" -> the polite default. Anything numeric floors at
    # 1 and caps at MAX_WORKERS, so a typo cannot silently raise concurrency or
    # turn into a thread stampede.
    if workers is None:
        return DEFAULT_WORKERS
    return max(1, min(MAX_WORKERS, int(workers)))


def crawl_pending(limit: int | None = None, db_path: Path | str = DEFAULT_DB_PATH,
                  workers: int = DEFAULT_WORKERS, delay: float = DEFAULT_DELAY,
                  batch_size: int = BATCH_SIZE, verbose: bool = True) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    workers = _clamp_workers(workers)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        rows = conn.execute(PENDING_SELECT).fetchall()
    finally:
        conn.close()
    pending = [dict(r) for r in rows]
    if limit:
        pending = pending[:limit]

    totals = {"pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "failed_rows": 0, "parked": 0, "failed": 0, "no_playable": 0,
              "paused_rate_limit": False, "stopped_for_memory": False,
              "skipped_after_stop": 0}
    if not pending:
        return totals

    _RATE_LIMITED.clear()
    ok, reason = memory_ok()
    if not ok:
        log(f"[!] [{SITE}] refusing to start: {reason}")
        totals["stopped_for_memory"] = True
        return totals
    if verbose:
        log(f"[*] [{SITE}] {len(pending)} pages pending "
            f"(workers={workers}, delay={delay}s).")

    batch: list[dict] = []
    batch_locs: list[str] = []

    def flush():
        flushed = export_staging(db_path, batch)
        totals["posts"] += flushed["posts_written"]
        totals["releases"] += flushed["releases_written"]
        totals["sources"] += flushed["sources_written"]
        _mark_scraped(db_path, batch_locs)
        batch.clear()
        batch_locs.clear()

    def fetch(row):
        _throttle(delay)
        return http_get(row["loc"], timeout=PAGE_TIMEOUT, retries=1)

    def handle(row, status, final, body):
        loc = row["loc"]
        totals["pages"] += 1
        if status == RATE_LIMIT_STATUS:
            _RATE_LIMITED.set()
            totals["paused_rate_limit"] = True
            log(f"[!] [{SITE}] HTTP 429 at {loc}: queue paused, row stays queued.")
            return
        if status != 200:
            totals["failed_rows"] += 1
            park_now = status in (404, 410, 451)
            totals["parked"] += int(park_now)
            kind = "transport" if status == 0 else f"http-{status}"
            _bump_error(db_path, loc, _failure(kind, status, final, kind),
                        park_now=park_now)
            return
        records = parse_page(body, loc)
        if not records:
            totals["failed_rows"] += 1
            totals["no_playable"] += 1
            _bump_error(db_path, loc, _failure(
                "no-playable-object", status, final,
                "page has no direct CDN media in its Nuxt payload"))
            return
        batch.extend(records)
        batch_locs.append(loc)
        if len(batch) >= batch_size:
            flush()
            ok, reason = memory_ok()
            if not ok:
                totals["stopped_for_memory"] = True
                log(f"[!] [{SITE}] STOP: {reason}")

    started = time.time()
    submitted = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: dict = {}

        def submit_next():
            nonlocal submitted
            if submitted >= len(pending):
                return False
            if STOP_REQUESTED or _RATE_LIMITED.is_set() or \
                    totals["stopped_for_memory"]:
                return False
            row = pending[submitted]
            submitted += 1
            futures[pool.submit(fetch, row)] = row
            return True

        for _ in range(workers):
            submit_next()

        while futures:
            done, _ = wait(list(futures), return_when=FIRST_COMPLETED)
            for future in done:
                row = futures.pop(future)
                try:
                    status, final, body = future.result()
                except Exception:
                    status, final, body = 0, row["loc"], ""
                handle(row, status, final, body)
                if verbose and (submitted % 100 == 0):
                    log(f"    ... {submitted}/{len(pending)} scheduled, "
                        f"{totals['posts']} posts, {time.time() - started:.0f}s")
                submit_next()
            if batch:
                flush()

    # Anything never scheduled is reported, not silently dropped.
    totals["skipped_after_stop"] = len(pending) - submitted
    if batch:
        flush()

    if verbose:
        paused = " paused=rate-limited" if totals["paused_rate_limit"] else ""
        stopped = " stopped=memory" if totals["stopped_for_memory"] else ""
        log(f"[✓] [{SITE}] pages={totals['pages']} posts={totals['posts']} "
            f"releases={totals['releases']} sources={totals['sources']} "
            f"failed_rows={totals['failed_rows']} parked={totals['parked']} "
            f"failed={totals['failed']} no_playable={totals['no_playable']} "
            f"in {time.time() - started:.0f}s{paused}{stopped}")
    return totals


# ---------------------------------------------------------------------------
# Verify (active vs dead)
# ---------------------------------------------------------------------------

def verify_sources(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                   delay: float = DEFAULT_DELAY, verbose: bool = True) -> dict:
    """HEAD-probes each unverified direct stream; never downloads the file."""
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    totals = {"checked": 0, "active": 0, "dead": 0, "unknown": 0,
              "paused_rate_limit": False}
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT id, source_url FROM sources"
            " WHERE status IN ('unverified', 'active') AND service = ? ORDER BY id",
            (SERVICE,)).fetchall()
        if limit:
            rows = rows[:limit]
        if verbose:
            log(f"[*] [{SITE}] {len(rows)} streams to verify.")
        for row in rows:
            if STOP_REQUESTED:
                break
            _throttle(delay)
            status = http_head(row["source_url"], timeout=PAGE_TIMEOUT)
            if status == RATE_LIMIT_STATUS:
                totals["paused_rate_limit"] = True
                break
            if 200 <= status < 300:
                state = "active"
            elif status in (401, 403, 404, 410):
                state = "dead"
            else:
                totals["unknown"] += 1
                continue
            conn.execute(
                "UPDATE sources SET status = ?, last_checked = ? WHERE id = ?",
                (state, int(time.time()), row["id"]))
            conn.commit()
            totals[state] += 1
            totals["checked"] += 1
            if verbose and totals["checked"] % 100 == 0:
                log(f"    ... {totals['checked']} checked, {totals['active']} active,"
                    f" {totals['dead']} dead")
    finally:
        conn.close()
    if verbose:
        log(f"[✓] [{SITE}] verify checked={totals['checked']} "
            f"active={totals['active']} dead={totals['dead']} "
            f"unknown={totals['unknown']}")
    return totals


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)

        def q(sql, *args):
            return conn.execute(sql, args).fetchone()[0]

        return {
            "works": q("SELECT COUNT(*) FROM posts"),
            "movies": q("SELECT COUNT(*) FROM posts WHERE media_type = 'movie'"),
            "series": q("SELECT COUNT(*) FROM posts WHERE media_type = 'series'"),
            "releases": q("SELECT COUNT(*) FROM releases"),
            "episodes": q("SELECT COUNT(*) FROM releases WHERE episode_number IS NOT NULL"),
            "direct_links": q("SELECT COUNT(*) FROM sources WHERE playback_type = ?",
                              PLAYBACK_DIRECT),
            "sources_unverified": q("SELECT COUNT(*) FROM sources WHERE status = 'unverified'"),
            "sources_active": q("SELECT COUNT(*) FROM sources WHERE status = 'active'"),
            "sources_dead": q("SELECT COUNT(*) FROM sources WHERE status = 'dead'"),
            "tier1_links": q("SELECT COUNT(*) FROM sources WHERE service_tier = 1"),
            "adult_posts": q("SELECT COUNT(*) FROM posts WHERE is_18_plus = 1"),
            "queued": q("SELECT COUNT(*) FROM sitemap_cache WHERE scraped IN (0, 2)"),
            "parked": q("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1"),
            "crawled": q("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1"),
            "sitemap_rows": q("SELECT COUNT(*) FROM sitemap_cache"),
            "release_less_posts": q(
                "SELECT COUNT(*) FROM posts p WHERE NOT EXISTS ("
                " SELECT 1 FROM releases r WHERE r.post_canonical_key = p.canonical_key)"),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _install_signals() -> None:
    def _stop(signum, _frame):
        global STOP_REQUESTED
        STOP_REQUESTED = True
        log(f"[!] [{SITE}] signal {signum}: finishing the page in flight, then stopping.")
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, _stop)
        except ValueError:  # not the main thread (e.g. under a test runner)
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="themoviebox.xyz staging importer")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="queue detail pages from the sitemap")
    sync.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync.add_argument("--limit", type=int)
    sync.add_argument("--seed", action="append", default=[],
                      help="an explicit page URL to queue (repeatable)")

    crawl = sub.add_parser("crawl", help="fetch queued pages")
    crawl.add_argument("--db", default=str(DEFAULT_DB_PATH))
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    crawl.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    crawl.add_argument("--batch-size", type=int, default=BATCH_SIZE)

    verify = sub.add_parser("verify", help="HEAD-probe unverified streams")
    verify.add_argument("--db", default=str(DEFAULT_DB_PATH))
    verify.add_argument("--limit", type=int)
    verify.add_argument("--delay", type=float, default=DEFAULT_DELAY)

    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _install_signals()
    if args.command == "sync":
        totals = sync_catalog(args.db, limit=args.limit, seeds=args.seed)
    elif args.command == "crawl":
        totals = crawl_pending(limit=args.limit, db_path=args.db,
                               workers=args.workers, delay=args.delay,
                               batch_size=args.batch_size)
    elif args.command == "verify":
        totals = verify_sources(db_path=args.db, limit=args.limit,
                                delay=args.delay)
    else:
        totals = stats(args.db)
    print(json.dumps(totals, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
