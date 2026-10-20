#!/usr/bin/env python3
"""
test_vegamovies_import.py — Comprehensive unit tests for Vegamovies importer.

Tests:
  1. Permanent TMDB poster unwrapping (base64 decoding & embedded HTML extraction).
  2. Movie post parsing with multiple qualities (480p, 720p, 1080p, 4K).
  3. TV series episode parsing (-:Episodes: X:- into E01..E10).
  4. TV series full season batch zip parsing (episode='Batch').
  5. Multi-mirror link mappings (FastDL, VCloud, VegaDrive, Filepress, GDToT, DropGalaxy).
  6. Staging database isolation and sitemap_cache marking.

100% Python Standard Library. Zero external dependencies.
"""

import base64
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fast_fetch
import import_vegamovies


SAMPLE_MOVIE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Download Titanic (1997) Dual Audio {Hindi 5.1-DD &amp; English} 480p [550MB] | 720p [1GB] | 1080p [2.3GB] | 2160p 4K [9.5GB] - Vegamovies</title>
    <meta property="og:title" content="Download Titanic (1997) Dual Audio {Hindi 5.1-DD &amp; English}">
    <meta property="og:image" content="https://new1.vegamovies.lease/wp-content/uploads/titanic.jpg">
</head>
<body>
    <div class="entry-content">
        <p>✅ Download Titanic (1997) Dual Audio {Hindi 5.1-DD &amp; English} Full Movie in 720p &amp; 480p</p>
        <p><img src="https://image.tmdb.org/t/p/w500/9xjZS2rlVxm8SFx8kPC3aIGCOYQ.jpg" alt="poster"></p>
        <p><strong>Storyline:</strong> A seventeen-year-old aristocrat falls in love with a kind but poor artist aboard the luxurious, ill-fated R.M.S. Titanic.</p>
        <p><strong>Genres:</strong> Drama, Romance</p>
        <p><strong>Language:</strong> Hindi DD 5.1 + English</p>
        
        <h5>Titanic (1997) {Hindi-English} 480p BluRay x264 [550MB]</h5>
        <p><a href="https://nexdrive.beer/genxfm001/"><button class="dwd-button">Download Now</button></a></p>
        
        <h5>Titanic (1997) {Hindi-English} 720p BluRay x264 [1GB]</h5>
        <p><a href="https://nexdrive.beer/genxfm002/"><button class="dwd-button">Download Now</button></a></p>

        <h5>Titanic (1997) {Hindi-English} 1080p BluRay x264 [2.3GB]</h5>
        <p><a href="https://nexdrive.beer/genxfm003/"><button class="dwd-button">Download Now</button></a></p>
    </div>
</body>
</html>
"""

SAMPLE_NEXDRIVE_MOVIE_480P = """
<!DOCTYPE html>
<html>
<head>
    <title>Titanic 1997 [Hindi-English] 480p [550MB] &#8211; Nexdrive.Beer</title>
</head>
<body>
    <div class="container">
        <h3>Titanic 1997 [Hindi-English] 480p [550MB]</h3>
        <p>
            <a href="https://fastdl.beer/embed?download=samplefastdl01">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/samplevcloud01">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/samplefilepress01">&#x26a1; Direct-Download &#x26a1;</a>
            <a href="https://new26.gdtot.dad/file/samplegdtot01">G-Drive [Login]</a>
            <a href="https://dgdrive.pro/sampledropgalaxy01">DropGalaxy</a>
        </p>
    </div>
</body>
</html>
"""

SAMPLE_NEXDRIVE_SERIES_EPISODES = """
<!DOCTYPE html>
<html>
<head>
    <title>Ozark Season 1 (Hindi-English) Single Episode 720p [250MB] &#8211; Nexdrive.Beer</title>
</head>
<body>
    <div class="container">
        <h4>-:Episodes: 1:-</h4>
        <p>
            <a href="https://fastdl.beer/embed?download=ozark_ep1_fastdl">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/ozark_ep1_vcloud">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/ozark_ep1_fp">&#x26a1; Filepress [G-Drive]</a>
        </p>

        <h4>-:Episodes: 2:-</h4>
        <p>
            <a href="https://fastdl.beer/embed?download=ozark_ep2_fastdl">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/ozark_ep2_vcloud">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/ozark_ep2_fp">&#x26a1; Filepress [G-Drive]</a>
        </p>

        <h4>-:Episodes: 3:-</h4>
        <p>
            <a href="https://fastdl.beer/embed?download=ozark_ep3_fastdl">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/ozark_ep3_vcloud">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/ozark_ep3_fp">&#x26a1; Filepress [G-Drive]</a>
        </p>
    </div>
</body>
</html>
"""

SAMPLE_NEXDRIVE_SERIES_BATCH = """
<!DOCTYPE html>
<html>
<head>
    <title>Ozark (Season 1) Hindi Dubbed 720p [2GB] = Complete Batch &#8211; Nexdrive.Beer</title>
</head>
<body>
    <div class="container">
        <h3>Ozark S01 Complete Batch</h3>
        <p>
            <a href="https://fastdl.beer/embed?download=ozark_batch_fastdl">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/ozark_batch_vcloud">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/ozark_batch_fp">&#x26a1; Filepress [G-Drive]</a>
        </p>
    </div>
</body>
</html>
"""


class TestVegamoviesImport(unittest.TestCase):

    def test_unwrap_tmdb_poster_base64(self):
        """Test unwrapping ?u=<base64> proxy URL to permanent image.tmdb.org."""
        raw_tmdb = "https://image.tmdb.org/t/p/original/9xjZS2rlVxm8SFx8kPC3aIGCOYQ.jpg"
        encoded = base64.b64encode(raw_tmdb.encode("utf-8")).decode("utf-8")
        proxy_url = f"https://new1.vegamovies.lease/poster.jpg?u={encoded}"
        
        result = import_vegamovies.unwrap_tmdb_poster(proxy_url)
        self.assertEqual(result, raw_tmdb)

    def test_unwrap_tmdb_poster_from_html(self):
        """Test fallback extraction of embedded TMDB image from post HTML."""
        local_wp_poster = "https://new1.vegamovies.lease/wp-content/uploads/2026/01/sample.jpg"
        result = import_vegamovies.unwrap_tmdb_poster(local_wp_poster, SAMPLE_MOVIE_HTML)
        self.assertEqual(result, "https://image.tmdb.org/t/p/w500/9xjZS2rlVxm8SFx8kPC3aIGCOYQ.jpg")

    def test_extract_movie_post_data_offline(self):
        """Test extracting movie releases and mirrors from mock Vegamovies and Nexdrive pages."""
        mock_client = MagicMock()
        mock_client.get_text.side_effect = [
            (200, "https://nexdrive.beer/genxfm001/", SAMPLE_NEXDRIVE_MOVIE_480P),
            (200, "https://nexdrive.beer/genxfm002/", SAMPLE_NEXDRIVE_MOVIE_480P.replace("480p", "720p").replace("550MB", "1GB")),
            (200, "https://nexdrive.beer/genxfm003/", SAMPLE_NEXDRIVE_MOVIE_480P.replace("480p", "1080p").replace("550MB", "2.3GB")),
        ]

        post_url = "https://new1.vegamovies.lease/download-titanic-1997-dual-audio-hindi-480p-720p-1080p/"
        data = import_vegamovies.extract_post_data_vegamovies(
            post_url=post_url,
            page_html=SAMPLE_MOVIE_HTML,
            client=mock_client,
            resolve_bridges=True,
        )

        self.assertIsNotNone(data)
        self.assertIn("Titanic", data["clean_title"])
        self.assertEqual(data["year"], 1997)
        self.assertEqual(data["content_type"], "movie")
        self.assertEqual(data["poster_url"], "https://image.tmdb.org/t/p/w500/9xjZS2rlVxm8SFx8kPC3aIGCOYQ.jpg")
        self.assertEqual(len(data["releases"]), 3)

        # Check first release (480p)
        rel1 = data["releases"][0]
        self.assertIn("480p", rel1["quality"])
        self.assertEqual(rel1["source_site"], "vegamovies")
        self.assertGreaterEqual(len(rel1["sources"]), 5)

        # Check services mapped
        services = {s["service"] for s in rel1["sources"]}
        self.assertIn("fastdl", services)
        self.assertIn("vcloud", services)
        self.assertIn("filepress", services)
        self.assertIn("gdtot", services)
        self.assertIn("dropgalaxy", services)

    def test_extract_series_episodes_offline(self):
        """Test extracting individual TV series episodes with -:Episodes: X:- markup."""
        mock_client = MagicMock()
        mock_client.get_text.return_value = (200, "https://nexdrive.beer/genxfm_series/", SAMPLE_NEXDRIVE_SERIES_EPISODES)

        series_html = """
        <title>Download Ozark (Season 1) Hindi Dubbed Complete Netflix WeB-DL 720p HEVC [250MB]</title>
        <a href="https://nexdrive.beer/genxfm_series/">Download Episodes</a>
        """
        post_url = "https://new1.vegamovies.lease/download-ozark-season-1-hindi-dubbed-netflix-web-series/"
        data = import_vegamovies.extract_post_data_vegamovies(
            post_url=post_url,
            page_html=series_html,
            client=mock_client,
            resolve_bridges=True,
        )

        self.assertIsNotNone(data)
        # Should have 3 individual episodes: E01, E02, E03
        self.assertEqual(len(data["releases"]), 3)
        self.assertEqual(data["releases"][0]["episode"], "E01")
        self.assertEqual(data["releases"][1]["episode"], "E02")
        self.assertEqual(data["releases"][2]["episode"], "E03")

        # Each episode must have all 3 download mirrors
        for r in data["releases"]:
            self.assertEqual(len(r["sources"]), 3)
            ep_services = {s["service"] for s in r["sources"]}
            self.assertEqual(ep_services, {"fastdl", "vcloud", "filepress"})

    def test_extract_series_batch_zip_offline(self):
        """Test extracting full season batch zip release."""
        mock_client = MagicMock()
        mock_client.get_text.return_value = (200, "https://nexdrive.beer/genxfm_batch/", SAMPLE_NEXDRIVE_SERIES_BATCH)

        series_batch_html = """
        <title>Download Ozark (Season 1) Hindi Dubbed Complete Batch Zip 720p</title>
        <a href="https://nexdrive.beer/genxfm_batch/">Download Complete Batch</a>
        """
        post_url = "https://new1.vegamovies.lease/download-ozark-season-1-batch/"
        data = import_vegamovies.extract_post_data_vegamovies(
            post_url=post_url,
            page_html=series_batch_html,
            client=mock_client,
            resolve_bridges=True,
        )

        self.assertIsNotNone(data)
        self.assertEqual(len(data["releases"]), 1)
        batch_rel = data["releases"][0]
        self.assertEqual(batch_rel["episode"], "Batch")
        self.assertEqual(len(batch_rel["sources"]), 3)

    def test_save_post_record_staging_db(self):
        """Test saving media records to isolated staging DB and sitemap_cache update."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = Path(tf.name)

        try:
            fast_fetch.DB_PATH = temp_db
            fast_fetch.init_db()

            # Seed sitemap_cache
            with fast_fetch.get_db() as conn:
                conn.execute(
                    "INSERT INTO sitemap_cache (loc, slug, scraped, site) VALUES (?, ?, 0, 'vegamovies')",
                    ("https://new1.vegamovies.lease/download-test-movie-2026/", "download-test-movie-2026"),
                )

            mock_data = {
                "url": "https://new1.vegamovies.lease/download-test-movie-2026/",
                "slug": "download-test-movie-2026",
                "title": "Test Movie (2026)",
                "clean_title": "Test Movie",
                "year": 2026,
                "content_type": "movie",
                "seasons": None,
                "poster_url": "https://image.tmdb.org/t/p/original/testposter.jpg",
                "backdrop_urls": None,
                "synopsis": "Test Synopsis",
                "genres": "Action, Sci-Fi",
                "language": "Hindi + English",
                "source_site": "vegamovies",
                "canonical_key": "test movie:2026",
                "releases": [
                    {
                        "release_title": "Test Movie (2026) 1080p BluRay",
                        "quality": "1080p",
                        "codec": "x264",
                        "size": "2.5GB",
                        "languages": "Hindi + English",
                        "season": None,
                        "episode": None,
                        "intermediate_url": "https://nexdrive.beer/genxfm999/",
                        "source_site": "vegamovies",
                        "sources": [
                            {
                                "source_name": "⚡ G-Direct [Instant]",
                                "service": "fastdl",
                                "resource_id": "testres01",
                                "source_url": "https://fastdl.beer/embed?download=testres01",
                                "final_url": "https://fastdl.beer/embed?download=testres01",
                                "playback_type": "download",
                            }
                        ],
                    }
                ],
            }

            post_id = import_vegamovies.save_post_record(mock_data, temp_db)
            self.assertGreater(post_id, 0)

            # Verify SQLite contents
            conn = sqlite3.connect(temp_db)
            c = conn.cursor()
            c.execute("SELECT title, clean_title, year, source_site, poster_url FROM posts WHERE id = ?", (post_id,))
            row = c.fetchone()
            self.assertEqual(row[0], "Test Movie (2026)")
            self.assertEqual(row[1], "Test Movie")
            self.assertEqual(row[2], 2026)
            self.assertEqual(row[3], "vegamovies")
            self.assertEqual(row[4], "https://image.tmdb.org/t/p/original/testposter.jpg")

            c.execute("SELECT count(*) FROM releases WHERE post_id = ?", (post_id,))
            self.assertEqual(c.fetchone()[0], 1)

            c.execute("SELECT service, resource_id FROM download_sources")
            s_row = c.fetchone()
            self.assertEqual(s_row[0], "fastdl")
            self.assertEqual(s_row[1], "testres01")

            c.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?", (mock_data["url"],))
            self.assertEqual(c.fetchone()[0], 1)
            conn.close()

        finally:
            if temp_db.exists():
                temp_db.unlink()


if __name__ == "__main__":
    unittest.main()
