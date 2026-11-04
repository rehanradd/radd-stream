"""single_flight.py — stdlib-only gate for the heavy resolver path (LANE 2).

Crown orders ``qoder11_heavy_resolver`` + ``qoder11_single_flight``. To be wired
at the ROUTE boundary (``/api/v1/stream`` / ``/api/v1/download`` on a cache
miss) — never inside ``fast_fetch.py``, never as a background sweep.

Hard ceilings this module states and enforces (Emperor boundary 2):
  * The gate performs NO network I/O itself; it wraps the caller's resolve
    function. Collapse rule: at most **one concurrent upstream attempt per key**
    (link id). Every other caller for the same id waits for, or reuses, that
    one attempt's answer.
  * Whole-process ceiling: at most ``global_cap`` concurrent upstream attempts
    across ALL keys (default 4). A caller that cannot get a slot gets
    ``STATUS_BUSY`` after at most ``cap_wait`` seconds and makes ZERO outbound
    requests. It can never fan out more concurrent attempts than it collapses.
  * Per-host fairness is the caller's job (route boundary): this module knows
    ids, not hosts. No prefetching, no retries here, ever.

Relationship to ``resolved_cache`` (qoder12's ``73de18e`` semantics):
  * This negative cache is a DISTINCT outcome class: it never opens the cache
    DB, never reads or writes ``fail_count``, and needs no SQLite table at all
    (pure in-memory). An ``unsupported`` verdict short-circuits re-probing here
    and is NOT evidence against the resolver's circuit; the caller must keep
    that distinction when it records anything downstream.

Staleness law (mirrors the bank rule at the cache itself): a stale answer is
unbankable and UNSERVEABLE — an entry older than its window is dropped, and
exactly one caller re-probes (concurrent callers collapse onto that probe,
they do not each pay for it).

Adaptive window: a failure window is ``neg_ttl_base * 2**(strikes-1)`` capped
at ``neg_ttl_max``; any success clears the negative entry and resets strikes.
Waiters time out bounded (``wait_timeout``) as ``STATUS_TIMEOUT`` instead of
hanging; a raising in-flight attempt releases the slot in ``finally``.
"""
from __future__ import annotations

import threading
import time
from collections import namedtuple

STATUS_OK = "ok"
STATUS_FAIL = "fail"                    # affirmative endpoint verdict — full window
STATUS_UNSUPPORTED = "unsupported"
STATUS_TRANSIENT = "transient"          # OUR side failed / ambiguous — short window only
STATUS_BUSY = "busy"                    # cap or wait: 0 upstream attempts
STATUS_TIMEOUT = "inflight_timeout"     # waiter gave up: 0 upstream attempts

#: Verbatim mirror of qoder12's ``resolved_cache.TRANSPORT_CAUSES`` (49feb8e):
#: our timeout/DNS/TLS/reset/connection errors are a verdict about OUR night,
#: not about their link. Pinned by a literal test — if the two sets ever
#: diverge, that test goes red before the drift ships.
TRANSPORT_CAUSES = frozenset(("timeout", "dns", "tls", "conn_reset", "conn_error"))

Outcome = namedtuple("Outcome", "status value cached")


def ok(value):
    return Outcome(STATUS_OK, value, False)


def fail(reason):
    return Outcome(STATUS_FAIL, reason, False)


def transient(reason):
    return Outcome(STATUS_TRANSIENT, reason, False)


def unsupported(reason):
    return Outcome(STATUS_UNSUPPORTED, reason, False)


def classify_fail_cause(cause):
    """Map a resolver ``fail_cause`` to a gate outcome, qoder12's exact law:
    an int (an HTTP status we actually received) or an unknown endpoint word is
    an AFFIRMATIVE verdict about the endpoint (full adaptive window); a word in
    TRANSPORT_CAUSES is our-side transport (short window, no strikes); an
    absent cause is AMBIGUOUS — ambiguity accrues nothing long (49feb8e retired
    'absent = probed-dead')."""
    if cause is None:
        return transient("ambiguous:absent_cause")
    if isinstance(cause, int):
        return fail(f"http_{cause}")
    if str(cause) in TRANSPORT_CAUSES:
        return transient(str(cause))
    return fail(str(cause))              # new endpoint vocabulary stays verdict


def outcome_from_resolve(res: dict):
    """The route-boundary interface (viewer wiring, when it is authorized):
    map ONE ``resolve_live_source`` answer dict to a gate Outcome.

    Order of tests mirrors qoder12's ``note_failure_from_probe`` (49feb8e)
    exactly: unprobed is its own non-evidence class; success-with-url banks ok;
    every failure is CLASSIFIED BY CAUSE — transport/ambiguous gets the short
    window, an answered endpoint verdict the full adaptive one. This function
    imports nothing from ``resolved_cache`` (qoder12 owns that file tonight);
    the vocabulary is pinned by literal in the test suite."""
    if res.get("unprobed"):
        return unsupported(res.get("fail_cause") or "no_branch_matched")
    if res.get("success") and res.get("url"):
        return ok(res)
    return classify_fail_cause(res.get("fail_cause"))


class _Flight:
    __slots__ = ("event", "outcome")

    def __init__(self):
        self.event = threading.Event()
        self.outcome: Outcome | None = None


class _Entry:
    __slots__ = ("value", "expires")

    def __init__(self, value, expires):
        self.value = value
        self.expires = expires


class SingleFlight:
    """Single-flight + negative cache + adaptive window, stdlib threading only.

    ``run(key, fn)`` calls ``fn()`` at most once per in-flight window for a
    ``key``; ``fn`` must return an ``Outcome`` (``ok``/``fail``/``unsupported``)
    — anything else is recorded as ``fail("bad_result_shape")`` and counted as
    an upstream exception, never as a silent pass. Clock and tunables are
    injectable for offline tests.
    """

    def __init__(self, *, result_ttl: float = 30.0,
                 neg_ttl_base: float = 30.0, neg_ttl_max: float = 600.0,
                 transient_ttl: float = 2.0,
                 global_cap: int = 4, cap_wait: float = 2.0,
                 wait_timeout: float = 75.0, clock=time.monotonic):
        self._result_ttl = result_ttl
        self._neg_base = neg_ttl_base
        self._neg_max = neg_ttl_max
        self._trans_ttl = float(transient_ttl)
        self._wait_timeout = wait_timeout
        self._clock = clock
        self._lock = threading.Lock()          # guards tables ONLY, held µs
        self._inflight: dict[object, _Flight] = {}
        self._entries: dict[object, _Entry] = {}
        self._neg: dict[object, tuple] = {}    # key -> (status, expires, value)
        self._strikes: dict[object, int] = {}
        self._sem = threading.Semaphore(max(1, int(global_cap)))
        self._cap_wait = cap_wait
        self.stats = {"attempts": 0, "collapses": 0, "negative_hits": 0,
                      "entry_hits": 0, "busy": 0, "wait_timeouts": 0, "transient_windows": 0,
                      "upstream_exceptions": 0, "fail_count_touched": 0}

    # ── public API ───────────────────────────────────────────────────────────

    def run(self, key, fn) -> Outcome:
        now = self._clock()
        with self._lock:
            neg = self._neg.get(key)
            if neg is not None:
                if now < neg[2]:
                    self.stats["negative_hits"] += 1
                    return Outcome(neg[0], neg[1], True)
                del self._neg[key]
            ent = self._entries.get(key)
            if ent is not None:
                if now < ent.expires:           # fresh, bankable answer
                    self.stats["entry_hits"] += 1
                    return Outcome(STATUS_OK, ent.value, True)
                del self._entries[key]          # stale: unbankable, re-probe once
            flight = self._inflight.get(key)
            if flight is not None:
                waiter = True
            else:
                waiter = False
                if not self._sem.acquire(timeout=self._cap_wait):
                    self.stats["busy"] += 1
                    return Outcome(STATUS_BUSY, "global_cap", False)
                flight = _Flight()
                self._inflight[key] = flight

        if waiter:
            self.stats["collapses"] += 1
            if flight.event.wait(self._wait_timeout):
                return flight.outcome._replace(cached=True)
            self.stats["wait_timeouts"] += 1
            return Outcome(STATUS_TIMEOUT, "inflight_still_running", False)

        # owner: exactly one upstream attempt for this key
        try:
            self.stats["attempts"] += 1
            try:
                res = fn()
                if not isinstance(res, Outcome):
                    res = transient(f"bad_result_shape:{type(res).__name__}")
            except Exception as exc:            # noqa: BLE001 — never strand waiters
                # A raise tells us nothing about the endpoint — ambiguity
                # accrues a SHORT window only (qoder12 49feb8e law).
                self.stats["upstream_exceptions"] += 1
                res = transient(f"exception:{type(exc).__name__}")
            self._settle(key, res)
            return res
        finally:
            self._sem.release()
            with self._lock:
                self._inflight.pop(key, None)
            if flight.outcome is None:          # raise before settle: release slot
                flight.outcome = Outcome(STATUS_FAIL, "abandoned", False)
            flight.event.set()                  # wake every waiter, none re-probes

    def window_for(self, key):
        """Remaining negative window (s) — 0.0 if none. Introspection for tests."""
        with self._lock:
            neg = self._neg.get(key)
            return max(0.0, neg[2] - self._clock()) if neg else 0.0

    # ── internals ────────────────────────────────────────────────────────────

    def _settle(self, key, res: Outcome):
        now = self._clock()
        with self._lock:
            if res.status == STATUS_OK:
                self._entries[key] = _Entry(res.value, now + self._result_ttl)
                self._neg.pop(key, None)
                self._strikes.pop(key, None)    # recovery on success
                flight_outcome = res
            elif res.status == STATUS_TRANSIENT:
                existing = self._neg.get(key)
                if (existing is not None and existing[0] != STATUS_TRANSIENT
                        and now < existing[2]):
                    pass    # a blip cannot erase an affirmative verdict on file
                else:
                    self._neg[key] = (res.status, res.value, now + self._trans_ttl)
                    self.stats["transient_windows"] += 1
                flight_outcome = res
            else:
                strikes = self._strikes.get(key, 0) + 1
                self._strikes[key] = strikes
                ttl = min(self._neg_base * (2 ** (strikes - 1)), self._neg_max)
                self._neg[key] = (res.status, res.value, now + ttl)
                flight_outcome = res
            flight = self._inflight.get(key)
            if flight is not None and flight.outcome is None:
                flight.outcome = flight_outcome
