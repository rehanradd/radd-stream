---
name: Radd Stream project context
description: Product scope and continuity notes from the user's prior Replit account chat.
---

Radd Stream is being developed from an existing GitHub project. Its stated scope is a Python media metadata aggregator, SQLite catalog manager, URL resolver, and CDN latency diagnostic engine; the repository also contains an Android app.

**Why:** The user shared a prior account's chat so this workspace can carry forward the project context.

The user expects the agent to handle the Radd Stream backend setup and verification; their role is to provide access or context they already have, not perform the operational work.

**Why:** The user explicitly clarified this division of work on 2026-10-15.

**How to apply:** Take ownership of setup and testing when access is available. Do not ask the user to perform operational steps the agent can do.

The user wants `Fast_Fetch/DAO.md` kept in its original form; do not edit it unless they explicitly ask.

**Why:** The user asked to restore that file and preserve it.

**How to apply:** Avoid content or formatting changes to `Fast_Fetch/DAO.md` unless the user specifically requests them.

The user reports that the GitHub repository is public; unauthenticated access checks in this workspace returned 404.

**Why:** Public visibility was stated by the user, but the workspace could not independently confirm it.

**How to apply:** Verify repository access before assuming an anonymous clone will work; public visibility does not grant write access.

The user wants `GITHUB_TOKEN` and `ORACLE_SSH_KEY` configured as environment variables in Replit Configurations, not Replit Secrets. Check only whether the variable names are present; do not reveal their values or ask to move them.

**Why:** The user explicitly called this a deliberate, permanent choice for this project.

**How to apply:** During new-workspace bootstrap, report presence or absence by name only and stop if either is missing.

The user says `.replit` contains sensitive configuration and must never be pushed or recorded in future Git history. Keep it local, ignored, and untracked; do not inspect its values. The user chose to leave existing history intact.

**Why:** The user explicitly asked for this as a permanent project rule.

**How to apply:** Exclude `.replit` from all commits and uploads. Do not rewrite existing history unless the user explicitly changes their decision.

The project uses dedicated per-site staging databases (`multimovies.db`, `hdtvb.db`, `vegamovies.db`, `rogmovies.db`, `ssrmovies.db`) merged into unified `fast_fetch.db` with `merge_catalogs.py`.

**Why:** Isolated staging databases eliminate SQLite lock contention and database corruption risks during high-throughput concurrent scraping.

**How to apply:** Always build dedicated importers (`import_<site>.py`) with isolated SQLite databases, comprehensive unit tests (`test_<site>_import.py`), and remote live progress monitors (`check_<site>.py`). Current status:
- MultiMovies: 100% completed (10,498 titles, 595,218 direct sources).
- HDTVB (HDHub4u): 100% completed (5,692 titles, 17,293 sources with direct 10Gbps Cloudflare R2).
- Vegamovies: Actively running on Oracle VM (PID 76635, 14,316 titles).
- Rogmovies: Actively running on Oracle VM (PID 77286, 7,868 titles).
- SSRMovies: Active domain `https://ssrmovies.surf` (27,362 posts across 274 pages on `/wp-json/wp/v2/posts?per_page=100`), LinksZilla resolver for Google CDN, Cloudflare R2, PixelDrain, and web streaming. Importer `import_ssrmovies.py`, tests `test_ssrmovies_import.py`, and monitor `check_ssrmovies.py` established.
