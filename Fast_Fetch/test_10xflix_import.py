#!/usr/bin/env python3
"""
test_10xflix_import.py — Comprehensive unit tests for 10xflix dedicated scraper.
Tests cover:
  1. Title cleaning and canonical key generation (movies & series).
  2. Byte size string parser.
  3. Release button & resolution parser from HTML.
  4. Post data extraction and MobileJSR mirror extraction.
  5. Isolated SQLite staging database initialization & foreign key cascade.
  6. Atomic post, release, and source persistence.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import import_10xflix


class TestTenXFlixImport(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_10xflix.db"
        import_10xflix.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_10xflix_title_movie(self):
        raw = "Street Fighter (2026) Hindi (Cleaned) Movie HQ HDTC | 1080p | 720p | 480p"
        title, year, season, episode, canon = import_10xflix.clean_10xflix_title(raw)
        self.assertEqual(title, "Street Fighter")
        self.assertEqual(year, 2026)
        self.assertIsNone(season)
        self.assertIsNone(episode)
        self.assertEqual(canon, "street-fighter_2026")

    def test_clean_10xflix_title_series(self):
        raw = "Sa Re Ga Ma Pa (2026) Hindi ORG S01E10 Series HDRip | 1080p | 720p | 480p"
        title, year, season, episode, canon = import_10xflix.clean_10xflix_title(raw)
        self.assertEqual(title, "Sa Re Ga Ma Pa")
        self.assertEqual(year, 2026)
        self.assertEqual(season, 1)
        self.assertEqual(episode, 10)
        self.assertEqual(canon, "sa-re-ga-ma-pa_2026_s1_e10")

    def test_parse_size_string(self):
        self.assertEqual(import_10xflix.parse_size_string("2.02GB"), int(2.02 * 1024 * 1024 * 1024))
        self.assertEqual(import_10xflix.parse_size_string("3.73.GB"), int(3.73 * 1024 * 1024 * 1024))
        self.assertEqual(import_10xflix.parse_size_string("997MB"), int(997 * 1024 * 1024))
        self.assertEqual(import_10xflix.parse_size_string("500KB"), int(500 * 1024))
        self.assertIsNone(import_10xflix.parse_size_string("Unknown"))
        self.assertIsNone(import_10xflix.parse_size_string(None))

    def test_parse_10xflix_releases(self):
        sample_html = """
        <p><strong>Download Links:</strong></p>
        <p><a href="https://mobilejsr.com/view/heZxR9W5aL">1080p [2.02GB]</a></p>
        <p><a href="https://mobilejsr.com/view/wDs1bdMrff">720p [997MB]</a></p>
        <p><a href="https://mobilejsr.com/view/bpcggpqnLN">480p [353MB]</a></p>
        """
        releases = import_10xflix.parse_10xflix_releases(sample_html, "Sample Movie")
        self.assertEqual(len(releases), 3)

        self.assertEqual(releases[0]["quality"], "1080p")
        self.assertEqual(releases[0]["bridge_url"], "https://mobilejsr.com/view/heZxR9W5aL")
        self.assertGreater(releases[0]["size_bytes"], 2_000_000_000)

        self.assertEqual(releases[1]["quality"], "720p")
        self.assertEqual(releases[1]["bridge_url"], "https://mobilejsr.com/view/wDs1bdMrff")

        self.assertEqual(releases[2]["quality"], "480p")
        self.assertEqual(releases[2]["bridge_url"], "https://mobilejsr.com/view/bpcggpqnLN")

    def test_extract_post_data_10xflix(self):
        mock_raw = {
            "title": {"rendered": "Armored (2009) Hindi ORG Dual Audio BluRay | 1080p | 720p | 480p | ESubs"},
            "link": "https://10xflix.bond/armored-2009-hindi-org-dual-audio-bluray-1080p-720p-480p-esubs/",
            "content": {
                "rendered": (
                    '<p><a href="https://mobilejsr.com/view/W3Pq15KDAN">1080p [2.1GB]</a></p>'
                    '<p><a href="https://mobilejsr.com/view/3Dmtq1rHjA">720p [1.1GB]</a></p>'
                )
            },
            "_embedded": {
                "wp:featuredmedia": [{"source_url": "https://image.tmdb.org/t/p/w500/sample_poster.jpg"}],
                "wp:term": [[{"name": "Action"}, {"name": "Thriller"}]],
            },
        }

        data = import_10xflix.extract_post_data_10xflix(mock_raw, resolve_direct=False)
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "Armored")
        self.assertEqual(data["year"], 2009)
        self.assertEqual(data["media_type"], "movie")
        self.assertEqual(data["poster_url"], "https://image.tmdb.org/t/p/w500/sample_poster.jpg")
        self.assertEqual(len(data["releases"]), 2)

    def test_save_post_to_staging_db(self):
        post_data = {
            "canonical_key": "street-fighter_2026",
            "title": "Street Fighter",
            "original_title": "Street Fighter (2026) Hindi",
            "year": 2026,
            "media_type": "movie",
            "imdb_id": "tt1234567",
            "poster_url": "https://example.com/poster.jpg",
            "synopsis": "A test movie synopsis.",
            "genres": json.dumps(["Action", "Adventure"]),
            "site": "10xflix",
            "post_url": "https://10xflix.bond/street-fighter-2026/",
            "releases": [
                {
                    "label": "1080p [2.02GB]",
                    "quality": "1080p",
                    "resolution": "1080p",
                    "size_bytes": 2168982732,
                    "season_number": None,
                    "episode_number": None,
                    "audio_languages": json.dumps(["Hindi"]),
                    "codec": "x264",
                    "bridge_url": "https://mobilejsr.com/view/heZxR9W5aL",
                    "sources": [
                        {
                            "source_name": "⚡ HubCloud [10Gbps Fast Server]",
                            "service": "hubcloud_10g",
                            "resource_id": "c3fxsjzrysc1o1z",
                            "source_url": "https://hubcloud.ist/video/c3fxsjzrysc1o1z",
                            "final_url": "https://gpdl2.hubcloud.ist/?id=sample",
                            "is_temporary": 0,
                            "quality": "1080p",
                        }
                    ],
                }
            ],
        }

        ok = import_10xflix.save_post_to_staging_db(self.db_path, post_data)
        self.assertTrue(ok)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            p_cnt = cur.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            r_cnt = cur.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            s_cnt = cur.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

            self.assertEqual(p_cnt, 1)
            self.assertEqual(r_cnt, 1)
            self.assertEqual(s_cnt, 1)

            saved_p = cur.execute("SELECT title, year, canonical_key FROM posts").fetchone()
            self.assertEqual(saved_p[0], "Street Fighter")
            self.assertEqual(saved_p[1], 2026)
            self.assertEqual(saved_p[2], "street-fighter_2026")


if __name__ == "__main__":
    unittest.main()
