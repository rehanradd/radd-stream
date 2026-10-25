#!/usr/bin/env python3
"""Offline tests for `backfill_animated_flag.py` — temp database only, no network,
never touches a real catalog."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backfill_animated_flag as bf
import fast_fetch


def _ledger(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


class BackfillAnimatedFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "site.db"
        self.patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.patch.start()
        fast_fetch.init_db()

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def _post(self, conn, *, title, clean, slug, genres=None, industry=None, animated=0):
        conn.execute(
            """
            INSERT INTO posts (url, slug, title, clean_title, year, content_type,
                               genres, industry, is_18_plus, is_animated, source_site,
                               canonical_key)
            VALUES (?, ?, ?, ?, 2024, 'movie', ?, ?, 0, ?, 'site_a', ?)
            """,
            (f"https://site-a.test/{slug}/", slug, title, clean, genres, industry,
             animated, fast_fetch.generate_canonical_key(clean, 2024)),
        )
        conn.commit()

    def counts(self, conn):
        return [r["clean_title"] for r in conn.execute(
            "SELECT clean_title FROM posts WHERE is_animated = 1 ORDER BY clean_title")]

    def test_title_vocabulary_is_flagged(self):
        conn = _ledger(self.db_path)
        self._post(conn, title="Hunjaro Anime (2024)", clean="Hunjaro", slug="hunjaro-anime")
        self._post(conn, title="A Quiet House (2024)", clean="A Quiet House", slug="a-quiet-house")
        result = bf.scan(conn, apply=True, progress=False)
        self.assertEqual(result["flagged"], 1)
        self.assertEqual(self.counts(conn), ["Hunjaro"])

    def test_genre_and_industry_evidence_alone_is_enough(self):
        conn = _ledger(self.db_path)
        self._post(conn, title="Kadan (2024)", clean="Kadan", slug="kadan",
                   genres='["Animation", "Action"]')
        self._post(conn, title="Sailor Moon (2024)", clean="Sailor Moon", slug="sailor-moon",
                   industry="Anime")
        result = bf.scan(conn, apply=True, progress=False)
        self.assertEqual(result["flagged"], 2)
        self.assertEqual(self.counts(conn), ["Kadan", "Sailor Moon"])

    def test_dry_run_reports_without_writing(self):
        conn = _ledger(self.db_path)
        self._post(conn, title="Dragon Ball Z (2024)", clean="Dragon Ball Z",
                   slug="dragon-ball-z", genres='["Animation"]')
        result = bf.scan(conn, apply=False, progress=False)
        self.assertEqual(result, {"scanned": 1, "flagged": 1, "applied": False})
        self.assertEqual(self.counts(conn), [])

    def test_an_already_flagged_post_is_not_rescanned(self):
        conn = _ledger(self.db_path)
        self._post(conn, title="Pokemon (2024)", clean="Pokemon", slug="pokemon", animated=1)
        self.assertEqual(bf.scan(conn, apply=True, progress=False)["scanned"], 0)

    def test_one_rule_owns_the_column_from_ingest_to_backfill(self):
        """`save_scraped_data()` must flag what this tool would flag, so a re-crawl
        cannot un-flag a title the backfill just recognised."""
        saved = fast_fetch.save_scraped_data({
            "url": "https://site-a.test/one-piece-anime/",
            "slug": "one-piece-anime",
            "title": "One Piece (2024)",
            "clean_title": "One Piece",
            "year": 2024,
            "content_type": "series",
            "source_site": "site_a",
            "releases": [],
        }, enrich_metadata=False)
        conn = _ledger(self.db_path)
        self.assertEqual(
            conn.execute("SELECT is_animated FROM posts WHERE id = ?", (saved,)).fetchone()[0], 1)
        self.assertEqual(bf.scan(conn, apply=True, progress=False)["scanned"], 0)

    def test_an_anime_only_site_flags_every_post_of_it(self):
        """These sites' staging schemas have no `is_animated` column at all, so the
        only evidence is the page they came from — ledger-side, never on the wire."""
        saved = fast_fetch.save_scraped_data({
            "url": "https://rareanimes.test/suke-shi-donghuarenge/",
            "slug": "suke-shi-donghuarenge",
            "title": "Suke Shi (2024)",
            "clean_title": "Suke Shi",
            "year": 2024,
            "content_type": "series",
            "source_site": "rareanimes",
            "releases": [],
        }, enrich_metadata=False)
        conn = _ledger(self.db_path)
        self.assertEqual(
            conn.execute("SELECT is_animated FROM posts WHERE id = ?", (saved,)).fetchone()[0], 1)

        # An already-merged row that arrived before the rule existed is repaired by
        # the same site evidence, through `post_sources`.
        other = conn.execute(
            """
            INSERT INTO posts (url, slug, title, clean_title, year, content_type,
                               is_18_plus, is_animated, source_site, canonical_key)
            VALUES ('https://rareanimes.test/naruto/', 'naruto', 'Naruto (2016)', 'Naruto',
                    2016, 'series', 0, 0, 'katmoviehd', ?)
            """,
            (fast_fetch.generate_canonical_key("Naruto", 2016),),
        ).lastrowid
        conn.execute("INSERT INTO post_sources (post_id, source_site, url) VALUES (?, 'rareanimes', "
                     "'https://rareanimes.test/naruto/')", (other,))
        conn.commit()
        result = bf.scan(conn, apply=True, progress=False)
        self.assertEqual(result["flagged"], 1)
        self.assertEqual(
            conn.execute("SELECT is_animated FROM posts WHERE id = ?", (other,)).fetchone()[0], 1)

    def test_a_live_action_title_is_not_flagged_by_either_path(self):
        saved = fast_fetch.save_scraped_data({
            "url": "https://site-a.test/the-godfather/",
            "slug": "the-godfather",
            "title": "The Godfather (2024)",
            "clean_title": "The Godfather",
            "year": 2024,
            "content_type": "movie",
            "source_site": "site_a",
            "releases": [],
        }, enrich_metadata=False)
        conn = _ledger(self.db_path)
        self.assertEqual(
            conn.execute("SELECT is_animated FROM posts WHERE id = ?", (saved,)).fetchone()[0], 0)
        self.assertEqual(bf.scan(conn, apply=True, progress=False),
                         {"scanned": 1, "flagged": 0, "applied": True})

    def test_the_caller_payload_is_not_mutated(self):
        payload = {
            "url": "https://site-a.test/spirited-away/",
            "slug": "spirited-away",
            "title": "Spirited Away (2024)",
            "clean_title": "Spirited Away",
            "year": 2024,
            "content_type": "movie",
            "source_site": "site_a",
            "releases": [],
        }
        fast_fetch.save_scraped_data(payload, enrich_metadata=False)
        self.assertNotIn("is_animated", payload)

    def test_a_database_without_the_column_is_refused_not_crashed(self):
        other = Path(self.temp_dir.name) / "legacy.db"
        conn = sqlite3.connect(str(other))
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT)")
        conn.commit()
        with self.assertRaises(ValueError):
            bf.scan(conn, apply=True, progress=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
