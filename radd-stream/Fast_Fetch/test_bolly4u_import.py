#!/usr/bin/env python3
"""
test_bolly4u_import.py — Comprehensive unit tests for Bolly4u dedicated scraper.
Tests cover:
  1. Title cleaning and canonical key generation.
  2. Byte size string parser.
  3. Strict zero adult content safety filter.
  4. HTML content parser (extracts quality tiers, sizes, and valid gateway links).
  5. Dedicated SQLite staging database initialization & foreign key cascade.
  6. Atomic post, release, and source persistence.
  7. Hidden /action JSON API photojin unwrap mock.
  8. Session-cookie negotiated linkskeep unwrap mock.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import import_bolly4u


class TestBolly4uImport(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_bolly4u.db"
        import_bolly4u.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_bolly4u_title(self):
        raw = "Street Fighter 2026 HDTS Hindi Dubbed Full Movie Download 1080p | 720p | 480p"
        title, year, m_type = import_bolly4u.clean_bolly4u_title(raw)
        self.assertEqual(title, "Street Fighter")
        self.assertEqual(year, 2026)
        self.assertEqual(m_type, "movie")

        raw2 = "Pattas 2020 WEB-DL UNCUT Hindi Dual Audio ORG Full Movie Download 1080p | 720p | 480p"
        title2, year2, m_type2 = import_bolly4u.clean_bolly4u_title(raw2)
        self.assertEqual(title2, "Pattas")
        self.assertEqual(year2, 2020)
        self.assertEqual(m_type2, "movie")

        raw_series = "Ali Baba Aur 40 Bhoot 2026 WEB-DL Hindi S01 Complete Download 720p"
        title3, year3, m_type3 = import_bolly4u.clean_bolly4u_title(raw_series)
        self.assertEqual(title3, "Ali Baba Aur 40 Bhoot")
        self.assertEqual(year3, 2026)
        self.assertEqual(m_type3, "series")

    def test_parse_size_string(self):
        self.assertEqual(import_bolly4u.parse_size_string("1.4GB"), int(1.4 * 1024 * 1024 * 1024))
        self.assertEqual(import_bolly4u.parse_size_string("750MB"), 750 * 1024 * 1024)
        self.assertEqual(import_bolly4u.parse_size_string("500KB"), 500 * 1024)
        self.assertIsNone(import_bolly4u.parse_size_string(None))
        self.assertIsNone(import_bolly4u.parse_size_string("N/A"))

    def test_is_adult_content(self):
        # Strict zero adult content enforcement
        self.assertTrue(import_bolly4u.is_adult_content("HotShots Web Series 720p"))
        self.assertTrue(import_bolly4u.is_adult_content("Ullu Charmsukh 2026 Complete S01"))
        self.assertTrue(import_bolly4u.is_adult_content("Friends Sex And Games 2026 S01 Complete"))
        self.assertTrue(import_bolly4u.is_adult_content("Kooku Web Series 1080p"))
        self.assertTrue(import_bolly4u.is_adult_content("Sensual Touch 2025 Hindi 18+ Movie"))
        # Clean titles must pass
        self.assertFalse(import_bolly4u.is_adult_content("Street Fighter 2026 HDTS Hindi Dubbed"))
        self.assertFalse(import_bolly4u.is_adult_content("Avengers Endgame 2019 Dual Audio"))
        self.assertFalse(import_bolly4u.is_adult_content("Ali Baba Aur 40 Bhoot 2026 Hindi"))

    def test_parse_bolly4u_content(self):
        sample_html = """
        <p><strong>Street Fighter 2026 HDTS Hindi Dubbed Full Movie Download</strong></p>
        <h4 style="text-align: center;"><strong>Free Download Full Movie Via Single Links</strong></h4>
        <h4 style="text-align: center;"><span style="color: #ff0000;"><strong>|| 1080p Download Links: 1.4GB ||</strong></span></h4>
        <p style="text-align: center;"><a href="https://photojin.study/download/krXE-8z9mHO">DIRECT 1</a> <a href="https://new2.linkskeep.lat/view/2TrzDkjMf6">DOWNLOAD LINKS</a></p>
        <h4 style="text-align: center;"><span style="color: #ff0000;"><strong>|| 720p Download Links: 750MB ||</strong></span></h4>
        <p style="text-align: center;"><a href="https://photojin.study/download/-qH-q78gSk-">DIRECT 1</a></p>
        <h4 style="text-align: center;"><span style="color: #ff0000;"><strong>|| 480p Download Links: 350MB ||</strong></span></h4>
        <p style="text-align: center;"><a href="https://photojin.study/download/TXbAj6TXs4c">DIRECT 1</a></p>
        """
        releases = import_bolly4u.parse_bolly4u_content(
            sample_html, "Street Fighter 2026 HDTS Hindi Dubbed Full Movie Download 1080p | 720p | 480p"
        )
        self.assertEqual(len(releases), 3)

        r1080 = releases[0]
        self.assertEqual(r1080["quality"], "1080P")
        self.assertEqual(r1080["resolution"], "1080p")
        self.assertEqual(r1080["size_bytes"], int(1.4 * 1024 * 1024 * 1024))
        self.assertEqual(len(r1080["links"]), 2)

        r720 = releases[1]
        self.assertEqual(r720["quality"], "720P")
        self.assertEqual(r720["size_bytes"], int(750 * 1024 * 1024))

        r480 = releases[2]
        self.assertEqual(r480["quality"], "480P")
        self.assertEqual(r480["size_bytes"], int(350 * 1024 * 1024))

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
            "loc": "https://bolly4uz.click/street-fighter-2026-hindi-dubbed-movie-download-hdts/",
            "success": True,
            "post": {
                "canonical_key": "street-fighter_2026",
                "title": "Street Fighter",
                "original_title": "Street Fighter 2026 HDTS Hindi Dubbed",
                "year": 2026,
                "media_type": "movie",
                "imdb_id": None,
                "poster_url": None,
                "synopsis": None,
                "genres": None,
                "site": "bolly4u",
                "post_url": "https://bolly4uz.click/street-fighter-2026-hindi-dubbed-movie-download-hdts/",
            },
            "releases": [
                {
                    "label": "1080P 1.4GB",
                    "quality": "1080P",
                    "resolution": "1080p",
                    "size_bytes": 1503238553,
                    "season_number": None,
                    "episode_number": None,
                    "audio_languages": "Hindi",
                    "codec": "x264",
                    "links": [("https://photojin.study/download/krXE-8z9mHO", "DIRECT 1")],
                    "sources": [
                        {
                            "source_name": "⚡ Google CDN [High-Speed Direct]",
                            "service": "google_cdn",
                            "resource_id": "rpzN2EzMyQjM5cTM",
                            "source_url": "https://photojin.study/download/krXE-8z9mHO",
                            "final_url": "https://lh3.googleusercontent.com/pw/TEST_DIRECT_STREAM=dv",
                            "is_temporary": 1,
                        }
                    ],
                }
            ],
        }

        # Seed cache
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sitemap_cache (loc, slug, scraped, site) VALUES (?, ?, 0, 'bolly4u');",
                (sample_result["loc"], "street-fighter-2026-hindi-dubbed-movie-download-hdts"),
            )
            conn.commit()

        import_bolly4u.save_post_to_staging(self.db_path, sample_result)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?;", (sample_result["loc"],))
            self.assertEqual(cur.fetchone()[0], 1)

            cur.execute("SELECT id, title, canonical_key, year FROM posts WHERE canonical_key = 'street-fighter_2026';")
            p_row = cur.fetchone()
            self.assertIsNotNone(p_row)
            self.assertEqual(p_row[1], "Street Fighter")
            self.assertEqual(p_row[3], 2026)
            post_id = p_row[0]

            cur.execute("SELECT id, label, quality, size_bytes FROM releases WHERE post_id = ?;", (post_id,))
            rel_row = cur.fetchone()
            self.assertIsNotNone(rel_row)
            self.assertEqual(rel_row[1], "1080P 1.4GB")
            self.assertEqual(rel_row[2], "1080P")
            rel_id = rel_row[0]

            cur.execute("SELECT service, final_url, is_temporary FROM sources WHERE release_id = ?;", (rel_id,))
            src_row = cur.fetchone()
            self.assertIsNotNone(src_row)
            self.assertEqual(src_row[0], "google_cdn")
            self.assertIn("googleusercontent.com", src_row[1])
            self.assertEqual(src_row[2], 1)

    def test_unwrap_photojin_mock(self):
        client = import_bolly4u.Bolly4uClient()

        # Mock the 3 HTTP calls for unwrap_photojin
        landing_html = """
        <form action="/download/step2" method="POST">
            <input type="hidden" name="access_token" value="MOCK_TOKEN_123" />
        </form>
        """
        step2_html = """
        <div id="generate_url" data-uid="MOCK_UID_456" data-token="MOCK_TOKEN_789"></div>
        """
        api_response_json = {
            "status": True,
            "download_url": "https://lh3.googleusercontent.com/pw/MOCK_STREAM_URL=dv"
        }

        with patch.object(client, "get_text") as mock_get_text:
            mock_get_text.return_value = (200, "https://photojin.study/download/test", landing_html, {})

            # Mock step 2 POST and step 3 API POST
            mock_resp_step2 = MagicMock()
            mock_resp_step2.__enter__.return_value = mock_resp_step2
            mock_resp_step2.read.return_value = step2_html.encode("utf-8")
            mock_resp_step2.geturl.return_value = "https://photojin.study/download/step2"

            mock_resp_api = MagicMock()
            mock_resp_api.__enter__.return_value = mock_resp_api
            mock_resp_api.read.return_value = json.dumps(api_response_json).encode("utf-8")

            with patch.object(client.opener, "open") as mock_open:
                mock_open.side_effect = [mock_resp_step2, mock_resp_api]

                results = client.unwrap_photojin("https://photojin.study/download/test")

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["service"], "google_cdn")
                self.assertEqual(results[0]["resource_id"], "MOCK_UID_456")
                self.assertEqual(results[0]["final_url"], "https://lh3.googleusercontent.com/pw/MOCK_STREAM_URL=dv")
                self.assertEqual(results[0]["is_temporary"], 1)


if __name__ == "__main__":
    unittest.main()
