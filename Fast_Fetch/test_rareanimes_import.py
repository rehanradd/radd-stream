#!/usr/bin/env python3
"""
test_rareanimes_import.py — Comprehensive unit tests for RareAnimes dedicated importer.

Tests:
  1. Title cleaning: Season detection, year extraction, canonical key generation.
  2. Content parsing: Info block extraction (Full Name, Season, Release Year, Synopsis).
  3. Episode & language release parsing: Hindi, Tamil, Telugu multi-audio splits.
  4. Stream unwrapping: PixelDrain direct CDN (api/file/) and HubCloud mapping.
  5. Staging SQLite database isolation and persistence.

100% Python Standard Library. Zero external dependencies.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import fast_fetch
import import_rareanimes


SAMPLE_EPISODE_CONTENT = """
<p>✅ Download Blue Box Season 2 Dual Audio {Hindi-Tamil-Telugu} In 480p &amp; 720p &amp; 1080p.</p>
<h5><span style="color: #ff0000;">Anime Series Info</span></h5>
<p>📰 Full Name: <span style="color: #339966;">Blue Box</span></p>
<p>🍂Season: <span style="color: #339966;">02</span></p>
<p>🎞Episodes: <span style="color: #339966;">24</span></p>
<p>🕓Release Year: <span style="color: #339966;">2026</span></p>
<p>🎭 Genre: <span style="color: #339966;">Animation and Drama</span></p>
<p>🔊Language: <span style="color: #339966;">Hindi, Tamil, Telugu</span></p>
<p>🎬Quality: <span style="color: #339966;">(480p, 720p, 1080p)</span></p>
<p><span style="color: #333399;"><span style="color: #ff0000;">Synopsis</span> <span style="color: #339966;">Badminton player Taiki admires basketball star Chinatsu.</span></span></p>
<hr />
<p>Episode 01 &#8211; Deja Vu</p>
<p><span style="color: #99cc00;">Hindi</span> – [<a href="https://hubcloud.ist/drive/nwryeqtyffgrhfv">HubCloud</a>] [<a href="https://pixeldrain.com/u/Ni52JxnV">DLBeta</a>] [<a href="https://mega.nz/file/iXJijBaB#abc">Mega</a>]</p>
<p><span style="color: #ff00ff;">Tamil </span>– [<a href="https://hubcloud.ist/drive/lecvdirs1ssv1cm">HubCloud</a>] [<a href="https://pixeldrain.com/u/EvUcka1z">DLBeta</a>]</p>
<p><span style="color: #00ccff;">Telugu </span>– [<a href="https://hubcloud.ist/drive/01asnensiabos1w">HubCloud</a>] [<a href="https://pixeldrain.com/u/jRdiaVPC">DLBeta</a>]</p>
<hr />
<p>Episode 02 &#8211; Admiration</p>
<p><span style="color: #99cc00;">Hindi</span> – [<a href="https://hubcloud.ist/drive/yoypi1yoiyff9jy">HubCloud</a>] [<a href="https://pixeldrain.com/u/5pzi5eWW">DLBeta</a>]</p>
"""

SAMPLE_MOVIE_CONTENT = """
<p>✅ Download The Iron Giant (1999) Movie BluRay Full Movie (Hindi+English).</p>
<h5><span style="color: #ff0000;">Movie Info</span></h5>
<p>📰 Full Name: <span style="color: #339966;">The Iron Giant</span></p>
<p>🕓Release Year: <span style="color: #339966;">1999</span></p>
<p>🔊Language: <span style="color: #339966;">Hindi</span></p>
<p><span style="color: #ff0000;">Synopsis</span> <span style="color: #339966;">A boy befriends a giant robot from outer space.</span></p>
<hr />
<h4 style="text-align: center;"><span style="color: #ff00ff;">Hindi &#8211; Download</span></h4>
<h3><a href="https://hubcloud.ist/drive/j00ejb0tylrlqo7">HubCloud</a></h3>
<h3><a href="https://pixeldrain.com/u/LmVxqSTH">DLBeta</a></h3>
<h3><a href="https://mega.nz/file/eaAkCBKS#xyz">Mega</a></h3>
"""

SAMPLE_RAW_POST_JSON = {
    "id": 12345,
    "title": {"rendered": "Blue Box Season 2 Hindi Episodes Download HD"},
    "link": "https://www.rareanimes.mov/blue-box-season-2-hindi-episodes-download-hd/",
    "slug": "blue-box-season-2-hindi-episodes-download-hd",
    "content": {"rendered": SAMPLE_EPISODE_CONTENT},
    "_embedded": {
        "wp:featuredmedia": [
            {"source_url": "https://www.rareanimes.mov/wp-content/uploads/2026/10/blue-box.png"}
        ],
        "wp:term": [
            [{"name": "Animes"}, {"name": "Hindi Dub"}]
        ]
    }
}


class TestTitleCleaning(unittest.TestCase):
    """Tests for clean_rareanimes_title."""

    def test_series_with_season(self):
        title, year, season, key = import_rareanimes.clean_rareanimes_title("Blue Box Season 2 Hindi Episodes Download HD")
        self.assertEqual(title, "Blue Box")
        self.assertEqual(season, 2)
        self.assertIn("blue-box", key)
        self.assertTrue(key.endswith("_s2"))

    def test_movie_with_year(self):
        title, year, season, key = import_rareanimes.clean_rareanimes_title("The Iron Giant (1999) Movie Hindi Dubbed Download HD")
        self.assertEqual(title, "The Iron Giant")
        self.assertEqual(year, 1999)
        self.assertIsNone(season)
        self.assertIn("the-iron-giant_1999", key)

    def test_multi_audio_title(self):
        title, year, season, key = import_rareanimes.clean_rareanimes_title("Ranma1/2 Season 3 Hindi Dubbed Episodes Download HD")
        self.assertEqual(season, 3)
        self.assertIn("ranma", key)


class TestContentParsing(unittest.TestCase):
    """Tests for parse_rareanimes_content."""

    def test_info_block_extraction(self):
        info, releases = import_rareanimes.parse_rareanimes_content(SAMPLE_EPISODE_CONTENT)
        self.assertEqual(info["full_name"], "Blue Box")
        self.assertEqual(info["season"], "02")
        self.assertEqual(info["episodes"], "24")
        self.assertEqual(info["year"], "2026")
        self.assertIn("Drama", info["genre"])
        self.assertIn("Taiki", info["synopsis"])

    def test_episode_releases_extraction(self):
        info, releases = import_rareanimes.parse_rareanimes_content(SAMPLE_EPISODE_CONTENT)
        self.assertGreaterEqual(len(releases), 4)

        # Check Episode 1 Hindi
        ep1_hi = next(r for r in releases if r["episode_number"] == 1 and "Hindi" in r["audio_languages"])
        self.assertEqual(ep1_hi["season_number"], 2)
        mirrors = dict(ep1_hi["mirrors"])
        self.assertIn("DLBeta", mirrors)
        self.assertIn("HubCloud", mirrors)
        self.assertIn("Mega", mirrors)
        self.assertEqual(mirrors["DLBeta"], "https://pixeldrain.com/u/Ni52JxnV")

        # Check Episode 1 Tamil
        ep1_ta = next(r for r in releases if r["episode_number"] == 1 and "Tamil" in r["audio_languages"])
        self.assertTrue(any("pixeldrain.com/u/EvUcka1z" in m[1] for m in ep1_ta["mirrors"]))

    def test_movie_content_parsing(self):
        info, releases = import_rareanimes.parse_rareanimes_content(SAMPLE_MOVIE_CONTENT)
        self.assertEqual(info["full_name"], "The Iron Giant")
        self.assertEqual(info["year"], "1999")
        self.assertEqual(len(releases), 1)
        r0 = releases[0]
        self.assertIsNone(r0["episode_number"])
        mirrors = dict(r0["mirrors"])
        self.assertIn("DLBeta", mirrors)
        self.assertEqual(mirrors["DLBeta"], "https://pixeldrain.com/u/LmVxqSTH")


class TestPostDataExtraction(unittest.TestCase):
    """Tests for extract_post_data_rareanimes."""

    def test_series_post_extraction(self):
        data = import_rareanimes.extract_post_data_rareanimes(
            post_url="https://www.rareanimes.mov/blue-box-season-2-hindi-episodes-download-hd/",
            raw_post_json=SAMPLE_RAW_POST_JSON,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "Blue Box")
        self.assertEqual(data["media_type"], "series")
        self.assertEqual(data["poster_url"], "https://www.rareanimes.mov/wp-content/uploads/2026/10/blue-box.png")

        # Verify PixelDrain direct CDN resolution
        pd_sources = [s for r in data["releases"] for s in r["sources"] if s["service"] == "pixeldrain"]
        self.assertGreater(len(pd_sources), 0)
        self.assertTrue(pd_sources[0]["final_url"].startswith("https://pixeldrain.com/api/file/"))
        self.assertEqual(pd_sources[0]["is_temporary"], 0)

        # Verify categories
        genres = json.loads(data["genres"])
        self.assertIn("Animes", genres)
        self.assertIn("Hindi Dub", genres)


class TestStagingDatabase(unittest.TestCase):
    """Tests for staging database schema and persistence."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_rareanimes.db"
        import_rareanimes.init_staging_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_created(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        self.assertIn("sitemap_cache", tables)
        self.assertIn("posts", tables)
        self.assertIn("releases", tables)
        self.assertIn("sources", tables)

    def test_save_post(self):
        post_data = {
            "canonical_key": "blue-box_s2",
            "title": "Blue Box",
            "original_title": "Blue Box Season 2 Hindi Episodes Download HD",
            "year": 2026,
            "media_type": "series",
            "poster_url": "https://www.rareanimes.mov/poster.png",
            "synopsis": "Taiki badminton anime",
            "genres": json.dumps(["Animes", "Sports"]),
            "site": "rareanimes",
            "post_url": "https://www.rareanimes.mov/blue-box/",
            "releases": [
                {
                    "label": "Episode 1 [Hindi]",
                    "quality": "720p",
                    "resolution": "720p",
                    "season_number": 2,
                    "episode_number": 1,
                    "audio_languages": json.dumps(["Hindi"]),
                    "codec": "x264",
                    "bridge_url": "https://pixeldrain.com/u/Ni52JxnV",
                    "sources": [
                        {
                            "source_name": "⚡ PixelDrain [Direct CDN]",
                            "service": "pixeldrain",
                            "resource_id": "Ni52JxnV",
                            "source_url": "https://pixeldrain.com/u/Ni52JxnV",
                            "final_url": "https://pixeldrain.com/api/file/Ni52JxnV",
                            "is_temporary": 0,
                            "quality": "720p",
                        }
                    ],
                }
            ],
        }

        ok = import_rareanimes.save_post_to_staging_db(self.db_path, post_data)
        self.assertTrue(ok)

        with sqlite3.connect(str(self.db_path)) as conn:
            p_cnt = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            r_cnt = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            s_cnt = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            pd_src = conn.execute("SELECT final_url FROM sources WHERE service = 'pixeldrain'").fetchone()[0]

        self.assertEqual(p_cnt, 1)
        self.assertEqual(r_cnt, 1)
        self.assertEqual(s_cnt, 1)
        self.assertEqual(pd_src, "https://pixeldrain.com/api/file/Ni52JxnV")

    def test_upsert_existing_post(self):
        post1 = {
            "canonical_key": "naruto-shippuden_s1",
            "title": "Naruto Shippuden",
            "original_title": "Naruto Shippuden Season 1",
            "year": 2007,
            "media_type": "series",
            "site": "rareanimes",
            "post_url": "https://www.rareanimes.mov/naruto/",
            "releases": [{
                "label": "Ep 1", "quality": "720p", "resolution": "720p",
                "season_number": 1, "episode_number": 1,
                "sources": [{"source_name": "PD", "service": "pixeldrain", "resource_id": "1", "source_url": "1", "final_url": "1", "is_temporary": 0, "quality": "720p"}]
            }]
        }
        import_rareanimes.save_post_to_staging_db(self.db_path, post1)

        # Update with new poster and synopsis
        post1["poster_url"] = "https://www.rareanimes.mov/new_poster.jpg"
        post1["synopsis"] = "Updated synopsis"
        import_rareanimes.save_post_to_staging_db(self.db_path, post1)

        with sqlite3.connect(str(self.db_path)) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            poster = conn.execute("SELECT poster_url FROM posts WHERE canonical_key = 'naruto-shippuden_s1'").fetchone()[0]
        self.assertEqual(cnt, 1)
        self.assertEqual(poster, "https://www.rareanimes.mov/new_poster.jpg")

    def test_save_empty_returns_false(self):
        self.assertFalse(import_rareanimes.save_post_to_staging_db(self.db_path, None))
        self.assertFalse(import_rareanimes.save_post_to_staging_db(self.db_path, {"releases": []}))


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases in title parsing and null handling."""

    def test_extract_none_returns_none(self):
        self.assertIsNone(import_rareanimes.extract_post_data_rareanimes("https://www.rareanimes.mov/bad/", None, None))

    def test_clean_title_with_colon_and_symbols(self):
        t, y, s, k = import_rareanimes.clean_rareanimes_title("JoJo's Bizarre Adventure Season 4 – Golden Wind Hindi Dubbed Episodes Download HD")
        self.assertIn("JoJo's Bizarre Adventure", t)
        self.assertEqual(s, 4)
        self.assertTrue(k.endswith("_s4"))

    def test_clean_title_bengali_tag(self):
        t, y, s, k = import_rareanimes.clean_rareanimes_title("Ben 10 Classic Season 1 Hindi – Tamil – Telugu – Bengali Episodes Download HD")
        self.assertEqual(t, "Ben 10 Classic")
        self.assertEqual(s, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
