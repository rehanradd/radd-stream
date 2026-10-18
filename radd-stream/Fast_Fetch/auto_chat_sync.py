#!/usr/bin/env python3
"""
auto_chat_sync.py — Background Chat Persistence Daemon & Multi-Tier Replication.

Follows THE DAO Directive (radd-stream/Fast_Fetch/DAO.md):
"Never lose a single cultivation breakthrough, conversation turn, or site conquest."

How it Works:
  1. Actively watches local Antigravity brain transcripts (~/.gemini/antigravity-cli/brain/).
  2. Detects new user/AI message turns in real-time (every 5 seconds).
  3. Automatically appends new turns into Fast_Fetch/CHAT_HISTORY.md.
  4. Automatically replicates CHAT_HISTORY.md across 3 durable storage layers:
     - Layer 1: Local workspace file (Fast_Fetch/CHAT_HISTORY.md)
     - Layer 2: Local persistent Git remote (gitsafe-backup)
     - Layer 3: Remote Off-Site Oracle Cloud VM (ubuntu@92.4.95.252:/opt/radd-stream/Fast_Fetch/)
  5. 100% Python Standard Library. Zero external pip packages.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_FILE = BASE_DIR / "CHAT_HISTORY.md"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import export_chat

STOP_REQUESTED = False


def _sig_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True


def get_ssh_key_file() -> str | None:
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


def replicate_offsite():
    """Replicates CHAT_HISTORY.md to Git and Oracle VM."""
    # 1. Git push
    try:
        workspace_dir = BASE_DIR.parent.parent
        subprocess.run(
            ["git", "add", str(OUTPUT_FILE)],
            cwd=workspace_dir,
            capture_output=True,
            timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", "chore(chat): auto-sync chat history", "--no-verify"],
            cwd=workspace_dir,
            capture_output=True,
            timeout=10,
        )
        subprocess.run(
            ["git", "push", "gitsafe-backup", "main"],
            cwd=workspace_dir,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass

    # 2. Oracle VM off-site sync
    key_path = get_ssh_key_file()
    if key_path:
        try:
            subprocess.run(
                [
                    "scp", "-i", key_path,
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=8",
                    str(OUTPUT_FILE),
                    "ubuntu@92.4.95.252:/opt/radd-stream/Fast_Fetch/CHAT_HISTORY.md",
                ],
                capture_output=True,
                timeout=20,
            )
        except Exception:
            pass
        finally:
            if os.path.exists(key_path):
                os.remove(key_path)


def run_daemon(poll_interval: float = 5.0):
    """Continuously monitors brain directory and syncs newly generated chat turns."""
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    print(f"[*] auto_chat_sync daemon started (monitoring every {poll_interval}s)...", flush=True)

    last_seen_mtimes: dict[str, float] = {}

    while not STOP_REQUESTED:
        try:
            brain_dirs = export_chat.find_brain_directories()
            if not brain_dirs:
                time.sleep(poll_interval)
                continue

            target_brain = brain_dirs[0]
            conv_dirs = export_chat.get_conversation_dirs(target_brain)
            if not conv_dirs:
                time.sleep(poll_interval)
                continue

            # Check latest conversation
            latest_conv = conv_dirs[0]
            t_file = latest_conv / ".system_generated" / "logs" / "transcript.jsonl"
            if t_file.exists():
                mtime = t_file.stat().st_mtime
                prev_mtime = last_seen_mtimes.get(str(t_file), 0.0)

                if mtime > prev_mtime:
                    last_seen_mtimes[str(t_file)] = mtime
                    added = export_chat.export_conversation(latest_conv, OUTPUT_FILE)
                    if added > 0:
                        print(f"[{time.strftime('%X')}] 💾 Auto-saved {added} new chat message(s) to CHAT_HISTORY.md", flush=True)
                        replicate_offsite()

        except Exception as e:
            print(f"[!] Daemon error: {e}", file=sys.stderr, flush=True)

        time.sleep(poll_interval)

    print("[*] auto_chat_sync daemon stopped gracefully.", flush=True)


if __name__ == "__main__":
    run_daemon()
