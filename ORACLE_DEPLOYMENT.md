# Oracle and GitHub Operations Runbook

This is the operational reference for the existing Radd Stream Oracle VM and
GitHub repository. Recheck the host before each deployment; IP addresses,
firewall rules, and installed services can change.

## Cost and host

The deployment target is the existing Oracle VM. The operating preference is
to use the current VM and free tools only: do not provision paid compute,
storage, a paid domain, or another paid service without explicit approval.
Oracle account charges and free-tier eligibility are controlled outside this
repository and are not guaranteed by this guide.

| Item | Last verified value |
|---|---|
| Repository | `https://github.com/radddao/radd-stream` |
| Default GitHub branch | `main` |
| Oracle public IP | `92.4.95.252` |
| Intended HTTP base URL | `http://92.4.95.252/` |
| SSH account and port | `ubuntu@92.4.95.252`, TCP 22 |
| Hostname | `instance-20260424-0405` |
| Operating system | Ubuntu 24.04.4 LTS |
| Python | Python 3.12.3; the backend uses only the standard library |
| Privileges | `sudo -n` worked for the `ubuntu` account |
| Installed services | Nginx, Supervisor, and `radd-stream.service` are active; backend listens on `127.0.0.1:8080` |

The 2026-10-15 check below is historical and was superseded by a read-only
inspection on 2026-10-17. The latest check found SSH on port 22, Nginx on port
80, and the Python backend on loopback port 8080. The `/opt` directory also
contains `unified-monitoring-agent` and `warp-watchdog`; leave these unrelated
directories alone.

The old RaddFlix project, its database backup, its site/service configuration,
the GitHub Actions runner, Flutter, and JADX were removed at the user's
request. Do not expect the old project, database, runner, or SDKs to be present.
Supervisor and Nginx themselves were preserved.

## Replit environment variables and credential handling

The user's permanent project choice is to configure these as environment
variables in Replit Configurations, not Replit Secrets:

| Variable | Use |
|---|---|
| `ORACLE_SSH_KEY` | SSH private key for the Oracle `ubuntu` account |
| `GITHUB_TOKEN` | GitHub repository access from Replit |

Verify only whether the variable names exist; never read or print their values.
Do not put values in this file, source code, Git URLs, command-line arguments,
logs, GitHub Actions artifacts, or chat. Do not copy `GITHUB_TOKEN` to the
Oracle VM. If a variable is missing, report its name and wait; do not ask the
user to move it to Secrets or paste its value in chat.

## SSH host-key fingerprint record

For production changes or deployment, compare the server fingerprint with
Oracle Cloud Console before connecting, and record the independently confirmed
key type, fingerprint, and verification date here. For a user-authorized
read-only inspection when Console verification is unavailable, follow the
limited TOFU procedure recorded below and label it as such. A fingerprint
learned only through `ssh-keyscan` is not independent verification.

The following keys were observed from `92.4.95.252:22` on 2026-10-16 and
re-observed during a read-only SSH session on 2026-10-17:

| Key type | Observed SHA256 fingerprint | Status |
|---|---|---|
| ED25519 | `SHA256:3FUGOWcK08jLYM6en6+lz806EsUI/iBWGAY0C620qME` | Matched guest key file in the same session; not Console-verified |
| ECDSA | `SHA256:VL9EVg/rDaO3ANsu9dlxi/qGuWVO5k/Bq8x0108IlLk` | Matched guest key file in the same session; not Console-verified |
| RSA | `SHA256:qXeS+ioA/9zF+olehkbqzoGHootLRMJQFMAWL7nKttQ` | Matched guest key file in the same session; not Console-verified |

The owner asked for the read-only inspection to proceed without requiring them
to obtain a fingerprint. The first connection therefore used temporary
`StrictHostKeyChecking=accept-new`. The fingerprints presented by SSH matched
the corresponding `/etc/ssh/ssh_host_*_key.pub` fingerprints read through that
same connection. This is a TOFU consistency check, not independent
authentication and not confirmation from Oracle Cloud Console. Use the saved
fingerprints to detect changes on later read-only checks; stop if a key changes.
This record does not authorize production changes or deployment.

## Latest read-only Oracle check — 2026-10-17

- Host: `instance-20260424-0405`, Ubuntu 24.04.4 LTS; `sudo -n` works for
  `ubuntu`.
- `radd-stream.service`, Nginx, and Supervisor were active. The service runs
  `/opt/radd-stream/Fast_Fetch/fast_fetch.py serve --host 127.0.0.1 --port 8080`.
- No application `.git` metadata was found in `/opt/radd-stream` or the
  alternate application locations searched. The only `.git` directory found
  was the unrelated `/home/ubuntu/.nvm/.git`.
- `/opt/radd-stream/Fast_Fetch/import_multimovies.py` and
  `test_multimovies_import.py` are absent. The deployed
  `/opt/radd-stream/Fast_Fetch/fast_fetch.py` SHA-256 is
  `2c2b41143dbd57c3735ff396abb0270a7961cfa67d9b214cb34eebb879d07161`.
- That source hash matched none of the 11 `fast_fetch.py` revisions compared
  from the fetched Git refs. The deployed file's exact commit cannot be
  established from the Oracle filesystem.
- This inspection was read-only. No app files, database, service, or Nginx
  settings were changed.

## Connect from Replit to Oracle

Run this from the Replit Shell. The key is normalized into a temporary
permission-restricted file because the configured PEM body may need line
wrapping. The script does not print the key and removes its temporary file on
exit.

```bash
set +x
umask 077
key_file="$(mktemp)"
trap 'rm -f "$key_file"' EXIT

python3 - "$key_file" <<'PY'
import os
import re
import sys

raw = os.environ.get("ORACLE_SSH_KEY", "")
match = re.fullmatch(
    r"(-----BEGIN ([A-Z0-9 ]+)-----)(.*?)(-----END \2-----)",
    raw,
    re.S,
)
if not match:
    raise SystemExit("ORACLE_SSH_KEY is not a supported PEM private key.")

header, _, body, footer = match.groups()
body = "".join(body.split())
if not re.fullmatch(r"[A-Za-z0-9+/=]+", body):
    raise SystemExit("The PEM body is invalid.")

with open(sys.argv[1], "w", encoding="ascii") as key_file:
    key_file.write(
        header + "\n"
        + "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
        + "\n" + footer + "\n"
    )
PY
chmod 600 "$key_file"

ssh -i "$key_file" -p 22 \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  ubuntu@92.4.95.252 \
  'hostname; id -un; sudo -n true'
```

`accept-new` records a new key; it does not independently verify the server
identity. On a later read-only connection, compare the presented key type and
fingerprint to the saved record before proceeding. Stop if it changes. Do not
use `StrictHostKeyChecking=no` or disable host-key checks. The saved record is
TOFU, not OCI Console verification.

### SSH troubleshooting

- `Load key ... invalid format`: confirm `ORACLE_SSH_KEY` contains the complete
  private PEM, including matching `BEGIN` and `END` lines. The normalizer above
  removes whitespace from the PEM body and wraps it at 64 characters. Do not
  print or paste the key anywhere.
- `Permission denied (publickey)`: this instance uses `ubuntu`; verify that the
  matching public key is installed on the instance and that the secret is the
  corresponding private key.
- Connection timeout/refused: verify the instance is running and its Oracle
  VCN security list or network security group permits inbound TCP 22. SSH on
  port 22 was reachable at the last check.
- Host-key warning: stop and compare the key type and fingerprint with the
  saved record. A changed key requires independent verification; do not bypass
  the warning.
- A failed SSH attempt does not authorize deleting or changing remote files.

## Connect to GitHub from Replit

Use the plain HTTPS repository URL and let Git's askpass helper read the token
from the environment. This keeps the token out of the remote URL, terminal
output, and persistent credential stores.

```bash
set +x
umask 077
auth_dir="$(mktemp -d)"
trap 'rm -rf "$auth_dir"' EXIT
mkdir -p "$auth_dir/home"
cat > "$auth_dir/askpass" <<'ASKPASS'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\n' 'x-access-token' ;;
  *) printf '%s\n' "${GITHUB_TOKEN:?GITHUB_TOKEN is missing from Replit Configurations}" ;;
esac
ASKPASS
chmod 700 "$auth_dir/askpass"

GIT_ASKPASS="$auth_dir/askpass" \
GIT_TERMINAL_PROMPT=0 \
GIT_CONFIG_NOSYSTEM=1 \
HOME="$auth_dir/home" \
git -c credential.helper= clone \
  https://github.com/radddao/radd-stream.git
```

For `fetch` or `push`, use the same environment variables and temporary
askpass helper around the relevant Git command. Keep the remote URL free of
credentials; do not use `https://TOKEN@github.com/...`, `git config
credential.helper store`, shell tracing, or `GIT_CURL_VERBOSE`. The token must
have the repository access needed for the operation. If access fails, check
that the Replit Secret exists and has the required repository permissions;
never print the token to diagnose it. Respect branch protection and push to a
feature branch or use a pull request when direct pushes are not allowed.

The legacy `push.py`, `github_push.py`, and `emergency_push.py` uploaders are
retired and their command-line entrypoints are disabled. They used broad
GitHub API writes and could target `main`; the emergency uploader skipped
tests. For new work, use Git with the temporary askpass helper above, commit
reviewed files on a task branch, and run the documented tests directly.

## Deployment layout and current limitations

The intended free, no-domain layout is:

```text
Client -> http://92.4.95.252:80 (Nginx) -> Python API on 127.0.0.1:8080
```

The Python backend is the part that runs on Oracle. The Android app is built
separately by GitHub Actions; it is not installed as a server process. Keep the
SQLite database outside the Git checkout, for example:
`/home/ubuntu/radd-stream-data/fast_fetch.db`. The database is gitignored and
the deleted backup is not recoverable from this VM. A new catalog must be
initialized and populated after deployment.

Important current behavior:

- `python3 Fast_Fetch/fast_fetch.py serve --port 8080` starts the dashboard/API.
  The default bind is `127.0.0.1`: nginx is the only thing that faces the network.
  The CLI accepts `--host`; pass an explicit address only when this process really
  must be reachable from outside the box. The Oracle systemd service uses
  `serve --host 127.0.0.1 --port 8080`. Do not open inbound TCP 8080.
- The API has no authentication. Routes such as `/api/fetch`, `/api/health-check`,
  `/api/heal`, `/api/v1/stream`, and `/api/m3u` can trigger outbound work or expose
  resolved URLs, so the public port answers 404 for the ingest-and-probe ones
  (`viewer.OPERATOR_ONLY_ROUTES`) and only the operator port on 127.0.0.1:8081
  serves them; nginx never proxies them. Browser CORS is an explicit empty
  allow-list (`redact.CORS_ALLOW_ORIGINS`), not a wildcard. Public metadata
  access should be limited to `/client`, `/api/v1/posts`, and
  `/api/v1/stats`; deny other `/api/` routes at Nginx unless they have been
  reviewed and secured. In particular, `/api/v1/posts/{id}` returns complete
  database rows, including source URLs, and must remain blocked until it is
  redacted or protected.
- The requested bare-IP URL uses plain HTTP. HTTP is not encrypted. Never send
  passwords, tokens, private keys, or other sensitive data over it.
- The Android debug build permits cleartext HTTP for development, but the
  release configuration requires HTTPS. Do not treat the bare-IP HTTP endpoint
  as a production Android release endpoint.
- Oracle's VCN security list/network security group is separate from the VM.
  SSH was reachable, but TCP 80 was not listening at the last check. Allow
  inbound TCP 80 in the Oracle Console before expecting the public URL to work;
  keep TCP 22 reachable for administration. Do not add a public ingress rule
  for port 8080.
- This VM had no HTTP/HTTPS listener after cleanup. Nginx is installed and
  active, but a new Nginx site configuration and the Python service must be
  installed and verified before the URL can respond.

## Safe deployment checklist

1. Connect with the SSH procedure above and recheck hostname, OS, Python
   version, available disk space, `sudo -n true`, and active listeners. Do not
   assume the baseline table is still current.
2. Use `/opt/radd-stream` for application code and a separate persistent
   directory for SQLite. Run the service as `ubuntu`, not root.
3. Obtain the intended Git revision in Replit using `GITHUB_TOKEN` from
   Replit Configurations. For a
   private repository, transfer a committed source archive over SSH; do not
   install `GITHUB_TOKEN` on Oracle. Keep `.git` and the database out of the
   deployed archive.
4. Verify Python setup and run:
   `python3 -S Fast_Fetch/test_database.py`,
   `python3 -S Fast_Fetch/test_vidout.py`, and `python3 setup_check.py`.
5. Run the backend with `serve --host 127.0.0.1 --port 8080`; do not expose
   port 8080. At Nginx, allow only the catalog routes listed above and deny
   fetch/heal/health-check/stream/playlist operations.
6. Configure Nginx on port 80 to proxy the intended public routes to the local
   backend. Test with `sudo nginx -t` before reloading Nginx.
7. Confirm Oracle ingress permits TCP 80. Check locally first with
   `curl -i http://127.0.0.1/`, then from outside with
   `curl -i http://92.4.95.252/`.
8. After deployment, verify the systemd service, Nginx, the database path, and
   `/api/v1/stats`. Populate the new catalog only after the service is stable.

## Reference deployment configuration

Use this for the current domainless, catalog-only public deployment. Keep the
temporary `key_file` from the SSH procedure in the same Replit Shell session.
Replace `/path/to/radd-stream` with the checkout path. The archive contains
tracked source only; it does not transfer `.git`, ignored databases, or the
GitHub token.

```bash
REPO_DIR=/path/to/radd-stream

ssh -i "$key_file" -p 22 -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new ubuntu@92.4.95.252 \
  'sudo install -d -o ubuntu -g ubuntu -m 0755 /opt/radd-stream &&
   sudo install -d -o ubuntu -g ubuntu -m 0700 /home/ubuntu/radd-stream-data'

git -C "$REPO_DIR" archive --format=tar HEAD |
  ssh -i "$key_file" -p 22 -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=accept-new ubuntu@92.4.95.252 \
    'tar -xf - -C /opt/radd-stream'
```

Before enabling the service, initialize and populate the fresh SQLite catalog
as the unprivileged service user:

```bash
ssh -i "$key_file" -p 22 -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new ubuntu@92.4.95.252 \
  'sudo -u ubuntu env RADD_DB_PATH=/home/ubuntu/radd-stream-data/fast_fetch.db \
     /usr/bin/python3 -S /opt/radd-stream/setup_check.py &&
   sudo -u ubuntu env RADD_DB_PATH=/home/ubuntu/radd-stream-data/fast_fetch.db \
     /usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py sync --site all &&
   sudo -u ubuntu env RADD_DB_PATH=/home/ubuntu/radd-stream-data/fast_fetch.db \
     /usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py crawl 50'
```

The sync/crawl makes outbound requests to configured public sites. Review the
source list and respect its terms before running it; it does not download media
files.

Create `/etc/systemd/system/radd-stream.service`:

```ini
[Unit]
Description=Radd Stream metadata API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/radd-stream
Environment=PYTHONUNBUFFERED=1
Environment=RADD_DB_PATH=/home/ubuntu/radd-stream-data/fast_fetch.db
ExecStart=/usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py serve --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
```

Create `/etc/nginx/conf.d/radd-stream-rate-limit.conf` (Nginx includes
`conf.d/*.conf` inside its `http` context on the verified host):

```nginx
limit_req_zone $binary_remote_addr zone=radd_stream:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=radd_stream_v2:10m rate=4r/s;
```

Create `/etc/nginx/sites-available/radd-stream` and enable it. This exposes the
PWA and only the list/statistics metadata endpoints: `/client`,
`/api/v1/posts`, and `/api/v1/stats`. Every other `/api/` route is denied:

```nginx
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 1m;
    limit_req zone=radd_stream burst=30 nodelay;
    limit_req_status 429;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_hide_header Access-Control-Allow-Origin;
    proxy_read_timeout 30s;

    location = / {
        limit_except GET HEAD { deny all; }
        return 302 /client;
    }
    location = /client {
        limit_except GET HEAD { deny all; }
        proxy_pass http://127.0.0.1:8080;
    }
    location = /api/v1/posts {
        limit_except GET HEAD { deny all; }
        proxy_pass http://127.0.0.1:8080;
    }
    location = /api/v1/stats {
        limit_except GET HEAD { deny all; }
        proxy_pass http://127.0.0.1:8080;
    }
    # v2 is the same deny-by-default projection on a versioned surface, and it is
    # a verb-first API (`POST /play`, `POST /episodes/{id}/offset`), so it must not
    # inherit the GET-only rule. Its bucket is tighter than v1's: one `/play` costs
    # an upstream resolve, which is the most expensive thing this box can do.
    location /api/v2/ {
        limit_req zone=radd_stream_v2 burst=20 nodelay;
        include /etc/nginx/proxy_params;
        proxy_pass http://127.0.0.1:8080;
        proxy_connect_timeout 5s;
        proxy_read_timeout 15s;
    }
    location ^~ /api/ {
        return 403;
    }
    location / {
        return 404;
    }
}
```

Enable and verify the service and proxy:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now radd-stream.service
sudo ln -sfn /etc/nginx/sites-available/radd-stream /etc/nginx/sites-enabled/radd-stream
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl --no-pager --full status radd-stream nginx
ss -ltn
curl -i http://127.0.0.1/
curl -i http://127.0.0.1/client
curl -i http://127.0.0.1/api/v1/stats
curl -i http://127.0.0.1/api/v1/posts?limit=1
curl -i http://127.0.0.1/api/fetch
```

Expected: root redirects to `/client`; `/client`, stats, and posts return 200;
`/api/fetch`, `/api/v1/posts/{id}`, and all other non-allowlisted `/api/` paths
return 403; the Python listener is `127.0.0.1:8080` and is not a public
listener. Finally test
`http://92.4.95.252/` from outside the VM. If local tests pass but the external
URL times out, add inbound TCP 80 in the Oracle VCN security list/network
security group; do not open TCP 8080.

## GitHub Actions status

As checked on 2026-10-15, the Android workflow files were under
`App/.github/workflows/`. GitHub only discovers workflows under the repository
root `.github/workflows/`, so do not assume the nested files trigger CI from
`main`. The latest observed Android CI run was on branch `radddao-work` and
failed during Android SDK setup, before Android tests or the APK build. Python
setup and the 36 database plus 6 VIDOUT offline tests passed in Replit. Recheck
the Actions page before relying on a build result.
