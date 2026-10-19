#!/usr/bin/env python3
"""
check_world4ufree.py — Live progress monitor for World4uFree scraper on Oracle VM or local.

Run from this shell:
    python check_world4ufree.py          # Show current progress snapshot
    python check_world4ufree.py --watch  # Live auto-refreshing monitor (every 3s)
    python check_world4ufree.py -n 25    # Show last 25 log lines
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ORACLE_IP = "92.4.95.252"
ORACLE_USER = "ubuntu"


def get_ssh_key_file() -> str:
    raw = os.environ.get("ORACLE_SSH_KEY", "")
    if not raw:
        print("[!] Error: ORACLE_SSH_KEY is not set in environment.", file=sys.stderr)
        sys.exit(1)
    match = re.fullmatch(r"(-----BEGIN ([A-Z0-9 ]+)-----)(.*?)(-----END \2-----)", raw, re.S)
    if not match:
        print("[!] Error: ORACLE_SSH_KEY is not a valid PEM private key.", file=sys.stderr)
        sys.exit(1)
    header, _, body, footer = match.groups()
    body = "".join(body.split())
    with tempfile.NamedTemporaryFile("w", encoding="ascii", delete=False) as f:
        key_path = f.name
        f.write(header + "\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + "\n" + footer + "\n")
    os.chmod(key_path, 0o600)
    return key_path


def query_oracle_scraper(key_path: str, tail_lines: int = 10) -> dict | None:
    remote_script = f"""
python3 - <<'INNER'
import json, os, sqlite3, subprocess

# 1. Process info
ps_out = subprocess.run(["ps", "-eo", "pid,user,%cpu,%mem,stat,time,command"], capture_output=True, text=True).stdout
scraper_proc = [line.strip() for line in ps_out.splitlines() if "import_world4ufree" in line and "grep" not in line]

# 2. Database metrics
db_path = "/home/ubuntu/radd-stream-data/world4ufree.db"
db_exists = os.path.exists(db_path)
counts = {{}}

if db_exists:
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            counts["total"] = cur.execute("SELECT count(*) FROM sitemap_cache;").fetchone()[0]
            counts["scraped"] = cur.execute("SELECT count(*) FROM sitemap_cache WHERE scraped = 1;").fetchone()[0]
            counts["pending"] = cur.execute("SELECT count(*) FROM sitemap_cache WHERE scraped = 0;").fetchone()[0]
            counts["failed"] = cur.execute("SELECT count(*) FROM sitemap_cache WHERE scraped = -1;").fetchone()[0]
            counts["posts"] = cur.execute("SELECT count(*) FROM posts;").fetchone()[0]
            counts["imdb"] = cur.execute("SELECT count(*) FROM posts WHERE imdb_id IS NOT NULL;").fetchone()[0]
            counts["releases"] = cur.execute("SELECT count(*) FROM releases;").fetchone()[0]
            counts["sources"] = cur.execute("SELECT count(*) FROM sources;").fetchone()[0]
            counts["cf_workers"] = cur.execute("SELECT count(*) FROM sources WHERE service = 'cloudflare_worker';").fetchone()[0]
    except Exception as e:
        counts["db_error"] = str(e)

# 3. Log tail
log_file = "/home/ubuntu/radd-stream-data/world4ufree.log"
tail = []
if os.path.exists(log_file):
    res = subprocess.run(["tail", "-n", str({tail_lines}), log_file], capture_output=True, text=True)
    tail = res.stdout.splitlines()

print(json.dumps({{
    "proc": scraper_proc,
    "db_exists": db_exists,
    "counts": counts,
    "tail": tail,
}}))
INNER
"""
    cmd = [
        "ssh", "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{ORACLE_USER}@{ORACLE_IP}",
        remote_script,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode != 0:
            return None
        return json.loads(res.stdout.strip())
    except Exception:
        return None


def render_display(data: dict):
    if not data:
        print("[!] Could not connect to Oracle VM or retrieve telemetry.", file=sys.stderr)
        return

    procs = data.get("proc", [])
    counts = data.get("counts", {})
    tail = data.get("tail", [])

    is_running = len(procs) > 0
    status_icon = "🟢 RUNNING" if is_running else "🔴 STOPPED / READY"

    print("\n" + "=" * 65)
    print(f" 🚀 ORACLE VM WORLD4UFREE SCRAPER MONITOR — {status_icon}")
    print("=" * 65)

    if is_running:
        for p in procs:
            parts = p.split(None, 6)
            if len(parts) >= 7:
                pid, user, cpu, mem, stat, time_str, cmd = parts
                print(f" Process  : PID {pid} | CPU: {cpu}% | RAM: {mem}% | Time: {time_str}")
    else:
        print(" Process  : N/A | CPU: N/A | RAM: N/A | Time: N/A")

    total = counts.get("total", 0)
    scraped = counts.get("scraped", 0)
    pending = counts.get("pending", 0)
    failed = counts.get("failed", 0)
    posts = counts.get("posts", 0)
    imdb = counts.get("imdb", 0)
    releases = counts.get("releases", 0)
    sources = counts.get("sources", 0)
    cf_cnt = counts.get("cf_workers", 0)

    pct = (scraped / total * 100) if total > 0 else 0.0
    bar_width = 32
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)

    print(f" Progress : [{bar}] {pct:.1f}% ({scraped:,}/{total:,} titles)")
    print("-" * 65)
    print(f" 📦 Catalog Posts       : {posts:,}")
    print(f" 🎬 Verified IMDb IDs   : {imdb:,}")
    print(f" 🎬 Releases Found       : {releases:,}")
    print(f" 🔗 Direct Sources       : {sources:,}")
    print(f" ⚡ 10Gbps CF Direct     : {cf_cnt:,} (Cloudflare Worker .mkv)")
    print(f" ⏳ Pending Titles       : {pending:,}")
    print(f" ⚠️  Failed Titles        : {failed:,}")
    print("-" * 65)

    if tail:
        print(" 📜 Recent Live Logs:")
        for line in tail[-8:]:
            print(f"       {line}")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Live monitor for World4uFree scraper on Oracle VM")
    parser.add_argument("--watch", "-w", action="store_true", help="Auto-refreshing monitor")
    parser.add_argument("--interval", "-i", type=float, default=3.0, help="Refresh interval (default: 3.0s)")
    parser.add_argument("-n", "--lines", type=int, default=10, help="Log lines to display")
    args = parser.parse_args()

    key_path = get_ssh_key_file()
    try:
        while True:
            data = query_oracle_scraper(key_path, tail_lines=args.lines)
            if args.watch:
                os.system("clear")
            render_display(data)
            if not args.watch:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[!] Exiting monitor.")
    finally:
        if os.path.exists(key_path):
            os.unlink(key_path)


if __name__ == "__main__":
    main()
