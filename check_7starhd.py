#!/usr/bin/env python3
"""
check_7starhd.py — Live progress monitor for 7StarHD / 10xflix scraper on Oracle VM.

Run from this shell:
    python check_7starhd.py          # Show current progress snapshot
    python check_7starhd.py --watch  # Live auto-refreshing monitor (every 3s)
    python check_7starhd.py -n 25    # Show last 25 log lines
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
    parts = raw.split(" ")
    lines = []
    i = 0
    while i < len(parts):
        if parts[i] == "-----BEGIN":
            header = []
            while i < len(parts) and not parts[i].endswith("-----"):
                header.append(parts[i])
                i += 1
            header.append(parts[i])
            i += 1
            lines.append(" ".join(header))
            break
        i += 1

    base64_data = ""
    while i < len(parts):
        if parts[i] == "-----END":
            footer = []
            while i < len(parts):
                footer.append(parts[i])
                i += 1
            lines.append(base64_data)
            lines.append(" ".join(footer))
            break
        base64_data += parts[i]
        i += 1

    if len(lines) >= 3:
        key_lines = [lines[0]]
        b64 = lines[1]
        for j in range(0, len(b64), 64):
            key_lines.append(b64[j:j+64])
        key_lines.append(lines[2])
        pem = "\n".join(key_lines) + "\n"
    else:
        match = re.fullmatch(r"(-----BEGIN ([A-Z0-9 ]+)-----)(.*?)(-----END \2-----)", raw, re.S)
        if match:
            h, _, b, f = match.groups()
            b = "".join(b.split())
            pem = h + "\n" + "\n".join(b[k:k+64] for k in range(0, len(b), 64)) + "\n" + f + "\n"
        else:
            pem = raw.strip() + "\n"

    with tempfile.NamedTemporaryFile("w", encoding="ascii", delete=False) as f:
        key_path = f.name
        f.write(pem)
    os.chmod(key_path, 0o600)
    return key_path


def query_oracle_scraper(key_path: str, tail_lines: int = 10) -> dict | None:
    remote_script = f"""
python3 - <<'INNER'
import json, os, sqlite3, subprocess

# 1. Process info
ps_out = subprocess.run(["ps", "-eo", "pid,user,%cpu,%mem,stat,time,command"], capture_output=True, text=True).stdout
scraper_proc = [line.strip() for line in ps_out.splitlines() if "import_7starhd" in line and "grep" not in line]

# 2. Status file
status_file = "/opt/radd-stream/Fast_Fetch/7starhd_status.json"
status_data = {{}}
if os.path.exists(status_file):
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception:
        pass

# 3. Database counts
db_file = "/home/ubuntu/radd-stream-data/7starhd.db"
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
        c.execute("SELECT count(*) FROM download_sources WHERE service LIKE '%r2%' OR final_url LIKE '%.r2.%'")
        db_stats["direct_r2"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = '7starhd' AND scraped = 1")
        db_stats["scraped_roots"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = '7starhd' AND scraped = 0")
        db_stats["pending_roots"] = c.fetchone()[0]
        c.execute("SELECT count(*) FROM sitemap_cache WHERE site = '7starhd'")
        db_stats["total_roots"] = c.fetchone()[0]
        conn.close()
    except Exception as e:
        db_stats["error"] = str(e)

# 4. Log tail
log_lines = []
for log_path in ["/home/ubuntu/radd-stream-data/7starhd.log", "/home/ubuntu/radd-stream-data/7starhd_scraper.log"]:
    if os.path.exists(log_path):
        try:
            tail = subprocess.run(["tail", "-n", "{tail_lines}", log_path], capture_output=True, text=True)
            log_lines = [l for l in tail.stdout.strip().splitlines() if l.strip()]
            if log_lines:
                break
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
        "ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5",
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
    print(f" 🚀 ORACLE VM 7STARHD SCRAPER MONITOR — {state_label}")
    print(f"{'=' * 65}")
    print(proc_line)
    print(f" Progress : [{bar}] {pct:.1f}% ({scraped:,}/{total:,} titles)")
    print(f"-" * 65)
    print(f" 📦 Catalog Titles       : {db.get('posts', 0):,}")
    print(f" 🎬 Releases Found       : {db.get('releases', 0):,}")
    print(f" 🔗 Direct Sources       : {db.get('sources', 0):,}")
    print(f" ⚡ R2 Direct Streams    : {db.get('direct_r2', 0):,} (10Gbps Cloudflare R2 direct)")
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
    parser = argparse.ArgumentParser(description="7StarHD scraper live monitor")
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
