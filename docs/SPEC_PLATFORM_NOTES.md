# Spec Platform Notes

> Moved **verbatim** out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `Fast_Fetch/AGENTS.md`
> carried at this sha. Law stayed in `Fast_Fetch/AGENTS.md`; this is the reference prose it now links to.
### from `Fast_Fetch/AGENTS.md` lines 289-320

### Windows
- UTF-8 console output is fixed at import (`sys.stdout.reconfigure`)
- Path separators use `pathlib.Path` — works on both `\` and `/`
- Use `run.bat` for one-command launch

### Linux / Ubuntu VPS / Oracle Cloud
For the actual Oracle host, secret-safe SSH/GitHub instructions, and the
domainless HTTP deployment plan, read
[`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md) before connecting or
changing the server.

- Current Oracle account: `ubuntu@92.4.95.252`, SSH port 22.
- Last verified host: Ubuntu 24.04.4, Python 3.12.3, non-interactive `sudo`
  available; no Python packages or Docker are required.
- Intended public URL is `http://92.4.95.252/`; it has no TLS. Do not send
  credentials over it or use it as a release Android endpoint.
- The backend defaults to `0.0.0.0` and has unauthenticated routes. For Oracle,
  start it with `serve --host 127.0.0.1 --port 8080`; never expose port 8080
  directly. Follow the runbook's public-route restrictions before enabling Nginx.
- Keep the SQLite database outside the Git checkout and out of Git. The prior
  database backup was deleted; a new catalog must be populated after deployment.

### Replit
- `.replit` file configures auto-run and port
- DB is stored at `/home/runner/radd-stream/Fast_Fetch/fast_fetch.db`
- Set `RADD_DB_PATH` env var in Replit Secrets if needed
- The HTML viewer can be served via Replit's built-in web server

### GitHub Codespace
- Python 3.11+ pre-installed
- `bash run.sh sync --site all` works immediately after clone
- Port 8080 auto-forwarded for HTML viewer if needed
