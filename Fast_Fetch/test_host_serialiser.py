#!/usr/bin/env python3
"""test_host_serialiser.py — the per-host gate in `link_health`, pinned offline.

`docs/LINK_HEALTH_SWEEP.md` §3 sets the politeness rule and §8 names the one code
change the sweep cannot start without: a serialiser in front of `probe_many()`,
because eight workers pointed at one file hoster are not eight polite clients —
they are a burst that gets the hoster to 429 us and the catalog to disappear.
That serialiser is `link_health.host_gate()`, wired into `_chain()` around each
hop of `_raw_request()`. This module is the evidence that it works, and it is the
regression test that notices if the fetch ever moves back outside the gate.

Rules it holds, and how each is proved without trusting a stopwatch:

* **the gate is really held around the fetch** — the fake fetch tries
  `acquire(blocking=False)` on its own host's lock from inside the request. If
  the gate were missing it would succeed, and that is recorded as a violation.
  This is deterministic: it needs no sleep, no race window, no loaded-box luck.
* two threads aimed at one host never have a request in flight together (an
  in-flight counter inside the fake, incremented under its own lock);
* two threads aimed at two hosts *do* — the gate is per host, not a global stop,
  proved with a `threading.Barrier` that only trips if both are inside at once.
  A serialised gate breaks the barrier instead, and the break shows up as an
  error from the thread;
* an exception releases the host. A wedge is worse than a slow sweep: one stuck
  lock would park a whole file hoster for the rest of the run;
* a link is never skipped for politeness — every input yields a result, so a
  crowded host shows up as waiting time, not as silence;
* the key folds `HTTP://Example.COM:443` and `http://example.com` into one host
  (one edge, one rate limit) while `:8080` stays its own listener;
* the gate wraps one request, not one redirect chain: hop A is released before
  hop B is knocked on;
* `spacing_s=0` — the private/test path `probe()` uses for loopback — never
  sleeps, so nothing here depends on how busy the box is.

Stdlib only. **No socket is opened anywhere in this file**: every fetch is a
monkeypatched `link_health._raw_request`, and `TestNoRealNetwork` additionally
replaces `http.client.HTTPConnection` with a tripwire. The fixture is this
module; `main()` prints its path so a reader can confirm where the fake lives.
Nothing here reads a database or touches `/home/ubuntu/radd-stream-data/`.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import link_health as lh  # noqa: E402

FIXTURE_PATH = os.path.abspath(__file__)


def _other_thread_can_take(gate) -> bool | None:
    """Ask a *different* thread whether `gate` is free. None means no answer."""
    taken: list[bool] = []

    def try_it():
        taken.append(gate.acquire(blocking=False))

    worker = threading.Thread(target=try_it, daemon=True)
    worker.start()
    worker.join(1.0)
    if not taken:
        return None
    if taken[0]:                      # it was free — give it straight back
        gate.release()
    return taken[0]


def _ok_exchange(method: str, sample_bytes: int) -> lh._Exchange:
    """A believable media response, assembled without a network."""
    headers = {"content-type": "video/mp4", "content-length": "1048576",
               "accept-ranges": "bytes"}
    exch = lh._Exchange(status=200, headers=headers, error="", header_ms=1)
    if method != "HEAD":
        exch.body = b"\0" * min(max(int(sample_bytes or 0), 0), 4096)
        exch.body_ms = 1
    return exch


class _Recorder:
    """Stand-in for `link_health._raw_request`: checks the gate from inside it."""

    def __init__(self, delay: float = 0.0, barrier=None, raise_once=None,
                 redirect_to=None, probe_lock: bool = False):
        self.delay = delay
        self.barrier = barrier
        self.raise_once = raise_once          # host_key that blows up first time
        self.redirect_to = redirect_to        # (from_url, to_url) -> answer 302
        self.probe_lock = probe_lock          # spawn the tripwire thread per call
        self.lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []
        self.intervals: list[tuple[str, float, float]] = []
        self.inflight: dict[str, int] = {}
        self.unheld: list[str] = []           # fetch ran with a gate others could take
        self.unheard: list[str] = []          # the tripwire thread never answered
        self.violations: list[tuple[str, int]] = []   # two requests, one host
        self.raised: set[str] = set()

    def __call__(self, url, method, headers, timeout, sample_bytes):
        key = lh.host_key(url)
        with self.lock:
            self.calls.append((key, method))
        if self.raise_once is not None and key == self.raise_once and key not in self.raised:
            self.raised.add(key)
            raise RuntimeError("simulated worker bug on the socket")
        if self.probe_lock:
            # Tripwire — the gate must already be held *by this probe*, so a
            # different thread must not be able to take it. (Asking the same
            # thread would prove nothing: the lock is re-entrant by design.)
            gate = lh._HOST_LOCKS.get(key)
            if gate is None:
                with self.lock:
                    self.unheld.append(key)
            else:
                answer = _other_thread_can_take(gate)
                if answer is None:
                    with self.lock:
                        self.unheard.append(key)
                elif answer:
                    with self.lock:
                        self.unheld.append(key)

        with self.lock:
            self.inflight[key] = self.inflight.get(key, 0) + 1
            if self.inflight[key] > 1:
                self.violations.append((key, self.inflight[key]))
        enter = time.monotonic()
        try:
            if self.barrier is not None:
                self.barrier.wait(timeout=2.0)
            if self.delay:
                time.sleep(self.delay)
            if self.redirect_to and url == self.redirect_to[0]:
                exch = lh._Exchange(status=302, headers={}, error="", header_ms=1)
                exch.location = self.redirect_to[1]
                return exch
            return _ok_exchange(method, sample_bytes)
        finally:
            with self.lock:
                self.intervals.append((key, enter, time.monotonic()))
                self.inflight[key] -= 1

    def keys(self) -> list[str]:
        with self.lock:
            return [k for k, _m in self.calls]

    def _spans(self, key) -> list[tuple]:
        with self.lock:
            return sorted([s for s in self.intervals if s[0] == key])

    def overlapping(self, keys) -> list[tuple]:
        """Interval pairs from the *same* key that share wall-clock time."""
        bad = []
        for key in keys:
            spans = self._spans(key)
            for prev, cur in zip(spans, spans[1:]):
                if cur[1] < prev[2]:
                    bad.append((key, prev, cur))
        return bad

    def concurrent_with(self, key_a: str, key_b: str) -> list[tuple]:
        """Interval pairs from two *different* keys that overlapped in time."""
        hits = []
        for a in self._spans(key_a):
            for b in self._spans(key_b):
                if a[1] < b[2] and b[1] < a[2]:
                    hits.append((a, b))
        return hits


def _run_threads(body, n: int, timeout: float = 30.0):
    """Run `body(i)` in n threads; return (results, errors). Join with a deadline."""
    results: list = [None] * n
    errors: list = []
    guard = threading.Lock()

    def wrapper(i):
        try:
            results[i] = body(i)
        except Exception as exc:            # a thread that raises must not be silent
            with guard:
                errors.append(f"thread {i}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=wrapper, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    alive = [t for t in threads if t.is_alive()]
    if alive:
        errors.append(f"{len(alive)} thread(s) still alive after {timeout}s — a gate is wedged")
    return results, errors


class TestHostKey(unittest.TestCase):
    """The politeness unit is the edge a rate limit charges, not the URL."""

    def test_default_web_ports_fold_one_edge_into_one_key(self):
        self.assertEqual(lh.host_key("HTTP://Example.COM:443/x.mp4"),
                         lh.host_key("http://example.com"))
        self.assertEqual(lh.host_key("https://example.com/x.mp4"),
                         lh.host_key("http://example.com"))
        self.assertEqual(lh.host_key("http://example.com"), "example.com")

    def test_a_non_default_port_stays_its_own_listener(self):
        self.assertEqual(lh.host_key("http://example.com:8080/x"), "example.com:8080")
        self.assertNotEqual(lh.host_key("http://example.com:8080/x"), "example.com")

    def test_the_scheme_is_stripped_and_the_host_lowercased(self):
        self.assertEqual(lh.host_key("HTTPS://CDN.Example.COM:443/a"), "cdn.example.com")

    def test_ipv6_literals_keep_their_brackets(self):
        self.assertEqual(lh.host_key("http://[2606::1]:8443/x"), "[2606::1]:8443")
        self.assertEqual(lh.host_key("http://[::1]/x"), "[::1]")

    def test_credentials_are_not_part_of_the_key(self):
        # probe() refuses these before any socket; the key must still group them.
        self.assertEqual(lh.host_key("https://user:pass@Host.Example.Test/x.mp4"),
                         "host.example.test")

    def test_unparseable_and_hostless_urls_share_the_empty_key(self):
        # Gated under "" rather than slipping past: a skipped link is how a dead
        # catalog hides, even when the link is nonsense.
        for bad in ("", "not a url", "http://host:NotAPort/x.mp4", None, 42):
            self.assertIsInstance(lh.host_key(bad), str, bad)
        self.assertEqual(lh.host_key("http://host:NotAPort/x.mp4"), "")
        self.assertEqual(lh.host_key("not a url"), "")
        self.assertEqual(lh.host_key(None), "")

    def test_the_default_spacing_is_the_documented_politeness_floor(self):
        # docs/LINK_HEALTH_SWEEP.md §3: one request per host per second. If the
        # default drifts, the sweep's budget arithmetic no longer describes code.
        # (RADD_HOST_SPACING_S is an operator dial, so an override is not a drift.)
        if os.environ.get("RADD_HOST_SPACING_S"):
            self.skipTest("operator overrode RADD_HOST_SPACING_S; default not under test")
        self.assertEqual(lh.DEFAULT_HOST_SPACING_S, 1.0)
        self.assertGreaterEqual(lh.DEFAULT_HOST_JITTER_S, 0.0)


class TestGateHoldsOneHost(unittest.TestCase):
    """The real claim: with a pool, one host gets one request at a time."""

    def setUp(self):
        self.original = lh._raw_request

    def tearDown(self):
        lh._raw_request = self.original

    def test_the_fetch_always_runs_inside_its_host_gate(self):
        """Deterministic: a free gate while fetching means the gate is absent."""
        url = "http://127.0.0.1:9001/movie.mp4"
        rec = _Recorder(probe_lock=True)
        lh._raw_request = rec
        results, errors = _run_threads(
            lambda i: lh.probe(url, allow_private=True, timeout=2.0), 4)
        self.assertEqual(errors, [], errors)
        self.assertEqual(len(rec.calls), 8, rec.calls)     # HEAD + GET per probe
        self.assertEqual(rec.unheard, [], "the tripwire thread never answered")
        self.assertEqual(rec.unheld, [],
                         "_raw_request ran while its host lock was free")
        self.assertEqual(rec.violations, [],
                         "two requests to one host were in flight together")

    def test_four_threads_on_one_host_never_overlap_and_none_is_skipped(self):
        url = "http://127.0.0.1:9011/movie.mp4"
        rec = _Recorder(delay=0.002)
        lh._raw_request = rec
        results, errors = _run_threads(
            lambda i: lh.probe(url, allow_private=True, timeout=2.0), 4)
        self.assertEqual(errors, [], errors)
        # Every input probe produced a result. A crowded host must cost waiting
        # time, never a missing link — silence is how a dead catalog hides.
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r is not None and r.ok for r in results),
                        [getattr(r, "error", None) for r in results])
        self.assertEqual(rec.overlapping([lh.host_key(url)]), [],
                         "two requests to one host were in flight together")

    def test_two_hosts_are_not_a_global_stop_they_run_concurrently(self):
        bar = threading.Barrier(2)
        rec = _Recorder(delay=0.01, barrier=bar)
        lh._raw_request = rec
        urls = ["http://127.0.0.1:9021/movie.mp4", "http://127.0.0.1:9022/movie.mp4"]
        results, errors = _run_threads(
            lambda i: lh.probe(urls[i], allow_private=True, timeout=2.0), 2)
        # A BrokenBarrierError here means one thread waited while the other was
        # idle: the hosts serialised together, which is what this test exists to
        # catch if the gate ever becomes a single global lock.
        self.assertEqual(errors, [], errors)
        self.assertTrue(all(r.ok for r in results), [r.error for r in results])
        key_a, key_b = lh.host_key(urls[0]), lh.host_key(urls[1])
        self.assertNotEqual(key_a, key_b)
        self.assertGreater(len(rec.concurrent_with(key_a, key_b)), 0,
                           "requests to two different hosts never shared wall-clock time")
        self.assertEqual(rec.violations, [], "one host overlapped itself")

    def test_probe_many_returns_one_result_per_link_and_serialises_per_host(self):
        a = "http://127.0.0.1:9031/movie.mp4"
        b = "http://127.0.0.1:9032/movie.mp4"
        rec = _Recorder(delay=0.002, probe_lock=True)
        lh._raw_request = rec
        links = [{"url": (a if i % 2 == 0 else b), "allow_private": True,
                  "timeout": 2.0} for i in range(8)]
        results = lh.probe_many(links, workers=8, allow_private=True, timeout=2.0)
        self.assertEqual(len(results), 8, "probe_many dropped a link")
        self.assertTrue(all(r.ok for r in results), [r.error for r in results])
        self.assertEqual(rec.unheld, [])
        self.assertEqual(rec.violations, [])
        self.assertEqual(rec.overlapping([lh.host_key(a), lh.host_key(b)]), [])

    def test_an_exception_releases_the_host(self):
        url = "http://127.0.0.1:9041/movie.mp4"
        key = lh.host_key(url)
        rec = _Recorder(raise_once=key)
        lh._raw_request = rec
        with self.assertRaises(RuntimeError):
            lh.probe(url, allow_private=True, timeout=2.0)
        gate = lh._HOST_LOCKS[key]
        self.assertTrue(gate.acquire(timeout=1.0),
                        "the gate stayed held after the probe raised")
        gate.release()
        lh._raw_request = _Recorder()      # and the host is usable again
        res = lh.probe(url, allow_private=True, timeout=2.0)
        self.assertTrue(res.ok, res.error)

    def test_a_caller_that_raises_inside_the_gate_releases_it(self):
        url = "http://127.0.0.1:9051/movie.mp4"
        with self.assertRaises(ValueError):
            with lh.host_gate(url, spacing_s=0.0):
                raise ValueError("bug in the caller")
        gate = lh._HOST_LOCKS[lh.host_key(url)]
        self.assertTrue(gate.acquire(timeout=1.0))
        gate.release()

    def test_the_gate_is_reentrant_so_a_whole_probe_cannot_self_deadlock(self):
        url = "http://127.0.0.1:9061/movie.mp4"

        def nested():
            with lh.host_gate(url, spacing_s=0.0):
                with lh.host_gate(url, spacing_s=0.0):
                    return "both"

        results, errors = _run_threads(lambda i: nested(), 1)
        self.assertEqual(errors, [], errors)
        self.assertEqual(results[0], "both")

    def test_spacing_waits_between_two_requests_to_one_host(self):
        url = "http://127.0.0.1:9071/movie.mp4"
        t0 = time.monotonic()
        with lh.host_gate(url, spacing_s=0.0, jitter_s=0.0):
            pass
        with lh.host_gate(url, spacing_s=0.05, jitter_s=0.0):
            pass
        waited = time.monotonic() - t0
        self.assertGreaterEqual(waited, 0.03, "the spacing floor was not held")
        self.assertLess(waited, 0.6, f"spacing overslept: {waited:.3f}s")

    def test_zero_spacing_never_sleeps(self):
        url = "http://127.0.0.1:9081/movie.mp4"
        t0 = time.monotonic()
        for _ in range(20):
            with lh.host_gate(url, spacing_s=0.0, jitter_s=0.0):
                pass
        self.assertLess(time.monotonic() - t0, 0.05,
                        "the private/test path is paying a politeness wait")

    def test_the_gate_wraps_one_hop_not_the_whole_redirect_chain(self):
        a = "http://127.0.0.1:9091/start.mp4"
        b = "http://127.0.0.1:9092/real.mp4"
        rec = _Recorder(redirect_to=(a, b))
        lh._raw_request = rec
        exch, final, err = lh._chain(a, "HEAD", {}, 2.0, 0, 5, host_spacing_s=0.0)
        self.assertEqual(rec.keys(), [lh.host_key(a), lh.host_key(b)], rec.keys())
        self.assertEqual(final, b, "the chain must land on the redirect target")
        self.assertEqual(err, "")
        self.assertEqual(exch.status, 200)
        key_a, key_b = lh.host_key(a), lh.host_key(b)
        span_a = rec._spans(key_a)[0]
        span_b = rec._spans(key_b)[0]
        self.assertLessEqual(span_a[2], span_b[1],
                             "hop A was still held while hop B was requested")


class TestNoRealNetwork(unittest.TestCase):
    """This suite must be offline: pin the fake, prove no HTTP client is built."""

    def setUp(self):
        self.original = lh._raw_request
        self.original_conn = lh.http.client.HTTPConnection

        class _Boom:
            def __init__(self, *a, **k):
                raise AssertionError("a real socket was opened by an offline test")

        lh.http.client.HTTPConnection = _Boom
        lh._raw_request = _Recorder()

    def tearDown(self):
        lh._raw_request = self.original
        lh.http.client.HTTPConnection = self.original_conn

    def test_probe_never_reaches_the_http_client_here(self):
        res = lh.probe("http://127.0.0.1:9111/movie.mp4", allow_private=True,
                       timeout=2.0)
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.protocol, "progressive")


def main():
    print(f"fixture: {FIXTURE_PATH}")
    print("no network: link_health._raw_request is monkeypatched and "
          "http.client.HTTPConnection is a tripwire; no socket is opened")
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
