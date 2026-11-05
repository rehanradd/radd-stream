"""test_producer_cleaner_fixes.py — order #75: three producer defects, pinned before fixed.

Crown doctrine (#52): the test ships first and must be verbatim RED against the unfixed
producer. Each class below says which assertion is the defect and which assertions are
characterization pins that must stay green through the fix — a pin that goes green only
because the fix widened something is a regression dressed as progress.

Offline, stdlib only. Run: python3 -S Fast_Fetch/test_producer_cleaner_fixes.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import import_katmoviehd as KM          # noqa: E402
import import_hindilinks4u as HL        # noqa: E402


# ---------------------------------------------------------------- (A)
class LeadingConjunctionTests(unittest.TestCase):
    """`_LEADING_DANGLE_RE` (import_katmoviehd.py:962-964) lists `and`; its own comment
    three lines above says the list is 'Deliberately *not* the/a/an/and'. The comment is
    the law, so `and` leaves the alternation and nothing else joins it."""

    def test_and_is_not_a_leading_dangle(self):
        self.assertIsNone(KM._LEADING_DANGLE_RE.match("And God Created Woman"))

    def test_and_god_created_woman_survives(self):
        self.assertEqual(KM.clean_katmoviehd_title("And God Created Woman")[0],
                         "And God Created Woman")

    def test_download_prefixed_and_title_survives(self):
        self.assertEqual(KM.clean_katmoviehd_title("Download And God Created Woman")[0],
                         "And God Created Woman")

    def test_and_title_with_parenthesised_year_survives(self):
        self.assertEqual(KM.clean_katmoviehd_title("And God Created Woman (1956)")[0],
                         "And God Created Woman")

    # --- characterization pins: the word boundary is load-bearing, and the fix must not
    # --- turn the strip into an article strip.
    def test_word_boundary_protects_words_starting_with_and(self):
        self.assertIsNone(KM._LEADING_DANGLE_RE.match("Andaz"))
        self.assertEqual(KM.clean_katmoviehd_title("Andaz")[0], "Andaz")

    def test_articles_are_still_never_stripped(self):
        # crown §1(A): do NOT widen the list to the/a/an — they open real titles.
        self.assertEqual(KM.clean_katmoviehd_title("The Family Star")[0], "The Family Star")
        self.assertEqual(KM.clean_katmoviehd_title("A Girl Upstairs")[0], "A Girl Upstairs")

    def test_remaining_prepositions_still_dangle(self):
        # Only `and` leaves the alternation; the rest of the list is unchanged, and this
        # pins that the fix did not quietly delete the whole rule.
        self.assertIsNotNone(KM._LEADING_DANGLE_RE.match("In the House"))
        self.assertIsNotNone(KM._LEADING_DANGLE_RE.match("Of Mice and Men"))


# ---------------------------------------------------------------- (B)
class Hl4uCloserTests(unittest.TestCase):
    """`import_hindilinks4u.py:328` strips brackets with the class `[\\(\\[\\]\\{\\}<>&]`,
    which contains `\\(` but no `\\)`: the opener goes, the closer is kept, and the catalog
    reads 'August 16 2023)'."""

    def test_closer_never_survives_a_year_glued_to_it(self):
        clean = HL.clean_hl4u_title("Download August 16 2023)")[0]
        self.assertNotIn(")", clean)

    def test_closer_never_survives_any_title(self):
        clean = HL.clean_hl4u_title("Dharma (The Chosen One)")[0]
        self.assertNotIn(")", clean)

    def test_no_bracket_character_survives(self):
        for raw in ("August 16 2023)", "Dharma (The Chosen One)",
                    "Xyz [2023] {abc} <d> &e"):
            clean = HL.clean_hl4u_title(raw)[0]
            for ch in "()[]{}<>":
                self.assertNotIn(ch, clean, f"{ch} survived in {raw!r} -> {clean!r}")

    def test_balanced_bracket_keeps_its_words(self):
        # The fix is a punctuation strip, NOT a bracket-group deletion: the alternate
        # name's words must remain in clean_title.
        clean = HL.clean_hl4u_title("Dharma (The Chosen One)")[0]
        for word in ("Chosen", "One"):
            self.assertIn(word, clean)

    def test_year_annotation_still_becomes_the_year_column(self):
        clean, year, key = HL.clean_hl4u_title("Space Jam (1996)")
        self.assertEqual(clean, "Space Jam")
        self.assertEqual(year, 1996)
        self.assertEqual(key, "space-jam_1996")


# ---------------------------------------------------------------- (C)
class SeasonNoiseTests(unittest.TestCase):
    """`_TITLE_NOISE_PATTERNS[9]` (import_katmoviehd.py:945-946) carries a bare `Season`
    alternative with no anchor, so it eats the final word of 'Mating Season'. Packaging
    means `Season <number>`; a word-final bare `Season` is a title word."""

    def test_word_final_season_survives(self):
        self.assertEqual(KM.clean_katmoviehd_title("Download Mating Season")[0],
                         "Mating Season")

    def test_season_is_not_eaten_when_other_junk_follows(self):
        self.assertIn("Season", KM.clean_katmoviehd_title("Mating Season (2026) S1 Hindi")[0])

    # --- characterization pins: packaging removal keeps working.
    def test_season_number_is_still_packaging(self):
        self.assertEqual(KM.clean_katmoviehd_title("Kadaisi Ulaga Por Season 2")[0],
                         "Kadaisi Ulaga Por")

    def test_season_number_and_complete_are_both_packaging(self):
        self.assertEqual(KM.clean_katmoviehd_title("Mating Season 1 Complete")[0], "Mating")

    def test_season_numeral_roman_is_packaging_without_stray_letters(self):
        clean = KM.clean_katmoviehd_title("Gadar Season III")[0]
        self.assertEqual(clean, "Gadar")

    def test_series_forms_are_untouched(self):
        self.assertEqual(KM.clean_katmoviehd_title("Kabir TV Series")[0], "Kabir")


if __name__ == "__main__":
    unittest.main(verbosity=2)
