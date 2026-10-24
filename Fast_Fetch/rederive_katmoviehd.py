#!/usr/bin/env python3
"""Re-derive KatMovieHD page identities from the raw evidence already in the ledger.

Why this is not "fixing the ledger by hand": every value below is recomputed by
`import_katmoviehd.derive_katmoviehd_identity()` — the same ladder the live scraper runs —
from the page title and the site's own `sitemap_cache.raw_json` (its `categories` list).
Nothing is typed in, and the source staging database is opened read-only: the work happens
on a copy, so the original scrape stays auditable and this run is repeatable.

The old parser filed films as series (and read seasons out of apostrophe-s), which is what
put 2,118 "External media ID matches a record with a different media type" rows into
`merge_conflicts`. Re-deriving lets those pages merge as the work KatMovieHD says they are.

    ionice -c3 nice -n19 python3 -S Fast_Fetch/rederive_katmoviehd.py

Stdlib only. Batches its writes; never opens a socket.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import import_katmoviehd  # noqa: E402  (the ladder lives with the scraper)

DATA_DIR = Path("/home/ubuntu/radd-stream-data")
DEFAULT_SOURCE = DATA_DIR / "katmoviehd.db"
DEFAULT_TARGET = DATA_DIR / "katmoviehd_refreshed.db"
BATCH = 500

#: Two pages of one work collapse onto one `canonical_key` — exactly what the live
#: scraper's upsert does. The displaced page is not deleted silently: its URL and
#: its surviving rows are recorded here, in the copy, so the merge is auditable.
_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS rederive_merged (
    loser_id INTEGER, loser_url TEXT, survivor_id INTEGER, survivor_key TEXT,
    merged_at TEXT
)
"""


def _category_index(conn) -> dict:
    """One pass over `sitemap_cache`: slug → the site's own category list.

    A per-post `SELECT … WHERE loc LIKE '%/slug'` would full-scan 51k stored API
    records for every one of the 38k pages — an hour of I/O for no information.
    The whole map is a few MB, so it is read once and looked up in memory.
    """
    index: dict = {}
    for slug, raw in conn.execute("SELECT slug, raw_json FROM sitemap_cache"):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        cats = payload.get("categories") if isinstance(payload, dict) else None
        if isinstance(cats, list):
            index[str(slug or "")] = [str(c) for c in cats if c]
    for loc, raw in conn.execute("SELECT loc, raw_json FROM sitemap_cache"
                                 " WHERE slug IS NULL OR slug = ''"):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        cats = payload.get("categories") if isinstance(payload, dict) else None
        if isinstance(cats, list):
            index[_slug_of(str(loc or ""))] = [str(c) for c in cats if c]
    return index


def _slug_of(post_url: str, fallback: str = "") -> str:
    text = str(post_url or "").strip().rstrip("/")
    return (text.split("/")[-1] if text else "") or fallback


def _categories_for(index: dict, slug: str, post_url: str) -> list:
    return index.get(slug) or index.get(_slug_of(post_url)) or []


def _episode_post_ids(conn) -> set:
    """Pages that really do carry episode-numbered releases (the ladder's T4)."""
    return {int(row[0]) for row in conn.execute(
        "SELECT DISTINCT post_id FROM releases WHERE episode_number IS NOT NULL")}


def rederive(source: Path, target: Path, *, limit: int | None = None,
             verbose: bool = True) -> dict:
    """Copy `source` to `target`, then rewrite every post's identity from raw evidence."""
    source = Path(source)
    target = Path(target)
    if not source.exists():
        raise SystemExit(f"no staging database at {source}")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        if target.exists():
            target.unlink()
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)          # an isolated copy; the original is never written
            dst.executescript(_AUDIT_DDL)
            rows = dst.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            stats = {"posts": rows, "changed": 0, "type_flips": 0, "key_changes": 0,
                     "title_changes": 0, "year_changes": 0, "season_changes": 0,
                     "merged_away": 0, "no_evidence": 0, "errors": 0}
            dst.row_factory = sqlite3.Row
            started = time.time()
            categories_by_slug = _category_index(dst)
            episode_posts = _episode_post_ids(dst)
            batch = []
            query = "SELECT * FROM posts ORDER BY id" + (f" LIMIT {int(limit)}" if limit else "")
            for post in dst.execute(query):
                slug = _slug_of(post["post_url"] or "", post["canonical_key"] or "")
                categories = _categories_for(categories_by_slug, slug, post["post_url"] or "")
                if not categories and not post["original_title"]:
                    stats["no_evidence"] += 1
                    continue
                try:
                    identity = import_katmoviehd.derive_katmoviehd_identity(
                        post["original_title"] or post["title"] or "",
                        slug=slug,
                        categories=categories,
                        has_episode_releases=post["id"] in episode_posts,
                    )
                except (ValueError, TypeError, KeyError):
                    stats["errors"] += 1
                    continue
                changes = {}
                if identity["title"] and identity["title"] != post["title"]:
                    changes["title"] = identity["title"]
                    stats["title_changes"] += 1
                if identity["year"] not in (None, "") and str(identity["year"]) != str(post["year"] or ""):
                    changes["year"] = identity["year"]
                    stats["year_changes"] += 1
                if identity["media_type"] and identity["media_type"] != post["media_type"]:
                    changes["media_type"] = identity["media_type"]
                    stats["type_flips"] += 1
                if identity["canonical_key"] and identity["canonical_key"] != post["canonical_key"]:
                    changes["canonical_key"] = identity["canonical_key"]
                    stats["key_changes"] += 1
                if not changes:
                    continue
                batch.append((changes, post["id"]))
                stats["changed"] += 1
                if len(batch) >= BATCH:
                    _flush(dst, batch)
                    batch = []
                    if verbose:
                        print(f"  … {stats['changed']} rewritten", flush=True)
            _flush(dst, batch)
            dst.commit()
            stats["merged_away"] = dst.execute(
                "SELECT COUNT(*) FROM rederive_merged").fetchone()[0]
            stats["posts_after"] = dst.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            stats["elapsed_seconds"] = round(time.time() - started, 1)
            return stats
        finally:
            dst.close()
    finally:
        src.close()


def _flush(conn, batch) -> None:
    for changes, post_id in batch:
        new_key = changes.get("canonical_key")
        if new_key:
            survivor = conn.execute(
                "SELECT id, canonical_key, post_url FROM posts"
                " WHERE canonical_key = ? AND id <> ?", (new_key, post_id)).fetchone()
            if survivor is not None:
                # the key already belongs to another page: move the releases (sources
                # follow their release), record the displacement, drop the fork
                conn.execute("UPDATE releases SET post_id = ? WHERE post_id = ?",
                             (survivor["id"], post_id))
                conn.execute("INSERT INTO rederive_merged"
                             " (loser_id, loser_url, survivor_id, survivor_key, merged_at)"
                             " VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                             (post_id, conn.execute(
                                 "SELECT post_url FROM posts WHERE id = ?",
                                 (post_id,)).fetchone()[0], survivor["id"], new_key))
                conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
                continue
        names = sorted(changes)
        conn.execute(
            f"UPDATE posts SET {', '.join(f'{name} = ?' for name in names)},"
            " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            tuple(changes[name] for name in names) + (post_id,))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    p.add_argument("--limit", type=int, default=None, help="only the first N posts (smoke run)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    stats = rederive(args.source, args.target, limit=args.limit)
    report = Path(str(args.target) + ".rederive.json")
    report.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True))
    print(f"report: {report}")
    print(f"next:   python3 -S Fast_Fetch/merge_fleet.py  # after it finishes, re-merge"
          f" {args.target.name} into the catalog")
    return 0


if __name__ == "__main__":
    sys.exit(main())
