#!/usr/bin/env python3
"""
Offline tests for import_mp4moviez.py — the legacy-database converter.

The asset under test is 29,848 scraped pages that `merge_catalogs.py` currently
refuses to read, so the suite is built around the two ways a converter like this
fails quietly:

* it loses rows — a duplicate slug replacing the film it was keyed onto, or a
  release that never reaches `sources`;
* it invents rows — a `final_url` or an `active` status for a link that was never
  probed, which would put a play-time result in durable storage.

Everything here runs against a synthetic legacy database in a temp directory with
`socket.socket` replaced by a raiser: the converter opens no connection, and a
test that accidentally tried to would fail instead of touching mp4moviez.deal.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import import_mp4moviez as mp  # noqa: E402


class _NoLiveSocket:
    def __init__(self, *a, **kw):
        raise AssertionError("an offline test tried to open a socket")


socket.socket = _NoLiveSocket  # type: ignore[assignment]


LEGACY_SCHEMA = """
CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    source_url TEXT, clean_title TEXT, year INTEGER, genres TEXT, duration TEXT,
    languages TEXT, cast_names TEXT, poster_url TEXT, synopsis TEXT, tags TEXT,
    is_18_plus INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT);
CREATE TABLE releases (
    id INTEGER PRIMARY KEY, post_id INTEGER, quality TEXT, url TEXT, resolved INTEGER);
CREATE TABLE sitemap_cache (url TEXT, lastmod TEXT, processed INTEGER);
"""

MOVIE_URL = ("https://www.mp4moviez.deal/the-incomer-(2026)-english-movie.html")
REPOST_URL = ("https://www.mp4moviez.deal/c60938/the-incomer-(2026)-english-movie.html")
DL = "https://www.mp4moviez.deal/dl.php?id=60938&q={q}&title=the-incomer-(2026)-english-movie"


def post(pid, url, title, year=2026, is_18_plus=0, **extra):
    row = dict(id=pid, source_url=url, clean_title=title, year=year, genres=None,
               duration=None, languages=None, cast_names=None, poster_url=None,
               synopsis=None, tags=None, is_18_plus=is_18_plus,
               created_at="2026-08-01 00:00:00", updated_at="2026-08-01 00:00:00")
    row.update(extra)
    return row


def release(rid, pid, quality, dl_id=60938):
    return dict(id=rid, post_id=pid, quality=quality,
                url=DL.format(q=quality.rstrip("p")), resolved=0)


def make_legacy_db(path: Path, posts, releases, queue=()) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany(
        "INSERT INTO posts (id, source_url, clean_title, year, genres, duration,"
        " languages, cast_names, poster_url, synopsis, tags, is_18_plus, created_at,"
        " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?);",
        [(p["id"], p["source_url"], p["clean_title"], p["year"], p["genres"],
          p["duration"], p["languages"], p["cast_names"], p["poster_url"],
          p["synopsis"], p["tags"], p["is_18_plus"], p["created_at"],
          p["updated_at"]) for p in posts])
    conn.executemany(
        "INSERT INTO releases (id, post_id, quality, url, resolved) VALUES (?,?,?,?,?);",
        [(r["id"], r["post_id"], r["quality"], r["url"], r["resolved"])
         for r in releases])
    conn.executemany("INSERT INTO sitemap_cache (url, lastmod, processed) VALUES (?,?,?);",
                     list(queue))
    conn.commit()
    conn.close()


class _TempDbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mp4moviez-test-"))
        self.db = self.tmp / "mp4moviez.db"

    def tearDown(self):
        for f in self.tmp.glob("*"):
            f.unlink()
        self.tmp.rmdir()

    def build(self, posts, releases, queue=()):
        make_legacy_db(self.db, posts, releases, queue)

    def open(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        return conn


class TestFieldDerivation(unittest.TestCase):
    def test_slug_and_anchor_come_from_the_url(self):
        self.assertEqual(mp.slug_from(MOVIE_URL),
                         "the-incomer-(2026)-english-movie")
        self.assertEqual(mp.anchor_from(REPOST_URL), "c60938")
        self.assertEqual(mp.anchor_from(MOVIE_URL), "")

    def test_dl_id_is_the_sites_own_number(self):
        self.assertEqual(mp.dl_id(DL.format(q=720)), "60938")
        self.assertEqual(mp.dl_id(""), "")

    def test_title_boilerplate_is_stripped(self):
        self.assertEqual(
            mp.clean_title("Download The Incomer 2026 English Movie in HD"),
            "The Incomer 2026 English Movie")
        self.assertEqual(mp.year_of("The Incomer 2026 English Movie"), 2026)

    def test_series_shape_is_read_from_the_title(self):
        self.assertEqual(mp.media_type_of("Marshals 2026 Season 2 Hindi Dubbed "
                                         "TV Series"), "series")
        self.assertEqual(mp.media_type_of("The Incomer 2026 English Movie"), "movie")
        self.assertEqual(mp.season_of("Season 2 Episode 5"), 2)
        self.assertEqual(mp.episode_of("Season 2 Episode 5"), 5)


class TestIsWork(unittest.TestCase):
    """The 1,438 rows that are not works must not become catalog entries."""

    def test_listing_page_without_links_is_rejected(self):
        self.assertFalse(mp.is_work(post(1, "https://www.mp4moviez.deal/352/latest-"
                                       "hollywood-hindi-dubbed-tv-series-(2026).html",
                                       "Latest Hollywood Hindi Dubbed TV Series"), 0))

    def test_takedown_notice_is_rejected_even_with_an_anchor(self):
        row = post(2, "https://www.mp4moviez.deal/c1/the-dark-knight-(2008)-hindi-"
                      "dubbed-movie.html",
                   "The requested file is not available anymore due to a copyright "
                   "claim please contact admin")
        self.assertFalse(mp.is_work(row, 0))

    def test_sitemap_url_and_untitled_rows_are_rejected(self):
        self.assertFalse(mp.is_work(post(3, "https://www.mp4moviez.deal/sitemap.xml",
                                         "Sitemap"), 4))
        self.assertFalse(mp.is_work(post(4, MOVIE_URL, "   "), 4))

    def test_unlinked_work_page_is_kept_with_an_anchor(self):
        """14,730 pages: a real title whose links the site has since removed."""
        row = post(5, "https://www.mp4moviez.deal/c60941/kopis-(2026)-english-movie.html",
                   "Download Kopis 2026 English Movie in HD")
        self.assertTrue(mp.is_work(row, 0))

    def test_release_row_alone_qualifies_without_an_anchor(self):
        self.assertTrue(mp.is_work(post(6, MOVIE_URL, "The Incomer"), 1))


class TestTransform(_TempDbCase):
    def test_contract_fields_and_unverified_provenance(self):
        self.build([post(1, MOVIE_URL, "Download The Incomer 2026 English Movie in HD")],
                   [release(1, 1, "720p")])
        conn = self.open()
        try:
            posts, releases_by_post = mp._legacy_rows(conn)
            record = mp.transform_post(posts[0], releases_by_post[1])
        finally:
            conn.close()

        row = record["post"]
        self.assertEqual(row["canonical_key"], "the-incomer-(2026)-english-movie")
        self.assertEqual(row["clean_title"], "The Incomer 2026 English Movie")
        self.assertEqual(row["year"], 2026)
        self.assertEqual(row["media_type"], "movie")
        self.assertEqual(row["source_site"], "mp4moviez")
        self.assertEqual(row["is_18_plus"], 0)
        self.assertEqual(row["is_animated"], 0)
        # The legacy row never read a synopsis; the converter must not write one.
        self.assertIsNone(row["synopsis"])
        self.assertIsNone(row["imdb_id"])

        rel = record["releases"][0]
        self.assertEqual(rel["post_canonical_key"], row["canonical_key"])
        self.assertEqual(rel["quality"], "720p")
        self.assertEqual(rel["bridge_url"], DL.format(q=720))
        self.assertEqual(rel["raw_meta"]["site_movie_id"], "60938")

    def test_adult_flag_is_carried_at_storage_time(self):
        self.build([post(1, MOVIE_URL, "Download Kopis 2026 English Movie", is_18_plus=1)],
                   [release(1, 1, "720p")])
        conn = self.open()
        try:
            posts, releases_by_post = mp._legacy_rows(conn)
            record = mp.transform_post(posts[0], releases_by_post[1])
        finally:
            conn.close()
        self.assertEqual(record["post"]["is_18_plus"], 1)

    def test_unlinked_work_records_that_it_has_no_links(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            record = mp.transform_post(
                post(1, "https://www.mp4moviez.deal/c60941/kopis-(2026)-english-movie.html",
                     "Download Kopis 2026 English Movie in HD"), [])
        finally:
            conn.close()
        self.assertEqual(record["releases"], [])
        self.assertIn("no download row", record["post"]["raw_meta"]["link_source"])


class TestDuplicateMerge(_TempDbCase):
    def test_repost_under_a_new_anchor_collapses_without_losing_either_page(self):
        self.build(
            [post(1, MOVIE_URL, "Download The Incomer 2026 English Movie in HD"),
             post(2, REPOST_URL, "Download The Incomer 2026 English Movie HDRip",
                  poster_url="https://www.mp4moviez.deal/incomer.jpg")],
            [release(1, 1, "720p"), release(2, 1, "480p"),
             release(3, 2, "1080p")])
        conn = self.open()
        try:
            records = mp.build_records(conn)
        finally:
            conn.close()
        self.assertEqual(len(records), 1)
        row = records[0]["post"]
        self.assertEqual(row["canonical_key"], "the-incomer-(2026)-english-movie")
        # fill-in, not overwrite: the second page's poster survives the merge.
        self.assertEqual(row["poster_url"], "https://www.mp4moviez.deal/incomer.jpg")
        self.assertEqual(len(records[0]["releases"]), 3)
        self.assertIn(REPOST_URL, row["raw_meta"]["duplicate_pages"])

    def test_adult_flag_is_sticky_across_a_merge(self):
        self.build([post(1, MOVIE_URL, "Title A", is_18_plus=1),
                    post(2, REPOST_URL, "Title A")],
                   [release(1, 1, "720p"), release(2, 2, "480p")])
        conn = self.open()
        try:
            records = mp.build_records(conn)
        finally:
            conn.close()
        self.assertEqual(records[0]["post"]["is_18_plus"], 1)

    def test_identical_repost_does_not_duplicate_its_release_rows(self):
        self.build([post(1, MOVIE_URL, "The Incomer"), post(2, REPOST_URL, "The Incomer")],
                   [release(1, 1, "720p"), release(2, 2, "720p")])
        conn = self.open()
        try:
            records = mp.build_records(conn)
        finally:
            conn.close()
        self.assertEqual(len(records[0]["releases"]), 1)


class TestConvert(_TempDbCase):
    FULL = staticmethod(lambda: (
        [post(1, MOVIE_URL, "Download The Incomer 2026 English Movie in HD"),
         post(2, REPOST_URL, "Download The Incomer 2026 English Movie HDRip"),
         post(3, "https://www.mp4moviez.deal/c60942/chip-in-(2026)-season-1-hindi-"
                 "dubbed-complete-k-drama-series.html",
              "Download Chip In 2026 Season 1 Hindi Dubbed Complete K Drama Series",
              is_18_plus=1),
         post(4, "https://www.mp4moviez.deal/352/latest-hollywood.html", "Latest"),
         post(5, "https://www.mp4moviez.deal/sitemap.xml", "Sitemap")],
        [release(1, 1, "720p"), release(2, 1, "480p"), release(3, 2, "1080p")]))

    def test_conversion_writes_exactly_what_the_plan_promised(self):
        posts, releases = self.FULL()
        self.build(posts, releases, queue=[("https://www.mp4moviez.deal/x.html", None, 0)])
        conn = self.open()
        try:
            before = mp.plan(conn)
        finally:
            conn.close()
        result = mp.convert(self.db)
        self.assertTrue(result["converted"], result)
        self.assertEqual(result["posts"], before["converted_posts"])
        self.assertEqual(result["releases"], before["converted_releases"])
        self.assertEqual(result["sources"], before["converted_sources"])
        # 5 legacy pages -> 2 works (one is the same film re-posted under a new
        # c<id> path), 3 releases, 3 sources, and the 2 non-works dropped.
        self.assertEqual(before["legacy_posts"], 5)
        self.assertEqual(before["converted_posts"], 2)
        self.assertEqual(before["converted_releases"], 3)
        self.assertEqual(before["converted_sources"], 3)
        self.assertEqual(before["merged_duplicate_pages"], 1)
        self.assertEqual(before["skipped_no_release"], 3)
        self.assertEqual(before["converted_18_plus"], 1)
        self.assertEqual(before["converted_series"], 1)
        self.assertEqual(before["queue_rows_left_alone"], 1)
        self.assertEqual(before["queue_never_fetched"], 1)

        conn = self.open()
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(posts)")}
            self.assertIn("canonical_key", cols)
            self.assertTrue(mp.already_converted(conn))
            row = conn.execute("SELECT canonical_key, title, scraped_at FROM posts "
                               "ORDER BY canonical_key").fetchall()
            self.assertEqual(row[0]["canonical_key"], "chip-in-(2026)-season-1-hindi-"
                                                      "dubbed-complete-k-drama-series")
            self.assertEqual(row[0]["scraped_at"], "2026-08-01 00:00:00")
            # The fleet contract wants a non-null key: the new table refuses a
            # keyless post rather than letting merge_catalogs collapse on NULL.
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO posts (canonical_key, title, clean_title) "
                             "VALUES (NULL, 'x', 'x')")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sources WHERE final_url IS NOT NULL"
                             " OR status <> 'unverified' OR last_checked IS NOT NULL"
                             ).fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT playback_type, COUNT(*) FROM sources GROUP BY 1")
                     .fetchall()[0]["playback_type"], "download")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM releases r WHERE NOT EXISTS "
                             "(SELECT 1 FROM sources s WHERE s.release_id = r.id)"
                             ).fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0], 1)
        finally:
            conn.close()

    def test_conversion_is_idempotent(self):
        posts, releases = self.FULL()
        self.build(posts, releases)
        mp.convert(self.db)
        again = mp.convert(self.db)
        self.assertFalse(again["converted"])
        self.assertIn("already carries", again["reason"])
        conn = self.open()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 2)
        finally:
            conn.close()

    def test_dry_run_writes_nothing(self):
        posts, releases = self.FULL()
        self.build(posts, releases)
        result = mp.convert(self.db, dry_run=True)
        self.assertFalse(result["converted"])
        conn = self.open()
        try:
            self.assertNotIn("canonical_key",
                             {r[1] for r in conn.execute("PRAGMA table_info(posts)")})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 5)
        finally:
            conn.close()

    def test_failure_mid_migration_leaves_the_legacy_tables_intact(self):
        posts, releases = self.FULL()
        self.build(posts, releases)
        real_values = mp._values
        calls = {"n": 0}

        def explode(row, columns):
            calls["n"] += 1
            if calls["n"] == 3:  # third release row: the write is already underway
                raise sqlite3.OperationalError("boom")
            return real_values(row, columns)

        mp._values = explode
        try:
            with self.assertRaises(sqlite3.OperationalError):
                mp.convert(self.db)
        finally:
            mp._values = real_values
        conn = self.open()
        try:
            tables = mp._legacy_tables(conn)
            self.assertIn("posts", tables)
            self.assertNotIn("posts_new", tables)
            self.assertNotIn("sources", tables)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 5)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 3)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(posts)")}
            self.assertNotIn("canonical_key", cols)
        finally:
            conn.close()

    def test_a_convert_of_a_database_without_legacy_tables_refuses(self):
        sqlite3.connect(self.db).close()
        result = mp.convert(self.db)
        self.assertFalse(result["converted"])
        self.assertIn("legacy posts/releases", result["reason"])


class TestMergeContractRead(_TempDbCase):
    """
    The whole point of the asset: merge_catalogs.py must be able to read it.

    Before this converter, `_source_family` raised ValueError on mp4moviez.db
    because the file had no `sources` table, so the largest staging database in
    the fleet could not enter the merge queue at all.
    """

    def setUp(self):
        super().setUp()
        merge = import_merge_catalogs()
        if merge is None:
            self.skipTest("merge_catalogs.py unavailable in this environment")
        self.merge = merge

    def test_the_converted_database_reads_as_staging_and_yields_sources(self):
        self.build(
            [post(1, MOVIE_URL, "Download The Incomer 2026 English Movie in HD",
                  genres='["Action"]', languages='["English"]')],
            [release(1, 1, "720p"), release(2, 1, "480p")])
        self.assertTrue(mp.convert(self.db)["converted"])

        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            self.assertEqual(self.merge._source_family(conn), "staging")
            stored = conn.execute("SELECT * FROM posts WHERE canonical_key = ?",
                                  ("the-incomer-(2026)-english-movie",)).fetchone()
            collected = self.merge._collect_staging_post(conn, stored, "mp4moviez")
        finally:
            conn.close()

        self.assertEqual(collected["source_site"], "mp4moviez")
        self.assertEqual(collected["content_type"], "movie")
        self.assertEqual(collected["url"], MOVIE_URL)
        self.assertEqual(len(collected["releases"]), 2)
        first = collected["releases"][0]
        self.assertEqual(len(first["sources"]), 1)
        src = first["sources"][0]
        self.assertEqual(src["service"], "mp4moviez")
        self.assertEqual(src["resource_id"], "60938")
        self.assertIsNone(src.get("final_url"))
        self.assertEqual(src["status"], "unverified")

    def test_a_release_with_no_sources_row_is_not_fabricated_into_one(self):
        self.build([post(1, "https://www.mp4moviez.deal/c60941/kopis-(2026)-english-"
                            "movie.html", "Download Kopis 2026 English Movie in HD")], [])
        mp.convert(self.db)
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            stored = conn.execute("SELECT * FROM posts").fetchone()
            collected = self.merge._collect_staging_post(conn, stored, "mp4moviez")
            self.assertEqual(collected["releases"], [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        finally:
            conn.close()


def import_merge_catalogs():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        import merge_catalogs  # noqa: WPS433
        return merge_catalogs
    except Exception:
        return None


class TestRawMetaIsJson(_TempDbCase):
    def test_raw_meta_columns_are_serialised_as_json_text(self):
        self.build([post(1, MOVIE_URL, "The Incomer")], [release(1, 1, "720p")])
        mp.convert(self.db)
        conn = self.open()
        try:
            for table, column in (("posts", "raw_meta"), ("releases", "raw_meta")):
                value = conn.execute(f"SELECT {column} FROM {table}").fetchone()[0]
                self.assertIsInstance(json.loads(value), dict, f"{table}.{column}")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
