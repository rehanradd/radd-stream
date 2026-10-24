#!/usr/bin/env python3
"""
catalog_api.py — Layer-2 read model over the canonical `cat_*` tables.

`catalog_v2.py` builds Layer 1 (works / seasons / episodes / prints / links /
entitlements / offsets). This module is the only thing allowed to *interpret* those
rows for a client: browse, search, detail, episode manifests, play bundles,
entitlement decisions, and cache state.

Design rules (enforced by `test_catalog_api.py`):

* **Pure functions.** Every entry point takes an already-open
  ``sqlite3.Connection`` (``row_factory = sqlite3.Row``) plus keyword params and
  returns a plain ``dict``. No HTTP, no argv, no printing, no global state, so
  `viewer.py` can call them from any handler and tests can call them directly.
* **Adult content is stored but never displayed.** `cat_works.is_18_plus = 1` is
  filtered at the SQL level in every listing, and asking for a flagged work by
  numeric id, work key or slug returns the *same* not-found result as a work that
  does not exist (no 403-shaped leak, no count skew). `include_adult=True` exists
  for admin surfaces only — the caller (viewer.py) is responsible for having
  checked admin credentials before passing it.
* **Zero data loss.** A dead link is returned with ``state="dead"`` and ranked
  last; a print whose scope could not be resolved is returned in
  ``scope_unresolved_prints`` instead of being silently dropped.
* **Never invent data.** Unknown column -> ``None``/``"unknown"``. Anything the
  projector does not write (tvdb_id, runtime, poster width, measured link speed)
  is reported as null and flagged, never guessed.

Return envelope: every function returns ``{"ok": True, ...payload}`` or
``{"ok": False, "error": {"code": ..., "message": ...}}`` with a stable machine
code from ``ERROR_CODES`` (`API_V2.md` §10.4). Listing endpoints treat "nothing
matched" as a successful empty result, not an error.

Search note / documented limit: the projector provides **no FTS index**, so
`search()` normalises (casefold + diacritic folding + punctuation → spaces) the
query and every candidate haystack (title, original page title, all aliases) and
ANDs a substring test per query token. That is a full scan of `cat_works` —
correct and punctuation-proof, but O(rows); fine for the current ~20k-row catalog,
and it degrades linearly. If a `cat_works_fts` FTS5 table is ever added by the
projector, `search()` automatically narrows candidates with `MATCH` first and
keeps the same ranking.

Standard Library only. Zero external pip packages.
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import json
import re
import sqlite3
import time
import unicodedata

import catalog_v2
import redact
import tiers

DEFAULT_LIMIT = 24
MAX_LIMIT = 100
MAX_SEARCH_LIMIT = 100
SORT_KEYS = ("trending", "newest", "quality", "rating", "title", "updated")
COVERAGE_TYPES = ("whole_work", "season_pack", "episode_range", "single_episode", "parts")
ERROR_CODES = (
    "not_found",
    "invalid_input",
    "cursor_invalid",
    "bad_connection",
)

# Link candidate groups — lower group ranks earlier. Playability decides the group.
# `cat_links.rank_score` already encodes playability, tier, freshness, range support
# and a -450 penalty for non-active state, so it is the within-group tiebreaker.
_GROUP_STREAMABLE = 0
_GROUP_RESOLVE = 1
_GROUP_WEBVIEW = 2
_GROUP_DOWNLOAD = 3
_GROUP_NONE = 4

_PLAYABILITY_GROUP = {
    "stream": _GROUP_STREAMABLE,
    "both": _GROUP_STREAMABLE,
    "resolve_required": _GROUP_RESOLVE,
    "webview": _GROUP_WEBVIEW,
    "download": _GROUP_DOWNLOAD,
    "none": _GROUP_NONE,
}

_CAM_TAGS = {"cam", "telesync", "telecine", "workprint", "hdcam", "mdcam", "rscam"}
_RES_LABEL = {
    "2160p": "4K", "4k": "4K", "uhd": "4K", "1080p": "1080p", "720p": "720p",
    "480p": "480p", "360p": "360p", "unknown": "",
}
_HDR_LABEL = {
    "dolby_vision": "Dolby Vision", "hdr10_plus": "HDR10+", "hdr10plus": "HDR10+",
    "hdr10": "HDR10", "hlg": "HLG",
}
_SOURCE_LABEL = {
    "bluray": "BluRay", "uhd_bluray": "BluRay", "blu_ray": "BluRay", "web_dl": "WEB-DL",
    "webdl": "WEB-DL", "webrip": "WEBRip", "web_rip": "WEBRip", "hdtv": "HDTV",
    "dvdrip": "DVDRip", "telesync": "TS", "telecine": "Telecine", "cam": "CAM",
    "workprint": "WORKPRINT", "unknown": "",
}
_EDITION_LABEL = {
    "director_cut": "Director's Cut", "extended": "Extended", "unrated": "Unrated",
    "uncut": "Uncut", "remastered": "Remastered", "restored": "Restored",
    "imax": "IMAX", "theatrical": "", "unknown": "",
}

def public_edge(func):
    """Every v2 response leaves this module through here, stripped.

    The builders already refuse to emit provenance; this is the net underneath
    them, so a field added to a view later is denied rather than published, and
    so one decorator covers all twelve entry points instead of twelve reviews.
    The only way to get provenance back is `include_provenance=True`, which an
    operator port sets in code and a request can never ask for.
    """
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        payload = func(*args, **kwargs)
        if kwargs.get("include_provenance"):
            return payload
        return redact.scrub(payload)
    return wrapped


# `content_type` accepts the v2 `work_type` values and, for compatibility with the
# v1 app, the four legacy v1 `posts.content_type` strings.
_CONTENT_TYPE_ALIASES = {
    "movie": ("movie",),
    "series": ("series",),
    "anime": ("anime",),
    "documentary": ("documentary",),
    "sport": ("sport_event",),
    "sport_event": ("sport_event",),
    "music_video": ("music_video",),
    "miniseries": ("miniseries", "series"),
    "tv_special": ("tv_special", "series"),
    "complete_season": ("series",),
    "ongoing_season": ("series",),
    "unknown": ("unknown",),
}

_QUALITY_ALIASES = {
    "4k": ("2160p",), "2160p": ("2160p",), "uhd": ("2160p",),
    "1080p": ("1080p",), "fullhd": ("1080p",), "fhd": ("1080p",),
    "720p": ("720p",), "hd": ("720p", "1080p"),
    "480p": ("480p",), "sd": ("480p",),
}

_OFFSET_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_PART_RE = re.compile(r"\b(?:part|disc|chapter)\s*(?:no\.?\s*)?(\d{1,2})\b", re.IGNORECASE)
_RANGE_RE = re.compile(r"(\d+)\s*(?:-|–|to)\s*(\d+)")
_NON_WORD_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")

# Search noise that is *not* removed: tokens are matched as substrings of a
# normalised haystack, so a dirty page title such as "Dune (2024) Hindi Dubbed 720p"
# already satisfies the query "dune" without any stop-word stripping. Stripping
# words would silently break searches for "Hindi" or "Dubbed", so we never drop one.


# ── small helpers ────────────────────────────────────────────────────────────

def _bad_input(message: str) -> dict:
    return {"ok": False, "error": {"code": "invalid_input", "message": message}}


def _not_found(message: str = "Not found") -> dict:
    """The single not-found shape. Adult rows and missing rows share it exactly."""
    return {"ok": False, "error": {"code": "not_found", "message": message}}


_NOT_FOUND_WORK = "Work not found"
_NOT_FOUND_RELEASE = "Release not found"


def _require_row_factory(conn) -> None:
    """Every reader below indexes rows by name; enforce it once, loudly."""
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("catalog_api needs an open sqlite3.Connection")
    if conn.row_factory is not sqlite3.Row:
        raise ValueError("catalog_api requires conn.row_factory = sqlite3.Row")


def _as_dict(row) -> dict:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def _json_list(value) -> list:
    """Layer 0 writes either a JSON array or a comma list into the same columns."""
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
        if isinstance(parsed, str):
            return [parsed.strip()] if parsed.strip() else []
    parts = re.split(r"[,;|/]", text)
    return [p.strip().strip('"').strip() for p in parts if p and p.strip()]


def normalize_text(text) -> str:
    """casefold + diacritic folding + punctuation → space, for matching only.

    Parentheses/brackets keep their content so a year inside them stays searchable
    ("Dune (2024)" -> "dune 2024").
    """
    if text in (None, ""):
        return ""
    folded = unicodedata.normalize("NFKD", str(text))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    folded = folded.replace("&", " and ")
    folded = _NON_WORD_RE.sub(" ", folded)
    return " ".join(_MULTI_SPACE_RE.split(folded.strip()))


def _register_udfs(conn) -> None:
    """Deterministic helpers usable inside SQL. Re-registering is cheap and safe."""
    conn.create_function("radd_norm", 1, lambda v: normalize_text(v), deterministic=True)
    conn.create_function(
        "radd_hay", 4,
        lambda title, original, genres, aliases: " | ".join(
            part for part in (
                normalize_text(title), normalize_text(original),
                normalize_text(genres), normalize_text(aliases)) if part),
        deterministic=True,
    )
    conn.create_function(
        "radd_list_has", 2,
        lambda blob, needle: 1 if _list_has(blob, needle) else 0,
        deterministic=True,
    )


def _list_has(blob, needle) -> bool:
    """Case/diacritic-insensitive membership in a JSON-or-comma list column."""
    wanted = normalize_text(needle)
    if not wanted:
        return False
    for item in _json_list(blob):
        norm = normalize_text(item)
        if norm == wanted or wanted in norm.split():
            return True
    return False


def _clamp_limit(limit, default=DEFAULT_LIMIT, ceiling=MAX_LIMIT) -> int:
    try:
        value = int(limit if limit not in (None, "") else default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(ceiling, value))


def _episode_range_bounds(text) -> tuple[int, int]:
    """(lo, hi) from '1-6', 'EP(01-06)', 'E1-E4000', '' — (0, 0) when unparseable."""
    if text in (None, ""):
        return 0, 0
    numbers = re.findall(r"\d+", str(text))
    if not numbers:
        return 0, 0
    lo = int(numbers[0])
    hi = int(numbers[1]) if len(numbers) > 1 else lo
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo > 2000:
        return lo, lo
    return lo, hi


def _adult_clause(alias: str) -> str:
    return f"({alias}.is_18_plus IS NULL OR {alias}.is_18_plus = 0)"


def _has_table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,)).fetchone() is not None


def _meta_value(conn, key: str):
    row = conn.execute(
        "SELECT value FROM cat_projection_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


# ── cursors ──────────────────────────────────────────────────────────────────

def _fingerprint(where_sql: str, params: dict) -> str:
    payload = where_sql + "|" + json.dumps(
        {k: params[k] for k in sorted(params)}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def encode_cursor(*, sort_value, work_id: int, sort: str, order: str, fingerprint: str) -> str:
    raw = json.dumps({"v": sort_value, "i": int(work_id), "s": sort, "o": order,
                      "f": fingerprint}, sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict | None:
    """Opaque cursor -> dict, or None when the caller handed us garbage."""
    if not cursor:
        return None
    text = str(cursor).strip()
    padded = text + "=" * (-len(text) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or "v" not in data or "i" not in data:
        return None
    if not isinstance(data["v"], (int, float, str)) or isinstance(data["v"], bool):
        return None
    return data


# ── sort keys ────────────────────────────────────────────────────────────────

def _sort_expr(sort: str) -> str:
    """One SQL expression per sort key. Every expression is COALESCEd non-NULL so
    keyset comparison can never be defeated by a NULL, and never references a column
    the projector does not write."""
    return {
        # trending = reach (sites) + depth (prints/episodes) + what actually plays.
        "trending": ("(COALESCE(w.available_stream, 0) * 40"
                     " + COALESCE(w.available_download, 0) * 10"
                     " + COALESCE(w.site_count, 0) * 15"
                     " + MIN(COALESCE(w.release_count, 0), 40) * 2"
                     " + COALESCE(w.best_quality_score, 0) / 10"
                     " + ROUND(COALESCE(w.imdb_rating, 0) * 4, 2)"
                     " + MIN(COALESCE(w.episode_count, 0), 100))"),
        # newest = year first, then the scrape timestamp, so a 2026 title cannot be
        # beaten by a fresh scrape of a 1998 film.
        "newest": ("(CAST(COALESCE(w.year, 0) AS INTEGER) * 10000000000"
                   " + CAST(COALESCE(w.first_seen_at, 0) AS INTEGER))"),
        "quality": "COALESCE(w.best_quality_score, 0)",
        "rating": "ROUND(COALESCE(w.imdb_rating, 0), 2)",
        "title": "radd_norm(COALESCE(w.title, ''))",
        "updated": "COALESCE(w.updated_at, 0)",
    }[sort]


# ── facet filters (shared by browse + search) ────────────────────────────────

def _facet_clauses(content_type, genres, languages, qualities, available,
                   year_from, year_to, min_quality, animated=None,
                   country=(), industry=()) -> tuple[list[str], dict]:
    clauses: list[str] = []
    params: dict = {}
    types: list[str] = []
    if content_type not in (None, "", "all"):
        values = ([content_type] if isinstance(content_type, str)
                  else [str(v) for v in content_type])
        for value in values:
            key = normalize_text(value)
            types.extend(_CONTENT_TYPE_ALIASES.get(key, (key,)))
    if types:
        placeholders = []
        for index, value in enumerate(sorted(set(types))):
            name = f"wt{index}"
            placeholders.append(f":{name}")
            params[name] = value
        clauses.append(f"w.work_type IN ({', '.join(placeholders)})")
    for index, genre in enumerate(_iter_terms(genres)):
        clauses.append(f"(w.genres IS NOT NULL AND radd_list_has(w.genres, :genre{index}))")
        params[f"genre{index}"] = genre
    for index, language in enumerate(_iter_terms(languages)):
        # Work-level declared language OR any print that actually carries that audio
        # track — a Hindi-dubbed print of an English work must be findable in Hindi.
        clauses.append(
            f"(radd_list_has(COALESCE(w.languages, ''), :lang{index})"
            " OR EXISTS (SELECT 1 FROM cat_releases lr"
            f"  WHERE lr.work_id = w.id AND radd_list_has(lr.audio_languages, :lang{index})))"
        )
        params[f"lang{index}"] = language
    resolutions: list[str] = []
    if qualities not in (None, "", "all"):
        values = ([qualities] if isinstance(qualities, str)
                  else [str(v) for v in qualities])
        for value in values:
            key = normalize_text(value).replace(" ", "")
            resolutions.extend(_QUALITY_ALIASES.get(key, (key,)))
    if resolutions:
        placeholders = []
        for index, value in enumerate(sorted(set(resolutions))):
            name = f"res{index}"
            placeholders.append(f":{name}")
            params[name] = value
        clauses.append(
            "EXISTS (SELECT 1 FROM cat_releases qr"
            f" WHERE qr.work_id = w.id AND qr.resolution IN ({', '.join(placeholders)}))")
    if available in (True, "stream", "download"):
        # Same live-link definition as `_AVAIL_COLS`, so the facet and the availability
        # block of the items it returns can never disagree.
        if available is True:
            clauses.append(_AVAIL_EXISTS_TEMPLATE.format(
                alias="av", playability="av.playability NOT IN ('none')"))
        elif available == "stream":
            clauses.append(_AVAIL_EXISTS_TEMPLATE.format(
                alias="av", playability="av.playability IN ('stream', 'both')"))
        else:
            clauses.append(_AVAIL_EXISTS_TEMPLATE.format(
                alias="av", playability="av.playability IN ('download', 'both')"))
    if year_from not in (None, ""):
        clauses.append("COALESCE(w.year, 0) >= :yfrom")
        params["yfrom"] = int(year_from)
    if year_to not in (None, ""):
        clauses.append("COALESCE(w.year, 0) <= :yto")
        params["yto"] = int(year_to)
    if min_quality not in (None, ""):
        clauses.append("COALESCE(w.best_quality_score, 0) >= :minq")
        params["minq"] = int(min_quality)
    if animated is not None:
        # API_V2.md §12 lists `animated` as a browse facet; `cat_works.is_animated`
        # is the projector's own flag, so it filters in SQL like every other facet.
        clauses.append("COALESCE(w.is_animated, 0) = :animated")
        params["animated"] = 1 if animated else 0
    for index, values in enumerate((country, industry)):
        terms = _iter_terms(values)
        if not terms:
            continue
        column = "country" if index == 0 else "industry"
        placeholders = []
        for term_index, term in enumerate(terms):
            name = f"{column}{index}_{term_index}"
            placeholders.append(f":{name}")
            params[name] = normalize_text(term)
        clauses.append(f"LOWER(COALESCE(w.{column}, '')) IN ({', '.join(placeholders)})")
    return clauses, params


def _iter_terms(values) -> list[str]:
    if values in (None, "", []):
        return []
    items = [values] if isinstance(values, str) else list(values)
    out = []
    for item in items:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


# ── item / link shaping ──────────────────────────────────────────────────────

#: How the v2 read model rewrites artwork for whoever we are serving. Deny by
#: default: unconfigured means root-relative handles, so an upstream art host can
#: never escape even if a future mount forgets to configure the boundary.
_PUBLIC_CONTEXT = {"base_url": "", "secret": ""}


def configure_public(base_url: str = "", secret: str = "") -> None:
    """Set the v2 public boundary (called by the HTTP layer, like `redact.set_needles`)."""
    _PUBLIC_CONTEXT["base_url"] = base_url or ""
    _PUBLIC_CONTEXT["secret"] = secret or ""


def _text(value):
    """Display text with known source brands removed, `None` staying `None`.

    A missing title is not an empty title: the app renders one as absent and the
    other as a blank row."""
    return None if value is None else redact.scrub_text(value)


def _images(work: dict, *, base_url: str | None = None, secret: str | None = None,
            work_id=None) -> dict:
    poster = work.get("poster_url")
    backdrops = _json_list(work.get("backdrop_urls"))
    base = _PUBLIC_CONTEXT["base_url"] if base_url is None else base_url
    key = _PUBLIC_CONTEXT["secret"] if secret is None else secret
    target = work_id if work_id is not None else work.get("id")

    def art(url, kind, index):
        # A poster on a public CDN names nothing about us and passes straight
        # through; a poster still sitting on the site we scraped it from becomes
        # one of our own handles, so no host name ever reaches a client.
        if not url:
            return None
        value = redact.public_art_value(url, target, key, base, kind, index,
                                        table="works")
        return {"src": value, "kind": kind, "index": index,
                "width": None, "height": None, "locale": None}

    return {
        "poster": art(poster, "poster", 0),
        # The projector stores no poster dimensions or locales: reported as null,
        # never guessed (API_V2.md §9 wants structured images with width).
        # The key is `src`, not `url`: `url` is on the public deny-list (every
        # upstream page column is named `url` somewhere), and artwork is one of
        # our own handles, so it gets a key the deny-list never claims.
        "backdrops": [value for value in
                      (art(url, "backdrop", index) for index, url in enumerate(backdrops))
                      if value],
    }


# State-aware availability. `cat_works.available_stream` / `available_download` are the
# projector's kind-only rollups (they count a dead link as "available"), which is a lie
# a player will discover on the first tap, so the read model recomputes availability
# from the links that are actually alive. A dead link is still *listed* everywhere —
# only the availability claim changes (zero data loss, no false promise).
_AVAIL_COLS = """
        (SELECT COUNT(*) FROM cat_links la WHERE la.work_id = w.id
          AND COALESCE(la.state, 'active') <> 'dead'
          AND la.playability IN ('stream', 'both')) AS live_stream_links,
        (SELECT COUNT(*) FROM cat_links ld WHERE ld.work_id = w.id
          AND COALESCE(ld.state, 'active') <> 'dead'
          AND ld.playability IN ('download', 'both')) AS live_download_links,
        (SELECT COUNT(*) FROM cat_links lp WHERE lp.work_id = w.id
          AND COALESCE(lp.state, 'active') <> 'dead'
          AND lp.playability NOT IN ('none')) AS live_play_links
"""


_AVAIL_EXISTS_TEMPLATE = (
    "EXISTS (SELECT 1 FROM cat_links {alias} WHERE {alias}.work_id = w.id"
    " AND COALESCE({alias}.state, 'active') <> 'dead' AND {playability})")


def _available_view(work: dict) -> dict:
    """The availability block of a grid item, computed from live links when known."""
    if work.get("live_play_links") is not None:
        stream = bool(work.get("live_stream_links"))
        download = bool(work.get("live_download_links"))
        any_playable = bool(work.get("live_play_links"))
    else:                                  # a bare cat_works row: kind-only rollups
        stream = bool(work.get("available_stream"))
        download = bool(work.get("available_download"))
        any_playable = stream or download
    return {
        "stream": stream,
        "download": download,
        "any": any_playable,
        # `state` per API_V2.md §6 row 13: a work whose links are all dead is still
        # listed (we do not hide data) but must not claim availability.
        "state": "available" if any_playable else "unavailable",
    }


def _browse_item(row) -> dict:
    work = _as_dict(row)
    seasons = work.get("season_count")
    return {
        "id": work["id"],
        "title": work["title"],
        "year": work.get("year"),
        "work_type": work.get("work_type"),
        "animated": bool(work.get("is_animated")),
        # Only ever true for an admin listing: a default response excludes these rows.
        "adult": bool(work.get("is_18_plus")),
        "poster": _images(work)["poster"],
        "rating": work.get("imdb_rating"),
        "genres": _json_list(work.get("genres")),
        "languages": _json_list(work.get("languages")),
        "country": work.get("country"),
        "industry": work.get("industry"),
        "site_count": work.get("site_count"),
        "seasons": seasons if seasons is not None else None,
        "episodes": work.get("episode_count"),
        "prints": work.get("release_count"),
        "quality_max": work.get("max_resolution") or "unknown",
        "best_quality_score": work.get("best_quality_score"),
        "available": _available_view(work),
        "flags": _work_flags(work),
        "identity_suspect": bool(work.get("identity_suspect")),
        "entitlement": {"model": work.get("entitlement_model") or "free"},
        "first_seen_at": work.get("first_seen_at"),
        "updated_at": work.get("updated_at"),
    }


def _work_flags(work: dict) -> list[str]:
    flags = []
    if work.get("identity_suspect"):
        flags.append("identity_suspect")
    if work.get("open_reviews"):
        flags.append("needs_review")
    if not _available_view(work)["any"]:
        flags.append("no_playable_source")
    return flags


_EVIDENCE_SQL = """
SELECT e.link_id, e.probed_at, e.ok, e.protocol, e.http_status, e.content_type,
       e.size_bytes, e.latency_ms, e.speed_mbps, e.accepts_ranges, e.error
FROM cat_link_evidence e
JOIN (SELECT link_id, MAX(probed_at) AS probed_at FROM cat_link_evidence
      WHERE link_id IN ({marks}) GROUP BY link_id) latest
  ON latest.link_id = e.link_id AND latest.probed_at = e.probed_at
"""


def _latest_evidence(conn, link_ids: list[int]) -> dict[int, dict]:
    if not link_ids or not _has_table(conn, "cat_link_evidence"):
        return {}
    marks = ", ".join(str(int(i)) for i in link_ids)
    try:
        rows = conn.execute(_EVIDENCE_SQL.format(marks=marks)).fetchall()
    except sqlite3.Error:
        return {}
    out: dict[int, dict] = {}
    for row in rows:                      # newest probe wins on ties
        data = _as_dict(row)
        link_id = data.pop("link_id")
        out[link_id] = data
    return out


_SECRET_BY_PATH: dict[str, str] = {}


def signing_secret(conn) -> str:
    """The handle-signing secret for this database, read once per path.

    Layer 1 and the ledger live in the same file, so the public edge and the v2
    read model sign with one key and a handle minted here validates there too."""
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        path = (row[2] or "") if row else ""
    except sqlite3.Error:
        path = ""
    secret = _SECRET_BY_PATH.get(path)
    if secret is None:
        secret = redact.stream_secret(path or None)
        _SECRET_BY_PATH[path] = secret
    return secret


def _link_group(row) -> int:
    """Candidate group from `playability` (what a client can do with the link).

    A link that only unwraps to a zip/rar archive can never be opened by the player,
    so it is treated as a download even when a scraper labelled it streamable.
    """
    playability = str(row["playability"] or "unknown")
    if str(row["kind"] or "") == "dead_end":
        return _GROUP_NONE
    if _is_static_file(row["final_url"] or row["url"]):
        return _GROUP_DOWNLOAD
    return _PLAYABILITY_GROUP.get(playability, _GROUP_NONE)


_STATIC_EXTS = (".zip", ".rar", ".7z", ".tar", ".gz")


def _is_static_file(url) -> bool:
    path = str(url or "").lower().split("?", 1)[0].split("#", 1)[0]
    return path.endswith(_STATIC_EXTS)


def _link_view(row, evidence: dict | None, secret: str = "") -> dict:
    """One `cat_links` row as the public may see it.

    The descriptor and the measurement stay; *who* hosts it goes: no site, no
    service, no source name, no upstream URL, no third-party resource id. What a
    client gets instead is our own opaque `stream_id`, and the one neutral word
    a user may ever be told about a server — how fast it behaves, not who runs it.
    """
    link = _as_dict(row)
    measured = evidence or {}
    speed = measured.get("speed_mbps")
    if speed is None:
        speed = link.get("speed_mbps")
    latency = measured.get("latency_ms")
    if latency is None:
        latency = link.get("latency_ms")
    status = measured.get("http_status")
    if status is None:
        status = link.get("http_status")
    ranges = link.get("accepts_ranges")
    if measured.get("accepts_ranges") is not None:
        ranges = measured["accepts_ranges"]
    state = link.get("state") or "unknown"
    resumable = bool(link.get("resumable")) or bool(ranges)
    return {
        "link_id": link["id"],
        "release_id": link["release_id"],
        "work_id": link["work_id"],
        "stream_id": (redact.mint_token(link["id"], secret) if secret else str(link["id"])),
        "label": "Fast direct" if resumable else "Standard",
        "kind": link.get("kind"),
        "playability": link.get("playability"),
        # Honest behaviour, not provenance: can our one player start this copy
        # itself. `tiers.py` reads it to pick the winner of a quality band, and
        # the app reads it to decide between the player and the download card.
        "playable": _link_group(row) <= _GROUP_RESOLVE and state != "dead",
        "group": _link_group(row),
        "state": state,
        "dead": state not in ("active", "unknown", "unchecked"),
        "tier": link.get("tier"),
        "protocol": link.get("protocol"),
        "content_type": link.get("content_type"),
        "ephemeral": bool(link.get("ephemeral")),
        "expires_at": link.get("expires_at"),
        "resumable": bool(link.get("resumable")),
        "accepts_ranges": bool(ranges),
        "cors_open": bool(link.get("cors_open")),
        "size_bytes": link.get("size_bytes"),
        "rank_score": link.get("rank_score"),
        "http_status": status,
        "latency_ms": latency,
        "speed_mbps": speed,
        # Honest about provenance: `measured` is only true when link_health actually
        # probed this link (cat_links carries no latency of its own until then).
        "measured": bool(measured) or link.get("latency_ms") is not None,
        "last_evidence_at": measured.get("probed_at") if measured else link.get("last_evidence_at"),
        "probe_error": measured.get("error") if measured else None,
    }


def _sort_links(links: list[dict]) -> list[dict]:
    """Deterministic candidate order: live before dead, then group, then rank_score,
    then measured speed desc, then measured latency asc, then id asc.

    A dead-but-fast link therefore ranks *below* a live-slow one (the dead link is
    still returned, never hidden) and the order is total, so two pages of results can
    never disagree.
    """
    return sorted(links, key=lambda link: (
        1 if link["dead"] else 0,
        link["group"],
        -(link["rank_score"] or 0),
        # An unmeasured link sorts after every measured one at the same rank_score,
        # so a probe result always beats an assumption.
        0 if link["speed_mbps"] is not None else 1,
        -(link["speed_mbps"] or 0),
        link["latency_ms"] if link["latency_ms"] is not None else 10 ** 9,
        link["link_id"],
    ))


def _ordered_links(conn, release_ids: list[int]) -> dict[int, list[dict]]:
    """All links for the given prints, grouped by release and ordered by `rank_score`.

    The Layer-1 `rank_score` already folds playability, tier, ephemerality, range support
    and link state (dead = -450) into one number, so "best print link first" is exactly
    "highest rank_score first"; `play_bundle` re-orders these same views for failover
    with `_sort_links`, which additionally forces live-before-dead by group.

    One query plus one evidence query, so a work with 40 prints stays cheap.
    """
    if not release_ids:
        return {}
    marks = ", ".join(str(int(i)) for i in release_ids)
    rows = conn.execute(
        f"SELECT * FROM cat_links WHERE release_id IN ({marks}) ORDER BY id", tuple()).fetchall()
    evidence = _latest_evidence(conn, [row["id"] for row in rows])
    secret = signing_secret(conn)
    views: dict[int, list[dict]] = {}
    for row in rows:
        views.setdefault(row["release_id"], []).append(
            _link_view(row, evidence.get(row["id"]), secret))
    for items in views.values():
        items[:] = sorted(items, key=lambda link: (-(link["rank_score"] or 0), link["link_id"]))
    return views


# ── print label ──────────────────────────────────────────────────────────────

def print_label(release) -> str:
    """Human print name for the UI: '4K HDR10 BluRay REPACK', '720p CAM — avoid'.

    Built only from columns the projector writes; a CAM-family print always gets the
    explicit ' — avoid' warning so a cam can never look like a distribution print.
    """
    row = _as_dict(release) if not isinstance(release, dict) else release
    res = _RES_LABEL.get(str(row.get("resolution") or "").strip().lower(),
                         str(row.get("resolution") or ""))
    source = _SOURCE_LABEL.get(str(row.get("source_tag") or "").strip().lower(),
                               str(row.get("source_tag") or ""))
    try:
        hdrs = [_HDR_LABEL.get(str(h).strip().lower(), str(h).strip().upper())
                for h in _json_list(row.get("hdr"))]
    except Exception:
        hdrs = []
    edition = _EDITION_LABEL.get(str(row.get("edition") or "").strip().lower(),
                                 str(row.get("edition") or ""))
    label_text = str(row.get("label") or "")
    parts: list[str] = [p for p in (res, *hdrs, source) if p]
    if edition:
        parts.append(edition)
    if "repack" in label_text.lower():
        parts.append("REPACK")
    elif "proper" in label_text.lower():
        parts.append("PROPER")
    try:
        version = int(row.get("print_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version > 0:
        parts.append(f"v{version}")
    if row.get("bit_depth") and int(row["bit_depth"]) >= 10 and "10bit" not in parts:
        parts.append("10-bit")
    if row.get("watermarked"):
        parts.append("Watermarked")
    if not parts:
        parts.append("Unknown print")
    core = " ".join(parts)
    details: list[str] = []
    codec = str(row.get("codec") or "").strip()
    if codec and codec.lower() not in ("unknown",):
        details.append(codec.upper())
    audio = _json_list(row.get("audio_languages"))
    if audio:
        details.append(" + ".join(audio))
    if str(row.get("subtitle_mode") or "") == "external":
        details.append("ESubs")
    elif str(row.get("subtitle_mode") or "") == "hardcoded":
        details.append("HardSubs")
    out = " · ".join([core] + [d for d in details if d]) if details else core
    if str(row.get("source_tag") or "").strip().lower() in _CAM_TAGS:
        out = f"{out} — avoid"
    return out


# ── print / episode coverage ─────────────────────────────────────────────────

def _print_view(conn, release_row, links_by_release: dict[int, list[dict]]) -> dict:
    release = _as_dict(release_row)
    lo, hi = _episode_range_bounds(release.get("episode_range")
                                   or release.get("label") or "")
    flags = _json_list(release.get("flags"))
    return {
        "release_id": release["id"],
        "work_id": release["work_id"],
        "print_label": print_label(release),
        "label": release.get("label"),
        "coverage": {
            "type": release.get("coverage_type"),
            "season_number": release.get("season_number"),
            "part_number": release.get("part_number"),
            "episode_range": release.get("episode_range") or None,
            "episode_first": lo or None,
            "episode_last": hi or None,
            "enumerated": release.get("coverage_type") in ("single_episode", "episode_range",
                                                           "season_pack", "parts"),
        },
        "resolution": release.get("resolution"),
        "quality_label": release.get("quality_label"),
        "source_tag": release.get("source_tag"),
        "codec": release.get("codec"),
        "bit_depth": release.get("bit_depth"),
        "hdr": _json_list(release.get("hdr")),
        "container": release.get("container"),
        "edition": release.get("edition"),
        "print_version": release.get("print_version"),
        "release_group": release.get("release_group") or None,
        "size_bytes": release.get("size_bytes"),
        "size_per_episode_bytes": release.get("size_per_episode_bytes"),
        "audio": {
            "languages": _json_list(release.get("audio_languages")),
            "channels": release.get("audio_channels"),
            "codecs": _json_list(release.get("audio_codecs")),
            "dual_audio": bool(release.get("dual_audio")),
        },
        "subtitles": {
            "mode": release.get("subtitle_mode"),
            "languages": _json_list(release.get("subtitle_languages")),
        },
        "watermarked": bool(release.get("watermarked")),
        "official_print": bool(release.get("official_print")),
        "quality_score": release.get("quality_score"),
        "flags": flags,
        "counts": {
            "links": release.get("link_count"),
            "streamable": release.get("streamable_count"),
            "downloadable": release.get("downloadable_count"),
        },
        "created_at": release.get("created_at"),
        "links": links_by_release.get(release["id"], []),
    }


def _release_map(conn, work_id: int) -> dict[int, dict]:
    return {row["id"]: _as_dict(row) for row in conn.execute(
        "SELECT * FROM cat_releases WHERE work_id = ?", (work_id,)).fetchall()}


def _offset_lookup(conn, *, work_key: str, season_number: int, episode_number: int,
                   release_label: str) -> dict | None:
    """Best cat_offsets row for one episode: exact print label first, then the
    label-agnostic ('') rows, most-confirmed and newest winning."""
    if not _has_table(conn, "cat_offsets"):
        return None
    row = conn.execute(
        """
        SELECT offset_seconds, chapter_title, release_label, confirmed_by, updated_at
        FROM cat_offsets
        WHERE work_key = :key AND season_number = :season AND episode_number = :episode
        ORDER BY (release_label = :label) DESC, (release_label = '') DESC,
                 confirmed_by DESC, updated_at DESC
        LIMIT 1
        """,
        {"key": work_key, "season": int(season_number or 0),
         "episode": int(episode_number), "label": release_label or ""},
    ).fetchone()
    return _as_dict(row) if row else None


def _covering_prints(conn, *, work: dict, season_number: int, episode_number: int,
                     episode_id: int | None) -> tuple[list[dict], list[dict]]:
    """Every print that stands for one episode, plus the ones whose scope is unclear.

    Materialised rows (`cat_release_episodes`) are authoritative. Packs and
    over-cap ranges have no rows by design, so they are matched structurally:
      * season_pack / parts  -> same season as the request
      * episode_range        -> parsed bounds contain the episode
      * whole_work           -> the work itself (movies), or the same season when the
                                projector stamped one
    Returns (confident, scope_unresolved).
    """
    work_id = int(work["id"])
    work_key = str(work.get("work_key") or "")
    releases = _release_map(conn, work_id)
    if not releases:
        return [], []
    confident: dict[int, dict] = {}
    unresolved: list[dict] = []
    family = catalog_v2.work_family(str(work.get("work_type") or "unknown"))

    if episode_id is not None:
        rows = conn.execute(
            """
            SELECT re.episode_id, re.ordinal, re.offset_seconds, re.chapter_title,
                   re.release_id
            FROM cat_release_episodes re WHERE re.episode_id = :ep AND re.release_id IN
            (SELECT id FROM cat_releases WHERE work_id = :work)
            ORDER BY re.release_id
            """, {"ep": episode_id, "work": work_id}).fetchall()
        for row in rows:
            entry = dict(confident.get(row["release_id"]) or {})
            entry.update({
                "release_id": row["release_id"],
                "match_kind": "materialised",
                "ordinal": row["ordinal"],
                "offset_seconds": row["offset_seconds"],
                "chapter_title": row["chapter_title"],
            })
            confident[row["release_id"]] = entry

    for release_id, release in releases.items():
        coverage = str(release.get("coverage_type") or "whole_work")
        rel_season = release.get("season_number")
        rel_season = int(rel_season) if rel_season not in (None, "") else 0
        if release_id in confident:
            continue
        if coverage == "single_episode":
            # A per-episode print without its materialised row would be a projector
            # bug; only accept it when the stamped season and range agree.
            lo, hi = _episode_range_bounds(release.get("label") or "")
            if rel_season == int(season_number or 0) and lo == int(episode_number or 0):
                confident[release_id] = {
                    "release_id": release_id, "match_kind": "structural",
                    "ordinal": int(episode_number or 0),
                    "offset_seconds": None, "chapter_title": None}
            continue
        if coverage == "season_pack":
            if rel_season == int(season_number or 0):
                confident[release_id] = {
                    "release_id": release_id, "match_kind": "pack_scope",
                    "ordinal": int(episode_number or 0),
                    "offset_seconds": None, "chapter_title": None}
            elif rel_season == 0 and family != "movie":
                unresolved.append({"release_id": release_id, "reason": "season_unresolved",
                                   "coverage_type": coverage, "label": release.get("label")})
            continue
        if coverage in ("episode_range", "parts"):
            lo, hi = _episode_range_bounds(release.get("episode_range")
                                           or release.get("label") or "")
            same_season = (rel_season == int(season_number or 0))
            if same_season and lo and hi and lo <= int(episode_number or 0) <= hi:
                confident[release_id] = {
                    "release_id": release_id, "match_kind": "range_bounds",
                    "ordinal": int(episode_number or 0),
                    "offset_seconds": None, "chapter_title": None}
            elif rel_season == 0 and family != "movie":
                unresolved.append({"release_id": release_id, "reason": "season_unresolved",
                                   "coverage_type": coverage, "label": release.get("label")})
            continue
        # whole_work
        if rel_season and rel_season == int(season_number or 0):
            confident[release_id] = {
                "release_id": release_id, "match_kind": "whole_work_season",
                "ordinal": int(episode_number or 0),
                "offset_seconds": None, "chapter_title": None}
        elif family == "movie" and not rel_season:
            confident[release_id] = {
                "release_id": release_id, "match_kind": "whole_work",
                "ordinal": int(episode_number or 0),
                "offset_seconds": None, "chapter_title": None}
        elif rel_season == 0:
            unresolved.append({"release_id": release_id, "reason": "scope_unresolved",
                               "coverage_type": coverage, "label": release.get("label")})

    # Overlay learned offsets for the prints that have no materialised row.
    for release_id, entry in confident.items():
        if entry.get("offset_seconds") is not None or entry.get("chapter_title") is not None:
            continue
        release = releases[release_id]
        if str(release.get("coverage_type")) in ("single_episode",):
            continue
        offset = _offset_lookup(conn, work_key=work_key,
                                season_number=release.get("season_number") or season_number or 0,
                                episode_number=episode_number,
                                release_label=str(release.get("label") or ""))
        if offset:
            entry["offset_seconds"] = offset["offset_seconds"]
            entry["chapter_title"] = offset["chapter_title"]
            entry["offset_confirmed_by"] = offset["confirmed_by"]
            entry["offset_source"] = ("cat_offsets:label"
                                      if (offset["release_label"] or "") == str(release.get("label") or "")
                                      else "cat_offsets:any_label")

    ordered = []
    for release_id in sorted(confident, key=lambda rid: (
            -(releases[rid]["quality_score"] or 0), rid)):
        entry = confident[release_id]
        release = releases[release_id]
        coverage = str(release.get("coverage_type") or "whole_work")
        entry["print_label"] = print_label(release)
        entry["label"] = release.get("label")
        entry["coverage_type"] = coverage
        entry["season_number"] = release.get("season_number")
        entry["resolution"] = release.get("resolution")
        entry["quality_score"] = release.get("quality_score")
        entry["size_bytes"] = release.get("size_bytes")
        entry["needs_offset_calibration"] = coverage in ("season_pack", "parts") and (
            entry.get("offset_seconds") is None)
        if entry["needs_offset_calibration"]:
            entry["pack_warning"] = (
                f"This file contains all of Season {release.get('season_number') or '?'}"
                if coverage == "season_pack" else "This file contains multiple parts")
        ordered.append(entry)
    for entry in unresolved:
        release = releases[entry["release_id"]]
        entry["print_label"] = print_label(release)
        entry["season_number"] = release.get("season_number")
        entry["quality_score"] = release.get("quality_score")
    return ordered, unresolved


def _find_episode(conn, *, work_id: int, season_number, episode_number, absolute):
    """Resolve one `cat_episodes` row from whichever addressing mode was used."""
    if absolute not in (None, ""):
        return conn.execute(
            "SELECT * FROM cat_episodes WHERE work_id = ? AND absolute_number = ?",
            (work_id, int(absolute))).fetchone()
    if season_number not in (None, "") and episode_number not in (None, ""):
        return conn.execute(
            """
            SELECT e.* FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id
            WHERE e.work_id = ? AND s.number = ? AND e.number = ?
            """, (work_id, int(season_number), int(episode_number))).fetchone()
    return None


# ── browse / search ──────────────────────────────────────────────────────────

def _listing_error(sort, order):
    if sort not in SORT_KEYS:
        return _bad_input(f"sort must be one of {', '.join(SORT_KEYS)}")
    if order not in ("desc", "asc"):
        return _bad_input("order must be 'desc' or 'asc'")
    return None


def _run_listing(conn, *, sort, order, limit, include_adult, cursor,
                 facet_clauses, facet_params, query_tokens, query_norm,
                 use_fts_match) -> dict:
    """Shared engine for `browse` and `search`.

    Pagination is keyset (`WHERE (expr, id) > (cursor)`), not OFFSET, because the
    catalog is re-sorted by every ingestion run: an offset page can repeat or skip a
    title, a keyset page cannot, provided the sort expression is total — which is why
    every expression is COALESCEd and the `id` tiebreak is fixed at ASC.
    """
    clauses = ["1 = 1"] if include_adult else [_adult_clause("w")]
    clauses.extend(facet_clauses)
    params = dict(facet_params)
    expr = _sort_expr(sort)

    if query_tokens:
        hay = ("radd_hay(w.title, w.original_title, w.genres,"
               " (SELECT group_concat(a.alias, ' | ') FROM cat_work_aliases a"
               "  WHERE a.work_id = w.id))")
        # One ANDed LIKE per query token: every token must appear somewhere in the
        # normalised title/original-title/alias haystack. No token is ever dropped.
        for index, token in enumerate(query_tokens):
            clauses.append(f"{hay} LIKE :q{index}")
            params[f"q{index}"] = f"%{token}%"

    where_sql = " AND ".join(clauses)
    fingerprint = _fingerprint(where_sql, dict(sorted(params.items())))
    if cursor is not None and cursor.get("f") not in (None, fingerprint):
        # A cursor minted for a different facet set would silently skip or repeat
        # rows, so it is rejected instead of trusted.
        return {"ok": False, "error": {"code": "cursor_invalid",
                                       "message": "Cursor belongs to a different filter set"}}

    if query_tokens and use_fts_match:
        # Optional accelerator: the fingerprint above is deliberately computed
        # without it, so a cursor keeps working if the FTS index disappears.
        where_sql += (" AND w.id IN (SELECT rowid FROM cat_works_fts"
                      " WHERE cat_works_fts MATCH :fts)")
        params["fts"] = " ".join(f'"{token}"*' for token in query_tokens)

    select_cols = """
        w.*,
        (SELECT COUNT(*) FROM cat_seasons s WHERE s.work_id = w.id) AS season_count,
        (SELECT COUNT(*) FROM cat_review_queue q WHERE q.work_id = w.id
          AND q.resolved_at IS NULL) AS open_reviews
    """ + "," + _AVAIL_COLS
    sql = f"SELECT {select_cols}, {expr} AS __sk FROM cat_works w WHERE {where_sql}"
    if cursor is not None:
        params["cv"] = cursor["v"]
        params["cid"] = int(cursor["i"])
        op = "<" if order == "desc" else ">"
        sql += f" AND (({expr} {op} :cv) OR ({expr} = :cv AND w.id > :cid))"
    direction = "DESC" if order == "desc" else "ASC"
    collate = " COLLATE NOCASE" if sort == "title" else ""
    sql += f" ORDER BY ({expr}{collate}) {direction}, id ASC"
    sql += " LIMIT :lim"
    params["lim"] = limit + 1

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        if not use_fts_match:
            raise
        # The FTS table exists but cannot serve this query (unsupported syntax or a
        # non-fts5 shim): degrade to the documented LIKE scan rather than 500.
        return _run_listing(conn, sort=sort, order=order, limit=limit,
                            include_adult=include_adult, cursor=cursor,
                            facet_clauses=facet_clauses, facet_params=facet_params,
                            query_tokens=query_tokens, query_norm=query_norm,
                            use_fts_match=False)
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for row in rows:
        item = _browse_item(row)
        item["sort_value"] = row["__sk"]
        items.append(item)
    if query_norm:
        for item in items:
            item["relevance"] = _relevance(item, query_norm, query_tokens)
        items.sort(key=lambda item: (
            -item["relevance"],
            -(item["sort_value"] if isinstance(item["sort_value"], (int, float)) else 0),
            item["id"]))
    next_cursor = None
    if has_more and rows:
        next_cursor = encode_cursor(sort_value=rows[-1]["__sk"], work_id=rows[-1]["id"],
                                   sort=sort, order=order, fingerprint=fingerprint)
    count_params = {key: value for key, value in params.items()
                    if key not in ("lim", "cv", "cid")}
    total_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM cat_works w WHERE {where_sql}", count_params).fetchone()
    return {
        "ok": True,
        "items": items,
        "count": len(items),
        "limit": limit,
        "sort": sort,
        "order": order,
        "next_cursor": next_cursor,
        "has_more": has_more,
        # Same WHERE as the rows, so a total can never advertise hidden adult titles.
        "total_estimate": (int(total_row["n"]) if total_row else 0),
        "adult_included": bool(include_adult),
        "fingerprint": fingerprint,
    }


def _relevance(item: dict, query_norm: str, tokens: list[str]) -> int:
    """Coarse, documented ranking for search: exact normalised title first,
    then prefix, then containment, then alias-only hits; quality breaks ties."""
    title_norm = normalize_text(item.get("title"))
    year = item.get("year")
    title_with_year = f"{title_norm} {year}".strip()
    score = 0
    if title_norm == query_norm or title_with_year == query_norm:
        score = 100
    elif title_norm.startswith(query_norm):
        score = 60
    elif query_norm in title_norm:
        score = 40
    else:
        score = 10
    if all(token in title_norm for token in tokens):
        score += 20
    score += min(int(item.get("best_quality_score") or 0), 1000) // 100
    score += int(round((item.get("rating") or 0) * 2))
    return score


@public_edge
def browse(conn, *, content_type=None, genres=(), languages=(), qualities=(),
           sort="trending", order="desc", cursor=None, limit=DEFAULT_LIMIT,
           include_adult=False, q=None, available=None, year_from=None, year_to=None,
           min_quality=None, animated=None, country=(), industry=()) -> dict:
    """Faceted catalog browse with keyset pagination.

    Returns ``{items[], next_cursor, has_more, total_estimate, ...}``. `total_estimate`
    is computed with the *same* adult filter as the rows, so it can never advertise
    titles the list hides.
    """
    _require_row_factory(conn)
    _register_udfs(conn)
    err = _listing_error(sort, order)
    if err:
        return err
    limit = _clamp_limit(limit)
    facet_clauses, facet_params = _facet_clauses(
        content_type, genres, languages, qualities, available, year_from, year_to,
        min_quality, animated=animated, country=country, industry=industry)
    query_norm = normalize_text(q)
    tokens = query_norm.split()
    decoded = None
    if cursor not in (None, ""):
        decoded = decode_cursor(cursor)
        if not decoded:
            return {"ok": False, "error": {"code": "cursor_invalid",
                                           "message": "Cursor is not valid for this request"}}
        if decoded.get("s") != sort or decoded.get("o") != order:
            return {"ok": False, "error": {"code": "cursor_invalid",
                                           "message": "Cursor belongs to a different sort/order"}}
    return _run_listing(
        conn, sort=sort, order=order, limit=limit, include_adult=bool(include_adult),
        cursor=decoded, facet_clauses=facet_clauses, facet_params=facet_params,
        query_tokens=tokens, query_norm=query_norm, use_fts_match=_has_table(conn, "cat_works_fts"))


@public_edge
def search(conn, *, q, limit=DEFAULT_LIMIT, include_adult=False, content_type=None,
           genres=(), languages=(), qualities=(), sort="relevance", order="desc",
           cursor=None, fields=None) -> dict:
    """Title search that survives dirty scraped titles.

    Matching is per-token AND over a normalised haystack (casefold, diacritics
    stripped, punctuation → spaces) built from `cat_works.title`, `original_title`
    and every `cat_work_aliases.alias`, so '(2025)' suffixes, ':' in 'Dune: Part
    Two', accents and 'Hindi Dubbed' noise can never make a query return nothing.
    `sort='relevance'` orders by the documented `_relevance()` score; any browse
    sort key is also accepted.

    Known limit: without an FTS index this is a full scan of `cat_works` (O(rows));
    correct but linear, and it does not use an index. See HANDOFF_api_read.md.
    """
    _require_row_factory(conn)
    _register_udfs(conn)
    query_norm = normalize_text(q)
    tokens = query_norm.split()
    if not tokens:
        return {"ok": True, "items": [], "count": 0, "query": q, "normalized": query_norm,
                "limit": _clamp_limit(limit, ceiling=MAX_SEARCH_LIMIT), "next_cursor": None,
                "has_more": False, "total_estimate": 0, "adult_included": bool(include_adult),
                "truncated": False, "fields": fields or None,
                "note": "empty query returns no results by design"}
    effective_sort = "trending" if sort in ("relevance", "", None) else sort
    err = _listing_error(effective_sort, order)
    if err:
        return err
    limit = _clamp_limit(limit, ceiling=MAX_SEARCH_LIMIT)
    facet_clauses, facet_params = _facet_clauses(
        content_type, genres, languages, qualities, None, None, None, None)
    result = _run_listing(
        conn, sort=effective_sort, order=order, limit=limit,
        include_adult=bool(include_adult),
        cursor=(decode_cursor(cursor) if cursor else None),
        facet_clauses=facet_clauses, facet_params=facet_params,
        query_tokens=tokens, query_norm=query_norm,
        use_fts_match=_has_table(conn, "cat_works_fts"))
    if cursor not in (None, "") and not result.get("ok"):
        return result
    result["query"] = q
    result["normalized"] = query_norm
    result["tokens"] = tokens
    result["sort"] = sort
    result["fields"] = fields or None
    if fields:
        wanted = {str(f).strip() for f in (fields if isinstance(fields, (list, tuple))
                                           else re.split(r"[,\s]+", str(fields))) if str(f).strip()}
        wanted.add("id")
        result["items"] = [{k: v for k, v in item.items() if k in wanted}
                           for item in result["items"]]
    return result


@public_edge
def suggest(conn, *, q, limit=10, include_adult=False) -> dict:
    """Cheap type-ahead: normalised title prefixes only, no aliases, no ranking maths."""
    _require_row_factory(conn)
    _register_udfs(conn)
    query_norm = normalize_text(q)
    if len(query_norm) < 2:
        return {"ok": True, "items": [], "query": q,
                "note": "suggest requires at least 2 characters"}
    limit = _clamp_limit(limit, default=10, ceiling=20)
    where = "w.title IS NOT NULL" if include_adult else f"{_adult_clause('w')}"
    rows = conn.execute(
        f"""
        SELECT w.id, w.title, w.year, w.work_type, w.poster_url, w.max_resolution
        FROM cat_works w WHERE {where} AND radd_norm(w.title) LIKE :pfx
        ORDER BY LENGTH(radd_norm(w.title)) ASC, COALESCE(w.year, 0) DESC, w.id ASC
        LIMIT :lim
        """, {"pfx": f"{query_norm}%", "lim": limit}).fetchall()
    return {
        "ok": True,
        "query": q,
        "normalized": query_norm,
        "items": [{"id": row["id"], "title": row["title"], "year": row["year"],
                   "work_type": row["work_type"], "poster_url": row["poster_url"],
                   "quality_max": row["max_resolution"]} for row in rows],
        "count": len(rows),
        "adult_included": bool(include_adult),
    }


# ── work detail ──────────────────────────────────────────────────────────────

def _resolve_work(conn, *, work_id=None, work_key=None, slug=None, url=None):
    """Address a work by numeric id, work_key ('imdb:tt..' / 'tmdb:..' / 'movie:..'),
    page slug or full page URL. Returns the cat_works row or None. Never raises.
    """
    if work_id not in (None, ""):
        text = str(work_id).strip()
        row = conn.execute(
            ("SELECT * FROM cat_works WHERE id = ?" if text.isdigit()
             else "SELECT * FROM cat_works WHERE work_key = ?"),
            (int(text) if text.isdigit() else text,)).fetchone()
        if row:
            return row
    if work_key not in (None, ""):
        row = conn.execute("SELECT * FROM cat_works WHERE work_key = ?",
                           (str(work_key).strip(),)).fetchone()
        if row:
            return row
    for candidate in (slug, url):
        if candidate in (None, ""):
            continue
        text = str(candidate).strip()
        # An exact page URL is the cheap, unambiguous case; a bare slug is matched on
        # the trailing path segment, shortest page URL first, so a category or index
        # page can never shadow the real post. `cat_works` has no slug column, so the
        # only durable place a slug exists is the tail of `cat_work_sites.page_url` —
        # tried with and without the trailing slash production scrapers keep adding.
        row = conn.execute(
            "SELECT w.* FROM cat_works w JOIN cat_work_sites s ON s.work_id = w.id"
            " WHERE s.page_url = ? OR s.page_url = ? LIMIT 1",
            (text, text.rstrip("/") + "/")).fetchone()
        if row is None:
            tail = "/" + text.strip("/")
            row = conn.execute(
                "SELECT w.* FROM cat_works w JOIN cat_work_sites s ON s.work_id = w.id"
                " WHERE s.page_url LIKE ? OR s.page_url LIKE ?"
                " ORDER BY LENGTH(s.page_url) LIMIT 1",
                (f"%{tail}", f"%{tail}/")).fetchone()
        if row:
            return row
        if text.isdigit():
            row = conn.execute("SELECT * FROM cat_works WHERE id = ?",
                               (int(text),)).fetchone()
            if row:
                return row
    return None


@public_edge
def work_detail(conn, *, work_id=None, work_key=None, slug=None, url=None,
                include_adult=False, fields=None, include_provenance=False) -> dict:
    """The full nested catalog answer for one work.

    Shape: identity (imdb/tmdb/tvdb + aliases), seasons -> episodes
    (each with `absolute_number`, `best_release_id`, `quality_options`, covering
    prints), parts (from `cat_parts` when the projector fills it, otherwise inferred
    from print labels and explicitly marked `inferred`), `print_groups` with
    `coverage_type` and every print's links ordered by `rank_score`, entitlement,
    availability, and flags (`identity_suspect` is surfaced, never silently merged).

    Which site a title came from, and the page it was scraped from, are not part of
    this shape: `include_provenance=True` (operator port only) puts them back under
    `provenance`. A public caller has no way to ask for that key.
    """
    _require_row_factory(conn)
    _register_udfs(conn)
    work_row = _resolve_work(conn, work_id=work_id, work_key=work_key, slug=slug, url=url)
    if work_row is None:
        return _not_found(_NOT_FOUND_WORK)
    work = _as_dict(work_row)
    if not include_adult and int(work.get("is_18_plus") or 0):
        return _not_found(_NOT_FOUND_WORK)
    wid = int(work["id"])

    release_rows = conn.execute(
        "SELECT * FROM cat_releases WHERE work_id = ?"
        " ORDER BY quality_score DESC, official_print DESC, id ASC", (wid,)).fetchall()
    release_ids = [row["id"] for row in release_rows]
    links_by_release = _ordered_links(conn, release_ids)
    prints = [_print_view(conn, row, links_by_release) for row in release_rows]
    print_index = {p["release_id"]: p for p in prints}

    episodes_by_season: dict[int, list[dict]] = {}
    covering_by_episode: dict[int, list[int]] = {}
    ep_rows = conn.execute(
        """
        SELECT e.*, s.number AS season_number FROM cat_episodes e
        JOIN cat_seasons s ON s.id = e.season_id WHERE e.work_id = ?
        ORDER BY s.number, e.number
        """, (wid,)).fetchall()
    materialised = conn.execute(
        """
        SELECT re.episode_id, re.release_id, re.ordinal, re.offset_seconds, re.chapter_title
        FROM cat_release_episodes re JOIN cat_episodes e ON e.id = re.episode_id
        WHERE e.work_id = ? ORDER BY re.episode_id, re.ordinal
        """, (wid,)).fetchall()
    for row in materialised:
        covering_by_episode.setdefault(row["episode_id"], []).append(row["release_id"])

    for row in ep_rows:
        ep = _as_dict(row)
        covers = covering_by_episode.get(ep["id"], [])
        quality_options = sorted({print_index[cid]["resolution"] for cid in covers
                                  if cid in print_index}, reverse=True)
        episodes_by_season.setdefault(int(ep.get("season_number") or 0), []).append({
            "id": ep["id"],
            "number": ep["number"],
            "absolute_number": ep["absolute_number"],
            "season_number": ep.get("season_number"),
            "title": ep.get("title"),
            "air_date": ep.get("air_date"),
            "runtime_minutes": ep.get("runtime_minutes"),
            "best_release_id": ep.get("best_release_id"),
            "print_ids": sorted(set(covers)),
            "print_labels": [print_index[cid]["print_label"] for cid in sorted(set(covers))
                             if cid in print_index],
            "quality_options": quality_options,
            "print_count": len(set(covers)),
        })

    season_rows = conn.execute(
        "SELECT * FROM cat_seasons WHERE work_id = ? ORDER BY number", (wid,)).fetchall()
    seasons = []
    for row in season_rows:
        season = _as_dict(row)
        number = int(season["number"])
        seasons.append({
            "id": season["id"],
            "number": number,
            "season_type": season.get("season_type"),
            "title": season.get("title"),
            "episode_count": season.get("episode_count"),
            "enumerated_episode_count": len(episodes_by_season.get(number, [])),
            "episodes": episodes_by_season.get(number, []),
            "print_ids": sorted({p["release_id"] for p in prints
                                 if p["coverage"]["season_number"] == number}),
            # A season with no enumerated episodes but a season_pack print is real
            # and playable — do not report it as empty.
            "pack_only": (not episodes_by_season.get(number, [])) and any(
                p["coverage"]["season_number"] == number
                and p["coverage"]["type"] in ("season_pack", "episode_range") for p in prints),
        })

    parts = _parts_for_work(conn, work, prints)
    alias_rows = conn.execute(
        "SELECT alias, locale, source_site, kind FROM cat_work_aliases WHERE work_id = ?"
        " ORDER BY alias", (wid,)).fetchall()
    aliases = [{"alias": redact.scrub_text(row["alias"]), "locale": row["locale"],
                "kind": row["kind"]} for row in alias_rows]
    reviews = conn.execute(
        "SELECT id, kind, release_id, page_url, detail, raised_at FROM cat_review_queue"
        " WHERE work_id = ? AND resolved_at IS NULL ORDER BY id", (wid,)).fetchall()
    entitlements = conn.execute(
        "SELECT * FROM cat_entitlements WHERE work_id = ?"
        " ORDER BY (release_id IS NOT NULL), id", (wid,)).fetchall()

    streamable = [p for p in prints if (p["counts"]["streamable"] or 0) > 0]
    downloadable = [p for p in prints if (p["counts"]["downloadable"] or 0) > 0]
    # `unavailable` means "every link we recorded is dead", never "hide it": the work
    # stays listed with its prints and dead links so healing is auditable (§6 row 13).
    all_links = [link for p in prints for link in p["links"]]
    dead_only = bool(all_links) and all(link["dead"] for link in all_links)

    payload = {
        "ok": True,
        "work": {
            "id": work["id"],
            "title": redact.scrub_text(work["title"]),
            "original_title": _text(work.get("original_title")),
            "year": work.get("year"),
            "work_type": work.get("work_type"),
            "animated": bool(work.get("is_animated")),
            "synopsis": work.get("synopsis"),
            "genres": _json_list(work.get("genres")),
            "languages": _json_list(work.get("languages")),
            "country": work.get("country"),
            "industry": work.get("industry"),
            "rating": work.get("imdb_rating"),
            "runtime_minutes": work.get("runtime_minutes"),
            "images": _images(work),
            "site_count": work.get("site_count"),
            "print_count": len(prints),
            "episode_count": work.get("episode_count"),
            "season_count": len(seasons),
            "quality_max": work.get("max_resolution") or "unknown",
            "best_quality_score": work.get("best_quality_score"),
            "first_seen_at": work.get("first_seen_at"),
            "updated_at": work.get("updated_at"),
            "source_rev": work.get("source_rev"),
        },
        "identity": {
            "imdb_id": work.get("imdb_id"),
            "tmdb_id": work.get("tmdb_id"),
            "tvdb_id": work.get("tvdb_id"),
            "work_type": work.get("work_type"),
            "title_variants": aliases,
        },
        "seasons": seasons,
        "parts": parts,
        "prints": prints,
        "print_groups": _group_prints(prints, parts, seasons),
        "availability": {
            "stream": bool(streamable),
            "download": bool(downloadable),
            "any": bool(streamable or downloadable),
            "state": "unavailable" if (dead_only or not (streamable or downloadable)) else "available",
            "print_count": len(prints),
            "streamable_print_count": len(streamable),
            "downloadable_print_count": len(downloadable),
            "link_total": sum(p["counts"]["links"] or 0 for p in prints),
            "dead_link_total": sum(1 for p in prints for link in p["links"] if link["dead"]),
        },
        "entitlements": [_entitlement_view(row) for row in entitlements],
        "flags": _detail_flags(work, prints, reviews, dead_only),
        "identity_suspect": bool(work.get("identity_suspect")),
        "review_queue": [{"id": row["id"], "kind": row["kind"], "release_id": row["release_id"],
                          "detail": _text(row["detail"]), "raised_at": row["raised_at"]}
                         for row in reviews],
        "scope_unresolved_prints": [
            {"release_id": p["release_id"], "label": _text(p["label"]),
             "coverage_type": p["coverage"]["type"], "print_label": p["print_label"],
             "quality_score": p["quality_score"],
             "reason": ("unknown_coverage_type"
                        if p["coverage"]["type"] not in COVERAGE_TYPES
                        else "season_unresolved")}
            for p in prints
            if p["coverage"]["type"] not in COVERAGE_TYPES
            or (str(work.get("work_type")) in ("series", "anime")
                and p["coverage"]["type"] in ("season_pack", "episode_range", "parts")
                and p["coverage"]["season_number"] is None)
        ],
    }
    if include_provenance:
        # Operator surface only (loopback port): which site, which page, which title
        # we scraped it from. Never reachable from a public response, because the
        # public server does not set the operator flag.
        sites = conn.execute(
            """
            SELECT source_site, post_id, page_url, page_title, page_content_type, last_seen_at
            FROM cat_work_sites WHERE work_id = ? ORDER BY source_site, page_url
            """, (wid,)).fetchall()
        payload["provenance"] = {
            "work_key": work["work_key"],
            "canonical_key": work["work_key"],
            "sites": [_as_dict(row) for row in sites],
            "title_variant_sources": [{"alias": row["alias"], "source_site": row["source_site"]}
                                       for row in alias_rows],
            "review_page_urls": [{"id": row["id"], "page_url": row["page_url"]}
                                 for row in reviews],
        }
    if fields:
        payload = _project_fields(payload, fields)
    return payload


def _detail_flags(work: dict, prints: list[dict], reviews, dead_only: bool) -> list[str]:
    flags: list[str] = []
    if work.get("identity_suspect"):
        flags.append("identity_suspect")
    if reviews:
        flags.append("needs_review")
    if any(p["watermarked"] for p in prints):
        flags.append("watermarked_print")
    if any(not p["official_print"] for p in prints):
        flags.append("unofficial_print")
    if any(not p["official_print"] and str(p["source_tag"]).lower() in _CAM_TAGS
           for p in prints):
        flags.append("cam_print_present")
    if dead_only:
        flags.append("all_links_dead")
    if not any((p["counts"]["streamable"] or 0) > 0 for p in prints):
        flags.append("no_streamable_print")
    if not any((p["counts"]["downloadable"] or 0) > 0 for p in prints):
        flags.append("no_downloadable_print")
    return flags


def _parts_for_work(conn, work: dict, prints: list[dict]) -> list[dict]:
    """Multi-part films. `cat_parts` is the authoritative source; the projector does
    not fill it today, so sibling whole_work prints whose label names a part are
    reported as parts with `inferred: true` instead of being merged into one item.
    """
    out: list[dict] = []
    if _has_table(conn, "cat_parts"):
        rows = conn.execute(
            "SELECT id, number, title FROM cat_parts WHERE work_id = ? ORDER BY number",
            (work["id"],)).fetchall()
        for row in rows:
            linked = [p["release_id"] for p in prints
                      if p["coverage"].get("part_number") == row["number"]]
            out.append({"id": row["id"], "number": row["number"], "title": row["title"],
                        "inferred": False, "source": "cat_parts", "print_ids": linked})
    if out:
        return out
    seen: dict[int, dict] = {}
    for p in prints:
        match = _PART_RE.search(str(p.get("label") or ""))
        if not match:
            continue
        number = int(match.group(1))
        entry = seen.setdefault(number, {"number": number, "title": None,
                                        "inferred": True, "source": "print_label",
                                        "print_ids": []})
        entry["print_ids"].append(p["release_id"])
        if entry["title"] is None:
            entry["title"] = str(p.get("label") or "").strip() or None
    if len(seen) > 1:
        return [seen[key] for key in sorted(seen)]
    return out


def _group_prints(prints: list[dict], parts: list[dict], seasons: list[dict]) -> list[dict]:
    """Editions/scope are grouped, never interleaved (API_V2.md §3 rule 3)."""
    groups: dict[tuple, dict] = {}
    for entry in prints:
        cov = entry["coverage"]
        key = (str(cov["type"]), int(cov["season_number"] or 0),
               int(cov["part_number"] or 0), str(entry["edition"] or "unknown"))
        group = groups.setdefault(key, {
            "scope": {"coverage_type": cov["type"],
                      "season_number": cov["season_number"],
                      "part_number": cov["part_number"],
                      "edition": entry["edition"]},
            "print_ids": [], "prints": [],
        })
        group["print_ids"].append(entry["release_id"])
        group["prints"].append(entry)
    ordered = []
    for key in sorted(groups, key=lambda k: (k[1], k[2], k[0], k[3])):
        group = groups[key]
        group["prints"].sort(key=lambda p: (-(p["quality_score"] or 0), p["release_id"]))
        group["print_ids"] = [p["release_id"] for p in group["prints"]]
        group["best_release_id"] = group["print_ids"][0] if group["print_ids"] else None
        ordered.append(group)
    return ordered


def _project_fields(payload: dict, fields) -> dict:
    wanted = set()
    items = (fields if isinstance(fields, (list, tuple))
             else [f for f in re.split(r"[,\s]+", str(fields)) if f])
    for item in items:
        text = str(item).strip()
        if text:
            wanted.add(text)
    if not wanted:
        return payload
    out = {"ok": True, "meta": {k: v for k, v in payload.items()
                                if k in ("id", "updated_at", "source_rev")}}
    for key in wanted:
        if key == "prints":
            out["prints"] = [{f: p[f] for f in p
                              if f in wanted | {"release_id", "print_label", "quality_score",
                                                "coverage", "links"}} for p in payload["prints"]]
        elif key in payload:
            out[key] = payload[key]
    out.setdefault("id", payload["work"]["id"])
    return out


# ── season / episode / release singletons ────────────────────────────────────

@public_edge
def season_detail(conn, *, work_id, season_number, include_adult=False) -> dict:
    """One season plus its episodes with the per-episode best print."""
    detail = work_detail(conn, work_id=work_id, include_adult=include_adult)
    if not detail.get("ok"):
        return detail
    for season in detail["seasons"]:
        if season["number"] == int(season_number):
            return {"ok": True, "work_id": detail["work"]["id"],
                    "work_title": detail["work"]["title"], "season": season,
                    "prints": [p for p in detail["prints"]
                               if (p["coverage"]["season_number"] or 0) == int(season_number)]}
    return _not_found("Season not found")


@public_edge
def episode_detail(conn, *, episode_id, include_adult=False) -> dict:
    """One episode: prints, coverage, offsets, links (Layer-1 view)."""
    _require_row_factory(conn)
    _register_udfs(conn)
    try:
        target_id = int(episode_id)
    except (TypeError, ValueError):
        return _bad_input("episode_id must be an integer")
    row = conn.execute(
        """
        SELECT e.*, s.number AS season_number, w.is_18_plus, w.work_key,
               w.title AS work_title, w.work_type, w.year
        FROM cat_episodes e
        JOIN cat_seasons s ON s.id = e.season_id
        JOIN cat_works w ON w.id = e.work_id WHERE e.id = ?
        """, (target_id,)).fetchone()
    if row is None or ((row["is_18_plus"] or 0) and not include_adult):
        return _not_found("Episode not found")
    episode = _as_dict(row)
    work = {"id": episode["work_id"], "work_key": episode["work_key"],
            "title": episode["work_title"], "work_type": episode["work_type"]}
    prints, unresolved = _covering_prints(
        conn, work=work, season_number=episode["season_number"],
        episode_number=episode["number"], episode_id=episode["id"])
    release_ids = [p["release_id"] for p in prints + unresolved]
    links_by_release = _ordered_links(conn, release_ids)
    releases = _release_map(conn, int(work["id"]))
    served = []
    for entry in prints:
        release = releases.get(entry["release_id"])
        if release is None:
            continue
        served.append(_merge_print(entry, _print_view(conn, release, links_by_release)))
    return {
        "ok": True,
        "episode": {
            "id": episode["id"], "work_id": episode["work_id"],
            "work_title": episode["work_title"],
            "season_number": episode["season_number"], "number": episode["number"],
            "absolute_number": episode["absolute_number"], "title": episode.get("title"),
            "air_date": episode.get("air_date"), "runtime_minutes": episode.get("runtime_minutes"),
            "best_release_id": episode.get("best_release_id"),
        },
        "prints": served,
        "print_count": len(served),
        "scope_unresolved_prints": unresolved,
    }


def _merge_print(coverage_entry: dict, print_view: dict) -> dict:
    """Coverage facts (which episode, at what offset) over the full print shape."""
    out = dict(print_view)
    for key in ("match_kind", "ordinal", "offset_seconds", "chapter_title",
                "needs_offset_calibration", "pack_warning", "offset_confirmed_by",
                "offset_source", "coverage_type", "season_number"):
        out[key] = coverage_entry.get(key)
    return out


@public_edge
def release_detail(conn, *, release_id, include_adult=False) -> dict:
    """One print: descriptor, ranked links, coverage."""
    _require_row_factory(conn)
    _register_udfs(conn)
    rid = int(release_id) if str(release_id).strip().lstrip("-").isdigit() else -1
    row = conn.execute(
        """
        SELECT r.*, w.is_18_plus, w.work_key, w.title AS work_title, w.work_type,
               w.year FROM cat_releases r JOIN cat_works w ON w.id = r.work_id
        WHERE r.id = ?
        """, (rid,)).fetchone()
    if row is None or ((row["is_18_plus"] or 0) and not include_adult):
        return _not_found(_NOT_FOUND_RELEASE)
    release = _as_dict(row)
    links_by_release = _ordered_links(conn, [release["id"]])
    print_view = _print_view(conn, row, links_by_release)
    episodes = conn.execute(
        """
        SELECT e.id, e.number, e.absolute_number, re.ordinal, re.offset_seconds,
               re.chapter_title, s.number AS season_number
        FROM cat_release_episodes re JOIN cat_episodes e ON e.id = re.episode_id
        JOIN cat_seasons s ON s.id = e.season_id
        WHERE re.release_id = ? ORDER BY re.ordinal, e.number
        """, (release["id"],)).fetchall()
    lo, hi = _episode_range_bounds(release.get("episode_range") or release.get("label") or "")
    return {
        "ok": True,
        "print": print_view,
        "print_label": print_view["print_label"],
        "work": {"id": release["work_id"],
                 "title": release["work_title"], "work_type": release["work_type"],
                 "year": release["year"]},
        "coverage": {
            "type": release.get("coverage_type"),
            "season_number": release.get("season_number"),
            "part_number": release.get("part_number"),
            "episode_range": release.get("episode_range") or None,
            "episode_first": lo or None,
            "episode_last": hi or None,
            "enumerated_episodes": [
                {"episode_id": row["id"], "number": row["number"],
                 "absolute_number": row["absolute_number"],
                 "season_number": row["season_number"], "ordinal": row["ordinal"],
                 "offset_seconds": row["offset_seconds"], "chapter_title": row["chapter_title"]}
                for row in episodes],
        },
        "descriptor_json": _maybe_json(release.get("descriptor_json")),
    }


def _maybe_json(value):
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


# ── episode manifest ─────────────────────────────────────────────────────────

@public_edge
def episode_manifest(conn, *, work_id=None, work_key=None, slug=None, season=None,
                     episode=None, absolute=None, include_adult=False) -> dict:
    """Every print that covers one episode, with the offset a client needs.

    Addressing modes (the mode actually used is echoed back in `target.resolved_by`):
      * `season=S` + `episode=E` -> the `cat_episodes` row for that pair
      * `absolute=N`            -> `cat_episodes.absolute_number` (dubbed/anime order)
      * `episode=E` only         -> allowed when the work has exactly one season
      * `season=S` only          -> the whole-season prints (packs and season-stamped
                                    `whole_work` files), not every per-episode print
      * nothing, on a movie      -> the whole work itself
    A `season_pack` print is enumerated by design with **no** `cat_release_episodes`
    rows, so an episode that lives only inside a pack still resolves: the pack comes
    back with `needs_offset_calibration` and `pack_warning` instead of a false
    "not found", with `offset_seconds`/`chapter_title` taken from `cat_offsets` when an
    operator or client has already calibrated it.
    """
    _require_row_factory(conn)
    _register_udfs(conn)
    row = _resolve_work(conn, work_id=work_id, work_key=work_key, slug=slug)
    if row is None:
        return _not_found(_NOT_FOUND_WORK)
    work = _as_dict(row)
    if not include_adult and int(work.get("is_18_plus") or 0):
        return _not_found(_NOT_FOUND_WORK)

    family = catalog_v2.work_family(str(work.get("work_type") or "unknown"))
    season_given = season not in (None, "")
    episode_given = episode not in (None, "")
    absolute_given = absolute not in (None, "")
    episode_row = None

    if absolute_given:
        resolved_by = "absolute"
        episode_row = conn.execute(
            "SELECT * FROM cat_episodes WHERE work_id = ? AND absolute_number = ?",
            (int(work["id"]), int(absolute))).fetchone()
        if episode_row is not None:
            srow = conn.execute("SELECT number FROM cat_seasons WHERE id = ?",
                                (episode_row["season_id"],)).fetchone()
            season_number = int(srow["number"]) if srow else 0
            episode_number = int(episode_row["number"])
        else:
            # An absolute index the projector never enumerated still has to be
            # answerable: a season pack covering it is a legitimate rendition, so we
            # resolve at season 0 and let pack/whole_work prints match structurally.
            season_number, episode_number = int(season or 0), int(absolute)
    elif episode_given:
        resolved_by = "season_episode"
        if season_given:
            season_number = int(season)
        else:
            # "Episode 25 of this show" is only unambiguous when the work has one
            # season. Season membership comes from `cat_seasons`, not from the
            # enumerated episodes: a season that exists only as a pack, or one the
            # projector refused to enumerate past the cap, still has exactly one season.
            season_rows = conn.execute(
                "SELECT number FROM cat_seasons WHERE work_id = ? ORDER BY number",
                (int(work["id"]),)).fetchall()
            numbers = sorted({int(row["number"]) for row in season_rows})
            if len(numbers) == 1:
                season_number = numbers[0]
            elif not numbers and family == "movie":
                season_number = 0
            else:
                return _bad_input("season is required when the work has more than one season")
        episode_number = int(episode)
        episode_row = _find_episode(conn, work_id=int(work["id"]),
                                    season_number=season_number,
                                    episode_number=episode_number, absolute=None)
    elif season_given:
        resolved_by = "season"
        season_number, episode_number = int(season), 0
    else:
        if family != "movie":
            return _bad_input("episode_manifest needs season+episode, absolute, or season")
        resolved_by = "whole_work"
        season_number, episode_number = 0, 1
        episode_row = _find_episode(conn, work_id=int(work["id"]), season_number=0,
                                    episode_number=1, absolute=None)

    episode_id = int(episode_row["id"]) if episode_row is not None else None
    prints, unresolved = _covering_prints(
        conn, work=work, season_number=season_number, episode_number=episode_number,
        episode_id=episode_id)
    release_ids = [p["release_id"] for p in prints]
    links_by_release = _ordered_links(conn, release_ids + [p["release_id"] for p in unresolved])
    releases = _release_map(conn, int(work["id"]))
    served = []
    for entry in prints:
        release = releases.get(entry["release_id"])
        if release is None:
            continue
        view = _print_view(conn, release, links_by_release)
        best_link = view["links"][0] if view["links"] else None
        served.append({
            **_merge_print(entry, view),
            "rank": len(served) + 1,
            "best_link_id": best_link["link_id"] if best_link else None,
            "playable": bool(best_link and best_link["group"] in
                             (_GROUP_STREAMABLE, _GROUP_RESOLVE) and not best_link["dead"]),
            "streamable_count": view["counts"]["streamable"],
            "downloadable_count": view["counts"]["downloadable"],
            "dead_links": sum(1 for link in view["links"] if link["dead"]),
        })
    for entry in unresolved:
        entry["scope_note"] = ("Kept visible per the zero-data-loss rule, but the"
                               " projector could not resolve which season this print is in.")
    return {
        "ok": True,
        "work_id": work["id"],
        "work_title": work["title"],
        "work_type": work.get("work_type"),
        "target": {
            "resolved_by": resolved_by,
            "season": season_number,
            "episode": episode_number,
            "absolute": (episode_row["absolute_number"] if episode_row and
                         episode_row["absolute_number"] is not None
                         else (int(absolute) if absolute not in (None, "") else None)),
            "episode_id": episode_id,
            "enumerated": episode_id is not None,
        },
        "prints": served,
        "print_count": len(served),
        "scope_unresolved_prints": unresolved,
        "identity_suspect": bool(work.get("identity_suspect")),
        "needs_offset_calibration": any(p["needs_offset_calibration"] for p in served),
        "playable": any(p["playable"] for p in served),
    }


# ── play bundle ──────────────────────────────────────────────────────────────

@public_edge
def play_bundle(conn, *, release_id, episode_id=None, include_adult=False) -> dict:
    """Ordered failover candidates for one print (optionally for one episode of it).

    Order: streamable best-first (rank_score), then alternates, then links needing a
    resolve step, then webview-only embeds, then downloads, then bridges/dead ends —
    a dead link is never hidden, it is ranked last with `state` set so the client can
    still see it (zero data loss). Every candidate carries the measured
    speed/latency/status when `cat_link_evidence` has a probe for it.
    """
    _require_row_factory(conn)
    _register_udfs(conn)
    detail = release_detail(conn, release_id=release_id, include_adult=include_adult)
    if not detail.get("ok"):
        return detail
    print_view = detail["print"]
    work = detail["work"]
    # The offset tables are keyed by our own work_key, which is deliberately not a
    # public field any more, so the ladder reads it straight from the row.
    key_row = conn.execute("SELECT work_key FROM cat_works WHERE id = ?",
                           (int(work["id"]),)).fetchone()
    work_key = str(key_row["work_key"]) if key_row else ""
    candidates = _sort_links(print_view["links"])
    for index, link in enumerate(candidates, start=1):
        link["rank"] = index
    coverage = detail["coverage"]
    offset_block = {"offset_seconds": None, "chapter_title": None, "ordinal": None,
                    "source": None, "needs_offset_calibration": False, "pack_warning": None}
    target = None
    if episode_id not in (None, ""):
        row = conn.execute(
            """
            SELECT e.id, e.number, e.absolute_number, s.number AS season_number, e.work_id
            FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id WHERE e.id = ?
            """, (int(episode_id),)).fetchone()
        if row is None or int(row["work_id"]) != int(work["id"]):
            return _not_found("Episode not found for this release")
        episode = _as_dict(row)
        material = conn.execute(
            "SELECT ordinal, offset_seconds, chapter_title FROM cat_release_episodes"
            " WHERE release_id = ? AND episode_id = ?",
            (int(print_view["release_id"]), int(episode["id"]))).fetchone()
        if material is not None:
            offset_block.update({
                "ordinal": material["ordinal"],
                "offset_seconds": material["offset_seconds"],
                "chapter_title": material["chapter_title"],
                "source": "cat_release_episodes",
            })
        if offset_block["offset_seconds"] is None:
            learned = _offset_lookup(conn, work_key=work_key,
                                     season_number=episode["season_number"],
                                     episode_number=episode["number"],
                                     release_label=str(print_view["label"] or ""))
            if learned:
                offset_block.update({
                    "offset_seconds": learned["offset_seconds"],
                    "chapter_title": learned["chapter_title"],
                    "ordinal": offset_block["ordinal"] or episode["number"],
                    "source": "cat_offsets",
                    "confirmed_by": learned["confirmed_by"],
                })
        if str(print_view["coverage"]["type"]) in ("season_pack", "parts") and (
                offset_block["offset_seconds"] is None):
            offset_block["needs_offset_calibration"] = True
            # The warning is about *this file*, so it names the season the print itself
            # was stamped with, not the season of the episode being asked for.
            pack_season = (print_view["coverage"]["season_number"]
                           or coverage["season_number"] or episode["season_number"])
            offset_block["pack_warning"] = (
                f"This file contains all of Season {pack_season}"
                if str(print_view["coverage"]["type"]) == "season_pack"
                else "This file contains multiple parts")
        target = {
            "kind": "episode", "episode_id": episode["id"],
            "work_id": work["id"], "release_id": print_view["release_id"],
            "work_type": work.get("work_type"), "season": episode["season_number"],
            "episode": episode["number"], "absolute": episode["absolute_number"],
        }
    else:
        target = {"kind": "release", "work_id": work["id"],
                  "release_id": print_view["release_id"], "season": coverage["season_number"],
                  "episode": None, "absolute": None}
        if coverage["type"] in ("season_pack", "parts"):
            offset_block["needs_offset_calibration"] = True
            offset_block["pack_warning"] = "This print covers more than one episode"

    stream_candidates = [l for l in candidates if l["group"] == _GROUP_STREAMABLE]
    alternates = [l for l in candidates if l["group"] in (_GROUP_RESOLVE, _GROUP_WEBVIEW)]
    download_options = [l for l in candidates
                        if l["group"] == _GROUP_DOWNLOAD or l["playability"] == "download"]
    playable = [l for l in candidates if not l["dead"] and l["group"] <= _GROUP_RESOLVE]
    protocol = None
    if stream_candidates:
        protocol = stream_candidates[0]["protocol"]
    # The quality switch and the download card: this print's copies collapsed to
    # one winner. The full ranked `candidates` stay for silent failover, which is
    # what makes showing the user a single option honest rather than fragile.
    ladder = tiers.for_release(
        {"quality": print_view.get("resolution") or print_view.get("quality_label"),
         "codec": print_view.get("codec"), "size": print_view.get("size_bytes")},
        candidates)
    for tier in ladder["tiers"]:
        # Same rule as the v1 ladder: the runner-ups leave as handles only, so a
        # silent failover never widens what one response discloses.
        backups = tier.pop("backups", None) or []
        tier["backup_handles"] = [str(item["stream_id"]) for item in backups
                                  if item.get("stream_id")]
    return {
        "ok": True,
        "target": target,
        "work_id": work["id"],
        "release_id": print_view["release_id"],
        "print_label": print_view["print_label"],
        "print": print_view,
        "tiers": ladder["tiers"],
        "auto": ladder["auto"],
        "coverage": {**coverage, **offset_block},
        "candidates": candidates,
        "stream_candidates": stream_candidates,
        "alternates": alternates,
        "download_options": download_options,
        "recommended_link_id": stream_candidates[0]["link_id"] if stream_candidates
        else (playable[0]["link_id"] if playable else None),
        "playable": bool(playable),
        "available": bool(candidates),
        # Explicit, non-404 shape when nothing plays (API_V2.md §6 row 13).
        "reason": None if playable else ("no_playable_source" if candidates else "no_source_recorded"),
        "tried": [{"link_id": link["link_id"], "state": link["state"],
                   "group": link["group"], "reason": (
                       "dead" if link["dead"] else f"playability_{link['playability']}")}
                  for link in candidates if link["dead"] or link["group"] > _GROUP_RESOLVE],
        "protocol": protocol,
        "ephemeral": bool(candidates and candidates[0]["ephemeral"]),
        "candidate_count": len(candidates),
        "dead_candidate_count": sum(1 for link in candidates if link["dead"]),
    }


# ── entitlements ─────────────────────────────────────────────────────────────

def _entitlement_view(row) -> dict:
    data = _as_dict(row) if not isinstance(row, dict) else dict(row)
    return {
        "id": data.get("id"),
        "work_id": data.get("work_id"),
        "release_id": data.get("release_id"),
        "model": data.get("model") or "unknown",
        "price": {"minor": data.get("price_minor"), "currency": data.get("currency")},
        "region": data.get("region"),
        "geo_allow": _json_list(data.get("geo_allow")),
        "geo_deny": _json_list(data.get("geo_deny")),
        "valid_from": data.get("valid_from"),
        "valid_until": data.get("valid_until"),
        "rental_hours": data.get("rental_hours"),
        "ownership": data.get("ownership") or "unknown",
        "requires_account": bool(data.get("requires_account")),
        "requires_age_gate": bool(data.get("requires_age_gate")),
        "updated_at": data.get("updated_at"),
    }


_PAID_MODELS = {"paid", "purchase", "rental", "subscription", "tvod", "ppv"}


@public_edge
def resolve_entitlement(conn, *, work_id=None, work_key=None, release_id=None,
                        principal=None, now=None, include_adult=False) -> dict:
    """Explicit licence decision from `cat_entitlements` — never allow-by-absence.

    `principal` may be None (anonymous), a string id, or a dict:
    ``{"id", "account": bool, "owns": bool|iterable_of_release_ids,
      "adult_ok": bool, "region": "IN"}``.
    The most specific applicable row wins (a release-scoped row beats a work-scoped
    one, `region`-specific beats global). When no row applies the decision is an
    explicit ``deny`` with reason ``no_entitlement_record`` — the caller must not
    treat a missing row as free.
    """
    _require_row_factory(conn)
    _register_udfs(conn)
    work_row = _resolve_work(conn, work_id=work_id, work_key=work_key)
    if work_row is None:
        return _not_found(_NOT_FOUND_WORK)
    work = _as_dict(work_row)
    if not include_adult and int(work.get("is_18_plus") or 0):
        return _not_found(_NOT_FOUND_WORK)
    moment = float(now if now not in (None, "") else time.time())
    # Copied, never mutated: `principal` belongs to the caller (viewer.py holds it).
    who = dict(principal) if isinstance(principal, dict) else (
        {"id": str(principal), "account": True} if principal else {})
    who.setdefault("account", bool(who.get("id")))

    scoped = conn.execute(
        "SELECT * FROM cat_entitlements WHERE work_id = :work"
        " AND (release_id IS NULL OR release_id = :rel)",
        {"work": int(work["id"]),
         "rel": (int(release_id) if release_id not in (None, "") else None)}).fetchall()
    rows = [_entitlement_view(row) for row in scoped]
    rows.sort(key=lambda item: (0 if item["release_id"] is not None else 1,
                                0 if (item["region"] or "") == str(who.get("region") or "") else 1,
                                item["id"] or 0))
    if not rows:
        return {
            "ok": True, "allowed": False, "decision": "deny",
            "reason": "no_entitlement_record",
            "message": "No entitlement row exists, so playback is not granted.",
            "work_id": work["id"], "release_id": release_id,
            "entitlement": None, "candidates": [], "checked_at": moment,
            "implicit": False,
        }

    for entry in rows:
        result = _evaluate(entry, who, work, moment, release_id)
        if result is not None:
            return result
    entry = rows[0]
    return {
        "ok": True, "allowed": False, "decision": "deny",
        "reason": "unknown_model", "work_id": work["id"],
        "release_id": entry["release_id"], "entitlement": entry,
        "candidates": rows, "checked_at": moment, "implicit": False,
        "message": f"Entitlement model '{entry['model']}' is not understood by this build",
    }


def _evaluate(entry: dict, who: dict, work: dict, moment: float, release_id) -> dict | None:
    base = {
        "ok": True, "work_id": work["id"], "release_id": entry["release_id"],
        "entitlement": entry, "checked_at": moment, "implicit": False,
        "requires_account": entry["requires_account"],
        "requires_age_gate": entry["requires_age_gate"],
    }
    model = str(entry.get("model") or "").strip().lower()
    if entry["release_id"] is not None:
        release_row_specified = release_id in (None, "", entry["release_id"])
        if not release_row_specified:
            return None
    if entry["requires_age_gate"] and not who.get("adult_ok"):
        return {**base, "allowed": False, "decision": "deny", "reason": "age_gate_required",
                "message": "This title requires an age gate before it may be played."}
    if entry["valid_from"] not in (None, "") and float(entry["valid_from"]) > moment:
        return {**base, "allowed": False, "decision": "deny", "reason": "not_yet_valid"}
    if entry["valid_until"] not in (None, "") and float(entry["valid_until"]) < moment:
        return {**base, "allowed": False, "decision": "deny", "reason": "expired",
                "message": "The licence window for this entitlement has closed."}
    region = str(who.get("region") or "").strip().upper()
    geo_allow = [str(g).strip().upper() for g in entry["geo_allow"]]
    geo_deny = [str(g).strip().upper() for g in entry["geo_deny"]]
    if geo_deny and region and region in geo_deny:
        return {**base, "allowed": False, "decision": "deny", "reason": "geo_denied"}
    if geo_allow and (not region or region not in geo_allow):
        return {**base, "allowed": False, "decision": "deny", "reason": "geo_required"}
    if entry["requires_account"] and not who.get("account"):
        return {**base, "allowed": False, "decision": "deny", "reason": "account_required"}
    if model in ("free", "ad_supported", "avod", ""):
        return {**base, "allowed": True, "decision": "allow",
                "reason": "free" if model != "" else "free_by_explicit_row",
                "ownership": entry["ownership"]}
    if model == "subscription":
        owned = who.get("subscription") or who.get("active_subscription")
        if owned:
            return {**base, "allowed": True, "decision": "allow", "reason": "subscribed",
                    "ownership": "until_expiry"}
        return {**base, "allowed": False, "decision": "licence_required",
                "reason": "subscription_required",
                "message": "A subscription is required before this title may be played."}
    if model in _PAID_MODELS:
        owns = who.get("owns")
        if owns is True:
            return {**base, "allowed": True, "decision": "allow", "reason": "purchased",
                    "ownership": entry["ownership"]}
        if isinstance(owns, (list, tuple, set, dict)) and entry["release_id"] is None:
            if int(work["id"]) in [int(v) for v in owns]:
                return {**base, "allowed": True, "decision": "allow", "reason": "purchased",
                        "ownership": entry["ownership"]}
        if isinstance(owns, (list, tuple, set, dict)):
            try:
                wanted = int(entry["release_id"] or 0)
            except (TypeError, ValueError):
                wanted = 0
            if wanted and wanted in [int(v) for v in owns]:
                return {**base, "allowed": True, "decision": "allow", "reason": "purchased",
                        "ownership": entry["ownership"]}
        return {**base, "allowed": False, "decision": "licence_required",
                "reason": "purchase_required",
                "price": entry["price"], "currency": entry["price"]["currency"],
                "rental_hours": entry["rental_hours"],
                "message": "This title is not free and no licence is held for it."}
    return None


# ── continue-watching target ─────────────────────────────────────────────────

@public_edge
def resolve_episode_target(conn, *, work_id=None, work_key=None, season=0, episode=None,
                           release_label="", include_adult=False) -> dict:
    """Where to seek when resuming episode N of the print used for episode N-1.

    The print label is the only stable handle a client has (release ids are rebuilt on
    every projection), so the lookup goes through `cat_offsets` keyed by
    (work_key, season_number, episode_number, release_label). An exact label match
    wins over a label-agnostic ('') offset; ties break on `confirmed_by` then recency.
    Falls back to the materialised `cat_release_episodes` row when the projector
    already carries a chapter for this print/episode pair.
    """
    _require_row_factory(conn)
    _register_udfs(conn)
    row = _resolve_work(conn, work_id=work_id, work_key=work_key)
    if row is None:
        return _not_found(_NOT_FOUND_WORK)
    work = _as_dict(row)
    if not include_adult and int(work.get("is_18_plus") or 0):
        return _not_found(_NOT_FOUND_WORK)
    if episode in (None, ""):
        return _bad_input("episode is required")
    season_number = int(season or 0)
    episode_number = int(episode)
    label = str(release_label or "")

    episode_row = _find_episode(conn, work_id=int(work["id"]), season_number=season_number,
                                episode_number=episode_number, absolute=None)
    release_row = None
    if label:
        release_row = conn.execute(
            "SELECT * FROM cat_releases WHERE work_id = ? AND label = ?"
            " ORDER BY quality_score DESC, id LIMIT 1",
            (int(work["id"]), label)).fetchone()
        if release_row is None:
            release_row = conn.execute(
                "SELECT * FROM cat_releases WHERE work_id = ? AND label LIKE ? ESCAPE '\\'"
                " ORDER BY quality_score DESC, id LIMIT 1",
                (int(work["id"]), "%" + label.replace("\\", "\\\\").replace("%", "\\%")
                 .replace("_", "\\_") + "%")).fetchone()
    materialised = None
    if episode_row is not None and release_row is not None:
        materialised = conn.execute(
            "SELECT ordinal, offset_seconds, chapter_title FROM cat_release_episodes"
            " WHERE release_id = ? AND episode_id = ?",
            (release_row["id"], episode_row["id"])).fetchone()
    learned = _offset_lookup(conn, work_key=str(work["work_key"]),
                             season_number=season_number, episode_number=episode_number,
                             release_label=label)
    offset_seconds = None
    chapter_title = None
    source = None
    if materialised is not None and (materialised["offset_seconds"] is not None
                                     or materialised["chapter_title"] is not None):
        offset_seconds = materialised["offset_seconds"]
        chapter_title = materialised["chapter_title"]
        source = "cat_release_episodes"
    elif learned is not None:
        offset_seconds = learned["offset_seconds"]
        chapter_title = learned["chapter_title"]
        source = ("cat_offsets:exact_label" if (learned["release_label"] or "") == label
                  else "cat_offsets:any_label")
        if label and (learned["release_label"] or "") != label:
            source = "cat_offsets:fallback_any_label"
    exact = bool(learned and (learned["release_label"] or "") == label)
    return {
        "ok": True,
        "work_id": work["id"],
        "target": {
            "season": season_number,
            "episode": episode_number,
            "episode_id": episode_row["id"] if episode_row is not None else None,
            "absolute_number": episode_row["absolute_number"] if episode_row is not None else None,
            "release_id": release_row["id"] if release_row is not None else None,
            "release_label": release_row["label"] if release_row is not None else (label or None),
            "coverage_type": release_row["coverage_type"] if release_row is not None else None,
        },
        "offset_seconds": offset_seconds,
        "chapter_title": chapter_title,
        "source": source,
        "confirmed_by": learned["confirmed_by"] if (learned and exact) else (
            learned["confirmed_by"] if learned else 0),
        "label_matched": exact,
        "found": offset_seconds is not None or chapter_title is not None,
        "needs_calibration": (offset_seconds is None
                              and (release_row is None or str(release_row["coverage_type"])
                                   in ("season_pack", "parts"))),
    }


# ── catalog state / cache ────────────────────────────────────────────────────

@public_edge
def catalog_state(conn) -> dict:
    """Revision + counts + projector version for ETag / cache validation.

    Every count excludes adult works, so an ETag can never hint at hidden rows and a
    cached `browse` response is invalidated exactly when its own visible rows change.
    """
    _require_row_factory(conn)
    adult_sql = "COALESCE(w.is_18_plus, 0) = 0"
    rev_row = conn.execute("SELECT COALESCE(MAX(source_rev), 0) AS v FROM cat_works").fetchone()
    works = conn.execute(
        f"SELECT COUNT(*) AS n FROM cat_works w WHERE {adult_sql}").fetchone()["n"]
    releases = conn.execute(
        f"SELECT COUNT(*) AS n FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
        f" WHERE {adult_sql}").fetchone()["n"]
    links = conn.execute(
        f"SELECT COUNT(*) AS n FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
        f" WHERE {adult_sql}").fetchone()["n"]
    episodes = conn.execute(
        f"SELECT COUNT(*) AS n FROM cat_episodes e JOIN cat_works w ON w.id = e.work_id"
        f" WHERE {adult_sql}").fetchone()["n"]
    seasons = conn.execute(
        f"SELECT COUNT(*) AS n FROM cat_seasons s JOIN cat_works w ON w.id = s.work_id"
        f" WHERE {adult_sql}").fetchone()["n"]
    states = {row["state"]: row["n"] for row in conn.execute(
        "SELECT COALESCE(state, 'unknown') AS state, COUNT(*) AS n FROM cat_links GROUP BY state")}
    open_reviews = conn.execute(
        "SELECT COUNT(*) AS n FROM cat_review_queue WHERE resolved_at IS NULL").fetchone()["n"]
    offsets = conn.execute("SELECT COUNT(*) AS n FROM cat_offsets").fetchone()["n"] if _has_table(
        conn, "cat_offsets") else 0
    counts = {
        "works": works, "prints": releases, "links": links, "episodes": episodes,
        "seasons": seasons, "link_states": states, "open_review_queue": open_reviews,
        "offsets": offsets,
        "last_projection": {key: _meta_value(conn, key) for key in
                            ("works", "releases", "links", "episodes", "posts",
                             "identity_suspect", "release_dups", "unattributed_links")},
    }
    projector_version = _meta_value(conn, "schema_version")
    projected_at = _meta_value(conn, "projected_at")
    payload = json.dumps({"rev": int(rev_row["v"]), "counts": counts,
                          "projector_version": projector_version,
                          "projected_at": projected_at}, sort_keys=True, default=str)
    return {
        "ok": True,
        "rev": int(rev_row["v"]),
        "counts": counts,
        "projector_version": int(projector_version) if (projector_version or "").isdigit() else None,
        "schema_version": catalog_v2.SCHEMA_VERSION,
        "projected_at": float(projected_at) if projected_at else None,
        "etag": '"' + hashlib.sha1(payload.encode("utf-8")).hexdigest() + '"',
        "adult_hidden_by_policy": True,
        "generated_at": time.time(),
    }


__all__ = [
    "browse", "search", "suggest", "work_detail", "season_detail", "episode_detail",
    "release_detail", "episode_manifest", "play_bundle", "resolve_entitlement",
    "resolve_episode_target", "catalog_state", "print_label", "normalize_text",
    "encode_cursor", "decode_cursor", "SORT_KEYS", "COVERAGE_TYPES", "DEFAULT_LIMIT",
    "MAX_LIMIT",
]
