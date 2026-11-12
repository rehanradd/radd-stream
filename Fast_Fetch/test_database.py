"""Offline regression tests for SQLite identity resolution and multi-site saves."""

import ast
import base64
import hashlib
import json
import io
import os
import re
import socket
import socketserver
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import current_hosts
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
        # Stage-2 gate: the resolver probes every candidate address over the
        # network, and this suite is offline. The probe is a network
        # boundary like the unwrappers below, so it is stubbed to a passing
        # file verdict by default; the strict-gate tests override it with a
        # failing verdict. Stage-1 dispatch is stubbed off the same way:
        # no fixture backend is proven here, so the legacy branches run
        # exactly as before the port.
        self.stage2_probe_patch = patch.object(
            fast_fetch, "_stage2_probe",
            return_value={"ok": True, "kind": "file", "mime": "video/mp4",
                          "size": None, "resumable": True, "renditions": [],
                          "failure": None})
        self.stage2_probe_patch.start()
        self.stage1_backend_patch = patch.object(
            current_hosts, "classify_backend", return_value="unknown")
        self.stage1_backend_patch.start()
        fast_fetch.init_db()

    def tearDown(self):
        self.stage1_backend_patch.stop()
        self.stage2_probe_patch.stop()
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

    def test_ingest_files_clean_title_rating_and_synopsis(self):
        """Audit #6/#27: a new row is filed with a normalised rating and
        a marker-free synopsis — but its clean_title stays as scraped.

        A 0–100 rating is filed on the 0–10 scale, a /PLOT marker
        synopsis is filed empty of the marker, and the raw `title` and
        `clean_title` columns keep the site's text: the stored
        clean_title is identity (the canonical key derives from it, and
        the API serves it verbatim), so it is never rewritten with the
        display title — display cleaning stays serve-time.
        """
        data = self.media(
            "site_a", "https://site-a.example/salaar/",
            title="Download Salaar - Part 1 (2023) Multi Audios "
                  "[Tel + Tam + Mal + Kan] NF WeB-DL 480p [700MB]",
            clean_title="Salaar - Part 1 (2023) Multi Audios "
                        "[Tel + Tam + Mal + Kan] NF WeB-DL 480p [700MB]",
            year=2023)
        data["imdb_rating"] = "100"
        data["synopsis"] = "/PLOT:\nA rebel rises."
        post_id = fast_fetch.save_scraped_data(data)
        row = self.rows(
            "SELECT title, clean_title, imdb_rating, synopsis, "
            "canonical_key FROM posts WHERE id = ?", (post_id,))[0]
        self.assertEqual(row[0], data["title"])
        self.assertEqual(row[1], data["clean_title"])
        self.assertEqual(row[2], "10.0")
        self.assertEqual(row[3], "A rebel rises.")
        self.assertEqual(
            row[4],
            fast_fetch.generate_canonical_key(data["clean_title"], 2023))

    def test_ingest_drops_an_unshowable_rating(self):
        data = self.media("site_a", "https://site-a.example/no-rating/")
        data["imdb_rating"] = "abc"
        post_id = fast_fetch.save_scraped_data(data)
        row = self.rows(
            "SELECT imdb_rating FROM posts WHERE id = ?", (post_id,))[0]
        self.assertIsNone(row[0])

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

    def test_fuzzy_match_refuses_when_adult_flags_disagree(self):
        """A flagged page must not attach to an unflagged twin through the fuzzy
        path: that would hide the twin via MAX + inherit_key_adult without the
        evidence the merge fold demands. The twin stays for the fold to decide."""
        self._insert_legacy_row(
            "https://site-a.example/puli-2015/", "Puli", 2015, "puli-2015")
        incoming = self.media(
            "site_b", "https://site-b.example/puli-2015/",
            title="Puli (2015) 18+ Hindi Dubbed", clean_title="Puli", year=2015,
        )
        incoming["is_18_plus"] = 1
        fast_fetch.save_scraped_data(incoming)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 2)
        self.assertEqual(
            [(r[0], r[1]) for r in self.rows(
                "SELECT clean_title, is_18_plus FROM posts ORDER BY id")],
            [("Puli", 0), ("Puli", 1)],
        )

    def test_ongoing_season_rescrape_with_new_episode_count_attaches(self):
        """A re-scrape that writes S01E09 where the last scrape wrote S01E08 is
        the same season, not a new post — the volatile episode count is stripped
        before the key is computed."""
        first = self.media(
            "site_a", "https://site-a.example/one-piece-s01e08/",
            title="One Piece S01E08 Hindi", clean_title="One Piece S01E08",
            year=2023, content_type="ongoing_season",
        )
        second = self.media(
            "site_a", "https://site-a.example/one-piece-s01e09/",
            title="One Piece S01E09 Hindi", clean_title="One Piece S01E09",
            year=2023, content_type="ongoing_season",
        )
        bracketed = self.media(
            "site_a", "https://site-a.example/one-piece-s01e10/",
            title="One Piece [S01E10 Added]", clean_title="One Piece [S01E10 Added]",
            year=2023, content_type="ongoing_season",
        )
        first_id = fast_fetch.save_scraped_data(first)
        self.assertEqual(fast_fetch.save_scraped_data(second), first_id)
        self.assertEqual(fast_fetch.save_scraped_data(bracketed), first_id)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)
        self.assertEqual(
            self.rows("SELECT canonical_key FROM posts WHERE id = ?", (first_id,))[0][0],
            "one-piece_2023",
        )

    def _insert_legacy_row(self, url, clean_title, year, canonical_key, site="site_a"):
        with fast_fetch.get_db() as conn:
            cur = conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, ?, 'movie', ?, 0, ?)",
                (url, url.rstrip("/").split("/")[-1], f"{clean_title} ({year})",
                 clean_title, year, site, canonical_key),
            )
            return cur.lastrowid

    def test_fuzzy_match_attaches_to_legacy_slug_keyed_row(self):
        """The catalog still carries slug-keyed rows (`puli-2015`); a new scrape
        filed under the derived key (`puli_2015`) must attach to it, not twin it."""
        legacy_id = self._insert_legacy_row(
            "https://site-a.example/puli-2015/", "Puli", 2015, "puli-2015")
        incoming = self.media(
            "site_b", "https://site-b.example/puli-2015/",
            title="Puli (2015)", clean_title="Puli", year=2015,
        )
        self.assertEqual(fast_fetch.save_scraped_data(incoming), legacy_id)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 1)

    def test_ambiguous_fuzzy_match_raises_and_creates_nothing(self):
        """Two legacy rows normalize to the same title+year: attaching to either
        would be a guess, so the ingest refuses and leaves both rows alone."""
        self._insert_legacy_row(
            "https://site-a.example/puli-2015/", "Puli", 2015, "puli-2015")
        self._insert_legacy_row(
            "https://site-b.example/puli.2015/", "Puli", 2015, "puli.2015",
            site="site_b")
        incoming = self.media(
            "site_c", "https://site-c.example/puli-2015/",
            title="Puli (2015)", clean_title="Puli", year=2015,
        )
        with self.assertRaisesRegex(ValueError, "Fuzzy title\\+year match is ambiguous"):
            fast_fetch.save_scraped_data(incoming)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 2)

    def test_fuzzy_match_does_not_merge_different_year(self):
        self._insert_legacy_row(
            "https://site-a.example/puli-2015/", "Puli", 2015, "puli-2015")
        incoming = self.media(
            "site_b", "https://site-b.example/puli-2016/",
            title="Puli (2016)", clean_title="Puli", year=2016,
        )
        new_id = fast_fetch.save_scraped_data(incoming)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 2)
        self.assertEqual(
            self.rows("SELECT year FROM posts WHERE id = ?", (new_id,))[0][0], 2016)

    def test_fuzzy_match_does_not_merge_subtitle_variant(self):
        """`Salaar` and `Salaar Part 1 Ceasefire` share words, not an identity:
        different normalized bases must stay different posts."""
        self._insert_legacy_row(
            "https://site-a.example/salaar-part-1-ceasefire/", "Salaar Part 1 Ceasefire",
            2023, "salaar-part-1-ceasefire_2023")
        incoming = self.media(
            "site_b", "https://site-b.example/salaar/",
            title="Salaar (2023)", clean_title="Salaar", year=2023,
        )
        fast_fetch.save_scraped_data(incoming)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts")[0][0], 2)

    def test_season_and_episode_normalized_to_one_spelling(self):
        data = self.media("site_a", "https://site-a.example/example-series/",
                          content_type="series")
        data["releases"] = [
            {"release_title": "Example Series S01E01", "quality": "720p",
             "season": "1", "episode": "1", "sources": []},
            {"release_title": "Example Series S01E02", "quality": "720p",
             "season": "S01", "episode": "E01", "sources": []},
            {"release_title": "Example Series S02E03", "quality": "720p",
             "season": "Season 2", "episode": "Episode 3", "sources": []},
            {"release_title": "Example Series S01 Batch", "quality": "720p",
             "season": "Batch", "episode": "Batch", "sources": []},
            {"release_title": "Example Series EP(01-06)", "quality": "720p",
             "season": "1", "episode": "01-06", "sources": []},
        ]
        post_id = fast_fetch.save_scraped_data(data)
        stored = self.rows(
            "SELECT season, episode FROM releases WHERE post_id = ? ORDER BY id",
            (post_id,))
        self.assertEqual(
            [(r[0], r[1]) for r in stored],
            [("S01", "E01"), ("S01", "E01"), ("S02", "E03"),
             (None, None), ("S01", "01-06")],
        )

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

    def test_init_db_creates_the_detail_path_indexes(self):
        """Appetize FAILED 2: `init_db` must mint `idx_posts_year` (the
        family work-ref lookup seeks it) and, when the projection table is
        present WITH its column, `idx_cat_works_source_rev` (the per-v2-GET
        `catalog_rev` seeks it). A fresh ledger-only DB has no `cat_works`
        table, and a hand-made stub table may lack `source_rev` — both
        cases must skip the index, never break `init_db`.
        """
        with fast_fetch.get_db() as conn:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            has_cat_works = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                " AND name = 'cat_works'").fetchone()
        self.assertIn("idx_posts_year", names)
        if has_cat_works:
            self.assertIn("idx_cat_works_source_rev", names)
        else:
            self.assertNotIn("idx_cat_works_source_rev", names)
            # The stub shape a test fixture carries: no `source_rev`, so
            # `init_db` must sail past it without raising.
            with fast_fetch.get_db() as conn:
                conn.execute(
                    "CREATE TABLE cat_works"
                    " (work_key TEXT PRIMARY KEY, runtime_minutes INTEGER)")
            fast_fetch.init_db()
            with fast_fetch.get_db() as conn:
                names = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'")}
            self.assertNotIn("idx_cat_works_source_rev", names)
            # ...and once the column exists, `init_db` mints the index.
            with fast_fetch.get_db() as conn:
                conn.execute(
                    "ALTER TABLE cat_works ADD COLUMN source_rev INTEGER")
            fast_fetch.init_db()
            with fast_fetch.get_db() as conn:
                names = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'")}
            self.assertIn("idx_cat_works_source_rev", names)

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
            payload = viewer.fetch_database_payload(full=True, stats="full")

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
            payload = viewer.fetch_database_payload(full=True, stats="full")

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

    def test_stage2_gate_refuses_an_unprobed_cached_page(self):
        """The strict gate: a cached address that fails its probe is never
        served, on either contract — the answer is no_playable_source,
        not a 302 to the stored page."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            "final_url": "https://cdn.example/site_a/page.html",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        with patch.object(fast_fetch, "_stage2_probe", return_value=failing):
            v1 = fast_fetch.resolve_live_source(source["id"])
            v2 = fast_fetch.resolve_live_source(source["id"], v2=True)
        for res in (v1, v2):
            self.assertFalse(res["success"], res)
            self.assertEqual(res["code"], "no_playable_source", res)

    def test_resolve_skips_second_probe_of_same_failed_address(self):
        """A failed cached probe is not repeated as the stale probe: the
        fall-through refuses the same address it just probed, so one dead
        copy costs one probe, not two. (Pushpa 2, 2026-11-07: every copy
        paid the cached probe AND the stale probe, ~35 probes for 8+10
        copies before the honest 404.)"""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            "final_url": "https://cdn.example/site_a/page.html",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(source["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        self.assertEqual(res["reason"], "stale_probe_failed", res)
        # The cached probe only: the fall-through must not re-probe the
        # address it just failed on.
        self.assertEqual(probe.call_count, 1, probe.call_args_list)
        self.assertEqual(probe.call_args_list[0].args[0],
                         "https://cdn.example/site_a/page.html")

    def test_failover_stops_after_budget(self):
        """The sibling failover is bounded: past the budget the resolver
        answers no_playable_source instead of probing every remaining
        copy. The clock is faked so the test does not sleep."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [
            {
                "source_name": f"Copy {i}",
                "service": "test-service",
                "resource_id": f"site_a-id-{i}",
                "source_url": f"https://site_a.example/source-{i}",
                "final_url": f"https://cdn.example/site_a/page-{i}.html",
                "is_temporary": 0,
            }
            for i in range(6)
        ]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
        self.assertEqual(len(rows), 6)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        calls = {"n": 0}

        def fake_monotonic():
            calls["n"] += 1
            return 1000.0 + (calls["n"] - 1) * 6.0

        with patch.object(fast_fetch, "_stage2_probe", probe), \
             patch.object(fast_fetch.time, "monotonic",
                          side_effect=fake_monotonic):
            res = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        # Primary cached probe + exactly one sibling's cached probe; the
        # remaining four siblings are never tried, and neither the primary
        # nor the tried sibling pays a second (stale) probe.
        self.assertEqual(probe.call_count, 2, probe.call_args_list)
        probed = [c.args[0] for c in probe.call_args_list]
        self.assertEqual(probed, ["https://cdn.example/site_a/page-0.html",
                                  "https://cdn.example/site_a/page-1.html"])

    def test_negative_cache_refuses_a_recently_failed_copy(self):
        """A copy that failed is refused without re-probing on the next
        attempt: the stale fall-through sees the address already failed
        (the negative-cache record) and answers stale_probe_failed, and
        the row keeps the failure class the dispatch recorded
        (no_unwrapper here — the cached probe failed first, then no
        unwrap branch matched this host). A lone copy with no playing
        sibling still refuses; a copy whose sibling plays is served by
        the failover instead (see the two tests after this one)."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            "final_url": "https://cdn.example/site_a/page.html",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            first = fast_fetch.resolve_live_source(source["id"])
        self.assertFalse(first["success"], first)
        self.assertEqual(first["code"], "no_playable_source", first)
        self.assertEqual(probe.call_count, 1, probe.call_args_list)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at, failure_class FROM download_sources "
                "WHERE id = ?", (source["id"],)).fetchone()
        self.assertIsNotNone(row["last_failed_at"], row)
        self.assertEqual(row["failure_class"], "no_unwrapper", row)
        # Second attempt: refused without any probe at all.
        probe2 = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe2):
            second = fast_fetch.resolve_live_source(source["id"])
        self.assertFalse(second["success"], second)
        self.assertEqual(second["code"], "no_playable_source", second)
        self.assertEqual(second["reason"], "stale_probe_failed", second)
        self.assertEqual(probe2.call_count, 0, probe2.call_args_list)

    def test_negative_cache_hit_still_serves_a_playing_sibling(self):
        """Session 102 (multimovies): a dead picked copy must not kill
        the press when its sibling plays. The first press records the
        picked copy's failure and serves the sibling by failover; the
        second press hits the fresh failure record, skips the picked
        copy's own work, and serves the sibling again — no probe of
        the picked copy's address either time after the first."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Dead copy",
            "service": "test-service",
            "resource_id": "site_a-id-0",
            "source_url": "https://site_a.example/source-0",
            "final_url": "https://cdn.example/site_a/page-0.html",
            "is_temporary": 0,
        }]
        media_data["releases"].append({
            "release_title": "Example Film 1080p (2)",
            "quality": "1080p",
            "codec": "x264",
            "size": "1GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": "https://site_a.example/release-2",
            "sources": [{
                "source_name": "Warm sibling",
                "service": "test-service",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/good.mp4",
                "is_temporary": 0,
            }],
        })
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        passing = {"ok": True, "kind": "file", "mime": "video/mp4",
                   "size": 1024, "resumable": True, "renditions": [],
                   "failure": None}

        def probe_side_effect(url, **_kw):
            if url == "https://cdn.example/site_a/good.mp4":
                return passing
            return failing

        probe = Mock(side_effect=probe_side_effect)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            first = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertTrue(first["success"], first)
        self.assertTrue(first.get("failover"), first)
        self.assertEqual(first["url"], "https://cdn.example/site_a/good.mp4", first)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at, failure_class FROM download_sources "
                "WHERE id = ?", (rows[0]["id"],)).fetchone()
        self.assertIsNotNone(row["last_failed_at"], row)
        self.assertEqual(row["failure_class"], "no_unwrapper", row)
        # Second press: the picked copy is skipped on its own record and
        # the sibling serves again; only the sibling's address is probed.
        probe2 = Mock(side_effect=probe_side_effect)
        with patch.object(fast_fetch, "_stage2_probe", probe2):
            second = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertTrue(second["success"], second)
        self.assertTrue(second.get("failover"), second)
        self.assertEqual(second["url"], "https://cdn.example/site_a/good.mp4", second)
        self.assertEqual(probe2.call_count, 1, probe2.call_args_list)
        self.assertEqual(probe2.call_args_list[0].args[0],
                         "https://cdn.example/site_a/good.mp4")
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at FROM download_sources WHERE id = ?",
                (rows[0]["id"],)).fetchone()
        self.assertIsNotNone(row["last_failed_at"], row)

    def test_negative_cache_hit_with_all_siblings_dead_probes_nothing(self):
        """Session 102: when the picked copy AND its sibling both carry
        fresh failure records, the repeat press refuses without probing
        either address — each side's record is proof enough."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Dead copy",
            "service": "test-service",
            "resource_id": "site_a-id-0",
            "source_url": "https://site_a.example/source-0",
            "final_url": "https://cdn.example/site_a/page-0.html",
            "is_temporary": 0,
        }]
        media_data["releases"].append({
            "release_title": "Example Film 1080p (2)",
            "quality": "1080p",
            "codec": "x264",
            "size": "1GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": "https://site_a.example/release-2",
            "sources": [{
                "source_name": "Dead sibling",
                "service": "test-service",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/page-1.html",
                "is_temporary": 0,
            }],
        })
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            first = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertFalse(first["success"], first)
        with fast_fetch.get_db() as conn:
            records = conn.execute(
                "SELECT COUNT(*) FROM download_sources "
                "WHERE last_failed_at IS NOT NULL").fetchone()[0]
        self.assertEqual(records, 2, "both copies carry a failure record")
        probe2 = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe2):
            second = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertFalse(second["success"], second)
        self.assertEqual(second["code"], "no_playable_source", second)
        self.assertEqual(probe2.call_count, 0, probe2.call_args_list)

    def test_all_siblings_negative_cached_refuses_fast_with_its_own_reason(self):
        """Session 103: when every sibling already carries a fresh failure
        record, the Stage-2 ladder refuses from one query instead of the
        loop — no sibling resolve runs at all, and the refusal names the
        cause instead of looking like another slow probe round."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Dead copy",
            "service": "test-service",
            "resource_id": "site_a-id-0",
            "source_url": "https://site_a.example/source-0",
            "final_url": "https://cdn.example/site_a/page-0.html",
            "is_temporary": 0,
        }]
        media_data["releases"].append({
            "release_title": "Example Film 1080p (2)",
            "quality": "1080p",
            "codec": "x264",
            "size": "1GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": "https://site_a.example/release-2",
            "sources": [{
                "source_name": "Dead sibling",
                "service": "test-service",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/page-1.html",
                "is_temporary": 0,
            }],
        })
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
            conn.execute(
                "UPDATE download_sources SET last_failed_at = ?, "
                # Session 107: stamp the current resolver version, as
                # _record_resolve_failure would — a NULL version is stale
                # and would be re-probed instead of skipped.
                "failure_class = 'no_unwrapper', failure_resolver_v = ?",
                (time.time(), fast_fetch.RESOLVER_VERSION))
        self.assertEqual(len(rows), 2)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        self.assertEqual(res["reason"], "all_siblings_negative_cached", res)
        self.assertEqual(probe.call_count, 0, probe.call_args_list)

    def test_failover_prefilter_skips_a_recorded_sibling_and_serves_the_live_one(self):
        """Session 103: the pre-filter drops recorded siblings from the
        ladder but still tries the unrecorded one — a dead pick with a
        playing sibling keeps playing, and only two probes are paid (the
        pick's own cached probe, then the live sibling's)."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [
            {
                "source_name": "Dead copy",
                "service": "test-service",
                "resource_id": "site_a-id-0",
                "source_url": "https://site_a.example/source-0",
                "final_url": "https://cdn.example/site_a/page-0.html",
                "is_temporary": 0,
            },
            {
                "source_name": "Recorded sibling",
                "service": "test-service",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/page-1.html",
                "is_temporary": 0,
            },
            {
                "source_name": "Live sibling",
                "service": "test-service",
                "resource_id": "site_a-id-2",
                "source_url": "https://site_a.example/source-2",
                "final_url": "https://cdn.example/site_a/good.mp4",
                "is_temporary": 0,
            },
        ]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
            conn.execute(
                "UPDATE download_sources SET last_failed_at = ?, "
                # Session 107: stamp the current resolver version, as
                # _record_resolve_failure would — a NULL version is stale
                # and would be re-probed instead of skipped.
                "failure_class = 'no_unwrapper', failure_resolver_v = ? "
                "WHERE id = ?",
                (time.time(), fast_fetch.RESOLVER_VERSION, rows[1]["id"]))
        self.assertEqual(len(rows), 3)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        passing = {"ok": True, "kind": "file", "mime": "video/mp4",
                   "size": 1024, "resumable": True, "renditions": [],
                   "failure": None}

        def probe_side_effect(url, **_kw):
            if url == "https://cdn.example/site_a/good.mp4":
                return passing
            return failing

        probe = Mock(side_effect=probe_side_effect)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertTrue(res["success"], res)
        self.assertTrue(res.get("failover"), res)
        self.assertEqual(res["url"], "https://cdn.example/site_a/good.mp4", res)
        self.assertEqual(probe.call_count, 2, probe.call_args_list)
        self.assertEqual(
            {c.args[0] for c in probe.call_args_list},
            {"https://cdn.example/site_a/page-0.html",
             "https://cdn.example/site_a/good.mp4"})

    def test_host_health_demotes_a_repeatedly_failing_service(self):
        """Session 103: a service this process has seen fail 3+ times in
        the last hour sorts last in the failover ladder, so a host whose
        CDN is down stops being tried first on every press. The sick
        sibling is first by id, but the healthy one is served and the
        sick one is never probed. The health table is in-process only —
        the durable record is still the negative cache — so the test
        notes the failures itself and cleans them up."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [
            {
                "source_name": "Dead copy",
                "service": "test-service",
                "resource_id": "site_a-id-0",
                "source_url": "https://site_a.example/source-0",
                "final_url": "https://cdn.example/site_a/page-0.html",
                "is_temporary": 0,
            },
            {
                "source_name": "Sick sibling",
                "service": "sickhost",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/sick.mp4",
                "is_temporary": 0,
            },
            {
                "source_name": "Healthy sibling",
                "service": "healthyhost",
                "resource_id": "site_a-id-2",
                "source_url": "https://site_a.example/source-2",
                "final_url": "https://cdn.example/site_a/healthy.mp4",
                "is_temporary": 0,
            },
        ]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
            conn.execute(
                "UPDATE download_sources SET created_at = 1000")
        self.assertEqual(len(rows), 3)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        passing = {"ok": True, "kind": "file", "mime": "video/mp4",
                   "size": 1024, "resumable": True, "renditions": [],
                   "failure": None}

        def probe_side_effect(url, **_kw):
            if url in ("https://cdn.example/site_a/sick.mp4",
                       "https://cdn.example/site_a/healthy.mp4"):
                return passing
            return failing

        probe = Mock(side_effect=probe_side_effect)
        try:
            for _ in range(3):
                fast_fetch._note_host_failure("sickhost")
            with patch.object(fast_fetch, "_stage2_probe", probe):
                res = fast_fetch.resolve_live_source(rows[0]["id"])
        finally:
            fast_fetch._host_failures.pop("sickhost", None)
        self.assertTrue(res["success"], res)
        self.assertTrue(res.get("failover"), res)
        self.assertEqual(res["url"],
                         "https://cdn.example/site_a/healthy.mp4", res)
        self.assertEqual(probe.call_count, 2, probe.call_args_list)
        self.assertNotIn("https://cdn.example/site_a/sick.mp4",
                         {c.args[0] for c in probe.call_args_list})

    def test_host_health_below_threshold_does_not_reorder(self):
        """Session 103: two failures are not enough to demote — the
        threshold is 3 — so the first sibling by id still wins. A single
        failure must never reorder the ladder."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [
            {
                "source_name": "Dead copy",
                "service": "test-service",
                "resource_id": "site_a-id-0",
                "source_url": "https://site_a.example/source-0",
                "final_url": "https://cdn.example/site_a/page-0.html",
                "is_temporary": 0,
            },
            {
                "source_name": "First sibling",
                "service": "sickhost",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/sick.mp4",
                "is_temporary": 0,
            },
            {
                "source_name": "Second sibling",
                "service": "healthyhost",
                "resource_id": "site_a-id-2",
                "source_url": "https://site_a.example/source-2",
                "final_url": "https://cdn.example/site_a/healthy.mp4",
                "is_temporary": 0,
            },
        ]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
            conn.execute(
                "UPDATE download_sources SET created_at = 1000")
        self.assertEqual(len(rows), 3)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        passing = {"ok": True, "kind": "file", "mime": "video/mp4",
                   "size": 1024, "resumable": True, "renditions": [],
                   "failure": None}

        def probe_side_effect(url, **_kw):
            if url in ("https://cdn.example/site_a/sick.mp4",
                       "https://cdn.example/site_a/healthy.mp4"):
                return passing
            return failing

        probe = Mock(side_effect=probe_side_effect)
        try:
            for _ in range(2):
                fast_fetch._note_host_failure("sickhost")
            with patch.object(fast_fetch, "_stage2_probe", probe):
                res = fast_fetch.resolve_live_source(rows[0]["id"])
        finally:
            fast_fetch._host_failures.pop("sickhost", None)
        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://cdn.example/site_a/sick.mp4", res)
        self.assertEqual(probe.call_count, 2, probe.call_args_list)

    def test_negative_cache_expires_after_ttl(self):
        """A failure record older than the TTL no longer refuses: the
        copy is probed again, a passing probe serves it, and the stale
        record is cleared from the row."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            "final_url": "https://cdn.example/site_a/page.html",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            first = fast_fetch.resolve_live_source(source["id"])
        self.assertFalse(first["success"], first)
        with fast_fetch.get_db() as conn:
            stale_at = time.time() - (fast_fetch.NEGATIVE_CACHE_TTL_SECONDS + 60)
            conn.execute(
                "UPDATE download_sources SET last_failed_at = ? WHERE id = ?",
                (stale_at, source["id"]))
        # No probe patch here: the setUp stub passes, so the copy serves.
        res = fast_fetch.resolve_live_source(source["id"])
        self.assertTrue(res["success"], res)
        self.assertTrue(res["cached"], res)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at, failure_class FROM download_sources "
                "WHERE id = ?", (source["id"],)).fetchone()
        self.assertIsNone(row["last_failed_at"], row)
        self.assertIsNone(row["failure_class"], row)

    def test_negative_cache_records_unwrap_failed_for_a_branch_that_returns_nothing(self):
        """A hubcloud branch that runs and returns no copy records
        unwrap_failed — the branch existed, it just had nothing."""
        media_data = self.media("ssrmovies", "https://ssrmovies.example/sample-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "HubCloud Drive",
            "service": "hubcloud",
            "resource_id": "test12345",
            "source_url": "https://hubcloud.ist/drive/test12345",
            "final_url": "https://hubcloud.ist/drive/test12345",
            "is_temporary": 1,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        with patch.object(fast_fetch, "unwrap_hubcloud_drive", return_value=[]):
            res = fast_fetch.resolve_live_source(source["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at, failure_class FROM download_sources "
                "WHERE id = ?", (source["id"],)).fetchone()
        self.assertIsNotNone(row["last_failed_at"], row)
        self.assertEqual(row["failure_class"], "unwrap_failed", row)

    def test_stage2_probe_retries_once_on_transport_error(self):
        """Session 107 (item 2): a transport failure (HTTP 0) is retried
        once inside _stage2_probe — the network blipped, not the link —
        and a second-try success is served instead of failing."""
        transport = {"ok": False, "kind": None, "mime": None, "size": None,
                     "resumable": False, "renditions": [],
                     "failure": "transport"}
        success = {"ok": True, "kind": "file", "mime": "video/mp4",
                   "size": 1234, "resumable": True, "renditions": [],
                   "failure": None}
        # The setUp stub replaces _stage2_probe; stop it so this test
        # calls the real one, and restart it before tearDown stops it.
        self.stage2_probe_patch.stop()
        try:
            with patch.object(current_hosts, "probe_media",
                              side_effect=[transport, success]) as probe:
                verdict = fast_fetch._stage2_probe(
                    "https://cdn.example/site_a/retry-once.mp4")
        finally:
            self.stage2_probe_patch.start()
        self.assertTrue(verdict.get("ok"), verdict)
        self.assertEqual(verdict.get("kind"), "file", verdict)
        self.assertEqual(probe.call_count, 2, probe.call_args_list)

    def test_stage1_probe_retries_once_on_transport_error(self):
        """Session 107 (item 2): the Stage-1 cached probe retries once on
        a transport error, and a second-try success is served with the
        measured mime/size/resumable."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            # A pixeldrain API address: classified "pixeldrain" by
            # classify_backend AND not a bridge URL (is_bridge_url
            # exempts /api/file/), so the Stage-1 cached probe runs.
            "final_url": "https://pixeldrain.com/api/file/stage1-retry.mp4",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        transport = {"ok": False, "kind": None, "mime": None, "size": None,
                     "resumable": False, "renditions": [],
                     "failure": "transport"}
        success = {"ok": True, "kind": "file", "mime": "video/mp4",
                   "size": 1234, "resumable": True, "renditions": [],
                   "failure": None}
        with patch.object(current_hosts, "classify_backend",
                          return_value="pixeldrain"), \
             patch.object(current_hosts, "probe_media",
                          side_effect=[transport, success]) as probe:
            res = fast_fetch.resolve_live_source(source["id"])
        self.assertTrue(res["success"], res)
        self.assertTrue(res["cached"], res)
        self.assertEqual(probe.call_count, 2, probe.call_args_list)

    def test_transport_error_twice_writes_no_negative_cache_row(self):
        """Session 107 (item 2): a transport failure on both tries writes
        NO negative-cache row — the copy must not spend 12h refused for
        a failure that says nothing about it. A real probe failure
        (probe_error) still records, as before."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            "final_url": "https://cdn.example/site_a/no-poison.mp4",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        transport = {"ok": False, "kind": None, "mime": None, "size": None,
                     "resumable": False, "renditions": [],
                     "failure": "transport"}
        probe = Mock(return_value=transport)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(source["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        self.assertEqual(probe.call_count, 1, probe.call_args_list)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at, failure_class, failure_resolver_v "
                "FROM download_sources WHERE id = ?",
                (source["id"],)).fetchone()
        self.assertIsNone(row["last_failed_at"], row)
        self.assertIsNone(row["failure_class"], row)
        self.assertIsNone(row["failure_resolver_v"], row)

    def test_stale_resolver_version_row_is_reprobed(self):
        """Session 107 (item 5): a failure recorded by an older resolver
        is stale — a new unwrapper may have landed since — so the next
        press clears it and re-probes the copy once instead of refusing
        on the old verdict."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            "final_url": "https://cdn.example/site_a/stale-version.mp4",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
            conn.execute(
                "UPDATE download_sources SET last_failed_at = ?, "
                "failure_class = 'no_unwrapper', failure_resolver_v = ? "
                "WHERE id = ?",
                (time.time(), fast_fetch.RESOLVER_VERSION - 1,
                 source["id"]))
        # No probe patch here: the setUp stub passes, so the copy serves.
        res = fast_fetch.resolve_live_source(source["id"])
        self.assertTrue(res["success"], res)
        self.assertTrue(res["cached"], res)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at, failure_class FROM download_sources "
                "WHERE id = ?", (source["id"],)).fetchone()
        self.assertIsNone(row["last_failed_at"], row)
        self.assertIsNone(row["failure_class"], row)

    def test_current_resolver_version_row_still_refuses(self):
        """Session 107 (item 5): a failure recorded by the CURRENT
        resolver still refuses without re-probing — only an older
        version is stale."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "Example CDN",
            "service": "test-service",
            "resource_id": "site_a-id",
            "source_url": "https://site_a.example/source",
            "final_url": "https://cdn.example/site_a/current-version.mp4",
            "is_temporary": 0,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
            conn.execute(
                "UPDATE download_sources SET last_failed_at = ?, "
                "failure_class = 'no_unwrapper', failure_resolver_v = ? "
                "WHERE id = ?",
                (time.time(), fast_fetch.RESOLVER_VERSION, source["id"]))
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(source["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        self.assertEqual(res["reason"], "stale_probe_failed", res)
        self.assertEqual(probe.call_count, 0, probe.call_args_list)

    def test_failover_tries_direct_copies_first(self):
        """The Stage-2 sibling failover tries direct copies before bridge
        copies in the same release (tiers.CANDIDATE_ORDER_SQL), not
        lowest id first."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [
            {
                "source_name": "Primary bridge",
                "service": "test-service",
                "resource_id": "site_a-id-0",
                "source_url": "https://site_a.example/source-0",
                "final_url": "https://cdn.example/site_a/page-0.html",
                "playback_type": "url",
                "is_temporary": 0,
            },
            {
                "source_name": "Sibling bridge",
                "service": "test-service",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/page-1.html",
                "playback_type": "url",
                "is_temporary": 0,
            },
            {
                "source_name": "Sibling direct",
                "service": "test-service",
                "resource_id": "site_a-id-2",
                "source_url": "https://site_a.example/source-2",
                "final_url": "https://cdn.example/site_a/page-2.html",
                "playback_type": "direct",
                "is_temporary": 0,
            },
        ]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
        self.assertEqual(len(rows), 3)
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        probed = [c.args[0] for c in probe.call_args_list]
        self.assertEqual(probed, ["https://cdn.example/site_a/page-0.html",
                                  "https://cdn.example/site_a/page-2.html",
                                  "https://cdn.example/site_a/page-1.html"])

    def test_stage1_sibling_failover_stops_after_budget(self):
        """The Stage-1 sibling failover is bounded by the same 10 s
        deadline as the Stage-2 ladder: past it, no new sibling is
        started. The clock is faked so the test does not sleep."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [
            {
                "source_name": f"VidBolt {i}",
                "service": "vidbolt",
                "resource_id": f"vidbolt-id-{i}",
                "source_url": f"https://vidbolt.xyz/embed/{i}",
                "final_url": f"https://vidbolt.xyz/embed/{i}",
                "is_temporary": 1,
            }
            for i in range(6)
        ]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
        self.assertEqual(len(rows), 6)
        stage1_fail = {"ok": False, "backend": "vidbolt", "failure": "unverified"}
        resolve_copy = Mock(return_value=stage1_fail)
        calls = {"n": 0}

        def fake_monotonic():
            calls["n"] += 1
            return 1000.0 + (calls["n"] - 1) * 6.0

        with patch.object(current_hosts, "classify_backend", return_value="vidbolt"), \
             patch.object(current_hosts, "resolve_copy", resolve_copy), \
             patch.object(fast_fetch.time, "monotonic", side_effect=fake_monotonic):
            res = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        self.assertEqual(res["reason"], "stage1_all_copies_failed", res)
        # Primary dispatch + exactly one sibling: the second sibling is
        # never started once the faked clock passes the deadline.
        self.assertEqual(resolve_copy.call_count, 2, resolve_copy.call_args_list)
    def test_stage1_single_copy_release_falls_through_to_stage2(self):
        """Session 102 (multimovies): a Stage-1 copy that is the ONLY
        source in its release must not be refused with
        stage1_all_copies_failed — the Stage-1 ladder tried nothing,
        so the Stage-2 cross-release ladder still runs and a playing
        sibling in another release serves the press."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "VidBolt 0",
            "service": "vidbolt",
            "resource_id": "vidbolt-id-0",
            "source_url": "https://vidbolt.xyz/embed/0",
            "final_url": "https://vidbolt.xyz/embed/0",
            "is_temporary": 1,
        }]
        media_data["releases"].append({
            "release_title": "Example Film 1080p (2)",
            "quality": "1080p",
            "codec": "x264",
            "size": "1GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": "https://site_a.example/release-2",
            "sources": [{
                "source_name": "Warm sibling",
                "service": "test-service",
                "resource_id": "site_a-id-1",
                "source_url": "https://site_a.example/source-1",
                "final_url": "https://cdn.example/site_a/good.mp4",
                "is_temporary": 0,
            }],
        })
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM download_sources ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        stage1_fail = {"ok": False, "backend": "vidbolt", "failure": "unverified"}
        resolve_copy = Mock(return_value=stage1_fail)
        passing = {"ok": True, "kind": "file", "mime": "video/mp4",
                   "size": 1024, "resumable": True, "renditions": [],
                   "failure": None}
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}

        def probe_side_effect(url, **_kw):
            if url == "https://cdn.example/site_a/good.mp4":
                return passing
            return failing

        def classify_side_effect(url, *args, **_kw):
            return "vidbolt" if "vidbolt" in url else "unknown"

        probe = Mock(side_effect=probe_side_effect)
        with patch.object(current_hosts, "classify_backend",
                          side_effect=classify_side_effect), \
             patch.object(current_hosts, "resolve_copy", resolve_copy), \
             patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(rows[0]["id"])
        self.assertTrue(res["success"], res)
        self.assertTrue(res.get("failover"), res)
        self.assertEqual(res["url"], "https://cdn.example/site_a/good.mp4", res)
        # Only the picked copy's own dispatch ran: the Stage-1 ladder
        # had no same-release sibling to try.
        self.assertEqual(resolve_copy.call_count, 1, resolve_copy.call_args_list)
    def test_unwrap_vidly_reads_the_signed_bridge_master(self):
        """Session 102 (multimovies): the live filmu page is a Next.js
        shell now — the media URL arrives as a CloudFront-signed master
        behind the dash-hls-bridge Workers proxy, flight-data escaped
        (\\/ and \\u0026). The extractor decodes the escapes first,
        then takes the bridge URL to the closing quote so the signed
        query (Policy/Signature/Key-Pair-Id) survives: without it the
        bridge 502s. The old /media/ shape still works as a fallback,
        an empty page stays unverified, and series still refuse."""
        escaped = ("https:\\/\\/dash-hls-bridge.johndoesdmc.workers.dev"
                   "\\/?url=https%3A%2F%2Fsacdn.hakunaymatata.com%2Fdash"
                   "%2F4636220553102250728_0_0_1080_h265_13%2Fmaster.m3u8"
                   "\\u0026Policy=POLICY\\u0026Signature=SIG"
                   "\\u0026Key-Pair-Id=KEY")
        expected = ("https://dash-hls-bridge.johndoesdmc.workers.dev"
                    "/?url=https%3A%2F%2Fsacdn.hakunaymatata.com%2Fdash"
                    "%2F4636220553102250728_0_0_1080_h265_13%2Fmaster.m3u8"
                    "&Policy=POLICY&Signature=SIG&Key-Pair-Id=KEY")
        page = ('<html><head><link rel="preload" as="fetch" href="'
                + escaped + '"></head><body></body></html>')

        class _FakePage:
            def __init__(self, status, body):
                self.status = status
                self._body = body
            def text(self):
                return self._body

        backend, candidates, failure = current_hosts._unwrap_vidly(
            "https://embed.filmu.in/movie/960875",
            lambda url, referer=None: _FakePage(200, page))
        self.assertEqual(backend, "vidly")
        self.assertIsNone(failure)
        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["url"], expected, candidates)
        # Legacy shape still yields its candidate.
        legacy_page = ("<html><body>https://cdn.example/media/abc123/"
                       "index.m3u8</body></html>")
        _b, legacy, _f = current_hosts._unwrap_vidly(
            "https://embed.filmu.in/movie/960875",
            lambda url, referer=None: _FakePage(200, legacy_page))
        self.assertEqual([c["url"] for c in legacy],
                         ["https://cdn.example/media/abc123/index.m3u8"])
        # Empty page: unverified. Series: refused without fetching.
        _b, empty, failure = current_hosts._unwrap_vidly(
            "https://embed.filmu.in/movie/960875",
            lambda url, referer=None: _FakePage(200, "<html></html>"))
        self.assertEqual(empty, [])
        self.assertEqual(failure, "unverified")
        fetched = []
        _b, _c, failure = current_hosts._unwrap_vidly(
            "https://embed.filmu.in/tv/960875",
            lambda url, referer=None: fetched.append(url) or _FakePage(200, page))
        self.assertEqual(failure, "series_server_unverified")
        self.assertEqual(fetched, [])



    def test_unwrap_fastdl_dead_page_uses_a_short_single_fetch(self):
        """A dead FastDL landing page costs one 5 s fetch, not 15 s x 3
        attempts (45 s) on the legacy http_get default."""
        getter = Mock(return_value=(0, "https://fastdl.beer/embed.php?download=x",
                                    "ERROR: timeout"))
        with patch.object(fast_fetch, "http_get", getter):
            direct, _res_id, _temp = fast_fetch.unwrap_fastdl(
                "https://fastdl.beer/embed.php?download=x")
        self.assertEqual(direct, "https://fastdl.beer/embed.php?download=x")
        self.assertEqual(getter.call_count, 1, getter.call_args_list)
        self.assertEqual(getter.call_args.kwargs.get("timeout"), 5)
        self.assertEqual(getter.call_args.kwargs.get("max_retries"), 0)

    def test_unwrap_vcloud_dead_page_uses_short_single_fetches(self):
        """Both V-Cloud hops (landing page, token URL) cost one 5 s
        fetch each, not 15 s x 3 attempts."""
        token = base64.b64encode(
            base64.b64encode(b"https://token.example/x")).decode()
        page = f"var url = atob(atob('{token}'));"
        getter = Mock(side_effect=[
            (200, "https://vcloud.example/abc", page),
            (0, "https://token.example/x", "ERROR: timeout"),
        ])
        with patch.object(fast_fetch, "http_get", getter):
            out = fast_fetch.unwrap_vcloud("https://vcloud.example/abc")
        self.assertEqual(len(out), 1)
        self.assertEqual(getter.call_count, 2, getter.call_args_list)
        for call in getter.call_args_list:
            self.assertEqual(call.kwargs.get("timeout"), 5)
            self.assertEqual(call.kwargs.get("max_retries"), 0)

    def test_unwrap_hubcloud_drive_dead_page_retries_once(self):
        """A dead HubCloud Drive page keeps its 10 s timeout but costs
        two attempts, not three."""
        getter = Mock(return_value=(0, "https://hubcloud.ist/drive/abc", ""))
        with patch.object(fast_fetch, "http_get", getter):
            out = fast_fetch.unwrap_hubcloud_drive("https://hubcloud.ist/drive/abc")
        self.assertEqual(len(out), 1)
        self.assertEqual(getter.call_count, 1, getter.call_args_list)
        self.assertEqual(getter.call_args.kwargs.get("timeout"), 10)
        self.assertEqual(getter.call_args.kwargs.get("max_retries"), 1)

    def test_unwrap_gdflix_dead_page_retries_once(self):
        """A dead GDFlix page keeps its 10 s timeout but costs two
        attempts, not three."""
        getter = Mock(return_value=(0, "https://new5.gdflix.io/file/x", ""))
        with patch.object(fast_fetch, "http_get", getter):
            direct, _res_id, _temp = fast_fetch.unwrap_gdflix(
                "https://new5.gdflix.io/file/x")
        self.assertEqual(direct, "https://new5.gdflix.io/file/x")
        self.assertEqual(getter.call_count, 1, getter.call_args_list)
        self.assertEqual(getter.call_args.kwargs.get("timeout"), 10)
        self.assertEqual(getter.call_args.kwargs.get("max_retries"), 1)

    def test_unwrap_greenmotors_dead_page_retries_once(self):
        """A dead GreenMotors page keeps its 10 s timeout but costs two
        attempts, not three."""
        getter = Mock(return_value=(0, "https://greenmotors.club/?id=testgm123", ""))
        with patch.object(fast_fetch, "http_get", getter):
            out = fast_fetch.unwrap_greenmotors("https://greenmotors.club/?id=testgm123")
        self.assertEqual(len(out), 1)
        self.assertEqual(getter.call_count, 1, getter.call_args_list)
        self.assertEqual(getter.call_args.kwargs.get("timeout"), 10)
        self.assertEqual(getter.call_args.kwargs.get("max_retries"), 1)

    def test_resolve_release_resolves_siblings_in_parallel(self):
        """Siblings resolve on worker threads, not one by one: four
        copies whose fetches each sleep 50 ms run on four distinct
        threads, so the batch costs one sleep, not four."""
        import threading

        thread_ids = []
        ids_lock = threading.Lock()

        def fake_fetch(url, referer=None, method="GET", range_bytes=None,
                       data=None, timeout=15.0):
            with ids_lock:
                thread_ids.append(threading.get_ident())
            time.sleep(0.05)
            return current_hosts.FetchResult(status=404, error="http_404")

        rows = [{"id": i + 1, "source_url": f"https://vidbolt.xyz/embed/{i}",
                 "final_url": f"https://vidbolt.xyz/embed/{i}",
                 "service": "vidbolt", "status": "active"}
                for i in range(4)]
        # setUp stubs classify_backend to "unknown"; this test needs the
        # real vidbolt branch so the fetch actually runs.
        with patch.object(current_hosts, "classify_backend", return_value="vidbolt"):
            res = current_hosts.resolve_release(rows, fetch=fake_fetch)
        self.assertEqual(len(res["failures"]), 4, res)
        self.assertIsNone(res["watch_winner"], res)
        self.assertEqual(len(set(thread_ids)), 4, thread_ids)

    def test_resolve_release_deadline_stops_new_siblings(self):
        """A deadline stops new siblings from starting: with a faked
        clock advancing 6 s per check, a 10 s deadline starting at
        t=1000 admits exactly two siblings."""
        def fake_fetch(url, referer=None, method="GET", range_bytes=None,
                       data=None, timeout=15.0):
            return current_hosts.FetchResult(status=404, error="http_404")

        rows = [{"id": i + 1, "source_url": f"https://vidbolt.xyz/embed/{i}",
                 "final_url": f"https://vidbolt.xyz/embed/{i}",
                 "service": "vidbolt", "status": "active"}
                for i in range(6)]
        calls = {"n": 0}

        def fake_monotonic():
            calls["n"] += 1
            return 1000.0 + (calls["n"] - 1) * 6.0

        with patch.object(current_hosts, "classify_backend", return_value="vidbolt"), \
             patch.object(current_hosts.time, "monotonic",
                          side_effect=fake_monotonic):
            res = current_hosts.resolve_release(
                rows, fetch=fake_fetch, deadline=1010.0)
        # Two siblings tried (each failed the probe); the remaining
        # four were never started.
        self.assertEqual(len(res["failures"]), 2, res)
        self.assertIsNone(res["watch_winner"], res)

    def test_stage2_gate_serves_a_probed_cached_address(self):
        """The other side of the gate: a cached address that passes its
        probe is served from cache, flagged as probed."""
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/")
        )
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id, final_url FROM download_sources LIMIT 1").fetchone()

        res = fast_fetch.resolve_live_source(source["id"])
        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], source["final_url"])
        self.assertTrue(res["cached"])
        self.assertTrue(res.get("stage2_probed"))

    def test_stage1_dispatch_serves_a_proven_backend_copy(self):
        """A proven backend resolves through current_hosts first: a passing
        resolve_copy is served fresh with measured mime/size/resumable."""
        media_data = self.media("site_a", "https://site-a.example/example-film/")
        media_data["releases"][0]["sources"] = [{
            "source_name": "VidBolt",
            "service": "vidbolt",
            "resource_id": "vidbolt-id",
            "source_url": "https://vidbolt.xyz/embed/abc",
            "final_url": "https://vidbolt.xyz/embed/abc",
            "is_temporary": 1,
        }]
        fast_fetch.save_scraped_data(media_data)
        with fast_fetch.get_db() as conn:
            source = conn.execute("SELECT id FROM download_sources LIMIT 1").fetchone()
        stage1 = {"ok": True, "url": "https://cdn.vidbolt.example/v.mp4",
                  "mime": "video/mp4", "size": 4242, "resumable": True,
                  "kind": "file", "temporary": True}
        with patch.object(current_hosts, "classify_backend", return_value="vidbolt"), \
             patch.object(current_hosts, "resolve_copy", return_value=stage1), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(source["id"])
        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.vidbolt.example/v.mp4")
        self.assertTrue(res["refreshed"])
        self.assertEqual(res["mime_type"], "video/mp4")
        self.assertEqual(res["file_size_bytes"], 4242)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT final_url, is_temporary, mime_type, file_size_bytes,"
                " http_status, is_resumable FROM download_sources WHERE id = ?",
                (source["id"],)).fetchone()
        self.assertEqual(row["final_url"], "https://cdn.vidbolt.example/v.mp4")
        self.assertEqual((row["mime_type"], row["file_size_bytes"],
                          row["http_status"], row["is_resumable"]),
                         ("video/mp4", 4242, 206, 1))

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

        # Phase C item 4: the hubcloud branch now resolves through the new
        # unwrap_hubcloud (main 41d12361), not the old inline
        # unwrap_hubcloud_drive — so the refresh is stubbed at the
        # dispatcher (a fake resolver carrying the fresh verdict), and the
        # old drive unwrapper is no longer consulted here.
        fresh = {
            "status": "active",
            "final_url": "https://fresh.r2.cloudflarestorage.com/new_token",
            "is_temporary": True, "expires_in": 18000.0,
            "content_type": "video/x-matroska",
            "http_status": 206, "size_bytes": 1705388883,
        }
        resolvers = self._FakeResolvers(verdict=fresh)
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers):
            res = fast_fetch.resolve_live_source(source["id"])

        self.assertTrue(res["success"])
        self.assertEqual(res["url"], "https://fresh.r2.cloudflarestorage.com/new_token")
        self.assertTrue(res["refreshed"])
        self.assertEqual(resolvers.calls, [("hubcloud",
                                            "https://hubcloud.ist/drive/test12345",
                                            True)])

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

    def test_a_ledger_demoted_link_is_re_resolved_never_recalled(self):
        """The play path's honesty begins here, in the resolver's refresh trigger.

        `tiers.UNPLAYABLE_STATES` names five ledger words and this function honoured
        two: a permanent row retired as `broken`, `gone` or `unreachable` walked past
        the check into the cached branch and answered as a stream. It must instead be
        re-resolved — and with no bridge to walk, fail. Nothing may re-state the
        stored address as playable, and nothing may launder it back to `active`.
        """
        for verdict in ("broken", "gone", "unreachable"):
            with self.subTest(status=verdict):
                media_data = self.media("site_a", f"https://site-a.example/{verdict}/")
                media_data["releases"][0]["sources"] = [{
                    "source_name": "Direct CDN",
                    "service": "google_cdn",
                    "resource_id": f"demoted-{verdict}",
                    "source_url": "https://video-downloads.googleusercontent.com/abc/file.mp4",
                    "final_url": "https://video-downloads.googleusercontent.com/abc/file.mp4",
                    "is_temporary": 0,
                }]
                fast_fetch.save_scraped_data(media_data)
                with fast_fetch.get_db() as conn:
                    source = conn.execute(
                        "SELECT id FROM download_sources ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    conn.execute(
                        "UPDATE download_sources SET status = ? WHERE id = ?",
                        (verdict, source["id"]))
                res = fast_fetch.resolve_live_source(source["id"])
                self.assertFalse(res["success"] and not res.get("stale"),
                                 f"a {verdict} link answered as a stream: {res}")
                strict = fast_fetch.resolve_live_source(source["id"], v2=True)
                self.assertFalse(strict["success"], strict)
                self.assertEqual(strict["code"], "no_playable_source", strict)
                with fast_fetch.get_db() as conn:
                    stored = conn.execute(
                        "SELECT status FROM download_sources WHERE id = ?",
                        (source["id"],)).fetchone()
                self.assertEqual(stored["status"], verdict,
                                 "a failed re-resolve must not promote the row back to active")

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
        SERVICE_ANIMAHD = "animahd-player"
        SERVICE_GOFILE = "gofile"
        SERVICE_FILEPRESS = "filepress"
        SERVICE_STREAMTAPE = "streamtape"
        SERVICE_STREAM = "stream"
        SERVICE_STREAMWISH = "streamwish"
        SERVICE_VOE = "voe"
        SERVICE_VIDHIDE = "vidhide"
        SERVICE_VIDMOLY = "vidmoly"
        SERVICE_UPLOADFLIX = "uploadflix"
        SERVICE_1XPLAYER = "1xplayer"
        SERVICE_MOVIEBOX = "moviebox"
        SERVICE_CASTLE = "castle"
        SERVICE_VIDBOLT = "vidbolt"
        SERVICE_VIBUXER = "vibuxer"
        SERVICE_VIDRIFT = "vidrift"
        SERVICE_IQSMART = "iqsmart"
        SERVICE_FILMU = "filmu"
        SERVICE_CINEVERSE = "cineverse"
        SERVICE_HUBCLOUD = "hubcloud"
        SERVICE_VIDOUT = "vidout"

        def __init__(self, verdict=None):
            self.verdict = verdict
            self.calls = []

        @staticmethod
        def _is(url, host):
            return url.startswith(f"https://{host}/")

        def is_mxdrop_embed(self, url):
            # Session 103: the live embed hosts are mxdrop.to, mxdrop.click
            # and mixdrop.ag — the file page (/f/) is never an embed.
            return (url.startswith("https://mxdrop.to/e/")
                    or url.startswith("https://mxdrop.click/e/")
                    or url.startswith("https://mixdrop.ag/e/"))

        def is_pkembed_embed(self, url):
            return self._is(url, "pkembed.site")

        def is_animahd_player(self, url):
            # The fake covers no animahd rows; the chain reads this
            # attribute before the Session 103 branches, so it must
            # exist (a missing attribute aborts the whole dispatch).
            return False

        def is_hglink_loader(self, url):
            # Phase C item 4: the chain reads this before the packer
            # branch. The fake recognises the hglink.to loader shape, so
            # a streamwish-loader row reaches the new streamwish branch
            # and an embed row does not.
            return url.startswith("https://hglink.to/")

        def streamwish_vibuxer_url(self, url):
            # Phase C item 4: the loader preserves the id, and a bare-id
            # vibuxer.com page is the same chain; /e/ and /embed/ are
            # unwrap_vibuxer's shape and are refused here.
            if url.startswith("https://hglink.to/"):
                return "https://vibuxer.com/" + url.rsplit("/", 1)[-1]
            if (url.startswith("https://vibuxer.com/")
                    and "/e/" not in url and "/embed/" not in url):
                return url
            return ""

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

        def unwrap_streamwish(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("streamwish", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/streamwish/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200}

        def unwrap_vidout(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("vidout", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/vidout/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200}

        def unwrap_hubcloud(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("hubcloud", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://fresh.r2.cloudflarestorage.com/new_token",
                "is_temporary": True, "expires_in": 18000.0,
                "content_type": "video/x-matroska",
                "http_status": 206, "size_bytes": 1705388883}

        def unwrap_gofile(self, url, fetch=None, verify=True):
            self.calls.append(("gofile", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cold2.example/dl/abc/Film.2024.1080p.mkv",
                "is_temporary": True, "expires_in": None,
                "content_type": "video/mp4", "http_status": 206,
                "size_bytes": 2000000000}

        def unwrap_filepress(self, url, fetch=None, verify=True):
            self.calls.append(("filepress", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://aws.flapdoodle.cyou/download/abc123/"
                             "Film.2024.1080p.mkv",
                "is_temporary": True, "expires_in": None,
                "content_type": "video/x-matroska", "http_status": 206,
                "size_bytes": 1800000000}

        def unwrap_streamtape(self, embed_url, fetch=None, verify=True):
            self.calls.append(("streamtape", embed_url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://streamtape.to/get_video?id=abc"
                             "&expires=1794166028&ip=x&token=y",
                "is_temporary": True, "expires_in": 3600.0,
                "content_type": "video/mp4", "http_status": 206,
                "size_bytes": 1401038502}

        def unwrap_packer_hls(self, embed_url, service, fetch=None, verify=True):
            self.calls.append(("packer_hls", embed_url, service, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/hls2/01/1/f/master.m3u8"
                             "?t=x&s=1&e=129600&f=1",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 206, "size_bytes": 512}

        def unwrap_voe(self, embed_url, fetch=None, verify=True):
            self.calls.append(("voe", embed_url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/hls/master.m3u8",
                "is_temporary": True, "expires_in": 14400.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 206, "size_bytes": 512}

        def unwrap_vidhide(self, embed_url, fetch=None, verify=True):
            self.calls.append(("vidhide", embed_url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/hls/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 206, "size_bytes": 512}

        def unwrap_uploadflix(self, url, fetch=None, verify=True):
            self.calls.append(("uploadflix", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cloud.secure-storage.top:8080/d/abc/Film.mkv",
                "is_temporary": True, "expires_in": None,
                "content_type": "application/octet-stream",
                "http_status": 206, "size_bytes": 2000000000}

        def unwrap_1xplayer(self, url, fetch=None, verify=True):
            self.calls.append(("1xplayer", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://i-arch-400.example/stream2/index.m3u8",
                "is_temporary": True, "expires_in": 7200.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

        def unwrap_moviebox(self, url, fetch=None, verify=True):
            self.calls.append(("moviebox", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://bcdnxw.example/bt/abc.mp4?sign=x&t=1",
                "is_temporary": True, "expires_in": None,
                "content_type": "video/mp4", "http_status": 206,
                "size_bytes": 3466489425}

        def unwrap_vidbolt(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("vidbolt", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/vidbolt/stream.m3u8",
                "is_temporary": True, "expires_in": 14400.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

        def unwrap_vibuxer(self, embed_url, fetch=None, verify=True, referer=None):
            self.calls.append(("vibuxer", embed_url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/vibuxer/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

        def unwrap_vidrift(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("vidrift", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/vidrift/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

        def unwrap_iqsmart(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("iqsmart", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/iqsmart/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

        def unwrap_filmu(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("filmu", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/filmu/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

        def unwrap_cineverse(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("cineverse", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://cdn.example/cineverse/master.m3u8",
                "is_temporary": True, "expires_in": 129600.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

        def unwrap_castle(self, url, fetch=None, verify=True, referer=None):
            self.calls.append(("castle", url, verify))
            return self.verdict or {
                "status": "active",
                "final_url": "https://img01.tlnob.example/video/abc/index_401.m3u8",
                "is_temporary": True, "expires_in": 10800.0,
                "content_type": "application/vnd.apple.mpegurl",
                "http_status": 200, "size_bytes": 512}

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

    def test_resolve_live_source_unwraps_a_mixdrop_file_page_to_its_signed_mp4(self):
        """Session 103: the catalog stores mixdrop file pages (/f/<id>),
        not embeds — the packer lives on /e/<id>, so the resolver rewrites
        the path before the matcher sees it. The same unwrap_mxdrop serves
        them (verified live: the unpacked wurl answered 206 video/mp4)."""
        file_page = "https://mixdrop.ag/f/k0ndmr6xbpdw6w"
        stored = self._embed_source("moviesmela", "mixdrop", file_page)
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
        self.assertEqual(resolvers.calls,
                         [("mxdrop", "https://mixdrop.ag/e/k0ndmr6xbpdw6w", True)])
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT final_url, is_temporary, status FROM download_sources"
                " WHERE id = ?", (stored["id"],)).fetchone()
        self.assertEqual(row["final_url"], "https://cdn.mxdrop.example/f.mp4")
        self.assertEqual((row["is_temporary"], row["status"]), (1, "active"))

    def test_mixdrop_embed_matcher_covers_the_live_hosts(self):
        """Session 103: mxdrop.click and mixdrop.ag serve the same packed
        config as mxdrop.to (verified live 2026-11-08); the file page is
        not an embed, only /e/ is."""
        hr = fast_fetch._embed_resolvers()
        for url in ("https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d",
                    "https://mxdrop.click/e/k0ndmr6xbpdw6w",
                    "https://mixdrop.ag/e/k0ndmr6xbpdw6w"):
            self.assertTrue(hr.is_mxdrop_embed(url), url)
        for url in ("https://mixdrop.ag/f/k0ndmr6xbpdw6w",
                    "https://mxdrop.to/xo78jxvjagwq9x"):
            self.assertFalse(hr.is_mxdrop_embed(url), url)

    def test_gofile_website_token_pins_the_hash_format(self):
        """Session 103: the website token is sha256(UA :: language ::
        accountToken :: 4h-window :: salt) — the UA and language hashed
        MUST be the ones sent on the request. The window is floor(now /
        14400); pinning the format here, the live server validates the
        value (the known vector was verified against gofile's own JS)."""
        hr = fast_fetch._embed_resolvers()
        fixed_now = 124589 * 14400  # window 124589
        with patch.object(hr.time, "time", return_value=float(fixed_now)):
            token = hr._gofile_website_token("TESTTOKEN123")
            prev = hr._gofile_website_token("TESTTOKEN123", -1)
        expected = hashlib.sha256(
            (f"{hr.GOFILE_USER_AGENT}::en-US::TESTTOKEN123::124589::"
             f"{hr.GOFILE_WT_SALT}").encode("utf-8")).hexdigest()
        expected_prev = hashlib.sha256(
            (f"{hr.GOFILE_USER_AGENT}::en-US::TESTTOKEN123::124588::"
             f"{hr.GOFILE_WT_SALT}").encode("utf-8")).hexdigest()
        self.assertEqual(token, expected)
        self.assertEqual(prev, expected_prev)
        self.assertEqual(len(token), 64)

    def test_gofile_unwrap_returns_the_picked_video_file(self):
        """Session 103: POST /accounts (guest token) -> GET /contents/<id>
        (website token in the X-Website-Token header) -> auth'd Range
        probe. A video file is picked ahead of a BIGGER non-video file,
        and the probe must carry the Authorization header — the bare link
        302s without it."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True):
            headers = dict(headers or {})
            if url.endswith("/accounts") and method == "POST":
                return (200, json.dumps(
                    {"status": "ok",
                     "data": {"token": "GUEST123"}}).encode(), {}, url)
            if "/contents/" in url:
                self.assertEqual(headers.get("X-Website-Token"),
                                 hr._gofile_website_token("GUEST123"))
                self.assertEqual(headers.get("Authorization"),
                                 "Bearer GUEST123")
                children = {
                    "c1": {"name": "Film.2024.1080p.mkv", "size": 2000000000,
                           "type": "file",
                           "link": "https://cold2.example/dl/abc/Film.mkv"},
                    "c2": {"name": "notes.zip", "size": 3000000000,
                           "type": "file",
                           "link": "https://cold2.example/dl/abc/notes.zip"},
                }
                return (200, json.dumps(
                    {"status": "ok",
                     "data": {"children": children}}).encode(), {}, url)
            # The auth'd Range probe of the picked file.
            self.assertEqual(headers.get("Authorization"), "Bearer GUEST123")
            self.assertIn("Range", headers)
            return (206, b"\x00\x00\x00\x18ftypisom" + b"\x00" * 504,
                    {"content-type": "video/mp4",
                     "content-range": "bytes 0-511/2000000000"}, url)

        verdict = hr.unwrap_gofile("https://gofile.io/d/abc123",
                                   fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(verdict["final_url"],
                         "https://cold2.example/dl/abc/Film.mkv")
        self.assertEqual(verdict["content_type"], "video/mp4")
        self.assertEqual(verdict["http_status"], 206)

    def test_gofile_unwrap_notfound_is_dead(self):
        """A deleted gofile folder answers error-notFound — dead, not a
        gate problem, and the negative cache records it as such."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True):
            if url.endswith("/accounts"):
                return (200, json.dumps(
                    {"status": "ok",
                     "data": {"token": "GUEST123"}}).encode(), {}, url)
            return (200, json.dumps({"status": "error-notFound"}).encode(),
                    {}, url)

        verdict = hr.unwrap_gofile("https://gofile.io/d/deadid",
                                   fetch=fake_fetch)
        self.assertEqual(verdict["status"], "dead", verdict)

    def test_gofile_unwrap_notpremium_on_both_windows_is_unknown(self):
        """error-notPremium on the current window AND the previous one means
        the salt rotated — unknown, with a note naming the constant to
        update, never a forced half-working answer."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True):
            if url.endswith("/accounts"):
                return (200, json.dumps(
                    {"status": "ok",
                     "data": {"token": "GUEST123"}}).encode(), {}, url)
            return (200, json.dumps({"status": "error-notPremium"}).encode(),
                    {}, url)

        verdict = hr.unwrap_gofile("https://gofile.io/d/abc123",
                                   fetch=fake_fetch)
        self.assertEqual(verdict["status"], "unknown", verdict)
        self.assertIn("GOFILE_WT_SALT", " ".join(verdict["notes"]))

    def test_filepress_unwrap_mints_then_probes_active(self):
        """Filepress cracked 2026-11-13: POST downlaod/ (method
        indexDownlaod — the API's own spelling) mints a 24-hex token,
        POST downlaod2/ swaps it for a direct .mkv link, and the Range
        probe of that link is the gate. The minted filename carries raw
        spaces/brackets, so the final URL must be percent-encoded."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            if url.endswith("/api/file/downlaod/") and method == "POST":
                body = json.loads(data.decode("utf-8"))
                self.assertEqual(body["method"], "indexDownlaod")
                self.assertIsNone(body["captchaValue"])
                self.assertEqual(headers.get("Referer"),
                                 "https://new3.filepress.lat")
                return (200, json.dumps(
                    {"status": True, "statusCode": 200,
                     "data": "6ad7ecde69b577b115172142"}).encode(), {}, url)
            if url.endswith("/api/file/downlaod2/") and method == "POST":
                body = json.loads(data.decode("utf-8"))
                self.assertEqual(body["id"], "6ad7ecde69b577b115172142")
                return (200, json.dumps(
                    {"status": True, "statusCode": 200,
                     "data": ["https://aws.flapdoodle.cyou/download/abc123/"
                              "Film (2024) [1080p].mkv"]}).encode(), {}, url)
            self.assertIn("Range", headers or {})
            return (206, b"\x1a\x45\xdf\xa3" + b"\x00" * 508,
                    {"content-type": "video/x-matroska",
                     "content-range": "bytes 0-511/1800000000"}, url)

        verdict = hr.unwrap_filepress(
            "https://new3.filepress.lat/file/6ad7ecde69b577b115172142/",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(verdict["final_url"],
                         "https://aws.flapdoodle.cyou/download/abc123/"
                         "Film%20%282024%29%20%5B1080p%5D.mkv")
        self.assertEqual(verdict["content_type"], "video/x-matroska")
        self.assertEqual(verdict["http_status"], 206)

    def test_filepress_unwrap_522_origin_is_error_never_active(self):
        """The download origin aws.flapdoodle.cyou answers 522 on every
        /download/* path (measured ~50 min, both egresses, 2026-11-13).
        A minted link that cannot be read is an error, never active — the
        gate must refuse it, and the row must not be served."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            if url.endswith("/api/file/downlaod/"):
                return (200, json.dumps(
                    {"status": True, "statusCode": 200,
                     "data": "6ad7ecde69b577b115172142"}).encode(), {}, url)
            if url.endswith("/api/file/downlaod2/"):
                return (200, json.dumps(
                    {"status": True, "statusCode": 200,
                     "data": ["https://aws.flapdoodle.cyou/download/abc123/"
                              "Film.mkv"]}).encode(), {}, url)
            return (522, b"", {"content-type": "text/html"}, url)

        verdict = hr.unwrap_filepress(
            "https://new3.filepress.lat/file/6ad7ecde69b577b115172142/",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "error", verdict)
        self.assertEqual(verdict["http_status"], 522)
        self.assertIn("HTTP 522", " ".join(verdict["notes"]))

    def test_filepress_unwrap_method_hidden_is_unknown(self):
        """METHOD_HIDDEN is the API's misleading name for 'this file is
        not in this mirror's index' — unknown, never dead: the file may
        mint fine from another mirror."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            return (200, json.dumps(
                {"status": False, "statusCode": 404,
                 "data": "METHOD_HIDDEN"}).encode(), {}, url)

        verdict = hr.unwrap_filepress(
            "https://new2.filepress.lat/file/6ad7599b69b577b115024f89/",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "unknown", verdict)
        self.assertIn("METHOD_HIDDEN", " ".join(verdict["notes"]))

    def test_filepress_unwrap_no_file_id_is_unknown(self):
        hr = fast_fetch._embed_resolvers()
        verdict = hr.unwrap_filepress("https://new3.filepress.lat/",
                                      fetch=lambda *a, **k: (404, b"", {}, ""))
        self.assertEqual(verdict["status"], "unknown", verdict)
        self.assertIn("no file id", " ".join(verdict["notes"]))

    def test_filepress_filename_encoding_is_idempotent(self):
        """A raw filename and an already-encoded one must mint the same
        URL — double-encoding (%25) breaks the signature."""
        hr = fast_fetch._embed_resolvers()
        raw = hr._filepress_encode_filename(
            "https://x.cyou/download/abc/Film (2024) [1080p].mkv")
        encoded = hr._filepress_encode_filename(
            "https://x.cyou/download/abc/Film%20%282024%29%20%5B1080p%5D.mkv")
        self.assertEqual(raw, encoded)
        self.assertEqual(raw, "https://x.cyou/download/abc/"
                              "Film%20%282024%29%20%5B1080p%5D.mkv")

    def test_streamtape_rebuild_uses_norobotlink_not_the_decoy(self):
        """Session 103: the raw #ideoooolink div is a decoy (wrong id,
        answers {"status":500}); only the norobotlink/captchalink JS
        rebuilds name the true signed URL. The test page is the live
        page's shape with a short token, and the probe proves the rebuilt
        URL."""
        hr = fast_fetch._embed_resolvers()
        page = """<div id="ideoooolink" style="display:none;">/streamtape.to/get_video?id=aPgd96YGjARfxkqX&expires=1794166028&ip=T1&token=T1</div><span id="captchalink" style="display:none;">/streamtape.to/get_video?id=aPg96YGjARfxkqX&expires=1794166028&ip=T1&token=T1</span><div id="norobotlink" style="display:none;">/streamtape.to/get_video?id=aPg96YGjARfxkqX&expires=1794166028&ip=T1&token=T1</div><script> document.getElementById('ideoooolink').innerHTML = "/streamtape.to/get_video?id=aPg" + ''+ ('xcdd96YGjARfxkqX&expires=1794166028&ip=T1&token=T1').substring(1).substring(2); document.getElementById('captchalink').innerHTML = '//streamtape.to/get_video?id=aP'+ ('defgg96YGjARfxkqX&expires=1794166028&ip=T1&token=T1').substring(4); document.getElementById('norobotlink').innerHTML = '//streamtape.to/get_video?id=aP' + ('xcdg96YGjARfxkqX&expires=1794166028&ip=T1&token=T1').substring(1).substring(2);</script>"""

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True):
            if "get_video" in url:
                return (206, b"\x00\x00\x00\x18ftypisom" + b"\x00" * 504,
                        {"content-type": "video/mp4",
                         "content-range": "bytes 0-511/1401038502"}, url)
            return (200, page.encode(), {}, url)

        verdict = hr.unwrap_streamtape(
            "https://streamtape.to/v/aPg96YGjARfxkqX", fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertIn("id=aPg96YGjARfxkqX", verdict["final_url"])
        self.assertNotIn("aPgd96YGj", verdict["final_url"])

    def test_packer_hls_unwrap_reads_hls2_and_accepts_the_playlist(self):
        """Session 103: one GET, unpack the P.A.C.K.E.R. block with the
        repo's own unpacker, read the hls2 master, Range-probe it with
        Referer. The packer payload here is minimal (two keys) but real —
        the same find_packed_config the live watch-online page goes
        through. An HLS master is playable media, not a failed file."""
        hr = fast_fetch._embed_resolvers()
        page = '''<html><script>eval(function(p,a,c,k,e,d){e=function(c){return c};while(c--)if(k[c])p=p.replace(new RegExp('\\b'+e(c)+'\\b','g'),k[c]);return p}('0={"1":"https://cdn.example/hls/master.m3u8"};',10,2,'var|hls2'.split('|'),0,{}))</script></html>'''
        seen = {}

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True):
            seen[url] = dict(headers or {})
            if "master.m3u8" in url:
                return (206, b"#EXTM3U\n#EXT-X-VERSION:3\n",
                        {"content-type": "application/vnd.apple.mpegurl",
                         "content-range": "bytes 0-511/512"}, url)
            return (200, page.encode(), {}, url)

        verdict = hr.unwrap_packer_hls(
            "https://watch-online.mom/e/r80snwale95i", "stream",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(verdict["final_url"],
                         "https://cdn.example/hls/master.m3u8")
        self.assertIn("mpegurl", verdict["content_type"])
        probe_headers = seen.get("https://cdn.example/hls/master.m3u8") or {}
        self.assertEqual(probe_headers.get("Referer"),
                         "https://watch-online.mom/e/r80snwale95i")

    def test_probe_playlist_or_file_names_dead_and_blocked(self):
        """The playlist-aware probe follows probe_range's own status map
        for the failures, and accepts an HLS master as playable media."""
        hr = fast_fetch._embed_resolvers()

        def _fetch_for(status, body=b"", ctype="video/mp4"):
            def fake(url, headers=None, timeout=25, method="GET",
                     follow=True):
                return (status, body, {"content-type": ctype}, url)
            return fake

        embed = "https://watch-online.mom/e/r80snwale95i"
        dead = hr._probe_playlist_or_file("https://cdn.example/f.m3u8",
                                          _fetch_for(404), embed)
        self.assertEqual(dead["status"], "dead")
        blocked = hr._probe_playlist_or_file("https://cdn.example/f.m3u8",
                                             _fetch_for(403), embed)
        self.assertEqual(blocked["status"], "blocked")
        playlist = hr._probe_playlist_or_file(
            "https://cdn.example/f.m3u8",
            _fetch_for(206, b"#EXTM3U\n", "application/vnd.apple.mpegurl"),
            embed)
        self.assertEqual(playlist["status"], "active")
        self.assertTrue(playlist["is_playlist"])

    def test_resolve_live_source_unwraps_a_mobilejsr_bridge_via_its_direct_mirror(self):
        """Session 103: mobilejsr was import-time only, so its rows always
        answered no_unwrapper even though the bridge page lists mirrors
        that play. The resolver runs the fan-out at resolve time and takes
        the direct-first mirror (pixeldrain ahead of the gofile landing
        page, which is a page URL rather than a direct link)."""
        stored = self._embed_source(
            "moviesmela", "mobilejsr", "https://mobilejsr.com/view/t1GxY4H6Ws")
        mirrors = [
            {"source_name": "GoFile [Cloud]", "service": "gofile",
             "resource_id": "abc", "source_url": "https://gofile.io/d/abc",
             "final_url": "https://gofile.io/d/abc", "is_temporary": 0},
            {"source_name": "PixelDrain [Direct CDN]", "service": "pixeldrain",
             "resource_id": "GS2GF6rq",
             "source_url": "https://pixeldrain.com/api/file/GS2GF6rq",
             "final_url": "https://pixeldrain.com/api/file/GS2GF6rq",
             "is_temporary": 0},
        ]
        with patch.object(fast_fetch, "unwrap_mobilejsr",
                          return_value=mirrors), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://pixeldrain.com/api/file/GS2GF6rq")
        self.assertTrue(res["refreshed"])

    def test_resolve_live_source_mobilejsr_with_only_unwrapped_mirrors_fails_honestly(self):
        """A mobilejsr bridge whose mirrors are all landing pages the gate
        cannot prove (a gofile page URL here) refuses honestly with
        unwrap_failed — the branch ran, it just had nothing playable to
        hand up."""
        stored = self._embed_source(
            "moviesmela", "mobilejsr", "https://mobilejsr.com/view/t1GxY4H6Ws")
        mirrors = [
            {"source_name": "GoFile [Cloud]", "service": "gofile",
             "resource_id": "abc", "source_url": "https://gofile.io/d/abc",
             "final_url": "https://gofile.io/d/abc", "is_temporary": 0},
        ]
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [], "failure": "probe_error"}
        probe = Mock(return_value=failing)
        with patch.object(fast_fetch, "unwrap_mobilejsr",
                          return_value=mirrors), \
             patch.object(fast_fetch, "_stage2_probe", probe):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT last_failed_at, failure_class FROM download_sources "
                "WHERE id = ?", (stored["id"],)).fetchone()
        self.assertIsNotNone(row["last_failed_at"], row)
        self.assertEqual(row["failure_class"], "unwrap_failed", row)

    def test_resolve_live_source_unwraps_a_gofile_folder_to_its_video_file(self):
        """Session 103: gofile cracked (wt API, header form). The
        unwrapper's auth'd Range probe IS the gate evidence — the bare
        direct link 302s without the guest Authorization header, so the
        generic bare probe would fail a proven link. The gate probe is
        stubbed to FAIL here on purpose: success anyway proves the skip."""
        stored = self._embed_source(
            "moviesmela", "gofile", "https://gofile.io/d/abc123")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://cold2.example/dl/abc/Film.2024.1080p.mkv")
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a header-gated link is never permanent")
        self.assertEqual(resolvers.calls,
                         [("gofile", "https://gofile.io/d/abc123", True)])
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT final_url, is_temporary, status FROM download_sources"
                " WHERE id = ?", (stored["id"],)).fetchone()
        self.assertEqual(row["final_url"],
                         "https://cold2.example/dl/abc/Film.2024.1080p.mkv")
        self.assertEqual((row["is_temporary"], row["status"]), (1, "active"))

    def test_resolve_live_source_unwraps_a_filepress_page_to_its_direct_mkv(self):
        """Filepress cracked 2026-11-13 (FileBee downlaod/downlaod2).
        The unwrapper's Range probe IS the gate evidence — the gate
        probe is stubbed to FAIL here on purpose: success anyway proves
        the skip. The minted link is a temporary signed file, never
        permanent."""
        stored = self._embed_source(
            "moviesmela", "filepress",
            "https://new3.filepress.lat/file/6ad7ecde69b577b115172142/")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://aws.flapdoodle.cyou/download/abc123/"
                         "Film.2024.1080p.mkv")
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a minted file link is never permanent")
        self.assertEqual(resolvers.calls,
                         [("filepress",
                           "https://new3.filepress.lat/file/6ad7ecde69b577b115172142/",
                           True)])
        with fast_fetch.get_db() as conn:
            row = conn.execute(
                "SELECT final_url, is_temporary, status FROM download_sources"
                " WHERE id = ?", (stored["id"],)).fetchone()
        self.assertEqual(row["final_url"],
                         "https://aws.flapdoodle.cyou/download/abc123/"
                         "Film.2024.1080p.mkv")
        self.assertEqual((row["is_temporary"], row["status"]), (1, "active"))

    def test_resolve_live_source_unwraps_a_streamtape_embed_to_its_signed_mp4(self):
        """Session 103: streamtape cracked (norobotlink rebuild). The
        unwrapper's bare Range probe already proved the signed get_video
        URL, so it stands as the gate — the gate probe is stubbed to FAIL
        here and success anyway proves the skip."""
        stored = self._embed_source(
            "moviesmela", "streamtape",
            "https://streamtape.to/v/aPg96YGjARfxkqX")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertTrue(res["url"].startswith(
            "https://streamtape.to/get_video?id=abc"), res)
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a signed token is never permanent")
        self.assertEqual(resolvers.calls,
                         [("streamtape",
                           "https://streamtape.to/v/aPg96YGjARfxkqX", True)])

    def test_resolve_live_source_unwraps_a_stream_embed_to_its_hls_master(self):
        """Session 103: the streamwish family cracked (1 GET + unpack +
        hls2 master). The unwrapper's Referer-carrying Range probe already
        proved the playlist, so it stands as the gate — the gate probe is
        stubbed to FAIL here and success anyway proves the skip."""
        stored = self._embed_source(
            "moviesmela", "stream",
            "https://watch-online.mom/e/r80snwale95i")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertTrue(res["url"].endswith("master.m3u8?t=x&s=1&e=129600&f=1"),
                        res)
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a signed token is never permanent")
        self.assertEqual(resolvers.calls,
                         [("packer_hls",
                           "https://watch-online.mom/e/r80snwale95i",
                           "stream", True)])

    def test_resolve_live_source_gofile_download_refuses_a_playlist(self):
        """A gofile folder whose picked file is an m3u8 is a playlist, not
        a file: the watch caller may play it, but the download caller must
        refuse it — the gate verdict built from the unwrapper's own probe
        has to carry the kind, or a playlist would be handed to a download.
        The gate probe is stubbed to fail so the v1 stale fall-through
        cannot mask the refusal with the last-known page URL."""
        stored = self._embed_source(
            "moviesmela", "gofile", "https://gofile.io/d/abc123")
        resolvers = self._FakeResolvers(verdict={
            "status": "active",
            "final_url": "https://cold2.example/dl/abc/Film.m3u8",
            "is_temporary": True, "expires_in": None,
            "content_type": "application/vnd.apple.mpegurl",
            "http_status": 200, "size_bytes": 512})
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"],
                                                 want="download")

        self.assertFalse(res["success"], res)
        self.assertEqual(res["code"], "no_playable_source", res)

    def test_verdict_from_unwrap_maps_playlist_and_file(self):
        """The gate verdict built from an unwrapper's own probe: an m3u8
        master is a playlist (never resumable), an mp4 is a file (resumable
        only on a 206)."""
        playlist = fast_fetch._verdict_from_unwrap({
            "content_type": "application/vnd.apple.mpegurl",
            "final_url": "https://cdn.example/hls/master.m3u8",
            "http_status": 206, "size_bytes": 512})
        self.assertEqual(playlist["kind"], "playlist")
        self.assertTrue(playlist["ok"])
        self.assertFalse(playlist["resumable"])
        self.assertTrue(fast_fetch._stage2_accept(playlist, "watch"))
        self.assertFalse(fast_fetch._stage2_accept(playlist, "download"))
        file_206 = fast_fetch._verdict_from_unwrap({
            "content_type": "video/mp4",
            "final_url": "https://cdn.example/f.mp4",
            "http_status": 206, "size_bytes": 100})
        self.assertEqual(file_206["kind"], "file")
        self.assertTrue(file_206["resumable"])
        self.assertTrue(fast_fetch._stage2_accept(file_206, "download"))
        file_200 = fast_fetch._verdict_from_unwrap({
            "content_type": "video/mp4",
            "final_url": "https://cdn.example/f.mp4",
            "http_status": 200, "size_bytes": 100})
        self.assertFalse(file_200["resumable"])

    # -- Session 104b: uploadflix (generic XFS doFree) -------------------

    _UPLOADFLIX_PAGE = """<html><head><title>Hostel Part II</title></head><body>
<form name="F1" method="POST" action="">
<input type="hidden" name="op" value="download2">
<input type="hidden" name="id" value="yba4err36sxr">
<input type="hidden" name="rand" value="">
<input type="hidden" name="referer" value="">
<input type="hidden" name="method_free" value="">
<input type="hidden" name="method_premium" value="">
</form>
<a rel="nofollow noopener noreferrer" href='https://cloud.secure-storage.top:8080/d/jmdldpaniybu2dju2e57qp5qs5q6px6s64ucn6p5kzwwnwy64wctprlkhvlssxlgisqwj4oo/Hostel Part II (2007) 480p BluRay x264 ESub.mkv'>Download</a>
</body></html>"""

    def test_uploadflix_unwrap_reads_the_dllink_anchor_off_the_file_page(self):
        """Session 104b: the file page already carries the storage-host
        dllink anchor (and the download2 form) — one GET + one Range
        probe. The href carries spaces in the filename, so the whole
        quoted value is read and quoted before requesting; the probe
        answers 206 application/octet-stream with EBML magic, which is
        what makes a Drive-labelled file a video at all."""
        hr = fast_fetch._embed_resolvers()
        seen = {}

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            seen[url] = dict(headers or {})
            if "secure-storage" in url:
                return (206, b"\x1a\x45\xdf\xa3" + b"\x00" * 508,
                        {"content-type": "application/octet-stream",
                         "content-range": "bytes 0-511/2000000000"}, url)
            return (200, self._UPLOADFLIX_PAGE.encode(), {}, url)

        verdict = hr.unwrap_uploadflix(
            "https://dl.uploadflix.com/yba4err36sxr", fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(
            verdict["final_url"],
            "https://cloud.secure-storage.top:8080/d/"
            "jmdldpaniybu2dju2e57qp5qs5q6px6s64ucn6p5kzwwnwy64wctprlkhvlssxlgisqwj4oo/"
            "Hostel%20Part%20II%20(2007)%20480p%20BluRay%20x264%20ESub.mkv")
        self.assertEqual(verdict["content_type"], "application/octet-stream")
        self.assertEqual(verdict["http_status"], 206)
        # The file page already carried the anchor: no form was POSTed.
        probe_headers = seen.get(verdict["final_url"]) or {}
        self.assertIn("Range", probe_headers)

    def test_uploadflix_unwrap_posts_download1_then_download2_when_no_anchor(self):
        """Session 104b: a page that shows the forms first is driven the
        JD way — download1 (method_free set, method_premium dropped),
        then download2 (adblock_detected=0) — and the anchor is read off
        the download2 answer. No countdown is ever slept."""
        hr = fast_fetch._embed_resolvers()
        page1 = """<html><body><form name="F1" method="POST" action="">
<input type="hidden" name="op" value="download1">
<input type="hidden" name="id" value="abc123">
<input type="hidden" name="rand" value="r1">
<input type="hidden" name="referer" value="">
<input type="hidden" name="method_free" value="Free Download">
<input type="hidden" name="method_premium" value="Premium Download">
</form></body></html>"""
        page2 = """<html><body><form name="F1" method="POST" action="">
<input type="hidden" name="op" value="download2">
<input type="hidden" name="id" value="abc123">
<input type="hidden" name="rand" value="r2">
<input type="hidden" name="referer" value="">
<input type="hidden" name="method_free" value="">
<input type="hidden" name="method_premium" value="">
</form></body></html>"""
        posted = []

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            if "secure-storage" in url:
                return (206, b"\x1a\x45\xdf\xa3" + b"\x00" * 508,
                        {"content-type": "application/octet-stream",
                         "content-range": "bytes 0-511/1000"}, url)
            if method == "POST":
                posted.append(urllib.parse.parse_qs(
                    (data or b"").decode()))
                if posted[-1].get("op") == ["download1"]:
                    return (200, page2.encode(), {}, url)
                return (200, self._UPLOADFLIX_PAGE.encode(), {}, url)
            return (200, page1.encode(), {}, url)

        verdict = hr.unwrap_uploadflix(
            "https://dl.uploadflix.com/abc123", fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(len(posted), 2, posted)
        self.assertEqual(posted[0].get("op"), ["download1"])
        self.assertEqual(posted[0].get("method_free"), ["Free Download"])
        self.assertNotIn("method_premium", posted[0])
        self.assertEqual(posted[1].get("op"), ["download2"])
        self.assertEqual(posted[1].get("adblock_detected"), ["0"])

    def test_uploadflix_unwrap_dead_page_is_dead(self):
        """A 404 file page is a deleted file, not a gate problem."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            return (404, b"Not Found", {}, url)

        verdict = hr.unwrap_uploadflix(
            "https://dl.uploadflix.com/gone123", fetch=fake_fetch)
        self.assertEqual(verdict["status"], "dead", verdict)

    def test_uploadflix_unwrap_page_with_no_link_is_unknown(self):
        """A live page with no anchor and no download form names nothing
        playable — unknown, never a guessed URL."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            return (200, b"<html><body>no file here</body></html>", {}, url)

        verdict = hr.unwrap_uploadflix(
            "https://dl.uploadflix.com/abc123", fetch=fake_fetch)
        self.assertEqual(verdict["status"], "unknown", verdict)

    # -- Session 104b: 1xplayer (playlist POST + CSRF key) --------------

    _XPLAYER_PAGE = """<html><body><div id='player-502da1cab1226d7b05937ff9fcc78824'></div>
<script>
   \tlet p3 = {"file":"~0TYfp6afVaCGGUhYCdfCve","hls":0,"translator":"2","key":"bhLGn4gnv84MiFpwHrGCZj-lylZ$MaLiKnqn3UC9uFxx3brsOxrNf1AkeaL$yk7$","movie":"502da1cab1226d7b05937ff9fcc78824","host":"1xcinema.net","kp":"tt4479696"};
   \tvar ppl = new HDVBPlayer(p3);
</script></body></html>"""
    _XPLAYER_MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x268
./360/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=858x358
./480/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x536
./720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x804
./1080/index.m3u8
"""
    _XPLAYER_VARIANT = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXTINF:10.0,
seg-00001.ts
#EXTINF:10.0,
seg-00002.ts
"""

    def test_1xplayer_unwrap_posts_the_playlist_and_probes_the_segment(self):
        """Session 104b: GET the play page, POST /playlist/<file>.txt
        with X-CSRF-TOKEN = the per-load key, fetch the signed master
        (Referer-gated: a bare master GET 404s live), take the highest
        variant, Range-probe its first .ts segment (206 video/mp2t, 0x47
        sync at 0/188). The master URL is the final answer; the segment
        is the proof the video exists behind it."""
        hr = fast_fetch._embed_resolvers()
        master_url = ("https://i-arch-400.example/stream2/i-arch-400/abc/"
                      "tok:1893456000:92.4.95.252:sig:==wTUlUdONEN140U0knTUlUP/"
                      "index.m3u8")
        seen = {}

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            seen[url] = dict(headers or {})
            if "/playlist/" in url and method == "POST":
                self.assertEqual(
                    headers.get("X-CSRF-TOKEN"),
                    "bhLGn4gnv84MiFpwHrGCZj-lylZ$MaLiKnqn3UC9uFxx3brsOxrNf1AkeaL$yk7$")
                self.assertTrue(url.endswith("/playlist/0TYfp6afVaCGGUhYCdfCve.txt"))
                return (200, master_url.encode(),
                        {"content-type": "application/vnd.apple.mpegurl"}, url)
            if url == master_url:
                self.assertEqual(
                    headers.get("Referer"),
                    "https://vd.1xplayer.com/play/ftt4479696?tr=2")
                return (200, self._XPLAYER_MASTER.encode(),
                        {"content-type": "text/html"}, url)
            if url.endswith("/index.m3u8"):
                # Any variant playlist (the unwrapper takes the highest).
                return (200, self._XPLAYER_VARIANT.encode(),
                        {"content-type": "application/vnd.apple.mpegurl"}, url)
            if url.endswith(".ts"):
                self.assertEqual(
                    headers.get("Referer"),
                    "https://vd.1xplayer.com/play/ftt4479696?tr=2")
                body = (b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 187
                        + b"\x47" + b"\x00" * 135)
                return (206, body,
                        {"content-type": "video/mp2t",
                         "content-range": "bytes 0-511/1000000"}, url)
            return (200, self._XPLAYER_PAGE.encode(), {}, url)

        with patch.object(hr.time, "time", return_value=1794117000.0):
            verdict = hr.unwrap_1xplayer(
                "https://vd.1xplayer.com/play/ftt4479696?tr=2",
                fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(verdict["final_url"], master_url)
        # The master URL carries its expiry as :<epoch>: — the resolver
        # records it so a signed token is never served past its life.
        self.assertEqual(verdict["expires_in"], 1893456000 - 1794117000)

    def test_1xplayer_unwrap_dead_page_is_dead(self):
        """The newest 1xplayer row 404s live (file removed) — dead."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            return (404, b"Not Found", {}, url)

        verdict = hr.unwrap_1xplayer(
            "https://vd.1xplayer.com/play/ftt10115562?tr=2",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "dead", verdict)

    def test_1xplayer_unwrap_page_without_p3_is_unknown(self):
        """A play page with no p3 file/key config names nothing to POST."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            return (200, b"<html><body>no player here</body></html>", {}, url)

        verdict = hr.unwrap_1xplayer(
            "https://vd.1xplayer.com/play/ftt4479696?tr=2",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "unknown", verdict)

    # -- Session 104b: MovieBox (signed play API) ------------------------

    _MOVIEBOX_DETAIL = {
        "code": 0, "message": "ok",
        "data": {
            "subject": {
                "subjectId": 7723849637673029968,
                "detailPath": "dhurandhar-hindi-iRsvvgqjzc9",
                "subjectType": 1, "title": "Dhurandhar [Hindi]"},
            "resource": {
                "seasons": [{"se": 0, "maxEp": 0}],
                "source": "fzmovies.cms"}}}
    _MOVIEBOX_PLAY = {
        "code": 0, "message": "ok",
        "data": {
            "streams": [
                {"format": "MP4", "id": "8814953776772696784",
                 "url": "https://bcdnxw.example/bt/aaa.mp4?sign=s1&t=1",
                 "resolutions": "480", "size": "979275210",
                 "duration": 12334, "codecName": "h264",
                 "signCookie": "", "signHeaderKey": "", "vipLocked": False},
                {"format": "MP4", "id": "5793360583714033352",
                 "url": "https://bcdnxw.example/resource/bbb.mp4?sign=s2&t=1",
                 "resolutions": "1080", "size": "3466489425",
                 "duration": 12334, "codecName": "h264",
                 "signCookie": "", "signHeaderKey": "", "vipLocked": False}],
            "freeNum": 999, "limited": False, "dash": [], "hls": [],
            "hasResource": True, "vipLocked": False,
            "playConfig": {"adFree": False, "maxResolution": 480}}}

    def test_moviebox_unwrap_picks_the_highest_free_mp4(self):
        """Session 104b: detail API for the subjectId, play API with
        Referer = the /movies/ player-page URL (the same call from
        /detail/ returns streams:[] live — the Referer is the whole
        discriminator), highest free MP4 wins (1080p on 123moviesfree),
        GET-Range probe of the signed URL. The captured 123moviesfree
        Dhurandhar answer is the fixture."""
        hr = fast_fetch._embed_resolvers()
        seen = {}

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            seen[url] = dict(headers or {})
            if "/wefeed-h5api-bff/detail" in url:
                self.assertIn("detailPath=dhurandhar-hindi-iRsvvgqjzc9", url)
                return (200, json.dumps(self._MOVIEBOX_DETAIL).encode(),
                        {}, url)
            if "/wefeed-h5api-bff/subject/play" in url:
                self.assertIn("subjectId=7723849637673029968", url)
                self.assertEqual(
                    headers.get("Referer"),
                    "https://123moviesfree.club/movies/dhurandhar-hindi-iRsvvgqjzc9"
                    "?id=7723849637673029968&type=/movie/detail&detailSe=&detailEp=&lang=en")
                return (200, json.dumps(self._MOVIEBOX_PLAY).encode(),
                        {}, url)
            if "bbb.mp4" in url:
                self.assertIn("Range", headers)
                return (206, b"\x00\x00\x00\x18ftypisom" + b"\x00" * 504,
                        {"content-type": "video/mp4",
                         "content-range": "bytes 0-511/3466489425"}, url)
            raise AssertionError(f"unexpected fetch: {url}")

        verdict = hr.unwrap_moviebox(
            "https://123moviesfree.club/detail/dhurandhar-hindi-iRsvvgqjzc9",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(verdict["final_url"],
                         "https://bcdnxw.example/resource/bbb.mp4?sign=s2&t=1")
        self.assertEqual(verdict["content_type"], "video/mp4")
        self.assertEqual(verdict["size_bytes"], 3466489425)
        self.assertEqual(
            [item["label"] for item in verdict["sources"]],
            ["480p", "1080p"])

    def test_moviebox_unwrap_all_vip_locked_is_unknown(self):
        """themoviebox's 1080p is vipLocked with an empty URL and its
        DASH needs a signed cookie — when no stream is free, the answer
        is unknown, never a locked URL handed to the player."""
        hr = fast_fetch._embed_resolvers()
        locked = json.loads(json.dumps(self._MOVIEBOX_PLAY))
        for stream in locked["data"]["streams"]:
            stream["vipLocked"] = True
            stream["url"] = ""

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            if "/wefeed-h5api-bff/detail" in url:
                return (200, json.dumps(self._MOVIEBOX_DETAIL).encode(),
                        {}, url)
            return (200, json.dumps(locked).encode(), {}, url)

        verdict = hr.unwrap_moviebox(
            "https://themoviebox.xyz/detail/dhurandhar-hindi-iRsvvgqjzc9",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "unknown", verdict)

    def test_moviebox_unwrap_detail_without_subject_id_is_unknown(self):
        """No subjectId in the detail answer means no play call to make."""
        hr = fast_fetch._embed_resolvers()

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            return (200, json.dumps(
                {"code": 0, "data": {"subject": {}}}).encode(), {}, url)

        verdict = hr.unwrap_moviebox(
            "https://themoviebox.xyz/detail/some-film-abc123",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "unknown", verdict)

    def test_moviebox_unwrap_series_episode_uses_se_and_ep(self):
        """A series detail URL carrying se/ep asks the play API for that
        episode, not the movie default."""
        hr = fast_fetch._embed_resolvers()
        seen = {}

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            seen[url] = dict(headers or {})
            if "/wefeed-h5api-bff/detail" in url:
                return (200, json.dumps(self._MOVIEBOX_DETAIL).encode(),
                        {}, url)
            if "/wefeed-h5api-bff/subject/play" in url:
                self.assertIn("se=1&ep=2", url)
                return (200, json.dumps(self._MOVIEBOX_PLAY).encode(),
                        {}, url)
            return (206, b"\x00\x00\x00\x18ftypisom" + b"\x00" * 504,
                    {"content-type": "video/mp4",
                     "content-range": "bytes 0-511/3466489425"}, url)

        verdict = hr.unwrap_moviebox(
            "https://themoviebox.xyz/detail/covenant-s1-xyz?se=1&ep=2",
            fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)

    # -- Session 104b: dispatch ------------------------------------------

    def test_resolve_live_source_unwraps_an_uploadflix_file_to_its_storage_link(self):
        """Session 104b: uploadflix cracked (generic XFS doFree). The
        catalog stores these rows under two service values — "uploadflix"
        and "dl" (57,845 rows, 52,583 of them dl.uploadflix.com) — so
        the branch matches on the URL markers, and this test uses the
        "dl" service to prove it. The unwrapper's unverified-SSL Range
        probe IS the gate evidence: the gate probe is stubbed to FAIL
        here and success anyway proves the skip."""
        stored = self._embed_source(
            "moviesmela", "dl", "https://dl.uploadflix.com/yba4err36sxr")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(
            res["url"],
            "https://cloud.secure-storage.top:8080/d/abc/Film.mkv")
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a rotating token is never permanent")
        self.assertEqual(resolvers.calls,
                         [("uploadflix",
                           "https://dl.uploadflix.com/yba4err36sxr", True)])

    def test_resolve_live_source_unwraps_a_1xplayer_play_to_its_master(self):
        """Session 104b: 1xplayer cracked (playlist POST + CSRF key).
        The unwrapper's Referer-carrying chain (master + variant +
        segment) already proved the playlist, so it stands as the gate
        — the gate probe is stubbed to FAIL here and success anyway
        proves the skip. A playlist for a download caller is refused
        by the gate verdict's kind, as for the other HLS hosts."""
        stored = self._embed_source(
            "moviesmela", "1xplayer",
            "https://vd.1xplayer.com/play/ftt4479696?tr=2")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(
            res["url"], "https://i-arch-400.example/stream2/index.m3u8")
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a signed master is never permanent")
        self.assertEqual(resolvers.calls,
                         [("1xplayer",
                           "https://vd.1xplayer.com/play/ftt4479696?tr=2",
                           True)])

    def test_resolve_live_source_unwraps_a_moviebox_detail_to_its_signed_mp4(self):
        """Session 104b: MovieBox cracked (signed play API). The
        unwrapper's GET-Range probe of the picked signed MP4 IS the gate
        evidence — the gate probe is stubbed to FAIL here and success
        anyway proves the skip. The live catalog holds 0 such rows
        today; this proves the dispatch, the live site is proven by
        the fixture harness."""
        stored = self._embed_source(
            "moviesmela", "themoviebox",
            "https://123moviesfree.club/detail/dhurandhar-hindi-iRsvvgqjzc9")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(
            res["url"], "https://bcdnxw.example/bt/abc.mp4?sign=x&t=1")
        self.assertTrue(res["refreshed"])
        self.assertTrue(res["is_temporary"], "a signed URL is never permanent")
        self.assertEqual(resolvers.calls,
                         [("moviebox",
                           "https://123moviesfree.club/detail/dhurandhar-hindi-iRsvvgqjzc9",
                           True)])

    @staticmethod
    def _voe_encode(data):
        """Encode a payload the way VOE's page does, so the decode can be
        tested without the live site: b64 the JSON, reverse, shift every
        char +3, b64 again, insert the LUT characters, inverse-ROT the
        letters. The LUT entries are two non-word characters each, which
        is what the loader-script regex matches."""
        raw = json.dumps(data, separators=(",", ":"))
        step = base64.b64encode(raw.encode()).decode()[::-1]
        step = "".join(chr(ord(c) + 3) for c in step)
        step = base64.b64encode(step.encode()).decode()
        text = step[:5] + "@#" + step[5:10] + "~!" + step[10:]
        out = []
        for ch in text:
            x = ord(ch)
            if 65 <= x <= 90:
                x = (x - 78) % 26 + 65
            elif 97 <= x <= 122:
                x = (x - 110) % 26 + 97
            out.append(chr(x))
        return "".join(out), "['@#','~!']"

    def test_voe_decode_round_trips_a_known_payload(self):
        """Session 103: VOE's obfuscation is pure stdlib (re + base64 +
        json) — the decode must invert the encode exactly, or the live
        payload decodes to garbage."""
        hr = fast_fetch._embed_resolvers()
        data = {"source": "https://cdn.example/hls/master.m3u8",
                "fallback": "https://cdn.example/f.mp4"}
        code, luts = self._voe_encode(data)
        self.assertEqual(hr.voe_decode(code, luts), data)

    def test_voe_unwrap_decodes_the_payload_and_accepts_the_playlist(self):
        """Session 103: the voe.sx page is a JS redirect to the mirror;
        the mirror page carries the obfuscated payload plus the loader
        script with the LUTs; the decoded source is an HLS master that
        Range-probes 206 mpegurl. Three requests, no browser."""
        hr = fast_fetch._embed_resolvers()
        data = {"source": "https://cdn.example/hls/master.m3u8",
                "fallback": "https://cdn.example/f.mp4"}
        code, luts = self._voe_encode(data)
        mirror = ("https://shannoncoldalready.example/e/n15ncgjxnnbx")
        page = ('<html><script type="application/json">["' + code
                + '"]</script><script src="/js/loader.test.js">'
                '</script></html>')
        seen = {}

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True):
            seen[url] = dict(headers or {})
            if url == "https://voe.sx/n15ncgjxnnbx":
                return (200, ("<script>window.location.href = '"
                              + mirror + "';</script>").encode(),
                        {}, url)
            if url == mirror:
                return (200, page.encode(), {}, url)
            if url.endswith("/js/loader.test.js"):
                return (200, ("var x = " + luts + ";").encode(), {}, url)
            if "master.m3u8" in url:
                return (206, b"#EXTM3U\n#EXT-X-VERSION:3\n",
                        {"content-type": "application/vnd.apple.mpegurl",
                         "content-range": "bytes 0-0/281"}, url)
            return (404, b"", {}, url)

        verdict = hr.unwrap_voe("https://voe.sx/n15ncgjxnnbx",
                                fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(verdict["final_url"],
                         "https://cdn.example/hls/master.m3u8")
        self.assertIn("mpegurl", verdict["content_type"])
        self.assertIn(mirror, seen)
        probe_headers = seen.get("https://cdn.example/hls/master.m3u8") or {}
        self.assertEqual(probe_headers.get("Referer"), mirror)

    def test_resolve_live_source_unwraps_a_voe_embed_to_its_hls_master(self):
        """Session 103: a voe row resolves through unwrap_voe; the gate
        probe is stubbed to FAIL on purpose — success anyway proves the
        unwrapper's own verified probe stands as the gate."""
        stored = self._embed_source(
            "moviesmela", "voe", "https://voe.sx/n15ncgjxnnbx")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/hls/master.m3u8")
        self.assertEqual(resolvers.calls[0][0], "voe")

    def test_vidhide_unwrap_follows_the_chain_to_the_hls_master(self):
        """Session 103: the embed page carries the sid, the helper POST
        names the hanerix page, the hanerix page carries the packer block
        with the hls2 master. Five requests, no browser — the fake fetch
        plays all four hops plus the Range probe."""
        hr = fast_fetch._embed_resolvers()
        mresult = base64.b64encode(
            json.dumps({"smwh": "37m6yf9fwmt2"}).encode()).decode()
        helper = json.dumps({
            "sources": {"smwh": {"siteUrl": "https://hanerix.com/e/"}},
            "mresult": mresult})
        svid = ('<html><script>const sid = "su9ss0k";</script></html>')
        packer = '''<html><script>eval(function(p,a,c,k,e,d){e=function(c){return c};while(c--)if(k[c])p=p.replace(new RegExp('\\b'+e(c)+'\\b','g'),k[c]);return p}('0={"1":"https://cdn.example/hls/master.m3u8"};',10,2,'var|hls2'.split('|'),0,{}))</script></html>'''
        seen = {}

        def fake_fetch(url, headers=None, timeout=25, method="GET",
                       follow=True, data=None):
            seen[url] = (method, dict(headers or {}))
            if url == "https://filesforever.link/embed/su9ss0k":
                return (200, svid.encode(), {}, url)
            if url == "https://pro.iqsmartgames.com/embedhelper2.php":
                self.assertEqual(method, "POST")
                self.assertIn(b"sid=su9ss0k", data or b"")
                return (200, helper.encode(), {}, url)
            if url == "https://hanerix.com/e/37m6yf9fwmt2":
                return (200, packer.encode(), {}, url)
            if "master.m3u8" in url:
                return (206, b"#EXTM3U\n#EXT-X-VERSION:3\n",
                        {"content-type": "application/vnd.apple.mpegurl",
                         "content-range": "bytes 0-0/281"}, url)
            return (404, b"", {}, url)

        verdict = hr.unwrap_vidhide(
            "https://filesforever.link/embed/su9ss0k", fetch=fake_fetch)
        self.assertEqual(verdict["status"], "active", verdict)
        self.assertEqual(verdict["final_url"],
                         "https://cdn.example/hls/master.m3u8")
        self.assertIn("mpegurl", verdict["content_type"])
        self.assertIn("https://hanerix.com/e/37m6yf9fwmt2", seen)
        probe_headers = seen.get(
            "https://cdn.example/hls/master.m3u8", (None, {}))[1]
        self.assertEqual(probe_headers.get("Referer"),
                         "https://hanerix.com/e/37m6yf9fwmt2")

    def test_resolve_live_source_unwraps_a_vidhide_embed_to_its_hls_master(self):
        """Session 103: a vidhide row resolves through unwrap_vidhide;
        the gate probe is stubbed to FAIL on purpose — success anyway
        proves the unwrapper's own verified probe stands as the gate."""
        stored = self._embed_source(
            "moviesmela", "vidhide",
            "https://filesforever.link/embed/su9ss0k")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/hls/master.m3u8")
        self.assertEqual(resolvers.calls[0][0], "vidhide")

    def test_resolve_live_source_routes_a_vidmoly_embed_to_the_packer_unwrapper(self):
        """Session 103: vidmoly has 0 rows in the catalog, so it is wired
        but unproven live — this test proves only the routing: a vidmoly
        row reaches the packer unwrapper with the vidmoly service label,
        and the verified verdict serves."""
        stored = self._embed_source(
            "moviesmela", "vidmoly",
            "https://vidmoly.net/embed-abc123.html")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://cdn.example/hls2/01/1/f/master.m3u8"
                         "?t=x&s=1&e=129600&f=1", res)
        packer_calls = [c for c in resolvers.calls if c[0] == "packer_hls"]
        self.assertEqual(len(packer_calls), 1, resolvers.calls)
        self.assertEqual(packer_calls[0][2], "vidmoly")

    def test_resolve_live_source_routes_a_hubcloud_row_to_the_new_hubcloud_unwrapper(self):
        """Phase C item 4: a hubcloud drive row reaches unwrap_hubcloud
        (not the old inline drive list), and the unwrapper's own Range
        probe IS the gate evidence — the Stage-2 probe is stubbed to fail
        and success anyway proves the skip."""
        stored = self._embed_source(
            "moviesmela", "hubcloud",
            "https://hubcloud.ist/drive/test12345")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://fresh.r2.cloudflarestorage.com/new_token")
        self.assertEqual(resolvers.calls, [("hubcloud",
                                            "https://hubcloud.ist/drive/test12345",
                                            True)])

    def test_resolve_live_source_routes_an_hglink_row_to_the_new_streamwish_unwrapper(self):
        """Phase C item 4: an hglink.to loader row reaches unwrap_streamwish,
        NOT the packer below it — the packer only keeps the embed shapes
        (watch-online, embedwish, vidmoly, streamwish /e/)."""
        stored = self._embed_source(
            "moviesmela", "streamwish",
            "https://hglink.to/g70gj3eith1c")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/streamwish/master.m3u8")
        self.assertEqual(resolvers.calls, [("streamwish",
                                            "https://hglink.to/g70gj3eith1c",
                                            True)])

    def test_resolve_live_source_routes_a_vidout_row_to_the_new_vidout_unwrapper(self):
        """Phase C item 4: a vidout page row reaches unwrap_vidout — the
        service had no serve branch at all before item 3, so it used to
        answer no_unwrapper."""
        stored = self._embed_source(
            "moviesmela", "vidout",
            "https://vidout.pages.dev/movie/tt12683756")
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/vidout/master.m3u8")
        self.assertEqual(resolvers.calls, [("vidout",
                                            "https://vidout.pages.dev/movie/tt12683756",
                                            True)])

    def test_resolve_live_source_routes_a_vidbolt_pro_row_to_the_vidbolt_unwrapper(self):
        """Session 112 (D2.5): vidbolt.pro is not a Stage-1 host
        (current_hosts claims vidbolt.xyz only), so the row reaches the
        vidbolt branch; the verified verdict serves even though the
        Stage-2 probe is stubbed to fail."""
        embed = "https://vidbolt.pro/movie/550"
        stored = self._embed_source("moviesmela", "vidbolt", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/vidbolt/stream.m3u8")
        self.assertEqual(resolvers.calls, [("vidbolt", embed, True)])

    def test_resolve_live_source_routes_a_vibuxer_mirror_row_to_the_vibuxer_unwrapper(self):
        """Session 112 (D2.5): the catalog tags vibuxer rows
        vibuxer-mirror/vibuxermirror, never "vibuxer" — the branch
        matches that label. vibuxer.com is a Stage-1 host, so the
        branch is reached here only on the Stage-1 import-failure
        path (sys.modules holds None for current_hosts); that is the
        branch's production reachability for vibuxer.com rows, and
        the test proves exactly it."""
        embed = "https://vibuxer.com/e/i4p45adamelv"
        stored = self._embed_source("moviesmela", "vibuxer-mirror", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.dict(sys.modules, {"current_hosts": None}):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/vibuxer/master.m3u8")
        self.assertEqual(resolvers.calls, [("vibuxer", embed, True)])

    def test_resolve_live_source_routes_a_vidrift_net_row_to_the_vidrift_unwrapper(self):
        """Session 112 (D2.5): vidrift.net (bare host) is not a Stage-1
        host (current_hosts claims embed.vidrift.net only), so the row
        reaches the vidrift branch; the verified verdict serves even
        though the Stage-2 probe is stubbed to fail."""
        embed = "https://vidrift.net/embed/movie/550"
        stored = self._embed_source("moviesmela", "vidrift", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/vidrift/master.m3u8")
        self.assertEqual(resolvers.calls, [("vidrift", embed, True)])

    def test_resolve_live_source_routes_an_iqsmart_row_to_the_iqsmart_unwrapper(self):
        """Session 112 (D2.5): the bare iqsmartgames.com host is not a
        Stage-1 host (current_hosts claims streams.iqsmartgames.com
        only, as streamhg), so the row reaches the iqsmart branch;
        the verified verdict serves even though the Stage-2 probe is
        stubbed to fail."""
        embed = "https://iqsmartgames.com/embed/movie/tt35786199?key=mykey"
        stored = self._embed_source("moviesmela", "iqsmart", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/iqsmart/master.m3u8")
        self.assertEqual(resolvers.calls, [("iqsmart", embed, True)])

    def test_resolve_live_source_routes_a_filmu_in_row_to_the_filmu_unwrapper(self):
        """Session 112 (D2.5): filmu.in (bare host) is not a Stage-1
        host (current_hosts claims embed.filmu.in and vidly.pro only,
        as vidly), so the row reaches the filmu branch; the verified
        verdict serves even though the Stage-2 probe is stubbed to
        fail."""
        embed = "https://filmu.in/movie/550"
        stored = self._embed_source("moviesmela", "filmu", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/filmu/master.m3u8")
        self.assertEqual(resolvers.calls, [("filmu", embed, True)])

    def test_resolve_live_source_routes_a_cineverse_row_to_the_cineverse_unwrapper(self):
        """Session 112 (D2.5): a cineverse.* host is not a Stage-1 host
        (current_hosts claims modiplay hosts only), so the row reaches
        the cineverse branch; the verified verdict serves even though
        the Stage-2 probe is stubbed to fail."""
        embed = "https://cineverse.tv/embed/tmdb/movie?id=550"
        stored = self._embed_source("moviesmela", "cineverse", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/cineverse/master.m3u8")
        self.assertEqual(resolvers.calls, [("cineverse", embed, True)])

    def test_resolve_live_source_routes_a_castle_row_to_the_castle_unwrapper(self):
        """Session newsites-batch1: a bulwik.com page is not a Stage-1
        host, so the row reaches the castle branch; the verified verdict
        serves even though the Stage-2 probe is stubbed to fail — the
        stored signed URL is never served, the unwrapper re-extracts a
        fresh signature from the live page on every press."""
        embed = "https://www.bulwik.com/movie/all-pass/10285268178004214"
        stored = self._embed_source("castle", "castle", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://img01.tlnob.example/video/abc/index_401.m3u8")
        self.assertEqual(resolvers.calls, [("castle", embed, True)])

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

    def test_resolve_live_source_serves_a_pkembed_embed_even_when_the_bare_gate_probe_fails(self):
        """Session 119 (D2.5 probe): the pkembed unwrapper's Range probe
        IS the gate evidence — the vkpluscdn plus2 node 403s a bare
        re-probe (bare Mozilla/5.0 UA), so the branch sets
        _gate_from_verdict and the verified verdict serves even though
        the Stage-2 probe is stubbed to fail. Without the flag this test
        fails: the bare probe kills a proven link."""
        embed = "https://pkembed.site/embed-g64v61whic26.html"
        stored = self._embed_source("moviesmela", "pkembed", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://cdn.pkembed.example/1000042_g64v61whic26_l.mp4")
        self.assertEqual(resolvers.calls, [("pkembed", embed, True)])

    def test_resolve_live_source_serves_an_mxdrop_embed_even_when_the_bare_gate_probe_fails(self):
        """Session 119 (D2.5 probe): same gate as pkembed — the mxcontent
        CDN 403s a bare re-probe, so the mxdrop branch sets
        _gate_from_verdict and the verified verdict serves even though
        the Stage-2 probe is stubbed to fail."""
        embed = "https://mxdrop.to/e/6d9c9f6d93dfb18063cbdb697dd4db5d"
        stored = self._embed_source("moviesmela", "mxdrop", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        with patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.mxdrop.example/f.mp4")
        self.assertEqual(resolvers.calls, [("mxdrop", embed, True)])

    def test_resolve_live_source_falls_through_to_the_filmu_unwrapper_when_stage1_vidly_fails(self):
        """Session 119 (D2.5 probe): Stage-1 vidly fails (blocked) on a
        vidly.pro row, but the Session 112 unwrap_filmu works — so the
        dispatcher falls through to the filmu branch instead of refusing
        the copy. The verified verdict serves even though the Stage-2
        probe is stubbed to fail (the branch already gates from verdict)."""
        embed = "https://vidly.pro/embed/movie/550"
        stored = self._embed_source("moviesmela", "filmu", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        stage1_fail = {"ok": False, "backend": "vidly", "failure": "blocked"}
        resolve_copy = Mock(return_value=stage1_fail)

        def classify_side_effect(url, *args, **_kw):
            return "vidly" if "vidly" in url else "unknown"

        with patch.object(current_hosts, "classify_backend",
                          side_effect=classify_side_effect), \
             patch.object(current_hosts, "resolve_copy", resolve_copy), \
             patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"], "https://cdn.example/filmu/master.m3u8")
        self.assertEqual(resolvers.calls, [("filmu", embed, True)])

    def test_resolve_live_source_falls_through_to_the_cineverse_unwrapper_when_stage1_modiplay_fails(self):
        """Session 119 (D2.5 probe): Stage-1 modiplay fails
        (shell_unverified) on a modiplay row, but the Session 112
        unwrap_cineverse works — so the dispatcher falls through to
        the cineverse branch instead of refusing the copy."""
        embed = "https://modiplay.site/embed/550"
        stored = self._embed_source("moviesmela", "cineverse", embed)
        resolvers = self._FakeResolvers()
        failing = {"ok": False, "kind": None, "mime": None, "size": None,
                   "resumable": False, "renditions": [],
                   "failure": "probe_error"}
        stage1_fail = {"ok": False, "backend": "modiplay",
                       "failure": "shell_unverified"}
        resolve_copy = Mock(return_value=stage1_fail)

        def classify_side_effect(url, *args, **_kw):
            return "modiplay" if "modiplay" in url else "unknown"

        with patch.object(current_hosts, "classify_backend",
                          side_effect=classify_side_effect), \
             patch.object(current_hosts, "resolve_copy", resolve_copy), \
             patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "_stage2_probe",
                          return_value=failing), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://cdn.example/cineverse/master.m3u8")
        self.assertEqual(resolvers.calls, [("cineverse", embed, True)])

    def test_stage1_success_never_falls_through_to_the_legacy_branches(self):
        """Session 119: the fall-through runs ONLY on a Stage-1 failure.
        When Stage-1 vidly succeeds, the Stage-1 URL is served and the
        filmu unwrapper is never called."""
        embed = "https://vidly.pro/embed/movie/550"
        stored = self._embed_source("moviesmela", "filmu", embed)
        resolvers = self._FakeResolvers()
        stage1_ok = {"ok": True, "backend": "vidly",
                     "url": "https://stage1.example/filmu/master.m3u8",
                     "temporary": False, "mime": "application/vnd.apple.mpegurl",
                     "kind": "playlist"}
        resolve_copy = Mock(return_value=stage1_ok)

        def classify_side_effect(url, *args, **_kw):
            return "vidly" if "vidly" in url else "unknown"

        with patch.object(current_hosts, "classify_backend",
                          side_effect=classify_side_effect), \
             patch.object(current_hosts, "resolve_copy", resolve_copy), \
             patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers), \
             patch.object(fast_fetch, "probe_url_ttl",
                          return_value=(None, {"observed": False,
                                               "reason": "no_directive"})):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertTrue(res["success"], res)
        self.assertEqual(res["url"],
                         "https://stage1.example/filmu/master.m3u8")
        self.assertEqual(resolvers.calls, [],
                         "a Stage-1 pass must not call the legacy branch")

    def test_a_fresh_negative_cache_record_keeps_a_stage1_row_off_the_legacy_branches(self):
        """Session 119: a fresh negative-cache record means this copy
        stays skipped — the sibling ladder decides, and the legacy
        filmu branch must not re-probe it. (The fall-through is for a
        Stage-1 failure on a fresh press, not for a copy that already
        failed at the current resolver version.)"""
        embed = "https://vidly.pro/embed/movie/550"
        stored = self._embed_source("moviesmela", "filmu", embed)
        with fast_fetch.get_db() as conn:
            conn.execute(
                "UPDATE download_sources SET last_failed_at = ?, "
                "failure_class = 'unwrap_failed', failure_resolver_v = ? "
                "WHERE id = ?",
                (time.time(), fast_fetch.RESOLVER_VERSION, stored["id"]))
        resolvers = self._FakeResolvers()
        resolve_copy = Mock(return_value={"ok": False, "backend": "vidly",
                                          "failure": "blocked"})

        def classify_side_effect(url, *args, **_kw):
            return "vidly" if "vidly" in url else "unknown"

        with patch.object(current_hosts, "classify_backend",
                          side_effect=classify_side_effect), \
             patch.object(current_hosts, "resolve_copy", resolve_copy), \
             patch.object(fast_fetch, "_embed_resolvers",
                          return_value=resolvers):
            res = fast_fetch.resolve_live_source(stored["id"])

        self.assertFalse(res["success"], res)
        self.assertEqual(resolvers.calls, [],
                         "a cache-failed copy must not be re-unwrapped")
        self.assertEqual(resolve_copy.call_count, 0,
                         "Stage-1 must not re-probe a cache-failed copy")

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
            # No work row, no runtime: the detail carries no invented number.
            self.assertNotIn("runtime_minutes", detail)

    def test_api_v1_query_matches_an_actor_in_cast_names(self):
        """The omnibox matches actors: a query naming an actor finds the films
        whose scraped cast list carries the name, the same way a title does —
        and a title with no cast simply has nothing to match on."""
        with_cast = self.media("site_a", "https://site-a.example/film-one/",
                               title="Film One (2024)", clean_title="Film One")
        with_cast["cast_names"] = "Shah Rukh Khan, Kajol"
        fast_fetch.save_scraped_data(with_cast)
        other = self.media("site_b", "https://site-b.example/film-two/",
                           title="Film Two (2024)", clean_title="Film Two")
        other["cast_names"] = "Aamir Khan"
        fast_fetch.save_scraped_data(other)
        no_cast = self.media("site_c", "https://site-c.example/film-three/",
                             title="Film Three (2024)", clean_title="Film Three")
        fast_fetch.save_scraped_data(no_cast)
        with patch.object(viewer, "DB_PATH", self.db_path):
            by_actor = viewer.api_v1_get_posts(query="Shah Rukh Khan", limit=10)
            self.assertEqual(by_actor["total"], 1)
            self.assertEqual(by_actor["results"][0]["clean_title"], "Film One")
            self.assertFalse(by_actor["fuzzy"])
            by_surname = viewer.api_v1_get_posts(query="Khan", limit=10)
            self.assertEqual(by_surname["total"], 2)
            # The detail carries the stored cast list; the list row never
            # renders cast, so the list select does not fetch it.
            detail = viewer.api_v1_get_post_detail(by_actor["results"][0]["id"])
            self.assertEqual(detail["cast_names"], "Shah Rukh Khan, Kajol")

    def test_api_v1_detail_carries_runtime_from_the_work_row(self):
        post_id = fast_fetch.save_scraped_data(
            self.media("site_a", "https://site-a.example/example-film/", imdb_id="tt9999999")
        )
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cat_works "
            "(work_key TEXT PRIMARY KEY, runtime_minutes INTEGER)")
        conn.execute(
            "INSERT INTO cat_works VALUES (?, ?)", ("imdb:tt9999999", 142))
        conn.commit()
        conn.close()
        with patch.object(viewer, "DB_PATH", self.db_path):
            detail = viewer.api_v1_get_post_detail(post_id)
            self.assertEqual(detail["runtime_minutes"], 142)

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

    def test_api_v1_list_defaults_to_newest_first(self):
        """Session 115: the list walks down through time — 2026, then 2025,
        2024, ... — with rows that carry no usable year last, never first.
        The default and the explicit `sort=newest` agree, and the old sorts
        keep their own orders (title alphabetical, trending by counts)."""
        seed = [
            ("Zulu 2026", 2026), ("Alpha 2025", 2025), ("Mike 2000", 2000),
            ("Kilo 1999", 1999), ("NoYear", None), ("ZeroYear", 0),
            ("Junk 2099", 2099),
        ]
        for title, year in seed:
            fast_fetch.save_scraped_data(
                self.media("site_a", f"https://site-a.example/{title.lower()}/",
                           title=f"{title} ({year})" if year else title,
                           clean_title=title, year=year))

        with patch.object(viewer, "DB_PATH", self.db_path):
            default = viewer.api_v1_get_posts(limit=10)["results"]
            self.assertEqual(len(default), 7)
            self.assertEqual([r["year"] for r in default[:4]],
                             [2026, 2025, 2000, 1999])
            self.assertEqual({r["year"] for r in default[4:]},
                             {None, 0, 2099})

            newest = viewer.api_v1_get_posts(limit=10, sort="newest")["results"]
            self.assertEqual([r["clean_title"] for r in newest],
                             [r["clean_title"] for r in default])

            titled = viewer.api_v1_get_posts(limit=10, sort="title")["results"]
            self.assertEqual(
                [r["clean_title"] for r in titled],
                ["Alpha 2025", "Junk 2099", "Kilo 1999", "Mike 2000",
                 "NoYear", "ZeroYear", "Zulu 2026"])

            # One release and one source each, so trending ties everywhere
            # and falls back to id DESC — the reverse of the seed order.
            trending = viewer.api_v1_get_posts(limit=10, sort="trending")["results"]
            self.assertEqual(
                [r["clean_title"] for r in trending],
                [title for title, _ in reversed(seed)])

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
        # A genuinely adult row, flagged by a strong studio token. The bare "Vixen"
        # this fixture used to rely on is now a suggestion-tier word (there is a 2017
        # action film called *Vixen*), so a single suggestion may no longer hide a work;
        # the studio prefix is what makes this row adult under the revised law.
        adult_id = self.save(
            title="Tushy Vixen Desires (2024)",
            clean_title="Tushy Vixen Desires",
            url="https://site-a.example/tushy-vixen-desires/",
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


class AdultPatternSplitDecisionTests(unittest.TestCase):
    """The 2026-10-29 decision, and the method behind it.

    Four contested bare words were judged by sampling ~a dozen live rows each, not by the
    dictionary: `adult` (10/12 real studio releases) and `naughty` (13/14 real) stay;
    `hunters` (0/12) and `rabbit` (0/12) are removed — every hit was a mainstream title.
    `xxx`/`blacked`/`vixen` became suggestion-tier: one word may never hide a work alone.
    See Fast_Fetch/AGENTS.md §6b."""

    def test_removed_tokens_are_absent_from_the_strong_list(self):
        joined = " ".join(fast_fetch.ADULT_TITLE_PATTERNS).lower()
        self.assertNotIn("hunters", joined)
        self.assertNotIn("rabbit", joined)

    def test_kept_tokens_are_present_in_the_strong_list(self):
        joined = " ".join(fast_fetch.ADULT_TITLE_PATTERNS).lower()
        self.assertIn("adult", joined)
        self.assertIn("naughty", joined)

    def test_mainstream_works_the_removed_tokens_were_hiding_are_clean(self):
        for title in (
            "KPop Demon Hunters", "KPop Demon Hunters Sing-Along",
            "Wallace & Gromit Curse of the Were-Rabbit", "1001 Rabbit Tales",
            "Rabbit School", "Transformers Prime Beast Hunters",
            "Holy Night Demon Hunters", "Peter Rabbit", "Jojo Rabbit",
        ):
            self.assertEqual(fast_fetch.is_adult_title(title), 0, title)

    def test_word_boundary_anchors_are_not_loosened(self):
        # \badult\b fires on the singular studio word but must not fire on a plural title.
        self.assertEqual(fast_fetch.is_adult_title("Adult Short Film 1 (2024)"), 1)
        self.assertEqual(fast_fetch.is_adult_title("Adults"), 0)

    def test_naughty_and_adult_still_flag(self):
        self.assertEqual(fast_fetch.is_adult_title("Naughty Office (2019)"), 1)
        self.assertEqual(fast_fetch.is_adult_title("TeamSkeet Adult Short Film"), 1)

    def test_suggestion_token_alone_does_not_hide_a_mainstream_work(self):
        self.assertEqual(fast_fetch.is_adult_title("Vixen (2017)"), 0)
        self.assertEqual(fast_fetch.is_adult_title("xXx Return of Xander Cage"), 0)
        self.assertEqual(fast_fetch.is_adult_title("Blacked Out (2010)"), 0)

    def test_two_independent_suggestions_corroborate(self):
        self.assertEqual(fast_fetch.is_adult_title("Vixen Blacked Diaries"), 1)

    def test_adult_source_site_authority_is_xprimehub_missav_and_javmost(self):
        # Owner-approved 2026-11-08 (Session 104): xprimehub.pics brands its whole
        # catalog 18+ in its own site title, the owner verified it live, and the VM
        # probe found every sampled post adult — the first host to reach whole-catalog
        # adult authority (previous max measured 36.25% on 10xflix). Missav joined
        # 2026-11-11 (owner-approved): a JAV-only tube, 100% adult by catalog.
        # Javmost joined 2026-11-11 (owner-approved): a JAV-only tube, the one
        # JAV site that loads from a real browser (MissAV and SupJav are
        # Cloudflare-walled even there). The pin is exact: provenance alone
        # hides nothing from any other site.
        self.assertEqual(fast_fetch.ADULT_SOURCE_SITES,
                         frozenset({"xprimehub", "missav", "javmost"}))
        self.assertEqual(fast_fetch.site_implies_adult("xprimehub"), 1)
        self.assertEqual(fast_fetch.site_implies_adult("missav"), 1)
        self.assertEqual(fast_fetch.site_implies_adult("javmost"), 1)
        self.assertEqual(fast_fetch.site_implies_adult("10xflix"), 0)
        self.assertEqual(fast_fetch.site_implies_adult(None), 0)

    def test_no_removed_token_survives_in_any_adult_list_in_the_tree(self):
        """hunters/rabbit were copied into per-site scrapers too; the AST sweep proves the
        removal is whole-tree, not just the engine list."""
        root = Path(fast_fetch.__file__).resolve().parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not any(isinstance(t, ast.Name) and "adult" in t.id.lower()
                           for t in targets):
                    continue
                if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    continue
                for element in node.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str):
                        low = element.value.lower()
                        for word in ("hunters", "rabbit"):
                            if word in low:
                                offenders.append(
                                    f"{path.relative_to(root)}: {element.value!r} -> {word}")
        self.assertEqual(offenders, [],
                         "a mainstream word survived in an adult list and still hides works: "
                         + "; ".join(offenders))


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


class AdultVersionWordFalsePositiveTests(unittest.TestCase):
    """A *version* of a film is not a kind of film, and the key law makes that loud.

    Measured read-only against production on 2026-10-29: of the 15,068 rows carrying
    `is_18_plus=1`, **7,663 (51%) were justified only by `\\buncut\\b` or `\\bunrated\\b`**
    in their own stored text. They are mainstream Indian cinema — Kanguva, Hi Nanna,
    Guntur Kaaram, Junior, Dharmaveer 2, Gangs of Godavari, Election — because
    desicinemas stamps "Uncut" on its releases the way other sites stamp "HDRip".

    Two words hid them, and the key-level law turned each one into a whole work:
    `inherit_key_adult()` propagates a flag to every row sharing a `canonical_key`, so
    one misflagged sibling buries every copy. When the backfill ran, 407 of the 455
    rows it flipped were this false positive and had to be reversed by hand.

    So a pattern list that feeds a key-level rule needs BOTH directions pinned: the
    version word must not flag on its own, and a real adult marker must still flag when
    the same page also says "Uncut". Removing the words without the second half would
    be a silent downgrade of the adult rule.
    """

    #: The edition vocabulary — what `release_descriptor.py` and `catalog_api.py`
    #: already file these under. Describing a cut is not describing an audience.
    VERSION_WORDS = frozenset({
        "uncut", "unrated", "extended", "remastered", "remaster", "restored",
        "restoration", "imax", "theatrical", "fanedit", "fansub", "cut",
    })

    #: Regex punctuation, so `r"\buncut\b"` yields the word "uncut" and not "buncut":
    #: a backslash is not a letter, so `[a-z]+` alone runs the boundary marker `b`
    #: straight into the word it bounds.
    _REGEX_PUNCTUATION = re.compile(r"\\.|[^\w\s]")

    def version_words_in(self, entry: str) -> set:
        return set(re.findall(
            r"[a-z]+", self._REGEX_PUNCTUATION.sub(" ", entry.lower()))) & self.VERSION_WORDS

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

    def insert_legacy(self, *, url, key, clean_title="Kanguva", year=2024,
                      site="site_a", flagged=0, title=None):
        """A row already in the ledger, written before this rule existed."""
        with fast_fetch.get_db() as conn:
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, url.rstrip("/").split("/")[-1],
                 title or f"{clean_title} ({year})", clean_title, year, "movie",
                 site, flagged, key))

    def flag(self, post_id):
        with fast_fetch.get_db() as conn:
            return conn.execute(
                "SELECT is_18_plus FROM posts WHERE id = ?", (post_id,)).fetchone()[0]

    def public(self, query=""):
        return viewer.api_v1_get_posts(query=query, limit=50)

    # --- the direction that was broken: a version word must not flag ---------------

    def test_uncut_in_a_title_is_not_adult(self):
        self.assertEqual(fast_fetch.is_adult_title("Kanguva (2024) HDRip Uncut HD"), 0)

    def test_unrated_in_a_title_is_not_adult(self):
        self.assertEqual(fast_fetch.is_adult_title("Hi Nanna 2023 Unrated Director Cut"), 0)

    def test_the_other_works_hidden_by_this_bug_are_not_adult(self):
        for title in ("Guntur Kaaram 2024 (Hindi) HDRip Unrated",
                      "Dharmaveer 2 (2024) Uncut",
                      "Gangs of Godavari 2024 WEB-DL Uncut",
                      "Junior (2023) Dual Audio Uncut HD",
                      "Election (2024) Uncut"):
            self.assertEqual(fast_fetch.is_adult_title(title), 0, title)

    def test_an_uncut_slug_does_not_flag_a_stored_post(self):
        """The engine derives the flag from the slug too, which is where desicinemas
        writes it: `save_scraped_data` reads `original_title or slug or url`."""
        post_id = self.save(
            title="Kanguva", clean_title="Kanguva", year=2024,
            slug="kanguva-2024-hindi-uncut-hd-download",
            url="https://desicinemas.example/movie/13741/",
        )
        self.assertEqual(self.flag(post_id), 0)
        self.assertEqual([row["id"] for row in self.public()["results"]], [post_id])

    def test_an_unrated_title_stored_through_the_api_is_served(self):
        post_id = self.save(
            title="Hi Nanna (2023)", clean_title="Hi Nanna", year=2023,
            url="https://desicinemas.example/hi-nanna-2023-unrated-directors-cut/",
        )
        self.assertEqual(self.flag(post_id), 0)
        self.assertEqual(self.public(query="Hi Nanna")["total"], 1)

    # --- the direction that must NOT regress: real markers still flag ---------------

    def test_true_adult_markers_still_flag(self):
        self.assertEqual(fast_fetch.is_adult_title("Something 18+ Adult Erotic"), 1)
        self.assertEqual(fast_fetch.is_adult_title("Ullu"), 1)

    def test_the_collapsed_18_pattern_still_matches_both_spellings(self):
        r"""\b18\s*\+ subsumes \b18\+, so collapsing the pair must not lose "18 +"."""
        self.assertEqual(fast_fetch.is_adult_title("Pyaar Mein 18+"), 1)
        self.assertEqual(fast_fetch.is_adult_title("Pyaar Mein 18 +"), 1)
        self.assertEqual(sum(1 for p in fast_fetch.ADULT_TITLE_PATTERNS if "18" in p), 1,
                         "the redundant pair must not come back")

    def test_a_studio_named_alongside_uncut_still_flags(self):
        """Removing the version words must not blind the rule to a page that says
        both: the studio is the evidence, "Uncut" is decoration."""
        for text in ("Kanguva 18+ Uncut", "Chutiyapa Ullu Originals UnCut",
                     "Hotshots Naughty Unrated"):
            self.assertEqual(fast_fetch.is_adult_title(text), 1, text)

    def test_a_version_word_never_flags_any_adult_list_alone(self):
        """Every `*ADULT*` literal in the tree, not just the engine's: the same two
        words were copied into site scrapers, and each is a separate flag decision."""
        offenders = []
        root = Path(fast_fetch.__file__).resolve().parent
        for path in sorted(root.rglob("*.py")):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not any(isinstance(t, ast.Name) and "adult" in t.id.lower()
                           for t in targets):
                    continue
                if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    continue
                for element in node.value.elts:
                    if not (isinstance(element, ast.Constant)
                            and isinstance(element.value, str)):
                        continue
                    hit = self.version_words_in(element.value)
                    if hit:
                        offenders.append(f"{path.relative_to(root)}: {element.value!r} "
                                         f"-> {sorted(hit)}")
        self.assertEqual(offenders, [],
                         "a version word in an adult list hides mainstream works: "
                         + "; ".join(offenders))

    # --- the key law, after the pattern change -------------------------------------

    def test_a_flagged_twin_still_hides_the_key(self):
        adult = self.save(
            site="site_b", clean_title="Kanguva", title="Kanguva (2024)", year=2024,
            url="https://site-b.example/kanguva-2024-ullu-original-uncut/",
            canonical_key="kanguva_2024",
        )
        self.assertEqual(self.flag(adult), 1, "the flag comes from the studio, not 'Uncut'")
        self.insert_legacy(url="https://site-a.example/one", key="kanguva_2024")

        self.assertEqual(fast_fetch.reconcile_key_adult(self.db_path), 1)
        self.assertEqual(self.public()["total"], 0)

    def test_an_unrelated_key_does_not_leak_across(self):
        """The bug at scale: one "Uncut" row must not hide a work it is not, and one
        genuinely adult work must not pull an unrelated key down with it."""
        kanguva = self.save(
            site="site_a", clean_title="Kanguva", title="Kanguva (2024) HDRip Uncut HD",
            year=2024, url="https://site-a.example/kanguva-2024-hindi-uncut-hd-download/",
        )
        adult = self.save(
            site="site_b", clean_title="Chutiyapa", title="Chutiyapa (2023) Ullu Originals",
            year=2023, url="https://site-b.example/chutiyapa-2023-ullu/",
        )
        self.assertEqual(self.flag(kanguva), 0)
        self.assertEqual(self.flag(adult), 1)

        self.assertEqual(fast_fetch.reconcile_key_adult(self.db_path), 0)
        self.assertEqual([row["id"] for row in self.public()["results"]], [kanguva])
        self.assertIsNone(viewer.api_v1_get_post_detail(adult))


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


class AuditAdultFlagsToolTests(unittest.TestCase):
    """The evidence audit that decides which flags may be lowered at all.

    Un-flagging is an exposure event, so the tool is tested on the things that make it
    safe rather than on its arithmetic: it reports before it writes, it refuses to write
    without the owner's words, it writes and verifies a preimage before touching a row,
    it frees only the version-word class, and it never frees a row whose key carries
    true-adult evidence elsewhere.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "audit.db"
        self.vault_dir = self.root / "vaults"
        self.vault_dir.mkdir()
        #: The tool's default preimage home is the host's backup dir. A test that lets it
        #: resolve there would write rollback artifacts into /home/ubuntu/radd-stream-backups.
        self.backup_dir = self.root / "backups"
        self.backup_patch = patch.dict(os.environ,
                                       {"RADD_BACKUP_DIR": str(self.backup_dir)})
        self.backup_patch.start()
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        fast_fetch.init_db()
        import audit_adult_flags as tool
        self.tool = tool

    def tearDown(self):
        self.backup_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def insert(self, url, key, title, clean_title, *, year=2024, site="site_a", flagged=1):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
                " source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, ?, 'movie', ?, ?, ?)",
                (url, url.rstrip("/").split("/")[-1], title, clean_title, year,
                 site, flagged, key))
            conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_canonical_key"
                         " ON posts(canonical_key)")

    def vault(self, site, rows):
        """One site's staging database, in the shape the merge expects."""
        path = self.vault_dir / f"{site}.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE posts (canonical_key TEXT PRIMARY KEY, title TEXT,"
                         " synopsis TEXT, url TEXT, slug TEXT, raw_meta TEXT)")
            conn.executemany("INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?)", rows)
        return path

    def build(self):
        self.insert("https://a.example/kanguva-2024-hindi-uncut-hd-download/",
                    "kanguva_2024", "Kanguva (2024) HDRip Uncut HD", "Kanguva")
        self.insert("https://b.example/hi-nanna-2023-unrated/", "hi_nanna_2023",
                    "Hi Nanna (2023) Unrated", "Hi Nanna", year=2023)
        self.insert("https://c.example/chutiyapa-18plus/", "chutiyapa_2023",
                    "Chutiyapa (2023) 18+", "Chutiyapa", year=2023, site="ullu")
        self.insert("https://d.example/gandi-hotti-uncut/", "hotti_2022",
                    "Gandi Hotti (2022) Uncut", "Gandi Hotti", year=2022)
        self.insert("https://e.example/gandi-hotti-ullu-originals/", "hotti_2022",
                    "Gandi Hotti (2022) Ullu Originals", "Gandi Hotti", year=2022,
                    site="site_b")
        self.insert("https://f.example/plain-film/", "plain_2021",
                    "A Plain Film", "A Plain Film", year=2021, site="vaultsite")
        self.insert("https://g.example/unbucketed-uncut/", "unknown",
                    "Unbucketed Uncut", "Unbucketed")
        self.insert("https://h.example/safe/", "safe_2020", "A Safe Film",
                    "A Safe Film", year=2020, flagged=0)
        self.vault("vaultsite", [("plain_2021", "A Plain Film",
                                  "An 18+ erotic web series",
                                  "https://f.example/plain-film/",
                                  "plain-film", "{}")])

    def audit(self, **kwargs):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return self.tool.audit(conn, vault_dir=self.vault_dir, **kwargs)

    def run_tool(self, *argv):
        from contextlib import redirect_stderr, redirect_stdout
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.tool.main([str(self.db_path), *argv])
        return code, out.getvalue() + err.getvalue()

    def flags(self):
        with sqlite3.connect(self.db_path) as conn:
            return {row[0]: int(row[1] or 0) for row in conn.execute(
                "SELECT url, is_18_plus FROM posts")}

    def backups(self):
        """The preimage home the tool resolved to — a temp dir here, never the host's."""
        return Path(os.environ["RADD_BACKUP_DIR"])

    def test_report_mode_cannot_write_even_by_accident(self):
        self.build()
        with self.assertRaises(sqlite3.OperationalError) as caught:
            conn = self.tool.open_ledger(self.db_path, write=False)
            try:
                conn.execute("UPDATE posts SET is_18_plus = 0")
            finally:
                conn.close()
        self.assertIn("readonly", str(caught.exception).lower())
        self.assertEqual(sum(self.flags().values()), 7, "a report left every flag alone")

    def test_the_preimage_defaults_to_the_backup_dir_and_is_named_for_the_audit(self):
        self.build()
        code, out = self.run_tool("--apply", "--owner-go", "owner GO",
                                  "--vault-dir", str(self.vault_dir))
        self.assertEqual(code, 0, out)
        landed = sorted(self.backups().glob("adult_audit_preimage_*.json"))
        self.assertEqual(len(landed), 1, out)
        self.assertEqual(landed[0].parent.resolve(), self.backups().resolve(),
                         "rollback artifacts land in the backup dir the operator chose, "
                         "not in whichever directory holds the ledger")
        self.assertFalse(list(self.db_path.parent.glob("adult_unflag_preimage_*.json")))

    def test_it_refuses_to_write_when_the_preimage_cannot_be_created(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions, so the refusal cannot be shown")
        self.build()
        self.backup_dir.mkdir(parents=True)
        os.chmod(self.backup_dir, 0o500)  # r-x: the owner may not create a file in it
        try:
            code, out = self.run_tool("--apply", "--owner-go", "owner GO",
                                      "--vault-dir", str(self.vault_dir))
        finally:
            os.chmod(self.backup_dir, 0o700)
        self.assertEqual(code, 1, out)
        self.assertIn("no usable preimage", out)
        self.assertEqual(sum(self.flags().values()), 7,
                         "a failed preimage must leave every flag exactly where it was")

    def test_no_journal_exists_unless_it_is_asked_for_and_it_holds_no_titles(self):
        self.build()
        code, out = self.run_tool("--vault-dir", str(self.vault_dir))
        self.assertEqual(code, 0, out)
        self.assertEqual(list(self.root.glob("*.txt")) + list(self.backups().glob("*")), [],
                         "the report printed and logged nothing behind the caller's back")
        journal = self.root / "decisions.txt"
        code, out = self.run_tool("--vault-dir", str(self.vault_dir),
                                  "--journal", str(journal))
        self.assertEqual(code, 0, out)
        text = journal.read_text(encoding="utf-8")
        self.assertIn("CANDIDATE", text)
        for title in ("Kanguva", "Hi Nanna", "Chutiyapa", "Gandi Hotti"):
            self.assertNotIn(title, text,
                             "a file of adult-row titles is not an artifact to keep")

    def test_a_freed_row_is_re_tested_against_its_own_text(self):
        self.build()
        adult = self.row_id("https://c.example/chutiyapa-18plus/")
        freed = self.row_id("https://a.example/kanguva-2024-hindi-uncut-hd-download/")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bad = self.tool.retest_freed(conn, [{"id": freed}, {"id": adult}],
                                         self.tool.ledger_columns(conn))
        self.assertEqual(set(bad), {adult},
                         "the row whose own text is adult must be named; the uncut one may "
                         "be freed because the re-test is about ITS evidence, not its sibling's")

    def test_report_classifies_each_class_from_its_own_evidence(self):
        self.build()
        result = self.audit()
        self.assertEqual(result["flagged"], 7)
        self.assertEqual(result["counts"][self.tool.TRUE_ADULT], 2)
        self.assertEqual(result["counts"][self.tool.VERSION_WORD_ONLY], 4)
        self.assertEqual(result["counts"][self.tool.VAULT_ADULT], 1)
        self.assertEqual(result["counts"][self.tool.UNRESOLVED], 0)
        self.assertEqual({c["id"] for c in result["candidates"]},
                         {self.row_id("https://a.example/"
                                       "kanguva-2024-hindi-uncut-hd-download/"),
                          self.row_id("https://b.example/hi-nanna-2023-unrated/"),
                          self.row_id("https://g.example/unbucketed-uncut/")})

    def row_id(self, url):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT id FROM posts WHERE url = ?", (url,)).fetchone()[0]

    def test_a_true_adult_sibling_blocks_the_candidate(self):
        self.build()
        result = self.audit()
        blocked = self.row_id("https://d.example/gandi-hotti-uncut/")
        self.assertNotIn(blocked, {c["id"] for c in result["candidates"]},
                         "'Uncut' is no evidence, but its sibling being Ullu is")
        self.assertEqual(result["blocked_sibling_adult"], 1)

    def test_the_vault_resolves_what_the_ledger_text_cannot(self):
        """The 2,647: nothing in the ledger's own columns, so the raw row is read."""
        self.build()
        result = self.audit()
        self.assertEqual(result["counts"][self.tool.VAULT_ADULT], 1)
        self.assertIn(("vaultsite", 1), result["vaults_loaded"])
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bare = self.tool.audit(conn, vault_dir=None)
        self.assertEqual(bare["counts"][self.tool.VAULT_ADULT], 0)
        self.assertEqual(bare["counts"][self.tool.UNRESOLVED], 1,
                         "an unread vault is an unresolved row, never a candidate")
        self.assertNotIn(self.row_id("https://f.example/plain-film/"),
                         {c["id"] for c in bare["candidates"]})

    def test_apply_refuses_without_the_owners_words(self):
        self.build()
        code, out = self.run_tool("--apply", "--vault-dir", str(self.vault_dir))
        self.assertEqual(code, 2)
        self.assertIn("--owner-go", out)
        self.assertEqual(sum(self.flags().values()), 7, "nothing moved")

    def test_apply_writes_and_verifies_a_preimage_before_it_writes(self):
        self.build()
        code, out = self.run_tool("--apply", "--owner-go", "owner GO",
                                  "--vault-dir", str(self.vault_dir))
        self.assertEqual(code, 0, out)
        preimage = sorted(self.backups().glob("adult_audit_preimage_*.json"))
        self.assertEqual(len(preimage), 1, out)
        payload = json.loads(preimage[0].read_text())
        self.assertEqual(payload["owner_go"], "owner GO")
        self.assertEqual({row["id"] for row in payload["rows"]},
                         {self.row_id("https://a.example/kanguva-2024-hindi-uncut-hd-download/"),
                          self.row_id("https://b.example/hi-nanna-2023-unrated/"),
                          self.row_id("https://g.example/unbucketed-uncut/")})
        for row in payload["rows"]:
            self.assertEqual(row["is_18_plus"], 1,
                             "the preimage is the PRE state, or it is not a rollback point")
            self.assertIsNotNone(row["canonical_key"])

    def test_the_rows_it_frees_are_exactly_the_rows_the_preimage_names(self):
        self.build()
        before = self.flags()
        code, out = self.run_tool("--apply", "--owner-go", "owner GO",
                                  "--vault-dir", str(self.vault_dir))
        self.assertEqual(code, 0, out)
        after = self.flags()
        freed = {url for url, flag in before.items() if flag and not after[url]}
        preimage = json.loads(next(self.backups().glob("adult_audit_preimage_*.json")).read_text())
        ids_in_preimage = {row["id"] for row in preimage["rows"]}
        self.assertEqual({self.row_id(url) for url in freed}, ids_in_preimage)

    def test_it_never_hides_anything(self):
        self.build()
        before = self.flags()
        self.run_tool("--apply", "--owner-go", "owner GO",
                      "--vault-dir", str(self.vault_dir))
        after = self.flags()
        for url, flag in before.items():
            if flag:
                continue
            self.assertEqual(after[url], 0, f"{url} went from public to hidden")
        still_hidden = [url for url, flag in before.items()
                        if flag and url.endswith(("chutiyapa-18plus/",
                                                  "gandi-hotti-ullu-originals/",
                                                  "plain-film/"))]
        for url in still_hidden:
            self.assertEqual(after[url], 1, url)

    def test_require_clean_siblings_holds_a_mixed_key_back(self):
        self.insert("https://z.example/only-copy-uncut/", "mixed_2022",
                    "Only Copy (2022) Uncut", "Only Copy", year=2022)
        self.insert("https://y.example/only-copy-mirror/", "mixed_2022",
                    "Only Copy (2022)", "Only Copy", year=2022, site="site_b")
        loose = self.audit()
        self.assertEqual(loose["mixed_keys_after"], 1)
        self.assertIn(self.row_id("https://z.example/only-copy-uncut/"),
                      {c["id"] for c in loose["candidates"]})
        tight = self.audit(require_clean_siblings=True)
        self.assertNotIn(self.row_id("https://z.example/only-copy-uncut/"),
                         {c["id"] for c in tight["candidates"]},
                         "freeing one copy while its twin stays hidden re-opens the "
                         "mixed key this whole lane exists to close")

    def test_the_unknown_key_is_a_bucket_not_a_work(self):
        self.build()
        result = self.audit()
        self.assertIn(self.row_id("https://g.example/unbucketed-uncut/"),
                      {c["id"] for c in result["candidates"]},
                      "`unknown` never blocks and is never blocked by a sibling")

    def test_max_rows_selects_a_first_tranche_by_id(self):
        self.build()
        code, out = self.run_tool("--apply", "--owner-go", "owner GO",
                                  "--vault-dir", str(self.vault_dir), "--max-rows", "1")
        self.assertEqual(code, 0, out)
        preimage = json.loads(next(self.backups().glob("adult_audit_preimage_*.json")).read_text())
        self.assertEqual(len(preimage["rows"]), 1)
        self.assertEqual(sum(self.flags().values()), 6)

    def test_projection_rerolls_only_works_with_no_flagged_row_left(self):
        self.build()
        import catalog_v2
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            catalog_v2.project(conn, reset=True, verbose=False)
        code, out = self.run_tool("--apply", "--owner-go", "owner GO", "--projection",
                                  "--vault-dir", str(self.vault_dir))
        self.assertEqual(code, 0, out)
        with sqlite3.connect(self.db_path) as conn:
            hidden = {row[0] for row in conn.execute(
                "SELECT title FROM cat_works WHERE is_18_plus = 1")}
            stamps = {row[0] for row in conn.execute("SELECT key FROM cat_projection_meta")}
        self.assertIn("Gandi Hotti", hidden, "its sibling is genuinely adult")
        self.assertIn("Chutiyapa", hidden)
        self.assertNotIn("Kanguva", hidden, "freed by the pattern fix, so the work is too")
        for stamp in self.tool.SAFE_STAMP_KEYS:
            self.assertNotIn(stamp, stamps,
                             "a safe counter taken before the flip is a stale public number")


class TlsPolicyTests(unittest.TestCase):
    """One TLS policy, one context factory, and a host cannot quietly opt back out.

    The engine used to ship three hand-rolled `CERT_NONE` contexts, so every outbound
    HTTPS fetch — catalog metadata, poster URLs, resolved source links — accepted any
    certificate. The default here is deliberately still permissive (flipping it in one
    commit breaks every scraper behind a host with a bad chain), so what these tests
    hold is the part that must not regress: the policy has ONE home, and a host named
    in the allow-list cannot return content over an untrusted chain.

    Loopback and a self-signed certificate only: no third-party site is contacted and
    no live probe is made.
    """

    SECRET = "FORGED-BODY-THAT-MUST-NEVER-BE-SERVED"

    def setUp(self):
        import config
        self.config = config
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self._saved_hosts = config.TLS_VERIFIED_HOSTS
        self._saved_mode = config.TLS_VERIFY
        config.TLS_VERIFIED_HOSTS = frozenset()
        config.TLS_VERIFY = "permissive"
        config._TLS_CONTEXTS.clear()

    def tearDown(self):
        self.config.TLS_VERIFIED_HOSTS = self._saved_hosts
        self.config.TLS_VERIFY = self._saved_mode
        self.config._TLS_CONTEXTS.clear()
        self.temp_dir.cleanup()

    def make_server(self):
        """A self-signed HTTPS server on 127.0.0.1, or a skip if openssl is absent."""
        cert = self.root / "cert.pem"
        key = self.root / "key.pem"
        try:
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(cert), "-days", "1",
                 "-subj", "/CN=localhost",
                 "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                check=True, capture_output=True)
        except Exception as exc:                                  # pragma: no cover
            self.skipTest(f"cannot mint a local certificate: {exc}")

        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    self.request.recv(4096)
                    body = outer.SECRET.encode()
                    self.request.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        plain = Server(("127.0.0.1", 0), Handler)
        port = plain.server_address[1]
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        plain.socket = context.wrap_socket(plain.socket, server_side=True)
        thread = threading.Thread(target=plain.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(plain.shutdown)
        self.addCleanup(plain.server_close)
        return f"https://localhost:{port}/"

    # ── the policy has one home ────────────────────────────────────────────────

    def test_the_engine_no_longer_builds_its_own_ssl_contexts(self):
        """`The bug is the duplication as much as the default.`

        A prose mention of CERT_NONE in a comment is fine; a second context factory in
        the engine is not, because it is one more place the posture is decided.
        """
        source = Path(fast_fetch.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ssl.create_default_context()", source)
        self.assertNotIn("verify_mode = ssl.CERT_NONE", source)
        self.assertNotIn("SSL_CONTEXT", source)

    def test_every_https_call_site_in_the_engine_asks_the_policy(self):
        """Every `urlopen`/`HTTPSHandler` in the engine passes a policy context.

        Read from the AST, not the text: the call and its `context=` argument are not
        always on the same line, and a hand-rolled context that scrolls off the end of
        a wrapped call is exactly the miss this is here to catch. A call with NO
        `context=` is accepted — that is urllib's verifying default, the safe
        direction; what must never come back is a context built by hand.
        """
        tree = ast.parse(Path(fast_fetch.__file__).read_text(encoding="utf-8"))
        unpoliced = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = callee.attr if isinstance(callee, ast.Attribute) else (
                callee.id if isinstance(callee, ast.Name) else "")
            if name not in ("urlopen", "HTTPSHandler"):
                continue
            context = next((kw for kw in node.keywords if kw.arg == "context"), None)
            if context is None:
                continue
            value = context.value
            if not (isinstance(value, ast.Call)
                    and getattr(value.func, "id", None) == "_tls_context"):
                unpoliced.append(f"line {node.lineno}: {name} chooses its own context")
        self.assertEqual(unpoliced, [], "\n".join(unpoliced))

    def test_the_default_is_todays_permissive_handshake(self):
        context = self.config.tls_context("anything.example")
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)

    def test_a_listed_host_is_verified_and_strict_mode_covers_everything(self):
        self.config.TLS_VERIFIED_HOSTS = frozenset({"api.dandndn.one"})
        self.assertTrue(self.config.tls_host_verified("API.DandnDN.one"))
        self.assertFalse(self.config.tls_host_verified("other.example"))
        self.assertEqual(self.config.tls_context("api.dandndn.one").verify_mode,
                         ssl.CERT_REQUIRED)
        self.config.TLS_VERIFY = "strict"
        self.assertTrue(self.config.tls_host_verified("never.heard.of.it"))

    def test_the_context_is_cached_per_policy_not_rebuilt_per_request(self):
        self.assertIs(self.config.tls_context("a.example"),
                      self.config.tls_context("b.example"))
        self.config.TLS_VERIFIED_HOSTS = frozenset({"a.example"})
        self.assertIsNot(self.config.tls_context("a.example"),
                         self.config.tls_context("b.example"))

    # ── a request path cannot silently downgrade ───────────────────────────────

    def test_an_unlisted_host_still_gets_content(self):
        url = self.make_server()
        import urllib.request
        with urllib.request.urlopen(url, context=fast_fetch._tls_context(url),
                                    timeout=10) as resp:
            self.assertEqual(resp.read().decode(), self.SECRET)

    def test_a_verified_host_raises_instead_of_returning_an_untrusted_chain(self):
        """The whole point of the allow-list: listing a host is not advisory."""
        import urllib.error
        import urllib.request
        url = self.make_server()
        self.config.TLS_VERIFIED_HOSTS = frozenset({"localhost"})
        with self.assertRaises(urllib.error.URLError) as caught:
            with urllib.request.urlopen(url, context=fast_fetch._tls_context(url),
                                        timeout=10) as resp:
                self.fail(f"an untrusted chain returned content: {resp.read()!r}")
        self.assertIsInstance(caught.exception.reason, ssl.SSLCertVerificationError,
                              "a handshake failure on a verified host must be a "
                              "verification failure, not a timeout or a fallback")

    def test_the_engine_request_path_returns_no_body_for_a_verified_host(self):
        """`http_get` swallows the exception into (0, url, "ERROR: …"), so the test is
        that the forged body never reaches the caller — not that Python raises."""
        url = self.make_server()
        self.config.TLS_VERIFIED_HOSTS = frozenset({"localhost"})
        status, _, content = fast_fetch.http_get(url, timeout=10, max_retries=0)
        self.assertEqual(status, 0)
        self.assertNotIn(self.SECRET, content)
        self.assertIn("ERROR", content)

    def test_one_verified_peer_verifies_the_whole_call(self):
        """Strictness never negotiates downwards when a call knows two hosts."""
        self.config.TLS_VERIFIED_HOSTS = frozenset({"trusted.example"})
        context = fast_fetch._tls_context("https://untrusted.example/x",
                                         "trusted.example")
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)


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

    def test_resumable_index_backs_the_resumable_count(self):
        with fast_fetch.get_db() as conn:
            # PRAGMA index_info(?) is not parameterizable; the name is a constant here.
            indexed_cols = [r[2] for r in conn.execute("PRAGMA index_info(idx_sources_resumable)")]
        self.assertEqual(indexed_cols, ["is_resumable"])

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
