"""test_single_flight.py — offline stdlib-thread proof of the LANE 2 gate.

Every behaviour the crown order names gets its own test, asserting the
UPSTREAM ATTEMPT COUNT (not just "didn't crash"). No network, no SQLite,
no ports — the injected clock makes windows exact.
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import single_flight as sf            # noqa: E402
from single_flight import SingleFlight, ok, fail, unsupported   # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self.t

    def advance(self, s):
        with self._lock:
            self.t += s


class CollapseTests(unittest.TestCase):
    def test_N_concurrent_same_id_exactly_one_upstream_attempt(self):
        g = SingleFlight(global_cap=64)
        release = threading.Event()
        started = threading.Semaphore(0)

        def slow_fn():
            started.release()
            release.wait(5)
            return ok("answer")

        results = []
        lock = threading.Lock()

        def caller():
            r = g.run("link-1", slow_fn)
            with lock:
                results.append(r)

        ts = [threading.Thread(target=caller) for _ in range(9)]
        for t in ts:
            t.start()
        started.acquire()                       # the one owner is inside fn
        time.sleep(0.05)                        # let waiters attach
        self.assertEqual(g.stats["attempts"], 1)
        release.set()
        for t in ts:
            t.join(5)
            self.assertFalse(t.is_alive(), "a waiter hung")
        self.assertEqual(g.stats["attempts"], 1)          # THE collapse assert
        self.assertEqual(len(results), 9)
        self.assertTrue(all(r.status == "ok" and r.value == "answer" for r in results))
        # waiter wake: every waiter got the in-flight result, none re-probed
        self.assertGreaterEqual(g.stats["collapses"], 1)
        self.assertEqual(g.stats["wait_timeouts"], 0)

    def test_distinct_ids_do_not_serialize(self):
        g = SingleFlight(global_cap=8)
        hold_a = threading.Event()
        a_in = threading.Event()

        def fn_a():
            a_in.set()
            hold_a.wait(5)
            return ok("A")

        ta = threading.Thread(target=lambda: g.run("id-A", fn_a))
        ta.start()
        a_in.wait(5)                             # A is in flight
        done_b = threading.Event()

        def fn_b():
            done_b.set()
            return ok("B")

        rb = g.run("id-B", fn_b)                 # must NOT wait behind A
        self.assertTrue(done_b.is_set(), "B never ran while A was in flight")
        self.assertEqual(rb.value, "B")
        self.assertEqual(g.stats["attempts"], 2)
        hold_a.set()
        ta.join(5)

    def test_stress_50_callers_x_20_ids_attempts_equal_ids(self):
        g = SingleFlight(global_cap=64)
        n_ids, n_threads = 20, 50
        results = []
        lock = threading.Lock()

        def fn(i):
            def _f():
                time.sleep(0.01)
                return ok(f"u{i}")
            return _f

        barrier = threading.Barrier(n_threads)

        def caller(j):
            barrier.wait(5)
            r = g.run(f"id-{j % n_ids}", fn(j % n_ids))
            with lock:
                results.append(r)

        ts = [threading.Thread(target=caller, args=(j,)) for j in range(n_threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
        self.assertEqual(len(results), n_threads)
        self.assertEqual(g.stats["attempts"], n_ids,
                         "upstream attempts must equal distinct ids, never more")
        self.assertTrue(all(r.status == "ok" for r in results))
        self.assertEqual(g.stats["busy"], 0)


class NegativeCacheTests(unittest.TestCase):
    def test_failure_cached_next_callers_make_zero_attempts(self):
        clk = FakeClock()
        g = SingleFlight(clock=clk)
        r1 = g.run("dead-1", lambda: fail("timeout"))
        self.assertEqual(r1.status, "fail")
        self.assertFalse(r1.cached)
        n = 0
        for _ in range(5):
            r = g.run("dead-1", lambda: fail("timeout"))
            n += 1 if r.status == "fail" and r.cached else 0
        self.assertEqual(n, 5)
        self.assertEqual(g.stats["attempts"], 1)          # 0 further upstream
        self.assertEqual(g.stats["negative_hits"], 5)

    def test_negative_entry_expires_and_reprobes(self):
        clk = FakeClock()
        g = SingleFlight(neg_ttl_base=10.0, clock=clk)
        g.run("k", lambda: fail("dns"))
        clk.advance(9.0)
        g.run("k", lambda: fail("dns"))
        self.assertEqual(g.stats["attempts"], 1)          # still inside window
        clk.advance(2.0)
        g.run("k", lambda: fail("dns"))
        self.assertEqual(g.stats["attempts"], 2)          # window passed: re-probe

    def test_unsupported_is_a_distinct_class_and_touches_no_fail_count(self):
        clk = FakeClock()
        g = SingleFlight(clock=clk)
        r = g.run("vidbolt-9", lambda: unsupported("no unpacker branch"))
        self.assertEqual(r.status, "unsupported")
        neg = g._neg["vidbolt-9"]
        self.assertEqual(neg[0], "unsupported")           # NOT merged into fail
        self.assertEqual(g.stats["fail_count_touched"], 0)  # circuit never moved
        r2 = g.run("vidbolt-9", lambda: fail("x"))
        self.assertTrue(r2.cached and r2.status == "unsupported")

    def test_success_clears_negative_entry_and_strikes(self):
        clk = FakeClock()
        g = SingleFlight(neg_ttl_base=10.0, clock=clk)
        g.run("k", lambda: fail("reset"))
        clk.advance(11)
        g.run("k", lambda: fail("reset"))
        self.assertEqual(g._strikes["k"], 2)
        clk.advance(22)
        r = g.run("k", lambda: ok("live"))
        self.assertEqual(r.status, "ok")
        self.assertNotIn("k", g._neg)
        self.assertNotIn("k", g._strikes)                 # recovery resets cooldown

    def test_adaptive_window_grows_then_recovers(self):
        clk = FakeClock()
        g = SingleFlight(neg_ttl_base=10.0, neg_ttl_max=40.0, clock=clk)
        g.run("k", lambda: fail("t"))
        self.assertAlmostEqual(g.window_for("k"), 10.0, places=3)
        clk.advance(11)
        g.run("k", lambda: fail("t"))
        self.assertAlmostEqual(g.window_for("k"), 20.0, places=3)
        clk.advance(21)
        g.run("k", lambda: fail("t"))
        self.assertAlmostEqual(g.window_for("k"), 40.0, places=3)   # capped
        clk.advance(41)
        g.run("k", lambda: ok("s"))
        clk.advance(31)                                    # result_ttl default 30
        g.run("k", lambda: fail("t"))
        self.assertAlmostEqual(g.window_for("k"), 10.0, places=3)   # strike 1 again


class SlotSafetyTests(unittest.TestCase):
    def test_raise_in_flight_releases_slot_and_wakes_waiters(self):
        clk = FakeClock()
        g = SingleFlight(global_cap=4, neg_ttl_base=10.0, clock=clk)
        boom = threading.Event()
        waiter_got = []

        def raiser():
            boom.wait(5)
            raise RuntimeError("crawler blew up")

        t_owner = threading.Thread(target=lambda: g.run("k", raiser))
        t_owner.start()
        time.sleep(0.02)
        t_w = threading.Thread(target=lambda: waiter_got.append(g.run("k", raiser)))
        t_w.start()
        time.sleep(0.02)
        boom.set()
        t_owner.join(5); t_w.join(5)
        self.assertFalse(t_owner.is_alive() or t_w.is_alive(), "slot stuck")
        self.assertEqual(len(waiter_got), 1)
        self.assertEqual(waiter_got[0].status, "fail")     # exception folded to fail
        # the fail opened an adaptive cooldown (by design, not a stuck slot):
        self.assertIn("k", g._neg)
        # slot released: after the window the SAME key is attempted again, ok
        clk.advance(11)
        r = g.run("k", lambda: ok("healed"))
        self.assertEqual(r.status, "ok")
        self.assertEqual(g.stats["attempts"], 2)
        self.assertEqual(g.stats["upstream_exceptions"], 1)   # one blow-up, one clean

    def test_waiter_timeout_is_bounded_and_makes_no_attempt(self):
        g = SingleFlight(wait_timeout=0.05, global_cap=4)
        hold = threading.Event()
        t = threading.Thread(target=lambda: g.run("k", lambda: hold.wait(5) or ok("x")))
        t.start()
        time.sleep(0.02)
        r = g.run("k", lambda: ok("y"))
        self.assertEqual(r.status, "inflight_timeout")
        self.assertEqual(g.stats["attempts"], 1)           # waiter never double-probed
        hold.set()
        t.join(5)

    def test_global_cap_busy_makes_zero_attempts(self):
        g = SingleFlight(global_cap=1, cap_wait=0.05)
        hold = threading.Event()
        in_a = threading.Event()

        def fn_a():
            in_a.set()
            hold.wait(5)
            return ok("A")

        t = threading.Thread(target=lambda: g.run("a", fn_a))
        t.start()
        in_a.wait(5)
        r = g.run("b", lambda: ok("B"))
        self.assertEqual(r.status, "busy")
        self.assertEqual(g.stats["attempts"], 1)           # cap-blocked = 0 upstream
        hold.set()
        t.join(5)


class BoundaryCompositionTests(unittest.TestCase):
    def test_adult_gate_runs_before_any_of_this(self):
        """Route-boundary composition: the caller's 18+ check short-circuits
        BEFORE gate.run — a flagged link never even reaches the flight tables,
        makes 0 upstream attempts, and poisons no cache."""
        g = SingleFlight()
        attempts = []

        def route(link_id, is_adult):
            if is_adult:
                return "404"
            return g.run(link_id, lambda: attempts.append(link_id) or ok("u"))

        self.assertEqual(route("flagged-159", True), "404")
        self.assertEqual(g.stats["attempts"], 0)
        self.assertEqual(attempts, [])
        self.assertEqual(g._inflight, {}) and self.assertEqual(g._neg, {})
        route("clean-1", False)
        self.assertEqual(g.stats["attempts"], 1)

    def test_module_needs_no_sqlite_table_at_all(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "single_flight.py")).read()
        self.assertGreater(len(src), 2000)               # non-empty: an emptied
        # module would make every assertNotIn below vacuously green (fleet notice)
        self.assertIn("def run(self, key, fn)", src)     # the API still exists
        self.assertNotIn("sqlite3", src)
        self.assertNotIn("import requests", src)
        g = SingleFlight()                                # no DB, no dir, works
        self.assertEqual(g.run("k", lambda: ok(1)).value, 1)

    def test_bounded_staleness_reprobe_is_once_not_per_request(self):
        clk = FakeClock()
        g = SingleFlight(result_ttl=5.0, global_cap=64, clock=clk)
        g.run("k", lambda: ok("v1"))
        self.assertEqual(g.stats["attempts"], 1)
        g.run("k", lambda: ok("v2"))                      # fresh: no upstream
        self.assertEqual(g.stats["attempts"], 1)
        clk.advance(6)                                    # stale: unbankable
        release = threading.Event()
        started = threading.Semaphore(0)

        def slow():
            started.release()
            release.wait(5)
            return ok("v3")

        outs = []
        lock = threading.Lock()

        def caller():
            r = g.run("k", slow)
            with lock:
                outs.append(r)

        ts = [threading.Thread(target=caller) for _ in range(8)]
        for t in ts:
            t.start()
        started.acquire()
        time.sleep(0.05)
        self.assertEqual(g.stats["attempts"], 2)          # exactly one re-probe
        release.set()
        for t in ts:
            t.join(5)
        self.assertEqual(g.stats["attempts"], 2)          # and still just one
        self.assertEqual(len(outs), 8)                    # non-empty guard: an
        # empty outs would make the all() below vacuously green (fleet notice)
        self.assertTrue(all(r.status == "ok" and r.value == "v3" for r in outs))
        # stale answer was NOT served: nothing in flight, banked value is v3;
        # a caller arriving after settle may legitimately hit the FRESH v3 entry
        self.assertEqual(g._entries["k"].value, "v3")
        self.assertEqual(g._inflight, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
