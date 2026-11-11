"""Run the Admin Panel v2 server (NOT a live deploy).

    python3 run.py --base-dir ./data --port 8080

Data (admin_v2.db + fixture DBs) lives under --base-dir. Fixture DBs
contain MOCK works/accounts only and must never be copied to a live
system as real data. Live deployment is a separate gated step:
branch + hosted CI + backup + live test + rollback note.

Live stores (optional, read from env; any WRITE to them needs a
backup before first live use — see the Phase 2 handoff):
    RADD_CATALOG_DB      merged catalog DB (posts, app_remote_config, ...)
    RADD_USER_STATE_DB   user_state.db (accounts + payment ledger)
    RADD_DOMAIN_REGISTRY domain_registry.json
    RADD_STATUS_DIR      directory of <site>_status.json files
    RADD_CERT_PATH       fullchain.pem for the cert-expiry read
    RADD_FLEET_DIR       Fast_Fetch dir (crawler scripts)
    RADD_TOTP_KEY        base64 TOTP encryption key (rotated 2026-11-11;
                         the shipped default must never be used live).
  --background-jobs starts the opt-in staggered domain-health +
  daily-analytics thread (OD-10). Off by default.
"""
import argparse
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from admin_v2.domain_check import check_domain
from admin_v2.live_stores import check_stream_url
from admin_v2.server import serve
from admin_v2.services import Service


def _totp_key():
    """TOTP encryption key from RADD_TOTP_KEY (base64), or None to let
    the Service use its default (fixture only — never live)."""
    raw = os.environ.get("RADD_TOTP_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception:
        return None
    return key if len(key) >= 16 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default="./data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--strict-host", action="store_true",
                        help="Gate mode: /admin only on the panel domain over HTTPS.")
    parser.add_argument("--background-jobs", action="store_true",
                        help="Start the opt-in staggered domain-health + daily analytics thread.")
    args = parser.parse_args()
    totp_key = _totp_key()
    svc = Service(
        args.base_dir,
        totp_key=totp_key if totp_key is not None else b"workspace-totp-key-change-at-gate",
        live_catalog_path=os.environ.get("RADD_CATALOG_DB"),
        live_ledger_path=os.environ.get("RADD_USER_STATE_DB"),
        live_registry_path=os.environ.get("RADD_DOMAIN_REGISTRY"),
        live_status_dir=os.environ.get("RADD_STATUS_DIR"),
        live_cert_path=os.environ.get("RADD_CERT_PATH"),
        live_fleet_base_dir=os.environ.get("RADD_FLEET_DIR"),
    )
    if args.background_jobs:
        svc.start_background_jobs(domain_checker=check_domain)
    serve(svc, host=args.host, port=args.port, strict_host=args.strict_host,
          domain_checker=check_domain, stream_checker=check_stream_url)


if __name__ == "__main__":
    main()
