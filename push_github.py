#!/usr/bin/env python3
"""
sync-github — Oracle VM Direct GitHub Synchronization Tool.
Pushes all changes made in /opt/radd-stream directly to https://github.com/radddao/radd-stream.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path("/opt/radd-stream")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_URL = f"https://x-access-token:{GITHUB_TOKEN}@github.com/radddao/radd-stream.git"

def run_tests() -> bool:
    print("[*] Running pre-push unit tests...", flush=True)
    test_dir = WORKSPACE / "Fast_Fetch"
    unit_tests = [
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
    res = subprocess.run([sys.executable, "-m", "unittest"] + unit_tests, cwd=test_dir, capture_output=True, text=True)
    if res.returncode == 0:
        print("[✓] All pre-push unit tests passed.", flush=True)
        return True
    print("[!] Unit tests failed:\n" + (res.stderr or res.stdout), file=sys.stderr)
    return False

def main():
    parser = argparse.ArgumentParser(description="Sync changes directly to GitHub")
    parser.add_argument("message", nargs="?", default=None, help="Commit message")
    parser.add_argument("--no-test", action="store_true", help="Skip pre-push tests")
    args = parser.parse_args()

    if not GITHUB_TOKEN:
        print("[!] GITHUB_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    if not args.no_test and not run_tests():
        sys.exit(1)

    msg = args.message or f"chore(oracle): update {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
    print(f"[*] Committing changes: '{msg}'...", flush=True)

    subprocess.run(["git", "config", "user.name", "radddao-oracle"], cwd=WORKSPACE)
    subprocess.run(["git", "config", "user.email", "ubuntu@radddao.org"], cwd=WORKSPACE)
    subprocess.run(["git", "add", "."], cwd=WORKSPACE)
    
    # Check if anything to commit
    status = subprocess.run(["git", "status", "--porcelain"], cwd=WORKSPACE, capture_output=True, text=True)
    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", msg], cwd=WORKSPACE)
    else:
        print("[*] Working tree clean. Checking for unpushed commits...", flush=True)

    print("[*] Pushing to GitHub (origin main)...", flush=True)
    push_res = subprocess.run(["git", "push", REPO_URL, "HEAD:main"], cwd=WORKSPACE, capture_output=True, text=True)
    if push_res.returncode == 0:
        print("[✓] Successfully pushed to GitHub: https://github.com/radddao/radd-stream", flush=True)
    else:
        print(f"[!] Push failed: {push_res.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
