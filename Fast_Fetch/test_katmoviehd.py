#!/usr/bin/env python3
"""
test_katmoviehd.py — Offline Unit Tests for KatMovieHD Importer & BBUpload/GoFile Resolver
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_katmoviehd import (
    clean_katmoviehd_title,
    init_staging_db,
    parse_katmoviehd_releases,
    save_post_to_staging_db,
)


class TestKatMovieHDImporter(unittest.TestCase):
    def test_clean_katmoviehd_title_movie(self):
        raw = "Download The Last House (2026) WEBRip 1080p 720p 480p [Hindi Dubbed] Full Movie"
        clean, year, season, canonical_key = clean_katmoviehd_title(raw)
        self.assertIn("The Last House", clean)
        self.assertEqual(year, 2026)
        self.assertIsNone(season)
        self.assertEqual(canonical_key, "the-last-house_2026")

    def test_clean_katmoviehd_title_series(self):
        raw = "MobLand Season 1 (Hindi Dubbed) All Episodes | TV Series"
        clean, year, season, canonical_key = clean_katmoviehd_title(raw)
        self.assertIn("MobLand", clean)
        self.assertEqual(season, 1)
        self.assertIn("_s1", canonical_key)

    def test_parse_katmoviehd_releases_bbupload_and_gofile(self):
        sample_html = """
        <iframe src="https://vd.1xplayer.com/play/ftt32268156?tr=5" width="100%" height="360"></iframe>
        <h2><a href="https://download.bbupload.to/download?v=FS6HLPAM">&gt; 1080pDL | GoFILE &lt;</a></h2>
        <h2><a href="https://download.bbupload.to/download?v=Y1RKMAOX">&gt; 720pDL | GoFILE &lt;</a></h2>
        <h2><a href="https://gofile.io/d/QwotlNmo">&gt; 480pDL | GoFILE &lt;</a></h2>
        """
        releases = parse_katmoviehd_releases(sample_html)
        self.assertEqual(len(releases), 4)

        # Check 1xplayer
        r_player = [r for r in releases if r["source_type"] == "1xplayer"][0]
        self.assertEqual(r_player["file_id"], "ftt32268156")

        # Check bbupload 1080p
        r_1080 = [r for r in releases if "1080p" in r["label"]][0]
        self.assertEqual(r_1080["source_type"], "bbupload")
        self.assertEqual(r_1080["file_id"], "FS6HLPAM")
        self.assertEqual(r_1080["quality"], "1080p")

        # Check gofile 480p
        r_480 = [r for r in releases if "480p" in r["label"]][0]
        self.assertEqual(r_480["source_type"], "gofile")
        self.assertEqual(r_480["file_id"], "QwotlNmo")
        self.assertEqual(r_480["quality"], "480p")

    def test_parse_katmoviehd_releases_episodes(self):
        sample_html = """
        <p><a href="https://gofile.io/d/VB07BKH4">Episode 1 - 1080p</a></p>
        <p><a href="https://download.bbupload.to/download?v=ABC12345">Episode 2 - 720p</a></p>
        """
        releases = parse_katmoviehd_releases(sample_html, default_season=1)
        self.assertEqual(len(releases), 2)

        ep1 = releases[0]
        self.assertEqual(ep1["episode_number"], 1)
        self.assertEqual(ep1["quality"], "1080p")
        self.assertEqual(ep1["source_type"], "gofile")

        ep2 = releases[1]
        self.assertEqual(ep2["episode_number"], 2)
        self.assertEqual(ep2["quality"], "720p")
        self.assertEqual(ep2["source_type"], "bbupload")

    def test_db_init_and_save(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = Path(tf.name)

        try:
            init_staging_db(db_path)

            post_data = {
                "canonical_key": "the-last-house_2026",
                "title": "The Last House",
                "original_title": "The Last House (2026)",
                "year": 2026,
                "media_type": "movie",
                "imdb_id": "tt32268156",
                "poster_url": "https://m.media-amazon.com/poster.jpg",
                "synopsis": "In an inexplicable situation, a family is confined.",
                "genres": '["Action", "Horror"]',
                "cast_names": "Sid Edwards, Lewis Goody",
                "director": "Louis Leterrier",
                "languages": "Hindi Dubbed",
                "rating": 7.5,
                "site": "katmoviehd",
                "post_url": "https://new.katmoviehd.top/the-last-house-2026/",
                "releases": [
                    {
                        "label": "1080pDL",
                        "quality": "1080p",
                        "resolution": "1080p",
                        "size_bytes": 4413379646,
                        "season_number": None,
                        "episode_number": None,
                        "audio_languages": "Hindi Dubbed",
                        "codec": "x264",
                        "bridge_url": "https://download.bbupload.to/download?v=FS6HLPAM",
                        "sources": [
                            {
                                "source_name": "⚡ SuperDuperLoad Direct Stream",
                                "service": "superduperload",
                                "resource_id": "FS6HLPAM",
                                "source_url": "https://download.bbupload.to/download?v=FS6HLPAM",
                                "final_url": "https://superduperload.site/get/token123",
                                "is_temporary": 1,
                                "quality": "1080p",
                            }
                        ],
                    }
                ],
            }

            ok = save_post_to_staging_db(db_path, post_data)
            self.assertTrue(ok)

            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute("SELECT clean_title, year, director, cast_names, languages, synopsis FROM posts WHERE canonical_key = 'the-last-house_2026';").fetchone() if "clean_title" in [c[1] for c in conn.execute("PRAGMA table_info(posts);")] else conn.execute("SELECT title, year, director, cast_names, languages, synopsis FROM posts WHERE canonical_key = 'the-last-house_2026';").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "The Last House")
                self.assertEqual(row[1], 2026)
                self.assertEqual(row[2], "Louis Leterrier")
                self.assertEqual(row[3], "Sid Edwards, Lewis Goody")
                self.assertEqual(row[4], "Hindi Dubbed")

                rel_row = conn.execute("SELECT quality, size_bytes FROM releases;").fetchone()
                self.assertIsNotNone(rel_row)
                self.assertEqual(rel_row[0], "1080p")
                self.assertEqual(rel_row[1], 4413379646)

                src_row = conn.execute("SELECT service, final_url FROM sources;").fetchone()
                self.assertIsNotNone(src_row)
                self.assertEqual(src_row[0], "superduperload")
                self.assertIn("superduperload.site", src_row[1])
        finally:
            if os.path.exists(str(db_path)):
                os.remove(str(db_path))


if __name__ == "__main__":
    unittest.main()
