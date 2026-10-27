#!/usr/bin/env python3
"""arena_tournament.py — Multi-Model Architecture Arena & Evaluation.

Zero external dependencies. 100% Python stdlib only.
Queries multiple top frontier AI models on OpenRouter with the identical prompt,
collects their sovereign earning and 2026 luxury UI proposals, and documents their fight.
"""

import os
import sys
import json
import urllib.request
import urllib.error
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

def query_model(model_name: str, prompt: str, system_prompt: str, api_key: str) -> dict:
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2500
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/radddao/radd-stream",
            "X-Title": f"Radd Stream Arena - {model_name}"
        },
        data=json.dumps(payload).encode("utf-8")
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"success": True, "model": model_name, "content": choice}
    except Exception as e:
        return {"success": False, "model": model_name, "error": str(e)}

def run_tournament():
    api_key = load_openrouter_key()
    if not api_key:
        print("[-] Error: OPENROUTER_API_KEY not found in environment or ~/.openrouter_env")
        return False

    contestants = [
        "meta-llama/llama-3.3-70b-instruct",
        "openai/gpt-4o-mini",
        "qwen/qwen-2.5-72b-instruct"
    ]

    system_prompt = (
        "You are a World-Class Media Systems Architect, Android Performance Specialist, "
        "and Sovereign Monetization Strategist. Deliver concise, battle-tested, concrete code logic and data models."
    )

    arena_prompt = """
PROJECT CONTEXT:
'Radd Stream' is a sovereign media aggregation and streaming engine serving 115,000+ titles with 3.7M links across 18 sites.
Backend: 100% Python standard library only (SQLite, urllib, json, no pip).
Client: Android Kotlin + Jetpack Compose + Media3/ExoPlayer.
Operator Location: Lahore, Pakistan (Currency: PKR, Rails: JazzCash, EasyPaisa, Raast).

Provide your concrete architecture, logic, and code snippets for these two pillars:

PILLAR 1: THE SOVEREIGN EARNING ENGINE
1. Auto-Rotating Link Shorteners for Downloads:
   - Python stdlib implementation in viewer.py: Randomly rotates between configured link shorteners (ShrinkMe, DropLink, etc.) when a Free user requests /api/v1/download.
   - How does it cache shortened URLs to avoid burning shortener API rate limits?
2. Rewarded Ad 'Temporary VIP Pass':
   - Android logic: When a user watches a rewarded ad (Monetag/Adsterra), grant 4 hours of VIP access (1080p/4K unlock, fast direct downloads).
   - How is the expiration persisted and validated locally without client tampering?
3. Pakistani Payment Rails UX (JazzCash Till, EasyPaisa, Raast):
   - Best UI flow in VipUpgradeScreen.kt for 1-tap copy of Till ID/Account and submitting the TID transaction code.

PILLAR 2: 2026/2027 LUXURY STREAMING UI & SEARCH
1. Luxury Visuals (Netflix/Apple TV+ Benchmark):
   - Jetpack Compose architecture: Liquid glassmorphism top/bottom bars, ambient radial glow behind hero carousel matching poster colors, and 60-120fps shimmer skeletons on budget 2GB-RAM phones.
2. Advanced Multi-Filter Search Engine:
   - Fast, debounced search filtering by: Genre, Industry (Bollywood, Hollywood, Pakistani, South Indian), Release Year, Quality, and Sort By.
3. Remote Forced/Recommended App Update Broadcast:
   - When remote-config returns a newer version code & apk_update_url, how is the dialog displayed and package installed seamlessly?

Format your response cleanly with exact Python and Kotlin code snippets.
"""

    results = []
    print(f"[+] Starting Tournament Arena with {len(contestants)} frontier models...")

    for model in contestants:
        print(f"[+] Calling contestant: {model}...")
        res = query_model(model, arena_prompt, system_prompt, api_key)
        results.append(res)
        if res.get("success"):
            print(f"[✓] {model} delivered proposal ({len(res.get('content', ''))} chars)")
        else:
            print(f"[-] {model} failed: {res.get('error')}")

    out_file = BASE_DIR / "docs" / "ARENA_ROUND_1_PROPOSALS.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    report = ["# 🥊 Multi-Model Tournament Arena (Round 1 Proposals)\n"]
    for r in results:
        if r.get("success"):
            report.append(f"## 🏆 Competitor: `{r['model']}`\n\n{r['content']}\n\n---\n")
        else:
            report.append(f"## ❌ Competitor: `{r['model']}` (Failed: {r.get('error')})\n\n---\n")

    out_file.write_text("\n".join(report))
    print(f"[✓] All competitor proposals saved to: {out_file}")
    return True

if __name__ == "__main__":
    success = run_tournament()
    sys.exit(0 if success else 1)
