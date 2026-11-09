"""Tests for fts_search.py (Session 123).

The fixture is a small in-memory database with the two projection tables the
index reads: `cat_works` and `cat_work_aliases`. No network, no catalog.
"""
import sqlite3
import unittest

import fts_search


def _fixture():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE cat_works (
            id INTEGER PRIMARY KEY, title TEXT, original_title TEXT,
            genres TEXT, is_18_plus INTEGER DEFAULT 0)
    """)
    conn.execute("""
        CREATE TABLE cat_work_aliases (
            work_id INTEGER, alias TEXT, locale TEXT,
            source_site TEXT, kind TEXT, PRIMARY KEY (work_id, alias, source_site))
    """)
    conn.execute(
        "INSERT INTO cat_works VALUES (1, 'Amélie', NULL, 'Romance, Comedy', 0)")
    conn.execute(
        "INSERT INTO cat_works VALUES (2, 'Dune: Part Two', 'Dune Part 2',"
        " 'Sci-Fi', 0)")
    conn.execute(
        "INSERT INTO cat_works VALUES (3, 'Pushpa 2: The Rule', NULL, 'Action', 0)")
    conn.execute(
        "INSERT INTO cat_work_aliases VALUES (2, 'Dune 2', NULL, 'x', 'aka')")
    return conn


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.conn = _fixture()

    def tearDown(self):
        self.conn.close()

    def test_absent_before_rebuild_available_after(self):
        self.assertFalse(fts_search.fts_available(self.conn))
        report = fts_search.rebuild_fts(self.conn)
        self.assertEqual(report, {"works": 3, "indexed": 3})
        self.assertTrue(fts_search.fts_available(self.conn))

    def test_rebuild_is_idempotent(self):
        fts_search.rebuild_fts(self.conn)
        report = fts_search.rebuild_fts(self.conn)
        self.assertEqual(report, {"works": 3, "indexed": 3})
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM cat_works_fts").fetchone()[0], 3)

    def test_rebuild_on_an_empty_projection_leaves_an_empty_index(self):
        empty = sqlite3.connect(":memory:")
        empty.execute("CREATE TABLE cat_works (id INTEGER PRIMARY KEY,"
                      " title TEXT, original_title TEXT, genres TEXT)")
        empty.execute("CREATE TABLE cat_work_aliases (work_id INTEGER,"
                      " alias TEXT, locale TEXT, source_site TEXT, kind TEXT,"
                      " PRIMARY KEY (work_id, alias, source_site))")
        report = fts_search.rebuild_fts(empty)
        self.assertEqual(report, {"works": 0, "indexed": 0})
        self.assertFalse(fts_search.fts_available(empty))
        empty.close()

    def test_title_prefix_tokens_find_the_work(self):
        fts_search.rebuild_fts(self.conn)
        self.assertEqual(fts_search.search_ids(self.conn, ["dune"]), [2])
        self.assertEqual(fts_search.search_ids(self.conn, ["dune", "part"]), [2])
        self.assertEqual(fts_search.search_ids(self.conn, ["push"]), [3])

    def test_an_alias_only_hit_is_found(self):
        # The LIKE haystack searches aliases too, so the index must as well —
        # otherwise the accelerator would hide a row the fallback finds.
        fts_search.rebuild_fts(self.conn)
        self.assertEqual(fts_search.search_ids(self.conn, ["dune", "2"]), [2])

    def test_a_diacritic_query_finds_the_folded_title(self):
        # "Amélie" is indexed as "amelie": the query token the catalog module
        # normalises is "amelie" too, so both sides agree.
        fts_search.rebuild_fts(self.conn)
        self.assertEqual(fts_search.search_ids(self.conn, ["amelie"]), [1])

    def test_no_tokens_answer_nothing(self):
        fts_search.rebuild_fts(self.conn)
        self.assertEqual(fts_search.search_ids(self.conn, []), [])

    def test_search_without_a_table_raises_for_the_fallback(self):
        with self.assertRaises(sqlite3.OperationalError):
            fts_search.search_ids(self.conn, ["dune"])


class NormalizerTwinTests(unittest.TestCase):
    def test_matches_the_catalog_modules_normalizer(self):
        import catalog_api

        samples = [
            "Amélie", "Dune: Part Two (2024)", "Tom & Jerry", "  spaced   out  ",
            "Pushpa 2: The Rule", "L'Étranger", "", None, "100% Wolf",
        ]
        for sample in samples:
            self.assertEqual(fts_search.normalize_text(sample),
                             catalog_api.normalize_text(sample), sample)


if __name__ == "__main__":
    unittest.main()
