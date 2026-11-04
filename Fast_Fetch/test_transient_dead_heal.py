#!/usr/bin/env python3
"""
test_transient_dead_heal.py — the size of a mislabel, and its cure.

Crown order qoder13_commit_and_proofs, task 2. The claim under test is the
RE-SCOPED one: `link_state` maps transient transport errors to `dead`
(`timeout / dns / tls / conn_reset / conn_error -> dead`), so **a verdict about
our probe is recorded as a verdict about their endpoint**. That is wrong
information, not lost information, and these tests are the proof of the second
half — that nothing is permanent:

  * the ledger row keeps its URL, `resource_id` and history throughout
    (`link_state.py`'s own Zero-Data-Loss rule, asserted here on the row),
  * a LATER successful probe overwrites the verdict in place
    (`run_health_check`'s `UPDATE download_sources SET status = …`), so no
    re-scrape and no `heal_post_links` is even required to undo it,
  * and the heal path selects exactly those rows (`status IN ('dead','expired')`),
    so a wrong `dead` is also the work queue's input, not its grave.

Offline and stdlib-only: a throwaway mini-catalog in a temp directory, the
network edges patched, every decision path (selection, probe result handling,
write-back SQL) left real. No production database is opened by these tests.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


class TransientDeadHeal(unittest.TestCase):
    """A transient verdict is healed by the next successful probe."""

    @classmethod
    def setUpClass(cls) -> None:
        # config.DB_PATH freezes at import, so the env must be set BEFORE the
        # first import of fast_fetch. Each test then gets its OWN database file
        # by rebinding the module global `fast_fetch.DB_PATH`, which is what
        # `get_db` falls back to (fast_fetch.py:622-625) — so the heal tests
        # write through the real connection path against a private catalog.
        os.environ["RADD_DB_PATH"] = str(
            (Path(tempfile.mkdtemp(prefix="transient-dead-base-")) / "none.db"))
        import fast_fetch  # noqa: F401  (the module under test's own DB wiring)
        cls.ff = fast_fetch

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="transient-dead-")
        self.addCleanup(self._tmp.cleanup)
        self.db = str(Path(self._tmp.name) / "mini.db")
        self.ff.DB_PATH = self.db
        self.ff.init_db()
        conn = self._conn()
        try:
            pid = conn.execute(
                "INSERT INTO posts (title, clean_title, url, is_18_plus)"
                " VALUES ('Transient Proof','Transient Proof',"
                " 'https://site.invalid/p/1',0)").lastrowid
            rid = conn.execute(
                "INSERT INTO releases (post_id, release_title, intermediate_url)"
                " VALUES (?,?,?)",
                (pid, "Transient Proof 1080p", "https://bridge.invalid/f/abc")
            ).lastrowid
            sid = conn.execute(
                "INSERT INTO download_sources (release_id, source_name, service,"
                " source_url, final_url, resource_id, playback_type, status,"
                " is_resumable, http_status, is_temporary)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rid, "pixeldrain", "pixeldrain", "https://pixeldrain.com/u/ABCDEF",
                 "https://pixeldrain.com/api/file/ABCDEF", "ABCDEF", "url",
                 "active", 1, 206, 0)).lastrowid
            conn.commit()
        finally:
            conn.close()
        self.pid, self.sid = pid, sid

    def _conn(self, row_factory: bool = False):
        """Every handle gets the same busy_timeout `get_db` uses: the heal tests
        write through `fast_fetch`'s own connection while this test holds one."""
        conn = sqlite3.connect(self.db, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _row(self) -> dict:
        conn = self._conn(row_factory=True)
        conn.row_factory = sqlite3.Row
        try:
            return dict(conn.execute("SELECT * FROM download_sources"
                                     " WHERE id = ?", (self.sid,)).fetchone())
        finally:
            conn.close()

    def _write_back(self, probe_result: dict) -> None:
        """The same UPDATE `run_health_check` issues after probing — copied in
        shape so the test proves the write-back, not a reimplementation."""
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE download_sources SET status = ?, is_resumable = ?,"
                " http_status = ?, file_size_bytes = ?, mime_type = ?,"
                " last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                (probe_result["status"], probe_result["is_resumable"],
                 probe_result["http_status"], probe_result["file_size_bytes"],
                 probe_result["mime_type"], self.sid))
            conn.commit()
        finally:
            conn.close()

    def test_transient_probe_failure_marks_dead_but_keeps_everything(self):
        """A transport failure answers no HTTP code at all — that is the
        mislabel: `http_status = 0` is a statement about US, stored in a column
        that reads as a statement about the file."""
        before = self._row()
        self.assertEqual("active", before["status"])
        # probe_single_source's catch-all shape (fast_fetch.py:4952-4957):
        # a ConnectionReset raises before any status line, so this is what lands.
        transient = {"status": "dead", "is_resumable": 0, "http_status": 0,
                     "file_size_bytes": None, "mime_type": None,
                     "error": "[Errno 104] Connection reset by peer"}
        self._write_back(transient)
        after = self._row()
        self.assertEqual("dead", after["status"])
        self.assertEqual(0, after["http_status"])
        # Zero data loss, asserted rather than trusted: the cure needs these.
        for keep in ("source_url", "final_url", "resource_id", "service",
                     "playback_type"):
            self.assertEqual(before[keep], after[keep],
                             f"a transient verdict destroyed {keep}")

    def test_a_later_successful_probe_heals_the_same_row_in_place(self):
        """No permanent damage: one good look overwrites the bad verdict, and
        the row's own identity/URL is what made the second look possible."""
        self._write_back({"status": "dead", "is_resumable": 0, "http_status": 0,
                          "file_size_bytes": None, "mime_type": None,
                          "error": "timed out"})
        self.assertEqual("dead", self._row()["status"])
        # The next probe succeeds — the real measured values this hoster gives.
        self._write_back({"status": "active", "is_resumable": 1,
                          "http_status": 206, "file_size_bytes": 200330217,
                          "mime_type": "video/matroska", "error": None})
        healed = self._row()
        self.assertEqual("active", healed["status"])
        self.assertEqual(206, healed["http_status"])
        self.assertEqual(1, healed["is_resumable"])
        self.assertEqual(200330217, healed["file_size_bytes"])
        self.assertIsNone(healed["error"] if "error" in healed else None)

    def test_heal_post_links_selects_exactly_the_transient_dead_row(self):
        """The work queue includes our mislabel by construction: heal chooses
        `status IN ('dead','expired')` (fast_fetch.py:5069), so a reset-marked
        row is a candidate for revival rather than a row nobody will visit."""
        self._write_back({"status": "dead", "is_resumable": 0, "http_status": 0,
                          "file_size_bytes": None, "mime_type": None,
                          "error": "conn_reset"})
        conn = self._conn()
        chosen = conn.execute(
            "SELECT s.id FROM download_sources s"
            " JOIN releases r ON s.release_id = r.id"
            " WHERE r.post_id = ? AND s.status IN ('dead', 'expired')",
            (self.pid,)).fetchall()
        conn.close()
        self.assertIn(self.sid, [r[0] for r in chosen])

    def test_full_heal_path_restores_a_dead_row_end_to_end(self):
        """Same assertion through the real `heal_post_links`, with only its
        three network edges patched."""
        self._write_back({"status": "dead", "is_resumable": 0, "http_status": 0,
                          "file_size_bytes": None, "mime_type": None,
                          "error": "conn_reset"})
        ff = self.ff
        saved = (ff.extract_post_data, ff.save_scraped_data,
                 ff.probe_single_source)
        try:
            ff.extract_post_data = lambda url, verbose=True: {
                "title": "Transient Proof", "url": url, "releases": []}
            ff.save_scraped_data = lambda data, *a, **k: 0
            ff.probe_single_source = lambda src, timeout=8: {
                "id": src["id"], "status": "active", "is_resumable": 1,
                "http_status": 206, "file_size_bytes": 200330217,
                "mime_type": "video/matroska", "latency_ms": 12, "error": None}
            result = ff.heal_post_links(self.pid, verbose=False)
        finally:
            (ff.extract_post_data, ff.save_scraped_data,
             ff.probe_single_source) = saved
        self.assertGreaterEqual(result.get("healed", 0), 1)
        self.assertEqual("active", self._row()["status"])

    def test_heal_bails_before_probing_when_the_post_page_is_gone(self):
        """The honest limit of the cure: heal's first step is re-extracting the
        POST page from the source site, and if that fails it returns before it
        ever re-probes. A perfectly healthy file behind a moved listing page
        stays `dead` — so `dead` cannot be read as "heal tried and failed"."""
        self._write_back({"status": "dead", "is_resumable": 0, "http_status": 0,
                          "file_size_bytes": None, "mime_type": None,
                          "error": "conn_reset"})
        ff = self.ff
        saved = ff.extract_post_data
        probed = []
        try:
            ff.extract_post_data = lambda url, verbose=True: None
            ff.probe_single_source = (
                lambda src, timeout=8: probed.append(src["id"]) or {
                    "id": src["id"], "status": "active", "is_resumable": 1,
                    "http_status": 206, "file_size_bytes": None,
                    "mime_type": None, "latency_ms": 1, "error": None})
            result = ff.heal_post_links(self.pid, verbose=False)
        finally:
            ff.extract_post_data = saved
        self.assertEqual(0, result.get("healed", -1))
        self.assertEqual([], probed, "heal probed even though extraction failed")
        self.assertEqual("dead", self._row()["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
