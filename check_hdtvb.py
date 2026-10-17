#!/usr/bin/env python3
"""
check_hdtvb.py — Live progress monitor for HDTVB (HDHub4u) scraper on Oracle VM.

Run from this shell:
    python check_hdtvb.py          # Show current progress snapshot
    python check_hdtvb.py --watch  # Live auto-refreshing monitor (every 3s)
    python check_hdtvb.py -n 25    # Show last 25 log lines
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
scraper_proc = [line.strip() for line in ps_out.splitlines() if "import_hdtvb" in line and "grep" not in line]

# 2. Status file
status_file = "/opt/radd-stream/Fast_Fetch/hdtvb_status.json"
status_data = {{}}
if os.path.exists(status_file):
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception:
        pass

# 3. Database counts
db_file = "/home/ubuntu/radd-stream-data/hdtvb.db"
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
        c.execute("SELECT count(*) FROM download_sources WHERE service = 'cloudflare_r2'")
        db_stats["direct_r2"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'hdhub4u' AND scraped = 1")
        db_stats["scraped_roots"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = 'hdhub4u' AND scraped = 0")
        db_stats["pending_roots"] = c.fetchone()[0]
        conn.close()
    except Exception as e:
        db_stats["error"] = str(e)

# 4. Log tail
log_file = "/home/ubuntu/radd-stream-data/hdtvb_scraper.log"
log_tail = []
if os.path.exists(log_file):
    with open(log_file, "r") as f:
        log_tail = f.readlines()[-{tail_lines}:]

print(json.dumps({{
    "process": scraper_proc,
    "status": status_data,
    "db": db_stats,
    "log_tail": [l.strip() for l in log_tail if l.strip()],
}}))
INNER
"""
    cmd = [
        "ssh", "-i", key_path, "-p", "22",
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{ORACLE_USER}@{ORACLE_IP}",
        remote_script,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            return {"error": res.stderr.strip() or "SSH error"}
        return json.loads(res.stdout)
    except Exception as e:
        return {"error": str(e)}


def render_dashboard(data: dict):
    if "error" in data:
        print(f"\n[!] Error connecting to Oracle VM: {data['error']}\n")
        return

    proc = data.get("process", [])
    st = data.get("status", {})
    db = data.get("db", {})
    tail = data.get("log_tail", [])

    is_running = len(proc) > 0
    status_icon = "🟢 RUNNING" if is_running else "🔴 STOPPED"

    completed = st.get("completed", db.get("scraped_roots", 0))
    total = st.get("total", 5692)
    percent = round((completed / max(1, total)) * 100, 1)

    bar_width = 36
    filled = int(bar_width * (percent / 100))
    bar = "█" * filled + "░" * (bar_width - filled)

    print("\n" + "=" * 65)
    print(f" 🚀 ORACLE VM HDTVB (HDHUB4U) SCRAPER MONITOR — {status_icon}")
    print("=" * 65)

    if proc:
        proc_str = proc[0]
        parts = proc_str.split()
        pid = parts[0] if parts else "?"
        cpu = parts[2] if len(parts) > 2 else "?"
        mem = parts[3] if len(parts) > 3 else "?"
        runtime = parts[5] if len(parts) > 5 else "?"
        print(f" Process  : PID {pid} | CPU: {cpu}% | RAM: {mem}% | Time: {runtime}")
    else:
        print(" Process  : Not currently running")

    print(f" Progress : [{bar}] {percent}% ({completed:,}/{total:,} titles)")
    print("-" * 65)
    print(f" 📦 Catalog Titles       : {db.get('posts', 0):,}")
    print(f" 🎬 Releases Found       : {db.get('releases', st.get('releases', 0)):,}")
    print(f" 🔗 Direct Sources       : {db.get('sources', st.get('sources', 0)):,}")
    print(f" ⚡ Cloudflare R2 Streams : {db.get('direct_r2', 0):,} (10Gbps direct MP4/MKV)")
    print(f" ⚠️  Failed Titles         : {st.get('failed', 0)}")
    print("-" * 65)
    print(" 📜 Recent Live Logs:")
    if tail:
        for line in tail[-8:]:
            print(f"   {line}")
    else:
        print("   (No logs yet)")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Check Oracle HDTVB scraper progress")
    parser.add_argument("-w", "--watch", action="store_true", help="Live monitor mode (refresh every 3s)")
    parser.add_argument("-n", "--lines", type=int, default=10, help="Number of log lines to show (default: 10)")
    parser.add_argument("--interval", type=float, default=3.0, help="Refresh interval in seconds (default: 3.0)")
    args = parser.parse_args()

    key_path = get_ssh_key_file()
    try:
        if args.watch:
            print("[*] Starting live monitor... Press Ctrl+C to stop.\n")
            while True:
                data = query_oracle_scraper(key_path, tail_lines=args.lines)
                if data:
                    if sys.stdout.isatty():
                        sys.stdout.write("\033[2J\033[H")
                    render_dashboard(data)
                time.sleep(args.interval)
        else:
            data = query_oracle_scraper(key_path, tail_lines=args.lines)
            if data:
                render_dashboard(data)
    except KeyboardInterrupt:
        print("\n[*] Monitor stopped.")
    finally:
        try:
            os.remove(key_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
