import sqlite3
import tempfile
import unittest
from pathlib import Path

import backfill_cast as bc
import fast_fetch


class BackfillCastTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.target = self.dir / "catalog.db"
        fast_fetch.init_db(self.target)
        with sqlite3.connect(self.target) as conn:
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year,"
                " content_type, canonical_key) VALUES"
                " ('https://10x.example/f1/', 'f1', 'Film One (2024)',"
                "  'Film One', 2024, 'movie', 'film-one_2024'),"
                " ('https://9x.example/f2/', 'f2', 'Film Two (2024)',"
                "  'Film Two', 2024, 'movie', 'film-two_2024'),"
                " ('https://10x.example/f3/', 'f3', 'Film Three (2024)',"
                "  'Film Three', 2024, 'movie', 'film-three_2024')")
            conn.execute(
                "INSERT INTO post_sources (post_id, source_site, url) VALUES"
                " (1, '10xflix', 'https://10x.example/f1/'),"
                " (2, '9xmovies', 'https://9x.example/f2/'),"
                " (3, '10xflix', 'https://10x.example/f3/')")
            # Post 3 already has cast: a fill must never overwrite it.
            conn.execute(
                "UPDATE posts SET cast_names = 'Kept Actor' WHERE id = 3")
        staging = self.dir / "10xflix.db"
        with sqlite3.connect(staging) as conn:
            conn.execute(
                "CREATE TABLE posts (id INTEGER PRIMARY KEY,"
                " post_url TEXT, cast_names TEXT, site TEXT)")
            conn.execute(
                "INSERT INTO posts VALUES"
                " (1, 'https://10x.example/f1/', 'Shah Rukh Khan, Kajol',"
                "  '10xflix'),"
                " (2, 'https://10x.example/gone/', 'Ghost Actor', '10xflix'),"
                " (3, 'https://10x.example/f3/', 'Junk Overwrite', '10xflix'),"
                " (4, 'https://10x.example/f4/', NULL, '10xflix'),"
                " (5, 'https://10x.example/f5/', '   ', '10xflix')")

    def tearDown(self):
        self.tmp.cleanup()

    def cast_of(self, post_id):
        with sqlite3.connect(self.target) as conn:
            return conn.execute(
                "SELECT cast_names FROM posts WHERE id = ?",
                (post_id,)).fetchone()[0]

    def test_report_counts_without_writing(self):
        stats = bc.backfill(self.target, self.dir, apply=False)
        self.assertEqual(stats["filled"], 1)
        self.assertEqual(stats["already_filled"], 1)
        self.assertEqual(stats["unmatched"], 1)
        self.assertEqual(stats["sites"]["10xflix"]["staging_with_cast"], 3)
        self.assertIsNone(self.cast_of(1))

    def test_apply_fills_blanks_and_keeps_existing(self):
        stats = bc.backfill(self.target, self.dir, apply=True)
        self.assertEqual(stats["filled"], 1)
        self.assertEqual(self.cast_of(1), "Shah Rukh Khan, Kajol")
        self.assertEqual(self.cast_of(3), "Kept Actor")

    def test_missing_column_refuses(self):
        bare = self.dir / "bare.db"
        with sqlite3.connect(bare) as conn:
            conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, url TEXT)")
        with self.assertRaises(ValueError):
            bc.backfill(bare, self.dir, apply=True)

    def test_site_filter_skips_other_staging_dbs(self):
        other = self.dir / "9xmovies.db"
        with sqlite3.connect(other) as conn:
            conn.execute(
                "CREATE TABLE posts (id INTEGER PRIMARY KEY,"
                " post_url TEXT, cast_names TEXT, site TEXT)")
            conn.execute(
                "INSERT INTO posts VALUES (1, 'https://9x.example/f2/',"
                " 'Aamir Khan', '9xmovies')")
        stats = bc.backfill(self.target, self.dir, apply=True,
                            only_sites=frozenset({"10xflix"}))
        self.assertEqual(self.cast_of(1), "Shah Rukh Khan, Kajol")
        self.assertIsNone(self.cast_of(2))


if __name__ == "__main__":
    unittest.main()
