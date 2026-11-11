#!/usr/bin/env python3
"""Tests for backfill_year_from_title.py (gap A17).

The ground-truth table is the full set of 44 blank-year posts whose title
carries any 19xx/20xx, measured on the live catalog 2026-11-11. The extractor
fills 22 of them safely and skips the other 22 (glued digits, decades, story
settings). If the catalog grows a new blank-year title with a year in it,
this table does not need to change — it pins the *rule*, not the catalog.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backfill_year_from_title as byt

MAX_YEAR = 2026

#: (title, expected year or None) — all 44 blank-year titles carrying a
#: 19xx/20xx on the live catalog, 2026-11-11.
GROUND_TRUTH = [
    ("Doraemon the Movie 2020: Nobita&#8217;s New Dinosaur", 2020),
    ("LEGO Ninjago: Dragons Rising (2023)", 2023),
    ("Doraemon the Movie 2024: Nobita&#8217;s Earth Symphony", 2024),
    ("Doraemon the Movie 2023: Nobita’s Sky Utopia", 2023),
    ("Ronja the Robber&#8217;s Daughter (2014)", 2014),
    ("Doraemon the Movie 2019: Nobita&#8217;s Chronicle of the Moon Exploration", 2019),
    ("Pokémon: The Movie 2000: The Power of One", 2000),
    ("Veergati (19950 Web", None),  # 1995 glued to a 0
    ("Dark Night 92026) Telugu ORG Movie HDRip | 1080p | 720p | 480p", None),
    ("Mithra Mandali 2025Telugu Full Movie HDTC | 1080p | 720p | 480p | HC-ESubs", None),
    ("WWE Monday Night Raw (15th September2025) NF English Full Show HDRip | 720p | 480p", None),
    ("WWE Friday Night SmackDown (28th March2025) English Full Show HDRip | 720p | 480p", None),
    ("The Beehive 2023Hindi ORG Dual Audio Movie HDRip | 720p | 480p | ESubs", None),
    ("Download Ghost in the Shell SAC_2045 (Season 1-2) Netflix Original Dual Audio "
     "{Hindi-English} 480p | 720p WEB-DL | Vegamovies.is", None),  # 2045 is a title fragment
    ("Dark Night 92026)", None),
    ("WWE Monday Night Raw (8th September2025) NF", None),
    ("WWE Friday Night SmackDown (28th March2025)", None),
    ("The Great Indian Kapil Show (26th July2025)", None),
    ("Waking Up to Danger 20211 WEB HD 800MB Hindi", None),  # 2021 glued to a 1
    ("Another Us2021 WEB HD 1GB Bengali", None),
    ("Another Us2021 WEB HD 850MB Telugu", None),
    ("Another Us2021 WEB HD 850MB Tamil", None),
    ("Jekyll and Hyde2021 WEB HD 700MB Hindi", None),
    ("M S Dhoni The Untold Story2016", None),
    ("Udeekan Teriyan (2023P Punjabi HD", None),  # 2023 glued to a P
    ("18+Delusyon 92025) Tagalong Vivamax", None),
    ("The Muse of Section E Book 2: The Dark Side (2025)", 2025),
    ("Once More Love in 1995", None),  # story setting, not release year
    ("Love Story in the 1970s", None),  # a decade, not a year
    ("Reborn in 2000: Crush on My Deskmate", None),  # story setting
    ("Shadow of Love (2026)", 2026),
    ("Smoke Blue no Ame Nochi Hare (2026)", 2026),
    ("Your Sky (2024)", 2024),
    ("Surely Tomorrow (2025)", 2025),
    ("Perfect 10 Liners (2024)", 2024),
    ("Make It Right 2026", 2026),
    ("When the Phone Rings (2024)", 2024),
    ("Derailment (2023)", 2023),
    ("The Legend of the Blue Sea (2016)", 2016),
    ("The Last Immortal (2023)", 2023),
    ("The One (2026)", 2026),
    ("Love Song in Winter (2024)", 2024),
    ("Our Yesterday’s Escape (2026)", 2026),
    ("Not Yours (2026)", 2026),
]


class ExtractYearTests(unittest.TestCase):
    def test_ground_truth_table(self):
        for title, expected in GROUND_TRUTH:
            with self.subTest(title=title):
                self.assertEqual(
                    byt.extract_year_from_title(title, max_year=MAX_YEAR),
                    expected)

    def test_extracts_22_of_the_44(self):
        extracted = [t for t, y in GROUND_TRUTH if y is not None]
        self.assertEqual(len(extracted), 22)

    def test_empty_and_none_titles(self):
        self.assertIsNone(byt.extract_year_from_title("", max_year=MAX_YEAR))
        self.assertIsNone(byt.extract_year_from_title(None, max_year=MAX_YEAR))

    def test_future_year_is_refused(self):
        self.assertIsNone(
            byt.extract_year_from_title("Some Film (2027)", max_year=MAX_YEAR))
        self.assertEqual(
            byt.extract_year_from_title("Some Film (2027)", max_year=2027), 2027)

    def test_first_safe_year_wins_when_the_first_is_a_story_setting(self):
        self.assertEqual(
            byt.extract_year_from_title("Love in 1995 (2024)", max_year=MAX_YEAR),
            2024)

    def test_year_before_a_colon_is_a_standalone_token(self):
        self.assertEqual(
            byt.extract_year_from_title("Doraemon the Movie 2020: Nobita",
                                        max_year=MAX_YEAR),
            2020)


class ScanAndApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "catalog.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT, year INTEGER)")
        conn.executemany(
            "INSERT INTO posts (id, title, year) VALUES (?,?,?)",
            [(1, "LEGO Ninjago: Dragons Rising (2023)", None),
             (2, "Another Us2021 WEB HD 1GB Bengali", None),
             (3, "Already Dated (2019)", 2019),
             (4, "No Year Here", None)])
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_writes_nothing(self):
        self.assertEqual(byt.main(["--db", str(self.db_path), "--max-year", "2026"]), 0)
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertIsNone(
                conn.execute("SELECT year FROM posts WHERE id=1").fetchone()[0])
        finally:
            conn.close()

    def test_apply_updates_only_the_safe_row(self):
        self.assertEqual(
            byt.main(["--db", str(self.db_path), "--max-year", "2026", "--apply"]), 0)
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = {r[0]: r[1] for r in conn.execute("SELECT id, year FROM posts")}
        finally:
            conn.close()
        self.assertEqual(rows[1], 2023)
        self.assertIsNone(rows[2])  # glued year, untouched
        self.assertEqual(rows[3], 2019)  # already dated, untouched
        self.assertIsNone(rows[4])  # no year, untouched

    def test_scan_counts(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            found, skipped, scanned = byt.scan(conn, max_year=MAX_YEAR, limit=None)
        finally:
            conn.close()
        self.assertEqual(scanned, 3)  # only blank-year rows
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0], (1, "LEGO Ninjago: Dragons Rising (2023)", 2023))
        self.assertEqual(skipped, 2)


if __name__ == "__main__":
    unittest.main()
