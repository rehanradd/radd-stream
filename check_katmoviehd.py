#!/usr/bin/env python3
"""
check_katmoviehd.py — Live progress monitor for KatMovieHD scraper on Oracle VM.

Run from this shell:
    python check_katmoviehd.py          # Show current progress snapshot
    python check_katmoviehd.py --watch  # Live auto-refreshing monitor (every 3s)
    python check_katmoviehd.py -n 25    # Show last 25 log lines
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
scraper_proc = [line.strip() for line in ps_out.splitlines() if "import_katmoviehd" in line and "grep" not in line]

# 2. Status file
status_file = "/opt/radd-stream/Fast_Fetch/katmoviehd_status.json"
status_data = {{}}
if os.path.exists(status_file):
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception:
        pass

# 3. Database counts
db_file = "/home/ubuntu/radd-stream-data/katmoviehd.db"
db_stats = {{}}
if os.path.exists(db_file):
    try:
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        db_stats["total_cache"] = cur.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        db_stats["scraped"] = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0]
        db_stats["pending"] = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0").fetchone()[0]
        db_stats["failed"] = cur.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0]
        db_stats["posts"] = cur.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        db_stats["releases"] = cur.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        db_stats["sources"] = cur.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        db_stats["r2_sources"] = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'fsl_r2'").fetchone()[0]
        db_stats["pixeldrain_sources"] = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'pixeldrain'").fetchone()[0]
        db_stats["hubcloud_sources"] = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'hubcloud'").fetchone()[0]
        db_stats["gdflix_sources"] = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'gdflix'").fetchone()[0]
        db_stats["katdrive_sources"] = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'katdrive'").fetchone()[0]
        db_stats["sendcm_sources"] = cur.execute("SELECT COUNT(*) FROM sources WHERE service = 'sendcm'").fetchone()[0]
        conn.close()
    except Exception as e:
        db_stats["error"] = str(e)

# 4. Recent logs
log_lines = []
log_file = "/home/ubuntu/radd-stream-data/katmoviehd.log"
if os.path.exists(log_file):
    try:
        tail = subprocess.run(["tail", "-n", "{tail_lines}", log_file], capture_output=True, text=True)
        log_lines = tail.stdout.strip().split("\\n") if tail.stdout.strip() else []
    except Exception:
        pass

print(json.dumps({{"process": scraper_proc, "status": status_data, "db": db_stats, "logs": log_lines}}))
INNER
"""
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=8",
        "-i", key_path,
        f"{ORACLE_USER}@{ORACLE_IP}",
        remote_script,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return None
        for line in result.stdout.strip().splitlines():
            if line.startswith("{"):
                return json.loads(line)
    except Exception:
        pass
    return None


def display_status(data: dict):
    proc = data.get("process", [])
    db = data.get("db", {})
    status = data.get("status", {})
    logs = data.get("logs", [])

    running = len(proc) > 0
    state_emoji = "🟢 RUNNING" if running else "🔴 STOPPED / READY"

    total = db.get("total_cache", 0)
    scraped = db.get("scraped", 0)
    pending = db.get("pending", 0)
    failed = db.get("failed", 0)
    posts = db.get("posts", 0)
    releases = db.get("releases", 0)
    sources = db.get("sources", 0)
    r2_sources = db.get("r2_sources", 0)
    pd_sources = db.get("pixeldrain_sources", 0)
    gd_sources = db.get("gdflix_sources", 0)
    kd_sources = db.get("katdrive_sources", 0)

    pct = (scraped / total * 100) if total > 0 else 0.0

    bar_width = 36
    filled = int(bar_width * pct / 100) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_width - filled)

    pid_str = "N/A"
    cpu_str = "N/A"
    mem_str = "N/A"
    time_str = "N/A"
    if proc:
        parts = proc[0].split()
        if len(parts) >= 6:
            pid_str = f"PID {parts[0]}"
            cpu_str = f"{parts[2]}%"
            mem_str = f"{parts[3]}%"
            time_str = parts[5]

    print(f"\n{'=' * 65}")
    print(f" 🚀 ORACLE VM KATMOVIEHD SCRAPER MONITOR — {state_emoji}")
    print(f"{'=' * 65}")
    print(f" Process  : {pid_str} | CPU: {cpu_str} | RAM: {mem_str} | Time: {time_str}")
    print(f" Progress : [{bar}] {pct:.1f}% ({scraped:,}/{total:,} titles)")
    print(f"-" * 65)
    print(f" 📦 Catalog Posts       : {posts:,}")
    print(f" 🎬 Releases Found       : {releases:,}")
    print(f" 🔗 Direct Sources       : {sources:,}")
    print(f" ⚡ Cloudflare R2        : {r2_sources:,} (10Gbps Direct Stream)")
    print(f" ⚡ PixelDrain Direct    : {pd_sources:,} (Instant Video/Matroska)")
    print(f" ⚡ GDFlix Mirrors       : {gd_sources:,}")
    print(f" ⚡ KatDrive Mirrors     : {kd_sources:,}")
    print(f" ⏳ Pending Titles       : {pending:,}")
    print(f" ⚠️  Failed Titles        : {failed:,}")
    print(f"-" * 65)

    if logs:
        print(" 📜 Recent Live Logs:")
        for line in logs[-10:]:
            print(f"       {line}")
    else:
        print(" 📜 No recent logs found.")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="KatMovieHD Oracle Live Monitor")
    parser.add_argument("--watch", "-w", action="store_true", help="Auto-refresh every 3s")
    parser.add_argument("-n", "--lines", type=int, default=8, help="Number of log lines to show")
    args = parser.parse_args()

    key_path = get_ssh_key_file()

    try:
        if args.watch:
            print("[*] Starting live watch mode (Ctrl+C to stop)...")
            while True:
                data = query_oracle_scraper(key_path, tail_lines=args.lines)
                os.system("clear" if os.name == "posix" else "cls")
                if data:
                    display_status(data)
                else:
                    print("[!] Waiting for response from Oracle VM...")
                time.sleep(3)
        else:
            data = query_oracle_scraper(key_path, tail_lines=args.lines)
            if data:
                display_status(data)
            else:
                print("[!] Unable to retrieve scraper status from Oracle VM.")
    finally:
        if os.path.exists(key_path):
            os.remove(key_path)


if __name__ == "__main__":
    main()
