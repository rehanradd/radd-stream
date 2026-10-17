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
