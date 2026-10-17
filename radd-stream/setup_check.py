#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_check.py — One-command bootstrap verifier for radd-stream.
Run this first on any new machine/platform to verify everything is ready.
Usage: python setup_check.py
"""
import sys
import os
from pathlib import Path

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

def check(label, cond, fail_msg="", warn=False):
    status = PASS if cond else (WARN if warn else FAIL)
    print(f"  {status} {label}")
    if not cond and fail_msg:
        print(f"         {fail_msg}")
    return cond

print("\n=== radd-stream Setup Check ===")
print(f"Platform: {sys.platform} | Python: {sys.version.split()[0]}\n")

all_ok = True

# Python version
ok = check(f"Python version >= 3.11 (found {sys.version.split()[0]})",
           sys.version_info >= (3, 11),
           "Install Python 3.11+ from https://python.org or via: sudo apt install python3.11")
all_ok = all_ok and ok

# Standard library modules
for mod in ["sqlite3", "urllib.request", "ssl", "json", "re", "pathlib", "base64", "concurrent.futures"]:
    try:
        __import__(mod)
        check(f"stdlib module '{mod}'", True)
    except ImportError as e:
        check(f"stdlib module '{mod}'", False, str(e))
        all_ok = False

# SSL
import ssl
try:
    ctx = ssl.create_default_context()
    check("SSL context creation", True)
except Exception as e:
    check("SSL context creation", False, str(e))
    all_ok = False

# Network (basic test)
import urllib.request
try:
    with urllib.request.urlopen("https://httpbin.org/status/200", timeout=8) as r:
        check(f"Network connectivity (HTTPS, status={r.status})", r.status == 200)
except Exception as e:
    check("Network connectivity", False, str(e), warn=True)

# File paths
base = Path(__file__).parent
ff_dir = base / "Fast_Fetch"
check("Fast_Fetch/ directory exists", ff_dir.exists(),
      f"Expected at: {ff_dir}")
check("fast_fetch.py exists", (ff_dir / "fast_fetch.py").exists())
check("config.py exists", (ff_dir / "config.py").exists())

# Import fast_fetch
try:
    sys.path.insert(0, str(ff_dir))
    import fast_fetch
    check("fast_fetch.py imports cleanly", True)
except Exception as e:
    check("fast_fetch.py imports cleanly", False, str(e))
    all_ok = False

# DB writeable?
try:
    db_path = ff_dir / "fast_fetch.db"
    import sqlite3
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE IF NOT EXISTS _test (x INTEGER)")
    con.execute("DROP TABLE _test")
    con.close()
    check(f"SQLite DB writable ({db_path.name})", True)
except Exception as e:
    check("SQLite DB writable", False, str(e))
    all_ok = False

print()
if all_ok:
    print("All checks passed! Run: python Fast_Fetch/fast_fetch.py sync --site all")
else:
    print("Some checks failed. Fix the issues above before running the scraper.")
print()
