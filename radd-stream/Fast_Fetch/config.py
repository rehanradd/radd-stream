# -*- coding: utf-8 -*-
"""
config.py — Central project configuration for radd-stream / Fast_Fetch.
Change PROJECT_NAME here and it propagates everywhere.
Supports Windows, Linux, macOS, Replit, VPS, Oracle Cloud.
"""

from pathlib import Path
import os
import sys

# ── Project Identity ──────────────────────────────────────────────────────────
PROJECT_NAME = "radd-stream"          # Change this to rename the project globally
PROJECT_VERSION = "3.1.0"
PROJECT_DESCRIPTION = "World #1 universal streaming scraper & SQLite database engine"
PROJECT_GITHUB = "https://github.com/radddao/radd-stream"

# ── Path Resolution (cross-platform) ─────────────────────────────────────────
# BASE_DIR: the directory containing fast_fetch.py
BASE_DIR = Path(__file__).parent.resolve()

# DB_PATH: can be overridden by environment variable RADD_DB_PATH
_env_db = os.environ.get("RADD_DB_PATH")
if _env_db:
    _p = Path(_env_db)
    if not _p.parent.exists():
        try:
            _p.parent.mkdir(parents=True, exist_ok=True)
            DB_PATH = _p
        except Exception:
            DB_PATH = BASE_DIR / "fast_fetch.db"
    else:
        DB_PATH = _p
else:
    DB_PATH = BASE_DIR / "fast_fetch.db"

# EXPORT_DIR: where to write HTML, JSON, CSV exports
EXPORT_DIR = Path(os.environ.get("RADD_EXPORT_DIR", str(BASE_DIR)))

# LOG_DIR: optional log directory
LOG_DIR = Path(os.environ.get("RADD_LOG_DIR", str(BASE_DIR / "logs")))

# ── Platform Detection ────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX   = sys.platform.startswith("linux")
IS_MACOS   = sys.platform == "darwin"
IS_REPLIT  = "REPL_ID" in os.environ or "REPLIT_DB_URL" in os.environ

# Ensure UTF-8 output everywhere
if IS_WINDOWS:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── HTTP Settings ─────────────────────────────────────────────────────────────
HTTP_TIMEOUT = int(os.environ.get("RADD_HTTP_TIMEOUT", "25"))    # seconds
HTTP_RETRIES = int(os.environ.get("RADD_HTTP_RETRIES", "3"))
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Crawl Settings ────────────────────────────────────────────────────────────
DEFAULT_CRAWL_LIMIT = int(os.environ.get("RADD_CRAWL_LIMIT", "50"))
CRAWL_WORKERS = int(os.environ.get("RADD_CRAWL_WORKERS", "5"))

# ── Cinemeta / Metadata Enrichment ───────────────────────────────────────────
CINEMETA_BASE = "https://v3-cinemeta.strem.io"
CINEMETA_ENABLED = os.environ.get("RADD_CINEMETA", "1") != "0"

# ── Adult Content Filter ──────────────────────────────────────────────────────
# Never set this to True — project policy
ALLOW_18_PLUS = False


def print_config():
    """Print current configuration (for debugging)."""
    print(f"Project  : {PROJECT_NAME} v{PROJECT_VERSION}")
    print(f"Base Dir : {BASE_DIR}")
    print(f"DB Path  : {DB_PATH}")
    print(f"Platform : {'Windows' if IS_WINDOWS else 'Linux' if IS_LINUX else 'macOS' if IS_MACOS else 'Unknown'}"
          f"{' [Replit]' if IS_REPLIT else ''}")
    print(f"Cinemeta : {'enabled' if CINEMETA_ENABLED else 'disabled'}")


if __name__ == "__main__":
    print_config()
