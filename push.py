#!/usr/bin/env python3
"""
push.py — Single Unified Multi-Tier Push & Deployment Tool.

Replaces the retired legacy scripts (push.py, github_push.py, emergency_push.py).
Located at project root for easy access.

Does EVERYTHING in one command:
  1. Runs local unit tests to ensure zero regressions before push.
  2. Syncs latest chat history to CHAT_HISTORY.md.
  3. Git stages and commits reviewed files with a clean message.
  4. Pushes to persistent local Git remote (gitsafe-backup main).
  5. Pushes to GitHub repository (github.com/radddao/radd-stream) via GITHUB_TOKEN.
  6. Syncs scraper files and CHAT_HISTORY.md to Oracle VM via ORACLE_SSH_KEY.

Usage:
    python3 push.py "feat: add new feature and tests"
    python3 push.py                   # Auto-generates clean timestamped message
    python3 push.py --no-test         # Skip test execution
    python3 push.py --no-oracle       # Push to Git/GitHub only without Oracle sync
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
ORACLE_IP = "92.4.95.252"
ORACLE_USER = "ubuntu"
GITHUB_REPO_URL = "https://x-access-token@github.com/radddao/radd-stream.git"


def get_oracle_key_file() -> str | None:
    raw = os.environ.get("ORACLE_SSH_KEY", "")
    if not raw:
        return None
    match = re.fullmatch(r"(-----BEGIN ([A-Z0-9 ]+)-----)(.*?)(-----END \2-----)", raw, re.S)
    if not match:
        return None
    header, _, body, footer = match.groups()
    body = "".join(body.split())
    with tempfile.NamedTemporaryFile("w", encoding="ascii", delete=False) as f:
        key_path = f.name
        f.write(header + "\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + "\n" + footer + "\n")
    os.chmod(key_path, 0o600)
    return key_path


def create_github_askpass(token: str) -> str:
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(f'#!/bin/sh\necho "{token}"\n')
        askpass_path = f.name
    os.chmod(askpass_path, 0o700)
    return askpass_path


def run_tests() -> bool:
    print("[*] Running pre-push unit tests...", flush=True)
    fast_fetch_dir = ROOT_DIR / "radd-stream" / "Fast_Fetch"
    unit_test_modules = [
        "test_database",
        "test_vidout",
        "test_vegamovies_import",
        "test_rogmovies_import",
        "test_ssrmovies_import",
        "test_7starhd_import",
        "test_hdhub4u_import",
        "test_rareanimes_import",
        "test_katmoviehd_import",
        "test_10xflix_import",
        "test_filmyzilla_import",
        "test_bolly4u_import",
        "test_world4ufree_import",
        "test_backup_manager",
    ]
    res = subprocess.run(
        [sys.executable, "-m", "unittest"] + unit_test_modules,
        cwd=fast_fetch_dir,
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        print("[✓] Pre-push unit tests passed successfully.", flush=True)
        return True
    else:
        print("[!] Unit tests failed! Review output below:\n", file=sys.stderr)
        print(res.stderr or res.stdout, file=sys.stderr)
        return False



def sync_chat_history():
    export_script = ROOT_DIR / "radd-stream" / "Fast_Fetch" / "export_chat.py"
    if export_script.exists():
        try:
            subprocess.run([sys.executable, str(export_script)], capture_output=True, timeout=15)
        except Exception:
            pass


def git_commit(message: str) -> bool:
    print(f"[*] Staging and committing changes with message: '{message}'...", flush=True)
    # Stage relevant tracking files
    subprocess.run(["git", "add", "."], cwd=ROOT_DIR, capture_output=True)

    # Check if anything to commit
    diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT_DIR)
    if diff_check.returncode == 0:
        print("[*] No working tree changes to commit. Proceeding to push existing commits.", flush=True)
        return True

    res = subprocess.run(["git", "commit", "-m", message], cwd=ROOT_DIR, capture_output=True, text=True)
    if res.returncode == 0:
        print("[✓] Local commit created successfully.", flush=True)
        return True
    else:
        print(f"[!] Commit failed: {res.stderr}", file=sys.stderr)
        return False


def push_gitsafe() -> bool:
    print("[*] Pushing to local persistent git remote (gitsafe-backup)...", flush=True)
    res = subprocess.run(["git", "push", "gitsafe-backup", "main"], cwd=ROOT_DIR, capture_output=True, text=True)
    if res.returncode == 0:
        print("[✓] Pushed to gitsafe-backup (main).", flush=True)
        return True
    else:
        print(f"[!] gitsafe-backup push failed: {res.stderr.strip()}", file=sys.stderr)
        return False


def push_github(force: bool = False) -> bool:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("[!] GITHUB_TOKEN not found in environment. Skipping GitHub push.", file=sys.stderr)
        return False

    print(f"[*] Pushing to GitHub (origin/main){' [FORCE]' if force else ''}...", flush=True)
    askpass = create_github_askpass(token)
    env = os.environ.copy()
    env["GIT_ASKPASS"] = askpass
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        # Check if origin remote is set
        remotes_out = subprocess.run(["git", "remote"], cwd=ROOT_DIR, capture_output=True, text=True).stdout
        if "origin" not in remotes_out.split():
            subprocess.run(["git", "remote", "add", "origin", GITHUB_REPO_URL], cwd=ROOT_DIR, capture_output=True)

        cmd = ["git", "push"]
        if force:
            cmd.append("--force")
        cmd.extend(["origin", "main"])

        res = subprocess.run(cmd, cwd=ROOT_DIR, env=env, capture_output=True, text=True)
        if res.returncode == 0:
            print("[✓] Pushed to GitHub repository (origin/main).", flush=True)
            return True
        else:
            # If rejected because of divergence, note it
            print(f"[!] GitHub push note: {res.stderr.strip()}", file=sys.stderr)
            return False
    finally:
        if os.path.exists(askpass):
            os.remove(askpass)



def sync_oracle() -> bool:
    key_path = get_oracle_key_file()
    if not key_path:
        print("[!] ORACLE_SSH_KEY not found in environment. Skipping Oracle sync.", file=sys.stderr)
        return False

    print(f"[*] Syncing updated scraper files and CHAT_HISTORY.md to Oracle VM ({ORACLE_IP})...", flush=True)
    files_to_sync = [
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_vegamovies.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_7starhd.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_hdhub4u.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_rareanimes.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_katmoviehd.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_10xflix.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_filmyzilla.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_bolly4u.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "import_world4ufree.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "backup_manager.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "fast_fetch.py",
        ROOT_DIR / "radd-stream" / "Fast_Fetch" / "CHAT_HISTORY.md",
    ]

    existing = [str(f) for f in files_to_sync if f.exists()]
    if not existing:
        return True

    cmd = [
        "scp", "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
    ] + existing + [f"{ORACLE_USER}@{ORACLE_IP}:/opt/radd-stream/Fast_Fetch/"]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            print(f"[✓] Synced {len(existing)} files to Oracle VM /opt/radd-stream/Fast_Fetch/.", flush=True)
            return True
        else:
            print(f"[!] Oracle SCP note: {res.stderr.strip()}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[!] Oracle SCP error: {e}", file=sys.stderr)
        return False
    finally:
        if os.path.exists(key_path):
            os.remove(key_path)


def main():
    parser = argparse.ArgumentParser(description="Unified Push & Deployment Tool for radd-stream")
    parser.add_argument("message", nargs="?", default=None, help="Commit message")
    parser.add_argument("--no-test", action="store_true", help="Skip running pre-push tests")
    parser.add_argument("--no-oracle", action="store_true", help="Skip syncing to Oracle VM")
    parser.add_argument("--force", action="store_true", help="Force push to GitHub origin (use when histories diverged)")
    args = parser.parse_args()

    # Pre-push test gate
    if not args.no_test:
        if not run_tests():
            print("\n[!] Aborting push due to test failure. Use --no-test to override if intentional.\n", file=sys.stderr)
            sys.exit(1)

    # Sync chat history
    sync_chat_history()

    # Commit message
    msg = args.message or f"chore(sync): automated multi-tier update {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
    git_commit(msg)

    # Multi-tier push
    print("\n" + "=" * 50)
    print(" 🚀 EXECUTING MULTI-TIER PUSH & DEPLOYMENT")
    print("=" * 50)

    gitsafe_ok = push_gitsafe()
    github_ok = push_github(force=args.force)


    oracle_ok = True
    if not args.no_oracle:
        oracle_ok = sync_oracle()

    print("=" * 50)
    print(f" gitsafe-backup : {'✅ Pushed' if gitsafe_ok else '❌ Failed'}")
    print(f" GitHub (origin): {'✅ Pushed' if github_ok else '⚠️ Notice'}")
    print(f" Oracle Cloud VM: {'✅ Synced' if oracle_ok else '⚠️ Notice'}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
