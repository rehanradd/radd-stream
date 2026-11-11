#!/usr/bin/env python3
"""Fast_Fetch/backfill_categories.py — categorize posts into the panel's 10 genre categories.

Gap A18 (2026-11-11). The panel seeded 10 genre categories (action,
adventure, animation, comedy, crime, drama, horror, romance, sci-fi,
thriller) but `category_works` is empty, so ~150,753 posts sit in "others".
This script fills `category_works` from catalog data already on disk — the
post's own `genres` field — by a fixed rule, never by inventing a genre.

The rule, and its limits:

* `posts.genres` is messy: JSON arrays (`["Action", "Drama"]`), plain strings
  ("Action", "Drama", "Web Series"), comma-separated ("Action, Horror"),
  lowercase variants ("drama"), dub/language markers ("unofficial-dubbed",
  "tamil-dubbed", "yoruba"), and adult markers ("18", "Hot", "Erotic").
  Each token is normalized (strip, lowercase) and looked up in
  CATEGORY_TOKENS. A post lands in every category any of its tokens maps to.
* Tokens that are not one of the 10 categories (web series, dubbed markers,
  language tags, "Reality", ...) map to nothing — those posts stay "others".
  The script reports how many stay and why; it never guesses a genre.
* Adult law: only posts with `is_18_plus = 0` are categorized (all 10
  categories are non-adult, `is_adult_only = 0`). A post whose genre tokens
  carry an adult marker ("18", "adult", "erotic", "hot", "xxx", "porn") is
  skipped entirely — a post tagged Erotic must not surface in a public
  Romance rail. Both skips are counted and reported.
* `category_works.work_id` is a `posts.id` (the panel's `get_work` reads the
  posts table by id). Inserts are idempotent: existing (category_id, work_id)
  pairs are read first and never re-inserted (the table has no unique
  constraint, so the guard lives here, not in the schema).

Safety: `--dry-run` is the default and touches nothing — it reads the catalog
(read-only) and the panel DB (read-only) and reports per-category counts plus
how many posts stay "others". `--apply` writes `category_works` in a single
transaction. The live run is parent-gated (panel DB backup first, like every
live data job).

Stdlib only, like everything else in Fast_Fetch.

Usage:
    python3 -S Fast_Fetch/backfill_categories.py --dry-run
    python3 -S Fast_Fetch/backfill_categories.py --apply
    python3 -S Fast_Fetch/backfill_categories.py --catalog-db <catalog.db> --panel-db <admin_v2.db> --limit 1000
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import config

#: Panel DB default: the live panel's data-live database. Override with
#: --panel-db or RADD_PANEL_DB. The panel is VM-only (not in git), so there
#: is no config entry for it; the deployment path is the default.
DEFAULT_PANEL_DB = os.environ.get(
    "RADD_PANEL_DB",
    "/home/ubuntu/admin-v2-workspace-20261105/data-live/admin_v2.db")

#: The 10 seeded panel categories, by key.
CATEGORY_KEYS = ("action", "adventure", "animation", "comedy", "crime",
                 "drama", "horror", "romance", "sci-fi", "thriller")

#: Genre token (normalized: stripped, lowercased) -> category key.
#: "anime" maps to animation: anime is animation, not a new genre.
CATEGORY_TOKENS = {
    "action": "action",
    "adventure": "adventure",
    "animation": "animation",
    "anime": "animation",
    "comedy": "comedy",
    "crime": "crime",
    "drama": "drama",
    "horror": "horror",
    "romance": "romance",
    "sci-fi": "sci-fi",
    "science fiction": "sci-fi",
    "sci fi": "sci-fi",
    "scifi": "sci-fi",
    "thriller": "thriller",
}

#: A genre token that marks adult content. Any post carrying one is skipped
#: entirely, even if it also carries a mappable token.
ADULT_TOKENS = frozenset({"18", "adult", "erotic", "hot", "xxx", "porn",
                          "pornographic", "nsfw"})


def parse_genre_tokens(genres) -> list[str]:
    """Normalize a posts.genres value into lowercase genre tokens.

    Accepts a JSON array (`["Action", "Drama"]`), a comma-separated string
    ("Action, Horror"), or a single plain string ("Action"). Blank, "[]",
    and unparseable values yield [].
    """
    if not genres:
        return []
    text = str(genres).strip()
    if not text or text == "[]":
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return [str(t).strip().lower() for t in parsed if str(t).strip()]
        # Malformed JSON array: fall through to comma-split.
    return [t.strip().lower() for t in text.split(",") if t.strip()]


def is_adult_tagged(tokens) -> bool:
    """True when any genre token is an adult marker."""
    return any(t in ADULT_TOKENS for t in tokens)


def categories_for_tokens(tokens) -> set[str]:
    """The category keys a token list maps to (empty when nothing maps)."""
    return {CATEGORY_TOKENS[t] for t in tokens if t in CATEGORY_TOKENS}


def read_categories(panel_conn) -> dict[str, int]:
    """Enabled panel categories as {key: id}."""
    rows = panel_conn.execute(
        "SELECT id, key FROM categories WHERE is_enabled=1").fetchall()
    return {key: cid for cid, key in rows}


def read_existing(panel_conn) -> set[tuple[int, int]]:
    """Existing (category_id, work_id) pairs, so inserts stay idempotent."""
    return {(cid, wid) for cid, wid in panel_conn.execute(
        "SELECT category_id, work_id FROM category_works").fetchall()}


def read_max_positions(panel_conn) -> dict[int, int]:
    """Highest position per category, so new rows append after existing ones."""
    return {cid: (mx if mx is not None else -1) for cid, mx in panel_conn.execute(
        "SELECT category_id, MAX(position) FROM category_works GROUP BY category_id").fetchall()}


def plan(catalog_conn, panel_conn, *, limit: int | None):
    """Compute the assignments. Returns (inserts, report).

    inserts is a list of (category_id, work_id) to add. report is a dict of
    counts. Nothing is written here.
    """
    categories = read_categories(panel_conn)
    missing = [k for k in CATEGORY_KEYS if k not in categories]
    existing = read_existing(panel_conn)

    sql = "SELECT id, genres, is_18_plus FROM posts ORDER BY id"
    if limit is not None:
        rows = catalog_conn.execute(sql + " LIMIT ?", (limit,)).fetchall()
    else:
        rows = catalog_conn.execute(sql).fetchall()

    inserts: list[tuple[int, int]] = []
    per_category: Counter = Counter()
    categorized_posts: set[int] = set()
    # Initialize every count to 0: a Counter only carries keys that were
    # incremented, and main() reads all of them (on a fresh panel DB,
    # already_present is 0 and the key would otherwise be missing).
    report = Counter({
        "scanned": len(rows),
        "adult_flagged": 0,
        "adult_tagged": 0,
        "no_genre": 0,
        "unmapped": 0,
        "already_present": 0,
    })
    for post_id, genres, is_18_plus in rows:
        if is_18_plus:
            report["adult_flagged"] += 1
            continue
        tokens = parse_genre_tokens(genres)
        if not tokens:
            report["no_genre"] += 1
            continue
        if is_adult_tagged(tokens):
            report["adult_tagged"] += 1
            continue
        cats = categories_for_tokens(tokens)
        if not cats:
            report["unmapped"] += 1
            continue
        new_here = False
        for key in sorted(cats):
            cid = categories.get(key)
            if cid is None:
                continue  # category missing from the panel; counted below
            if (cid, post_id) in existing:
                report["already_present"] += 1
                continue
            inserts.append((cid, post_id))
            per_category[key] += 1
            new_here = True
        if new_here:
            categorized_posts.add(post_id)
    report["missing_categories"] = len(missing)
    report["new_posts"] = len(categorized_posts)
    report["new_assignments"] = len(inserts)
    report["stays_others"] = (report["no_genre"] + report["unmapped"]
                              + report["adult_flagged"] + report["adult_tagged"])
    return inserts, dict(report), dict(per_category), missing


def apply_inserts(panel_db: str, inserts, *, now: int | None = None) -> int:
    """Insert (category_id, work_id) rows into the panel DB. Returns the count."""
    if not inserts:
        return 0
    now = now if now is not None else int(time.time())
    conn = sqlite3.connect(panel_db)
    try:
        positions = read_max_positions(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            for cid, wid in inserts:
                positions[cid] = positions.get(cid, -1) + 1
                conn.execute(
                    "INSERT INTO category_works "
                    "(category_id, work_id, position, created_by, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (cid, wid, positions[cid], 0, now))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return len(inserts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-db", type=Path, default=None,
                        help="catalog database path (default: config.DB_PATH)")
    parser.add_argument("--panel-db", type=Path, default=None,
                        help="panel database path (default: %s)" % DEFAULT_PANEL_DB)
    parser.add_argument("--apply", action="store_true",
                        help="write category_works (default is --dry-run)")
    parser.add_argument("--limit", type=int, default=None,
                        help="only scan the first N posts")
    args = parser.parse_args(argv)
    catalog_db = Path(args.catalog_db).expanduser() if args.catalog_db \
        else Path(config.DB_PATH)
    panel_db = Path(args.panel_db).expanduser() if args.panel_db \
        else Path(DEFAULT_PANEL_DB)

    catalog_conn = sqlite3.connect("file:%s?mode=ro" % catalog_db, uri=True)
    panel_conn = sqlite3.connect("file:%s?mode=ro" % panel_db, uri=True)
    try:
        inserts, report, per_category, missing = plan(
            catalog_conn, panel_conn, limit=args.limit)
    finally:
        catalog_conn.close()
        panel_conn.close()

    print("scanned %d posts" % report["scanned"])
    print("new assignments: %d across %d posts" % (
        report["new_assignments"], report["new_posts"]))
    for key in CATEGORY_KEYS:
        if per_category.get(key):
            print("  %-10s +%d" % (key, per_category[key]))
    if missing:
        print("WARNING: categories missing from the panel DB: %s" % ", ".join(missing))
    print("already categorized: %d assignments" % report["already_present"])
    print("stays 'others': %d (no genre %d, unmapped genre %d, adult-flagged %d, "
          "adult-tagged %d)" % (
              report["stays_others"], report["no_genre"], report["unmapped"],
              report["adult_flagged"], report["adult_tagged"]))

    if not args.apply:
        print("dry-run: nothing written (pass --apply to write category_works)")
        return 0
    count = apply_inserts(str(panel_db), inserts)
    print("applied: inserted %d category_works rows" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
