#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for `Fast_Fetch/prefetch_worker.py` and its run mode (gap A7).

The worker keeps the top-200 Tier-1 links warm in `resolved_cache`, but the
code alone never ran: its load ceiling parked it permanently while the box
idled at load 6-8. Gap A7 wires the run mode — a systemd timer + oneshot
service with a tuned ceiling (4.0) and a bounded wait (300s) — and these
tests pin that mode:

* a sweep warms the cache (a `source='pool'` row is banked, then served, and
  a second sweep skips the warm row without re-resolving);
* the load gate waits, proceeds when quiet, and yields the sweep after the
  max wait instead of hanging;
* a failed resolve banks nothing, and the in-process backoff holds;
* flagged posts — and public posts sharing a flagged work's canonical_key —
  are never selected, so the worker never resolves an adult link;
* the shipped systemd units describe the run mode (timer cadence, service
  command, deprioritisation, DB path);
* the CLI `--dry-run` plans a real sweep against a scratch DB without
  touching the network or banking a row.

No network, no production DB: every test runs against an in-memory SQLite
fixture (or a scratch temp file for the CLI test) with a stubbed resolver.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fast_fetch  # noqa: E402
import prefetch_worker  # noqa: E402
import resolved_cache  # noqa: E402


#: The only tables the worker's queries touch, with the columns `tiers`
#: reads when it ranks a release's links.
_SCHEMA = """
CREATE TABLE posts (
    id INTEGER PRIMARY KEY, clean_title TEXT, title TEXT,
    is_18_plus INTEGER, canonical_key TEXT);
CREATE TABLE releases (
    id INTEGER PRIMARY KEY, post_id INTEGER, quality TEXT, codec TEXT,
    size TEXT, size_bytes INTEGER, resolution TEXT, quality_label TEXT,
    languages TEXT);
CREATE TABLE download_sources (
    id INTEGER PRIMARY KEY, release_id INTEGER, kind TEXT, status TEXT,
    source_url TEXT, final_url TEXT, service TEXT, source_name TEXT,
    http_status INTEGER, is_resumable INTEGER, rank_score INTEGER,
    file_size_bytes INTEGER, mime_type TEXT, playable INTEGER,
    streamable INTEGER, speed_mbps REAL, latency_ms INTEGER,
    last_checked_at TEXT);
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    resolved_cache.init_resolved_cache(conn)
    return conn


def _add_public_post(conn, post_id=1, release_id=10, source_id=100):
    """One public work with a single playable direct link."""
    conn.execute(
        "INSERT INTO posts VALUES (?, ?, ?, 0, ?)",
        (post_id, "Test Film One", "Test Film One", "test-film-one"))
    conn.execute(
        "INSERT INTO releases VALUES (?, ?, '1080p', NULL, NULL, NULL, NULL, NULL, NULL)",
        (release_id, post_id))
    conn.execute(
        """INSERT INTO download_sources
           (id, release_id, kind, status, source_url, service, source_name,
            http_status, is_resumable, file_size_bytes, mime_type)
           VALUES (?, ?, 'direct', 'active',
                   'https://pixeldrain.com/api/file/TEST100',
                   'pixeldrain', 'Pixeldrain', 200, 1, 2000000000, 'video/mp4')""",
        (source_id, release_id))
    conn.commit()


def _add_flagged_post(conn, post_id=2, release_id=20, source_id=200,
                      canonical_key="flagged-film"):
    conn.execute(
        "INSERT INTO posts VALUES (?, ?, ?, 1, ?)",
        (post_id, "Flagged Film", "Flagged Film", canonical_key))
    conn.execute(
        "INSERT INTO releases VALUES (?, ?, '1080p', NULL, NULL, NULL, NULL, NULL, NULL)",
        (release_id, post_id))
    conn.execute(
        """INSERT INTO download_sources
           (id, release_id, kind, status, source_url, service, source_name,
            http_status, is_resumable, file_size_bytes, mime_type)
           VALUES (?, ?, 'direct', 'active',
                   'https://pixeldrain.com/api/file/TEST200',
                   'pixeldrain', 'Pixeldrain', 200, 1, 2000000000, 'video/mp4')""",
        (source_id, release_id))
    conn.commit()


def _add_twin_post(conn, post_id=3, release_id=30, source_id=300,
                   canonical_key="flagged-film"):
    """A public post sharing a flagged work's canonical_key: also excluded."""
    conn.execute(
        "INSERT INTO posts VALUES (?, ?, ?, 0, ?)",
        (post_id, "Flagged Film", "Flagged Film", canonical_key))
    conn.execute(
        "INSERT INTO releases VALUES (?, ?, '1080p', NULL, NULL, NULL, NULL, NULL, NULL)",
        (release_id, post_id))
    conn.execute(
        """INSERT INTO download_sources
           (id, release_id, kind, status, source_url, service, source_name,
            http_status, is_resumable, file_size_bytes, mime_type)
           VALUES (?, ?, 'direct', 'active',
                   'https://pixeldrain.com/api/file/TEST300',
                   'pixeldrain', 'Pixeldrain', 200, 1, 2000000000, 'video/mp4')""",
        (source_id, release_id))
    conn.commit()


@contextmanager
def _yield_conn(conn):
    yield conn


def _fake_resolve_factory(calls):
    """A resolver that always succeeds with a direct file, recording calls."""
    def _resolve(source_id, v2=True):
        calls.append((source_id, v2))
        return {"success": True, "id": source_id,
                "url": "https://pixeldrain.com/api/file/TEST100",
                "service": "pixeldrain", "is_temporary": False,
                "is_resumable": True, "mime_type": "video/mp4",
                "file_size_bytes": 2_000_000_000}
    return _resolve


class TestSweepWarmsCache(unittest.TestCase):
    def _run(self, conn, calls, **over):
        kwargs = dict(limit=1, min_fresh=3600.0, load_ceiling=4.0,
                      fail_backoff=900.0, dry_run=False, verbose=False,
                      max_wait_seconds=300.0, _failure_backoff={})
        kwargs.update(over)
        with mock.patch.object(fast_fetch, "get_db",
                               side_effect=lambda: _yield_conn(conn)), \
             mock.patch.object(fast_fetch, "resolve_live_source",
                               side_effect=_fake_resolve_factory(calls)), \
             mock.patch.object(prefetch_worker, "current_load",
                               return_value=0.1):
            return prefetch_worker.prefetch_once(**kwargs)

    def test_sweep_warms_then_skips_warm_rows(self):
        """The proof gap A7 needs: a sweep banks a pool row, a second sweep
        serves it and does not re-resolve."""
        conn = _make_conn()
        _add_public_post(conn)
        calls: list = []
        stats = self._run(conn, calls)
        self.assertEqual(stats["posts"], 1)
        self.assertEqual(stats["tier1"], 1)
        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(calls, [(100, True)],
                         "the worker must resolve under the honest v2 contract")
        row = conn.execute(
            "SELECT link_id, url, source FROM resolved_cache WHERE link_id = 100"
        ).fetchone()
        self.assertIsNotNone(row, "the sweep must bank a cache row")
        self.assertEqual(row["source"], "pool")
        self.assertTrue(row["url"].endswith("/TEST100"))
        self.assertIsNotNone(resolved_cache.lookup_cache(conn, 100),
                             "a banked row must serve immediately")
        stats2 = self._run(conn, calls)
        self.assertEqual(stats2["warm"], 1, "the second sweep must skip the warm row")
        self.assertEqual(stats2["resolved"], 0)
        self.assertEqual(len(calls), 1, "a warm row must not be re-resolved")

    def test_failed_resolve_banks_nothing_and_backs_off(self):
        """A v2 refusal is not cacheable, and the in-process backoff holds
        the link for the rest of the sweep cycle."""
        conn = _make_conn()
        _add_public_post(conn)
        calls: list = []
        backoff: dict[int, float] = {}
        with mock.patch.object(fast_fetch, "get_db",
                               side_effect=lambda: _yield_conn(conn)), \
             mock.patch.object(fast_fetch, "resolve_live_source",
                               side_effect=lambda sid, v2=True: (
                                   calls.append((sid, v2)),
                                   {"success": False, "code": "no_playable_source",
                                    "reason": "re_resolve_failed"})[1]), \
             mock.patch.object(prefetch_worker, "current_load",
                               return_value=0.1):
            stats = prefetch_worker.prefetch_once(
                limit=1, min_fresh=3600.0, load_ceiling=4.0, fail_backoff=900.0,
                dry_run=False, verbose=False, max_wait_seconds=300.0,
                _failure_backoff=backoff)
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(stats["resolved"], 1)
            n = conn.execute(
                "SELECT COUNT(*) FROM resolved_cache").fetchone()[0]
            self.assertEqual(n, 0, "a failed resolve must bank nothing")
            stats2 = prefetch_worker.prefetch_once(
                limit=1, min_fresh=3600.0, load_ceiling=4.0, fail_backoff=900.0,
                dry_run=False, verbose=False, max_wait_seconds=300.0,
                _failure_backoff=backoff)
            self.assertEqual(stats2["resolved"], 0,
                             "the backoff must hold the failed link")
            self.assertEqual(len(calls), 1)

    def test_post_with_no_playable_link_is_skipped(self):
        conn = _make_conn()
        conn.execute("INSERT INTO posts VALUES (4, 'No Links', 'No Links', 0, 'no-links')")
        conn.commit()
        calls: list = []
        stats = self._run(conn, calls)
        self.assertEqual(stats["posts"], 1)
        self.assertEqual(stats["skipped_no_link"], 1)
        self.assertEqual(calls, [])


class TestAdultExclusion(unittest.TestCase):
    def test_flagged_and_twin_posts_are_never_selected(self):
        """Adult law, at the query: a flagged post is out, and so is every
        public post sharing its canonical_key — the worker never even
        resolves a link for a flagged work, let alone caches one."""
        conn = _make_conn()
        _add_flagged_post(conn)
        _add_twin_post(conn)
        self.assertEqual(prefetch_worker.select_priority_posts(conn, 10), [])
        calls: list = []
        with mock.patch.object(fast_fetch, "get_db",
                               side_effect=lambda: _yield_conn(conn)), \
             mock.patch.object(fast_fetch, "resolve_live_source",
                               side_effect=_fake_resolve_factory(calls)), \
             mock.patch.object(prefetch_worker, "current_load",
                               return_value=0.1):
            stats = prefetch_worker.prefetch_once(
                limit=10, min_fresh=3600.0, load_ceiling=4.0, fail_backoff=900.0,
                dry_run=False, verbose=False, max_wait_seconds=300.0,
                _failure_backoff={})
        self.assertEqual(stats["posts"], 0)
        self.assertEqual(calls, [], "no adult link may ever be resolved")


class TestLoadGate(unittest.TestCase):
    def test_wait_proceeds_when_quiet(self):
        with mock.patch.object(prefetch_worker, "current_load", return_value=0.1):
            self.assertEqual(
                prefetch_worker.wait_for_quiet_machine(4.0), (False, False, False))

    def test_wait_blocks_then_proceeds(self):
        # current_load is read twice per gated round (the loop condition and
        # the log line), so the stub returns high once, then quiet forever.
        state = {"first": True}

        def _load():
            if state["first"]:
                state["first"] = False
                return 9.0
            return 0.1

        with mock.patch.object(prefetch_worker, "current_load",
                               side_effect=_load), \
             mock.patch.object(prefetch_worker, "LOAD_POLL_SECONDS", 0.01):
            self.assertEqual(
                prefetch_worker.wait_for_quiet_machine(4.0), (True, False, False))

    def test_wait_yields_after_max_wait(self):
        """A busy box must not hang a timer-driven sweep: after the max wait
        the gate reports timed_out and the caller yields."""
        with mock.patch.object(prefetch_worker, "current_load", return_value=9.0), \
             mock.patch.object(prefetch_worker, "LOAD_POLL_SECONDS", 0.01):
            blocked, stopping, timed_out = prefetch_worker.wait_for_quiet_machine(
                4.0, max_wait_seconds=0.05)
        self.assertTrue(blocked)
        self.assertFalse(stopping)
        self.assertTrue(timed_out)

    def test_sweep_yields_on_busy_box(self):
        """The sweep-level consequence: gated=1, nothing resolved, nothing
        banked, and the next timer firing retries."""
        conn = _make_conn()
        _add_public_post(conn)
        calls: list = []
        with mock.patch.object(fast_fetch, "get_db",
                               side_effect=lambda: _yield_conn(conn)), \
             mock.patch.object(fast_fetch, "resolve_live_source",
                               side_effect=_fake_resolve_factory(calls)), \
             mock.patch.object(prefetch_worker, "current_load",
                               return_value=9.0), \
             mock.patch.object(prefetch_worker, "LOAD_POLL_SECONDS", 0.01):
            stats = prefetch_worker.prefetch_once(
                limit=1, min_fresh=3600.0, load_ceiling=4.0, fail_backoff=900.0,
                dry_run=False, verbose=False, max_wait_seconds=0.05,
                _failure_backoff={})
        self.assertEqual(stats["gated"], 1)
        self.assertEqual(stats["resolved"], 0)
        self.assertEqual(calls, [])
        n = conn.execute("SELECT COUNT(*) FROM resolved_cache").fetchone()[0]
        self.assertEqual(n, 0)


class TestRunModeUnits(unittest.TestCase):
    """The shipped systemd units must describe the decided run mode."""

    def _read(self, name):
        path = Path(__file__).resolve().parent / name
        self.assertTrue(path.is_file(), f"{name} must ship beside the worker")
        return path.read_text(encoding="utf-8")

    def test_defaults_match_the_run_mode(self):
        self.assertEqual(prefetch_worker.LOAD_CEILING, 4.0,
                         "the ceiling default must be the tuned value, not the "
                         "2.0 that parked the worker permanently")
        self.assertEqual(prefetch_worker.MAX_WAIT_SECONDS, 300.0)

    def test_service_unit(self):
        src = self._read("radd-prefetch.service")
        self.assertIn("Type=oneshot", src)
        self.assertIn("WorkingDirectory=/opt/radd-stream", src)
        self.assertIn("User=ubuntu", src)
        self.assertIn(
            "RADD_DB_PATH=/home/ubuntu/radd-stream-data/merged_catalog_20261025.db", src)
        self.assertIn("prefetch_worker.py --once --limit 200 --load-ceiling 4.0", src)
        self.assertIn("--max-wait-seconds 300", src)
        self.assertIn("Nice=19", src, "background work must not steal the API's CPU")
        self.assertIn("IOSchedulingClass=idle", src)
        self.assertIn("TimeoutStartSec=7200", src,
                      "a full cold sweep may run over an hour")

    def test_timer_unit(self):
        src = self._read("radd-prefetch.timer")
        self.assertIn("OnCalendar=*-*-* 00,06,12,18:30:00", src,
                      "every 6h: the shortest cache horizon")
        self.assertIn("Persistent=true", src)
        self.assertIn("RandomizedDelaySec=600", src)
        self.assertIn("WantedBy=timers.target", src)
        self.assertNotIn("03:40", src, "must not collide with the catalog backup")
        for hour in ("02", "08", "14", "20"):
            self.assertNotIn(f"{hour}:00", src,
                             "must not collide with the autocrawl slots")


class TestCliDryRun(unittest.TestCase):
    def test_dry_run_plans_without_banking_or_network(self):
        """The real CLI path, end to end on a scratch DB: --dry-run prints
        the plan, exits 0, and leaves resolved_cache empty."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "scratch.db"
            conn = sqlite3.connect(db)
            conn.executescript(_SCHEMA)
            conn.commit()
            _add_public_post(conn)
            conn.close()
            script = Path(__file__).resolve().parent / "prefetch_worker.py"
            proc = subprocess.run(
                [sys.executable, "-S", str(script), "--once", "--dry-run",
                 "--db", str(db)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("would resolve source #100", proc.stdout)
            conn = sqlite3.connect(db)
            n = conn.execute("SELECT COUNT(*) FROM resolved_cache").fetchone()[0]
            conn.close()
            self.assertEqual(n, 0, "a dry run must bank nothing")


if __name__ == "__main__":
    unittest.main()
