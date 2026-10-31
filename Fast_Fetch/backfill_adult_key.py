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

Read-only by default. The residual it used to leave unwritten — a work flagged on one
site and served by another under a *different* key — is reachable without re-keying
anything, by grouping on `(clean_title, year)` instead of `canonical_key`. It must be
reached only with `--corroborate`, because propagation multiplies one row's verdict across
its siblings and a stored flag is not always anybody's evidence: measured on the live
catalog 2026-10-30 (`--audit`), 10,816 of 15,068 flags cannot be reproduced by
`is_adult_title()` at all, and the works they hide are mostly mainstream. Folding across
those would hide 3,490 further rows; `--corroborate` hides the 12 that stand on
reproducible evidence.

Do not read the unconditional `--apply` as safe merely because it is older. It propagates
asserted-only flags too, one key at a time; it was gated before provenance was measurable,
and `--audit` is what tells you how much of a catalog is in that state. Re-keying stored
rows stays out of scope: `find_existing_post` raises once a `canonical_key` matches more
than one record, so rewriting 150k keys into the title+year scheme would put thousands of
works over that threshold and break ingest.

    python3 -S Fast_Fetch/backfill_adult_key.py <db.path>                        # report
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --audit                 # provenance
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --corroborate           # report
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --corroborate --apply   # fold
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --undo                  # reverse it
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


def mem_headroom_mb(meminfo: str = "/proc/meminfo") -> int:
    """MemAvailable in MB — the pass below holds the whole ledger in memory, so on this
    one-CPU box it is a load decision, not just a correctness one."""
    try:
        with open(meminfo) as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def audit_flags(conn, *, samples: int = 12) -> dict:
    """Split every stored flag into what the central rule reproduces and what it cannot.

    The second half is not "false positives" — a title with no adult vocabulary can still
    name an adult work — it is flags nobody can re-derive from the row's own text, which
    is exactly the population that may not be *propagated* to other rows and the worklist
    a human has to review. Read-only.
    """
    rows = conn.execute(
        "SELECT %s FROM posts WHERE COALESCE(is_18_plus, 0) = 1"
        % ", ".join(fast_fetch.ADULT_FOLD_FIELDS)).fetchall()
    reproducible = [row for row in rows if fast_fetch.adult_rule_agrees(row)]
    asserted = [row for row in rows if not fast_fetch.adult_rule_agrees(row)]
    return {
        "flagged": len(rows),
        "reproducible": len(reproducible),
        "asserted_only": len(asserted),
        "samples": [(row["id"], str(row["source_site"] or ""),
                     str(row["clean_title"] or row["title"] or "")[:60])
                    for row in asserted[:samples]],
    }


def run_audit(db_path: Path) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        out = audit_flags(conn)
    finally:
        conn.close()
    print(f"[i] {db_path}: {out['flagged']:,} rows carry the flag; "
          f"{out['reproducible']:,} reproduce from `is_adult_title()`, "
          f"{out['asserted_only']:,} are asserted-only and cannot be propagated")
    for post_id, site, title in out["samples"]:
        print(f"      id={post_id} site={site or '?':<14} {title!r}")
    return 0


def run_corroborated(db_path: Path, *, apply: bool, undo: bool = False) -> int:
    """The precision-gated fold: propagate only what the shared rule can defend.

    `--undo` first reverses this pass's own flips and leaves any flag that has since
    gained independent evidence (the rule agrees, or a sibling under the same key is
    flagged). Every write happens in one transaction, journal and all.
    """
    headroom = mem_headroom_mb()
    if headroom and headroom < 2000:
        print(f"[!] refused: MemAvailable {headroom} MB < 2000 MB — this pass loads the "
              f"ledger once, and the live box is out of breath", file=sys.stderr)
        return 3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    started = time.time()
    try:
        if undo:
            out = fast_fetch.undo_corroborated_adult_fold(conn)
            conn.commit()
            print(f"[✓] undo: {out['unflagged']:,} rows restored, {out['kept']:,} kept "
                  f"(their flag now stands on its own evidence)")
            return 0
        before = public_total(conn)
        exposures = fast_fetch.corroborated_adult_exposures(conn)
        print(f"[i] corroborated exposures: {len(exposures):,} rows publicly served under "
              f"a flag the rule reproduces (public total {before:,})")
        for item in exposures[:10]:
            print(f"      post {item['post_id']}  <-  {item['evidence']}")
        if len(exposures) > 10:
            print(f"      … {len(exposures) - 10} more")
        if not apply:
            print("[i] report only; pass --corroborate --apply to write, --undo to reverse")
            return 0
        flipped = fast_fetch.apply_corroborated_adult_fold(conn, exposures)
        after = public_total(conn)
        if flipped != before - after:
            print(f"[!] VERIFICATION FAILED: flipped {flipped} rows but the public total "
                  f"moved {before - after}", file=sys.stderr)
            conn.rollback()
            return 1
        dropped = invalidate_safe_stamp(conn)
        conn.commit()
        print(f"[✓] {flipped:,} rows hidden and journalled in `adult_fold_journal`; "
              f"{dropped:,} adult-excluded stamps retired")
        left = fast_fetch.corroborated_adult_exposures(conn)
        print(f"[i] corroborated exposures after the fold: {len(left):,} — must be 0")
        return 0 if not left else 1
    finally:
        print(f"[i] {time.time() - started:.1f}s", flush=True)
        conn.close()


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
    parser.add_argument("--audit", action="store_true",
                        help="read-only: how many stored flags the central rule still "
                             "reproduces, and how many are asserted-only")
    parser.add_argument("--corroborate", action="store_true",
                        help="propagate only flags the central rule reproduces "
                             "(report; combine with --apply to write)")
    parser.add_argument("--undo", action="store_true",
                        help="reverse the corroborated fold, keeping any flag that has "
                             "since gained independent evidence")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"[!] no such database: {args.db}", file=sys.stderr)
        return 2
    if args.audit:
        return run_audit(args.db)
    if args.corroborate or args.undo:
        return run_corroborated(args.db, apply=args.apply, undo=args.undo)
    report(args.db, apply=args.apply, projection=args.projection)
    return 0


if __name__ == "__main__":
    sys.exit(main())
