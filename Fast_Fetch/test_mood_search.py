"""Offline tests for the mood/descriptive query lexicon (Gap A4).

The lexicon maps a feeling or a description to genre tokens. It is a
hand-curated word list, not a model: a mood fires only on a whole stemmed
word, so "fun" never fires on "funeral" and a query with no mood word maps
to nothing — the caller then runs the ordinary search untouched.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mood_search


class MoodsForQueryTests(unittest.TestCase):
    def test_pure_mood_queries(self):
        self.assertEqual(mood_search.moods_for_query("something funny"), ["funny"])
        self.assertEqual(mood_search.moods_for_query("sad love story"),
                         ["sad", "love"])
        self.assertEqual(mood_search.moods_for_query("something scary tonight"),
                         ["scary"])

    def test_mood_words_are_matched_whole_not_as_substrings(self):
        self.assertEqual(mood_search.moods_for_query("funeral"), [])
        self.assertEqual(mood_search.moods_for_query("fun"), [])
        self.assertEqual(mood_search.moods_for_query("lovers"), [])

    def test_plurals_and_adjective_forms_stem_to_the_mood(self):
        self.assertEqual(mood_search.moods_for_query("comedies"), ["comedy"])
        self.assertEqual(mood_search.moods_for_query("thrillers"), ["thriller"])
        self.assertEqual(mood_search.moods_for_query("romantic films"), ["romantic"])

    def test_a_query_with_no_mood_word_maps_to_nothing(self):
        self.assertEqual(mood_search.moods_for_query("dune"), [])
        self.assertEqual(mood_search.moods_for_query(""), [])
        self.assertEqual(mood_search.moods_for_query("inception"), [])


class GenresForQueryTests(unittest.TestCase):
    def test_english_moods_map_to_english_genres(self):
        self.assertEqual(mood_search.genres_for_query("something funny"), ["comedy"])
        self.assertEqual(mood_search.genres_for_query("sad love story"),
                         ["drama", "romance"])
        self.assertEqual(mood_search.genres_for_query("something scary"),
                         ["horror", "thriller"])

    def test_roman_urdu_hindi_queries_find_english_genres(self):
        self.assertEqual(mood_search.genres_for_query("mazahiya"), ["comedy"])
        self.assertEqual(mood_search.genres_for_query("mohabbat"), ["romance"])
        self.assertEqual(mood_search.genres_for_query("bhoot"), ["horror"])
        self.assertEqual(mood_search.genres_for_query("jadui"), ["fantasy"])

    def test_devanagari_queries_map_identically(self):
        self.assertEqual(mood_search.genres_for_query("मजाहिया"), ["comedy"])
        self.assertEqual(mood_search.genres_for_query("मोहब्बत"), ["romance"])
        self.assertEqual(mood_search.genres_for_query("भूत"), ["horror"])

    def test_genres_are_deduped_in_first_seen_order(self):
        self.assertEqual(mood_search.genres_for_query("funny comedy"),
                         ["comedy"])
        self.assertEqual(mood_search.genres_for_query("love romance"),
                         ["romance", "drama"])


class StripMoodWordsTests(unittest.TestCase):
    def test_pure_mood_leaves_no_literal_remainder(self):
        self.assertEqual(mood_search.strip_mood_words("something funny"), "")
        self.assertEqual(
            mood_search.strip_mood_words("something funny to watch tonight"), "")
        self.assertEqual(mood_search.strip_mood_words("sad love story"), "")

    def test_mixed_query_keeps_only_the_literal_remainder(self):
        self.assertEqual(
            mood_search.strip_mood_words("sad love story about a dog"),
            "about dog")
        self.assertEqual(
            mood_search.strip_mood_words("The Comedy of Errors"), "errors")

    def test_a_title_query_keeps_only_its_non_mood_words(self):
        # "dark" is a mood word, so it is stripped here — the search layer
        # is what protects the title, by searching the remainder
        # ("knight") literally first instead of filtering by the mood.
        self.assertEqual(mood_search.strip_mood_words("dune"), "dune")
        self.assertEqual(mood_search.strip_mood_words("the dark knight"),
                         "knight")


if __name__ == "__main__":
    unittest.main()
