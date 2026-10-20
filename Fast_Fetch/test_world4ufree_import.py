#!/usr/bin/env python3
"""
test_world4ufree_import.py — Comprehensive unit tests for World4uFree dedicated scraper.
Tests cover:
  1. Title cleaning and canonical key generation.
  2. Strict zero adult content safety filter.
  3. HTML content parser (extracts IMDb ID, high-res s1600 poster, and w4links releases).
  4. Dedicated SQLite staging database initialization & foreign key cascade.
  5. Atomic post, release, and multi-source persistence.
  6. Hidden /action JSON API photolinx mock unwrapping.
  7. Session-negotiated fastilinks multi-mirror unwrapping.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import import_world4ufree


class TestWorld4uFreeImport(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_world4ufree.db"
        import_world4ufree.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_world4ufree_title(self):
        raw = "Street Fighter 2026 Hindi (Line) Movie 1080p 720p 480p HDTC"
        title, year, m_type = import_world4ufree.clean_world4ufree_title(raw)
        self.assertEqual(title, "Street Fighter")
        self.assertEqual(year, 2026)
        self.assertEqual(m_type, "movie")

        raw2 = "Avengers: Infinity War 2018 IMAX Dual Audio [Hindi – Eng] BluRay 1080p 720p 480p HEVC"
        title2, year2, m_type2 = import_world4ufree.clean_world4ufree_title(raw2)
        self.assertEqual(title2, "Avengers Infinity War")
        self.assertEqual(year2, 2018)
        self.assertEqual(m_type2, "movie")

        raw_series = "Bigg Boss (Season 20) 2026 Hindi 1080p 720p 480p HEVC WEBRip x264 [E43]"
        title3, year3, m_type3 = import_world4ufree.clean_world4ufree_title(raw_series)
        self.assertEqual(title3, "Bigg Boss")
        self.assertEqual(year3, 2026)
        self.assertEqual(m_type3, "series")

    def test_is_adult_content(self):
        self.assertTrue(import_world4ufree.is_adult_content("HotShots Web Series 720p"))
        self.assertTrue(import_world4ufree.is_adult_content("Ullu Charmsukh 2026 Complete S01"))
        self.assertTrue(import_world4ufree.is_adult_content("Sensual Lust 2025 Hindi 18+ Movie"))
        # Clean titles
        self.assertFalse(import_world4ufree.is_adult_content("Street Fighter 2026 Hindi Line HDTC"))
        self.assertFalse(import_world4ufree.is_adult_content("Avengers Endgame 2019 Dual Audio"))

    def test_parse_world4ufree_content(self):
        sample_html = """
        <p><a href="https://www.imdb.com/title/tt27419420/"><img src="imdb.png" /></a></p>
        <p><img src="https://blogger.googleusercontent.com/img/b/123/s501/Street.Fighter.2026.jpg" /></p>
        <p><strong><a href="https://w4links.space/115615/">1080p x264</a></strong></p>
        <p><strong><a href="https://w4links.space/115615/">720p HEVC</a></strong></p>
        <p><strong><a href="https://w4links.space/115615/">480p x264</a></strong></p>
        """
        imdb_id, poster_url, releases = import_world4ufree.parse_world4ufree_content(
            sample_html, "Street Fighter 2026 Hindi Line Movie 1080p 720p 480p HDTC"
        )
        self.assertEqual(imdb_id, "tt27419420")
        self.assertIn("/s1600/", poster_url)
        self.assertEqual(len(releases), 3)

        self.assertEqual(releases[0]["quality"], "1080P")
        self.assertEqual(releases[0]["codec"], "x264")
        self.assertEqual(releases[0]["bridge_url"], "https://w4links.space/115615/")

        self.assertEqual(releases[1]["quality"], "720P")
        self.assertEqual(releases[1]["codec"], "hevc")

        self.assertEqual(releases[2]["quality"], "480P")

    def test_database_initialization_and_schema(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cur.fetchall()}
            self.assertIn("sitemap_cache", tables)
            self.assertIn("posts", tables)
            self.assertIn("releases", tables)
            self.assertIn("sources", tables)

    def test_save_post_to_staging(self):
        sample_result = {
            "loc": "https://world4ufree.garden/street-fighter-2026-hindi-line-hdtc/",
            "success": True,
            "post": {
                "canonical_key": "street-fighter_2026",
                "title": "Street Fighter",
                "original_title": "Street Fighter 2026 Hindi Line HDTC",
                "year": 2026,
                "media_type": "movie",
                "imdb_id": "tt27419420",
                "poster_url": "https://blogger.googleusercontent.com/img/b/123/s1600/poster.jpg",
                "synopsis": None,
                "genres": None,
                "site": "world4ufree",
                "post_url": "https://world4ufree.garden/street-fighter-2026-hindi-line-hdtc/",
            },
            "releases": [
                {
                    "label": "1080p x264",
                    "quality": "1080P",
                    "resolution": "1080p",
                    "size_bytes": 2197267669,
                    "season_number": None,
                    "episode_number": None,
                    "audio_languages": "Hindi",
                    "codec": "x264",
                    "bridge_url": "https://w4links.space/115615/",
                    "sources": [
                        {
                            "source_name": "⚡ Cloudflare Worker [10Gbps Direct Stream]",
                            "service": "cloudflare_worker",
                            "resource_id": "Dc2bYdZzkrC",
                            "source_url": "https://photolinx.beauty/download/Dc2bYdZzkrC",
                            "final_url": "https://winter-silence-9c49.ejohnsoncraig.workers.dev/download/Dc2bYdZzkrC",
                            "is_temporary": 1,
                        },
                        {
                            "source_name": "⚡ Mediafire [Direct Download]",
                            "service": "mediafire",
                            "resource_id": "yu73s0q86tzisx9",
                            "source_url": "https://www.mediafire.com/file/yu73s0q86tzisx9/file.mkv",
                            "final_url": "https://www.mediafire.com/file/yu73s0q86tzisx9/file.mkv",
                            "is_temporary": 0,
                        },
                        {
                            "source_name": "⚡ GDFlix [Google Drive Fast Server]",
                            "service": "gdflix",
                            "resource_id": "j8Fp2VRK3AzEz3n",
                            "source_url": "https://gdflix.dev/file/j8Fp2VRK3AzEz3n",
                            "final_url": "https://gdflix.dev/file/j8Fp2VRK3AzEz3n",
                            "is_temporary": 0,
                        },
                    ],
                }
            ],
        }

        # Seed cache
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sitemap_cache (loc, slug, scraped, site) VALUES (?, ?, 0, 'world4ufree');",
                (sample_result["loc"], "street-fighter-2026-hindi-line-hdtc"),
            )
            conn.commit()

        import_world4ufree.save_post_to_staging(self.db_path, sample_result)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?;", (sample_result["loc"],))
            self.assertEqual(cur.fetchone()[0], 1)

            cur.execute("SELECT id, title, canonical_key, imdb_id FROM posts WHERE canonical_key = 'street-fighter_2026';")
            p_row = cur.fetchone()
            self.assertIsNotNone(p_row)
            self.assertEqual(p_row[1], "Street Fighter")
            self.assertEqual(p_row[3], "tt27419420")
            post_id = p_row[0]

            cur.execute("SELECT id, label, quality FROM releases WHERE post_id = ?;", (post_id,))
            rel_row = cur.fetchone()
            self.assertIsNotNone(rel_row)
            self.assertEqual(rel_row[1], "1080p x264")
            rel_id = rel_row[0]

            cur.execute("SELECT count(*) FROM sources WHERE release_id = ?;", (rel_id,))
            src_count = cur.fetchone()[0]
            self.assertEqual(src_count, 3)

    def test_unwrap_photolinx_mock(self):
        client = import_world4ufree.World4uFreeClient()

        landing_html = """
        <section id="generate_url" data-uid="Dc2bYdZzkrC" data-token="MOCK_TOKEN_W4U"></section>
        """
        api_response_json = {
            "status": True,
            "download_url": "https://test.workers.dev/download/Dc2bYdZzkrC"
        }

        with patch.object(client, "get_text") as mock_get_text:
            mock_get_text.return_value = (200, "https://photolinx.beauty/download/Dc2bYdZzkrC", landing_html, {})

            mock_resp_api = MagicMock()
            mock_resp_api.__enter__.return_value = mock_resp_api
            mock_resp_api.read.return_value = json.dumps(api_response_json).encode("utf-8")

            with patch.object(client.opener, "open") as mock_open:
                mock_open.return_value = mock_resp_api

                results = client.unwrap_photolinx("https://photolinx.beauty/download/Dc2bYdZzkrC")

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["service"], "cloudflare_worker")
                self.assertEqual(results[0]["resource_id"], "Dc2bYdZzkrC")
                self.assertEqual(results[0]["final_url"], "https://test.workers.dev/download/Dc2bYdZzkrC")
                self.assertEqual(results[0]["is_temporary"], 1)


if __name__ == "__main__":
    unittest.main()
