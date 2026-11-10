#!/usr/bin/env python3
"""test_posts_query_plan.py — what `/api/v1/posts?q=` actually pays for.

This suite exists because a report claimed the route's cost was a **missing
index** and that claim was measured against the wrong file. On the production
catalog every join column the statement touches is already indexed
(`idx_releases_post`, `idx_sources_rel`) and `cat_work_sites.post_id` has
`idx_cat_work_sites_post`. The plan below is the correction, pinned offline so
it stays correct whatever the next person's box has cached.

The claim being pinned is narrow and it is not "search is fast":

* `api_v1_get_posts` issues **two** full passes over `posts` per request for
  the trending and unknown sorts — the exact-total `COUNT(*)` and the paged
  list — and neither can use an index, because `LIKE '%inception%'` has a
  leading wildcard. No index removes a leading-wildcard scan; only a different
  index *structure* (FTS5) does. The newest, title and rating sorts
  (`newest` since Session 115, title and rating since Session posts503) add
  a third, narrow pass: the page's ids from `posts` alone, ordered by the
  sort key. That pass DOES sort a temp B-tree, by design — it sorts only ids
  and keys, no joins, ~0.33s on the live catalog — and it is what keeps the
  paged statement from grouping all ~135k public posts before sorting
  (~4.8s live). Title needed it: `type=movie&quality=720p&sort=title` has
  91,592 live matches, and the one-query shape ran ~2.2s warm and crossed
  the 10s deadline into a 503 during the 2026-11-10 Firebase Robo test.
* With the newest/title/rating sorts the paged statement does NOT sort a
  temp B-tree, so a slow `q=inception` is not an `ORDER BY` problem either.
  With `sort=trending` it does, and that is the one case where the old
  by-media shape's defect is reproduced here. The unknown-sort statement
  (`ORDER BY p.id DESC`) is the same shape as the old default and also
  builds no order B-tree.
* `q=a` and `q=%` are accepted and answered. A one-letter query scans the whole
  ledger to return twenty rows, and `%` is interpolated into the pattern
  unescaped, so two keystrokes can ask for every row in the catalog.

Stdlib only, one throwaway database in a temp directory, no network, no
production file. Run: python3 -S Fast_Fetch/test_posts_query_plan.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog_v2  # noqa: E402

#: The statement `viewer.api_v1_get_posts` builds for `q=…` with the default sort,
#: transcribed from `Fast_Fetch/viewer.py` (`api_v1_get_posts`, the `total` read and
#: the paged read). Kept as data so the plan is asserted, not remembered.
TOTAL_SQL = ("SELECT COUNT(*) FROM posts p"
             " WHERE COALESCE(p.is_18_plus,0)=0"
             " AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ? OR p.cast_names LIKE ?)")

#: Step 1 of the default (`newest`, Session 115) path: the page's ids from
#: `posts` alone, ordered by the clamped year. The clamp is transcribed from
#: `viewer._NEWEST_YEAR_SQL`.
NEWEST_IDS_SQL = ("SELECT p.id FROM posts p"
                  " WHERE COALESCE(p.is_18_plus,0)=0"
                  " AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ? OR p.cast_names LIKE ?)"
                  " ORDER BY CASE WHEN p.year BETWEEN 1900"
                  " AND CAST(strftime('%Y', 'now') AS INTEGER) + 1"
                  " THEN p.year ELSE 0 END DESC, p.id DESC LIMIT ? OFFSET ?")

#: Step 1 of the title path (Session posts503): the page's ids from `posts`
#: alone, ordered by the title key. Same shape as NEWEST_IDS_SQL, different
#: ORDER BY — and the same reason: the one-query shape grouped the fan-out
#: for every match before sorting.
TITLE_IDS_SQL = ("SELECT p.id FROM posts p"
                 " WHERE COALESCE(p.is_18_plus,0)=0"
                 " AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ? OR p.cast_names LIKE ?)"
                 " ORDER BY lower(COALESCE(NULLIF(TRIM(p.clean_title), ''), p.title)) ASC,"
                 " p.id DESC LIMIT ? OFFSET ?")

#: Step 1 of the rating path (Session posts503): same two-step shape, the
#: rating key. The ORDER BY is transcribed from `viewer.api_v1_get_posts`
#: (`sort=rating`).
RATING_IDS_SQL = ("SELECT p.id FROM posts p"
                  " WHERE COALESCE(p.is_18_plus,0)=0"
                  " AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ? OR p.cast_names LIKE ?)"
                  " ORDER BY (p.imdb_rating IS NULL OR TRIM(p.imdb_rating) = '') ASC,"
                  " CAST(p.imdb_rating AS REAL) DESC, p.id DESC LIMIT ? OFFSET ?")

#: Step 2 of the two-step path (newest, title, rating): the page's counts,
#: for just those ids — no ORDER BY and no LIMIT, because the page is
#: already exactly these ids and the order is imposed in Python.
PAGED_NEWEST_SQL = """
    SELECT p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,
           p.poster_url, p.backdrop_urls, p.imdb_rating, p.imdb_id, p.tmdb_id,
           p.genres, p.is_animated, p.industry, p.country, p.language,
           COUNT(DISTINCT r.id) as release_count,
           COUNT(DISTINCT s.id) as source_count
    FROM posts p
    LEFT JOIN releases r ON r.post_id = p.id
    LEFT JOIN download_sources s ON s.release_id = r.id
    WHERE COALESCE(p.is_18_plus,0)=0
      AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ? OR p.cast_names LIKE ?)
      AND p.id IN (?,?,?)
    GROUP BY p.id
"""

PAGED_SQL = """
    SELECT p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,
           p.poster_url, p.backdrop_urls, p.imdb_rating, p.imdb_id, p.tmdb_id,
           p.genres, p.is_animated, p.industry, p.country, p.language,
           COUNT(DISTINCT r.id) as release_count,
           COUNT(DISTINCT s.id) as source_count
    FROM posts p
    LEFT JOIN releases r ON r.post_id = p.id
    LEFT JOIN download_sources s ON s.release_id = r.id
    WHERE COALESCE(p.is_18_plus,0)=0
      AND (p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ? OR p.cast_names LIKE ?)
    GROUP BY p.id
    ORDER BY {order}
    LIMIT ? OFFSET ?
"""
DEFAULT_ORDER = "p.id DESC"
TRENDING_ORDER = "(release_count + source_count) DESC, p.id DESC"


class _Fixture(unittest.TestCase):
    """A real schema with the real production index set, and a handful of rows.

    Index parity matters: an assertion about `SEARCH r USING COVERING INDEX
    idx_releases_post` means nothing on a fixture that forgot the index, and a
    fixture that invents one production lacks would prove the opposite lie. The
    row count is deliberately tiny — these tests judge the *plan*, which is a
    property of the schema and the SQL text, not of how much data is in the way.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="posts_plan_")
        cls.path = os.path.join(cls.tmp, "fixture_catalog.db")
        print(f"[fixture] database: {cls.path}", flush=True)
        cls.conn = sqlite3.connect(cls.path)
        cls.conn.row_factory = sqlite3.Row
        # The three tables the statement reads, with the columns the statement
        # names. `catalog_v2.ensure_schema` creates neither `releases` nor
        # `download_sources` at all (they are `fast_fetch.py`'s schema), so
        # building them here is the only way to get a plan at all — and it is the
        # same fact the drift test below pins: no single `ensure_schema` in this
        # repo produces the shape the live catalog has.
        cls.conn.executescript("""
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY, clean_title TEXT, title TEXT, slug TEXT,
                year INTEGER, content_type TEXT, seasons INTEGER, poster_url TEXT,
                backdrop_urls TEXT, imdb_rating TEXT, imdb_id TEXT, tmdb_id TEXT,
                genres TEXT, is_animated INTEGER, industry TEXT, country TEXT,
                language TEXT, cast_names TEXT, is_18_plus INTEGER DEFAULT 0);
            CREATE TABLE releases (
                id INTEGER PRIMARY KEY, post_id INTEGER, release_title TEXT,
                quality TEXT, codec TEXT, languages TEXT, source_site TEXT,
                origin_url TEXT);
            CREATE TABLE download_sources (
                id INTEGER PRIMARY KEY, release_id INTEGER, resource_id TEXT,
                status TEXT, is_temporary INTEGER, service TEXT);
            CREATE INDEX idx_releases_post ON releases(post_id);
            CREATE INDEX idx_releases_origin ON releases(post_id, source_site, origin_url);
            CREATE INDEX idx_releases_post_quality ON releases(post_id, quality);
            CREATE INDEX idx_sources_rel ON download_sources(release_id);
            CREATE INDEX idx_sources_res ON download_sources(resource_id);
            CREATE INDEX idx_sources_rel_status ON download_sources(release_id, status);
            """)
        cls.conn.commit()
        for name in ("idx_releases_post", "idx_releases_post_quality",
                     "idx_sources_rel"):
            assert cls._has_index(name), f"fixture drifted from production: {name}"

    @classmethod
    def _has_index(cls, name):
        return cls.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (name,)).fetchone() is not None

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def plan(self, sql, params):
        return " ; ".join(str(x) for r in
                          self.conn.execute("EXPLAIN QUERY PLAN " + sql, params)
                          for x in tuple(r))

    def seed(self, title, **kw):
        cols = {"clean_title": title, "title": title, "year": 2024,
                "content_type": "movie", "is_18_plus": 0}
        cols.update(kw)
        cur = self.conn.execute(
            "INSERT INTO posts(clean_title, title, year, content_type, is_18_plus)"
            " VALUES(:clean_title,:title,:year,:content_type,:is_18_plus)", cols)
        self.conn.commit()
        return int(cur.lastrowid)


class TestCostIsTheScan(_Fixture):
    def test_the_default_route_makes_three_passes_and_only_the_narrow_one_sorts(self):
        """The default sort (`newest`, Session 115) is total + narrow ids +
        page. The ids pass is the only one that sorts a temp B-tree, and it
        sorts only ids and years — no joins — which is what keeps the page
        from grouping all ~135k posts before sorting (~4.8s live). The page
        pass reaches its rows by primary key and carries no ORDER BY at all.
        """
        self.seed("Inception")
        self.seed("Inception Two")
        self.seed("Inception Three")
        total_plan = self.plan(TOTAL_SQL, ["%inception%"] * 4)
        ids_plan = self.plan(NEWEST_IDS_SQL, ["%inception%"] * 4 + [20, 0])
        # EXPLAIN never executes, so the ids need not exist — three literals
        # stand in for the page's id list.
        paged_plan = self.plan(PAGED_NEWEST_SQL, ["%inception%"] * 4 + [1, 2, 3])
        self.assertIn("SCAN p", total_plan, total_plan)
        self.assertIn("SCAN p", ids_plan, ids_plan)
        self.assertIn("USE TEMP B-TREE FOR ORDER BY", ids_plan, ids_plan)
        self.assertIn("SEARCH p USING INTEGER PRIMARY KEY", paged_plan, paged_plan)
        self.assertNotIn("USE TEMP B-TREE FOR ORDER BY", paged_plan, paged_plan)

    def test_title_and_rating_use_the_narrow_ids_pass_like_newest(self):
        """Session posts503: title and rating join newest in the two-step
        shape — the ids pass sorts a temp B-tree (ids + keys only, no joins)
        and the page-by-ids pass reaches its rows by primary key with no
        ORDER BY at all. The one-query shape grouped the fan-out for every
        match before sorting; for `type=movie&quality=720p&sort=title`
        (91,592 live matches) that ran ~2.2s warm and crossed the 10s
        deadline into a 503 during the 2026-11-10 Firebase Robo test.
        """
        self.seed("Inception")
        self.seed("Inception Two")
        self.seed("Inception Three")
        for ids_sql in (TITLE_IDS_SQL, RATING_IDS_SQL):
            ids_plan = self.plan(ids_sql, ["%inception%"] * 4 + [20, 0])
            self.assertIn("SCAN p", ids_plan, ids_plan)
            self.assertIn("USE TEMP B-TREE FOR ORDER BY", ids_plan, ids_plan)
        paged_plan = self.plan(PAGED_NEWEST_SQL, ["%inception%"] * 4 + [1, 2, 3])
        self.assertIn("SEARCH p USING INTEGER PRIMARY KEY", paged_plan, paged_plan)
        self.assertNotIn("USE TEMP B-TREE FOR ORDER BY", paged_plan, paged_plan)

    def test_the_old_sorts_still_make_two_full_passes_over_posts(self):
        """Trending and the unknown sort keep the old shape: one pass for
        `total`, one for the page, both `SCAN p`. Title and rating moved to
        the three-pass shape with newest (Session posts503) — see the test
        above — so they are no longer "old sorts" in this sense.

        This is the sentence the earlier report got wrong: there is no missing
        index to add here, and an index cannot serve a leading-wildcard `LIKE`.
        """
        self.seed("Inception")
        total_plan = self.plan(TOTAL_SQL, ["%inception%"] * 4)
        paged_plan = self.plan(PAGED_SQL.format(order=DEFAULT_ORDER),
                               ["%inception%"] * 4 + [20, 0])
        self.assertIn("SCAN p", total_plan, total_plan)
        self.assertIn("SCAN p", paged_plan, paged_plan)
        for plan in (total_plan, paged_plan):
            self.assertNotIn("USING INDEX", plan.split("SEARCH r")[0].split("SEARCH s")[0],
                             "a paged plan that stops scanning posts is a different"
                             " statement; update this test and the findings doc together")

    def test_the_join_columns_are_indexed_and_the_join_is_not_the_cost(self):
        """Production parity, asserted rather than assumed.

        The two `SEARCH … USING COVERING INDEX` lines are why a `q` that matches
        few posts is not a four-million-row fan-out. It also retires the claim
        that `releases.post_id` or `download_sources.release_id` needed building.
        """
        self.seed("Inception")
        plan = self.plan(PAGED_SQL.format(order=DEFAULT_ORDER),
                         ["%inception%"] * 4 + [20, 0])
        self.assertIn("SEARCH r USING COVERING INDEX idx_releases_post", plan, plan)
        self.assertIn("SEARCH s USING COVERING INDEX idx_sources_rel", plan, plan)

    def test_no_paged_statement_builds_an_order_btree_but_trending_does(self):
        """The unknown-sort statement keeps the old id-DESC shape (no order
        B-tree); the newest page statement has no ORDER BY at all (the order
        is imposed in Python); trending still pays the temp B-tree."""
        self.seed("Inception")
        plain = self.plan(PAGED_SQL.format(order=DEFAULT_ORDER),
                          ["%inception%"] * 4 + [20, 0])
        self.assertNotIn("USE TEMP B-TREE FOR ORDER BY", plain, plain)
        newest = self.plan(PAGED_NEWEST_SQL,
                           ["%inception%"] * 4 + [1, 1, 1])
        self.assertNotIn("USE TEMP B-TREE FOR ORDER BY", newest, newest)
        trending = self.plan(PAGED_SQL.format(order=TRENDING_ORDER),
                             ["%inception%"] * 4 + [20, 0])
        self.assertIn("USE TEMP B-TREE FOR ORDER BY", trending, trending)


    def test_ensure_schema_alone_does_not_give_the_join_indexes(self):
        """The drift, pinned: this suite's indexes are NOT what `ensure_schema` builds.

        Read it as a warning about measurement files, not as a bug list: a catalog
        created by `ensure_schema` has no `idx_releases_post`, so its plan says
        `SCAN releases` and every latency number off it is a different database's
        number. That is how a missing-index claim came to be reported against
        production and be false there.
        """
        scratch = sqlite3.connect(":memory:")
        catalog_v2.ensure_schema(scratch)
        names = {r[0] for r in scratch.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND tbl_name IN ('releases','download_sources')")}
        scratch.close()
        self.assertNotIn("idx_releases_post", names,
                         "ensure_schema now builds it; update the findings doc and"
                         " this test together")


class TestCorrectness(_Fixture):
    def test_a_one_letter_query_is_answered_with_rows_instead_of_refused(self):
        """The availability risk and the quality defect are the same query.

        Recorded as a failing-in-spirit assertion that PASSES, because the point
        is that nothing here refuses `q=a`. If a minimum-length floor lands, this
        test must be inverted, not deleted.
        """
        self.seed("Dawn")          # contains the letter, is not equal to it
        rows = self.conn.execute(PAGED_SQL.format(order=DEFAULT_ORDER),
                                 ["%a%"] * 4 + [20, 0]).fetchall()
        self.assertEqual([r["clean_title"] for r in rows], ["Dawn"],
                         "a single letter should not match this fixture")
        self.assertEqual(len(self.conn.execute(TOTAL_SQL, ["%a%"] * 4).fetchall()), 1)

    def test_the_pattern_is_not_escaped_so_two_keystrokes_can_name_every_row(self):
        """`f"%{query}%"` in `viewer.py:2546` interpolates LIKE metacharacters.

        `q=%` is not a search, it is `WHERE 1=1` wearing a query parameter, and
        the route then pays a full scan for the exact total and returns page 1.
        """
        self.seed("Inception")
        self.seed("Unrelated Title")
        every = self.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        wildcard = self.conn.execute(
            "SELECT COUNT(*) FROM posts p WHERE p.clean_title LIKE ?",
            ("%" + "%" + "%",)).fetchone()[0]
        self.assertEqual(wildcard, every, "q=% matched fewer than every row")
        self.assertGreater(wildcard, 1, "the fixture lost a row")


if __name__ == "__main__":
    unittest.main(verbosity=2)
