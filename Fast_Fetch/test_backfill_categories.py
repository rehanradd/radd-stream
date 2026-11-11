#!/usr/bin/env python3
"""Tests for backfill_categories.py (gap A18)."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backfill_categories as bc

CATEGORY_KEYS = ("action", "adventure", "animation", "comedy", "crime",
                 "drama", "horror", "romance", "sci-fi", "thriller")


def make_panel_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, "
        "display_name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, "
        "is_enabled INTEGER NOT NULL DEFAULT 1, is_adult_only INTEGER NOT NULL DEFAULT 0, "
        "created_by INTEGER, updated_by INTEGER, created_at INTEGER, updated_at INTEGER)")
    conn.execute(
        "CREATE TABLE category_works (id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL, "
        "work_id INTEGER NOT NULL, position INTEGER NOT NULL DEFAULT 0, "
        "created_by INTEGER, created_at INTEGER)")
    for i, key in enumerate(CATEGORY_KEYS, start=1):
        conn.execute(
            "INSERT INTO categories (id, key, display_name, position) VALUES (?,?,?,?)",
            (i, key, key.title(), i))
    conn.commit()
    conn.close()


def make_catalog_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE posts (id INTEGER PRIMARY KEY, genres TEXT, is_18_plus INTEGER)")
    conn.executemany(
        "INSERT INTO posts (id, genres, is_18_plus) VALUES (?,?,?)",
        [(1, '["Action", "Drama"]', 0),          # action + drama
         (2, "Action, Horror", 0),               # action + horror
         (3, "drama", 0),                        # lowercase plain string
         (4, '["18", "Hot", "Romance", "Erotic"]', 0),  # adult-tagged: skip
         (5, "Comedy", 1),                       # adult-flagged: skip
         (6, "", 0),                             # no genre
         (7, "[]", 0),                           # empty array
         (8, "Web Series", 0),                   # unmapped
         (9, '["unofficial-dubbed"]', 0),        # unmapped
         (10, '["Anime", "Comedy"]', 0),         # animation (anime) + comedy
         (11, "Science Fiction", 0),             # sci-fi
         (12, '["Action"]', 0),                  # action, already categorized below
         ])
    conn.commit()
    conn.close()


class ParseTests(unittest.TestCase):
    def test_json_array(self):
        self.assertEqual(bc.parse_genre_tokens('["Action", "Drama"]'),
                         ["action", "drama"])

    def test_plain_string(self):
        self.assertEqual(bc.parse_genre_tokens("Action"), ["action"])
        self.assertEqual(bc.parse_genre_tokens("drama"), ["drama"])

    def test_comma_separated(self):
        self.assertEqual(bc.parse_genre_tokens("Action, Horror"),
                         ["action", "horror"])

    def test_blank_and_empty_array(self):
        self.assertEqual(bc.parse_genre_tokens(""), [])
        self.assertEqual(bc.parse_genre_tokens(None), [])
        self.assertEqual(bc.parse_genre_tokens("[]"), [])
        self.assertEqual(bc.parse_genre_tokens("   "), [])

    def test_malformed_json_falls_back_to_comma_split(self):
        self.assertEqual(bc.parse_genre_tokens('["Action", '), ['["action"'])


class MappingTests(unittest.TestCase):
    def test_each_category_maps(self):
        for key in CATEGORY_KEYS:
            with self.subTest(key=key):
                self.assertEqual(bc.categories_for_tokens([key]), {key})

    def test_anime_is_animation_not_a_new_genre(self):
        self.assertEqual(bc.categories_for_tokens(["anime"]), {"animation"})

    def test_sci_fi_variants(self):
        for token in ("sci-fi", "science fiction", "sci fi", "scifi"):
            with self.subTest(token=token):
                self.assertEqual(bc.categories_for_tokens([token]), {"sci-fi"})

    def test_unmapped_tokens_map_to_nothing(self):
        for token in ("web series", "unofficial-dubbed", "tamil-dubbed",
                      "yoruba", "reality", "hollywood-eng"):
            with self.subTest(token=token):
                self.assertEqual(bc.categories_for_tokens([token]), set())

    def test_adult_tokens(self):
        self.assertTrue(bc.is_adult_tagged(["romance", "erotic"]))
        self.assertTrue(bc.is_adult_tagged(["18"]))
        self.assertTrue(bc.is_adult_tagged(["hot"]))
        self.assertFalse(bc.is_adult_tagged(["romance"]))
        self.assertFalse(bc.is_adult_tagged(["action", "drama"]))


class PlanAndApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog_db = Path(self.tmp.name) / "catalog.db"
        self.panel_db = Path(self.tmp.name) / "admin_v2.db"
        make_catalog_db(self.catalog_db)
        make_panel_db(self.panel_db)
        # Post 12 is already categorized as action.
        conn = sqlite3.connect(str(self.panel_db))
        conn.execute(
            "INSERT INTO category_works (category_id, work_id, position, created_by, created_at) "
            "VALUES (1, 12, 0, 0, 1)")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self):
        catalog_conn = sqlite3.connect("file:%s?mode=ro" % self.catalog_db, uri=True)
        panel_conn = sqlite3.connect("file:%s?mode=ro" % self.panel_db, uri=True)
        try:
            return bc.plan(catalog_conn, panel_conn, limit=None)
        finally:
            catalog_conn.close()
            panel_conn.close()

    def test_plan_counts(self):
        inserts, report, per_category, missing = self._plan()
        self.assertEqual(missing, [])
        self.assertEqual(report["scanned"], 12)
        # New: post 1 (action+drama), 2 (action+horror), 3 (drama),
        # 10 (animation+comedy), 11 (sci-fi) = 8 assignments, 5 posts.
        self.assertEqual(report["new_assignments"], 8)
        self.assertEqual(report["new_posts"], 5)
        self.assertEqual(per_category, {"action": 2, "drama": 2, "horror": 1,
                                        "animation": 1, "comedy": 1, "sci-fi": 1})
        self.assertEqual(report["already_present"], 1)   # post 12
        self.assertEqual(report["adult_flagged"], 1)     # post 5
        self.assertEqual(report["adult_tagged"], 1)      # post 4
        self.assertEqual(report["no_genre"], 2)          # posts 6, 7
        self.assertEqual(report["unmapped"], 2)          # posts 8, 9
        self.assertEqual(report["stays_others"], 6)

    def test_apply_is_idempotent(self):
        inserts, _, _, _ = self._plan()
        self.assertEqual(bc.apply_inserts(str(self.panel_db), inserts, now=1700000000), 8)
        # A second plan sees everything already present: zero new.
        inserts2, report2, _, _ = self._plan()
        self.assertEqual(inserts2, [])
        self.assertEqual(report2["new_assignments"], 0)
        self.assertEqual(report2["already_present"], 9)

    def test_apply_rows_carry_position_and_system_author(self):
        inserts, _, _, _ = self._plan()
        bc.apply_inserts(str(self.panel_db), inserts, now=1700000000)
        conn = sqlite3.connect(str(self.panel_db))
        try:
            rows = conn.execute(
                "SELECT category_id, work_id, position, created_by, created_at "
                "FROM category_works ORDER BY category_id, position").fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 9)  # 1 pre-existing + 8 new
        for cid, wid, pos, created_by, created_at in rows:
            self.assertEqual(created_by, 0)
            if wid != 12:  # the pre-existing row was seeded with created_at=1
                self.assertEqual(created_at, 1700000000)
        # Positions append after the pre-existing action row (position 0).
        action_positions = [r[2] for r in rows if r[0] == 1]
        self.assertEqual(action_positions, [0, 1, 2])

    def test_dry_run_writes_nothing(self):
        self.assertEqual(
            bc.main(["--catalog-db", str(self.catalog_db),
                     "--panel-db", str(self.panel_db)]), 0)
        conn = sqlite3.connect(str(self.panel_db))
        try:
            count = conn.execute("SELECT COUNT(*) FROM category_works").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)  # only the pre-existing row

    def test_empty_category_works_still_reports_every_count(self):
        # The live panel DB has an empty category_works: already_present is
        # 0, and the report must still carry the key (a Counter drops
        # never-incremented keys, which crashed main() on the live dry-run).
        conn = sqlite3.connect(str(self.panel_db))
        conn.execute("DELETE FROM category_works")
        conn.commit()
        conn.close()
        inserts, report, _, _ = self._plan()
        self.assertEqual(report["already_present"], 0)
        self.assertEqual(report["new_assignments"], 9)
        for key in ("scanned", "adult_flagged", "adult_tagged", "no_genre",
                    "unmapped", "already_present", "new_posts",
                    "new_assignments", "stays_others", "missing_categories"):
            self.assertIn(key, report)
        # And the dry-run main() must not crash on the empty table.
        self.assertEqual(
            bc.main(["--catalog-db", str(self.catalog_db),
                     "--panel-db", str(self.panel_db)]), 0)


if __name__ == "__main__":
    unittest.main()
