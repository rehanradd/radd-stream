#!/usr/bin/env python3
"""
test_themoviebox_gapfill.py — offline unit tests for the MovieBox year+genre
gap-fill (Session 126 follow-up).

No test touches the network: the feed is a mocked ``_api_request`` and every
DB is a temp file. The rules this suite keeps, and the measured fact each one
exists because of:

* every year walk hit the feed's 100-page cap (5,000 items), so each year
  cell holds more works than the walk returned — a year+genre cell has its
  own cap, and genre is a proven server-side filter (measured 2026-11-09:
  ``{"genre": "Action"}`` returned 44/44 items carrying Action).
* gap-fill harvests with ``sort=Latest`` — the only sort whose pages are
  disjoint works (unsorted pages reshuffle; ``Hot`` returns sports clips,
  ``newest`` concert mixes).
* a work the source vault already stages is a duplicate here, never
  re-staged: the follow-up vault holds only works the source lacks.
* the genre vocabulary comes from the source vault itself: the ``genres``
  column holds comma-joined combos (``Drama,Romance``) with case variants
  (``drama`` vs ``Drama``), so tokens are split, counted case-insensitively,
  and each keeps its most common spelling.
"""

from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_themoviebox as mb  # noqa: E402

NEW_ITEM = {
    "subjectId": "4242",
    "subjectType": 1,
    "title": "Gapfill Test Film",
    "description": "A film only the genre cell reaches.",
    "releaseDate": "2024-03-01",
    "duration": 5400,
    "genre": "Action",
    "cover": {"url": "https://pbcdnw.aoneroom.com/image/a.jpg"},
    "countryName": "United States",
    "detailPath": "gapfill-test-film-x1",
    "detailUrl": "", "sniffUrl": "", "sourceUrl": "", "dl": None,
    "isPornographic": False, "webHighRisk": False,
    "season": 0,
}


def silenced():
    return contextlib.redirect_stdout(io.StringIO())


def feed(items):
    """First feed request answers with `items`; every later one is empty."""
    first = (200, {"code": 0, "message": "ok", "data": {
        "items": items, "pager": {"hasMore": False, "nextPage": "2"}}})
    done = (200, {"code": 0, "message": "ok",
                  "data": {"items": [], "pager": {"hasMore": False}}})

    def side_effect(*args, **kwargs):
        side_effect.calls += 1
        return first if side_effect.calls == 1 else done

    side_effect.calls = 0
    return mock.MagicMock(side_effect=side_effect)


class GenreTokenTests(unittest.TestCase):
    def test_combos_split_case_folds_best_spelling_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "source.db"
            conn = sqlite3.connect(db)
            mb.ensure_schema(conn)
            for genres in ("Drama", "drama", "Drama,Romance", "Action",
                           "Action,Crime,Drama", ""):
                conn.execute(
                    "INSERT INTO posts (canonical_key, title, clean_title,"
                    " genres) VALUES (?, ?, ?, ?)",
                    (f"k-{genres}", "T", "T", genres))
            conn.commit()
            tokens = mb._genre_tokens(conn)
            conn.close()
        # Drama: 4 mentions (Drama x3, drama x1) spelled "Drama"; Action: 2;
        # Crime and Romance: 1 each, alphabetical on the tie.
        self.assertEqual(tokens, ["Drama", "Action", "Crime", "Romance"])

    def test_limit_caps_the_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "source.db"
            conn = sqlite3.connect(db)
            mb.ensure_schema(conn)
            for genres in ("Drama", "Action"):
                conn.execute(
                    "INSERT INTO posts (canonical_key, title, clean_title,"
                    " genres) VALUES (?, ?, ?, ?)",
                    (f"k-{genres}", "T", "T", genres))
            conn.commit()
            tokens = mb._genre_tokens(conn, limit=1)
            conn.close()
        # Equal counts sort alphabetically, so Action leads the cut.
        self.assertEqual(tokens, ["Action"])


class KnownKeysDedupTests(unittest.TestCase):
    def test_a_key_from_elsewhere_is_a_duplicate_not_a_restage(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            known = {mb.fast_fetch.generate_canonical_key(
                NEW_ITEM["title"], 2024)}
            with silenced(), \
                    mock.patch.object(mb, "memory_ok",
                                      return_value=(True, "ok")), \
                    mock.patch.object(mb, "_api_request", feed([NEW_ITEM])):
                totals = mb.harvest_catalog(db, known_keys=known)
            self.assertEqual(totals["posts"], 0, totals)
            self.assertEqual(totals["duplicates"], 1, totals)
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM posts").fetchone()[0], 0)
            conn.close()

    def test_without_known_keys_the_same_item_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "v.db"
            with silenced(), \
                    mock.patch.object(mb, "memory_ok",
                                      return_value=(True, "ok")), \
                    mock.patch.object(mb, "_api_request", feed([NEW_ITEM])):
                totals = mb.harvest_catalog(db)
            self.assertEqual(totals["posts"], 1, totals)
            conn = sqlite3.connect(db)
            row = conn.execute(
                "SELECT title FROM posts").fetchone()
            conn.close()
            self.assertEqual(row[0], "Gapfill Test Film")


class GapfillTests(unittest.TestCase):
    def test_one_cell_writes_only_what_the_source_lacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            target = Path(tmp) / "followup.db"
            conn = sqlite3.connect(source)
            mb.ensure_schema(conn)
            conn.execute(
                "INSERT INTO posts (canonical_key, title, clean_title,"
                " genres) VALUES (?, ?, ?, ?)",
                (mb.fast_fetch.generate_canonical_key("Gapfill Test Film",
                                                     2024),
                 "Gapfill Test Film", "Gapfill Test Film", "Action"))
            conn.commit()
            conn.close()
            # The feed names the same film (a duplicate) and one new one.
            twin = dict(NEW_ITEM, subjectId="9999")
            fresh = dict(NEW_ITEM, subjectId="4243", title="Gapfill Second",
                         detailPath="gapfill-second-x1")
            with silenced(), \
                    mock.patch.object(mb, "memory_ok",
                                      return_value=(True, "ok")), \
                    mock.patch.object(mb, "_api_request",
                                      feed([twin, fresh])):
                totals = mb.gapfill_catalog(target, source_db=source,
                                            years=[2024], genres=["Action"])
            self.assertEqual(totals["cells_done"], 1, totals)
            self.assertEqual(totals["posts"], 1, totals)
            self.assertEqual(totals["duplicates"], 1, totals)
            conn = sqlite3.connect(target)
            titles = {row[0] for row in conn.execute("SELECT title FROM posts")}
            conn.close()
            self.assertEqual(titles, {"Gapfill Second"})

    def test_gapfill_uses_sort_latest_in_the_filter_body(self):
        bodies = []

        def recording_api(path, payload, **kwargs):
            bodies.append(payload)
            return feed([])(path, payload, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            target = Path(tmp) / "followup.db"
            conn = sqlite3.connect(source)
            mb.ensure_schema(conn)
            conn.execute(
                "INSERT INTO posts (canonical_key, title, clean_title,"
                " genres) VALUES (?, ?, ?, ?)",
                ("k-1", "T", "T", "Action"))
            conn.commit()
            conn.close()
            with silenced(), \
                    mock.patch.object(mb, "memory_ok",
                                      return_value=(True, "ok")), \
                    mock.patch.object(mb, "_api_request",
                                      side_effect=recording_api):
                mb.gapfill_catalog(target, source_db=source,
                                   years=[2024], genres=["Action"])
        self.assertEqual(len(bodies), 1, bodies)
        self.assertEqual(bodies[0]["sort"], "Latest")
        self.assertEqual(bodies[0]["year"], "2024")
        self.assertEqual(bodies[0]["genre"], "Action")

    def test_no_genre_vocabulary_means_no_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            target = Path(tmp) / "followup.db"
            conn = sqlite3.connect(source)
            mb.ensure_schema(conn)
            conn.commit()
            conn.close()
            with silenced():
                totals = mb.gapfill_catalog(target, source_db=source,
                                            years=[2024])
            self.assertEqual(totals["cells_done"], 0, totals)
            self.assertIn("genre", totals["stop_reason"])


class ParseYearsTests(unittest.TestCase):
    def test_range_and_list_and_dedup(self):
        self.assertEqual(mb._parse_years("2019-2026"),
                         tuple(range(2019, 2027)))
        self.assertEqual(mb._parse_years("2024,2025"), (2024, 2025))
        self.assertEqual(mb._parse_years("2024,2024-2025"), (2024, 2025))
        self.assertEqual(mb._parse_years(None), mb.GAPFILL_YEARS)


class CliTests(unittest.TestCase):
    def test_recover_and_gapfill_defaults(self):
        args = mb.parse_args(["recover"])
        self.assertEqual(args.command, "recover")
        self.assertEqual(args.db, str(mb.DEFAULT_FOLLOWUP_DB_PATH))
        self.assertEqual(args.source_db, str(mb.DEFAULT_DB_PATH))
        args = mb.parse_args(["gapfill", "--years", "2024,2025",
                              "--genres", "Action,Drama"])
        self.assertEqual(args.command, "gapfill")
        self.assertEqual(args.years, "2024,2025")
        self.assertEqual(args.genres, "Action,Drama")
        self.assertEqual(args.max_genres, mb.GAPFILL_MAX_GENRES)


if __name__ == "__main__":
    unittest.main()
