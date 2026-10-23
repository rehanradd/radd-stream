#!/usr/bin/env python3
"""Off-site backup runner: every catalog database that is safe to read right now.

Exclusions are deliberate, not an oversight:
  * a database another process still holds open in non-WAL (rollback journal) mode
    would block that writer for the whole VACUUM INTO read, so a crawler or merge
    mid-run would stall or fail. WAL databases are concurrent-safe and included.
  * derived projections (anything readable from the staging databases plus
    catalog_v2.py) are skipped to keep each archive small.

Usage: python3 -S Fast_Fetch/run_backup.py [--dry-run] [--keep-derived]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = Path("/home/ubuntu/radd-stream-data")
OUT_DIR = Path("/tmp/radd-stream-backups")
DERIVED_HINTS = ("catalog_full", "merged_catalog_stale")


def journal_mode(db: Path) -> str:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        except sqlite3.Error:
            return "locked"
        finally:
            conn.close()
    except sqlite3.Error:
        return "locked"


def held_open_by(db: Path) -> str:
    """Return "pid:comm" for the first process with this file (or its journal) open."""
    wanted = set()
    for candidate in (db, Path(str(db) + "-wal"), Path(str(db) + "-journal"), Path(str(db) + "-shm")):
        try:
            wanted.add(os.stat(candidate).st_ino)
        except OSError:
            continue
    if not wanted:
        return ""
    me = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            comm = Path(f"/proc/{entry}/comm").read_text().strip()
        except OSError:
            comm = "?"
        try:
            fds = os.listdir(f"/proc/{entry}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                stat = os.stat(f"/proc/{entry}/fd/{fd}")
            except OSError:
                continue
            if stat.st_ino in wanted and stat.st_mode & 0o200:
                return f"{entry}:{comm}"
    return ""


def is_derived(name: str) -> bool:
    stem = Path(name).stem.casefold()
    return any(h in stem for h in DERIVED_HINTS)


def select_databases(data_dir: Path, *, keep_derived: bool = False) -> tuple[list[Path], list[tuple[str, str]]]:
    chosen, skipped = [], []
    for db in sorted(data_dir.glob("*.db")):
        if is_derived(db.name) and not keep_derived:
            skipped.append((db.name, "rebuildable projection/superseded snapshot"))
            continue
        mode = journal_mode(db)
        if mode == "locked":
            skipped.append((db.name, "cannot open for reading right now"))
            continue
        writer = held_open_by(db)
        if writer and mode != "wal":
            skipped.append((db.name, f"writer {writer} active on journal_mode={mode}"))
            continue
        chosen.append(db)
    return chosen, skipped


def prune_local_archives(out_dir: Path, *, keep: int = 5) -> None:
    """Keep the newest archives in the local scratch directory and drop the rest."""
    archives = sorted(out_dir.glob("radd-stream-backup_*.tar.gz"), key=lambda p: p.name, reverse=True)
    for stale in archives[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Back up catalog databases to Hugging Face")
    parser.add_argument("--dry-run", action="store_true", help="Archive only, upload nothing")
    parser.add_argument("--keep-derived", action="store_true", help="Include derived projection DBs")
    parser.add_argument("--dir", default=str(DATA_DIR), help="Directory holding the .db files")
    parser.add_argument("--out", default=str(OUT_DIR), help="Where to write the archive")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(BASE_DIR))
    import backup_manager

    data_dir = Path(args.dir)
    out_dir = Path(args.out)
    chosen, skipped = select_databases(data_dir, keep_derived=args.keep_derived)
    if not chosen:
        print("[!] No database is safe to back up right now.", file=sys.stderr)
        return 1

    print(f"[*] Backing up {len(chosen)} databases", flush=True)
    for name, reason in skipped:
        print(f"    skipped {name}: {reason}", flush=True)

    started = time.monotonic()
    archive, manifest = backup_manager.create_backup_archive(chosen, out_dir)
    print(f"[✓] {archive.name} ({manifest['archive']['size_mb']} MB) in {time.monotonic() - started:.0f}s", flush=True)
    (out_dir / "LATEST_SHA256.txt").write_text(
        f"{manifest['archive']['sha256']}  {archive.name}\n"
    )

    if args.dry_run:
        print("[*] Dry run: nothing uploaded.", flush=True)
        return 0

    extras = []
    code = backup_manager.snapshot_code(out_dir)
    if code:
        extras.append(code)
    uploaded = backup_manager.upload_to_huggingface(archive, manifest=manifest, extra_files=extras)
    if uploaded:
        # Only forget local copies once they exist off-site.
        prune_local_archives(out_dir)
        repo = os.environ.get("HF_DATASET_REPO", "")
        print(f"[✓] Hugging Face upload succeeded: https://huggingface.co/datasets/{repo}", flush=True)
        return 0
    print("[!] Hugging Face upload FAILED; keeping every local archive.", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
