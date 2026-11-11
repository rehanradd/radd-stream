"""Offline tests for "Did you mean" (Gap A4).

The correction itself is the omnibox fuzzy machinery's — a 3-gram
candidate pass over `clean_title`, then a true edit-distance check in
Python. This module only turns that output into the one string the UI
shows, and only for the tokens the catalog can vouch for. A token with
no close title word is left exactly as typed, and a suggestion never
names a title the public surface hides.
"""

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import did_you_mean


class DidYouMeanTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, clean_title TEXT,"
            " is_18_plus INTEGER NOT NULL DEFAULT 0)")
        for post_id, title in (
                (1, "Inception"),
                (2, "Dune"),
                (3, "Avatar"),
                (4, "The Dark Knight"),
                (5, "Avengers Endgame")):
            self.conn.execute(
                "INSERT INTO posts (id, clean_title, is_18_plus) VALUES (?, ?, 0)",
                (post_id, title))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_one_edit_away_corrects(self):
        self.assertEqual(did_you_mean.correct_token(self.conn, "incepton"),
                         "inception")
        self.assertEqual(did_you_mean.correct_token(self.conn, "avngers"),
                         "avengers")
        self.assertEqual(did_you_mean.correct_token(self.conn, "dunne"),
                         "dune")

    def test_an_exact_title_word_needs_no_correction(self):
        self.assertIsNone(did_you_mean.correct_token(self.conn, "dune"))
        self.assertIsNone(did_you_mean.correct_token(self.conn, "inception"))
        self.assertIsNone(did_you_mean.correct_token(self.conn, "avatar"))

    def test_short_tokens_and_unknown_words_never_correct(self):
        self.assertIsNone(did_you_mean.correct_token(self.conn, "it"))
        self.assertIsNone(did_you_mean.correct_token(self.conn, "up"))
        self.assertIsNone(did_you_mean.correct_token(self.conn, "zzzzqq"))
        self.assertIsNone(did_you_mean.correct_token(self.conn, ""))

    def test_two_edits_away_is_not_a_correction(self):
        self.assertIsNone(did_you_mean.correct_token(self.conn, "incepto"))
        self.assertIsNone(did_you_mean.correct_token(self.conn, "avngrzx"))

    def test_old_title_corrects_despite_newer_crowd(self):
        # Recall: the old newest-first window let 200 newer rows
        # sharing one gram ("ave") crowd "Avengers Endgame" out, so
        # "avengrs" / "avengerss" got no correction. Relevance
        # ordering must surface the old title anyway. The limit=200
        # call matters: with 250 crowd rows the window truncates, so
        # only the ordering can save the old title — a test at the
        # default limit would pass even with a broken score.
        for i in range(10, 260):
            self.conn.execute(
                "INSERT INTO posts (id, clean_title, is_18_plus)"
                " VALUES (?, ?, 0)", (i, f"Avenue {i}"))
        self.conn.commit()
        self.assertEqual(
            did_you_mean.correct_token(self.conn, "avengrs", limit=200),
            "avengers")
        self.assertEqual(
            did_you_mean.correct_token(self.conn, "avengerss", limit=200),
            "avengers")
        self.assertEqual(did_you_mean.correct_token(self.conn, "avengrs"),
                         "avengers")
        self.assertEqual(did_you_mean.correct_token(self.conn, "avengerss"),
                         "avengers")
        suggestion = did_you_mean.suggest_correction(self.conn, "avengrs")
        self.assertEqual(suggestion["query"], "avengers")

    def test_exact_word_wins_over_newer_misspelling(self):
        # A newer misspelling sharing every gram ("batmann") must not
        # outrank the exact title word ("batman").
        self.conn.execute(
            "INSERT INTO posts (id, clean_title, is_18_plus)"
            " VALUES (6, 'Batman Begins', 0)")
        self.conn.execute(
            "INSERT INTO posts (id, clean_title, is_18_plus)"
            " VALUES (7, 'Batmann Returns', 0)")
        self.conn.commit()
        self.assertIsNone(did_you_mean.correct_token(self.conn, "batman"))

    def test_suggest_correction_rebuilds_the_query(self):
        suggestion = did_you_mean.suggest_correction(self.conn, "incepton")
        self.assertEqual(suggestion["query"], "inception")
        self.assertEqual(suggestion["corrected_tokens"], {"incepton": "inception"})

    def test_partial_correction_keeps_the_good_tokens(self):
        suggestion = did_you_mean.suggest_correction(self.conn, "incepton 2")
        self.assertEqual(suggestion["query"], "inception 2")
        self.assertEqual(suggestion["corrected_tokens"], {"incepton": "inception"})

    def test_a_clean_query_has_no_suggestion(self):
        self.assertIsNone(did_you_mean.suggest_correction(self.conn, "dune"))
        self.assertIsNone(did_you_mean.suggest_correction(self.conn, ""))
        self.assertIsNone(did_you_mean.suggest_correction(self.conn, "   "))

    def test_a_flagged_title_is_never_suggested(self):
        self.conn.execute(
            "INSERT INTO posts (id, clean_title, is_18_plus) VALUES (6, 'Secret Adult Film', 1)")
        self.conn.commit()
        # One edit away from the flagged title — and from nothing public.
        self.assertIsNone(did_you_mean.correct_token(self.conn, "secrt"))
        self.assertIsNone(
            did_you_mean.suggest_correction(self.conn, "secrt adult film"))

    def test_a_database_without_a_posts_table_has_no_suggestion(self):
        empty = sqlite3.connect(":memory:")
        try:
            self.assertIsNone(did_you_mean.correct_token(empty, "incepton"))
            self.assertIsNone(
                did_you_mean.suggest_correction(empty, "incepton"))
        finally:
            empty.close()


if __name__ == "__main__":
    unittest.main()
