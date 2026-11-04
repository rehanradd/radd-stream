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


class TestAddendumDefects(unittest.TestCase):
    """The two defects from /tmp/crown_orders/qoder12_addendum.md, each
    reproduced experimentally by the Crown Prince before being ordered here.

    1. ``executescript`` issues an implicit COMMIT before running — on the
       shared-connection contract ("record does not commit; the caller's
       transaction owns it") that was a one-shot-per-restart landmine: the
       first lookup of a cold process committed whatever the caller had
       pending, so a later rollback kept a write it believed discarded.
    2. ``fail_count`` had a reader (the guard) and a resetter (the upsert)
       but NO incrementer anywhere — a circuit that can never open is dead
       code wearing a safety promise.
    """

    def test_ensure_schema_does_not_commit_caller_transaction(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE scratch(x INTEGER)")
        conn.execute("INSERT INTO scratch VALUES (1)")   # opens an implicit txn
        self.assertTrue(conn.in_transaction,
                        "fixture: caller must hold a pending transaction")
        # cold path: no resolved_cache table yet, so the probe fails and the
        # DDL runs INSIDE the caller's transaction
        self.assertIsNone(resolved_cache.lookup_cache(conn, 1))
        self.assertTrue(conn.in_transaction,
                        "schema init must run inside the caller's transaction, "
                        "never commit it (executescript would have)")
        conn.rollback()
        left = conn.execute("SELECT COUNT(*) FROM scratch").fetchone()[0]
        self.assertEqual(left, 0,
                         "the caller's rolled-back write must have actually died")

    def test_init_resolved_cache_keeps_transaction_open(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE scratch(x INTEGER)")
        conn.execute("INSERT INTO scratch VALUES (1)")
        resolved_cache.init_resolved_cache(conn)
        self.assertTrue(conn.in_transaction)
        conn.commit()

    def test_note_failure_opens_the_circuit_end_to_end(self):
        """record fresh -> served; note_failure MAX times (each one a
        measured probe-failure, exactly like the routes' failure path calls
        it) -> refused. No hand-edited SQL: the circuit is now reachable
        through the module's own API alone."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, now=now))
        for i in range(resolved_cache.MAX_FAIL_COUNT):
            self.assertEqual(resolved_cache.note_failure(conn, 77), 1,
                             f"note_failure {i + 1} must touch the cached row")
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now),
                          "after MAX_FAIL_COUNT probed-dead failures the row "
                          "must be retired, not re-served and re-probed forever")

    def test_note_failure_below_threshold_still_serves(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        for _ in range(resolved_cache.MAX_FAIL_COUNT - 1):
            resolved_cache.note_failure(conn, 77)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, now=now))

    def test_note_failure_on_uncached_link_is_harmless(self):
        conn = fresh_conn()
        self.assertEqual(resolved_cache.note_failure(conn, 424242), 0)

    def test_fresh_resolve_closes_the_circuit_again(self):
        """A newly verified URL must clear the failures of the URL it
        replaces — already the upsert contract, now proven via note_failure
        instead of a hand-set column."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        for _ in range(resolved_cache.MAX_FAIL_COUNT):
            resolved_cache.note_failure(conn, 77)
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now))
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now + 1)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, now=now + 1))

    def test_record_on_a_virgin_database_creates_the_schema(self):
        """The WAL stress (12 threads, cold file, writes before any read)
        reproduced this: lookup_cache and note_failure probed-and-created,
        but record_resolved_cache assumed the table existed, so the first
        writer of a fresh database died with 'no such table: resolved_cache'
        and the resolve it had just paid for was thrown away."""
        conn = sqlite3.connect(":memory:")          # virgin: no schema yet
        now = time.time()
        row = resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        self.assertIsNotNone(row)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, now=now))
        conn.rollback()
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now),
                          "record still must not commit — the caller's "
                          "transaction owns the write")


class TestViewerRouteContract(unittest.TestCase):
    """These tests pin the SECURITY ORDERING of the two HTTP routes that read
    the cache. The invariants are properties of viewer.py's request path:

      * ``redact.link_is_adult`` must run BEFORE any ``lookup_cache`` call —
        a hidden title must stay hidden from the cache exactly as it is from
        the resolver, so a cached row can never answer for an adult link;
      * the cache path is public-port-only (guarded by ``not full``) — the
        operator port must keep seeing live resolver diagnostics;
      * the download route asks for ``want="download"`` and re-checks
        ``kind == "file"`` — a playlist row, however fresh, must never be
        served as a single-file download; it falls through to the resolver;
      * every cache call sits inside a ``try`` — a cache fault can only make
        an answer slower, never different.

    They read the source because instantiating the HTTP handler offline would
    mock more machinery than the assertion is worth; if anyone reorders the
    handler, these go red before a reviewer has to find it by eye.
    """

    VIEWER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "viewer.py")

    @classmethod
    def _route_source(cls, route: str) -> str:
        with open(cls.VIEWER_PATH, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index(f'path == "{route}"')
        end = src.index('\n        elif path ==', start)
        return src[start:end]

    @classmethod
    def _lookup_at(cls, body: str) -> int:
        # the call site, not the prose that mentions it in a comment
        return body.index("resolved_cache.lookup_cache(")

    def test_adult_gate_precedes_cache_lookup(self):
        for route in ("/api/v1/stream", "/api/v1/download"):
            with self.subTest(route=route):
                body = self._route_source(route)
                self.assertLess(body.index("link_is_adult"),
                                self._lookup_at(body),
                                f"{route}: the cache must never be consulted "
                                f"before the adult gate has refused a hidden link")

    def test_cache_lookup_is_public_port_only(self):
        for route in ("/api/v1/stream", "/api/v1/download"):
            with self.subTest(route=route):
                body = self._route_source(route)
                self.assertLess(body.index("if not full:"),
                                self._lookup_at(body),
                                f"{route}: the operator port must bypass the cache")

    def test_download_route_refuses_playlist_rows(self):
        body = self._route_source("/api/v1/download")
        self.assertIn('want="download"', body,
                      "the download route must ask the cache with the stage-2 contract")
        self.assertIn('hit.get("kind") == "file"', body,
                      "a cached playlist must fall through to the live resolver, "
                      "never be served as a single-file download")

    def test_cache_faults_are_wrapped(self):
        for route in ("/api/v1/stream", "/api/v1/download"):
            with self.subTest(route=route):
                body = self._route_source(route)
                self.assertIn("except Exception", body,
                              f"{route}: cache errors must degrade to the old path")

    def test_routes_incremente_the_circuit_on_measured_death(self):
        """The circuit's incrementer must sit where a probe FOUND the URL
        dead (resolver answered without a playable/stale URL) on both public
        routes — addendum defect 2's wiring, pinned as a source invariant."""
        for route in ("/api/v1/stream", "/api/v1/download"):
            with self.subTest(route=route):
                body = self._route_source(route)
                self.assertIn("resolved_cache.note_failure(", body,
                              f"{route}: a probed-dead link must close the circuit")


class TestCrownPrinceCategoryHardening(unittest.TestCase):
    """HIGH-fix (/tmp/crown_orders/qoder12.md): fast_fetch.unwrap_hubcloud
    FAILS OPEN — it hands back the raw HTML landing page with
    service="hubcloud", is_temporary=0. The old marker list minted that a
    category-A permanent file with 24h of trust, and the cache then 302'd
    every player at a bridge for a day. Category A now requires BOTH a
    trusted direct-file service label AND a direct-file URL host, with
    host_classifier.is_direct_file as the single authority."""

    PERMANENT = resolved_cache.HEURISTIC_CAP_PERMANENT_SECONDS
    TEMPORARY = resolved_cache.HEURISTIC_CAP_TEMPORARY_SECONDS

    def _recorded(self, conn, link_id, data, now):
        resolved_cache.record_resolved_cache(conn, link_id, data, now=now)
        return conn.execute(
            "SELECT category, reverify_after - resolved_at FROM resolved_cache "
            "WHERE link_id = ?", (link_id,)).fetchone()

    def test_order_measured_cases_all_denied_a(self):
        """The four lines the Crown Prince measured against the old module."""
        cases = [
            ({"service": "hubcloud"}, "https://hubcloud.foo/dr/xyz"),
            ({}, "https://hubcloud.foo/d/abc"),
            ({}, "https://hubcloud.io/file/1"),
            ({}, "https://drive.google.com/file/d/x/view"),
        ]
        for data, url in cases:
            with self.subTest(service=data.get("service"), url=url):
                self.assertEqual(resolved_cache._derive_category(data, url), "B")

    def test_hubcloud_landing_never_gets_24h_horizon(self):
        conn = fresh_conn()
        now = time.time()
        for path in ("/dr/xyz", "/drive/ABC123", "/d/abc"):
            row = self._recorded(
                conn, 1, {"url": f"https://hubcloud.foo{path}",
                          "service": "hubcloud", "is_temporary": False,
                          "mime_type": "text/html"}, now)
            with self.subTest(path=path):
                self.assertEqual(row[0], "B")
                self.assertLess(row[1], self.TEMPORARY + 1,
                                "a bridge-shaped URL must cap at the 6h "
                                "temporary horizon, never 24h")

    def test_failed_unwrap_stored_with_temporary_cap(self):
        """The exact fail-open answer unwrap_hubcloud returns for a non-gpdl
        URL: the landing page itself, service stamped hubcloud, not marked
        temporary. Stored is fine — but only ever trusted for 6h, not a day."""
        conn = fresh_conn()
        now = time.time()
        row = self._recorded(conn, 42, {
            "url": "https://hubcloud.bar/drive/HB789", "service": "hubcloud",
            "is_temporary": False, "mime_type": "video/mp4",  # even a lying mime
        }, now)
        self.assertEqual(row[0], "B")
        self.assertAlmostEqual(row[1], self.TEMPORARY - resolved_cache.REVERIFY_MARGIN_SECONDS,
                               delta=2)
        self.assertLess(row[1], self.PERMANENT / 2)

    def test_service_label_alone_is_not_sufficient(self):
        conn = fresh_conn()
        now = time.time()
        # trusted direct-file label on an unrecognised host
        row = self._recorded(conn, 1, {"url": "https://weird.example/v.mp4",
                                       "service": "pixeldrain"}, now)
        self.assertEqual(row[0], "B")
        # trusted host with no service marker at all
        row = self._recorded(conn, 2, {"url": "https://pixeldrain.com/api/file/x"}, now)
        self.assertEqual(row[0], "B")

    def test_genuine_direct_files_keep_24h_trust(self):
        conn = fresh_conn()
        now = time.time()
        for link_id, url, service in (
            (1, "https://pixeldrain.com/api/file/s2yMcLkb", "pixeldrain"),
            (2, "https://bucket.r2.dev/movie.mp4", "fsl_r2"),
            (3, "https://video.x.googleusercontent.com/videoplay?id=1", "google_cdn"),
            (4, "https://dl.fastdl.beer/file/abc.mp4", "fastdl"),
        ):
            row = self._recorded(conn, link_id, {"url": url, "service": service,
                                                 "mime_type": "video/mp4"}, now)
            with self.subTest(url=url):
                self.assertEqual(row[0], "A")
                self.assertAlmostEqual(row[1],
                                       self.PERMANENT - resolved_cache.REVERIFY_MARGIN_SECONDS,
                                       delta=2)

    def test_host_classifier_is_the_single_authority(self):
        """No duplicated host table survives in resolved_cache: the module
        must not carry _CATEGORY_A_SERVICES or substring marker lists."""
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "resolved_cache.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("_CATEGORY_A_SERVICES", src)
        self.assertNotIn('a_markers', src)
        self.assertIn("host_classifier.is_direct_file", src)


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
