#!/usr/bin/env python3
"""
test_filmyzilla_import.py — Comprehensive unit tests for FilmyZilla dedicated scraper.
Tests cover:
  1. Title cleaning and canonical key generation.
  2. Byte size string parser.
  3. Quality, resolution, and codec parser.
  4. Movie page HTML parser (title, poster, genres, release servers).
  5. Isolated SQLite staging database initialization & foreign key cascade.
  6. Atomic post, release, and source persistence.
  7. Direct Google CDN redirect resolution.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import import_filmyzilla


class TestFilmyZillaImport(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_filmyzilla.db"
        import_filmyzilla.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_filmyzilla_title(self):
        raw = "Street Fighter (2026) Hindi Dubbed Movie Free Download Filmyzilla"
        title, year, canon = import_filmyzilla.clean_filmyzilla_title(raw)
        self.assertEqual(title, "Street Fighter")
        self.assertEqual(year, 2026)
        self.assertEqual(canon, "street_fighter__2026")

        raw2 = "Aryabhatt Ka Zero (2026) Hindi Movie Free Download Filmyzilla"
        title2, year2, canon2 = import_filmyzilla.clean_filmyzilla_title(raw2)
        self.assertEqual(title2, "Aryabhatt Ka Zero")
        self.assertEqual(year2, 2026)
        self.assertEqual(canon2, "aryabhatt_ka_zero__2026")

        raw3 = "Blue (2026) Hindi Dubbed Movie"
        title3, year3, canon3 = import_filmyzilla.clean_filmyzilla_title(raw3)
        self.assertEqual(title3, "Blue")
        self.assertEqual(year3, 2026)
        self.assertEqual(canon3, "blue__2026")

    def test_parse_size_string(self):
        self.assertEqual(import_filmyzilla.parse_size_string("1.03 GB"), int(1.03 * 1024 * 1024 * 1024))
        self.assertEqual(import_filmyzilla.parse_size_string("450 MB"), int(450 * 1024 * 1024))
        self.assertEqual(import_filmyzilla.parse_size_string("500 KB"), int(500 * 1024))
        self.assertIsNone(import_filmyzilla.parse_size_string(None))
        self.assertIsNone(import_filmyzilla.parse_size_string("N/A"))

    def test_parse_quality_and_codec(self):
        q1, r1, c1 = import_filmyzilla.parse_quality_and_codec("Street Fighter (2026) Movie 1080p HDTS.mkv")
        self.assertEqual(q1, "1080p HDTS")
        self.assertEqual(r1, "1080p")
        self.assertEqual(c1, "x264")

        q2, r2, c2 = import_filmyzilla.parse_quality_and_codec("Street Fighter (2026) Movie HEVC 720p HDTS.mkv")
        self.assertEqual(q2, "720p HDTS")
        self.assertEqual(r2, "720p")
        self.assertEqual(c2, "hevc")

        q3, r3, c3 = import_filmyzilla.parse_quality_and_codec("Street Fighter (2026) Movie 480p HDRip.mkv")
        self.assertEqual(q3, "480p HDRip")
        self.assertEqual(r3, "480p")
        self.assertEqual(c3, "x264")

    def test_parse_filmyzilla_movie_page(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Street Fighter (2026) Hindi Dubbed Movie Free Download Filmyzilla</title>
        </head>
        <body>
            <img src="https://www.filmyzilla75.com/files/images/Street-fighter-(2026)-hindi-dubbed-movie.jpg?t=123" height="300" width="200" alt="poster" />
            <div class="info">
                <p>Genres : Action, Adventure</p>
                <p>Language : Hindi, English</p>
                <p>Release Date : 16 Oct 2026</p>
            </div>
            <div class="links">
                <a href="https://www.filmyzilla75.com/server/39913/Street-Fighter-(2026)-Hindi-Dubbed-Movie-480p-HDTS.mkv.html">Street Fighter (2026) Hindi Dubbed Movie 480p HDTS.mkv</a>
                <a href="/server/39911/Street-Fighter-(2026)-Hindi-Dubbed-Movie-720p-HDTS.mkv.html">Street Fighter (2026) Hindi Dubbed Movie 720p HDTS.mkv</a>
            </div>
        </body>
        </html>
        """
        parsed = import_filmyzilla.parse_filmyzilla_movie_page(
            sample_html,
            "https://www.filmyzilla75.com/movie/22418/Street-fighter-(2026)-hindi-dubbed-movie.html"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "Street Fighter")
        self.assertEqual(parsed["year"], 2026)
        self.assertEqual(parsed["canonical_key"], "street_fighter__2026")
        self.assertEqual(parsed["poster_url"], "https://www.filmyzilla75.com/files/images/Street-fighter-(2026)-hindi-dubbed-movie.jpg")
        self.assertIn("Action", parsed["genres"])
        self.assertIn("Hindi", parsed["languages"])
        self.assertEqual(len(parsed["servers"]), 2)
        self.assertEqual(parsed["servers"][0]["server_id"], "39913")
        self.assertEqual(parsed["servers"][0]["quality"], "480p HDTS")
        self.assertEqual(parsed["servers"][1]["server_id"], "39911")
        self.assertEqual(parsed["servers"][1]["quality"], "720p HDTS")

    def test_modern_thefilmyzilla_page_parsing(self):
        sample_modern_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Uunchai (2022) Hindi HD FilmyZilla</title>
            <meta property="og:image" content="https://thefilmyzilla.in/upload/uunchai-2022-hindi-hd-4215.webp">
        </head>
        <body>
            <div class="info-row"><div class="info-label">Release Year</div><div class="info-value">2022</div></div>
            <div class="info-row"><div class="info-label">Genres</div><div class="info-value">Bollywood,Comedy,Drama</div></div>
            <div class="info-row"><div class="info-label">Language</div><div class="info-value language">Hindi</div></div>
            <div class="info-row"><div class="info-label">Director</div><div class="info-value">Sooraj Barjatya</div></div>
            <div class="info-row"><div class="info-label">Cast</div><div class="info-value">Amitabh Bachchan, Anupam Kher, Boman Irani</div></div>
            <a href="/server/uunchai-2022-hindi-hd-4215.html" class="file-button">Download Now</a>
        </body>
        </html>
        """
        parsed = import_filmyzilla.parse_filmyzilla_movie_page(
            sample_modern_html,
            "https://thefilmyzilla.in/uunchai-2022-hindi-hd-4215.html"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "Uunchai")
        self.assertEqual(parsed["year"], 2022)
        self.assertEqual(parsed["canonical_key"], "uunchai__2022")
        self.assertEqual(parsed["director"], "Sooraj Barjatya")
        self.assertEqual(parsed["cast_names"], "Amitabh Bachchan, Anupam Kher, Boman Irani")
        self.assertEqual(parsed["poster_url"], "https://thefilmyzilla.in/upload/uunchai-2022-hindi-hd-4215.webp")
        self.assertIn("Bollywood", parsed["genres"])
        self.assertIn("Hindi", parsed["languages"])
        self.assertIn("/server/uunchai-2022-hindi-hd-4215.html", parsed["modern_server_page"])

    def test_staging_db_init_and_foreign_keys(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            self.assertIn("sitemap_cache", tables)
            self.assertIn("posts", tables)
            self.assertIn("releases", tables)
            self.assertIn("sources", tables)

    def test_save_post_to_staging_db(self):
        post_data = {
            "canonical_key": "street_fighter__2026",
            "title": "Street Fighter",
            "original_title": "Street Fighter (2026) Hindi Dubbed Movie Free Download Filmyzilla",
            "year": 2026,
            "media_type": "movie",
            "imdb_id": None,
            "poster_url": "https://www.filmyzilla75.com/files/images/Street-fighter-(2026).jpg",
            "genres": json.dumps(["Action", "Adventure"]),
            "synopsis": "Released: 16 Oct 2026",
            "site": "filmyzilla",
            "post_url": "https://www.filmyzilla75.com/movie/22418/Street-fighter.html",
            "releases": [
                {
                    "label": "Street Fighter 720p HDTS",
                    "quality": "720p HDTS",
                    "resolution": "720p",
                    "size_bytes": 1105954119,
                    "season_number": None,
                    "episode_number": None,
                    "audio_languages": json.dumps(["Hindi"]),
                    "codec": "x264",
                    "bridge_url": "https://www.filmyzilla75.com/download/39911/server_1",
                    "sources": [
                        {
                            "source_name": "⚡ Google CDN Direct Stream",
                            "service": "google_cdn",
                            "resource_id": "39911",
                            "source_url": "https://www.filmyzilla75.com/download/39911/server_1",
                            "final_url": "https://lh3.googleusercontent.com/pw/sample-direct-stream",
                            "is_temporary": 1,
                            "quality": "720p HDTS",
                        },
                        {
                            "source_name": "⚡ FilmyZilla Direct Gateway",
                            "service": "filmyzilla_server",
                            "resource_id": "39911",
                            "source_url": "https://www.filmyzilla75.com/server/39911/Street-Fighter.html",
                            "final_url": "https://www.filmyzilla75.com/download/39911/server_1",
                            "is_temporary": 0,
                            "quality": "720p HDTS",
                        },
                    ],
                }
            ],
        }

        ok = import_filmyzilla.save_post_to_staging_db(self.db_path, post_data)
        self.assertTrue(ok)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            post_cnt = cur.execute("SELECT count(*) FROM posts").fetchone()[0]
            rel_cnt = cur.execute("SELECT count(*) FROM releases").fetchone()[0]
            src_cnt = cur.execute("SELECT count(*) FROM sources").fetchone()[0]
            self.assertEqual(post_cnt, 1)
            self.assertEqual(rel_cnt, 1)
            self.assertEqual(src_cnt, 2)

    def test_resolve_direct_cdn(self):
        client = import_filmyzilla.FilmyZillaClient()
        fake_redirect = import_filmyzilla.urllib.error.HTTPError(
            url="https://www.filmyzilla75.com/download/39911/server_1",
            code=302,
            msg="Found",
            hdrs={"Location": "https://video-downloads.googleusercontent.com/sample_hash"},
            fp=None,
        )

        with patch.object(client.no_redirect_opener, "open", side_effect=fake_redirect):
            cdn = client.resolve_direct_cdn(
                "https://www.filmyzilla75.com/download/39911/server_1",
                referer="https://www.filmyzilla75.com/server/39911/page.html"
            )
            self.assertEqual(cdn, "https://video-downloads.googleusercontent.com/sample_hash")


if __name__ == "__main__":
    unittest.main()
