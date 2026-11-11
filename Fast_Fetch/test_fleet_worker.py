#!/usr/bin/env python3
"""Tests for fleet_worker.py (gap A20)."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fleet_worker as fw


def make_catalog_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE admin_fleet_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "crawler_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, "
        "started_at INTEGER NOT NULL, finished_at INTEGER, pid INTEGER, "
        "exit_code INTEGER, detail TEXT NOT NULL DEFAULT '')")
    conn.commit()
    conn.close()


def make_panel_db(path: Path, rows) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE fleet_crawlers (site_key TEXT PRIMARY KEY, "
        "status TEXT NOT NULL DEFAULT 'idle', last_sync_at INTEGER, "
        "progress INTEGER NOT NULL DEFAULT 0, failure_reason TEXT, "
        "created_at INTEGER, updated_at INTEGER)")
    conn.executemany(
        "INSERT INTO fleet_crawlers (site_key, last_sync_at) VALUES (?,?)", rows)
    conn.commit()
    conn.close()


class FleetCommandTests(unittest.TestCase):
    BASE = "/opt/radd-stream/Fast_Fetch"

    def test_importer_sites_take_sync_limit_for_both_modes(self):
        for site in ("castle", "dramadog", "megacartoons"):
            for mode in ("sync", "crawl"):
                with self.subTest(site=site, mode=mode):
                    self.assertEqual(
                        fw.fleet_command(site, mode, 10, base_dir=self.BASE),
                        ["python3", "%s/importers/import_%s.py" % (self.BASE, site),
                         "sync", "--limit", "10"])

    def test_engine_sync_sites(self):
        self.assertEqual(
            fw.fleet_command("rogmovies", "sync", 100, base_dir=self.BASE),
            ["python3", "%s/fast_fetch.py" % self.BASE, "sync", "--site", "rogmovies"])
        self.assertEqual(
            fw.fleet_command("vegamovies", "sync", 100, base_dir=self.BASE),
            ["python3", "%s/fast_fetch.py" % self.BASE, "sync", "--site", "vegamovies"])

    def test_script_sync_sites_use_their_flag(self):
        self.assertEqual(
            fw.fleet_command("9xmovies", "sync", 100, base_dir=self.BASE),
            ["python3", "%s/import_9xmovies.py" % self.BASE, "--sync-api"])
        self.assertEqual(
            fw.fleet_command("hdtvb", "sync", 100, base_dir=self.BASE),
            ["python3", "%s/import_hdtvb.py" % self.BASE, "--sync-sitemap"])

    def test_crawl_mode(self):
        self.assertEqual(
            fw.fleet_command("multimovies", "crawl", 25, base_dir=self.BASE),
            ["python3", "%s/import_multimovies.py" % self.BASE, "--limit-roots", "25"])
        self.assertEqual(
            fw.fleet_command("9xmovies", "crawl", 25, base_dir=self.BASE),
            ["python3", "%s/import_9xmovies.py" % self.BASE, "--limit", "25"])

    def test_unknown_site_is_refused(self):
        with self.assertRaises(ValueError):
            fw.fleet_command("notasite", "sync", 10, base_dir=self.BASE)

    def test_unrunnable_panel_sites_are_refused(self):
        # harpalgeo, movienestbd, moviesdrive, xprimehub have no validated
        # command in the main repo; the worker must not invent one.
        for site in ("harpalgeo", "movienestbd", "moviesdrive", "xprimehub"):
            with self.subTest(site=site):
                with self.assertRaises(ValueError):
                    fw.fleet_command(site, "sync", 10, base_dir=self.BASE)

    def test_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            fw.fleet_command("rogmovies", "bogus", 10, base_dir=self.BASE)

    def test_runnable_set_is_21_sites(self):
        self.assertEqual(len(fw.RUNNABLE_SITES), 21)
        self.assertEqual(len(fw.FLEET_SITES), 18)
        self.assertEqual(len(fw.IMPORTER_SITES), 3)


class PickStalestTests(unittest.TestCase):
    def test_never_synced_first_then_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel_db = Path(tmp) / "admin_v2.db"
            make_panel_db(panel_db, [
                ("vegamovies", 1700000000),
                ("rogmovies", None),
                ("ssrmovies", 1600000000),
                ("harpalgeo", None),  # unrunnable: must be skipped
            ])
            conn = sqlite3.connect(str(panel_db))
            try:
                self.assertEqual(fw.pick_stalest(conn), "rogmovies")
            finally:
                conn.close()

    def test_oldest_synced_when_none_are_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel_db = Path(tmp) / "admin_v2.db"
            make_panel_db(panel_db, [
                ("vegamovies", 1700000000),
                ("ssrmovies", 1600000000),
            ])
            conn = sqlite3.connect(str(panel_db))
            try:
                self.assertEqual(fw.pick_stalest(conn), "ssrmovies")
            finally:
                conn.close()

    def test_none_when_only_unrunnable_sites_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel_db = Path(tmp) / "admin_v2.db"
            make_panel_db(panel_db, [("harpalgeo", None), ("xprimehub", None)])
            conn = sqlite3.connect(str(panel_db))
            try:
                self.assertIsNone(fw.pick_stalest(conn))
            finally:
                conn.close()


class RunOneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog_db = Path(self.tmp.name) / "catalog.db"
        self.panel_db = Path(self.tmp.name) / "admin_v2.db"
        self.log_dir = Path(self.tmp.name) / "logs"
        make_catalog_db(self.catalog_db)
        make_panel_db(self.panel_db, [("dramadog", None), ("rogmovies", None)])

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_runner(self, exit_code):
        calls = []

        def runner(command, log_path):
            calls.append((command, log_path))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("fake crawler output\n")
            return exit_code

        runner.calls = calls
        return runner

    def test_success_marks_synced_and_audits_done(self):
        runner = self._fake_runner(0)
        result = fw.run_one("dramadog", "sync", 10, catalog_db=self.catalog_db,
                            panel_db=self.panel_db, base_dir="/opt/radd-stream/Fast_Fetch",
                            log_dir=self.log_dir, load_ceiling=9999,
                            max_wait_seconds=1, runner=runner)
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["audit_id"], 1)
        # The command is the importer command.
        self.assertEqual(runner.calls[0][0][-3:], ["sync", "--limit", "10"])
        conn = sqlite3.connect(str(self.catalog_db))
        try:
            row = conn.execute(
                "SELECT crawler_id, status, exit_code FROM admin_fleet_audit WHERE id=1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("dramadog", "done", 0))
        conn = sqlite3.connect(str(self.panel_db))
        try:
            row = conn.execute(
                "SELECT status, last_sync_at, failure_reason FROM fleet_crawlers "
                "WHERE site_key='dramadog'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "idle")
        self.assertIsNotNone(row[1])
        self.assertIsNone(row[2])

    def test_failure_audits_failed_and_records_reason(self):
        runner = self._fake_runner(3)
        result = fw.run_one("dramadog", "sync", 10, catalog_db=self.catalog_db,
                            panel_db=self.panel_db, base_dir="/opt/radd-stream/Fast_Fetch",
                            log_dir=self.log_dir, load_ceiling=9999,
                            max_wait_seconds=1, runner=runner)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 3)
        conn = sqlite3.connect(str(self.catalog_db))
        try:
            row = conn.execute(
                "SELECT status, exit_code FROM admin_fleet_audit WHERE id=1").fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("failed", 3))
        conn = sqlite3.connect(str(self.panel_db))
        try:
            row = conn.execute(
                "SELECT status, last_sync_at, failure_reason FROM fleet_crawlers "
                "WHERE site_key='dramadog'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "idle")
        self.assertIsNone(row[1])  # not synced
        self.assertIn("exit 3", row[2])

    def test_dry_run_writes_nothing_and_spawns_nothing(self):
        runner = self._fake_runner(0)
        result = fw.run_one("dramadog", "sync", 10, catalog_db=self.catalog_db,
                            panel_db=self.panel_db, base_dir="/opt/radd-stream/Fast_Fetch",
                            log_dir=self.log_dir, load_ceiling=9999,
                            max_wait_seconds=1, dry_run=True, runner=runner)
        self.assertTrue(result["dry_run"])
        self.assertEqual(runner.calls, [])
        conn = sqlite3.connect(str(self.catalog_db))
        try:
            count = conn.execute("SELECT COUNT(*) FROM admin_fleet_audit").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_load_gate_yields_when_the_box_is_busy(self):
        runner = self._fake_runner(0)
        result = fw.run_one("dramadog", "sync", 10, catalog_db=self.catalog_db,
                            panel_db=self.panel_db, base_dir="/opt/radd-stream/Fast_Fetch",
                            log_dir=self.log_dir, load_ceiling=0.0,
                            max_wait_seconds=0, runner=runner)
        self.assertEqual(result["status"], "yielded")
        self.assertEqual(runner.calls, [])

    def test_wait_for_quiet_machine_returns_true_when_quiet(self):
        self.assertTrue(fw.wait_for_quiet_machine(9999, max_wait_seconds=1))


if __name__ == "__main__":
    unittest.main()
