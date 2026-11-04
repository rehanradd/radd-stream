#!/usr/bin/env python3 -S
# -*- coding: utf-8 -*-
"""reconcile_adult.py — close the adult-twin hole the way AGENTS.md says it must
be closed: reconcile ``MAX(is_18_plus)`` across every row that shares a
``canonical_key``.

Why this exists
---------------
The public list/search routes and the stream/download redirectors already hide
every row flagged ``is_18_plus = 1`` (``redact.adult_clause`` /
``redact.link_is_adult``). But adult law is applied per *row* while media
identity is per *key*: when the same work arrives from two sites and only one
copy got flagged, the unflagged twin is publicly listable and playable under
its own id. That is the hole this migration shuts: a key that has ANY flagged
row has ALL its rows flagged.

Policy (deliberate, read before changing)
-----------------------------------------
* **Only rows with a usable ``canonical_key`` participate.** A row whose key is
  NULL or the empty string is NEVER flipped by propagation — an "empty key
  matches empty key" join would flag the entire catalog in one UPDATE. Keyless
  rows are counted and reported so an operator sees how much of the catalog
  has no identity to reconcile on.
* **Flagging only propagates upward.** A key with at least one ``is_18_plus=1``
  row flips its unflagged twins (including ``NULL`` and ``0`` — both mean
  "public" to ``redact.adult_clause``). Nothing here ever UN-clears a flag.
* **Dry-run is the default.** Without ``--apply`` this makes no write at all —
  it prints the plan: keys, row ids, and how many works that hides.
* **A fresh backup is required before any apply.** We call
  ``backup_manager.safe_vacuum_sqlite`` (``VACUUM INTO``: consistent snapshot,
  never disrupts WAL writers) into ``--backup-dir``, verify the backup opens
  and answers its row counts, and record its sha256. If any step fails, we
  refuse to write. No backup, no apply, no flag to override that.
* **Idempotent.** A second run flips nothing; the plan is derived from stored
  state, not from history.
* **One short ``BEGIN IMMEDIATE`` transaction** for the whole UPDATE, with a
  busy timeout, so a live crawler is never queued behind a multi-second lock.
* **Consequence to remember:** the flip is not permanent against new scrapes —
  ``save_scraped_data`` re-derives ``is_18_plus`` per title, so a future twin
  can arrive unflagged again. This tool is meant to run periodically (the same
  cadence as the identity backfill), not once.

This is a data migration that makes content disappear from public routes.
Re-measure, back up, apply to a scratch copy first. Never run ``--apply``
against the live production catalog from an agent lane.

Standard library only. Never deletes a parser or a filter.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

try:  # package-style and in-directory execution, like every sibling module
    from Fast_Fetch import backup_manager
except ImportError:  # pragma: no cover - running from inside Fast_Fetch/
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import backup_manager  # type: ignore

__all__ = [
    "DEFAULT_DB", "DEFAULT_BUSY_TIMEOUT_MS",
    "build_plan", "reconcile", "take_verified_backup", "BackupRefused",
]

#: Same resolution order the running service uses, but never assumed: an
#: operator points --db at whatever catalog they intend to audit.
DEFAULT_DB = os.environ.get(
    "RADD_DB_PATH", "/home/ubuntu/radd-stream-data/merged_catalog_20261025.db")
DEFAULT_BUSY_TIMEOUT_MS = 5000

# ── the plan (pure reads) ────────────────────────────────────────────────────

_PLAN_SQL = """
    WITH keyed AS (
        SELECT id, canonical_key, COALESCE(is_18_plus, 0) AS flag
          FROM posts
         WHERE canonical_key IS NOT NULL AND canonical_key != ''
    ),
    flagged_keys AS (
        SELECT canonical_key FROM keyed GROUP BY canonical_key HAVING MAX(flag) = 1
    )
    SELECT k.id, k.canonical_key
      FROM keyed k
      JOIN flagged_keys f ON f.canonical_key = k.canonical_key
     WHERE k.flag = 0
     ORDER BY k.id
"""

_MIXED_KEY_COUNT_SQL = """
    SELECT COUNT(*) FROM (
        SELECT canonical_key FROM posts
         WHERE canonical_key IS NOT NULL AND canonical_key != ''
         GROUP BY canonical_key
        HAVING MAX(COALESCE(is_18_plus, 0)) = 1
           AND MIN(COALESCE(is_18_plus, 0)) = 0
    )
"""

_APPLY_SQL = """
    WITH flip AS (
        SELECT p.id AS rid FROM posts p
         WHERE COALESCE(p.is_18_plus, 0) = 0
           AND p.canonical_key IS NOT NULL AND p.canonical_key != ''
           AND p.canonical_key IN (
               SELECT canonical_key FROM posts
                WHERE canonical_key IS NOT NULL AND canonical_key != ''
               GROUP BY canonical_key HAVING MAX(is_18_plus) = 1)
    )
    UPDATE posts SET is_18_plus = 1
     WHERE id IN (SELECT rid FROM flip)
"""


def build_plan(conn: sqlite3.Connection) -> dict:
    """Everything dry-run prints, computed from stored state only."""
    rows = conn.execute(_PLAN_SQL).fetchall()
    keyless = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE canonical_key IS NULL OR canonical_key = ''"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    return {
        "mixed_keys": conn.execute(_MIXED_KEY_COUNT_SQL).fetchone()[0],
        "rows_to_flip": [{"post_id": int(r[0]), "canonical_key": r[1]} for r in rows],
        "flip_count": len(rows),
        "keyless_rows_excluded": int(keyless),
        "total_posts": int(total),
        "flagged_before": conn.execute(
            "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1").fetchone()[0],
    }


# ── the backup gate ──────────────────────────────────────────────────────────

class BackupRefused(RuntimeError):
    """No fresh verified backup — the migration will not write."""


def take_verified_backup(db_path: str | Path, backup_dir: str | Path | None = None) -> dict:
    """Snapshot ``db_path`` via ``backup_manager`` and prove the snapshot is real.

    Returns {path, sha256, counts}. Raises ``BackupRefused`` on ANY failure —
    a backup we cannot read back is not a backup."""
    source = Path(db_path)
    if not source.exists():
        raise BackupRefused(f"database not found: {source}")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out_dir = Path(backup_dir) if backup_dir else source.parent / "adult_reconcile_backups"
    target = out_dir / f"{source.name}.pre-adult-reconcile-{stamp}.db"
    try:
        ok = backup_manager.safe_vacuum_sqlite(source, target)
    except Exception as exc:                      # noqa: BLE001 — any backup fault refuses
        raise BackupRefused(f"safe_vacuum_sqlite raised: {exc}") from exc
    if not ok or not target.exists() or target.stat().st_size == 0:
        raise BackupRefused(f"backup snapshot missing or empty: {target}")
    try:
        counts = backup_manager._db_row_counts(target)
        sha = backup_manager.calculate_sha256(target)
    except Exception as exc:                      # noqa: BLE001
        target.unlink(missing_ok=True)
        raise BackupRefused(f"backup failed verification: {exc}") from exc
    if not counts.get("posts"):
        target.unlink(missing_ok=True)
        raise BackupRefused(f"backup reads back with no posts rows: {target}")
    return {"path": str(target), "sha256": sha, "counts": counts}


# ── the migration ────────────────────────────────────────────────────────────

def reconcile(db_path: str | Path, *, apply: bool = False,
              backup_dir: str | Path | None = None,
              busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
              list_limit: int = 2000) -> dict:
    """Plan (and with ``apply``, perform) the MAX(is_18_plus) reconciliation.

    ``apply=False`` opens the database read-only whenever possible and makes no
    write — the default, and the only mode an agent lane may run against real
    data. ``apply=True`` first takes a verified backup (refusing everything on
    failure), then performs the flips in one short ``BEGIN IMMEDIATE``.
    """
    report = {"mode": "apply" if apply else "dry-run", "db": str(db_path)}
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True) if not apply else sqlite3.connect(str(db_path))
    except sqlite3.Error:
        conn = sqlite3.connect(str(db_path))       # non-URI path: dry-run still only reads
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    try:
        plan = build_plan(conn)
        report.update({k: v for k, v in plan.items() if k != "rows_to_flip"})
        report["rows_to_flip_sample"] = plan["rows_to_flip"][:list_limit]
        report["would_hide_works"] = plan["mixed_keys"]
        if not apply:
            report["changed"] = 0
            report["applied"] = False
            return report
        if not plan["rows_to_flip"]:
            report.update({"changed": 0, "applied": True,
                           "flagged_after": plan["flagged_before"],
                           "idempotent_check": 0,
                           "backup": "skipped: nothing to flip"})
            return report
        report["backup"] = take_verified_backup(db_path, backup_dir)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(_APPLY_SQL)
        # sqlite3's cursor.rowcount is -1 for an UPDATE driven by a WITH clause;
        # changes() is the truth.
        changed = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        after = build_plan(conn)
        report.update({
            "changed": int(changed),
            "applied": True,
            "flagged_after": after["flagged_before"],
            "idempotent_check": after["flip_count"],          # must be 0
        })
        if after["flip_count"] != 0:
            raise sqlite3.DatabaseError(
                "post-apply check failed: twins still unflagged")
        return report
    finally:
        conn.close()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Reconcile MAX(is_18_plus) across every posts row sharing a "
                    "canonical_key. DRY-RUN UNLESS --apply IS PASSED, and --apply "
                    "refuses without a fresh verified backup.")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"catalog to act on (default: {DEFAULT_DB})")
    ap.add_argument("--apply", action="store_true",
                    help="perform the flips (requires backup success; run on a scratch copy first)")
    ap.add_argument("--backup-dir", default=None,
                    help="where the pre-apply snapshot goes (default: <db dir>/adult_reconcile_backups)")
    ap.add_argument("--busy-timeout-ms", type=int, default=DEFAULT_BUSY_TIMEOUT_MS)
    ap.add_argument("--list-limit", type=int, default=2000)
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args(argv)

    try:
        report = reconcile(args.db, apply=args.apply, backup_dir=args.backup_dir,
                           busy_timeout_ms=args.busy_timeout_ms, list_limit=args.list_limit)
    except BackupRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        print("No rows were written.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        mode = "APPLIED" if report.get("applied") else "DRY-RUN (no writes)"
        print(f"[{mode}] {report['db']}")
        print(f"  posts total ................ {report['total_posts']:,}")
        print(f"  currently flagged .......... {report['flagged_before']:,}")
        print(f"  keys with a flagged twin ... {report['mixed_keys']:,}")
        print(f"  rows that would flip ....... {report['flip_count']:,}")
        print(f"  keyless rows EXCLUDED ...... {report['keyless_rows_excluded']:,}"
              "  (never propagated — no identity to reconcile on)")
        for row in report.get("rows_to_flip_sample", []):
            print(f"    flip post {row['post_id']:>8}  {row['canonical_key']}")
        if report["flip_count"] > len(report.get("rows_to_flip_sample", [])):
            print(f"    … {report['flip_count']} total (--list-limit to see more)")
        if report.get("applied"):
            print(f"  changed = {report['changed']:,}, flagged after = {report['flagged_after']:,}")
            print(f"  idempotent: re-plan flips {report['idempotent_check']} rows (want 0)")
            print(f"  backup: {report.get('backup', {}).get('path', 'skipped')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
