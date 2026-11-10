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
import socket
import sqlite3
import ssl
import sys
import tempfile
import threading
import time
import unittest
import urllib.error

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


class TestColdStartRace(unittest.TestCase):
    """Crown order qoder12_night Step 0. `_ensure_schema` is a check-then-act
    on shared state: on this lane (WAL, 1 core, real thread interleavings) two
    connections can both see "no table" and both run the DDL, and the second
    can lose the existence-check/create race inside sqlite itself. The module
    must be safe by construction — IF NOT EXISTS everywhere, the specific
    concurrent-create error tolerated, every other OperationalError raised."""

    def _race_one_round(self, n_threads: int) -> list:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        barrier = threading.Barrier(n_threads)
        errors = []
        lock = threading.Lock()

        def worker(i):
            conn = sqlite3.connect(path, timeout=5.0)
            conn.execute("PRAGMA busy_timeout = 5000")
            try:
                barrier.wait()                 # every thread first-touches together
                data = file_resolve(id=900 + i,
                                    url="https://pixeldrain.com/api/file/race%d" % i)
                resolved_cache.record_resolved_cache(conn, 900 + i, data)
                conn.commit()
                self.assertIsNotNone(
                    resolved_cache.lookup_cache(conn, 900 + i))
            except Exception as exc:           # noqa: BLE001 — collected, asserted below
                with lock:
                    errors.append("%s: %s" % (type(exc).__name__, exc))
            finally:
                conn.close()

        try:
            ts = [threading.Thread(target=worker, args=(i,))
                  for i in range(n_threads)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            # the schema survived the race whole: table AND both indexes
            conn = sqlite3.connect(path, timeout=5.0)
            idx = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name LIKE 'idx_rc%'")}
            n_rows = conn.execute(
                "SELECT COUNT(*) FROM resolved_cache").fetchone()[0]
            conn.close()
            self.assertEqual(idx, {"idx_rc_reverify", "idx_rc_expiry"},
                             "a reader must never see a half-built schema")
            self.assertEqual(n_rows, n_threads)
            return errors
        finally:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(path + suffix)
                except OSError:
                    pass

    def test_simultaneous_first_touch_has_zero_errors(self):
        """8 threads, one fresh DB, barrier-released onto _ensure_schema +
        record at the same instant, 5 rounds. Zero exceptions of ANY kind and
        zero 'no such table' specifically — a traceback path here is a
        resolve thrown away on the live server's cold boot."""
        for round_no in range(5):
            errors = self._race_one_round(8)
            no_table = [e for e in errors if "no such table" in e]
            self.assertEqual(errors, [],
                             f"round {round_no}: cold-start race raised {errors}")
            self.assertEqual(no_table, [])

    def test_concurrent_creator_error_is_recognised_by_text(self):
        """The tolerance must be exactly 'already exists': a concurrent
        creator and a broken statement are not the same failure and must not
        be handled identically (order Step 0, is_temporary — no)."""
        ok = sqlite3.OperationalError("table resolved_cache already exists")
        self.assertTrue(resolved_cache._is_concurrent_create(ok))
        typo = sqlite3.OperationalError(
            "no such column: file_sze_bytes")
        self.assertFalse(resolved_cache._is_concurrent_create(typo))
        dead = sqlite3.OperationalError("no such table: resolved_cache")
        self.assertFalse(resolved_cache._is_concurrent_create(dead),
                         "the race we actually hit must not be swallowed — "
                         "it must be REPAIRED by init, not tolerated by lookup")

    def test_every_ddl_statement_is_if_not_exists(self):
        for statement in resolved_cache._DDL_STATEMENTS:
            head = statement.strip().upper()[:26]
            self.assertIn("IF NOT EXISTS", head,
                          f"DDL must be re-runnable by construction: {head}")

    def test_ddl_statement_set_is_pinned_non_empty_and_exact(self):
        """Vacuous-loop backstop (crown grant 2026-11-05): the sweep above
        ITERATES `_DDL_STATEMENTS`, so an emptied or restructured list sails
        through it green — the same blind spot as M1 and TRANSPORT_CAUSES.
        Pinned here: non-empty, exactly THREE statements (one table + the
        reverify and expiry indexes). A legitimate fourth statement is
        allowed only as a deliberate edit that moves this number too —
        silence-by-shrink is what dies."""
        stmts = list(resolved_cache._DDL_STATEMENTS)
        self.assertTrue(stmts, "_DDL_STATEMENTS must never be empty")
        self.assertEqual(len(stmts), 3,
                         "expected exactly: CREATE TABLE resolved_cache + "
                         "idx_rc_reverify + idx_rc_expiry")
        heads = [s.strip().upper() for s in stmts]
        self.assertEqual(sum(h.startswith("CREATE TABLE") for h in heads), 1)
        self.assertEqual(sum(h.startswith("CREATE INDEX") for h in heads), 2)
        joined = " ".join(heads)
        for letter in ("'FILE'", "'PLAYLIST'", "'VIEWER'"):
            self.assertIn(letter, joined.replace('"', "'"),
                          "the kind CHECK vocabulary must survive any DDL "
                          "restructure — this is what the sweep cannot see")


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
        routes — addendum defect 2's wiring, pinned as a source invariant.
        Updated for crown order qoder12_unprobed: the routes must call the
        GUARDED incrementer (which reads the envelope's unprobed signal),
        never the bare one."""
        for route in ("/api/v1/stream", "/api/v1/download"):
            with self.subTest(route=route):
                body = self._route_source(route)
                self.assertIn("resolved_cache.note_failure_from_probe(", body,
                              f"{route}: a probed-dead link must close the circuit")
                self.assertNotIn("resolved_cache.note_failure(",
                                 _strip_from_probe(body),
                                 f"{route}: bare increment without the evidence "
                                 "guard is the qoder12_unprobed defect")


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


class TestPoolHealing(unittest.TestCase):
    """Emperor order 2026-11-05 night (LANE 1, pool re-probe): the pool may
    heal a dead-token link ONLY by arriving with a genuinely fresh answer.

    The pool's per-link body (prefetch_worker.prefetch_once) is:
    resolve_live_source(id, v2=True) -> success? -> record(source="pool").
    The v2 contract refuses stale answers with `no_playable_source`, but the
    cache must not depend on the caller's honesty: a stale result must be
    unbankable HERE too, or a future caller that forgets the flag re-poisons
    the pool with a URL we believe is dead.
    """

    def test_record_refuses_a_stale_v1_fallback(self):
        """success+stale is v1's frozen-URL envelope. It is servable to a
        player (maybe) but it is NEVER bankable: caching it would promote an
        unverified URL into the pool's fresh-by-construction state."""
        conn = fresh_conn()
        now = time.time()
        stale_answer = file_resolve(cached=True, refreshed=False, stale=True)
        self.assertIsNone(
            resolved_cache.record_resolved_cache(conn, 77, stale_answer,
                                                 source="pool", now=now),
            "a stale resolve must not be banked, whatever flag the caller forgot")
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now))

    def test_pool_success_heals_a_link_the_circuit_had_retired(self):
        """The heal sequence, end to end through the module's own API:
        served -> probed dead x MAX -> refused -> pool re-probe succeeds with
        a fresh URL -> served again, marked source='pool'. This is what the
        two dead-token links need, and it must not need a hand-edited row."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        for _ in range(resolved_cache.MAX_FAIL_COUNT):
            resolved_cache.note_failure(conn, 77)
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now))
        stored = resolved_cache.record_resolved_cache(
            conn, 77, file_resolve(url="https://pixeldrain.com/api/file/NEW123"),
            source="pool", now=now + 1)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["source"], "pool")
        hit = resolved_cache.lookup_cache(conn, 77, now=now + 1)
        self.assertIsNotNone(hit, "a healed row must serve immediately")
        self.assertTrue(hit["url"].endswith("/NEW123"))

    def test_pool_healed_playlist_serves_watch_not_download(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 88, playlist_resolve(),
                                             source="pool", now=now)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 88, "watch", now=now))
        self.assertIsNone(resolved_cache.lookup_cache(conn, 88, "download", now=now),
                          "the pool cannot heal a playlist into a downloadable file")
        row = sqlite3_conn_row(conn, 88)
        self.assertEqual(row["category"], "B")
        self.assertLessEqual(row["reverify_after"] - now,
                             resolved_cache.HEURISTIC_CAP_TEMPORARY_SECONDS)

    def test_worker_bank_guard_is_v2_and_pool_marked(self):
        """Pin prefetch_worker.py (READ ONLY here — qoder13's file): it must
        resolve under the honest v2 contract and bank under source="pool"
        inside the success branch only. If either pin breaks, the pool has
        started trusting v1 envelopes."""
        import re
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "prefetch_worker.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("resolve_live_source(source_id, v2=True)", src)
        self.assertIn('source="pool"', src)
        success_at = src.index("if result.get(\"success\"):")
        bank_at = src.index("resolved_cache.record_resolved_cache(")
        self.assertGreater(bank_at, success_at,
                           "record must run inside the success branch")
        self.assertNotIn("record_resolved_cache(",
                         src[src.index("stats[\"failed\"] += 1"):],
                         "the failure branch must not bank anything")

    def test_v2_refusal_envelope_is_unbankable(self):
        """The exact shape resolve_live_source v2 returns on re-resolve
        failure (fast_fetch.py: re_resolve_failed / bridge_unresolved): no
        url at all. record returns None and the ledger of refusals stays
        empty — nothing for the circuit to even increment."""
        conn = fresh_conn()
        refusal = {"success": False, "code": "no_playable_source",
                   "reason": "re_resolve_failed", "stale": True}
        self.assertIsNone(resolved_cache.record_resolved_cache(
            conn, 1617406, refusal, source="pool"))
        self.assertIsNone(resolved_cache.lookup_cache(conn, 1617406))


def sqlite3_conn_row(conn, link_id):
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM resolved_cache WHERE link_id = ?",
                            (link_id,)).fetchone()
    finally:
        conn.row_factory = None


class TestUnprobedIsNotEvidence(unittest.TestCase):
    """Crown order qoder12_unprobed. The failure circuit may only open on
    MEASURED evidence: a probe that reached upstream and came back without
    media. When the resolver's dispatch chain matches no unpacker branch
    (1fichier, nexdrive — zero branches exist), nothing was
    contacted, nothing was measured, and incrementing `fail_count` on every
    request is fabricated evidence that circuit-breaks the row one-way: only
    a fresh resolve can re-close it, and for this class no fresh resolve is
    reachable. Both behaviours live in this one class so nobody can
    "simplify" the distinction away later. MAX_FAIL_COUNT stays 3."""

    UNSUPPORTED_ENVELOPE = {"success": False, "code": "no_playable_source",
                            "reason": "re_resolve_failed", "stale": True,
                            "unprobed": True}
    PROBED_DEAD_ENVELOPE = {"success": False, "code": "no_playable_source",
                            "reason": "re_resolve_failed", "stale": True,
                            "unprobed": False,
                            # qoder12_transport_evidence: an endpoint status we
                            # actually received — the affirmative shape every
                            # strikable answer now carries.
                            "fail_cause": 404}

    def test_unprobed_answers_leave_fail_count_unchanged(self):
        """6 simulated requests on a link WITH a cache row, each answered by
        the route's guard, must leave the row servable and the counter at 0
        — the exact scenario the order measured at viewer.py:3246."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        for _ in range(6):
            self.assertEqual(
                resolved_cache.note_failure_from_probe(conn, 77,
                                                       self.UNSUPPORTED_ENVELOPE),
                0, "an unprobed answer may not touch the circuit")
        self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"], 0)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, now=now),
                             "the row must still serve: nothing about the link "
                             "changed and nothing was measured")

    def test_v1_stale_success_envelope_is_equally_unbankable_as_evidence(self):
        """The stream route sees v1 shapes too: success+stale on an
        unsupported host is the frozen-URL answer, and its non-bank branch
        used to increment every single time. unprobed must ride in BOTH
        fallback envelopes, and the guard must read it in both."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        v1_frozen = {"success": True, "url": "https://old.example/f.m3u8",
                     "cached": True, "refreshed": False, "stale": True,
                     "unprobed": True}
        for _ in range(resolved_cache.MAX_FAIL_COUNT + 3):
            self.assertEqual(
                resolved_cache.note_failure_from_probe(conn, 77, v1_frozen), 0)
        self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"], 0)

    def test_probed_dead_answers_still_trip_the_circuit_at_three(self):
        """The other half of the distinction, kept in this module so a
        future edit cannot trade one behaviour for the other: an answer from
        a branch that DID run and failed, naming an endpoint status
        (``fail_cause`` an int), increments exactly as before and opens the
        circuit at MAX_FAIL_COUNT = 3. The circuit must never stop
        accruing — a fix that disabled it entirely is a defect, not a win
        (crown order qoder12_transport_evidence, Boundaries)."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(), now=now)
        legacy = dict(self.PROBED_DEAD_ENVELOPE)
        del legacy["unprobed"]
        del legacy["fail_cause"]
        # Direction RE-DECIDED 2026-11-05 by qoder12_transport_evidence:
        # the old rule "absent field = probed" is RETIRED. Once transport
        # causes exist an absent cause means "cannot tell which side
        # failed", and a strike accuses a third party's link — ambiguous
        # accrues nothing. Asserted here so nobody trades it back without
        # seeing exactly which invariant they flipped.
        self.assertEqual(
            resolved_cache.note_failure_from_probe(conn, 77, legacy), 0,
            "absent cause is ambiguous evidence — it may not strike")
        for _ in range(resolved_cache.MAX_FAIL_COUNT):
            self.assertEqual(
                resolved_cache.note_failure_from_probe(
                    conn, 77, self.PROBED_DEAD_ENVELOPE), 1)
        self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"],
                         resolved_cache.MAX_FAIL_COUNT)
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now),
                          "genuinely probed-dead must retire, exactly as designed")

    def test_resolver_fallthrough_marks_the_answer_unprobed_for_real(self):
        """Not my prose — the shipped boundary: a scratch DB with links
        whose services have no unpacker branch (1fichier for v2, nexdrive
        for v1; the chain cannot touch the network here), resolve v2 and
        v1 must both carry unprobed=True in the refusal envelope. Rebased
        onto main: the branch's vidbolt/cineverse fixtures are cracked
        since Session 112 (vidbolt resolves live), so they no longer serve
        as the unprobed boundary; the v1 row's bridge final_url lands in
        the bridge refusal, which carries the same signal the frozen
        answer carried before main's stale-probe gate."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        old_env = os.environ.get("RADD_DB_PATH")
        saved = {name: sys.modules.get(name)
                 for name in ("fast_fetch", "config")}
        for name in saved:
            sys.modules.pop(name, None)
        os.environ["RADD_DB_PATH"] = path
        try:
            import fast_fetch as ff
            ff.init_db()
            conn = sqlite3.connect(path)
            conn.execute("INSERT INTO posts (id, url, title, is_18_plus) "
                         "VALUES (1, 'https://qa.local/p/1', 'QA', 0)")
            conn.execute("INSERT INTO posts (id, url, title, is_18_plus) "
                         "VALUES (2, 'https://qa.local/p/2', 'QA2', 0)")
            conn.execute("INSERT INTO releases (id, post_id) VALUES (1, 1)")
            conn.execute("INSERT INTO releases (id, post_id) VALUES (2, 2)")
            # NOTE: the rows live in different posts on purpose. Same-post
            # rows are failover siblings, and resolving the first would
            # leave a fresh negative-cache record that short-circuits the
            # second with main's all_siblings_negative_cached refusal —
            # an envelope that predates the unprobed signal and does not
            # carry it. Separate posts keep each resolve on the dispatch
            # path this test pins.
            conn.execute(
                "INSERT INTO download_sources (id, release_id, service, "
                "source_url, final_url, playback_type, is_temporary, status) "
                "VALUES (42, 1, '1fichier', 'https://1fichier.com/?abc123', "
                "'https://dash-hls-bridge.johndoesjkc.workers.dev/?url=https"
                "%3A%2F%2Fsacdn.local%2Fmaster.m3u8&Policy=zz', "
                "'iframe', 1, 'expired')")
            conn.execute(
                "INSERT INTO download_sources (id, release_id, service, "
                "source_url, final_url, playback_type, is_temporary, status) "
                "VALUES (43, 2, 'nexdrive', "
                "'https://nexdrive.net/file/abc123', "
                "'https://nexdrive.net/file/abc123', "
                "'iframe', 1, 'expired')")
            conn.commit()
            conn.close()
            res2 = ff.resolve_live_source(42, v2=True)
            self.assertFalse(res2.get("success"))
            self.assertTrue(res2.get("unprobed"),
                            "no branch matched: the v2 refusal must say it "
                            "measured nothing")
            self.assertIn("fail_cause", res2,
                          "qoder12_transport_evidence: every shipped failure "
                          "envelope names HOW it failed — the circuit's "
                          "ambiguous-never-strikes rule only works because "
                          "strikable answers affirmatively carry a cause")
            self.assertEqual(res2["fail_cause"], "not_media",
                              "a chain that matched no branch reached the end "
                              "without an exception: link_state's own word "
                              "for 'answered, no media', and unprobed wins "
                              "the guard first anyway")
            res1 = ff.resolve_live_source(43, v2=False)
            self.assertTrue(res1.get("stale"),
                            "fixture: v1 refuses the bridge stale URL too")
            self.assertTrue(res1.get("unprobed"),
                            "and the refusal must carry the same signal")
            self.assertIn("fail_cause", res1,
                          "fail_cause must ride in BOTH fallback envelopes, "
                          "same law as unprobed")
        finally:
            for name, mod in saved.items():
                if mod is not None:
                    sys.modules[name] = mod
                else:
                    sys.modules.pop(name, None)
            if old_env is None:
                os.environ.pop("RADD_DB_PATH", None)
            else:
                os.environ["RADD_DB_PATH"] = old_env
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(path + suffix)
                except OSError:
                    pass

    def test_viewer_call_sites_route_through_the_evidence_guard(self):
        """Both failure paths in viewer.py must call note_failure_from_probe
        (the guarded API) and none may keep calling the bare incrementer —
        the guard lives in resolved_cache so the rule has exactly one
        definition, but the routes must actually use it."""
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "viewer.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertEqual(src.count("resolved_cache.note_failure_from_probe("), 2,
                         "stream + download failure paths, guarded")
        self.assertNotIn("resolved_cache.note_failure(", _strip_from_probe(src),
                         "no call site may increment without the evidence check")

    def test_note_failure_docstring_owns_the_evidence_rule(self):
        doc = resolved_cache.note_failure.__doc__ or ""
        self.assertIn("probed", doc.lower())
        doc2 = resolved_cache.note_failure_from_probe.__doc__ or ""
        self.assertIn("unprobed", doc2)


def _strip_from_probe(src: str) -> str:
    """Blank out the guarded calls so a leftover bare note_failure( is visible."""
    return src.replace("resolved_cache.note_failure_from_probe(", "GUARDED(")


class TestTransportIsNotEvidence(unittest.TestCase):
    """Crown order qoder12_transport_evidence. `unprobed` closed one class of
    fabricated evidence (nothing was contacted); this closes the second: a
    probe that DID dispatch and failed at the TRANSPORT layer on OUR side —
    timeout, DNS, TLS, reset, connection error. `link_state.classify` maps
    every one of those to `dead`, and before this guard the same answer
    flowed into `note_failure`, so three of our bad nights opened the
    circuit (MAX_FAIL_COUNT) and `lookup_cache` refused a link that may be
    perfectly alive — on a 1-CPU box, precisely when the machine is busiest.
    A verdict about OUR probe must never be recorded as a verdict about
    THEIR endpoint. The accrual side is asserted with equal force: endpoint-
    answered dead (an HTTP status int, or the endpoint word `not_media`)
    still strikes and still retires the row at three. If transport causes
    stopped being strikable WITHOUT that holding, the circuit would be
    disabled, not fixed."""

    BASE = {"success": False, "code": "no_playable_source",
            "reason": "re_resolve_failed", "stale": True, "unprobed": False}

    def _envelope(self, cause):
        env = dict(self.BASE)
        env["fail_cause"] = cause
        return env

    def _banked_conn(self):
        conn = fresh_conn()
        resolved_cache.record_resolved_cache(conn, 77, file_resolve(),
                                             now=time.time())
        return conn

    NAMED_TRANSPORT_CAUSES = ("timeout", "dns", "tls", "conn_reset",
                              "conn_error")

    def test_each_named_transport_cause_by_literal_is_refused(self):
        """Literal-cause duplicate of the per-vocabulary loop below, because
        a loop over `TRANSPORT_CAUSES` is vacuously green when that set is
        emptied (crown-found mutation blind spot, 2026-11-05). These five
        words are hardcoded HERE, so an emptied production vocabulary has
        nowhere to hide: the refusal must survive a set that shrank."""
        for cause in self.NAMED_TRANSPORT_CAUSES:
            with self.subTest(cause=cause):
                conn = self._banked_conn()
                self.assertEqual(
                    resolved_cache.note_failure_from_probe(
                        conn, 77, self._envelope(cause)), 0,
                    f"our own {cause} may not strike a third party's link")
                self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"], 0)

    def test_transport_cause_set_is_closed_against_the_named_literals(self):
        """Non-empty AND exactly these words: a later lane cannot silently
        drop one (that re-opens the circuit on a transport failure) nor add
        one (that could mute a genuine endpoint verdict). Membership changes
        here must be a deliberate, argued edit to BOTH this literal and
        fast_fetch._transport_cause_of's mapping."""
        self.assertEqual(
            set(resolved_cache.TRANSPORT_CAUSES),
            set(self.NAMED_TRANSPORT_CAUSES),
            "TRANSPORT_CAUSES must contain exactly "
            f"{sorted(self.NAMED_TRANSPORT_CAUSES)}")

    def test_transport_cause_never_touches_fail_count(self):
        for cause in sorted(resolved_cache.TRANSPORT_CAUSES):
            with self.subTest(cause=cause):
                conn = self._banked_conn()
                for _ in range(resolved_cache.MAX_FAIL_COUNT + 2):
                    self.assertEqual(
                        resolved_cache.note_failure_from_probe(
                            conn, 77, self._envelope(cause)), 0,
                        f"our own {cause} may not strike a third party's link")
                self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"], 0)

    def test_three_transport_failures_do_not_refuse_the_row(self):
        """The order's named scenario, end to end: three transport failures
        (timeout, dns, tls) and `lookup_cache` must STILL hand out the row —
        the exact mirror of the endpoint-dead test below."""
        conn = self._banked_conn()
        now = time.time()
        for cause in ("timeout", "dns", "tls"):
            resolved_cache.note_failure_from_probe(conn, 77,
                                                   self._envelope(cause))
        self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"], 0)
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, now=now),
                             "our bad night must not close the shop on a link "
                             "that was never measured dead")

    def test_endpoint_status_int_still_trips_at_three(self):
        """Boundary of the order, non-negotiable: a genuinely dead endpoint
        (we received the status) accrues MAX_FAIL_COUNT endpoint-answered
        verdicts and `lookup_cache` refuses it, exactly as before this fix."""
        conn = self._banked_conn()
        now = time.time()
        for _ in range(resolved_cache.MAX_FAIL_COUNT):
            self.assertEqual(
                resolved_cache.note_failure_from_probe(
                    conn, 77, self._envelope(404)), 1)
        self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"],
                         resolved_cache.MAX_FAIL_COUNT)
        self.assertIsNone(resolved_cache.lookup_cache(conn, 77, now=now),
                          "endpoint-answered dead must still retire")

    def test_not_media_still_strikes(self):
        """An endpoint that ANSWERED and simply did not hand us media is
        evidence about them — link_state's own word, and the resolver's
        affirmative default when its chain ran to the end without raising."""
        conn = self._banked_conn()
        self.assertEqual(
            resolved_cache.note_failure_from_probe(
                conn, 77, self._envelope("not_media")), 1)

    def test_absent_cause_is_ambiguous_and_never_strikes(self):
        """The written re-decision (crown item 3): the retired direction was
        "absent field = probed". Absent now means we cannot tell which side
        failed, and a strike accuses a third party's link — so it accrues
        nothing. Pinning the refusal AND the docstring that owns it."""
        conn = self._banked_conn()
        now = time.time()
        for _ in range(resolved_cache.MAX_FAIL_COUNT + 2):
            self.assertEqual(
                resolved_cache.note_failure_from_probe(conn, 77,
                                                       dict(self.BASE)), 0,
                "absent fail_cause is ambiguous evidence")
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 77, now=now),
                             "ambiguous answers must not retire a servable row")
        doc = resolved_cache.note_failure_from_probe.__doc__ or ""
        self.assertIn("RETIRED", doc,
                      "the direction change must stay written where a reader "
                      "of the guard will meet it")

    def test_unprobed_refusal_survives_the_new_field(self):
        """unprobed and a transport cause can ride the same envelope; the
        older refusal is checked first and still returns 0."""
        env = dict(self.BASE)
        env["unprobed"] = True
        env["fail_cause"] = "timeout"
        conn = self._banked_conn()
        self.assertEqual(
            resolved_cache.note_failure_from_probe(conn, 77, env), 0)
        self.assertEqual(sqlite3_conn_row(conn, 77)["fail_count"], 0)

    def test_transport_vocabulary_is_link_states_own_words(self):
        """No new taxonomy (crown item 1): every refused cause must be a word
        `link_state` already uses AND already maps to `dead` — which is
        exactly why these answers used to strike. If link_state ever grows a
        transport word this guard misses, the subset pin does not catch it;
        the direction of that drift (an endpoint word mis-refused) is caught
        by the accrual tests above instead."""
        import link_state
        for word in sorted(resolved_cache.TRANSPORT_CAUSES):
            with self.subTest(word=word):
                self.assertIn(word, link_state._ERROR_CODES,
                              "resolved_cache must not invent a vocabulary")
                self.assertEqual(
                    link_state.classify({"ok": False, "error": word}),
                    link_state.STATUS_DEAD,
                    "the word must be one whose dead verdict used to flow "
                    "into the circuit unchecked")


class TestTransportCauseNaming(unittest.TestCase):
    """The naming half of qoder12_transport_evidence lives in the resolver:
    `_transport_cause_of` must answer in link_state's words, so the cache
    surface and the ledger surface cannot disagree about a failure. Pure
    function, no sockets, no DB."""

    @classmethod
    def setUpClass(cls):
        cls._saved = sys.modules.get("fast_fetch")
        os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")
        import fast_fetch as ff
        cls.ff = ff

    def _maps(self, exc, expected):
        self.assertEqual(self.ff._transport_cause_of(exc), expected,
                         f"{exc!r} must map to {expected!r}")

    def test_direct_exception_classes(self):
        self._maps(TimeoutError("slow"), "timeout")
        self._maps(ConnectionResetError(104, "reset by peer"), "conn_reset")
        self._maps(BrokenPipeError(32, "pipe"), "conn_reset")
        self._maps(ssl.SSLError("handshake failure"), "tls")

    def test_urlerror_wrapped_reasons(self):
        self._maps(urllib.error.URLError(TimeoutError()), "timeout")
        self._maps(urllib.error.URLError(ssl.SSLError("x")), "tls")
        self._maps(urllib.error.URLError(ConnectionResetError(104, "r")),
                   "conn_reset")
        self._maps(urllib.error.URLError(
            socket.gaierror(-2, "Name or service not known")), "dns")
        self._maps(urllib.error.URLError(OSError(111, "Connection refused")),
                   "conn_error")
        self._maps(urllib.error.URLError("some unknown failure"), "conn_error")

    def test_bare_gaierror_and_errno_oserrors(self):
        self._maps(socket.gaierror(-3, "Temporary failure"), "dns")
        self._maps(OSError(111, "refused"), "conn_error")

    def test_unmappable_exception_is_ambiguous_not_a_invented_cause(self):
        """None is the honest answer for "this maps to no link_state word" —
        and the circuit treats ambiguous as non-evidence. A made-up cause
        string here would be the new taxonomy the order forbade."""
        self.assertEqual(self.ff._transport_cause_of(ValueError("nope")),
                         None)

    def test_shipped_refusal_envelope_names_its_cause(self):
        """fast_fetch must set fail_cause in BOTH fallback envelopes at the
        point of failure, not have viewer.py guess later (no new control
        flow: one field, two carriers)."""
        import inspect
        src = inspect.getsource(self.ff.resolve_live_source)
        self.assertGreaterEqual(src.count('"fail_cause": probe_fail_cause'), 2,
                                "v2 refusal and v1 stale envelopes both carry "
                                "the named cause")
        self.assertIn('probe_fail_cause = int(exc.code)', src,
                      "an HTTPError answered — the status must be named as an "
                      "int, strikable evidence about the endpoint")


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


class TestViewerKindGate(unittest.TestCase):
    """Task #24 (crown order 2026-11-05): mega crypto-share URLs (the `#`
    fragment IS the AES key) and Google Drive ``/view`` HTML pages banked as
    kind='file' Category A — and ``/api/v1/download``
    gates on exactly ``kind='file'``, so a viewer page could answer the
    single-file download route. Three laws, each with its own test:

      (a) an HTML viewer-shaped URL is NOT kind='file';
      (b) a `#` fragment is never banked and never handed out in a play_url;
      (c) ``lookup_cache(want="download")`` refuses viewer-shaped rows —
          INCLUDING rows banked as 'file' before this fix — while real direct
          files still pass.

    Acceptance is doubled by qoder14's expectedFailure gate in
    test_host_classifier.py::test_kind_gate_expectations; when these go green
    that one XPASSes and the marker comes off there.
    """

    VIEWER = "https://drive.google.com/file/d/1abc/view"
    MEGA = "https://mega.nz/file/AbCd#AESkeymaterial"
    REAL = "https://pixeldrain.com/api/file/s2yMcLkb"

    def _row(self, conn, link_id):
        return conn.execute(
            "SELECT kind, url FROM resolved_cache WHERE link_id = ?",
            (link_id,)).fetchone()

    def test_law_a_viewer_page_is_not_banked_as_file(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 1, {"url": self.VIEWER,
                                                      "service": "google_cdn"},
                                             now=now)
        self.assertNotEqual(self._row(conn, 1)[0], "file",
                            "an HTML viewer page is not a single-file "
                            "download candidate")

    def test_law_a_declared_file_kind_cannot_outvote_viewer_shape(self):
        """Labels lie (the module's own founding rule): a resolver envelope
        that CLAIMS kind='file' for a /view URL gets overruled by the shape."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(
            conn, 2, {"url": self.VIEWER, "kind": "file"}, now=now)
        self.assertNotEqual(self._row(conn, 2)[0], "file")

    def test_law_a_mega_packer_url_is_not_a_file(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 3,
                                            {"url": self.MEGA, "service": "mega"},
                                            now=now)
        self.assertNotEqual(self._row(conn, 3)[0], "file",
                            "mega shares are client-side-encrypted pages; no "
                            "naive byte GET exists on the host at all")

    def test_law_b_mega_key_fragment_is_never_banked(self):
        conn = fresh_conn()
        now = time.time()
        summary = resolved_cache.record_resolved_cache(
            conn, 4, {"url": self.MEGA, "service": "mega"}, now=now)
        stored = self._row(conn, 4)[1]
        self.assertNotIn("#", stored,
                         "the fragment (mega's AES key) must not sit in a "
                         "banked row that other code paths read as a play_url")
        self.assertNotIn("#", summary["url"])
        self.assertEqual(stored, "https://mega.nz/file/AbCd")

    def test_law_b_media_fragment_on_a_real_file_is_stripped_but_stays_file(self):
        """#t=10,60 is a client-side seek hint, never sent to the server: the
        stripped URL IS the replayable byte GET, so kind stays 'file' and the
        fragment is still not banked."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(
            conn, 5, {"url": "https://cdn.example/a.mp4#t=10,60",
                      "mime_type": "video/mp4"}, now=now)
        kind, stored = self._row(conn, 5)
        self.assertEqual(kind, "file")
        self.assertEqual(stored, "https://cdn.example/a.mp4")

    def test_law_b_lookup_never_hands_a_fragment_to_a_play_url(self):
        """Legacy rows — banked BEFORE the strip — must not leak the fragment
        through watch either: the read path strips defensively."""
        conn = fresh_conn()
        now = time.time()
        conn.execute(
            "INSERT INTO resolved_cache (link_id, url, category, kind, "
            "resolved_at, reverify_after, source, fail_count) "
            "VALUES (99, ?, 'A', 'file', ?, ?, 'jit', 0)",
            (self.MEGA, now, now + 3600))
        hit = resolved_cache.lookup_cache(conn, 99, want="watch", now=now)
        self.assertIsNotNone(hit)
        self.assertNotIn("#", hit["url"],
                         "a fragment-bearing banked URL must reach the wire "
                         "fragment-free even for rows this fix predates")

    def test_law_c_download_route_refuses_viewer_rows_banked_before_the_fix(self):
        """The legacy-row blast radius: rows ALREADY stored kind='file' for viewer
        shapes. The stored kind cannot be trusted for old rows, so the
        download gate re-checks the URL shape at read time."""
        conn = fresh_conn()
        now = time.time()
        for link_id, url in ((101, self.VIEWER), (102, self.MEGA)):
            conn.execute(
                "INSERT INTO resolved_cache (link_id, url, category, kind, "
                "resolved_at, reverify_after, source, fail_count) "
                "VALUES (?, ?, 'A', 'file', ?, ?, 'jit', 0)",
                (link_id, url, now, now + 3600))
        self.assertIsNone(
            resolved_cache.lookup_cache(conn, 101, want="download", now=now),
            "/api/v1/download's own gate: a viewer-shaped row must not answer "
            "the download route, however it was banked")
        self.assertIsNone(
            resolved_cache.lookup_cache(conn, 102, want="download", now=now))

    def test_law_c_real_direct_files_still_pass_download(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(
            conn, 110, {"url": self.REAL, "mime_type": "video/mp4",
                        "service": "pixeldrain"}, now=now)
        hit = resolved_cache.lookup_cache(conn, 110, want="download", now=now)
        self.assertIsNotNone(hit, "the fix must not fence real byte GETs out "
                             "of /api/v1/download")
        self.assertEqual(hit["kind"], "file")
        self.assertEqual(hit["url"], self.REAL)

    def test_law_c_mxdrop_packer_signed_mp4_still_passes(self):
        """The measured counterweight: mxdrop is an embed packer but signs a
        real mp4 URL — viewer-shaped means HTML/fragment surfaces, NOT every
        non-direct host (category already caps that at B)."""
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(
            conn, 111, playlist_resolve(url="https://mxdrop.example/v/1234.mp4?s=9&e=999",
                                       mime_type="video/mp4", service="mxdrop"),
            now=now)
        hit = resolved_cache.lookup_cache(conn, 111, want="download", now=now)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["kind"], "file")

    def test_html_path_is_viewer_shaped(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(
            conn, 120, {"url": "https://packer.example/watch.html?id=5",
                        "mime_type": "text/html"}, now=now)
        self.assertNotEqual(self._row(conn, 120)[0], "file",
                            "an .html path is a page, not a byte GET")

    def test_viewer_is_in_the_closed_kind_vocabulary(self):
        """The CHECK constraint must know the new letter, or every viewer
        banking is an IntegrityError on the request path."""
        ddl = " ".join(resolved_cache._DDL_STATEMENTS)
        self.assertIn("'viewer'", ddl.replace('"', "'"),
                      "kind CHECK widened to file|playlist|viewer")

    def test_viewer_rows_never_answer_download_even_freshly_banked(self):
        conn = fresh_conn()
        now = time.time()
        resolved_cache.record_resolved_cache(conn, 130,
                                            {"url": self.VIEWER,
                                             "service": "google_cdn"}, now=now)
        self.assertIsNone(
            resolved_cache.lookup_cache(conn, 130, want="download", now=now))

    def test_law_d_watch_refuses_viewer_rows(self):
        """§6 fix 1: the kind gate is not download-only. A row banked as
        kind='viewer' — an HTML page / Drive /view / mega share — must not
        answer the watch route either, or the player gets a 302 to a page.
        Real file and playlist rows still pass watch."""
        conn = fresh_conn()
        now = time.time()
        for link_id, url in ((131, self.VIEWER), (132, self.MEGA)):
            conn.execute(
                "INSERT INTO resolved_cache (link_id, url, category, kind, "
                "resolved_at, reverify_after, source, fail_count) "
                "VALUES (?, ?, 'A', 'viewer', ?, ?, 'jit', 0)",
                (link_id, url, now, now + 3600))
        self.assertIsNone(
            resolved_cache.lookup_cache(conn, 131, want="watch", now=now),
            "a viewer-kind row must not answer the stream route, however "
            "it was banked")
        self.assertIsNone(
            resolved_cache.lookup_cache(conn, 132, want="watch", now=now))
        # The "either" fallback shares the watch rule, never the hole.
        self.assertIsNone(
            resolved_cache.lookup_cache(conn, 131, want="either", now=now))
        # Real media still passes watch: a file and a playlist.
        resolved_cache.record_resolved_cache(
            conn, 133, {"url": self.REAL, "mime_type": "video/mp4",
                        "service": "pixeldrain"}, now=now)
        hit = resolved_cache.lookup_cache(conn, 133, want="watch", now=now)
        self.assertIsNotNone(hit, "the fix must not fence real files out "
                             "of watch")
        self.assertEqual(hit["kind"], "file")
        resolved_cache.record_resolved_cache(
            conn, 134, playlist_resolve(), now=now)
        hit = resolved_cache.lookup_cache(conn, 134, want="watch", now=now)
        self.assertIsNotNone(hit, "playlists are watch media too")
        self.assertEqual(hit["kind"], "playlist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
