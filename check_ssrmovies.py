#!/usr/bin/env python3
"""
check_ssrmovies.py — Live progress monitor for SSRMovies scraper on Oracle VM.

Run from this shell:
    python check_ssrmovies.py          # Show current progress snapshot
    python check_ssrmovies.py --watch  # Live auto-refreshing monitor (every 3s)
    python check_ssrmovies.py -n 25    # Show last 25 log lines
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
scraper_proc = [line.strip() for line in ps_out.splitlines() if "import_ssrmovies" in line and "grep" not in line]

# 2. Status file
status_file = "/opt/radd-stream/Fast_Fetch/ssrmovies_status.json"
status_data = {{}}
if os.path.exists(status_file):
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception:
        pass

# 3. Database counts
db_file = "/home/ubuntu/radd-stream-data/ssrmovies.db"
db_counts = {{}}
if os.path.exists(db_file):
    try:
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM posts")
        db_counts["posts"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM releases")
        db_counts["releases"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM download_sources")
        db_counts["sources"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM download_sources WHERE final_url LIKE '%.r2.%'")
        db_counts["direct_r2"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM download_sources WHERE service = 'google_cdn' OR final_url LIKE '%googleusercontent%'")
        db_counts["gdirect"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM download_sources WHERE service = 'stream' OR final_url LIKE '%watch-online%'")
        db_counts["streams"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'ssrmovies' AND scraped = 1")
        db_counts["scraped"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'ssrmovies' AND scraped = 0")
        db_counts["pending"] = c.fetchone()[0]
        conn.close()
    except Exception as e:
        db_counts["error"] = str(e)

# 4. Tail logs
log_file = "/home/ubuntu/radd-stream-data/ssrmovies_scraper.log"
recent_logs = []
if os.path.exists(log_file):
    out = subprocess.run(["tail", "-n", str({tail_lines}), log_file], capture_output=True, text=True).stdout
    recent_logs = [line for line in out.splitlines() if line.strip()]

print(json.dumps({{
    "proc": scraper_proc,
    "status": status_data,
    "db": db_counts,
    "logs": recent_logs,
}}))
INNER
"""
    cmd = [
        "ssh", "-i", key_path,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=5",
        f"{ORACLE_USER}@{ORACLE_IP}",
        remote_script,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if res.returncode != 0:
            return None
        return json.loads(res.stdout.strip())
    except Exception:
        return None


def format_display(info: dict) -> str:
    proc_lines = info.get("proc", [])
    is_running = len(proc_lines) > 0
    status = info.get("status", {})
    db = info.get("db", {})
    logs = info.get("logs", [])

    out = []
    out.append("=" * 65)
    header_status = "🟢 RUNNING" if is_running else "🔴 STOPPED"
    out.append(f" 🚀 ORACLE VM SSRMOVIES SCRAPER MONITOR — {header_status}")
    out.append("=" * 65)

    if is_running:
        parts = proc_lines[0].split()
        pid = parts[0]
        cpu = parts[2]
        mem = parts[3]
        time_str = parts[5]
        out.append(f" Process  : PID {pid} | CPU: {cpu}% | RAM: {mem}% | Time: {time_str}")
    else:
        out.append(" Process  : Not currently running")

    total = status.get("total", 0) or (db.get("scraped", 0) + db.get("pending", 0))
    completed = status.get("completed", 0) or db.get("scraped", 0)
    pct = (completed / total * 100) if total > 0 else 0

    bar_len = 32
    filled = int(bar_len * (pct / 100))
    bar = "█" * filled + "░" * (bar_len - filled)
    out.append(f" Progress : [{bar}] {pct:.1f}% ({completed:,}/{total:,} titles)")

    out.append("-" * 65)
    out.append(f" 📦 Catalog Titles       : {db.get('posts', 0):,}")
    out.append(f" 🎬 Releases Found       : {db.get('releases', 0):,}")
    out.append(f" 🔗 Direct Sources       : {db.get('sources', 0):,}")
    out.append(f" ⚡ Google CDN Streams   : {db.get('gdirect', 0):,} (lh3 direct)")
    out.append(f" ⚡ Cloudflare R2 Streams: {db.get('direct_r2', 0):,} (10Gbps direct)")
    out.append(f" ▶  Watch-Online Streams : {db.get('streams', 0):,}")
    if is_running:
        out.append(f" ⏳ Pending Titles       : {db.get('pending', 0):,}")
        out.append(f" ⚠️  Failed Titles        : {status.get('failed', 0)}")
    out.append("-" * 65)

    out.append(" 📜 Recent Live Logs:")
    if logs:
        for l in logs[-8:]:
            out.append(f"   {l}")
    else:
        out.append("   (No logs found in /home/ubuntu/radd-stream-data/ssrmovies_scraper.log)")

    out.append("=" * 65)
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Live monitor for SSRMovies scraper on Oracle VM")
    parser.add_argument("--watch", "-w", action="store_true", help="Auto-refresh every 3s")
    parser.add_argument("--interval", "-i", type=float, default=3.0, help="Refresh interval in seconds")
    parser.add_argument("-n", "--lines", type=int, default=10, help="Log lines to tail")
    args = parser.parse_args()

    key_file = get_ssh_key_file()
    try:
        while True:
            info = query_oracle_scraper(key_file, tail_lines=args.lines)
            if info:
                if args.watch:
                    print("\033[2J\033[H", end="")
                print(format_display(info))
            else:
                print(f"[!] Could not connect to Oracle VM at {ORACLE_IP}")

            if not args.watch:
                break
            time.sleep(args.interval)
    finally:
        try:
            os.unlink(key_file)
        except Exception:
            pass


if __name__ == "__main__":
    main()
