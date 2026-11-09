"""Scale quick wins (Session 125): serve-path pragmas + search limits.

The serve pragmas live in one helper (`db_pragmas.apply_serve_pragmas`) so a
connection nobody wires is the same as no pragmas at all. These tests pin
both halves: the helper's values on a real file, and every serve-path call
site actually applying them — plus the search side of the batch (the
in-function limit clamp, the 10 s deadline, and the 503 `search_timeout`
on the HTTP branch).

Offline, stdlib, tempfile fixtures, no network except loopback to the
in-process test server for the 503 proof. `mmap_size` assertions use file
DBs only: a `:memory:` database has nothing to map and answers no row.
"""

import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accounts
import admin_panel
import api_v2
import catalog_v2
import db_pragmas
import engagement
import fast_fetch
import panel_feed
import redact
import viewer

#: The helper's values, read back off a live file-DB connection.
EXPECTED = {
    "journal_mode": "wal",
    "busy_timeout": 30000,
    "foreign_keys": 1,
    "cache_size": -65536,
    "mmap_size": 268435456,
    "temp_store": 2,
    "synchronous": 1,
    "wal_autocheckpoint": 1000,
}

_BASELINE_NEEDLES = redact.needles()
_BASELINE_TEXT_NEEDLES = redact.text_needles()


def _check_pragmas(test, conn, *, busy_timeout=30000, journal_mode="wal"):
    """`read_pragmas` on `conn` is EXPECTED, with the two named overrides."""
    got = db_pragmas.read_pragmas(conn)
    want = dict(EXPECTED)
    want["busy_timeout"] = busy_timeout
    want["journal_mode"] = journal_mode
    test.assertEqual(got, want)


class HelperValuesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "helper.db"

    def test_apply_sets_all_eight_pragmas_on_a_file_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            db_pragmas.apply_serve_pragmas(conn)
            _check_pragmas(self, conn)
        finally:
            conn.close()

    def test_constants_are_the_decided_values(self):
        # -65536 = 64 MiB per connection, not the build note's -131072:
        # ThreadingMixIn is one thread per connection, unbounded, so
        # 128 MiB x an unbounded thread count was unbounded memory.
        self.assertEqual(db_pragmas.CACHE_SIZE_PAGES, -65536)
        self.assertEqual(db_pragmas.MMAP_SIZE_BYTES, 268435456)
        self.assertEqual(db_pragmas.BUSY_TIMEOUT_MS, 30000)

    def test_read_pragmas_is_none_safe_on_a_memory_db(self):
        # `mmap_size` answers no row on a :memory: database (there is
        # nothing to map); every other pragma answers one row.
        conn = sqlite3.connect(":memory:")
        try:
            db_pragmas.apply_serve_pragmas(conn)
            got = db_pragmas.read_pragmas(conn)
        finally:
            conn.close()
        self.assertEqual(set(got), set(EXPECTED))
        self.assertIsNone(got["mmap_size"])
        self.assertEqual(got["cache_size"], -65536)
        self.assertEqual(got["temp_store"], 2)


class ServePathPragmaTests(unittest.TestCase):
    """Every serve-path call site returns the helper values."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "serve.db"
        # The file must exist before a mode=ro handle can open it.
        sqlite3.connect(self.db_path).close()

    def test_fast_fetch_get_db(self):
        with fast_fetch.get_db(self.db_path) as conn:
            _check_pragmas(self, conn)

    def test_viewer_get_db(self):
        with patch.object(viewer, "DB_PATH", self.db_path):
            with viewer.get_db() as conn:
                _check_pragmas(self, conn)

    def test_api_v2_session(self):
        with api_v2.session(self.db_path) as conn:
            _check_pragmas(self, conn)

    def test_admin_panel_session(self):
        with admin_panel._session(self.db_path) as conn:
            _check_pragmas(self, conn)

    def test_accounts_connect_keeps_5000_busy_timeout(self):
        conn = accounts.connect(self.db_path, install_schema=False)
        try:
            _check_pragmas(self, conn, busy_timeout=5000)
        finally:
            conn.close()

    def test_engagement_connect_keeps_5000_busy_timeout(self):
        conn = engagement.connect(self.db_path, install_schema=False)
        try:
            _check_pragmas(self, conn, busy_timeout=5000)
        finally:
            conn.close()

    def test_accounts_catalog_oracle_takes_the_catalog_timeout(self):
        # A catalog connection, so the 30000 ms catalog value — even
        # though the oracle lives in accounts.py next to the 5000 ms
        # user-state helpers. The file's journal mode stays "delete": a
        # read-only handle must not flip it.
        conn = accounts._open_catalog_read_only(self.db_path)
        try:
            _check_pragmas(self, conn, busy_timeout=30000,
                           journal_mode="delete")
        finally:
            conn.close()

    def test_panel_feed_open_panel_keeps_5000_busy_timeout(self):
        # The panel database is neither the catalog nor the user-state DB,
        # and no rule in this batch re-times it: its live value (sqlite's
        # 5000 ms default) is kept. Read-only, so journal_mode stays put.
        conn = panel_feed._open_panel(self.db_path)
        try:
            self.assertIsNotNone(conn)
            _check_pragmas(self, conn, busy_timeout=5000,
                           journal_mode="delete")
        finally:
            if conn is not None:
                conn.close()


class RedactSiteTests(unittest.TestCase):
    """The `redact` connect sites call the helper (their connections are
    internal, so the call is recorded instead of read back) and keep
    answering the same values."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "redact.db"
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY,"
                     " poster_url TEXT, backdrop_urls TEXT,"
                     " is_18_plus INTEGER, source_site TEXT)")
        conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY,"
                     " post_id INTEGER)")
        conn.execute("CREATE TABLE download_sources (id INTEGER PRIMARY KEY,"
                     " release_id INTEGER)")
        conn.execute("CREATE TABLE server_state (key TEXT PRIMARY KEY,"
                     " value TEXT)")
        conn.execute("INSERT INTO posts VALUES (1, 'https://img.example/p.jpg',"
                     " '[\"https://img.example/b.jpg\"]', 0, 'testsite123')")
        conn.execute("INSERT INTO posts VALUES (2, NULL, NULL, 1, 'testsite123')")
        conn.execute("INSERT INTO releases VALUES (10, 1)")
        conn.execute("INSERT INTO download_sources VALUES (100, 10)")
        conn.execute("INSERT INTO server_state VALUES ('stream_secret', 'abc')")
        conn.commit()
        conn.close()

    def test_sites_call_the_helper_and_keep_their_answers(self):
        calls = []
        real = db_pragmas.apply_serve_pragmas

        def recording(conn, **kwargs):
            calls.append(conn)
            return real(conn, **kwargs)

        with patch.object(db_pragmas, "apply_serve_pragmas",
                          side_effect=recording):
            self.assertEqual(
                redact.art_url_for(1, "poster", 0, self.db_path),
                "https://img.example/p.jpg")
            self.assertFalse(redact.art_is_adult(1, self.db_path))
            self.assertTrue(redact.art_is_adult(2, self.db_path))
            self.assertFalse(redact.link_is_adult(100, self.db_path))
            self.assertTrue(redact.link_is_adult(999999, self.db_path))
            self.assertEqual(redact._read_legacy_db_secret(self.db_path), "abc")
            self.assertIn("testsite123", redact.site_needles(self.db_path))
            self.assertIn("testsite123", redact.site_text_needles(self.db_path))
        # Six connect sites in the code, eight invocations here
        # (art_is_adult and link_is_adult are each called twice).
        self.assertEqual(len(calls), 8)
        for conn in calls:
            self.assertIsInstance(conn, sqlite3.Connection)


class SearchLimitTests(unittest.TestCase):
    """The in-function limit clamp + the 10 s search deadline."""

    def setUp(self):
        redact.set_needles(_BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.addCleanup(redact.set_needles, _BASELINE_NEEDLES,
                        _BASELINE_TEXT_NEEDLES)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        for patcher in (patch.object(fast_fetch, "DB_PATH", self.db_path),
                        patch.object(viewer, "DB_PATH", self.db_path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        fast_fetch.init_db(self.db_path)
        # Enough rows that the count + page queries execute well past the
        # 1000-instruction progress-handler interval — a 3-row fixture
        # would never trip the deadline handler at all.
        conn = sqlite3.connect(self.db_path)
        # The by-media evidence query reads the v2 projection tables, so
        # the fixture carries that schema too (same as test_media_search).
        catalog_v2.ensure_schema(conn)
        conn.commit()
        conn.executemany(
            "INSERT INTO posts (clean_title, title, year, content_type,"
            " url, is_18_plus) VALUES (?, ?, 2024, 'movie', ?, 0)",
            [("Film %04d" % i, "Film %04d" % i,
              "https://example.test/film-%04d" % i) for i in range(300)])
        conn.commit()
        conn.close()

    def test_limit_clamps_to_100(self):
        self.assertEqual(viewer.api_v1_get_posts(limit=500)["limit"], 100)
        self.assertEqual(viewer.api_v1_get_posts(limit=101)["limit"], 100)

    def test_limit_clamps_to_at_least_1(self):
        self.assertEqual(viewer.api_v1_get_posts(limit=0)["limit"], 1)
        self.assertEqual(viewer.api_v1_get_posts(limit=-3)["limit"], 1)

    def test_limit_inside_the_range_is_untouched(self):
        self.assertEqual(viewer.api_v1_get_posts(limit=7)["limit"], 7)

    def test_by_media_already_clamps_to_50_internally(self):
        # No change was made here: `media_search.search_by_media` clamps
        # `min(50, max(1, int(limit or 10)))` before it queries. This pins
        # that the clamp exists, so a future refactor cannot drop it.
        import media_search
        with viewer.get_db() as conn:
            result = media_search.search_by_media(
                conn, title="Film", limit=500)
        self.assertEqual(len(result["results"]), 50)

    def test_past_deadline_aborts_the_query(self):
        # The progress handler returns 1 past the deadline; CPython's
        # sqlite3 surfaces that as OperationalError("interrupted") — a
        # raise inside the callback is swallowed, so this is the signal
        # the /api/v1/posts branch maps to 503 `search_timeout`.
        with patch.object(viewer, "SEARCH_DEADLINE_SECONDS", 0):
            with self.assertRaisesRegex(sqlite3.OperationalError,
                                        "interrupted"):
                viewer.api_v1_get_posts()

    def test_normal_deadline_answers(self):
        result = viewer.api_v1_get_posts()
        self.assertEqual(result["total"], 300)
        self.assertEqual(len(result["results"]), 20)


class PostsHttpTimeoutTests(unittest.TestCase):
    """The /api/v1/posts branch answers a timed-out search with 503
    `search_timeout`, not a hung worker past nginx's 15 s read timeout."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "catalog.db"
        cls._db_patch = patch.object(viewer, "DB_PATH", cls.db_path)
        cls._db_patch.start()
        fast_fetch.init_db(cls.db_path)
        conn = sqlite3.connect(cls.db_path)
        conn.executemany(
            "INSERT INTO posts (clean_title, title, year, content_type,"
            " url, is_18_plus) VALUES (?, ?, 2024, 'movie', ?, 0)",
            [("Film %04d" % i, "Film %04d" % i,
              "https://example.test/film-%04d" % i) for i in range(300)])
        conn.commit()
        conn.close()
        cls.server = viewer.make_server("127.0.0.1", 0, operator=False)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._db_patch.stop()
        cls.tmp.cleanup()

    def _get_posts(self):
        redact.limiter._buckets.clear()
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/v1/posts" % self.port,
                    timeout=15) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def test_normal_request_is_200(self):
        status, _body = self._get_posts()
        self.assertEqual(status, 200)

    def test_past_deadline_is_503_search_timeout(self):
        with patch.object(viewer, "SEARCH_DEADLINE_SECONDS", 0):
            status, body = self._get_posts()
        self.assertEqual(status, 503)
        self.assertIn("search_timeout", body)


if __name__ == "__main__":
    unittest.main()
