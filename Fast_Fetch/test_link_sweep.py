#!/usr/bin/env python3
"""Tests for link_sweep.py — the bounded link-health sample.

Offline: a fake prober stands in for the network, temp DBs stand in for the
catalog, no production file is touched. The merge tests build a real
`catalog_v2` projection (the admin test's ingest pattern) because a hand-drawn
`cat_*` fixture would test `apply_evidence` against columns the projector
does not write.

    python3 -S Fast_Fetch/test_link_sweep.py
"""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import catalog_v2        # noqa: E402
import fast_fetch        # noqa: E402
import link_health       # noqa: E402
import link_sweep        # noqa: E402
import viewer            # noqa: E402


def _minimal_catalog(path, hosts):
    """A hand-built cat_links: `hosts` maps host -> link count. Plus one
    magnet: row and one empty-URL row, which the sample must not draw."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE cat_links (id INTEGER PRIMARY KEY, release_id INT,"
        " work_id INT, ledger_link_id INT, url TEXT, final_url TEXT,"
        " service TEXT, state TEXT DEFAULT 'unchecked',"
        " playability TEXT DEFAULT 'both', rank_score INT DEFAULT 0)")
    conn.execute("CREATE TABLE cat_projection_meta"
                 " (key TEXT PRIMARY KEY, value TEXT)")
    rows = []
    link_id = 0
    for host, count in hosts.items():
        for i in range(count):
            link_id += 1
            rows.append((link_id, 1, 1, 1000 + link_id,
                         f"https://{host}/p{i}", "", "svc",
                         "unchecked", "both", 100 - link_id))
    link_id += 1
    rows.append((link_id, 1, 1, 1000 + link_id, "magnet:?xt=urn:btih:abc",
                 "", "svc", "unchecked", "both", 0))
    link_id += 1
    rows.append((link_id, 1, 1, 1000 + link_id, "", "", "svc",
                 "unchecked", "both", 0))
    conn.executemany("INSERT INTO cat_links VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def _real_catalog(path):
    """A real ledger -> real projection, two titles, one link each.

    The caller keeps `fast_fetch.DB_PATH` (and `viewer.DB_PATH`) patched at
    `path` for the whole test: `save_scraped_data` reads the module global,
    and a patch that lapses mid-fixture writes to the wrong database.
    """
    fast_fetch.init_db(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    for title, slug in (("Alpha Film", "alpha-film"), ("Beta Film", "beta-film")):
        data = {
            "url": f"https://cdn.example/movie/{slug}/",
            "slug": slug, "title": f"{title} (2024)", "clean_title": title,
            "year": 2024, "content_type": "movie",
            "poster_url": "https://cdn/poster.jpg", "genres": '["Action"]',
            "synopsis": f"{title} synopsis", "is_18_plus": 0,
            "source_site": "cdn.example", "industry": "Bollywood",
            "country": "India", "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
            "releases": [{"release_title": f"{title} 1080p",
                          "quality": "1080p", "codec": "x264",
                          "size": "1.5GB", "languages": '["Hindi"]',
                          "season": "", "episode": "", "intermediate_url": "",
                          "origin_url": "", "source_site": "cdn.example",
                          "sources": [{"source_url":
                                       f"https://cdn.example/{slug}.mp4",
                                       "quality": "1080p",
                                       "status": "active"}]}],
        }
        fast_fetch.save_scraped_data(data, enrich_metadata=False,
                                     ensure_db=False)
    conn.commit()
    catalog_v2.project(conn, rev=1, verbose=False)
    conn.commit()
    return conn


def _result(url, **over):
    fields = {"url": url, "ok": False, "http_status": 0, "protocol": "unusable",
              "content_type": "", "size_bytes": 0, "accepts_ranges": False,
              "resumable": False, "cors_open": False, "latency_ms": 0,
              "download_speed_mbps": 0.0, "streamable": False,
              "downloadable": False, "redirects_to": "", "error": "",
              "checked_at": 1_700_000_000.0}
    fields.update(over)
    return link_health.ProbeResult(**fields)


class ArithmeticTests(unittest.TestCase):
    def test_1000_links_buys_plus_minus_3_percent(self):
        self.assertAlmostEqual(link_sweep.margin(0.5, 1000), 0.031, places=3)

    def test_sample_size_scales_as_the_square(self):
        self.assertEqual(link_sweep.sample_size_for(0.05), 385)
        self.assertEqual(link_sweep.sample_size_for(0.02), 2401)

    def test_a_sample_of_zero_raises(self):
        with self.assertRaises(ValueError):
            link_sweep.margin(0.5, 0)

    def test_the_sample_is_orders_of_magnitude_cheaper_than_the_full_sweep(self):
        self.assertLess(link_sweep.estimate_hours(1000), 1.0)
        self.assertGreater(link_sweep.estimate_hours(3_705_474), 72.0)


class StrataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = _minimal_catalog(Path(self.tmp.name) / "cat.db",
                                    {"a.example": 6, "b.example": 3,
                                     "c.example": 1})
        self.addCleanup(self.cat.close)

    def test_strata_counts_hosts_and_excludes_the_unprobeable(self):
        info = link_sweep.strata(self.cat)
        self.assertEqual(info["population"], 10)
        self.assertEqual(info["total_links"], 12)
        self.assertEqual(info["unprobeable"], 2)
        self.assertEqual(info["by_host"],
                         {"a.example": 6, "b.example": 3, "c.example": 1})

    def test_allocation_is_proportional_and_sums_to_the_limit(self):
        alloc = link_sweep.allocate({"a.example": 6, "b.example": 3,
                                     "c.example": 1}, 5)
        self.assertEqual(sum(alloc.values()), 5)
        self.assertEqual(alloc, {"a.example": 3, "b.example": 1,
                                 "c.example": 1})

    def test_allocation_never_exceeds_the_population(self):
        self.assertEqual(sum(link_sweep.allocate({"a.example": 2}, 100).values()),
                         2)

    def test_a_host_whose_share_rounds_to_zero_gets_nothing(self):
        alloc = link_sweep.allocate({"big.example": 999, "tiny.example": 1}, 10)
        self.assertNotIn("tiny.example", alloc)
        self.assertEqual(sum(alloc.values()), 10)

    def test_draw_is_deterministic_for_a_seed_and_respects_allocation(self):
        sample1, plan1 = link_sweep.draw_sample(self.cat, 5, seed=7)
        sample2, _ = link_sweep.draw_sample(self.cat, 5, seed=7)
        self.assertEqual([r["link_id"] for r in sample1],
                         [r["link_id"] for r in sample2])
        hosts = {}
        for row in sample1:
            hosts[row["host"]] = hosts.get(row["host"], 0) + 1
        self.assertEqual(hosts, plan1["allocation"])
        self.assertNotIn("magnet:", "".join(r["url"] for r in sample1))


class VerdictTests(unittest.TestCase):
    def test_verdict_mapping(self):
        cases = [
            (_result("https://a.example/1", ok=True), "alive"),
            (_result("https://a.example/2", http_status=404,
                     error="http_404"), "dead"),
            (_result("https://a.example/3", http_status=401,
                     error="http_401"), "expired"),
            (_result("https://a.example/4", http_status=429,
                     error="http_429"), "expired"),
            (_result("https://a.example/5", error="blocklisted"), "blocked"),
            (_result("https://a.example/6", error="invalid_url"), "no_verdict"),
            (_result("https://a.example/7", error="timeout"), "dead"),
        ]
        for result, want in cases:
            self.assertEqual(link_sweep._verdict_of(result), want, result)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = _minimal_catalog(Path(self.tmp.name) / "cat.db",
                                    {"a.example": 6, "b.example": 4})
        self.addCleanup(self.cat.close)
        self.staging = sqlite3.connect(str(Path(self.tmp.name) / "sweep.db"))
        self.staging.row_factory = sqlite3.Row
        self.addCleanup(self.staging.close)
        self.probed = []
        # The guards are real code, tested in their own cases below; every
        # other run test needs a box above the floors, and this VM is not one.
        for patcher in (
                mock.patch.object(link_sweep, "_read_mem",
                                  return_value=(8192.0, 4096.0)),
                mock.patch.object(link_sweep, "_load_average",
                                  return_value=0.5)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _prober_for(self, mapping):
        def prober(items):
            out = []
            for item in items:
                self.probed.append(item["url"])
                out.append(mapping(item["url"]))
            return out
        return prober

    def test_mixed_outcomes_are_counted_and_stored(self):
        def mapping(url):
            if url.endswith("/p0"):
                return _result(url, ok=True, protocol="progressive",
                               http_status=200)
            if url.endswith("/p1"):
                return _result(url, http_status=404, error="http_404")
            if url.endswith("/p2"):
                return _result(url, http_status=403, error="http_403")
            if url.endswith("/p3"):
                return _result(url, error="blocklisted")
            return _result(url, error="invalid_url")
        summary = link_sweep.run_sample(
            self.cat, self.staging, limit=10,
            prober=self._prober_for(mapping))
        self.assertEqual(summary["state"], "complete")
        self.assertEqual(summary["links_done"], 10)
        self.assertEqual(summary["alive"], 2)
        self.assertEqual(summary["dead"], 2)
        self.assertEqual(summary["expired"], 2)
        self.assertEqual(summary["blocked"], 2)
        self.assertEqual(summary["no_verdict"], 2)
        stored = link_sweep.status(self.staging)
        self.assertTrue(stored["available"])
        self.assertEqual(stored["evidenced"], 10)
        self.assertEqual(stored["alive_share"], 0.3333)
        self.assertIsNone(stored["margin_95"],
                          "6 measured links support no percentage")

    def test_a_429_parks_the_host_for_the_rest_of_the_run(self):
        seen = []

        def mapping(url):
            seen.append(url)
            if "a.example/p0" in url:
                return _result(url, http_status=429, error="http_429")
            return _result(url, ok=True, http_status=200)

        with mock.patch.object(link_sweep, "BATCH_SIZE", 3):
            summary = link_sweep.run_sample(
                self.cat, self.staging, limit=10, seed=1,
                prober=self._prober_for(mapping))
        # The park bites after the batch that discovered the 429: the three
        # a.example links in that first batch were already knocked on
        # together, but no later a.example link is.
        a_probed = [u for u in seen if "a.example" in u]
        self.assertEqual(a_probed, ["https://a.example/p0",
                                    "https://a.example/p1",
                                    "https://a.example/p2"])
        self.assertEqual(summary["host_parked"], 3)
        self.assertEqual(summary["expired"], 1)

    def test_a_second_run_resumes_and_probes_nothing_new(self):
        mapping = lambda url: _result(url, ok=True, http_status=200)
        first = link_sweep.run_sample(self.cat, self.staging, limit=6,
                                      prober=self._prober_for(mapping))
        calls = []
        second = link_sweep.run_sample(
            self.cat, self.staging, limit=6,
            prober=lambda items: calls.append(len(items)) or [])
        self.assertEqual(second["links_done"], first["links_done"])
        self.assertEqual(calls, [])

    def test_high_load_parks_the_run_instead_of_probing(self):
        slept = []
        with mock.patch.object(link_sweep, "_load_average",
                               return_value=9.0), \
             mock.patch.object(link_sweep, "LOAD_MAX_WAIT_SECONDS", 0):
            summary = link_sweep.run_sample(
                self.cat, self.staging, limit=4,
                prober=lambda items: (_ for _ in ()).throw(
                    AssertionError("must not probe under load")),
                sleep=slept.append)
        self.assertEqual(summary["state"], "paused_load")
        self.assertEqual(summary["links_done"], 0)
        self.assertEqual(len(slept), 1)

    def test_low_memory_parks_the_run_instead_of_probing(self):
        with mock.patch.object(link_sweep, "_read_mem",
                               return_value=(100.0, 100.0)):
            summary = link_sweep.run_sample(
                self.cat, self.staging, limit=4,
                prober=lambda items: (_ for _ in ()).throw(
                    AssertionError("must not probe under the memory floor")))
        self.assertEqual(summary["state"], "paused_memory")
        self.assertEqual(summary["links_done"], 0)

    def test_a_sample_over_the_run_cap_is_refused(self):
        with mock.patch.object(link_sweep, "MAX_LINKS_PER_RUN", 5):
            with self.assertRaises(ValueError):
                link_sweep.run_sample(self.cat, self.staging, limit=10,
                                      prober=lambda items: [])


class StatusTests(unittest.TestCase):
    def test_status_on_an_empty_staging_file_is_honest(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with closing(sqlite3.connect(str(Path(tmp.name) / "s.db"))) as staging:
            staging.row_factory = sqlite3.Row
            out = link_sweep.status(staging)
        self.assertFalse(out["available"])
        self.assertEqual(out["sampled"], 0)
        self.assertIsNone(out["alive_share"])
        self.assertIsNone(out["margin_95"])


class MergeTests(unittest.TestCase):
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
        self.cat = _real_catalog(self.db_path)
        self.addCleanup(self.cat.close)
        self.staging = sqlite3.connect(str(Path(self.tmp.name) / "sweep.db"))
        self.staging.row_factory = sqlite3.Row
        self.addCleanup(self.staging.close)

    def test_merge_moves_verdicts_and_stamps_the_run(self):
        links = {row["url"]: row["id"] for row in self.cat.execute(
            "SELECT id, url FROM cat_links")}
        self.assertEqual(len(links), 2)

        def mapping(url):
            if "alpha-film" in url:
                return _result(url, ok=True, protocol="progressive",
                               http_status=200)
            return _result(url, http_status=404, error="http_404")
        run = link_sweep.run_sample(self.cat, self.staging, limit=10,
                                    prober=lambda items: [
                                        mapping(i["url"]) for i in items])
        self.assertEqual(run["alive"], 1)
        self.assertEqual(run["dead"], 1)
        outcome = link_sweep.merge(self.cat, self.staging)
        self.assertEqual(outcome["merged_links"], 2)
        states = {row["url"]: row["state"] for row in self.cat.execute(
            "SELECT url, state FROM cat_links")}
        self.assertEqual(states["https://cdn.example/alpha-film.mp4"], "active")
        self.assertEqual(states["https://cdn.example/beta-film.mp4"], "dead")
        row = self.cat.execute(
            "SELECT value FROM cat_projection_meta"
            " WHERE key = 'link_sweep_last_run'").fetchone()
        self.assertIsNotNone(row)
        stamp = json.loads(row[0])
        self.assertEqual(stamp["alive"], 1)
        self.assertEqual(stamp["dead"], 1)
        self.assertEqual(stamp["merged_links"], 2)
        journal = int(self.cat.execute(
            "SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0])
        self.assertEqual(journal, 2)
        again = link_sweep.merge(self.cat, self.staging)
        self.assertEqual(again["merged_links"], 2)
        journal2 = int(self.cat.execute(
            "SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0])
        self.assertEqual(journal2, journal,
                         "a replay appends no second journal row")
        states2 = {r["url"]: r["state"] for r in self.cat.execute(
            "SELECT url, state FROM cat_links")}
        self.assertEqual(states2, states)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat_path = Path(self.tmp.name) / "cat.db"
        self.cat = _minimal_catalog(self.cat_path, {"a.example": 4})
        self.addCleanup(self.cat.close)
        self.staging_path = Path(self.tmp.name) / "sweep.db"

    def test_plan_prints_the_cost_and_exits_zero(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = link_sweep.main(["plan", "--target", str(self.cat_path),
                                    "--limit", "4"])
        self.assertEqual(code, 0)
        self.assertIn("population (probeable projected links): 4", out.getvalue())
        self.assertIn("a.example: 4", out.getvalue())

    def test_status_without_a_run_is_honest(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = link_sweep.main(["status", "--staging",
                                    str(self.staging_path)])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out.getvalue())["available"])

    def test_plan_without_a_target_is_a_usage_error(self):
        with self.assertRaises(SystemExit):
            link_sweep.main(["plan"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
