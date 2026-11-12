#!/usr/bin/env python3
"""Offline tests for the FTS5 search index (`fts_posts` / `fts_posts_tri`).

The search-performance benchmark (2026-11-12) measured FTS5 (unicode61)
on `clean_title` + `cast_names` at 0.13 ms (`salaar`) to 26 ms
(`pushpa 2`) against ~1,000 ms for the 4x leading-wildcard LIKE, with
better bm25 relevance — and the trigram index at 15–52 ms for the
typo-correction pass against 903–1,424 ms for the LIKE-gram scan.
This suite pins the implementation of that winner:

1. **The index.** Built by `fts_posts.rebuild_fts`, kept in step by
   its six triggers, verified by `verify_fts`; absent or empty it
   must never answer (the search falls back to LIKE instead).
2. **The swap point.** `viewer._works_search_candidate_ids` answers
   from FTS5 when the index exists — title, multi-word, cast, and
   whole-word stopword queries — and answers the same sets from the
   LIKE fallback when it does not. The fallback is the old behaviour,
   only slower.
3. **The correction layer.** `did_you_mean` over the trigram index:
   `avengrs` → `avengers`, `salar` → `salaar` (exact-title evidence
   beats the served `salary`), `inceptoin` → `inception` (a
   transposition is one Damerau edit), and a flagged title is never
   suggested. The fuzzy fallback serves `Inception` for `inceptoin`
   through the same trigram pass.
4. **The adult rule.** A corroborated flagged work stays hidden on
   `/api/v1/works` with FTS5 engaged, and the fuzzy/correction paths
   never serve a flagged row.
5. **Latency.** The candidate-ids call for `salaar` / `pushpa 2`
   stays under 50 ms p50 on the fixture DB (the benchmark's live
   numbers are 0.13 ms / 26 ms; the fixture is small, so this pins
   the shape, not the scale).

    python3 -S Fast_Fetch/test_fts_posts.py
"""

import os
import sqlite3
import statistics
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import did_you_mean          # noqa: E402
import fast_fetch            # noqa: E402
import fts_posts             # noqa: E402
import redact                # noqa: E402
import search_fuzzy          # noqa: E402
import viewer                # noqa: E402

_BASELINE_NEEDLES = redact.needles()
_BASELINE_TEXT_NEEDLES = redact.text_needles()


class Fixture(unittest.TestCase):
    """A small ledger with the titles the benchmark measured, plus the
    adult and stopword shapes the works API pins. Ingested the way
    production ingests (`save_scraped_data`), except the flagged
    Kanguva twin, which is inserted directly under a different key —
    the way production files it.
    """

    FTS = False  # subclasses flip this to build the index in setUp

    def setUp(self):
        redact.set_needles(_BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.addCleanup(redact.set_needles, _BASELINE_NEEDLES,
                        _BASELINE_TEXT_NEEDLES)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
                        mock.patch.object(viewer, "DB_PATH", self.db_path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.addCleanup(viewer._WORKS_LIST_CACHE.clear)
        os.environ["RADD_STREAM_SECRET"] = "test-secret-for-fts-posts"
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        self.addCleanup(setattr, viewer, "_SIGNING_SECRET", None)
        self.addCleanup(lambda: redact.limiter._buckets.clear())
        self.salaar_a = self.ingest("Salaar", 2023, cast=["Prabhas"])
        self.salaar_b = self.ingest("Salaar Part 1 Ceasefire", 2023,
                                    cast=["Prabhas"])
        self.salaar_c = self.ingest("Salaar \u2013 1 \u2013 Ceasefire", 2024,
                                    cast=["Prabhas"])
        self.salaar_2 = self.ingest("Salaar 2", 2026, cast=["Prabhas"])
        self.salary = self.ingest("Salary Man", 2023, cast=["Someone"])
        self.inception = self.ingest("Inception", 2010,
                                     cast=["Leonardo DiCaprio"])
        self.avengers = self.ingest("Avengers Endgame", 2019,
                                    cast=["Robert Downey Jr."])
        self.avatar = self.ingest("Avatar", 2009, cast=["Sam Worthington"])
        self.dune = self.ingest("Dune", 2021, cast=["Timothee Chalamet"])
        self.dune_2 = self.ingest("Dune: Part Two", 2024,
                                  cast=["Timothee Chalamet"])
        self.godfather = self.ingest("The Godfather", 1972,
                                     cast=["Marlon Brando"])
        self.wandering = self.ingest("The Wandering Earth", 2019,
                                     cast=["Wu Jing"])
        self.other = self.ingest("Other Title", 2020, cast=["Someone"])
        self.together = self.ingest("Together", 2024, cast=["Someone"])
        self.jawan = self.ingest("Jawan", 2023, cast=["Shah Rukh Khan"])
        self.pushpa = self.ingest("Pushpa 2 The Rule", 2024,
                                  cast=["Allu Arjun"])
        self.deadpool = self.ingest("Deadpool", 2016, cast=["Ryan Reynolds"])
        self.deadloch = self.ingest("Deadloch", 2023, cast=["Kate Box"])
        self.undead = self.ingest("Undead Rising", 2023, cast=["Someone"])
        self.amelie = self.ingest("Am\u00e9lie", 2001, cast=["Audrey Tautou"])
        self.kanguva = self.ingest("Kanguva", 2024, cast=["Suriya"])
        self.kanguva_flagged = self.insert_flagged_twin()
        # A flagged title the correction must never suggest: one edit
        # away from a typo, and from nothing public.
        self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year,"
            " content_type, source_site, is_18_plus, canonical_key)"
            " VALUES (?, ?, ?, ?, 2023, 'movie', 'othercdn.site', 1, ?)",
            ("https://othercdn.site/movie/secret-adult-film-2023/",
             "secret-adult-film-2023", "Secret Adult Film (2023)",
             "Secret Adult Film", "secret-adult-film_2023"))
        self.conn.commit()
        if self.FTS:
            result = fts_posts.rebuild_fts(self.conn)
            self.assertEqual(result["posts"], result["fts_rows"])
            self.assertEqual(result["posts"], result["tri_rows"])
            self.assertTrue(fts_posts.fts_available(self.conn))
            self.assertTrue(fts_posts.trigram_available(self.conn))

    def ingest(self, title, year, cast=None):
        data = {
            "url": "https://somecdn.site/movie/%s-%d/"
                   % (title.lower().replace(" ", "-"), year),
            "slug": title.lower().replace(" ", "-"),
            "title": "%s (%d)" % (title, year),
            "clean_title": title,
            "year": year,
            "content_type": "movie",
            "poster_url": "https://cdn/poster.jpg",
            "genres": '["Action"]',
            "cast_names": str(list(cast or ["Someone"])).replace("'", '"'),
            "synopsis": "%s synopsis" % title,
            "is_18_plus": 0,
            "source_site": "somecdn.site",
            "industry": "Bollywood",
            "country": "India",
            "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(title, year),
            "releases": [{
                "release_title": "%s 720p" % title,
                "quality": "720p", "codec": "x264", "size": "1.5GB",
                "languages": '["Hindi"]',
                "season": "", "episode": "",
                "intermediate_url": "", "origin_url": "",
                "source_site": "somecdn.site",
                "sources": [{
                    "source_url": "https://cdn.example/%s.mp4" % title,
                    "quality": "720p", "status": "active"}]}],
        }
        post_id = fast_fetch.save_scraped_data(
            data, enrich_metadata=False, ensure_db=False)
        self.conn.commit()
        return post_id

    def insert_flagged_twin(self):
        """A flagged Kanguva twin under a different key whose title
        carries the corroborating evidence (`ullu`): the works
        grouping must hide the whole work."""
        cursor = self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year,"
            " content_type, source_site, is_18_plus, canonical_key,"
            " industry, country, language)"
            " VALUES (?, ?, ?, ?, 2024, 'movie', 'othercdn.site', 1,"
            " 'kanguva_2024_b', 'Bollywood', 'India', 'Tamil')",
            ("https://othercdn.site/movie/kanguva-ullu-2024/",
             "kanguva-ullu-2024", "Kanguva Ullu Original (2024)",
             "Kanguva Ullu Original"))
        post_id = cursor.lastrowid
        self.conn.execute(
            "INSERT INTO releases (post_id, release_title, quality,"
            " codec, size, languages, intermediate_url, source_site,"
            " origin_url) VALUES (?, ?, '720p', 'x264', '1.5GB',"
            " '[\"Tamil\"]', '', 'othercdn.site', '')",
            (post_id, "Kanguva Ullu Original 720p"))
        self.conn.commit()
        return post_id

    def candidate_ids(self, query):
        return set(viewer._works_search_candidate_ids(self.conn, query))


class FtsBuildTests(Fixture):
    FTS = True

    def test_absent_before_rebuild_available_after(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY,"
                     " clean_title TEXT, cast_names TEXT)")
        conn.execute("INSERT INTO posts VALUES (1, 'Salaar', '[\"Prabhas\"]')")
        self.assertFalse(fts_posts.fts_available(conn))
        self.assertFalse(fts_posts.trigram_available(conn))
        self.assertIsNone(fts_posts.search_candidate_ids(conn, "salaar"))
        result = fts_posts.rebuild_fts(conn)
        self.assertEqual((result["posts"], result["fts_rows"],
                          result["tri_rows"]), (1, 1, 1))
        self.assertTrue(fts_posts.fts_available(conn))
        self.assertTrue(fts_posts.trigram_available(conn))
        self.assertEqual(fts_posts.search_candidate_ids(conn, "salaar"), [1])
        conn.close()

    def test_rebuild_is_idempotent(self):
        first = fts_posts.rebuild_fts(self.conn)
        second = fts_posts.rebuild_fts(self.conn)
        self.assertEqual(first["posts"], second["posts"])
        self.assertEqual(first["fts_rows"], second["fts_rows"])
        self.assertEqual(fts_posts.verify_fts(self.conn), [])

    def test_insert_update_delete_keep_the_index_in_step(self):
        def find(token):
            return self.conn.execute(
                "SELECT rowid FROM fts_posts WHERE fts_posts MATCH ?",
                (f'"{token}"',)).fetchall()

        self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year,"
            " content_type, source_site, is_18_plus, canonical_key)"
            " VALUES ('https://seed.test/new', 'new', 'Quarterly Report (2024)',"
            " 'Quarterly Report', 2024, 'movie', 'seed.test', 0, 'quarterly_2024')")
        self.assertEqual(len(find("Quarterly")), 1,
                         "AFTER INSERT trigger is not firing")
        self.conn.execute("UPDATE posts SET clean_title = 'Twice Monthly'"
                          " WHERE slug = 'new'")
        self.assertEqual(len(find("Quarterly")), 0, "stale token still searchable")
        self.assertEqual(len(find("Monthly")), 1,
                         "AFTER UPDATE trigger did not reindex")
        self.conn.execute("DELETE FROM posts WHERE slug = 'new'")
        self.assertEqual(len(find("Monthly")), 0,
                         "AFTER DELETE trigger is not firing")
        self.conn.commit()
        self.assertEqual(fts_posts.verify_fts(self.conn), [])

    def test_verify_fails_on_a_dropped_trigger(self):
        self.conn.execute("DROP TRIGGER fts_posts_ai")
        self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year,"
            " content_type, source_site, is_18_plus, canonical_key)"
            " VALUES ('https://seed.test/orphan', 'orphan', 'Orphaned Record (2024)',"
            " 'Orphaned Record', 2024, 'movie', 'seed.test', 0, 'orphaned_2024')")
        self.conn.commit()
        failures = fts_posts.verify_fts(self.conn)
        self.assertTrue(failures, "a dropped trigger must fail verify")
        self.assertTrue(any("trigger" in f or "holds" in f for f in failures),
                        str(failures))

    def test_match_builder_shapes(self):
        self.assertEqual(fts_posts.build_match("pushpa 2"),
                         '"pushpa" AND "2"*')
        self.assertEqual(fts_posts.build_match("the", whole_word=True), '"the"')
        self.assertEqual(fts_posts.build_match("salaar"), '"salaar"*')
        self.assertEqual(fts_posts.build_match(""), "")
        self.assertEqual(fts_posts.build_match("   !!!   "), "")
        self.assertEqual(fts_posts.build_match("pushpa 2 the rule"),
                         '"pushpa" AND "2" AND "the" AND "rule"*')

    def test_diacritic_query_finds_the_folded_title(self):
        self.assertEqual(self.candidate_ids("amelie"), {self.amelie})


class WorksCandidateTests(Fixture):
    FTS = True

    def test_exact_title_finds_its_posts(self):
        self.assertEqual(
            self.candidate_ids("salaar"),
            {self.salaar_a, self.salaar_b, self.salaar_c, self.salaar_2})

    def test_multi_word_query_stays_precise(self):
        self.assertEqual(self.candidate_ids("pushpa 2"), {self.pushpa})
        self.assertEqual(self.candidate_ids("pushpa 2 the rule"), {self.pushpa})
        self.assertEqual(self.candidate_ids("dune part two"), {self.dune_2})

    def test_actor_search_uses_cast_names(self):
        self.assertEqual(self.candidate_ids("shah rukh khan"), {self.jawan})
        self.assertEqual(self.candidate_ids("prabhas"),
                         {self.salaar_a, self.salaar_b, self.salaar_c,
                          self.salaar_2})

    def test_stopword_matches_whole_words_only(self):
        ids = self.candidate_ids("the")
        self.assertIn(self.godfather, ids)
        self.assertIn(self.wandering, ids)
        self.assertNotIn(self.other, ids)
        self.assertNotIn(self.together, ids)

    def test_empty_and_punctuation_queries_answer_nothing_without_a_scan(self):
        self.assertEqual(self.candidate_ids(""), set())
        self.assertEqual(self.candidate_ids("   "), set())
        self.assertEqual(self.candidate_ids("!!!"), set())

    def test_nonsense_query_answers_nothing(self):
        self.assertEqual(self.candidate_ids("asdfghjkl"), set())

    def test_prefix_finds_deadpool_not_undead(self):
        # Prefix-on-last-token, the benchmark's search shape: `dead`
        # names titles starting with it, not titles containing it
        # mid-word. The LIKE fallback still answers the old substring
        # way — this is the one deliberate difference, and the
        # benchmark's relevance table is why (Deadpool in the top 3).
        self.assertEqual(self.candidate_ids("dead"),
                         {self.deadpool, self.deadloch})
        self.assertNotIn(self.undead, self.candidate_ids("dead"))


class FallbackAgreesTests(Fixture):
    """The same fixture WITHOUT the index: the LIKE fallback must
    answer the same candidate sets as FTS5 for the queries both
    shapes express — same contract, only slower."""

    def test_fallback_matches_fts_on_the_shared_queries(self):
        fts_fixture = WorksCandidateTests("test_exact_title_finds_its_posts")
        fts_fixture.setUp()
        try:
            for query, expected in (
                    ("salaar", {self.salaar_a, self.salaar_b, self.salaar_c,
                                self.salaar_2}),
                    ("pushpa 2", {self.pushpa}),
                    ("shah rukh khan", {self.jawan}),
                    ("the", None),
                    ("asdfghjkl", set())):
                like_ids = self.candidate_ids(query)
                fts_ids = fts_fixture.candidate_ids(query)
                self.assertEqual(like_ids, fts_ids, query)
                if expected is not None:
                    self.assertEqual(like_ids, expected, query)
        finally:
            # doCleanups, not tearDown: the fixture's temp dir, mock
            # patchers and cache clear live in addCleanup handlers,
            # which only doCleanups runs.
            fts_fixture.doCleanups()

    def test_stopword_fallback_matches_whole_words_only(self):
        ids = self.candidate_ids("the")
        self.assertIn(self.godfather, ids)
        self.assertIn(self.wandering, ids)
        self.assertNotIn(self.other, ids)
        self.assertNotIn(self.together, ids)


class CorrectionTests(Fixture):
    FTS = True

    def test_avengrs_corrects_to_avengers(self):
        self.assertEqual(did_you_mean.correct_token(self.conn, "avengrs"),
                         "avengers")

    def test_salar_corrects_to_salaar_not_salary(self):
        # Ambiguity, benchmark §3 fix 1: both are one edit away, but
        # `Salaar` IS a whole title and `Salary Man` is not.
        self.assertEqual(did_you_mean.correct_token(self.conn, "salar"),
                         "salaar")

    def test_transposition_corrects(self):
        # Benchmark §3 fix 2: Damerau-Levenshtein, transposition = 1 edit.
        self.assertEqual(did_you_mean.correct_token(self.conn, "inceptoin"),
                         "inception")

    def test_two_edits_away_still_never_corrects(self):
        self.assertIsNone(did_you_mean.correct_token(self.conn, "incepto"))
        self.assertIsNone(did_you_mean.correct_token(self.conn, "avngrzx"))

    def test_a_flagged_title_is_never_suggested_via_trigram(self):
        self.assertIsNone(did_you_mean.correct_token(self.conn, "secrt"))
        self.assertIsNone(
            did_you_mean.suggest_correction(self.conn, "secrt adult film"))

    def test_bare_title_beats_a_better_printed_multi_word_title(self):
        # Prints + mirrors are the tiebreak, not the decider: give
        # `Salary Man` five extra prints and `Salaar` must still win
        # on exact-title evidence.
        for _ in range(5):
            self.conn.execute(
                "INSERT INTO releases (post_id, release_title, quality,"
                " codec, size, languages, intermediate_url, source_site,"
                " origin_url) VALUES (?, 'Salary Man extra', '720p',"
                " 'x264', '1GB', '[\"Hindi\"]', '', 'somecdn.site', '')",
                (self.salary,))
        self.conn.commit()
        self.assertEqual(did_you_mean.correct_token(self.conn, "salar"),
                         "salaar")


class WorksEndToEndTests(Fixture):
    FTS = True

    def test_salaar_is_one_work_plus_its_sequel(self):
        resp = viewer.api_v1_get_works(query="salaar", limit=20)
        self.assertEqual(resp["total"], 2)
        work = next(i for i in resp["results"] if int(i["id"]) == self.salaar_a)
        self.assertEqual(work["post_ids"],
                         [self.salaar_a, self.salaar_b, self.salaar_c])

    def test_typo_with_hits_surfaces_did_you_mean_via_trigram(self):
        resp = viewer.api_v1_get_works(query="salar", limit=20)
        self.assertEqual([int(i["id"]) for i in resp["results"]],
                         [self.salary])
        self.assertEqual(resp["did_you_mean"], "salaar")

    def test_transposition_finds_the_film_through_the_fuzzy_fallback(self):
        resp = viewer.api_v1_get_posts(query="inceptoin", limit=10)
        self.assertEqual(resp["total"], 1)
        self.assertTrue(resp["fuzzy"])
        self.assertEqual(resp["results"][0]["clean_title"], "Inception")

    def test_flagged_work_stays_hidden_with_fts_engaged(self):
        resp = viewer.api_v1_get_works(query="kanguva", limit=20)
        self.assertEqual(resp["total"], 0)

    def test_stopword_route_matches_whole_words_only(self):
        resp = viewer.api_v1_get_works(query="the", limit=50)
        wids = {int(i["id"]) for i in resp["results"]}
        self.assertIn(self.godfather, wids)
        self.assertNotIn(self.other, wids)
        self.assertNotIn(self.together, wids)

    def test_candidate_latency_is_well_under_the_50ms_bar(self):
        # The benchmark's live numbers are 0.13 ms (`salaar`) and
        # 26 ms (`pushpa 2`); on this small fixture the call is
        # sub-millisecond. The bar pins the shape (FTS engaged, no
        # scan) rather than the scale — the live number is verified
        # after the gate deploy, on the 224k catalog.
        for query in ("salaar", "pushpa 2"):
            samples = []
            for _ in range(50):
                started = time.perf_counter()
                viewer._works_search_candidate_ids(self.conn, query)
                samples.append((time.perf_counter() - started) * 1000.0)
            p50 = statistics.median(samples)
            self.assertLess(p50, 50.0, f"{query}: p50 {p50:.2f} ms")


class DamerauTests(unittest.TestCase):
    def test_transposition_is_one_edit(self):
        self.assertTrue(search_fuzzy.damerau_le1("inceptoin", "inception"))
        self.assertTrue(search_fuzzy.damerau_le1("abdc", "abcd"))
        self.assertTrue(search_fuzzy.damerau_le1("avngers", "avengers"))

    def test_two_edits_are_still_two(self):
        self.assertFalse(search_fuzzy.damerau_le1("incepto", "inception"))
        self.assertFalse(search_fuzzy.damerau_le1("abc", "xyz"))
        self.assertFalse(search_fuzzy.damerau_le1("avengers", "av"))

    def test_fuzzy_match_accepts_a_transposition(self):
        self.assertTrue(
            search_fuzzy.fuzzy_match(["inceptoin"], ["inception"]))
        self.assertFalse(
            search_fuzzy.fuzzy_match(["incepto"], ["inception"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
