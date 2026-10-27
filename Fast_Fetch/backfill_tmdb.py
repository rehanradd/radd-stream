#!/usr/bin/env python3
"""Backfill artwork and identity metadata from TMDB, with a keyless Cinemeta
fallback for rows TMDB cannot name or has no credentials to reach.

The catalog was scraped from ten sites whose pages carry different amounts of
art. Some rows have a poster and no backdrops, some have neither, and almost no
scraper wrote per-season or per-episode images. This script asks TMDB once per
title and writes what it finds into the two places the API reads:

* the **work** — `posts.poster_url`, `posts.backdrop_urls` (a JSON array), and
  the identity columns `posts.tmdb_id` / `posts.imdb_id` when they are empty;
* the **seasons** — `post_artwork`, one `season_poster` row per season and one
  `episode_still` row per episode. `viewer.api_v1_get_post_detail()` publishes
  these as `season_artwork`, and the app prefers them over its fallback of
  spreading work-level backdrops across the season list.

Lookup order is cheapest-first: a stored `tmdb_id`, then an IMDb id through
`/find`, then a title search with the year. A search result is accepted only
when its title normalises to the same words and its year is within one; a miss
is reported as a miss rather than mapping a different film's poster.

Fast and lightweight by construction:

* stdlib only (`urllib`, `sqlite3`, `ThreadPoolExecutor`) — no pip;
* network work runs in a small worker pool, SQLite writes stay on the main
  thread, one transaction per batch;
* every request shares one global minimum interval (default 20/s), so raising
  `--workers` overlaps latency instead of hammering TMDB;
* `--limit`, `--after-id` and a batch-level commit make a long run resumable;
* `--dry-run` prints what would be written and touches nothing.

Credentials are read from the environment ONLY, because a key passed on the
command line is visible in the process list:

    TMDB_BEARER_TOKEN=...   # v4 read token, preferred
    TMDB_API_KEY=...        # v3 key, used as a query parameter

With neither set the run does not stop: Stremio's free, open-source Cinemeta
addon (`v3-cinemeta.strem.io`) answers by IMDb id or title with no key at all.
TMDB is still preferred where a key exists, and Cinemeta is consulted only when
TMDB could not name the work or the row still has no genres, synopsis or year.
Cinemeta also supplies a poster and one backdrop when none is stored, so a
keyless run is still an artwork backfill.

Typical use:

    TMDB_API_KEY=... python3 -S Fast_Fetch/backfill_tmdb.py --site hdtvb
    TMDB_API_KEY=... python3 -S Fast_Fetch/backfill_tmdb.py --db <path> --limit 1000 --dry-run
    python3 -S Fast_Fetch/backfill_tmdb.py --db <path> --limit 1000   # Cinemeta only
    python3 -S Fast_Fetch/backfill_tmdb.py --db <path> --no-cinemeta --dry-run
    TMDB_API_KEY=... python3 -S Fast_Fetch/backfill_tmdb.py --db <path> --force

A run is safe to repeat: existing root art is left alone unless `--force`, and a
season/episode row is upserted by its key. Rows with `is_18_plus = 1` are skipped
— they are stored but never presented, so spending TMDB calls on them would only
make the run longer.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sqlite3
import ssl
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import config
import fast_fetch

TMDB_API_ROOT = "https://api.themoviedb.org/3"
TMDB_IMAGE_ROOT = "https://image.tmdb.org/t/p"

#: Stremio's Cinemeta addon. Open source, no key, and it answers the two shapes
#: this script needs: `/meta/{movie|series}/{imdb_id}.json` for identity and
#: `/catalog/{movie|series}/top/search={title}.json` when no IMDb id is stored.
CINEMETA_API_ROOT = "https://v3-cinemeta.strem.io"

#: TMDB's documented canonical widths. Small enough for a phone, sharp enough
#: that the detail screen's 3.2:1 header is not visibly soft.
POSTER_SIZE = "w500"
BACKDROP_SIZE = "w1280"
SEASON_POSTER_SIZE = "w500"
STILL_SIZE = "w300"

#: A work's backdrop strip is a gallery, not an archive. Eight is plenty and
#: keeps the detail payload small.
MAX_BACKDROPS = 8

SERIES_TYPES = frozenset({"series", "ongoing_season", "complete_season"})
ART_KINDS = ("season_poster", "episode_still")

DEFAULT_WORKERS = 6
DEFAULT_MIN_INTERVAL = 0.05   # 20 requests/second, shared by every worker
DEFAULT_CINEMETA_INTERVAL = 0.10  # 10/second: a free public addon, not our key
DEFAULT_TIMEOUT = 20.0
BATCH = 200

_IMDB_RE = re.compile(r"^tt\d{6,10}$")
_YEAR_RE = re.compile(r"(?<!\d)((?:18|19|20|21)\d{2})(?!\d)")
_LEADING_NOISE_RE = re.compile(r"^\s*(?:download|watch|free\s+download)\s+", re.I)

#: Words that begin the release metadata tail of a scraper's headline. The cut
#: happens after the first word, so a title that legitimately starts with one
#: ("Hindi Medium", "English Vinglish") survives.
_NOISE_TAIL_RE = re.compile(
    r"\b(?:"
    r"480p|540p|576p|720p|1080p|2160p|4k|8k|"
    r"web[\s-]?dl|webrip|hdrip|bluray|blu[\s-]ray|dvdrip|hdts|hdtc|cam|predvd|"
    r"hevc|x264|x265|h\.?264|h\.?265|av1|aac|ddp?5\.1|"
    r"esubs?|subtitles?|subs|dual\s+audio|multi\s+audio|"
    r"season\s*\d+(?:\s*[-–]\s*\d+)?|"
    r"s\d{1,2}(?:\s*[-–]\s*s?\d{1,2})?(?:\s*e\d{1,4})?|"
    r"complete|all\s+episodes|full\s+show|web\s+series|"
    r"netflix|amazon|prime\s+video|hotstar|disney\+?|altbalaji|zee5|sonyliv|jiocinema|"
    r"hindi|english|tamil|telugu|malayalam|kannada|punjabi|urdu|dubbed"
    r")\b",
    re.I,
)
_GROUP_RE = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")


# ── pure text helpers (unit-tested without a network) ────────────────────────

def parse_year(value) -> int | None:
    """The first plausible year in a value, or None.

    `posts.year` is declared INTEGER but old rows hold labels like `2003–2006`,
    so a plain `int()` is not an option here."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1880 <= value <= 2200 else None
    match = _YEAR_RE.search(str(value))
    return int(match.group(1)) if match else None


def normalize_title(text) -> str:
    """Case/punctuation/width-insensitive form used only for equality checks."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold().replace("&", " and ")
    folded = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    return " ".join(folded.split())


def strip_title_noise(text) -> str:
    """A searchable title from a scraper headline.

    This is a lookup aid, never a stored value: the catalogue keeps the headline
    the site published, and only the query sent to TMDB is trimmed. A guard in
    `choose_candidate()` still refuses a result whose title does not match, so a
    wrong trim produces a miss rather than a different title's artwork.
    """
    cleaned = _LEADING_NOISE_RE.sub("", str(text or "")).strip()

    def keep_group(match: re.Match) -> str:
        inner = match.group(1)
        return " " if re.search(
            r"\d{4}|season|s\d|hindi|english|audio|480p|720p|1080p|2160p|"
            r"web|blu|complete|series", inner, re.I) else match.group(0)

    cleaned = _GROUP_RE.sub(keep_group, cleaned)
    match = _NOISE_TAIL_RE.search(cleaned)
    if match and cleaned[:match.start()].strip():
        cleaned = cleaned[:match.start()]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—:|.")
    return cleaned


def search_titles(clean_title, title) -> list[str]:
    """Distinct, non-empty lookup titles, most specific first."""
    out: list[str] = []
    for value in (clean_title, title):
        candidate = strip_title_noise(value)
        if candidate and candidate.casefold() not in {item.casefold() for item in out}:
            out.append(candidate)
    return out


def is_series_like(content_type, seasons) -> bool:
    ctype = str(content_type or "").strip().casefold()
    return ctype in SERIES_TYPES or bool(str(seasons or "").strip())


def normalize_imdb_id(value) -> str | None:
    text = str(value or "").strip().casefold()
    return text if _IMDB_RE.fullmatch(text) else None


def normalize_rating(value) -> str | None:
    """A one-decimal rating string, or None for anything that is not a score.

    Cinemeta reports `imdbRating` as a decimal string; some scrapers wrote a
    `"7.8/10"` label into the same column, so the suffix is tolerated. Zero is
    treated as "unrated": it is what a missing score looks like, not a work
    every viewer hated."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().split("/", 1)[0].strip()
    try:
        rating = float(text)
    except (TypeError, ValueError):
        return None
    if not 0.0 < rating <= 10.0:
        return None
    return f"{rating:.1f}"


def cinemeta_kind(content_type, seasons) -> str:
    """The Cinemeta path segment for this row: `series` or `movie`."""
    return "series" if is_series_like(content_type, seasons) else "movie"


def cinemeta_year(meta: dict) -> int | None:
    """Cinemeta carries the year as `year` on a meta and `releaseInfo` on a search
    result; `releaseInfo` may be a range ("2020–2023"), so it goes through the
    same tolerant parser as the catalogue's own labels."""
    return parse_year(meta.get("year") or meta.get("releaseInfo"))


def choose_cinemeta_candidate(payload: dict, *, query: str,
                              year: int | None) -> dict | None:
    """The one Cinemeta search hit that names the same work, or None.

    Same guard as [choose_candidate]: normalized title equality (or a prefix,
    which covers "The Office" → "The Office (US)"), and a year within one when
    both sides have one."""
    wanted = normalize_title(query)
    if not wanted:
        return None
    best: tuple[int, dict] | None = None
    for item in payload.get("metas") or []:
        if not isinstance(item, dict) or item.get("adult"):
            continue
        name = normalize_title(item.get("name"))
        if not name:
            continue
        if name == wanted:
            score = 100
        elif len(wanted) >= 4 and (name.startswith(wanted) or wanted.startswith(name)):
            score = 90
        else:
            continue
        item_year = cinemeta_year(item)
        if year and item_year and abs(item_year - year) > 1:
            continue
        if year and item_year:
            score -= abs(item_year - year)
        elif year and not item_year:
            score -= 5
        if best is None or score > best[0]:
            best = (score, item)
    return best[1] if best else None


def image_url(path, size: str) -> str | None:
    text = str(path or "").strip()
    if not text.startswith("/"):
        return None
    return f"{TMDB_IMAGE_ROOT}/{size}{text}"


def _sort_images(images, *, textless_first: bool) -> list[dict]:
    """Best-first image records, honouring TMDB's own vote counts."""
    if not isinstance(images, list):
        return []
    usable = [item for item in images if isinstance(item, dict) and item.get("file_path")]

    def key(item: dict):
        language = item.get("iso_639_1")
        textless = 1 if language in (None, "") else 0
        english = 1 if language == "en" else 0
        return (
            textless if textless_first else 0,
            english,
            float(item.get("vote_average") or 0.0),
            int(item.get("vote_count") or 0),
        )

    return sorted(usable, key=key, reverse=True)


def best_poster(detail: dict) -> str | None:
    direct = image_url(detail.get("poster_path"), POSTER_SIZE)
    if direct:
        return direct
    for item in _sort_images((detail.get("images") or {}).get("posters"), textless_first=False):
        found = image_url(item.get("file_path"), POSTER_SIZE)
        if found:
            return found
    return None


def backdrop_pool(detail: dict) -> list[str]:
    """The work's backdrop gallery, best first, capped and de-duplicated."""
    out: list[str] = []

    def add(path):
        url = image_url(path, BACKDROP_SIZE)
        if url and url not in out and len(out) < MAX_BACKDROPS:
            out.append(url)

    add(detail.get("backdrop_path"))
    for item in _sort_images((detail.get("images") or {}).get("backdrops"), textless_first=True):
        add(item.get("file_path"))
    return out


def candidate_names(item: dict) -> list[str]:
    return [str(item.get(key) or "") for key in
            ("name", "title", "original_name", "original_title")]


def choose_candidate(payload: dict, *, query: str, year: int | None) -> dict | None:
    """The one search result that names the same work, or None.

    Exact normalised title first, then a prefix match (TMDB often appends a
    country or year: "The Office" → "The Office (US)"). A year, when both sides
    have one, must agree within a year — a remake is a different work."""
    wanted = normalize_title(query)
    if not wanted:
        return None
    best: tuple[int, dict] | None = None
    for item in payload.get("results") or []:
        if not isinstance(item, dict) or item.get("adult"):
            continue
        names = [normalize_title(name) for name in candidate_names(item) if name]
        if not names:
            continue
        hits = [name for name in names if name == wanted]
        if not hits:
            hits = [name for name in names
                    if len(wanted) >= 4 and (name.startswith(wanted) or wanted.startswith(name))]
        if not hits:
            continue
        item_year = parse_year(item.get("first_air_date") or item.get("release_date"))
        if year and item_year and abs(item_year - year) > 1:
            continue
        score = 100
        if hits[0] != wanted:
            score -= 10
        if year and item_year:
            score -= abs(item_year - year)
        elif year and not item_year:
            score -= 5
        if best is None or score > best[0]:
            best = (score, item)
    return best[1] if best else None


def choose_find_result(payload: dict, *, want_tv: bool) -> tuple[str, dict] | None:
    """The first usable `/find` result as `(kind, record)`.

    An IMDb id is exact identity, so the preferred medium wins and the other is
    only a fallback for a catalogue row whose content type was misread."""
    tv = [item for item in payload.get("tv_results") or [] if isinstance(item, dict)]
    movie = [item for item in payload.get("movie_results") or [] if isinstance(item, dict)]
    ordered = ((tv, "tv"), (movie, "movie")) if want_tv else ((movie, "movie"), (tv, "tv"))
    for rows, kind in ordered:
        if rows:
            return kind, rows[0]
    return None


def season_posters(season_payload: dict) -> str | None:
    """This season's own poster. Never the work's poster: a copy of it on every
    season is exactly what this backfill exists to stop."""
    direct = image_url(season_payload.get("poster_path"), SEASON_POSTER_SIZE)
    if direct:
        return direct
    for item in _sort_images((season_payload.get("images") or {}).get("posters"),
                             textless_first=False):
        found = image_url(item.get("file_path"), SEASON_POSTER_SIZE)
        if found:
            return found
    return None


def _artwork_row(post_id: int, kind: str, season: int, episode: int, url: str,
                 *, width=None, height=None, language=None) -> "ArtworkRow":
    return ArtworkRow(
        post_id=post_id,
        kind=kind,
        season_number=int(season),
        episode_number=int(episode),
        url=url,
        width=int(width) if width else None,
        height=int(height) if height else None,
        language=str(language) if language else None,
    )


def season_artwork(post_id: int, detail: dict, season_fetch, *,
                   include_specials: bool = False,
                   want_stills: bool = True) -> list["ArtworkRow"]:
    """Build season-poster and episode-still rows from a TV detail payload.

    `season_fetch(season_number)` returns a `/tv/{id}/season/{n}` payload and may
    be `None` when that call failed. Season posters come from the root detail's
    own `seasons[]` entries first, so shows whose seasons are already mapped cost
    no extra request; a season detail is fetched when stills are wanted or when
    that season's poster is missing."""
    rows: list[ArtworkRow] = []
    seasons = detail.get("seasons") or []
    if not isinstance(seasons, list):
        return rows
    ordered = []
    for entry in seasons:
        if not isinstance(entry, dict):
            continue
        try:
            number = int(entry.get("season_number"))
        except (TypeError, ValueError):
            continue
        if number < 0 or (number == 0 and not include_specials):
            continue
        ordered.append((number, entry))
    for number, entry in sorted(ordered, key=lambda pair: pair[0]):
        poster = image_url(entry.get("poster_path"), SEASON_POSTER_SIZE)
        payload = None
        if want_stills or poster is None:
            payload = season_fetch(number)
        if isinstance(payload, dict):
            poster = season_posters(payload) or poster
        if poster:
            rows.append(_artwork_row(post_id, "season_poster", number, 0, poster))
        if not want_stills or not isinstance(payload, dict):
            continue
        for episode in payload.get("episodes") or []:
            if not isinstance(episode, dict):
                continue
            try:
                episode_number = int(episode.get("episode_number"))
            except (TypeError, ValueError):
                continue
            if episode_number <= 0:
                continue
            still = image_url(episode.get("still_path"), STILL_SIZE)
            if still:
                rows.append(_artwork_row(post_id, "episode_still", number,
                                         episode_number, still))
    return rows


# ── HTTP client ──────────────────────────────────────────────────────────────

class TmdbError(RuntimeError):
    """A credential or protocol failure worth stopping for. Never carries a URL."""


class _Pace:
    """One global minimum interval, shared by every worker.

    The lock is released before sleeping, so workers queue by start time rather
    than serialising the whole request."""

    def __init__(self, interval: float):
        self.interval = max(0.0, float(interval))
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self.interval
        if delay:
            time.sleep(delay)


class TmdbClient:
    def __init__(self, *, api_key: str = "", bearer_token: str = "",
                 min_interval: float = DEFAULT_MIN_INTERVAL,
                 timeout: float = DEFAULT_TIMEOUT, retries: int = 3):
        if not api_key and not bearer_token:
            raise ValueError("a TMDB key or bearer token is required")
        self._api_key = api_key
        self._bearer = bearer_token
        self._timeout = timeout
        self._retries = max(1, retries)
        self._pace = _Pace(min_interval)
        self._ssl = ssl.create_default_context()

    def _headers(self) -> dict:
        headers = {"Accept": "application/json",
                   "User-Agent": "radd-stream-tmdb-backfill/1.0"}
        if self._bearer:
            headers["Authorization"] = f"Bearer {self._bearer}"
        return headers

    def _url(self, path: str, params: dict | None) -> str:
        query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        if self._api_key:
            query["api_key"] = self._api_key
        encoded = urllib.parse.urlencode(query)
        return f"{TMDB_API_ROOT}{path}" + (f"?{encoded}" if encoded else "")

    def get(self, path: str, params: dict | None = None) -> dict | None:
        """One JSON object, or None for a 404. A key failure raises [TmdbError]."""
        url = self._url(path, params)
        last_error: Exception | None = None
        for attempt in range(self._retries):
            self._pace.wait()
            try:
                request = urllib.request.Request(url, headers=self._headers())
                with urllib.request.urlopen(request, timeout=self._timeout,
                                            context=self._ssl) as response:
                    body = response.read().decode("utf-8", "replace")
                parsed = json.loads(body)
                return parsed if isinstance(parsed, dict) else {}
            except urllib.error.HTTPError as error:
                status = int(error.code)
                if status == 404:
                    return None
                if status in (401, 403):
                    raise TmdbError("TMDB refused the configured credentials") from None
                if status == 429:
                    retry_after = error.headers.get("Retry-After") if error.headers else None
                    try:
                        delay = min(30.0, max(1.0, float(retry_after or 2)))
                    except (TypeError, ValueError):
                        delay = 2.0
                    time.sleep(delay)
                    last_error = error
                    continue
                if 500 <= status < 600:
                    last_error = error
                    time.sleep(min(8.0, 2.0 ** attempt))
                    continue
                last_error = error
                break
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
                last_error = error
                time.sleep(min(8.0, 2.0 ** attempt))
        raise TmdbError(f"TMDB request failed after {self._retries} attempts: "
                        f"{type(last_error).__name__ if last_error else 'unknown'}")

    # ── the endpoints this script needs ─────────────────────────────────────

    def find(self, imdb_id: str) -> dict | None:
        return self.get(f"/find/{urllib.parse.quote(imdb_id)}",
                        {"external_source": "imdb_id"})

    def search(self, kind: str, query: str, year: int | None) -> dict | None:
        params = {"query": query, "include_adult": "false", "language": "en-US"}
        if year:
            params["first_air_date_year" if kind == "tv" else "year"] = year
        return self.get(f"/search/{kind}", params)

    def detail(self, kind: str, tmdb_id: int) -> dict | None:
        return self.get(f"/{kind}/{int(tmdb_id)}",
                        {"append_to_response": "images,external_ids",
                         "language": "en-US"})

    def season(self, tmdb_id: int, season_number: int) -> dict | None:
        return self.get(f"/tv/{int(tmdb_id)}/season/{int(season_number)}",
                        {"append_to_response": "images", "language": "en-US"})


class CinemetaError(RuntimeError):
    """Cinemeta could not be reached. Never carries a URL."""


class CinemetaClient:
    """Keyless metadata from Stremio's open-source Cinemeta addon.

    Identity first: a stored IMDb id is answered by `/meta`, which is exact and
    costs one request. A title search is the fallback and is guarded by the same
    normalized-name and year-within-one rule TMDB's search uses, so a remake or
    a similarly named film is a miss rather than the wrong poster.

    No credentials exist to fail, so a transport failure is a [CinemetaError]
    and the caller keeps whatever TMDB already produced. Pacing is shared per
    client; the addon is free and public, not something to hammer."""

    def __init__(self, *, min_interval: float = DEFAULT_CINEMETA_INTERVAL,
                 timeout: float = DEFAULT_TIMEOUT, retries: int = 2):
        self._timeout = timeout
        self._retries = max(1, retries)
        self._pace = _Pace(min_interval)
        self._ssl = ssl.create_default_context()

    def _headers(self) -> dict:
        return {"Accept": "application/json",
                "User-Agent": "radd-stream-cinemeta-fallback/1.0"}

    def _get(self, path: str) -> dict | None:
        """One JSON object, or None for a 404."""
        url = f"{CINEMETA_API_ROOT}{path}"
        last_error: Exception | None = None
        for attempt in range(self._retries):
            self._pace.wait()
            try:
                request = urllib.request.Request(url, headers=self._headers())
                with urllib.request.urlopen(request, timeout=self._timeout,
                                            context=self._ssl) as response:
                    body = response.read().decode("utf-8", "replace")
                parsed = json.loads(body)
                return parsed if isinstance(parsed, dict) else {}
            except urllib.error.HTTPError as error:
                if int(error.code) == 404:
                    return None
                last_error = error
                if 500 <= int(error.code) < 600:
                    time.sleep(min(4.0, 2.0 ** attempt))
                    continue
                break
            except (urllib.error.URLError, TimeoutError, OSError,
                    json.JSONDecodeError) as error:
                last_error = error
                time.sleep(min(4.0, 2.0 ** attempt))
        raise CinemetaError(
            f"Cinemeta request failed after {self._retries} attempts: "
            f"{type(last_error).__name__ if last_error else 'unknown'}")

    def meta(self, kind: str, imdb_id: str) -> dict | None:
        payload = self._get(f"/meta/{kind}/{urllib.parse.quote(str(imdb_id))}.json")
        meta = (payload or {}).get("meta")
        return meta if isinstance(meta, dict) and meta else None

    def search(self, kind: str, query: str) -> dict | None:
        encoded = urllib.parse.quote(str(query), safe="")
        payload = self._get(f"/catalog/{kind}/top/search={encoded}.json")
        return payload if isinstance(payload, dict) else None

    def lookup(self, *, imdb_id: str | None = None, titles=(),
               year: int | None = None, series: bool = False) -> dict | None:
        """A full meta for this work, or None.

        The preferred medium is tried first and the other second, because a row
        whose content type was misread still has exact IMDb identity. A title
        search then resolves to its best candidate's own meta record."""
        kinds = ("series", "movie") if series else ("movie", "series")
        if imdb_id:
            for kind in kinds:
                meta = self.meta(kind, imdb_id)
                if meta:
                    return meta
        for query in titles:
            for kind in kinds:
                payload = self.search(kind, query)
                candidate = choose_cinemeta_candidate(payload or {}, query=query,
                                                      year=year)
                if not candidate:
                    continue
                found = self.meta(kind, candidate["id"]) if candidate.get("id") else None
                return found or candidate
        return None


# ── planning one post ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ArtworkRow:
    post_id: int
    kind: str
    season_number: int
    episode_number: int
    url: str
    width: int | None = None
    height: int | None = None
    language: str | None = None


@dataclass
class PostPlan:
    post_id: int
    updates: dict = field(default_factory=dict)
    artwork: list[ArtworkRow] = field(default_factory=list)
    outcome: str = "no-match"


def _row_value(row, key, default=None):
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return default


def _blank(value) -> bool:
    """True for the several shapes an empty text column can take here: a scraper
    wrote `''`, an older writer wrote the literal JSON `[]`, or it is NULL."""
    return str(value or "").strip() in ("", "[]")


def metadata_missing(row, updates: dict | None = None) -> bool:
    """Whether this row (or the plan so far) still lacks a fact the Cinemeta
    fallback exists to supply: genres, synopsis, year or the IMDb score."""
    planned = updates or {}

    def current(key):
        return planned[key] if key in planned else _row_value(row, key)

    return (_blank(current("genres")) or _blank(current("synopsis"))
            or parse_year(current("year")) is None
            or normalize_rating(current("imdb_rating")) is None)


def cinemeta_updates(row, meta: dict, *, force: bool = False) -> dict:
    """The writes a Cinemeta meta can justify, limited to what is missing.

    A value that is already stored is left alone unless `force`, the same rule
    TMDB art follows. Genres go in as the JSON array string the API publishes;
    the single `background` is stored as a one-entry backdrop gallery."""
    updates: dict = {}

    def missing(key) -> bool:
        return force or _blank(_row_value(row, key))

    genres = meta.get("genres")
    if isinstance(genres, str):
        genres = [part.strip() for part in genres.split(",")]
    if isinstance(genres, list):
        genres = [str(item).strip() for item in genres if str(item).strip()]
    else:
        genres = []
    if genres and missing("genres"):
        updates["genres"] = json.dumps(genres)

    synopsis = str(meta.get("description") or "").strip()
    if synopsis and missing("synopsis"):
        updates["synopsis"] = synopsis

    year = cinemeta_year(meta)
    if year is not None and (force or parse_year(_row_value(row, "year")) is None):
        updates["year"] = int(year)

    rating = normalize_rating(meta.get("imdbRating"))
    if rating and (force or normalize_rating(_row_value(row, "imdb_rating")) is None):
        updates["imdb_rating"] = rating

    imdb_id = normalize_imdb_id(meta.get("id"))
    if imdb_id and not normalize_imdb_id(_row_value(row, "imdb_id")):
        updates["imdb_id"] = imdb_id

    poster = str(meta.get("poster") or "").strip()
    if poster.startswith(("http://", "https://")) and missing("poster_url"):
        updates["poster_url"] = poster

    background = str(meta.get("background") or "").strip()
    if background.startswith(("http://", "https://")) and missing("backdrop_urls"):
        updates["backdrop_urls"] = json.dumps([background])
    return updates


def plan_post(row, client: TmdbClient | None, *, force: bool = False,
              include_specials: bool = False,
              want_stills: bool = True,
              fallback: CinemetaClient | None = None) -> PostPlan:
    """Resolve one stored row to a work and plan its writes.

    `client` is optional: a run with no TMDB credentials passes None and goes
    straight to the keyless `fallback`. With a key, Cinemeta is still consulted
    when TMDB names nothing or the row still has no genres, synopsis or year.

    TMDB network failures inside a worker are allowed to propagate; the caller
    counts them and leaves the row untouched, so a transient outage never
    deletes art. A Cinemeta failure is swallowed here instead: whatever TMDB
    already produced is still worth writing.
    """
    post_id = int(_row_value(row, "id"))
    title = _row_value(row, "title") or ""
    clean_title = _row_value(row, "clean_title") or ""
    year = parse_year(_row_value(row, "year"))
    series = is_series_like(_row_value(row, "content_type"), _row_value(row, "seasons"))
    stored_tmdb = _row_value(row, "tmdb_id")
    try:
        stored_tmdb = int(stored_tmdb) if stored_tmdb not in (None, "", 0) else None
    except (TypeError, ValueError):
        stored_tmdb = None
    imdb_id = normalize_imdb_id(_row_value(row, "imdb_id"))

    kind = ""
    tmdb_id = None
    detail = None

    if client is not None and stored_tmdb:
        preferred = "tv" if series else "movie"
        detail = client.detail(preferred, stored_tmdb)
        if detail is not None:
            kind, tmdb_id = preferred, stored_tmdb
        else:
            other = "movie" if preferred == "tv" else "tv"
            detail = client.detail(other, stored_tmdb)
            if detail is not None:
                kind, tmdb_id = other, stored_tmdb

    if client is not None and detail is None and imdb_id:
        found = client.find(imdb_id)
        picked = choose_find_result(found or {}, want_tv=series)
        if picked:
            kind, record = picked
            tmdb_id = record.get("id")
            if tmdb_id:
                detail = client.detail(kind, int(tmdb_id))

    if client is not None and detail is None:
        queries = search_titles(clean_title, title)
        kinds = ("tv", "movie") if series else ("movie", "tv")
        for query in queries:
            for search_kind in kinds:
                payload = client.search(search_kind, query, year)
                candidate = choose_candidate(payload or {}, query=query, year=year)
                if not candidate:
                    continue
                tmdb_id = candidate.get("id")
                if tmdb_id:
                    detail = client.detail(search_kind, int(tmdb_id))
                    if detail is not None:
                        kind = search_kind
                        break
            if detail is not None:
                break

    updates: dict = {}
    artwork: list[ArtworkRow] = []
    outcome = "no-match"

    if detail is not None and tmdb_id:
        poster = best_poster(detail)
        if poster and (force or not str(_row_value(row, "poster_url") or "").strip()):
            updates["poster_url"] = poster
        backdrops = backdrop_pool(detail)
        stored_backdrops = str(_row_value(row, "backdrop_urls") or "").strip()
        if backdrops and (force or stored_backdrops in ("", "[]")):
            updates["backdrop_urls"] = json.dumps(backdrops)

        if not stored_tmdb:
            updates["tmdb_id"] = int(tmdb_id)
        external = detail.get("external_ids") or {}
        found_imdb = normalize_imdb_id(external.get("imdb_id"))
        if found_imdb and not imdb_id:
            updates["imdb_id"] = found_imdb

        if kind == "tv":
            artwork = season_artwork(
                post_id, detail,
                lambda number: client.season(int(tmdb_id), number),
                include_specials=include_specials,
                want_stills=want_stills,
            )

        matched_by = "stored-id" if stored_tmdb else ("imdb" if imdb_id else "title")
        outcome = f"matched-{matched_by}"

    # Keyless fallback: no key at all, TMDB named nothing, or a TMDB match whose
    # row still cannot feed the app's genre/synopsis/year fields.
    if fallback is not None and (detail is None or force or metadata_missing(row, updates)):
        meta = None
        try:
            meta = fallback.lookup(
                imdb_id=imdb_id or updates.get("imdb_id"),
                titles=search_titles(clean_title, title),
                year=year,
                series=series,
            )
        except CinemetaError:
            meta = None
        if meta:
            for key, value in cinemeta_updates(row, meta, force=force).items():
                updates.setdefault(key, value)
            if detail is None:
                outcome = "matched-cinemeta"

    if outcome == "no-match" and not updates:
        return PostPlan(post_id=post_id, outcome="no-match")
    return PostPlan(post_id=post_id, updates=updates, artwork=artwork,
                    outcome=outcome)


# ── SQLite ───────────────────────────────────────────────────────────────────

_UPSERT_ART = """
INSERT INTO post_artwork
    (post_id, kind, season_number, episode_number, url, source, width, height, language)
VALUES (?, ?, ?, ?, ?, 'tmdb', ?, ?, ?)
ON CONFLICT(post_id, kind, season_number, episode_number) DO UPDATE SET
    url = excluded.url,
    source = excluded.source,
    width = excluded.width,
    height = excluded.height,
    language = excluded.language,
    updated_at = CURRENT_TIMESTAMP
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def post_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(posts)")}


def select_columns(columns: set[str]) -> str:
    """The columns the planner reads, with honest NULLs for old databases."""
    wanted = ["id", "title", "clean_title", "year", "content_type", "seasons",
              "poster_url", "backdrop_urls", "genres", "synopsis", "imdb_rating"]
    parts = []
    for name in wanted:
        parts.append(name if name in columns else f"NULL AS {name}")
    parts.append("tmdb_id" if "tmdb_id" in columns else "NULL AS tmdb_id")
    parts.append("imdb_id" if "imdb_id" in columns else "NULL AS imdb_id")
    return ", ".join(parts)


def _missing_metadata_sql(columns: set[str]) -> str | None:
    """Candidates the Cinemeta fallback can still improve, or None.

    Only used when a fallback client runs: with TMDB alone the planner never
    writes these columns, and selecting on them would re-scan the same rows on
    every run for no write."""
    parts = []
    if "genres" in columns:
        parts.append("(p.genres IS NULL OR p.genres = '' OR p.genres = '[]')")
    if "synopsis" in columns:
        parts.append("(p.synopsis IS NULL OR p.synopsis = '')")
    if "year" in columns:
        parts.append("p.year IS NULL")
    if "imdb_rating" in columns:
        # CAST turns a junk label like "." or "N/A" into 0.0, so a stored
        # placeholder is treated as missing rather than as a real score.
        parts.append("(p.imdb_rating IS NULL OR p.imdb_rating = ''"
                     " OR CAST(p.imdb_rating AS REAL) <= 0"
                     " OR CAST(p.imdb_rating AS REAL) > 10)")
    return " OR ".join(parts) or None


def candidate_sql(columns: set[str], *, art_table: bool, force: bool,
                  fallback: bool = False) -> str:
    adult = "p.is_18_plus = 0" if "is_18_plus" in columns else "1 = 1"
    if force:
        where = adult
    else:
        missing_root = (
            "(p.poster_url IS NULL OR p.poster_url = '' "
            "OR p.backdrop_urls IS NULL OR p.backdrop_urls = '' "
            "OR p.backdrop_urls = '[]')"
        )
        series = "p.content_type IN ('series','ongoing_season','complete_season')"
        missing_seasons = (
            f"({series} AND NOT EXISTS (SELECT 1 FROM post_artwork a "
            "WHERE a.post_id = p.id AND a.kind = 'season_poster'))"
            if art_table else series
        )
        missing_meta = _missing_metadata_sql(columns) if fallback else None
        if missing_meta:
            where = f"{adult} AND ({missing_root} OR {missing_seasons} OR {missing_meta})"
        else:
            where = f"{adult} AND ({missing_root} OR {missing_seasons})"
    return f"SELECT {select_columns(columns)} FROM posts p WHERE {where} AND p.id > ? " \
           f"ORDER BY p.id LIMIT ?"


def apply_plan(conn: sqlite3.Connection, plan: PostPlan, *, force: bool,
               columns: set[str]) -> int:
    """Write one plan. Returns how many artwork rows were written."""
    updates = {key: value for key, value in plan.updates.items()
               if key in columns and value not in (None, "")}
    if updates:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE posts SET {assignments} WHERE id = ?",
                     (*updates.values(), plan.post_id))
    if not plan.artwork:
        return 0
    if force:
        conn.execute("DELETE FROM post_artwork WHERE post_id = ? AND source = 'tmdb'",
                     (plan.post_id,))
    conn.executemany(_UPSERT_ART, [
        (row.post_id, row.kind, row.season_number, row.episode_number, row.url,
         row.width, row.height, row.language)
        for row in plan.artwork
    ])
    return len(plan.artwork)


def run(conn: sqlite3.Connection, client: TmdbClient | None, *, limit: int = 0,
        after_id: int = 0, workers: int = DEFAULT_WORKERS, force: bool = False,
        dry_run: bool = False, include_specials: bool = False,
        want_stills: bool = True, batch: int = BATCH,
        fallback: CinemetaClient | None = None) -> dict:
    columns = post_columns(conn)
    required = {"id", "title", "clean_title", "year", "content_type", "seasons",
                "poster_url", "backdrop_urls"}
    missing = required - columns
    if missing:
        raise ValueError(f"posts is missing column(s): {', '.join(sorted(missing))}")
    art_table = table_exists(conn, "post_artwork")
    sql = candidate_sql(columns, art_table=art_table, force=force,
                        fallback=fallback is not None)

    counters = {"processed": 0, "matched": 0, "no_match": 0, "failed": 0,
                "artwork_rows": 0, "last_id": after_id}
    started = time.time()
    remaining = limit if limit > 0 else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while True:
            take = batch if remaining is None else min(batch, remaining)
            if take <= 0:
                break
            rows = conn.execute(sql, (counters["last_id"], take)).fetchall()
            if not rows:
                break
            counters["last_id"] = int(rows[-1]["id"])
            futures = {
                pool.submit(plan_post, row, client, force=force,
                            include_specials=include_specials,
                            want_stills=want_stills,
                            fallback=fallback): row
                for row in rows
            }
            plans: list[PostPlan] = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    plans.append(future.result())
                except TmdbError as error:
                    if "credentials" in str(error):
                        raise
                    counters["failed"] += 1
                except Exception:
                    counters["failed"] += 1
            plans.sort(key=lambda item: item.post_id)
            if dry_run:
                written = sum(len(plan.artwork) for plan in plans)
            else:
                written = 0
                with conn:
                    for plan in plans:
                        written += apply_plan(conn, plan, force=force,
                                              columns=columns)
            for plan in plans:
                counters["processed"] += 1
                counters["artwork_rows"] += len(plan.artwork) if dry_run else 0
                if plan.outcome.startswith("matched"):
                    counters["matched"] += 1
                else:
                    counters["no_match"] += 1
            if not dry_run:
                counters["artwork_rows"] += written
            if remaining is not None:
                remaining -= len(rows)
            elapsed = max(0.001, time.time() - started)
            print(f"[.] {counters['processed']} processed · {counters['matched']} matched · "
                  f"{counters['artwork_rows']} art rows · {counters['failed']} failed · "
                  f"{counters['processed'] / elapsed:.1f}/s · last id {counters['last_id']}",
                  flush=True)
    counters["elapsed"] = time.time() - started
    return counters


# ── CLI ──────────────────────────────────────────────────────────────────────

def _credentials() -> tuple[str, str] | None:
    """TMDB credentials from the environment, or None when the run should use
    the keyless Cinemeta addon instead."""
    bearer = os.environ.get("TMDB_BEARER_TOKEN", "").strip()
    api_key = os.environ.get("TMDB_API_KEY", "").strip()
    if bearer or api_key:
        return api_key, bearer
    return None


def _target_path(args) -> Path:
    if args.db:
        return Path(args.db).expanduser()
    if args.site:
        return config.staging_db_path(args.site)
    return Path(config.DB_PATH)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--db", type=Path, help="SQLite database (default: config.DB_PATH)")
    target.add_argument("--site", help="Use that site's staging database")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most this many candidates (0 = all)")
    parser.add_argument("--after-id", type=int, default=0,
                        help="Resume after this posts.id (exclusive)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Network workers (default {DEFAULT_WORKERS})")
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL,
                        help="Seconds between request starts, shared by all workers "
                             f"(default {DEFAULT_MIN_INTERVAL})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"Per-request timeout in seconds (default {DEFAULT_TIMEOUT:g})")
    parser.add_argument("--no-stills", action="store_true",
                        help="Fetch season posters but skip episode stills")
    parser.add_argument("--include-specials", action="store_true",
                        help="Include TMDB season 0 (specials)")
    parser.add_argument("--force", action="store_true",
                        help="Re-read every non-adult row and replace existing art/metadata")
    parser.add_argument("--no-cinemeta", action="store_true",
                        help="Never consult the keyless Cinemeta fallback")
    parser.add_argument("--dry-run", action="store_true",
                        help="Query upstreams and report, but write nothing")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit < 0 or args.after_id < 0 or args.workers < 1 or args.min_interval < 0:
        parser.error("--limit/--after-id must be >= 0, --workers >= 1, "
                     "--min-interval >= 0")
    db_path = _target_path(args)
    if not db_path.exists():
        print(f"[!] no database at {db_path}", file=sys.stderr)
        return 2
    credentials = _credentials()
    fallback = None if args.no_cinemeta else CinemetaClient(
        min_interval=max(args.min_interval, DEFAULT_CINEMETA_INTERVAL),
        timeout=args.timeout)
    if credentials is None and fallback is None:
        print("[!] No TMDB credentials and Cinemeta disabled: nothing to do. "
              "Set TMDB_BEARER_TOKEN or TMDB_API_KEY, or drop --no-cinemeta.",
              file=sys.stderr)
        return 2
    api_key, bearer = credentials or ("", "")

    conn = connect(db_path)
    try:
        if not table_exists(conn, "posts"):
            print(f"[!] {db_path} has no posts table", file=sys.stderr)
            return 2
        if not args.dry_run:
            conn.executescript(fast_fetch.POST_ARTWORK_DDL)
        total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        print(f"[·] {db_path.name}: {total} posts"
              + (" (dry run — nothing will be written)" if args.dry_run else ""),
              flush=True)
        if credentials:
            print("[·] TMDB credentials found"
                  + ("; Cinemeta fallback on" if fallback else "; Cinemeta fallback off"),
                  flush=True)
        else:
            print("[·] No TMDB credentials — keyless Cinemeta metadata only",
                  flush=True)
        client = (TmdbClient(api_key=api_key, bearer_token=bearer,
                             min_interval=args.min_interval, timeout=args.timeout)
                  if credentials else None)
        counters = run(
            conn, client,
            limit=args.limit,
            after_id=args.after_id,
            workers=args.workers,
            force=args.force,
            dry_run=args.dry_run,
            include_specials=args.include_specials,
            want_stills=not args.no_stills,
            fallback=fallback,
        )
    except ValueError as error:
        print(f"[!] {error}", file=sys.stderr)
        return 2
    except TmdbError as error:
        print(f"[!] {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[!] interrupted; every completed batch is already committed. "
              "Resume with --after-id.", file=sys.stderr)
        return 130
    finally:
        conn.close()

    print(f"[{'·' if args.dry_run else '✓'}] {counters['processed']} posts processed · "
          f"{counters['matched']} matched · {counters['no_match']} no match · "
          f"{counters['artwork_rows']} season/episode rows · "
          f"{counters['failed']} failed · {counters['elapsed']:.0f}s")
    print(f"    resume after id {counters['last_id']} with --after-id "
          f"{counters['last_id']}" if counters["processed"] else "    nothing to do")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
