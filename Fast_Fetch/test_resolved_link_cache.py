"""Tests for resolved_link_cache.py (Session 123, scale plan B2).

The fixture is a small in-memory database with the three tables the module
reads: `download_sources` (the ledger rows whose stored resolution is the
cache), `cat_works` (the adult flag) and `cat_links` (the projector's rank).
No network, no resolver — `warm()` takes a fake `resolve` callable.
"""
import sqlite3
import time
import unittest

import resolved_link_cache


def _fixture():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE download_sources (
            id INTEGER PRIMARY KEY, final_url TEXT, is_temporary INTEGER,
            expires_at REAL, last_checked_at TEXT, status TEXT)
    """)
    conn.execute("""
        CREATE TABLE cat_works (id INTEGER PRIMARY KEY, is_18_plus INTEGER)
    """)
    conn.execute("""
        CREATE TABLE cat_links (
            id INTEGER PRIMARY KEY, work_id INTEGER, ledger_link_id INTEGER,
            playability TEXT, state TEXT, rank_score INTEGER)
    """)
    return conn


def _stamp(offset_seconds):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + offset_seconds))


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.conn = _fixture()

    def tearDown(self):
        self.conn.close()

    def _row(self, link_id, final_url="https://cdn.example/x.mp4", temp=0,
             expires_at=None, last_checked=None):
        self.conn.execute(
            "INSERT INTO download_sources (id, final_url, is_temporary,"
            " expires_at, last_checked_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (link_id, final_url, temp, expires_at, last_checked))

    def test_missing_row_is_none(self):
        self.assertIsNone(resolved_link_cache.freshness(self.conn, 999))

    def test_no_cached_url_is_stale(self):
        self._row(1, final_url=None)
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertFalse(got["fresh"])
        self.assertEqual(got["reason"], "no_cached_url")

    def test_measured_window_future_is_fresh(self):
        self._row(1, expires_at=time.time() + 3600)
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertTrue(got["fresh"])
        self.assertEqual(got["reason"], "measured_window")
        self.assertGreater(got["expires_in"], 0)

    def test_measured_window_past_is_stale(self):
        self._row(1, expires_at=time.time() - 60)
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertFalse(got["fresh"])
        self.assertEqual(got["reason"], "measured_window")

    def test_unreadable_expiry_falls_through_to_the_ceiling(self):
        # A garbage stamp is no measurement: the temporary ceiling decides.
        self._row(1, temp=1, expires_at="not-a-number",
                  last_checked=_stamp(-3600))
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertTrue(got["fresh"])
        self.assertEqual(got["reason"], "temporary_ceiling")

    def test_temporary_inside_the_ceiling_is_fresh(self):
        self._row(1, temp=1, last_checked=_stamp(-3600))
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertTrue(got["fresh"])
        self.assertEqual(got["reason"], "temporary_ceiling")

    def test_temporary_past_the_ceiling_is_stale(self):
        self._row(1, temp=1, last_checked=_stamp(-7 * 3600))
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertFalse(got["fresh"])
        self.assertEqual(got["reason"], "temporary_stale")

    def test_temporary_never_checked_is_stale(self):
        self._row(1, temp=1, last_checked=None)
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertFalse(got["fresh"])
        self.assertEqual(got["reason"], "temporary_stale")

    def test_permanent_cached_is_fresh(self):
        self._row(1, temp=0, last_checked=None)
        got = resolved_link_cache.freshness(self.conn, 1)
        self.assertTrue(got["fresh"])
        self.assertEqual(got["reason"], "permanent_cached")

    def test_the_ceiling_is_six_hours(self):
        self.assertEqual(resolved_link_cache.TEMPORARY_FRESH_HOURS, 6.0)


class TopLinksTests(unittest.TestCase):
    def setUp(self):
        self.conn = _fixture()
        self.conn.execute("INSERT INTO cat_works VALUES (1, 0)")
        self.conn.execute("INSERT INTO cat_works VALUES (2, 1)")
        # id, work_id, ledger_link_id, playability, state, rank_score
        rows = [
            (1, 1, 101, "stream", "active", 90),
            (2, 1, 102, "both", "unchecked", 95),
            (3, 1, 103, "download", "active", 99),
            (4, 2, 104, "stream", "active", 100),
            (5, 1, None, "stream", "active", 98),
            (6, 1, 105, "stream", "active", 50),
        ]
        self.conn.executemany(
            "INSERT INTO cat_links VALUES (?, ?, ?, ?, ?, ?)", rows)

    def tearDown(self):
        self.conn.close()

    def test_orders_by_rank_and_excludes_adult_download_only_and_unlinked(self):
        # 104 is the adult work's link (highest rank, excluded); 103 is
        # download-only; the NULL ledger id cannot be resolved.
        self.assertEqual(resolved_link_cache.top_links(self.conn), [102, 101, 105])

    def test_limit_is_honoured(self):
        self.assertEqual(resolved_link_cache.top_links(self.conn, limit=2), [102, 101])


class WarmTests(unittest.TestCase):
    def setUp(self):
        self.conn = _fixture()
        self.conn.execute("INSERT INTO cat_works VALUES (1, 0)")
        for link_id in (201, 202, 203, 204):
            self.conn.execute(
                "INSERT INTO download_sources (id, final_url, is_temporary,"
                " expires_at, last_checked_at, status)"
                " VALUES (?, ?, 1, NULL, NULL, 'active')",
                (link_id, "https://cdn.example/%d.mp4" % link_id))
        # 201 is already fresh (measured window), so the warmer must skip it.
        self.conn.execute("UPDATE download_sources SET expires_at = ? WHERE id = 201",
                          (time.time() + 3600,))
        rows = [
            (1, 1, 201, "stream", "active", 40),
            (2, 1, 202, "stream", "active", 30),
            (3, 1, 203, "stream", "active", 20),
            (4, 1, 204, "stream", "active", 10),
        ]
        self.conn.executemany(
            "INSERT INTO cat_links VALUES (?, ?, ?, ?, ?, ?)", rows)

    def tearDown(self):
        self.conn.close()

    def test_skips_fresh_links_and_counts_outcomes(self):
        calls = []

        def fake_resolve(link_id):
            calls.append(link_id)
            if link_id == 203:
                return {"success": False}
            return {"success": True, "cached": False, "refreshed": True}

        report = resolved_link_cache.warm(self.conn, resolve=fake_resolve)
        self.assertEqual(calls, [202, 203, 204])
        self.assertEqual(report["attempted"], 4)
        self.assertEqual(report["already_fresh"], 1)
        self.assertEqual(report["refreshed"], 2)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["failures"], [203])

    def test_a_raising_resolver_does_not_abort_the_run(self):
        def fake_resolve(link_id):
            if link_id == 202:
                raise RuntimeError("boom")
            return {"success": True, "cached": True}

        report = resolved_link_cache.warm(self.conn, resolve=fake_resolve)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["served_cached"], 2)
        self.assertEqual(report["failures"], [202])


if __name__ == "__main__":
    unittest.main()
