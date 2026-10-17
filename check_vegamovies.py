#!/usr/bin/env python3
"""
check_vegamovies.py — Live progress monitor for Vegamovies scraper on Oracle VM.

Run from this shell:
    python check_vegamovies.py          # Show current progress snapshot
    python check_vegamovies.py --watch  # Live auto-refreshing monitor (every 3s)
    python check_vegamovies.py -n 25    # Show last 25 log lines
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
scraper_proc = [line.strip() for line in ps_out.splitlines() if "import_vegamovies" in line and "grep" not in line]

# 2. Status file
status_file = "/opt/radd-stream/Fast_Fetch/vegamovies_status.json"
status_data = {{}}
if os.path.exists(status_file):
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception:
        pass

# 3. Database counts
db_file = "/home/ubuntu/radd-stream-data/vegamovies.db"
db_stats = {{}}
if os.path.exists(db_file):
    try:
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM posts")
        db_stats["posts"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM releases")
        db_stats["releases"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM download_sources")
        db_stats["sources"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM download_sources WHERE service = 'fastdl'")
        db_stats["direct_gdl"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'vegamovies' AND scraped = 1")
        db_stats["scraped_roots"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'vegamovies' AND scraped = 0")
        db_stats["pending_roots"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'vegamovies'")
        db_stats["total_roots"] = c.fetchone()[0]
        conn.close()
    except Exception as e:
        db_stats["error"] = str(e)

# 4. Log tail
log_lines = []
log_path = "/home/ubuntu/radd-stream-data/vegamovies_scraper.log"
if os.path.exists(log_path):
    try:
        tail = subprocess.run(["tail", "-n", "{tail_lines}", log_path], capture_output=True, text=True)
        log_lines = tail.stdout.strip().splitlines()
    except Exception:
        pass

result = {{
    "process": scraper_proc,
    "status": status_data,
    "db": db_stats,
    "logs": log_lines,
}}
print(json.dumps(result))
INNER
"""

    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
        "-i", key_path, f"{ORACLE_USER}@{ORACLE_IP}",
        "bash", "-lc", remote_script,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return None
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
    except Exception:
        return None
    return None


def display(data: dict):
    proc = data.get("process", [])
    status = data.get("status", {})
    db = data.get("db", {})
    logs = data.get("logs", [])

    running = len(proc) > 0
    state_label = "🟢 RUNNING" if running else "🔴 STOPPED"

    total = db.get("total_roots", 0)
    scraped = db.get("scraped_roots", 0)
    pending = db.get("pending_roots", 0)
    pct = (scraped / total * 100) if total > 0 else 0

    bar_len = 36
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)

    # Process info line
    proc_line = ""
    if proc:
        parts = proc[0].split()
        pid = parts[0] if len(parts) > 0 else "?"
        cpu = parts[2] if len(parts) > 2 else "?"
        mem = parts[3] if len(parts) > 3 else "?"
        elapsed = parts[5] if len(parts) > 5 else "?"
        proc_line = f" Process  : PID {pid} | CPU: {cpu}% | RAM: {mem}% | Time: {elapsed}"
    else:
        proc_line = " Process  : Not running"

    print(f"\n{'=' * 65}")
    print(f" 🚀 ORACLE VM VEGAMOVIES SCRAPER MONITOR — {state_label}")
    print(f"{'=' * 65}")
    print(proc_line)
    print(f" Progress : [{bar}] {pct:.1f}% ({scraped:,}/{total:,} titles)")
    print(f"-" * 65)
    print(f" 📦 Catalog Titles       : {db.get('posts', 0):,}")
    print(f" 🎬 Releases Found       : {db.get('releases', 0):,}")
    print(f" 🔗 Direct Sources       : {db.get('sources', 0):,}")
    print(f" ⚡ G-Direct Streams     : {db.get('direct_gdl', 0):,} (Google CDN direct)")
    print(f" ⏳ Pending Titles       : {pending:,}")
    if status.get("failed", 0) > 0:
        print(f" ⚠️  Failed Titles        : {status.get('failed', 0):,}")
    else:
        print(f" ⚠️  Failed Titles         : 0")
    print(f"-" * 65)

    if logs:
        print(f" 📜 Recent Live Logs:")
        for line in logs[-8:]:
            print(f"   {line}")

    print(f"{'=' * 65}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Vegamovies scraper live monitor")
    parser.add_argument("--watch", "-w", action="store_true", help="Auto-refresh every 3 seconds")
    parser.add_argument("-n", type=int, default=10, help="Number of log tail lines")
    args = parser.parse_args()

    key_path = get_ssh_key_file()

    try:
        if args.watch:
            while True:
                data = query_oracle_scraper(key_path, args.n)
                os.system("clear" if os.name == "posix" else "cls")
                if data:
                    display(data)
                else:
                    print("[!] Unable to connect to Oracle VM")
                time.sleep(3)
        else:
            data = query_oracle_scraper(key_path, args.n)
            if data:
                display(data)
            else:
                print("[!] Unable to connect to Oracle VM")
    finally:
        try:
            os.unlink(key_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
