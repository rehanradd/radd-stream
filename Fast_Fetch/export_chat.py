#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_chat.py — Universal, cross-platform Antigravity conversation exporter.

Preserves all historical chat sessions in Fast_Fetch/CHAT_HISTORY.md and
dynamically appends new conversation turns from local Antigravity brain transcripts.

Usage:
    python Fast_Fetch/export_chat.py              # Export latest conversation
    python Fast_Fetch/export_chat.py --all        # Export all local conversations
    python Fast_Fetch/export_chat.py --id <conv>  # Export specific conversation ID
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DEFAULT_OUTPUT = BASE_DIR / "CHAT_HISTORY.md"


def find_brain_directories() -> list[Path]:
    """Find potential Antigravity brain directories across platforms."""
    candidates = []
    
    # 1. Environment variable if set
    env_app_data = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
    if env_app_data:
        p = Path(env_app_data) / "brain"
        if p.is_dir():
            candidates.append(p)

    # 2. Linux / macOS standard path
    home = Path.home()
    standard_linux = home / ".gemini" / "antigravity-cli" / "brain"
    if standard_linux.is_dir():
        candidates.append(standard_linux)

    # 3. Windows standard paths
    appdata = os.environ.get("APPDATA")
    if appdata:
        win_appdata = Path(appdata) / "antigravity-cli" / "brain"
        if win_appdata.is_dir():
            candidates.append(win_appdata)

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        win_user = Path(userprofile) / ".gemini" / "antigravity-cli" / "brain"
        if win_user.is_dir():
            candidates.append(win_user)

    return [c.resolve() for c in candidates if c.is_dir()]


def get_conversation_dirs(brain_dir: Path) -> list[Path]:
    """List all valid conversation directories sorted by most recently modified."""
    convs = [
        d for d in brain_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".") and (d / ".system_generated" / "logs" / "transcript.jsonl").exists()
    ]
    convs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return convs


def extract_messages_from_transcript(transcript_path: Path) -> list[dict]:
    """Extract ordered user and assistant chat messages from a transcript.jsonl file."""
    messages = []
    if not transcript_path.exists():
        return messages

    full_path = transcript_path.parent / "transcript_full.jsonl"
    full_lines = None

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                step = json.loads(line)
            except json.JSONDecodeError:
                continue

            step_type = step.get("type", "")
            source = step.get("source", "")
            created = step.get("created_at", "")
            content = step.get("content")

            # If truncated and full file exists, load from full file
            if step.get("truncated_fields") and full_path.exists():
                if full_lines is None:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as ff:
                        full_lines = ff.readlines()
                if idx < len(full_lines):
                    try:
                        step = json.loads(full_lines[idx])
                        content = step.get("content")
                    except json.JSONDecodeError:
                        pass

            if not content:
                continue

            content_str = str(content).strip()
            if len(content_str) < 3:
                continue

            if step_type == "USER_INPUT" or source == "USER_EXPLICIT":
                # Clean prompt metadata tags if present for readability
                clean_text = content_str
                match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content_str, re.DOTALL)
                if match:
                    clean_text = match.group(1).strip()
                messages.append({
                    "role": "USER",
                    "created_at": created,
                    "content": clean_text,
                    "raw_content": content_str,
                })
            elif step_type == "PLANNER_RESPONSE" or source == "MODEL":
                messages.append({
                    "role": "AI",
                    "created_at": created,
                    "content": content_str,
                    "raw_content": content_str,
                })

    return messages


def sanitize_secrets(text: str) -> str:
    """Redacts API tokens and credentials from chat exports."""
    text = re.sub(r'ghp_[A-Za-z0-9_]{20,}', '[REDACTED_GH_TOKEN]', text)
    text = re.sub(r'hf_[A-Za-z0-9_]{20,}', '[REDACTED_HF_TOKEN]', text)
    text = re.sub(r'x-access-token:[A-Za-z0-9_]+@', 'x-access-token:[REDACTED]@', text)
    return text


def export_conversation(conv_dir: Path, output_file: Path) -> int:
    """Safely append or export messages from a conversation into output_file."""
    transcript_path = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
    messages = extract_messages_from_transcript(transcript_path)
    if not messages:
        return 0

    existing_content = ""
    if output_file.exists():
        existing_content = output_file.read_text(encoding="utf-8", errors="replace")

    conv_id = conv_dir.name
    new_lines = []

    # If this conversation hasn't been logged yet, write section header
    conv_header_marker = f"Conversation ID: {conv_id}"
    if conv_header_marker not in existing_content:
        new_lines.append(f"\n\n---\n\n# Conversation Session `{conv_id}`\n\n")
        new_lines.append(f"> Auto-exported from Antigravity session\n")
        new_lines.append(f"> Conversation ID: {conv_id}\n\n---\n\n")

    added_count = 0
    for msg in messages:
        # Check if this exact message is already in existing content by created timestamp
        timestamp_marker = f"`{msg['created_at']}`"
        if timestamp_marker in existing_content:
            continue

        if msg["role"] == "USER":
            user_text = sanitize_secrets(msg["content"])
            new_lines.append(f"## 👤 USER  `{msg['created_at']}`\n\n{user_text}\n\n---\n\n")
            added_count += 1
        elif msg["role"] == "AI":
            # Cap extremely long tool text outputs to preserve readability
            text = sanitize_secrets(msg["content"])
            if len(text) > 12000:
                text = text[:12000] + "\n\n... [truncated for readability] ..."
            new_lines.append(f"## 🤖 AI (Antigravity)  `{msg['created_at']}`\n\n{text}\n\n---\n\n")
            added_count += 1

    if new_lines:
        with open(output_file, "a", encoding="utf-8") as f:
            f.writelines(new_lines)

    return added_count


def run_export(
    conversation_id: str | None = None,
    all_convs: bool = False,
    output_path: Path = DEFAULT_OUTPUT,
    brain_dir: Path | None = None,
) -> int:
    """Execute conversation export."""
    brain_dirs = [brain_dir] if brain_dir else find_brain_directories()
    if not brain_dirs:
        print("[!] No Antigravity brain directories found on this system.", file=sys.stderr)
        return 0

    target_brain = brain_dirs[0]
    conv_dirs = get_conversation_dirs(target_brain)
    if not conv_dirs:
        print(f"[!] No conversation transcripts found in {target_brain}", file=sys.stderr)
        return 0

    if conversation_id:
        selected = [d for d in conv_dirs if d.name == conversation_id]
        if not selected:
            print(f"[!] Conversation ID {conversation_id} not found in {target_brain}", file=sys.stderr)
            return 0
    elif all_convs:
        selected = conv_dirs
    else:
        # Default: latest conversation
        selected = [conv_dirs[0]]

    total_added = 0
    for c_dir in selected:
        count = export_conversation(c_dir, output_path)
        print(f"[✓] Conversation {c_dir.name}: exported {count} new messages to {output_path.name}")
        total_added += count

    return total_added


def parse_args():
    parser = argparse.ArgumentParser(description="Export Antigravity conversations to CHAT_HISTORY.md")
    parser.add_argument("--id", dest="conversation_id", help="Specific conversation ID to export")
    parser.add_argument("--all", action="store_true", help="Export all discovered conversations")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output markdown file path")
    parser.add_argument("--brain-dir", help="Explicit path to brain directory")
    return parser.parse_args()


def main():
    args = parse_args()
    b_dir = Path(args.brain_dir).resolve() if args.brain_dir else None
    out = Path(args.output).resolve()
    run_export(
        conversation_id=args.conversation_id,
        all_convs=args.all,
        output_path=out,
        brain_dir=b_dir,
    )


if __name__ == "__main__":
    main()
