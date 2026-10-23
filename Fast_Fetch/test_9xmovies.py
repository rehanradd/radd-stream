#!/usr/bin/env python3
"""
test_9xmovies.py — Offline Unit Tests for 9xmovies Importer & Bridge Parser
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_9xmovies import (
    clean_9xmovies_title,
    init_staging_db,
    parse_9xmovies_content,
    parse_size_string,
    save_post_to_staging,
)


class Test9xmoviesImporter(unittest.TestCase):
    def test_clean_9xmovies_title_movie(self):
        raw = "Star Wars: Episode IX – The Rise of Skywalker (2019) Hindi ORG Dual Audio 1080p | 720p | 480p BluRay ESubs Download"
        title, year, season, mtype, key = clean_9xmovies_title(raw)
        self.assertIn("Star Wars", title)
        self.assertIn("Skywalker", title)
        self.assertEqual(year, 2019)
        self.assertIsNone(season)
        self.assertEqual(mtype, "movie")
        self.assertTrue(key.startswith("star-wars"))
        self.assertIn("2019", key)

    def test_clean_9xmovies_title_series(self):
        raw = "The Night Manager S01 (2023) Hindi Complete Web Series 720p HDRip"
        title, year, season, mtype, key = clean_9xmovies_title(raw)
        self.assertIn("The Night Manager", title)
        self.assertEqual(year, 2023)
        self.assertEqual(season, 1)
        self.assertEqual(mtype, "series")

    def test_parse_size_string(self):
        self.assertEqual(parse_size_string("2.6GB"), int(2.6 * 1024**3))
        self.assertEqual(parse_size_string("650MB"), int(650 * 1024**2))
        self.assertEqual(parse_size_string("1.4GB"), int(1.4 * 1024**3))
        self.assertIsNone(parse_size_string("invalid"))
        self.assertIsNone(parse_size_string(None))

    def test_parse_9xmovies_content(self):
        sample_html = """
        <p><img src="https://blogger.googleusercontent.com/img/b/R29vZ2xl/test/s320/poster.jpg" /></p>
        <p>IMDb: <a href="https://www.imdb.com/title/tt2527338/">tt2527338</a></p>
        <p>|| 1080p Download Links [2.6GB] ||</p>
        <p><a href="https://linksddr.com/view/98G4s90PXx">Download 1080p</a></p>
        <p>|| 720p Download Links [1.4GB] ||</p>
        <p><a href="https://linksddr.com/view/jZ4HySKWxb">Download 720p</a></p>
        <p>|| 480p Download Links [650MB] ||</p>
        <p><a href="https://linksddr.com/view/F2yXn6jGwW">Download 480p</a></p>
        """
        imdb_id, poster, releases = parse_9xmovies_content(
            sample_html, "Star Wars (2019) 1080p"
        )
        self.assertEqual(imdb_id, "tt2527338")
        self.assertIsNotNone(poster)
        self.assertIn("/s1600/", poster)
        self.assertEqual(len(releases), 3)

        q_list = [r["quality"] for r in releases]
        self.assertIn("1080P", q_list)
        self.assertIn("720P", q_list)
        self.assertIn("480P", q_list)

        r1080 = [r for r in releases if r["quality"] == "1080P"][0]
        self.assertEqual(r1080["bridge_url"], "https://linksddr.com/view/98G4s90PXx")
        self.assertEqual(r1080["size_bytes"], int(2.6 * 1024**3))

    def test_db_init_and_save(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = Path(tf.name)

        try:
            init_staging_db(db_path)

            # Insert test item in sitemap_cache
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 0);",
                    ("https://9xmovie.bayern/test-movie/", "test-movie"),
                )

            res = {
                "loc": "https://9xmovie.bayern/test-movie/",
                "success": True,
                "post": {
                    "canonical_key": "test-movie-2024",
                    "title": "Test Movie",
                    "original_title": "Test Movie 2024",
                    "year": 2024,
                    "media_type": "movie",
                    "imdb_id": "tt1234567",
                    "poster_url": "https://blogger.googleusercontent.com/poster.jpg",
                    "synopsis": "A great test movie.",
                    "genres": "Action",
                    "site": "9xmovies",
                    "post_url": "https://9xmovie.bayern/test-movie/",
                },
                "releases": [
                    {
                        "label": "1080P x264 2.6GB",
                        "quality": "1080P",
                        "resolution": "1080p",
                        "size_bytes": 2791728742,
                        "codec": "x264",
                        "season_number": None,
                        "episode_number": None,
                        "audio_languages": "Hindi",
                        "bridge_url": "https://linksddr.com/view/test1080",
                        "sources": [
                            {
                                "source_name": "⚡ HubCloud 10Gbps CDN",
                                "service": "hubcloud",
                                "resource_id": "testvideo1",
                                "source_url": "https://hubcloud.ist/video/testvideo1",
                                "final_url": "https://hubcloud.ist/video/testvideo1",
                                "is_temporary": 0,
                            }
                        ],
                    }
                ],
            }

            save_post_to_staging(db_path, res)

            # Verify contents
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                p_row = cur.execute(
                    "SELECT title, year, imdb_id FROM posts WHERE canonical_key = 'test-movie-2024';"
                ).fetchone()
                self.assertIsNotNone(p_row)
                self.assertEqual(p_row[0], "Test Movie")
                self.assertEqual(p_row[1], 2024)

                r_row = cur.execute(
                    "SELECT quality, bridge_url FROM releases WHERE post_canonical_key = 'test-movie-2024';"
                ).fetchone()
                self.assertIsNotNone(r_row)
                self.assertEqual(r_row[0], "1080P")

                s_row = cur.execute(
                    "SELECT source_name, service FROM sources;"
                ).fetchone()
                self.assertIsNotNone(s_row)
                self.assertEqual(s_row[1], "hubcloud")

                scraped = cur.execute(
                    "SELECT scraped FROM sitemap_cache WHERE loc = 'https://9xmovie.bayern/test-movie/';"
                ).fetchone()[0]
                self.assertEqual(scraped, 1)

        finally:
            if db_path.exists():
                os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
