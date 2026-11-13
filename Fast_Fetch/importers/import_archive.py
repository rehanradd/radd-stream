#!/usr/bin/env python3
"""
import_archive.py — Internet Archive Feature Films staging importer.

Archive-only legal catalog: no TMDb key, no OMDb key, no key of any kind.
The metadata spine is Archive.org itself (title / year / poster from the
item), and ``tmdb_id`` stays NULL until a commercial TMDb agreement exists —
never invented.

APIs (free, no key, stdlib only):
* List: ``advancedsearch.php?q=collection:feature_films AND NOT
  title:(Jesus)`` — NEVER default order: the default sort concentrates the
  Jesus Film translations at the top (59% of the first 150 rows, measured
  2026-11-09). Sorted by downloads desc, pages of 100.
* Item: ``https://archive.org/metadata/<identifier>`` — metadata + ``files``.
* File: ``https://archive.org/download/<identifier>/<filename>`` — answers
  **302 to a storage node** (``ia*.us.archive.org``); the 302 itself already
  carries ``Content-Type: video/mp4``. Any probe MUST follow redirects;
  a no-follow press is not a play verdict here (ExoPlayer follows them).

HARD GATES — skip the item if ANY fails (measured 2026-11-09, proof run
10/10 direct .mp4 play, pool ~8,900 PD films from 28,589 raw):
1. ``is_dark`` true -> skip (file list withheld; do not retry around it).
2. No ``licenseurl`` -> skip (unlicensed is not public domain until proven).
3. ``licenseurl`` not in the allowlist -> skip. ALLOW: Public Domain Mark
   1.0, the old public-domain dedication, CC0 1.0, CC BY (any version),
   CC BY-SA (the share-alike obligation is recorded). DENY: CC BY-NC,
   BY-NC-SA, BY-ND, sampling, unknown. **"Plays" != "importable"** — CC
   BY-NC plays fine but is NOT usable in a monetized app (measured:
   Karate Warriors 1976 is CC BY-NC 4.0 and is skipped).
4. No ``.mp4`` in ``files`` -> skip.
5. Range probe (follow redirects, expect 206 + video/*) AND ffprobe (video
   stream + audio stream + duration > 0) — BOTH must pass. A row without
   probe evidence must never be marked playable, so a missing ffprobe
   binary fails closed: the item is skipped, not imported unproven.
6. Content screen: titles matching a suggestive/18+ wordlist are stored
   flagged ``is_18_plus=1`` for manual review, never auto-published
   (same shape as xprimehub: scrape, tag, do not publish). The wordlist
   names acts/studios only — ``naked`` is deliberately NOT in it: The
   Naked City (1948), The Naked Gun and Naked Lunch are mainstream films,
   and a review flag that fires on them is noise, not signal. Titles are
   word-boundary matched (the repo's adult law: the anchors stay);
   identifiers are glued slugs, so they are substring matched only on
   the long act-naming tokens — "sex" never fires inside "sussex",
   "adult" never inside "adultery".

Mapping onto the staging shape (``merge_catalogs.py`` reads it):
* One post per Archive identifier; site ``archive.org``; ``source_url`` =
  the item page ``https://archive.org/details/<identifier>`` (NOT the file).
* ``canonical_key`` is ``archive_org:<identifier>`` — unique per item, so
  no false corroboration with another site's title+year key. One work per
  normalized title+year is the v2 projection's job, not the staging key's.
* Translation dedupe: within one harvest, a second item with the same
  normalized title AND a known year is skipped (the feed is downloads
  sorted, so the most-downloaded — usually the English original — wins).
  Yearless items dedupe by identifier only: two yearless films sharing a
  title are kept apart rather than collapsed on a guess.
* One release per probed .mp4 variant (cap 3); quality band from **ffprobe
  height** (>=1080 -> 1080p, 720-1079 -> 720p, <720 -> 480p), NOT the
  filename — the build note's width rule mislabels a 1280x720 file as
  1080p, and 1080p is a VIP-gated band, so the width rule would 402 a free
  720p file (measured on Sita Sings the Blues, 2026-11-09; see the
  checkpoint). Largest .mp4 first; ``_512kb`` is the low-band release. Cap:
  a ``.ia.mp4`` over 1 GB is dropped when a plain .mp4 of the same item
  already probes >=720p (Bowery at Midnight: both files are the same
  1.27 GB encode — storing the derivative twice buys nothing).
* One ``download_sources`` row per release: ``service = "archive_org"``,
  ``final_url`` = the direct download URL (stable, no expiry), ``resumable
  = 1`` (Range 206 proven), ``size`` from ``files``, ``licenseurl`` stored
  in ``raw_meta`` for audit.

Data-quality rules, measured live 2026-11-09:
* Year missing in metadata is common (3/10 proof items) — fall back to a
  4-digit year in the identifier, then in the title, else NULL. Never
  invent a year.
* ``files[].format`` is NOT a reliable mp4 detector (values seen: MPEG4,
  h.264, 512Kb MPEG4, h.264 IA) — match the filename suffix ``.mp4``.
* ``licenseurl`` forms seen live: ``http(s)://creativecommons.org/
  publicdomain/mark/1.0/`` (PD Mark), ``http://creativecommons.org/
  licenses/publicdomain/`` (old public-domain dedication),
  ``https://creativecommons.org/licenses/by-nc/4.0/`` (DENY).
* Titles carry cast in trailing parens (``The Golfers (Andy Clyde Thelma
  Hill)``) — ``clean_title`` strips a trailing ``(YYYY)`` or a trailing
  digit-free paren group; ``(Part 2)`` keeps its digits and is kept.
"""
from __future__ import annotations

import argparse
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

SITE = "archive.org"
SERVICE = "archive_org"
SERVICE_TIER = 1
PLAYBACK_DIRECT = "direct"
DEFAULT_SOURCE_STATUS = "active"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/archive_org.db")

SEARCH_BASE = "https://archive.org/advancedsearch.php"
SEARCH_QUERY = "collection:feature_films AND NOT title:(Jesus)"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DETAILS_URL = "https://archive.org/details/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"
THUMB_NAME = "__ia_thumb.jpg"

USER_AGENT = "RaddStream/1.0 (archive.org importer; +https://raddstream.duckdns.org/)"
JSON_TIMEOUT = 30
RANGE_TIMEOUT = 30
FFPROBE_TIMEOUT = 60
HTTP_RETRIES = 2
TRANSPORT_RETRIES = 2
PER_PAGE = 100
MAX_MP4_VARIANTS = 3
IA_MP4_SIZE_CAP = 1_000_000_000  # 1 GB: drop a huge .ia.mp4 when plain >=720p exists

# ---------------------------------------------------------------------------
# License gate
# ---------------------------------------------------------------------------

#: Substrings that deny a license outright, checked FIRST: a BY-NC-SA URL
#: contains both "by-nc" and "by-sa", and the NC half is what decides it.
_DENY_LICENSE_MARKERS = (
    "by-nc", "by-nd", "nc-sa", "nc-nd", "sampling",
    "noncommercial", "non-commercial",
)

#: (marker, kind, share_alike) — checked after the deny list, in order.
_ALLOW_LICENSE_MARKERS = (
    ("publicdomain/mark", "pd_mark", False),
    ("publicdomain/zero", "cc0", False),
    ("licenses/publicdomain", "publicdomain", False),
    ("licenses/by-sa", "cc_by_sa", True),
    ("licenses/by/", "cc_by", False),
    ("cc0", "cc0", False),
    ("public domain", "pd_mark", False),
)


def classify_license(licenseurl) -> tuple[str, str | None, bool]:
    """Classify an Archive ``licenseurl`` value.

    Returns ``(verdict, kind, share_alike)`` where verdict is ``"allow"``
    or ``"deny"``. Accepts a string or a one-element list (Archive metadata
    sometimes returns multi-valued fields as lists). A missing, empty or
    unrecognised value denies: unlicensed is not public domain until proven.
    """
    if isinstance(licenseurl, (list, tuple)):
        licenseurl = licenseurl[0] if licenseurl else None
    if not isinstance(licenseurl, str) or not licenseurl.strip():
        return "deny", None, False
    value = licenseurl.strip().lower()
    for marker in _DENY_LICENSE_MARKERS:
        if marker in value:
            return "deny", None, False
    for marker, kind, share_alike in _ALLOW_LICENSE_MARKERS:
        if marker in value:
            return "allow", kind, share_alike
    return "deny", None, False


# ---------------------------------------------------------------------------
# Content screen (manual-review flag, not a public hide rule by itself)
# ---------------------------------------------------------------------------

#: Tokens that name an act or a studio. Titles are word-boundary matched,
#: exactly like the repo's adult law (the anchors stay: "sex" never fires
#: inside "Sussex", "adult" never fires inside "Adulterated").
_REVIEW_TOKENS = (
    "bondage", "burlesque", "erotic", "porn", "nsfw", "xxx", "nudity",
    "nudist", "striptease", "sex", "adult", "blue movie", "stag film",
)
_REVIEW_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _REVIEW_TOKENS) + r")\b",
    re.IGNORECASE,
)

#: Identifiers are glued slugs ("blondeinbondage" has no word boundary
#: inside it), so they are substring matched — but only on the long,
#: act-naming tokens. The short tokens stay out: "sex" would fire inside
#: "sussex", "adult" inside "adultery", "xxx" inside "foxxx".
_IDENTIFIER_TOKENS = (
    "bondage", "burlesque", "erotic", "porn", "striptease", "nudity", "nudist",
    "nsfw",
)


def needs_review(title: str | None, identifier: str | None) -> str | None:
    """Return the matched review token, or None when the item is clean."""
    match = _REVIEW_RE.search(title or "")
    if match:
        return match.group(0).lower()
    lowered = (identifier or "").lower()
    for token in _IDENTIFIER_TOKENS:
        if token in lowered:
            return token
    return None


# ---------------------------------------------------------------------------
# Title / year / identity helpers
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _clean_title(title: str | None) -> str:
    """Normalise a metadata title for display and dedupe.

    Strips one trailing ``(YYYY)`` group, or a trailing digit-free paren
    group (the cast list Archive appends: ``The Golfers (Andy Clyde Thelma
    Hill)``). A paren group carrying a digit (``(Part 2)``) is part of the
    title and is kept.
    """
    if not title:
        return ""
    text = " ".join(str(title).split())
    match = _TRAILING_PAREN_RE.search(text)
    if match:
        inner = match.group(0).strip().strip("()").strip()
        if _YEAR_RE.fullmatch(inner) or not any(ch.isdigit() for ch in inner):
            text = text[:match.start()].strip()
    return text


def _year_of(metadata: dict, identifier: str, title: str | None) -> int | None:
    """Year from metadata, else a 4-digit year in the identifier, then the title.

    Never invents: returns None when nothing carries a year.
    """
    raw = metadata.get("year")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is not None:
        match = _YEAR_RE.search(str(raw))
        if match:
            return int(match.group(1))
    for text in (identifier or "", title or ""):
        match = _YEAR_RE.search(text)
        if match:
            return int(match.group(1))
    return None


def _norm_key(clean_title: str, year: int | None) -> str:
    """Translation-dedupe key: normalised title, plus the year when known."""
    norm = re.sub(r"[^a-z0-9]+", " ", clean_title.lower()).strip()
    return f"{norm}|{year}" if year is not None else norm


def _canonical_key(identifier: str) -> str:
    return f"archive_org:{identifier}"


# ---------------------------------------------------------------------------
# .mp4 candidates
# ---------------------------------------------------------------------------

_SKIP_FILE_MARKERS = ("preview", "trailer", "sample")


def _mp4_files(files: list) -> list[dict]:
    """The playable .mp4 candidates of one item, best first.

    Matches the filename suffix (``files[].format`` is unreliable: MPEG4,
    h.264, 512Kb MPEG4, h.264 IA). Skips preview/trailer/sample files.
    Order: plain .mp4 before ``.ia.mp4`` before ``_512kb.mp4``, larger
    first inside each class — the largest plain file is the default release.
    """
    candidates = []
    for entry in files or []:
        name = (entry or {}).get("name") or ""
        if not name.lower().endswith(".mp4"):
            continue
        lowered = name.lower()
        if any(marker in lowered for marker in _SKIP_FILE_MARKERS):
            continue
        size = entry.get("size")
        try:
            size = int(size) if size is not None else 0
        except (TypeError, ValueError):
            size = 0
        candidates.append({
            "name": name,
            "size": size,
            "is_512kb": "_512kb" in lowered,
            "is_ia": name.lower().endswith(".ia.mp4"),
        })
    candidates.sort(key=lambda c: (c["is_512kb"], c["is_ia"], -c["size"]))
    return candidates[:MAX_MP4_VARIANTS]


def quality_band(width: int | None, height: int | None = None) -> str:
    """Quality band from ffprobe resolution — never from the filename.

    The band names the VERTICAL resolution ("1080p" = 1080 lines), so the
    height decides. Measuring on the live batch (2026-11-09): Sita Sings
    the Blues ships a 1280x720 file, which is 720p by height but would
    read 1080p under a width rule — and 1080p is a VIP-gated band, so the
    width rule would have answered 402 to free users for a free 720p
    file. Height falls back to width only when no height was recorded.
    """
    if height:
        if height >= 1080:
            return "1080p"
        if height >= 720:
            return "720p"
        return "480p"
    if width is None:
        return "480p"
    if width >= 1280:
        return "1080p"
    if width >= 720:
        return "720p"
    return "480p"


# ---------------------------------------------------------------------------
# Probes (injectable: tests pass fakes, the CLI uses the real ones)
# ---------------------------------------------------------------------------

def http_get_json(url: str, timeout: int = JSON_TIMEOUT,
                  retries: int = HTTP_RETRIES) -> dict:
    """GET a JSON document with transport retries; HTTP answers are not retried."""
    last_exc: Exception | None = None
    for attempt in range(max(1, TRANSPORT_RETRIES + 1)):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                wait = exc.headers.get("Retry-After")
                time.sleep(min(60.0, float(wait or 5)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def probe_range(url: str, opener=None) -> dict:
    """Range-probe one download URL: follow redirects, expect 206 + video/*.

    ``opener`` defaults to ``urllib.request.urlopen``; tests pass a fake.
    """
    if opener is None:
        opener = urllib.request.urlopen
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-4095"})
    try:
        with opener(req, timeout=RANGE_TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
            content_type = ""
            headers = getattr(resp, "headers", None)
            if headers is not None:
                content_type = headers.get("Content-Type", "") or ""
            ok = status == 206 and content_type.lower().startswith("video/")
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

    ``runner`` defaults to the real ffprobe call; tests pass a fake.
    A missing ffprobe binary fails closed (None) — the item is skipped,
    never imported unproven.
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


# ---------------------------------------------------------------------------
# Record building (pure gates + probes; no I/O except the probes)
# ---------------------------------------------------------------------------

def build_record(identifier: str, metadata: dict, files: list,
                 range_probe=probe_range,
                 ffprobe_probe=probe_ffprobe) -> tuple[dict | None, str]:
    """Apply the HARD GATES to one Archive item.

    Returns ``(record, "")`` on success, ``(None, reason)`` on skip.
    The record is shaped for ``export_staging`` (posts/releases/sources).
    """
    if (metadata or {}).get("is_dark"):
        return None, "dark"
    verdict, kind, share_alike = classify_license((metadata or {}).get("licenseurl"))
    if verdict != "allow":
        return None, "license_not_allowed"
    candidates = _mp4_files(files)
    if not candidates:
        return None, "no_mp4"

    raw_title = (metadata or {}).get("title") or identifier
    if isinstance(raw_title, (list, tuple)):
        raw_title = raw_title[0] if raw_title else identifier
    title = _clean_title(raw_title)
    if not title:
        return None, "no_title"
    year = _year_of(metadata or {}, identifier, (metadata or {}).get("title"))
    detail_url = DETAILS_URL.format(identifier=identifier)

    probed = []
    for cand in candidates:
        url = DOWNLOAD_URL.format(identifier=identifier,
                                  filename=urllib.parse.quote(cand["name"]))
        ranged = range_probe(url)
        if not ranged.get("ok"):
            continue
        ff = ffprobe_probe(url)
        if ff is None:
            continue
        probed.append({**cand, "url": url, "ffprobe": ff,
                       "range_status": ranged.get("status"),
                       "content_type": ranged.get("content_type")})
    if not probed:
        return None, "probe_failed"

    # Cap: drop a >1 GB .ia.mp4 when a plain .mp4 already probes >=720p.
    plain_hd = any(not p["is_ia"] and p["ffprobe"]["width"] >= 720 for p in probed)
    if plain_hd:
        probed = [p for p in probed
                  if not (p["is_ia"] and p["size"] > IA_MP4_SIZE_CAP)]
    probed.sort(key=lambda p: (-p["ffprobe"]["width"], -p["size"]))

    flag_token = needs_review(title, identifier)
    licenseurl = (metadata or {}).get("licenseurl")
    if isinstance(licenseurl, (list, tuple)):
        licenseurl = licenseurl[0] if licenseurl else None

    poster_url = None
    for entry in files or []:
        if (entry or {}).get("name") == THUMB_NAME:
            poster_url = DOWNLOAD_URL.format(
                identifier=identifier, filename=THUMB_NAME)
            break

    subjects = (metadata or {}).get("subject") or []
    if isinstance(subjects, str):
        subjects = [subjects]
    generic = {"feature films", "movies", "movie", "films", "film"}
    genres = ", ".join(s for s in (str(s).strip() for s in subjects)
                       if s and s.lower() not in generic)[:200] or None
    language = (metadata or {}).get("language")
    if isinstance(language, (list, tuple)):
        language = language[0] if language else None
    description = (metadata or {}).get("description") or ""
    if isinstance(description, (list, tuple)):
        description = description[0] if description else ""
    synopsis = re.sub(r"<[^>]+>", " ", str(description))
    synopsis = " ".join(synopsis.split())[:500] or None

    raw_meta = {
        "identifier": identifier,
        "licenseurl": licenseurl,
        "license_kind": kind,
        "share_alike": share_alike,
        "flag_reason": flag_token,
        "probe": [
            {"file": p["name"], "range_status": p["range_status"],
             "width": p["ffprobe"]["width"], "height": p["ffprobe"]["height"],
             "codec": p["ffprobe"]["codec"],
             "duration": p["ffprobe"]["duration"]}
            for p in probed
        ],
    }
    record = {
        "canonical_key": _canonical_key(identifier),
        "title": title,
        "clean_title": title,
        "year": year,
        "media_type": "movie",
        "poster_url": poster_url,
        "backdrop_url": None,
        "backdrop_urls": None,
        "imdb_id": None,
        "tmdb_id": None,
        "imdb_rating": None,
        "synopsis": synopsis,
        "genres": genres,
        "director": None,
        "cast_names": None,
        "duration": None,
        "release_date": None,
        "languages": str(language) if language else None,
        "industry": None,
        "country": None,
        "seasons": None,
        "url": detail_url,
        "slug": identifier,
        "is_18_plus": 1 if flag_token else 0,
        "is_animated": 0,
        "source_site": SITE,
        "raw_meta": raw_meta,
        "releases": [],
    }
    for probed_file in probed:
        ff = probed_file["ffprobe"]
        band = quality_band(ff["width"], ff["height"])
        record["releases"].append({
            "label": band,
            "quality": band,
            "resolution": f"{ff['width']}x{ff['height']}" if ff["height"] else None,
            "size_bytes": probed_file["size"],
            "codec": ff["codec"],
            "season": None,
            "episode": None,
            "audio": None,
            "bridge_url": None,
            "raw_meta": {
                "file": probed_file["name"],
                "duration": ff["duration"],
                "licenseurl": licenseurl,
            },
            "sources": [{
                "source_name": SERVICE,
                "service": SERVICE,
                "service_tier": SERVICE_TIER,
                "resource_id": identifier,
                "source_url": detail_url,
                "final_url": probed_file["url"],
                "playback_type": PLAYBACK_DIRECT,
                "status": DEFAULT_SOURCE_STATUS,
                "is_temporary": 0,
                "quality": band,
                "mime_type": "video/mp4",
                "last_checked": int(time.time()),
                "raw_meta": {
                    "licenseurl": licenseurl,
                    "license_kind": kind,
                    "size": probed_file["size"],
                    "duration": ff["duration"],
                },
            }],
        })
    return record, ""


# ---------------------------------------------------------------------------
# Feed walk + harvest
# ---------------------------------------------------------------------------

def search_url(page: int, per_page: int = PER_PAGE) -> str:
    params = {
        "q": SEARCH_QUERY,
        "fl[]": ["identifier", "title", "creator", "year", "licenseurl",
                 "downloads"],
        "sort[]": ["downloads desc"],
        "rows": per_page,
        "page": page,
        "output": "json",
    }
    return SEARCH_BASE + "?" + urllib.parse.urlencode(params, doseq=True)


def harvest(db_path: Path | str = DEFAULT_DB_PATH, limit: int | None = None,
            start_page: int = 1, per_page: int = PER_PAGE,
            fetch_json=http_get_json, range_probe=probe_range,
            ffprobe_probe=probe_ffprobe, verbose: bool = True) -> dict:
    """Walk the feed from ``start_page``; fetch, gate, probe and stage items.

    Stops at ``limit`` staged posts, at an empty/short feed page, or at a
    feed error (the error is recorded, not raised — a harvest that dies
    halfway still keeps what it staged).
    """
    totals = {"items": 0, "fetched": 0, "posts": 0, "duplicates": 0,
              "dup_title_year": 0, "skipped_dark": 0, "skipped_license": 0,
              "skipped_no_mp4": 0, "skipped_probe": 0, "flagged_review": 0,
              "errors": 0, "last_error": None}
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure_schema(conn)
        page = start_page
        batch: list[dict] = []
        while True:
            if limit is not None and totals["posts"] >= limit:
                break
            try:
                feed = fetch_json(search_url(page, per_page))
            except Exception as exc:  # noqa: BLE001 - feed failure ends the run
                totals["errors"] += 1
                totals["last_error"] = str(exc)
                break
            docs = ((feed or {}).get("response") or {}).get("docs") or []
            if not docs:
                break
            for doc in docs:
                if limit is not None and totals["posts"] >= limit:
                    break
                identifier = (doc or {}).get("identifier")
                if not identifier:
                    continue
                totals["items"] += 1
                if identifier in seen_ids:
                    totals["duplicates"] += 1
                    continue
                seen_ids.add(identifier)
                try:
                    payload = fetch_json(METADATA_URL.format(identifier=identifier))
                except Exception as exc:  # noqa: BLE001 - one bad item skips
                    totals["errors"] += 1
                    totals["last_error"] = str(exc)
                    continue
                totals["fetched"] += 1
                metadata = (payload or {}).get("metadata") or {}
                files = (payload or {}).get("files") or []
                record, reason = build_record(identifier, metadata, files,
                                              range_probe, ffprobe_probe)
                if record is None:
                    key = {"dark": "skipped_dark",
                           "license_not_allowed": "skipped_license",
                           "no_mp4": "skipped_no_mp4",
                           "probe_failed": "skipped_probe"}.get(reason)
                    if key:
                        totals[key] += 1
                    else:
                        totals["errors"] += 1
                        totals["last_error"] = f"skip:{reason}"
                    continue
                # Translation dedupe: same normalised title + known year.
                title_key = _norm_key(record["clean_title"], record["year"])
                if record["year"] is not None and title_key in seen_titles:
                    totals["dup_title_year"] += 1
                    continue
                seen_titles.add(title_key)
                if record["is_18_plus"]:
                    totals["flagged_review"] += 1
                batch.append(record)
                totals["posts"] += 1
                if len(batch) >= 10:
                    export_staging(db_path, batch, conn=conn)
                    batch = []
            conn.commit()
            if len(docs) < per_page:
                break
            page += 1
        if batch:
            export_staging(db_path, batch, conn=conn)
        conn.commit()
    finally:
        conn.close()
    if verbose:
        print(f"[✓] [{SITE}] harvest items={totals['items']} "
              f"posts={totals['posts']} duplicates={totals['duplicates']} "
              f"dup_title_year={totals['dup_title_year']} "
              f"skipped_license={totals['skipped_license']} "
              f"skipped_probe={totals['skipped_probe']} "
              f"flagged_review={totals['flagged_review']} "
              f"errors={totals['errors']}")
    return totals


# ---------------------------------------------------------------------------
# Staging database (same posts/releases/sources shape merge_catalogs reads)
# ---------------------------------------------------------------------------

_SCHEMA_TABLES = """
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
    source_site TEXT DEFAULT 'archive.org',
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
CREATE INDEX IF NOT EXISTS idx_archive_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_archive_posts_key ON posts(canonical_key);
CREATE INDEX IF NOT EXISTS idx_archive_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_archive_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_archive_releases_post ON releases(post_canonical_key);
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
    """Upsert records; a re-export of one item replaces its releases+sources.

    ``conn`` lets a caller that already holds a write transaction reuse its
    own connection — opening a second writer against the same file would
    make SQLite wait the full 60 s timeout and then raise "database is
    locked".
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
# Verify / stats (read-only)
# ---------------------------------------------------------------------------

def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    """Count staging rows; the gate audit behind ``verify``."""
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        out = {
            "posts": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "releases": conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "flagged_review": conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
            "posts_without_release": conn.execute(
                "SELECT COUNT(*) FROM posts p WHERE NOT EXISTS ("
                "SELECT 1 FROM releases r WHERE r.post_canonical_key = p.canonical_key)"
                ).fetchone()[0],
            "sources_without_final_url": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE final_url IS NULL OR final_url = ''"
                ).fetchone()[0],
            "posts_without_license": 0,
            "license_kinds": {},
        }
        for row in conn.execute("SELECT raw_meta FROM posts"):
            try:
                meta = json.loads(row["raw_meta"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            if not meta.get("licenseurl"):
                out["posts_without_license"] += 1
            kind = meta.get("license_kind") or "unknown"
            out["license_kinds"][kind] = out["license_kinds"].get(kind, 0) + 1
        return out
    finally:
        conn.close()


def verify_db(db_path: Path | str = DEFAULT_DB_PATH) -> tuple[bool, dict]:
    """Gate audit: every post has a release, a final URL and a licence.

    Returns ``(ok, stats_dict)``; ``ok`` is False when any audit count
    is non-zero, so a bad batch cannot pass silently.
    """
    result = stats(db_path)
    ok = (result["posts_without_release"] == 0
          and result["sources_without_final_url"] == 0
          and result["posts_without_license"] == 0
          and result["posts"] > 0)
    return ok, result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="archive.org staging importer")
    sub = parser.add_subparsers(dest="command", required=True)

    harvest_cmd = sub.add_parser(
        "harvest", help="walk the feature_films feed and stage gated items")
    harvest_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    harvest_cmd.add_argument("--limit", type=int, default=None,
                             help="stop after this many staged posts")
    harvest_cmd.add_argument("--start-page", type=int, default=1)
    harvest_cmd.add_argument("--per-page", type=int, default=PER_PAGE)

    verify_cmd = sub.add_parser("verify", help="gate-audit a staging database")
    verify_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))

    stats_cmd = sub.add_parser("stats", help="count staging rows")
    stats_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "harvest":
        totals = harvest(db_path=args.db, limit=args.limit,
                         start_page=args.start_page, per_page=args.per_page)
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
