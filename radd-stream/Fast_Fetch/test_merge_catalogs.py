#!/usr/bin/env python3
"""Offline unit tests for merge_catalogs.py."""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fast_fetch
import merge_catalogs


class MergeCatalogsTests(unittest.TestCase):
    def test_merge_site_db_migrates_records_with_playback_type(self):
        with tempfile.TemporaryDirectory() as td:
            src_db = Path(td) / "source_multimovies.db"
            tgt_db = Path(td) / "unified_catalog.db"

            # Create source database
            fast_fetch.DB_PATH = src_db
            fast_fetch.init_db()
            post_id = fast_fetch.save_scraped_data(
                {
                    "url": "https://m1.multimovies.courses/movie/pushpa-2",
                    "slug": "pushpa-2",
                    "title": "Pushpa 2 (2024)",
                    "clean_title": "Pushpa 2",
                    "year": 2024,
                    "content_type": "movie",
                    "source_site": "multimovies",
                    "releases": [{
                        "release_title": "Pushpa 2 Cineverse",
                        "quality": "1080p",
                        "source_site": "multimovies",
                        "sources": [{
                            "source_name": "Cineverse [iframe]",
                            "service": "cineverse",
                            "resource_id": "pushpa2-cineverse",
                            "source_url": "https://embed.example/movie/pushpa2",
                            "final_url": "https://embed.example/movie/pushpa2",
                            "playback_type": "iframe",
                        }],
                    }],
                },
                enrich_metadata=False,
                ensure_db=False,
            )

            # Now merge into target DB
            # This fixture uses isolated temporary databases; no project or
            # production catalog is involved.
            stats = merge_catalogs.merge_site_db(
                src_db, tgt_db, verbose=False, owner_authorized=True
            )
            self.assertEqual(stats["posts_merged"], 1)
            self.assertEqual(stats["releases_merged"], 1)
            self.assertEqual(stats["sources_merged"], 1)

            # Verify target DB has the record and playback_type
            fast_fetch.DB_PATH = tgt_db
            with fast_fetch.get_db() as conn:
                row = conn.execute(
                    """
                    SELECT p.clean_title, r.release_title, ds.playback_type, ds.source_url
                    FROM posts p
                    JOIN releases r ON r.post_id = p.id
                    JOIN download_sources ds ON ds.release_id = r.id
                    WHERE p.clean_title = 'Pushpa 2'
                    """
                ).fetchone()

                self.assertIsNotNone(row)
                self.assertEqual(row["clean_title"], "Pushpa 2")
                self.assertEqual(row["playback_type"], "iframe")
                self.assertEqual(row["source_url"], "https://embed.example/movie/pushpa2")

    def test_merge_site_db_fails_closed_without_owner_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            source_db = Path(td) / "source.db"
            target_db = Path(td) / "target.db"

            with self.assertRaisesRegex(PermissionError, "owner authorization"):
                merge_catalogs.merge_site_db(source_db, target_db, verbose=False)

            self.assertFalse(target_db.exists())

    def test_merge_cli_requires_explicit_owner_authorization(self):
        with self.assertRaisesRegex(SystemExit, "explicit instruction"):
            merge_catalogs.main(["source.db"])


if __name__ == "__main__":
    unittest.main()
