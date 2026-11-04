#!/usr/bin/env python3
"""PROBE_COVERAGE.md §6, made executable.

The production catalog reports ``active_sources = 4,006,773``. Measured evidence for
that liveness: ``last_checked_at`` on 71 rows, a real ``http_status`` on 10, and
``status='active'`` backed by either on **10**. The gap is not a rounding artifact —
``download_sources.status`` is declared ``TEXT DEFAULT 'active'``, so a row becomes
"active" by nobody writing anything.

These tests run against a synthetic scratch database (one per test, in a temp dir) and
NEVER open the production catalog. They assert the behaviour of the read-only query this
lane ships, and they pin where ``link_state`` — trunk's honest classifier — still
disagrees with it, so that wiring ``stats_payload()`` into ``/api/v1/stats`` cannot pass
silently while still reporting a label as a measurement.

Stdlib only. No network. No production path is read: ``link_state`` deliberately never
imports ``config``, and nothing here does either.

    python3 -S Fast_Fetch/test_probe_coverage.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import link_state  # noqa: E402  (stdlib-only by design; safe to import offline)


#: Verbatim from production `sqlite_master` (merged_catalog_20261025.db), so the
#: `status TEXT DEFAULT 'active'` mechanism under test is the real one and not a
#: paraphrase of it. The FK target is absent on purpose: SQLite does not resolve
#: `REFERENCES` until `PRAGMA foreign_keys=ON`, which this test never turns on.
DDL = """
CREATE TABLE download_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    source_name TEXT,
    service TEXT,
    resource_id TEXT,
    source_url TEXT,
    final_url TEXT,
    playback_type TEXT DEFAULT 'url',
    is_temporary INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    is_resumable INTEGER DEFAULT 0,
    http_status INTEGER DEFAULT NULL,
    file_size_bytes INTEGER DEFAULT NULL,
    mime_type TEXT DEFAULT NULL,
    last_checked_at TIMESTAMP DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expires_at REAL DEFAULT NULL,
    ttl_source TEXT DEFAULT NULL,
    FOREIGN KEY (release_id) REFERENCES releases(id) ON DELETE CASCADE
)
"""

#: The evidence predicate from PROBE_COVERAGE.md §6. `http_status = 0` is NOT evidence:
#: 0 is what our own probe records when the connection failed, i.e. a verdict about us.
#:
#: The whole expression is wrapped in ONE outer pair of parentheses, and that is load-
#: bearing: `A OR B` unparenthesised inside `status = 'active' AND NOT <pred>` parses as
# `status AND ((NOT A) OR B)`, which double-counts every probed row. The conservation
#: test below is what catches it.
EVIDENCE = ("((d.last_checked_at IS NOT NULL AND d.last_checked_at <> '')"
            " OR (d.http_status IS NOT NULL AND d.http_status <> 0))")

#: The query this lane delivers to the emitter. Not shipped as a code change — this
#: string and the one in the doc are the same text on purpose.
COVERAGE_SQL = f"""
SELECT
    COUNT(*)                                                             AS sources,
    SUM(CASE WHEN {EVIDENCE} THEN 1 ELSE 0 END)                          AS checked_sources,
    SUM(CASE WHEN {EVIDENCE} THEN 0 ELSE 1 END)                          AS unchecked_sources,
    SUM(CASE WHEN d.status = 'active' AND  {EVIDENCE}     THEN 1 ELSE 0 END)
                                                                         AS checked_active_sources,
    SUM(CASE WHEN d.status = 'active' AND NOT {EVIDENCE} THEN 1 ELSE 0 END)
                                                                         AS unchecked_active_sources,
    ROUND(100.0 * SUM(CASE WHEN {EVIDENCE} THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 4)                                AS verification_coverage
  FROM download_sources d
"""


class ProbeCoverageBase(unittest.TestCase):
    """One isolated catalog per test — the discipline that fixed the 93 s lock storm in
    `test_transient_dead_heal.py`: never share a WAL database between tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="probe-coverage-")
        self.addCleanup(self._tmp.cleanup)
        self.db = str(Path(self._tmp.name) / "mini.db")
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(DDL)
        self.addCleanup(self.conn.close)

    # ---- builders -------------------------------------------------------------

    def insert(self, **cols):
        """Insert one source row. Columns left out take their PRODUCTION DEFAULT,
        which is exactly how 4,006,763 rows became 'active'."""
        cols.setdefault("release_id", 1)
        cols.setdefault("service", "unknown-service")
        names = ", ".join(cols)
        marks = ", ".join("?" * len(cols))
        cur = self.conn.execute(
            f"INSERT INTO download_sources ({names}) VALUES ({marks})",
            tuple(cols.values()))
        self.conn.commit()
        return cur.lastrowid

    def default_active(self, service="filepress"):
        """The production majority: `status` never written, no evidence columns."""
        return self.insert(service=service, source_url=f"https://{service}/x")

    def probed_active(self, service="bcdnxw.hakunaymatata.com", code=206):
        return self.insert(service=service, http_status=code, is_resumable=1 if code == 206 else 0,
                           last_checked_at="2026-11-04 18:09:33")

    def label_only(self, status, service="bridge"):
        """A non-default `status` written by an importer with NO probe evidence — the
        shape of production's 23 `dead` + 17,132 `js_required` + 9,314 `unknown` + 2
        `blocked` rows."""
        return self.insert(status=status, service=service)

    def coverage(self):
        return self.conn.execute(COVERAGE_SQL).fetchone()

    # ---- the assertions are grouped by the claim they defend ------------------


class TestDefaultIsNotAVerdict(ProbeCoverageBase):

    def test_an_unwritten_status_reads_as_active_and_must_count_as_unchecked(self):
        """The whole finding, in one assertion pair. `status` was never supplied; the
        column DEFAULT hands us 'active'; the ledger therefore claims a working link."""
        self.default_active()
        raw = self.conn.execute("SELECT status, http_status, last_checked_at"
                                " FROM download_sources").fetchone()
        self.assertEqual("active", raw["status"],
                         "the fixture must reproduce production's mechanism: the DEFAULT")
        self.assertIsNone(raw["http_status"])
        self.assertIsNone(raw["last_checked_at"])

        row = self.coverage()
        self.assertEqual(0, row["checked_active_sources"],
                         "an active row nobody knocked on cannot be evidence-backed")
        self.assertEqual(1, row["unchecked_active_sources"])

    def test_checked_plus_unchecked_equals_the_published_active_count(self):
        """Conservation. The honest split must not lose or double-count a row, or the
        emitter's denominator stops matching its own numerator."""
        for _ in range(3):
            self.default_active()
        for _ in range(2):
            self.probed_active()
        self.label_only("dead")
        row = self.coverage()
        published = self.conn.execute(
            "SELECT COUNT(*) FROM download_sources d WHERE d.status = 'active'").fetchone()[0]
        self.assertEqual(published, 5, "status='active' as the emitter counts it today")
        self.assertEqual(published, row["checked_active_sources"] + row["unchecked_active_sources"],
                         "the split must sum back to what `active_sources` reports today")
        self.assertEqual(2, row["checked_active_sources"])
        self.assertEqual(3, row["unchecked_active_sources"])

    def test_coverage_is_a_real_fraction_and_not_a_construction(self):
        """3 unchecked + 2 checked => 40.00%, and an empty catalog => 0.0, never 100%.
        A `COUNT(*) WHERE status='active'` emitter cannot express the empty case honestly
        because it has no denominator to divide by."""
        for _ in range(3):
            self.default_active()
        for _ in range(2):
            self.probed_active()
        self.assertAlmostEqual(40.0, self.coverage()["verification_coverage"], places=4)

        self.conn.execute("DELETE FROM download_sources")
        row = self.coverage()
        self.assertIsNone(row["verification_coverage"],
                          "NULL from NULLIF(COUNT(*),0) — a divide-by-zero must not print 0% "
                          "as if it were a measurement")
        self.assertEqual(0, row["sources"])


class TestEvidenceIsDefinedByWritingNotByLabeling(ProbeCoverageBase):

    def test_http_status_zero_is_our_failure_and_not_their_answer(self):
        """`run_health_check` writes `http_status = 0` on a transport error. Reading 0
        as evidence would record a verdict about OUR probe as a verdict about THEIR link."""
        self.insert(service="pixeldrain", http_status=0, is_resumable=0,
                    last_checked_at="2026-11-04 17:35:40")
        row = self.coverage()
        self.assertEqual(1, row["checked_active_sources"],
                         "a timestamp IS evidence that somebody knocked")

        only_zero = self.insert(service="megaup", http_status=0)
        row = self.coverage()
        self.assertEqual(1, row["unchecked_sources"])
        bare = self.conn.execute("SELECT status FROM download_sources WHERE id = ?",
                                 (only_zero,)).fetchone()
        self.assertEqual("active", bare["status"],
                         "http_status=0 alone still reads 'active' to a status-only emitter")

    def test_a_timestamp_alone_is_a_knock_even_with_no_code(self):
        """All 61 of production's timestamped non-active rows have `http_status IS NULL`:
        the probe ran and the connection died. That is a checked row with a bad answer,
        not an unchecked row."""
        self.insert(service="bcdnxw.hakunaymatata.com", http_status=None,
                    last_checked_at="2026-11-02 01:34:43")
        row = self.coverage()
        self.assertEqual(1, row["checked_sources"])
        self.assertEqual(0, row["unchecked_sources"])

    def test_an_empty_string_timestamp_is_not_a_knock(self):
        """`last_checked_at = ''` is a write that carries no information. Deliberate
        divergence from `link_state`, which tests `IS NULL` only — pinned here so the
        reconciliation is a decision and not an accident. (Whether production holds ''
        rows is NOT MEASURED; see PROBE_COVERAGE.md §11.)"""
        self.insert(service="gofile", last_checked_at="")
        row = self.coverage()
        self.assertEqual(0, row["checked_sources"])
        self.assertEqual(1, row["unchecked_sources"])

    def test_a_resumability_claim_without_a_probe_is_not_evidence(self):
        """Production: 2 of 4,073,865 rows claim `is_resumable = 1`. A flag set at
        scrape time is a prediction about Range support, not an observed 206."""
        self.insert(service="hubcloud", is_resumable=1, http_status=None,
                    last_checked_at=None)
        row = self.coverage()
        self.assertEqual(0, row["checked_sources"])
        self.assertEqual(1, row["unchecked_active_sources"])


class TestLinkStateAgreement(ProbeCoverageBase):
    """`link_state` already re-labels an evidence-free 'active' row as 'unverified',
    which is the right idea and 90% of the fix. These pin where it agrees, and the one
    place it does not."""

    def test_the_shipped_query_and_the_classifier_agree_on_verified_liveness(self):
        for _ in range(4):
            self.default_active()
        for _ in range(2):
            self.probed_active()
        summary = link_state.status_summary(self.conn)
        row = self.coverage()
        self.assertEqual(row["checked_active_sources"], summary["by_status"].get("active", 0),
                         "link_state's 'active' bucket is evidence-backed; it must equal the "
                         "shipped query's checked_active_sources or the two emitters disagree")
        self.assertEqual(row["sources"], summary["total"])

    def test_stats_payload_refuses_to_report_an_unprobed_catalog_as_active(self):
        """The number the order asked for: `active_sources` = evidence-backed liveness.
        On an all-default catalog — which is what production IS — this reports 0."""
        for _ in range(5):
            self.default_active()
        payload = link_state.stats_payload(self.conn)
        self.assertEqual(0, payload["active_sources"],
                         "5 rows labelled 'active' by DEFAULT, 0 of them probed")
        self.assertEqual(5, payload["unverified_sources"])
        self.assertEqual(0, payload["checked_sources"])
        self.assertEqual(0.0, payload["verification_coverage"])
        self.assertEqual(5, payload["sources"])

    def test_verdict_labels_without_evidence_are_still_counted_as_checked(self):
        """THE 374x TRAP. `status_summary` decides `checked` by *state*, and its SQL
        passes any non-'active' status straight through — so importer-written labels
        (`dead` with no timestamp, `js_required`, `unknown`, `blocked`) count as knocks.
        Production: 26,542 label-counted vs 71 evidenced = 374x.

        This test asserts the CURRENT behaviour on purpose. If `link_state` is fixed to
        require evidence for every state, this fails, and the fix is real — update
        PROBE_COVERAGE.md §5 in the same commit, do not delete this test.
        """
        self.label_only("dead")          # production's 23-row shape
        self.label_only("js_required")   # production's 17,132-row shape
        summary = link_state.status_summary(self.conn)
        self.assertEqual(0, self.coverage()["checked_sources"],
                         "neither row has ever been knocked on")
        self.assertEqual(2, summary["checked"],
                         "link_state counts a label as a check — measured, not assumed")
        self.assertGreater(summary["coverage"], 0.0,
                           "and so its coverage is non-zero on a ledger with zero evidence")
        self.assertNotEqual(summary["checked"], self.coverage()["checked_sources"])

    def test_a_null_status_is_unverified_in_both_places(self):
        self.insert(status=None, service="dl")
        summary = link_state.status_summary(self.conn)
        row = self.coverage()
        self.assertEqual(1, summary["by_status"].get(link_state.STATUS_UNVERIFIED, 0))
        self.assertEqual(0, summary["checked"])
        self.assertEqual(1, row["unchecked_sources"])


class TestReadOnlySafety(ProbeCoverageBase):
    """The emitter must not be able to write through the coverage query, and the
    measurement must be reproducible by the next lane with one flag."""

    def test_query_only_blocks_every_write_but_still_answers(self):
        self.default_active()
        ro = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        ro.row_factory = sqlite3.Row
        ro.execute("PRAGMA query_only=ON")
        try:
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("UPDATE download_sources SET status = 'dead' WHERE id = 1")
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("CREATE INDEX attempt ON download_sources(last_checked_at)")
            row = ro.execute(COVERAGE_SQL).fetchone()
            self.assertEqual(1, row["unchecked_active_sources"],
                             "the honest read still works under the guard")
        finally:
            ro.close()

    def test_the_measurement_never_depends_on_an_index_that_does_not_exist(self):
        """PROBE_COVERAGE.md §7: no index covers the evidence columns, so the plan must
        stay a plain `SCAN` — which is *sequential* and is why one full pass cost 75.5 s
        while `GROUP BY service` over the same columns fetches 4.07M rows at random."""
        plan = [r[3] for r in self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT d.last_checked_at, d.http_status, d.status"
            " FROM download_sources d")]
        # The alias is what SQLite names the scan target, so match `SCAN d`, not `SCAN
        # download_sources` — asserted loosely enough to still fail if an index appears.
        self.assertTrue(any(p.startswith("SCAN d") and "USING INDEX" not in p for p in plan),
                        f"expected a plain sequential scan, got {plan}")
        self.assertFalse(any("TEMP B-TREE" in p for p in plan),
                         "the shipped aggregate groups in one pass; a spill to disk on a "
                         "95%-full host is a write this lane must not cause")


if __name__ == "__main__":
    unittest.main(verbosity=2)
