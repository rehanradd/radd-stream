---
name: Radd Stream staging-database merge gate
description: User-required approval process before any per-site staging database is merged into the unified or Oracle catalog.
---

Never merge a per-site staging database into the unified or Oracle catalog unless the user explicitly requests that specific merge in the current conversation. Crawler completion, passing tests, historical notes, or prior approval do not authorize a merge.

Before executing a requested merge, state the exact source database(s), target database, current row counts, and verified backup/rollback plan. Obtain a separate explicit confirmation from the user for that plan. If either approval is missing or unclear, leave all databases isolated and do not use SQL, file copying, the merge function, or another write path to bypass the gate.

**Why:** The user explicitly asked for this strict merge rule to be saved for future agents.

**How to apply:** Read this before any catalog merge. The merge CLI also requires `--owner-authorized`; use it only after both user approvals are present.
