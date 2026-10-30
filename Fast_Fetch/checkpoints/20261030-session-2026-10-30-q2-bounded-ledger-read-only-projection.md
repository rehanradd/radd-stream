# Session 2026-10-30 (q2 bounded ledger + read-only projection) `[Q2-LEDGER]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-30 (q2 bounded ledger + read-only projection) `[Q2-LEDGER]`

**Half 1 — `/api/data` is bounded twice, and the dashboard uses the bounded form.** The endpoint
answered 2,533,437 bytes in 46.6 s, and it was never the rows: the list has been `LIMIT 50` since
`ffc3f5b`. The cost was five `posts` scans, a 1.4 M-row `releases` UNION and — with no safe stamp on
the file — a 3.8 M-link `GROUP BY state`, on every load. Now:

- Rows: `limit` (default **50**) clamps to `_LEDGER_PAGE_CEILING` (**200**), `page` is bounded, and
  `has_more` comes from fetching `limit + 1` rows — never a `COUNT`. The dashboard paginates and sends
  `q`/`limit`/`page`; Prev/Next are real requests, not a client-side slice.
- Counters: `stats="stamp"` is the default — it reads `cat_projection_meta` and publishes `null` for
  anything unstamped (the page renders `—`). Only `stats="full"`, an explicit operator button on the
  loopback port, counts live. A typo in `stats` falls back to the stamp; the expensive branch is
  chosen, never fallen into.
- `/api/data` stays in `OPERATOR_ONLY_ROUTES`: 404 on the public port, never proxied by nginx. The
  full `full=True` ledger remains loopback-only, and the adult rule on this panel is unchanged.

**A correction to this session's own audit numbers.** The timings that justified the work —
`is_18_plus=1` 93.04 s, `COUNT(*) FROM releases` 112.61 s, `count download_sources` **1012.76 s** —
were measured under `nice -n 19 ionice -c3` on a saturated 1-vCPU box. Re-measured at normal
priority with a warm cache: `posts` 0.01 s, `is_18_plus=1` 0.35 s. So those numbers are upper bounds
produced by starvation, not the queries' intrinsic cost. They still make the case (a dashboard must
not run *any* table scan per load, and 46.6 s was measured end-to-end on the wire), but a future
reader should not quote 1012 s as a scan cost.

**Half 2 — the projection rebuild runs read-only, and it is still running.** `Fast_Fetch/project_readonly.py`
ATTACHes the live catalog `file:...?mode=ro` and binds `posts`/`releases`/`download_sources`/`post_sources`
to TEMP VIEWs, so `catalog_v2.project()` reads them through the view and writes only into a NEW file.
It refuses to reuse an output and refuses to project a file onto itself. `test_project_readonly.py`
hashes the source (main + `-wal`) before and after, proves the source gains no `cat_` table, and
checks zero link loss on a fixture. Hosted CI gated the code at `b2c102d`.

Measured **before** (read-only, 2026-10-30 00:52):
`posts` **150,799**, `is_18_plus=1` **15,068**, `releases` **1,780,121**, `download_sources` **4,073,865**.
The existing projection in the production file is stale and was stamped when it had 130,016 posts:
`works` **116,922**, `releases` **1,383,752**, `links` **3,783,959**, `links_by_state`
`{"unchecked": 3456460}`, and **none** of `works_safe`/`releases_safe`/`links_*_safe` — which is why
`/api/v1/stats` still falls back to counting.

The rebuild itself reached `ledger read: 150,799 posts -> 129,457 works (107 s)` and
`works written: 129,457 (207 s)`, then entered the page/link pass (4,073,865 source rows to walk;
output 191 MB at the time). **It has not finished, and at 01:45 host time it was stopped, not
merely paused** — `catalog_v2.project()` is one monolithic pass with no resume point, so a stop
discards the output. Measured CPU share for the rebuild: **0.4 %** under `nice -n 19 ionice -c3`
(8 CPU-seconds in 30 minutes, 15,995 involuntary preemptions), **~9 %** after relaunching at
`nice -n 5 ionice -c2 -n6`. The box is one vCPU saturated by five `qodercli` lanes; `/proc/stat`
shows ~90 % user time and **0 % idle**. At ~9 % of a core the ~5–6 CPU-hours this corpus needs is a
40+ hour wall-clock job.

**Why it was stopped (Q4-MASTER guardrail, 2026-10-30 01:30, observed load 8.71–10.2):** heavy work
is frozen above load 4 on this host, and a 6.4 GB catalog scan is heavy work by definition. Memory
was never the trigger — MemAvailable 4.8 GB, SwapFree 3.0 GB, `radd-stream` cgroup MemoryCurrent
60 MB, all far above the 1,500 MB / 800 MB / 1,200 MB floors — the rule is load-led here. The
partial output `/home/ubuntu/radd-stream-data/cat_projection_20261030.db` (195 MB) and its journal
were deleted per the wrapper's own semantics: an incomplete projection must not be mistaken for a
finished one.

**Queued action — the exact command, to be run in a quiet window (load ≤ 4), never at load 8+:**

```bash
nice -n 5 ionice -c2 -n6 env RADD_PROJECT_PROGRESS=2000 \
  python3 -S /tmp/q2_bledger/Fast_Fetch/project_readonly.py \
  /home/ubuntu/radd-stream-data/merged_catalog_20261025.db \
  /home/ubuntu/radd-stream-data/cat_projection_20261030.db
# watchdog: stop if MemAvailable < 2500 MB or SwapFree < 800 MB
```

Expected cost: ~5–6 CPU-hours (~30–40 min wall clock on an idle core; 40+ hours at the observed
9 % share). Numbers wanted from it, all printed by the driver: `walked_links == 4,073,865`,
`orphan_cat_links == 0`, every source row not carried by id matched by URL, and the five safe
stamps in `cat_projection_meta`; the works count is already known at **129,457** from the pass that
completed. Until that run finishes there are **no after-numbers**, and none are quoted.

Acceptance test for the finished run: `walked_links == download_sources`, `orphan_cat_links == 0`,
every source row not carried by id has its URL in `cat_links`, and `cat_projection_meta` carries the
five safe stamps. The driver prints exactly those lines as `[✓] verify: {...}`.

**Adult invariant.** The rebuild creates no new path: `catalog_v2` already rolls `is_18_plus` up over
every page that shares a `canonical_key`, so a flagged page flags the work; the driver only changes
which file the writes land in. The known per-row twin hole in the public list route is unchanged and
still needs the reconciliation described in `AGENTS.md`.

**Gate.** `test_database` 133, `test_redact` 61, `test_catalog_api` 127, `test_catalog_v2` 96,
`test_api_v2` 46, `test_admin_panel` 58, `test_operator_isolation` 28, `test_vidout` 6,
`test_bounded_ledger` 10, `test_project_readonly` 5 — all OK. Both new modules are steps in
`backend-ci.yml`; hosted **Backend CI green at `b2c102d`**.

**Landed.** After two clean merges of the moving tip (`79d9143`, then `8935d49`) and hosted Backend
CI green on the final tree at `db81220` (run `40953382031`), `db81220` was fast-forwarded onto
`master` and `main`. The fleet kept landing (next tip `396e476`), and `db81220` is an ancestor of it,
so this work is in both branches. Merge commits were used, not rebases: the branch had already been
pushed and its CI-checked shas are part of the record.

**Not done.** No `full=True` against production, no `/api/v1/stats` polling, no service restart, no
write to either production database, `/opt/radd-stream` untouched. The console branch `q2-dashboard`
(`4c18987`, `cfe2e74`) is **not** in `master`; it and this branch both touch `fetch_database_payload`
and `DASHBOARD_HTML`, so the merge order matters — the console's new page never calls `/api/data`,
while the old panel now paginates.

