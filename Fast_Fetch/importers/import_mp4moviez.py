#!/usr/bin/env python3
"""
import_mp4moviez.py — bring the legacy mp4moviez database into the staging contract.

This is a converter, not a crawler, and it says so in every line: mp4moviez.db
already holds 29,848 scraped pages and 54,267 download rows, scraped by a worker
that predated the fleet schema. It cannot be merged as it stands, because
`merge_catalogs.py` reads a staging database through three tables the legacy file
does not have — `posts.canonical_key`, `releases.post_canonical_key`, and
`sources` — and raises
`ValueError: Source database has neither download_sources nor sources table`
before it reaches a single row.

Measured on 2026-10-28 against the file itself, not against a sample:

| Fact | Value |
|---|---|
| posts | 29,848 — 7 with no title, 2 whose `source_url` is a `sitemap-*.xml` file |
| posts with at least one release | 13,680 |
| posts with NO release | 16,168 |
| ... of which carry a `c<digits>` anchor (a real work, links gone) | 14,730 |
| ... of which are category/listing pages or takedown notices | 1,438 |
| releases | 54,267, every one `resolved = 0` — 240/360/480/720p, max four tiers per post |
| `dl.php?id=` | exactly 13,680 distinct ids, one per post-with-releases, none shared by two posts; the `q=` parameter carries the tier |
| distinct page slugs | 29,503; 336 slugs appear on 2+ rows (681 rows) |
| colliding slugs whose (year, title) differs | 4 — three are punctuation variants of the same film (Spider-Man / Spider Man), one is the takedown notice reusing The Dark Knight's slug, and takedowns are dropped |
| `is_18_plus = 1` | 91 |
| synopsis / genres / cast / tags populated | 0 — the legacy scrape never read them |
| queue rows | 32,967: 29,848 processed, 3,119 never fetched |

**The hole in this asset, stated where it cannot be missed:** 14,730 of the 29,848
stored pages — 3.4x the number that have links at all — are work pages with a
`c<id>` anchor and **zero download rows**. Re-fetched 2026-10-29, five of them
answer HTTP 200 with 11-12 kB of HTML containing 39 anchors, **every one a
category link**, no `<h1>`-`<h4>` at all, and no `dl.php` reference anywhere. The
site kept the URLs and emptied the pages. (The `data-key` attributes on those
pages belong to an ad SDK mounted on `<ins class=… data-cp-host=…>` elements —
not a gated download button, and no decoder recovers a link from them.) So a
re-drive of this cohort cannot recover rows: there is nothing on the page to
parse, and inventing one is what the `link_source` note exists to prevent.

The rules this file follows, in order of importance:

1. **A key is the site's own, never one we invent.** The page slug is the
   canonical key: it is what the URL publishes, it survives a re-crawl, and the
   336 rows that repeat a slug are the *same film re-posted under a new `c<id>`
   path*, which `merge_catalogs.py` collapses onto one catalog record by design.
2. **Nothing is invented into `sources`.** The stored link is
   `https://www.mp4moviez.deal/dl.php?id=<n>&q=<quality>&title=<slug>` — the
   site's own redirect endpoint, durable and re-resolvable, but never followed by
   this project's scraper. So `final_url` is NULL, `status` is `unverified`,
   `last_checked` is NULL, and `playback_type` is `download`. A converter that
   wrote `active` here would be claiming a probe that did not happen.
3. **A row that is not a work does not become a post.** A category/listing page
   carries no release and no `c<id>` anchor; converting the 1,438 of them would
   push index pages into the catalog and inflate the merge count with things
   nobody can watch. They are counted and reported instead. The 3,119 queue URLs
   the legacy scraper never fetched are left exactly as they were, and they are
   not 3,119 missing films: 1,781 are listing/pagination rows (many storing a
   literal `&amp;p=2` instead of `&p=2`), 1,338 are work-shaped pages the old
   parser would find link-less anyway, and 24 carry an adult token.
4. **The migration is additive inside one transaction.** The legacy columns are
   copied into `raw_meta` before their tables are replaced, every count is
   re-checked before COMMIT, and a mismatch rolls the whole thing back. `check`
   reports the plan and writes nothing.

Stdlib only. Never opens `fast_fetch.db` or a merged catalog.

**Proof it works, measured 2026-10-29 on a copy, never on production:** `convert`
on `/tmp/mp4moviez_copy.db` wrote 28,066 posts / 54,267 releases / 54,267 sources
with 0 null keys, and `merge_catalogs.merge_site_db` then read it end to end into a
throwaway target in 710 s — `posts_merged=28066 releases_merged=54267
sources_merged=54267 posts_conflicted=0`. The live `mp4moviez.db` is still in legacy
form on purpose: a converter that drops and renames tables under an in-flight merge
is how a run loses rows, so `convert` is one command for whoever owns the queue.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
from pathlib import Path

SITE = "mp4moviez"
BASE_URL = "https://www.mp4moviez.deal"
LEGACY_DB_PATH = Path("/home/ubuntu/radd-stream-data/mp4moviez.db")
DEFAULT_DB_PATH = LEGACY_DB_PATH

# `dl.php?id=60944&q=240&title=Marshals-(2026)-...` — the id is the page's own
# number and the q is the tier; both stay in the URL we store.
DL_ID_RE = re.compile(r"[?&]id=(?P<id>\d+)")
DL_QUALITY_RE = re.compile(r"[?&]q=(?P<q>\d+)")
QUALITY_RE = re.compile(r"^(?P<height>\d{3,4})p$", re.I)
CONTENT_ANCHOR_RE = re.compile(r"^c\d+$", re.I)

SERIES_RE = re.compile(
    r"\bseason\s*\d+|\bs\d{1,2}\b|\bepisode\s*\d+|\bep\s*\d+|tv series"
    r"|web series|dual audio complete|complete\b", re.I)
SEASON_NUM_RE = re.compile(r"season\s*(?P<n>\d+)|\bs(?P<n2>\d{1,2})\b", re.I)
EPISODE_NUM_RE = re.compile(r"episode\s*(?P<n>\d+)|\be(?P<n2>\d{1,3})\b", re.I)
YEAR_RE = re.compile(r"[(\s]?(?P<year>(?:19|20)\d{2})[)\s]?")

# The boilerplate this site wraps every title in, and the notice it leaves behind
# when a copyright claim takes a page's links away.
TITLE_PREFIX_RE = re.compile(r"^\s*(?:download|watch)\s+", re.I)
TITLE_SUFFIX_RE = re.compile(
    r"\s+(?:in\s+(?:hd|4k|uhd|full\s+hd)|hd|4k|uhd|dual\s+audio|full\s+movie"
    r"|web[-\s]drip|hdtv|cam|ts)\s*$", re.I)
TAKEDOWN_RE = re.compile(r"not available anymore due to a copyright claim", re.I)

POST_COLUMNS = (
    "canonical_key", "title", "clean_title", "year", "media_type", "poster_url",
    "backdrop_url", "backdrop_urls", "imdb_id", "tmdb_id", "imdb_rating",
    "synopsis", "genres", "director", "cast_names", "duration", "release_date",
    "languages", "industry", "country", "seasons", "url", "slug", "is_18_plus",
    "is_animated", "source_site", "raw_meta",
)
RELEASE_COLUMNS = (
    "post_canonical_key", "label", "quality", "resolution", "size_bytes", "codec",
    "season_number", "episode_number", "audio_languages", "bridge_url",
    "origin_url", "air_date", "raw_meta",
)
SOURCE_COLUMNS = (
    "release_id", "source_name", "service", "resource_id", "source_url",
    "final_url", "playback_type", "status", "is_temporary", "quality",
    "last_checked",
)

_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS posts_new (
    canonical_key TEXT PRIMARY KEY NOT NULL,
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
    source_site TEXT DEFAULT 'mp4moviez',
    scraped_at TIMESTAMP,
    raw_meta TEXT
)""",
    """CREATE TABLE IF NOT EXISTS releases_new (
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
    air_date TEXT,
    raw_meta TEXT
)""",
    """CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    source_name TEXT,
    service TEXT,
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'download',
    status TEXT DEFAULT 'unverified',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER
)""",
)

_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_mp4moviez_posts_slug ON posts(slug)",
    "CREATE INDEX IF NOT EXISTS idx_mp4moviez_posts_type ON posts(media_type)",
    "CREATE INDEX IF NOT EXISTS idx_mp4moviez_releases_post ON releases(post_canonical_key)",
    "CREATE INDEX IF NOT EXISTS idx_mp4moviez_releases_origin ON releases(origin_url)",
    "CREATE INDEX IF NOT EXISTS idx_mp4moviez_sources_status ON sources(status)",
    "CREATE INDEX IF NOT EXISTS idx_mp4moviez_sources_release ON sources(release_id)",
)


# ---------------------------------------------------------------------------
# Field derivation: everything below reads what the row publishes
# ---------------------------------------------------------------------------

def slug_from(url: str) -> str:
    """The published page slug, which is also this site's canonical key."""
    parts = [p for p in urllib.parse.urlsplit(url or "").path.split("/") if p]
    if not parts:
        return ""
    last = parts[-1]
    if last.lower().endswith(".html"):
        last = last[:-5]
    return last.lower()


def anchor_from(url: str) -> str:
    parts = [p for p in urllib.parse.urlsplit(url or "").path.split("/") if p]
    return parts[0] if len(parts) > 1 else ""


def clean_title(text: str | None) -> str:
    """Strips this site's own wrapper words; never touches a host field."""
    cleaned = re.sub(r"\s+", " ", urllib.parse.unquote(text or "")).strip()
    cleaned = re.split(r"\s*[»|]\s*filmy", cleaned, maxsplit=1, flags=re.I)[0].strip()
    cleaned = TITLE_PREFIX_RE.sub("", cleaned)
    while True:
        shorter = TITLE_SUFFIX_RE.sub("", cleaned).strip()
        if shorter == cleaned:
            break
        cleaned = shorter
    return cleaned.strip(" -|:,")


def media_type_of(*texts: str) -> str:
    joined = " ".join(t for t in texts if t)
    return "series" if SERIES_RE.search(joined) else "movie"


def _int_or_none(match: re.Match | None, *groups: str) -> int | None:
    for name in groups:
        value = match.group(name) if match else None
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def season_of(text: str) -> int | None:
    return _int_or_none(SEASON_NUM_RE.search(text or ""), "n", "n2")


def episode_of(text: str) -> int | None:
    return _int_or_none(EPISODE_NUM_RE.search(text or ""), "n", "n2")


def year_of(*texts: str) -> int | None:
    for text in texts:
        match = YEAR_RE.search(text or "")
        if match:
            return int(match.group("year"))
    return None


def dl_id(url: str) -> str:
    match = DL_ID_RE.search(url or "")
    return match.group("id") if match else ""


def _json_list(value) -> str | None:
    """Keeps a published JSON array, or None when the legacy scrape left it empty."""
    if value in (None, "", "[]", "{}"):
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, list) and not parsed:
        return None
    return json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, (list, dict)) \
        else str(value)


# ---------------------------------------------------------------------------
# The transform
# ---------------------------------------------------------------------------

def is_work(post: dict, release_count: int) -> bool:
    """
    A work is a page the site gave download rows, or a page whose URL carries its
    own `c<id>` content anchor.

    The second branch is deliberate and it is the honest half: 14,730 stored
    pages are titled, dated, anchored works with zero links because the site
    published them before moving its buttons behind a script. They convert as
    catalog entries with no sources — metadata a viewer can find, flagged in
    `raw_meta.link_source` as unlinked — rather than vanishing from the asset.
    What is *not* accepted is the 1,438 rows that are neither: category indexes,
    pagination pages, XML, untitled rows and copyright-takedown notices.
    """
    url = post.get("source_url") or ""
    if url.lower().endswith(".xml"):
        return False
    if TAKEDOWN_RE.search(post.get("clean_title") or ""):
        return False
    if not (post.get("clean_title") or "").strip():
        return False
    return bool(release_count or CONTENT_ANCHOR_RE.match(anchor_from(url)))


def transform_post(post: dict, releases: list[dict]) -> dict | None:
    """One legacy post plus its rows -> contract rows, or None when it is not a work."""
    if not is_work(post, len(releases)):
        return None
    url = post.get("source_url") or ""
    key = slug_from(url)
    if not key:
        return None
    title = clean_title(post.get("clean_title")) or key.replace("-", " ").strip()
    year = post.get("year") or year_of(title, key)
    media_type = media_type_of(title, key)
    season = season_of(title) if media_type == "series" else None
    episode = episode_of(title) if media_type == "series" else None
    languages = _json_list(post.get("languages"))

    record = {
        "canonical_key": key,
        "title": title,
        "clean_title": title,
        "year": year,
        "media_type": media_type,
        "poster_url": (post.get("poster_url") or "").strip() or None,
        "backdrop_url": None,
        "backdrop_urls": None,
        "imdb_id": None,
        "tmdb_id": None,
        "imdb_rating": None,
        "synopsis": (post.get("synopsis") or "").strip() or None,
        "genres": _json_list(post.get("genres")),
        "director": None,
        "cast_names": _json_list(post.get("cast_names")),
        "duration": (post.get("duration") or "").strip() or None,
        "release_date": None,
        "languages": languages,
        "industry": None,
        "country": None,
        "seasons": None,
        "url": url,
        "slug": key,
        "is_18_plus": int(post.get("is_18_plus") or 0),
        "is_animated": 0,
        "source_site": SITE,
        "raw_meta": {
            "site": SITE,
            "converted_from": "legacy mp4moviez.db posts/releases tables",
            "legacy_post_id": post.get("id"),
            "content_anchor": anchor_from(url),
            "legacy_tags": _json_list(post.get("tags")),
            "legacy_updated_at": post.get("updated_at"),
            "legacy_created_at": post.get("created_at"),
            "link_source": ("stored dl.php redirect endpoint, never followed by "
                            "this converter; final_url is null because no probe "
                            "happened here"),
        },
    }
    if not releases:
        record["raw_meta"]["link_source"] = ("no download row exists for this page "
                                             "in the legacy scrape — a real title "
                                             "the site has since unlinked")

    out_releases = []
    for rel in releases:
        link = rel.get("url") or ""
        quality = (rel.get("quality") or "").strip() or None
        resource = dl_id(link)
        out_releases.append({
            "post_canonical_key": key,
            "label": f"{title} [{quality}]" if quality else title,
            "quality": quality,
            "resolution": quality,
            "size_bytes": None,
            "codec": None,
            "season_number": season,
            "episode_number": episode,
            "audio_languages": languages,
            "bridge_url": link or None,
            "origin_url": url,
            "air_date": None,
            "raw_meta": {
                "legacy_release_id": rel.get("id"),
                "legacy_resolved": int(rel.get("resolved") or 0),
                "site_movie_id": resource or None,
            },
        })
    return {"post": record, "releases": out_releases}


def _legacy_rows(conn: sqlite3.Connection) -> tuple[list[dict], dict[int, list[dict]]]:
    conn.row_factory = sqlite3.Row
    posts = [dict(r) for r in conn.execute("SELECT * FROM posts ORDER BY id")]
    releases_by_post: dict[int, list[dict]] = {}
    for rel in conn.execute("SELECT * FROM releases ORDER BY id"):
        releases_by_post.setdefault(rel["post_id"], []).append(dict(rel))
    return posts, releases_by_post


def _merge_into(anchor: dict, other: dict) -> None:
    """
    Two pages, one work: keep the richer header, keep every download row.

    336 mp4moviez slugs are the same film re-posted under a new `c<id>` path. Their
    rows must not overwrite each other — a `MAX`-style fill-in keeps whatever either
    page published, the adult flag stays sticky, and both pages' releases survive.
    """
    a, b = anchor["post"], other["post"]
    for column in POST_COLUMNS:
        if column in ("canonical_key", "title", "clean_title", "url", "slug",
                      "source_site", "raw_meta", "is_18_plus"):
            continue
        if a.get(column) in (None, "", 0) and b.get(column) not in (None, "", 0):
            a[column] = b[column]
    a["is_18_plus"] = int(a.get("is_18_plus") or 0) or int(b.get("is_18_plus") or 0)

    seen = {(rel["bridge_url"], rel["quality"]) for rel in anchor["releases"]}
    for rel in other["releases"]:
        if (rel["bridge_url"], rel["quality"]) not in seen:
            anchor["releases"].append(rel)
        seen.add((rel["bridge_url"], rel["quality"]))

    pages = a["raw_meta"].setdefault("duplicate_pages", [])
    if b.get("url") and b["url"] != a.get("url") and b["url"] not in pages:
        pages.append(b["url"])


def build_records(conn: sqlite3.Connection) -> list[dict]:
    """Every legacy work, merged onto its canonical key, ready to write."""
    posts, releases_by_post = _legacy_rows(conn)
    merged: dict[str, dict] = {}
    for post in posts:
        record = transform_post(post, releases_by_post.get(post["id"], []))
        if record is None:
            continue
        key = record["post"]["canonical_key"]
        if key in merged:
            _merge_into(merged[key], record)
        else:
            merged[key] = record
    return [merged[key] for key in sorted(merged)]


def plan(conn: sqlite3.Connection) -> dict:
    """Reads the legacy tables and reports exactly what a conversion would write."""
    posts, releases_by_post = _legacy_rows(conn)
    records = build_records(conn)
    counts = {p["id"]: len(releases_by_post.get(p["id"], [])) for p in posts}
    return {
        "legacy_posts": len(posts),
        "legacy_releases": sum(counts.values()),
        "posts_with_releases": sum(1 for n in counts.values() if n),
        "converted_posts": len(records),
        "converted_releases": sum(len(r["releases"]) for r in records),
        "converted_sources": sum(len(r["releases"]) for r in records),
        "skipped_no_release": sum(1 for n in counts.values() if not n),
        "skipped_takedown": sum(1 for p in posts
                                if TAKEDOWN_RE.search(p.get("clean_title") or "")),
        "merged_duplicate_pages": sum(
            len(r["post"]["raw_meta"].get("duplicate_pages", [])) for r in records),
        "converted_18_plus": sum(1 for r in records if r["post"]["is_18_plus"]),
        "converted_series": sum(1 for r in records
                                if r["post"]["media_type"] == "series"),
        "converted_without_releases": sum(1 for r in records if not r["releases"]),
        "queue_rows_left_alone": (
            conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
            if conn.execute("SELECT name FROM sqlite_master WHERE name='sitemap_cache'")
            .fetchone() else 0),
        "queue_never_fetched": (
            conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE processed = 0")
            .fetchone()[0]
            if conn.execute("SELECT name FROM sqlite_master WHERE name='sitemap_cache'")
            .fetchone() else 0),
    }


def _values(row: dict, columns) -> tuple:
    return tuple(json.dumps(row.get(c), ensure_ascii=False)
                 if isinstance(row.get(c), (dict, list)) else row.get(c)
                 for c in columns)


def _legacy_tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def already_converted(conn: sqlite3.Connection) -> bool:
    """True when posts already carry the contract's canonical key."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(posts)")}
    return "canonical_key" in cols and "sources" in _legacy_tables(conn)


def convert(db_path: Path | str = DEFAULT_DB_PATH, dry_run: bool = False) -> dict:
    """
    Rewrites mp4moviez.db into the staging contract, in one transaction.

    The legacy rows are read and merged first, then written to `posts_new` /
    `releases_new` inside the transaction that also drops the old tables and
    renames, so any failure — including a count that does not match the plan —
    leaves the original tables exactly as they were found. `executescript` is
    avoided on purpose: it commits before it runs, and a migration that commits
    half its own DDL is not reversible.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.isolation_level = None
    conn.row_factory = sqlite3.Row
    result = {"converted": False, "posts": 0, "releases": 0, "sources": 0}
    try:
        tables = _legacy_tables(conn)
        if not {"posts", "releases"} <= tables:
            result["reason"] = "legacy posts/releases tables are not both present"
            return result
        if already_converted(conn):
            result["reason"] = "already carries canonical_key and a sources table"
            return result

        report = plan(conn)
        records = build_records(conn)
        result["plan"] = report
        if dry_run:
            result["reason"] = "dry run: nothing written"
            return result

        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            columns = POST_COLUMNS + ("scraped_at",)
            conn.executemany(
                f"INSERT INTO posts_new ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' * len(columns))});",
                [_values(r["post"], POST_COLUMNS) + (r["post"]["raw_meta"].get(
                    "legacy_created_at"),) for r in records])
            release_rows = []
            for record in records:
                release_rows.extend(
                    _values(rel, RELEASE_COLUMNS) for rel in record["releases"])
            conn.executemany(
                f"INSERT INTO releases_new ({', '.join(RELEASE_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(RELEASE_COLUMNS))});", release_rows)

            written_posts = conn.execute("SELECT COUNT(*) FROM posts_new").fetchone()[0]
            written_releases = conn.execute(
                "SELECT COUNT(*) FROM releases_new").fetchone()[0]
            if (written_posts, written_releases) != (report["converted_posts"],
                                                     report["converted_releases"]):
                raise sqlite3.Error(
                    f"count mismatch: posts {written_posts}/"
                    f"{report['converted_posts']}, releases {written_releases}/"
                    f"{report['converted_releases']}")

            conn.execute("DROP TABLE posts")
            conn.execute("DROP TABLE releases")
            conn.execute("ALTER TABLE posts_new RENAME TO posts")
            conn.execute("ALTER TABLE releases_new RENAME TO releases")
            for rel in conn.execute("SELECT id, bridge_url, quality FROM releases"):
                conn.execute(
                    """INSERT INTO sources (release_id, source_name, service,
                       resource_id, source_url, final_url, playback_type, status,
                       is_temporary, quality, last_checked)
                       VALUES (?, ?, ?, ?, ?, NULL, 'download', 'unverified', 0, ?,
                               NULL);""",
                    (rel["id"], f"mp4moviez {rel['quality'] or 'unknown'} download",
                     SITE, dl_id(rel["bridge_url"] or "") or None, rel["bridge_url"],
                     rel["quality"]))
            written_sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            if written_sources != written_releases:
                raise sqlite3.Error(f"sources {written_sources} != releases "
                                    f"{written_releases}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        for statement in _INDEX_STATEMENTS:
            conn.execute(statement)
        result.update({"converted": True, "posts": written_posts,
                       "releases": written_releases, "sources": written_sources})
        return result
    finally:
        conn.close()


def stats(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = _legacy_tables(conn)
        out = {"tables": sorted(tables), "converted": already_converted(conn)}
        if "posts" in tables:
            out["posts"] = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        if "releases" in tables:
            out["releases"] = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        if "sources" in tables:
            out["sources"] = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            out["by_status"] = {r[0]: r[1] for r in conn.execute(
                "SELECT status, COUNT(*) FROM sources GROUP BY 1")}
        if out["converted"]:
            out["media_type"] = {r[0]: r[1] for r in conn.execute(
                "SELECT media_type, COUNT(*) FROM posts GROUP BY 1")}
            out["is_18_plus"] = {r[0]: r[1] for r in conn.execute(
                "SELECT is_18_plus, COUNT(*) FROM posts GROUP BY 1")}
            out["posts_without_sources"] = conn.execute(
                "SELECT COUNT(*) FROM posts p WHERE NOT EXISTS "
                "(SELECT 1 FROM releases r WHERE r.post_canonical_key = "
                "p.canonical_key)").fetchone()[0]
            out["null_canonical_key"] = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE canonical_key IS NULL OR "
                "canonical_key = ''").fetchone()[0]
        return out
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(f"mp4moviez legacy-to-staging converter "
                     f"({LEGACY_DB_PATH} -> staging contract)"))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    parser.add_argument("command", nargs="?", default="check",
                        choices=["check", "convert", "stats"])
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args(argv)
    db = Path(args.db)
    if args.command == "stats":
        print(json.dumps(stats(db), indent=2, ensure_ascii=False))
        return 0
    if args.command == "check":
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            print(json.dumps(plan(conn), indent=2, ensure_ascii=False))
        finally:
            conn.close()
        return 0
    result = convert(db, dry_run=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("converted") or "already carries" in result.get("reason", "") \
        else 1


if __name__ == "__main__":
    sys.exit(main())
