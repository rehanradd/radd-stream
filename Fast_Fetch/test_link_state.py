#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for link-state propagation — `Fast_Fetch/link_state.py`.

These exist because of one measured fact (``HANDOFF_audit.md`` §5 / defect D7):
**every row** of ``download_sources`` says ``status = 'active'``, and
``/api/v1/stats`` therefore reported ``active_sources == sources`` by
construction. The rule this file protects is that a link is only called live
after something knocked on it, that knocking on it never deletes it, and that a
sweep over millions of rows can be interrupted at any batch and resumed.

No network is used or allowed: ``link_health.probe``/``probe_many`` are patched to
explode, and every verdict comes from a fake prober built out of real
``link_health.ProbeResult`` objects. The fixture ledger is created by
``fast_fetch.init_db`` so these tests run against the production schema, not a
caricature of it.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog_v2            # noqa: E402
import fast_fetch            # noqa: E402
import link_health           # noqa: E402
import link_state            # noqa: E402
import tiers                 # noqa: E402


def live(url, *, status=200, ranges=True, protocol="progressive", size=2_000_000_000,
         speed=40.0, latency=120, cors=True) -> link_health.ProbeResult:
    """A probe that says: this server answers, plays, and resumes."""
    return link_health.ProbeResult(
        url=url, ok=True, http_status=status, protocol=protocol,
        content_type="video/mp4", size_bytes=size, accepts_ranges=ranges,
        resumable=ranges, cors_open=cors, latency_ms=latency,
        download_speed_mbps=min(speed, 20.0), streamable=True, downloadable=True,
        checked_at=1_730_000_000.0)


def failed(url, *, status=0, error="conn_error", protocol="unusable") -> link_health.ProbeResult:
    return link_health.ProbeResult(url=url, ok=False, http_status=status,
                                   protocol=protocol, error=error,
                                   checked_at=1_730_000_000.0)


def answered_but_not_media(url, *, status=200) -> link_health.ProbeResult:
    """A bridge page: the endpoint is alive, the bytes are HTML."""
    return link_health.ProbeResult(url=url, ok=False, http_status=status,
                                   protocol="html_page", content_type="text/html",
                                   latency_ms=300, error="not_media",
                                   checked_at=1_730_000_000.0)


class FakeProber:
    """Deterministic, network-free prober that records every row it was asked about."""

    def __init__(self, answers: dict, *, unknown="skip", explode_after: int | None = None):
        self.answers = dict(answers)
        self.unknown = unknown
        self.calls: list[list[int]] = []
        self.explode_after = explode_after

    def __call__(self, rows) -> list:
        self.calls.append([int(row["id"]) for row in rows])
        if self.explode_after is not None and len(self.calls) > self.explode_after:
            raise KeyboardInterrupt("operator hit ctrl-c mid-batch")
        out = []
        for row in rows:
            url = row.get("final_url") or row.get("source_url") or ""
            answer = self.answers.get(url, self.unknown)
            if answer == "skip":
                out.append(None)
            elif callable(answer):
                out.append(answer(url))
            else:
                out.append(answer)
        return out

    @property
    def probed_urls(self) -> list[str]:
        urls = []
        for batch in self.calls:
            urls.extend(batch)
        return urls


class LedgerTestCase(unittest.TestCase):
    """One temp catalog holding the mix the audit found missing: live, dead,
    expired, alive-but-not-media, an un-probeable magnet, and never-checked rows."""

    LIVE = "https://cdn.example.com/movie-1080p.mp4"
    RESUMABLE_LIVE = "https://mirror.example.com/movie-1080p.mp4"
    DEAD = "https://gone.example.com/movie.mp4"
    EXPIRED = "https://token.example.com/movie.mp4?sig=old"
    PAGE = "https://bridge.example.com/get/abc"
    BLOCKED = "http://127.0.0.1:8080/internal"
    MAGNET = "magnet:?xt=urn:btih:deadbeef"
    LATE1 = "https://late1.test/a.mkv"
    LATE2 = "https://late2.test/b.mkv"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "catalog.db"
        self._patch = unittest.mock.patch.object(fast_fetch, "DB_PATH", self.db_path)
        self._patch.start()
        fast_fetch.init_db(self.db_path)
        # Nothing in this file may reach the network. Not "should not": cannot.
        self._no_net = [
            unittest.mock.patch.object(link_health, "probe",
                                       side_effect=AssertionError("network use in a test")),
            unittest.mock.patch.object(link_health, "probe_many",
                                       side_effect=AssertionError("network use in a test")),
        ]
        for patcher in self._no_net:
            patcher.start()
        self.conn = link_state.connect(self.db_path)
        link_state.ensure_schema(self.conn)
        self.rows = self._seed()

    def tearDown(self):
        self.conn.close()
        for patcher in self._no_net:
            patcher.stop()
        self._patch.stop()
        self.tmp.cleanup()

    def _seed(self) -> dict[str, int]:
        """Two prints of one movie, nine ledger links, exactly the mix the audit says
        is missing from production: a live CDN that ignores Range, a live resumable
        mirror, a 404, a 403 token, a 200-HTML bridge, a target the SSRF guard
        refuses, a magnet, and two links past the first batch boundary (so an
        interrupted run has somewhere to resume from)."""
        conn = self.conn
        conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year, content_type,"
            " source_site, is_18_plus) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            ("https://site.test/movie/", "movie", "Movie (2024)", "Movie", 2024, "movie",
             "testsite"))
        post_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        releases = {}
        for label, quality in (("1080p", "1080p"), ("720p", "720p")):
            conn.execute(
                "INSERT INTO releases (post_id, release_title, quality, codec, size,"
                " source_site, origin_url) VALUES (?, ?, ?, 'x265', '2.1GB', 'testsite', ?)",
                (post_id, f"Movie {label}", quality, f"https://site.test/{label}/"))
            releases[label] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        plan = [
            (releases["1080p"], "hubcloud_10g", "Direct", self.LIVE, "active"),
            (releases["1080p"], "pixeldrain", "Mirror", self.RESUMABLE_LIVE, "active"),
            (releases["1080p"], "fsl_r2", "Gone", self.DEAD, "active"),
            (releases["1080p"], "fastdl", "Token", self.EXPIRED, "active"),
            (releases["1080p"], "greenmotors", "Bridge", self.PAGE, "active"),
            (releases["720p"], "internal", "Blocked", self.BLOCKED, "active"),
            (releases["720p"], "torrent", "Magnet", self.MAGNET, "active"),
            # Two links the sweep must reach only after a resume: they start after
            # the first batch boundary, so an interrupted run has somewhere to land.
            (releases["720p"], "vegadrive", "Late 1", self.LATE1, "active"),
            (releases["720p"], "vegadrive", "Late 2", self.LATE2, "active"),
        ]
        ids = {}
        for release_id, service, name, url, status in plan:
            conn.execute(
                "INSERT INTO download_sources (release_id, source_name, service, resource_id,"
                " source_url, final_url, playback_type, is_temporary, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (release_id, name, service, f"res-{len(ids)}", url, url,
                 "download" if service == "torrent" else "direct", status))
            ids[url] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return {"post": post_id, "1080p": releases["1080p"], "720p": releases["720p"],
                "ids": ids}

    # ── helpers ────────────────────────────────────────────────────────────── #
    def row(self, url: str) -> sqlite3.Row:
        return self.conn.execute(
            "SELECT * FROM download_sources WHERE id = ?", (self.rows["ids"][url],)).fetchone()

    def snapshot(self) -> list[tuple]:
        """Every ledger row, all columns — the proof that nothing was deleted or
        silently blanked."""
        return list(self.conn.execute(
            "SELECT * FROM download_sources ORDER BY id"))

    def prober(self, **overrides) -> FakeProber:
        answers = {
            self.LIVE: live(self.LIVE, ranges=False, speed=12.0),
            self.RESUMABLE_LIVE: live(self.RESUMABLE_LIVE),
            self.DEAD: failed(self.DEAD, status=404, error="http_404"),
            self.EXPIRED: failed(self.EXPIRED, status=403, error="http_403"),
            self.PAGE: answered_but_not_media(self.PAGE),
            self.BLOCKED: failed(self.BLOCKED, error="blocked_target"),
            self.LATE1: live(self.LATE1),
            self.LATE2: failed(self.LATE2, status=502, error="http_502"),
        }
        answers.update(overrides)
        return FakeProber(answers)

    def run_sweep(self, prober=None, **kwargs) -> dict:
        kwargs.setdefault("scope", "test")
        kwargs.setdefault("batch_size", 4)
        kwargs.setdefault("stale_after_seconds", None)
        return link_state.propagate(self.conn, prober=prober or self.prober(), **kwargs)


class ClassifyTests(unittest.TestCase):
    """The status table in the module docstring, enforced row by row."""

    def test_every_branch_of_the_published_table(self):
        cases = [
            (live("https://a/x.mp4"), "active"),
            (failed("https://a", status=404, error="http_404"), "dead"),
            (failed("https://a", status=410, error="http_410"), "dead"),
            (failed("https://a", status=451, error="http_451"), "dead"),
            (failed("https://a", status=500, error="http_500"), "dead"),
            (failed("https://a", status=403, error="http_403"), "expired"),
            (failed("https://a", status=429, error="http_429"), "expired"),
            (failed("https://a", error="timeout"), "dead"),
            (failed("https://a", error="dns"), "dead"),
            (failed("https://a", error="tls"), "dead"),
            (failed("https://a", error="conn_reset"), "dead"),
            (failed("https://a", error="conn_error:ValueError"), "dead"),
            (failed("https://a", error="redirect_loop"), "dead"),
            (failed("https://a", error="empty_body"), "dead"),
            # alive but not media: liveness is true, playability is the other axis
            (answered_but_not_media("https://a"), "active"),
            # we never looked, so we have no verdict and must not claim one
            (failed("https://a", error="blocked_target"), "unverified"),
            (failed("https://a", error="blocklisted"), "unverified"),
            (failed("https://a", error="invalid_url"), "unverified"),
            (None, "unverified"),
        ]
        for payload, expected in cases:
            self.assertEqual(link_state.classify(payload), expected,
                             getattr(payload, "error", payload))

    def test_effective_status_refuses_an_unprobed_active(self):
        unprobed = {"status": "active", "checked_at": None,
                    "last_checked_at": None, "http_status": None}
        probed = dict(unprobed, checked_at=1.0)
        legacy = dict(unprobed, last_checked_at="2026-10-01 00:00:00", http_status=206)
        self.assertEqual(link_state.effective_status(unprobed), "unverified")
        self.assertEqual(link_state.effective_status(probed), "active")
        self.assertEqual(link_state.effective_status(legacy), "active",
                         "a fast_fetch.run_health_check measurement counts as evidence")
        for status in ("dead", "expired", "unverified"):
            self.assertEqual(link_state.effective_status({"status": status}), status,
                             "a written-down failure is never softened")
        self.assertEqual(link_state.projected_state(unprobed), "unchecked")
        self.assertEqual(link_state.projected_state(probed), "active")

    def test_magnet_and_empty_urls_are_never_probed(self):
        self.assertFalse(link_state.should_probe({"final_url": "magnet:?xt=urn:btih:x"}))
        self.assertFalse(link_state.should_probe({"final_url": "", "source_url": ""}))
        self.assertFalse(link_state.should_probe({"final_url": "ftp://h/a.mkv"}))
        self.assertTrue(link_state.should_probe({"final_url": "https://h/a.mkv"}))

    def test_no_verdict_produces_no_write(self):
        """A link we refused to look at keeps its unverified state and gets no
        timestamp, so a later run with a legitimate reason can still check it."""
        row = {"id": 1, "source_url": "http://x", "final_url": "http://x"}
        self.assertIsNone(link_state.verdict_for(row, failed("http://x", error="blocked_target")))
        self.assertIsNotNone(link_state.verdict_for(row, failed("http://x", status=404,
                                                               error="http_404")))


class PropagationTests(LedgerTestCase):
    def test_verdicts_land_on_the_right_rows_and_nothing_is_deleted(self):
        before = self.snapshot()
        summary = self.run_sweep()

        self.assertEqual(summary["rows_updated"], 7, "seven links got a real verdict")
        self.assertEqual(self.row(self.LIVE)["status"], "active")
        self.assertEqual(self.row(self.RESUMABLE_LIVE)["status"], "active")
        self.assertEqual(self.row(self.RESUMABLE_LIVE)["is_resumable"], 1)
        self.assertEqual(self.row(self.RESUMABLE_LIVE)["cors_open"], 1)
        self.assertEqual(self.row(self.RESUMABLE_LIVE)["http_status"], 200)
        self.assertEqual(self.row(self.LIVE)["is_resumable"], 0,
                         "the prober said this one ignores Range")
        self.assertEqual(self.row(self.DEAD)["status"], "dead")
        self.assertEqual(self.row(self.DEAD)["http_status"], 404)
        self.assertEqual(self.row(self.DEAD)["probe_error"], "http_404")
        self.assertEqual(self.row(self.EXPIRED)["status"], "expired")
        self.assertEqual(self.row(self.PAGE)["status"], "active",
                         "the bridge answers 200 — that is liveness, not playability")
        self.assertEqual(self.row(self.PAGE)["probe_error"], "not_media")
        self.assertEqual(self.row(self.PAGE)["protocol"], "html_page")

        # The dead link is still in the ledger, with its URL and resource id intact.
        gone = self.row(self.DEAD)
        self.assertEqual(gone["final_url"], self.DEAD)
        self.assertIsNotNone(gone["resource_id"])
        self.assertIsNotNone(gone["checked_at"])
        self.assertIsNotNone(gone["last_checked_at"])
        self.assertEqual(
            str(gone["last_checked_at"]),
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(gone["checked_at"])),
            "the text stamp tiers._seconds_since() reads and the epoch stamp we store "
            "are the same instant")
        self.assertIsNotNone(tiers._seconds_since(gone["last_checked_at"]),
                            "the stamp must parse, or the ladder loses its freshness term")

        after = self.snapshot()
        self.assertEqual(len(after), len(before), "zero data loss: no row was deleted")
        self.assertEqual([row[0] for row in before], [row[0] for row in after],
                         "same ids, same order")
        # columns the sweep must not blank out
        for index, (old, new) in enumerate(zip(before, after)):
            self.assertEqual(old[:9], new[:9], f"identity columns of row {old[0]} changed")

    def test_unprobeable_and_unanswered_rows_are_left_alone(self):
        self.run_sweep()
        magnet = self.row(self.MAGNET)
        self.assertEqual(magnet["status"], "active", "no verdict, so no rewrite")
        self.assertIsNone(magnet["checked_at"])
        blocked = self.row(self.BLOCKED)
        self.assertIsNone(blocked["checked_at"],
                          "blocked_target is not a measurement of the link")

    def test_run_is_idempotent(self):
        first = self.run_sweep()
        snapshot = self.snapshot()
        second_prober = self.prober()
        second = link_state.propagate(self.conn, scope="test", prober=second_prober,
                                      batch_size=4, stale_after_seconds=None, resume=False)
        # Only the row we could not answer is offered again (the blocked target);
        # every measured row is skipped, so a rerun costs one request, not 2.3M.
        self.assertEqual(second["rows_checked"], 1)
        self.assertEqual(second["rows_updated"], 0)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertGreater(first["rows_updated"], 0)

    def test_reprobe_everything_writes_the_same_truth_twice(self):
        self.run_sweep()
        snapshot = self.snapshot()
        link_state.propagate(self.conn, scope="test", prober=self.prober(), batch_size=4,
                             only_unchecked=False, stale_after_seconds=None, resume=False)
        self.assertEqual(self.snapshot(), snapshot,
                         "re-probing is idempotent, not a drift source")

    def test_interrupted_mid_batch_resumes_without_reprobing(self):
        prober = FakeProber(self.prober().answers, explode_after=1)
        with self.assertRaises(KeyboardInterrupt):
            link_state.propagate(self.conn, scope="test", prober=prober, batch_size=2,
                                 stale_after_seconds=None)
        cursor = self.conn.execute(
            "SELECT * FROM link_state_cursor WHERE scope = 'test'").fetchone()
        self.assertEqual(cursor["state"], "interrupted")
        self.assertGreater(cursor["last_id"], 0, "the cursor stopped where the work stopped")
        committed = set(prober.calls[0])
        self.assertEqual(len(committed), 2)
        checked = ("SELECT COUNT(*) AS n FROM download_sources WHERE checked_at IS NOT NULL")
        self.assertEqual(self.conn.execute(checked).fetchone()["n"], 2,
                         "only the committed batch survived the interrupt")

        # resume with the SAME prober, so its call log proves what was re-read
        prober.explode_after = None
        resumed = link_state.propagate(self.conn, scope="test", prober=prober,
                                       batch_size=2, stale_after_seconds=None)
        self.assertEqual(resumed["state"], "complete")
        re_read = [row_id for batch in prober.calls[1:] for row_id in batch]
        self.assertEqual(set(re_read) & committed, set(),
                         "the resume starts at the cursor: committed work is never redone")
        self.assertEqual(self.conn.execute(checked).fetchone()["n"], 7)
        for url in (self.LIVE, self.RESUMABLE_LIVE, self.DEAD, self.EXPIRED, self.PAGE,
                    self.LATE1, self.LATE2):
            self.assertIsNotNone(self.row(url)["checked_at"], url)
        self.assertIsNone(self.row(self.MAGNET)["checked_at"], "not a probeable link")

    def test_max_batches_takes_a_slice_and_leaves_the_cursor_for_next_time(self):
        first = self.run_sweep(max_batches=1)
        self.assertEqual(first["batches"], 1)
        self.assertEqual(first["state"], "running")
        self.assertEqual(first["rows_checked"], 4)
        checked = ("SELECT COUNT(*) AS n FROM download_sources WHERE checked_at IS NOT NULL")
        self.assertEqual(self.conn.execute(checked).fetchone()["n"], 4)
        second = self.run_sweep()
        self.assertLessEqual(second["batches"], 2, "resumed at the cursor, not at id 0")
        self.assertEqual(second["rows_checked"], 4)
        self.assertEqual(self.conn.execute(checked).fetchone()["n"], 7)
        cursor = self.conn.execute(
            "SELECT state FROM link_state_cursor WHERE scope = 'test'").fetchone()
        self.assertEqual(cursor["state"], "complete")

    def test_pages_are_bounded_and_no_write_lock_is_held_between_batches(self):
        seen = []

        def watch(summary):
            seen.append(self.conn.in_transaction)

        self.run_sweep(batch_size=2, progress=watch)
        self.assertTrue(seen)
        self.assertFalse(any(seen), "each batch must COMMIT before the next page is read")
        batches = self.conn.execute(
            "SELECT rows_checked FROM link_state_cursor WHERE scope = 'test'").fetchone()[0]
        self.assertGreaterEqual(batches, 4, "2 rows per page over 9 links")

    def test_batch_size_is_clamped(self):
        rows, _ = link_state.iter_pending(self.conn, batch_size=999_999, only_unchecked=False)
        self.assertLessEqual(len(rows), link_state.MAX_BATCH_SIZE)


class HonestyStatsTests(LedgerTestCase):
    def test_an_unchecked_catalog_reports_unverified_not_active(self):
        stats = link_state.stats_payload(self.conn)
        self.assertEqual(stats["sources"], 9)
        self.assertEqual(stats["active_sources"], 0,
                         "nothing has been knocked on, so nothing is claimed live")
        self.assertEqual(stats["unverified_sources"], 9)
        self.assertEqual(stats["verification_coverage"], 0.0)

    def test_after_a_sweep_active_sources_is_the_number_of_live_links(self):
        self.run_sweep()
        stats = link_state.stats_payload(self.conn)
        self.assertEqual(stats["active_sources"], 4)  # 2 cdns + the live bridge page + late1
        self.assertEqual(stats["dead_sources"], 2, "the 404 plus late2")
        self.assertEqual(stats["expired_sources"], 1)
        self.assertEqual(stats["unverified_sources"], 2, "magnet + blocked, by design")
        self.assertEqual(stats["resumable_sources"], 2,
                         "only the mirror and late1 accept Range; the prober said so")
        self.assertAlmostEqual(stats["verification_coverage"], 7 / 9, places=3)
        # the honest numbers must add up to the catalog, not float free of it
        self.assertEqual(sum(stats["by_status"].values()), stats["sources"])

    def test_the_inherited_active_claim_is_downgraded_in_the_ledger(self):
        """``viewer.py:2583`` runs ``SELECT COUNT(*) FROM download_sources WHERE
        status = 'active'`` and cannot be edited here — so the *stored* value has to
        tell the truth. This is the test that the backfill makes viewer's SQL honest."""
        moved = link_state.mark_unverified(self.conn, batch_size=4)
        self.assertEqual(moved["rows_moved"], 9)
        viewer_sql = "SELECT COUNT(*) FROM download_sources WHERE status = 'active'"
        self.assertEqual(self.conn.execute(viewer_sql).fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM download_sources"
                              " WHERE status = 'unverified'").fetchone()[0], 9)
        # and a sweep afterwards replaces the guess with measurements, not with more guesses
        self.run_sweep()
        self.assertEqual(self.conn.execute(viewer_sql).fetchone()[0], 4)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM download_sources"
                              " WHERE status = 'unverified'").fetchone()[0], 2)

    def test_mark_unverified_is_batched_resumable_and_never_touches_a_verdict(self):
        # resumable: one bounded page at a time, and the cursor remembers the position
        first = link_state.mark_unverified(self.conn, batch_size=4, max_batches=1,
                                           resume=False, scope="slice")
        self.assertEqual(first["rows_moved"], 4)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM download_sources WHERE status = 'unverified'").fetchone()[0], 4)
        rest = link_state.mark_unverified(self.conn, batch_size=4, scope="slice")
        self.assertEqual(rest["rows_moved"], 5, "resumed after the four already moved")
        self.assertEqual(len(self.snapshot()), 9, "zero data loss: nothing was deleted")

        # The sweep now replaces those guesses with measurements, and a second
        # backfill must leave every recorded verdict alone.
        self.run_sweep()
        dead_before = self.row(self.DEAD)["status"]
        again = link_state.mark_unverified(self.conn, batch_size=3)
        self.assertEqual(again["rows_moved"], 0,
                         "no evidence-free 'active' claim is left to downgrade")
        self.assertEqual(self.row(self.DEAD)["status"], dead_before,
                         "a measured 'dead' is not re-labelled 'unverified'")
        self.assertEqual(self.row(self.LIVE)["status"], "active",
                         "a measured 'active' is not downgraded")

    def test_projection_summary_matches_the_ledger(self):
        summary = link_state.status_summary(self.conn, projection=True)
        self.assertEqual(summary["total"], 0, "no projection built yet")
        catalog_v2.project(self.conn, verbose=False)
        summary = link_state.status_summary(self.conn, projection=True)
        self.assertEqual(summary["by_status"].get("unchecked"), 9)
        self.assertEqual(summary["coverage"], 0.0)


class ProjectionTests(LedgerTestCase):
    def test_projected_links_default_to_unchecked_and_carry_the_ledger_key(self):
        catalog_v2.project(self.conn, verbose=False)
        links = self.conn.execute(
            "SELECT * FROM cat_links ORDER BY id").fetchall()
        self.assertEqual(len(links), 9)
        self.assertTrue(all(row["ledger_link_id"] in self.rows["ids"].values()
                            for row in links),
                        "every projected link can be traced back to its ledger row")
        self.assertEqual({row["state"] for row in links}, {"unchecked"})

    def test_a_measured_link_projects_active_and_a_dead_one_projects_dead(self):
        self.run_sweep()
        catalog_v2.project(self.conn, verbose=False)
        states = dict(self.conn.execute(
            "SELECT ledger_link_id, state FROM cat_links").fetchall())
        self.assertEqual(states[self.rows["ids"][self.LIVE]], "active")
        self.assertEqual(states[self.rows["ids"][self.DEAD]], "dead")
        self.assertEqual(states[self.rows["ids"][self.EXPIRED]], "expired")
        self.assertEqual(states[self.rows["ids"][self.MAGNET]], "unchecked")
        live_rank = self.conn.execute(
            "SELECT rank_score FROM cat_links WHERE ledger_link_id = ?",
            (self.rows["ids"][self.RESUMABLE_LIVE],)).fetchone()["rank_score"]
        dead_rank = self.conn.execute(
            "SELECT rank_score FROM cat_links WHERE ledger_link_id = ?",
            (self.rows["ids"][self.DEAD],)).fetchone()["rank_score"]
        self.assertGreater(live_rank, dead_rank)
        self.assertEqual(
            self.conn.execute("SELECT accepts_ranges FROM cat_links").fetchall()[0][0], 0)

    def test_propagation_updates_the_projection_without_a_rebuild(self):
        catalog_v2.project(self.conn, verbose=False)
        evidence_before = self.conn.execute(
            "SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0]
        self.run_sweep()
        row = self.conn.execute(
            "SELECT * FROM cat_links WHERE ledger_link_id = ?",
            (self.rows["ids"][self.DEAD],)).fetchone()
        self.assertEqual(row["state"], "dead")
        self.assertEqual(row["http_status"], 404)
        self.assertEqual(row["protocol"], "unusable")
        self.assertIsNotNone(row["last_evidence_at"])
        after = self.conn.execute("SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0]
        self.assertGreater(after, evidence_before,
                           "evidence is append-only: an audit trail, not a overwrite")

    def test_legacy_projection_without_the_key_is_matched_by_url(self):
        """A catalog projected before ``ledger_link_id`` existed (catalog_full.db) must
        still receive its verdicts, and gain the key while we are there."""
        catalog_v2.project(self.conn, verbose=False)
        self.conn.execute("UPDATE cat_links SET ledger_link_id = NULL")
        self.conn.commit()
        self.run_sweep()
        row = self.conn.execute(
            "SELECT state, ledger_link_id FROM cat_links WHERE url = ?",
            (self.DEAD,)).fetchone()
        self.assertEqual(row["state"], "dead")
        self.assertEqual(row["ledger_link_id"], self.rows["ids"][self.DEAD])


class TierLadderTests(LedgerTestCase):
    """The reason the blanket 'active' hurt: `tiers` ranks on status, so an
    unverified catalog hands the player a dead server."""

    def test_for_release_never_hands_a_dead_link_to_the_player(self):
        release = {"quality": "1080p", "codec": "x265", "size": "2.1GB"}
        before = link_state.candidate_links(self.conn, self.rows["1080p"])
        self.assertEqual({row["status"] for row in before}, {"unverified"})
        # A sweep marks the 404 dead and the CDN live; the ladder must then refuse
        # the dead copy as the tier winner and promote a verified one.
        dead_id = self.rows["ids"][self.DEAD]
        answer = dict.fromkeys(
            [self.LIVE, self.RESUMABLE_LIVE, self.PAGE], live(self.LIVE))
        answer[self.DEAD] = failed(self.DEAD, status=404, error="http_404")
        answer[self.EXPIRED] = failed(self.EXPIRED, status=403, error="http_403")
        link_state.propagate(self.conn, scope="tiers",
                             prober=FakeProber(answer, unknown="skip"),
                             batch_size=9, stale_after_seconds=None)
        after = link_state.candidate_links(self.conn, self.rows["1080p"])
        statuses = {row["id"]: row["status"] for row in after}
        self.assertEqual(statuses[dead_id], "dead")

        ladder = tiers.for_release(release, after)
        tier = ladder["tiers"][0]
        winner = tier["link"]
        self.assertNotEqual(winner["id"], dead_id,
                            "a link the propagation marked dead cannot be the winner")
        self.assertEqual(winner["status"], "active")
        self.assertEqual(tier["mode"], "play")
        self.assertTrue(ladder["auto"]["playable"])
        offered = [winner["id"]] + [row["id"] for row in tier["backups"]]
        self.assertNotIn(dead_id, offered, "neither the winner nor a failover copy is dead")
        self.assertTrue(all(row["status"] == "active" for row in tier["backups"]))
        # zero data loss: collapsing to one winner folds copies away, it never drops them
        self.assertEqual(tier["copies"], len(after))
        self.assertIn(dead_id, [row["id"] for row in after],
                      "the dead copy is still recorded, so the healers can still find it")

    def test_an_unverified_catalog_does_not_earn_the_liveness_bonus(self):
        unverified = dict(playback_type="direct", status="unverified")
        verified = dict(playback_type="direct", status="active")
        dead = dict(playback_type="direct", status="dead")
        scores = [tiers.score(row) for row in (unverified, verified, dead)]
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[2], scores[0])

    def test_candidate_links_read_the_effective_status_not_the_stored_one(self):
        self.conn.execute(
            "UPDATE download_sources SET status = 'active' WHERE final_url = ?", (self.LIVE,))
        self.conn.commit()
        rows = link_state.candidate_links(self.conn, self.rows["1080p"])
        self.assertEqual({row["status"] for row in rows}, {"unverified"})
        self.run_sweep()
        rows = link_state.candidate_links(self.conn, self.rows["1080p"])
        self.assertNotIn("unverified", {row["status"] for row in rows} - {"unverified"},
                         "after a sweep every probed row carries a real verdict")


class CliTests(LedgerTestCase):
    def test_dry_run_is_a_plan_and_writes_nothing(self):
        """Without ``--apply`` the CLI must not knock on a single URL: pointed at 3M
        rows, a "dry run" that probed would itself be the outage. ``link_health`` is
        patched to raise on any request in this file, so reaching the assertions at
        all is the proof that no request was made."""
        before = self.snapshot()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = link_state.main(["--db", str(self.db_path), "--scope", "cli",
                                    "--max-batches", "1"])
        self.assertEqual(code, 0)
        plan = json.loads(out.getvalue())
        self.assertTrue(plan["plan_only"])
        self.assertEqual(plan["rows_probed"], 0, "a plan makes no request")
        self.assertEqual(plan["rows_updated"], 0)
        self.assertEqual(plan["rows_pending"], 8, "eight http(s) links need a verdict")
        self.assertEqual(self.snapshot(), before, "and the ledger is byte-for-byte unchanged")

    def test_stats_flag_reports_honest_numbers(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = link_state.main(["--db", str(self.db_path), "--stats"])
        self.assertEqual(code, 0)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["total"], 9)
        self.assertEqual(summary["by_status"], {"unverified": 9})
        self.assertEqual(summary["coverage"], 0.0)


class SchemaSafetyTests(unittest.TestCase):
    def test_ensure_schema_is_additive_and_idempotent(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "fresh.db"
        fast_fetch.init_db(path)
        conn = link_state.connect(path)
        added = link_state.ensure_schema(conn)
        self.assertIn("checked_at", added["columns"])
        again = link_state.ensure_schema(conn)
        self.assertEqual(again["columns"], [], "a second run adds nothing")
        self.assertEqual(again["tables"], [])
        conn.close()

    def test_read_only_connection_can_never_write(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "fresh.db"
        fast_fetch.init_db(path)
        rw = link_state.connect(path)
        rw.execute(
            "INSERT INTO download_sources (release_id, source_name, service, source_url,"
            " final_url, playback_type, status) VALUES"
            " (1, 'x', 'y', 'https://h/a.mkv', 'https://h/a.mkv', 'direct', 'active')")
        rw.commit()
        rw.close()

        conn = link_state.connect(path, read_only=True)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO domains_config (name, url) VALUES ('x', 'y')")
        with self.assertRaises(sqlite3.OperationalError):
            link_state.ensure_schema(conn)
        # Summarising an UNINSTALLED catalog — no cursor table, no checked_at column,
        # which is exactly the state of the production merged ledger — must still
        # answer honestly instead of believing the stored 'active'.
        self.assertEqual(link_state.status_summary(conn)["total"], 1)
        self.assertEqual(link_state.status_summary(conn)["coverage"], 0.0)
        self.assertEqual(link_state.status_summary(conn)["by_status"], {"unverified": 1})
        self.assertEqual(link_state.stats_payload(conn)["active_sources"], 0)
        self.assertEqual(link_state.stats_payload(conn)["unverified_sources"], 1)
        conn.close()


_TEMPLATE_TMP: tempfile.TemporaryDirectory | None = None
_TEMPLATE_DB: Path | None = None


def _template_db() -> Path:
    """One cold ``init_db`` for the whole file, copied wherever a plain *uninstalled*
    catalog is the point. The index-and-classify pass is the expensive part of this
    suite on a loaded box; reusing the artifact costs every schema test nothing extra."""
    global _TEMPLATE_TMP, _TEMPLATE_DB
    if _TEMPLATE_DB is None:
        _TEMPLATE_TMP = tempfile.TemporaryDirectory()
        _TEMPLATE_DB = Path(_TEMPLATE_TMP.name) / "template.db"
        with unittest.mock.patch.object(fast_fetch, "DB_PATH", _TEMPLATE_DB):
            fast_fetch.init_db(_TEMPLATE_DB)
    return _TEMPLATE_DB


class EvidenceSchemaStatusTests(unittest.TestCase):
    """Spec gap 4 (`/tmp/q5-probe-evidence-spec.md`): the six evidence columns
    ``LEDGER_COLUMNS`` owns are installed by a *declared* step, and a catalog that has
    not had that step says so out loud instead of measuring less and calling the
    difference coverage.

    Fixtures only, on copied files in ``/tmp``. Nothing here opens a production
    database: the migration is additive, but it is still a write, and the live ledger
    is applied by the operator."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        shutil.copy(_template_db(), self.db_path)
        self.conn = link_state.connect(self.db_path)
        self.addCleanup(self.conn.close)

    def tuples(self, sql: str, params=()) -> list[tuple]:
        """PRAGMA/SELECT results as plain tuples — the fixture connection rows are
        ``sqlite3.Row``, and a before/after comparison must not hinge on that."""
        return [tuple(row) for row in self.conn.execute(sql, params)]

    def _seed_link(self, url: str, **legacy) -> int:
        self.conn.execute(
            "INSERT INTO download_sources (release_id, source_name, service, source_url,"
            " final_url, playback_type, status) VALUES"
            " (1, 'x', 'y', ?, ?, 'direct', 'active')", (url, url))
        if legacy:
            sets = ", ".join(f"{k} = ?" for k in legacy)
            self.conn.execute(f"UPDATE download_sources SET {sets}"
                              " WHERE id = (SELECT MAX(id) FROM download_sources)",
                              tuple(legacy.values()))
        self.conn.commit()
        return self.conn.execute("SELECT MAX(id) FROM download_sources").fetchone()[0]

    def test_an_uninstalled_catalog_reports_itself_legacy_only(self):
        status = link_state.schema_status(self.conn)
        self.assertEqual(status["evidence_columns_missing"], list(link_state.LEDGER_COLUMNS))
        self.assertEqual(status["cursor_tables_present"], [])
        self.assertFalse(status["installed"])
        self.assertTrue(status["legacy_evidence_only"])
        self.assertEqual(status["projection"], "absent")
        # The silent shrink, made visible: this is the list `_pending_where` judges a
        # row by, and without the migration it never contains `checked_at`.
        self.assertNotIn("checked_at", status["pending_evidence"])
        # And it must stay a question that can be asked: summarising this catalog is
        # still allowed to answer (spec verification 3).
        self.assertEqual(link_state.status_summary(self.conn)["total"], 0)
        self.assertIn("active_sources", link_state.stats_payload(self.conn))

    def test_schema_plan_is_exactly_what_the_migration_adds(self):
        """Spec verification 1, on a fixture: the PRAGMA name diff is the plan, the
        plan is the six columns plus the two cursor tables, and nothing else moved."""
        plan = link_state.schema_plan(self.conn)
        self.assertEqual(sorted(plan["ledger_columns"]),
                         sorted(link_state.LEDGER_COLUMNS))
        self.assertEqual(sorted(plan["cursor_tables"]), sorted(link_state.CURSOR_TABLES))
        self.assertFalse(plan["projection_link_id"], "no cat_links in this file")

        before = {row[1] for row in self.conn.execute("PRAGMA table_info(download_sources)")}
        added = link_state.ensure_schema(self.conn)
        link_state.ensure_projection_schema(self.conn)
        after = {row[1] for row in self.conn.execute("PRAGMA table_info(download_sources)")}
        self.assertEqual(sorted(after - before), sorted(link_state.LEDGER_COLUMNS),
                         "the name diff is exactly the six additions")
        self.assertEqual(before & after, before, "no existing column disappeared")
        self.assertEqual(sorted(added["columns"]), sorted(plan["ledger_columns"]))
        self.assertEqual(added["tables"], plan["cursor_tables"])
        installed = link_state.schema_status(self.conn)
        self.assertTrue(installed["installed"])
        self.assertEqual(installed["evidence_columns_missing"], [])
        self.assertEqual(installed["cursor_tables_present"], list(link_state.CURSOR_TABLES))
        self.assertIn("checked_at", installed["pending_evidence"])
        self.assertEqual(link_state.schema_plan(self.conn),
                         {"ledger_columns": [], "cursor_tables": [],
                          "projection_link_id": False})

    def test_the_migration_leaves_existing_columns_and_values_alone(self):
        """Additive means additive: same declared type, same default, same stored row."""
        src = "https://cdn.example.com/movie.mkv"
        link_id = self._seed_link(
            src, http_status=206, is_resumable=1, mime_type="video/x-matroska",
            file_size_bytes=1234, last_checked_at="2026-10-01 00:00:00")
        cols = self.tuples("PRAGMA table_info(download_sources)")
        rows = self.tuples(
            "SELECT id, release_id, source_name, service, source_url, final_url,"
            " playback_type, is_temporary, status, is_resumable, http_status,"
            " file_size_bytes, mime_type, last_checked_at, expires_at, ttl_source"
            " FROM download_sources ORDER BY id")
        link_state.ensure_schema(self.conn)
        self.assertEqual(self.tuples("PRAGMA table_info(download_sources)")[:len(cols)],
                         cols, "every pre-existing column is declared exactly as before")
        again = self.tuples(
            "SELECT id, release_id, source_name, service, source_url, final_url,"
            " playback_type, is_temporary, status, is_resumable, http_status,"
            " file_size_bytes, mime_type, last_checked_at, expires_at, ttl_source"
            " FROM download_sources ORDER BY id")
        self.assertEqual(again, rows, "and no stored value moved")
        row = self.conn.execute("SELECT * FROM download_sources WHERE id = ?",
                                (link_id,)).fetchone()
        self.assertIsNone(row["checked_at"],
                          "a fresh column is NULL here, not a fabricated verdict")

    def test_a_second_migration_run_adds_nothing(self):
        """Spec verification 2, across both ensure calls."""
        first = link_state.ensure_schema(self.conn)
        self.assertTrue(first["columns"] and first["tables"])
        second = link_state.ensure_schema(self.conn)
        self.assertEqual(second, {"columns": [], "tables": []})
        self.assertEqual(link_state.ensure_projection_schema(self.conn),
                         {"columns": [], "skipped": True})

    def test_a_legacy_projection_is_offered_the_link_id_and_gains_it(self):
        """The other half of the migration: `cat_links.ledger_link_id`, which a
        catalog_full.db-era projection never had, so a verdict could not reach the row
        the API serves."""
        self.conn.execute("CREATE TABLE cat_links ("
                          " id INTEGER PRIMARY KEY, url TEXT, state TEXT DEFAULT 'active')")
        self.conn.commit()
        status = link_state.schema_status(self.conn)
        self.assertEqual(status["projection"], "no_link_id")
        self.assertTrue(link_state.schema_plan(self.conn)["projection_link_id"])
        added = link_state.ensure_projection_schema(self.conn)
        self.assertEqual(added["columns"], ["ledger_link_id"])
        self.assertFalse(added["skipped"])
        self.assertEqual(link_state.schema_status(self.conn)["projection"], "linked")

    def test_a_legacy_timestamp_row_is_still_not_re_probed_after_install(self):
        """Held deliberately, and pinned so the hold is a fact and not a rumour.

        Spec verification 4 wanted the opposite assertion — that once `checked_at`
        exists, a row carrying *only* a legacy `last_checked_at` stops counting as a
        swept verdict. That is true as a criticism (`_pending_where`'s legacy tolerance
        is a stopgap, not a verdict), but shipping it is a sweep-semantics change: every
        row the old health check ever touched becomes pending, which on the production
        ledger is a multi-million-request re-probe — a heavy read the Fleet Resource
        Guardrail freezes at load, and outside 'additive migration only'. What this
        change does instead is make the tolerance visible: `schema_status`'s
        `pending_evidence` names the columns the sweep judges by. Flipping the stopgap
        off is an owner/supervisor call, queued, not taken here."""
        link_state.ensure_schema(self.conn)
        a = self._seed_link("https://a.example.com/1.mkv")
        self._seed_link("https://b.example.com/2.mkv")
        plan = link_state.propagate(self.conn, scope="legacy", dry_run=True,
                                    only_unchecked=True, stale_after_seconds=None,
                                    resume=False)
        self.assertEqual(plan["rows_pending"], 2)
        self.conn.execute("UPDATE download_sources SET last_checked_at = ?,"
                          " http_status = 200 WHERE id = ?",
                          (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), a))
        self.conn.commit()
        after = link_state.propagate(self.conn, scope="legacy", dry_run=True,
                                     only_unchecked=True, stale_after_seconds=None,
                                     resume=False)
        self.assertEqual(after["rows_pending"], 1,
                         "a legacy-measured row is believed, and that belief is now reported")
        self.assertIn("last_checked_at",
                      link_state.schema_status(self.conn)["pending_evidence"])


class EvidenceSchemaCliTests(unittest.TestCase):
    """The migration is reachable as its own declared action, and asking about it is
    never a write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        shutil.copy(_template_db(), self.db_path)
        # Nothing in this class may reach the network: the migration is a DDL step.
        for name in ("probe", "probe_many"):
            patcher = unittest.mock.patch.object(
                link_health, name, side_effect=AssertionError("network use in a test"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def digest(self) -> str:
        return hashlib.md5(self.db_path.read_bytes()).hexdigest()

    def run_cli(self, argv) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = link_state.main(argv)
        return code, json.loads(out.getvalue())

    def test_schema_flag_needs_no_apply_and_writes_nothing(self):
        before = self.digest()
        code, payload = self.run_cli(["--db", str(self.db_path), "--schema"])
        self.assertEqual(code, 0)
        self.assertFalse(payload["schema"]["installed"])
        self.assertEqual(payload["would_add"]["ledger_columns"],
                         list(link_state.LEDGER_COLUMNS))
        self.assertEqual(payload["plan"], "read-only connection: nothing was written")
        self.assertEqual(self.digest(), before)

    def test_schema_flag_with_apply_still_writes_nothing(self):
        """Asking a question must not inherit consent from the `--apply` next to it."""
        before = self.digest()
        code, payload = self.run_cli(["--db", str(self.db_path), "--schema", "--apply"])
        self.assertEqual(code, 0)
        self.assertNotIn("added", payload, "--schema never runs the migration")
        self.assertTrue(payload["legacy_evidence_only"])
        self.assertEqual(self.digest(), before)

    def test_ensure_schema_without_apply_is_a_plan(self):
        before = self.digest()
        code, payload = self.run_cli(["--db", str(self.db_path), "--ensure-schema"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["would_add"]["cursor_tables"],
                         list(link_state.CURSOR_TABLES))
        self.assertEqual(self.digest(), before,
                         'a "dry run" of a migration must not migrate')

    def test_ensure_schema_with_apply_installs_and_probes_nothing(self):
        before = self.digest()
        code, payload = self.run_cli(["--db", str(self.db_path), "--ensure-schema",
                                      "--apply"])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(payload["added"]["ledger"]["columns"]),
                         sorted(link_state.LEDGER_COLUMNS))
        self.assertEqual(payload["added"]["ledger"]["tables"], list(link_state.CURSOR_TABLES))
        self.assertEqual(payload["added"]["projection"], {"columns": [], "skipped": True})
        self.assertTrue(payload["after"]["installed"])
        self.assertNotEqual(self.digest(), before, "the write happened where it was declared")
        conn = link_state.connect(self.db_path, read_only=True)
        try:
            self.assertEqual(link_state.status_summary(conn)["total"], 0)
        finally:
            conn.close()
        # A second declared run is a no-op, which is what makes it safe to re-run.
        again = self.run_cli(["--db", str(self.db_path), "--ensure-schema", "--apply"])
        self.assertEqual(again[1]["added"]["ledger"], {"columns": [], "tables": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
