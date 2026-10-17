#!/usr/bin/env python3
"""Offline tests for the complete MultiMovies import path."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fast_fetch
import import_multimovies


class MultiMoviesImportTests(unittest.TestCase):
    def test_sitemap_locs_support_namespace_and_entities(self):
        xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://m1.multimovies.courses/movie/a?x=1&amp;y=2</loc></url>
        </urlset>"""
        self.assertEqual(
            import_multimovies._locs(xml),
            ["https://m1.multimovies.courses/movie/a?x=1&y=2"],
        )

    def test_episode_url_maps_to_root_and_coordinates(self):
        result = import_multimovies.series_root_for_episode(
            "https://m1.multimovies.courses/series/show-name/season/2/episode/7"
        )
        self.assertEqual(
            result,
            ("https://m1.multimovies.courses/series/show-name", 2, 7),
        )

    @patch("import_multimovies.fetch_sitemap_inventory")
    def test_discover_sitemaps_groups_episodes_by_root(self, mock_inventory):
        mock_inventory.return_value = (
            ["https://m1.multimovies.courses/movie/movie-a"],
            [
                "https://m1.multimovies.courses/series/show-x/season/1/episode/2",
                "https://m1.multimovies.courses/series/show-x/season/1/episode/1",
            ],
        )
        client = import_multimovies.SiteClient("https://m1.multimovies.courses", 0.0)
        titles, episodes, grouped = import_multimovies.discover_sitemaps(client)
        self.assertEqual(titles, ["https://m1.multimovies.courses/movie/movie-a"])
        self.assertEqual(len(episodes), 2)
        root = "https://m1.multimovies.courses/series/show-x"
        self.assertIn(root, grouped)
        self.assertEqual(grouped[root][0], "https://m1.multimovies.courses/series/show-x/season/1/episode/1")
        self.assertEqual(grouped[root][1], "https://m1.multimovies.courses/series/show-x/season/1/episode/2")

    def test_download_page_discovery_only_accepts_same_site_download_routes(self):
        page = """
        <a class="cinejoy-btn-download" href="/download/movie-a">Download</a>
        <a href="https://m1.multimovies.courses/download/movie-b">More</a>
        <a href="https://ads.example/redirect">Ad</a>
        """
        self.assertEqual(
            import_multimovies.download_page_urls(
                "https://m1.multimovies.courses/movie/movie-a",
                page,
                "m1.multimovies.courses",
            ),
            [
                "https://m1.multimovies.courses/download/movie-a",
                "https://m1.multimovies.courses/download/movie-b",
            ],
        )

    def test_download_mirrors_are_grouped_by_quality_and_typed(self):
        page = """
        <div class="quality-group"><h3>1080p</h3>
          <a class="dl-mirror-btn" href="https://fastdl.beer/dl?id=abc">GDFlix</a>
          <a class="dl-mirror-btn" href="https://filebee.xyz/file/xyz">Google Drive</a>
        </div>
        <a href="https://ads.example/out">Advertisement</a>
        """
        releases = import_multimovies.parse_download_mirrors(
            page,
            "https://m1.multimovies.courses/download/movie-a",
            "m1.multimovies.courses",
            {"clean_title": "Movie A", "year": 2024, "language": "Hindi"},
        )
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["quality"], "1080P")
        self.assertEqual(len(releases[0]["sources"]), 2)
        self.assertEqual(
            {source["playback_type"] for source in releases[0]["sources"]},
            {"download"},
        )
        self.assertNotIn("ads.example", str(releases))

    def test_episode_watch_servers_preserve_each_server_type(self):
        page = """
        <script>
        var watchConfig = {
          "initialServers": [
            {"name":"Cineverse","type":"iframe","url":"https://embed.example/movie/1","quality":"HD"},
            {"name":"Direct HLS","type":"hls","url":"https://cdn.example/movie/1.m3u8","quality":"FHD"}
          ]
        };
        </script>
        """
        media = {"clean_title": "Series A", "language": "Hindi"}
        releases = import_multimovies.episode_releases(
            page,
            "https://m1.multimovies.courses/series/series-a/season/1/episode/2",
            media,
            1,
            2,
        )
        self.assertEqual(len(releases), 2)
        self.assertEqual(
            [release["episode"] for release in releases],
            ["E02", "E02"],
        )
        self.assertEqual(
            [release["sources"][0]["playback_type"] for release in releases],
            ["iframe", "hls"],
        )
        self.assertEqual(releases[0]["season"], "S01")

    def test_parser_can_skip_episode_fetch_and_link_resolution(self):
        page = """
        <title>Series A (2024) - MultiMovies</title>
        <a href="/series/series-a/season/8/episode/1">Episode</a>
        <script>var watchConfig = {"initialServers":[
          {"name":"Cineverse","type":"iframe","url":"https://embed.example/movie/1"}
        ]};</script>
        """
        with patch.object(fast_fetch, "http_get", side_effect=AssertionError("unexpected fetch")), \
             patch.object(fast_fetch, "resolve_vidout_playlist", side_effect=AssertionError("unexpected resolve")):
            data = fast_fetch.extract_post_data_multimovies(
                "https://m1.multimovies.courses/series/series-a",
                page,
                verbose=False,
                crawl_episodes=False,
                resolve_streams=False,
            )
        self.assertEqual(data["content_type"], "series")
        self.assertEqual(data["releases"][0]["sources"][0]["playback_type"], "iframe")

    def test_restricted_title_filter_matches_project_rules(self):
        self.assertTrue(import_multimovies._is_restricted("Some Adult Title", "some-title"))
        self.assertTrue(import_multimovies._is_restricted("Show", "show-nsfw"))
        self.assertFalse(import_multimovies._is_restricted("Family Movie", "family-movie-2024"))

    def test_source_playback_type_is_saved_after_schema_migration(self):
        original_db_path = fast_fetch.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                fast_fetch.DB_PATH = Path(temp_dir) / "test.db"
                fast_fetch.init_db()
                post_id = fast_fetch.save_scraped_data(
                    {
                        "url": "https://m1.multimovies.courses/movie/test-title",
                        "slug": "test-title",
                        "title": "Test Title",
                        "clean_title": "Test Title",
                        "content_type": "movie",
                        "source_site": "multimovies",
                        "releases": [{
                            "release_title": "Test Title Cineverse",
                            "quality": "HD",
                            "source_site": "multimovies",
                            "sources": [{
                                "source_name": "Cineverse [iframe]",
                                "service": "cineverse",
                                "resource_id": "1",
                                "source_url": "https://embed.example/movie/1",
                                "final_url": "https://embed.example/movie/1",
                                "playback_type": "iframe",
                            }],
                        }],
                    },
                    enrich_metadata=False,
                    ensure_db=False,
                )
                with fast_fetch.get_db() as conn:
                    row = conn.execute(
                        """
                        SELECT ds.playback_type
                        FROM download_sources ds
                        JOIN releases r ON r.id = ds.release_id
                        WHERE r.post_id = ?
                        """,
                        (post_id,),
                    ).fetchone()
                self.assertEqual(row["playback_type"], "iframe")
        finally:
            fast_fetch.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
