#!/usr/bin/env python3
"""
ai — Fast, Unlimited, Free Local AI Assistant for radd-stream.
Powered by Ollama (qwen2.5-coder:1.5b) running locally on Oracle VM CPU.
Zero external API calls, zero cost, completely offline & unlimited.
"""
import sys
import json
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5-coder:1.5b"

SYSTEM_CONTEXT = """You are a pair programming partner on the radd-stream project.
Guidelines:
1. Python standard library only (no external pip dependencies).
2. Production SQLite databases are in /home/ubuntu/radd-stream-data/.
3. Staging DBs must never be merged into fast_fetch.db without confirmation.
4. Keep answers concise, direct, and actionable.
"""

def stream_query(prompt: str):
    full_prompt = f"[System Context]\n{SYSTEM_CONTEXT}\n[User Query]\n{prompt}"
    payload = json.dumps({
        "model": MODEL,
        "prompt": full_prompt,
        "stream": True
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                if line:
                    data = json.loads(line.decode("utf-8"))
                    chunk = data.get("response", "")
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
        sys.stdout.write("\n")
    except Exception as e:
        sys.stderr.write(f"Error querying local AI: {e}\n")

def interactive():
    print("=" * 60)
    print(" 🌌 Unlimited Free Local AI (qwen2.5-coder:1.5b)")
    print(" Type your question below, or type 'exit' / Ctrl+C to quit.")
    print("=" * 60)
    while True:
        try:
            prompt = input("\n🤖 ai> ").strip()
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit", "q"):
                break
            stream_query(prompt)
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        stream_query(query)
    else:
        interactive()

if __name__ == "__main__":
    main()
