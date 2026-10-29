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

    def test_an_unprobed_source_is_stored_as_unverified_not_active(self):
        """
        `status` is a measurement, so the writer may not invent one.

        A staging database that never followed its `dl.php` link stores
        final_url NULL with status 'unverified'. Inserting 'active' anyway made
        every merged row claim a probe that did not happen, and a viewer could
        only discover the truth by clicking.
        """
        unprobed = self.media("site_staging", "https://site-c.example/film/")
        unprobed["releases"][0]["sources"][0]["final_url"] = None
        unprobed["releases"][0]["sources"][0]["status"] = "unverified"
        fast_fetch.save_scraped_data(unprobed)

        probed = self.media("site_probe", "https://site-d.example/film/")
        probed["releases"][0]["sources"][0]["status"] = "js_required"
        fast_fetch.save_scraped_data(probed)

        silent = self.media("site_silent", "https://site-e.example/film/")
        silent["releases"][0]["sources"][0].pop("status", None)
        fast_fetch.save_scraped_data(silent)

        stored = {row[0]: row[1] for row in self.rows(
            "SELECT source_url, status FROM download_sources")}
        self.assertEqual(stored["https://site_staging.example/source"], "unverified")
        self.assertEqual(stored["https://site_probe.example/source"], "js_required",
                         "a measured verdict must survive the merge, good or bad")
        self.assertEqual(stored["https://site_silent.example/source"], "unverified",
                         "no status means no probe, not a successful one")

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

    def test_operator_dashboard_payload_exposes_every_site_page(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        fast_fetch.save_scraped_data(
            self.media("site_b", "https://site-b.example/example-film/")
        )
        # Operator mode (loopback port) keeps full provenance; the public
        # projection is asserted in test_redact.py.
        with patch.object(viewer, "DB_PATH", self.db_path):
            payload = viewer.fetch_database_payload(full=True)

        self.assertEqual(payload["stats"]["posts_count"], 1)
        self.assertEqual(len(payload["posts"]), 1)
        self.assertEqual(
            {page["source_site"] for page in payload["posts"][0]["source_pages"]},
            {"site_a", "site_b"},
        )
        self.assertEqual(payload["posts"][0]["id"], post_id)

    def test_operator_site_counts_include_legacy_release_attribution(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE releases SET source_site = 'rogmovies' WHERE post_id = ?",
                (post_id,),
            )

        with patch.object(viewer, "DB_PATH", self.db_path):
            payload = viewer.fetch_database_payload(full=True)

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

    def test_direct_media_and_bridge_urls_are_classified_honestly(self):
        direct = (
            "https://cdn.example/movie.mkv",
            "https://cdn.example/movie.mp4?token=abc",
            "https://video-downloads.googleusercontent.com/abc/file",
            "https://drive.usercontent.google.com/download?id=abc&export=download",
            "https://pixeldrain.com/api/file/abc123",
            "https://bucket.r2.cloudflarestorage.com/a/b/token",
            "https://pub-1a2b.r2.dev/a/b",
        )
        bridges = (
            "https://hubcloud.ist/drive/abc123",
            "https://hubcloud.ist/?id=abc",
            "https://fastdl.beer/embed.php?download=abc",
            "https://new5.gdflix.io/file/abc123",
            "https://pixeldrain.com/u/abc123",
            "https://pixeldrain.com/d/abc123",
            "https://gamerxyt.com/hubcloud.php?id=abc",
            "https://secure.linkszilla.top/view/abc",
        )
        for url in direct:
            self.assertTrue(fast_fetch.is_direct_media_url(url), url)
        for url in bridges:
            self.assertTrue(fast_fetch.is_bridge_url(url), url)
            self.assertFalse(fast_fetch.is_direct_media_url(url), url)

    def test_resolve_live_source_unwraps_a_cached_fastdl_bridge(self):
        """A stored FastDL `embed.php` page is HTML, not video. The resolver must
        re-resolve it to the Google CDN address and persist that instead of
        handing ExoPlayer the landing page."""
        media_data = self.media("vegamovies", "https://vegamovies.example/film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "FastDL",
            "service": "fastdl",
            "resource_id": "abc123",
            "source_url": "https://fastdl.beer/embed.php?download=abc123",
            "final_url": "https://fastdl.beer/embed.php?download=abc123",
            "is_temporary": 1,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()

        direct = "https://video-downloads.googleusercontent.com/abc/file.mp4"
        with patch.object(fast_fetch, "unwrap_fastdl",
                          return_value=(direct, "abc123", 1)), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(source["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], direct)
        self.assertTrue(res["refreshed"])
        with fast_fetch.get_db() as conn:
            stored = conn.execute(
                "SELECT final_url FROM download_sources WHERE id = ?",
                (source["id"],)).fetchone()
        self.assertEqual(stored["final_url"], direct)

    def test_unwrap_gdflix_finds_the_google_endpoint_behind_the_landing_page(self):
        page = ('<script>const player={"fileId":"1AbCdEfGhIjKlMnOpQrStUvWxYz12"};</script>')
        with patch.object(fast_fetch, "http_get",
                          return_value=(200, "https://new5.gdflix.io/file/x", page)):
            url, res_id, temp = fast_fetch.unwrap_gdflix("https://new5.gdflix.io/file/x")
        self.assertTrue(url.startswith("https://drive.usercontent.google.com/download?id="), url)
        self.assertEqual(res_id, "x")
        self.assertEqual(temp, 1)

        embedded = '<a href="https://video-downloads.googleusercontent.com/abc/file.mp4">'
        with patch.object(fast_fetch, "http_get",
                          return_value=(200, "https://new5.gdflix.io/file/x", embedded)):
            url, _res_id, _temp = fast_fetch.unwrap_gdflix("https://new5.gdflix.io/file/x")
        self.assertEqual(url, "https://video-downloads.googleusercontent.com/abc/file.mp4")

    def test_resolve_live_source_refuses_a_bridge_it_cannot_unwrap(self):
        """The whole point of the bridge guard: an unwrap that fails must not be
        reported as a playable stream. The v1 contract keeps stale *media* URLs,
        but never a landing page."""
        media_data = self.media("ssrmovies", "https://ssrmovies.example/film/")
        bridge = "https://new5.gdflix.io/file/j8Fp2VRK3AzEz3n"
        media_data["releases"][0]["sources"] = [{
            "source_name": "GDFlix Mirror",
            "service": "gdflix",
            "resource_id": "j8Fp2VRK3AzEz3n",
            "source_url": bridge,
            "final_url": bridge,
            "is_temporary": 1,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()

        with patch.object(fast_fetch, "unwrap_gdflix",
                          return_value=(bridge, "j8Fp2VRK3AzEz3n", 0)):
            res = fast_fetch.resolve_live_source(source["id"])

        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source")
        self.assertEqual(res["reason"], "bridge_unresolved")

    def test_a_cached_direct_media_url_is_still_served_from_cache(self):
        media_data = self.media("site_a", "https://site-a.example/direct/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Direct CDN",
            "service": "google_cdn",
            "resource_id": "direct-1",
            "source_url": "https://video-downloads.googleusercontent.com/abc/file.mp4",
            "final_url": "https://video-downloads.googleusercontent.com/abc/file.mp4",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute(
                "SELECT id, final_url FROM download_sources LIMIT 1").fetchone()
        res = fast_fetch.resolve_live_source(source["id"])
        self.assertTrue(res["success"], res)
        self.assertTrue(res["cached"])
        self.assertEqual(res["url"], source["final_url"])

    class _FakeResolvers:
        """The shape of `importers/host_resolvers.py`, without its sockets.

        Two renditions, an `active` verdict and a verdict that did not reach a
        byte endpoint — the only two answers the JIT branch is allowed to act on
        differently. A verdict may also carry what its own Range probe measured
        (`expires_in`, `content_type`, `size_bytes`, `http_status`), which is what
        the JIT path now stores instead of throwing away.
        """

        SERVICE_MXDROP = "mxdrop"
        SERVICE_PKEMBED = "pkembed"

        def __init__(self, verdict=None):
            self.verdict = verdict
            self.calls = []

        @staticmethod
        def _is(url, host):
            return url.startswith(f"https://{host}/")

        def is_mxdrop_embed(self, url):
            return self._is(url, "mxdrop.to")

        def is_pkembed_embed(self, url):
            return self._is(url, "pkembed.site")

        def unwrap_mxdrop(self, embed_url, fetch=None, verify=True, referer=None):
            self.calls.append(("mxdrop", embed_url, verify))
            return self.verdict or {
                "status": "active", "final_url": "https://cdn.mxdrop.example/f.mp4",
                "is_temporary": True, "expires_in": 21000.0}

        def unwrap_pkembed(self, embed_url, fetch=None, verify=True, referer=None):
            self.calls.append(("pkembed", embed_url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.pkembed.example/1000042_g64v61whic26_l.mp4",
                "is_temporary": True, "expires_in": 43200.0,
                "sources": [{"quality": "480p", "url": "x_l.mp4"},
                            {"quality": "360p", "url": "x_n.mp4"}]}

    def _embed_source(self, site, service, embed):
        media_data = self.media(site, f"https://{site}.example/film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": service,
            "service": service,
            "resource_id": "54343",
            "source_url": embed,
            "final_url": embed,
            "is_temporary": 1,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            return conn.execute(
                "SELECT id, final_url FROM download_sources LIMIT 1").fetchone()

    def test_resolve_live_source_unwraps_an_mxdrop_embed_to_its_signed_mp4(self):
        embed = "https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d"
        stored = self._embed_source("moviesmela", "mxdrop", embed)
        resolvers = self._FakeResolvers()
        with patch.object(fast_fetch, "_embed_resolvers", return_value=resolvers), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.mxdrop.example/f.mp4")
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a signed token is never permanent")
        self.assertEqual(resolvers.calls, [("mxdrop", embed, True)])
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT final_url, is_temporary, status FROM download_sources"
                " WHERE id = ?", (stored["id"],)).fetchone()
        self.assertEqual(row["final_url"], "https://cdn.mxdrop.example/f.mp4")
        self.assertEqual((row["is_temporary"], row["status"]), (1, "active"))

    def test_resolve_live_source_unwraps_a_pkembed_embed_to_its_top_rendition(self):
        embed = "https://pkembed.site/embed-g64v61whic26.html"
        stored = self._embed_source("moviesmela", "pkembed", embed)
        resolvers = self._FakeResolvers()
        with patch.object(fast_fetch, "_embed_resolvers", return_value=resolvers), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://cdn.pkembed.example/1000042_g64v61whic26_l.mp4")
        self.assertTrue(res["is_temporary"])
        self.assertEqual(resolvers.calls, [("pkembed", embed, True)])

    def test_resolve_live_source_refuses_an_embed_it_could_not_read(self):
        """`unverified` means the page unpacked and no byte endpoint answered.

        The v1 contract keeps a stale *media* URL for the shipped app, but an
        embed page is HTML: handing it to ExoPlayer is the failure this guard
        exists for, so both contracts now answer `no_playable_source`.
        """
        embed = "https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d"
        stored = self._embed_source("moviesmela", "mxdrop", embed)
        resolvers = self._FakeResolvers(verdict={
            "status": "unverified",
            "final_url": "https://vidbed.example/f.mp4?t=expired&u=1502033903&e=1",
            "notes": ["byte endpoint answered 403"]})
        with patch.object(fast_fetch, "_embed_resolvers", return_value=resolvers), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "unreachable"})):
            v1 = fast_fetch.resolve_live_source(stored["id"])
            v2 = fast_fetch.resolve_live_source(stored["id"], v2=True)

        for res in (v1, v2):
            self.assertFalse(res["success"], res)
            self.assertEqual(res["code"], "no_playable_source", res)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT final_url FROM download_sources WHERE id = ?",
                (stored["id"],)).fetchone()
        self.assertEqual(row["final_url"], embed, "the embed page stays stored")

    def test_a_signed_packer_window_is_recorded_and_survives_to_the_cached_answer(self):
        """The window is in the URL, and before this branch nothing read it.

        The packer CDNs answer with no Cache-Control and no Expires, so
        `probe_url_ttl` honestly reports `no_directive`. If the lifetime the
        resolver parsed out of the signed query were thrown away as well, the row
        fell back to the six-hour temporary-link ceiling — and a token that lives
        thirty minutes would be served from cache for the last twenty-nine of
        them. Measured on the committed path: the second call returned
        `expires_in=None, ttl_source=None` while holding a signed CDN URL.
        """
        embed = "https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d"
        stored = self._embed_source("moviesmela", "mxdrop", embed)
        resolvers = self._FakeResolvers(verdict={
            "status": "active",
            "final_url": "https://n1sxu2vld.mxcontent.example/v2/f.mp4?s=sig",
            "expires_in": 1800.0, "content_type": "video/mp4",
            "size_bytes": 425208621, "http_status": 206})
        probes = (None, {"observed": False, "reason": "no_directive", "http": 206})
        with patch.object(fast_fetch, "_embed_resolvers", return_value=resolvers), \
             patch.object(fast_fetch, "probe_url_ttl", return_value=probes):
            first = fast_fetch.resolve_live_source(stored["id"])
            self.assertAlmostEqual(first["expires_in"], 1800.0, delta=5.0)
            second = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(first["refreshed"])
        self.assertTrue(second["cached"], second)
        self.assertFalse(second["refreshed"])
        self.assertEqual(second["url"], first["url"])
        self.assertAlmostEqual(second["expires_in"], 1800.0, delta=6.0)
        self.assertEqual(len(resolvers.calls), 1, "a cached answer re-unpacks nothing")
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT expires_at, ttl_source, mime_type, file_size_bytes,"
                " http_status, is_resumable FROM download_sources WHERE id = ?",
                (stored["id"],)).fetchone()
        self.assertAlmostEqual(row["expires_at"] - time.time(), 1800.0, delta=6.0)
        self.assertEqual(row["ttl_source"], "signed_params")
        self.assertEqual((row["mime_type"], row["file_size_bytes"], row["http_status"]),
                         ("video/mp4", 425208621, 206))
        self.assertEqual(row["is_resumable"], 1, "a 206 is evidence the stream seeks")

    def test_a_cached_packer_answer_refreshes_once_its_signed_window_has_passed(self):
        """The point of recording the window: the cache has to respect it."""
        embed = "https://pkembed.site/embed-g64v61whic26.html"
        stored = self._embed_source("moviesmela", "pkembed", embed)
        resolvers = self._FakeResolvers()
        probes = (None, {"observed": False, "reason": "no_directive", "http": 206})
        with patch.object(fast_fetch, "_embed_resolvers", return_value=resolvers), \
             patch.object(fast_fetch, "probe_url_ttl", return_value=probes):
            fast_fetch.resolve_live_source(stored["id"])
            with fast_fetch.get_db() as conn:
                # Thirty-one minutes on a host whose `s`+`e` window is half an hour:
                # the stored instant is simply in the past now.
                conn.execute("UPDATE download_sources SET expires_at = ? WHERE id = ?",
                             (time.time() - 1.0, stored["id"]))
                row = conn.execute("SELECT final_url FROM download_sources WHERE id = ?",
                                   (stored["id"],)).fetchone()
            self.assertTrue(fast_fetch.is_direct_media_url(row["final_url"]),
                            row["final_url"])
            again = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(again["refreshed"], again)
        self.assertFalse(again["cached"], again)
        self.assertEqual(len(resolvers.calls), 2, again)

    def test_a_window_the_host_declares_in_its_headers_beats_the_signed_number(self):
        """Two sources of truth exist and the measured one wins: a host that says
        `Cache-Control: max-age=60` about the URL it just issued is answered by
        that, not by the lifetime its query string claims."""
        embed = "https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d"
        stored = self._embed_source("moviesmela", "mxdrop", embed)
        header_expiry = time.time() + 60.0
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=self._FakeResolvers()), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(60.0, {"observed": True, "ttl": 60.0,
                                               "expires_at": header_expiry, "http": 200})):
            res = fast_fetch.resolve_live_source(stored["id"])
        self.assertAlmostEqual(res["expires_in"], 60.0, delta=5.0)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT expires_at, ttl_source FROM download_sources WHERE id = ?",
                (stored["id"],)).fetchone()
        self.assertEqual(row["ttl_source"], "response_headers")
        self.assertAlmostEqual(row["expires_at"], header_expiry, delta=1.0)

    def test_a_row_of_another_service_never_takes_the_embed_branch(self):
        """The branch is chosen by the row's own host, not by what the resolver
        happens to be able to do: an ok.ru row is never offered to `unwrap_mxdrop`
        just because the packer hosts are wired up next door."""
        stored = self._embed_source(
            "moviesmela", "ok.ru", "https://ok.ru/videoembed/1234567")
        resolvers = self._FakeResolvers()
        with patch.object(fast_fetch, "_embed_resolvers", return_value=resolvers):
            res = fast_fetch.resolve_live_source(stored["id"])
        self.assertEqual(resolvers.calls, [])
        self.assertNotEqual(res.get("url"), "https://cdn.mxdrop.example/f.mp4")
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT final_url FROM download_sources WHERE id = ?",
                (stored["id"],)).fetchone()
        self.assertEqual(row["final_url"], "https://ok.ru/videoembed/1234567")

    def test_the_embed_branch_is_skipped_when_the_module_is_unavailable(self):
        """No importers directory is a missing feature, not a broken resolver:
        every other host must keep resolving and this row must simply be refused."""
        embed = "https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d"
        stored = self._embed_source("moviesmela", "mxdrop", embed)
        with patch.object(fast_fetch, "_embed_resolvers", return_value=None), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "unreachable"})):
            res = fast_fetch.resolve_live_source(stored["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)

    def test_the_packer_hosts_answer_as_bridges(self):
        for url in ("https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d",
                    "https://pkembed.site/embed-g64v61whic26.html",
                    "https://pkembed.site/zp8vd43rpa80.html"):
            self.assertTrue(fast_fetch.is_bridge_url(url), url)
            self.assertFalse(fast_fetch.is_direct_media_url(url), url)

    def test_embed_resolvers_imports_lazily_and_caches(self):
        """The JIT path reaches the unpackers where the importers left them, and a
        second call does not re-walk the import system."""
        original = fast_fetch._RESOLVERS
        fast_fetch._RESOLVERS = None
        try:
            first = fast_fetch._embed_resolvers()
            self.assertIsNotNone(first, "importers/host_resolvers.py must be found")
            self.assertIs(first, fast_fetch._embed_resolvers())
            self.assertEqual(first.SERVICE_MXDROP, "mxdrop")
            self.assertTrue(first.is_pkembed_embed(
                "https://pkembed.site/embed-g64v61whic26.html"))
        finally:
            fast_fetch._RESOLVERS = original

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

    def test_api_v1_type_anime_answers_the_animation_flag(self):
        """`type=anime` used to be compared against `content_type`, which only ever
        holds movie / series / complete_season / ongoing_season — so the chip the app
        shows returned zero rows while `/api/v1/stats` counted animated titles."""
        animated = self.media("site_a", "https://site-a.example/animated-film/",
                              title="Animated Film (2024)", clean_title="Animated Film")
        animated["is_animated"] = 1
        fast_fetch.save_scraped_data(animated)
        industry_anime = self.media("site_b", "https://site-b.example/other-film/",
                                    clean_title="Other Film", year=2023)
        industry_anime["industry"] = "Anime"
        fast_fetch.save_scraped_data(industry_anime)
        plain = self.media("site_c", "https://site-c.example/live-action-film/",
                           clean_title="Live Action Film", year=2022)
        fast_fetch.save_scraped_data(plain)
        series = self.media("site_d", "https://site-d.example/animated-series/",
                            clean_title="Animated Series", year=2021,
                            content_type="series")
        series["is_animated"] = 1
        fast_fetch.save_scraped_data(series)
        with patch.object(viewer, "DB_PATH", self.db_path):
            anime = viewer.api_v1_get_posts(content_type="anime", limit=10)
            self.assertEqual(anime["total"], 3)
            self.assertEqual(
                sorted(r["clean_title"] for r in anime["results"]),
                ["Animated Film", "Animated Series", "Other Film"],
            )
            # Every other value keeps the exact-equality filter it always had, and
            # animation is orthogonal to it: an animated series is still a series.
            self.assertEqual(
                sorted(r["clean_title"] for r in
                       viewer.api_v1_get_posts(content_type="movie", limit=10)["results"]),
                ["Animated Film", "Live Action Film", "Other Film"],
            )
            self.assertEqual(
                [r["clean_title"] for r in
                 viewer.api_v1_get_posts(content_type="series", limit=10)["results"]],
                ["Animated Series"],
            )
            self.assertEqual(viewer.api_v1_get_posts(limit=10)["total"], 4)

    def test_api_v1_list_filters_use_the_columns_the_ledger_actually_writes(self):
        """Industry/genre/quality/sort are composed by the list route itself, so a
        chip narrows the whole catalog before paging instead of only the rows a
        client happened to load. Quality is an existence test over releases."""
        bolly = self.media("site_a", "https://site-a.example/bolly-action/",
                           clean_title="Bolly Action", year=2024, quality="1080p")
        bolly.update({"industry": "Bollywood", "genres": "Action, Drama",
                      "imdb_rating": "8.4"})
        fast_fetch.save_scraped_data(bolly)

        holly = self.media("site_b", "https://site-b.example/holly-four/",
                           clean_title="Holly Four", year=2023, quality="2160p")
        holly.update({"industry": "Hollywood", "genres": "Drama, Sci-Fi",
                      "imdb_rating": "7.1"})
        fast_fetch.save_scraped_data(holly)

        pak = self.media("site_c", "https://site-c.example/pak-comedy/",
                         clean_title="Pak Comedy", year=2022, quality="720p")
        pak.update({"industry": "Pakistani", "country": "Pakistan",
                    "language": "Urdu", "genres": "Comedy", "imdb_rating": "6.5"})
        fast_fetch.save_scraped_data(pak)

        anime = self.media("site_d", "https://site-d.example/anime-horror/",
                           clean_title="Anime Horror", year=2021, quality="2160p")
        anime.update({"industry": "Anime", "is_animated": 1,
                      "genres": "Horror, Action", "imdb_rating": "9.0"})
        fast_fetch.save_scraped_data(anime)

        south = self.media("site_e", "https://site-e.example/south-drama/",
                           clean_title="South Drama", year=2020, quality="720p")
        south.update({"industry": "Tollywood (Telugu)", "country": "India",
                      "language": "Telugu", "genres": "Drama"})
        fast_fetch.save_scraped_data(south)

        with patch.object(viewer, "DB_PATH", self.db_path):
            def titles(**filters):
                return sorted(r["clean_title"] for r in
                              viewer.api_v1_get_posts(limit=10, **filters)["results"])

            self.assertEqual(titles(industry="bollywood"), ["Bolly Action"])
            self.assertEqual(titles(industry="hollywood"), ["Holly Four"])
            self.assertEqual(titles(industry="pakistani"), ["Pak Comedy"])
            self.assertEqual(titles(industry="south_indian"), ["South Drama"])
            self.assertEqual(titles(industry="anime"), ["Anime Horror"])

            self.assertEqual(titles(genre="action"), ["Anime Horror", "Bolly Action"])
            self.assertEqual(titles(genre="sci-fi"), ["Holly Four"])
            self.assertEqual(titles(genre="horror"), ["Anime Horror"])

            self.assertEqual(titles(quality="4k"), ["Anime Horror", "Holly Four"])
            self.assertEqual(titles(quality="1080p"), ["Bolly Action"])
            self.assertEqual(titles(quality="720p"), ["Pak Comedy", "South Drama"])

            # Facets compose with the existing text/type filters.
            self.assertEqual(
                titles(query="Bolly", quality="1080p", genre="action"),
                ["Bolly Action"])

            self.assertEqual(
                [r["clean_title"] for r in
                 viewer.api_v1_get_posts(limit=10, sort="title")["results"]],
                ["Anime Horror", "Bolly Action", "Holly Four", "Pak Comedy", "South Drama"])
            rated = [r["clean_title"] for r in
                     viewer.api_v1_get_posts(limit=10, sort="rating")["results"]]
            self.assertEqual(rated[:3], ["Anime Horror", "Bolly Action", "Holly Four"])
            self.assertEqual(rated[-1], "South Drama")  # no rating sorts last

    def test_api_v1_list_reports_whether_a_work_has_a_subtitled_print(self):
        """The tile's Subtitled chip needs one answer per work, and the label grammar owns
        the vocabulary. `subtitled` is that grammar's verdict — a work whose prints never
        claim subtitles reports False, and a word that merely looks like `sub` never
        raises the chip."""
        esubbed = self.media("site_a", "https://site-a.example/esub/",
                             clean_title="Esub Show", quality="1080p")
        esubbed["releases"][0]["release_title"] = "Esub Show 1080p WEB-DL x265 [English] ESubs"
        fast_fetch.save_scraped_data(esubbed)

        plain = self.media("site_b", "https://site-b.example/plain/",
                           clean_title="Plain Show", quality="720p")
        plain["releases"][0]["release_title"] = "Plain Show 720p WEB-DL x265"
        fast_fetch.save_scraped_data(plain)

        hardsub = self.media("site_c", "https://site-c.example/hsub/",
                             clean_title="Hardsub Anime", quality="720p")
        hardsub["releases"][0]["release_title"] = "Hardsub Anime 720p x265 HardSubs"
        fast_fetch.save_scraped_data(hardsub)

        # The verdict is per WORK, so it must hold even when the subtitled print is not
        # the one the prefilter happens to read first.
        later = self.media("site_d", "https://site-d.example/later/",
                           clean_title="Later Subbed", quality="1080p")
        later["releases"][0]["release_title"] = "Later Subbed 1080p x265"
        later["releases"].append(dict(later["releases"][0],
                                      release_title="Later Subbed 2160p HDR10 ESUB",
                                      quality="2160p",
                                      intermediate_url="https://site-d.example/release-2"))
        fast_fetch.save_scraped_data(later)

        lookalike = self.media("site_e", "https://site-e.example/submarine/",
                               clean_title="Submerged", quality="1080p")
        lookalike["releases"][0]["release_title"] = "Submerged 1080p x265 BluRay"
        fast_fetch.save_scraped_data(lookalike)

        with patch.object(viewer, "DB_PATH", self.db_path):
            flags = {r["clean_title"]: r["subtitled"]
                     for r in viewer.api_v1_get_posts(limit=10)["results"]}
            self.assertEqual(
                flags,
                {"Esub Show": True, "Plain Show": False, "Hardsub Anime": True,
                 "Later Subbed": True, "Submerged": False},
            )

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


class KeyLevelAdultIdentityTests(unittest.TestCase):
    """The adult law is applied per ROW while a work's identity is per KEY.

    Two measured defects in the production catalog:

    * 455 unflagged `posts` rows shared their exact `canonical_key` with a flagged
      row — one work, one identity, one copy hidden and one copy served.
      `save_scraped_data` folded the flag with `is_18_plus = MAX(is_18_plus, ?)` on
      the *single row it touched*, so a key that already carried several rows never
      reconciled.
    * `canonical_key` came from the page slug, so most rows carried a site's SEO
      sentence (`4-play-2021-hindi-movie-free-download`) instead of the work's
      identity (`4-play_2021`), and two sites writing one film were not even
      recognised as one work. `clean_title` is populated on every row and
      `generate_canonical_key()` already existed — it was just never used here.
    """

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

    def save(self, site="site_a", url="https://site-a.example/x", **overrides):
        media_kwargs = {k: v for k, v in overrides.items()
                        if k in ("title", "clean_title", "year", "content_type",
                                 "imdb_id", "tmdb_id", "quality", "source_name")}
        data = DatabaseSaveTests.media(site, url, **media_kwargs)
        data.update(overrides)
        return fast_fetch.save_scraped_data(data)

    def insert_legacy(self, *, url, key, clean_title="4 Play", year=2021,
                      site="site_a", flagged=0, content_type="movie"):
        """A row already in the ledger, written before this law existed."""
        with fast_fetch.get_db() as conn:
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, url.rstrip("/").split("/")[-1], f"{clean_title} ({year})",
                 clean_title, year, content_type, site, flagged, key))

    def flags(self):
        with fast_fetch.get_db() as conn:
            return {row["url"]: int(row["is_18_plus"] or 0) for row in
                    conn.execute("SELECT url, is_18_plus FROM posts")}

    def public(self, query=""):
        return viewer.api_v1_get_posts(query=query, limit=50)

    def test_a_flagged_write_reconciles_every_row_sharing_the_key(self):
        self.insert_legacy(url="https://site-a.example/one", key="4-play_2021")
        self.insert_legacy(url="https://site-b.example/two", key="4-play_2021",
                           site="site_b")

        # Site B's page is re-crawled and arrives flagged this time. The write matches
        # its OWN row by URL, so the MAX lands on one row only — the law has to reach
        # the sibling that already carries the same key.
        self.save(site="site_b", url="https://site-b.example/two",
                  clean_title="4 Play", title="4 Play (2021)", year=2021,
                  is_18_plus=1, canonical_key="4-play_2021")

        self.assertEqual(self.flags(), {
            "https://site-a.example/one": 1,
            "https://site-b.example/two": 1,
        })

    def test_the_public_list_and_search_hide_both_copies(self):
        self.insert_legacy(url="https://site-a.example/one", key="4-play_2021")
        self.insert_legacy(url="https://site-b.example/two", key="4-play_2021",
                           site="site_b", flagged=1)

        # The exposed state, with nothing written: the backfill is what closes it.
        self.assertEqual(self.public()["total"], 1)
        self.assertEqual(self.public(query="4 Play")["total"], 1)

        flipped = fast_fetch.reconcile_key_adult(self.db_path)
        self.assertEqual(flipped, 1)
        self.assertEqual(self.public()["total"], 0)
        self.assertEqual(self.public(query="4 Play")["total"], 0)

    def test_the_unknown_key_never_spreads_a_flag(self):
        self.insert_legacy(url="https://site-a.example/one", key="unknown",
                           clean_title="Unrelated Film", year=1998)
        self.insert_legacy(url="https://site-b.example/two", key="unknown",
                           clean_title="Another Film", year=1999, flagged=1)

        # `unknown` is what `generate_canonical_key` answers for a titleless payload,
        # so it is a shared bucket of unrelated works, not one work. Propagating from
        # it would hide titles on the strength of one bad page.
        flipped = fast_fetch.reconcile_key_adult(self.db_path)
        self.assertEqual(flipped, 0)
        self.assertEqual(self.flags(), {
            "https://site-a.example/one": 0,
            "https://site-b.example/two": 1,
        })
        with fast_fetch.get_db() as conn:
            self.assertEqual(fast_fetch.inherit_key_adult(conn, "unknown"), 0)
            self.assertEqual(fast_fetch.inherit_key_adult(conn, ""), 0)

    def test_an_existing_row_is_not_re_keyed_by_an_ingest(self):
        self.insert_legacy(url="https://site-a.example/one",
                           key="4-play-2021-hindi-movie-free-download")

        self.save(site="site_a", url="https://site-a.example/one",
                  clean_title="4 Play", title="4 Play (2021)", year=2021)

        with fast_fetch.get_db() as conn:
            stored = conn.execute("SELECT canonical_key FROM posts WHERE url = ?",
                                  ("https://site-a.example/one",)).fetchone()[0]
        self.assertEqual(
            stored, "4-play-2021-hindi-movie-free-download",
            "re-keying stored rows is a reviewed migration of its own, not a side "
            "effect of ingesting one page")

    def test_two_sites_writing_one_film_collapse_into_one_post(self):
        first = self.save(site="site_a", url="https://site-a.example/4-play-2021-hindi/",
                          clean_title="4 Play", title="4 Play (2021)", year=2021,
                          canonical_key="4-play-2021-hindi")
        second = self.save(site="site_b", url="https://site-b.example/4-play-watch-3/",
                           clean_title="4 Play", title="4 Play (2021)", year=2021,
                           canonical_key="4_play_2021")

        self.assertEqual(first, second,
                         "a page slug must not decide whether two sites are one work")
        with fast_fetch.get_db() as conn:
            sites = sorted(row["source_site"] for row in conn.execute(
                "SELECT source_site FROM post_sources WHERE post_id = ?", (first,)))
            key = conn.execute("SELECT canonical_key FROM posts WHERE id = ?",
                               (first,)).fetchone()[0]
        self.assertEqual(sites, ["site_a", "site_b"])
        self.assertEqual(key, "4-play_2021")

    def test_a_reconciled_key_projects_as_one_hidden_work(self):
        self.insert_legacy(url="https://site-a.example/one", key="4-play_2021")
        self.insert_legacy(url="https://site-b.example/two", key="4-play_2021",
                           site="site_b", flagged=1)
        fast_fetch.reconcile_key_adult(self.db_path)

        import catalog_v2
        with fast_fetch.get_db() as conn:
            catalog_v2.project(conn, reset=True, verbose=False)
            works = conn.execute(
                "SELECT is_18_plus, COUNT(*) AS n FROM cat_works GROUP BY is_18_plus"
            ).fetchall()
        self.assertEqual({row["is_18_plus"]: row["n"] for row in works}, {1: 1},
                         "both copies fold into one hidden work, not two answers")

    def test_reconciling_a_clean_catalog_flips_nothing(self):
        self.insert_legacy(url="https://site-a.example/one", key="safe-film_2021")
        self.insert_legacy(url="https://site-b.example/two", key="other-adult_2022",
                           site="site_b", flagged=1)
        self.assertEqual(fast_fetch.reconcile_key_adult(self.db_path), 0)
        self.assertEqual(self.public()["total"], 1)


class BackfillAdultKeyToolTests(unittest.TestCase):
    """The reviewed repair for rows written before the key-level law existed.

    `--apply` must drop the public total by EXACTLY the number of rows it flips, and
    must say so; the residual (same work, different key) must be reported and left
    alone, because closing it is the re-key migration this task forbids.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        self.cinemeta_patch = patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        self.cinemeta_patch.start()
        fast_fetch.init_db()
        import catalog_v2
        self.catalog_v2 = catalog_v2

    def tearDown(self):
        self.cinemeta_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def insert(self, *, url, key, clean_title, year=2021, site="site_a", flagged=0):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, ?, 'movie', ?, ?, ?)",
                (url, url.rstrip("/").split("/")[-1], f"{clean_title} ({year})",
                 clean_title, year, site, flagged, key))

    def build_catalog(self):
        # One exposed twin (same key) and one residual (different key).
        self.insert(url="https://a.example/one", key="4-play_2021", clean_title="4 Play")
        self.insert(url="https://b.example/two", key="4-play_2021",
                    clean_title="4 Play", site="site_b", flagged=1)
        self.insert(url="https://c.example/three",
                    key="3g-gaali-galoch-girls-episodes",
                    clean_title="3G Gaali Galoch Girls", year=2019)
        self.insert(url="https://d.example/four",
                    key="3g-gaali-galoch-girls_2019",
                    clean_title="3G Gaali Galoch Girls", year=2019,
                    site="site_b", flagged=1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            self.catalog_v2.project(conn, reset=True, verbose=False)

    def meta_keys(self):
        with sqlite3.connect(self.db_path) as conn:
            return {row[0] for row in
                    conn.execute("SELECT key FROM cat_projection_meta")}

    def test_the_tool_reports_without_writing(self):
        self.build_catalog()
        import backfill_adult_key as tool
        summary = tool.report(self.db_path)
        self.assertEqual(summary["exposed_keys"], 1)
        self.assertEqual(summary["exposed_rows"], 1)
        self.assertEqual(summary["flipped"], 0)
        self.assertEqual(summary["public_total_after"], summary["public_total_before"])
        self.assertEqual(self.flags(), {
            "https://a.example/one": 0, "https://b.example/two": 1,
            "https://c.example/three": 0, "https://d.example/four": 1,
        })

    def test_apply_drops_the_public_total_by_exactly_the_rows_flipped(self):
        self.build_catalog()
        import backfill_adult_key as tool
        before = tool.public_total(sqlite3.connect(self.db_path))
        summary = tool.report(self.db_path, apply=True)
        self.assertEqual(summary["flipped"], 1)
        self.assertEqual(summary["public_total_before"], before)
        self.assertEqual(summary["public_total_after"], before - summary["flipped"])
        self.assertEqual(self.flags()["https://a.example/one"], 1)

    def test_the_projection_step_hides_the_work_and_retires_the_safe_stamp(self):
        self.build_catalog()
        import backfill_adult_key as tool
        self.assertIn("works_safe", self.meta_keys())
        tool.report(self.db_path, apply=True, projection=True)
        keys = self.meta_keys()
        for stamp in tool.SAFE_STAMP_KEYS:
            self.assertNotIn(stamp, keys,
                             "a stamp taken before the flip must not survive it")
        with sqlite3.connect(self.db_path) as conn:
            flagged = conn.execute(
                "SELECT is_18_plus FROM cat_works WHERE title = '4 Play'").fetchone()[0]
        self.assertEqual(int(flagged), 1)

    def test_the_residual_is_reported_and_never_written(self):
        self.build_catalog()
        import backfill_adult_key as tool
        summary = tool.report(self.db_path, apply=True)
        # Before the flip the metric counts both exposed rows, because the projection
        # folds each pair into one hidden work. After it, only the pair the key law
        # cannot see remains: `3G Gaali Galoch Girls`, one work under two keys.
        self.assertEqual(summary["residual_other_key"], 2)
        self.assertEqual(summary["residual_after"], 1)
        with sqlite3.connect(self.db_path) as conn:
            still_public = conn.execute(
                "SELECT is_18_plus FROM posts WHERE url = ?",
                ("https://c.example/three",)).fetchone()[0]
        self.assertEqual(int(still_public), 0)

    def test_unknown_keys_are_never_offered_for_backfill(self):
        self.insert(url="https://a.example/one", key="unknown", clean_title="One")
        self.insert(url="https://b.example/two", key="unknown", clean_title="Two",
                    flagged=1)
        import backfill_adult_key as tool
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(tool.exposed_keys(conn), [])

    def flags(self):
        with sqlite3.connect(self.db_path) as conn:
            return {row[0]: int(row[1] or 0) for row in conn.execute(
                "SELECT url, is_18_plus FROM posts")}


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

    def payload(self, url, *, with_release):
        return {
            "url": url,
            "slug": url.rstrip("/").split("/")[-1],
            "title": "Example Film (2024)",
            "clean_title": "Example Film",
            "year": 2024,
            "content_type": "movie",
            "is_18_plus": 0,
            "is_animated": 0,
            "source_site": "example",
            "industry": "Hollywood",
            "country": "USA",
            "language": "English",
            "canonical_key": fast_fetch.generate_canonical_key("Example Film", 2024),
            "releases": [{
                "release_title": "Example Film 1080p", "quality": "1080p", "codec": "x264",
                "size": "1GB", "languages": "English",
                "sources": [{"source_name": "Example CDN", "source_url": "https://cdn.example/a"}],
            }] if with_release else [],
        }

    def save(self, url, *, with_release):
        with patch.object(fast_fetch, "fetch_cinemeta_metadata", return_value=None):
            fast_fetch.save_scraped_data(self.payload(url, with_release=with_release))

    def row_for(self, url):
        with fast_fetch.get_db() as conn:
            return conn.execute(
                "SELECT scraped, attempts, last_cause FROM sitemap_cache WHERE loc = ?",
                (url,),
            ).fetchone()

    def test_a_page_that_yielded_nothing_is_not_marked_indexed(self):
        """The silent-loss path: `scraped = 1` on an empty response hid ~1.7k
        katmoviehd and ~2.4k hindilinks4u URLs behind a green tick."""
        url = "https://example.empty/empty-page/"
        self.seed([(url, "2024-01-01", "empty-page", 0, 0)])
        self.save(url, with_release=False)
        row = self.row_for(url)
        self.assertEqual(row[0], -1, "an unreadable page is a failure, not an index")
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], "parse_no_releases")

    def test_an_empty_page_stays_reachable_until_the_budget_runs_out(self):
        url = "https://example.empty/retry-me/"
        self.seed([(url, "2024-01-01", "retry-me", 0, 0)])
        for _ in range(fast_fetch.MAX_CRAWL_ATTEMPTS - 1):
            self.save(url, with_release=False)
        with fast_fetch.get_db() as conn:
            queued = [r["loc"] for r in fast_fetch.select_crawl_candidates(conn, None, 10)]
        self.assertEqual(queued, [url])
        self.save(url, with_release=False)
        with fast_fetch.get_db() as conn:
            self.assertEqual(fast_fetch.select_crawl_candidates(conn, None, 10), [])

    def test_a_page_that_yielded_a_release_is_still_indexed(self):
        url = "https://example.good/good-page/"
        self.seed([(url, "2024-01-01", "good-page", 0, 0)])
        self.save(url, with_release=True)
        row = self.row_for(url)
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 0)
        self.assertIsNone(row[2])


class SiteScoutStagingIsolationTests(unittest.TestCase):
    """Integration smoke test: site_scout.py (Phase 1) never targets the production
    catalog and its stdlib gate works alongside the DB test suite. Imports are
    stdlib-only so this adds no dependency to the existing database tests."""

    def setUp(self):
        import site_scout
        self.site_scout = site_scout

    def test_scaffold_gate_rejects_production_catalog_path(self):
        code = "import sqlite3\np='/home/ubuntu/radd-stream-data/fast_fetch.db'\n"
        ok, reasons = self.site_scout.check_stdlib_compliance(
            code, data_dir=Path("/home/ubuntu/radd-stream-data")
        )
        self.assertFalse(ok)
        self.assertTrue(any("fast_fetch.db" in r for r in reasons))

    def test_scaffold_gate_rejects_third_party_import(self):
        ok, reasons = self.site_scout.check_stdlib_compliance(
            "import requests\n", data_dir=Path("/home/ubuntu/radd-stream-data")
        )
        self.assertFalse(ok)
        self.assertTrue(reasons)

    def test_scaffold_gate_accepts_staging_db_draft(self):
        code = (
            "import urllib.request, sqlite3\n"
            "from pathlib import Path\n"
            "DB = Path('/home/ubuntu/radd-stream-data/vegamovies.db')\n"
        )
        ok, reasons = self.site_scout.check_stdlib_compliance(
            code, data_dir=Path("/home/ubuntu/radd-stream-data")
        )
        self.assertTrue(ok, reasons)

    def test_challenge_page_is_flagged_not_bypassed(self):
        html = "<html><body><div class='cf-turnstile'>Just a moment...</div></body></html>"
        self.assertTrue(self.site_scout.is_challenge_interstitial(html))


if __name__ == "__main__":
    unittest.main()
