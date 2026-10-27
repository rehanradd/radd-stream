#!/usr/bin/env python3
"""Offline tests for `backfill_tmdb.py` and the `season_artwork` wire shape.

Nothing here opens a socket: the HTTP client is replaced by a fake that returns
canned TMDB payloads, and the database is a temporary file. The tests pin the
three decisions that can quietly produce wrong artwork if they drift:

* a title search must not accept a different work (year/title guard);
* a season without its own poster must not inherit the work's poster;
* only public art CDNs may leave the API, because season rows have no
  `posts.poster_url` fallback behind `/api/v1/art`.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import backfill_tmdb as tmdb
import fast_fetch
import viewer

TV_DETAIL = {
    "id": 99,
    "poster_path": "/root.jpg",
    "backdrop_path": "/backdrop-1.jpg",
    "images": {
        "posters": [],
        "backdrops": [
            {"file_path": "/backdrop-2.jpg", "vote_average": 5.0,
             "vote_count": 10, "iso_639_1": None},
        ],
    },
    "external_ids": {"imdb_id": "tt1234567"},
    "seasons": [
        {"season_number": 0, "poster_path": "/specials.jpg", "episode_count": 1},
        {"season_number": 1, "poster_path": "/season-1.jpg", "episode_count": 2},
        {"season_number": 2, "poster_path": None, "episode_count": 1},
    ],
}

SEASON_PAYLOADS = {
    1: {
        "poster_path": "/season-1.jpg",
        "images": {"posters": []},
        "episodes": [
            {"episode_number": 1, "still_path": "/still-1-1.jpg"},
            {"episode_number": 2, "still_path": None},
        ],
    },
    2: {
        "poster_path": None,
        "images": {"posters": [
            {"file_path": "/season-2.jpg", "vote_average": 7.0,
             "vote_count": 4, "iso_639_1": "en"},
        ]},
        "episodes": [
            {"episode_number": 1, "still_path": "/still-2-1.jpg"},
        ],
    },
}


class FakeClient:
    def __init__(self, *, detail=None, seasons=None, find=None, search=None):
        self._detail = detail
        self._seasons = seasons or SEASON_PAYLOADS
        self._find = find
        self._search = search
        self.calls = []

    def detail(self, kind, tmdb_id):
        self.calls.append(("detail", kind, tmdb_id))
        return self._detail

    def season(self, tmdb_id, number):
        self.calls.append(("season", tmdb_id, number))
        return self._seasons.get(number)

    def find(self, imdb_id):
        self.calls.append(("find", imdb_id))
        return self._find

    def search(self, kind, query, year):
        self.calls.append(("search", kind, query, year))
        return self._search


def post_row(**overrides):
    row = {
        "id": 7,
        "title": "Example Show (2020) Complete Series",
        "clean_title": "Example Show",
        "year": 2020,
        "content_type": "series",
        "seasons": "Season 1",
        "poster_url": None,
        "backdrop_urls": None,
        "tmdb_id": None,
        "imdb_id": None,
        "genres": None,
        "synopsis": None,
        "imdb_rating": None,
    }
    row.update(overrides)
    return row


CINEMETA_META = {
    "id": "tt1234567",
    "name": "Example Show",
    "type": "series",
    "year": "2020",
    "genres": ["Drama", "Mystery"],
    "description": "A show about examples.",
    "poster": "https://images.metahub.space/poster/medium/tt1234567/img",
    "background": "https://images.metahub.space/background/medium/tt1234567/img",
    "imdbRating": "8.1",
}


class FakeCinemeta:
    def __init__(self, meta=None, error=None):
        self._meta = meta
        self._error = error
        self.calls = []

    def lookup(self, *, imdb_id=None, titles=(), year=None, series=False):
        self.calls.append({"imdb_id": imdb_id, "titles": tuple(titles),
                           "year": year, "series": series})
        if self._error is not None:
            raise self._error
        return self._meta


class TextHelperTests(unittest.TestCase):
    def test_parse_year_reads_labels_and_integers(self):
        self.assertEqual(tmdb.parse_year("2003–2006"), 2003)
        self.assertEqual(tmdb.parse_year(2019), 2019)
        self.assertIsNone(tmdb.parse_year("n/a"))
        self.assertIsNone(tmdb.parse_year(None))
        self.assertIsNone(tmdb.parse_year(12))

    def test_strip_title_noise_leaves_a_real_title_alone(self):
        self.assertEqual(tmdb.strip_title_noise("Hindi Medium (2017)"), "Hindi Medium")
        self.assertEqual(tmdb.strip_title_noise("English Vinglish"), "English Vinglish")
        self.assertEqual(
            tmdb.strip_title_noise(
                "Download Equinox (Season 1) English with Substitle Netflix Series "
                "480p 720p & 1080p WEB-DL | Vegamovies.gallery"),
            "Equinox",
        )
        self.assertEqual(
            tmdb.strip_title_noise("The Diplomat (Season 1–4) [Hindi + English] "
                                   "Dual Audio (2023–2026) Complete Netflix Series"),
            "The Diplomat",
        )

    def test_normalize_title_ignores_case_punctuation_and_width(self):
        self.assertEqual(tmdb.normalize_title("The Punisher"),
                         tmdb.normalize_title("the  PUNISHER!"))
        self.assertEqual(tmdb.normalize_title("Fast & Furious"),
                         tmdb.normalize_title("Fast and Furious"))

    def test_normalize_imdb_id_rejects_anything_else(self):
        self.assertEqual(tmdb.normalize_imdb_id(" TT1234567 "), "tt1234567")
        self.assertIsNone(tmdb.normalize_imdb_id("https://example.test/tt1234567"))

    def test_normalize_rating_accepts_decimals_and_rejects_noise(self):
        self.assertEqual(tmdb.normalize_rating("8.1"), "8.1")
        self.assertEqual(tmdb.normalize_rating("7.8/10"), "7.8")
        self.assertEqual(tmdb.normalize_rating(6), "6.0")
        self.assertIsNone(tmdb.normalize_rating("0"))
        self.assertIsNone(tmdb.normalize_rating("N/A"))
        self.assertIsNone(tmdb.normalize_rating("."))
        self.assertIsNone(tmdb.normalize_rating(None))


class CandidateTests(unittest.TestCase):
    def test_same_title_and_year_wins(self):
        payload = {"results": [
            {"name": "The Diplomat", "first_air_date": "2013-01-01"},
            {"name": "The Diplomat", "first_air_date": "2023-04-20"},
        ]}
        picked = tmdb.choose_candidate(payload, query="The Diplomat", year=2023)
        self.assertEqual(picked["first_air_date"], "2023-04-20")

    def test_a_remake_is_not_the_same_work(self):
        payload = {"results": [
            {"title": "The Thing", "release_date": "1982-06-25"},
        ]}
        self.assertIsNone(tmdb.choose_candidate(payload, query="The Thing", year=2011))

    def test_tmdb_country_suffix_matches_by_prefix(self):
        payload = {"results": [
            {"name": "The Office", "first_air_date": "2005-03-24"},
        ]}
        picked = tmdb.choose_candidate(payload, query="The Office", year=2005)
        self.assertIsNotNone(picked)

    def test_adult_result_is_never_picked(self):
        payload = {"results": [
            {"name": "Example Show", "first_air_date": "2020-01-01", "adult": True},
        ]}
        self.assertIsNone(tmdb.choose_candidate(payload, query="Example Show", year=2020))

    def test_find_prefers_the_catalogued_medium(self):
        payload = {
            "movie_results": [{"id": 1}],
            "tv_results": [{"id": 2}],
        }
        self.assertEqual(tmdb.choose_find_result(payload, want_tv=True), ("tv", {"id": 2}))
        self.assertEqual(tmdb.choose_find_result(payload, want_tv=False), ("movie", {"id": 1}))


class SeasonArtworkTests(unittest.TestCase):
    def test_each_season_gets_its_own_poster_and_stills(self):
        rows = tmdb.season_artwork(7, TV_DETAIL, lambda n: SEASON_PAYLOADS.get(n))
        posters = [row for row in rows if row.kind == "season_poster"]
        stills = [row for row in rows if row.kind == "episode_still"]
        self.assertEqual([row.season_number for row in posters], [1, 2])
        self.assertEqual([row.url for row in posters], [
            "https://image.tmdb.org/t/p/w500/season-1.jpg",
            "https://image.tmdb.org/t/p/w500/season-2.jpg",
        ])
        self.assertEqual(
            [(row.season_number, row.episode_number) for row in stills],
            [(1, 1), (2, 1)],
        )

    def test_specials_are_skipped_unless_asked_for(self):
        rows = tmdb.season_artwork(7, TV_DETAIL, lambda n: SEASON_PAYLOADS.get(n))
        self.assertNotIn(0, [row.season_number for row in rows])
        with_specials = tmdb.season_artwork(
            7, TV_DETAIL, lambda n: SEASON_PAYLOADS.get(n), include_specials=True)
        self.assertIn(0, [row.season_number for row in with_specials])

    def test_a_season_without_a_poster_never_inherits_the_work_poster(self):
        detail = dict(TV_DETAIL)
        detail["seasons"] = [{"season_number": 3, "poster_path": None,
                              "episode_count": 1}]
        rows = tmdb.season_artwork(7, detail, lambda n: None)
        posters = [row for row in rows if row.kind == "season_poster"]
        self.assertEqual(posters, [])
        self.assertNotIn("root.jpg", json.dumps([row.url for row in rows]))

    def test_no_stills_still_maps_season_posters(self):
        rows = tmdb.season_artwork(
            7, TV_DETAIL, lambda n: SEASON_PAYLOADS.get(n), want_stills=False)
        self.assertEqual({row.kind for row in rows}, {"season_poster"})
        self.assertEqual(len(rows), 2)


class PlanPostTests(unittest.TestCase):
    def test_stored_tmdb_id_is_used_without_a_search(self):
        client = FakeClient(detail=TV_DETAIL)
        plan = tmdb.plan_post(post_row(tmdb_id=99), client)
        self.assertEqual(plan.outcome, "matched-stored-id")
        self.assertEqual(plan.updates["poster_url"],
                         "https://image.tmdb.org/t/p/w500/root.jpg")
        self.assertEqual(json.loads(plan.updates["backdrop_urls"]), [
            "https://image.tmdb.org/t/p/w1280/backdrop-1.jpg",
            "https://image.tmdb.org/t/p/w1280/backdrop-2.jpg",
        ])
        self.assertTrue(all(call[0] != "search" for call in client.calls))
        self.assertEqual(len([row for row in plan.artwork
                              if row.kind == "season_poster"]), 2)

    def test_imdb_lookup_wins_over_a_title_search(self):
        found = {"tv_results": [{"id": 99}], "movie_results": []}
        client = FakeClient(detail=TV_DETAIL, find=found)
        plan = tmdb.plan_post(post_row(imdb_id="tt1234567"), client)
        self.assertEqual(plan.outcome, "matched-imdb")
        self.assertTrue(any(call[0] == "find" for call in client.calls))
        self.assertFalse(any(call[0] == "search" for call in client.calls))

    def test_title_search_is_the_last_resort(self):
        client = FakeClient(
            detail=TV_DETAIL,
            search={"results": [{"id": 99, "name": "Example Show",
                                 "first_air_date": "2020-01-01"}]},
        )
        plan = tmdb.plan_post(post_row(), client)
        self.assertEqual(plan.outcome, "matched-title")
        self.assertEqual(plan.updates["tmdb_id"], 99)
        self.assertEqual(plan.updates["imdb_id"], "tt1234567")

    def test_no_candidate_writes_nothing(self):
        plan = tmdb.plan_post(post_row(), FakeClient(search={"results": []}))
        self.assertEqual(plan.outcome, "no-match")
        self.assertEqual(plan.updates, {})
        self.assertEqual(plan.artwork, [])

    def test_existing_root_art_is_left_alone_without_force(self):
        client = FakeClient(detail=TV_DETAIL)
        row = post_row(
            tmdb_id=99,
            imdb_id="tt1234567",
            poster_url="https://image.tmdb.org/t/p/w500/existing.jpg",
            backdrop_urls='["https://image.tmdb.org/t/p/w1280/existing.jpg"]',
        )
        plan = tmdb.plan_post(row, client)
        self.assertEqual(plan.updates, {})
        self.assertTrue(plan.artwork)

    def test_force_replaces_root_art(self):
        client = FakeClient(detail=TV_DETAIL)
        row = post_row(
            tmdb_id=99,
            poster_url="https://image.tmdb.org/t/p/w500/existing.jpg",
            backdrop_urls='["https://image.tmdb.org/t/p/w1280/existing.jpg"]',
        )
        plan = tmdb.plan_post(row, client, force=True)
        self.assertEqual(plan.updates["poster_url"],
                         "https://image.tmdb.org/t/p/w500/root.jpg")


class CinemetaFallbackTests(unittest.TestCase):
    def test_year_reads_a_release_range(self):
        self.assertEqual(tmdb.cinemeta_year({"releaseInfo": "2020–2023"}), 2020)
        self.assertEqual(tmdb.cinemeta_year({"year": "2019"}), 2019)
        self.assertIsNone(tmdb.cinemeta_year({"releaseInfo": "n/a"}))

    def test_search_candidate_must_match_title_and_year(self):
        payload = {"metas": [
            {"id": "tt-old", "name": "The Thing", "releaseInfo": "1982"},
            {"id": "tt-new", "name": "The Thing", "releaseInfo": "2011"},
        ]}
        picked = tmdb.choose_cinemeta_candidate(payload, query="The Thing", year=2011)
        self.assertEqual(picked["id"], "tt-new")
        self.assertIsNone(
            tmdb.choose_cinemeta_candidate(payload, query="Another Film", year=2011))

    def test_meta_fills_only_what_is_missing(self):
        row = post_row()
        updates = tmdb.cinemeta_updates(row, CINEMETA_META)
        self.assertEqual(json.loads(updates["genres"]), ["Drama", "Mystery"])
        self.assertEqual(updates["synopsis"], "A show about examples.")
        self.assertEqual(updates["imdb_id"], "tt1234567")
        self.assertEqual(updates["imdb_rating"], "8.1")
        self.assertEqual(updates["poster_url"], CINEMETA_META["poster"])
        self.assertEqual(json.loads(updates["backdrop_urls"]),
                         [CINEMETA_META["background"]])
        self.assertNotIn("year", updates)  # the row already says 2020

    def test_stored_facts_are_never_overwritten(self):
        row = post_row(
            genres='["Comedy"]',
            synopsis="Stored synopsis",
            poster_url="https://img.example/p.jpg",
            backdrop_urls='["https://img.example/b.jpg"]',
            imdb_id="tt1234567",
            imdb_rating="8.1",
        )
        self.assertEqual(tmdb.cinemeta_updates(row, CINEMETA_META), {})

    def test_no_tmdb_client_uses_cinemeta(self):
        fallback = FakeCinemeta(meta=CINEMETA_META)
        plan = tmdb.plan_post(post_row(), None, fallback=fallback)
        self.assertEqual(plan.outcome, "matched-cinemeta")
        self.assertEqual(json.loads(plan.updates["genres"]), ["Drama", "Mystery"])
        self.assertEqual(plan.updates["synopsis"], "A show about examples.")
        self.assertEqual(plan.artwork, [])
        self.assertEqual(fallback.calls[0]["titles"], ("Example Show",))
        self.assertTrue(fallback.calls[0]["series"])

    def test_tmdb_match_with_missing_metadata_consults_cinemeta(self):
        client = FakeClient(detail=TV_DETAIL)
        fallback = FakeCinemeta(meta=CINEMETA_META)
        plan = tmdb.plan_post(post_row(tmdb_id=99), client, fallback=fallback)
        self.assertEqual(plan.outcome, "matched-stored-id")
        # TMDB still owns the art; Cinemeta fills the fields TMDB's path ignores.
        self.assertEqual(plan.updates["poster_url"],
                         "https://image.tmdb.org/t/p/w500/root.jpg")
        self.assertEqual(json.loads(plan.updates["genres"]), ["Drama", "Mystery"])
        self.assertEqual(plan.updates["synopsis"], "A show about examples.")
        self.assertEqual(len(fallback.calls), 1)

    def test_complete_row_does_not_call_cinemeta(self):
        client = FakeClient(detail=TV_DETAIL)
        fallback = FakeCinemeta(meta=CINEMETA_META)
        row = post_row(tmdb_id=99, imdb_id="tt1234567",
                       genres='["Drama"]', synopsis="Known.", imdb_rating="8.1")
        plan = tmdb.plan_post(row, client, fallback=fallback)
        self.assertEqual(fallback.calls, [])
        self.assertEqual(plan.outcome, "matched-stored-id")

    def test_cinemeta_failure_keeps_the_tmdb_plan(self):
        client = FakeClient(detail=TV_DETAIL)
        fallback = FakeCinemeta(error=tmdb.CinemetaError("unreachable"))
        plan = tmdb.plan_post(post_row(tmdb_id=99), client, fallback=fallback)
        self.assertEqual(plan.outcome, "matched-stored-id")
        self.assertIn("poster_url", plan.updates)

    def test_a_placeholder_rating_is_treated_as_missing(self):
        row = post_row(genres='["Drama"]', synopsis="Known.",
                       imdb_id="tt1234567", imdb_rating=".")
        updates = tmdb.cinemeta_updates(row, CINEMETA_META)
        self.assertEqual(updates["imdb_rating"], "8.1")

    def test_candidate_sql_only_widens_for_the_fallback(self):
        columns = {"id", "title", "clean_title", "year", "content_type", "seasons",
                   "poster_url", "backdrop_urls", "genres", "synopsis", "is_18_plus"}
        with_fallback = tmdb.candidate_sql(columns, art_table=True, force=False,
                                           fallback=True)
        without = tmdb.candidate_sql(columns, art_table=True, force=False,
                                     fallback=False)
        self.assertIn("p.genres", with_fallback)
        self.assertIn("p.synopsis", with_fallback)
        self.assertNotIn("p.genres", without)

    def test_lookup_prefers_imdb_identity_over_search(self):
        class StubClient(tmdb.CinemetaClient):
            def __init__(self):
                self.calls = []

            def meta(self, kind, imdb_id):
                self.calls.append(("meta", kind, imdb_id))
                return CINEMETA_META if kind == "series" else None

            def search(self, kind, query):
                self.calls.append(("search", kind, query))
                return {"metas": []}

        client = StubClient()
        meta = client.lookup(imdb_id="tt1234567", titles=("Example Show",),
                             year=2020, series=True)
        self.assertEqual(meta, CINEMETA_META)
        self.assertEqual(client.calls, [("meta", "series", "tt1234567")])


class DatabaseAndWireTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "catalog.db"
        self.fast_patch = patch.object(fast_fetch, "DB_PATH", self.db_path)
        self.viewer_patch = patch.object(viewer, "DB_PATH", self.db_path)
        self.fast_patch.start()
        self.viewer_patch.start()
        fast_fetch.init_db()
        with fast_fetch.get_db() as conn:
            conn.execute(
                "INSERT INTO posts (url, title, clean_title, year, content_type, "
                "seasons, poster_url, is_18_plus) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                ("https://site.example/show/", "Example Show", "Example Show",
                 2020, "series", "Season 1", None),
            )
            self.post_id = conn.execute("SELECT id FROM posts").fetchone()[0]

    def tearDown(self):
        self.viewer_patch.stop()
        self.fast_patch.stop()
        self.temp_dir.cleanup()

    def test_apply_plan_upserts_and_force_replaces_tmdb_rows(self):
        row = post_row(id=self.post_id, content_type="series")
        plan = tmdb.PostPlan(
            post_id=self.post_id,
            updates={"poster_url": "https://image.tmdb.org/t/p/w500/p.jpg",
                     "backdrop_urls": '["https://image.tmdb.org/t/p/w1280/b.jpg"]'},
            artwork=[tmdb.ArtworkRow(self.post_id, "season_poster", 1, 0,
                                     "https://image.tmdb.org/t/p/w500/s1.jpg")],
            outcome="matched-stored-id",
        )
        with fast_fetch.get_db() as conn:
            with conn:
                written = tmdb.apply_plan(conn, plan, force=False,
                                           columns=tmdb.post_columns(conn))
            self.assertEqual(written, 1)
            stored = conn.execute("SELECT poster_url FROM posts WHERE id = ?",
                                  (self.post_id,)).fetchone()[0]
            self.assertEqual(stored, plan.updates["poster_url"])
            count = conn.execute("SELECT COUNT(*) FROM post_artwork").fetchone()[0]
            self.assertEqual(count, 1)

        plan.artwork = [tmdb.ArtworkRow(self.post_id, "season_poster", 1, 0,
                                        "https://image.tmdb.org/t/p/w500/new.jpg")]
        with fast_fetch.get_db() as conn:
            with conn:
                tmdb.apply_plan(conn, plan, force=True, columns=tmdb.post_columns(conn))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM post_artwork").fetchone()[0], 1)
            url = conn.execute("SELECT url FROM post_artwork").fetchone()[0]
            self.assertTrue(url.endswith("/new.jpg"))

    def test_detail_route_publishes_public_season_art_only(self):
        with fast_fetch.get_db() as conn:
            conn.executemany(
                "INSERT INTO post_artwork (post_id, kind, season_number, "
                "episode_number, url) VALUES (?, ?, ?, ?, ?)",
                [
                    (self.post_id, "season_poster", 1, 0,
                     "https://image.tmdb.org/t/p/w500/s1.jpg"),
                    (self.post_id, "episode_still", 1, 1,
                     "https://image.tmdb.org/t/p/w300/e1.jpg"),
                    (self.post_id, "season_poster", 2, 0,
                     "https://img.site.example/s2.jpg"),
                ],
            )
        detail = viewer.api_v1_get_post_detail(self.post_id, base_url="http://box")
        self.assertIsNotNone(detail)
        art = detail["season_artwork"]
        self.assertEqual(
            [(item["kind"], item["season"], item["episode"]) for item in art],
            [("season_poster", 1, 0), ("episode_still", 1, 1)],
        )
        self.assertTrue(all(item["url"].startswith("https://image.tmdb.org/")
                            for item in art))

    def test_adult_post_never_publishes_season_art(self):
        with fast_fetch.get_db() as conn:
            conn.execute("UPDATE posts SET is_18_plus = 1 WHERE id = ?", (self.post_id,))
            conn.execute(
                "INSERT INTO post_artwork (post_id, kind, season_number, "
                "episode_number, url) VALUES (?, 'season_poster', 1, 0, ?)",
                (self.post_id, "https://image.tmdb.org/t/p/w500/s1.jpg"),
            )
        self.assertIsNone(viewer.api_v1_get_post_detail(self.post_id))

    def test_missing_artwork_table_is_an_honest_empty_list(self):
        with fast_fetch.get_db() as conn:
            conn.execute("DROP TABLE post_artwork")
        detail = viewer.api_v1_get_post_detail(self.post_id, base_url="http://box")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["season_artwork"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
