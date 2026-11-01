# Head-Pass Staging Decision — #18 (2026-11-01)

> Owner ruling that produced this: *"Then run 18 with head-pass staging decision recorded, own
> worktree only, push and report sha."*  This file is the decision. **#18 was not run.** The reason
> is §6, and it is a load number, not a memory number.  Sha reported: `45db0b1` on
> `refs/heads/q2-census-pricing` (with `0da8c9e`, the root `AGENTS.md` trim, in the same push after
> two rejected attempts — see the correction in the 16:1x checkpoint).

---

## 1. The decision

**Do not refactor `catalog_v2.project()` to stage the head pass. Run `project_readonly.py` as it is,
in an admitted window, under a peak-RSS sampler, and let the sampled number be the evidence.**

Two options were on the table and only one of them is a decision I am allowed to make now:

| Option | What it costs | What it buys | Verdict |
|---|---|---|---|
| **A — stage the head pass** (chunked `WHERE id BETWEEN ? AND ?`, or a TEMP table, or a streaming cursor into the accumulator) | a change to the code path that every projection consumer shares, plus a re-derivation of the pricing model that was calibrated against the *current* retention pattern | a resident figure that no longer has to be quoted | **not now** |
| **B — run as-is, measured** | one admitted window, one sampler, nothing to review | the real `VmHWM` for the real ledger | **recommended** |

A is a capacity refactor ordered against a number nobody has measured on the real file. B measures
the number and only *then* tells us whether A was ever needed. Choosing A today would spend a
touch-on-`catalog_v2` — the largest and most-tested module in this repo — to avoid a cost that may
turn out to be 150 MB rather than 590 MB. If B comes back over the floor, A is a real task and B
supplies the argument for it; if B comes back under, A would have been a refactor of a working
system for nothing.

**This corrects a sentence I published at 09:5x**: "`--mean-row-bytes` is closed by staging the head
pass, not by a quieter box". The second half stands — a mean row length is a content read, so no
window buys it. The first half was wrong: staging splits the same `SCAN p`, so it cannot *supply* a
missing count either; all it does is bound the memory the count costs once someone reads it. Both
halves were re-derived against the plan output in §3 rather than against my memory of the argument.

## 2. Why the question was still open, in one sentence

`price_projection.py` is the tool that answers *"does the projection fit?"*, and it **refuses to look
at the ledger the deployment actually uses** — measured 2026-11-01:

```
$ python3 -S Fast_Fetch/price_projection.py /home/ubuntu/radd-stream-data/merged_catalog_20261025.db --plan-only
[!] refused: merged_catalog_20261025.db is a production or snapshot file, not a pricing target
```

That refusal is correct as a *write* guard and wrong as a *plan* guard: `--plan-only` runs
`EXPLAIN QUERY PLAN`, which describes without executing, so it reads no row content and cannot write
anything. The name-based block (`FORBIDDEN_PREFIXES = ("merged_catalog_", "preapply_")`) therefore
means the only authorized cheap question about the real ledger is currently unanswerable by the tool
built to answer it. I did **not** relax the guard — that is the owner's call and it would be a change
to a safety instrument — and instead ran the schema-only half directly (§3), read-only, and recorded
it here.

## 3. What I ran instead, and its full output

A `mode=ro` URI open with `PRAGMA query_only=ON`, then three things and nothing else: `sqlite_master`
(table names), `PRAGMA index_list`/`index_info` (index inventory), and `EXPLAIN QUERY PLAN` for the
four `price_projection.STATEMENTS`. No `SELECT` of any table. Reproduce with:

```bash
python3 -S /tmp/q2_schema_probe.py        # scratch; the point is the four statements, not my file
```

Measured on `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` — 6,396,899,328 B, mtime
2026-10-29 10:52 — SQLite 3.45.1:

- **31 tables**; all four Layer-0 tables present (`posts`, `releases`, `download_sources`, `post_sources`).
- Index inventory, by table:
  - `posts` — `idx_posts_slug`, `idx_posts_imdb`, `idx_posts_tmdb`, `idx_posts_canonical_key`,
    `idx_posts_source_ind` (`source_site`,`industry`), `sqlite_autoindex_posts_1` (unique on `url`)
  - `releases` — `idx_releases_source_site`, `idx_releases_origin` (`post_id`,`source_site`,`origin_url`), `idx_releases_post` (`post_id`)
  - `download_sources` — `idx_sources_service`, `idx_sources_rel_status` (`release_id`,`status`),
    `idx_sources_status_temp` (`status`,`is_temporary`), `idx_sources_res`, `idx_sources_rel` (`release_id`)
  - `post_sources` — `idx_post_sources_site_post` (`source_site`,`post_id`), `idx_post_sources_post` (`post_id`),
    `sqlite_autoindex_post_sources_1` (primary key on `source_site`,`url`)
- Plans:

```
PLAN head pass             SCAN p
PLAN sources per post      SEARCH post_sources USING INDEX idx_post_sources_post (post_id=?)
PLAN releases per post     SEARCH releases      USING INDEX idx_releases_post (post_id=?)
PLAN downloads per release SEARCH download_sources USING INDEX idx_sources_rel (release_id=?)
```

## 4. Reading of it

All three of `price_projection.EXPECTED_INDEX` are satisfied **on the production ledger, by name**:
`idx_post_sources_post`, `idx_releases_post`, `idx_sources_rel`. So the model's plan-shaped
`does not fit` — the one that fires when a rebuild scans `releases` once per post — does **not** fire
here. The ledger is engine-shaped; it is what `fast_fetch.init_db` builds.

The bare `SCAN p` on the head pass is **not** a defect and must not be read as one: it is `SELECT
p.id, p.* … ORDER BY p.id`, which is the whole table in rowid order by design. No index can serve
`p.*` cheaper than the scan, and staging the head pass (§1 option A) does not change that either —
it only splits the same scan into chunks. That is the concrete sense in which A does not buy
feasibility; it buys a bound on residency, which is exactly the number B measures.

**What the probe still does not know.** Row count and mean row bytes are `COUNT(*)` and length
sums — content reads, frozen. So the resident figure stays the quotation it has been since 09:5x:
**≈ 292 MB** at the code-recorded 146,176 posts × the calibrated 1,975 B/row, and ≈ 590 MB if the
real ledger's rows average 4 KB. Neither is a measurement of this file. The calibration itself
(`price_projection.CALIBRATION`: 3,000 synthetic rows, 5,925,000 B retained, RSS 17 → 23 MB, factor
1.01×) was taken on a synthetic ledger shaped like the engine's DDL, so it is a good model of the
pattern and a poor one of the data.

## 5. Execution recipe for the admitted window

Run it **as-is**, and let the sampler be the deliverable:

```bash
/usr/bin/time -v python3 -S Fast_Fetch/project_readonly.py \
    /home/ubuntu/radd-stream-data/merged_catalog_20261025.db \
    /var/tmp/q2_projection_20261101.db
```

The argument order is `(SRC, OUT)` and the asymmetry is the point: `resolve_target` guards **OUT
only** — the source may legitimately be the live ledger, that is what the driver is for. So the tool
that *performs* the projection will read the merged catalog, while the tool that only *prices* it
refuses it by name (§2). If that reversal is not what the owner intended, it is the one thing in this
file worth changing.

OUT must therefore be a fresh file that is not named like a catalog or snapshot (`fast_fetch.db`,
`merged_catalog_*`, `preapply_*`) and is **not** inside `/home/ubuntu/radd-stream-data` — a new `.db`
there joins q3's merge input glob and the next lane reads it as a catalog. `/var/tmp` is recommended
over `/tmp` only because `/tmp/tmpjbp1_4w9` (22 GB of VACUUM snapshots) is evidence sitting on the
same 193 GB root filesystem and should keep the free space it has.

`/usr/bin/time -v` reports `Maximum resident set size`, which is `VmHWM` and the metric this repo has
already agreed is the planning number (instantaneous `VmRSS` is not — see
`docs/API_SURFACE_AUDIT.md` and the OOM post-mortem). `project_readonly.py` reports no RSS at all, so
without the wrapper the run leaves no capacity evidence behind. Its own memory posture is already
conservative and needs no change: `cache_size=-262144` (256 MB), `temp_store=FILE` with the comment
"*no multi-GB RSS spike on the finalize sort*", the source attached `mode=ro` under
`PRAGMA query_only=ON`, and zero-loss verification at the end. The run's own first output is the
`COUNT(*)` source stamp (`posts`, `adult_rows`, `releases`, `download_sources`) — that is a content
read, which is precisely why this whole recipe waits for an admitted window.

Admissibility, unchanged and self-enforcing: **two consecutive sustained sub-4 load windows**, `cpu
some avg10 < 50%`, and hard floors `MemAvailable ≥ 1,500 MB`, `SwapFree ≥ 800 MB`, radd cgroup
`MemoryCurrent ≤ 1,200 MB`.

## 6. Why #18 is still not run

At the moment this decision was written the host read **load 8.32, 6.95, 6.47** (`16:09:52`), with
`MemAvailable` ≈ 3,109 MB and the radd cgroup at ≈ 263 MB. The memory floors pass; **the load gate
does not**, by a wide margin, and a production read of a 6.4 GB ledger is inside the freeze regardless.
So the honest status of #18 is: *feasibility answered from plan shape, residency still a quotation,
run not attempted.* Anyone who reads "the decision is recorded" as "the rebuild was sized" has been
given the wrong impression by a document, which is the failure this file exists to avoid.

### 6a. Measured 16:22–16:24: it is the CPU clause, not the load clause

Load fell inside a minute, so I sampled rather than assumed — three consecutive 60 s windows,
`/proc/loadavg` plus busy-CPU percentage from two `/proc/stat` reads:

| window | load 1/5/15 | cpu busy | MemAvailable | SwapFree | verdict |
|---|---|---|---|---|---|
| 16:22:18 | 1.78 / 3.09 / 5.01 | **74.6 %** | 3,024 MB | 3,066 MB | load ✓ cpu ✗ |
| 16:23:18 | 3.70 / 3.39 / 4.99 | **92.7 %** | 2,759 MB | 3,066 MB | load ✓ cpu ✗ |
| 16:24:18 | 3.60 / 3.49 / 4.93 | **93.1 %** | 2,789 MB | 3,067 MB | load ✓ cpu ✗ |

**Three consecutive sub-4 load windows, and the gate still says no** — the `cpu some avg10 < 50%`
clause is 25 to 43 points away, and widening rather than settling. This is the gate earning its keep:
the load number alone would have admitted this run at 16:19 (1.37) on a box that was already 75 %
busy, and a projection that is CPU-bound on a `SCAN p` of the whole `posts` table is precisely the
work that finishes slowly and takes the service's latency with it. **The floors that pass are not the
floors that decide.** #18 waits for a window under 50 % CPU, not merely under 4 load.

The sampler is three lines, not a tool: read the first line of `/proc/stat`, sleep 60, read it again,
`busy = 1 - (idle + iowait) / total`, and print `/proc/loadavg` beside it. Anyone re-deciding #18
should sample rather than read `uptime`, because the 1-minute load average is the only number on that
box that moves fast enough to look like an opening — and it is the one that lied at 16:19.

## 7. What would change this decision

1. A measured `VmHWM` from §5 above the floor → option A becomes a task, with the number attached.
2. `price_projection.py` gaining a schema-only mode that is allowed to read a production *plan*
   (owner call, §2) → the next ledger of this kind answers its own index question without a hand
   probe, and this file's §3 becomes reproducible by a tool instead of by my scratch script.
3. Any change to `posts`' row shape or the retention pattern in `catalog_v2._WorkAccumulator.absorb`
   → the 1,975 B/row quotation and the 1.01× factor both stop describing reality and every number in
   §4 must be re-derived, not re-used.

## 8. Owner ruling 16:30 — the guard stays, and what that costs

*"Keep the guard: do not change `resolve_target` to allow plan-only production reads; price from a
staged or non-production catalog."*  Nothing in §2 was changed and nothing will be. But the second
half of that instruction has no target on this host, and that is worth knowing before someone looks
for it:

I swept the schema of **every `.db` in the staging data dir** — 49 files, `mode=ro` +
`PRAGMA query_only=ON`, `SELECT name FROM sqlite_master WHERE type='table'` only, no row content, 18
sidecar-bearing vaults skipped and listed rather than opened. Result:

| class | count | shape |
|---|---|---|
| forbidden by name (`merged_catalog_`, `preapply_`, `fast_fetch.db`, `user_state.db`, `resolvers.db`) | 5 | the only files that could hold the Layer-0 four-table shape |
| sidecar-barred (0-byte `-wal` / 32 KB `-shm` debris) | 18 | not opened at all |
| openable scrape vaults | 26 | **every one 2/4: `posts` + `releases` + `sources` + `sitemap_cache`, missing `download_sources` and `post_sources`** |

**Full Layer-0 shape among openable non-production files: zero.** So "price from a staged or
non-production catalog" cannot be satisfied by *finding* one — the staging tree holds merge
*inputs* (old-schema vaults), and the four-table shape is created by the merge, which writes it into
exactly the names the guard refuses. That is not a hole to route around; it is the reason the guard
reads the way it does. The practical consequence for #18: **the only instrument left that can size the
projection is Decision B's own measured `VmHWM`** — a staged ledger would have to be *manufactured*,
and a manufactured ledger prices a shape, not this data.

**Window status at 16:32, sampled not assumed:** load 5.24 / 3.76 / 4.26 with busy CPU **99.7 %**
(two `/proc/stat` reads 60 s apart). The load clause failed and the CPU clause failed by 50 points.
#18 remains unrun.
