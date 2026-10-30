#!/usr/bin/env python3
"""
Autonomous OpenRouter Builder for import_mp4moviez.py.
Delegates synthesis to DeepSeek V3 (deepseek/deepseek-chat) on OpenRouter.
100% Python stdlib only.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FAST_FETCH = Path("/opt/radd-stream/Fast_Fetch")
TARGET_FILE = FAST_FETCH / "importers" / "import_mp4moviez.py"
TEST_FILE = FAST_FETCH / "importers" / "test_mp4moviez_import.py"
LOG_FILE = FAST_FETCH / "build_mp4moviez.log"

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
PRIMARY_MODEL = "deepseek/deepseek-chat"
FALLBACK_MODEL = "meta-llama/llama-3.3-70b-instruct"


def log(msg: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")


def call_openrouter(prompt: str, system_prompt: str = "", model: str = PRIMARY_MODEL) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 4000,
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://radd-stream.local",
            "X-Title": "MP4Moviez Builder",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        if model != FALLBACK_MODEL:
            log(f"⚠️ {model} failed ({e}), falling back to {FALLBACK_MODEL}...")
            return call_openrouter(prompt, system_prompt, model=FALLBACK_MODEL)
        raise e


def extract_code(raw_response: str) -> str:
    if "```python" in raw_response:
        parts = raw_response.split("```python")
        return parts[1].split("```")[0].strip()
    elif "```" in raw_response:
        parts = raw_response.split("```")
        return parts[1].split("```")[0].strip()
    return raw_response.strip()


def main():
    log("🚀 Launching OpenRouter Autonomous Worker for import_mp4moviez.py...")

    system_prompt = (
        "You are an elite Python systems architect on the radd-stream media project.\n"
        "INVIOLABLE CONSTRAINTS:\n"
        "1. ZERO external pip packages. 100% Python standard library ONLY (urllib, re, json, sqlite3, html, concurrent.futures).\n"
        "2. Strict Staging Isolation: Target database is strictly /home/ubuntu/radd-stream-data/mp4moviez.db.\n"
        "3. Zero Provenance Leaks: Scrub brand tokens (mp4moviez, mp4moviezhd) from clean_title and synopsis.\n"
        "4. 18+ Content Flagging: Scan tags and synopses. Flag adult content with is_18_plus = 1.\n"
        "5. Output ONLY clean, executable Python code with no conversational markdown chatter."
    )

    spec_prompt = """
Build the complete production scraper module: `Fast_Fetch/importers/import_mp4moviez.py`.

TARGET SITE: https://www.mp4moviez.deal
TARGET STAGING DB: /home/ubuntu/radd-stream-data/mp4moviez.db
SITEMAP: https://www.mp4moviez.deal/sitemap.xml

SITE ARCHITECTURE:
- Movie / series listings at /<id>/<slug>.html or /c<id>/<slug>.html
- Direct download options page at /<slug>-<id>.html
- Download links format: dl.php?id=<id>&q=<240|360|480|720>&title=<slug>
- Quality tiers: 240p, 360p, 480p, 720p, 1080p
- Downstream bridge: Referer header required for dl.php requests

REQUIRED FUNCTIONS TO IMPLEMENT (matching Fast_Fetch conventions):
1. `http_get(url, timeout=30, retries=3)` -> (status, final_url, body)
2. `parse_page(html_or_url, url=None)` -> returns structured post_data dict with clean_title, year, genres, duration, languages, cast_names, poster_url, is_18_plus, releases list
3. `harvest_links(page_url, body)` -> extracts dl.php quality options
4. `resolve_links(post_data, probe=True)` -> resolves downstream CDN mirrors
5. `export_staging(db_path, posts=())` -> commits cleanly into SQLite staging tables (posts, releases, sources)
6. `sync_catalog(limit=None, db_path=DEFAULT_DB_PATH)` -> enumerates from sitemap.xml into sitemap_cache table
7. `crawl_pending(limit=None, db_path=DEFAULT_DB_PATH, workers=4)` -> multi-threaded worker loop
8. CLI `main()` with arguments: sync, crawl, parse, resolve, stats, --workers, --limit, --db

Write the entire, robust, production-ready module now.
"""

    log(f"Tasking {PRIMARY_MODEL} on OpenRouter to synthesize import_mp4moviez.py...")
    for attempt in range(1, 4):
        try:
            raw = call_openrouter(spec_prompt, system_prompt)
            code = extract_code(raw)

            TARGET_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TARGET_FILE, "w", encoding="utf-8") as f:
                f.write(code + "\n")

            compile(code, str(TARGET_FILE), "exec")
            log(f"✅ import_mp4moviez.py compiled successfully ({len(code)} bytes)!")
            break
        except SyntaxError as e:
            log(f"❌ SyntaxError on attempt {attempt}: {e}. Retrying with fix...")
            spec_prompt += f"\n\nFIX SYNTAX ERROR: {e}"
        except Exception as e:
            log(f"❌ Error on attempt {attempt}: {e}")
            time.sleep(3)
    else:
        log("🔥 Failed to build import_mp4moviez.py after 3 attempts.")
        return

    # Now ask OpenRouter to build the unit test suite
    test_prompt = f"""
Write the companion unit test suite: `Fast_Fetch/importers/test_mp4moviez_import.py`.
It must test import_mp4moviez offline using unittest:
- Test title parsing & brand scrubbing (strip mp4moviez watermarks)
- Test 18+ content classifier
- Test size parsing and quality tier extraction
- Test staging database schema creation
- Test harvest_links with sample HTML fixtures
100% offline, pure Python standard library, executes in < 3 seconds.
"""

    log(f"Tasking {PRIMARY_MODEL} to synthesize test_mp4moviez_import.py...")
    try:
        raw_test = call_openrouter(test_prompt, system_prompt)
        test_code = extract_code(raw_test)
        with open(TEST_FILE, "w", encoding="utf-8") as f:
            f.write(test_code + "\n")
        compile(test_code, str(TEST_FILE), "exec")
        log(f"✅ test_mp4moviez_import.py compiled successfully ({len(test_code)} bytes)!")
    except Exception as e:
        log(f"⚠️ Test suite generation error: {e}")

    log("🎉 OpenRouter Autonomous Worker finished build phase!")


if __name__ == "__main__":
    main()
