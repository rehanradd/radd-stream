"""Tests for maintenance.py (Session 123).

Everything runs with injected fakes — no network, no database, no threads
except the one `start_maintenance_thread` test, which only checks the thread
starts and is a daemon (it sleeps 60s before its first tick, so starting it
is cheap and it never does work inside the test).
"""
import os
import unittest
from unittest import mock

import maintenance


class EnabledTests(unittest.TestCase):
    def test_default_is_on(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(maintenance.enabled())

    def test_off_values_disable(self):
        for value in ("0", "off", "false", "no", "OFF", " False "):
            with mock.patch.dict(os.environ, {"RADD_MAINTENANCE": value}):
                self.assertFalse(maintenance.enabled(), value)

    def test_interval_default_is_six_hours(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(maintenance.interval_seconds(), 6 * 3600.0)

    def test_interval_override(self):
        with mock.patch.dict(os.environ, {"RADD_MAINTENANCE_INTERVAL_HOURS": "2"}):
            self.assertEqual(maintenance.interval_seconds(), 2 * 3600.0)

    def test_bad_interval_falls_back_to_the_default(self):
        with mock.patch.dict(os.environ, {"RADD_MAINTENANCE_INTERVAL_HOURS": "soon"}):
            self.assertEqual(maintenance.interval_seconds(), 6 * 3600.0)


class TickTests(unittest.TestCase):
    def _tick(self, **kwargs):
        calls = []

        def propagate(**kw):
            calls.append(("propagate", kw))
            return {"rows_checked": 400}

        def warm(**kw):
            calls.append(("warm", kw))
            return {"refreshed": 3}

        def heal(**kw):
            calls.append(("heal", kw))
            return {"healed": 1}

        with mock.patch.object(maintenance, "mem_available_mb", return_value=4096.0):
            summary = maintenance.tick_once(
                propagate=propagate, warm=warm, heal=heal, **kwargs)
        return summary, calls

    def test_runs_all_three_jobs_in_order_with_bounded_slices(self):
        summary, calls = self._tick()
        self.assertEqual([name for name, _ in calls],
                         ["propagate", "warm", "heal"])
        self.assertEqual(calls[0][1], {"max_batches": 2})
        self.assertEqual(calls[1][1], {"limit": 20})
        self.assertEqual(calls[2][1], {"limit": 50, "verbose": False})
        self.assertEqual(summary["propagate"], {"rows_checked": 400})
        self.assertEqual(summary["warm"], {"refreshed": 3})
        self.assertEqual(summary["heal"], {"healed": 1})
        self.assertFalse(summary["skipped_for_memory"])

    def test_a_failing_job_does_not_stop_the_tick(self):
        def boom(**kw):
            raise RuntimeError("no network")

        with mock.patch.object(maintenance, "mem_available_mb", return_value=4096.0):
            summary = maintenance.tick_once(
                propagate=boom,
                warm=lambda **kw: {"refreshed": 0},
                heal=lambda **kw: {"healed": 0})
        self.assertIn("error", summary["propagate"])
        self.assertEqual(summary["warm"], {"refreshed": 0})
        self.assertEqual(summary["heal"], {"healed": 0})

    def test_low_memory_skips_the_whole_tick(self):
        calls = []
        with mock.patch.object(maintenance, "mem_available_mb", return_value=800.0):
            summary = maintenance.tick_once(
                propagate=lambda **kw: calls.append("propagate") or {},
                warm=lambda **kw: calls.append("warm") or {},
                heal=lambda **kw: calls.append("heal") or {})
        self.assertTrue(summary["skipped_for_memory"])
        self.assertEqual(calls, [])

    def test_unknown_memory_does_not_block_the_tick(self):
        # A box that cannot report memory (non-Linux) runs the tick: the
        # floor is a guard for a reading we have, not a reason to stop
        # maintenance where we have none.
        with mock.patch.object(maintenance, "mem_available_mb", return_value=None):
            summary = maintenance.tick_once(
                propagate=lambda **kw: {"rows_checked": 0},
                warm=lambda **kw: {"refreshed": 0},
                heal=lambda **kw: {"healed": 0})
        self.assertFalse(summary["skipped_for_memory"])


    def test_a_warm_limit_of_200_reaches_the_warm_job(self):
        summary, calls = self._tick(warm_limit=200)
        self.assertEqual(calls[1], ("warm", {"limit": 200}))
        self.assertEqual(summary["warm"], {"refreshed": 3})


class FirstTickWarmTests(unittest.TestCase):
    def test_first_tick_warms_the_eager_set_not_the_top_up_slice(self):
        self.assertEqual(
            maintenance._first_tick_kwargs(200), {"warm_limit": 200})

    def test_first_tick_keeps_the_other_slices(self):
        self.assertEqual(
            maintenance._first_tick_kwargs(200, propagate_batches=1,
                                           heal_limit=5),
            {"warm_limit": 200, "propagate_batches": 1, "heal_limit": 5})

    def test_first_tick_overrides_an_explicit_warm_limit(self):
        self.assertEqual(
            maintenance._first_tick_kwargs(200, warm_limit=7)["warm_limit"],
            200)

    def test_the_eager_set_is_the_scale_plans_two_hundred(self):
        self.assertEqual(maintenance.FIRST_TICK_WARM_LIMIT, 200)


class StartThreadTests(unittest.TestCase):
    def test_disabled_returns_none_and_starts_nothing(self):
        with mock.patch.dict(os.environ, {"RADD_MAINTENANCE": "off"}):
            self.assertIsNone(maintenance.start_maintenance_thread())

    def test_enabled_starts_a_daemon_thread(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            thread = maintenance.start_maintenance_thread()
        self.assertIsNotNone(thread)
        self.assertTrue(thread.daemon)
        self.assertTrue(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
