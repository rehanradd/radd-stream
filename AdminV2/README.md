# Radd Stream Admin Panel v2

Stdlib-only Python, server-rendered HTML, plain CSS, no build step,
no external fonts/scripts/CDNs.

## Status — read first

- The live panel runs from the VM workspace
  (`/home/ubuntu/admin-v2-workspace-20261105`), **not** from this git
  directory. Nothing in this directory is deployed automatically.
  Deploying from git is a separate gated step (backup + live test +
  rollback note) decided by the supervisor.
- **Live data and secrets are excluded from git and must stay that way.**
  Never commit `data-live/` (the live `admin_v2.db`, sessions, TOTP
  secrets), any `*.db`, `backups/`, `*.log`, `__pycache__`, `.env`, or
  certificates. The `.gitignore` entries for this directory enforce it.
- The TOTP encryption key is **not** in this code. The live panel reads
  it from the `RADD_TOTP_KEY` environment variable. `run.py` ships a
  fixture-only default (`workspace-totp-key-change-at-gate`) that must
  never be used live.
- The default disclaimer contact in `admin_v2/store.py`
  (`radddao1@gmail.com`) is the public takedown contact, not a secret.

## Run (workspace only)

    python3 run.py --base-dir ./data --port 8080

Then open http://127.0.0.1:8080/admin/login — but first create the
owner account from a terminal:

    python3 -m admin_v2.setup_owner --base-dir ./data

The setup command prompts for a password with getpass (never echoed,
never printed). It refuses if any admin user already exists.

Live stores (optional, read from env; any WRITE to them needs a
backup before first live use):

    RADD_CATALOG_DB      merged catalog DB (posts, app_remote_config, ...)
    RADD_USER_STATE_DB   user_state.db (accounts + payment ledger)
    RADD_DOMAIN_REGISTRY domain_registry.json
    RADD_STATUS_DIR      directory of <site>_status.json files
    RADD_CERT_PATH       fullchain.pem for the cert-expiry read
    RADD_FLEET_DIR       Fast_Fetch dir (crawler scripts)
    RADD_TOTP_KEY        base64 TOTP encryption key

`--background-jobs` starts the opt-in staggered domain-health +
daily-analytics thread. Off by default.

The systemd unit `radd-stream-admin-v2.service` is a deployment
template with VM-specific paths; it is not started from git.

## Tests

Panel tests are in git but **not** in backend CI (deliberate — the
panel is VM-only code under version control for audit, not a CI gate).
Run them locally from this directory:

    python3 -m unittest discover -s tests
    python3 tools/orphan_audit.py

Expected: all tests pass, 0 orphans. Fixture DBs are created fresh
in temp dirs by the tests (`store.init_catalog_fixture` /
`init_ledger_fixture`); no fixture or live DB file is needed.

## Files

- `admin_v2/services.py` — all business logic, role/validation/audit rules
- `admin_v2/server.py` — HTTP routing, auth, CSRF, rate limits, HTML pages
- `admin_v2/templates.py` — design CSS + layout (phone bottom tabs, desktop sidebar)
- `admin_v2/fixture_app.py` — public-contract client that proves panel changes reach the app
- `admin_v2/pairing.py` — pairing matrix, 74 controls
- `admin_v2/smart.py` — cache/SWR/single-flight, jobs, circuits, direct-first ranking
- `admin_v2/store.py` — SQLite migrations, WAL, single-writer lock, MOCK fixtures
- `admin_v2/setup_owner.py` — first-run owner command (terminal only)
- `admin_v2/security.py` — password hashing, TOTP, redaction of secrets from logs/audit
- `admin_v2/live_stores.py` — read/write access to the live catalog, ledger, registry
- `admin_v2/domain_check.py`, `admin_v2/errors.py`, `admin_v2/recovery.py` — helpers
- `tests/` — unit, API, end-to-end pairing, regressions, orphan audit, phone checklist
- `tools/orphan_audit.py` — orphan check used by the tests

## Live TV channels

`/admin/live-tv` manages `live_tv_registry.json`: add, edit, delete, enable/disable.
Adding or saving a channel probes its stream URL first (HEAD, 1-byte Range GET
fallback); a dead stream refuses unless force is ticked. A duplicate name or
stream URL is a warning, not a refusal. Delete needs the confirm box. Every
write backs up the registry first and is audited. Tests: `tests/test_live_tv_controls.py`.

## Known gaps (honest)

- No live deploy, no nginx/HTTPS wiring, no VM work of any kind from git.
- No full HTML write form on every screen (API is complete; HTML lists + login/search/hide forms only).
- No real 360px device pass (CSS/HTML checks only).
- TOTP secret wrapping is placeholder-grade; TOTP is disabled by default.
