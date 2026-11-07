#!/usr/bin/env python3
"""openrouter_oracle.py — Autonomous deep code review & architecture auditor using OpenRouter.

Zero external dependencies. 100% Python stdlib only.
Reads real codebase files and invokes top frontier models via OpenRouter
(claude-3.5-sonnet, gpt-4o, deepseek-chat) to generate deep audits and action plans.
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

def call_openrouter(prompt: str, system_prompt: str = "", model: str = "meta-llama/llama-3.3-70b-instruct") -> dict:
    api_key = load_openrouter_key()
    if not api_key:
        return {"success": False, "error": "OPENROUTER_API_KEY not found"}

    models_to_try = [model, "openai/gpt-4o-mini", "qwen/qwen-2.5-72b-instruct"]
    last_err = ""

    for m in models_to_try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": m,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2800
        }

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/radddao/radd-stream",
                "X-Title": "Radd Stream Autonomous Auditor"
            },
            data=json.dumps(payload).encode("utf-8")
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"success": True, "model": m, "content": choice}
        except Exception as e:
            last_err = f"Model {m} failed: {e}"
            continue

    return {"success": False, "error": last_err}

def build_code_manifest() -> str:
    """Collect snippets and key structures from actual code files."""
    files_to_sample = [
        ("Fast_Fetch/viewer.py", 2500, 2600),
        ("Fast_Fetch/admin_panel.py", 1000, 1110),
        ("App/app/src/main/kotlin/com/raddstream/app/network/RaddStreamApi.kt", 1, 80),
        ("App/app/src/main/kotlin/com/raddstream/app/ui/screens/HomeScreen.kt", 1, 100),
        ("App/app/src/main/kotlin/com/raddstream/app/ui/screens/DetailScreen.kt", 1, 100),
        ("App/app/src/main/kotlin/com/raddstream/app/ui/screens/PlayerScreen.kt", 1, 100),
        ("App/app/src/main/kotlin/com/raddstream/app/ui/screens/DownloadsScreen.kt", 1, 100),
        ("App/app/src/main/kotlin/com/raddstream/app/ui/screens/VipUpgradeScreen.kt", 1, 100),
    ]

    manifest = []
    for rel_path, start_line, end_line in files_to_sample:
        fpath = BASE_DIR / rel_path
        if not fpath.exists():
            continue
        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            snippet = "\n".join(lines[max(0, start_line-1):min(total, end_line)])
            manifest.append(f"### File: {rel_path} (Lines {start_line}-{min(total, end_line)} of {total})\n```\n{snippet}\n```\n")
        except Exception as e:
            manifest.append(f"### File: {rel_path} (Error reading: {e})\n")

    return "\n".join(manifest)

def run_deep_audit():
    print("[+] Collecting codebase sample and current project state...")
    code_manifest = build_code_manifest()

    audit_prompt = f"""
You are the Principal Systems Architect and Media Streaming Engineer conducting a rigorous, pure-code review of 'Radd Stream'.
We have a Python stdlib backend (Fast_Fetch) serving an SQLite catalog of 130,000+ posts, 1.38M releases, and 3.78M links across 18 scraped sites, paired with an Android app in Kotlin / Jetpack Compose / ExoPlayer.

Here are exact code slices from the project:
{code_manifest}

Perform a thorough, no-fluff technical audit addressing the following specific areas:
1. **API Contract & Stream / Download Link Generation**:
   - How does `/api/v1/stream` resolve watch links? How do we ensure players get direct `.mp4`/`.mkv`/HLS or PixelDrain direct streams rather than intermediary HTML bridge landing pages (HubCloud, FastDL, GDFLix)?
   - How should download links be served to users?
2. **Missing Metadata, Dead Links & Open-Source Free IMDb Solutions**:
   - For titles with missing genres, posters, or IMDb ratings, what are the best 100% free, keyless or lightweight open-source solutions? (Evaluate: Cinemeta Stremio open API `https://v3-cinemeta.strem.io/meta/{type}/{id}.json`, IMDb suggestion endpoint `https://v3.sg.media-imdb.com/suggestion/`, and TMDB).
3. **Screen-by-Screen UI Evaluation (Netflix / Prime Video Benchmark)**:
   - What UI elements should be visible vs hidden on HomeScreen, DetailScreen, and PlayerScreen?
   - How should Free users vs VIP users experience the app?
4. **Monetization & Hidden Sovereign Earning Methods**:
   - Where should ads be placed (rewarded video for unlocking 1080p/4K, inter-episode interstitials, native banners)?
   - How do link shorteners (ShrinkMe/DropLink) integrate into download mirrors?
   - How are Pakistani payment channels (JazzCash Till/Account, EasyPaisa, Raast instant PKR 200/mo) presented to maximize conversion without chargeback risk?
5. **Exact Action Items & Bugs to Fix**:
   - Provide concrete, line-level code fixes and tasks for our background autonomous workers.
"""

    system_prompt = "You are a master media systems architect and Android / Python performance expert. Deliver an exhaustive, pure-code engineering report with specific algorithms, data models, and step-by-step instructions."

    print("[+] Sending request to top frontier model via OpenRouter...")
    result = call_openrouter(audit_prompt, system_prompt=system_prompt, model="anthropic/claude-3.5-sonnet")

    if not result.get("success"):
        print(f"[-] OpenRouter call failed: {result.get('error')}")
        return False

    out_file = BASE_DIR / "docs" / "OPENROUTER_PURE_CODE_AUDIT.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(f"# 🧠 OpenRouter Deep System Audit ({result.get('model')})\n\n" + result["content"])
    print(f"[✓] Audit successfully saved to {out_file} (Length: {len(result['content'])} characters)")
    return True

if __name__ == "__main__":
    success = run_deep_audit()
    sys.exit(0 if success else 1)
