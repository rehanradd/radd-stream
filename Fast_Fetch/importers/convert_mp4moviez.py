#!/usr/bin/env python3
"""
convert_mp4moviez.py — Rebuild the legacy mp4moviez crawl as a staging vault.

The first mp4moviez pass wrote a private schema (posts.source_url, releases.url,
no canonical identity, no source rows). merge_catalogs.py refuses it. This
converter reads that database read-only and writes a new vault in the shared
staging shape (posts/releases/sources/sitemap_cache) so the normal merge can
carry it into the unified catalog.

Identity comes from the page slug, not the H1 dump: titles on this site are
stored as "Download <title> <year> ... HDRip -", which would poison the
canonical key. The slug carries the title and a year marker
("marshals-(2026)-season-2-...-60944"), so the key is generated from that.

Rows that are not works (sitemaps, category shelves) have no year in the slug
and are skipped with a counted reason instead of becoming catalog entries.

Stdlib only. Usage:
    python3 -S Fast_Fetch/importers/convert_mp4moviez.py \
        --source /home/ubuntu/radd-stream-data/mp4moviez.db \
        --target /home/ubuntu/radd-stream-data/mp4moviez_staging.db
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch

SITE = "mp4moviez"

STAGING_SCHEMA = """
CREATE TABLE sitemap_cache (
    loc TEXT PRIMARY KEY,
    lastmod TEXT,
    slug TEXT,
    scraped INTEGER DEFAULT 0,
    raw_json TEXT,
    error_count INTEGER DEFAULT 0
);
CREATE TABLE posts (
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
    source_site TEXT DEFAULT 'mp4moviez',
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_meta TEXT
);
CREATE TABLE releases (
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
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    source_name TEXT,
    service TEXT,
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'url',
    status TEXT DEFAULT 'active',
    is_temporary INTEGER DEFAULT 0,
    quality TEXT,
    last_checked INTEGER,
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
CREATE INDEX idx_mp4moviez_posts_slug ON posts(slug);
CREATE INDEX idx_mp4moviez_posts_year ON posts(year);
CREATE INDEX idx_mp4moviez_releases_key ON releases(post_canonical_key);
CREATE INDEX idx_mp4moviez_sources_release ON sources(release_id);
CREATE INDEX idx_mp4moviez_sources_status ON sources(status);
"""

_YEAR_IN_SLUG = re.compile(r"[-\(](19\d{2}|20\d{2})(?=[-\)]|$)")
# "vijaypath-1(994)" is a real slug on this site; read it as 1994, not a shelf.
_MALFORMED_YEAR = re.compile(r"(?<!\d)1\((\d{3})\)")
# The structured marker also cuts the title for pages whose slug carries no year.
_WORK_MARKER = re.compile(
    r"(?:^|[-\(])(?:all-sea(?:s)?on|sea(?:s)?on-\d+|episode-\d+|s\d{1,2}(?:e\d{1,3})?(?:-|$))"
)
_SEASON = re.compile(r"(?:^|[-\(])sea(?:s)?on-(\d+)")
_EPISODE = re.compile(r"(?:^|[-\(])episode-(\d+)")
_SXXEYY = re.compile(r"(?:^|[-\(])s(\d{1,2})(?:e(\d{1,3}))?(?:-|$)")
# "seaon-1" and "dubbed-series" are real spellings on this site.
_SERIES_MARKER = re.compile(
    r"(?:^|[-\(])(?:all-sea(?:s)?on|sea(?:s)?on-\d+|episode-\d+|s\d{1,2}(?:e\d{1,3})?(?:-|$))"
    r"|-series(?:-|$)|k-drama"
)
_ACRONYMS = {"wwe": "WWE", "ufc": "UFC", "nba": "NBA", "tv": "TV", "hd": "HD",
             "hbo": "HBO", "bbc": "BBC", "ii": "II", "iii": "III"}


def _slug_parts(url: str) -> str:
    """Returns the decoded last path segment without its .html suffix."""
    path = urllib.parse.urlsplit(url or "").path
    base = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
    return re.sub(r"\.html?$", "", base, flags=re.IGNORECASE)


def _find_year_span(base: str, year: int | None) -> tuple[int, int, int | None] | None:
    """Locates the year marker in a slug, preferring the year the page recorded."""
    if year:
        match = re.search(rf"[-\(]{int(year)}(?=[-\)]|$)", base)
        if match:
            return match.start(), match.end(), int(year)
    match = _YEAR_IN_SLUG.search(base)
    if match:
        return match.start(), match.end(), int(match.group(1))
    return None


def _display_title(raw: str) -> str:
    words = [w for w in re.split(r"[\s\-_]+", raw) if w]
    return " ".join(_ACRONYMS.get(w.lower(), w[:1].upper() + w[1:]) for w in words)


def parse_slug(url: str, year: int | None = None) -> dict | None:
    """
    Derives title/year/media type from a post URL.

    Returns None for pages that are not works (sitemaps, category shelves,
    static pages). A slug without a year is still a work when it carries
    season/episode structure; older series pages were indexed that way.
    """
    slug = _slug_parts(url)
    if not slug or slug.lower().startswith("latest-"):
        return None
    normalized = _MALFORMED_YEAR.sub(r"1\1", slug)
    span = _find_year_span(normalized, year)
    if span is not None:
        start, _end, slug_year = span
        raw_title = normalized[:start].strip("-")
        is_series = bool(_SERIES_MARKER.search(normalized))
    else:
        marker = _WORK_MARKER.search(normalized)
        if marker is None:
            return None
        raw_title = normalized[: marker.start()].strip("-")
        slug_year = None
        is_series = True
    if not raw_title:
        return None
    season = episode = None
    if is_series:
        m = _SEASON.search(normalized)
        if m:
            season = int(m.group(1))
        m = _EPISODE.search(normalized)
        if m:
            episode = int(m.group(1))
        m = _SXXEYY.search(normalized)
        if m:
            season = season if season is not None else int(m.group(1))
            if m.group(2):
                episode = episode if episode is not None else int(m.group(2))
    return {
        "slug": slug,
        "title": _display_title(raw_title),
        "raw_title": raw_title.replace("-", " "),
        "year": slug_year,
        "media_type": "series" if is_series else "movie",
        "season": season,
        "episode": episode,
    }


def _resource_id(url: str) -> str | None:
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    except ValueError:
        return None
    values = query.get("id")
    return values[0] if values else None


def _first(rows: list[dict], field: str):
    for row in rows:
        if row.get(field):
            return row[field]
    return None


def _read_legacy(source: sqlite3.Connection, limit: int | None,
                 require_releases: bool) -> tuple[list[dict], dict]:
    """Reads the legacy rows and groups published posts by canonical key."""
    stats = {
        "legacy_posts": 0,
        "legacy_posts_without_releases": 0,
        "skipped_not_a_work": 0,
        "skipped_listing": 0,
        "skipped_unknown_key": 0,
        "skipped_by_limit": 0,
        "skipped_require_releases": 0,
        "legacy_releases": 0,
        "releases_without_url": 0,
        "releases_on_skipped_posts": 0,
        "releases_on_skipped_groups": 0,
        "releases_on_limited_groups": 0,
    }
    posts = source.execute("SELECT * FROM posts ORDER BY id ASC").fetchall()
    stats["legacy_posts"] = len(posts)
    releases = {}
    for row in source.execute("SELECT post_id, quality, url FROM releases ORDER BY id ASC"):
        releases.setdefault(row["post_id"], []).append(
            {"quality": (row["quality"] or "").strip().lower() or "unknown",
             "url": (row["url"] or "").strip()})
    stats["legacy_releases"] = sum(len(v) for v in releases.values())
    stats["legacy_posts_without_releases"] = sum(
        1 for post in posts if not releases.get(post["id"]))

    groups: dict[str, dict] = {}
    for post in posts:
        url = post["source_url"] or ""
        rel_rows = releases.get(post["id"], [])
        rels = [r for r in rel_rows if r["url"]]
        stats["releases_without_url"] += len(rel_rows) - len(rels)
        parsed = parse_slug(url, post["year"])
        if parsed is None:
            stats["releases_on_skipped_posts"] += len(rels)
            if "latest" in url.lower():
                stats["skipped_listing"] += 1
            else:
                stats["skipped_not_a_work"] += 1
            continue
        title = parsed["raw_title"].strip()
        if not title:
            stats["releases_on_skipped_posts"] += len(rels)
            stats["skipped_unknown_key"] += 1
            continue
        key = fast_fetch.generate_canonical_key(title, parsed["year"])
        if not key or key == "unknown":
            stats["releases_on_skipped_posts"] += len(rels)
            stats["skipped_unknown_key"] += 1
            continue
        member = {
            "legacy_id": post["id"],
            "url": url,
            "slug": parsed["slug"],
            "title": parsed["title"],
            "year": parsed["year"],
            "media_type": parsed["media_type"],
            "season": parsed["season"],
            "episode": parsed["episode"],
            "poster_url": post["poster_url"] or None,
            "genres": post["genres"] or None,
            "duration": post["duration"] or None,
            "languages": post["languages"] or None,
            "cast_names": post["cast_names"] or None,
            "synopsis": post["synopsis"] or None,
            "tags": post["tags"] or None,
            "is_18_plus": int(post["is_18_plus"] or 0),
            "page_title": post["clean_title"] or None,
            "releases": rels,
        }
        group = groups.setdefault(key, {"key": key, "members": []})
        group["members"].append(member)

    if require_releases:
        kept = {}
        for key, group in groups.items():
            if any(m["releases"] for m in group["members"]):
                kept[key] = group
            else:
                stats["skipped_require_releases"] += len(group["members"])
                stats["releases_on_skipped_groups"] += sum(
                    len(m["releases"]) for m in group["members"])
        groups = kept
    ordered = sorted(groups.values(), key=lambda g: min(m["legacy_id"] for m in g["members"]))
    if limit and len(ordered) > limit:
        for group in ordered[limit:]:
            stats["skipped_by_limit"] += len(group["members"])
            stats["releases_on_limited_groups"] += sum(
                len(m["releases"]) for m in group["members"])
        ordered = ordered[:limit]
    stats["grouped_keys"] = len(groups)
    stats["selected_keys"] = len(ordered)
    return ordered, stats


def _build_post(group: dict, stats: dict) -> tuple[dict, list[dict]]:
    members = group["members"]
    # The most complete page wins the catalog slot; the others become provenance.
    survivor = max(members, key=lambda m: (len(m["releases"]), -m["legacy_id"]))
    if len(members) > 1:
        stats["collapsed_posts"] += len(members) - 1
    order = [survivor] + [m for m in members if m is not survivor]
    seen: set[tuple[str, str]] = set()
    releases = []
    for member in order:
        for rel in member["releases"]:
            signature = (rel["quality"], rel["url"])
            if signature in seen:
                stats["duplicate_releases_dropped"] += 1
                continue
            seen.add(signature)
            releases.append({
                "quality": rel["quality"],
                "resolution": rel["quality"],
                "url": rel["url"],
                "season": member["season"],
                "episode": member["episode"],
            })
    # One episode page labelled "movie" must not outvote a season pack: any
    # series evidence in the group makes the work a series.
    media_type = ("series" if any(m["media_type"] == "series" for m in members)
                  else survivor["media_type"])
    seasons = sorted({m["season"] for m in members if m["season"] is not None})
    post = {
        "canonical_key": group["key"],
        "title": survivor["title"],
        "clean_title": survivor["title"],
        "year": survivor["year"],
        "media_type": media_type,
        "seasons": json.dumps(seasons) if seasons else None,
        "poster_url": _first(order, "poster_url"),
        "genres": _first(order, "genres"),
        "duration": _first(order, "duration"),
        "languages": _first(order, "languages"),
        "cast_names": _first(order, "cast_names"),
        "synopsis": _first(order, "synopsis"),
        "url": survivor["url"],
        "slug": survivor["slug"],
        "is_18_plus": max(m["is_18_plus"] for m in members),
        "raw_meta": json.dumps({
            "legacy_post_ids": [m["legacy_id"] for m in members],
            "legacy_urls": [m["url"] for m in members] if len(members) > 1 else None,
            "page_title": survivor["page_title"],
            "tags": survivor["tags"],
        }),
    }
    return post, releases


class ConservationError(RuntimeError):
    def __init__(self, message: str, stats: dict) -> None:
        super().__init__(message)
        self.stats = stats


def _accounting(stats: dict) -> dict:
    """Every legacy row and release must be written or carry a counted reason."""
    stats["posts_accounted"] = (
        stats["posts_written"] + stats["collapsed_posts"]
        + stats["skipped_not_a_work"] + stats["skipped_listing"]
        + stats["skipped_unknown_key"] + stats["skipped_by_limit"]
        + stats["skipped_require_releases"])
    stats["releases_accounted"] = (
        stats["sources_written"] + stats["duplicate_releases_dropped"]
        + stats["releases_without_url"] + stats["releases_on_skipped_posts"]
        + stats["releases_on_skipped_groups"] + stats["releases_on_limited_groups"])
    stats["posts_conserved"] = stats["posts_accounted"] == stats["legacy_posts"]
    stats["releases_conserved"] = (
        stats["releases_accounted"] == stats["legacy_releases"])
    return stats


def _identity_lines(stats: dict) -> list[str]:
    ok = "OK" if stats["posts_conserved"] else "MISMATCH"
    release_ok = "OK" if stats["releases_conserved"] else "MISMATCH"
    return [
        f"[=] posts {stats['legacy_posts']} = staged {stats['posts_written']}"
        f" + collapsed {stats['collapsed_posts']} + skipped"
        f" {stats['skipped_not_a_work'] + stats['skipped_listing'] + stats['skipped_unknown_key'] + stats['skipped_by_limit'] + stats['skipped_require_releases']}"
        f" (not-a-work {stats['skipped_not_a_work']},"
        f" listing {stats['skipped_listing']},"
        f" unknown-key {stats['skipped_unknown_key']},"
        f" by-limit {stats['skipped_by_limit']},"
        f" require-releases {stats['skipped_require_releases']})"
        f" [{stats['posts_accounted']}/{stats['legacy_posts']} {ok}]",
        f"[=] releases {stats['legacy_releases']} = sources {stats['sources_written']}"
        f" + deduped {stats['duplicate_releases_dropped']}"
        f" + no-url {stats['releases_without_url']}"
        f" + on-skipped-posts {stats['releases_on_skipped_posts']}"
        f" + on-skipped-groups {stats['releases_on_skipped_groups']}"
        f" + beyond-limit {stats['releases_on_limited_groups']}"
        f" [{stats['releases_accounted']}/{stats['legacy_releases']} {release_ok}]",
    ]


def convert(source_path: Path, target_path: Path, limit: int | None = None,
            require_releases: bool = False) -> dict:
    source_path = Path(source_path)
    target_path = Path(target_path)
    if source_path.resolve() == target_path.resolve():
        raise ValueError("Refusing to overwrite the legacy source database")
    if not source_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_path}")

    src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        groups, stats = _read_legacy(src, limit, require_releases)
        sitemap_rows = src.execute("SELECT url, lastmod, processed FROM sitemap_cache").fetchall()
    finally:
        src.close()

    stats.update({
        "posts_written": 0, "releases_written": 0, "sources_written": 0,
        "sitemap_rows": len(sitemap_rows), "collapsed_posts": 0,
        "duplicate_releases_dropped": 0, "posts_18_plus": 0,
        "staged_without_releases": 0,
        "skipped_unknown_key": stats.get("skipped_unknown_key", 0),
    })

    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target_path.name + ".", suffix=".tmp",
                                    dir=str(target_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            conn.executescript(STAGING_SCHEMA)
            conn.executemany(
                "INSERT INTO sitemap_cache (loc, lastmod, scraped, error_count)"
                " VALUES (?, ?, ?, 0)",
                [(r["url"], r["lastmod"], 1 if r["processed"] else 0) for r in sitemap_rows],
            )
            for group in groups:
                post, releases = _build_post(group, stats)
                conn.execute(
                    """
                    INSERT INTO posts (
                        canonical_key, title, clean_title, year, media_type,
                        poster_url, genres, duration, languages, cast_names,
                        synopsis, seasons, url, slug, is_18_plus, source_site,
                        raw_meta
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (post["canonical_key"], post["title"], post["clean_title"],
                     post["year"], post["media_type"], post["poster_url"],
                     post["genres"], post["duration"], post["languages"],
                     post["cast_names"], post["synopsis"], post["seasons"],
                     post["url"], post["slug"], post["is_18_plus"], SITE,
                     post["raw_meta"]),
                )
                stats["posts_written"] += 1
                stats["posts_18_plus"] += post["is_18_plus"]
                if not releases:
                    stats["staged_without_releases"] += 1
                for rel in releases:
                    cur = conn.execute(
                        """
                        INSERT INTO releases (
                            post_canonical_key, label, quality, resolution,
                            season_number, episode_number
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (post["canonical_key"], rel["quality"], rel["quality"],
                         rel["resolution"], rel["season"], rel["episode"]),
                    )
                    stats["releases_written"] += 1
                    conn.execute(
                        """
                        INSERT INTO sources (
                            release_id, source_name, service, resource_id,
                            source_url, playback_type, status, is_temporary, quality
                        ) VALUES (?, ?, ?, ?, ?, 'download', 'unverified', 0, ?)
                        """,
                        (cur.lastrowid, SITE, SITE, _resource_id(rel["url"]),
                         rel["url"], rel["quality"]),
                    )
                    stats["sources_written"] += 1
            conn.commit()
        finally:
            conn.close()
        _accounting(stats)
        if not (stats["posts_conserved"] and stats["releases_conserved"]):
            raise ConservationError(
                "Converted row counts do not match the legacy input: "
                + " | ".join(_identity_lines(stats)), stats)
        os.replace(tmp_path, target_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    stats["target"] = str(target_path)
    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert the legacy mp4moviez database into a staging vault.")
    parser.add_argument("--source",
                        default="/home/ubuntu/radd-stream-data/mp4moviez.db",
                        help="Legacy mp4moviez database (read-only)")
    parser.add_argument("--target",
                        default="/home/ubuntu/radd-stream-data/mp4moviez_staging.db",
                        help="Staging vault to write")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stage only the first N canonical works (bounded pilot)")
    parser.add_argument("--require-releases", action="store_true",
                        help="Keep only works that carry at least one release")
    parser.add_argument("--force", action="store_true",
                        help="Replace the target if it already exists")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = Path(args.target)
    if target.exists() and not args.force:
        print(f"[!] {target} exists; rerun with --force to rebuild it", file=sys.stderr)
        return 2
    try:
        stats = convert(Path(args.source), target, limit=args.limit,
                        require_releases=args.require_releases)
    except ConservationError as exc:
        print(json.dumps(exc.stats, indent=2, sort_keys=True))
        for line in _identity_lines(exc.stats):
            print(line, file=sys.stderr)
        print(f"[!] {exc}", file=sys.stderr)
        return 3
    print(json.dumps(stats, indent=2, sort_keys=True))
    for line in _identity_lines(stats):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
