"""Offline regression tests for SQLite identity resolution and multi-site saves."""

import base64
import json
import io
import os
import sqlite3
import time
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_fetch
import viewer


class DatabaseSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        self.cinemeta_patch = patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        self.cinemeta_patch.start()
        fast_fetch.init_db()

    def tearDown(self):
        self.cinemeta_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def media(
        site,
        url,
        *,
        title="Example Film (2024)",
        clean_title="Example Film",
        year=2024,
        content_type="movie",
        imdb_id=None,
        tmdb_id=None,
        quality="1080p",
        source_name="Example CDN",
    ):
        return {
            "url": url,
            "slug": url.rstrip("/").split("/")[-1],
            "title": title,
            "clean_title": clean_title,
            "year": year,
            "content_type": content_type,
            "seasons": None,
            "poster_url": None,
            "backdrop_urls": None,
            "imdb_rating": None,
            "genres": None,
            "synopsis": None,
            "is_18_plus": 0,
            "is_animated": 0,
            "source_site": site,
            "industry": "Hollywood",
            "country": "USA",
            "language": "English",
            "canonical_key": fast_fetch.generate_canonical_key(clean_title, year),
            "tmdb_id": tmdb_id,
            "imdb_id": imdb_id,
            "releases": [
                {
                    "release_title": f"{clean_title} {quality}",
                    "quality": quality,
                    "codec": "x264",
                    "size": "1GB",
                    "languages": "English",
                    "season": None,
                    "episode": None,
                    "intermediate_url": f"https://{site}.example/release",
                    "sources": [
                        {
                            "source_name": source_name,
                            "service": "test-service",
                            "resource_id": f"{site}-id",
                            "source_url": f"https://{site}.example/source",
                            "final_url": f"https://cdn.example/{site}",
                            "is_temporary": 0,
                        }
                    ],
                }
            ],
        }

    def rows(self, query, params=()):
        with fast_fetch.get_db() as conn:
            return conn.execute(query, params).fetchall()

    def test_same_movie_from_multiple_sites_shares_one_post_and_keeps_page_urls(self):
        first = self.media("site_a", "https://site-a.example/example-film/")
        second = self.media(
            "site_b",
            "https://site-b.example/example-film-2024/",
            title="Example Film 2024 720p Hindi",
            quality="720p",
        )

        first_id = fast_fetch.save_scraped_data(first)
        second_id = fast_fetch.save_scraped_data(second)

        self.assertEqual(first_id, second_id)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)
        self.assertEqual(
            {row[0] for row in self.rows("SELECT DISTINCT source_site FROM releases")},
            {"site_a", "site_b"},
        )
        self.assertEqual(
            {row[0] for row in self.rows("SELECT source_site FROM post_sources")},
            {"site_a", "site_b"},
        )
        self.assertEqual(
            {row[0] for row in self.rows("SELECT source_name FROM download_sources")},
            {"Example CDN"},
        )
        source_links = self.rows(
            "SELECT source_site, url FROM post_sources WHERE post_id = ? ORDER BY source_site",
            (first_id,),
        )
        self.assertEqual(
            [(row[0], row[1]) for row in source_links],
            [
                ("site_a", "https://site-a.example/example-film/"),
                ("site_b", "https://site-b.example/example-film-2024/"),
            ],
        )

    def test_concurrent_cross_site_ingests_share_one_master_record(self):
        barrier = threading.Barrier(8)

        def ingest(site_number):
            data = self.media(
                f"site_{site_number}",
                f"https://site-{site_number}.example/example-film/",
            )
            barrier.wait(timeout=10)
            return fast_fetch.save_scraped_data(data)

        with ThreadPoolExecutor(max_workers=8) as pool:
            post_ids = list(pool.map(ingest, range(8)))

        self.assertEqual(len(set(post_ids)), 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM post_sources")[0][0], 8)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM releases")[0][0], 8)

    def test_reingesting_one_site_replaces_only_its_releases(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        fast_fetch.save_scraped_data(
            self.media("site_b", "https://site-b.example/example-film/")
        )
        refreshed = self.media(
            "site_a",
            "https://site-a.example/example-film/",
            quality="2160p",
            source_name="Refreshed source",
        )
        self.assertEqual(fast_fetch.save_scraped_data(refreshed), post_id)

        sites = self.rows(
            "SELECT source_site, quality FROM releases WHERE post_id = ? ORDER BY source_site",
            (post_id,),
        )
        self.assertEqual([(row[0], row[1]) for row in sites], [("site_a", "2160p"), ("site_b", "1080p")])
        self.assertEqual(
            self.rows(
                "SELECT source_name FROM download_sources s "
                "JOIN releases r ON r.id = s.release_id WHERE r.source_site = 'site_a'"
            )[0][0],
            "Refreshed source",
        )

    def test_empty_refresh_does_not_delete_last_known_releases(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        empty_refresh = self.media("site_a", "https://site-a.example/example-film/")
        empty_refresh["releases"] = []

        self.assertEqual(fast_fetch.save_scraped_data(empty_refresh), post_id)
        self.assertEqual(
            self.rows("SELECT COUNT(*) FROM releases WHERE post_id = ?", (post_id,))[0][0],
            1,
        )
        self.assertEqual(
            self.rows("SELECT COUNT(*) FROM download_sources")[0][0],
            1,
        )

    def test_malformed_release_sources_do_not_delete_known_good_links(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        malformed = self.media("site_a", "https://site-a.example/example-film/")
        malformed["releases"][0]["sources"] = "not a source list"

        with self.assertRaisesRegex(ValueError, "sources must be a list"):
            fast_fetch.save_scraped_data(malformed)

        self.assertEqual(self.rows("SELECT COUNT(*) FROM releases WHERE post_id = ?", (post_id,))[0][0], 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM download_sources")[0][0], 1)

    def test_same_title_and_year_but_different_media_types_do_not_merge(self):
        movie = self.media("site_a", "https://site-a.example/example-film/")
        series = self.media(
            "site_b",
            "https://site-b.example/example-film-series/",
            content_type="series",
        )
        movie_id = fast_fetch.save_scraped_data(movie)
        series_id = fast_fetch.save_scraped_data(series)

        self.assertNotEqual(movie_id, series_id)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 2)

    def test_series_and_season_pack_variants_share_the_series_identity(self):
        series = self.media(
            "site_a",
            "https://site-a.example/example-series/",
            content_type="series",
        )
        season_pack = self.media(
            "site_b",
            "https://site-b.example/example-series-complete/",
            content_type="complete_season",
        )
        self.assertEqual(
            fast_fetch.save_scraped_data(series),
            fast_fetch.save_scraped_data(season_pack),
        )
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)

    def test_external_id_matches_even_if_site_titles_differ(self):
        first = self.media(
            "site_a",
            "https://site-a.example/old-title/",
            title="Old Title (2023)",
            clean_title="Old Title",
            year=2023,
            imdb_id="tt1234567",
            tmdb_id=12345,
        )
        second = self.media(
            "site_b",
            "https://site-b.example/alternate-title/",
            title="Alternate Title (2024)",
            clean_title="Alternate Title",
            year=2024,
            imdb_id="tt1234567",
            tmdb_id=12345,
        )
        self.assertEqual(
            fast_fetch.save_scraped_data(first),
            fast_fetch.save_scraped_data(second),
        )
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)

    def test_conflicting_external_ids_do_not_merge_on_title_key(self):
        first = self.media(
            "site_a",
            "https://site-a.example/example-film/",
            imdb_id="tt1111111",
        )
        second = self.media(
            "site_b",
            "https://site-b.example/example-film/",
            imdb_id="tt2222222",
        )
        first_id = fast_fetch.save_scraped_data(first)
        second_id = fast_fetch.save_scraped_data(second)

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 2)

    def test_conflicting_ids_for_same_tmdb_match_fail_explicitly(self):
        first = self.media(
            "site_a",
            "https://site-a.example/example-film/",
            imdb_id="tt1111111",
            tmdb_id=12345,
        )
        second = self.media(
            "site_b",
            "https://site-b.example/example-film/",
            imdb_id="tt2222222",
            tmdb_id=12345,
        )
        fast_fetch.save_scraped_data(first)

        with self.assertRaisesRegex(ValueError, "External media IDs conflict"):
            fast_fetch.save_scraped_data(second)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)

    def test_reused_source_url_with_changed_media_type_is_rejected_atomically(self):
        original = self.media("site_a", "https://site-a.example/example-film/")
        post_id = fast_fetch.save_scraped_data(original)
        changed_page = self.media(
            "site_a",
            "https://site-a.example/example-film/",
            content_type="series",
        )

        with self.assertRaisesRegex(ValueError, "different media type"):
            fast_fetch.save_scraped_data(changed_page)

        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)
        self.assertEqual(
            self.rows("SELECT content_type FROM posts WHERE id = ?", (post_id,))[0][0],
            "movie",
        )
        self.assertEqual(self.rows("SELECT COUNT(*) FROM releases")[0][0], 1)

    def test_ambiguous_legacy_canonical_matches_are_not_arbitrarily_selected(self):
        fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/", imdb_id="tt1111111")
        )
        fast_fetch.save_scraped_data(
            self.media("site_b", "https://site-b.example/example-film/", imdb_id="tt2222222")
        )
        incoming = self.media("site_c", "https://site-c.example/example-film/")

        with self.assertRaisesRegex(ValueError, "matches multiple records"):
            fast_fetch.save_scraped_data(incoming)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 2)

    def test_malformed_legacy_json_metadata_does_not_break_a_merge(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE posts SET genres = ?, backdrop_urls = ? WHERE id = ?",
                ("Drama, Mystery", "{broken-json", post_id),
            )
        incoming = self.media("site_b", "https://site-b.example/example-film/")
        incoming["genres"] = json.dumps(["Drama", "Mystery"])
        incoming["backdrop_urls"] = json.dumps(["https://img.example/backdrop.jpg"])

        self.assertEqual(fast_fetch.save_scraped_data(incoming), post_id)
        post = self.rows("SELECT genres, backdrop_urls FROM posts WHERE id = ?", (post_id,))[0]
        self.assertEqual(json.loads(post["genres"]), ["Drama, Mystery", "Drama", "Mystery"])
        self.assertEqual(json.loads(post["backdrop_urls"]), ["{broken-json", "https://img.example/backdrop.jpg"])

    def test_bad_input_is_rejected_before_any_post_is_written(self):
        with self.assertRaisesRegex(ValueError, "source URL"):
            fast_fetch.save_scraped_data({"clean_title": "Example"})
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 0)

    def test_invalid_url_is_rejected_before_metadata_enrichment(self):
        data = self.media("site_a", "javascript:alert(1)")
        with patch.object(
            fast_fetch,
            "fetch_cinemeta_metadata",
            side_effect=AssertionError("invalid data must not trigger network enrichment"),
        ):
            with self.assertRaisesRegex(ValueError, "absolute HTTP"):
                fast_fetch.save_scraped_data(data)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 0)

    def test_metadata_enrichment_runs_before_save_without_mutating_caller_data(self):
        data = self.media("site_a", "https://site-a.example/example-film/")
        data.update(year=None, tmdb_id=None, imdb_id=None, poster_url=None, imdb_rating=None, genres=None)
        metadata = {
            "year": 2024,
            "imdb_id": "tt1234567",
            "imdb_rating": "8.1",
            "poster_url": "https://example.test/poster.jpg",
            "genres": ["Drama"],
            "backdrop_url": "https://example.test/backdrop.jpg",
            "synopsis": "A test synopsis.",
        }
        with patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=metadata):
            post_id = fast_fetch.save_scraped_data(data)

        row = self.rows("SELECT year, imdb_id, imdb_rating, genres, synopsis FROM posts WHERE id = ?", (post_id,))[0]
        self.assertEqual(tuple(row), (2024, "tt1234567", "8.1", '["Drama"]', "A test synopsis."))
        self.assertIsNone(data["year"])
        self.assertIsNone(data["imdb_id"])

    def test_init_db_backfills_first_seen_page_for_existing_databases(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            conn.execute("DROP TABLE post_sources")
            conn.execute("UPDATE releases SET source_site = NULL WHERE post_id = ?", (post_id,))

        fast_fetch.init_db()

        page = self.rows(
            "SELECT source_site, url FROM post_sources WHERE post_id = ?",
            (post_id,),
        )[0]
        self.assertEqual((page["source_site"], page["url"]), ("site_a", "https://site-a.example/example-film/"))
        # Unknown legacy attribution is left unknown instead of being guessed from posts.source_site.
        self.assertIsNone(self.rows("SELECT source_site FROM releases WHERE post_id = ?", (post_id,))[0][0])

    def test_domain_migration_updates_per_site_source_pages(self):
        fast_fetch.save_scraped_data(
            self.media("site_a", "https://old.example/example-film/")
        )

        result = fast_fetch.migrate_domains_in_db("old.example", "new.example")

        self.assertEqual(result["post_sources_updated"], 1)
        self.assertEqual(
            self.rows("SELECT url FROM post_sources")[0][0],
            "https://new.example/example-film/",
        )

    def test_dashboard_payload_exposes_every_site_page(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        fast_fetch.save_scraped_data(
            self.media("site_b", "https://site-b.example/example-film/")
        )
        with patch.object(viewer, "DB_PATH", self.db_path):
            payload = viewer.fetch_database_payload()

        self.assertEqual(payload["stats"]["posts_count"], 1)
        self.assertEqual(len(payload["posts"]), 1)
        self.assertEqual(
            {page["source_site"] for page in payload["posts"][0]["source_pages"]},
            {"site_a", "site_b"},
        )
        self.assertEqual(payload["posts"][0]["id"], post_id)

    def test_dashboard_site_counts_include_legacy_release_attribution(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE releases SET source_site = 'rogmovies' WHERE post_id = ?",
                (post_id,),
            )

        with patch.object(viewer, "DB_PATH", self.db_path):
            payload = viewer.fetch_database_payload()

        self.assertEqual(payload["stats"]["rog_posts"], 1)

    def test_cli_site_filter_includes_legacy_release_attribution(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE releases SET source_site = 'rogmovies' WHERE post_id = ?",
                (post_id,),
            )

        output = io.StringIO()
        with patch.object(sys, "argv", ["fast_fetch.py", "list", "--site", "rogmovies"]):
            with redirect_stdout(output):
                fast_fetch.main()

        self.assertIn("Example Film", output.getvalue())
        self.assertIn("ROGMOVIES", output.getvalue())

    def test_post_delete_cascades_through_site_pages_releases_and_links(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))

        self.assertEqual(self.rows("SELECT COUNT(*) FROM post_sources")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM releases")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM download_sources")[0][0], 0)

    def test_fetch_categories_hdhub4u_filters_restricted_categories(self):
        sample_html = """
        <a href="/category/bollywood-movies/">Bollywood</a>
        <a href="/category/animated-movies/">Animation</a>
        <a href="/category/adult/">18+</a>
        <a href="/category/action-movies/">Action</a>
        """
        with patch.object(fast_fetch, "http_get", return_value=(200, "https://new7.hdhub4u.cl/", sample_html)):
            cats = fast_fetch.fetch_categories_hdhub4u()

        self.assertIn("bollywood-movies", cats)
        self.assertIn("animated-movies", cats)
        self.assertIn("action-movies", cats)
        self.assertNotIn("adult", cats)

    def test_fetch_category_urls_hdhub4u_extracts_posts_and_paginates(self):
        p1_html = """
        <a href="/toy-story-5-2026-hindi-full-movie/">Toy Story 5</a>
        <a href="/category/animated-movies/page/2/">Next</a>
        <a href="/how-to-download/">How to</a>
        """
        p2_html = """
        <a href="/swapped-2026-hindi-full-movie/">Swapped</a>
        """
        def mock_get(url, **kwargs):
            if "page/2" in url:
                return 200, url, p2_html
            elif "page/3" in url:
                return 404, url, ""
            return 200, url, p1_html

        with patch.object(fast_fetch, "http_get", side_effect=mock_get):
            records = fast_fetch.fetch_category_urls_hdhub4u("animated-movies", max_pages=3, verbose=False)

        locs = [r[0] for r in records]
        slugs = [r[2] for r in records]
        hub_domain = fast_fetch.DOMAINS["hdhub4u"].rstrip("/")
        self.assertIn(f"{hub_domain}/toy-story-5-2026-hindi-full-movie/", locs)
        self.assertIn(f"{hub_domain}/swapped-2026-hindi-full-movie/", locs)
        self.assertIn("toy-story-5-2026-hindi-full-movie", slugs)
        self.assertIn("swapped-2026-hindi-full-movie", slugs)
        self.assertTrue(all(r[3] == "hdhub4u" for r in records))

    def test_fetch_categories_ssrmovies_filters_restricted_categories(self):
        cats_json = json.dumps([
            {"id": 3, "slug": "bollywood-movies", "name": "Bollywood Movies", "count": 100},
            {"id": 116, "slug": "18-movies", "name": "18+ Movies", "count": 50},
            {"id": 8, "slug": "hollywood-movies-hd", "name": "Hollywood Movies", "count": 80},
        ])
        with patch.object(fast_fetch, "http_get", return_value=(200, "https://ssrmovies.gripe", cats_json)):
            cats = fast_fetch.fetch_categories_ssrmovies()

        slugs = [c["slug"] for c in cats]
        self.assertIn("bollywood-movies", slugs)
        self.assertIn("hollywood-movies-hd", slugs)
        self.assertNotIn("18-movies", slugs)

    def test_fetch_category_urls_ssrmovies_extracts_posts_via_rest_api(self):
        posts_json = json.dumps([
            {"link": "https://ssrmovies.gripe/jannat-2008/", "slug": "jannat-2008", "date": "2026-10-14T00:00:00"},
            {"link": "https://ssrmovies.gripe/talvar-2015/", "slug": "talvar-2015", "date": "2026-10-14T01:00:00"},
        ])
        def mock_get(url, **kwargs):
            if "page=1" in url:
                return 200, url, posts_json
            return 200, url, "[]"

        with patch.object(fast_fetch, "http_get", side_effect=mock_get):
            records = fast_fetch.fetch_category_urls_ssrmovies(3, max_pages=2, verbose=False)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0][0], "https://ssrmovies.gripe/jannat-2008/")
        self.assertEqual(records[0][2], "jannat-2008")
        self.assertEqual(records[0][3], "ssrmovies")

    def test_sync_category_archives_persists_into_sitemap_cache(self):
        fake_hdhub_records = [
            ("https://new7.hdhub4u.cl/sample-movie-1/", "", "sample-movie-1", "hdhub4u"),
            ("https://new7.hdhub4u.cl/sample-movie-2/", "", "sample-movie-2", "hdhub4u"),
        ]
        with patch.object(fast_fetch, "fetch_categories_hdhub4u", return_value=["bollywood-movies"]), \
             patch.object(fast_fetch, "fetch_category_urls_hdhub4u", return_value=fake_hdhub_records):
            count = fast_fetch.sync_category_archives(site="hdhub4u", max_pages_per_cat=1, verbose=False)

        self.assertEqual(count, 2)
        cached = self.rows("SELECT loc, slug, site FROM sitemap_cache WHERE site = 'hdhub4u' ORDER BY slug")
        self.assertEqual(len(cached), 2)
        self.assertEqual(tuple(cached[0]), ("https://new7.hdhub4u.cl/sample-movie-1/", "sample-movie-1", "hdhub4u"))

    def test_cli_sync_categories_command(self):
        fake_records = [("https://ssrmovies.gripe/sample-ssr-1/", "2026-10-14", "sample-ssr-1", "ssrmovies")]
        with patch.object(fast_fetch, "sync_category_archives", return_value=1) as mock_sync:
            with patch.object(sys, "argv", ["fast_fetch.py", "sync-categories", "--site", "ssrmovies", "--pages", "2"]):
                fast_fetch.main()
        mock_sync.assert_called_once_with(site="ssrmovies", max_pages_per_cat=2, category=None)

    def test_resolve_live_source_permanent(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id, final_url FROM download_sources LIMIT 1").fetchone()

        res = fast_fetch.resolve_live_source(source["id"])
        self.assertTrue(res["success"])
        self.assertEqual(res["url"], source["final_url"])
        self.assertTrue(res["cached"])
        self.assertFalse(res["refreshed"])

    def test_resolve_live_source_temporary_refresh(self):
        media_data = self.media("ssrmovies", "https://ssrmovies.example/sample-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "HubCloud Drive",
            "service": "fsl_r2",
            "resource_id": "test12345",
            "source_url": "https://hubcloud.ist/drive/test12345",
            "final_url": "https://old.r2.cloudflarestorage.com/test",
            "is_temporary": 1,
        }]
        post_id = fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
            conn.execute("UPDATE download_sources SET status = 'expired' WHERE id = ?", (source["id"],))

        mock_unwrapped = [{
            "source_name": "HubCloud R2",
            "service": "fsl_r2",
            "resource_id": "test12345",
            "source_url": "https://hubcloud.ist/drive/test12345",
            "final_url": "https://fresh.r2.cloudflarestorage.com/new_token",
            "is_temporary": 1,
        }]
        with patch.object(fast_fetch, "unwrap_hubcloud_drive", return_value=mock_unwrapped):
            res = fast_fetch.resolve_live_source(source["id"])

        self.assertTrue(res["success"])
        self.assertEqual(res["url"], "https://fresh.r2.cloudflarestorage.com/new_token")
        self.assertTrue(res["refreshed"])

    def test_api_v1_posts_and_detail(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/", imdb_id="tt9999999")
        )
        with patch.object(viewer, "DB_PATH", self.db_path):
            posts_resp = viewer.api_v1_get_posts(limit=10)
            self.assertEqual(posts_resp["total"], 1)
            self.assertEqual(len(posts_resp["results"]), 1)
            self.assertEqual(posts_resp["results"][0]["id"], post_id)

            detail = viewer.api_v1_get_post_detail(post_id)
            self.assertIsNotNone(detail)
            self.assertEqual(detail["clean_title"], "Example Film")
            self.assertEqual(detail["imdb_id"], "tt9999999")
            self.assertEqual(len(detail["releases"]), 1)

    def test_api_v1_rules(self):
        rules = viewer.api_v1_rules()
        self.assertIn("version", rules)
        self.assertIn("services", rules)
        self.assertIn("pixeldrain", rules["services"])
        self.assertIn("direct_cloud", rules["services"])
        self.assertIn("greenmotors", rules["services"])

    def test_decode_greenmotors_payload(self):
        dest_url = "https://hblinks.lol/archives/119453"
        b64_dest = base64.b64encode(dest_url.encode()).decode()
        json_obj = json.dumps({"w": 10, "l": "https://greenmotors.cc/homelander/", "o": b64_dest})
        p4 = base64.b64encode(json_obj.encode()).decode()
        import codecs
        p3 = codecs.encode(p4, "rot_13")
        p2 = base64.b64encode(p3.encode()).decode()
        payload = base64.b64encode(p2.encode()).decode()

        decoded = fast_fetch.decode_greenmotors_payload(payload)
        self.assertEqual(decoded, dest_url)

    def test_unwrap_greenmotors(self):
        dest_url = "https://hblinks.lol/archives/119453"
        b64_dest = base64.b64encode(dest_url.encode()).decode()
        json_obj = json.dumps({"w": 10, "l": "https://greenmotors.cc/homelander/", "o": b64_dest})
        p4 = base64.b64encode(json_obj.encode()).decode()
        import codecs
        p3 = codecs.encode(p4, "rot_13")
        p2 = base64.b64encode(p3.encode()).decode()
        payload = base64.b64encode(p2.encode()).decode()

        gm_html = f"""
        <html><body>
        <script>
        s('o','{payload}',180*1000);
        setTimeout(()=>window.location.href='https://greenmotors.cc/homelander/', 2000);
        </script>
        </body></html>
        """
        hb_html = """
        <html><body>
        <a href="https://hubcloud.ist/drive/9sospqs8q1nnhc8">HubCloud 1080p</a>
        <a href="https://pixeldrain.com/u/negn6f">PixelDrain Mirror</a>
        </body></html>
        """

        def mock_get(url, **kwargs):
            if "greenmotors" in url:
                return 200, url, gm_html
            elif "hblinks" in url:
                return 200, url, hb_html
            return 404, url, ""

        mock_hub = [{
            "source_name": "⚡ HubCloud [FSL R2 CDN]",
            "service": "fsl_r2",
            "resource_id": "9sospqs8q1nnhc8",
            "source_url": "https://hubcloud.ist/drive/9sospqs8q1nnhc8",
            "final_url": "https://r2.cloudflarestorage.com/hub/token123",
            "is_temporary": 1,
        }]

        with patch.object(fast_fetch, "http_get", side_effect=mock_get), \
             patch.object(fast_fetch, "unwrap_hubcloud_drive", return_value=mock_hub):
            sources = fast_fetch.unwrap_greenmotors("https://greenmotors.club/?id=testgm123")

        self.assertEqual(len(sources), 2)
        svcs = [s["service"] for s in sources]
        self.assertIn("fsl_r2", svcs)
        self.assertIn("pixeldrain", svcs)
        self.assertTrue(any("pixeldrain.com/api/file/negn6f" in s["final_url"] for s in sources))

    def test_unwrap_direct_cloud(self):
        class MockResponse:
            def __init__(self, data_bytes, url):
                self._data = data_bytes
                self._url = url
            def read(self):
                return self._data
            def geturl(self):
                return self._url
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        landing_html = """
        <html><body>
        <div id="generate_url" data-uid="uid_test_123" data-token="tok_test_456"></div>
        </body></html>
        """.encode("utf-8")

        action_json = json.dumps({
            "status": True,
            "download_url": "https://video-downloads.googleusercontent.com/test_direct_stream"
        }).encode("utf-8")

        class MockOpener:
            def open(self, req, timeout=10):
                url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
                if "/action" in url:
                    return MockResponse(action_json, "https://storage.direct-cloud.org/action")
                return MockResponse(landing_html, "https://storage.direct-cloud.org/d/uid_test_123")

        with patch("urllib.request.build_opener", return_value=MockOpener()):
            cdn_url, svc, is_temp = fast_fetch.unwrap_direct_cloud("https://dl.direct-cloud.top/d/test_id")

        self.assertEqual(cdn_url, "https://video-downloads.googleusercontent.com/test_direct_stream")
        self.assertEqual(svc, "google_cdn")
        self.assertEqual(is_temp, 1)

    def test_resolve_live_source_direct_cloud_and_greenmotors(self):
        media_data = self.media("ssrmovies", "https://ssrmovies.example/sample-dc-film/")
        media_data["releases"][0]["sources"] = [
            {
                "source_name": "Direct-Cloud High Speed",
                "service": "direct_cloud",
                "resource_id": "dc123",
                "source_url": "https://dl.direct-cloud.top/d/dc123",
                "final_url": "https://old.storage.direct-cloud.org/d/expired",
                "is_temporary": 1,
            },
            {
                "source_name": "HDHub4u Greenmotors Bridge",
                "service": "greenmotors",
                "resource_id": "gm123",
                "source_url": "https://greenmotors.club/?id=gm123",
                "final_url": "https://greenmotors.club/?id=gm123",
                "is_temporary": 0,
            }
        ]
        post_id = fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            dc_src = conn.execute("SELECT id FROM download_sources WHERE service = 'direct_cloud'").fetchone()
            gm_src = conn.execute("SELECT id FROM download_sources WHERE service = 'greenmotors'").fetchone()
            conn.execute("UPDATE download_sources SET status = 'expired' WHERE id IN (?, ?)", (dc_src["id"], gm_src["id"]))

        mock_gm_unwrapped = [{
            "source_name": "⚡ HubCloud [FSL R2 CDN]",
            "service": "fsl_r2",
            "resource_id": "r2_fresh",
            "source_url": "https://greenmotors.club/?id=gm123",
            "final_url": "https://r2.cloudflarestorage.com/fresh_token",
            "is_temporary": 1,
        }]

        with patch.object(fast_fetch, "unwrap_direct_cloud", return_value=("https://video-downloads.googleusercontent.com/fresh_dc", "google_cdn", 1)), \
             patch.object(fast_fetch, "unwrap_greenmotors", return_value=mock_gm_unwrapped):
            res_dc = fast_fetch.resolve_live_source(dc_src["id"])
            res_gm = fast_fetch.resolve_live_source(gm_src["id"])

        self.assertTrue(res_dc["success"])
        self.assertEqual(res_dc["url"], "https://video-downloads.googleusercontent.com/fresh_dc")
        self.assertTrue(res_dc["refreshed"])

        self.assertTrue(res_gm["success"])
        self.assertEqual(res_gm["url"], "https://r2.cloudflarestorage.com/fresh_token")
        self.assertTrue(res_gm["refreshed"])


class AdultContentFilterTests(unittest.TestCase):
    """18+ rows stay in the catalog but must never surface through any presentation surface."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        self.viewer_db_patch = patch.object(viewer, "DB_PATH", self.db_path)
        self.viewer_db_patch.start()
        self.cinemeta_patch = patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        self.cinemeta_patch.start()
        fast_fetch.init_db()

    def tearDown(self):
        self.cinemeta_patch.stop()
        self.viewer_db_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def save(self, **overrides):
        data = DatabaseSaveTests.media(
            "site_a",
            overrides.pop("url", "https://site-a.example/example-film/"),
            **overrides,
        )
        data.update(overrides)
        return fast_fetch.save_scraped_data(data)

    def flag(self, post_id):
        with fast_fetch.get_db() as conn:
            return conn.execute("SELECT is_18_plus FROM posts WHERE id = ?", (post_id,)).fetchone()[0]

    def test_adult_studio_in_clean_title_is_flagged(self):
        post_id = self.save(
            title="Tushy What The Wife Saw (2024)",
            clean_title="Tushy What The Wife Saw",
            url="https://site-a.example/tushy-what-the-wife-saw/",
        )
        self.assertEqual(self.flag(post_id), 1)

    def test_adult_marker_only_in_slug_is_flagged(self):
        post_id = self.save(
            title="Example Film",
            clean_title="Example Film",
            url="https://site-a.example/realitykings-example-film-2024/",
        )
        self.assertEqual(self.flag(post_id), 1)

    def test_safe_title_is_left_unflagged(self):
        post_id = self.save()
        self.assertEqual(self.flag(post_id), 0)

    def test_adult_posts_hidden_from_api_detail_m3u_and_resolver(self):
        adult_id = self.save(
            title="Vixen Desires (2024)",
            clean_title="Vixen Desires",
            url="https://site-a.example/vixen-desires/",
        )
        safe_id = self.save(
            url="https://site-a.example/example-film-2/",
            clean_title="Example Film Two",
            title="Example Film Two (2024)",
        )

        resp = viewer.api_v1_get_posts(limit=10)
        self.assertEqual(resp["total"], 1)
        self.assertEqual([r["id"] for r in resp["results"]], [safe_id])

        self.assertIsNone(viewer.api_v1_get_post_detail(adult_id))
        self.assertEqual(viewer.generate_m3u_playlist(adult_id), "")

        with fast_fetch.get_db() as conn:
            adult_source = conn.execute(
                "SELECT s.id FROM download_sources s "
                "JOIN releases r ON r.id = s.release_id "
                "WHERE r.post_id = ?",
                (adult_id,),
            ).fetchone()
            self.assertIsNotNone(adult_source)
        resolution = fast_fetch.resolve_live_source(adult_source["id"])
        self.assertFalse(resolution["success"])
        self.assertIn("18+", resolution["error"])


class CrawlRetryAccountingTests(unittest.TestCase):
    """A failed page must be retried a bounded number of times, never abandoned."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "retry.db"
        self.patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.patch.start()
        fast_fetch.init_db()

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def seed(self, rows):
        with fast_fetch.get_db() as conn:
            conn.executemany(
                "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, attempts) VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def test_fresh_schema_carries_retry_columns(self):
        with fast_fetch.get_db() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(sitemap_cache)")}
        self.assertIn("attempts", cols)
        self.assertIn("last_attempt", cols)

    def test_pre_existing_schema_is_migrated_without_losing_rows(self):
        legacy = Path(self.temp_dir.name) / "legacy.db"
        with sqlite3.connect(str(legacy)) as conn:
            conn.execute(
                "CREATE TABLE sitemap_cache (loc TEXT PRIMARY KEY, lastmod TEXT, slug TEXT, scraped INTEGER DEFAULT 0)"
            )
            conn.execute("INSERT INTO sitemap_cache (loc, slug, scraped) VALUES ('a', 'a', 1)")
            conn.commit()
        self.patch.stop()
        self.patch = patch.object(fast_fetch, "DB_PATH", legacy)
        self.patch.start()
        fast_fetch.init_db()
        with fast_fetch.get_db() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(sitemap_cache)")}
            row = conn.execute("SELECT scraped, attempts FROM sitemap_cache WHERE loc = 'a'").fetchone()
        self.assertIn("attempts", cols)
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 0)

    def test_pending_pages_outrank_retryable_failures(self):
        self.seed([
            ("fail-old", "2024-01-01", "fail-old", -1, 1),
            ("pending-new", "2024-06-01", "pending-new", 0, 0),
        ])
        with fast_fetch.get_db() as conn:
            rows = fast_fetch.select_crawl_candidates(conn, None, 10)
        self.assertEqual([r["loc"] for r in rows], ["pending-new", "fail-old"])

    def test_parked_pages_stop_being_selected(self):
        self.seed([("dead", "2024-01-01", "dead", -1, fast_fetch.MAX_CRAWL_ATTEMPTS)])
        with fast_fetch.get_db() as conn:
            self.assertEqual(fast_fetch.select_crawl_candidates(conn, None, 10), [])

    def test_indexed_pages_are_never_recrawled(self):
        self.seed([("done", "2024-01-01", "done", 1, 1)])
        with fast_fetch.get_db() as conn:
            self.assertEqual(fast_fetch.select_crawl_candidates(conn, None, 10), [])

    def test_site_filter_keeps_other_sites_out(self):
        self.seed([
            ("one/a", "2024-01-01", "a", 0, 0),
            ("two/b", "2024-01-01", "b", 0, 0),
        ])
        with fast_fetch.get_db() as conn:
            conn.execute("UPDATE sitemap_cache SET site = 'hdhub4u' WHERE loc = 'one/a'")
            conn.execute("UPDATE sitemap_cache SET site = 'vegamovies' WHERE loc = 'two/b'")
            rows = fast_fetch.select_crawl_candidates(conn, "vegamovies", 10)
        self.assertEqual([r["loc"] for r in rows], ["two/b"])

    def test_failure_records_an_attempt_and_stays_queued(self):
        self.seed([("retry/me", "2024-01-01", "retry-me", 0, 0)])
        before = time.time()
        fast_fetch.record_crawl_attempt("retry/me", indexed=False)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT scraped, attempts, last_attempt FROM sitemap_cache WHERE loc = 'retry/me'"
            ).fetchone()
            queued = fast_fetch.select_crawl_candidates(conn, None, 10)
        self.assertEqual(row[0], -1)
        self.assertEqual(row[1], 1)
        self.assertGreaterEqual(row[2], before)
        self.assertEqual([r["loc"] for r in queued], ["retry/me"])

    def test_retry_budget_is_exhausted_after_bounded_attempts(self):
        self.seed([("doomed", "2024-01-01", "doomed", 0, 0)])
        for _ in range(fast_fetch.MAX_CRAWL_ATTEMPTS):
            fast_fetch.record_crawl_attempt("doomed", indexed=False)
        with fast_fetch.get_db() as conn:
            attempts = conn.execute("SELECT attempts FROM sitemap_cache WHERE loc = 'doomed'").fetchone()[0]
            self.assertEqual(fast_fetch.select_crawl_candidates(conn, None, 10), [])
        self.assertEqual(attempts, fast_fetch.MAX_CRAWL_ATTEMPTS)

    def test_retry_budget_is_one_page_not_the_whole_queue(self):
        self.seed([(f"p/{i}", "2024-01-01", f"p{i}", 0, 0) for i in range(6)])
        with fast_fetch.get_db() as conn:
            self.assertEqual(len(fast_fetch.select_crawl_candidates(conn, None, 4)), 4)

    def test_retry_index_backs_the_candidate_query(self):
        with fast_fetch.get_db() as conn:
            # PRAGMA index_info(?) is not parameterizable; the name is a constant here.
            indexed_cols = [r[2] for r in conn.execute("PRAGMA index_info(idx_sitemap_retry)")]
        self.assertEqual(indexed_cols, ["scraped", "attempts"])


if __name__ == "__main__":
    unittest.main()
