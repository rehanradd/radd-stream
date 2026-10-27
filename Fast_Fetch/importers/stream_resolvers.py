#!/usr/bin/env python3
"""
stream_resolvers.py — embed-resolver adapters for playback fallback.

This module does **not** scrape a catalog and never creates posts. It turns a
TMDB/IMDb identity into the documented embed URL of four public resolver
front-ends, so the Android client can fall back to one when a catalog work has
no stored stream:

    vidsrc       https://vidsrc.sh/        (the domain that replaced vidsrc.me)
    superembed   https://superembed.stream/
    vidlink      https://vidlink.pro/
    2embed       https://www.2embed.cc/

Everything is pure Python standard library. The only writable location is
``/home/ubuntu/radd-stream-data/resolvers.db``, which holds capability metadata
and probe results — never catalog content (no titles, no synopses, no release
labels). The merged catalog is opened read-only, and only to count how many
works carry a usable external id.

Status vocabulary matches ``import_pagalmovies.py``: ``active`` / ``dead`` /
``blocked`` / ``error`` / ``unknown``. ``playback_type`` is always ``embed``
because every URL here is an HTML player page, not a media file.

A probe proves the *front-end* answered, not that a title is playable: these
sites return a 200 player shell for ids they do not know. That distinction is
recorded in ``resolvers.notes`` rather than hidden.

CLI
    python3 -S Fast_Fetch/importers/stream_resolvers.py providers
    python3 -S Fast_Fetch/importers/stream_resolvers.py urls --tmdb 27205 --kind movie
    python3 -S Fast_Fetch/importers/stream_resolvers.py probe --tmdb 27205 --imdb tt1375666
    python3 -S Fast_Fetch/importers/stream_resolvers.py coverage
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path("/home/ubuntu/radd-stream-data")
DEFAULT_DB_PATH = DATA_DIR / "resolvers.db"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
PROBE_TIMEOUT = 15
BODY_SNIFF_BYTES = 4096

# Live verification, 2026-10-28, one movie (TMDB 27205 / tt1375666) and one
# episode (TMDB 1396 / tt0903747 S1E1) per provider, GET only. See `notes`.
VERIFIED_AT = "2026-10-28"

PROVIDERS = {
    "vidsrc": {
        "base_url": "https://vidsrc.sh",
        "kinds": ["movie", "tv"],
        "id_types": ["tmdb", "imdb"],
        "notes": (
            "TMDB: /embed/movie/{tmdb} and /embed/tv/{tmdb}/{season}/{episode}. "
            "IMDb (vidsrc.me lineage): /embed/movie?imdb={tt} and "
            "/embed/tv?imdb={tt}&season={s}&episode={e}. "
            f"Live GET {VERIFIED_AT}: movie 200, tv 200 (HTML player shell). "
            "A 200 does not prove the id resolves to a playable stream."
        ),
    },
    "superembed": {
        "base_url": "https://multiembed.mov",
        "kinds": ["movie", "tv"],
        "id_types": ["imdb", "tmdb"],
        "notes": (
            "BLOCKER / MOVED: superembed.stream's old paths /movie/{tt} and "
            "/tv/{tt}/{s}/{e} return 404 (verified 2026-10-28). Its own docs now "
            "publish the player host multiembed.mov with query args: "
            "/?video_id={tt}, /?video_id={tmdb}&tmdb=1, episode adds &s=&e=. "
            "Direct browserless GET to multiembed.mov returns 403 (bot/geo gate); "
            "not bypassed. URL shape follows the published docs; a WebView client "
            "with a normal origin may still load it. Status recorded as blocked."
        ),
    },
    "vidlink": {
        "base_url": "https://vidlink.pro",
        "kinds": ["movie", "tv"],
        "id_types": ["tmdb"],
        "notes": (
            "TMDB only, as documented: /movie/{tmdb} and "
            "/tv/{tmdb}/{season}/{episode}. No documented IMDb path. "
            f"Live GET {VERIFIED_AT}: movie 200, tv 200 (HTML player shell)."
        ),
    },
    "2embed": {
        "base_url": "https://www.2embed.cc",
        "kinds": ["movie", "tv"],
        "id_types": ["tmdb", "imdb"],
        "notes": (
            "TMDB: /embed/{tmdb} and /embedtv/{tmdb}&s={s}&e={e} (the TV path "
            "uses '&', not a path segment). IMDb: /embed/imdb/movie?id={tt} and "
            "/embed/imdb/tv?id={tt}&s={s}&e={e}. "
            f"Live GET {VERIFIED_AT}: movie 200, tv 200 (HTML player shell)."
        ),
    },
}

PROVIDER_ORDER = ("vidsrc", "superembed", "vidlink", "2embed")

# ---------------------------------------------------------------------------
# Identity normalisation — "unknown id" means malformed, never guessed
# ---------------------------------------------------------------------------

TMDB_RE = re.compile(r"^\d{1,9}$")
IMDB_RE = re.compile(r"^tt\d{7,9}$", re.I)
KINDS = ("movie", "tv")


def normalize_tmdb(tmdb_id) -> int | None:
    """Returns a positive TMDB id, or None when the value is not one."""
    if tmdb_id is None or isinstance(tmdb_id, bool):
        return None
    text = str(tmdb_id).strip()
    if not TMDB_RE.fullmatch(text):
        return None
    value = int(text)
    return value if value > 0 else None


def normalize_imdb(imdb_id) -> str | None:
    """Returns a lowercase tt-id (7-9 digits), or None."""
    if imdb_id is None:
        return None
    text = str(imdb_id).strip()
    return text.lower() if IMDB_RE.fullmatch(text) else None


def normalize_episode_number(value, maximum: int = 9999) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    number = int(text)
    return number if 1 <= number <= maximum else None


# ---------------------------------------------------------------------------
# URL builders — one per provider, exactly the documented shape
# ---------------------------------------------------------------------------

def _vidsrc_url(kind: str, tmdb: int | None, imdb: str | None,
                season: int | None, episode: int | None) -> str | None:
    base = PROVIDERS["vidsrc"]["base_url"]
    if tmdb is not None:
        if kind == "movie":
            return f"{base}/embed/movie/{tmdb}"
        return f"{base}/embed/tv/{tmdb}/{season}/{episode}"
    if imdb is not None:
        if kind == "movie":
            return f"{base}/embed/movie?imdb={imdb}"
        return f"{base}/embed/tv?imdb={imdb}&season={season}&episode={episode}"
    return None


def _superembed_url(kind: str, tmdb: int | None, imdb: str | None,
                    season: int | None, episode: int | None) -> str | None:
    # superembed.stream moved its player to multiembed.mov and replaced path
    # segments with query args (?video_id=...&tmdb=1&s=..&e=..). IMDb is listed
    # first in its own docs, so it wins when both ids are present.
    base = PROVIDERS["superembed"]["base_url"]
    if imdb is not None:
        if kind == "movie":
            return f"{base}/?video_id={imdb}"
        return f"{base}/?video_id={imdb}&s={season}&e={episode}"
    if tmdb is not None:
        if kind == "movie":
            return f"{base}/?video_id={tmdb}&tmdb=1"
        return f"{base}/?video_id={tmdb}&tmdb=1&s={season}&e={episode}"
    return None


def _vidlink_url(kind: str, tmdb: int | None, imdb: str | None,
                 season: int | None, episode: int | None) -> str | None:
    base = PROVIDERS["vidlink"]["base_url"]
    if tmdb is None:  # TMDB is the only documented shape
        return None
    if kind == "movie":
        return f"{base}/movie/{tmdb}"
    return f"{base}/tv/{tmdb}/{season}/{episode}"


def _2embed_url(kind: str, tmdb: int | None, imdb: str | None,
                season: int | None, episode: int | None) -> str | None:
    base = PROVIDERS["2embed"]["base_url"]
    if tmdb is not None:
        if kind == "movie":
            return f"{base}/embed/{tmdb}"
        return f"{base}/embedtv/{tmdb}&s={season}&e={episode}"
    if imdb is not None:
        if kind == "movie":
            return f"{base}/embed/imdb/movie?id={imdb}"
        return f"{base}/embed/imdb/tv?id={imdb}&s={season}&e={episode}"
    return None


BUILDERS = {
    "vidsrc": _vidsrc_url,
    "superembed": _superembed_url,
    "vidlink": _vidlink_url,
    "2embed": _2embed_url,
}


def resolver_urls(tmdb_id=None, imdb_id=None, kind: str = "movie",
                  season=None, episode=None) -> list[dict]:
    """
    Builds one embed URL per capable provider.

    Returns ``[]`` when there is no usable id, when ``kind`` is not movie/tv,
    or when a TV request has no valid season/episode pair. Providers that do
    not accept the supplied id type are skipped — none is invented.

    Each item: ``{resolver, url, playback_type, status}`` with status
    ``unknown`` until :func:`validate` probes it.
    """
    tmdb = normalize_tmdb(tmdb_id)
    imdb = normalize_imdb(imdb_id)
    if tmdb is None and imdb is None:
        return []

    requested_kind = (kind or "").strip().lower()
    if requested_kind not in KINDS:
        return []

    season_number = episode_number = None
    if requested_kind == "tv":
        season_number = normalize_episode_number(season, maximum=999)
        episode_number = normalize_episode_number(episode, maximum=9999)
        if season_number is None or episode_number is None:
            return []

    out: list[dict] = []
    for name in PROVIDER_ORDER:
        provider = PROVIDERS[name]
        if requested_kind not in provider["kinds"]:
            continue
        url = BUILDERS[name](requested_kind, tmdb, imdb, season_number, episode_number)
        if not url:
            continue
        out.append({
            "resolver": name,
            "url": url,
            "playback_type": "embed",
            "status": "unknown",
        })
    return out


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

_OPENER = urllib.request.build_opener()
_OPENER.addheaders = [
    ("User-Agent", USER_AGENT),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "en-US,en;q=0.9"),
]


def _http_probe(url: str, timeout: int = PROBE_TIMEOUT):
    """One GET, redirects followed. Returns (code, final_url, body_sniff).

    Never raises: a transport failure is code 0, which classifies as ``error``.
    """
    try:
        response = _OPENER.open(url, timeout=timeout)
        body = response.read(BODY_SNIFF_BYTES).decode("utf-8", "replace")
        return getattr(response, "status", 200) or 200, response.geturl(), body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(BODY_SNIFF_BYTES).decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, url, body
    except Exception as exc:  # DNS, TLS, timeout — a probe failure, not a crash
        return 0, url, f"[network error] {exc}"


def classify_status(http_code: int, body: str = "") -> str:
    """Maps an HTTP answer onto the project's status vocabulary."""
    if http_code in (401, 403, 429, 503):
        return "blocked"
    if http_code in (404, 410):
        return "dead"
    if 200 <= http_code < 300:
        head = (body or "")[:800].lower()
        if any(marker in head for marker in (
                "just a moment", "checking your browser", "cf-challenge",
                "enable javascript and cookies", "attention required")):
            return "blocked"
        return "active"
    return "error"


# ---------------------------------------------------------------------------
# Database — capability metadata and probe history only
# ---------------------------------------------------------------------------

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS resolvers (
            name TEXT NOT NULL PRIMARY KEY,
            base_url TEXT NOT NULL,
            kinds TEXT NOT NULL,
            id_types TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS resolver_probes (
            resolver TEXT NOT NULL,
            kind TEXT NOT NULL,
            id TEXT NOT NULL,
            url TEXT NOT NULL,
            http_code INTEGER,
            status TEXT NOT NULL,
            probed_at INTEGER NOT NULL,
            PRIMARY KEY (resolver, kind, id, url)
        );
        """
    )


def seed_resolvers(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Writes/refreshes the four capability rows. Returns the row count."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        ensure_schema(conn)
        for name in PROVIDER_ORDER:
            provider = PROVIDERS[name]
            conn.execute(
                """
                INSERT INTO resolvers (name, base_url, kinds, id_types, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    base_url = excluded.base_url,
                    kinds = excluded.kinds,
                    id_types = excluded.id_types,
                    notes = excluded.notes;
                """,
                (
                    name,
                    provider["base_url"],
                    json.dumps(provider["kinds"]),
                    json.dumps(provider["id_types"]),
                    provider["notes"],
                ),
            )
        conn.commit()
        return conn.execute("SELECT COUNT(*) FROM resolvers;").fetchone()[0]
    finally:
        conn.close()


def _probe_identity(entry: dict) -> tuple[str, str]:
    """
    Recovers the (kind, id) a probe row is filed under.

    ``probe_work`` stamps both on the entry. A caller that validates bare
    ``resolver_urls`` output gets them read back off the URL instead — the URL
    is the only thing that knows whether it is a movie or an episode.
    """
    url = entry.get("url") or ""
    kind = entry.get("kind")
    if kind not in KINDS:
        lowered = url.lower()
        episode_args = "s=" in lowered and "e=" in lowered
        kind = "tv" if ("/tv" in lowered or "embedtv" in lowered or episode_args) else "movie"

    work_id = entry.get("id")
    if not work_id:
        imdb = re.search(r"(tt\d{7,9})", url, re.I)
        if imdb:
            work_id = f"imdb:{imdb.group(1).lower()}"
        else:
            tmdb = (re.search(r"/(?:movie|tv|embed|embedtv)/(\d{1,9})", url)
                    or re.search(r"[?&]video_id=(\d{1,9})", url))
            work_id = f"tmdb:{tmdb.group(1)}" if tmdb else "unknown"
    return kind, work_id


def record_probes(entries: list[dict], db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Upserts one probe row per entry. Entries must carry http_code/probed_at."""
    if not entries:
        return 0
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    written = 0
    try:
        ensure_schema(conn)
        for entry in entries:
            if not entry.get("http_code") and entry.get("http_code") != 0:
                continue  # never probed; nothing to record
            kind, work_id = _probe_identity(entry)
            conn.execute(
                """
                INSERT INTO resolver_probes
                    (resolver, kind, id, url, http_code, status, probed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(resolver, kind, id, url) DO UPDATE SET
                    http_code = excluded.http_code,
                    status = excluded.status,
                    probed_at = excluded.probed_at;
                """,
                (
                    entry["resolver"], kind, work_id, entry["url"],
                    entry["http_code"], entry["status"],
                    entry["probed_at"],
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def validate(entries: list[dict], probe: bool = True,
             db_path: Path | str = DEFAULT_DB_PATH,
             timeout: int = PROBE_TIMEOUT) -> list[dict]:
    """
    Probes each embed URL and records the result in ``resolver_probes``.

    ``probe=False`` makes **no network calls and no database writes**; the
    entries come back untouched with ``status`` still ``unknown``.

    Each probed entry gains ``http_code``, ``final_url`` and a classified
    ``status``. The probe also needs to know which work it belongs to, so
    callers pass ``kind``/``id`` on the entry (``probe_work`` does this).
    """
    if not probe:
        return entries

    seed_resolvers(db_path)
    now = int(time.time())
    for entry in entries:
        code, final_url, body = _http_probe(entry["url"], timeout=timeout)
        entry["http_code"] = code
        entry["final_url"] = final_url
        entry["status"] = classify_status(code, body)
        entry["probed_at"] = now
    record_probes(entries, db_path)
    return entries


def _work_id_label(tmdb: int | None, imdb: str | None) -> str:
    return f"imdb:{imdb}" if imdb else f"tmdb:{tmdb}"


def probe_work(tmdb_id=None, imdb_id=None, kind: str = "movie",
               season=None, episode=None, db_path: Path | str = DEFAULT_DB_PATH,
               probe: bool = True) -> list[dict]:
    """Builds + validates the URLs for one work. ``probe=False`` is offline."""
    url_entries = resolver_urls(tmdb_id, imdb_id, kind, season, episode)
    if not url_entries:
        return []
    tmdb = normalize_tmdb(tmdb_id)
    imdb = normalize_imdb(imdb_id)
    label = _work_id_label(tmdb, imdb)
    record_kind = (kind or "").strip().lower()
    for entry in url_entries:
        entry["kind"] = record_kind
        entry["id"] = label
    return validate(url_entries, probe=probe, db_path=db_path)


# ---------------------------------------------------------------------------
# Read-only catalog coverage
# ---------------------------------------------------------------------------

WORK_KEY_SQL = """
    SELECT COUNT(*) FROM (
        SELECT CASE
            WHEN imdb_id GLOB 'tt[0-9]*' THEN 'imdb:' || lower(imdb_id)
            WHEN tmdb_id IS NOT NULL AND tmdb_id > 0 THEN 'tmdb:' || tmdb_id
            ELSE 'title:' || lower(trim(COALESCE(clean_title, title, '')))
                 || ':' || COALESCE(CAST(year AS TEXT), 'ny')
        END AS work_key
        FROM posts
        WHERE COALESCE(is_18_plus, 0) = 0
        GROUP BY work_key
    );
"""

HAS_ID_SQL = """
    (imdb_id GLOB 'tt[0-9]*' OR (tmdb_id IS NOT NULL AND tmdb_id > 0))
"""


def merged_catalog_path() -> Path:
    """
    Locates the merged catalog without writing to it.

    The running service names its database in ``RADD_DB_PATH`` (today that is
    ``merged_catalog_20261025.db``). A deployed host therefore outranks a
    filename guess; the newest ``merged_catalog_*.db`` is next, and the legacy
    ``fast_fetch.db`` is the last resort.
    """
    configured = os.environ.get("RADD_DB_PATH")
    if configured and Path(configured).is_file():
        return Path(configured)
    candidates = sorted(DATA_DIR.glob("merged_catalog_*.db"))
    if candidates:
        return candidates[-1]
    return DATA_DIR / "fast_fetch.db"


def coverage(db_path: Path | str | None = None) -> dict:
    """Counts the merged catalog's resolver-usable works. READ-ONLY."""
    db_path = Path(db_path) if db_path else merged_catalog_path()
    if not db_path.is_file():
        return {"error": f"catalog not found: {db_path}"}
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15)
    try:
        total_posts = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE COALESCE(is_18_plus, 0) = 0;"
        ).fetchone()[0]
        posts_with_id = conn.execute(
            f"SELECT COUNT(*) FROM posts WHERE COALESCE(is_18_plus, 0) = 0 AND {HAS_ID_SQL};"
        ).fetchone()[0]
        total_works = conn.execute(WORK_KEY_SQL).fetchone()[0]
        works_with_id = conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT CASE"
            "    WHEN imdb_id GLOB 'tt[0-9]*' THEN 'imdb:' || lower(imdb_id)"
            "    WHEN tmdb_id IS NOT NULL AND tmdb_id > 0 THEN 'tmdb:' || tmdb_id"
            "    ELSE 'title:' || lower(trim(COALESCE(clean_title, title, '')))"
            "         || ':' || COALESCE(CAST(year AS TEXT), 'ny')"
            "  END AS work_key"
            "  FROM posts"
            f"  WHERE COALESCE(is_18_plus, 0) = 0 AND {HAS_ID_SQL}"
            "  GROUP BY work_key"
            ");"
        ).fetchone()[0]
    finally:
        conn.close()
    pct = round(100.0 * works_with_id / total_works, 1) if total_works else 0.0
    return {
        "posts": total_posts,
        "posts_with_id": posts_with_id,
        "works": total_works,
        "works_with_id": works_with_id,
        "coverage_pct": pct,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Embed resolver adapters (URL builder + probe). No catalog writes.")
    parser.add_argument("command", nargs="?", default="providers",
                        choices=["providers", "urls", "probe", "coverage", "stats"])
    parser.add_argument("--tmdb", default=None)
    parser.add_argument("--imdb", default=None)
    parser.add_argument("--kind", default="movie", choices=list(KINDS))
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--episode", type=int, default=None)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--catalog", default=None,
                        help="coverage: read this DB instead of the detected merged catalog")
    parser.add_argument("--no-probe", action="store_true",
                        help="with 'probe', build URLs but make no network calls")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "coverage":
        print(json.dumps(coverage(args.catalog), indent=2))
        return 0

    if args.command == "providers":
        seed_resolvers(args.db)
        print(json.dumps(PROVIDERS, indent=2))
        return 0

    if args.command == "stats":
        conn = sqlite3.connect(args.db, timeout=15)
        try:
            ensure_schema(conn)
            rows = conn.execute(
                "SELECT resolver, kind, status, COUNT(*) FROM resolver_probes"
                " GROUP BY resolver, kind, status ORDER BY resolver, kind;"
            ).fetchall()
        finally:
            conn.close()
        print(json.dumps(rows, indent=2))
        return 0

    if not args.tmdb and not args.imdb:
        parser.error(f"{args.command} requires --tmdb or --imdb")

    probe = not args.no_probe and args.command == "probe"
    if probe:
        entries = probe_work(args.tmdb, args.imdb, args.kind, args.season,
                             args.episode, db_path=args.db)
    else:
        entries = resolver_urls(args.tmdb, args.imdb, args.kind,
                                args.season, args.episode)
    if not entries:
        print("[!] No usable id/kind/season/episode; nothing to build.", file=sys.stderr)
        return 1
    if not args.quiet:
        for entry in entries:
            code = entry.get("http_code", "-")
            print(f"[{entry['status']:>7}] {code}  {entry['resolver']:<11} {entry['url']}")
    else:
        print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
