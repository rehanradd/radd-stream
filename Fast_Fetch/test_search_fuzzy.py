"""Offline regression tests for typo-tolerant search and the free-only filter.

The fuzzy fallback runs only when exact search finds nothing, and only ever
returns catalog rows one edit away from the query, token by token. The
free-only filter mirrors the client's VipQualityGate: a work counts as
included for a free viewer when it has at least one print that is not a
premium band — and a print with no quality label counts as free, the same
as the client treats an unknown band.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_fetch
import search_fuzzy
import viewer


class FuzzyHelpersTests(unittest.TestCase):
    def test_edit_distance(self):
        self.assertTrue(search_fuzzy.edit_distance_le1("avengers", "avengers"))
        self.assertTrue(search_fuzzy.edit_distance_le1("avngers", "avengers"))
        self.assertTrue(search_fuzzy.edit_distance_le1("avenger", "avengers"))
        self.assertTrue(search_fuzzy.edit_distance_le1("avengerss", "avengers"))
        self.assertTrue(search_fuzzy.edit_distance_le1("avengerr", "avengers"))
        self.assertFalse(search_fuzzy.edit_distance_le1("avngers", "avatar"))
        self.assertFalse(search_fuzzy.edit_distance_le1("abc", "xyz"))
        self.assertFalse(search_fuzzy.edit_distance_le1("avengers", "av"))

    def test_damerau_le1_counts_a_transposition_as_one_edit(self):
        # The correction check (FTS5 search, 2026-11-12): `inceptoin`
        # is two Levenshtein edits from `inception` but one Damerau
        # edit, and transpositions are one of the most common typos.
        self.assertTrue(search_fuzzy.damerau_le1("inceptoin", "inception"))
        self.assertTrue(search_fuzzy.damerau_le1("abdc", "abcd"))
        self.assertTrue(search_fuzzy.damerau_le1("avngers", "avengers"))
        self.assertFalse(search_fuzzy.damerau_le1("incepto", "inception"))
        self.assertFalse(search_fuzzy.damerau_le1("abc", "xyz"))
        self.assertFalse(search_fuzzy.damerau_le1("avengers", "av"))

    def test_tokenize(self):
        self.assertEqual(search_fuzzy.tokenize("Avengers: Endgame!"), ["avengers", "endgame"])
        self.assertEqual(search_fuzzy.tokenize(""), [])

    def test_fuzzy_match_needs_every_token(self):
        self.assertTrue(
            search_fuzzy.fuzzy_match(["avngers", "endgame"], ["avengers", "endgame"]))
        self.assertFalse(
            search_fuzzy.fuzzy_match(["avngers", "endgame"], ["avengers", "infinity"]))
        self.assertFalse(search_fuzzy.fuzzy_match([], ["avengers"]))
        # A transposition matches: the fuzzy fallback serves
        # `Inception` for `inceptoin`.
        self.assertTrue(
            search_fuzzy.fuzzy_match(["inceptoin"], ["inception"]))
        self.assertFalse(
            search_fuzzy.fuzzy_match(["incepto"], ["inception"]))

    def test_fuzzy_tokens_refuses_short_and_long(self):
        self.assertEqual(search_fuzzy.fuzzy_tokens("Avngers"), ["avngers"])
        self.assertEqual(search_fuzzy.fuzzy_tokens("It"), [])
        self.assertEqual(search_fuzzy.fuzzy_tokens("a b c d"), [])
        self.assertEqual(search_fuzzy.fuzzy_tokens("x" * 21), [])

    def test_candidate_grams_share_with_a_one_edit_title(self):
        grams = search_fuzzy.candidate_grams("avngers")
        title = "avengers"
        self.assertTrue(any(g in title for g in grams))


class FuzzySearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_path_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        self.cinemeta_patch = patch.object(
            fast_fetch, "fetch_cinemeta_metadata", return_value=None)
        self.cinemeta_patch.start()
        fast_fetch.init_db()

    def tearDown(self):
        self.cinemeta_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def media(site, url, *, title, clean_title, quality="1080p", is_18_plus=0):
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
            "tmdb_id": None,
            "imdb_id": None,
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

    def test_typo_finds_the_title_exact_missed(self):
        fast_fetch.save_scraped_data(self.media(
            "site_a", "https://site-a.example/avengers/",
            title="Avengers: Endgame (2019)", clean_title="Avengers Endgame"))
        fast_fetch.save_scraped_data(self.media(
            "site_b", "https://site-b.example/avatar/",
            title="Avatar (2019)", clean_title="Avatar"))
        with patch.object(viewer, "DB_PATH", self.db_path):
            resp = viewer.api_v1_get_posts(query="Avngers", limit=10)
            self.assertEqual(resp["total"], 1)
            self.assertTrue(resp["fuzzy"])
            self.assertEqual(resp["results"][0]["clean_title"], "Avengers Endgame")
            # The exact spelling still answers exactly, never fuzzily.
            exact = viewer.api_v1_get_posts(query="Avengers", limit=10)
            self.assertEqual(exact["total"], 1)
            self.assertFalse(exact["fuzzy"])
            # Two edits away is not a match: the fallback stays silent.
            self.assertEqual(
                viewer.api_v1_get_posts(query="Avngrzx", limit=10)["total"], 0)

    def test_fuzzy_never_serves_an_adult_row(self):
        fast_fetch.save_scraped_data(self.media(
            "site_a", "https://site-a.example/avengers/",
            title="Avengers: Endgame (2019)", clean_title="Avengers Endgame",
            is_18_plus=1))
        with patch.object(viewer, "DB_PATH", self.db_path):
            resp = viewer.api_v1_get_posts(query="Avngers", limit=10)
            self.assertEqual(resp["total"], 0)

    def test_free_only_keeps_only_works_with_a_free_print(self):
        fast_fetch.save_scraped_data(self.media(
            "site_a", "https://site-a.example/premium-only/",
            title="Premium Only (2019)", clean_title="Premium Only", quality="1080p"))
        fast_fetch.save_scraped_data(self.media(
            "site_b", "https://site-b.example/free-too/",
            title="Free Too (2019)", clean_title="Free Too", quality="720p"))
        fast_fetch.save_scraped_data(self.media(
            "site_c", "https://site-c.example/unlabelled/",
            title="Unlabelled (2019)", clean_title="Unlabelled", quality=None))
        with patch.object(viewer, "DB_PATH", self.db_path):
            all_posts = viewer.api_v1_get_posts(limit=10)
            self.assertEqual(all_posts["total"], 3)
            free = viewer.api_v1_get_posts(limit=10, free_only=True)
            self.assertEqual(free["total"], 2)
            self.assertEqual(
                sorted(r["clean_title"] for r in free["results"]),
                ["Free Too", "Unlabelled"])


if __name__ == "__main__":
    unittest.main()
