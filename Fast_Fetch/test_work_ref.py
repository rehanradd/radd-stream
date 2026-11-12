"""Offline tests for the `work_ref` filter on `/api/v1/posts`.

A sync client names a work by the minted handle the server gave it, never
by a title or an id — so the pull side of sync needs the server to turn a
handle back into a post. The resolver unmints with the server's own secret,
so a forged handle is an empty page, never an error; the adult clause holds
at every step, so a flagged work is indistinguishable from a missing one.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_v2
import fast_fetch
import redact
import viewer

_TEST_SECRET = "test-secret-for-work-ref-only"


class WorkRefResolveTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        self.cinemeta_patch = patch.object(
            fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        self.cinemeta_patch.start()
        # The viewer caches its signing secret in a module global; pin it to
        # a test value so mint and parse agree without touching the env.
        self.secret_patch = patch.object(viewer, "_SIGNING_SECRET", _TEST_SECRET)
        self.secret_patch.start()
        fast_fetch.init_db()

    def tearDown(self):
        self.secret_patch.stop()
        self.cinemeta_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def media(site, url, *, title, clean_title, quality="1080p",
              is_18_plus=0, imdb_id=None, tmdb_id=None):
        return {
            "url": url,
            "slug": url.rstrip("/").split("/")[-1],
            "title": title,
            "clean_title": clean_title,
            "year": 2019,
            "content_type": "movie",
            "seasons": None,
            "poster_url": None,
            "backdrop_urls": None,
            "imdb_rating": None,
            "genres": None,
            "synopsis": None,
            "is_18_plus": is_18_plus,
            "is_animated": 0,
            "source_site": site,
            "industry": "Hollywood",
            "country": "USA",
            "language": "English",
            "canonical_key": fast_fetch.generate_canonical_key(clean_title, 2019),
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
                            "source_name": "Example CDN",
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

    def handle_for(self, key):
        return redact.mint_text(key, _TEST_SECRET)

    def posts(self, **kw):
        with patch.object(viewer, "DB_PATH", self.db_path):
            return viewer.api_v1_get_posts(**kw)

    def test_imdb_handle_resolves_to_the_one_post(self):
        fast_fetch.save_scraped_data(self.media(
            "site_a", "https://site-a.example/avengers/",
            title="Avengers: Endgame (2019)", clean_title="Avengers Endgame",
            imdb_id="tt4154796"))
        fast_fetch.save_scraped_data(self.media(
            "site_b", "https://site-b.example/avatar/",
            title="Avatar (2019)", clean_title="Avatar", imdb_id="tt0499549"))
        resp = self.posts(work_ref=self.handle_for("imdb:tt4154796"), limit=10)
        self.assertEqual(resp["total"], 1)
        self.assertFalse(resp["fuzzy"])
        self.assertEqual(resp["results"][0]["clean_title"], "Avengers Endgame")

    def test_title_family_handle_resolves_without_any_id(self):
        fast_fetch.save_scraped_data(self.media(
            "site_a", "https://site-a.example/avengers/",
            title="Avengers: Endgame (2019)", clean_title="Avengers Endgame"))
        key = catalog_v2.work_key_for("Avengers Endgame", 2019, "movie")
        self.assertEqual(key, "movie:avengers endgame:2019")
        resp = self.posts(work_ref=self.handle_for(key), limit=10)
        self.assertEqual(resp["total"], 1)
        self.assertEqual(resp["results"][0]["clean_title"], "Avengers Endgame")

    def test_a_forged_handle_is_an_empty_page_not_an_error(self):
        fast_fetch.save_scraped_data(self.media(
            "site_a", "https://site-a.example/avengers/",
            title="Avengers: Endgame (2019)", clean_title="Avengers Endgame",
            imdb_id="tt4154796"))
        resp = self.posts(work_ref="not-a-handle-at-all", limit=10)
        self.assertEqual(resp["total"], 0)
        self.assertEqual(resp["results"], [])
        # A handle minted with a different secret is just as foreign.
        foreign = redact.mint_text("imdb:tt4154796", "someone-elses-secret")
        self.assertEqual(self.posts(work_ref=foreign, limit=10)["total"], 0)

    def test_an_adult_works_handle_resolves_to_nothing(self):
        fast_fetch.save_scraped_data(self.media(
            "site_a", "https://site-a.example/avengers/",
            title="Avengers: Endgame (2019)", clean_title="Avengers Endgame",
            is_18_plus=1, imdb_id="tt4154796"))
        resp = self.posts(work_ref=self.handle_for("imdb:tt4154796"), limit=10)
        self.assertEqual(resp["total"], 0)

    def test_a_handle_for_a_work_that_is_not_here_is_empty(self):
        resp = self.posts(work_ref=self.handle_for("imdb:tt0000000"), limit=10)
        self.assertEqual(resp["total"], 0)

    def test_family_lookup_with_a_year_seeks_the_year_index(self):
        """Appetize FAILED 2: the family lookup was a 4.8 s full-table scan
        on the live catalog, because the UDF term has no index and nothing
        else in the WHERE could seek. `idx_posts_year` (minted by
        `fast_fetch.init_db`) lets the planner seek the year's rows before
        the UDF runs. The statement is transcribed from
        `viewer._resolve_work_ref`; the plan is asserted, not remembered.
        """
        conn = sqlite3.connect(self.db_path)
        conn.create_function(
            "radd_norm_title", 1, catalog_v2.normalize_title, deterministic=True)
        sql = ("SELECT id, clean_title, title, year, content_type, is_animated"
               " FROM posts p"
               " WHERE (p.is_18_plus IS NULL OR p.is_18_plus = 0)"
               " AND radd_norm_title(COALESCE(p.clean_title, p.title)) = ?"
               " AND p.year = ? ORDER BY id DESC")
        plan = [row[3] for row in conn.execute(
            "EXPLAIN QUERY PLAN " + sql, ("avengers endgame", 2019)).fetchall()]
        conn.close()
        self.assertTrue(
            any("USING INDEX idx_posts_year" in step for step in plan),
            f"family lookup scans instead of seeking the year index: {plan}")


if __name__ == "__main__":
    unittest.main()
