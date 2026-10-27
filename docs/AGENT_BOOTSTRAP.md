# Radd Stream agent bootstrap

Use this once in a new workspace/account before taking on a task. Do not make feature changes during bootstrap.

Repository: `https://github.com/radddao/radd-stream`. Authenticated GitHub API metadata verified that the repository is public on 2026-10-16. Unauthenticated GitHub API and raw-file requests from this Replit workspace returned 404, while authenticated reads and a Git clone succeeded. For Git operations, use the temporary askpass flow in `ORACLE_DEPLOYMENT.md`; do not treat an unauthenticated 404 as proof that the repository or file is missing.

## 1. Check the configured variables

The user's permanent project choice is to configure `GITHUB_TOKEN` and `ORACLE_SSH_KEY` as environment variables in Replit **Configurations**, not **Secrets**. Verify whether each name is present in the current workspace; report presence only. Never read, print, copy, or expose either value, and do not ask to move them. If either is missing, report which name is absent and stop.

## 2. Read the project instructions

Read `AGENTS.md`, `SESSION.md`, `CHANGELOG.md`, `docs/PROJECT_MAP.md`, and `docs/SESSION_CHECKPOINT.md`. Then read the relevant subsystem guide:

- Backend: `Fast_Fetch/AGENTS.md` and `Fast_Fetch/CONTINUITY.md`
- Android: `App/AGENTS.md`
- Oracle access/deployment: `ORACLE_DEPLOYMENT.md`

Inspect the current Git branch, remotes, and working-tree status; notes may be stale. The old-account attachment is only a final prompt/tool trace, not a complete conversation.

## 3. Project facts and boundaries

- Radd Stream is a Python standard-library backend and REST API in `Fast_Fetch/`, with a SQLite catalog.
- The Android client is Kotlin/Jetpack Compose in `App/`. Android APKs are built by GitHub Actions, not on Oracle.
- GitHub discovers workflows under repository-root `.github/workflows/`. `main` currently has root `ci.yml` and `release.yml`, as well as additional workflows under `App/.github/workflows/`; verify the latest Actions run before relying on CI. `radddao-work` is divergent. Review changes carefully; do not merge that branch wholesale.
- Treat `Fast_Fetch/DAO.md` as the project manifesto and preserve it unless the user explicitly asks for edits.
- The user expects the Dao Partner to handle routine setup, implementation, testing, and handoffs when access allows. This does not grant account/server permissions or override platform rules.

## 4. Safe work and handoff rules

- Verify each coherent milestone, update `docs/SESSION_CHECKPOINT.md`, stage only reviewed paths, commit, and push promptly. Agents are authorized by the owner to push verified milestones directly to `main` to trigger automated CI and maintain seamless progress. Never force-push or use `git add -A`.
- Treat `.replit` as local-only sensitive configuration. Do not read its values, stage, commit, or push it; keep it ignored and untracked. Older copies remain in Git history, which the user chose to leave intact; do not rewrite history unless they explicitly change that decision.
- Use the temporary Git askpass procedure in `ORACLE_DEPLOYMENT.md`; never put credentials in URLs, arguments, files, or logs. The old `push.py`, `github_push.py`, and `emergency_push.py` uploaders are retired and their warning stubs have been deleted from the tree; do not run or restore them.
- If a push fails, keep the local commit and checkpoint, report the exact blocker, and do not claim the change is synchronized. Keep uploaded chats, databases, secrets, APKs, and build outputs out of Git.
- Oracle is intended for the Python API and persistent database. A read-only check on 2026-10-17 found `radd-stream.service` active on `127.0.0.1:8080` behind Nginx on port 80, but no `.git` metadata in the app directory; the deployed source's exact Git provenance is unknown. The saved host fingerprints are TOFU, not OCI Console verified. Do not deploy automatically; verify the intended source/recovery path and obtain explicit user confirmation before production changes.

## 5. Stop and report

After bootstrap, report which configured variable names are present (never their values), the current branch/status, the instructions read, and any access or setup blockers. Then stop and wait for the user's actual task; do not start unrelated implementation or deploy anything.
