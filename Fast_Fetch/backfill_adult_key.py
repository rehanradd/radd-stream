#!/usr/bin/env python3
"""Reconcile `posts.is_18_plus` across rows that share one work identity, and report
what that law still cannot reach.

Why this file exists: the adult rule (`redact.adult_clause`) is applied per **row**,
while a work's identity is per **key**. `save_scraped_data()` folded the flag with
`is_18_plus = MAX(is_18_plus, ?)` on the single row it touched, so a `canonical_key`
that already carried several rows never reconciled. Measured in production: 442 keys
hold both a flagged row and an unflagged one, and **455 unflagged rows are therefore
publicly served while their sibling is hidden** — one film, two addresses, and the
public list answers for the one nobody flagged.

Two steps in one file, because the flag has two homes, exactly like
`backfill_animated_flag.py`:

* the **ledger** (`posts.is_18_plus`) — what `/api/v1/posts` filters on;
* the **projection** (`cat_works.is_18_plus`) — what the v2 API and the app filter on.

The ledger step is `fast_fetch.inherit_key_adult()`, one bounded statement per key,
each resolved by `idx_posts_canonical_key` rather than by scanning the table — the
same rule the ingest path now runs, so the repair and the law cannot disagree.

The projection step reconciles the second home without a rebuild: a full
`catalog_v2.project()` of this catalog is hours of one CPU, and `cat_work_sites`
already keeps every post folded into its work, so the roll-up column can be updated
from the projection's own rows. It is the same `any()` rule the projector applies.
It then **deletes the adult-excluded counters** `/api/v1/stats` reads: those stamps
were taken before the flip, and `_get_cached_stats()` treats a missing stamp as
"count it live" rather than publishing a stale public number. That invalidation is
the honest half of this shortcut.

Read-only by default. The residual it reports is measured and never written: those are
works flagged on one site and served by another under a *different* key, which no
key-level law can reach. Closing them means re-keying stored rows — a reviewed
migration with its own snapshot, not a side effect of this one.

    python3 -S Fast_Fetch/backfill_adult_key.py <db.path>                        # report
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --apply                # ledger
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --apply --projection   # + cat_*/stats

Stdlib only. Never run it while a projection is reading the same database.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import fast_fetch
import redact

#: The keys that hold both a flagged row and an unflagged one, with the number of
#: exposed (unflagged) rows under each. `unknown` is excluded: it is the shared bucket
#: every titleless payload lands in, not one work, and propagating from it would hide
#: unrelated titles on the strength of one bad page.
EXPOSED_KEYS_SQL = """
    SELECT canonical_key,
           SUM(CASE WHEN COALESCE(is_18_plus, 0) = 0 THEN 1 ELSE 0 END) AS exposed
      FROM posts
     WHERE canonical_key IS NOT NULL AND canonical_key <> '' AND canonical_key <> 'unknown'
     GROUP BY canonical_key
    HAVING MAX(COALESCE(is_18_plus, 0)) = 1
       AND MIN(COALESCE(is_18_plus, 0)) = 0
     ORDER BY exposed DESC
"""

PUBLIC_TOTAL_SQL = f"SELECT COUNT(*) FROM posts WHERE {redact.adult_clause('posts')}"

#: A work the projection hides while a ledger row folded into it is still public —
#: flagged on one site, served under another key. Read-only evidence for the residual.
#: `DISTINCT p.id` because one post can be folded through several pages, and the
#: number being reported is rows a caller can read, not join pairs.
RESIDUAL_SQL = """
    SELECT COUNT(DISTINCT p.id) FROM cat_works w
      JOIN cat_work_sites s ON s.work_id = w.id
      JOIN posts p ON p.id = s.post_id
     WHERE w.is_18_plus = 1 AND COALESCE(p.is_18_plus, 0) = 0
"""

#: The same `any()` roll-up the projector applies, reached through the projection's
#: own work→post table.
PROJECTION_FLAG_SQL = """
    UPDATE cat_works SET is_18_plus = 1
     WHERE is_18_plus = 0
       AND EXISTS (SELECT 1 FROM cat_work_sites s JOIN posts p ON p.id = s.post_id
                   WHERE s.work_id = cat_works.id AND COALESCE(p.is_18_plus, 0) = 1)
"""

#: Every adult-excluded counter `/api/v1/stats` publishes. A flag flip invalidates all
#: of them at once, and the endpoint's all-or-nothing stamp rule turns that into a
#: live recount instead of a stale public number.
SAFE_STAMP_KEYS = ("works_safe", "adult_works", "releases_safe", "links_safe",
                   "links_active_safe", "links_resumable_safe", "links_temporary_safe",
                   "links_by_state_safe")


def _has_table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)).fetchone() is not None


def public_total(conn) -> int:
    """What `/api/v1/posts` claims the catalog holds — every non-flagged row."""
    return int(conn.execute(PUBLIC_TOTAL_SQL).fetchone()[0] or 0)


def exposed_keys(conn) -> list[tuple[str, int]]:
    return [(str(row[0]), int(row[1] or 0)) for row in conn.execute(EXPOSED_KEYS_SQL)]


def residual_exposures(conn) -> int | None:
    """Rows still public under a *different* key than the flagged copy.

    `None` when the projection is not in this database, which is a different answer
    from zero: without `cat_works` there is no cross-site identity to measure against.
    """
    if not (_has_table(conn, "cat_works") and _has_table(conn, "cat_work_sites")):
        return None
    return int(conn.execute(RESIDUAL_SQL).fetchone()[0] or 0)


def apply_ledger(conn, keys) -> int:
    """Flag every exposed sibling, key by key. Returns the rows flipped.

    `keys` is required: the caller has to have seen the exposure list before any
    write, which is the whole point of the report/`--apply` split.
    """
    flipped = 0
    for key in keys:
        flipped += fast_fetch.inherit_key_adult(conn, key)
    return flipped


def apply_projection(conn) -> tuple[int, int]:
    """Fold the ledger's flags into `cat_works`, then retire the safe stamps.

    Returns (works hidden, stamp keys deleted).
    """
    if not (_has_table(conn, "cat_works") and _has_table(conn, "cat_work_sites")):
        print("[!] no projection in this database — run catalog_v2.project() instead")
        return (0, 0)
    cur = conn.execute(PROJECTION_FLAG_SQL)
    hidden = max(int(cur.rowcount or 0), 0)
    dropped = invalidate_safe_stamp(conn)
    return (hidden, dropped)


def invalidate_safe_stamp(conn) -> int:
    """Delete the adult-excluded counters `/api/v1/stats` reads.

    After a flip they describe the catalog as it was. `_get_cached_stats()` answers
    from a live recount the moment a stamp is missing, so deleting them costs one
    counting query and buys a number that cannot be stale.
    """
    if not _has_table(conn, "cat_projection_meta"):
        return 0
    marks = ",".join("?" * len(SAFE_STAMP_KEYS))
    cur = conn.execute(
        f"DELETE FROM cat_projection_meta WHERE key IN ({marks})", SAFE_STAMP_KEYS)
    return cur.rowcount


def report(db_path: Path, *, apply: bool = False, projection: bool = False) -> dict:
    started = time.time()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        before = public_total(conn)
        keys = exposed_keys(conn)
        exposed_rows = sum(count for _, count in keys)
        summary = {
            "db": str(db_path),
            "public_total_before": before,
            "exposed_keys": len(keys),
            "exposed_rows": exposed_rows,
            "residual_other_key": residual_exposures(conn),
            "residual_after": None,
            "flipped": 0,
            "works_hidden_by_projection": 0,
            "stamps_dropped": 0,
            "public_total_after": before,
        }
        print(f"[i] {db_path}: public posts {before:,}; "
              f"{len(keys):,} keys hold a flagged and an unflagged row; "
              f"{exposed_rows:,} rows are exposed")
        if summary["residual_other_key"] is None:
            print("[i] residual (same work, different key): no projection in this db")
        else:
            print(f"[i] residual (same work, different key): "
                  f"{summary['residual_other_key']:,} rows — not touched here")
        for key, count in keys[:10]:
            print(f"      {key}  exposed={count}")
        if len(keys) > 10:
            print(f"      … {len(keys) - 10} more keys")

        if not apply:
            print("[i] report only; pass --apply to reconcile the ledger")
            return summary

        summary["flipped"] = apply_ledger(conn, keys=[k for k, _ in keys])
        after = public_total(conn)
        summary["public_total_after"] = after
        if summary["flipped"] != before - after:
            print(f"[!] VERIFICATION FAILED: flipped {summary['flipped']} rows but the "
                  f"public total moved {before - after}", file=sys.stderr)
            conn.rollback()
            return summary
        print(f"[✓] ledger: {summary['flipped']:,} rows flagged; "
              f"public total {before:,} -> {after:,} (exactly the rows flipped)")
        summary["residual_after"] = residual_exposures(conn)
        if summary["residual_after"] is not None:
            print(f"[i] residual after the flip: {summary['residual_after']:,} rows — "
                  f"the same work flagged on one site and served under another key, "
                  f"which this law cannot reach")
        if projection:
            hidden, dropped = apply_projection(conn)
            summary["works_hidden_by_projection"] = hidden
            summary["stamps_dropped"] = dropped
            print(f"[✓] projection: {hidden:,} works hidden; {dropped:,} "
                  f"adult-excluded stamps retired, so /api/v1/stats recounts live "
                  f"until the next rebuild")
        conn.commit()
        return summary
    finally:
        print(f"[i] {time.time() - started:.1f}s", flush=True)
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="write the ledger reconciliation (default: report only)")
    parser.add_argument("--projection", action="store_true",
                        help="with --apply, also fold flags into cat_works")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"[!] no such database: {args.db}", file=sys.stderr)
        return 2
    report(args.db, apply=args.apply, projection=args.projection)
    return 0


if __name__ == "__main__":
    sys.exit(main())
