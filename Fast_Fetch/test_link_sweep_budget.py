#!/usr/bin/env python3
"""test_link_sweep_budget.py — the arithmetic behind docs/LINK_HEALTH_SWEEP.md, pinned.

Why this file exists: the sweep design's load-bearing statements are numbers ("a full
sweep is infeasible", "1,000 links buys ±3.1 %", "a host below 30 samples supports no
percentage"), and a number in a design doc is a claim, not evidence. Every constant here
is read out of the code that will do the work, so if `link_health.py` changes its timeout
or its sample size the budget maths moves with it and this test tells whoever made the
change. No network, no production file, no catalog read. ~1 s.
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import link_health  # noqa: E402
import link_state   # noqa: E402

# ── the workload, as the qoder4 master measured it tonight (docs/CAPACITY_MEASURED.md,
#    at 54662d2). Cited, not re-measured: recounting means a 26-second read on a box at
#    load 10, which is the exact thing the design refuses to do.
POPULATION_UNCHECKED = 3_456_460     # cat_projection_meta links_by_state["unchecked"]
POPULATION_SOURCES = 3_705_474       # /api/v1/stats "sources"

# ── the polite operating point, from the doc §3/§4 (a design choice, so it is named here
#    rather than buried in a formula)
HOSTS_IN_FLIGHT = 8                  # one worker per host; never two on one host
SPACING_S = 1.0                      # between requests to the same host
TYPICAL_OK_S = 0.6                   # RTT + TLS + server, a live hoster
DEAD_TAIL_FRACTION = 0.10            # links that burn the full connect timeout


def margin(p: float, n: int, z: float = 1.96) -> float:
    """95 % normal-approximation half-width. `n = 0` is undefined, not zero."""
    if n <= 0:
        raise ValueError("a sample of zero supports no claim")
    return z * math.sqrt(max(p, 0.0) * (1.0 - max(p, 0.0)) / n)


def sample_size_for(margin_wanted: float, p: float = 0.5) -> int:
    return int(math.ceil((1.96 ** 2) * p * (1.0 - p) / (margin_wanted ** 2)))


def sweep_hours(n_links: int, workers: int = HOSTS_IN_FLIGHT,
                t_ok: float = TYPICAL_OK_S, dead_fraction: float = DEAD_TAIL_FRACTION,
                t_dead: float = float(link_health.DEFAULT_TIMEOUT),
                spacing: float = SPACING_S) -> float:
    """Wall hours for `n_links`, at the polite ceiling.

    Two ceilings are computed and the *larger* is returned, because they are independent
    limits and a design that used the smaller one would be wrong about which one binds:
    (a) thread throughput — `workers` links per `t_ok`-ish second, with the dead tail
    costing `t_dead` instead; (b) per-host politeness — `workers` hosts at `spacing`
    seconds apart, which no amount of threading can beat.
    """
    if n_links <= 0:
        return 0.0
    live = n_links * (1.0 - dead_fraction)
    dead = n_links * dead_fraction
    thread_s = (live * t_ok + dead * t_dead) / max(1, workers)
    politeness_s = n_links * spacing / max(1, workers)
    return max(thread_s, politeness_s) / 3600.0


def per_host_claim(hosts: dict, wanted_margin: float = 0.05,
                   min_per_host: int = 30) -> dict:
    """Which hosts may be named. A host with too few samples is refused, not warned.

    `hosts` maps a host to its sampled link count. Below `min_per_host` the interval is
    wider than the number it brackets, so writing a percentage there would be decoration.
    """
    n = sample_size_for(wanted_margin)
    out = {}
    for host, count in hosts.items():
        if count < min_per_host:
            out[host] = None                       # no claim, at any margin
        elif count < n:
            out[host] = margin(0.5, count)          # a wider, honest margin
        else:
            out[host] = wanted_margin
    return out


class TestConstantsComeFromCode(unittest.TestCase):
    def test_the_budget_is_built_on_the_codes_own_constants_not_on_prose(self):
        """If someone changes the timeout, the sweep's cost changes and this must fail."""
        self.assertEqual(float(link_health.DEFAULT_TIMEOUT), 8.0)
        self.assertEqual(int(link_health.DEFAULT_SAMPLE_BYTES), 524_288)
        self.assertEqual(int(link_health.DEFAULT_MAX_REDIRECTS), 5)
        self.assertEqual(int(link_health.DEFAULT_EWMA_WEIGHT * 10), 4)

    def test_a_probe_reads_at_most_one_sample_and_says_resumable_from_headers(self):
        """No branch of `probe()` downloads the media, and `resumable` is a header verdict.

        Asserted against the source text because the behaviour is the whole cost model:
        a probe that read a whole file would make §1's arithmetic meaningless.
        """
        src = inspect.getsource(link_health)
        self.assertIn("sample_bytes", src)
        self.assertIn('Range"] = f"bytes=0-', src.replace(" ", " "))
        self.assertIn("Accept-Ranges", src)
        self.assertNotIn("read()", src.replace("resp.read(sample_bytes)", "")
                         .replace("read(sample_bytes)", ""),
                         "a probe that reads an unbounded body must re-price the sweep")


class TestRequestsPerLink(unittest.TestCase):
    def test_the_good_case_is_one_head_and_the_worst_case_is_bounded_not_open_ended(self):
        """1 HEAD; up to 1 + MAX_REDIRECTS per phase; 2 phases ⇒ at most 12 requests."""
        hops = 1 + int(link_health.DEFAULT_MAX_REDIRECTS)
        self.assertEqual(hops, 6)
        self.assertLessEqual(2 * hops, 12)
        self.assertLessEqual(2 * hops * int(link_health.DEFAULT_SAMPLE_BYTES),
                             10 * 1024 * 1024,
                             "even the worst case reads under 10 MiB per link")

    def test_a_dead_link_costs_about_thirteen_times_a_live_one(self):
        """The reason the sample must be taken at a bounded time and never in a request path."""
        ratio = float(link_health.DEFAULT_TIMEOUT) / TYPICAL_OK_S
        self.assertGreater(ratio, 12)
        self.assertLess(ratio, 14)


class TestFullSweepInfeasible(unittest.TestCase):
    def test_the_full_population_would_take_days_of_the_only_core(self):
        """§1's conclusion, as arithmetic: not slow — infeasible."""
        hours = sweep_hours(POPULATION_SOURCES)
        self.assertGreater(hours, 72, "if this ever reads as feasible, re-check politeness")
        self.assertLess(hours, 24 * 14, "a two-week estimate means a formula bug")

    def test_the_dead_tail_alone_is_more_than_a_work_week(self):
        dead = POPULATION_SOURCES * DEAD_TAIL_FRACTION
        tail_hours = dead * float(link_health.DEFAULT_TIMEOUT) / HOSTS_IN_FLIGHT / 3600.0
        self.assertGreater(tail_hours, 24 * 4 - 2, "10 % of 3.7 M at 8 s is ~4.3 days")
        self.assertLess(tail_hours, 24 * 5)

    def test_politeness_binds_before_threads_do_at_this_operating_point(self):
        """8 threads cannot outrun 1 request/second/host: the ceiling is per-host."""
        live_only = (POPULATION_SOURCES * TYPICAL_OK_S) / HOSTS_IN_FLIGHT / 3600.0
        polite = POPULATION_SOURCES * SPACING_S / HOSTS_IN_FLIGHT / 3600.0
        # With live links only, politeness binds: 69 h of threads vs 128.6 h of spacing.
        self.assertGreater(polite / live_only, 1.5,
                           "the doc's 'threads are not the limit' claim holds only while hosts "
                           "answer; if this fails, the polite operating point has changed")
        # With the dead tail priced in, threads bind: 172 h vs 128.6 h. Both ceilings are real,
        # which is why sweep_hours() returns the max and not one of them.
        self.assertGreater(sweep_hours(POPULATION_SOURCES), polite,
                           "the tail must push the thread-bound term past politeness")


class TestSampleSupportsAClaim(unittest.TestCase):
    def test_1000_links_buys_plus_minus_3_percent_and_nothing_tighter(self):
        self.assertAlmostEqual(margin(0.5, 1000), 0.031, places=3)
        self.assertGreater(margin(0.5, 384), 0.049)
        self.assertLess(margin(0.5, 384), 0.051)

    def test_the_size_needed_scales_as_the_square_of_the_tightening(self):
        """±5 % is 384; ±2 % is 2,401 — the same 6.25× that the formula says, not a guess."""
        n5, n2 = sample_size_for(0.05), sample_size_for(0.02)
        self.assertEqual(n5, 385)
        self.assertEqual(n2, 2401)
        self.assertAlmostEqual(n2 / n5, (0.05 / 0.02) ** 2, delta=0.05)

    def test_per_host_tables_cost_384_each_and_that_is_the_real_bill(self):
        hours_20_hosts = sweep_hours(20 * 384)
        self.assertGreater(hours_20_hosts, 0.2)
        self.assertLess(hours_20_hosts, 0.7, "20 hosts x 384 is ~22 minutes, not days")
        self.assertGreater(sweep_hours(POPULATION_SOURCES) / hours_20_hosts, 300.0,
                           "the sample must be orders of magnitude cheaper than the sweep — "
                           "that ratio is the entire argument for sampling")

    def test_a_host_with_fewer_than_30_samples_is_refused_not_rounded(self):
        out = per_host_claim({"good.example": 400, "thin.example": 120,
                              "useless.example": 12})
        self.assertEqual(out["good.example"], 0.05)
        self.assertGreater(out["thin.example"], 0.05)
        self.assertIsNone(out["useless.example"])

    def test_a_sample_of_zero_raises_instead_of_reporting_zero_error(self):
        with self.assertRaises(ValueError):
            margin(0.5, 0)


class TestVerdictVocabulary(unittest.TestCase):
    def test_the_sweeps_own_states_are_the_closed_set_the_projection_accepts(self):
        self.assertEqual(sorted(link_state.LEDGER_STATUSES),
                         ["active", "dead", "expired", "unverified"])
        self.assertEqual(link_state.PROJECTED_UNCHECKED, "unchecked")

    def test_no_verdict_is_not_dead_and_a_measured_404_is(self):
        """"We could not look" and "the file is gone" may not share a bucket."""
        self.assertEqual(link_health.verdict_state(False, error="blocklisted"), "")
        self.assertEqual(link_state.classify({"error": "invalid_url"}),
                         link_state.STATUS_UNVERIFIED)
        self.assertEqual(link_health.verdict_state(False, error="http_404",
                                                   http_status=404), "dead")
        self.assertEqual(link_state.classify({"ok": False, "http_status": 429}),
                         link_state.STATUS_EXPIRED)

    def test_unknown_is_counted_as_not_alive_by_the_projection_rule(self):
        """The 8,543 `unknown` rows are the resolver's no-verdicts, not deaths.

        Pinned because a future summary that folds `unknown` into `active` would raise
        `active_sources` without anybody knocking on a single extra door.
        """
        import catalog_v2
        src = inspect.getsource(catalog_v2)
        self.assertIn("state IN ('unknown', 'unchecked') THEN 0", src)
        self.assertIn("unchecked|active|dead|expired|unknown", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
