# -*- coding: utf-8 -*-
"""
config.py — Central project configuration for radd-stream / Fast_Fetch.
Brand constants are read from the ONE brand file at the repo root:
../brand.properties (flat key=value, shared with the Android Gradle build).
PROJECT_NAME is still importable unchanged, so nothing that does
`from config import PROJECT_NAME` today can break.
Supports Windows, Linux, macOS, Replit, VPS, Oracle Cloud.
"""

from pathlib import Path
import configparser
import os
import sys

# ── Brand File (single source of truth for BOTH app and server) ───────────────
# BASE_DIR is defined below from __file__; the brand file lives one level up.
_ROOT_DIR = Path(__file__).resolve().parent.parent
BRAND_FILE = Path(os.environ.get("RADD_BRAND_FILE", str(_ROOT_DIR / "brand.properties")))


def _read_brand(path: Path) -> dict:
    """Parse brand.properties into a flat {key: value} dict (stdlib only).

    The file is sectioned for humans; Python configparser needs the sections,
    and the Gradle build reads the very same file with java.util.Properties.
    Values are returned exactly as written (no % interpolation).
    """
    merged = {}
    if not path.exists():
        return merged
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str          # keep key case: keys are fully qualified
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
        for section in parser.sections():
            for key, value in parser.items(section):
                merged[key] = value.strip()
    except Exception:
        return {}
    return merged


BRAND = _read_brand(BRAND_FILE)


def brand(key: str, fallback: str = "") -> str:
    """Look up one brand.properties key, falling back if the file is absent."""
    value = BRAND.get(key, "")
    return value if value else fallback


def brand_int(key: str, fallback: int) -> int:
    try:
        return int(brand(key, "") or "0")
    except ValueError:
        return fallback


def brand_bool(key: str, fallback: bool) -> bool:
    value = brand(key, "").lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    return fallback


def brand_prefixed(prefix: str) -> dict:
    """All brand keys under a prefix, with the prefix stripped."""
    cut = prefix if prefix.endswith(".") else prefix + "."
    return {k[len(cut):]: v for k, v in BRAND.items() if k.startswith(cut)}


# ── Project Identity ──────────────────────────────────────────────────────────
PROJECT_NAME = brand("server.project.name", "radd-stream")     # rename = edit brand.properties
PROJECT_VERSION = brand("server.project.version", "3.1.0")
PROJECT_DESCRIPTION = brand(
    "server.project.description",
    "World #1 universal streaming scraper & SQLite database engine",
)
PROJECT_GITHUB = brand("server.project.github", "https://github.com/radddao/radd-stream")

# Consumer-facing brand strings (the Android app reads the same keys)
BRAND_APP_NAME = brand("identity.name", "RADD Stream")
BRAND_APP_NAME_SHORT = brand("identity.name.short", BRAND_APP_NAME)
BRAND_APP_VERSION = brand("identity.version.name", "0.1.0")
BRAND_CLIENT_NAME = brand("network.client_name", "radd-stream-android")
BRAND_TAGLINE = brand("identity.tagline", "")
BRAND_COPY = brand_prefixed("copy")
BRAND_FEATURES = {k: brand_bool("features." + k, True) for k in brand_prefixed("features")}
BRAND_TTL = {k: brand_int("cache.ttl." + k, 0) for k in brand_prefixed("cache.ttl")}
BRAND_STORAGE = {k: brand_int("storage." + k, 0) for k in brand_prefixed("storage") if k != "ttl"}
BRAND_COLORS_DARK = brand_prefixed("colors.dark")
BRAND_COLORS_LIGHT = brand_prefixed("colors.light")

# ── Path Resolution (cross-platform) ─────────────────────────────────────────
# BASE_DIR: the directory containing fast_fetch.py
BASE_DIR = Path(__file__).parent.resolve()

# DB filename also comes from the brand file (default keeps the historical name)
_DB_FILENAME = brand("server.database.filename", "fast_fetch.db")

# DB_PATH: can be overridden by environment variable RADD_DB_PATH
_env_db = os.environ.get("RADD_DB_PATH")
if _env_db:
    _p = Path(_env_db)
    if not _p.parent.exists():
        try:
            _p.parent.mkdir(parents=True, exist_ok=True)
            DB_PATH = _p
        except Exception:
            DB_PATH = BASE_DIR / _DB_FILENAME
    else:
        DB_PATH = _p
else:
    DB_PATH = BASE_DIR / _DB_FILENAME

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
# Defaults come from brand.properties ([storage]); env vars still win.
HTTP_TIMEOUT = int(os.environ.get("RADD_HTTP_TIMEOUT", str(brand_int("storage.http_timeout_seconds", 25))))
HTTP_RETRIES = int(os.environ.get("RADD_HTTP_RETRIES", str(brand_int("storage.http_retries", 3))))
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
# Never set this to True — project policy. brand.properties can only turn the
# filter ON (features.adult_filter_enforced); a 'false' there is ignored.
ALLOW_18_PLUS = False


def print_config():
    """Print current configuration (for debugging)."""
    print(f"Project  : {PROJECT_NAME} v{PROJECT_VERSION}")
    print(f"Brand    : {BRAND_APP_NAME} v{BRAND_APP_VERSION} ({'loaded' if BRAND else 'MISSING'}: {BRAND_FILE})")
    print(f"Base Dir : {BASE_DIR}")
    print(f"DB Path  : {DB_PATH}")
    print(f"Platform : {'Windows' if IS_WINDOWS else 'Linux' if IS_LINUX else 'macOS' if IS_MACOS else 'Unknown'}"
          f"{' [Replit]' if IS_REPLIT else ''}")
    print(f"Cinemeta : {'enabled' if CINEMETA_ENABLED else 'disabled'}")


if __name__ == "__main__":
    print_config()
