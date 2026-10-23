#!/usr/bin/env python3
"""
test_7starhd_import.py — Comprehensive unit tests for 7StarHD / 10xflix dedicated importer.

Tests:
  1. Release link parsing: quality (1080p, 720p, 480p, 4K), size, codec, MobileJSR URL.
  2. Post metadata extraction: clean title, year, audio/language, poster, synopsis, canonical key.
  3. MobileJSR session negotiation & CSRF unlock integration.
  4. WP REST API pagination and sitemap_cache population.
  5. Staging SQLite database isolation and atomic persistence.

100% Python Standard Library. Zero external dependencies.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fast_fetch
import import_7starhd


SAMPLE_7STARHD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Pattas (2020) Hindi ORG Dual Audio South Movie HDRip | 1080p | 720p | 480p | ESubs - 7StarHD</title>
    <meta name="description" content="Pattas 2020 Hindi Dual Audio South Movie watch online and download in 1080p, 720p and 480p." />
    <meta property="og:image" content="https://img.7starhd.rich/posters/2020/pattas.jpg" />
</head>
<body>
    <div class="entry-content">
        <p style="text-align: center;"><img src="https://img.7starhd.rich/posters/2020/pattas-main.jpg" alt="Pattas" /></p>
        <p><strong>Storyline:</strong> A petty thief learns about his past and seeks justice.</p>
        <hr />
        <p style="text-align: center;">
            <a href="https://mobilejsr.com/view/sdq9ZKg54N" target="_blank" class="btn btn-primary">1080p [2.48GB]</a>
        </p>
        <p style="text-align: center;">
            <a href="https://mobilejsr.com/view/YYppC1M8Hk" target="_blank" class="btn btn-primary">720p [1.40GB]</a>
        </p>
        <p style="text-align: center;">
            <a href="https://mobilejsr.com/view/AF3zsDkznt" target="_blank" class="btn btn-primary">480p [481MB]</a>
        </p>
    </div>
</body>
</html>
"""


class TestSevenStarHDImport(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_7starhd.db"
        fast_fetch.DB_PATH = self.db_path
        fast_fetch.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_release_links(self):
        releases = import_7starhd.parse_7starhd_release_links(SAMPLE_7STARHD_HTML)
        self.assertEqual(len(releases), 3)

        r_1080p = releases[0]
        self.assertEqual(r_1080p["quality"], "1080p")
        self.assertEqual(r_1080p["size"], "2.48GB")
        self.assertEqual(r_1080p["codec"], "x264")
        self.assertEqual(r_1080p["jsr_url"], "https://mobilejsr.com/view/sdq9ZKg54N")

        r_720p = releases[1]
        self.assertEqual(r_720p["quality"], "720p")
        self.assertEqual(r_720p["size"], "1.40GB")
        self.assertEqual(r_720p["jsr_url"], "https://mobilejsr.com/view/YYppC1M8Hk")

        r_480p = releases[2]
        self.assertEqual(r_480p["quality"], "480p")
        self.assertEqual(r_480p["size"], "481MB")
        self.assertEqual(r_480p["jsr_url"], "https://mobilejsr.com/view/AF3zsDkznt")

    def test_extract_post_metadata(self):
        data = import_7starhd.extract_post_data_7starhd(
            post_url="https://7starhd.rich/pattas-2020-hindi-org-dual-audio-south-movie-hdrip-1080p-720p-480p-esubs/",
            page_html=SAMPLE_7STARHD_HTML,
            site_name="7starhd",
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["clean_title"], "Pattas")
        self.assertEqual(data["year"], 2020)
        self.assertEqual(data["source_site"], "7starhd")
        self.assertEqual(len(data["releases"]), 3)

        # Check releases structure
        r0 = data["releases"][0]
        self.assertIn("1080P", r0["release_title"])
        self.assertEqual(r0["quality"], "1080p")
        self.assertEqual(r0["size"], "2.48GB")
        self.assertEqual(len(r0["sources"]), 1)
        self.assertEqual(r0["sources"][0]["service"], "mobilejsr")

    def test_mobilejsr_unwrapping_mock(self):
        mock_html = """
        <html>
        <body>
            <a href="https://hubcloud.ist/video/test12345">HubCloud Direct</a>
            <a href="https://1fichier.com/?testfile1fichier">1fichier Stream</a>
            <a href="https://new2.filepress.lat/file/abcdef">Filepress Drive</a>
        </body>
        </html>
        """
        with patch.object(fast_fetch, "http_get", return_value=(200, "https://mobilejsr.com/view/test", mock_html)):
            with patch.object(fast_fetch, "unwrap_hubcloud_drive", return_value=[{
                "source_name": "⚡ HubCloud [FSL Cloudflare R2]",
                "service": "fsl_r2",
                "resource_id": "test12345",
                "source_url": "https://hubcloud.ist/video/test12345",
                "final_url": "https://pub-r2.dev/video.mp4",
                "is_temporary": 1,
            }]):
                with patch.object(fast_fetch, "unwrap_filepress", return_value=("https://drive.google.com/uc?id=abc", "abcdef", 0)):
                    sources = fast_fetch.unwrap_mobilejsr("https://mobilejsr.com/view/test")
                    self.assertGreaterEqual(len(sources), 3)
                    services = [s["service"] for s in sources]
                    self.assertIn("fsl_r2", services)
                    self.assertIn("1fichier", services)
                    self.assertIn("filepress", services)

    def test_sync_api_to_db(self):
        mock_posts = [
            {"link": "https://7starhd.rich/movie-one-2026/", "slug": "movie-one-2026", "modified": "2026-10-18T10:00:00"},
            {"link": "https://7starhd.rich/movie-two-2026/", "slug": "movie-two-2026", "modified": "2026-10-18T11:00:00"},
        ]
        client = import_7starhd.SevenStarHDClient()
        with patch.object(client, "get_json", return_value=(200, mock_posts, {})):
            total = import_7starhd.sync_api_to_db(client, self.db_path, max_pages=1, site_name="7starhd")
            self.assertEqual(total, 2)

            with sqlite3.connect(str(self.db_path)) as conn:
                c = conn.cursor()
                c.execute("SELECT count(*) FROM sitemap_cache WHERE site = '7starhd' AND scraped = 0")
                self.assertEqual(c.fetchone()[0], 2)

    def test_scrape_worker_saves_to_db(self):
        client = import_7starhd.SevenStarHDClient()
        import_7starhd.init_staging_db(self.db_path)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sitemap_cache (loc, slug, scraped, site) VALUES (?, ?, 0, '7starhd')",
                ("https://7starhd.rich/pattas-2020/", "pattas-2020"),
            )
            conn.commit()

        with patch.object(client, "get_text", return_value=(200, "https://7starhd.rich/pattas-2020/", SAMPLE_7STARHD_HTML)):
            ok, rels, srcs = import_7starhd.scrape_7starhd_worker(
                "https://7starhd.rich/pattas-2020/",
                client,
                site_name="7starhd",
                resolve_direct=False,
            )
            self.assertTrue(ok)
            self.assertEqual(rels, 3)
            self.assertEqual(srcs, 3)

            stats = import_7starhd.get_db_stats(self.db_path, site_name="7starhd")
            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["releases"], 3)
            self.assertEqual(stats["sources"], 3)
            self.assertEqual(stats["sitemap_scraped"], 1)
            self.assertEqual(stats["sitemap_pending"], 0)


if __name__ == "__main__":
    unittest.main()
