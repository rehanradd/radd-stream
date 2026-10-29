#!/usr/bin/env python3
"""test_adult_twin_probe.py — the adult-twin counting query, pinned offline.

The design and the quiet-window run live in `docs/ADULT_TWIN_PROBE.md`; this is the
evidence half. A throwaway in-memory fixture, so the counting rules and the index-only
plan are asserted without reading the 6.4 GB catalog the service is running on.

Rules it holds:
* a `canonical_key` carrying both a flagged and an unflagged row is an exposure;
* a key carrying ONLY flagged rows is correctly hidden and must not be counted as one;
* a key carrying only unflagged rows is not an exposure either;
* `canonical_key IS NULL` rows are never twins of each other — NULL is not a value;
* query (A) counts works and (B) counts flagged rows: different numbers, by design;
* the grouping read plans `SEARCH … USING INDEX idx_posts_canonical_key` with no
  `USE TEMP B-TREE FOR GROUP BY`. That is the only reason this audit is safe to run at
  all on a box where `SELECT COUNT(*) … WHERE is_18_plus = 1` was measured (qoder4,
  2026-10-30) at 26.46 s, and if the index ever goes away this test fails before someone
  mistakes a `SCAN posts` for a production measurement.

Stdlib only, no network, no production file.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WORKS_MIXED = ("SELECT COUNT(*) FROM (SELECT canonical_key FROM posts"
               " WHERE canonical_key IS NOT NULL"
               " GROUP BY canonical_key"
               " HAVING SUM(is_18_plus) > 0 AND SUM(1 - is_18_plus) > 0)")

ROWS_EXPOSED = ("SELECT COUNT(*) FROM posts p WHERE p.is_18_plus = 1"
                " AND EXISTS (SELECT 1 FROM posts q"
                "  WHERE q.canonical_key = p.canonical_key AND q.is_18_plus = 0)")

GROUP_BY = ("SELECT canonical_key FROM posts WHERE canonical_key IS NOT NULL"
            " GROUP BY canonical_key"
            " HAVING SUM(is_18_plus) > 0 AND SUM(1 - is_18_plus) > 0")


class AdultTwins(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, canonical_key TEXT,"
            " clean_title TEXT, is_18_plus INTEGER DEFAULT 0);"
            " CREATE INDEX idx_posts_canonical_key ON posts(canonical_key);")

    def add(self, key, title, flag):
        self.conn.execute("INSERT INTO posts(canonical_key, clean_title, is_18_plus)"
                          " VALUES (?,?,?)", (key, title, flag))

    def works(self):
        self.conn.commit()
        return self.conn.execute(WORKS_MIXED).fetchone()[0]

    def rows(self):
        self.conn.commit()
        return self.conn.execute(ROWS_EXPOSED).fetchone()[0]

    def test_a_key_holding_both_flags_is_one_exposed_work(self):
        self.add("k1", "4 Play", 0)
        self.add("k1", "4 Play hd", 1)
        self.assertEqual(self.works(), 1)
        self.assertEqual(self.rows(), 1, "one flagged row is one exposed row")

    def test_a_fully_flagged_work_is_hidden_and_is_not_an_exposure(self):
        """Both rows flagged: every listing path bails, so nothing leaks. Counting it
        would overstate the defect and make the reconciliation look bigger than it is."""
        self.add("k3", "Dirty Only", 1)
        self.add("k3", "Dirty Only hd", 1)
        self.assertEqual(self.works(), 0)
        self.assertEqual(self.rows(), 0)

    def test_a_clean_work_is_untouched(self):
        self.add("k2", "Clean Only", 0)
        self.add("k2", "Clean Only hd", 0)
        self.assertEqual(self.works(), 0)
        self.assertEqual(self.rows(), 0)

    def test_null_keys_are_not_twins_of_each_other(self):
        """SQL `=` never matches NULL, so two unflagged-or-flagged NULL-key rows must not
        read as one mixed work. A probe that used `GROUP BY canonical_key` without the
        `IS NOT NULL` guard would count them and then chase a nonexistent leak."""
        self.add(None, "No key A", 0)
        self.add(None, "No key B", 1)
        self.assertEqual(self.works(), 0)
        self.assertEqual(self.rows(), 0)

    def test_three_flagged_twins_under_two_keys_count_two_works_and_three_rows(self):
        """The (A)/(B) distinction, which is why the doc says to report both numbers:
        the historical 442 / 455 pair is works / rows, not two views of one figure."""
        for key, flag in (("k1", 0), ("k1", 1), ("k1", 1), ("k4", 0), ("k4", 1),
                          ("k9", 0)):
            self.add(key, f"t{key}{flag}", flag)
        self.assertEqual(self.works(), 2)
        self.assertEqual(self.rows(), 3)

    def test_the_grouping_read_stays_inside_the_key_index(self):
        """The safety property of the whole probe, asserted rather than promised.

        If this ever starts printing `SCAN posts`, the count is a multi-minute table read
        on the file the live service uses, and `docs/ADULT_TWIN_PROBE.md` §4 says abort
        the run rather than let it finish.
        """
        self.add("k1", "x", 0)
        self.add("k1", "y", 1)
        self.conn.commit()
        self.conn.execute("ANALYZE")
        plan = " ; ".join(str(x) for r in
                          self.conn.execute("EXPLAIN QUERY PLAN " + GROUP_BY)
                          for x in tuple(r))
        self.assertIn("idx_posts_canonical_key", plan, plan)
        self.assertNotIn("USE TEMP B-TREE FOR GROUP BY", plan, plan)

    def test_the_exposure_read_uses_the_index_for_its_correlation_too(self):
        self.add("k1", "x", 1)
        self.add("k1", "y", 0)
        self.conn.commit()
        plan = " ; ".join(str(x) for r in
                          self.conn.execute("EXPLAIN QUERY PLAN " + ROWS_EXPOSED)
                          for x in tuple(r))
        self.assertIn("idx_posts_canonical_key", plan, plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
