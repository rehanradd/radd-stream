#!/usr/bin/env python3
"""Fast_Fetch/backfill_year_from_title.py — backfill blank posts.year from the title itself.

Gap A17 (2026-11-11). Several titles show a blank Year in the app even though
the year is sitting in the title ("Doraemon the Movie 2020: ...", "LEGO
Ninjago: Dragons Rising (2023)"). This script fills exactly those rows from
catalog data already on disk — no external lookup, no TMDb, no network.

The extractor is deliberately conservative, because a 4-digit number in a
title is not always the release year:

* The year must be a standalone token — not glued to a digit or a letter on
  either side. That rejects "Veergati (19950 Web" (1995 glued to a 0),
  "Dark Night 92026)" (2026 glued to a 9), "Mithra Mandali 2025Telugu"
  (2025 glued to a word), "Waking Up to Danger 20211" (2021 glued to a 1),
  "Another Us2021", "M S Dhoni The Untold Story2016", and "Ghost in the
  Shell SAC_2045" (2045 is part of the title, glued to an underscore).
* A year preceded by "in " is a story setting, not a release year — that
  rejects "Reborn in 2000", "Once More Love in 1995" and "Love Story in
  the 1970s" (the decade is also rejected by the token rule: 1970 followed
  by "s").
* The year must be in range 1900..max-year (default: the current year), so a
  fictional future year never lands as the release year.

Measured on the live catalog 2026-11-11: 10,214 posts have a blank year.
Only 44 of them carry any 19xx/20xx in the title, and this extractor fills
22 of those safely; the other 22 are glued or ambiguous and are reported as
skipped. The remaining 10,170 blank-year rows carry no year in the title at
all (4 have a tmdb_id, 345 have an imdb_id, 9,866 have neither) and need an
external metadata lookup — TMDb is owner-gated (commercial agreement
pending); Cinemeta via imdb_id covers 345 and is the same open question as
gap A1 (TMDb key vs Cinemeta-only). This script does not do that lookup.

Safety: `--dry-run` is the default and touches nothing. `--apply` writes
`posts.year` in a single transaction and reports the count. The live run is
parent-gated (backup first, like every live data job).

Stdlib only, like everything else in Fast_Fetch.

Usage:
    python3 -S Fast_Fetch/backfill_year_from_title.py --db <catalog.db>
    python3 -S Fast_Fetch/backfill_year_from_title.py --db <catalog.db> --apply
    python3 -S Fast_Fetch/backfill_year_from_title.py --db <catalog.db> --limit 100
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

import config

#: The default catalog, resolved through config (RADD_DB_PATH / DB_PATH) —
#: never a hardcoded absolute path (repo rule 5).
def _default_db() -> Path:
    return Path(config.DB_PATH)

#: A year must not touch a digit, a letter, or an underscore on either side.
#: Underscore matters: "SAC_2045" is a title fragment, not a release year.
_YEAR_RE = re.compile(r"(?<![0-9A-Za-z_])((?:19|20)[0-9]{2})(?![0-9A-Za-z_])")

#: A year preceded by "in " is a story setting ("Reborn in 2000"), not the
#: release year. Checked against the text immediately before the match.
_IN_PREFIX_RE = re.compile(r"\bin\s+$", re.IGNORECASE)


def extract_year_from_title(title, *, max_year: int) -> int | None:
    """Return the release year carried in ``title``, or None when there is none.

    Returns the first standalone 19xx/20xx token that is not a story-setting
    year ("in 1995") and lies in 1900..max_year. Glued or decade years are
    never returned.
    """
    if not title:
        return None
    for match in _YEAR_RE.finditer(title):
        year = int(match.group(1))
        if year < 1900 or year > max_year:
            continue
        if _IN_PREFIX_RE.search(title[: match.start()]):
            continue
        return year
    return None


def scan(conn, *, max_year: int, limit: int | None):
    """Yield (post_id, title, year) for every blank-year post with a safe year."""
    sql = "SELECT id, title FROM posts WHERE year IS NULL ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    found = []
    skipped = 0
    for post_id, title in rows:
        year = extract_year_from_title(title, max_year=max_year)
        if year is None:
            skipped += 1
            continue
        found.append((post_id, title, year))
    return found, skipped, len(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None,
                        help="catalog database path (default: config.DB_PATH)")
    parser.add_argument("--apply", action="store_true",
                        help="write posts.year (default is --dry-run)")
    parser.add_argument("--limit", type=int, default=None,
                        help="only scan the first N blank-year posts")
    parser.add_argument("--max-year", type=int,
                        default=time.localtime().tm_year,
                        help="newest year accepted (default: current year)")
    args = parser.parse_args(argv)
    db_path = Path(args.db).expanduser() if args.db else _default_db()

    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True) if not args.apply \
        else sqlite3.connect(str(db_path))
    try:
        found, skipped, scanned = scan(conn, max_year=args.max_year,
                                       limit=args.limit)
    finally:
        conn.close()

    print("scanned %d blank-year posts" % scanned)
    print("extracted a safe year for %d" % len(found))
    print("skipped %d (no standalone year in the title)" % skipped)
    for post_id, title, year in found[:20]:
        print("  %d: %r -> %d" % (post_id, title, year))
    if len(found) > 20:
        print("  ... and %d more" % (len(found) - 20))

    if not args.apply:
        print("dry-run: nothing written (pass --apply to write posts.year)")
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany("UPDATE posts SET year=? WHERE id=?",
                             [(year, post_id) for post_id, _, year in found])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    print("applied: updated year on %d posts" % len(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
