#!/usr/bin/env python3
"""Backfill `posts.cast_names` on a merged catalog from the staging databases
that scraped it.

Why this file exists: three importers (10xflix, 9xmovies, desicinemas) scrape a
cast list into their staging `posts.cast_names`, and the merge carries it into
the ledger for new rows — but the ~31,000 catalog posts those sites already
contributed were merged before the column existed, so their rows are blank and
the app's cast row and actor search have nothing to show for them. This fills
the blanks from the staging rows that produced each catalog post.

The join is the page, not the title: a staging row's URL is the
`post_sources.url` the merge recorded for that page (the displaced page of a
retargeted row is kept there too), so the match is exact and a title's cast
never lands on a different title that happens to share a name. First
non-empty cast wins; a row that already has cast is never overwritten.

    python3 -S Fast_Fetch/backfill_cast.py <catalog.db>                 # report
    python3 -S Fast_Fetch/backfill_cast.py <catalog.db> --apply         # fill blanks

Report mode is read-only and safe any time. `--apply` writes the catalog, so
run it with the service stopped, or against a copy (the gate's backup + swap
covers the live one). The target must already have the `cast_names` column —
deploy the code first (`fast_fetch.init_db` adds it on start); without it the
script refuses to run rather than silently altering the schema.

Stdlib only.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def site_of(db_path: Path) -> str:
    """The site string the merge files a staging database under: the filename
    stem, lowercased, alphanumeric only (see `merge_catalogs`)."""
    return "".join(c for c in db_path.stem.casefold() if c.isalnum()) or "unknown"


def staging_dbs(staging_dir: Path, target: Path) -> list:
    """Every `*.db` in the directory that could hold staged posts, except the
    target catalog itself. WAL sidecars (`-shm`, `-wal`) are not databases."""
    return sorted(
        p for p in staging_dir.glob("*.db")
        if p.is_file() and p.resolve() != target.resolve()
    )


def cast_rows(conn: sqlite3.Connection, default_site: str) -> list:
    """`(url, site, cast_names)` for every staging post that carries a cast
    list, in row order — first row wins per catalog post. The URL column is
    `post_url` on the importers that name it that way, `url` on most others,
    `source_url` on mp4moviez; the site is the row's own when it has one,
    else the database's. A staging table with none of the three URL columns
    cannot be joined to the catalog, so it fails loudly instead of being
    silently skipped."""
    cols = _columns(conn, "posts")
    if "cast_names" not in cols:
        return []
    url_col = next((c for c in ("post_url", "url", "source_url")
                    if c in cols), None)
    if url_col is None:
        raise ValueError(
            "staging posts has no page-url column (looked for post_url,"
            " url, source_url); columns are: %s" % sorted(cols))
    site_col = "site" if "site" in cols else (
        "source_site" if "source_site" in cols else None)
    site_sql = f", {site_col}" if site_col else ""
    rows = conn.execute(
        f"SELECT {url_col}{site_sql}, cast_names FROM posts"
        " WHERE cast_names IS NOT NULL AND TRIM(cast_names) <> ''"
        " ORDER BY rowid"
    ).fetchall()
    out = []
    for row in rows:
        url = row[0]
        site = (row[1] if site_col else None) or default_site
        cast = row[-1]
        if url:
            out.append((url, site, cast))
    return out


def backfill(target: Path, staging_dir: Path, *, apply: bool = False,
             only_sites: frozenset | None = None) -> dict:
    """Fill blank `posts.cast_names` on the target from the staging databases.

    Returns the counts, per site and total. With `apply=False` nothing is
    written; with `apply=True` only blank rows are filled.
    """
    with sqlite3.connect(target) as conn:
        if "cast_names" not in _columns(conn, "posts"):
            raise ValueError(
                "target has no posts.cast_names column — deploy the code "
                "first (fast_fetch.init_db adds it on start)")
        stats: dict = {"sites": {}, "matched": 0, "filled": 0,
                       "already_filled": 0, "unmatched": 0}
        for db_path in staging_dbs(staging_dir, target):
            site = site_of(db_path)
            if only_sites is not None and site not in only_sites:
                continue
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as src:
                rows = cast_rows(src, site)
            if not rows:
                continue
            site_stats = {"staging_with_cast": len(rows), "matched": 0,
                          "filled": 0, "already_filled": 0, "unmatched": 0}
            for url, row_site, cast in rows:
                found = conn.execute(
                    "SELECT post_id FROM post_sources"
                    " WHERE source_site = ? AND url = ?",
                    (row_site, url),
                ).fetchone()
                if found is None:
                    site_stats["unmatched"] += 1
                    continue
                site_stats["matched"] += 1
                cur = conn.execute(
                    "UPDATE posts SET cast_names = ? WHERE id = ?"
                    " AND (cast_names IS NULL OR TRIM(cast_names) = '')",
                    (cast, found[0]),
                )
                if cur.rowcount:
                    site_stats["filled"] += 1
                else:
                    site_stats["already_filled"] += 1
            for key in ("matched", "filled", "already_filled", "unmatched"):
                stats[key] += site_stats[key]
            stats["sites"][site] = site_stats
        # The connection context manager commits on exit: report mode must
        # roll back first, or the "report" would write the fills it counted.
        if apply:
            conn.commit()
        else:
            conn.rollback()
        return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Fill blank posts.cast_names from staging databases.")
    parser.add_argument("db", type=Path, help="merged catalog database")
    parser.add_argument("--staging-dir", type=Path, default=None,
                        help="directory holding the staging *.db files "
                             "(default: the catalog's own directory)")
    parser.add_argument("--site", action="append", default=[],
                        help="only backfill this site (repeatable)")
    parser.add_argument("--apply", action="store_true",
                        help="write the fills; without it, report only")
    args = parser.parse_args(argv)
    staging_dir = args.staging_dir or args.db.parent
    try:
        stats = backfill(args.db, staging_dir, apply=args.apply,
                         only_sites=frozenset(args.site) or None)
    except ValueError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2
    verb = "filled" if args.apply else "would fill"
    for site, s in sorted(stats["sites"].items()):
        print(f"{site}: {s['staging_with_cast']} staging rows with cast, "
              f"{s['matched']} matched, {s[verb]} {s['filled']}, "
              f"{s['already_filled']} already filled, "
              f"{s['unmatched']} unmatched")
    print(f"total: matched {stats['matched']}, {verb} {stats['filled']}, "
          f"already filled {stats['already_filled']}, "
          f"unmatched {stats['unmatched']}")
    if not args.apply:
        print("report only — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
