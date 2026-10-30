# 2026-10-30 04:15 — qoder4 master: the box entered the halt band, and what was actually consuming it [Q4-SAFETY]

> Rotated verbatim out of `docs/SESSION_CHECKPOINT.md` by the q3 documentation diet, 2026-10-30.
> Absorbed during the rebase onto trunk `4fe6f65` (trunk moved while this diet was
> open, so this entry was written to the append-here file after the rotation had
> already happened — the rebase moved it here instead of dropping it).
> Source: `git show 4fe6f65:docs/SESSION_CHECKPOINT.md` lines 4-45. Not edited, not summarised.

---


## 2026-10-30 04:15 — qoder4 master: the box entered the halt band, and what was actually consuming it [Q4-SAFETY]

**Trigger:** the owner's order was *"keep vm safe remember it do not over load it"*. Three briefs
were dispatched at 03:46 (q2 themoviebox crawl, q3 docs diet, q5 missav recon; q1 held idle as
reserve). This entry is the supervision record, not a code change — **no `.py` behaviour changed,
no crawl, no merge, no Gradle, no service action**, `radd-stream.service` stayed `active` at
**37 MB** cgroup memory (`memory.current` = 37031936).

**The memory is not the service and not a crawler — it is the fleet's own processes.** Measured at
04:09, `free -m` → total 11925 / used 9687 / free 106, and `ps --sort=-rss` put five `qodercli`
processes at 4937 + 1348 + 983 + 802 + 583 MB ≈ **8.6 GB RSS**, i.e. ~89 % of installed RAM held by
idle-or-generating agent CLIs. `MemAvailable` fell 2830 → 2355 → 2101 → **1750 MB** over ~25 minutes
while load1 sat at 6.34–6.71. The only non-lane CPU consumer was the legitimate scheduled job
`backup_manager.py --dir /home/ubuntu/radd-stream-data --hf` (pid 1727773, 22 min elapsed) — left
running; killing a backup is not a safety measure. SwapFree stayed healthy (2475–2498 MB), so the
box was absorbing pressure into cache rather than swapping the service out.

**What I changed as supervisor, and what I refused to change.** Dispatch is frozen: nothing new goes
out while `MemAvailable` < 1800 MB. I armed an edge-triggered watchdog (`b3u69zrpx`) that reports a
crossing within 30 s instead of my polling, and I **cut my own churn** — the 15-minute safety cron
was spawning an agent turn on a box already at 1.7 GB available, so it is now `3de42e38` at
:05/:45 with a 60-credit cap. I did **not** interrupt the three lanes: the broadcast `send-keys
Escape` method was explicitly refused by the owner earlier and is not retried; in-flight generation
is allowed to finish, and a finished lane is not re-tasked until the recovery event fires.

**The finding that outranks the load number: the live tree is stale *and* dirty.** `/opt/radd-stream`
— which is what `ExecStart` loads, not a workspace — sits at **`bf9e565`** while trunk is
**`dc73ac7`**: `git rev-list --left-right --count origin/master...HEAD` → **85 behind / 2 ahead**,
with 33 modified + 27 untracked paths, **22 of them backend**, including `Fast_Fetch/viewer.py`,
`redact.py`, `catalog_v2.py`, `test_catalog_api.py`, `test_merge_catalogs.py`,
`importers/import_themoviebox.py`, `importers/import_humtv.py`, plus untracked `dispatch_worker.py`
and `openrouter_*.py`. The newest backend mtime is 2026-10-29 22:41 (`viewer.py`), so nothing is
mid-write at this moment — but **any restart of `radd-stream` today loads that superseded mixture,
not trunk**, which is precisely the failure mode already logged as task #19 (the 19:14:31 OOM-kill
auto-restarted on an uncommitted mixed tree). I am **not** committing over it and **not** resetting
it; both would destroy another lane's work. It is recorded here and as task #26 so the owner can
decide, and every lane brief from now on names its own `/tmp/<lane>` worktree as mandatory.

**Not overstated:** `themoviebox.db` mtime moved to 03:55 but the vault still holds **44 posts and no
link table** — the crawl has not produced playable rows, so task #38 stays open and the vault stays
excluded from merge. Trunk is unchanged at `dc73ac7` on both refs.
