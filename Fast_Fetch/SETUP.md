# SETUP.md — Platform-Specific Setup Guide

> Complete setup instructions for every platform: Windows, Linux/VPS, Replit, GitHub Codespace, Oracle Cloud.

---

## Prerequisites (All Platforms)

- **Python 3.11+** — the only requirement
- Internet connection
- No pip install needed — zero external dependencies

---

## Verification Commands

Run these from the repository root after setup:

```bash
python -S Fast_Fetch/test_database.py
python -S Fast_Fetch/test_vidout.py
python setup_check.py
```

For an internet-backed parser and database-ingestion audit:

```bash
python Fast_Fetch/test_all_sites.py
```

The live audit uses a temporary database and does not write sample content into
the local catalog.

---

## Windows (Local Machine)

### Option A — With Git installed
```cmd
:: Clone the repo
git clone https://github.com/rehanradd/radd-stream.git
cd radd-stream

:: Verify setup
python setup_check.py

:: First sync (populates URL index)
run.bat sync --site all

:: Fetch a specific movie
run.bat fetch "https://multimovies.garden/movie/pathaan-2023/"

:: Open the HTML dashboard
run.bat export-html
:: Then open Fast_Fetch/database_view.html in your browser
```

### Option B — Without Git (direct download)
1. Go to: `https://github.com/rehanradd/radd-stream`
2. Click **Code** → **Download ZIP**
3. Extract to `C:\radd-stream\` (or any folder)
4. Open PowerShell in that folder:
```powershell
python setup_check.py
run.bat sync --site all
```

### Push changes to GitHub

Use Git with GitHub CLI or the operating system's secure credential manager on
Windows. In Replit, use the temporary askpass flow in
[`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md). Do not put a token in a
Git URL, command argument, source file, or log. The old
`github_push.py`, `push.py`, and `emergency_push.py` uploaders are retired; the
warning stubs that replaced them have been deleted from the repo root. Use Git on a
task branch as described in `SESSION.md`.

### Environment Variables (Windows)
```powershell
$env:RADD_DB_PATH = "D:\my-data\streams.db"
$env:RADD_HTTP_TIMEOUT = "30"
run.bat sync --site all
```

---

## Linux / Ubuntu VPS / Debian

### Ubuntu 22.04+ (Python 3.11 built-in)
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python (if not present)
sudo apt install python3.11 python3.11-venv git -y

# Clone repo
git clone https://github.com/rehanradd/radd-stream.git
cd radd-stream

# Verify
python3 setup_check.py

# First sync
bash run.sh sync --site all

# Crawl 100 posts
bash run.sh crawl 100

# Generate HTML dashboard
bash run.sh export-html
```

### Ubuntu 20.04 (needs Python 3.11 via deadsnakes)
```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install python3.11 -y
python3.11 setup_check.py  # Use python3.11 explicitly
```

### Run as Background Service (systemd)
```bash
# Create service file
sudo nano /etc/systemd/system/radd-stream.service
```
```ini
[Unit]
Description=radd-stream auto-crawl service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/radd-stream
ExecStart=/bin/bash run.sh crawl 50
Restart=on-failure
RestartSec=3600

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable radd-stream
sudo systemctl start radd-stream
```

### Cron Auto-Crawl
```bash
crontab -e
# Add (crawl every 6 hours):
0 */6 * * * cd /home/ubuntu/radd-stream && bash run.sh crawl 100 >> /home/ubuntu/radd-stream.log 2>&1
```

---

## Existing Oracle Cloud VM (Ubuntu)

The existing project VM is documented in
[`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md). This setup uses that
already-provisioned server and free tools; do not create paid infrastructure,
a domain, or third-party services without approval. Oracle free-tier eligibility
and billing are controlled by the account and are not guaranteed here.

### Setup

Current target:

- Web host: `http://92.4.95.252/` (plain HTTP; no domain/TLS configured).
- SSH: `ubuntu@92.4.95.252` on port 22, using the Replit Configurations
  environment variable `ORACLE_SSH_KEY`.
- Last verified OS/Python: Ubuntu 24.04.4 LTS / Python 3.12.3.
- Nginx and Supervisor are installed; Nginx had no listener on port 80 after
  cleanup, and the old project/database backup were removed.

Use the runbook's SSH procedure rather than pasting a key into a command or
chat. The backend does not need `pip`; use the system Python. Before public
HTTP is enabled, check the Oracle VCN ingress rule for TCP 80, keep TCP 22
available for administration, and do not open port 8080 directly.

```bash
# Verify the repository and Python environment before deploying
python3 setup_check.py
python3 -S Fast_Fetch/test_database.py
python3 -S Fast_Fetch/test_vidout.py

# The database is local, ignored by Git, and starts empty on a fresh deployment.
# Store it outside the code directory and initialize/populate it deliberately.
RADD_DB_PATH=/home/ubuntu/radd-stream-data/fast_fetch.db \
  python3 Fast_Fetch/fast_fetch.py stats
```

Do not start the API publicly until the protections in
[`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md) are in place. The API has
unauthenticated fetch/heal/resolve routes, and the requested HTTP URL is not
encrypted. The Android release build requires HTTPS; HTTP is suitable only for
browser/debug testing.

---

## Replit

### Method 1 — Import from GitHub (Recommended)
1. Go to **https://replit.com** → New Repl
2. Click **Import from GitHub**
3. URL: `https://github.com/rehanradd/radd-stream`
4. Select **Python** template
5. Replit reads `.replit` file automatically — press **Run** or use Shell:

```bash
python Fast_Fetch/fast_fetch.py sync --site all
python Fast_Fetch/fast_fetch.py stats
```

### Replit Secrets (Environment Variables)
In Replit → Secrets panel, add:
```
Key: RADD_DB_PATH
Value: /home/runner/radd-stream/Fast_Fetch/fast_fetch.db
```

### Replit Always-On
- Enable **Always On** in Replit settings to keep the DB persistent
- Use `background_task` in `.replit` to run auto-crawl

### Replit Shell Commands
```bash
# Sync all sites
python Fast_Fetch/fast_fetch.py sync --site all

# Search
python Fast_Fetch/fast_fetch.py search "avengers"

# Fetch a post
python Fast_Fetch/fast_fetch.py fetch "https://vegamovies.gallery/avengers-endgame-2019/"

# Stats
python Fast_Fetch/fast_fetch.py stats
```

---

## GitHub Codespace

### Setup
1. Go to: `https://github.com/rehanradd/radd-stream`
2. Click **Code** (green button) → **Codespaces** → **New codespace**
3. Wait ~30 seconds for environment to load (Python 3.11+ pre-installed)
4. Open Terminal:

```bash
python setup_check.py
bash run.sh sync --site all
```

### Persistent Storage
- Codespace storage persists between sessions (up to 15GB free)
- DB is stored in workspace, survives restarts
- Stop/start codespace to save compute minutes (60h/month free)

---

## GitHub Actions (Automated Crawl)

Auto-crawl via GitHub Actions (free 2000 min/month):

Create `.github/workflows/auto-crawl.yml`:
```yaml
name: Auto Crawl

on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:         # Manual trigger

jobs:
  crawl:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Download DB artifact
        uses: actions/download-artifact@v3
        with:
          name: database
          path: Fast_Fetch/
        continue-on-error: true  # OK if no previous DB

      - name: Sync and crawl
        run: |
          python Fast_Fetch/fast_fetch.py sync --site all
          python Fast_Fetch/fast_fetch.py crawl 50
          python Fast_Fetch/fast_fetch.py stats
      
      - name: Upload DB artifact
        uses: actions/upload-artifact@v3
        with:
          name: database
          path: Fast_Fetch/fast_fetch.db
          retention-days: 30
```

> **Note:** DB file is stored as GitHub artifact (max 500MB, kept 30 days). For permanent storage, use Oracle Cloud or Replit Always-On.

---

## Any New Machine — One-Command Bootstrap

```bash
# Linux/Mac:
curl -L https://raw.githubusercontent.com/rehanradd/radd-stream/main/run.sh | bash -s sync

# Or clone + run:
git clone https://github.com/rehanradd/radd-stream && cd radd-stream && python3 setup_check.py && bash run.sh sync --site all
```

---

## Changing the Project Name

1. Edit `Fast_Fetch/config.py`:
   ```python
   PROJECT_NAME = "my-movie-db"  # Change this
   ```
2. Optionally rename the DB:
   ```python
   DB_PATH = BASE_DIR / "my-movie-db.db"
   ```
3. That's it. No other files need changing.

---

## Common Issues & Fixes

### "Python not found"
```bash
# Linux: install python3.11
sudo apt install python3.11 -y

# Windows: download from https://python.org
# Then check: python --version
```

### "SSL certificate error" / "CERTIFICATE_VERIFY_FAILED"
The engine uses a permissive SSL context (`CERT_NONE`) — this error should never occur. If it does:
```python
# In fast_fetch.py, SSL_CONTEXT is already set to:
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE
```

### "SyntaxError" on import
```bash
python --version  # Must be 3.11+
# Python 3.10 doesn't support: dict | None, match statements
```

### Site returns HTTP 403
```bash
# Domain has rotated — update it:
python Fast_Fetch/fast_fetch.py set-domain vegamovies https://vegamovies.newdomain.com
# Then retry
python Fast_Fetch/fast_fetch.py sync --site vegamovies
```

### DB is empty / "no such table"
```bash
# Run sync first — it creates all tables automatically
python Fast_Fetch/fast_fetch.py sync --site all
```

### "UnicodeEncodeError" on Windows
- Fixed automatically at import via `sys.stdout.reconfigure(encoding='utf-8')`
- If running from old CMD: use PowerShell instead, or set `PYTHONIOENCODING=utf-8`
