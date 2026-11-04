#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for `Fast_Fetch/resolved_cache.py` and its stream-route contract.

The rule this file protects: a cache hit means *we knocked on that exact URL
and it answered with media* — a scraper's say-so is never cached. Every
servability decision is tested here: hit, miss, expiry fallback, want/kind
filtering (a playlist is never a download), the category freshness caps, the
failure circuit, and the IP-bound sharing rule.

No network, no production DB: every test runs against an in-memory SQLite.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import resolved_cache  # noqa: E402


def fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    resolved_cache.init_resolved_cache(conn)
    return conn


# A realistic answer shaped like resolve_live_source's stage-1 cached return.
def file_resolve(**over) -> dict:
    data = {
        "success": True, "id": 77,
        "url": "https://pixeldrain.com/api/file/s2yMcLkb",
        "cached": True, "refreshed": False, "service": "pixeldrain",
        "is_temporary": False, "is_resumable": True,
        "source_name": "Pixeldrain", "mime_type": "video/mp4",
        "file_size_bytes": 2_405_181_686,
    }
    data.update(over)
    return data


def playlist_resolve(**over) -> dict:
    data = {
        "success": True, "id": 88,
        "url": "https://embed.vidrift.net/api/orion/9d6a/master.m3u8?token=abc",
        "service": "vidrift", "is_temporary": True, "is_resumable": False,
        "mime_type": "application/vnd.apple.mpegurl", "file_size_bytes": None,
        "expires_in": 3600.0,
    }
    data.update(over)
    return data


class TestInit(unittest.TestCase):
    def test_init_is_idempotent(self):
        conn = fresh_conn()
        resolved_cache.init_resolved_cache(conn)  # second call must not raise
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='resolved_cache'"
        ).fetchone()[0]
        self.assertEqual(n, 1)

    def test_lookup_self_inits_missing_table(self):
        conn = sqlite3.connect(":memory:")  # no DDL run yet
        resolved_cache._SCHEMA_OK = None
        try:
            self.assertIsNone(resolved_cache.lookup_cache(conn, 1))
            rows = conn.execute("SELECT COUNT(*) FROM resolved_cache").fetchone()[0]
            self.assertEqual(rows, 0)
        finally:
            resolved_cache._SCHEMA_OK = "resolved_cache"


class TestHitMiss(unittest.TestCase):
    def test_miss_on_empty_cache(self):
        conn = fresh_conn()
        self.assertIsNone(resolved_cache.lookup_cache(conn, 999))

    def test_record_then_hit_watch(self):
        conn = fresh_conn()
        now = time.time()
        stored = resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        hit = resolved_cache.lookup_cache(conn, 77, want="watch", now=now + 5)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["url"], file_resolve()["url"])
        self.assertEqual(hit["kind"], "file")
        self.assertEqual(hit["category"], "A")
        self.assertEqual(hit["is_resumable"], 1)
        self.assertEqual(hit["file_size_bytes"], 2_405_181_686)
        self.assertEqual(hit["source"], "jit")
        self.assertEqual(hit["fail_count"], 0)
        self.assertGreater(hit["reverify_after"], now)
        self.assertEqual(stored["link_id"], 77)

    def test_record_without_url_is_noop(self):
        conn = fresh_conn()
        self.assertIsNone(
            resolved_cache.record_resolved_cache(conn, 5, {"success": False}))
        self.assertIsNone(resolved_cache.lookup_cache(conn, 5))

    def test_expired_row_is_a_miss_fallback(self):
        """Past reverify_after the cache must refuse, so the request path
        falls back to the live resolver — the whole expiry contract in one."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(
            conn, 88, playlist_resolve(expires_in=120.0), now=now)
        # inside the window minus margin: hit
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 88, now=now + 30))
        # beyond the measured 120s death: miss
        self.assertIsNone(resolved_cache.lookup_cache(conn, 88, now=now + 180))

    def test_upsert_replaces_url_and_resets_circuit(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        conn.execute("UPDATE resolved_cache SET fail_count = 9 WHERE link_id = 77")
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now))
        new = file_resolve(url="https://pixeldrain.com/api/file/NEWHASH")
        resolved_cache.record_resolved_cache(conn, 77, new, now=now + 1)
        hit = resolved_cache.lookup_cache(conn, 77, now=now + 1)
        self.assertIsNotNone(hit, "fresh resolve must reset the failure circuit")
        self.assertEqual(hit["url"], "https://pixeldrain.com/api/file/NEWHASH")
        self.assertEqual(hit["fail_count"], 0)


class TestKindAndCategoryFiltering(unittest.TestCase):
    def test_download_never_gets_a_playlist(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 88, playlist_resolve(), now=now)
        self.assertEqual(resolved_cache.lookup_cache(conn, 88, want="watch", now=now)["kind"],
                         "playlist")
        self.assertIsNone(resolved_cache.lookup_cache(conn, 88, want="download", now=now),
                          "a playlist is segments, not a file (stage-2 rule)")

    def test_download_gets_a_file(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, want="download",
                                                          now=now))

    def test_packer_signed_file_is_B_but_file_kind(self):
        """mxdrop/pkembed are embed packers yet sign an mp4 URL: category and
        kind must be derived independently, or this row is miscached."""
        conn = fresh_conn()
        now = time.time()
        data = playlist_resolve(url="https://mxdrop.example/v/1234.mp4?s=9&e=999",
                               mime_type="video/mp4", service="mxdrop")
        resolved_cache.record_resolved_cache(conn, 91, data, now=now)
        hit = resolved_cache.lookup_cache(conn, 91, want="download", now=now)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["category"], "B")
        self.assertEqual(hit["kind"], "file")

    def test_kind_derived_from_mime_and_extension(self):
        conn = fresh_conn()
        now = time.time()
        for url, mime, expect in (
            ("https://cdn.example/a.mp4", "video/mp4", "file"),
            ("https://cdn.example/a.m3u8", None, "playlist"),
            ("https://cdn.example/x?format=m3u8", "application/x-mpegURL", "playlist"),
            ("https://cdn.example/manifest.mpd", "application/dash+xml", "playlist"),
        ):
            with self.subTest(url=url):
                resolved_cache.record_resolved_cache(
                    conn, 1, {"url": url, "mime_type": mime}, now=now)
                hit = resolved_cache.lookup_cache(conn, 1, now=now)
                self.assertEqual(hit["kind"], expect)

    def test_category_caps_freshness_horizon(self):
        """A permanent category-A file is trusted up to 24h; a temporary or
        category-B row is capped at the 6h bridge-token heuristic — each minus
        the reverify margin. Nothing measured is never promised."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 1, file_resolve(), now=now)
        a = resolved_cache.lookup_cache(conn, 1, now=now)
        resolved_cache.record_resolved_cache(
            conn, 2, playlist_resolve(expires_in=None), now=now)  # temporary, unmeasured
        b = resolved_cache.lookup_cache(conn, 2, now=now)
        self.assertAlmostEqual(a["reverify_after"] - now,
                               resolved_cache.HEURISTIC_CAP_PERMANENT_SECONDS
                               - resolved_cache.REVERIFY_MARGIN_SECONDS, delta=2)
        self.assertAlmostEqual(b["reverify_after"] - now,
                               resolved_cache.HEURISTIC_CAP_TEMPORARY_SECONDS
                               - resolved_cache.REVERIFY_MARGIN_SECONDS, delta=2)

    def test_measured_expiry_is_margined(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(
            conn, 3, file_resolve(expires_at=now + 300), now=now)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 3, now=now + 200))
        self.assertIsNone(resolved_cache.lookup_cache(conn, 3, now=now + 280),
                          "must not serve inside the 60s death margin")


class TestServingGuards(unittest.TestCase):
    def test_failure_circuit_opens(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        conn.execute("UPDATE resolved_cache SET fail_count = ? WHERE link_id = 77",
                     (resolved_cache.MAX_FAIL_COUNT,))
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now))

    def test_ip_bound_row_not_shared_by_default(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(ip_bound=1), now=now)
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now),
                          "a token bound to another client's IP must not be replayed")
        self.assertIsNotNone(resolved_cache.lookup_cache(
            conn, 77, now=now, allow_ip_bound=True))

    def test_ip_bound_zero_and_null_are_servable(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 1, file_resolve(ip_bound=0), now=now)
        resolved_cache.record_resolved_cache(conn, 2, file_resolve(ip_bound=None), now=now)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 1, now=now))
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 2, now=now))

    def test_bad_want_falls_back_to_either(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 88, playlist_resolve(), now=now)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 88, want="banana",
                                                          now=now))


class TestConstraints(unittest.TestCase):
    def test_illegal_enum_values_rejected(self):
        conn = fresh_conn()
        now = time.time()
        base = dict(link_id=1, url="u", category="A", kind="file",
                    resolved_at=now, reverify_after=now + 60, updated=None)
        bad_rows = [
            {**base, "category": "C"},
            {**base, "kind": "page"},
            {**base, "source": "magic"},
            {**base, "ip_bound": 7},
            {**base, "is_resumable": 2},
        ]
        for row in bad_rows:
            row.pop("updated")
            cols = ", ".join(k for k in row if k != "link_id")
            with self.subTest(row=row.get("category", row.get("kind")),
                              cols=list(row)):
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        f"INSERT INTO resolved_cache ({', '.join(row)}) "
                        f"VALUES ({', '.join('?' for _ in row)})",
                        tuple(row.values()))

    def test_record_rejects_bad_source_label(self):
        conn = fresh_conn()
        with self.assertRaises(ValueError):
            resolved_cache.record_resolved_cache(conn, 1, file_resolve(), source="x")


class TestEpochHygiene(unittest.TestCase):
    def test_all_stamps_are_epoch_real(self):
        """No localized timestamp strings anywhere: the v1 staleness check's
        time.mktime() bug (5h over-age on this UTC+5 host) must not be
        inherited by the cache."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        row = conn.execute("SELECT resolved_at, reverify_after, expires_at "
                           "FROM resolved_cache WHERE link_id = 77").fetchone()
        for value in row:
            if value is None:
                continue
            self.assertIsInstance(value, float)
            self.assertGreater(value, 1_600_000_000.0)  # epoch seconds, sane


if __name__ == "__main__":
    unittest.main(verbosity=2)
