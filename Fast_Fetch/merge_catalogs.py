#!/usr/bin/env python3
"""
merge_catalogs.py — Merges a dedicated per-site staging database into the unified catalog.

Standard Library only. Zero external pip packages.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
from pathlib import Path

# Add Fast_Fetch directory to sys.path
BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch


def _fmt_size(value) -> str | None:
    """Renders a byte count as the human-readable string the unified catalog stores."""
    if value in (None, ""):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return None


def _source_family(src_conn: sqlite3.Connection) -> str:
    tables = {r[0] for r in src_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "download_sources" in tables:
        return "unified"
    if "sources" in tables:
        return "staging"
    raise ValueError("Source database has neither download_sources nor sources table")


def _pick(row: sqlite3.Row, *names, default=None):
    """Returns the first present column value, tolerating per-site schema drift."""
    keys = row.keys()
    for name in names:
        if name in keys and row[name] is not None:
            return row[name]
    return default


def _post_release_rows(src_conn: sqlite3.Connection, post: sqlite3.Row) -> list[sqlite3.Row]:
    """Fetches a post's releases under either staging linkage (post_id or canonical key)."""
    rcols = {r[1] for r in src_conn.execute("PRAGMA table_info(releases)")}
    if "post_id" in rcols:
        return src_conn.execute(
            "SELECT * FROM releases WHERE post_id = ? ORDER BY id", (post["id"],)).fetchall()
    if "post_canonical_key" in rcols:
        return src_conn.execute(
            "SELECT * FROM releases WHERE post_canonical_key = ? ORDER BY id",
            (post["canonical_key"],)).fetchall()
    return []


def _collect_staging_post(src_conn: sqlite3.Connection, post: sqlite3.Row,
                          default_site: str = "unknown") -> dict:
    """Maps a per-site staging database (posts/releases/sources) onto the unified shape."""
    url = _pick(post, "post_url", "url", default="")
    if not url:
        raw_meta = _pick(post, "raw_meta")
        if raw_meta:
            try:
                url = (json.loads(raw_meta) or {}).get("loc", "")
            except (json.JSONDecodeError, TypeError):
                url = ""
    # A staging database knows which site it holds even when its rows do not;
    # leaving those as "unknown" loses the attribution the API ranks and filters by.
    site = _pick(post, "site", "source_site", default=default_site) or default_site
    media_type = (_pick(post, "media_type", "content_type", default="movie") or "movie").lower()
    backdrops = _pick(post, "backdrop_url")
    language = _pick(post, "languages", "language", default="Unknown")

    releases = []
    for rel in _post_release_rows(src_conn, post):
        src_rows = src_conn.execute(
            "SELECT * FROM sources WHERE release_id = ? ORDER BY id", (rel["id"],)
        ).fetchall()
        releases.append({
            "release_title": _pick(rel, "label", "release_title"),
            "quality": rel["quality"],
            "codec": rel["codec"],
            "size": _fmt_size(_pick(rel, "size_bytes", "size")),
            "languages": _pick(rel, "audio_languages", "languages"),
            "season": _pick(rel, "season_number", "season"),
            "episode": _pick(rel, "episode_number", "episode"),
            "intermediate_url": _pick(rel, "bridge_url", "intermediate_url"),
            "source_site": site,
            "sources": [
                {
                    "source_name": s["source_name"],
                    "service": s["service"],
                    "resource_id": s["resource_id"],
                    "source_url": s["source_url"],
                    "final_url": s["final_url"],
                    "playback_type": _pick(s, "playback_type", default="url"),
                    "is_temporary": _pick(s, "is_temporary", default=0),
                    "status": _pick(s, "status", default="active"),
                }
                for s in src_rows
            ],
        })

    return {
        "url": url,
        "slug": urllib.parse.urlsplit(url).path.strip("/").replace(".html", ""),
        "title": _pick(post, "clean_title", "title", default=""),
        "clean_title": _pick(post, "clean_title", "title", default=""),
        "year": _pick(post, "year"),
        "content_type": "movie" if media_type == "movie" else "series",
        "seasons": _pick(post, "seasons"),
        "poster_url": _pick(post, "poster_url"),
        "backdrop_urls": json.dumps([backdrops]) if backdrops else _pick(post, "backdrop_urls"),
        "imdb_rating": _pick(post, "rating", "imdb_rating"),
        "genres": _pick(post, "genres"),
        "synopsis": _pick(post, "synopsis"),
        "is_18_plus": _pick(post, "is_18_plus", default=0),
        "is_animated": _pick(post, "is_animated", default=0),
        "source_site": site,
        "industry": _pick(post, "industry", default="Unknown"),
        "country": _pick(post, "country", default="Unknown"),
        "language": language,
        "canonical_key": _pick(post, "canonical_key"),
        "tmdb_id": _pick(post, "tmdb_id"),
        "imdb_id": _pick(post, "imdb_id"),
        "releases": releases,
    }


def _collect_unified_post(src_conn: sqlite3.Connection, post: sqlite3.Row) -> dict:
    """Reads a source database that already uses the unified releases/download_sources schema."""
    rel_rows = src_conn.execute(
        "SELECT * FROM releases WHERE post_id = ? ORDER BY id",
        (post["id"],),
    ).fetchall()

    releases = []
    for rel in rel_rows:
        ds_rows = src_conn.execute(
            "SELECT * FROM download_sources WHERE release_id = ?",
            (rel["id"],),
        ).fetchall()
        releases.append({
            "release_title": rel["release_title"],
            "quality": rel["quality"],
            "codec": rel["codec"],
            "size": rel["size"],
            "languages": rel["languages"],
            "season": rel["season"],
            "episode": rel["episode"],
            "intermediate_url": rel["intermediate_url"],
            "source_site": rel["source_site"],
            "sources": [
                {
                    "source_name": ds["source_name"],
                    "service": ds["service"],
                    "resource_id": ds["resource_id"],
                    "source_url": ds["source_url"],
                    "final_url": ds["final_url"],
                    "playback_type": ds["playback_type"] if "playback_type" in ds.keys() else "url",
                    "is_temporary": ds["is_temporary"],
                    "status": ds["status"] if "status" in ds.keys() else "active",
                }
                for ds in ds_rows
            ],
        })

    return {
        "url": post["url"],
        "slug": post["slug"],
        "title": post["title"],
        "clean_title": post["clean_title"],
        "year": post["year"],
        "content_type": post["content_type"],
        "seasons": post["seasons"],
        "poster_url": post["poster_url"],
        "backdrop_urls": post["backdrop_urls"] if "backdrop_urls" in post.keys() else None,
        "imdb_rating": post["imdb_rating"] if "imdb_rating" in post.keys() else None,
        "genres": post["genres"] if "genres" in post.keys() else None,
        "synopsis": post["synopsis"] if "synopsis" in post.keys() else None,
        "is_18_plus": post["is_18_plus"],
        "is_animated": post["is_animated"] if "is_animated" in post.keys() else 0,
        "source_site": post["source_site"],
        "industry": post["industry"] if "industry" in post.keys() else "Unknown",
        "country": post["country"] if "country" in post.keys() else "Unknown",
        "language": post["language"] if "language" in post.keys() else "Unknown",
        "canonical_key": post["canonical_key"],
        "tmdb_id": post["tmdb_id"],
        "imdb_id": post["imdb_id"],
        "releases": releases,
    }


_SERIES_TYPES = {"series", "complete_season", "ongoing_season"}


def _media_family(content_type) -> str:
    return "series" if str(content_type or "").strip().casefold() in _SERIES_TYPES else "movie"


def _same_media_type(anchor: dict, post_data: dict) -> bool:
    return _media_family(anchor["content_type"]) == _media_family(post_data.get("content_type"))


def _has_episode_evidence(post_data: dict) -> bool:
    """True when the scraped releases carry season/episode structure, whatever the scraper labelled the page."""
    return any(
        str(rel.get("season") or "").strip() or str(rel.get("episode") or "").strip()
        for rel in post_data.get("releases", [])
    )


def _ensure_conflict_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_db TEXT,
            url TEXT,
            canonical_key TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def merge_site_db(source_db_path: Path, target_db_path: Path, verbose: bool = True) -> dict[str, int]:
    """
    Merges all posts, post_sources, releases, and download_sources from source_db into target_db.
    Maintains canonical identity matching across sites.
    """
    if not source_db_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_db_path}")

    default_site = "".join(c for c in source_db_path.stem.casefold() if c.isalnum()) or "unknown"

    stats = {
        "posts_merged": 0,
        "posts_created": 0,
        "releases_merged": 0,
        "sources_merged": 0,
        "posts_conflicted": 0,
    }

    # Ensure target DB is initialized
    fast_fetch.DB_PATH = target_db_path
    fast_fetch.init_db()

    src_conn = sqlite3.connect(source_db_path)
    src_conn.row_factory = sqlite3.Row
    family = _source_family(src_conn)

    try:
        # Fetch all master posts from source DB
        post_cols = {r[1] for r in src_conn.execute("PRAGMA table_info(posts)")}
        if "id" in post_cols:
            src_posts = src_conn.execute("SELECT * FROM posts ORDER BY id").fetchall()
        else:
            src_posts = src_conn.execute("SELECT rowid AS id, * FROM posts ORDER BY rowid").fetchall()
        total = len(src_posts)
        if verbose:
            print(
                f"[*] Found {total} posts in source database {source_db_path.name} "
                f"({family} schema)",
                flush=True,
            )

        key_to_post: dict[str, dict] = {}
        conflicts: list[tuple[str, str, str]] = []
        for idx, post in enumerate(src_posts, 1):
            if family == "staging":
                post_data = _collect_staging_post(src_conn, post, default_site)
                sources_pages = []
            else:
                post_data = _collect_unified_post(src_conn, post)
                sources_pages = list(src_conn.execute(
                    "SELECT * FROM post_sources WHERE post_id = ?",
                    (post["id"],),
                ).fetchall())

            # Several staging rows can describe the same title from different pages.
            # Retarget later rows onto the URL that already created the catalog record,
            # otherwise the identity lookup would create siblings and then refuse to merge.
            key = post_data.get("canonical_key")
            original_url = post_data.get("url", "")
            # Provenance stays with the page that was scraped even when the row is
            # retargeted onto an existing catalog record below.
            post_data["origin_url"] = original_url
            anchor = key_to_post.get(key) if key else None
            if anchor is not None and original_url and anchor["url"] != original_url:
                # The same title reached us from several pages (one page per season,
                # one page per episode pack, ...). Retarget onto the URL that already
                # owns the catalog record so the pages collapse into one work and the
                # displaced page is kept as a source page. Never collapse when the two
                # rows disagree about whether this is a movie or a series unless one of
                # them carries real season/episode evidence — guessing wrong here would
                # mis-file a whole film as a season.
                if _same_media_type(anchor, post_data):
                    post_data["url"] = anchor["url"]
                elif anchor["episode_evidence"] or _has_episode_evidence(post_data):
                    post_data["content_type"] = anchor["content_type"]
                    post_data["url"] = anchor["url"]
                if post_data["url"] == anchor["url"]:
                    sources_pages.append({
                        "source_site": post_data["source_site"],
                        "url": original_url,
                        "source_title": post_data["title"],
                        "source_slug": post_data["slug"],
                    })
            elif anchor is None and key:
                key_to_post[key] = {
                    "url": original_url,
                    "content_type": post_data.get("content_type") or "movie",
                    "episode_evidence": _has_episode_evidence(post_data),
                }

            releases = post_data["releases"]

            try:
                target_post_id = fast_fetch.save_scraped_data(
                    post_data,
                    enrich_metadata=False,
                    ensure_db=False,
                )
            except (ValueError, sqlite3.Error) as exc:
                # One bad identity must not abandon the rest of the site.
                conflicts.append((post_data.get("url", ""), key or "", str(exc)[:300]))
                if verbose:
                    print(f"[!] conflict @ {idx}: {post_data.get('url', '')} — {exc}", flush=True)
                continue

            # Record post sources
            with fast_fetch.get_db() as conn:
                for sp in sources_pages:
                    conn.execute(
                        """
                        INSERT INTO post_sources (post_id, source_site, url, source_title, source_slug)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(source_site, url) DO UPDATE SET
                            source_title = COALESCE(excluded.source_title, post_sources.source_title),
                            source_slug = COALESCE(excluded.source_slug, post_sources.source_slug),
                            last_seen_at = CURRENT_TIMESTAMP
                        WHERE post_sources.post_id = excluded.post_id
                        """,
                        (target_post_id, sp["source_site"], sp["url"], sp["source_title"], sp["source_slug"]),
                    )
                conn.commit()

            stats["posts_merged"] += 1
            stats["releases_merged"] += len(releases)
            stats["sources_merged"] += sum(len(r["sources"]) for r in releases)

            if verbose and (idx % 100 == 0 or idx == total):
                print(f"[{idx}/{total}] Merged: posts={stats['posts_merged']}, releases={stats['releases_merged']}, sources={stats['sources_merged']}", flush=True)

        if conflicts:
            with fast_fetch.get_db() as conn:
                _ensure_conflict_table(conn)
                for url, key, err in conflicts:
                    conn.execute(
                        "INSERT INTO merge_conflicts (source_db, url, canonical_key, error) VALUES (?, ?, ?, ?)",
                        (str(source_db_path), url, key, err),
                    )
                conn.commit()
        stats["posts_conflicted"] = len(conflicts)
        if verbose and conflicts:
            print(f"[!] {len(conflicts)} identity conflict(s) recorded in merge_conflicts", flush=True)

    finally:
        src_conn.close()

    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge per-site staging database into unified catalog.")
    parser.add_argument("source_db", help="Path to per-site source database (e.g., multimovies.db)")
    parser.add_argument(
        "--target-db",
        default=None,
        help="Path to unified catalog target database (defaults to Fast_Fetch/fast_fetch.db)",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    source_path = Path(args.source_db).resolve()
    target_path = Path(args.target_db or os.environ.get("RADD_DB_PATH") or (BASE_DIR / "fast_fetch.db")).resolve()
    print(f"[*] Merging {source_path} -> {target_path}", flush=True)
    stats = merge_site_db(source_path, target_path, verbose=True)
    print(f"[✓] Merge complete! Summary: {stats}", flush=True)


if __name__ == "__main__":
    main()
