#!/usr/bin/env python3
"""dispatch_worker.py — Robust executor for the 3 Qoder accounts + OpenRouter watchdog.
Usage:
  python3 dispatch_worker.py qoder1 "<prompt>" [model]
  python3 dispatch_worker.py qoder2 "<prompt>" [model]
  python3 dispatch_worker.py qoder3 "<prompt>" [model]
  python3 dispatch_worker.py openrouter "<prompt>" [model]
"""

import sys
import subprocess
import os
import json
import urllib.request
from pathlib import Path

QODER_BIN = "/home/ubuntu/.qoder/entry/qoder"

ACCOUNT_CONFIGS = {
    "qoder1": "/home/ubuntu/.qoder",
    "qoder2": "/home/ubuntu/.qoder_account2",
    "qoder3": "/home/ubuntu/.qoder_account3",
}

def run_qoder(account: str, prompt: str, model: str = "DeepSeek-Flash") -> str:
    config_dir = ACCOUNT_CONFIGS.get(account, "/home/ubuntu/.qoder")
    cmd = [
        QODER_BIN,
        "--config-dir", config_dir,
        "-p",
        "-m", model,
        prompt
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        return proc.stdout if proc.returncode == 0 else f"ERROR: {proc.stderr}\nSTDOUT: {proc.stdout}"
    except Exception as e:
        return f"EXCEPTION: {str(e)}"

def run_openrouter(prompt: str, model: str = "meta-llama/llama-3.3-70b-instruct") -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return "ERROR: OPENROUTER_API_KEY not found"
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a senior full-stack architect and security auditor. Output direct code or actionable audit with zero preamble."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 3000
    }
    
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://radd-stream.local",
            "X-Title": "Radd-Stream Auditor"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"EXCEPTION: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: dispatch_worker.py <qoder1|qoder2|qoder3|openrouter> <prompt> [model]")
        sys.exit(1)
    
    target = sys.argv[1].lower()
    prompt_text = sys.argv[2]
    model_override = sys.argv[3] if len(sys.argv) > 3 else None
    
    if target in ACCOUNT_CONFIGS:
        model = model_override or "DeepSeek-Flash"
        out = run_qoder(target, prompt_text, model)
        print(out)
    elif target == "openrouter":
        model = model_override or "meta-llama/llama-3.3-70b-instruct"
        out = run_openrouter(prompt_text, model)
        print(out)
    else:
        print(f"Unknown target: {target}")
        sys.exit(1)
