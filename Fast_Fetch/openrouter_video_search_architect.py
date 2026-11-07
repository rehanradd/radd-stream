#!/usr/bin/env python3
"""openrouter_video_search_architect.py — Design Video Click & Device Media Search Architecture.

Queries OpenRouter with top frontier models (Llama-3.3-70B / GPT-4o-mini)
to architect the 'Search from Video / Device Media Recognition' engine for Radd Stream.
"""

import os
import sys
import json
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def load_openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key.strip()
    env_file = Path.home() / ".openrouter_env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("export OPENROUTER_API_KEY=") or line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
                if key:
                    return key
    return ""

def run_architect():
    api_key = load_openrouter_key()
    if not api_key:
        print("[-] Error: OPENROUTER_API_KEY not found")
        return False

    system_prompt = (
        "You are the Principal AI Architect and Video Engineering Specialist for Radd Stream. "
        "Design production-grade, lightweight, zero-pip backend and Kotlin Jetpack Compose architectures."
    )

    prompt = """
PROJECT SPECIFICATION: ADVANCED SEARCH FROM VIDEO CLICK ON USER DEVICE & PLAYER X-RAY

We are adding two major video-search capabilities to 'Radd Stream' (Android + Python stdlib backend):

FEATURE 1: 'SEARCH FROM USER DEVICE VIDEO' (Reverse Video/Media Matcher)
- User selects any local video/clip from their device storage (WhatsApp clip, screen record, gallery file).
- The app extracts:
  a) Cleaned filename tokens & sanitized title regex matching.
  b) Video duration, aspect ratio, audio stream metadata (MediaMetadataRetriever).
  c) Fast perceptual hash / keyframe sample (first 10 seconds).
- It queries the backend API: `GET /api/v1/search/by-media?title=...&duration=...`
- The backend matches against 115,000+ catalog titles in SQLite using FTS5 / trigram similarity.
- Returns the matched title with 1-tap 4K streaming and direct download mirrors.

FEATURE 2: 'IN-PLAYER SCENE / ACTOR SEARCH' (X-Ray from Video Click)
- When watching any movie/series in PlayerScreen.kt:
  - User single-taps a '🔍 Inspect Scene' button or long-presses the frame.
  - Player queries backend with `(work_id, current_timestamp_seconds)`.
  - Displays an ambient bottom sheet showing:
    * Cast members active in this work (from TMDB credits).
    * Scene context / episode overview.
    * Instant audio language & subtitle switchers.

Provide:
1. Python stdlib implementation for `/api/v1/search/by-media` in `viewer.py` matching catalog entries by sanitized filename tokens, duration proximity (+/- 10%), and clean title similarity.
2. Kotlin Jetpack Compose implementation for the local video file picker and metadata extraction (`DeviceVideoSearchScreen.kt`).
3. Kotlin implementation for the in-player X-Ray scene inspect sheet in `PlayerScreen.kt`.
"""

    models_to_try = [
        "meta-llama/llama-3.3-70b-instruct",
        "openai/gpt-4o-mini"
    ]

    for model in models_to_try:
        print(f"[+] Requesting Video Search Architecture from: {model}...")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 2800
        }

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/radddao/radd-stream",
                "X-Title": "Radd Stream Video Search Architecture"
            },
            data=json.dumps(payload).encode("utf-8")
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                out_file = BASE_DIR / "docs" / "ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md"
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_text(f"# 🎬 Advanced Search from Video & Device Media Architecture ({model})\n\n" + choice)
                print(f"[✓] Successfully generated and saved to {out_file} ({len(choice)} chars)")
                return True
        except Exception as e:
            print(f"[-] Model {model} failed: {e}")
            continue

    return False

if __name__ == "__main__":
    success = run_architect()
    sys.exit(0 if success else 1)
