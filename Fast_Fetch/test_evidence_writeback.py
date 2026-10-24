#!/usr/bin/env python3
"""Real scenario tests for the measured-evidence write-back (API_V2.md §6.2, G-7).

`catalog_v2.project()` derives a link's state from what the ledger *claims*;
`catalog_v2.apply_evidence()` overwrites it with what a probe *measured*. These
tests drive the same path production does — ledger rows written by
`fast_fetch.save_scraped_data`, projected with `catalog_v2.project`, then folded
with `apply_evidence` — and assert on the columns the v2 API reads. Nothing is
mocked, and nothing reaches the network: `apply_evidence` never opens a socket.
"""

from __future__ import annotations

import sqlite3
import unittest

import catalog_v2
import link_health
from test_catalog_v2 import ProjectionTestCase, _row


def probe(url, *, ok=True, status=200, protocol="progressive", content_type="video/mp4",
          size=5_000_000, latency=120, speed=8.5, ranges=True, cors=False,
          error="", at=1_700_000_000.0, final=""):
    """One ProbeResult exactly as `link_health.probe` would return it."""
    return link_health.ProbeResult(
        url=url, ok=ok, http_status=status, protocol=protocol,
        content_type=content_type, size_bytes=size, accepts_ranges=ranges,
        resumable=bool(ranges and ok), cors_open=cors, latency_ms=latency,
        download_speed_mbps=speed, streamable=bool(ok and protocol == "progressive"),
        downloadable=bool(ok and protocol == "progressive"),
        redirects_to=final, error=error, checked_at=at,
    )


class LedgerColumnFidelity(ProjectionTestCase):
    """The projector must put each measured fact in the column that names it."""

    def test_measured_ledger_columns_land_in_their_own_slots(self):
        self.add_post("hdhub4u", "https://hdhub4u.test/movie/fidelity",
                      clean_title="Fidelity", releases=[
                          {"release_title": "Fidelity 1080p WEB-DL", "quality": "1080p",
                           "sources": [{"source_name": "CDN", "service": "google_cdn",
                                        "resource_id": "fid-1",
                                        "source_url": "https://cdn.test/fid.mp4"}]}])
        self.conn.execute(
            "UPDATE download_sources SET http_status = 200, is_resumable = 1,"
            " last_checked_at = '2023-11-14 22:13:20', mime_type = 'video/mp4'"
            " WHERE resource_id = 'fid-1'")
        self.project()

        link = _row(self.conn, "SELECT * FROM cat_links")
        self.assertEqual(200, link["http_status"])
        self.assertIsNone(link["latency_ms"])
        self.assertIsNone(link["speed_mbps"])
        self.assertEqual("video/mp4", link["content_type"])
        self.assertEqual(1, link["accepts_ranges"])
        self.assertEqual("active", link["state"])
        self.assertAlmostEqual(1_700_000_000.0, float(link["last_evidence_at"]), places=0)


class ApplyEvidenceTests(ProjectionTestCase):
    """Probe truth written back onto `cat_links` without a re-projection."""

    def setUp(self):
        super().setUp()
        self.url = "https://cdn.test/measured.mp4"
        self.add_post("hdhub4u", "https://hdhub4u.test/movie/measured",
                      clean_title="Measured", releases=[
                          {"release_title": "Measured 1080p WEB-DL", "quality": "1080p",
                           "sources": [{"source_name": "CDN", "service": "google_cdn",
                                        "resource_id": "m-1", "source_url": self.url}]}])
        self.project()

    def link(self):
        return _row(self.conn, "SELECT * FROM cat_links")

    def test_an_unprobed_active_link_projects_as_unchecked_then_measures_active(self):
        before = self.link()
        self.assertEqual("unchecked", before["state"])
        self.assertIsNone(before["latency_ms"])

        stats = catalog_v2.apply_evidence(self.conn, [probe(self.url)])
        self.assertEqual("active", self.link()["state"])
        self.assertGreaterEqual(stats["links_updated"], 1)
        self.assertEqual(120, self.link()["latency_ms"])
        self.assertAlmostEqual(8.5, float(self.link()["speed_mbps"]), places=3)
        self.assertEqual(200, self.link()["http_status"])
        self.assertEqual(1, self.link()["accepts_ranges"])
        self.assertAlmostEqual(1_700_000_000.0, float(self.link()["last_evidence_at"]), places=0)
        # measured score, not the structural prior: a live tier-1 progressive stream
        self.assertGreater(self.link()["rank_score"], 0)

    def test_a_measured_404_is_dead_and_scores_below_every_live_peer(self):
        dead = probe(self.url, ok=False, status=404, protocol="unusable", size=0,
                     content_type="", error="http_404", at=1_700_000_010.0)
        catalog_v2.apply_evidence(self.conn, [dead])
        self.assertEqual("dead", self.link()["state"])
        self.assertEqual(0, self.link()["rank_score"])
        self.assertIsNone(self.link()["content_type"])

    def test_token_rot_is_expired_not_dead(self):
        rotted = probe(self.url, ok=False, status=403, error="http_403",
                       protocol="unusable", size=0, content_type="", at=1_700_000_200.0)
        catalog_v2.apply_evidence(self.conn, [rotted])
        self.assertEqual("expired", self.link()["state"])

    def test_a_refused_probe_is_not_a_verdict(self):
        """blocked_target means we never knocked — the ledger state must not move."""
        before = self.link()["state"]
        refused = probe(self.url, ok=False, status=0, protocol="unusable", size=0,
                        content_type="", error="blocked_target", ranges=False,
                        latency=0, speed=0.0, at=1_700_000_300.0)
        stats = catalog_v2.apply_evidence(self.conn, [refused])
        self.assertEqual(before, self.link()["state"])
        self.assertEqual(0, stats.get("measured_links", 0))

    def test_newest_verdict_wins_over_an_older_one(self):
        catalog_v2.apply_evidence(self.conn, [probe(self.url, at=1_700_000_000.0)])
        catalog_v2.apply_evidence(self.conn, [
            probe(self.url, ok=False, status=404, protocol="unusable", size=0,
                  content_type="", error="http_404", at=1_700_000_900.0)])
        self.assertEqual("dead", self.link()["state"])

    def test_replaying_the_same_journal_changes_nothing(self):
        catalog_v2.apply_evidence(self.conn, [probe(self.url)])
        first = dict(self.link())
        again = catalog_v2.apply_evidence(self.conn)          # no new results
        self.assertEqual(0, again["links_updated"])
        self.assertEqual(first["state"], self.link()["state"])
        self.assertEqual(first["rank_score"], self.link()["rank_score"])
        self.assertEqual(first["latency_ms"], self.link()["latency_ms"])

    def test_evidence_survives_a_rebuild_and_is_re_pointed_by_url(self):
        """A rebuild renumbers `cat_links`; the probed URL heals the pointer."""
        catalog_v2.apply_evidence(self.conn, [probe(self.url)])
        self.assertEqual("active", self.link()["state"])

        # A new work whose link projects first shifts every id by one.
        self.add_post("hdhub4u", "https://hdhub4u.test/movie/aaa-first",
                      clean_title="AAFirst", imdb_id="tt0000001", releases=[
                          {"release_title": "AAFirst 480p", "quality": "480p",
                           "sources": [{"source_name": "CDN", "service": "google_cdn",
                                        "resource_id": "a-1",
                                        "source_url": "https://cdn.test/aaa.mp4"}]}])
        catalog_v2.project(self.conn, rev=2, verbose=False)

        stale = _row(self.conn, "SELECT COUNT(*) AS n FROM cat_link_evidence")
        self.assertEqual(1, stale["n"])                       # the journal survived the reset
        fresh = self.link()
        self.assertEqual("unchecked", fresh["state"])         # the measurement is gone with the ids

        other = _row(self.conn, "SELECT id FROM cat_links WHERE id <> ? ORDER BY id",
                     (fresh["id"]))
        if other is None:
            self.skipTest("fixture produced one link only; nothing to re-point at")
        # What a rebuild's id re-allocation does to a pointer: it names a different row.
        self.conn.execute("UPDATE cat_link_evidence SET link_id = ?", (other["id"],))
        self.conn.commit()

        stats = catalog_v2.apply_evidence(self.conn)
        self.assertGreaterEqual(stats["evidence_repointed"], 1)
        self.assertEqual("active", self.link()["state"])
        self.assertEqual("unchecked",
                         _row(self.conn, "SELECT * FROM cat_links WHERE id = ?",
                              (other["id"]))["state"])

    def test_an_unknown_url_is_reported_never_invented(self):
        rows_before = self.conn.execute("SELECT COUNT(*) FROM cat_links").fetchone()[0]
        stats = catalog_v2.apply_evidence(
            self.conn, [probe("https://nowhere.test/ghost.mp4")])
        self.assertGreaterEqual(stats.get("results_unresolved", 0), 1)
        self.assertEqual(rows_before,
                         self.conn.execute("SELECT COUNT(*) FROM cat_links").fetchone()[0])

    def test_a_client_report_moves_state_without_hijacking_the_score_scale(self):
        """`POST /links/{id}/report` samples have no protocol: not a measured probe."""
        reported = {"url": self.url, "ok": 1, "latency_ms": 40, "http_status": 0,
                    "probed_at": 1_700_000_500.0, "error": ""}
        stats = catalog_v2.apply_evidence(self.conn, [reported])
        self.assertEqual("active", self.link()["state"])
        self.assertEqual(40, self.link()["latency_ms"])
        self.assertEqual(0, stats["measured_links"])
        # the structural prior of §6.3, now including the +100 the active verdict earns:
        # stream 500 + tier-1 150 + non-ephemeral 100 + active 100
        self.assertEqual(850, self.link()["rank_score"])

    def test_coverage_counters_follow_the_states(self):
        catalog_v2.apply_evidence(self.conn, [probe(self.url)])
        meta = dict(self.conn.execute("SELECT key, value FROM cat_projection_meta").fetchall())
        self.assertIn("links_by_state", meta)
        self.assertIn("active", meta["links_by_state"])


class ApplyEvidenceGuardTests(unittest.TestCase):
    def test_it_refuses_a_database_without_the_projection(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with self.assertRaises(ValueError):
            catalog_v2.apply_evidence(conn, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
