#!/usr/bin/env python3
"""
test_moviezguru.py — Offline Unit Tests for MoviezGuru Importer & Google CDN Resolver
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_moviezguru import (
    clean_moviezguru_title,
    init_staging_db,
    is_adult_content,
    parse_moviezguru_content,
    parse_size_string,
    save_post_to_staging,
)


class TestMoviezGuruImporter(unittest.TestCase):
    def test_clean_moviezguru_title_movie(self):
        raw = "Romanchakam (2026) Full Movie NETFLIX ORG. Hindi Dubbed WEBRip ESubs 720p 480p Download"
        title, year, season, mtype, key = clean_moviezguru_title(raw)
        self.assertIn("Romanchakam", title)
        self.assertEqual(year, 2026)
        self.assertIsNone(season)
        self.assertEqual(mtype, "movie")
        self.assertEqual(key, "romanchakam-2026")

    def test_clean_moviezguru_title_series(self):
        raw = "Mirzapur S03 (2024) Hindi Complete Web Series 720p HDRip"
        title, year, season, mtype, key = clean_moviezguru_title(raw)
        self.assertIn("Mirzapur", title)
        self.assertEqual(year, 2024)
        self.assertEqual(season, 3)
        self.assertEqual(mtype, "series")
        self.assertIn("s3", key)

    def test_parse_size_string(self):
        self.assertEqual(parse_size_string("450 MB"), int(450 * 1024**2))
        self.assertEqual(parse_size_string("1.3 GB"), int(1.3 * 1024**3))
        self.assertIsNone(parse_size_string("invalid"))
        self.assertIsNone(parse_size_string(None))

    def test_adult_filter(self):
        self.assertTrue(is_adult_content("Hotshots 18+ Sensual Web Series"))
        self.assertTrue(is_adult_content("Ullu Erotic Hindi Movie"))
        self.assertFalse(is_adult_content("Romanchakam (2026) Full Movie"))

    def test_parse_moviezguru_content(self):
        sample_html = """
        <p><img src="https://moviezguru.guru/wp-content/uploads/2026/10/poster.jpg" /></p>
        <p>IMDb: <a href="https://www.imdb.com/title/tt2527338/">tt2527338</a></p>
        <p>Romanchakam (2026) – [ORG. Hindi Dubbed] – 480p WEBRip (450 MB): <a href="https://mzgserver.shop/file/PAR67eDVwySa8vF">Download</a></p>
        <p>Romanchakam (2026) – [ORG. Hindi Dubbed] – 720p WEBRip (1.3 GB): <a href="https://mzgserver.shop/file/onI5f0F8nrURb7G">Download</a></p>
        """
        imdb_id, poster, releases = parse_moviezguru_content(
            sample_html, "Romanchakam (2026) 720p"
        )
        self.assertEqual(imdb_id, "tt2527338")
        self.assertIsNotNone(poster)
        self.assertEqual(len(releases), 2)

        q_list = [r["quality"] for r in releases]
        self.assertIn("480P", q_list)
        self.assertIn("720P", q_list)

        r720 = [r for r in releases if r["quality"] == "720P"][0]
        self.assertEqual(r720["bridge_url"], "https://mzgserver.shop/file/onI5f0F8nrURb7G")
        self.assertEqual(r720["size_bytes"], int(1.3 * 1024**3))

    def test_db_init_and_save(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = Path(tf.name)

        try:
            init_staging_db(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO sitemap_cache (loc, slug, scraped) VALUES (?, ?, 0);",
                    ("https://moviezguru.guru/test-movie/", "test-movie"),
                )

            res = {
                "loc": "https://moviezguru.guru/test-movie/",
                "success": True,
                "post": {
                    "canonical_key": "test-movie-2026",
                    "title": "Test Movie",
                    "original_title": "Test Movie 2026",
                    "year": 2026,
                    "media_type": "movie",
                    "imdb_id": "tt1234567",
                    "poster_url": "https://moviezguru.guru/poster.jpg",
                    "synopsis": "A great test movie.",
                    "genres": "Action",
                    "site": "moviezguru",
                    "post_url": "https://moviezguru.guru/test-movie/",
                },
                "releases": [
                    {
                        "label": "720P WEBRip 1.3 GB",
                        "quality": "720P",
                        "resolution": "720p",
                        "size_bytes": 1395864371,
                        "codec": "x264",
                        "season_number": None,
                        "episode_number": None,
                        "audio_languages": "Hindi",
                        "bridge_url": "https://mzgserver.shop/file/testfile",
                        "sources": [
                            {
                                "source_name": "⚡ Google CDN 10Gbps Direct",
                                "service": "google_drive",
                                "resource_id": "1fbNEX328pgWXE2W3vj83550DYSNaindJ",
                                "source_url": "https://drive.usercontent.google.com/download?id=1fbNEX328pgWXE2W3vj83550DYSNaindJ&export=download",
                                "final_url": "https://drive.usercontent.google.com/download?id=1fbNEX328pgWXE2W3vj83550DYSNaindJ&export=download",
                                "is_temporary": 0,
                            }
                        ],
                    }
                ],
            }

            save_post_to_staging(db_path, res)

            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                p_row = cur.execute(
                    "SELECT title, year, imdb_id FROM posts WHERE canonical_key = 'test-movie-2026';"
                ).fetchone()
                self.assertIsNotNone(p_row)
                self.assertEqual(p_row[0], "Test Movie")
                self.assertEqual(p_row[1], 2026)

                r_row = cur.execute(
                    "SELECT quality, bridge_url FROM releases WHERE post_canonical_key = 'test-movie-2026';"
                ).fetchone()
                self.assertIsNotNone(r_row)
                self.assertEqual(r_row[0], "720P")

                s_row = cur.execute(
                    "SELECT source_name, service FROM sources;"
                ).fetchone()
                self.assertIsNotNone(s_row)
                self.assertEqual(s_row[1], "google_drive")

                scraped = cur.execute(
                    "SELECT scraped FROM sitemap_cache WHERE loc = 'https://moviezguru.guru/test-movie/';"
                ).fetchone()[0]
                self.assertEqual(scraped, 1)

        finally:
            if db_path.exists():
                os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
