#!/usr/bin/env python3
"""Tests for Player Fix v2 server work (diagnosis §6.2/§6.3/§6.4 + research
fold-in): serve-time verification (cached-first, bounded live probe only
when never-checked), warm-all-bands, the 2-hard/3-flaky strike rule,
quarantine-then-delete, the host circuit breaker + measured host priority,
and the stratified sweep (oldest-first, sibling promotion, poison guard).

Offline: fake resolvers/probers stand in for the network, temp SQLite
files stand in for the catalog. No production file is touched.

    python3 -S Fast_Fetch/test_serve_verify.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys_path = str(Path(__file__).parent.resolve())
import sys
sys.path.insert(0, sys_path)

import api_v2            # noqa: E402
import catalog_api       # noqa: E402
import catalog_v2        # noqa: E402
import fast_fetch        # noqa: E402
import link_health       # noqa: E402
import link_sweep        # noqa: E402
import panel_feed        # noqa: E402
import redact            # noqa: E402
import resolved_cache    # noqa: E402
import serve_verify      # noqa: E402
import tiers             # noqa: E402
import viewer            # noqa: E402

NOW = 1_791_000_000.0
DAY = 86400.0


def _mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _probe_dict(url, **over):
    fields = {"ok": False, "http_status": 0, "protocol": "unusable",
              "content_type": "", "size_bytes": 0, "error": ""}
    fields.update(over)
    return dict(fields)


def _journal_rows(conn, link_id, entries):
    """entries: (days_ago, ok, http_status, error)."""
    for days_ago, ok, status, error in entries:
        conn.execute(
            "INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol,"
            " http_status, content_type, size_bytes, latency_ms, speed_mbps,"
            " accepts_ranges, error, url) VALUES (?, ?, ?, '', ?, '', 0, 0, 0.0,"
            " 0, ?, '')",
            (link_id, NOW - days_ago * DAY, ok, status, error))
    conn.commit()


def _quarantine_db():
    conn = _mem_conn()
    conn.execute(
        "CREATE TABLE cat_links (id INTEGER PRIMARY KEY, ledger_link_id INT,"
        " state TEXT DEFAULT 'unchecked', url TEXT, final_url TEXT,"
        " release_id INT, last_evidence_at REAL, rank_score INT DEFAULT 0)")
    conn.execute(
        "CREATE TABLE cat_link_evidence (id INTEGER PRIMARY KEY, link_id INT,"
        " probed_at REAL, ok INT, protocol TEXT, http_status INT,"
        " content_type TEXT, size_bytes INT, latency_ms INT, speed_mbps REAL,"
        " accepts_ranges INT, error TEXT, url TEXT)")
    conn.execute(
        "CREATE TABLE download_sources (id INTEGER PRIMARY KEY, source_url TEXT,"
        " service TEXT)")
    conn.execute(
        "CREATE TABLE cat_projection_meta (key TEXT PRIMARY KEY, value TEXT)")
    return conn


class PureHelpersTests(unittest.TestCase):
    def test_normalise_url_dedupes_tracking_and_order(self):
        first = serve_verify.normalise_url(
            "https://EXAMPLE.com/p?a=1&b=2&utm_source=x#frag")
        second = serve_verify.normalise_url(
            "https://example.com/p?b=2&a=1&fbclid=zzz")
        self.assertEqual(first, second)
        self.assertNotIn("utm_source", first)
        self.assertNotIn("#", first)
        self.assertEqual(serve_verify.normalise_url("not a url"), "")
        self.assertEqual(serve_verify.normalise_url("magnet:?xt=urn:btih:abc"), "")

    def test_url_expiry_past_only_reads_expiry_params(self):
        self.assertTrue(serve_verify.url_expiry_past(
            "https://cdn.example/f.mp4?expires=%d" % int(NOW - 10), now=NOW))
        self.assertFalse(serve_verify.url_expiry_past(
            "https://cdn.example/f.mp4?expires=%d" % int(NOW + 3600), now=NOW))
        # `t` is the SIGNING time (MovieBox), never an expiry — a past `t`
        # must not condemn a fresh signature.
        self.assertFalse(serve_verify.url_expiry_past(
            "https://cdn.example/f.mp4?sign=abc&t=%d" % int(NOW - 3600),
            now=NOW))
        self.assertFalse(serve_verify.url_expiry_past(
            "https://cdn.example/f.mp4", now=NOW))

    def test_classify_failure_splits_hard_flaky_transport(self):
        self.assertEqual(serve_verify.classify_failure(404, "http_404"), "hard")
        self.assertEqual(serve_verify.classify_failure(410, ""), "hard")
        self.assertEqual(serve_verify.classify_failure(0, "dns"), "hard")
        self.assertEqual(serve_verify.classify_failure(0, "timeout"), "flaky")
        self.assertEqual(serve_verify.classify_failure(429, "http_429"), "flaky")
        self.assertEqual(serve_verify.classify_failure(500, ""), "flaky")
        self.assertEqual(serve_verify.classify_failure(0, "tls"), "transport")
        self.assertEqual(serve_verify.classify_failure(0, "conn_reset"),
                         "transport")
        self.assertEqual(serve_verify.classify_failure(0, "blocklisted"),
                         "no_verdict")

    def test_batch_is_poisoned_only_over_half_no_answer(self):
        answered = [_probe_dict("u", ok=True, http_status=200,
                                protocol="progressive")]
        self.assertFalse(serve_verify.batch_is_poisoned([]))
        self.assertFalse(serve_verify.batch_is_poisoned(
            answered * 3 + [_probe_dict("u", error="timeout")] * 2))
        self.assertTrue(serve_verify.batch_is_poisoned(
            answered * 2 + [_probe_dict("u", error="timeout")] * 3))

    def test_is_fresh_verified_reads_the_stamp(self):
        self.assertTrue(serve_verify.is_fresh_verified(
            {"verified_at": NOW - 60}, now=NOW))
        self.assertFalse(serve_verify.is_fresh_verified(
            {"verified_at": NOW - 3600}, now=NOW))
        self.assertFalse(serve_verify.is_fresh_verified({}, now=NOW))

    def test_is_known_good_trusts_hot_measured_verdicts_only(self):
        hot = {"status": "active", "http_status": 200,
               "last_checked_at": NOW - 3600}
        self.assertTrue(serve_verify.is_known_good(hot, now=NOW))
        stale = {"status": "active", "http_status": 200,
                 "last_checked_at": NOW - 8 * DAY}
        self.assertFalse(serve_verify.is_known_good(stale, now=NOW))
        unchecked = {"status": "unchecked", "http_status": 0,
                     "last_checked_at": None}
        self.assertFalse(serve_verify.is_known_good(unchecked, now=NOW))
        dead = {"status": "dead", "http_status": 404,
                "last_checked_at": NOW - 60}
        self.assertFalse(serve_verify.is_known_good(dead, now=NOW))

    def test_recheck_due_follows_the_ttl_tiers(self):
        self.assertTrue(serve_verify.recheck_due(
            {"last_checked_at": None}, now=NOW))
        failing = {"status": "dead", "last_checked_at": NOW - 21 * 3600}
        self.assertTrue(serve_verify.recheck_due(failing, now=NOW))
        fresh_fail = {"status": "dead", "last_checked_at": NOW - 3600}
        self.assertFalse(serve_verify.recheck_due(fresh_fail, now=NOW))

    def test_thresholds_default_without_a_panel(self):
        knobs = serve_verify.thresholds()
        self.assertEqual(knobs["min_hard"], 2)
        self.assertEqual(knobs["min_flaky"], 3)
        self.assertEqual(knobs["min_days"], 2)


class FinalUrlTests(unittest.TestCase):
    def _prober(self, mapping):
        def probe(url, timeout=5.0):
            return _probe_dict(url, **mapping(url))
        return probe

    def test_progressive_200_verifies(self):
        ok, reason, _ = serve_verify.verify_final_url(
            "https://cdn.example/f.mp4",
            prober=self._prober(lambda u: {"ok": True, "http_status": 200,
                                           "protocol": "progressive",
                                           "content_type": "video/mp4",
                                           "size_bytes": 1000}))
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_html_page_200_is_a_soft_404_not_a_file(self):
        ok, reason, _ = serve_verify.verify_final_url(
            "https://cdn.example/f.mp4",
            prober=self._prober(lambda u: {"ok": True, "http_status": 200,
                                           "protocol": "html_page",
                                           "content_type": "text/html",
                                           "size_bytes": 4000}))
        self.assertFalse(ok)
        self.assertEqual(reason, "webview")

    def test_404_is_hard_and_429_is_rate_limited(self):
        ok, reason, _ = serve_verify.verify_final_url(
            "https://cdn.example/f.mp4",
            prober=self._prober(lambda u: {"ok": False, "http_status": 404,
                                           "error": "http_404"}))
        self.assertFalse(ok)
        self.assertEqual(reason, "http_404")
        ok, reason, _ = serve_verify.verify_final_url(
            "https://cdn.example/f.mp4",
            prober=self._prober(lambda u: {"ok": False, "http_status": 429,
                                           "error": "http_429"}))
        self.assertFalse(ok)
        self.assertEqual(reason, "http_429")

    def test_empty_200_is_dead_without_a_body_read(self):
        ok, reason, _ = serve_verify.verify_final_url(
            "https://cdn.example/f.mp4",
            prober=self._prober(lambda u: {"ok": True, "http_status": 200,
                                           "protocol": "progressive",
                                           "content_type": "video/mp4",
                                           "size_bytes": 0}))
        self.assertFalse(ok)
        self.assertEqual(reason, "empty_file")

    def test_expired_url_is_dead_without_a_probe(self):
        calls = []
        ok, reason, _ = serve_verify.verify_final_url(
            "https://cdn.example/f.mp4?expires=%d" % int(NOW - 5),
            prober=lambda url, timeout=5.0: calls.append(url) or _probe_dict(url),
            now=NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "expired_url")
        self.assertEqual(calls, [])


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "cand.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute(
            "CREATE TABLE download_sources (id INTEGER PRIMARY KEY,"
            " source_url TEXT, service TEXT, last_failed_at REAL,"
            " failure_class TEXT, failure_resolver_v INTEGER)")
        resolved_cache._ensure_schema(self.conn)
        self.conn.execute(
            "CREATE TABLE cat_links (id INTEGER PRIMARY KEY, ledger_link_id INT,"
            " state TEXT DEFAULT 'unchecked', url TEXT, final_url TEXT,"
            " release_id INT, last_evidence_at REAL, rank_score INT DEFAULT 0)")
        self.conn.execute(
            "CREATE TABLE cat_link_evidence (id INTEGER PRIMARY KEY, link_id INT,"
            " probed_at REAL, ok INT, protocol TEXT, http_status INT,"
            " content_type TEXT, size_bytes INT, latency_ms INT, speed_mbps REAL,"
            " accepts_ranges INT, error TEXT, url TEXT)")
        self.conn.execute(
            "CREATE TABLE cat_projection_meta (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.execute(
            "INSERT INTO download_sources (id, source_url, service) VALUES"
            " (11, 'https://good.example/bridge', 'svc'),"
            " (22, 'https://dead.example/bridge', 'svc')")
        self.conn.execute(
            "INSERT INTO cat_links (id, ledger_link_id, state, url, final_url)"
            " VALUES (1, 11, 'unchecked', 'https://good.example/bridge', ''),"
            " (2, 22, 'unchecked', 'https://dead.example/bridge', '')")
        self.conn.commit()
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _ok_prober(self, url, timeout=5.0):
        return _probe_dict(url, ok=True, http_status=200,
                           protocol="progressive", content_type="video/mp4",
                           size_bytes=1000)

    def test_fresh_banked_resolution_verifies_without_a_resolver(self):
        resolved_cache.record_resolved_cache(
            self.conn, 11, {"url": "https://good.example/f.mp4",
                            "resolved_at": time.time()})
        self.conn.commit()
        calls = []
        result = serve_verify.verify_candidate(
            11, resolver=lambda sid: calls.append(sid) or {"success": False},
            prober=self._ok_prober, conn=self.conn)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["reason"], "banked")
        self.assertEqual(calls, [])

    def test_stale_banked_resolution_falls_through_to_a_live_probe(self):
        resolved_cache.record_resolved_cache(
            self.conn, 11, {"url": "https://good.example/f.mp4",
                            "resolved_at": time.time() - 3600})
        self.conn.commit()
        result = serve_verify.verify_candidate(
            11, resolver=lambda sid: {"success": True,
                                      "url": "https://good.example/f.mp4"},
            prober=self._ok_prober, conn=self.conn)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["reason"], "ok")

    def test_403_re_signs_once_and_plays_on_the_fresh_signature(self):
        calls = []
        urls = ["https://good.example/old.mp4?sign=stale",
                "https://good.example/new.mp4?sign=fresh"]

        def resolver(sid):
            calls.append(sid)
            return {"success": True, "url": urls[len(calls) - 1]}

        def prober(url, timeout=5.0):
            if "old.mp4" in url:
                return _probe_dict(url, ok=False, http_status=403,
                                   error="http_403")
            return self._ok_prober(url, timeout)

        result = serve_verify.verify_candidate(
            11, resolver=resolver, prober=prober, conn=self.conn)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["final_url"], urls[1])
        self.assertEqual(len(calls), 2)

    def test_403_twice_records_hard_failure_evidence(self):
        result = serve_verify.verify_candidate(
            22, resolver=lambda sid: {"success": True,
                                      "url": "https://dead.example/f.mp4"},
            prober=lambda url, timeout=5.0: _probe_dict(
                url, ok=False, http_status=403, error="http_403"),
            conn=self.conn)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "http_403")
        self.conn.commit()
        journal = int(self.conn.execute(
            "SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0])
        self.assertEqual(journal, 1)
        failed_at = self.conn.execute(
            "SELECT last_failed_at FROM download_sources WHERE id = 22"
            ).fetchone()[0]
        self.assertIsNotNone(failed_at)

    def test_transport_failure_records_nothing(self):
        result = serve_verify.verify_candidate(
            11, resolver=lambda sid: (_ for _ in ()).throw(
                ConnectionError("down")),
            prober=self._ok_prober, conn=self.conn)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "transport")
        self.conn.commit()
        journal = int(self.conn.execute(
            "SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0])
        self.assertEqual(journal, 0)
        failed_at = self.conn.execute(
            "SELECT last_failed_at FROM download_sources WHERE id = 11"
            ).fetchone()[0]
        self.assertIsNone(failed_at)

    def test_open_circuit_skips_the_host_without_a_resolve(self):
        for _ in range(3):
            serve_verify.record_host_failure(self.conn, "dead.example")
        self.conn.commit()
        self.assertTrue(serve_verify.circuit_open(
            self.conn, "dead.example"))
        calls = []
        result = serve_verify.verify_candidate(
            22, resolver=lambda sid: calls.append(sid) or {"success": True,
                                                           "url": "x"},
            prober=self._ok_prober, conn=self.conn)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "host_circuit_open")
        self.assertEqual(calls, [])

    def test_cached_only_candidate_returns_unchecked_without_a_resolve(self):
        # Detail fast path: no fresh banked resolution, no open circuit,
        # no live probe — the link is "unchecked", not failed, and the
        # resolver is never called.
        calls = []
        result = serve_verify.verify_candidate(
            11, resolver=lambda sid: calls.append(sid) or {"success": False},
            prober=self._ok_prober, conn=self.conn, live=False)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "unchecked")
        self.assertEqual(calls, [])

    def test_cached_only_candidate_still_serves_a_fresh_banked_resolution(self):
        resolved_cache.record_resolved_cache(
            self.conn, 11, {"url": "https://good.example/f.mp4",
                            "resolved_at": time.time()})
        self.conn.commit()
        result = serve_verify.verify_candidate(
            11, resolver=lambda sid: (_ for _ in ()).throw(
                AssertionError("live resolve on fast path")),
            prober=self._ok_prober, conn=self.conn, live=False)
        self.assertTrue(result["verified"])
        self.assertEqual(result["reason"], "banked")


class HostPriorityTests(unittest.TestCase):
    def setUp(self):
        self.conn = _mem_conn()
        self.addCleanup(self.conn.close)

    def test_probe_outcomes_feed_the_live_rate(self):
        serve_verify.record_host_failure(self.conn, "a.example")
        serve_verify.record_host_failure(self.conn, "a.example")
        serve_verify.record_host_success(self.conn, "a.example")
        self.conn.commit()
        self.assertAlmostEqual(
            serve_verify.host_live_rate(self.conn, "a.example"), 1 / 3)
        self.assertIsNone(serve_verify.host_live_rate(self.conn, "nope.example"))
        self.assertEqual(
            serve_verify.host_rank_score(self.conn, "nope.example"), 0.5)

    def test_seed_host_ranking_opens_dead_and_marks_weak(self):
        out = serve_verify.seed_host_ranking(self.conn, [
            {"host": "dead.example", "probes": 10, "successes": 0},
            {"host": "weak.example", "probes": 10, "successes": 2},
            {"host": "good.example", "probes": 10, "successes": 9},
            {"host": "tiny.example", "live_rate": 0.0, "probes": 1},
            {"host": "", "probes": 5, "successes": 0},
        ], now=NOW)
        self.assertEqual(out, {"hosts_seeded": 4, "circuits_opened": 1})
        self.assertTrue(serve_verify.circuit_open(
            self.conn, "dead.example", now=NOW))
        self.assertFalse(serve_verify.circuit_open(
            self.conn, "weak.example", now=NOW))
        row = self.conn.execute(
            "SELECT consecutive_failures FROM host_health"
            " WHERE host = 'weak.example'").fetchone()
        self.assertEqual(row[0], 2)
        self.assertAlmostEqual(
            serve_verify.host_live_rate(self.conn, "good.example"), 0.9)
        self.assertFalse(serve_verify.circuit_open(
            self.conn, "tiny.example", now=NOW))

    def test_host_health_table_migrates_old_schema(self):
        self.conn.execute(
            "CREATE TABLE host_health (host TEXT PRIMARY KEY,"
            " consecutive_failures INTEGER NOT NULL DEFAULT 0,"
            " opened_until REAL NOT NULL DEFAULT 0,"
            " backoff_s REAL NOT NULL DEFAULT 120)")
        self.conn.execute(
            "INSERT INTO host_health (host) VALUES ('old.example')")
        self.assertTrue(serve_verify._ensure_host_health(self.conn))
        cols = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(host_health)").fetchall()}
        self.assertTrue({"probes", "successes", "measured_at"} <= cols)
        serve_verify.record_host_failure(self.conn, "old.example")
        self.assertEqual(
            serve_verify.host_live_rate(self.conn, "old.example"), 0.0)


class ProbeCsvRankingTests(unittest.TestCase):
    """The Salaar check's CSV shape, in miniature: bridge-domain keys,
    soft-404s counted dead, no-answer rows never counted."""
    SOURCES = (
        "source_id,source_url\n"
        "1,https://fastdl.beer/cloud/aaa\n"
        "2,https://fastdl.beer/cloud/bbb\n"
        "3,https://mobilejsr.com/x\n"
        "4,https://mobilejsr.com/y\n"
        "5,https://mobilejsr.com/z\n"
        "6,https://vcloud.beer/cloud/q\n"
        "7,https://hubcloud.pw/cloud/w\n"
        "8,https://clicknupload.cam/f\n"
        "9,https://1fichier.com/?abc\n"
        "10,https://streamtape.to/v\n"
        "11,https://streamtape.xyz/v\n"
        "12,https://filebee.xyz/f\n"
        "13,https://fastdl.beer/cloud/ccc\n"
    )
    CHECKS = (
        "source_id,host_or_site,quality_band,url_probed,http_code,"
        "content_type,verdict,elapsed_ms,error\n"
        "1,fastdl,720p,https://video-downloads.googleusercontent.com/f1,"
        "200,video/mkv,alive,100,\n"
        "2,fastdl,480p,https://video-downloads.googleusercontent.com/f2,"
        "200,video/mkv,alive,100,\n"
        "3,mobilejsr,720p,https://mobilejsr.com/x,404,text/html,dead,50,\n"
        "4,mobilejsr,720p,https://mobilejsr.com/y,404,text/html,dead,50,\n"
        "5,mobilejsr,1080p,https://mobilejsr.com/z,404,text/html,dead,50,\n"
        "6,google_cdn,720p,https://video-downloads.googleusercontent.com/f3,"
        "200,video/mkv,alive,100,\n"
        "7,hubcloud,720p,https://hubcloud.pw/cloud/w,200,text/html,"
        "page_alive,100,\n"
        "8,clicknupload,720p,https://clicknupload.cam/f,200,text/html,"
        "page_alive,100,soft404-marker:file not found\n"
        "9,1fichier,1080p,https://1fichier.com/?abc,404,text/html,dead,50,\n"
        "10,streamtape,720p,https://streamtape.to/v,206,video/mp4,alive,80,\n"
        "11,streamtape,720p,https://streamtape.xyz/v,404,text/html,dead,50,\n"
        "12,filepress,720p,https://filebee.xyz/f,403,text/html,unknown,50,"
        "http 403\n"
        "13,fastdl,720p,https://video-downloads.googleusercontent.com/f4,"
        "400,,expired,100,token expired\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sources = Path(self.tmp.name) / "sources.csv"
        self.checks = Path(self.tmp.name) / "checks.csv"
        self.sources.write_text(self.SOURCES, encoding="utf-8")
        self.checks.write_text(self.CHECKS, encoding="utf-8")

    def test_ranking_is_keyed_by_bridge_domain_not_label(self):
        ranking = serve_verify.ranking_from_probe_csvs(
            self.checks, self.sources)
        by_host = {row["host"]: row for row in ranking}
        # fastdl's files live on googleusercontent, but the RUNTIME key
        # is the bridge domain — fastdl.beer, not the file host.
        self.assertIn("fastdl.beer", by_host)
        self.assertNotIn("video-downloads.googleusercontent.com", by_host)
        self.assertEqual(by_host["fastdl.beer"]["probes"], 2)
        self.assertEqual(by_host["fastdl.beer"]["successes"], 2)
        # The expired Google token is recorded but never counted: a dead
        # signature is a re-sign, not a dead link.
        self.assertEqual(by_host["fastdl.beer"]["expired"], 1)
        # google_cdn's alive row is a vcloud.beer bridge, not fastdl's.
        self.assertEqual(by_host["vcloud.beer"]["probes"], 1)
        self.assertEqual(by_host["vcloud.beer"]["successes"], 1)
        # Best-measured hosts first: fastdl.beer (2/2) heads the list.
        self.assertEqual(ranking[0]["host"], "fastdl.beer")

    def test_soft404_counts_dead_and_unknown_counts_nothing(self):
        ranking = serve_verify.ranking_from_probe_csvs(
            self.checks, self.sources)
        by_host = {row["host"]: row for row in ranking}
        soft = by_host["clicknupload.cam"]
        self.assertEqual((soft["probes"], soft["successes"], soft["dead"]),
                         (1, 0, 1))
        # filebee (all-unknown) has nothing measured: omitted entirely.
        self.assertNotIn("filebee.xyz", by_host)
        # hubcloud.pw (page up, file unproven) is likewise unmeasured.
        self.assertNotIn("hubcloud.pw", by_host)
        # One dead probe is recorded, not a circuit: below the threshold.
        self.assertEqual(by_host["1fichier.com"]["probes"], 1)

    def test_without_sources_join_falls_back_to_probed_domain(self):
        ranking = serve_verify.ranking_from_probe_csvs(self.checks)
        by_host = {row["host"]: row for row in ranking}
        self.assertIn("video-downloads.googleusercontent.com", by_host)
        self.assertEqual(
            by_host["video-downloads.googleusercontent.com"]["successes"], 3)

    def test_sources_join_accepts_several_files(self):
        # The multi-title check reuses Salaar's rows, whose sources live
        # in a second file: the join must merge both.
        extra = Path(self.tmp.name) / "extra-sources.csv"
        extra.write_text(
            "source_id,source_url\n"
            "14,https://fastdl.beer/cloud/ddd\n", encoding="utf-8")
        checks = Path(self.tmp.name) / "checks2.csv"
        checks.write_text(
            self.CHECKS
            + "14,fastdl,720p,https://video-downloads.googleusercontent.com/f5,"
            "200,video/mkv,alive,100,\n",
            encoding="utf-8")
        ranking = serve_verify.ranking_from_probe_csvs(
            checks, [self.sources, extra])
        by_host = {row["host"]: row for row in ranking}
        self.assertEqual(by_host["fastdl.beer"]["probes"], 3)
        self.assertEqual(by_host["fastdl.beer"]["successes"], 3)

    def test_seed_from_csvs_opens_the_dead_host_only(self):
        conn = _mem_conn()
        self.addCleanup(conn.close)
        out = serve_verify.seed_from_probe_csvs(
            conn, self.checks, self.sources, now=NOW)
        self.assertEqual(out["hosts_seeded"], 7)
        self.assertEqual(out["circuits_opened"], 1)
        self.assertTrue(serve_verify.circuit_open(
            conn, "mobilejsr.com", now=NOW))
        self.assertFalse(serve_verify.circuit_open(
            conn, "1fichier.com", now=NOW))
        self.assertEqual(
            serve_verify.host_rank_score(conn, "fastdl.beer"), 1.0)
        self.assertEqual(
            serve_verify.host_rank_score(conn, "mobilejsr.com"), 0.0)
        # An unmeasured host stays neutral — the seed never invents one.
        self.assertEqual(
            serve_verify.host_rank_score(conn, "hubcloud.pw"), 0.5)

    def test_grand_scale_720p_order_is_measured_not_asserted(self):
        # Phase C item 4 (§5): the 720p serve order — 5centscdn, mp4moviez,
        # fsl_r2, then hubcloud as a backup — must come out of the measured
        # alive rates, not out of a hardcoded list. This rebuilds the
        # grand-scale 720p rates in miniature (5centscdn 96/110 = 87%,
        # mp4moviez 49/59 = 83%, fsl_r2 12/28 = 43%, hubcloud page-alive
        # only, mobilejsr 410/514 dead) and asserts the ranking reproduces
        # the order. The per-band table in tiers.BAND_SERVICE_PRIORITY is
        # the same order, pinned by test_tiers.BandServicePriorityTests.
        rows = []
        sources = ["source_id,source_url"]
        sid = 100
        plan = (("5centscdn", 9, 1, "dead"), ("mp4moviez", 8, 2, "dead"),
                ("fsl_r2", 4, 6, "dead"), ("hubcloud", 0, 10, "page_alive"),
                ("mobilejsr", 0, 10, "dead"))
        for host, alive, other, verdict in plan:
            total = alive + other
            for i in range(total):
                sid += 1
                sources.append(f"{sid},https://{host}/x{sid}")
                v = "alive" if i < alive else verdict
                code = "200" if v == "alive" else ("404" if v == "dead" else "200")
                ctype = "video/mkv" if v == "alive" else "text/html"
                rows.append(f"{sid},{host},720p,https://{host}/x{sid},{code},"
                            f"{ctype},{v},100,")
        checks = Path(self.tmp.name) / "checks720.csv"
        checks.write_text(
            "source_id,host_or_site,quality_band,url_probed,http_code,"
            "content_type,verdict,elapsed_ms,error\n" + "\n".join(rows) + "\n",
            encoding="utf-8")
        srcs = Path(self.tmp.name) / "sources720.csv"
        srcs.write_text("\n".join(sources) + "\n", encoding="utf-8")
        ranking = serve_verify.ranking_from_probe_csvs(checks, srcs)
        hosts = [row["host"] for row in ranking]
        self.assertEqual(hosts[:3], ["5centscdn", "mp4moviez", "fsl_r2"])
        self.assertEqual(hosts[-1], "mobilejsr")
        # hubcloud is page-alive only: unmeasured, so it is omitted, not ranked.
        self.assertNotIn("hubcloud", hosts)
        by_host = {row["host"]: row for row in ranking}
        self.assertEqual(by_host["mobilejsr"]["successes"], 0)


class StrikeQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.conn = _quarantine_db()
        self.addCleanup(self.conn.close)
        for link_id, ledger_id in ((1, 101), (2, 102), (3, 103), (4, 104),
                                   (5, 105), (6, 106)):
            self.conn.execute(
                "INSERT INTO cat_links (id, ledger_link_id, state, url)"
                " VALUES (?, ?, 'dead', ?)",
                (link_id, ledger_id, "https://h.example/%d" % link_id))
            self.conn.execute(
                "INSERT INTO download_sources (id, source_url, service)"
                " VALUES (?, ?, 'svc')",
                (ledger_id, "https://h.example/%d" % link_id))
        self.conn.commit()

    def _strikes(self):
        _journal_rows(self.conn, 1, [(2, 0, 404, "http_404"),
                                     (0, 0, 404, "http_404")])
        _journal_rows(self.conn, 2, [(0, 0, 404, "http_404"),
                                     (0, 0, 404, "http_404")])
        _journal_rows(self.conn, 3, [(2, 0, 429, "http_429"),
                                     (1, 0, 429, "http_429"),
                                     (0, 0, 429, "http_429")])
        _journal_rows(self.conn, 4, [(3, 0, 404, "http_404"),
                                     (2, 0, 404, "http_404"),
                                     (1, 1, 200, ""),
                                     (0, 0, 404, "http_404")])
        _journal_rows(self.conn, 5, [(2, 0, 0, "timeout"),
                                     (1, 0, 0, "timeout"),
                                     (0, 0, 0, "timeout")])

    def test_strike_rule_counts_hard_flaky_and_resets(self):
        self._strikes()
        self.assertTrue(serve_verify.should_quarantine(
            serve_verify.strike_state(self.conn, 1)))
        self.assertFalse(serve_verify.should_quarantine(
            serve_verify.strike_state(self.conn, 2)),
            "two hard failures on the SAME day are one bad afternoon")
        self.assertTrue(serve_verify.should_quarantine(
            serve_verify.strike_state(self.conn, 3)))
        self.assertFalse(serve_verify.should_quarantine(
            serve_verify.strike_state(self.conn, 4)),
            "one success resets the run")
        self.assertTrue(serve_verify.should_quarantine(
            serve_verify.strike_state(self.conn, 5)))

    def test_quarantine_then_delete_never_deletes_unquarantined(self):
        self._strikes()
        first = serve_verify.quarantine_and_delete_dead_links(
            self.conn, delete=True)
        states = {row[0]: row[1] for row in self.conn.execute(
            "SELECT id, state FROM cat_links")}
        self.assertEqual(first["newly_quarantined"], 3)
        self.assertEqual(first["deleted"], 0,
                         "quarantine precedes delete, even when asked")
        self.assertEqual(states[1], "quarantined")
        self.assertEqual(states[2], "dead")
        self.assertEqual(states[4], "dead")
        second = serve_verify.quarantine_and_delete_dead_links(
            self.conn, delete=True)
        self.assertEqual(second["deleted"], 3)
        remaining = [row[0] for row in self.conn.execute(
            "SELECT id FROM cat_links")]
        self.assertEqual(sorted(remaining), [2, 4, 6])
        ledger = [row[0] for row in self.conn.execute(
            "SELECT id FROM download_sources")]
        self.assertEqual(sorted(ledger), [102, 104, 106])

    def test_expired_links_are_never_quarantined_or_deleted(self):
        self.conn.execute(
            "UPDATE cat_links SET state = 'expired' WHERE id = 6")
        _journal_rows(self.conn, 6, [(2, 0, 404, "http_404"),
                                     (0, 0, 404, "http_404")])
        out = serve_verify.quarantine_and_delete_dead_links(
            self.conn, delete=True)
        self.assertEqual(out["newly_quarantined"], 0)
        self.assertEqual(out["deleted"], 0)
        state = self.conn.execute(
            "SELECT state FROM cat_links WHERE id = 6").fetchone()[0]
        self.assertEqual(state, "expired")


class TiersQuarantineTests(unittest.TestCase):
    def _link(self, **over):
        link = {"stream_id": "h", "kind": "direct", "playable": True,
                "status": "active", "is_resumable": True,
                "is_temporary": False,
                "file_size_bytes": 2_000_000_000}
        link.update(over)
        return link

    def test_quarantined_scores_zero_and_never_plays(self):
        link = self._link(status="quarantined")
        self.assertEqual(tiers.score(link, "720p"), 0)
        self.assertFalse(tiers.playable(link, "720p"))

    def test_for_release_drops_quarantined_copies_entirely(self):
        release = {"quality": "720p", "codec": "x264", "size": "1.5GB",
                   "release_title": "Dune 720p", "languages": ""}
        only_bad = tiers.for_release(
            release, [self._link(status="quarantined")])
        self.assertEqual(only_bad["tiers"], [])
        mixed = tiers.for_release(
            release, [self._link(status="quarantined"),
                      self._link(stream_id="good")])
        self.assertEqual(len(mixed["tiers"]), 1)
        self.assertEqual(mixed["tiers"][0]["link"]["stream_id"], "good")


class OptionGroupsVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "viewer.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("CREATE TABLE download_sources (id INTEGER PRIMARY KEY,"
                     " source_url TEXT, service TEXT)")
        conn.commit()
        conn.close()
        for patcher in (mock.patch.object(viewer, "DB_PATH", self.db_path),):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _link(self, stream_id, kind="direct"):
        return {"stream_id": stream_id, "kind": kind, "playable": True,
                "status": "active", "is_resumable": True,
                "is_temporary": False, "file_size_bytes": 2_000_000_000,
                "mime_type": "video/mp4"}

    def _release(self, quality, stream_ids):
        rel = {"season": "", "episode": "", "quality": quality,
               "codec": "x264", "size": "1.5GB",
               "release_title": "Dune %s" % quality, "languages": ""}
        projected = dict(rel)
        projected["sources"] = [self._link(sid) for sid in stream_ids]
        return rel, projected

    def _groups(self, releases, **kwargs):
        rels, projected = zip(*releases)
        return viewer._option_groups(list(rels), list(projected), **kwargs)

    def _verifier_for(self, good):
        def verifier(link, conn):
            ok = link["stream_id"] in good
            return {"verified": ok, "reason": "ok" if ok else "http_404",
                    "verified_at": NOW if ok else None}
        return verifier

    def test_dead_winner_falls_to_the_next_candidate_in_band(self):
        groups = self._groups(
            [self._release("720p", ["bad", "good"])],
            verify=True, _verifier=self._verifier_for({"good"}))
        tier = groups[0]["tiers"][0]
        self.assertEqual(tier["band"], "720p")
        self.assertEqual(tier["link"]["stream_id"], "good")
        self.assertEqual(tier["link"]["verified_at"], NOW)

    def test_a_band_with_no_verified_link_is_hidden(self):
        groups = self._groups(
            [self._release("720p", ["good"]),
             self._release("480p", ["bad"])],
            verify=True, _verifier=self._verifier_for({"good"}))
        self.assertEqual([t["band"] for t in groups[0]["tiers"]], ["720p"])
        self.assertEqual(groups[0]["auto"]["band"], "720p")

    def test_a_verified_gated_tier_stays_gated(self):
        groups = self._groups(
            [self._release("1080p", ["good1080"]),
             self._release("720p", ["good720"])],
            verify=True, _verifier=self._verifier_for(
                {"good1080", "good720"}))
        by_band = {t["band"]: t for t in groups[0]["tiers"]}
        self.assertTrue(by_band["1080p"]["gated"])
        self.assertEqual(groups[0]["auto"]["band"], "720p")

    def test_poisoned_batch_leaves_the_ladder_untouched(self):
        def transport(link, conn):
            return {"verified": False, "reason": "transport"}
        groups = self._groups(
            [self._release("720p", ["a"]), self._release("480p", ["b"])],
            verify=True, _verifier=transport)
        self.assertEqual([t["band"] for t in groups[0]["tiers"]],
                         ["720p", "480p"])
        self.assertNotIn("verified_at", groups[0]["tiers"][0]["link"])

    def test_a_hanging_candidate_times_out_and_its_band_hides(self):
        import time as _time

        def verifier(link, conn):
            if link["stream_id"] == "slow":
                _time.sleep(0.4)
                return {"verified": True, "reason": "ok",
                        "verified_at": NOW}
            return {"verified": True, "reason": "ok", "verified_at": NOW}

        groups = self._groups(
            [self._release("720p", ["fast"]),
             self._release("480p", ["slow"])],
            verify=True, verify_timeout=0.1, _verifier=verifier)
        self.assertEqual([t["band"] for t in groups[0]["tiers"]], ["720p"])

    def test_host_priority_orders_the_winner(self):
        conn = sqlite3.connect(str(self.db_path))
        serve_verify.seed_host_ranking(conn, [
            {"host": "weak.example", "probes": 10, "successes": 0},
            {"host": "good.example", "probes": 10, "successes": 10},
        ], now=NOW)
        conn.close()
        hosts = {"weak-link": "weak.example", "good-link": "good.example"}

        def verifier(link, conn):
            return {"verified": True, "reason": "ok", "verified_at": NOW}

        groups = self._groups(
            [self._release("720p", ["weak-link", "good-link"])],
            verify=True, _verifier=verifier,
            _host_of=lambda link: hosts[link["stream_id"]])
        # The first candidate by score is the weak host's link; the
        # measured ranking promotes the good host's link to winner.
        self.assertEqual(groups[0]["tiers"][0]["link"]["stream_id"],
                         "good-link")

    def test_unchecked_candidate_keeps_its_band(self):
        # Detail fast path: a candidate with no cached verdict either
        # way is not known dead, only never checked — its band stays,
        # and the press re-verifies it live.
        def unchecked(link, conn):
            return {"verified": False, "reason": "unchecked"}
        groups = self._groups(
            [self._release("720p", ["a"]),
             self._release("480p", ["b"])],
            verify=True, _verifier=unchecked)
        self.assertEqual([t["band"] for t in groups[0]["tiers"]],
                         ["720p", "480p"])
        self.assertEqual(groups[0]["tiers"][0]["link"]["stream_id"], "a")
        self.assertNotIn("verified_at", groups[0]["tiers"][0]["link"])
        self.assertEqual(groups[0]["auto"]["band"], "720p")

    def test_unchecked_winner_yields_to_a_verified_backup(self):
        def mixed(link, conn):
            if link["stream_id"] == "warm":
                return {"verified": True, "reason": "ok",
                        "verified_at": NOW}
            return {"verified": False, "reason": "unchecked"}
        groups = self._groups(
            [self._release("720p", ["cold", "warm"])],
            verify=True, _verifier=mixed)
        tier = groups[0]["tiers"][0]
        self.assertEqual(tier["link"]["stream_id"], "warm")
        self.assertEqual(tier["link"]["verified_at"], NOW)
        self.assertEqual(tier["backup_handles"], ["cold"])

    def test_dead_band_is_hidden_but_unchecked_band_stays(self):
        def mixed(link, conn):
            if link["stream_id"] == "dead":
                return {"verified": False, "reason": "http_404"}
            return {"verified": False, "reason": "unchecked"}
        groups = self._groups(
            [self._release("720p", ["dead"]),
             self._release("480p", ["cold"])],
            verify=True, _verifier=mixed)
        self.assertEqual([t["band"] for t in groups[0]["tiers"]], ["480p"])

    def _token(self, source_id):
        os.environ["RADD_STREAM_SECRET"] = "test-secret-for-serve-verify"
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        viewer._SIGNING_SECRET = None
        self.addCleanup(setattr, viewer, "_SIGNING_SECRET", None)
        return redact.mint_token(source_id, viewer.signing_secret())

    def test_cached_only_verifier_never_resolves_live(self):
        conn = sqlite3.connect(str(self.db_path))
        self.addCleanup(conn.close)
        token = self._token(111)
        with mock.patch.object(
                viewer, "_resolve_coalesced",
                side_effect=AssertionError("live resolve on fast path")):
            result = viewer._verify_tier_link(
                {"stream_id": token}, conn, live=False)
        self.assertEqual(result["verified"], False)
        self.assertEqual(result["reason"], "unchecked")
        self.assertEqual(result["source_id"], 111)

    def test_cached_only_verifier_reports_a_dead_ledger_row(self):
        conn = sqlite3.connect(str(self.db_path))
        self.addCleanup(conn.close)
        conn.execute("ALTER TABLE download_sources ADD COLUMN status TEXT")
        conn.execute("ALTER TABLE download_sources ADD COLUMN http_status INT")
        conn.execute(
            "ALTER TABLE download_sources ADD COLUMN last_checked_at TEXT")
        conn.execute(
            "INSERT INTO download_sources (id, source_url, service, status,"
            " http_status, last_checked_at) VALUES (111,"
            " 'https://dead.example/x', 'svc', 'dead', 404,"
            " '2026-11-13 00:00:00')")
        conn.commit()
        token = self._token(111)
        with mock.patch.object(
                viewer, "_resolve_coalesced",
                side_effect=AssertionError("live resolve on fast path")):
            result = viewer._verify_tier_link(
                {"stream_id": token}, conn, live=False)
        self.assertEqual(result["verified"], False)
        self.assertEqual(result["reason"], "dead")


class WarmAllBandsTests(unittest.TestCase):
    def setUp(self):
        os.environ["RADD_STREAM_SECRET"] = "test-secret-for-serve-verify"
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        viewer._SIGNING_SECRET = None
        self.addCleanup(setattr, viewer, "_SIGNING_SECRET", None)

    def _p_dict(self):
        tok1 = redact.mint_token(111, viewer.signing_secret())
        tok2 = redact.mint_token(222, viewer.signing_secret())
        return {"option_groups": [
            {"auto": {"band": "720p", "stream_id": tok1},
             "tiers": [{"band": "720p", "link": {"stream_id": tok1}},
                       {"band": "480p", "link": {"stream_id": tok2}}]}]}

    def test_warm_starts_one_thread_per_band(self):
        started = []
        with (mock.patch.object(viewer, "_preresolve_is_warm",
                                return_value=False),
              mock.patch.object(viewer, "_start_preresolve",
                                side_effect=started.append)):
            result = viewer._preresolve_for_detail(self._p_dict())
        self.assertEqual(result["status"], "warming")
        self.assertEqual(result["band"], "720p")
        self.assertEqual(result["bands"], ["720p", "480p"])
        self.assertEqual(started, [111, 222])

    def test_warm_reports_warm_when_every_band_is_cached(self):
        with (mock.patch.object(viewer, "_preresolve_is_warm",
                                return_value=True),
              mock.patch.object(viewer, "_start_preresolve") as start):
            result = viewer._preresolve_for_detail(self._p_dict())
        self.assertEqual(result["status"], "warm")
        self.assertEqual(result["bands"], ["720p", "480p"])
        start.assert_not_called()

    def test_no_groups_is_unavailable(self):
        self.assertEqual(viewer._preresolve_for_detail({}),
                         {"status": "unavailable"})


class PlayVerifiedTests(unittest.TestCase):
    def setUp(self):
        self.conn = _mem_conn()
        self.addCleanup(self.conn.close)
        self.conn.execute(
            "CREATE TABLE cat_links (id INTEGER PRIMARY KEY, release_id INT,"
            " kind TEXT, playability TEXT, state TEXT, final_url TEXT,"
            " url TEXT, ledger_link_id INT)")
        self.conn.execute(
            "CREATE TABLE download_sources (id INTEGER PRIMARY KEY,"
            " last_failed_at REAL, failure_resolver_v INTEGER)")
        resolved_cache._ensure_schema(self.conn)
        for release_id, ledger_id in ((1, 11), (2, 22)):
            self.conn.execute(
                "INSERT INTO cat_links (id, release_id, kind, playability,"
                " state, final_url, url, ledger_link_id)"
                " VALUES (?, ?, 'stream', 'both', 'active', '',"
                " 'https://h.example/x', ?)",
                (release_id, release_id, ledger_id))
            self.conn.execute(
                "INSERT INTO download_sources (id, last_failed_at,"
                " failure_resolver_v) VALUES (?, NULL, NULL)", (ledger_id,))
        self.conn.commit()

    def test_verified_candidate_needs_a_fresh_banked_resolution(self):
        self.assertFalse(api_v2._release_has_verified_candidate(self.conn, 1))
        resolved_cache.record_resolved_cache(
            self.conn, 11, {"url": "https://h.example/f.mp4",
                            "resolved_at": time.time()})
        self.conn.commit()
        self.assertTrue(api_v2._release_has_verified_candidate(self.conn, 1))
        resolved_cache.record_resolved_cache(
            self.conn, 11, {"url": "https://h.example/f.mp4",
                            "resolved_at": time.time() - 3600})
        self.conn.commit()
        self.assertFalse(api_v2._release_has_verified_candidate(self.conn, 1))

    def test_play_prefers_the_verified_print(self):
        resolved_cache.record_resolved_cache(
            self.conn, 22, {"url": "https://h.example/f.mp4",
                            "resolved_at": time.time()})
        self.conn.commit()
        bundles = {1: {"ok": True, "playable": True, "release_id": 1,
                       "quality_score": 90},
                   2: {"ok": True, "playable": True, "release_id": 2,
                       "quality_score": 80}}
        with mock.patch.object(
                catalog_api, "play_bundle",
                side_effect=lambda conn, release_id, **kw: bundles[release_id]):
            picked = api_v2._play_first_playable(
                self.conn, [1, 2], episode_id=None, include_adult=False)
        self.assertEqual(picked["release_id"], 2)

    def test_play_falls_back_when_nothing_is_verified(self):
        bundles = {1: {"ok": True, "playable": True, "release_id": 1},
                   2: {"ok": True, "playable": True, "release_id": 2}}
        with mock.patch.object(
                catalog_api, "play_bundle",
                side_effect=lambda conn, release_id, **kw: bundles[release_id]):
            picked = api_v2._play_first_playable(
                self.conn, [1, 2], episode_id=None, include_adult=False)
        self.assertEqual(picked["release_id"], 1)


def _sweep_catalog(path, hosts):
    """Hand-built cat_links with evidence ages: hosts maps host -> list of
    (link_id, last_evidence_at-or-None, release_id, path)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE cat_links (id INTEGER PRIMARY KEY, release_id INT,"
        " work_id INT, ledger_link_id INT, url TEXT, final_url TEXT,"
        " service TEXT, state TEXT DEFAULT 'unchecked',"
        " playability TEXT DEFAULT 'both', rank_score INT DEFAULT 0,"
        " last_evidence_at REAL)")
    conn.execute("CREATE TABLE cat_projection_meta"
                 " (key TEXT PRIMARY KEY, value TEXT)")
    rows = []
    for host, links in hosts.items():
        for link_id, evidence_at, release_id, slug in links:
            rows.append((link_id, release_id, 1, 1000 + link_id,
                         "https://%s/%s" % (host, slug), "", "svc",
                         "unchecked", "both", 100 - link_id, evidence_at))
    conn.executemany("INSERT INTO cat_links VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     rows)
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


class SweepFoldInTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
                mock.patch.object(link_sweep, "_read_mem",
                                  return_value=(8192.0, 4096.0)),
                mock.patch.object(link_sweep, "_load_average",
                                  return_value=0.5)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_draw_is_oldest_first_not_random(self):
        cat = _sweep_catalog(Path(self.tmp.name) / "cat.db", {
            "a.example": [(1, None, 1, "p0"), (2, 100.0, 1, "p1"),
                          (3, 200.0, 1, "p2"), (4, 300.0, 1, "p3")],
            "b.example": [(5, None, 2, "p0"), (6, 50.0, 2, "p1")]})
        self.addCleanup(cat.close)
        sample, plan = link_sweep.draw_sample(cat, 3, seed=7)
        # Population 6, limit 3 -> a:2, b:1; oldest first per host.
        self.assertEqual([r["link_id"] for r in sample], [1, 2, 5])
        self.assertEqual(plan["allocation"], {"a.example": 2, "b.example": 1})

    def test_draw_dedupes_the_same_file_under_two_urls(self):
        cat = _sweep_catalog(Path(self.tmp.name) / "cat.db", {
            "a.example": [(1, None, 1, "p?a=1&b=2&utm_source=x"),
                          (2, None, 1, "p?b=2&a=1"),
                          (3, None, 1, "other")]})
        self.addCleanup(cat.close)
        sample, _plan = link_sweep.draw_sample(cat, 10, seed=7)
        self.assertEqual([r["link_id"] for r in sample], [1, 3])

    def test_failing_sample_promotes_its_siblings(self):
        cat = _sweep_catalog(Path(self.tmp.name) / "cat.db", {
            "a.example": [(1, None, 1, "p0"), (2, None, 1, "p1")],
            "b.example": [(3, None, 2, "p0")]})
        self.addCleanup(cat.close)
        staging = sqlite3.connect(str(Path(self.tmp.name) / "sweep.db"))
        staging.row_factory = sqlite3.Row
        self.addCleanup(staging.close)
        probed = []

        def prober(items):
            out = []
            for item in items:
                probed.append(item["url"])
                if item["url"].endswith("/p0") and "a.example" in item["url"]:
                    out.append(link_health.ProbeResult(
                        url=item["url"], ok=False, http_status=404,
                        protocol="unusable", error="http_404",
                        checked_at=NOW))
                else:
                    out.append(link_health.ProbeResult(
                        url=item["url"], ok=True, http_status=200,
                        protocol="progressive", checked_at=NOW))
            return out

        summary = link_sweep.run_sample(cat, staging, limit=1, prober=prober)
        self.assertEqual(summary["state"], "complete")
        self.assertIn("https://a.example/p1", probed,
                      "the dead sample's same-movie sibling must be checked")
        self.assertEqual(summary["siblings_promoted"], 1)
        self.assertEqual(summary["links_done"], 2)

    def test_poisoned_batch_records_nothing_and_pauses(self):
        cat = _sweep_catalog(Path(self.tmp.name) / "cat.db", {
            "a.example": [(1, None, 1, "p0"), (2, None, 1, "p1")]})
        self.addCleanup(cat.close)
        staging = sqlite3.connect(str(Path(self.tmp.name) / "sweep.db"))
        staging.row_factory = sqlite3.Row
        self.addCleanup(staging.close)

        def prober(items):
            return [link_health.ProbeResult(
                url=item["url"], ok=False, http_status=0,
                protocol="unusable", error="timeout", checked_at=NOW)
                for item in items]

        summary = link_sweep.run_sample(cat, staging, limit=10, prober=prober)
        self.assertEqual(summary["state"], "paused_network")
        self.assertEqual(summary["links_done"], 0)
        evidenced = int(staging.execute(
            "SELECT COUNT(*) FROM link_sweep_evidence").fetchone()[0])
        self.assertEqual(evidenced, 0)


class MergeCountersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "cat.db"
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
                        mock.patch.object(viewer, "DB_PATH", self.db_path),
                        mock.patch.object(link_sweep, "_read_mem",
                                          return_value=(8192.0, 4096.0)),
                        mock.patch.object(link_sweep, "_load_average",
                                          return_value=0.5)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cat = self._real_catalog(self.db_path)
        self.addCleanup(self.cat.close)
        self.staging = sqlite3.connect(str(Path(self.tmp.name) / "sweep.db"))
        self.staging.row_factory = sqlite3.Row
        self.addCleanup(self.staging.close)

    def _real_catalog(self, path):
        fast_fetch.init_db(path)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        for title, slug in (("Alpha Film", "alpha-film"),
                            ("Beta Film", "beta-film")):
            data = {
                "url": "https://cdn.example/movie/%s/" % slug,
                "slug": slug, "title": "%s (2024)" % title,
                "clean_title": title, "year": 2024,
                "content_type": "movie",
                "poster_url": "https://cdn/poster.jpg",
                "genres": '["Action"]', "synopsis": "%s synopsis" % title,
                "is_18_plus": 0, "source_site": "cdn.example",
                "industry": "Bollywood", "country": "India",
                "language": "Hindi",
                "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
                "releases": [{"release_title": "%s 1080p" % title,
                              "quality": "1080p", "codec": "x264",
                              "size": "1.5GB", "languages": '["Hindi"]',
                              "season": "", "episode": "",
                              "intermediate_url": "", "origin_url": "",
                              "source_site": "cdn.example",
                              "sources": [{"source_url":
                                          "https://cdn.example/%s.mp4" % slug,
                                          "quality": "1080p",
                                          "status": "active"}]}],
            }
            fast_fetch.save_scraped_data(data, enrich_metadata=False,
                                         ensure_db=False)
        conn.commit()
        catalog_v2.project(conn, rev=1, verbose=False)
        conn.commit()
        return conn

    def _result(self, url, **over):
        fields = {"url": url, "ok": False, "http_status": 0,
                  "protocol": "unusable", "content_type": "",
                  "size_bytes": 0, "accepts_ranges": False,
                  "resumable": False, "cors_open": False, "latency_ms": 0,
                  "download_speed_mbps": 0.0, "streamable": False,
                  "downloadable": False, "redirects_to": "", "error": "",
                  "checked_at": NOW}
        fields.update(over)
        return link_health.ProbeResult(**fields)

    def test_merge_stamps_newly_dead_and_quarantine_counters(self):
        def mapping(url):
            if "alpha-film" in url:
                return self._result(url, ok=True, protocol="progressive",
                                    http_status=200)
            return self._result(url, http_status=404, error="http_404")

        link_sweep.run_sample(self.cat, self.staging, limit=10,
                              prober=lambda items: [
                                  mapping(i["url"]) for i in items])
        outcome = link_sweep.merge(self.cat, self.staging)
        self.assertEqual(outcome["newly_marked_dead"], 1)
        self.assertEqual(outcome["quarantined"], 0,
                         "one 404 is a strike, not a quarantine")
        self.assertEqual(outcome["deleted"], 0)
        stamp = outcome["stamp"]
        self.assertEqual(stamp["newly_marked_dead"], 1)
        self.assertIn("quarantined", stamp)
        self.assertIn("deleted", stamp)


class KnobsTests(unittest.TestCase):
    def test_warmup_count_default_is_200_for_the_top_200(self):
        self.assertEqual(panel_feed.TUNING_KNOBS["warmup_count"],
                         (200, 0, 200))

    def test_quarantine_thresholds_are_operator_knobs(self):
        self.assertEqual(panel_feed.TUNING_KNOBS["quarantine_min_failures"],
                         (3, 1, 10))
        self.assertEqual(panel_feed.TUNING_KNOBS["quarantine_min_days"],
                         (2, 1, 30))


if __name__ == "__main__":
    print("fixture: %s (offline — fake resolvers/probers, temp DBs)"
          % Path(__file__).name)
    unittest.main(verbosity=2)
