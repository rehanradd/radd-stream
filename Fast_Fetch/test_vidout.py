"""Offline tests for MultiMovies' VIDOUT HLS playlist extraction."""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_fetch


class VidoutPlaylistTests(unittest.TestCase):
    def test_extracts_absolute_playlist_url(self):
        page = '<video src="https://cdn.example/master.m3u8?token=abc&amp;expires=123">'
        self.assertEqual(
            fast_fetch.extract_hls_playlist_url(page, "https://vidout.pages.dev/movie/tt1234567"),
            "https://cdn.example/master.m3u8?token=abc&expires=123",
        )

    def test_extracts_escaped_and_relative_playlist_urls(self):
        escaped = r'<script>const src="https:\/\/cdn.example\/master.m3u8?token=abc\u0026expires=123";</script>'
        self.assertEqual(
            fast_fetch.extract_hls_playlist_url(escaped, "https://vidout.pages.dev/movie/tt1234567"),
            "https://cdn.example/master.m3u8?token=abc&expires=123",
        )
        self.assertEqual(
            fast_fetch.extract_hls_playlist_url(
                '<source src="/hls/master.m3u8">',
                "https://vidout.pages.dev/movie/tt1234567",
            ),
            "https://vidout.pages.dev/hls/master.m3u8",
        )

    def test_non_playlist_page_returns_none(self):
        self.assertIsNone(
            fast_fetch.extract_hls_playlist_url(
                '<video src="https://cdn.example/video.mp4">',
                "https://vidout.pages.dev/movie/tt1234567",
            )
        )

    def test_movie_extraction_keeps_embed_and_adds_playlist_as_final_url(self):
        embed_url = "https://vidout.pages.dev/movie/tt1234567"
        playlist_url = "https://cdn.example/master.m3u8?token=abc"
        config = {
            "initialServers": [
                {"name": "VIDOUT", "url": embed_url, "type": "iframe"},
                {"name": "Cineverse", "url": "https://player.example/embed/tmdb/movie?id=123456"},
            ]
        }

        def fake_http_get(url, timeout=12):
            self.assertEqual(url, embed_url)
            return 200, url, f'<script>const playlist="{playlist_url}";</script>'

        with patch.object(fast_fetch, "http_get", side_effect=fake_http_get):
            result = fast_fetch.extract_post_data_multimovies(
                "https://multimovies.garden/movie/example-123",
                f"<title>Example Movie (2024) - MultiMovies</title>"
                f"<script>watchConfig = {json.dumps(config)};</script>",
                verbose=False,
            )

        vidout = next(
            release["sources"][0]
            for release in result["releases"]
            if release["sources"][0]["service"] == "vidout"
        )
        self.assertEqual(vidout["source_url"], embed_url)
        self.assertEqual(vidout["final_url"], playlist_url)
        self.assertEqual(vidout["playback_type"], "hls")
        self.assertIn("Direct HLS", vidout["source_name"])

    def test_failed_vidout_request_falls_back_to_embed_url(self):
        embed_url = "https://vidout.pages.dev/movie/tt1234567"
        config = {"initialServers": [{"name": "VIDOUT", "url": embed_url}]}

        with patch.object(fast_fetch, "http_get", return_value=(503, embed_url, "")):
            result = fast_fetch.extract_post_data_multimovies(
                "https://multimovies.garden/movie/example-123",
                f"<title>Example Movie (2024)</title>"
                f"<script>watchConfig = {json.dumps(config)};</script>",
                verbose=False,
            )

        self.assertEqual(result["releases"][0]["sources"][0]["final_url"], embed_url)

    def test_episode_extraction_resolves_vidout_playlist(self):
        embed_url = "https://vidout.pages.dev/tv/123456/s1/e1"
        playlist_url = "https://cdn.example/episode.m3u8"
        episode_config = {
            "initialServers": [{"name": "VIDOUT", "url": embed_url}]
        }
        episode_url = "https://multimovies.garden/series/example-123/season/1/episode/1"

        def fake_http_get(url, timeout=12):
            if url == episode_url:
                return (
                    200,
                    url,
                    f"<script>watchConfig = {json.dumps(episode_config)};</script>",
                )
            if url == embed_url:
                return 200, url, f'<script>source="{playlist_url}";</script>'
            self.fail(f"Unexpected URL requested: {url}")

        with patch.object(fast_fetch, "http_get", side_effect=fake_http_get):
            result = fast_fetch.extract_post_data_multimovies(
                "https://multimovies.garden/series/example-123",
                '<title>Example Series (2024)</title>'
                '<a href="/series/example-123/season/1/episode/1">Episode 1</a>'
                '<script>watchConfig = {"initialServers":[]};</script>',
                verbose=False,
            )

        episode_source = next(
            release["sources"][0]
            for release in result["releases"]
            if release.get("episode") == "E01"
        )
        self.assertEqual(episode_source["source_url"], embed_url)
        self.assertEqual(episode_source["final_url"], playlist_url)


if __name__ == "__main__":
    unittest.main()
