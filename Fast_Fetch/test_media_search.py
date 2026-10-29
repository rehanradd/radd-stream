#!/usr/bin/env python3
"""Offline tests for `media_search.py` — the by-media matcher.

Four things had to be proven, in this order:

1. **Honesty.** A hint the ledger cannot answer is reported as `unknown_on`, never
   as agreement. That is the whole design: a score that silently rewarded empty
   rows would rank a blank work above a described one.
2. **The bridge.** Runtime and rungs live in `cat_works`/`cat_releases`, reached
   through `cat_work_sites.post_id`. A fixture built by the real projector (rather
   than hand-drawn `cat_*` rows) is what proves that column is where the v1↔v2 join
   actually lives — `posts.canonical_key` matches nothing there.
3. **The edge.** Nothing this endpoint returns may carry provenance, adult rows may
   not appear, and a request with no title is refused rather than answered with a
   list that would mean nothing.
4. **The shape.** This is the 2026-10-29 production defect: `q=love` answered in
   45 s and `q=a` never answered, because one statement scanned `posts`, joined the
   1 780 121-row `releases` and the 4 073 865-row `download_sources` under it,
   grouped, and then sorted every group to show 10 rows. `QueryShape` asserts on the
   SQL the module actually executes and on that SQL's `EXPLAIN QUERY PLAN`, and keeps
   the statement it replaced as the counter-example — so these tests go red the
   moment the fan-out comes back, at any fixture size.

    python3 -S Fast_Fetch/test_media_search.py
"""
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import catalog_v2          # noqa: E402
import fast_fetch          # noqa: E402
import media_search        # noqa: E402
import redact              # noqa: E402
import viewer              # noqa: E402

NEEDLE = "clicknupload"     # one of redact's own needles, not an invented word
_BASELINE_NEEDLES = redact.needles()
_BASELINE_TEXT_NEEDLES = redact.text_needles()


class Fixture(unittest.TestCase):
    """Real ledger → real `catalog_v2` projection, so the evidence this module reads
    is evidence the projector actually writes."""

    def setUp(self):
        redact.set_needles(_BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.addCleanup(redact.set_needles, _BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
                        mock.patch.object(viewer, "DB_PATH", self.db_path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        # The v2 side of the bridge exists before anything is projected into it, so a
        # fixture that reads `posts` directly does not fail on a missing table. The
        # commit is not ceremony: DDL here leaves a write transaction open, and
        # `save_scraped_data` runs on its own connection, which then waits on a lock
        # this connection will never release.
        catalog_v2.ensure_schema(self.conn)
        self.conn.commit()
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)

    def ingest(self, *, title, site="somecdn.site", is_18_plus=0,
               release_title=None, languages='["Hindi"]'):
        label = release_title if release_title is not None else f"{title} 120min 1080p"
        # The projector takes the rung from the release row's `quality` and only
        # falls back to the label, so a fixture that disagrees with itself would
        # test the fallback rather than the bridge. Keep them tolding the same story.
        rung = media_search.normalize_resolution(label)
        slug = title.lower().replace(" ", "-")
        data = {
            "url": f"https://{site}/movie/{slug}/",
            "slug": slug,
            "title": f"{title} ({2024})",
            "clean_title": title,
            "year": 2024,
            "content_type": "movie",
            "poster_url": "https://cdn/poster.jpg",
            "genres": '["Action"]',
            "synopsis": f"{title} synopsis",
            "is_18_plus": is_18_plus,
            "source_site": site,
            "industry": "Bollywood",
            "country": "India",
            "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
            "releases": [{"release_title": label, "quality": rung,
                          "codec": "x264", "size": "1.5GB", "languages": languages,
                          "season": "", "episode": "", "intermediate_url": "",
                          "origin_url": "", "source_site": site,
                          "sources": [{"source_url": "https://cdn.example/one.mp4",
                                       "quality": rung, "status": "active"}]}],
        }
        fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
        self.conn.commit()
        catalog_v2.project(self.conn, rev=1, verbose=False)
        self.conn.commit()

    def search(self, **kw):
        return media_search.search_by_media(self.conn, **kw)

    def only(self, result):
        self.assertEqual(result["total"], 1, result)
        return result["results"][0]


class Helpers(unittest.TestCase):
    def test_dimensions_and_words_reduce_to_the_same_rung(self):
        for value in ("1920x1080", "1080p", "FULL HD", "fhd"):
            self.assertEqual(media_search.normalize_resolution(value), "1080p", value)
        for value in ("3840x2160", "2160p", "4K", "UHD"):
            self.assertEqual(media_search.normalize_resolution(value), "2160p", value)
        self.assertEqual(media_search.normalize_resolution("1280x720"), "720p")
        self.assertEqual(media_search.normalize_resolution("SD"), "480p")

    def test_an_unreadable_rung_is_no_rung(self):
        for value in ("", None, "web-dl", "x265", "1920", "taller than wide"):
            self.assertEqual(media_search.normalize_resolution(value), "", repr(value))

    def test_a_height_between_two_rungs_is_labeled_by_the_ladder_not_invented(self):
        self.assertEqual(media_search.normalize_resolution("1440x1080"), "1080p")
        # The 0.9 step is deliberate: a 1000-row print is a re-encoded 1080p, not a
        # 720p, and 1280x720 stays 720p because 720 is under 1080 * 0.9.
        self.assertEqual(media_search.normalize_resolution("1780x1000"), "1080p")
        self.assertEqual(media_search.normalize_resolution("1280x720"), "720p")
        self.assertEqual(media_search.normalize_resolution("640x360"), "")

    def test_duration_agrees_only_within_the_tolerance(self):
        matches = media_search.duration_matches
        self.assertIs(matches(120, 120 * 60), True)
        self.assertIs(matches(120, 135 * 60), True)         # 15% is the window
        self.assertIs(matches(120, 140 * 60), False)
        self.assertIs(matches(120, 90 * 60), False)

    def test_an_unanswerable_duration_is_none_not_false(self):
        matches = media_search.duration_matches
        for runtime in (None, "", 0, -5, "not a number"):
            self.assertIsNone(matches(runtime, 7200), runtime)
        self.assertIsNone(matches(120, None))
        self.assertIsNone(matches(120, 0))


class EvidenceBridge(Fixture):
    def test_the_projector_actually_writes_the_evidence_this_reads(self):
        """If this fails, the bridge below is testing a fixture, not the catalog."""
        self.ingest(title="Bridge Check")
        row = self.conn.execute(
            """
            SELECT w.runtime_minutes AS runtime, r.resolution AS resolution,
                   w.languages AS languages, r.audio_languages AS audio
            FROM cat_work_sites cs
            JOIN cat_works w ON w.id = cs.work_id
            JOIN cat_releases r ON r.work_id = w.id
            """).fetchone()
        self.assertIsNotNone(row, "the projector produced no cat_work_sites row")
        self.assertEqual(row["runtime"], 120)
        self.assertEqual(media_search.normalize_resolution(row["resolution"]), "1080p")
        spoken = " ".join(str(row[k] or "") for k in ("languages", "audio")).lower()
        self.assertIn("hindi", spoken)

    def test_canonical_key_is_not_the_bridge(self):
        """The wrong join is the bug this module exists to avoid: it answers zero rows."""
        self.ingest(title="Bridge Check")
        joined = self.conn.execute(
            "SELECT COUNT(*) FROM cat_works w WHERE w.work_key IN"
            " (SELECT canonical_key FROM posts)").fetchone()[0]
        self.assertEqual(joined, 0)


class Scoring(Fixture):
    def test_a_work_the_hints_agree_with_is_ranked_above_one_that_only_exists(self):
        self.ingest(title="Alpha Film", release_title="Alpha Film 120min 1080p")
        self.ingest(title="Beta Film", release_title="Beta Film 60min 480p")
        result = self.search(title="Film", duration_s=120 * 60, resolution="1080p")
        self.assertEqual([r["clean_title"] for r in result["results"]],
                         ["Alpha Film", "Beta Film"])
        top = result["results"][0]
        self.assertEqual(sorted(top["matched_on"]), ["duration_s", "resolution"])
        self.assertEqual(top["mismatched_on"], [])

    def test_a_contradicted_hint_is_reported_not_silently_dropped(self):
        self.ingest(title="Alpha Film", release_title="Alpha Film 120min 480p")
        item = self.only(self.search(title="Alpha", resolution="1080p"))
        self.assertEqual(item["mismatched_on"], ["resolution"])
        self.assertEqual(item["matched_on"], [])
        self.assertEqual(item["resolutions"], ["480p"])

    def test_a_hint_the_ledger_cannot_answer_is_unknown_never_matched(self):
        """The core honesty rule: an empty row must not be credited with agreement."""
        self.ingest(title="Blank Film", release_title="Blank Film")
        item = self.only(self.search(title="Blank", duration_s=9999, resolution="2160p"))
        self.assertEqual(sorted(item["unknown_on"]), ["duration_s", "resolution"])
        self.assertEqual(item["matched_on"], [])
        self.assertEqual(item["mismatched_on"], [])

    def test_agreement_beats_the_popularity_the_ledger_would_have_shown(self):
        """Beta has three times the mirrors and is the wrong answer; agreement wins."""
        self.ingest(title="Alpha Film", release_title="Alpha Film 120min 1080p")
        self.ingest(title="Beta Film", release_title="Beta Film 300min 480p")
        beta = int(self.conn.execute(
            "SELECT id FROM posts WHERE clean_title = 'Beta Film'").fetchone()["id"])
        beta_release = int(self.conn.execute(
            "SELECT id FROM releases WHERE post_id = ?", (beta,)).fetchone()["id"])
        for n in range(3):
            self.conn.execute(
                "INSERT INTO download_sources (release_id, source_url, service, status)"
                " VALUES (?, ?, 'hubcloud_10g', 'active')",
                (beta_release, f"https://mirror{n}.example/{n}.mp4"))
        self.conn.commit()
        result = self.search(title="Film", duration_s=120 * 60, resolution="1080p")
        self.assertEqual([r["clean_title"] for r in result["results"]],
                         ["Alpha Film", "Beta Film"])
        self.assertEqual(result["results"][1]["mismatched_on"],
                         ["duration_s", "resolution"])

    def test_audio_language_matches_a_substring_of_the_stored_list(self):
        self.ingest(title="Tongue Film", languages='["Hindi", "Tamil"]')
        item = self.only(self.search(title="Tongue", audio_language="tamil"))
        self.assertEqual(item["matched_on"], ["audio_language"])
        miss = self.only(self.search(title="Tongue", audio_language="punjabi"))
        self.assertEqual(miss["mismatched_on"], ["audio_language"])


class EdgeContract(Fixture):
    def test_no_title_is_refused_instead_of_answered_with_noise(self):
        self.ingest(title="Alpha Film")
        for blank in ("", "   ", None):
            result = self.search(title=blank, duration_s=120 * 60)
            self.assertFalse(result["success"])
            self.assertEqual(result["results"], [])
            self.assertIn("title", result["error"].lower())

    def test_an_adult_work_is_absent_not_marked(self):
        self.ingest(title="Hidden Film", is_18_plus=1)
        result = self.search(title="Hidden", duration_s=120 * 60)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total"], 0)

    def test_a_public_row_carries_no_provenance_key_or_needle(self):
        self.ingest(title="Leaky Film", site=f"{NEEDLE}.site")
        result = self.search(title="Leaky", duration_s=120 * 60, resolution="1080p")
        blob = repr(result).lower()
        self.assertNotIn(NEEDLE, blob)
        for item in result["results"]:
            leaked = set(item) & redact.PROVENANCE
            self.assertEqual(leaked, set(), sorted(leaked))

    def test_full_is_the_only_shape_that_carries_the_upstream(self):
        """Loopback may see where a row came from; the public edge may not."""
        self.ingest(title="Loopback Film", site=f"{NEEDLE}.site")
        public = self.search(title="Loopback")["results"][0]
        for key in ("source_site", "url", "slug"):
            self.assertNotIn(key, public)
        item = self.search(title="Loopback", full=True)["results"][0]
        self.assertEqual(item["source_site"], f"{NEEDLE}.site")
        self.assertNotIn(NEEDLE, str(item["clean_title"]).lower())

    def test_the_answer_names_the_tolerance_and_the_window_it_searched(self):
        self.ingest(title="Meta Film")
        result = self.search(title="Meta", duration_s=120 * 60)
        self.assertEqual(result["duration_tolerance"], media_search.DURATION_TOLERANCE)
        self.assertEqual(result["query"]["duration_s"], 120 * 60)
        self.assertEqual(result["query"]["resolution"], None)
        self.assertGreaterEqual(result["candidates"], 1)

    def test_a_garbage_duration_is_ignored_rather_than_poisoning_the_rank(self):
        self.ingest(title="Robust Film")
        for junk in ("abc", -5, 0, None, ""):
            result = self.search(title="Robust", duration_s=junk)
            self.assertTrue(result["success"], junk)
            self.assertEqual(result["query"]["duration_s"], None, junk)
            self.assertEqual(result["results"][0]["unknown_on"], [])


class RouteShape(Fixture):
    """The part `media_search` cannot own: what `viewer` bolts on around it.

    A by-media row must be the same shape as a `q=` row, or the app needs a second
    renderer for it — and a second renderer is where provenance reappears.
    """

    def call(self, **kw):
        return viewer.api_v1_search_by_media(**kw)

    def test_an_enriched_row_carries_our_own_art_handle_and_a_work_ref(self):
        self.ingest(title="Shaped Film")
        item = self.call(query="Shaped", duration_s=120 * 60)["results"][0]
        self.assertTrue(item["work_ref"], "the account surface needs a handle it minted")
        poster = item["poster_url"]
        self.assertTrue(poster.startswith("/api/v1/art?"), poster)
        self.assertNotIn("cdn/poster.jpg", poster)
        self.assertNotIn("somecdn.site", poster)

    def test_the_row_shape_is_the_shape_a_keyword_search_already_returns(self):
        self.ingest(title="Shaped Film")
        by_media = self.call(query="Shaped", duration_s=120 * 60)["results"][0]
        by_word = viewer.api_v1_get_posts(query="Shaped")["results"][0]
        # What the by-media route adds is read off `media_search` itself rather
        # than hand-listed here: ask the module for the same row with no viewer
        # enrichment, and whatever it alone puts beyond the keyword shape is
        # exactly what viewer is allowed to put beyond it. A future field on one
        # side only now fails instead of quietly widening an expected set.
        bare = self.search(title="Shaped", duration_s=120 * 60)["results"][0]
        media_only = set(bare) - set(by_word)
        self.assertTrue(media_only, "the matcher contributes nothing to compare")
        self.assertEqual(set(by_media) - set(by_word), media_only)
        self.assertEqual(set(by_word) - set(by_media), set(),
                         "a display key the by-media route lost")

    def test_both_routes_answer_the_subtitled_question_with_the_same_value(self):
        self.ingest(title="Subbed Film",
                    release_title="Subbed Film 120min 1080p Hindi English ESub")
        self.ingest(title="Plain Film", release_title="Plain Film 120min 1080p")
        for title, expected in (("Subbed", True), ("Plain", False)):
            by_media = self.call(query=title, duration_s=120 * 60)["results"][0]
            by_word = viewer.api_v1_get_posts(query=title)["results"][0]
            self.assertEqual(by_media["subtitled"], expected, title)
            self.assertEqual(by_word["subtitled"], by_media["subtitled"], title)

    def test_the_full_projection_is_not_half_a_row_on_either_route(self):
        self.ingest(title="Full Shape Film")
        by_media = self.call(query="Full", duration_s=120 * 60, full=True)["results"][0]
        by_word = viewer.api_v1_get_posts(query="Full", full=True)["results"][0]
        self.assertEqual(set(by_word) - set(by_media), set())

    def test_a_request_without_a_title_is_the_refusal_not_a_200_full_of_noise(self):
        self.ingest(title="Shaped Film")
        refused = self.call(duration_s=120 * 60)
        self.assertFalse(refused["success"])
        self.assertEqual(refused["results"], [])


#: The statement this module ran until 2026-10-29, kept verbatim from `c2d11be` as
#: the counter-example the shape tests are measured against. It is what 45 s and a
#: 504 looked like; the tests below assert that nothing like it is executed anymore,
#: and assert on *this* text so that claim is checkable rather than rhetorical.
_OLD_STATEMENT = """
    SELECT p.id, p.clean_title, p.year, p.content_type,
           COUNT(DISTINCT r.id) AS release_count,
           COUNT(DISTINCT s.id) AS source_count
    FROM posts p
    LEFT JOIN releases r ON r.post_id = p.id
    LEFT JOIN download_sources s ON s.release_id = r.id
    WHERE (p.is_18_plus IS NULL OR p.is_18_plus = 0)
      AND (p.clean_title LIKE ? OR p.title LIKE ?)
    GROUP BY p.id
    ORDER BY (release_count + source_count) DESC, p.id DESC
    LIMIT ?
    """

#: The production catalog is 150 799 posts over 1 780 121 releases and 4 073 865
#: download sources — roughly 12 releases per post and 2 sources per release. These
#: fixtures keep those *ratios* at 1/125 the size, which is enough for the planner to
#: choose the plans being asserted on (planning is shape-driven, not size-driven) and
#: fast enough to build on a one-core box. The wall-clock budget below is therefore
#: stated for this size; the production-scale numbers are measured against a copy of
#: the catalog, and reported in CONTINUITY.md, not asserted here.
SCALE_POSTS = 1200
SCALE_RELEASES_PER_POST = 12
SCALE_SOURCES_PER_RELEASE = 2

#: The owner's suggested ceiling for a bounded request. The fixture below answers in
#: roughly a tenth of it, so this is a regression trap and not a benchmark.
WALL_CLOCK_BUDGET_S = 1.5


class _Spy:
    """A connection that remembers every statement it was asked to run.

    Asserting on the SQL the module *executed* is the only version of these tests
    that can fail: a test that re-derived the statement from the source would keep
    passing after the fan-out came back. This is also how "no SQL at all" is proven.
    """

    def __init__(self, conn):
        self._conn = conn
        self.calls: list = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), tuple(params)))
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _Refusing:
    """A connection that must never be asked a question."""

    def execute(self, sql, params=()):
        raise AssertionError(
            f"a non-query reached the ledger: {' '.join(str(sql).split())[:120]}")


def _plan(conn, sql, params):
    """`EXPLAIN QUERY PLAN` detail strings — read-only, so this costs nothing to assert on."""
    return " | ".join(str(row["detail"])
                      for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params))


class _Scaled(unittest.TestCase):
    """The production ratios, built with raw inserts.

    `Fixture` goes through `save_scraped_data` and the projector because the evidence
    bridge has to be the real one — that costs seconds per post and is the wrong tool
    for a test about the shape of the SQL. Same tables, same indexes, same planner.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "scaled.db"
        fast_fetch.init_db(cls.db_path)
        conn = sqlite3.connect(cls.db_path)
        catalog_v2.ensure_schema(conn)
        conn.executemany(
            "INSERT INTO posts (url, slug, title, clean_title, year, content_type)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(f"https://scaled.test/{i}", f"s-{i}",
              f"Movie On Number {i} (2024)", f"Movie On Number {i}", 2024, "movie")
             for i in range(SCALE_POSTS)])
        conn.executemany(
            "INSERT INTO releases (post_id, release_title, quality)"
            " VALUES (?, ?, ?)",
            [(i + 1, f"r{i}-{k}", "1080p")
             for i in range(SCALE_POSTS) for k in range(SCALE_RELEASES_PER_POST)])
        conn.executemany(
            "INSERT INTO download_sources (release_id, source_url, service, status)"
            " VALUES (?, ?, ?, ?)",
            [(rid, f"https://mirror.test/{rid}-{k}.mp4", "hubcloud_10g", "active")
             for rid in range(1, SCALE_POSTS * SCALE_RELEASES_PER_POST + 1)
             for k in range(SCALE_SOURCES_PER_RELEASE)])
        # The v2 side at one work per post. The projector proves the bridge in
        # `EvidenceBridge`; these rows exist so `_work_evidence` runs against a
        # populated ledger here and its statements are planned like the real ones.
        conn.executemany(
            "INSERT INTO cat_works (id, work_key, title, work_type, runtime_minutes,"
            " languages, updated_at) VALUES (?, ?, ?, 'movie', 120, '[\"Hindi\"]',"
            " 1730000000)",
            [(i + 1, f"imdb:tt{i:07d}", f"Movie On Number {i}")
             for i in range(SCALE_POSTS)])
        conn.executemany(
            "INSERT INTO cat_work_sites (work_id, source_site, post_id, page_url)"
            " VALUES (?, 'scaled.test', ?, ?)",
            [(i + 1, i + 1, f"https://scaled.test/{i}")
             for i in range(SCALE_POSTS)])
        conn.executemany(
            "INSERT INTO cat_releases (work_id, label, resolution, audio_languages,"
            " created_at) VALUES (?, 'print', '1080p', '[\"Hindi\"]', 1730000000)",
            [(i + 1,) for i in range(SCALE_POSTS)])
        conn.commit()
        conn.row_factory = sqlite3.Row
        cls.conn = conn

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def search(self, **kw):
        spy = _Spy(self.conn)
        result = media_search.search_by_media(spy, **kw)
        return result, spy


class QueryShape(_Scaled):
    """Item D: the request shape, asserted on the statements and their plans."""

    def test_a_one_character_token_never_reaches_the_ledger(self):
        """`q=a` is not a slow query, it is a non-query, and the fix is to not run it.

        The old shape answered this by scanning every post and sorting every group;
        on the live catalog it never answered at all (client timeout at 60 071 ms).
        """
        started = time.perf_counter()
        for token in ("a", "7", "x"):
            result = media_search.search_by_media(_Refusing(), title=token,
                                                  duration_s=7200, resolution="1080p")
            self.assertTrue(result["success"], token)
            self.assertEqual(result["results"], [], token)
            self.assertEqual(result["candidates"], 0, token)
            self.assertIn("hint", result, token)
        self.assertLess(time.perf_counter() - started, WALL_CLOCK_BUDGET_S)

    def test_a_blank_title_is_refused_without_a_query_too(self):
        for blank in ("", "   ", None, "\t\n"):
            result = media_search.search_by_media(_Refusing(), title=blank)
            self.assertFalse(result["success"], repr(blank))
            self.assertEqual(result["candidates"], 0, repr(blank))

    def test_the_floor_is_the_floor_not_an_off_by_one(self):
        """One character under the floor issues no SQL; on it, the search runs."""
        media_search.search_by_media(_Refusing(),
                                     title="x" * (media_search.MIN_QUERY_CHARS - 1))
        result = media_search.search_by_media(self.conn,
                                              title="x" * media_search.MIN_QUERY_CHARS)
        self.assertTrue(result["success"])

    def test_no_statement_it_runs_sorts_a_set_it_did_not_bound_first(self):
        result, spy = self.search(title="on", limit=10)
        self.assertGreater(len(spy.calls), 0, "the search ran nothing")
        self.assertGreater(result["candidates"], 0)
        for sql, params in spy.calls:
            details = _plan(self.conn, sql, params)
            self.assertNotIn("USE TEMP B-TREE FOR ORDER BY", details, sql[:120])
            if "FROM posts p" in sql:
                self.assertNotIn("USE TEMP B-TREE", details,
                                 f"candidates arm sorts an unbounded set: {sql[:120]}")

    def test_it_never_joins_the_catalog_to_the_posts_it_scans(self):
        """The fan-out is gone as a statement, not merely made faster."""
        _, spy = self.search(title="on", limit=10)
        for sql, params in spy.calls:
            if "FROM posts p" in sql:
                self.assertNotIn("LEFT JOIN", sql, sql[:120])
                self.assertNotIn("JOIN releases", sql, sql[:120])
                self.assertNotIn("JOIN download_sources", sql, sql[:120])
            self.assertNotIn("COUNT(DISTINCT", sql.upper(), sql[:120])
            self.assertNotIn("GROUP BY p.id", sql, sql[:120])

    def test_the_statement_this_replaced_sorted_every_group(self):
        """Red-side proof: the plan the tests above deny is real and measurable.

        The plan names the two joins by their *indexes* (`idx_releases_post`,
        `idx_sources_rel`), which is exactly the four-million-row walk — so this
        asserts on those, not on the table names.
        """
        details = _plan(self.conn, _OLD_STATEMENT, ("%on%", "%on%", 20))
        self.assertIn("SCAN p", details, details)
        self.assertIn("USE TEMP B-TREE FOR ORDER BY", details, details)
        self.assertEqual(details.count("USE TEMP B-TREE FOR count(DISTINCT)"), 2, details)
        self.assertEqual(details.count("LEFT-JOIN"), 2, details)
        self.assertIn("idx_sources_rel", details, details)

    def test_the_window_bounds_the_work_not_just_the_answer(self):
        """Every post in this fixture matches `on`; the counts must be read back for
        the capped ids only, which is the difference between 40 probes and 120 000."""
        limit = 10
        result, spy = self.search(title="on", limit=limit)
        self.assertLessEqual(result["candidates"], media_search.CANDIDATE_WINDOW)
        self.assertLessEqual(result["candidates"], max(limit * 4, limit))
        matched = self.conn.execute(
            "SELECT COUNT(*) FROM posts WHERE clean_title LIKE '%on%'").fetchone()[0]
        self.assertGreater(matched, result["candidates"] * 4,
                           "the fixture is too small to prove a cap")
        count_calls = [c for c in spy.calls if "FROM releases" in c[0]
                       or "FROM download_sources" in c[0]]
        self.assertEqual(len(count_calls), 2, "the counts must come from two index reads")
        for sql, params in count_calls:
            self.assertEqual(len(params), result["candidates"], sql[:120])

    def test_the_number_of_statements_does_not_grow_with_the_request(self):
        """Three arms, two count reads, one row fetch, two evidence reads. Eight
        statements whatever the `limit` is: a larger page must not quietly buy work."""
        small, small_spy = self.search(title="on", limit=1)
        large, large_spy = self.search(title="on", limit=50)
        self.assertEqual(len(small_spy.calls), len(large_spy.calls))
        self.assertLessEqual(len(large_spy.calls), 8)
        self.assertGreater(large["candidates"], small["candidates"])

    def test_a_bounded_request_lands_inside_the_budget_at_both_ends_of_the_window(self):
        for limit in (10, 50):
            started = time.perf_counter()
            result, _ = self.search(title="on", limit=limit)
            elapsed = time.perf_counter() - started
            self.assertTrue(result["success"])
            self.assertLess(elapsed, WALL_CLOCK_BUDGET_S,
                            f"limit={limit} took {elapsed * 1000:.0f} ms")


class TextIsText(Fixture):
    """What the shape must not lose on its way to being fast."""

    counter = 0

    def seed(self, title, is_18_plus=0):
        """Raw rows: `save_scraped_data` cleans titles, and these tests are about
        titles that are punctuation."""
        TextIsText.counter += 1
        slug = f"seed-{TextIsText.counter}"
        self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
            " is_18_plus) VALUES (?, ?, ?, ?, 2024, 'movie', ?)",
            (f"https://text.test/{slug}", slug, f"{title} (2024)", title, is_18_plus))
        self.conn.commit()
        return int(self.conn.execute(
            "SELECT id FROM posts WHERE slug = ?", (slug,)).fetchone()["id"])

    def mirrors(self, post_id, releases=1, sources_per_release=1):
        for r in range(releases):
            rid = self.conn.execute(
                "INSERT INTO releases (post_id, release_title) VALUES (?, ?)",
                (post_id, f"print-{r}")).lastrowid
            for s in range(sources_per_release):
                self.conn.execute(
                    "INSERT INTO download_sources (release_id, source_url, service)"
                    " VALUES (?, ?, 'hubcloud_10g')",
                    (rid, f"https://mirror.test/{post_id}-{r}-{s}.mp4"))
        self.conn.commit()

    def titles(self, result):
        return [r["clean_title"] for r in result["results"]]

    def test_a_percent_sign_in_a_title_is_a_percent_sign(self):
        """`%` is a LIKE wildcard, so an unescaped query of `% Film` asks for every
        title ending in anything — the `q=a` cliff reached with two keystrokes."""
        self.seed("Fifty % Film")
        self.seed("Fifty X Film")
        self.seed("Alpha Film")
        self.assertEqual(self.titles(self.search(title="% Film")), ["Fifty % Film"])

    def test_an_underscore_is_not_a_single_character_wildcard(self):
        self.seed("Under_Score Film")
        self.seed("UnderXScore Film")
        self.assertEqual(self.titles(self.search(title="_Score Film")),
                         ["Under_Score Film"])

    def test_the_escape_survives_a_like_round_trip(self):
        for text in ("100%", "a_b", "a\\b", "%_%", "_", "50%%"):
            pattern = media_search._contains_pattern(text)
            hit = self.conn.execute("SELECT ? LIKE ? ESCAPE '\\'", (text, pattern)).fetchone()[0]
            self.assertEqual(hit, 1, (text, pattern))

    def test_an_adult_work_cannot_take_the_top_slot_by_being_the_most_popular(self):
        """The ranking signal is print-and-mirror count; a flagged row would win it
        outright. The bail is in every arm, not in the projection."""
        visible = self.seed("Visible Film")
        self.mirrors(visible, releases=1, sources_per_release=1)
        hidden = self.seed("Hidden Film", is_18_plus=1)
        self.mirrors(hidden, releases=20, sources_per_release=5)
        result = self.search(title="Film", limit=10)
        self.assertNotIn("Hidden Film", self.titles(result))
        self.assertEqual(self.titles(result), ["Visible Film"])
        self.assertGreater(result["results"][0]["release_count"], 0)

    def test_ties_break_on_the_highest_id_and_stay_put_across_a_limit_sweep(self):
        """A tie with no last-resort key is a real defect: the next page repeats a
        row or drops one. Every row here has zero prints, so all of them tie."""
        wanted = [self.seed(f"Tied Film {n}") for n in range(6)]
        sweep = {}
        for limit in (1, 2, 3, 6):
            result = self.search(title="Tied", limit=limit)
            sweep[limit] = [r["id"] for r in result["results"]]
        ordered = sorted(wanted, reverse=True)
        self.assertEqual(sweep[6], ordered)
        for limit in (1, 2, 3):
            self.assertEqual(sweep[limit], ordered[:limit], limit)

    def test_the_row_answers_the_count_keys_a_keyword_row_answers(self):
        post = self.seed("Counted Film")
        self.mirrors(post, releases=3, sources_per_release=4)
        item = self.only(self.search(title="Counted"))
        self.assertEqual(item["release_count"], 3)
        self.assertEqual(item["source_count"], 12)


class PopulationCost(_Scaled):
    """The one scan left in the path, measured so the migration can price it.

    `_work_evidence` reaches the v2 ledger through `cat_work_sites.post_id`, and that
    column has no index (`catalog_v2.DDL` indexes `cat_releases.work_id` but not the
    site bridge), so both evidence statements are `SCAN cs` — over 275 488 rows in
    production, once per request. This test does not assert a fix; it asserts the
    cost is *known*, and it is the number `migrations/` is written against.
    """

    def test_the_evidence_bridge_is_the_unindexed_scan_it_is_reported_as(self):
        _, spy = self.search(title="on", limit=10)
        evidence = [call for call in spy.calls if "cat_work_sites" in call[0]]
        self.assertEqual(len(evidence), 2, "both evidence statements, no more")
        for sql, params in evidence:
            details = _plan(self.conn, sql, params)
            self.assertIn("SCAN cs", details,
                          "expected the unindexed bridge scan; if this is now an"
                          " index probe, retire this test and the migration entry")



if __name__ == "__main__":
    unittest.main(verbosity=2)
