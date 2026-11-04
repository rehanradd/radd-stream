#!/usr/bin/env python3 -S
# -*- coding: utf-8 -*-
"""Tests for reconcile_adult.py — the invariant proven is BEHAVIOR, not column
values: after reconciliation the formerly-leaking twin must vanish from the
public list predicate (``redact.adult_clause``) and must not obtain a stream
token (``redact.link_is_adult``), exactly as the shipped routes judge it.

Offline only: temp databases, no network, no live catalog.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import reconcile_adult  # noqa: E402

try:
    from Fast_Fetch import redact
except ImportError:
    import redact  # type: ignore


DDL = """
CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT, canonical_key TEXT,
                    is_18_plus INTEGER);
CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER);
CREATE TABLE download_sources (id INTEGER PRIMARY KEY, release_id INTEGER,
                               source_url TEXT, final_url TEXT, service TEXT,
                               status TEXT);
"""

ROWS = [
    # (id, title, key, flag)
    (1, "Bad Copy flagged",    "shared-key-a", 1),      # the anchor
    (2, "Bad Copy unflagged",  "shared-key-a", 0),      # THE LEAKING TWIN
    (3, "Good Copy",           "clean-key-b",  0),      # control, must stay
    (4, "Null flag twin",      "shared-key-c", 1),
    (5, "NULL-flagged row",    "shared-key-c", None),   # NULL = public -> flips
    (6, "Keyless unflagged",   "",             0),      # never propagated
    (7, "Null-key unflagged",  None,           0),      # never propagated
    (8, "Already both flagged","shared-key-d", 1),
    (9, "Already both flaggedB","shared-key-d",1),      # nothing to do
]


def make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    conn.executemany("INSERT INTO posts VALUES (?,?,?,?)", ROWS)
    conn.executemany("INSERT INTO releases VALUES (?,?)",
                     [(100 + p, p) for p in range(1, 10)])
    conn.executemany("INSERT INTO download_sources VALUES (?,?,?,?,?,?)",
                     [(200 + r[0], 100 + r[0], f"https://x/{r[0]}", "", "s", "active")
                      for r in ROWS])
    conn.commit()
    conn.close()


class ReconcileAdultTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "catalog.db")
        self.bdir = os.path.join(self.dir.name, "backups")
        make_db(self.db)
        self.addCleanup(self.dir.cleanup)

    # ── plan / dry-run ───────────────────────────────────────────────────────

    def test_plan_counts_the_twins_only(self):
        plan = reconcile_adult.build_plan(sqlite3.connect(self.db))
        self.assertEqual(plan["mixed_keys"], 2)            # a (1/0) and c (1/NULL)
        self.assertEqual({r["post_id"] for r in plan["rows_to_flip"]}, {2, 5})
        self.assertEqual(plan["keyless_rows_excluded"], 2)
        self.assertEqual(plan["flagged_before"], 4)

    def test_dry_run_is_the_default_and_writes_nothing(self):
        with open(self.db, "rb") as fh:
            before = fh.read()
        report = reconcile_adult.reconcile(self.db)         # no --apply
        self.assertFalse(report["applied"])
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["changed"], 0)
        with open(self.db, "rb") as fh:
            self.assertEqual(fh.read(), before)
        flags = dict(sqlite3.connect(self.db).execute(
            "SELECT id, is_18_plus FROM posts").fetchall())
        self.assertEqual(flags[2], 0)                       # twin untouched

    # ── apply: behavior proven through redact.py ─────────────────────────────

    def _public_list_ids(self):
        """The shipped public-list predicate, run verbatim against our db."""
        conn = sqlite3.connect(self.db)
        try:
            clause = redact.adult_clause("posts")
            return {r[0] for r in conn.execute(
                f"SELECT id FROM posts WHERE {clause}")}
        finally:
            conn.close()

    def test_apply_hides_the_twin_from_the_public_surface(self):
        report = reconcile_adult.reconcile(self.db, apply=True,
                                           backup_dir=self.bdir)
        self.assertTrue(report["applied"])
        self.assertEqual(report["changed"], 2)              # posts 2 and 5
        public = self._public_list_ids()
        self.assertNotIn(1, public)                         # anchor was hidden
        self.assertNotIn(2, public)                         # LEAK NOW CLOSED
        self.assertNotIn(5, public)
        self.assertIn(3, public)                            # control still listed
        self.assertIn(6, public)                            # keyless still listed
        self.assertIn(7, public)

    def test_apply_denies_the_twin_a_stream_token(self):
        reconcile_adult.reconcile(self.db, apply=True, backup_dir=self.bdir)
        self.assertTrue(redact.link_is_adult(202, self.db))   # twin's link: no play
        self.assertTrue(redact.link_is_adult(205, self.db))
        self.assertFalse(redact.link_is_adult(203, self.db))  # control still plays

    def test_reconciled_then_orphaned_twin_is_unreachable_both_ways(self):
        """Composition: reconciliation hides the twin on the list route, and if a
        later merge orphans its release chain, the fail-closed guard keeps the
        redirector shut too — no row to judge is adult-capable, not servable."""
        reconcile_adult.reconcile(self.db, apply=True, backup_dir=self.bdir)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE download_sources SET release_id = 99998 WHERE id = 202")
        conn.commit()
        conn.close()
        self.assertNotIn(2, self._public_list_ids())            # list: still hidden
        self.assertTrue(redact.link_is_adult(202, self.db))     # redirector: no play
        self.assertFalse(redact.link_is_adult(203, self.db))    # control still plays

    def test_apply_requires_a_verified_backup_and_refuses_without(self):
        locked = "/proc/definitely-not-writable/backups"
        with self.assertRaises(reconcile_adult.BackupRefused):
            reconcile_adult.reconcile(self.db, apply=True, backup_dir=locked)
        flags = dict(sqlite3.connect(self.db).execute(
            "SELECT id, is_18_plus FROM posts").fetchall())
        self.assertEqual(flags[2], 0)                        # refusal wrote nothing

    def test_backup_is_real_and_snapshot_matches_pre_apply(self):
        report = reconcile_adult.reconcile(self.db, apply=True,
                                           backup_dir=self.bdir)
        backup = report["backup"]["path"]
        self.assertTrue(os.path.exists(backup))
        self.assertTrue(len(report["backup"]["sha256"]) == 64)
        # the backup froze PRE-apply state: the twin is still unflagged there
        twin = sqlite3.connect(backup).execute(
            "SELECT COALESCE(is_18_plus,0) FROM posts WHERE id = 2").fetchone()[0]
        self.assertEqual(twin, 0)
        self.assertGreaterEqual(report["backup"]["counts"]["posts"], len(ROWS))

    def test_idempotent_second_run_changes_nothing(self):
        first = reconcile_adult.reconcile(self.db, apply=True, backup_dir=self.bdir)
        second = reconcile_adult.reconcile(self.db, apply=True, backup_dir=self.bdir)
        self.assertEqual(first["changed"], 2)
        self.assertEqual(second["changed"], 0)
        self.assertEqual(second["flip_count"], 0)
        self.assertEqual(second["idempotent_check"], 0)
        self.assertIn("nothing to flip", second["backup"])   # no needless snapshot

    def test_flag_never_propagates_downward(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE posts SET is_18_plus = 0 WHERE id = 1")   # un-flag anchor
        conn.commit(); conn.close()
        reconcile_adult.reconcile(self.db, apply=True, backup_dir=self.bdir)
        conn = sqlite3.connect(self.db)
        flags = dict(conn.execute("SELECT id, is_18_plus FROM posts").fetchall())
        conn.close()
        self.assertEqual(flags[1], 0)     # the (manually) unflagged row stays 0:
                                          # no key has MAX=1 for a anymore? key a
                                          # still has post 2 flipped by first runs?
                                          # here anchor=0 and twin was 0 -> nothing
                                          # flagged -> no propagation, twin stays 0
        self.assertEqual(flags[2], 0)

    def test_cli_dry_run_is_default(self):
        rc = reconcile_adult.main(["--db", self.db])          # no --apply flag
        self.assertEqual(rc, 0)
        flags = dict(sqlite3.connect(self.db).execute(
            "SELECT id, is_18_plus FROM posts").fetchall())
        self.assertEqual(flags[2], 0)

    def test_cli_apply_via_main_and_json(self):
        rc = reconcile_adult.main(["--db", self.db, "--apply",
                                   "--backup-dir", self.bdir, "--json"])
        self.assertEqual(rc, 0)
        flags = dict(sqlite3.connect(self.db).execute(
            "SELECT id, COALESCE(is_18_plus,0) FROM posts").fetchall())
        self.assertEqual(flags[2], 1)
        self.assertEqual(flags[6], 0)                         # keyless stays


if __name__ == "__main__":
    unittest.main(verbosity=2)
