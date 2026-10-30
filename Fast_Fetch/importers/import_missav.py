#!/usr/bin/env python3
"""missav.live -> per-site staging database. Standard library only.

WHAT THIS MODULE IS, MEASURED 2026-10-30: the site answers an unauthenticated
automated client with a Cloudflare JS challenge on every path, `/robots.txt`
included (`GET /` -> 403, 5,434 bytes, `<title>Just a moment...</title>`;
`GET /robots.txt` -> 403, 5,485 bytes). No homepage, no rail, no item page and
no tier markup was ever captured, so this module does NOT contain an HTML
parser. `extract_record()` refuses with `CaptureRequired` and says what it
needs. Writing selectors against pages nobody has seen would be invention, and
an invented parser that passes its own tests is worse than no parser.

WHAT IT DOES CONTAIN is the half that can be proven today, because it is the
compliance-critical half:

  1. Every row is 18+ by SOURCE, not by title. `posts.is_18_plus` is
     `NOT NULL DEFAULT 1 CHECK (is_18_plus = 1)`, so a missav row cannot be
     written unflagged even by hand-written SQL. `WRITE` never reads an adult
     flag from its input.
  2. `canonical_key` is the site's content code, namespaced: `STARS-123` ->
     `missav-stars-123`. The prefix is deliberate — `docs/ADULT_TWIN_PROBE.md`
     measured 442 keys that already hold both a flagged and an unflagged row,
     and a missav row must never share a key with a clean row elsewhere.
  3. Every declared tier is a `releases` row; a tier with no URL gets NO
     `sources` row (nothing invented); a dead mirror is stored with
     `status='dead'` and kept.
  4. Subtitle-language tags are preserved in their own column and in the tags.
  5. The crawl gate is code: load >= 4.0, MemAvailable <= 4000 MB, another
     importer running, or a missing/zero --limit all refuse. `sync` refuses a
     second time for the measured site reason, with its own exit code, so the
     two causes stay distinguishable in logs.
  6. Staging only: `DEFAULT_DB_PATH` is missav.db. No string in this module
     names the production catalog or any merged catalog, and nothing merges it.

The record shape is the module's own contract (`RECORD_FIELDS`), not the site's
markup. When a real page is captured — a human's browser save, per
`docs/SITE_MISSAV.md` §6 — the only work is `extract_record()`: turn those bytes
into this dict. Everything downstream is tested already.

Usage:
  python3 -S import_missav.py gate
  python3 -S import_missav.py schema --db /tmp/missav.db
  python3 -S import_missav.py write-record --db /tmp/missav.db --json rec.json
  python3 -S import_missav.py sync --limit 25
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE_URL = "https://missav.live"
SITE_NAME = "missav"
DEFAULT_DB_PATH = Path("/home/ubuntu/radd-stream-data/missav.db")
PAGE_TIMEOUT = 25
RATE_LIMIT_STATUS = 429

LOAD_CEILING = 4.0
MEM_FLOOR_MB = 4000.0

#: Measured 2026-10-30: the vhost challenges unauthenticated automated clients
#: on every path, including /robots.txt, so there is no crawl policy to honour
#: and no page to parse. This is a SITE reason, distinct from the box reason.
SITE_REASON = ("missav.live answers an unauthenticated automated client with a "
               "Cloudflare JS challenge on every path, /robots.txt included "
               "(measured 2026-10-30: 403 on both, 5,434 / 5,485 bytes); this lane "
               "does not solve, spoof or otherwise route around it")

KEY_PREFIX = "missav-"

#: The owner named `ABC-123` as the shape, not a measured vocabulary. This is a
#: CLASS of codes, deliberately permissive about separators and suffixes.
#: A suffix must be separated (`ABC-123-v2`); glued on (`ABC-123456`) it is
#: indistinguishable from a longer number, so it is refused rather than guessed.
CODE_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]{2,10})[-_ ]?(?P<num>\d{2,5})(?:[-_ ](?P<suffix>[A-Za-z0-9]{1,6}))?$"
)
TIER_RE = re.compile(r"^(?:240p|360p|480p|540p|720p|1080p|1440p|2160p|4k|uhd|fhd|hd|sd)$", re.I)
SOURCE_STATUSES = ("unverified", "active", "dead", "geo_blocked")
KINDS = ("stream", "download")

RECORD_FIELDS = (
    "code", "title", "url", "studio", "release_date", "duration", "series",
    "performers", "tags", "subtitles", "poster_url", "thumb_url",
    "backdrop_url", "streams", "downloads",
)


class RecordRefused(ValueError):
    """The record cannot be stored without inventing something."""


class CaptureRequired(RuntimeError):
    """No item page has been captured, so HTML cannot become a record yet."""


# ── the gate ────────────────────────────────────────────────────────────────

def read_loadavg(path: str = "/proc/loadavg") -> float:
    try:
        return float(Path(path).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 9999.0


def read_mem_available_mb(path: str = "/proc/meminfo") -> float:
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return float(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return 0.0
    return 0.0


def crawl_blocked(loadavg: float, mem_available_mb: float,
                  other_crawlers: int, limit: int | None) -> list[str]:
    """Reasons a crawl may not start now. Empty list means the gate is open.

    `limit=None` is refused on purpose: an unbounded first crawl is the swarm
    the fleet rule exists to prevent, on a box that has already OOM-killed
    production once.
    """
    reasons = []
    if loadavg >= LOAD_CEILING:
        reasons.append(f"1-min load {loadavg:.2f} is at or above the {LOAD_CEILING} ceiling")
    if mem_available_mb <= MEM_FLOOR_MB:
        reasons.append(f"MemAvailable {mem_available_mb:.0f} MB is at or below {MEM_FLOOR_MB:.0f} MB")
    if other_crawlers:
        reasons.append(f"{other_crawlers} other import process(es) are running")
    if not limit or limit < 1:
        reasons.append("no --limit given; an unbounded crawl is never started by default")
    return reasons


def current_gate_state() -> tuple[float, float, int]:
    """(load1, mem_available_mb, other_crawlers) measured right now."""
    import os

    other = 0
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or int(pid) == os.getpid():
                continue
            try:
                cmd = (Path("/proc") / pid / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            except OSError:
                continue
            if re.search(r"Fast_Fetch/.*import", cmd):
                other += 1
    except OSError:
        other = 0
    return read_loadavg(), read_mem_available_mb(), other


# ── identity ────────────────────────────────────────────────────────────────

def canonical_key(code: str | None) -> str:
    """`STARS-123` -> `missav-stars-123`; refuse anything that is not a code.

    The content code IS the identity (one work, one code), which is why it
    beats a title slug. The `missav-` namespace is not cosmetic: a key shared
    with a clean row from another site is exactly the twin hole this source
    must not widen.
    """
    m = CODE_RE.match((code or "").strip())
    if not m:
        raise RecordRefused(f"not a content code: {code!r}")
    parts = [m.group("prefix").lower(), m.group("num")]
    if m.group("suffix"):
        parts.append(m.group("suffix").lower())
    return KEY_PREFIX + "-".join(parts)


def normalize_tier(label: str | None) -> str | None:
    text = (label or "").strip().lower()
    if not text:
        return None
    m = re.search(r"\b(240p|360p|480p|540p|720p|1080p|1440p|2160p|4k|uhd|fhd)\b", text)
    if m:
        return m.group(1)
    return text if TIER_RE.match(text) else None


def playback_type(url: str | None) -> str:
    path = (url or "").split("?")[0].lower()
    return "hls" if path.endswith(".m3u8") else "redirect"


# ── record -> rows ──────────────────────────────────────────────────────────

def _strings(value, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise RecordRefused(f"{field} must be a string or a list of strings")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RecordRefused(f"{field} has an empty or non-string member")
        out.append(item.strip())
    return out


def normalize_record(record: dict) -> dict:
    """Validate one normalized record and return a clean copy.

    Strict on purpose: a tier or mirror without a URL is data the site did not
    publish, so it becomes a release with no source — never a fabricated URL,
    and never a silently dropped row.
    """
    if not isinstance(record, dict):
        raise RecordRefused("record must be a dict")
    title = (record.get("title") or "").strip()
    if not title:
        raise RecordRefused("a record without a title cannot be stored")
    key = canonical_key(record.get("code"))

    rec = {
        "canonical_key": key,
        "code": record.get("code").strip(),
        "title": title,
        "url": (record.get("url") or "").strip() or None,
        "studio": (record.get("studio") or "").strip() or None,
        "release_date": (record.get("release_date") or "").strip() or None,
        "duration": (record.get("duration") or "").strip() or None,
        "series": (record.get("series") or "").strip() or None,
        "performers": _strings(record.get("performers"), "performers"),
        "tags": _strings(record.get("tags"), "tags"),
        "subtitles": _strings(record.get("subtitles"), "subtitles"),
        "poster_url": (record.get("poster_url") or "").strip() or None,
        "thumb_url": (record.get("thumb_url") or "").strip() or None,
        "backdrop_url": (record.get("backdrop_url") or "").strip() or None,
        "streams": [],
        "downloads": [],
    }
    for kind in KINDS:
        field = kind + "s"
        seen: set[str] = set()
        for entry in record.get(field) or []:
            if not isinstance(entry, dict):
                raise RecordRefused(f"{kind} entries must be objects")
            tier = normalize_tier(entry.get("quality") or entry.get("label"))
            if not tier:
                raise RecordRefused(f"{kind} entry without a recognizable quality: {entry!r}")
            url = (entry.get("url") or "").strip() or None
            status = (entry.get("status") or "unverified").strip().lower()
            if status not in SOURCE_STATUSES:
                raise RecordRefused(f"unknown source status {status!r}")
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            rec[field].append({"quality": tier, "url": url, "status": status})
    return rec


# ── staging write ───────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS page_cache (
    url TEXT PRIMARY KEY,
    kind TEXT,
    fetched_at INTEGER,
    http_status INTEGER,
    error_count INTEGER DEFAULT 0,
    html_sha TEXT
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
    -- THE GUARD: every missav row is 18+ by source, so an unflagged row is not
    -- a policy violation to be fixed later, it is an unrepresentable state.
    is_18_plus INTEGER NOT NULL DEFAULT 1 CHECK (is_18_plus = 1),
    is_animated INTEGER DEFAULT 0,
    source_site TEXT NOT NULL DEFAULT 'missav' CHECK (source_site = 'missav'),
    studio TEXT,
    thumb_url TEXT,
    content_code TEXT,
    series TEXT,
    subtitles TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_meta TEXT
);
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('stream', 'download')),
    label TEXT,
    quality TEXT,
    resolution TEXT,
    size_bytes INTEGER,
    codec TEXT,
    audio_languages TEXT,
    origin_url TEXT,
    container TEXT,
    source_tag TEXT,
    site_hits INTEGER,
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
    playback_type TEXT DEFAULT 'redirect',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 1,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
CREATE INDEX IF NOT EXISTS idx_missav_releases_post ON releases(post_canonical_key);
CREATE INDEX IF NOT EXISTS idx_missav_sources_release ON sources(release_id);
CREATE INDEX IF NOT EXISTS idx_missav_posts_code ON posts(content_code);
"""

POST_COLUMNS = (
    "canonical_key", "title", "clean_title", "year", "media_type", "poster_url",
    "backdrop_url", "backdrop_urls", "imdb_id", "tmdb_id", "imdb_rating", "synopsis",
    "genres", "director", "cast_names", "duration", "release_date", "languages",
    "industry", "country", "seasons", "url", "slug", "source_site", "studio",
    "thumb_url", "content_code", "series", "subtitles", "raw_meta",
)
RELEASE_COLUMNS = (
    "post_canonical_key", "kind", "label", "quality", "resolution", "size_bytes",
    "codec", "audio_languages", "origin_url", "container", "source_tag", "site_hits",
)
SOURCE_COLUMNS = (
    "release_id", "source_name", "service", "resource_id", "source_url", "final_url",
    "playback_type", "status", "is_temporary", "quality", "last_checked",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _insert(conn: sqlite3.Connection, table: str, columns: tuple, row: dict) -> int:
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    cur = conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})",
                       [row.get(c) for c in columns])
    return int(cur.lastrowid)


def write_record(conn: sqlite3.Connection, record: dict) -> dict:
    """Store one normalized record. Returns {"post", "releases", "sources"}.

    `is_18_plus` is never read from the record and never written by this
    function: the column's DEFAULT 1 is the value, and the CHECK constraint is
    what makes that true (see `SCHEMA`).
    """
    rec = normalize_record(record)
    key = rec["canonical_key"]

    exists = conn.execute("SELECT 1 FROM posts WHERE canonical_key = ?", (key,)).fetchone()
    if exists:
        return {"post": 0, "releases": 0, "sources": 0, "skipped": True}

    year = None
    m = re.search(r"(19|20)\d{2}", rec["release_date"] or "")
    if m:
        year = int(m.group(0))

    post = {
        "canonical_key": key,
        "title": rec["title"],
        "clean_title": rec["title"],
        "year": year,
        "media_type": None,          # the site's own type word was never measured
        "poster_url": rec["poster_url"],
        "backdrop_url": rec["backdrop_url"],
        "cast_names": ", ".join(rec["performers"]) or None,
        "duration": rec["duration"],
        "release_date": rec["release_date"],
        "industry": rec["studio"],
        # `url` comes from the record when the capture supplies it. It is NOT
        # composed from the code: a URL this module invented would be a link to
        # a page that may not exist, which is the one thing we never store.
        "url": rec["url"],
        "slug": key[len(KEY_PREFIX):],
        "source_site": SITE_NAME,
        "studio": rec["studio"],
        "thumb_url": rec["thumb_url"],
        "content_code": rec["code"],
        "series": rec["series"],
        "subtitles": ", ".join(rec["subtitles"]) or None,
        "raw_meta": json.dumps({
            "code": rec["code"],
            "performers": rec["performers"],
            "tags": rec["tags"],
            "subtitles": rec["subtitles"],
            "studio": rec["studio"],
            "series": rec["series"],
            "record_url": rec["url"],
        }, ensure_ascii=False),
    }
    _insert(conn, "posts", POST_COLUMNS, post)

    kept = 0
    for kind in KINDS:
        for entry in rec[kind + "s"]:
            release_id = _insert(conn, "releases", RELEASE_COLUMNS, {
                "post_canonical_key": key,
                "kind": kind,
                "label": entry["quality"],
                "quality": entry["quality"],
                "source_tag": SITE_NAME,
            })
            kept += 1
            if not entry["url"]:
                continue  # declared tier, no URL: a release, deliberately no source
            _insert(conn, "sources", SOURCE_COLUMNS, {
                "release_id": release_id,
                "source_name": SITE_NAME,
                "resource_id": f"{key}:{kind}:{entry['quality']}",
                "source_url": entry["url"],
                "playback_type": playback_type(entry["url"]),
                "status": entry["status"],
                "is_temporary": 1,
                "quality": entry["quality"],
            })
    conn.commit()
    sources = conn.execute(
        "SELECT COUNT(*) FROM sources s JOIN releases r ON r.id = s.release_id "
        "WHERE r.post_canonical_key = ?", (key,)).fetchone()[0]
    return {"post": 1, "releases": kept, "sources": int(sources), "skipped": False}


# ── the absent half, made explicit ──────────────────────────────────────────

def extract_record(html_text: str) -> dict:
    """HTML -> normalized record. NOT IMPLEMENTED, on purpose.

    Measured 2026-10-30: the site serves a Cloudflare JS challenge to
    unauthenticated automated clients on every path, `/robots.txt` included, so
    no page has ever been captured and there are no selectors to write. An
    invented parser passes its own invented tests and fails on the first real
    byte, which is worse than a loud refusal. See `docs/SITE_MISSAV.md` §6.
    """
    raise CaptureRequired(
        "no missav item page has been captured: " + SITE_REASON +
        ". Save one page from a browser to /tmp/q5_missav/item.html and write "
        "this function against it; everything downstream is already tested."
    )


def parse_item(html_text: str) -> dict:
    return normalize_record(extract_record(html_text))


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cmd_gate(_args) -> int:
    load1, mem, other = current_gate_state()
    print(f"load1={load1:.2f} MemAvailable={mem:.0f}MB other_crawlers={other}")
    reasons = crawl_blocked(load1, mem, other, limit=1)
    for r in reasons:
        print(f"BLOCKED: {r}")
    print(f"site: {SITE_REASON}")
    if reasons:
        return 3
    print("box gate open, but the site refuses this client: nothing to crawl")
    return 4


def _cmd_schema(args) -> int:
    path = Path(args.db)
    conn = sqlite3.connect(path)
    try:
        ensure_schema(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)")]
        print(f"{path}: posts({len(cols)} cols), is_18_plus guarded: "
              f"{'is_18_plus' in cols}")
    finally:
        conn.close()
    return 0


def _cmd_write_record(args) -> int:
    """Read one record (or a list) and store it. Bad input is refused before
    the database file is touched, so a typo cannot leave an empty staging DB."""
    try:
        payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"cannot read {args.json}: {exc}")
        return 2
    except json.JSONDecodeError as exc:
        print(f"{args.json} is not JSON: {exc}")
        return 2
    records = payload if isinstance(payload, list) else [payload]
    try:
        cleaned = [normalize_record(rec) for rec in records]
    except RecordRefused as exc:
        print(f"record refused: {exc}")
        return 2
    conn = sqlite3.connect(Path(args.db))
    try:
        ensure_schema(conn)
        totals = {"post": 0, "releases": 0, "sources": 0}
        for rec in cleaned:
            got = write_record(conn, rec)
            for k in totals:
                totals[k] += got[k]
        print(f"wrote {totals['post']} post(s), {totals['releases']} release(s), "
              f"{totals['sources']} source(s) into {args.db}")
    finally:
        conn.close()
    return 0


def _cmd_sync(args) -> int:
    load1, mem, other = current_gate_state()
    reasons = crawl_blocked(load1, mem, other, args.limit)
    if reasons:
        for r in reasons:
            print(f"BLOCKED: {r}")
        print("crawl deferred, gate conditions not met")
        return 3
    print(f"No page has ever been captured: {SITE_REASON}.")
    print("crawl refused at the site, not deferred by the box; see docs/SITE_MISSAV.md")
    return 4


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gate").set_defaults(func=_cmd_gate)

    p = sub.add_parser("schema")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.set_defaults(func=_cmd_schema)

    p = sub.add_parser("write-record")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--json", required=True)
    p.set_defaults(func=_cmd_write_record)

    p = sub.add_parser("sync")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=_cmd_sync)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
