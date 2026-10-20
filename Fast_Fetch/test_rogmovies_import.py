#!/usr/bin/env python3
"""
test_rogmovies_import.py — Comprehensive unit tests for Rogmovies importer.

Tests:
  1. Permanent TMDB poster unwrapping (base64 decoding & embedded HTML extraction).
  2. Movie post parsing with multiple qualities (480p, 720p, 1080p, 4K).
  3. TV series episode parsing (-:Episodes: X:- into E01..E10).
  4. TV series full season batch zip parsing (episode='Batch').
  5. Multi-mirror link mappings (FastDL, VCloud, VegaDrive, Filepress, GoFile, VikingFile, MegaUp, GDToT).
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
import import_rogmovies


SAMPLE_ROG_MOVIE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Download Maremma (2026) Prime Video : Hindi-Dubbed (Multi-Audio) WeB-DL 480p [600MB] | 720p [1.5GB] | 1080p [2.6GB] X264 | Rogmovies Official</title>
    <meta property="og:title" content="Download Maremma (2026) Prime Video : Hindi-Dubbed (Multi-Audio) WeB-DL 480p [600MB]">
    <meta property="og:image" content="https://img.rogmovies.one/238df49c1c5d/download-maremma-2026-hindi-org-dubbed-web-dl-480p-720p-1080p.webp?p=194751&amp;u=aHR0cHM6Ly9pbWFnZS50bWRiLm9yZy90L3Avb3JpZ2luYWwvZ01OOGtrY2lJeDNhYm5BQlYzS0p5NkRuRGdOLmpwZw">
</head>
<body>
    <div class="entry-content">
        <p>✅ Download Maremma (2026) Prime Video Full Movie in 720p &amp; 480p</p>
        <p><img src="https://image.tmdb.org/t/p/w500/qsnsKf59pYN3GzfQRqvNjE8tcdz.jpg" alt="poster"></p>
        <p><strong>Storyline:</strong> A gripping action thriller set in rural Italy.</p>
        <p><strong>Genres:</strong> Action, Thriller</p>
        <p><strong>Language:</strong> Hindi Org + English</p>
        
        <h5>Maremma (2026) Multi-Audio WeB-DL 480p x264 [600MB]</h5>
        <p><a href="https://nexdrive.beer/genxfm_rog_001/"><button class="dwd-button">Download Now</button></a></p>
        
        <h5>Maremma (2026) Multi-Audio WeB-DL 720p x264 [1.5GB]</h5>
        <p><a href="https://nexdrive.beer/genxfm_rog_002/"><button class="dwd-button">Download Now</button></a></p>

        <h5>Maremma (2026) Multi-Audio WeB-DL 1080p x264 [2.6GB]</h5>
        <p><a href="https://nexdrive.beer/genxfm_rog_003/"><button class="dwd-button">Download Now</button></a></p>
    </div>
</body>
</html>
"""

SAMPLE_NEXDRIVE_ROG_MOVIE_480P = """
<!DOCTYPE html>
<html>
<head>
    <title>Maremma (2026) Multi-Audio WeB-DL 480p x264 [600MB] &#8211; Nexdrive.Beer</title>
</head>
<body>
    <div class="container">
        <h3>Maremma (2026) Multi-Audio WeB-DL 480p x264 [600MB]</h3>
        <p>
            <a href="https://fastdl.beer/embed.php?download=rog_fastdl_01">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/rog_vcloud_01">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://one.vegadrive.app/s/sample_vegadrive_token">&#x26a1; V-Drive [Multi]</a>
            <a href="https://filebee.xyz/file/rog_filepress_01">&#x26a1; Filepress [G-Drive]</a>
            <a href="https://gofile.io/d/samplegofile01">https://gofile.io/d/samplegofile01</a>
            <a href="https://vikingfile.com/f/sampleviking01">https://vikingfile.com/f/sampleviking01</a>
            <a href="https://megaup.net/samplemegaup01/Maremma.mkv">https://megaup.net/samplemegaup01</a>
            <a href="https://new26.gdtot.dad/file/samplegdtot01">G-Drive [Login]</a>
        </p>
    </div>
</body>
</html>
"""

SAMPLE_NEXDRIVE_ROG_SERIES_EPISODES = """
<!DOCTYPE html>
<html>
<head>
    <title>4 Thieves Season 1 (Hindi) Single Episode 720p [200MB] &#8211; Nexdrive.Beer</title>
</head>
<body>
    <div class="container">
        <h4>-:Episodes: 1:-</h4>
        <p>
            <a href="https://fastdl.beer/embed.php?download=thieves_ep1_fastdl">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/thieves_ep1_vcloud">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/thieves_ep1_fp">&#x26a1; Filepress [G-Drive]</a>
        </p>

        <h4>-:Episodes: 2:-</h4>
        <p>
            <a href="https://fastdl.beer/embed.php?download=thieves_ep2_fastdl">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/thieves_ep2_vcloud">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/thieves_ep2_fp">&#x26a1; Filepress [G-Drive]</a>
        </p>
    </div>
</body>
</html>
"""

SAMPLE_NEXDRIVE_ROG_SERIES_BATCH = """
<!DOCTYPE html>
<html>
<head>
    <title>4 Thieves (Season 1) Hindi Complete Batch Zip 720p [1.5GB] &#8211; Nexdrive.Beer</title>
</head>
<body>
    <div class="container">
        <h3>4 Thieves S01 Complete Batch</h3>
        <p>
            <a href="https://fastdl.beer/embed.php?download=thieves_batch_fastdl">&#x26a1; G-Direct [Instant]</a>
            <a href="https://vcloud.beer/thieves_batch_vcloud">&#x26a1; V-Cloud [Resumable]</a>
            <a href="https://filebee.xyz/file/thieves_batch_fp">&#x26a1; Filepress [G-Drive]</a>
        </p>
    </div>
</body>
</html>
"""


class TestRogmoviesImport(unittest.TestCase):

    def test_unwrap_tmdb_poster_base64(self):
        """Test unwrapping ?u=<base64> proxy URL from Rogmovies og:image."""
        raw_tmdb = "https://image.tmdb.org/t/p/original/gMN8kkciIx3abnABV3KJy6DnDgN.jpg"
        encoded = base64.b64encode(raw_tmdb.encode("utf-8")).decode("utf-8")
        proxy_url = f"https://img.rogmovies.one/download-maremma.webp?p=194751&u={encoded}"
        
        result = import_rogmovies.unwrap_tmdb_poster(proxy_url)
        self.assertEqual(result, raw_tmdb)

    def test_unwrap_tmdb_poster_from_html(self):
        """Test fallback extraction of embedded TMDB image from post HTML."""
        local_poster = "https://rogmovies.one/wp-content/uploads/sample.jpg"
        result = import_rogmovies.unwrap_tmdb_poster(local_poster, SAMPLE_ROG_MOVIE_HTML)
        self.assertEqual(result, "https://image.tmdb.org/t/p/w500/qsnsKf59pYN3GzfQRqvNjE8tcdz.jpg")

    def test_extract_movie_post_data_offline(self):
        """Test extracting movie releases and mirrors from mock Rogmovies and Nexdrive pages."""
        mock_client = MagicMock()
        mock_client.get_text.side_effect = [
            (200, "https://nexdrive.beer/genxfm_rog_001/", SAMPLE_NEXDRIVE_ROG_MOVIE_480P),
            (200, "https://nexdrive.beer/genxfm_rog_002/", SAMPLE_NEXDRIVE_ROG_MOVIE_480P.replace("480p", "720p").replace("600MB", "1.5GB")),
            (200, "https://nexdrive.beer/genxfm_rog_003/", SAMPLE_NEXDRIVE_ROG_MOVIE_480P.replace("480p", "1080p").replace("600MB", "2.6GB")),
        ]

        post_url = "https://rogmovies.one/download-maremma-2026-hindi-org-dubbed-web-dl-480p-720p-1080p/"
        data = import_rogmovies.extract_post_data_rogmovies(
            post_url=post_url,
            page_html=SAMPLE_ROG_MOVIE_HTML,
            client=mock_client,
            resolve_bridges=True,
        )

        self.assertIsNotNone(data)
        self.assertIn("Maremma", data["clean_title"])
        self.assertEqual(data["year"], 2026)
        self.assertEqual(data["content_type"], "movie")
        self.assertEqual(data["source_site"], "rogmovies")
        # Should be an official permanent image.tmdb.org URL
        self.assertTrue(data["poster_url"].startswith("https://image.tmdb.org/"))
        self.assertEqual(len(data["releases"]), 3)

        # Check first release (480p)
        rel1 = data["releases"][0]
        self.assertIn("480p", rel1["quality"])
        self.assertEqual(rel1["source_site"], "rogmovies")
        self.assertGreaterEqual(len(rel1["sources"]), 8)

        # Check all mirrors are mapped
        services = {s["service"] for s in rel1["sources"]}
        self.assertIn("fastdl", services)
        self.assertIn("vcloud", services)
        self.assertIn("vegadrive", services)
        self.assertIn("filepress", services)
        self.assertIn("gofile", services)
        self.assertIn("vikingfile", services)
        self.assertIn("megaup", services)
        self.assertIn("gdtot", services)

    def test_extract_series_episodes_offline(self):
        """Test extracting individual TV series episodes with -:Episodes: X:- markup."""
        mock_client = MagicMock()
        mock_client.get_text.return_value = (200, "https://nexdrive.beer/genxfm_thieves/", SAMPLE_NEXDRIVE_ROG_SERIES_EPISODES)

        series_html = """
        <title>Download 4 Thieves (2020) S01 Hindi Complete Watcho Originals Web Series 480p | 720p</title>
        <a href="https://nexdrive.beer/genxfm_thieves/">Download Episodes</a>
        """
        post_url = "https://rogmovies.one/download-4-thieves-2020-s01-hindi-complete-watcho-originals-web-series-480p-720p/"
        data = import_rogmovies.extract_post_data_rogmovies(
            post_url=post_url,
            page_html=series_html,
            client=mock_client,
            resolve_bridges=True,
        )

        self.assertIsNotNone(data)
        # Should have 2 individual episodes: E01, E02
        self.assertEqual(len(data["releases"]), 2)
        self.assertEqual(data["releases"][0]["episode"], "E01")
        self.assertEqual(data["releases"][1]["episode"], "E02")

        # Each episode must have all 3 download mirrors
        for r in data["releases"]:
            self.assertEqual(len(r["sources"]), 3)
            ep_services = {s["service"] for s in r["sources"]}
            self.assertEqual(ep_services, {"fastdl", "vcloud", "filepress"})

    def test_extract_series_batch_zip_offline(self):
        """Test extracting full season batch zip release."""
        mock_client = MagicMock()
        mock_client.get_text.return_value = (200, "https://nexdrive.beer/genxfm_thieves_batch/", SAMPLE_NEXDRIVE_ROG_SERIES_BATCH)

        series_batch_html = """
        <title>Download 4 Thieves (Season 1) Hindi Complete Batch Zip 720p</title>
        <a href="https://nexdrive.beer/genxfm_thieves_batch/">Download Complete Batch</a>
        """
        post_url = "https://rogmovies.one/download-4-thieves-season-1-batch/"
        data = import_rogmovies.extract_post_data_rogmovies(
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
        """Test saving media records to isolated rogmovies.db staging DB and sitemap_cache update."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = Path(tf.name)

        try:
            fast_fetch.DB_PATH = temp_db
            fast_fetch.init_db()

            # Seed sitemap_cache
            with fast_fetch.get_db() as conn:
                conn.execute(
                    "INSERT INTO sitemap_cache (loc, slug, scraped, site) VALUES (?, ?, 0, 'rogmovies')",
                    ("https://rogmovies.one/download-test-film-2026/", "download-test-film-2026"),
                )

            mock_data = {
                "url": "https://rogmovies.one/download-test-film-2026/",
                "slug": "download-test-film-2026",
                "title": "Test Film (2026)",
                "clean_title": "Test Film",
                "year": 2026,
                "content_type": "movie",
                "seasons": None,
                "poster_url": "https://image.tmdb.org/t/p/original/testposter_rog.jpg",
                "backdrop_urls": None,
                "synopsis": "Test Synopsis",
                "genres": "Action",
                "language": "Hindi + English",
                "source_site": "rogmovies",
                "canonical_key": "test film:2026",
                "releases": [
                    {
                        "release_title": "Test Film (2026) 720p WeB-DL",
                        "quality": "720p",
                        "codec": "x264",
                        "size": "1.2GB",
                        "languages": "Hindi + English",
                        "season": None,
                        "episode": None,
                        "intermediate_url": "https://nexdrive.beer/genxfm888/",
                        "source_site": "rogmovies",
                        "sources": [
                            {
                                "source_name": "⚡ G-Direct [Instant]",
                                "service": "fastdl",
                                "resource_id": "testres_rog",
                                "source_url": "https://fastdl.beer/embed.php?download=testres_rog",
                                "final_url": "https://fastdl.beer/embed.php?download=testres_rog",
                                "playback_type": "download",
                            }
                        ],
                    }
                ],
            }

            post_id = import_rogmovies.save_post_record(mock_data, temp_db)
            self.assertGreater(post_id, 0)

            # Verify SQLite contents
            conn = sqlite3.connect(temp_db)
            c = conn.cursor()
            c.execute("SELECT title, clean_title, year, source_site, poster_url FROM posts WHERE id = ?", (post_id,))
            row = c.fetchone()
            self.assertEqual(row[0], "Test Film (2026)")
            self.assertEqual(row[1], "Test Film")
            self.assertEqual(row[2], 2026)
            self.assertEqual(row[3], "rogmovies")
            self.assertEqual(row[4], "https://image.tmdb.org/t/p/original/testposter_rog.jpg")

            c.execute("SELECT count(*) FROM releases WHERE post_id = ?", (post_id,))
            self.assertEqual(c.fetchone()[0], 1)

            c.execute("SELECT service, resource_id FROM download_sources")
            s_row = c.fetchone()
            self.assertEqual(s_row[0], "fastdl")
            self.assertEqual(s_row[1], "testres_rog")

            c.execute("SELECT scraped FROM sitemap_cache WHERE loc = ? AND site = 'rogmovies'", (mock_data["url"],))
            self.assertEqual(c.fetchone()[0], 1)
            conn.close()

        finally:
            if temp_db.exists():
                temp_db.unlink()


if __name__ == "__main__":
    unittest.main()
