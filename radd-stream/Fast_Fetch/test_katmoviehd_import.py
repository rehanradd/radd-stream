#!/usr/bin/env python3
"""
test_katmoviehd_import.py — Comprehensive unit tests for KatMovieHD staging importer.
Zero external dependencies. 100% Python standard library.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import import_katmoviehd


class TestTitleCleaning(unittest.TestCase):
    def test_movie_with_year(self):
        raw = "The Campaign (2012) Hindi Dubbed (ORG) &amp; English [Dual Audio] BluRay 1080p 720p 480p HD [Full Movie]"
        clean, year, season, ckey = import_katmoviehd.clean_katmoviehd_title(raw)
        self.assertEqual(clean, "The Campaign")
        self.assertEqual(year, 2012)
        self.assertIsNone(season)
        self.assertEqual(ckey, "the-campaign_2012")

    def test_series_with_season(self):
        raw = "The Punisher (Season 2) Hindi Dubbed (DD 5.1) &amp; English [Dual Audio] | WEB-DL 1080p 720p 480p HD [2017–2019 Marvel Series] [Episode 04 Added]"
        clean, year, season, ckey = import_katmoviehd.clean_katmoviehd_title(raw)
        self.assertEqual(clean, "The Punisher")
        self.assertEqual(year, 2017)
        self.assertEqual(season, 2)
        self.assertEqual(ckey, "the-punisher_s2")

    def test_multi_audio_and_4k(self):
        raw = "Colony (2026) Hindi Dubbed (ORG) &amp; Korean [Dual Audio] BluRay 4K 2160p 1080p 720p 480p SDR [Full Movie]"
        clean, year, season, ckey = import_katmoviehd.clean_katmoviehd_title(raw)
        self.assertEqual(clean, "Colony")
        self.assertEqual(year, 2026)
        self.assertIsNone(season)
        self.assertEqual(ckey, "colony_2026")


class TestDevalueChunkParsing(unittest.TestCase):
    def test_valid_chunk_parsing(self):
        chunk_line = json.dumps({
            "type": "chunk",
            "id": 1,
            "data": [
                {"success": 1, "data": 2},
                True,
                {"items": 3, "page": 10, "perPage": 11, "totalItems": 12, "totalPages": 12},
                [4],
                {"categories": 5, "created": 7, "id": 8, "post_status": 9, "post_title": 10, "slug": 11, "thumbnail_image": 12},
                [6],
                "action",
                "2026-10-18T12:00:00Z",
                "12345",
                "publish",
                "Test Movie (2026)",
                "test-movie-2026",
                "https://image.tmdb.org/t/p/w500/test.jpg"
            ]
        })
        items = import_katmoviehd.parse_sveltekit_chunk(chunk_line)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["slug"], "test-movie-2026")
        self.assertEqual(it["id"], "12345")
        self.assertEqual(it["post_title"], "Test Movie (2026)")
        self.assertEqual(it["categories"], ["action"])
        self.assertEqual(it["thumbnail_image"], "https://image.tmdb.org/t/p/w500/test.jpg")

    def test_empty_or_non_chunk(self):
        items = import_katmoviehd.parse_sveltekit_chunk('{"type":"data"}\n\n{"type":"skip"}')
        self.assertEqual(items, [])


class TestContentParsing(unittest.TestCase):
    def test_movie_releases_parsing(self):
        html_content = """
        <div>
          <a href="https://www.imdb.com/title/tt1790886/">IMDb Rating:-6.1/10</a>
          <h2>: DOWNLOAD LINKS :</h2>
          <a href="https://links.kmhd.me/file/The_4ea27398">480p Links [383MB]</a>
          <a href="https://links.kmhd.me/file/The_802fa3b8">720p Links [821MB]</a>
          <a href="https://links.kmhd.me/file/The_49a7402c">1080p 10bit Links [1.57GB]</a>
        </div>
        """
        releases = import_katmoviehd.parse_katmoviehd_releases(html_content)
        self.assertEqual(len(releases), 3)
        self.assertEqual(releases[0]["quality"], "480p")
        self.assertEqual(releases[0]["file_id"], "The_4ea27398")
        self.assertEqual(releases[1]["quality"], "720p")
        self.assertEqual(releases[1]["file_id"], "The_802fa3b8")
        self.assertEqual(releases[2]["quality"], "1080p")
        self.assertEqual(releases[2]["file_id"], "The_49a7402c")

    def test_series_episode_releases_parsing(self):
        html_content = """
        <div>
          <p class="p1"><b>Episode 1 - </b></p>
          <a href="https://links.kmhd.me/file/Marv_af24180c">1080p 10bit</a>
          <a href="https://links.kmhd.me/file/Marv_f0c22ba8">480p</a>
          <hr />
          <p class="p1"><b>Episode 2 - </b></p>
          <a href="https://links.kmhd.me/file/Marv_de55b0b9">1080p 10bit</a>
          <a href="https://links.kmhd.me/file/Marv_19f316fc">480p</a>
        </div>
        """
        releases = import_katmoviehd.parse_katmoviehd_releases(html_content, default_season=2)
        self.assertEqual(len(releases), 4)
        self.assertEqual(releases[0]["episode_number"], 1)
        self.assertEqual(releases[0]["season_number"], 2)
        self.assertEqual(releases[0]["file_id"], "Marv_af24180c")
        self.assertEqual(releases[2]["episode_number"], 2)
        self.assertEqual(releases[2]["season_number"], 2)
        self.assertEqual(releases[2]["file_id"], "Marv_de55b0b9")


class TestStagingDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "katmoviehd.db"
        import_katmoviehd.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_created(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            self.assertIn("sitemap_cache", tables)
            self.assertIn("posts", tables)
            self.assertIn("releases", tables)
            self.assertIn("sources", tables)

    def test_save_and_retrieve_post(self):
        post_data = {
            "canonical_key": "the-campaign_2012",
            "title": "The Campaign",
            "original_title": "The Campaign (2012)",
            "year": 2012,
            "media_type": "movie",
            "imdb_id": "tt1790886",
            "poster_url": "https://image.tmdb.org/t/p/w500/test.jpg",
            "synopsis": None,
            "genres": json.dumps(["comedy"]),
            "rating": 6.1,
            "site": "katmoviehd",
            "post_url": "https://new.katmoviehd.top/the-campaign-2012-hindi",
            "releases": [
                {
                    "label": "720p Links [821MB]",
                    "quality": "720p",
                    "resolution": "720p",
                    "size_bytes": 861150158,
                    "season_number": None,
                    "episode_number": None,
                    "audio_languages": json.dumps(["Hindi", "English"]),
                    "codec": "x264",
                    "bridge_url": "https://links.kmhd.me/file/The_802fa3b8",
                    "sources": [
                        {
                            "source_name": "⚡ HubCloud [FSL Cloudflare R2]",
                            "service": "fsl_r2",
                            "resource_id": "le9qbqhol77qush",
                            "source_url": "https://hubcloud.ist/drive/le9qbqhol77qush",
                            "final_url": "https://r2.cloudflarestorage.com/test",
                            "is_temporary": 0,
                            "quality": "720p",
                        },
                        {
                            "source_name": "⚡ PixelDrain [Direct CDN]",
                            "service": "pixeldrain",
                            "resource_id": "negn6f",
                            "source_url": "https://pixeldrain.com/u/negn6f",
                            "final_url": "https://pixeldrain.com/api/file/negn6f",
                            "is_temporary": 0,
                            "quality": "720p",
                        },
                    ],
                }
            ],
        }

        ok = import_katmoviehd.save_post_to_staging_db(self.db_path, post_data)
        self.assertTrue(ok)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            p_row = cur.execute("SELECT id, title, imdb_id, rating FROM posts WHERE canonical_key = 'the-campaign_2012'").fetchone()
            self.assertIsNotNone(p_row)
            self.assertEqual(p_row[1], "The Campaign")
            self.assertEqual(p_row[2], "tt1790886")
            self.assertEqual(p_row[3], 6.1)

            rel_row = cur.execute("SELECT id, label, quality, size_bytes FROM releases WHERE post_id = ?", (p_row[0],)).fetchone()
            self.assertIsNotNone(rel_row)
            self.assertEqual(rel_row[3], 861150158)

            src_rows = cur.execute("SELECT source_name, service, final_url FROM sources WHERE release_id = ?", (rel_row[0],)).fetchall()
            self.assertEqual(len(src_rows), 2)
            self.assertEqual(src_rows[0][1], "fsl_r2")
            self.assertEqual(src_rows[1][1], "pixeldrain")


if __name__ == "__main__":
    unittest.main()
