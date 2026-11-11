# FLEET_RUNBOOK.md — the fleet schedule (gap A20)

## The problem (measured 2026-11-11)

The fleet has no schedule and no crawler has ever run through the panel:

- `fleet_crawlers` (panel DB): 25 sites, **every `last_sync_at` NULL**.
- `fleet_runs`: 0 rows. `fleet_audit`: 0 rows. Catalog `admin_fleet_audit`: 0 rows.
- No fleet timer, no fleet cron, no fleet service on the box.
- The trigger path exists (panel `run_fleet`, repo `admin_panel._fleet_command`)
  but nothing ever calls it.

## What this ships

- `fleet_worker.py` — runs ONE crawler per invocation: picks the stalest
  runnable site, runs the bounded command, records the run in the catalog's
  `admin_fleet_audit` (running → done/failed, with pid and exit code) and in
  the panel's `fleet_crawlers` (`last_sync_at` on success, `failure_reason`
  on failure). One site per run, one run per day.
- `radd-fleet.service` + `radd-fleet.timer` — the schedule. The timer fires
  daily at 03:30 PKT (a quiet hour, clear of the prefetch sweeps at :30 and
  the gate-backup window). The service runs
  `fleet_worker.py --stalest --limit 100` with a load gate (ceiling 4.0,
  bounded wait 300 s), Nice=19, idle IO class.
- `test_fleet_worker.py` — 16 tests, in the backend gate.

## Install (landing step — the builder does not install units)

```bash
sudo cp Fast_Fetch/radd-fleet.service Fast_Fetch/radd-fleet.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radd-fleet.timer
systemctl list-timers radd-fleet.timer --no-pager
```

Verify the first run the next morning:

```bash
systemctl status radd-fleet.service --no-pager
sqlite3 "file:/home/ubuntu/radd-stream-data/merged_catalog_20261025.db?mode=ro" \
  "SELECT crawler_id, status, exit_code FROM admin_fleet_audit ORDER BY id DESC LIMIT 3;"
sqlite3 /home/ubuntu/admin-v2-workspace-20261105/data-live/admin_v2.db \
  "SELECT site_key, datetime(last_sync_at, 'unixepoch') FROM fleet_crawlers WHERE last_sync_at IS NOT NULL;"
ls -la /opt/radd-stream/Fast_Fetch/fleet-*.log | tail -3
```

## What the worker can and cannot run

Runnable (21): the repo's 18 fleet sites plus the 3 importer sites
(castle, dramadog, megacartoons). The command is exactly the panel's
`fleet_command` — importer sites take `importers/import_<site>.py sync
--limit N` for both modes; engine sites take `fast_fetch.py sync --site
<site>` in sync mode; script sites take `import_<site>.py <site sync flag>`;
crawl mode takes `import_<site>.py --limit N` (multimovies: `--limit-roots N`).

Not runnable (4 of the panel's 25): harpalgeo, movienestbd, moviesdrive,
xprimehub — no validated command in the main repo (one-off sweeps, or, for
xprimehub, an 18+ site with no importer wired). The worker refuses them
with `ValueError: unknown crawler`. Wiring their command is a separate job.

Also not runnable by the worker (not in the panel's fleet at all):
1hdhub4u, 1xbet, 1tamilblasters, freehdmovies, hdutv, hdmovieshub — these
appeared in an earlier "never ran" list but are not fleet_crawlers rows and
have no command anywhere. They need a site decision before any work.

## Proof run (2026-11-11)

One small run proves the path end-to-end (see the landing report for the
result):

```bash
python3 -S Fast_Fetch/fleet_worker.py --site dramadog --limit 10
```

Dramadog was chosen because it is an importer site (bounded `sync --limit
10`), it was just added in the new-sites batch, and its staging database
already exists. The run writes to the dramadog staging DB only — never to
the live catalog's posts. Merging staging into the live catalog is
`merge_fleet.py` / `merge_catalogs.py`, a separate, gated step.

## Safety rules

- Never run a fleet crawl while a gate backup copy is running (A8 outage
  lesson: backup copy + sweep overloaded the 1-vCPU box, 10:11–10:14 PKT
  2026-11-11, ~3 min of 503s). Check `systemctl status radd-prefetch.service`
  and that no backup is in flight before any manual run.
- The worker's load gate yields the run (does not hang the timer) when the
  box stays busy; the timer re-fires the next day.
- A failed run does not update `last_sync_at`, so the same site is picked
  again tomorrow — a failing crawler retries daily until it is fixed or
  disabled, it does not silently fall out of the rotation.
- The worker never writes to the live catalog's posts. It writes only to
  `admin_fleet_audit` (catalog DB), `fleet_crawlers` (panel DB), and the
  crawler's own staging database.
