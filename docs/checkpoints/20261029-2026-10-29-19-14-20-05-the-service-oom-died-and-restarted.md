# 2026-10-29 19:14–20:05 — the service OOM-died and restarted itself on a tree nobody deployed; two public-edge defects landed while it was warming

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 19:14–20:05 — the service OOM-died and restarted itself on a tree nobody deployed; two public-edge defects landed while it was warming

**What happened first, in order, because the order is the finding.** At 19:14:31 the kernel killed
the running API: `Out of memory: Killed process 265554 (python3) total-vm:9552712kB,
anon-rss:8038108kB`, chosen because `task_memcg=/system.slice/radd-stream.service` was the largest
eligible victim while a `copilot-runtime` allocation tipped the box over; the unit reported `7.5G
memory peak, 1.3G memory swap peak` and systemd restarted it at 19:14:36 (`Restart=`, counter 1).
**Production flapped with nobody deciding it.** My previous entries argued at length that a restart
is the owner's call; the machine overrode that argument at 19:14.

**The first thing I checked was the 18+ invariant, not the uptime.** Measured through nginx on the
restarted process: `/api/v1/posts/159` (a flagged post) → **404**, `/api/m3u?id=159` → **403**,
`/api/m3u?id=158` → 403, `/api/m3u` → 403, `/api/v1/posts/158` → 200/98,502 B. The invariant holds on
the tree that came back up, which is the only reassurance that matters in the first sixty seconds.

**What came back up is not what CI is green on.** `/opt/radd-stream` HEAD is `bf9e565`, and
`git merge-base bf9e565 <tip>` is `19abff7`: the live tree and the pushed tip **diverged**, the tip 35
commits ahead, the live tree 2 ahead. So the restarted service loaded a tree that does **not** contain
`34f22c6` (the stats fix) or anything after it, **plus ten uncommitted edits by other lanes**
(`redact.py`, `viewer.py`, `catalog_v2.py`, `test_catalog_api.py`, `test_merge_catalogs.py`,
`SITES.md`, `AGENTS.md`, `CONTINUITY.md`, `importers/convert_mp4moviez.py` + its test) and nine
untracked files. `34f22c6`'s `sources_by_state` is visible in the tip's `viewer.py` and absent from
the running build. **Policy change, deliberately: I am no longer copying docs into
`/opt/radd-stream`.** It is a deployment tree, and every convenience copy I put there is now part of
what a crash-restart silently ships. Docs live in worktrees and on the tip only.

**One of those live-only commits is real code that has never been tested anywhere.** `5446771
fix(ci): the 9 hosted test failures and all 23 lint errors, fixed in code` touches nine `.kt` files,
four test files, `build.gradle.kts` and two new `values-v23/values-v27` theme dirs — and because it
was never pushed, GitHub Actions has never seen it. It is a parallel fix to the App route that *did*
go green (`2caadb3`), so merging it blind could regress a green build; I did not merge it. It is now
pinned at local ref **`salvage/live-tree-ci-fix-5446771`** (→ `bf9e565`) so a reset of the live tree
cannot destroy it, and it is q1's problem to reconcile against its own green commit.

**Two defects I could fix without touching the running service, both measured, now at `2164cce` on
`main` and `master` with CI in progress:**
1. `redact.client_ip` keyed the application rate-limit bucket on the **leftmost
   `X-Forwarded-For`** entry — caller-typed text. Three requests, three invented values, three
   `RateLimit-Limit: 60 / RateLimit-Remaining: 59`. The 60/60 s browse ceiling was decoration and
   only nginx's `10 r/s` was load-bearing; the same read could also throttle one honest user by a
   stranger's chosen string. It now keys on `X-Real-IP` (which `proxy_params` sets from
   `$remote_addr` and overwrites), falls back to the *rightmost* XFF — the entry our own proxy
   appended — and trusts no forwarded header when the socket peer is not loopback.
2. `/api/v1/posts?page=abc` → **502** at the edge: a bare `int()` raised out of the handler and the
   connection closed with no response. `viewer.bounded_int()` now falls back to the documented
   default inside the documented band (`page` 1..1e6, `limit` 1..100). The journal already carried the
   same class of crash on its own: `ValueError: invalid literal for int() with base 10:
   '1/v1/models'`.

**Gate, run in the worktree at the tip, one module per invocation:** `test_redact` 60 (was 58, +2 new
regressions), `test_database` 124, `test_api_v2` 46, `test_catalog_api` 127, `test_tiers` 23 — all OK,
380 tests. `docs/API_SURFACE_AUDIT.md` records the whole edge/:8080/:8081 matrix and the seven open
defects.

**Three retractions, mine, all published earlier today by me.** (a) "`/download/` is a dead public APK
path" — wrong: the *directory* 403s because `autoindex off`; `/download/radd-stream.apk` answers 200
and the APK is present (22,738,552 B). (b) "`page_size=1` returned 11 KB so the parameter is
dangerously ignored" — `page_size` has never existed; the route reads `limit`/`page` only, and that
body was the ordinary 20-item page. My `page_size` sweep therefore never requested more than 20 rows
and **is not what exhausted memory** — I checked before letting myself believe otherwise. (c) "the
deployed stats are stale but serving" — on a cold cache they are not serving: post-restart,
`/api/v1/stats` timed out at my 15 s client deadline and `/api/v1/search/by-media?q=ra` did too, and
the route's real ceiling is the edge's `proxy_read_timeout 30s`, so the public symptom is **30 s of
spinner then 504**.

**Capacity, restated from one new number.** The service's *resting* RSS 28 minutes after the restart
is **65,892 KiB**. So 7.7 GiB is a transient peak produced by a large read, not this process's size —
which is why `VmHWM` is the planning metric and why bounding the large reads is a capacity task, not
a cleanliness task. At 19:14 the fleet was holding ~3 GiB across four runtimes plus ~1 GiB of JVM and
the local model, with swap 4.3/6.1 GiB used and 15-min load 16.59. **The fleet and the API cannot both
run at peak on this box**, so merge batch 4 stays held even though its backup gate is now satisfied
(see below), and the next catalog-walking job starts only when lanes are idle.

**The gate that was blocking merges for two hours cleared itself.** `preapply_20261029_1726.db`
printed `done in 5944.6s posts=150799 flagged=15068` at 19:05 and the file is 6,396,899,328 B — a
verified `Connection.backup()`, not a copy. Two side effects worth keeping: that line is the
authoritative-looking **15,068** in the 15,020-vs-15,068 disagreement (15,020 was measured at 05:12,
before lanes flagged anything, and the gap is 48 rows — the shape of "48 rows got flagged during the
day", which is inference, not proof, and I still will not run the unindexed count to settle it on a
box that just OOM-died); and the production DB file's mtime is **10:52** with a 0-byte WAL, i.e.
**no apply has landed on production** — task #12's `--apply` did not commit, whatever else it did.

**Fleet, and how to actually deliver to a busy lane.** All five sessions existed but three looked idle
when they were not: the `Type your message` placeholder renders even mid-turn, so idle detection must
test for `esc to cancel`, not for the placeholder. `paste-buffer` + `send-keys Enter` does **not**
submit to a lane that is generating; `tmux send-keys -H 0d` (raw CR) does, and the message then waits
in the queue. Delivered on the true gates: **q3** ← `Q3-SEARCH-LATENCY` (with five new facts: the 30 s
edge ceiling, no `page_size`, the live tree ≠ the tip, `2164cce`, RAM-not-tokens is the binding
constraint), **q1** ← `Q1-CACHE-WIRING`, **q2** ← `Q2-BOUNDED-LEDGER-READS` (fresh context, so the
brief was self-contained: worktree at the tip, fixture DB only, never `merged_catalog_20261025.db`,
never restart the unit, CI's fifteen-module list, push a branch and report the sha). q2 is already
correcting my brief rather than obeying it — `/api/data`'s post list has had `LIMIT 50` since
`ffc3f5b`, so "no row ceiling" was wrong and it is now hunting the real large read
(`_ledger_link_breakdown`, the stats path). That is the behavior I want from a lane and I have no
interest in being agreed with. Two housekeeping facts: qoder2's pane is served by a **new** instance
(pid 1388336, started 19:48) while the old account2 CLI (1242663) is still `SIGSTOP`'d at ~290 MiB —
left stopped, not killed, because I am not certain which process owns that tty and a stopped 290 MiB
is cheaper than a mistake. And I fired `GET /api/health-check` at `:8081` during the audit: it is
reachable there with no token, it runs long outbound probes on a daemon thread, and it ran 25,481 ms
before my client gave up while the work continued server-side. That added load to a box that OOM-died
minutes later. Do not repeat it, and treat "it answers on the operator port at all" as the finding.

**Next.** (1) Read CI's verdict on `2164cce` — if any of the fifteen modules disagrees with my local
run, that is a real signal, since my local run is not the whole list. (2) `limit_req_status 429` is a
one-line nginx change that turns over-limit 503s into honest 429s; it touches the edge config on a
live host, so it waits for the owner. (3) The three fixes that actually want deploying (`34f22c6`
stats, `2164cce` limiter + pager, and whatever q2 finds) all need the same thing: a restart decision
that is not mine. (4) q3 must not be given another task until `Q3-SEARCH-LATENCY` comes back with
A..F, and its context is at 79% — expect it to run out mid-brief. (5) `salvage/live-tree-ci-fix-5446771`
needs q1's eyes before the next live-tree commit or reset buries it.

