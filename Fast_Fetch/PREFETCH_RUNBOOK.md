# Prefetch runbook — Gap A7

The phase-1 resolved cache (`Fast_Fetch/resolved_cache.py`) answers stream
requests from `resolved_cache` — but only the request path ever wrote to it.
The prefetch worker (`prefetch_worker.py`) existed in main and never ran: its
default load ceiling (2.0) parked it permanently while the box idled at load
6–8 under the five qoder/agy agent lanes. The live table proves it — 1 JIT
row, 0 pool rows (measured 2026-11-11).

This is the run mode that fixes it: **a systemd timer + oneshot service**,
the same scheduling mechanism the box already uses (the daily 03:40
Hugging Face backup timer is active; cron is not installed here).

## What runs, and when

- **Timer** `radd-prefetch.timer` — a `--once` sweep every 6 hours at
  00:30, 06:30, 12:30, 18:30 PKT (`RandomizedDelaySec=600`,
  `Persistent=true`). 6h is the shortest cache horizon (temporary rows), so
  each sweep re-warms rows before they go cold. The times are offset from the
  03:40 backup and the 02/08/14/20:00 autocrawl so no two heavy jobs share a
  slot.
- **Service** `radd-prefetch.service` — `Type=oneshot`, runs
  `prefetch_worker.py --once --limit 200 --load-ceiling 4.0
  --max-wait-seconds 300` as `ubuntu` from `/opt/radd-stream`, with
  `RADD_DB_PATH` set to the live catalog (the same value
  `radd-stream.service` carries).

## Why this mode, and why these numbers

- **Ceiling 4.0** — measured 2026-11-11 the box idles at load ~0.1 (the
  6–8 idle of 2026-11-04 was the agent lanes, retired since). On this
  1-vCPU box 4.0 parks the worker only under genuine saturation, and the
  timer re-fires a yielded sweep six hours later. If the box's idle load
  changes materially, retune `--load-ceiling` in the service file — the
  worker's own default (`LOAD_CEILING`) carries the same value.
- **Max wait 300s** — a sweep that finds the box busy waits at most 5 minutes
  for a quiet slot, then yields (`gated` in the stats) instead of hanging the
  oneshot until systemd kills it. The per-resolve gate still applies inside
  a running sweep, so a box that gets busy mid-sweep is left alone too.
- **Nice=19 + idle IO class** — the same deprioritisation as the backup
  unit, so the worker cannot steal CPU or disk from the live API even while
  it is resolving.
- **TimeoutStartSec=7200** — a full cold sweep (200 links, one slow unwrap
  each) can legitimately run over an hour; 2h matches the backup unit.

## Install (landing step — not done by the branch)

```bash
sudo cp Fast_Fetch/radd-prefetch.service Fast_Fetch/radd-prefetch.timer \
    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radd-prefetch.timer
```

No service restart, no backup, no live-tree change beyond the two unit
files. The timer starts the worker; nothing else runs it.

## Verify it works

```bash
systemctl list-timers radd-prefetch.timer   # next firing, last firing
journalctl -u radd-prefetch.service --since "6 hours ago"
# each sweep logs one line: sweep: posts=… tier1=… warm=… resolved=… failed=… gated=…
```

Check the pool itself (read-only) — pool rows should grow after the first
firing, and stay warm:

```sql
SELECT source, COUNT(*) FROM resolved_cache GROUP BY source;
SELECT COUNT(*) FROM resolved_cache WHERE source = 'pool'
  AND reverify_after > strftime('%s', 'now');
```

A sweep that finds everything warm logs `warm=N resolved=0` and finishes
in seconds. A first sweep on an empty pool resolves up to 200 cold links
and takes a while — that is the bootstrap, not a problem.

## Safety properties (pinned by `test_prefetch_worker.py`)

- The worker only writes `resolved_cache` rows, via
  `record_resolved_cache(..., source='pool')`, inside the success branch of
  a v2 resolve. Failed resolves bank nothing.
- Adult law: the priority query excludes `is_18_plus=1` posts **and** any
  post sharing a `canonical_key` with a flagged one — the worker never even
  resolves a link for a flagged work.
- The load gate is checked before **every** resolve, not just at sweep
  start; a sweep yields after 300s of busy box.
- Dry-run (`--dry-run`) prints the plan and touches nothing remote.
