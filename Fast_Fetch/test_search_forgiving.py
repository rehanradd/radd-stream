"""Offline tests for forgiving search on the v2 read model (Gap A4) and
for subtitle tracks in the play bundle (Gap A3).

Mood/descriptive queries, "Did you mean", and the FTS5 path are layered
above `_run_listing`: the tests assert the behaviour, not the path, and
one test builds the FTS index to prove the MATCH branch answers the
same way as the LIKE fallback.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog_api
import fts_search
import subtitle_tracks
from test_catalog_api import CatalogApiTestCase


class ForgivingSearchTests(CatalogApiTestCase):
    def setUp(self):
        super().setUp()
        self.add_genre_post("Laugh Out Loud", ["Comedy"])
        self.add_genre_post("A Romantic Evening", ["Romance", "Drama"])
        self.add_genre_post("The Haunted Manor", ["Horror"])
        self.add_genre_post("The Comedy of Errors", ["Drama"])
        self.project(rev=2)

    def add_genre_post(self, clean_title, genres):
        post_id = self.add_post(
            "test", f"https://test.example/{clean_title.lower().replace(' ', '-')}/",
            clean_title=clean_title)
        self.conn.execute(
            "UPDATE posts SET genres = ? WHERE id = ?",
            (json.dumps(genres), post_id))
        self.conn.commit()
        return post_id

    def titles(self, result):
        return {item["title"] for item in result["items"]}

    def test_pure_mood_query_is_a_genre_browse(self):
        found = catalog_api.search(self.conn, q="something funny")
        self.assertIn("Laugh Out Loud", self.titles(found))
        self.assertEqual(found["moods"], ["funny"])
        self.assertEqual(found["mood_genres"], ["comedy"])
        # The mood browse is genre-filtered: a drama that happens to be
        # called a comedy is not a comedy.
        self.assertNotIn("The Comedy of Errors", self.titles(found))

    def test_hindi_mood_query_finds_english_titles(self):
        for query in ("mazahiya", "मजाहिया", "mohabbat"):
            found = catalog_api.search(self.conn, q=query)
            self.assertIn("Laugh Out Loud" if query != "mohabbat"
                          else "A Romantic Evening",
                          self.titles(found), query)

    def test_title_containing_a_mood_word_is_searched_literally_first(self):
        found = catalog_api.search(self.conn, q="comedy of errors")
        self.assertIn("The Comedy of Errors", self.titles(found))
        self.assertEqual(found["moods"], ["comedy"])
        self.assertNotIn("mood_fallback", found)

    def test_mixed_mood_query_falls_back_to_the_mood(self):
        found = catalog_api.search(self.conn, q="sad love story about a dog")
        self.assertIn("A Romantic Evening", self.titles(found))
        self.assertTrue(found.get("mood_fallback"))

    def test_typo_offers_did_you_mean_and_serves_the_correction(self):
        found = catalog_api.search(self.conn, q="dunne")
        self.assertEqual(found.get("did_you_mean"), "dune")
        self.assertTrue(found.get("fuzzy"))
        self.assertIn("Dune", self.titles(found))

    def test_clean_query_has_no_did_you_mean(self):
        found = catalog_api.search(self.conn, q="dune")
        self.assertNotIn("did_you_mean", found)
        self.assertNotIn("fuzzy", found)
        self.assertIn("Dune", self.titles(found))

    def test_empty_query_still_returns_the_documented_envelope(self):
        found = catalog_api.search(self.conn, q="")
        self.assertTrue(found["ok"])
        self.assertEqual(found["items"], [])
        self.assertEqual(found["moods"], [])
        self.assertEqual(found["mood_genres"], [])

    def test_suggest_corrects_a_typo(self):
        page = catalog_api.suggest(self.conn, q="dunne")
        self.assertEqual([i["title"] for i in page["items"]], ["Dune"])
        self.assertEqual(page.get("did_you_mean"), "dune")
        clean = catalog_api.suggest(self.conn, q="dun")
        self.assertEqual([i["title"] for i in clean["items"]], ["Dune"])
        self.assertNotIn("did_you_mean", clean)

    def test_search_works_with_the_fts_index_present(self):
        fts_search.rebuild_fts(self.conn)
        self.assertTrue(fts_search.fts_available(self.conn))
        found = catalog_api.search(self.conn, q="dune")
        self.assertIn("Dune", self.titles(found))
        mood = catalog_api.search(self.conn, q="something funny")
        self.assertIn("Laugh Out Loud", self.titles(mood))
        typo = catalog_api.search(self.conn, q="dunne")
        self.assertEqual(typo.get("did_you_mean"), "dune")
        self.assertIn("Dune", self.titles(typo))


class PlayBundleTracksTests(CatalogApiTestCase):
    def test_candidates_carry_their_subtitle_tracks(self):
        row = self.conn.execute(
            "SELECT id FROM download_sources WHERE resource_id = ?",
            ("DUNE-HLS",)).fetchone()
        ledger_link_id = int(row[0])
        subtitle_tracks.upsert_tracks(
            self.conn, ledger_link_id,
            [{"language": "en", "url": "https://cdn.example.com/dune.en.srt"},
             {"language": "hi", "url": "https://cdn.example.com/dune.hi.vtt"}],
            source="resolve")
        self.conn.commit()
        bundle = self.bundle("1080p WEB-DL")
        self.assertTrue(bundle["ok"])
        for candidate in bundle["candidates"]:
            self.assertIn("tracks", candidate)
            self.assertIsInstance(candidate["tracks"], list)
        hls = [c for c in bundle["candidates"]
               if c["link_id"] == self.link_of["DUNE-HLS"]["id"]]
        self.assertEqual(len(hls), 1)
        self.assertEqual(hls[0]["tracks"], [
            {"lang": "en", "kind": "subtitles",
             "subtitle_url": "https://cdn.example.com/dune.en.srt", "format": "srt",
             "default": False, "forced": False},
            {"lang": "hi", "kind": "subtitles",
             "subtitle_url": "https://cdn.example.com/dune.hi.vtt", "format": "vtt",
             "default": False, "forced": False},
        ])

    def test_candidates_without_tracks_carry_an_empty_list(self):
        bundle = self.bundle("1080p WEB-DL")
        self.assertTrue(bundle["ok"])
        self.assertTrue(bundle["candidates"])
        for candidate in bundle["candidates"]:
            self.assertEqual(candidate["tracks"], [])


if __name__ == "__main__":
    unittest.main()
