#!/usr/bin/env python3
"""
import_themoviebox.py — themoviebox.xyz into a dedicated staging vault.

themoviebox.xyz is the public skin of an Aoneroom/AutoPlay-family front end: a
Nuxt 3 SSR app whose every page ships its whole render payload in a single
``<script id="__NUXT_DATA__">`` block. That payload is *not* plain JSON — Nuxt
serialises it with `devalue`, a flat pool of values where every object and array
member is an integer index back into the pool. This module unflattens that pool
(``unflatten``) and then walks the hydrated graph, pulling:

  * identity   — title, release date / year, duration, genres, dubs, cast
  * artwork    — poster / backdrop / stills, blurHash, avgHueLight, avgHueDark
  * structure  — seasons and episodes (a series page is one work, many releases)
  * flags      — ``isPornographic`` / ``webHighRisk`` -> ``is_18_plus``

What it deliberately does NOT pretend: **the site never publishes a playable
print in its HTML.** Measured on this host 2026-10-29 against three live detail
pages (one movie, two series): the only ``.mp4`` ever present is the *trailer*
(``trailer.videoAddress`` — 640x360, 30-169 s), while the work's own print is
resolved client-side. The payload says so out loud:

    subject.detailUrl = ""   subject.sniffUrl = ""   subject.sourceUrl = ""
    resource.seasons[0].resolutions = [{360,480,1080}]   <- tiers, no URLs
    postTitle = "Matchbox-1080P"

So a scraper that simply regexes ``macdn.aoneroom.com`` mp4s — as this module
did until it was fixed — stages a 169-second trailer as the film's ``-ld`` print
and calls the row ``active``. That is the defect this file's media rules exist
to prevent: the trailer subtree is pruned from the media walk, and a work with no
print is recorded as **metadata-only**, never as a playable source.

Metadata-only does not mean structureless, and that distinction was the defect
measured 2026-10-30: 44 staged works reported ``0 releases / 0 sources`` while
every detail page listed its renditions (``resource.seasons[].resolutions[]``,
360/480/720/1080 with per-season episode counts). Those tiers are now stored as
releases with **empty source lists** — a declared print whose URL is not public
— and any populated ``dl``-shaped mirror field is stored with its status
(``dead`` included). Nothing is invented: a tier with no URL has no source row,
and a page whose payload has neither still yields the post with zero sources.

Discovery does not use a sitemap either. ``/sitemap.xml`` is a real HTTP 404 on
this site (measured: 12 connections, one answered 404 with a full HTML page), so
the queued-from-sitemap path would have ingested nothing. The site's own catalog
API is public and paginated and returns the same subject objects:

    POST https://h5-api.aoneroom.com/wefeed-h5api-bff/subject/filter
         {"page": 1, "perPage": 50}

which is what ``sync`` walks now. ``subjectType`` in the request body is
decoration, and believing otherwise cost a request loop: measured 2026-10-30,
{subjectType: 1}, {subjectType: 2}, {subjectTypes: [1]} and {subjectType: 1,
areaName: "india"} all answer the *same* mixed popularity page. The item's own
``subjectType`` field is the only classifier, and it matters — the soup is
dominated by type 2 (series) with type 6 (*music mixes*: 2-3 hour "Best of X"
compilations that are not films), and ``sort`` swaps in yet other non-works
(sort=newest -> type 7 concert mixes, sort=hot -> type 9 sports clips). Only
types 1 and 2 are ingested, and because the endpoint cannot be filtered
server-side, it cannot be enumerated either: 100 items over 2 pages against a
44-row vault produced 84 duplicates. ``pager.totalCount: 1000000`` is a pager
fiction. The endpoint that *does* filter (``/subject/search``) is authenticated,
and its client-side token is not reverse-engineered here.

Finally, the edge reset roughly two thirds of TLS handshakes from this host
(8/24 successes, independent of IP and of HTTP version — four CloudFront
addresses all flap). **That measurement was taken under heavy local load and is
not the site's alone:** at load 8.2 the failures included a TLS reset after a
0.99 s TCP connect and a SYN that never connected, while at load 1.9 one request
answered in 1.1 s. Attribute a transport failure to the site only below load 4.
Transport failure is therefore retried far harder than an HTTP error is, and
every retry passes through the shared politeness throttle.

Isolation is the whole point: this writes only to the vault named by ``--db``,
which defaults to ``/home/ubuntu/radd-stream-data/themoviebox.db``. It never
imports the production ``fast_fetch.db``/merged catalog and never runs the
unified ``save_scraped_data`` path. A later ``merge_catalogs.py`` run is the only
thing allowed to bring these rows into the unified catalog.

Stdlib only. Polite by default (two fetch workers, a 0.3 s floor between request
starts, batched commits, a memory floor) because this runs on a one-core box.

Usage:
    python3 -S Fast_Fetch/importers/import_themoviebox.py sync --pages 4
    python3 -S Fast_Fetch/importers/import_themoviebox.py sync --seed https://themoviebox.xyz/detail/matchbox-the-movie-S5hfykcX3Z4
    python3 -S Fast_Fetch/importers/import_themoviebox.py crawl --workers 2 --delay 0.3 --limit 40
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
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch  # noqa: E402  (path bootstrap must run first)

SITE = "themoviebox"
BASE_URL = "https://themoviebox.xyz"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/themoviebox.db")

#: The site's own catalog service. Public, paginated, and the only discovery
#: surface that exists — ``/sitemap.xml`` is a hard 404 here.
API_BASE = "https://h5-api.aoneroom.com/wefeed-h5api-bff"
API_FILTER_PATH = "/subject/filter"
API_PAGE_SIZE = 50
API_MAX_PAGES = 200
API_TIMEOUT = 20

#: A detail page is ``{BASE_URL}/detail/{subject.detailPath}`` — measured from the
#: ``href="/detail/<slug>"`` anchors the browse pages emit, not guessed.
DETAIL_PREFIX = "/detail/"

#: ``subject.subjectType``. Measured over 200 unfiltered items: 2 (series) and 6
#: dominate. 6 is a *music mix* ("Best of X ... Extended Mix", 40-120 min), which
#: is not a work this catalog should ever list as a film, so it is not accepted.
SUBJECT_TYPE_MOVIE = 1
SUBJECT_TYPE_SERIES = 2
ACCEPTED_SUBJECT_TYPES = (SUBJECT_TYPE_MOVIE, SUBJECT_TYPE_SERIES)
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
PAGE_TIMEOUT = 30
RATE_LIMIT_STATUS = 429
MAX_SCRAPE_ATTEMPTS = 3
FAILURE_LEDGER_LIMIT = 8

#: Retries for a connection that never completed (reset / timeout / TLS failure).
#: Deliberately far above the retry count for an HTTP answer: this edge resets
#: ~2 of 3 handshakes from this host, so a transport failure carries no
#: information about the page, while a 404 does.
TRANSPORT_RETRIES = 6
#: Retries for an HTTP-level failure of an already-established connection.
HTTP_ERROR_RETRIES = 1
#: Cap on connections spent per page, so flapping cannot make one row loop.
MAX_CONNECTIONS_PER_PAGE = TRANSPORT_RETRIES + 3

#: The directive's hard floor: stop before the box thrashes.
MIN_MEM_AVAILABLE_MB = 2500
MIN_SWAP_FREE_MB = 800

#: Hosts this site serves its own media and art from. A stream on any other host
#: is an ad and is dropped. Being on this host is *necessary, not sufficient*:
#: the trailer is served from ``macdn.aoneroom.com`` too, and with a ``-ld``/
#: ``-sd`` print suffix, so a host filter alone cannot tell them apart — see
#: ``NONPLAYABLE_KEYS``, which is what actually keeps trailers out of ``sources``.
MEDIA_HOST_HINTS = ("aoneroom.com",)
ART_HOST_HINTS = ("aoneroom.com",)

#: Payload subtrees that name an image or a preview rather than the work's print.
#: A media URL found under one of these is never a playable source.
NONPLAYABLE_KEYS = frozenset({"trailer", "stills", "gif", "preview"})

#: Mirrors the payload can name instead of a stream. Measured 2026-10-30 on both
#: surfaces (item page and `/wefeed-h5api-bff/detail`): `dl` is present and
#: ``null``, so no populated example has been captured — but the field is the
#: site's own, and dropping a populated one silently is what the Zero Data Loss
#: rule forbids. A mirror is stored with its status, dead or alive.
MIRROR_KEYS = ("dl", "downloads", "downloadList", "mirrors")
MIRROR_URL_KEYS = ("url", "downUrl", "link", "downloadUrl", "src")
PLAYBACK_DOWNLOAD = "download"
DEAD_STATUS_TOKENS = frozenset({"dead", "down", "expired", "invalid", "removed",
                                "unavailable", "offline", "0", "false"})

STOP_REQUESTED = False
_RATE_LIMITED = threading.Event()

NUXT_SCRIPT_RE = re.compile(
    r'<script[^>]*\bid\s*=\s*["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
    re.I | re.S)
MEDIA_URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?\.(?:mp4|m3u8)(?:\?[^\s\"'<>\\]*)?", re.I)
YEAR_RE = re.compile(r"(19|20)\d{2}")

TITLE_KEYS = ("title", "name", "originalTitle", "original_title", "cleanTitle")
DATE_KEYS = ("releaseDate", "release_date", "airDate", "firstAirDate", "date")
SYNOPSIS_KEYS = ("synopsis", "overview", "description", "plot", "summary")
GENRE_KEYS = ("genres", "genre")
#: ``cover``/``image``/``thumbnail`` hold ``{"url": ...}`` objects here, not
#: strings, so artwork is read through ``_image_url`` rather than ``_first_text``.
POSTER_KEYS = ("posterUrl", "poster_url", "poster", "image", "cover", "thumbnail")
BACKDROP_KEYS = ("backdropUrl", "backdrop_url", "backdrop", "banner")
DURATION_KEYS = ("duration", "runtime")
EPISODE_KEYS = ("episodeNumber", "episode_number", "episode", "epNum", "ep")
SEASON_KEYS = ("seasonNumber", "season_number", "season", "se")
CAST_KEYS = ("cast", "actors")
#: ``staffList`` is credited people of *any* kind (its ``staffType`` distinguishes
#: them and no populated example has been captured from this site yet), so its
#: names are kept as raw evidence rather than asserted to be the cast.
STAFF_LIST_KEYS = ("staffList", "staff")
DUB_KEYS = ("dubs", "languages", "audio", "subtitles", "audioLanguages")
RATING_KEYS = ("rating", "imdbRating", "imdb_rating", "voteAverage",
               "imdbRatingValue", "imdbRate")
COUNTRY_KEYS = ("countryName", "country", "region")
INDUSTRY_KEYS = ("industry", "countryName")
#: The subject-type field, and the field that names the print tiers the site
#: publishes without ever naming their URLs.
SUBJECT_TYPE_KEYS = ("subjectType", "subject_type")
#: A dict is a work only if the site can route to it. Without this, cast entries
#: and banner wrappers parsed as titles became catalog rows.
WORK_MARKER_KEYS = ("detailPath", "subjectId")
RESOLUTION_KEYS = ("resolutions",)
#: A staff entry is ``{"staffId", "staffType", <name>}``; the name field is not
#: stable across payloads, so any of these is taken.
STAFF_NAME_KEYS = ("name", "staffName", "title", "label")
LABEL_KEYS = ("name", "title", "label", "language", "value", "lanName")

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
        for key in LABEL_KEYS:
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


def _lookup_values(item: dict, ancestors: list, keys) -> list:
    """Every non-empty value under these keys, across the item and its ancestors.

    ``_lookup_raw`` stops at the first key that is merely *present*, and this
    site presents empty placeholders beside real data: measured 2026-10-30 a feed
    item carries ``subtitles: ""`` and ``dubs: []`` as normal members, so a work
    with three dub languages and an empty subtitles string answered 'no
    languages'. Collecting every populated key is the only reading that survives
    both halves of that shape.
    """
    found: list = []
    for node in [item] + list(reversed(ancestors)):
        if not isinstance(node, dict):
            continue
        for key in keys:
            value = node.get(key)
            if value not in (None, "", [], {}):
                found.append(value)
    return found


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
    # A stream this site owns is served from its own edge and nothing else. The
    # filter is unconditional: the previous version only narrowed the list when at
    # least one URL was on the edge, so a page whose *only* mp4 was an ad or a
    # studio trailer kept that foreign URL as the work's playable print.
    found = [url for url in found if any(host in url for host in MEDIA_HOST_HINTS)]
    seen, ordered = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _collect_candidates(root):
    """(dict, ancestors) for every dict that directly holds a *playable* media URL.

    Subtrees named by ``NONPLAYABLE_KEYS`` are never entered. This is the whole
    reason the walk is not a plain regex over the page: this site's trailer sits
    on the same ``macdn.aoneroom.com`` edge, in the same ``/media/…-ld.mp4`` shape
    as a print, so nothing about the URL itself distinguishes the two. Only its
    position in the graph does — and mistaking one for the other records a
    169-second 640x360 preview as the film.
    """
    out = []

    def walk(node, ancestors):
        if isinstance(node, dict):
            if _direct_media_urls(node):
                out.append((node, list(ancestors)))
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    if _nonplayable(key):
                        continue
                    walk(value, ancestors + [node])
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value, ancestors)

    walk(root, [])
    return out


def _nonplayable(key) -> bool:
    return isinstance(key, str) and key.casefold() in NONPLAYABLE_KEYS


def _image_url(value) -> str | None:
    """Artwork is an object (``{"url": ..., "width": ...}``) or, rarely, a string.

    Anything that is not URL-shaped is refused: a payload label landing in
    ``poster_url`` is worse than no poster, because the catalog will render it.
    """
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith(("http://", "https://", "//")):
            return text
        return None
    if isinstance(value, dict):
        for key in ("url", "imageUrl", "sourceUrl", "link"):
            text = _image_url(value.get(key))
            if text:
                return text
    return None


def _lookup_image(item: dict, ancestors: list, keys) -> str | None:
    for node in [item] + list(reversed(ancestors)):
        if not isinstance(node, dict):
            continue
        for key in keys:
            text = _image_url(node.get(key))
            if text:
                return text
    return None


def _image_list(value) -> list[str]:
    """``stills`` is one image object or a list of them; empty/None is no image.

    Measured 2026-10-30 on the detail page and its API answer: ``subject.stills``
    is a single ``{"url", "width", ...}`` object there, not a list. Accepting only
    a list dropped the one still the page publishes, leaving ``backdrop_url`` NULL.
    """
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for element in value:
        text = _image_url(element)
        if text and text not in out:
            out.append(text)
    return out


def _positive_int(raw) -> int | None:
    """A number that is actually a number. This site uses ``0`` for 'no season /
    no episode', so 0 must not be read as evidence that a work is a series."""
    if isinstance(raw, bool):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _duration_text(raw) -> str | None:
    """Duration as the site gives it, or NULL. Measured 2026-10-30: every series
    item carries ``duration: 0``, so the raw value landed in 40 of 40 staged rows
    and read as 'this work runs for zero time'. The unit is never stated by the
    site either, so it is stored verbatim and never converted."""
    value = _positive_int(raw)
    return str(value) if value is not None else None


def _is_episode(node: dict) -> bool:
    if not isinstance(node, dict):
        return False
    if any(_positive_int(node.get(k)) is not None for k in EPISODE_KEYS):
        return True
    return any(_positive_int(node.get(k)) is not None for k in SEASON_KEYS)


def _subject_type(item: dict, ancestors: list) -> int | None:
    for node in [item] + list(reversed(ancestors)):
        if not isinstance(node, dict):
            continue
        for key in SUBJECT_TYPE_KEYS:
            if key in node:
                raw = node.get(key)
                try:
                    return int(str(raw).strip())
                except (TypeError, ValueError):
                    return None
    return None


def _media_type(subject_type: int | None, releases: list) -> str:
    """``subjectType`` decides; the graph is only the fallback.

    The site states the kind explicitly, and deriving it from "does some dict
    carry a season field" was wrong on measured data: a *film*'s payload carries
    ``season: 0`` and ``seasons: [{se: 0, maxEp: 0}]``, which turned every movie
    into a series.
    """
    if subject_type == SUBJECT_TYPE_MOVIE:
        return "movie"
    if subject_type == SUBJECT_TYPE_SERIES:
        return "series"
    if any(r.get("episode") is not None or r.get("season") is not None
           for r in releases):
        return "series"
    return "movie"


def _resource_resolutions(node) -> list[int]:
    """The print tiers the site publishes *without* publishing their URLs.

    ``resource.seasons[].resolutions[]`` names 360/480/1080 for a work whose only
    mp4 in the page is its trailer. Recording that as evidence is what lets a
    later pass tell 'this work has a 1080p print we cannot yet reach' apart from
    'this work has nothing'.
    """
    tiers: list[int] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key in RESOLUTION_KEYS and isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, dict):
                            try:
                                tier = int(str(entry.get("resolution")).strip())
                            except (TypeError, ValueError):
                                continue
                            if tier and tier not in tiers:
                                tiers.append(tier)
                else:
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return sorted(tiers, reverse=True)


def _resource_renditions(root) -> list[dict]:
    """Every print tier the payload declares: season, resolution, episode count.

    Measured 2026-10-30 on both surfaces: `resource.seasons[].resolutions[]`
    names 360/480/720/1080 with a per-season ``epNum``, while
    ``detailUrl``/``sniffUrl``/``sourceUrl`` are empty strings and ``dl`` is
    null. Dropping the tiers left the vault reporting ``0 releases`` for a work
    whose four renditions the page had just listed, which reads as "this site
    has nothing" instead of "four prints exist and none of their URLs is
    published". Each tier therefore becomes a release with an empty source list.
    """
    out: list[dict] = []
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            seasons = node.get("seasons")
            if isinstance(seasons, list):
                host = _as_text(node.get("source"))
                for season in seasons:
                    if not isinstance(season, dict):
                        continue
                    se = _positive_int(season.get("se"))
                    for entry in season.get("resolutions") or []:
                        if not isinstance(entry, dict):
                            continue
                        resolution = _positive_int(entry.get("resolution"))
                        if resolution is None:
                            continue
                        episodes = _positive_int(entry.get("epNum"))
                        key = (se, resolution, episodes)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append({"season": se, "resolution": resolution,
                                    "episodes": episodes, "source_host": host})
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(root)
    return out


def _declared_releases(renditions: list[dict], title: str,
                       audio: str | None) -> list[dict]:
    """One release per declared rendition, with no source: the URL is not public."""
    releases = []
    for item in renditions:
        quality = f"{item['resolution']}p"
        label = title
        if item["season"] is not None:
            label += f" S{item['season']:02d}"
        releases.append({
            "label": f"{label} {quality}".strip(),
            "quality": quality,
            "resolution": str(item["resolution"]),
            "size_bytes": None,
            "codec": None,
            "season": item["season"],
            "episode": None,
            "audio": audio,
            "bridge_url": None,
            "raw_meta": {"declared": True, "episodes": item["episodes"],
                         "source_host": item["source_host"], "play_url": None},
            "sources": [],
        })
    return releases


def _mirror_source(url: str, entry: dict) -> dict:
    raw_status = entry.get("status") or entry.get("state")
    available = entry.get("available")
    dead = available is False or (
        isinstance(raw_status, str)
        and raw_status.strip().lower() in DEAD_STATUS_TOKENS)
    name = url.rsplit("/", 1)[-1].split("?", 1)[0] or url
    return {
        "source_name": SERVICE,
        "service": SERVICE,
        "service_tier": SERVICE_TIER,
        "resource_id": name,
        "source_url": url,
        "final_url": url,
        "playback_type": PLAYBACK_DOWNLOAD,
        "status": "dead" if dead else "active",
        "is_temporary": 0,
        "quality": _quality_from_url(url),
        "mime_type": _mime_type(url),
        "last_checked": None,
        "raw_meta": {"url": url, "declared_status": raw_status,
                      "available": available},
    }


def _mirror_sources(root) -> list[dict]:
    """Download mirrors under the site's own ``dl``-shaped fields, dead or alive."""
    out: list[dict] = []

    def add(value):
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if isinstance(entry, str):
                if entry.startswith(("http://", "https://")):
                    out.append(_mirror_source(entry, {}))
            elif isinstance(entry, dict):
                url = next((_as_text(entry.get(k)) for k in MIRROR_URL_KEYS
                            if _as_text(entry.get(k))), None)
                if url and url.startswith(("http://", "https://")):
                    out.append(_mirror_source(url, entry))

    def walk(node):
        if isinstance(node, dict):
            for key in MIRROR_KEYS:
                if key in node:
                    add(node[key])
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(root)
    seen, ordered = set(), []
    for src in out:
        key = (src["source_url"], src["status"])
        if key not in seen:
            seen.add(key)
            ordered.append(src)
    return ordered


def _attach_mirrors(record: dict, mirrors: list[dict]) -> None:
    """Bind each mirror to the release of its quality; never invent a quality."""
    by_quality: dict = {}
    for rel in record["releases"]:
        if rel.get("quality"):
            by_quality.setdefault(rel["quality"], rel)
    for src in mirrors:
        target = by_quality.get(src.get("quality"))
        if target is None and record["releases"]:
            target = record["releases"][0]
        if target is None:
            target = {
                "label": f"{record['title']} download",
                "quality": src.get("quality"), "resolution": None,
                "size_bytes": None, "codec": None, "season": None,
                "episode": None, "audio": None, "bridge_url": None,
                "raw_meta": {"declared": True}, "sources": [],
            }
            record["releases"].append(target)
        target["sources"].append(src)


def _enrich_with_declared_media(record: dict, root) -> None:
    """Add declared renditions and mirrors when the record has no playable print.

    Used by both ingest paths: ``parse_page`` for a detail page (only when the
    payload names one work, so a sibling card's tiers cannot leak in) and
    ``harvest_catalog`` for a single feed subject.
    """
    renditions = _resource_renditions(root)
    if renditions:
        tiers = sorted({r["resolution"] for r in renditions}, reverse=True)
        record["raw_meta"]["available_resolutions"] = tiers
        # The per-season episode counts are the only place this site states how
        # long a season is; keep them on the post, not only inside each release.
        record["raw_meta"]["declared_renditions"] = renditions
    if not record["releases"] and renditions:
        record["releases"] = _declared_releases(
            renditions, record["title"], record["languages"])
    mirrors = _mirror_sources(root)
    if mirrors:
        _attach_mirrors(record, mirrors)


def _work_anchor(item: dict, ancestors: list) -> dict:
    """The nearest dict that names a work, skipping episode/season containers.

    For a movie page that is the item itself. For a series page the media sits on
    the episode dict, so the work identity is the enclosing series object.
    """
    for node in [item] + list(reversed(ancestors)):
        if (isinstance(node, dict) and not _is_episode(node)
                and _first_text(node, ("title",))
                and any(node.get(k) is not None for k in WORK_MARKER_KEYS)):
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
    return _positive_int(_lookup_raw(item, ancestors, EPISODE_KEYS))


def _season_number(item: dict, ancestors: list) -> int | None:
    number = _positive_int(_lookup_raw(item, ancestors, SEASON_KEYS))
    if number is not None:
        return number
    # A season dict may carry its number on a `number` field.
    return _positive_int(_lookup_raw(item, ancestors, ("number",)))


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


def _trailer_evidence(item: dict, ancestors: list) -> dict:
    """The trailer and the print tiers the site names but does not link.

    Kept as metadata, never as a source: it is what distinguishes a work whose
    playable print we simply cannot reach from a work that has nothing at all.
    """
    evidence: dict = {}
    nodes = [item] + list(reversed(ancestors))
    for node in nodes:
        if not isinstance(node, dict):
            continue
        trailer = node.get("trailer")
        if isinstance(trailer, dict) and "trailer_url" not in evidence:
            address = trailer.get("videoAddress")
            if isinstance(address, dict):
                url = _as_text(address.get("url"))
                if url:
                    evidence["trailer_url"] = url
                    evidence["trailer_seconds"] = address.get("duration")
                    evidence["trailer_width"] = address.get("width")
        tiers = _resource_resolutions({k: v for k, v in node.items()
                                       if k in RESOLUTION_KEYS or k == "seasons"})
        if tiers and "available_resolutions" not in evidence:
            evidence["available_resolutions"] = tiers
        for key in ("detailUrl", "sniffUrl", "sourceUrl", "dl"):
            if key in node and node.get(key):
                evidence["client_resolved_field"] = key
                break
    return evidence


def _iter_releases(candidates: list, work_title: str):
    """Releases for every media-bearing node, one stream at a time.

    The same print is reachable from more than one dict in this graph (the
    resource node and the episode node both carry it), so a caller that grouped
    by node would store the identical file twice.
    """
    for item, ancestors in candidates:
        for release in _build_releases(item, ancestors, work_title):
            yield release


def _stamp_seasons(record: dict) -> None:
    """Write ``seasons`` from whatever releases exist *now*.

    ``_build_record`` used to compute this before ``_enrich_with_declared_media``
    added the declared renditions, so a series whose only releases are the ones
    the site declares (the normal shape here) stored ``seasons = NULL`` while its
    twenty releases each named a season. Stamping after enrichment is the fix.
    """
    seasons = sorted({r["season"] for r in record.get("releases") or []
                      if r.get("season") is not None})
    record["seasons"] = json.dumps(seasons) if seasons else None


def _build_record(anchor: dict, candidates: list, page_url: str) -> dict | None:
    title = _first_text(anchor, TITLE_KEYS) or ""
    if not title:
        return None
    subject_type = _subject_type(candidates[0][0] if candidates else anchor,
                                 candidates[0][1] if candidates else [])
    if subject_type is not None and subject_type not in ACCEPTED_SUBJECT_TYPES:
        return None
    release_date = _lookup(anchor, [], DATE_KEYS)
    year = _year_of(release_date) or _year_of(_lookup(anchor, [], ("year",)))
    slug = page_url.rstrip("/").rsplit("/", 1)[-1] if page_url else ""

    releases, seen_urls = [], set()
    for release in _iter_releases(candidates, title):
        url = (release["sources"] or [{}])[0].get("source_url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        release["raw_meta"]["page_url"] = page_url
        releases.append(release)

    all_ancestors = [anc for _item, anc in candidates for anc in anc]
    # The adult flags live on the *subject*, and a metadata-only work has no media
    # candidates at all, so checking only the candidates would publish an
    # ``isPornographic`` title with ``is_18_plus = 0``.
    is_adult = (_is_adult(anchor, all_ancestors, page_url, title, slug)
                or any(_is_adult(item, anc, page_url, title, slug)
                       for item, anc in candidates))

    poster = _lookup_image(anchor, all_ancestors, POSTER_KEYS)
    backdrop = _lookup_image(anchor, all_ancestors, BACKDROP_KEYS)
    stills: list[str] = []
    for node in [anchor] + all_ancestors:
        if isinstance(node, dict):
            stills.extend(_image_list(node.get("stills")))
    stills = [s for s in dict.fromkeys(stills) if s != backdrop]
    # The site names no backdrop field at all on the measured payloads; the one
    # wide image it publishes is ``stills``. Without this fallback the backdrop
    # column stays NULL on every row while the URL sits in ``backdrop_urls``.
    backdrop = backdrop or (stills[0] if stills else None)
    backdrop_urls = [s for s in ([backdrop] + stills) if s]
    evidence = _trailer_evidence(candidates[0][0] if candidates else anchor,
                                 candidates[0][1] if candidates else [])

    record = {
        "canonical_key": fast_fetch.generate_canonical_key(title, year),
        "title": title,
        "clean_title": title,
        "year": year,
        "media_type": _media_type(subject_type, releases),
        "poster_url": poster,
        "backdrop_url": backdrop,
        "backdrop_urls": json.dumps(backdrop_urls) if backdrop_urls else None,
        "imdb_id": None,
        "tmdb_id": None,
        "imdb_rating": _lookup(anchor, [], RATING_KEYS),
        "synopsis": _lookup(anchor, [], SYNOPSIS_KEYS),
        "genres": _join_labels(_lookup_raw(anchor, all_ancestors, GENRE_KEYS)),
        "director": None,
        "cast_names": _join_labels(_lookup_raw(anchor, all_ancestors, CAST_KEYS)),
        "duration": _duration_text(_lookup(anchor, [], DURATION_KEYS)),
        "release_date": release_date,
        "languages": _join_labels(_lookup_values(anchor, all_ancestors, DUB_KEYS)),
        "industry": _lookup(anchor, all_ancestors, INDUSTRY_KEYS),
        "country": _lookup(anchor, all_ancestors, COUNTRY_KEYS),
        "seasons": None,
        "url": page_url,
        "slug": slug,
        "is_18_plus": 1 if is_adult else 0,
        "is_animated": int(bool(fast_fetch.looks_animated(title))),
        "source_site": SITE,
        "raw_meta": {
            "page_url": page_url,
            "subjectType": subject_type,
            "postTitle": _lookup(anchor, all_ancestors, ("postTitle",)),
            "detailPath": _lookup(anchor, all_ancestors, ("detailPath",)),
            "subjectId": _lookup(anchor, all_ancestors, ("subjectId",)),
            "hasResource": _lookup(anchor, all_ancestors, ("hasResource",)),
            "freeEpisodeCount": _lookup(anchor, all_ancestors,
                                        ("freeEpisodeCount",)),
            "blurHash": _lookup(anchor, [], ("blurHash", "blur_hash")),
            "avgHueLight": _lookup(anchor, [], ("avgHueLight", "avg_hue_light")),
            "avgHueDark": _lookup(anchor, [], ("avgHueDark", "avg_hue_dark")),
            "staff": _join_labels(_lookup_raw(anchor, all_ancestors,
                                              STAFF_LIST_KEYS)),
            "isPornographic": _flag(anchor, all_ancestors, ADULT_FLAG_KEYS) or None,
            "webHighRisk": _flag(anchor, all_ancestors, HIGH_RISK_KEYS) or None,
            **evidence,
        },
        "releases": releases,
    }
    _stamp_seasons(record)
    return record


def _collect_anchors(root) -> list[tuple[dict, list]]:
    """Every dict that names a work, whether or not it links a stream.

    This site's detail pages state the work (title, cover, rating, run time,
    ``subjectType``) and leave its print to a client-side call, so an anchor with
    no media under it is the *normal* shape here, not a parse failure.

    A work is a dict carrying ``title`` **and** an address the site can route to.
    Requiring only a name was wrong on measured data: a detail page produced 19
    records, 18 of them cast members and banner wrappers.
    """
    out: list[tuple[dict, list]] = []

    def walk(node, ancestors):
        if isinstance(node, dict):
            if _first_text(node, ("title",)) and any(
                    node.get(k) is not None for k in WORK_MARKER_KEYS):
                out.append((node, list(ancestors)))
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value, ancestors + [node])
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value, ancestors)

    walk(root, [])
    return out


def _work_identity(anchor: dict) -> str:
    """One key per work, so the same subject repeated across the graph is one row.

    A measured detail page carries ~30 near-identical ``subject`` dicts for a
    single film; grouping by Python object identity would emit 30 posts.
    """
    for key in ("subjectId", "detailPath"):
        text = _as_text(anchor.get(key))
        if text:
            return f"{key}:{text}"
    return f"title:{(_as_text(anchor.get('title')) or '').casefold()}"


def parse_page(html: str, page_url: str) -> list[dict]:
    """Returns every staging record the page's Nuxt payload names, deduplicated.

    A normal detail page yields exactly one; a listing payload that happens to
    carry several works yields one per work. Returns an empty list on a page with
    no ``__NUXT_DATA__`` and no titled subject. A record with empty release
    ``sources`` is a valid outcome and means *no playable URL was published* — the
    declared renditions are still listed as releases, and it is never a trailer
    wearing a print.
    """
    data = extract_nuxt_payload(html)
    if data is None:
        return []

    groups: dict[str, dict] = {}
    order: list[str] = []

    def group_for(anchor: dict, ancestors: list) -> dict:
        identity = _work_identity(anchor)
        if identity not in groups:
            groups[identity] = {"anchor": anchor, "candidates": []}
            order.append(identity)
        return groups[identity]

    for item, ancestors in _collect_candidates(data):
        anchor = _work_anchor(item, ancestors)
        group_for(anchor, ancestors)["candidates"].append((item, ancestors))

    for anchor, ancestors in _collect_anchors(data):
        group_for(anchor, ancestors)

    records = []
    for identity in order:
        group = groups[identity]
        record = _build_record(group["anchor"], group["candidates"], page_url)
        if record:
            records.append(record)

    # The tier list lives beside the subject, not under it. Attaching it is only
    # honest when the page describes one work; on a multi-work payload a sibling
    # card's tiers would be claimed as this title's capability.
    if len(records) == 1:
        # A page with no playable URL still declares its renditions; storing them
        # as releases with empty sources keeps that gap visible (the owner's
        # complaint was a vault reading "0 releases" for works that list four).
        _enrich_with_declared_media(records[0], data)
        container = _detail_container(data)
        if container is not None:
            _apply_detail_evidence(records[0], container)
        else:
            _stamp_seasons(records[0])
    return records


def _detail_container(root, budget: int = 20000):
    """First dict holding ``subject``, ``stars`` and ``metadata`` together.

    A Nuxt detail page hydrates the detail answer under two keys (``data`` and
    ``state``); either carries the credits and keywords, which sit beside
    ``subject`` and are therefore invisible to the per-anchor lookups. Bounded
    breadth-first, because the graph is shared and cyclic.
    """
    queue = deque([root])
    seen = set()
    while queue and budget > 0:
        node = queue.popleft()
        budget -= 1
        if isinstance(node, dict):
            if (isinstance(node.get("subject"), dict)
                    and isinstance(node.get("stars"), list)
                    and isinstance(node.get("metadata"), dict)):
                return node
            children = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        if id(node) in seen:
            continue
        seen.add(id(node))
        for child in children:
            if isinstance(child, (dict, list)):
                queue.append(child)
    return None


def _credits_from_stars(stars):
    """``(cast, directors, writers)`` from ``stars[]``, one entry per person.

    Measured 2026-10-30: crew carry ``character`` "Director" (staffType 2) or
    "Writer" (staffType 3); actors carry the role played (staffType 1). A person
    repeats once per season, so entries are de-duplicated by ``staffId``.
    """
    cast, directors, writers = [], [], []
    seen = {"cast": set(), "director": set(), "writer": set()}
    for entry in stars if isinstance(stars, list) else []:
        if not isinstance(entry, dict):
            continue
        name = _as_text(entry.get("name"))
        if not name:
            continue
        ident = _as_text(entry.get("staffId")) or name.casefold()
        role = (_as_text(entry.get("character")) or "").strip().casefold()
        staff_type = _positive_int(entry.get("staffType"))
        if role == "director" or staff_type == 2:
            bucket, target = "director", directors
        elif role == "writer" or staff_type == 3:
            bucket, target = "writer", writers
        else:
            bucket, target = "cast", cast
        if ident not in seen[bucket]:
            seen[bucket].add(ident)
            target.append(name)
    return cast, directors, writers


def _split_dubs(dubs, subtitles):
    """Audio languages and subtitle languages, kept apart.

    ``dubs[]`` mixes both, distinguished only by ``type`` (0 = audio, 1 =
    subtitle) with free text in ``lanName`` ("French dub", "Arabic sub"), and
    ``subject.subtitles`` is a separate comma-separated blob. Joining them into
    one column erased which was which.
    """
    audio, subs = [], []
    for entry in dubs if isinstance(dubs, list) else []:
        if isinstance(entry, dict):
            name = _as_text(entry.get("lanName")) or _as_text(entry.get("lanCode"))
            if not name:
                continue
            if str(entry.get("type")).strip() == "1":
                subs.append(name)
            else:
                audio.append(name)
        elif isinstance(entry, str) and entry.strip():
            audio.append(entry.strip())
    blob = _as_text(subtitles)
    if blob:
        subs.extend(part.strip() for part in blob.split(",") if part.strip())
    audio, subs = list(dict.fromkeys(audio)), list(dict.fromkeys(subs))
    return (", ".join(audio) or None, ", ".join(subs) or None)


def _apply_detail_evidence(record: dict, container: dict) -> None:
    """Fill fields that live beside ``subject`` in a detail payload."""
    subject = container.get("subject")
    if not isinstance(subject, dict):
        subject = {}
    cast, directors, writers = _credits_from_stars(container.get("stars"))
    if cast:
        record["cast_names"] = ", ".join(cast)
    if directors:
        record["director"] = ", ".join(directors)
    if writers:
        record["raw_meta"]["writers"] = ", ".join(writers)
    audio, subs = _split_dubs(subject.get("dubs"), subject.get("subtitles"))
    if audio:
        record["languages"] = audio
    if subs:
        record["raw_meta"]["subtitles"] = subs
    metadata = container.get("metadata")
    if isinstance(metadata, dict):
        keywords = _as_text(metadata.get("keyWords"))
        if keywords:
            record["raw_meta"]["keywords"] = keywords
    _stamp_seasons(record)


def parse_detail_api(payload, page_url: str) -> list[dict]:
    """One record from the site's own JSON detail answer, or ``[]``.

    Measured 2026-10-30: ``GET {API_BASE}/detail?subjectId=…`` answers 200 with
    ~39 KB of JSON and no credential, where the same work's HTML page is ~410 KB.
    The payload repeats ``subject``/``stars``/``resource``/``metadata`` in the
    shape the page hydrates, so it feeds the same builders — fewer bytes and less
    parse work for identical data. This never replays a credential: an answer
    that is not this public shape yields ``[]`` and the caller should stop, not
    send a token.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("subject"), dict):
        return []
    record = _build_record(data["subject"], _collect_candidates(data), page_url)
    if not record:
        return []
    # A detail answer names exactly one work, so its renditions cannot belong to
    # a sibling the way a listing page's could.
    _enrich_with_declared_media(record, data)
    _apply_detail_evidence(record, data)
    return [record]


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


def http_get(url: str, timeout: int = PAGE_TIMEOUT, retries: int | None = None,
             debug: dict | None = None, delay: float = DEFAULT_DELAY,
             transport_retries: int = TRANSPORT_RETRIES) -> tuple[int, str, str]:
    """Returns (status, final_url, body). Status 0 means transport failure.

    The two failure kinds are budgeted separately because they mean different
    things here. An HTTP answer came from the origin and is evidence about the
    page, so it is retried once. A reset arrived before the origin spoke — on this
    site that is the normal case, ~2 of 3 handshakes fail from this host,
    independent of path, IP and HTTP version — so it is retried hard. Under the
    old single budget of two attempts, a whole crawl silently lost most of the
    catalog to a CDN flap and the vault stayed empty.

    Every attempt goes through the shared throttle, so retrying cannot burst past
    the politeness floor the way a private sleep loop would.
    """
    if retries is None:
        retries = HTTP_ERROR_RETRIES
    budget = max(1, min(MAX_CONNECTIONS_PER_PAGE,
                        1 + max(0, transport_retries) + max(0, retries)))
    transport_left = max(0, transport_retries)
    http_left = max(0, retries)
    last = (0, url, "")
    for attempt in range(budget):
        if attempt:
            time.sleep(0.25 + 0.15 * (attempt % 4))
        _throttle(delay)
        try:
            with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                return resp.status, resp.geturl(), body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            last = (exc.code, url, body)
            if exc.code == RATE_LIMIT_STATUS or http_left == 0:
                return last
            http_left -= 1
        except Exception as exc:  # URLError, timeout, reset, bad TLS
            last = (0, url, "")
            if debug is not None:
                debug.setdefault("transport_error", f"{type(exc).__name__}: {exc}")
            if transport_left == 0:
                return last
            transport_left -= 1
    return last


def http_head(url: str, timeout: int = PAGE_TIMEOUT, delay: float = DEFAULT_DELAY,
              transport_retries: int = TRANSPORT_RETRIES) -> int:
    """A HEAD probe for a direct file. Returns the status, 0 on transport failure."""
    for attempt in range(max(1, transport_retries + 1)):
        if attempt:
            time.sleep(0.25 + 0.15 * (attempt % 4))
        _throttle(delay)
        try:
            with urllib.request.urlopen(_request(url, method="HEAD"),
                                        timeout=timeout) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except Exception:
            continue
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
# Discovery (the site's own catalog feed)
# ---------------------------------------------------------------------------

def _api_request(path: str, payload: dict, timeout: int = API_TIMEOUT,
                 delay: float = DEFAULT_DELAY) -> tuple[int, dict | None]:
    """POST to the catalog service; returns (status, parsed body). Never raises."""
    status, _final, body = (0, "", "")
    for attempt in range(TRANSPORT_RETRIES + 1):
        status, _final, body = http_get_json(f"{API_BASE}{path}", payload,
                                            timeout=timeout, delay=delay)
        if status not in (0, RATE_LIMIT_STATUS):
            break
        if STOP_REQUESTED:
            break
    if not body:
        return status, None
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, None


def http_get_json(url: str, payload: dict, timeout: int = API_TIMEOUT,
                  delay: float = DEFAULT_DELAY) -> tuple[int, str, str]:
    """``http_get`` with a JSON body: same reset-tolerant budget, POST instead of GET."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json",
               "Content-Type": "application/json",
               "Origin": BASE_URL, "Referer": f"{BASE_URL}/"}
    last = (0, url, "")
    for attempt in range(max(1, TRANSPORT_RETRIES + 1)):
        if attempt:
            time.sleep(0.25 + 0.15 * (attempt % 4))
        _throttle(delay)
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, data=data, headers=headers),
                    timeout=timeout) as resp:
                return resp.status, resp.geturl(), resp.read().decode("utf-8",
                                                                      "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, url, (exc.read().decode("utf-8", "replace")
                                   if exc.fp else "")
        except Exception:
            continue
    return last


def _detail_url(item: dict) -> str | None:
    """A work's page address, built the way the site itself builds it."""
    path = _as_text(item.get("detailPath"))
    if not path:
        return None
    return f"{BASE_URL}{DETAIL_PREFIX}{path.strip('/')}"


def detail_api_url(subject_id) -> str:
    return f"{API_BASE}/detail?subjectId={urllib.parse.quote(str(subject_id))}"


def _queued_subject_id(row) -> str | None:
    """The ``subjectId`` a queue row carries, or None for an HTML-only row.

    Rows queued before 2026-10-30 carry ``{}``; they crawl from their page, which
    the parser handles. Rows queued by ``sync``/``harvest`` carry the id so the
    crawl can read the 39 KB JSON answer instead of the 410 KB HTML one.
    """
    try:
        raw = row["raw_json"]
    except (KeyError, IndexError, TypeError):
        return None
    if not raw:
        return None
    try:
        ledger = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(ledger, dict):
        return _as_text(ledger.get("subjectId"))
    return None


def _walk_feed(subject_types=ACCEPTED_SUBJECT_TYPES, pages: int = API_MAX_PAGES,
               per_page: int = API_PAGE_SIZE, delay: float = DEFAULT_DELAY):
    """Yield ``(item, detail_url)`` for every work the feed names.

    Paginated instead of page-scraped: one request here describes 50 works with
    the same fields the SSR payload carries, which on a one-core box behind an
    edge that resets two thirds of handshakes is the difference between covering
    the catalog and covering a rounding error of it.

    Measured 2026-10-30 on this host, and it decides the request budget: the
    ``subjectType`` body key is **ignored**. ``{"subjectType": 1}``,
    ``{"subjectType": 2}``, ``{"subjectType": "1"}``, ``{"subjectTypes": [1]}``
    and ``{"subjectType": 1, "areaName": "india"}`` all answer the same mixed
    popularity page (identical type histogram, items shuffled between calls).
    ``sort`` is honored and swaps in different non-works entirely: ``sort=newest``
    returns subjectType 7 (concert mixes) and ``sort=hot`` returns subjectType 9
    (sports clips). So looping the accepted types would fetch one random soup
    twice for nothing, and only the item's own ``subjectType`` field classifies.
    One pass over the pages, whitelist applied where the data actually is.
    """
    page = 1
    while page <= max(1, pages):
        if STOP_REQUESTED:
            return
        ok, reason = memory_ok()
        if not ok:
            log(f"[!] [{SITE}] feed stopped: {reason}")
            return
        status, body = _api_request(API_FILTER_PATH, {
            "page": page, "perPage": per_page}, delay=delay)
        if status == RATE_LIMIT_STATUS:
            log(f"[!] [{SITE}] feed HTTP 429 at page {page}")
            return
        if status != 200 or not isinstance(body, dict) or body.get("code") != 0:
            log(f"[!] [{SITE}] feed page {page} -> "
                f"HTTP {status} {(body or {}).get('message', '')!r}")
            return
        data = body.get("data") or {}
        items = data.get("items") or []
        if not items:
            break
        for item in items:
            if isinstance(item, dict):
                url = _detail_url(item)
                if url:
                    yield item, url
        pager = data.get("pager") or {}
        if not pager.get("hasMore"):
            break
        try:
            page = int(str(pager.get("nextPage")))
        except (TypeError, ValueError):
            break


def _existing_keys(conn: sqlite3.Connection) -> set:
    try:
        return {row[0] for row in conn.execute("SELECT canonical_key FROM posts")}
    except sqlite3.Error:
        return set()


def sync_catalog(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                 seeds=(), pages: int = API_MAX_PAGES,
                 per_page: int = API_PAGE_SIZE, verbose: bool = True) -> dict:
    """Queue detail pages from the catalog feed (plus any explicitly seeded URL).

    The old version of this function read ``/sitemap.xml``. That path answers HTTP
    404 on this site — measured, 12 connections, one of which returned a complete
    HTML 404 page — so the queue could only ever fill with zero rows.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    totals = {"pages": 0, "queued": 0, "duplicates": 0, "errors": 0, "items": 0}
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        known = _existing_keys(conn)

        def queue(loc, lastmod=None, slug=None, subject_id=None):
            if not loc:
                return
            # Keep the id the feed already gave us: the crawl can then ask the
            # JSON detail endpoint (39 KB) instead of the HTML page (410 KB).
            raw = json.dumps({"subjectId": subject_id}) if subject_id else "{}"
            cur = conn.execute(
                "INSERT OR IGNORE INTO sitemap_cache (loc, lastmod, slug, scraped,"
                " raw_json, error_count) VALUES (?, ?, ?, 0, ?, 0)",
                (loc, lastmod, slug or (loc.rstrip("/").rsplit("/", 1)[-1]
                                        or None), raw))
            if cur.rowcount:
                totals["queued"] += 1
            else:
                totals["duplicates"] += 1

        for seed in seeds or ():
            if seed:
                queue(seed)

        for item, url in _walk_feed(pages=pages, per_page=per_page):
            if STOP_REQUESTED:
                break
            totals["items"] += 1
            key = fast_fetch.generate_canonical_key(
                _first_text(item, TITLE_KEYS) or "",
                _year_of(_lookup(item, [], DATE_KEYS)))
            # A dubbed print is a separate subject with the same title and year, so
            # queueing every one of them spends connections re-fetching a work whose
            # row already exists and lets the last dub win the upsert.
            if key in known:
                totals["duplicates"] += 1
                continue
            known.add(key)
            totals["pages"] += 1
            queue(url, _lookup(item, [], DATE_KEYS),
                  _as_text(item.get("detailPath")),
                  _as_text(item.get("subjectId")))
            if limit and totals["queued"] >= limit:
                break
        conn.commit()
    finally:
        conn.close()
    if verbose:
        log(f"[✓] [{SITE}] sync items={totals['items']} queued={totals['queued']} "
            f"duplicates={totals['duplicates']}")
    return totals


def harvest_catalog(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
                    pages: int = API_MAX_PAGES, per_page: int = API_PAGE_SIZE,
                    verbose: bool = True) -> dict:
    """Write catalog rows straight from the feed, and queue each page for enrichment.

    This is the ingest that MovieBox can honestly support today: the feed carries
    the full subject (title, year, run time, genre, cover, rating, subtitles,
    dub list, adult flags) and the playable print is nowhere in it. So a harvest
    produces **metadata-only** rows — no ``sources``, no trailer recorded as if it
    were the film — plus one release per rendition the subject declares. ``crawl``
    remains for the detail pages, which add season/episode structure and any
    print the site later exposes in HTML.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    totals = {"items": 0, "posts": 0, "duplicates": 0, "skipped_type": 0,
              "queued": 0, "stopped_for_memory": False}
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    batch: list[dict] = []
    try:
        ensure_schema(conn)
        known = _existing_keys(conn)
        for item, url in _walk_feed(pages=pages, per_page=per_page):
            if STOP_REQUESTED:
                break
            totals["items"] += 1
            record = _build_record(item, [], url)
            if not record:
                totals["skipped_type"] += 1
                continue
            _enrich_with_declared_media(record, item)
            if record["canonical_key"] in known:
                totals["duplicates"] += 1
                continue
            known.add(record["canonical_key"])
            conn.execute(
                "INSERT OR IGNORE INTO sitemap_cache (loc, lastmod, slug, scraped,"
                " raw_json, error_count) VALUES (?, ?, ?, 0, ?, 0)",
                (url, record.get("release_date"), record["slug"],
                 json.dumps({"subjectId": _as_text(item.get("subjectId"))})
                 if _as_text(item.get("subjectId")) else "{}"))
            totals["queued"] += 1
            batch.append(record)
            if len(batch) >= BATCH_SIZE:
                totals["posts"] += export_staging(db_path, batch,
                                                  conn=conn)["posts_written"]
                conn.commit()
                batch = []
                if not memory_ok()[0]:
                    totals["stopped_for_memory"] = True
                    log(f"[!] [{SITE}] harvest STOP: {memory_ok()[1]}")
                    break
            if limit and totals["posts"] + len(batch) >= limit:
                break
        if batch:
            totals["posts"] += export_staging(db_path, batch,
                                              conn=conn)["posts_written"]
        conn.commit()
    finally:
        conn.close()
    if verbose:
        log(f"[✓] [{SITE}] harvest items={totals['items']} posts={totals['posts']} "
            f"duplicates={totals['duplicates']} skipped_type={totals['skipped_type']}"
            + (" stopped=memory" if totals["stopped_for_memory"] else ""))
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


def export_staging(db_path: Path | str = DEFAULT_DB_PATH, posts=(),
                   conn: sqlite3.Connection | None = None) -> dict:
    """Upserts parsed records; a re-export of one page replaces its releases+sources.

    ``conn`` lets a caller that already holds a write transaction on this database
    reuse its own connection. Opening a second writer against the same file would
    make SQLite wait the full 60 s timeout and then raise ``database is locked``,
    which is exactly how a live harvest dies at its first batch.
    """
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
        if own:
            conn.commit()
    finally:
        if own:
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

    totals = {"pages": 0, "api_pages": 0, "posts": 0, "releases": 0, "sources": 0,
              "failed_rows": 0, "parked": 0, "failed": 0, "metadata_only": 0,
              "with_media": 0,
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
        subject_id = _queued_subject_id(row)
        if subject_id:
            # Same work, a tenth of the bytes, no Nuxt unflatten.
            return http_get(detail_api_url(subject_id), timeout=API_TIMEOUT,
                            delay=delay)
        return http_get(row["loc"], timeout=PAGE_TIMEOUT, delay=delay)

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
        subject_id = _queued_subject_id(row)
        if subject_id:
            totals["api_pages"] += 1
            try:
                payload = json.loads(body)
            except (TypeError, ValueError):
                payload = None
            records = parse_detail_api(payload, loc)
        else:
            records = parse_page(body, loc)
        if not records:
            totals["failed_rows"] += 1
            _bump_error(db_path, loc, _failure(
                "detail-api-shape" if subject_id else "no-subject", status, final,
                "detail answer was not the public subject shape" if subject_id
                else "page carried no titled subject in its Nuxt payload"))
            return
        # A subject with no print is the expected outcome on this site, not a
        # failure: the play URL is resolved client-side. It is written as a
        # metadata row and marked crawled, so a re-run does not keep spending
        # connections on it looking for a stream the page never contains.
        # "No media" is decided by sources, not releases: declared renditions
        # carry no URL and are still metadata-only.
        if all(not any(rel["sources"] for rel in rec["releases"])
               for rec in records):
            totals["metadata_only"] += 1
        else:
            totals["with_media"] += 1
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
            f"metadata_only={totals['metadata_only']} "
            f"with_media={totals['with_media']} "
            f"failed_rows={totals['failed_rows']} parked={totals['parked']} "
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
            # A work with no *source* is this site's normal shape, not a broken
            # row: its prints are declared by tier but their URLs are resolved by
            # a client-side call. Counting by sources rather than releases is
            # what stops a merge from treating "four tiers, no URL" as a
            # playable title — or as a work that does not exist.
            "metadata_only_posts": q(
                "SELECT COUNT(*) FROM posts p WHERE NOT EXISTS ("
                " SELECT 1 FROM sources s JOIN releases r ON s.release_id = r.id"
                " WHERE r.post_canonical_key = p.canonical_key)"),
            "trailer_evidence_posts": q(
                "SELECT COUNT(*) FROM posts WHERE raw_meta LIKE '%trailer_url%'"),
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

    sync = sub.add_parser("sync", help="queue detail pages from the catalog feed")
    sync.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sync.add_argument("--limit", type=int)
    sync.add_argument("--pages", type=int, default=API_MAX_PAGES,
                      help=f"feed pages to walk per subject type (default {API_MAX_PAGES})")
    sync.add_argument("--per-page", type=int, default=API_PAGE_SIZE,
                      help="works per feed request (default 50)")
    sync.add_argument("--seed", action="append", default=[],
                      help="an explicit page URL to queue (repeatable)")

    harvest = sub.add_parser("harvest",
                             help="write catalog rows straight from the feed")
    harvest.add_argument("--db", default=str(DEFAULT_DB_PATH))
    harvest.add_argument("--limit", type=int)
    harvest.add_argument("--pages", type=int, default=API_MAX_PAGES)
    harvest.add_argument("--per-page", type=int, default=API_PAGE_SIZE)

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
        totals = sync_catalog(args.db, limit=args.limit, seeds=args.seed,
                              pages=args.pages, per_page=args.per_page)
    elif args.command == "harvest":
        totals = harvest_catalog(args.db, limit=args.limit, pages=args.pages,
                                 per_page=args.per_page)
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
