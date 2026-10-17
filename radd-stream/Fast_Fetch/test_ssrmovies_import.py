#!/usr/bin/env python3
"""
test_ssrmovies_import.py — Comprehensive unit tests for SSRMovies dedicated importer.

Tests:
  1. Release button parsing: quality (1080p, 720p, 480p, 4K), size, codec, season/episode.
  2. Post metadata extraction: clean title, year, audio/language, poster, synopsis, canonical key.
  3. LinksZilla mirror mapping and resolution into stream and download sources.
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
import import_ssrmovies


SAMPLE_SSR_MOVIE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Thaapi 2026 Punjabi (Cleaned) 1080p 720p 480p HQ HDTC x264 – SSRmovies</title>
    <meta name="description" content="Thaapi 2026 Punjabi Full Movie watch online and download in 1080p, 720p and 480p HD." />
    <meta property="og:image" content="https://imgurworld.top/images/2026/10/17/thaapi-poster.jpg" />
</head>
<body>
    <div class="entry-content">
        <p style="text-align: center;">Thaapi enjoy the full movie in 480p 720p and 1080p HQ HDTC x264 best HD quality. Thaapi is available in Punjabi language.</p>
        <p class="poster" align="center"><img src="https://imgurworld.top/images/2026/10/17/thaapi-main.jpg" alt="poster" /></p>
        <p style="text-align: center;"><strong>Thaapi (2026) 1080p 720p 480p HQ HDTC x264</strong></p>
        <hr />
        <p style="text-align: center;">
            <a href="https://secure.linkszilla.top/view/-Zw8TA6H1r" target="_blank" class="emd_dl_purple_light">Watch &amp; Download in 1080p - 2.8GB</a>
        </p>
        <p style="text-align: center;">
            <a href="https://secure.linkszilla.top/view/pbeNXh-zEb" target="_blank" class="emd_dl_blue_four">Watch &amp; Download in 720p - 1.2GB</a>
        </p>
        <p style="text-align: center;">
            <a href="https://secure.linkszilla.top/view/re-x6kHg5c" target="_blank" class="emd_dl_red">Watch &amp; Download in 480p - 434MB</a>
        </p>
    </div>
</body>
</html>
"""


class TestSSRMoviesImport(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ssrmovies.db"
        fast_fetch.DB_PATH = self.db_path
        fast_fetch.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_release_buttons(self):
        btn_1080p = '<a href="https://secure.linkszilla.top/view/-Zw8TA6H1r">Watch &amp; Download in 1080p - 2.8GB</a>'
        btn_720p = '<a href="https://secure.linkszilla.top/view/pbeNXh-zEb">Watch &amp; Download in 720p - 1.2GB</a>'
        btn_480p = '<a href="https://secure.linkszilla.top/view/re-x6kHg5c">Watch &amp; Download in 480p - 434MB</a>'
        btn_4k_hevc = '<a href="https://secure.linkszilla.top/view/4k-hevc">Watch &amp; Download in 4K 2160p 10Bit HEVC - 6.5GB</a>'

        r_1080p = import_ssrmovies.parse_ssrmovies_release_button(btn_1080p)
        self.assertIsNotNone(r_1080p)
        self.assertEqual(r_1080p["quality"], "1080p")
        self.assertEqual(r_1080p["size"], "2.8GB")
        self.assertEqual(r_1080p["codec"], "x264")

        r_720p = import_ssrmovies.parse_ssrmovies_release_button(btn_720p)
        self.assertEqual(r_720p["quality"], "720p")
        self.assertEqual(r_720p["size"], "1.2GB")

        r_480p = import_ssrmovies.parse_ssrmovies_release_button(btn_480p)
        self.assertEqual(r_480p["quality"], "480p")
        self.assertEqual(r_480p["size"], "434MB")

        r_4k = import_ssrmovies.parse_ssrmovies_release_button(btn_4k_hevc)
        self.assertEqual(r_4k["quality"], "2160p")
        self.assertEqual(r_4k["size"], "6.5GB")
        self.assertEqual(r_4k["codec"], "hevc")

    def test_extract_post_metadata(self):
        data = import_ssrmovies.extract_post_data_ssrmovies_enhanced(
            post_url="https://ssrmovies.surf/thaapi-2026-punjabi-cleaned-1080p-720p-480p-hq-hdtc-x264/",
            page_html=SAMPLE_SSR_MOVIE_HTML,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["clean_title"], "Thaapi")
        self.assertEqual(data["year"], 2026)
        self.assertEqual(data["content_type"], "movie")
        self.assertEqual(data["language"], "Punjabi")
        self.assertEqual(data["poster_url"], "https://imgurworld.top/images/2026/10/17/thaapi-main.jpg")
        self.assertIn("Thaapi 2026 Punjabi Full Movie", data["synopsis"])
        self.assertEqual(len(data["releases"]), 3)

        qualities = [r["quality"] for r in data["releases"]]
        self.assertIn("1080p", qualities)
        self.assertIn("720p", qualities)
        self.assertIn("480p", qualities)

    @patch("fast_fetch.unwrap_linkszilla")
    def test_extract_post_with_resolved_mirrors(self, mock_unwrap_lz):
        mock_unwrap_lz.return_value = [
            {
                "source_name": "▶ Watch Online Stream",
                "service": "stream",
                "resource_id": "stream_01",
                "source_url": "https://watch-online.mom/e/stream_01",
                "final_url": "https://watch-online.mom/e/stream_01",
                "is_temporary": 0,
            },
            {
                "source_name": "⚡ Direct-Cloud [High Speed]",
                "service": "google_cdn",
                "resource_id": "dc_01",
                "source_url": "https://dl.direct-cloud.top/d/dc_01",
                "final_url": "https://lh3.googleusercontent.com/pw/sample_direct_cdn",
                "is_temporary": 1,
            },
        ]

        data = import_ssrmovies.extract_post_data_ssrmovies_enhanced(
            post_url="https://ssrmovies.surf/thaapi-2026-punjabi-cleaned-1080p-720p-480p-hq-hdtc-x264/",
            page_html=SAMPLE_SSR_MOVIE_HTML,
            resolve_direct=True,
        )
        self.assertEqual(len(data["releases"]), 3)
        sources_1080p = data["releases"][0]["sources"]
        self.assertEqual(len(sources_1080p), 2)
        services = [s["service"] for s in sources_1080p]
        self.assertIn("stream", services)
        self.assertIn("google_cdn", services)

    def test_sync_api_to_db(self):
        client = import_ssrmovies.SSRMoviesClient(base_url="https://ssrmovies.surf")

        sample_posts = [
            {
                "id": 101,
                "link": "https://ssrmovies.surf/movie-alpha-2026/",
                "slug": "movie-alpha-2026",
                "modified": "2026-10-17T12:00:00",
                "title": {"rendered": "Movie Alpha 2026"},
            },
            {
                "id": 102,
                "link": "https://ssrmovies.surf/movie-beta-2026/",
                "slug": "movie-beta-2026",
                "modified": "2026-10-17T12:30:00",
                "title": {"rendered": "Movie Beta 2026"},
            },
        ]

        with patch.object(client, "get_json") as mock_json:
            mock_json.side_effect = [
                # Probe call
                (200, [{"id": 101}], {"x-wp-total": "2", "x-wp-totalpages": "1"}),
                # Page 1 call
                (200, sample_posts, {"x-wp-total": "2", "x-wp-totalpages": "1"}),
            ]

            synced = import_ssrmovies.sync_api_to_db(client, self.db_path, max_pages=1)
            self.assertEqual(synced, 2)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT loc, slug, scraped, site FROM sitemap_cache").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["loc"], "https://ssrmovies.surf/movie-alpha-2026/")
            self.assertEqual(rows[0]["site"], "ssrmovies")

    def test_end_to_end_worker_scrape_and_save(self):
        client = import_ssrmovies.SSRMoviesClient(base_url="https://ssrmovies.surf")

        # Insert a pending URL
        test_url = "https://ssrmovies.surf/thaapi-2026-punjabi-cleaned-1080p-720p-480p-hq-hdtc-x264/"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sitemap_cache (loc, slug, scraped, site) VALUES (?, ?, 0, 'ssrmovies')",
                (test_url, "thaapi-2026"),
            )
            conn.commit()

        with patch.object(client, "get_text") as mock_text:
            mock_text.return_value = (200, test_url, SAMPLE_SSR_MOVIE_HTML)

            ok, rels, srcs = import_ssrmovies.scrape_ssrmovies_worker(
                post_url=test_url,
                client=client,
                resolve_direct=False,
            )
            self.assertTrue(ok)
            self.assertEqual(rels, 3)

        # Check DB
        with sqlite3.connect(self.db_path) as conn:
            p_row = conn.execute("SELECT title, year, clean_title, content_type FROM posts WHERE clean_title = 'Thaapi'").fetchone()
            self.assertIsNotNone(p_row)
            self.assertEqual(p_row[1], 2026)

            r_rows = conn.execute("SELECT release_title, quality, size FROM releases").fetchall()
            self.assertEqual(len(r_rows), 3)

            scraped_flag = conn.execute("SELECT scraped FROM sitemap_cache WHERE loc = ?", (test_url,)).fetchone()[0]
            self.assertEqual(scraped_flag, 1)


if __name__ == "__main__":
    unittest.main()
