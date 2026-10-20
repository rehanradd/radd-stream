#!/usr/bin/env python3
"""
disciple.py — Local Qwen 2.5 Coder Assistant for radd-stream.

Follows THE DAO Directive (Fast_Fetch/DAO.md):
"Save spiritual qi (cloud tokens) by delegating boilerplate, regexes, and unit tests
to the local disciple (qwen2.5-coder:1.5b) running free on Oracle VM CPU."

Zero external dependencies. 100% Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "qwen2.5-coder:1.5b"

SYSTEM_RULES = """You are an expert Python engineer on the radd-stream project.
Strict Inviolable Rules:
1. Use 100% Python standard library only. NEVER import or suggest external pip or npm packages.
2. Clean, concise, and robust code. Always handle edge cases and malformed inputs gracefully.
3. No adult content (is_18_plus = 0 strictly enforced).
4. Output raw Python code inside ```python ... ``` blocks with clear function signatures and docstrings.
"""


def query_disciple(prompt: str, system_override: str | None = None, timeout: int = 180) -> str:
    """Queries local Qwen model via Ollama HTTP API with zero token charges."""
    system = system_override or SYSTEM_RULES
    full_prompt = f"[System Context]\n{system}\n\n[Instruction]\n{prompt}"

    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": True,
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    try:
        chunks = []
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for line in resp:
                if line:
                    data = json.loads(line.decode("utf-8"))
                    chunk = data.get("response", "")
                    chunks.append(chunk)
                    if data.get("done", False):
                        break
        return "".join(chunks).strip()
    except Exception as e:
        return f"[!] Error querying local disciple (Qwen): {e}"


def extract_code_block(response: str) -> str:
    """Extracts code enclosed within markdown code fences, or returns the raw response."""
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", response)
    if m:
        return m.group(1).strip()
    return response.strip()


def draft_code(instruction: str) -> str:
    """Drafts a Python function or snippet using local Qwen."""
    resp = query_disciple(f"Write a Python function for: {instruction}")
    return extract_code_block(resp)


def draft_tests(code_or_spec: str) -> str:
    """Drafts standard library unittest test cases for the given code or specification."""
    prompt = f"Write Python unittest.TestCase tests using standard library only for the following:\n\n{code_or_spec}"
    resp = query_disciple(prompt)
    return extract_code_block(resp)


def main():
    parser = argparse.ArgumentParser(description="Query local Qwen 2.5 Coder Disciple")
    subparsers = parser.add_subparsers(dest="command")

    # code command
    code_p = subparsers.add_parser("code", help="Draft a Python function or snippet")
    code_p.add_argument("prompt", help="Code generation prompt")
    code_p.add_argument("-o", "--out", type=Path, default=None, help="Output file path")

    # tests command
    test_p = subparsers.add_parser("tests", help="Draft unit test cases")
    test_p.add_argument("prompt", help="Target function or specification")
    test_p.add_argument("-o", "--out", type=Path, default=None, help="Output file path")

    # general ask
    ask_p = subparsers.add_parser("ask", help="General coding query")
    ask_p.add_argument("prompt", help="Query prompt")

    args = parser.parse_args()

    if not args.command:
        # Default to ask if arguments provided without subcommand
        if len(sys.argv) > 1:
            print(query_disciple(" ".join(sys.argv[1:])))
        else:
            parser.print_help()
        return

    if args.command == "code":
        code = draft_code(args.prompt)
        if args.out:
            args.out.write_text(code, encoding="utf-8")
            print(f"[✓] Code saved to {args.out}")
        else:
            print(code)

    elif args.command == "tests":
        tests = draft_tests(args.prompt)
        if args.out:
            args.out.write_text(tests, encoding="utf-8")
            print(f"[✓] Tests saved to {args.out}")
        else:
            print(tests)

    elif args.command == "ask":
        print(query_disciple(args.prompt))


if __name__ == "__main__":
    main()
