#!/usr/bin/env python3
"""Offline tests for HDHub4u / hdtvb.net staging import path."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fast_fetch
import import_hdtvb


class HDTVBImportTests(unittest.TestCase):
    def test_parse_sitemap_urls(self):
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://hdtvb.net/category-a/</loc></url>
            <url><loc>https://hdtvb.net/movie-one-2026.html</loc></url>
            <url><loc>https://hdtvb.net/movie-two-2025.html</loc></url>
            <url><loc>https://hdtvb.net/movie-one-2026.html</loc></url>
        </urlset>"""
        urls = import_hdtvb.parse_sitemap_urls(sample_xml)
        self.assertEqual(urls, [
            "https://hdtvb.net/movie-one-2026.html",
            "https://hdtvb.net/movie-two-2025.html",
        ])

    def test_extract_post_data_movie(self):
        sample_html = """
        <html>
        <head>
          <title>Love Of Your Life (2026) (Hindi + English) Dual Audio Hollywood Movie HD ESub &raquo; HDHub4u</title>
        </head>
        <body>
          <h1 class="entry-title">&#xE02C; Love Of Your Life (2026) (Hindi + English) Dual Audio Hollywood Movie HD ESub</h1>
          <img class="movie-cover" src="/uploads/posts/covers/photo_love.png" onerror="this.src='/no-poster.webp';">
          <div class="downloads">
            <a href="https://hubcdn.io/cloud/token1">Download 440Mb {480p-HEVC}</a>
            <a href="https://hubcdn.io/cloud/token2">Download 1.1Gb {720p-HD}</a>
            <a href="https://hubcdn.io/cloud/token3">Download 12.6Gb {2160p-WEB-DL}</a>
          </div>
        </body>
        </html>
        """
        data = import_hdtvb.extract_post_data_hdtvb(
            "https://hdtvb.net/love-of-your-life-2026.html",
            sample_html,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["clean_title"], "Love Of Your Life")
        self.assertEqual(data["year"], 2026)
        self.assertEqual(data["content_type"], "movie")
        self.assertEqual(data["poster_url"], "https://hdtvb.net/uploads/posts/covers/photo_love.png")
        self.assertEqual(len(data["releases"]), 3)

        # Check quality groupings
        self.assertEqual(data["releases"][0]["quality"], "480p-HEVC")
        self.assertEqual(data["releases"][0]["size"], "440Mb")
        self.assertEqual(data["releases"][1]["quality"], "720p-HD")
        self.assertEqual(data["releases"][1]["size"], "1.1Gb")
        self.assertEqual(data["releases"][2]["quality"], "2160p-WEB-DL")
        self.assertEqual(data["releases"][2]["size"], "12.6Gb")

        # Check source gateway
        sources = data["releases"][0]["sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["playback_type"], "url")
        self.assertEqual(sources[0]["source_url"], "https://hubcdn.io/cloud/token1")

    def test_extract_post_data_series(self):
        sample_html = """
        <html>
        <head><title>The Trap S01 (2026) Dual Audio Web Series &raquo; HDHub4u</title></head>
        <body>
          <h1 class="entry-title">The Trap S01 (2026) Dual Audio Completed Web Series HEVC</h1>
          <a href="https://hubcdn.io/cloud/series_token">Download 4.5Gb {1080p-HEVC}</a>
        </body>
        </html>
        """
        data = import_hdtvb.extract_post_data_hdtvb(
            "https://hdtvb.net/the-trap-s01.html",
            sample_html,
            resolve_direct=False,
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["clean_title"], "The Trap")
        self.assertEqual(data["content_type"], "series")
        self.assertEqual(data["year"], 2026)
        self.assertEqual(len(data["releases"]), 1)
        self.assertEqual(data["releases"][0]["quality"], "1080p-HEVC")

    def test_save_post_record_into_staging_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_db = Path(tmp_dir) / "test_hdtvb.db"
            fast_fetch.DB_PATH = temp_db
            fast_fetch.init_db()

            # Pre-populate sitemap_cache
            with fast_fetch.get_db() as conn:
                conn.execute(
                    "INSERT INTO sitemap_cache (loc, slug, scraped, site) VALUES (?, ?, 0, 'hdhub4u')",
                    ("https://hdtvb.net/test-movie.html", "test-movie"),
                )

            data = {
                "url": "https://hdtvb.net/test-movie.html",
                "slug": "test-movie",
                "title": "Test Movie 2026",
                "clean_title": "Test Movie",
                "year": 2026,
                "content_type": "movie",
                "poster_url": "https://hdtvb.net/poster.jpg",
                "source_site": "hdhub4u",
                "canonical_key": "test_movie_2026",
                "releases": [{
                    "release_title": "Test Movie 2026 1080p",
                    "quality": "1080p",
                    "codec": "x264",
                    "size": "2.5Gb",
                    "languages": "Hindi",
                    "season": None,
                    "episode": None,
                    "intermediate_url": "https://hubcdn.io/cloud/abc",
                    "source_site": "hdhub4u",
                    "sources": [{
                        "source_name": "Cloudflare R2 Direct",
                        "service": "cloudflare_r2",
                        "source_url": "https://pub-xyz.r2.dev/stream.mkv",
                        "final_url": "https://pub-xyz.r2.dev/stream.mkv",
                        "playback_type": "direct",
                    }],
                }],
            }

            post_id = import_hdtvb.save_post_record(data, temp_db)
            self.assertGreater(post_id, 0)

            # Verify in DB
            with fast_fetch.get_db() as conn:
                row = conn.execute("SELECT clean_title, year FROM posts WHERE id = ?", (post_id,)).fetchone()
                self.assertEqual(row["clean_title"], "Test Movie")
                self.assertEqual(row["year"], 2026)

                src_row = conn.execute(
                    "SELECT ds.source_name, ds.playback_type, ds.source_url "
                    "FROM download_sources ds JOIN releases r ON r.id = ds.release_id WHERE r.post_id = ?",
                    (post_id,)
                ).fetchone()
                self.assertEqual(src_row["playback_type"], "direct")
                self.assertEqual(src_row["source_url"], "https://pub-xyz.r2.dev/stream.mkv")

                cache_row = conn.execute(
                    "SELECT scraped FROM sitemap_cache WHERE loc = ?",
                    ("https://hdtvb.net/test-movie.html",)
                ).fetchone()
                self.assertEqual(cache_row["scraped"], 1)


if __name__ == "__main__":
    unittest.main()
