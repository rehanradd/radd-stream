#!/usr/bin/env python3
"""Backfill `posts.is_animated` across a database that was ingested before the
flag had one owner.

Why this file exists: `is_animated` drives the app's Anime filter and the v2
`animated` facet, and it used to be written by exactly one page parser. Every
other scraper's payload carried a literal `0`, so the 130,016-post merged catalog
held ONE animated title. New ingests are flagged by `fast_fetch.save_scraped_data()`
through the same `looks_animated()` rule; this repairs what is already stored.

It is deliberately two steps in one file, because the flag has two homes:

* the **ledger** (`posts.is_animated`) — what the rule recognises;
* the **projection** (`cat_works.is_animated`, `cat_works.work_type`) — what the
  API actually filters on.

`--projection` reconciles the second without a rebuild. A full `catalog_v2.project()`
of this catalog is hours of one CPU, and a roll-up column that the projection can
re-derive from its own rows (`cat_work_sites` keeps every post folded into a work)
does not need one; `catalog_v2.apply_evidence()` already works this way for link
measurements. The two UPDATEs below are exactly the rule the projector applies —
`is_animated` over *any* page of the work, and `work_type_for()` turning a series or
an unknown-type work into `anime` once it is flagged — and
`test_backfill_animated_flag.py` proves the shortcut and a fresh projection agree.

    python3 -S Fast_Fetch/backfill_animated_flag.py <db.path>                        # report
    python3 -S Fast_Fetch/backfill_animated_flag.py <db.path> --apply               # ledger
    python3 -S Fast_Fetch/backfill_animated_flag.py <db.path> --apply --projection   # + cat_*

Stdlib only. Never run it while a projection is reading the same database.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import fast_fetch

BATCH = 5000

#: The columns the rule is allowed to read. `genres` is JSON text and `industry`
#: is what `classify_media()` derives from the same vocabulary, so both are honest
#: evidence. `post_sources.source_site` is provenance, and it is read here because
#: this is the ledger, where provenance is allowed to exist: a post that has a page
#: on an anime-only site is animation by construction. None of it is ever emitted.
SELECT_SQL = """
    SELECT id, title, clean_title, slug, genres, industry, is_animated
    FROM posts
    WHERE is_animated = 0
"""

SITE_EVIDENCE_SQL = """
    SELECT DISTINCT ps.post_id
    FROM post_sources ps
    WHERE ps.source_site IN ({marks}) AND ps.post_id IN (SELECT id FROM posts WHERE is_animated = 0)
"""

UPDATE_SQL = "UPDATE posts SET is_animated = 1 WHERE id = ?"

#: Flag a projected work when any page folded into it is animated in the ledger —
#: the same `any()` roll-up `catalog_v2.project()` does, reached through the
#: projection's own work→post table.
PROJECTION_FLAG_SQL = """
    UPDATE cat_works SET is_animated = 1
    WHERE is_animated = 0
      AND EXISTS (SELECT 1 FROM cat_work_sites s JOIN posts p ON p.id = s.post_id
                  WHERE s.work_id = cat_works.id AND p.is_animated = 1)
"""

#: `work_type_for()` turns an animated series (or a work whose content type never
#: resolved) into `anime`; nothing else changes. Applied after the flag, so the
#: facet and the `type=anime` route answer from the same fact.
PROJECTION_TYPE_SQL = """
    UPDATE cat_works SET work_type = 'anime'
    WHERE is_animated = 1 AND work_type IN ('series', 'unknown')
"""

PROJECTION_COUNT_SQL = """
    SELECT COUNT(*) FROM cat_works w
    WHERE w.is_animated = 0 AND EXISTS (
        SELECT 1 FROM cat_work_sites s JOIN posts p ON p.id = s.post_id
        WHERE s.work_id = w.id AND p.is_animated = 1)
"""

PROJECTION_RETYPES_SQL = """
    SELECT COUNT(*) FROM cat_works WHERE is_animated = 1
      AND work_type IN ('series', 'unknown')
"""


def _site_evidence(conn: sqlite3.Connection) -> set[int]:
    """Post ids that have at least one page on an anime-only site."""
    names = sorted(fast_fetch.ANIME_ONLY_SITES)
    try:
        rows = conn.execute(SITE_EVIDENCE_SQL.format(marks=",".join("?" * len(names))), names)
    except sqlite3.Error:
        return set()          # a database with no `post_sources` table has no site evidence
    return {r[0] for r in rows}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def has_ledger_posts(conn: sqlite3.Connection) -> bool:
    columns = {r[1] for r in conn.execute("PRAGMA table_info(posts)")}
    return "is_animated" in columns and "title" in columns


def scan(conn: sqlite3.Connection, *, apply: bool, progress: bool = True) -> dict:
    """Flag every stored post the shared animation rule recognises.

    Returns the counts; with `apply=False` nothing is written, so the same
    function is the dry run and the real run.
    """
    if not has_ledger_posts(conn):
        raise ValueError("this database has no posts.is_animated column")
    started = time.time()
    seen = flagged = 0
    from_sites = _site_evidence(conn)
    flagged = len(from_sites)
    ids = list(from_sites)
    for row in conn.execute(SELECT_SQL):
        if row["id"] in from_sites:
            continue
        seen += 1
        if not fast_fetch.looks_animated(
            row["clean_title"] or row["title"] or "",
            row["slug"] or "",
            row["genres"] or "",
            row["industry"] or "",
        ):
            continue
        flagged += 1
        ids.append(row["id"])
        if apply and len(ids) >= BATCH:
            conn.executemany(UPDATE_SQL, [(i,) for i in ids])
            conn.commit()
            ids.clear()
        if progress and seen % 25000 == 0:
            print(f"[.] scanned {seen} unflagged posts, {flagged} match "
                  f"({time.time() - started:.0f}s)", flush=True)
    if apply and ids:
        conn.executemany(UPDATE_SQL, [(i,) for i in ids])
        conn.commit()
    if apply:
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
    return {"scanned": seen, "flagged": flagged, "applied": bool(apply)}


def has_projection(conn: sqlite3.Connection) -> bool:
    """True when this database has a `cat_*` layer to reconcile."""
    tables = {r[1] for r in conn.execute("PRAGMA table_info(cat_works)")}
    return "is_animated" in tables and "work_type" in tables


def reconcile_projection(conn: sqlite3.Connection, *, apply: bool) -> dict:
    """Carry the ledger's animation flag into the projection, without a rebuild.

    Reports the same counts it would write, so one call is both the dry run and the
    real one. A database with no `cat_*` layer is an honest zero, not an error:
    projecting is the other step's job.
    """
    if not has_projection(conn):
        return {"projection": False, "works_to_flag": 0, "works_to_retype": 0,
                "applied": False}
    to_flag = conn.execute(PROJECTION_COUNT_SQL).fetchone()[0]
    if apply:
        conn.execute(PROJECTION_FLAG_SQL)
        flagged = conn.execute("SELECT changes()").fetchone()[0]
    else:
        flagged = to_flag
    to_retype = conn.execute(PROJECTION_RETYPES_SQL).fetchone()[0]
    if apply:
        conn.execute(PROJECTION_TYPE_SQL)
        retyped = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
    else:
        retyped = to_retype
    return {"projection": True, "works_to_flag": int(flagged),
            "works_to_retype": int(retyped), "applied": bool(apply)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path, help="SQLite database to repair in place")
    parser.add_argument("--apply", action="store_true",
                        help="write the flag (default: report only)")
    parser.add_argument("--projection", action="store_true",
                        help="also reconcile cat_works, instead of re-projecting")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"[!] no database at {args.db}", file=sys.stderr)
        return 2
    conn = _connect(args.db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        result = scan(conn, apply=args.apply)
        already = conn.execute("SELECT COUNT(*) FROM posts WHERE is_animated = 1").fetchone()[0]
        print(f"[{'✓' if args.apply else '·'}] {args.db.name}: {total} posts, "
              f"{result['scanned']} were unflagged, {result['flagged']} match the rule, "
              f"{already} flagged in total"
              + ("" if args.apply else " (dry run — pass --apply to write)"))
        if args.projection:
            fixed = reconcile_projection(conn, apply=args.apply)
            if not fixed["projection"]:
                print("[·] no cat_* projection in this database — nothing to reconcile")
            else:
                print(f"[{'✓' if args.apply else '·'}] projection: "
                      f"{fixed['works_to_flag']} works flagged animated, "
                      f"{fixed['works_to_retype']} re-typed to anime"
                      + ("" if args.apply else " (dry run)"))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
