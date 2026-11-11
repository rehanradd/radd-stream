"""Offline tests for forgiving search on the v1 list route (Gap A4) and
for the list-row "subtitled" badge reading stored tracks (Gap A3).

The v1 list search is the omnibox path the app uses: a pure mood query
is answered from the genre facet, a title that happens to contain a mood
word is still searched literally first, and a typo'd query surfaces the
correction the fuzzy fallback already knew.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fast_fetch
import subtitle_tracks
import viewer


class ViewerSearchForgivingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        self.cinemeta_patch = patch.object(
            fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        self.cinemeta_patch.start()
        fast_fetch.init_db()
        self._seed()

    def tearDown(self):
        self.cinemeta_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def media(site, url, *, title, clean_title, genres=None,
              quality="720p", is_18_plus=0, release_title=None):
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
            "genres": json.dumps(genres) if genres else None,
            "synopsis": None,
            "is_18_plus": is_18_plus,
            "is_animated": 0,
            "source_site": site,
            "industry": "Hollywood",
            "country": "USA",
            "language": "English",
            "canonical_key": fast_fetch.generate_canonical_key(clean_title, 2019),
            "tmdb_id": None,
            "imdb_id": None,
            "releases": [
                {
                    "release_title": release_title or f"{clean_title} {quality}",
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

    def _seed(self):
        fast_fetch.save_scraped_data(self.media(
            "site_funny", "https://site-funny.example/laugh-out-loud/",
            title="Laugh Out Loud (2019)", clean_title="Laugh Out Loud",
            genres=["Comedy"]))
        fast_fetch.save_scraped_data(self.media(
            "site_romance", "https://site-romance.example/romantic-evening/",
            title="A Romantic Evening (2019)", clean_title="A Romantic Evening",
            genres=["Romance", "Drama"]))
        fast_fetch.save_scraped_data(self.media(
            "site_errors", "https://site-errors.example/comedy-of-errors/",
            title="The Comedy of Errors (2019)", clean_title="The Comedy of Errors",
            genres=["Drama"]))
        fast_fetch.save_scraped_data(self.media(
            "site_inception", "https://site-inception.example/inception/",
            title="Inception (2019)", clean_title="Inception",
            genres=["Thriller"]))
        fast_fetch.save_scraped_data(self.media(
            "site_adult", "https://site-adult.example/adult-comedy/",
            title="Adult Comedy (2019)", clean_title="Adult Comedy",
            genres=["Comedy"], is_18_plus=1))

    def posts(self, query, **kwargs):
        with patch.object(viewer, "DB_PATH", self.db_path):
            return viewer.api_v1_get_posts(query=query, limit=10, **kwargs)

    def clean_titles(self, resp):
        return [r["clean_title"] for r in resp["results"]]

    def test_pure_mood_query_is_answered_from_the_genre(self):
        resp = self.posts("something funny")
        self.assertIn("Laugh Out Loud", self.clean_titles(resp))
        self.assertEqual(resp["moods"], ["funny"])
        self.assertEqual(resp["mood_genres"], ["comedy"])
        # The mood browse is genre-filtered: a drama called a comedy is not one.
        self.assertNotIn("The Comedy of Errors", self.clean_titles(resp))
        # ... and a flagged comedy is never served, mood or not.
        self.assertNotIn("Adult Comedy", self.clean_titles(resp))

    def test_hindi_mood_query_finds_english_titles(self):
        resp = self.posts("mazahiya")
        self.assertIn("Laugh Out Loud", self.clean_titles(resp))
        self.assertEqual(resp["mood_genres"], ["comedy"])

    def test_title_containing_a_mood_word_is_searched_literally_first(self):
        resp = self.posts("comedy of errors")
        self.assertIn("The Comedy of Errors", self.clean_titles(resp))
        self.assertEqual(resp["moods"], ["comedy"])
        self.assertFalse(resp["fuzzy"])

    def test_typo_surfaces_did_you_mean(self):
        resp = self.posts("incepton")
        self.assertEqual(resp.get("did_you_mean"), "inception")
        self.assertTrue(resp["fuzzy"])
        self.assertIn("Inception", self.clean_titles(resp))

    def test_exact_query_has_no_did_you_mean(self):
        resp = self.posts("Inception")
        self.assertIsNone(resp.get("did_you_mean"))
        self.assertFalse(resp["fuzzy"])
        self.assertIn("Inception", self.clean_titles(resp))

    def test_unmatchable_query_has_no_suggestion(self):
        resp = self.posts("zzzzqq")
        self.assertEqual(resp["total"], 0)
        self.assertIsNone(resp.get("did_you_mean"))


class SubtitledPostsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        self.cinemeta_patch = patch.object(
            fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        self.cinemeta_patch.start()
        fast_fetch.init_db()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.post_ids = {}
        for site, title, release_title in (
                ("site_tracked", "Tracked Film", "Tracked Film 720p"),
                ("site_labelled", "Labelled Film", "Labelled Film ESub 720p"),
                ("site_plain", "Plain Film", "Plain Film 720p")):
            post_id = fast_fetch.save_scraped_data(
                ViewerSearchForgivingTests.media(
                    site, f"https://{site}.example/film/",
                    title=f"{title} (2019)", clean_title=title,
                    release_title=release_title))
            self.post_ids[title] = post_id
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.cinemeta_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_stored_tracks_mark_a_post_subtitled_without_a_label(self):
        row = self.conn.execute(
            "SELECT s.id FROM download_sources s JOIN releases r"
            " ON r.id = s.release_id WHERE r.post_id = ?",
            (self.post_ids["Tracked Film"],)).fetchone()
        subtitle_tracks.upsert_tracks(
            self.conn, int(row[0]),
            [{"language": "en", "url": "https://cdn.example.com/en.srt"}])
        self.conn.commit()
        flags = viewer._subtitled_posts(
            self.conn, list(self.post_ids.values()))
        self.assertTrue(flags[self.post_ids["Tracked Film"]])
        self.assertTrue(flags[self.post_ids["Labelled Film"]])
        self.assertFalse(flags[self.post_ids["Plain Film"]])

    def test_empty_input_is_empty(self):
        self.assertEqual(viewer._subtitled_posts(self.conn, []), {})


if __name__ == "__main__":
    unittest.main()
