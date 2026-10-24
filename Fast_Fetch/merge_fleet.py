#!/usr/bin/env python3
"""merge_fleet.py — merge every per-site staging database into one fresh catalog.

Keeps the live database untouched: the target is a new file the operator swaps in
only after the counts, adult filtering and redaction have been checked.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/radd-stream/Fast_Fetch")
import merge_catalogs

DATA_DIR = Path("/home/ubuntu/radd-stream-data")
DEFAULT_TARGET = DATA_DIR / "merged_catalog_20261024.db"

SITES = [
    "rareanimes", "toonworld4all", "desicinemas", "hdtvb", "moviezguru",
    "hindilinks4u", "hdhub4u", "7starhd", "katmoviehd", "vegamovies",
    "multimovies", "rogmovies", "ssrmovies", "10xflix", "bolly4u",
    "filmyzilla", "9xmovies", "world4ufree",
]


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET).resolve()
    report = Path(str(target) + ".report.json")
    results = {}
    if report.exists():
        try:
            results = json.loads(report.read_text())
        except json.JSONDecodeError:
            results = {}

    total_started = time.time()
    for site in SITES:
        src = DATA_DIR / f"{site}.db"
        if not src.exists():
            print(f"[!] missing {src}", flush=True)
            results[site] = {"skipped": "missing"}
            continue
        if results.get(site, {}).get("posts_merged"):
            print(f"[=] {site} already merged, skipping", flush=True)
            continue
        started = time.time()
        try:
            stats = merge_catalogs.merge_site_db(src, target, verbose=False)
        except Exception as exc:  # noqa: BLE001 — one site must not abandon the fleet
            stats = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        stats["elapsed_seconds"] = round(time.time() - started, 1)
        results[site] = stats
        print(f"[{site}] {stats}", flush=True)
        report.write_text(json.dumps(results, indent=2))

    print(
        f"[done] fleet merged in {round(time.time() - total_started, 1)}s -> {target}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
