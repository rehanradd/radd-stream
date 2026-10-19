#!/usr/bin/env python3
"""
check_filmyzilla.py — Live progress monitor for FilmyZilla scraper on Oracle VM.

Run from this shell:
    python check_filmyzilla.py          # Show current progress snapshot
    python check_filmyzilla.py --watch  # Live auto-refreshing monitor (every 3s)
    python check_filmyzilla.py -n 25    # Show last 25 log lines
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
scraper_proc = [line.strip() for line in ps_out.splitlines() if "import_filmyzilla" in line and "grep" not in line]

# 2. Database metrics
db_path = "/home/ubuntu/radd-stream-data/filmyzilla.db"
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
            counts["releases"] = cur.execute("SELECT count(*) FROM releases;").fetchone()[0]
            counts["sources"] = cur.execute("SELECT count(*) FROM sources;").fetchone()[0]
            counts["google_cdn"] = cur.execute("SELECT count(*) FROM sources WHERE service = 'google_cdn';").fetchone()[0]
    except Exception as e:
        counts["db_error"] = str(e)

# 3. Log tail
log_file = "/home/ubuntu/radd-stream-data/filmyzilla.log"
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


def format_progress_bar(done: int, total: int, width: int = 36) -> str:
    if total <= 0:
        return f"[{'░' * width}] 0.0%"
    pct = min(1.0, done / total)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct * 100:.1f}% ({done:,}/{total:,} titles)"


def render_dashboard(data: dict) -> str:
    proc_lines = data.get("proc", [])
    counts = data.get("counts", {})
    tail = data.get("tail", [])

    is_running = bool(proc_lines)
    status_icon = "🟢 RUNNING" if is_running else "🔴 STOPPED / READY"

    header = f"""
=================================================================
 🎬 ORACLE VM FILMYZILLA SCRAPER MONITOR — {status_icon}
=================================================================
"""
    if proc_lines:
        first = proc_lines[0].split()
        pid = first[0]
        cpu = first[2]
        mem = first[3]
        uptime = first[5]
        proc_info = f" Process  : PID {pid} | CPU: {cpu}% | RAM: {mem}% | Time: {uptime}"
    else:
        proc_info = " Process  : N/A | CPU: N/A | RAM: N/A | Time: N/A"

    total = counts.get("total", 0)
    scraped = counts.get("scraped", 0)
    pending = counts.get("pending", 0)
    failed = counts.get("failed", 0)
    posts = counts.get("posts", 0)
    releases = counts.get("releases", 0)
    sources = counts.get("sources", 0)
    google_cdn = counts.get("google_cdn", 0)

    progress = format_progress_bar(scraped, total)

    stats = f"""{proc_info}
 Progress : {progress}
-----------------------------------------------------------------
 📦 Catalog Posts       : {posts:,}
 🎬 Releases Found       : {releases:,}
 🔗 Direct Sources       : {sources:,}
 ⚡ Google CDN Streams   : {google_cdn:,} (High-Speed Direct)
 ⏳ Pending Titles       : {pending:,}
 ⚠️  Failed Titles        : {failed:,}
-----------------------------------------------------------------
 📜 Recent Live Logs:
"""
    tail_str = ""
    if tail:
        for line in tail[-8:]:
            tail_str += f"       {line}\n"
    else:
        tail_str = "       (No log output available yet)\n"

    footer = "=================================================================\n"
    return header + stats + tail_str + footer


def main():
    parser = argparse.ArgumentParser(description="Live monitor for FilmyZilla on Oracle VM")
    parser.add_argument("--watch", action="store_true", help="Continuously poll every 3 seconds")
    parser.add_argument("-n", "--lines", type=int, default=10, help="Number of tail log lines to show")
    args = parser.parse_args()

    key_path = get_ssh_key_file()
    try:
        if args.watch:
            while True:
                data = query_oracle_scraper(key_path, tail_lines=args.lines)
                if data:
                    print("\033[2J\033[H", end="")
                    print(render_dashboard(data), flush=True)
                time.sleep(3)
        else:
            data = query_oracle_scraper(key_path, tail_lines=args.lines)
            if data:
                print(render_dashboard(data))
            else:
                print("[!] Unable to connect to Oracle VM or retrieve metrics.", file=sys.stderr)
    finally:
        if os.path.exists(key_path):
            os.remove(key_path)


if __name__ == "__main__":
    main()
