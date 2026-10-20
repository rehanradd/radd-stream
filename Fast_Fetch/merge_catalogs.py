#!/usr/bin/env python3
"""
merge_catalogs.py — Merges a dedicated per-site staging database into the unified catalog.

Standard Library only. Zero external pip packages.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Add Fast_Fetch directory to sys.path
BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch


def merge_site_db(source_db_path: Path, target_db_path: Path, verbose: bool = True) -> dict[str, int]:
    """
    Merges all posts, post_sources, releases, and download_sources from source_db into target_db.
    Maintains canonical identity matching across sites.
    """
    if not source_db_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_db_path}")

    stats = {
        "posts_merged": 0,
        "posts_created": 0,
        "releases_merged": 0,
        "sources_merged": 0,
    }

    # Ensure target DB is initialized
    fast_fetch.DB_PATH = target_db_path
    fast_fetch.init_db()

    src_conn = sqlite3.connect(source_db_path)
    src_conn.row_factory = sqlite3.Row

    try:
        # Fetch all master posts from source DB
        src_posts = src_conn.execute("SELECT * FROM posts ORDER BY id").fetchall()
        total = len(src_posts)
        if verbose:
            print(f"[*] Found {total} posts in source database {source_db_path.name}", flush=True)

        for idx, post in enumerate(src_posts, 1):
            post_id = post["id"]

            # Fetch source pages
            sources_pages = src_conn.execute(
                "SELECT * FROM post_sources WHERE post_id = ?",
                (post_id,),
            ).fetchall()

            # Fetch releases and their download_sources
            releases = []
            rel_rows = src_conn.execute(
                "SELECT * FROM releases WHERE post_id = ?",
                (post_id,),
            ).fetchall()

            for rel in rel_rows:
                rel_id = rel["id"]
                ds_rows = src_conn.execute(
                    "SELECT * FROM download_sources WHERE release_id = ?",
                    (rel_id,),
                ).fetchall()

                download_sources = [
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
                ]

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
                    "sources": download_sources,
                })

            post_data = {
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

            # Save into target DB using canonical deduplication
            target_post_id = fast_fetch.save_scraped_data(
                post_data,
                enrich_metadata=False,
                ensure_db=False,
            )

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

            stats["posts_merged"] += 1
            stats["releases_merged"] += len(releases)
            stats["sources_merged"] += sum(len(r["sources"]) for r in releases)

            if verbose and (idx % 100 == 0 or idx == total):
                print(f"[{idx}/{total}] Merged: posts={stats['posts_merged']}, releases={stats['releases_merged']}, sources={stats['sources_merged']}", flush=True)

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
