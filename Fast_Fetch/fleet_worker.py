#!/usr/bin/env python3
"""Fast_Fetch/fleet_worker.py — run one fleet crawler per invocation, on a schedule.

Gap A20 (2026-11-11). The fleet has no schedule and no crawler has ever run
through the panel: `fleet_crawlers` carries 25 sites, every `last_sync_at` is
NULL; `fleet_runs`, `fleet_audit`, and the catalog's `admin_fleet_audit` are
all empty; there is no fleet timer, no fleet cron, and no fleet service on
the box. The trigger path exists (the panel's `run_fleet`, and the repo's
`admin_panel._fleet_command`) but nothing ever calls it.

This worker is the scheduled half: a systemd timer fires it once a day, it
picks the stalest runnable crawler, runs the bounded command for that site,
and records the run in the catalog's `admin_fleet_audit` (running -> done /
failed, with pid and exit code) and in the panel's `fleet_crawlers`
(`last_sync_at` on success, `failure_reason` on failure). One site per run,
one run per day, so the 1-vCPU box is never asked to crawl the whole fleet
at once.

What it can run: the repo's 18 engine/script sites (FLEET_SITES) plus the 3
importer sites (castle, dramadog, megacartoons) — 21 sites. The command it
builds is exactly the panel's `fleet_command` (live_stores.py): importer
sites take `importers/import_<site>.py sync --limit N` for both modes;
engine sites take `fast_fetch.py sync --site <site>` in sync mode; script
sites take `import_<site>.py <site sync flag>`; crawl mode takes
`import_<site>.py --limit N` (multimovies: `--limit-roots N`). Every piece
is a literal or an integer; the site must be in the runnable set, so a
caller can never add an argument, a path, or a shell word. No shell is ever
used.

What it cannot run (4 of the panel's 25): harpalgeo, movienestbd,
moviesdrive, xprimehub — those have no validated command in the main repo
(they were one-off sweeps, or, for xprimehub, an 18+ site with no importer
wired). The worker refuses them with a clear error; wiring their command is
a separate job, not a schedule. The runbook (FLEET_RUNBOOK.md) lists them.

Politeness is part of the contract: a `/proc/loadavg` gate before the run
(ceiling 4.0, bounded wait 300 s — the same numbers as the prefetch worker),
Nice=19 + idle IO class in the service unit, and a per-run log file under
the fleet log dir so a run is auditable after the fact. The worker never
touches the live catalog's posts — a crawler writes to its own staging
database; merging staging into the live catalog is `merge_fleet.py` /
`merge_catalogs.py`, a separate, gated step.

RUN MODE (gap A20, 2026-11-11): a systemd timer + oneshot service, shipped
beside this file as `radd-fleet.timer` / `radd-fleet.service` and installed
by the landing (see `FLEET_RUNBOOK.md`). The timer fires once a day at
03:30 PKT — a quiet hour, clear of the prefetch sweeps (00:30, 06:30, 12:30,
18:30) and the gate-backup window — and the worker runs the single stalest
site, so the fleet rotates over ~3 weeks. Until the units are installed the
fleet does not run on a schedule; the panel's run-scraper button is the only
trigger.

Stdlib only, like everything else in Fast_Fetch. Run it under systemd or
`nohup`; SIGINT/SIGTERM finish the current wait and exit cleanly.

Usage:
    python3 -S Fast_Fetch/fleet_worker.py --stalest            # pick + run the stalest site
    python3 -S Fast_Fetch/fleet_worker.py --site dramadog --limit 10
    python3 -S Fast_Fetch/fleet_worker.py --stalest --dry-run  # show the plan only
    python3 -S Fast_Fetch/fleet_worker.py --site rogmovies --mode crawl --limit 25
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import config

#: The 18 engine/script fleet sites, exactly admin_panel.FLEET_SITES.
FLEET_SITES = (
    "10xflix", "7starhd", "9xmovies", "bolly4u", "desicinemas", "filmyzilla",
    "hdhub4u", "hdtvb", "hindilinks4u", "katmoviehd", "moviezguru",
    "multimovies", "rareanimes", "rogmovies", "ssrmovies", "toonworld4all",
    "vegamovies", "world4ufree",
)

#: Importer sites: importers/import_<site>.py takes `sync --limit N` for both modes.
IMPORTER_SITES = frozenset({"castle", "dramadog", "megacartoons"})

#: Sites the worker can run: the 18 fleet sites plus the 3 importers.
RUNNABLE_SITES = frozenset(FLEET_SITES) | IMPORTER_SITES

#: Engine-sync sites take `fast_fetch.py sync --site <site>` in sync mode.
ENGINE_SYNC_SITES = frozenset({
    "vegamovies", "rogmovies", "ssrmovies", "7starhd", "katmoviehd",
    "multimovies", "10xflix", "hdhub4u", "filmyzilla",
})

#: Script sites take `import_<site>.py <flag>` in sync mode.
SCRIPT_SYNC_FLAGS = {
    "9xmovies": "--sync-api",
    "bolly4u": "--sync-api",
    "desicinemas": "--sync-sitemaps",
    "hdtvb": "--sync-sitemap",
    "hindilinks4u": "--sync-sitemap",
    "moviezguru": "--sync-api",
    "rareanimes": "--sync-api",
    "toonworld4all": "--sync-api",
    "world4ufree": "--sync-api",
}

FLEET_MODES = ("sync", "crawl")

#: The panel's 25 sites minus the 21 runnable ones: no validated command in
#: the main repo. The worker refuses these; see the module docstring.
UNRUNNABLE_SITES = frozenset({"harpalgeo", "movienestbd", "moviesdrive", "xprimehub"})

#: Panel DB default (VM-only, not in git): the live panel's data-live database.
DEFAULT_PANEL_DB = os.environ.get(
    "RADD_PANEL_DB",
    "/home/ubuntu/admin-v2-workspace-20261105/data-live/admin_v2.db")

LOAD_CEILING = 4.0
LOAD_POLL_SECONDS = 15.0


def fleet_command(site, mode, limit, *, python="python3", base_dir=None):
    """The argv for one validated fleet run — exactly the panel's fleet_command.

    Every piece is a literal or an integer; the site must be in the runnable
    set, so a caller can never add an argument, a path, or a shell word.
    No shell is ever used to run it.
    """
    if site not in RUNNABLE_SITES:
        raise ValueError("unknown crawler: %s" % site)
    if mode not in FLEET_MODES:
        raise ValueError("unknown mode: %s" % mode)
    base = Path(base_dir) if base_dir else Path(config.BASE_DIR)
    if site in IMPORTER_SITES:
        # importers/ modules take `sync --limit N` for both modes.
        return [python, str(base / "importers" / ("import_%s.py" % site)),
                "sync", "--limit", str(int(limit))]
    if mode == "sync":
        if site in ENGINE_SYNC_SITES:
            return [python, str(base / "fast_fetch.py"), "sync", "--site", site]
        return [python, str(base / ("import_%s.py" % site)),
                SCRIPT_SYNC_FLAGS[site]]
    limit = int(limit)
    if site == "multimovies":
        return [python, str(base / ("import_%s.py" % site)),
                "--limit-roots", str(limit)]
    return [python, str(base / ("import_%s.py" % site)),
            "--limit", str(limit)]


def load_average() -> float:
    """1-minute load average, or 0.0 where /proc/loadavg does not exist."""
    try:
        with open("/proc/loadavg") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def wait_for_quiet_machine(load_ceiling: float,
                           max_wait_seconds: float | None = None) -> bool:
    """Wait until 1-minute loadavg drops to the ceiling.

    Returns True when the machine is quiet, False when the bounded wait ran
    out (the caller yields the run instead of hanging a scheduled run).
    """
    deadline = None
    if max_wait_seconds is not None:
        deadline = time.monotonic() + max_wait_seconds
    while True:
        if load_average() <= load_ceiling:
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(LOAD_POLL_SECONDS)


def pick_stalest(panel_conn):
    """The stalest runnable crawler: never-synced first, then oldest sync.

    Reads the panel's fleet_crawlers. Returns the site_key, or None when
    every runnable site has synced and none is due (never happens today:
    all 25 are NULL).
    """
    rows = panel_conn.execute(
        "SELECT site_key, last_sync_at FROM fleet_crawlers "
        "ORDER BY last_sync_at IS NOT NULL, last_sync_at ASC, site_key ASC").fetchall()
    for site_key, _last_sync in rows:
        if site_key in RUNNABLE_SITES:
            return site_key
    return None


def record_run_start(catalog_conn, site, mode, limit, *, now: int | None = None) -> int:
    """Reserve the audit row for a run. Returns the audit id."""
    now = now if now is not None else int(time.time())
    cur = catalog_conn.execute(
        "INSERT INTO admin_fleet_audit (crawler_id, action, status, started_at, detail) "
        "VALUES (?,?,?,?,?)",
        (site, "run", "running", now, "mode %s limit %d" % (mode, limit)))
    catalog_conn.commit()
    return int(cur.lastrowid)


def record_run_pid(catalog_conn, audit_id: int, pid: int) -> None:
    catalog_conn.execute(
        "UPDATE admin_fleet_audit SET pid=? WHERE id=?", (int(pid), audit_id))
    catalog_conn.commit()


def record_run_finish(catalog_conn, audit_id: int, *, status: str,
                      exit_code: int, now: int | None = None) -> None:
    now = now if now is not None else int(time.time())
    catalog_conn.execute(
        "UPDATE admin_fleet_audit SET status=?, finished_at=?, exit_code=? WHERE id=?",
        (status, now, int(exit_code), audit_id))
    catalog_conn.commit()


def mark_crawler_synced(panel_conn, site, *, now: int | None = None,
                        failure_reason: str | None = None) -> None:
    """Update the panel's fleet_crawlers row after a run."""
    now = now if now is not None else int(time.time())
    if failure_reason is None:
        panel_conn.execute(
            "UPDATE fleet_crawlers SET status='idle', last_sync_at=?, "
            "failure_reason=NULL, updated_at=? WHERE site_key=?",
            (now, now, site))
    else:
        panel_conn.execute(
            "UPDATE fleet_crawlers SET status='idle', failure_reason=?, "
            "updated_at=? WHERE site_key=?",
            (failure_reason[:500], now, site))
    panel_conn.commit()


def run_one(site, mode, limit, *, catalog_db, panel_db, base_dir,
            log_dir, load_ceiling=LOAD_CEILING, max_wait_seconds=300,
            dry_run=False, runner=None):
    """Run one fleet crawl. Returns a dict describing what happened.

    ``runner`` is injected by tests (a fake that returns an exit code instead
    of spawning a subprocess).
    """
    command = fleet_command(site, mode, limit, base_dir=base_dir)
    if dry_run:
        return {"site": site, "mode": mode, "limit": int(limit),
                "command": command, "dry_run": True, "status": "planned"}
    if not wait_for_quiet_machine(load_ceiling, max_wait_seconds):
        return {"site": site, "mode": mode, "limit": int(limit),
                "command": command, "status": "yielded",
                "reason": "load stayed above %.1f" % load_ceiling}

    catalog_conn = sqlite3.connect(str(catalog_db))
    panel_conn = sqlite3.connect(str(panel_db))
    try:
        audit_id = record_run_start(catalog_conn, site, mode, limit)
        panel_conn.execute(
            "UPDATE fleet_crawlers SET status='running', updated_at=? WHERE site_key=?",
            (int(time.time()), site))
        panel_conn.commit()
    finally:
        catalog_conn.close()
        panel_conn.close()

    log_path = Path(log_dir) / ("fleet-%s-%d.log" % (site, audit_id))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if runner is not None:
        exit_code = runner(command, log_path)
        pid = 0
    else:
        with open(log_path, "ab") as sink:
            proc = subprocess.Popen(command, cwd=str(base_dir),
                                    stdin=subprocess.DEVNULL,
                                    stdout=sink, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            pid = int(proc.pid)
            catalog_conn = sqlite3.connect(str(catalog_db))
            try:
                record_run_pid(catalog_conn, audit_id, pid)
            finally:
                catalog_conn.close()
            proc.wait()
            exit_code = int(proc.returncode)

    status = "done" if exit_code == 0 else "failed"
    catalog_conn = sqlite3.connect(str(catalog_db))
    panel_conn = sqlite3.connect(str(panel_db))
    try:
        record_run_finish(catalog_conn, audit_id, status=status, exit_code=exit_code)
        if exit_code == 0:
            mark_crawler_synced(panel_conn, site)
        else:
            mark_crawler_synced(panel_conn, site,
                                failure_reason="exit %d (see %s)" % (exit_code, log_path.name))
    finally:
        catalog_conn.close()
        panel_conn.close()
    return {"site": site, "mode": mode, "limit": int(limit),
            "command": command, "audit_id": audit_id, "pid": pid,
            "exit_code": exit_code, "status": status,
            "log": str(log_path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--site", help="crawler to run")
    target.add_argument("--stalest", action="store_true",
                        help="run the stalest runnable crawler")
    parser.add_argument("--mode", default="sync", choices=FLEET_MODES)
    parser.add_argument("--limit", type=int, default=100,
                        help="crawl limit (importer/crawl modes only; default 100)")
    parser.add_argument("--catalog-db", type=Path, default=None,
                        help="catalog database path (default: config.DB_PATH)")
    parser.add_argument("--panel-db", type=Path, default=None,
                        help="panel database path (default: %s)" % DEFAULT_PANEL_DB)
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Fast_Fetch directory (default: config.BASE_DIR)")
    parser.add_argument("--log-dir", type=Path, default=None,
                        help="per-run log directory (default: <base-dir>)")
    parser.add_argument("--load-ceiling", type=float, default=LOAD_CEILING)
    parser.add_argument("--max-wait-seconds", type=float, default=300)
    parser.add_argument("--dry-run", action="store_true",
                        help="show the plan; run nothing, write nothing")
    args = parser.parse_args(argv)

    catalog_db = Path(args.catalog_db).expanduser() if args.catalog_db \
        else Path(config.DB_PATH)
    panel_db = Path(args.panel_db).expanduser() if args.panel_db \
        else Path(DEFAULT_PANEL_DB)
    base_dir = Path(args.base_dir).expanduser() if args.base_dir \
        else Path(config.BASE_DIR)
    log_dir = Path(args.log_dir).expanduser() if args.log_dir else base_dir

    if args.stalest:
        panel_conn = sqlite3.connect("file:%s?mode=ro" % panel_db, uri=True)
        try:
            site = pick_stalest(panel_conn)
        finally:
            panel_conn.close()
        if site is None:
            print("no runnable crawler found (all 21 have synced)")
            return 0
    else:
        site = args.site

    result = run_one(site, args.mode, args.limit, catalog_db=catalog_db,
                     panel_db=panel_db, base_dir=base_dir, log_dir=log_dir,
                     load_ceiling=args.load_ceiling,
                     max_wait_seconds=args.max_wait_seconds,
                     dry_run=args.dry_run)
    if result.get("dry_run"):
        print("plan: %s %s limit %d" % (result["site"], result["mode"], result["limit"]))
        print("command: %s" % " ".join(result["command"]))
        print("dry-run: nothing written, nothing spawned")
        return 0
    if result["status"] == "yielded":
        print("yielded: %s (%s)" % (result["site"], result["reason"]))
        return 0
    print("fleet run: %s %s limit %d -> %s (exit %d, audit %d, log %s)" % (
        result["site"], result["mode"], result["limit"], result["status"],
        result["exit_code"], result["audit_id"], result["log"]))
    return 0 if result["exit_code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
