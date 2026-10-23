#!/usr/bin/env python3
"""
auto_chat_sync.py — Background Chat Persistence Daemon on Oracle VM.

Follows THE DAO Directive (Fast_Fetch/DAO.md):
"Never lose a single cultivation breakthrough, conversation turn, or site conquest."

Monitors active Antigravity brain transcripts (~/.gemini/antigravity-cli/brain/)
and auto-appends newly generated message turns directly into Fast_Fetch/CHAT_HISTORY.md.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_FILE = BASE_DIR / "CHAT_HISTORY.md"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import export_chat

STOP_REQUESTED = False


def _sig_handler(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True


def run_daemon(poll_interval: float = 5.0):
    """Continuously monitors brain directory and syncs newly generated chat turns."""
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    print(f"[*] auto_chat_sync daemon started on Oracle VM (monitoring every {poll_interval}s)...", flush=True)

    last_seen_mtimes: dict[str, float] = {}

    while not STOP_REQUESTED:
        try:
            brain_dirs = export_chat.find_brain_directories()
            if not brain_dirs:
                time.sleep(poll_interval)
                continue

            for target_brain in brain_dirs:
                conv_dirs = export_chat.get_conversation_dirs(target_brain)
                if not conv_dirs:
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

        except Exception as e:
            print(f"[!] Daemon error: {e}", file=sys.stderr, flush=True)

        time.sleep(poll_interval)

    print("[*] auto_chat_sync daemon stopped gracefully.", flush=True)


if __name__ == "__main__":
    run_daemon()
