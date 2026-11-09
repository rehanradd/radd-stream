"""Scheduled background maintenance inside `serve` (Session 123).

The wiring audit's finding was blunt: the healing daemon existed but was
invoked only via the CLI (`fast_fetch.py heal --daemon`), and
`link_state.propagate()` had no caller at all — so no verdict was ever earned
on the production catalog outside a manual run. This module is the scheduler
that closes that gap: `viewer.start_server` starts one daemon thread that
runs a bounded tick every few hours. Each tick does three small jobs, in
order, and never holds the database or the network long:

1. `link_state.propagate` — one bounded slice (a page or two, resumable via
   its `serve` cursor), so the projection keeps earning real `active` verdicts
   instead of waiting for a manual sweep. The slice is small on purpose: the
   catalog is millions of rows, and a tick that tried to eat it whole would
   hold the write lock and starve presses. The sweep is slow by design and
   the press-time probe is what keeps a played link honest.
2. `resolved_cache.warm` — the top-N eager pre-warm, so the links `/play`
   picks first are resolved before the first press of the day.
3. `fast_fetch.heal_expiring_sources` — re-resolve temporary links whose
   stored check is older than the interval, before their tokens die.

What a tick deliberately does NOT do: `ping_domains` stays CLI-only. A domain
migration rewrites site configuration in the database, and that is an
operator decision — a background thread inside the serving process must never
make it on its own. Healing, warming and verdicts only refresh link rows;
they never rewrite site config.

Safety, in the order it matters:

* The thread is a daemon and every tick is wrapped so a failure in one job
  logs and moves on, and a failure in the whole tick logs and waits for the
  next interval. Nothing here can kill `serve_forever`.
* The fleet guardrail is enforced before each tick: if `MemAvailable` is
  under 1500 MB the tick is skipped outright (the box is 1 vCPU; memory
  saturation is what kills it, not load).
* The first tick waits a minute after startup, so the server is listening and
  serving before any background work competes with it.
* It is env-gated: `RADD_MAINTENANCE=off` (also `0`, `false`, `no`) disables
  it entirely, and `RADD_MAINTENANCE_INTERVAL_HOURS` overrides the 6-hour
  default. The off-switch is the safety valve an operator reaches for
  without redeploying.
"""
from __future__ import annotations

import os
import threading
import time

#: How long after `serve` starts the first tick waits — the server must be
#: listening and serving before background work competes with it.
FIRST_TICK_DELAY_SECONDS = 60.0

#: Default cadence, in hours — the same 6 hours the CLI daemon used.
DEFAULT_INTERVAL_HOURS = 6.0

#: Bounded slices per tick. A propagate page is 200 rows (link_state's own
#: default); two pages is 400 verdicts a tick. The warmer resolves 20 links
#: a tick (each resolve is seconds of network work); the healer re-checks 50
#: expiring temporaries (its own default limit).
PROPAGATE_BATCHES_PER_TICK = 2
WARM_LIMIT_PER_TICK = 20
HEAL_LIMIT_PER_TICK = 50

#: The fleet guardrail's memory floor (AGENTS.md): stop heavy work at once
#: below this much available memory.
MEMORY_FLOOR_MB = 1500

#: The propagate cursor scope — one independent cursor, so this sweep never
#: fights another sweep's position.
PROPAGATE_SCOPE = "serve"


def enabled() -> bool:
    """Whether scheduled maintenance runs. Env-gated, default on."""
    return os.environ.get("RADD_MAINTENANCE", "").strip().lower() not in (
        "0", "off", "false", "no")


def interval_seconds() -> float:
    """The tick cadence in seconds, from the env override or the default."""
    try:
        hours = float(os.environ.get("RADD_MAINTENANCE_INTERVAL_HOURS", "") or 0)
    except ValueError:
        hours = 0.0
    if hours <= 0:
        hours = DEFAULT_INTERVAL_HOURS
    return hours * 3600.0


def mem_available_mb() -> float | None:
    """Available memory in MB, or None when it cannot be read (non-Linux)."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def tick_once(*, propagate_batches: int = PROPAGATE_BATCHES_PER_TICK,
              warm_limit: int = WARM_LIMIT_PER_TICK,
              heal_limit: int = HEAL_LIMIT_PER_TICK,
              propagate=None, warm=None, heal=None) -> dict:
    """Run one bounded maintenance tick and report what happened.

    The three callables are injectable so tests can run this with no network
    and no database; when omitted they are the real jobs, imported lazily so
    this module stays importable without the resolver. A job that raises is
    caught, recorded, and never stops the later jobs. Returns a summary with
    one entry per job (`skipped` when the memory floor refused the tick).
    """
    summary: dict = {"skipped_for_memory": False}
    available = mem_available_mb()
    if available is not None and available < MEMORY_FLOOR_MB:
        summary["skipped_for_memory"] = True
        summary["mem_available_mb"] = round(available, 1)
        print(f"[maintenance] tick skipped: MemAvailable {available:.0f} MB"
              f" < {MEMORY_FLOOR_MB} MB floor", flush=True)
        return summary
    if propagate is None:
        import link_state

        def propagate(**kwargs):
            import fast_fetch

            with fast_fetch.get_db() as conn:
                return link_state.propagate(
                    conn, scope=PROPAGATE_SCOPE, **kwargs)
    if warm is None:
        import resolved_cache

        def warm(**kwargs):
            import fast_fetch

            with fast_fetch.get_db() as conn:
                return resolved_cache.warm(conn, **kwargs)
    if heal is None:
        def heal(**kwargs):
            import fast_fetch

            return fast_fetch.heal_expiring_sources(**kwargs)
    jobs = (
        ("propagate", propagate, {"max_batches": int(propagate_batches)}),
        ("warm", warm, {"limit": int(warm_limit)}),
        ("heal", heal, {"limit": int(heal_limit), "verbose": False}),
    )
    for name, job, kwargs in jobs:
        try:
            summary[name] = job(**kwargs)
        except Exception as ex:      # noqa: BLE001 — a failed job must not end the tick
            summary[name] = {"error": str(ex)}
            print(f"[maintenance] {name} failed: {ex}", flush=True)
    print("[maintenance] tick done: %s" % {
        name: ("error" if isinstance(result, dict) and "error" in result else "ok")
        for name, result in summary.items() if name != "skipped_for_memory"
    }, flush=True)
    return summary


def _loop(*, interval: float, **tick_kwargs) -> None:
    time.sleep(FIRST_TICK_DELAY_SECONDS)
    while True:
        try:
            tick_once(**tick_kwargs)
        except Exception as ex:      # noqa: BLE001 — the loop must never die
            print(f"[maintenance] tick crashed: {ex}", flush=True)
        time.sleep(interval)


def start_maintenance_thread(**tick_kwargs) -> threading.Thread | None:
    """Start the daemon maintenance thread, or None when disabled.

    Called from `viewer.start_server` once the servers are listening. The
    thread is a daemon: it never blocks process exit, and it never raises
    into the serving loop.
    """
    if not enabled():
        print("[maintenance] disabled by RADD_MAINTENANCE", flush=True)
        return None
    interval = interval_seconds()
    thread = threading.Thread(
        target=_loop, kwargs={"interval": interval, **tick_kwargs},
        name="radd-maintenance", daemon=True)
    thread.start()
    print(f"[maintenance] scheduled: first tick in {FIRST_TICK_DELAY_SECONDS:.0f}s,"
          f" then every {interval / 3600.0:g}h", flush=True)
    return thread
