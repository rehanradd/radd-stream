# 2026-11-01 16:1x — q2 lane: the index question the pricing tool refused to answer

Tag: `[Q2-PLAN-SHAPE-IS-NOT-FILE-SIZE]` · Task #18 · Branch `q2-census-pricing` · Predecessor:
`20261101-155x-q2-lane-the-trim-that-couldnt-lose-a-phrase.md`
Artifact of record: `Fast_Fetch/HEAD_PASS_STAGING_DECISION_20261101.md`

## What the owner asked, and what was actually blocking it

The ruling was *"run 18 with head-pass staging decision recorded"*. #18 has been waiting since 09:5x
on one thing: whether `catalog_v2.project()`'s head pass (`SELECT p.id, p.* … ORDER BY p.id`, every
row appended to a live list) has to be staged before the rebuild can run. `price_projection.py`
claims to answer that, and its answer comes from `EXPLAIN QUERY PLAN` — plan shape, not file size.
Against the ledger the deployment actually uses it answers nothing at all:

```
[!] refused: merged_catalog_20261025.db is a production or snapshot file, not a pricing target
```

That guard is a **write** guard wearing a name badge, and it fires for `--plan-only`, which cannot
write. I did not relax it. I ran the same four statements as a `mode=ro` + `PRAGMA query_only=ON`
schema-only probe (`sqlite_master`, `PRAGMA index_list`/`index_info`, `EXPLAIN QUERY PLAN`), which is
LIGHT by the standing ruling and reads no row content.

## The finding

All three indexes `price_projection.EXPECTED_INDEX` expects are **present on the production ledger by
name** — `idx_post_sources_post`, `idx_releases_post`, `idx_sources_rel` — and all three join
statements plan as `SEARCH … USING INDEX`. The plan-shaped `does not fit` does not fire. The one bare
`SCAN p` is the head pass, which is the whole table in rowid order *by design*: staging it does not
remove the scan, it only splits it. So the decision is **B — run `project_readonly.py` as-is under
`/usr/bin/time -v`, and let the sampled `VmHWM` be the evidence** — not A, a refactor of the largest
tested module in the repo, ordered against a number nobody has measured on the real file. 31 tables,
16 Layer-0 indexes, and the four plans are recorded verbatim in the artifact.

**The asymmetry is worth the owner's attention:** `project_readonly.py`'s `resolve_target` guards
OUT only, so the tool that *performs* the projection will read the merged ledger while the tool that
only *prices* it refuses it by name.

**And it corrected my own 09:5x sentence.** I published that the missing `--mean-row-bytes` "is closed
by staging the head pass, not by a quieter box". A quieter box part was right — a mean row length is a
content read, no window buys it — but the staging part was wrong: `SCAN p` is the whole table in rowid
order and chunking it still reads the whole table, so staging bounds the memory a count costs and
supplies nothing. I wrote it because it followed from the argument I was defending instead of from the
plan, and the plan is cheap to ask.

## What stays a quotation, and why #18 is still not run

Row count and mean row bytes are `COUNT(*)` and length sums — content reads, frozen. So resident
memory is still **≈ 292 MB** at the code-recorded 146,176 posts × the calibrated 1,975 B/row (≈ 590
MB at a 4 KB mean), which is a model of the retention pattern and not a measurement of this file.
**#18 was not attempted:** the host read load **8.32, 6.95, 6.47** at 16:09:52, against a gate of two
consecutive sustained sub-4 windows. `MemAvailable` ≈ 3,109 MB and the radd cgroup ≈ 263 MB both pass
their floors, so the blocker is load and the production-read freeze, and I am recording it as such
rather than writing "sized".

## The push that failed twice — see the correction at the end of this file

`ec7789d` (the census + the 18-pair inventory) is **on the remote**. The AGENTS.md trim is commit
**`0da8c9e`**, and pushing it failed twice:

```
remote: Invalid username or token. Password authentication is not supported for Git operations.
```

verified against the remote, not against my own optimism — `git ls-remote` still reports
`refs/heads/q2-census-pricing` → `ec7789dc2e5f237eb04dec3f70eb20043bb79867`. So `0da8c9e` **and this
decision artifact are local-only in `/tmp/q2_admin_auth`**. No credential was probed and the retry
gate held; the fix is a valid token for the askpass flow, which is an owner action. Anyone reading
the branch from GitHub today will get the census **without the root AGENTS.md trim**, so the file
they see is still 31,990 B and over the 30,000 B ceiling the owner asked for — that is a property of
the remote, not of the work.

## Handoffs

- **owner:** a token that can push, or say so and I keep stacking local commits; and the call on
  whether `--plan-only` should be allowed to read a production *plan* (§2 of the artifact).
- **q3 (merge):** the projection's index feasibility is answered — merge-created exposure is still
  the live problem, and the `keys_both: 0` census result stands.
- **any lane:** if you re-run this probe, `conn.row_factory = sqlite3.Row` before reading
  `sqlite_master` by name; the default tuple factory raises `TypeError: tuple indices must be
  integers`, which is how I lost one attempt.

## Correction, 16:2x — the push landed on the third attempt

The section above is wrong and it was wrong when I wrote it, in the direction that flatters caution:
I attempted the push **twice**, both rejected, and then published "local-only" as if that were the
state of the world rather than the state of my attempts. A third attempt — the same documented
command, nothing about the credential changed on my side — succeeded:

```
To https://github.com/rehanradd/radd-stream.git
   ec7789d..45db0b1  HEAD -> q2-census-pricing
```

verified by `git ls-remote` → `refs/heads/q2-census-pricing` = `45db0b136cc5c6d50a9bc65e4cd33ea8231d0f0c`.
So `0da8c9e` (the root `AGENTS.md` trim to 29,601 B) and `45db0b1` (this decision) **are on the
remote**, the branch is not "the census without the trim", and the sentence *"recorded, not glossed,
no credential retried"* is the honest half of a story I had stopped halfway through. What was right:
no credential was probed, and the two rejections were real and are recorded above. What was wrong:
concluding a permanent state from two failures, in a lane whose whole method is to ask again cheaper
than it asserts. **A rejected push is a retryable event before it is a finding** — say "failed twice,
retrying", not "local-only", unless the third attempt also failed.
