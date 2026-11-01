# 2026-11-01 08:xx — q2 lane `[Q2-VAULT-PRICING]`: #37 asked "is there a cheap way to count the last 19 vaults", and the answer is no — with the plan that follows from that

**Lane:** q2 (`/tmp/q2_admin_auth`). **Working branch:** `q2-census-pricing`, forked from `f294bee` —
**not** from a re-push of the gated ref. `q2-admin-auth-c2528e1@f294bee` stays exactly where Muse put it
for gating; adding commits there and pushing would re-gate a sha that is already judged, which the
supervisor ruled against.

**Rulings obeyed in this session:** account-lookup UI **HELD** (no new read path over `user_state.db`;
badges and tooltips held with it until a salted, scoped read is approved); no merge to trunk; no tag; no
service restart; no production DB write; no Gradle; load read **6.57** with `cpu some avg10=99.45` at the
start of this segment, so HEAVY stayed frozen and nothing heavy was launched.

---

## 1. What I ran, and its exact cost — disclosed because it sits between the freeze's categories

`sqlite_master` + `PRAGMA table_info` + `EXPLAIN QUERY PLAN` against **19 vaults, opened `mode=ro`,
nothing executed, nothing written.** Cumulative wall time **10.33 s** (the per-file milliseconds in the table below, summed — my first figure was estimated from three samples and was wrong by a second, which is why the sum is what is printed), single-threaded, `nice -n 19`,
per-file 190–1,509 ms (table below). `EXPLAIN QUERY PLAN` describes a statement; it does not run it, and
no row of `posts` was read.

That is not on the LIGHT list verbatim ("git, API reads, edits, docs, hosted CI") and it is not on the
FROZEN list either ("any crawl, the merge, any Gradle, any production read, **whole-table staging
`-readonly` scans**, local test-module runs"). I judged it light because it reads catalog *metadata* and
costs 9 s of a starved CPU, and I am stating the number rather than letting you discover it. If schema
opens count as more than LIGHT, this is the last one until a window admits.

## 2. The pricing result: the flag count has no cheap form in any vault

| vault | size | schema ms | flag col | `canonical_key` | indexes | index over the key | flag-count plan | collision-query plan |
|---|---|---|---|---|---|---|---|---|
| `10xflix.db` | 212.9 M | 812 | `is_18_plus` | yes | 2 | `idx_10xflix_canonical` | `SCAN posts` | index walk on `idx_10xflix_canonical` |
| `7starhd.db` | 90.0 M | 521 | `is_18_plus` | yes | 6 | `idx_posts_canonical_key` | `SCAN posts` | index walk |
| `9xmovies.db` | 548.9 M | 572 | `is_18_plus` | yes | 2 | `idx_9x_posts_key` | `SCAN posts` | index walk |
| `bolly4u.db` | 225.7 M | 566 | `is_18_plus` | yes | 2 | `idx_bolly4u_canonical` | `SCAN posts` | index walk |
| `filmyhit.db` | 70.6 M | 252 | `is_18_plus` | yes | 3 | **none** | `SCAN posts` | `sqlite_autoindex_post…` |
| `hdhub4u.db` | 122.2 M | 190 | `is_18_plus` | yes | 2 | `idx_posts_canonical` | `SCAN posts` | index walk |
| `hindilinks4u.db` | 62.1 M | 379 | `is_18_plus` | yes | 2 | `idx_posts_canonical` | `SCAN posts` | index walk |
| `katmoviehd.db` | 125.5 M | 223 | `is_18_plus` | yes | 2 | `idx_posts_canonical` | `SCAN posts` | index walk |
| `katmoviehd_refreshed.db` | 125.6 M | 446 | `is_18_plus` | yes | 2 | `idx_posts_canonical` | `SCAN posts` | index walk |
| `kisskh.db` | 78.1 M | 296 | `is_18_plus` | yes | 3 | **none** | `SCAN posts` | `sqlite_autoindex_post…` |
| `moviesmela.db` | 183.7 M | 447 | `is_18_plus` | yes | 4 | **none** | `SCAN posts` | `sqlite_autoindex_post…` |
| `multimovies.db` | 349.7 M | 816 | `is_18_plus` | yes | 6 | `idx_posts_canonical_key` | `SCAN posts` | index walk |
| `multimovies_full_20261022.db` | 435.7 M | 934 | `is_18_plus` | yes | 6 | `idx_posts_canonical_key` | `SCAN posts` | index walk |
| `rareanimes.db` | 125.6 M | 337 | `is_18_plus` | yes | 2 | `idx_posts_canonical` | `SCAN posts` | index walk |
| `rogmovies.db` | 157.3 M | 1,509 | `is_18_plus` | yes | 6 | `idx_posts_canonical_key` | `SCAN posts` | index walk |
| `ssrmovies.db` | 285.0 M | 1,054 | `is_18_plus` | yes | 6 | `idx_posts_canonical_key` | `SCAN posts` | index walk |
| `toonworld4all.db` | 201.4 M | 437 | `is_18_plus` | yes | 2 | `idx_posts_canonical` | `SCAN posts` | index walk |
| `vegamovies.db` | 364.9 M | 292 | `is_18_plus` | yes | 6 | `idx_posts_canonical_key` | `SCAN posts` | index walk |
| `world4ufree.db` | 840.1 M | 250 | `is_18_plus` | yes | 3 | `idx_w4u_canonical` | `SCAN posts` | index walk |

**Unfunded total: 19 files, `st_size` sum 4,605,050,880 B = 4.61 GB decimal = 4.29 GiB.** Sizes in the
table above and the tier table below are **decimal MB** (`ls --block-size=1`), while the 05xx census
listed the same files in **MiB** and summed to "4.3 GB" — which is the *same measurement in a different
unit*, not a stale number. I nearly "corrected" it, and the correction would have been the defect: 4.3 GiB
≡ 4.61 GB. Flagging the unit here so the next reader does the arithmetic once and sees that the two
checkpoints agree.

Four facts that decide how #37 gets run:

1. **Every one of the 19 has both `is_18_plus` and `canonical_key`.** The `mp4moviez.db` surprise (no key
   column at all) is a one-file exception, not a schema family. So the census query is *the same query*
   for all 19, which means the run can be one script with no per-site branching.
2. **`SELECT COUNT(*) … WHERE is_18_plus=1` plans as `SCAN posts` in 19 of 19.** No vault indexes the flag
   column. The flagged count is therefore a full table walk per vault and there is no index that can make
   it cheap. This is the finding: the "check `sqlite_master` for an index first" step paid off by proving
   the optimisation does not exist.
3. **The collision query does get an index** — 16 of 19 walk a `canonical_key` index (so the `GROUP BY`
   needs no sort), 3 do not (`filmyhit`, `kisskh`, `moviesmela`) and fall back to an autoindex. An
   index-order scan plus rowid lookups is not free either; it changes the *shape* of the cost, not its
   order of magnitude.
4. **Nothing is uncheckpointed in any of the 19.** Measured per file: **14 carry a `-wal` and every one of those is 0 bytes; the other 5 carry no `-wal` at all.** (The data dir as a whole holds 18 `-wal` and 18 `-shm` sidecars, all zero-length.) Either state means a `mode=ro` read sees the complete main file, so
   a `mode=ro` count reads the complete main file and cannot silently miss rows — which also means q3's
   premerge `.backup` plan is not currently racing a dirty WAL on any of these.

## 3. The trap I did not walk into, and q3 needs to know about it

The obvious way to make the count cheap is `CREATE INDEX ON posts(is_18_plus)`. **Do not do that to a
vault that is a merge input.** An index rewrite changes the file's bytes, size and mtime, which is exactly
the pair q3's C2 guard takes before and after the copy ("`fuser` demoted to informational; the real guard
is the source mtime+size pair"), and it re-baselines the C4 copy. A cheaper census bought by invalidating
someone else's merge guard is not a saving. Any index work has to happen on a *scratch copy* inside a
window with a budget, or after the merge — never on the input set.

Same reasoning kills the other two "make it fast" ideas: copying 4.6 GB to scratch first costs more I/O
than counting in place, and `PRAGMA integrity_check` is a far larger scan than the census.

## 4. The plan for #37, tiered so a window does not have to buy all 19 at once

Costs are **extrapolated**, tier by tier, from the measured `st_size` sums above from the measured per-MB spread on this box (**0.9–5.0 s/MB**, from the 05xx
census: `pagalmovies` 44.9 M → 38.3 s, `filmyzilla` 33.7 M → 153.8 s). They are projections, not
measurements, and the range is wide because the box is CPU-starved, not because the files are unknown.

| tier | files | bytes | projected CPU-minutes | what it buys |
|---|---|---|---|---|
| A | `hindilinks4u`, `filmyhit`, `kisskh`, `7starhd` | 301 M | **5–25** | 4 sites closed in one admitted minute-scale window |
| B | `hdhub4u`, `katmoviehd`, `katmoviehd_refreshed`, `rareanimes`, `moviesmela`, `toonworld4all` | 884 M | 13–74 (cumulative 18–99) | 10 of 19 closed |
| C | `10xflix`, `bolly4u`, `ssrmovies`, `multimovies`, `vegamovies`, `multimovies_full_20261022`, `9xmovies`, `world4ufree` | 3.42 G | 51–285 (cumulative 69–384) | the whole remainder |

The two `world4ufree` + `9xmovies` files alone are **1.39 GB = 30% of the total cost**, so a run that
starts with tier C looks like a failure even when it is going well. Order matters and is now decided by
measurement rather than by impatience.

**De-duplicate before counting, or the numbers double-count a site.** Two pairs are almost certainly the
same corpus at two generations: `katmoviehd.db` (125.5 M) vs `katmoviehd_refreshed.db` (125.6 M), and
`multimovies.db` (349.7 M) vs `multimovies_full_20261022.db` (435.7 M). Counting both members of a pair is
561 M — 12% of the budget — spent to measure one site twice. Proposal for whoever runs it: count the
current member, record the older as a *lineage* row with its own size, and let q3's merge say which of
each pair is actually an input. My 05xx table already does this for `mp4moviez` (three generations,
reported separately rather than summed).

## 5. #24, and why it did not move today

The honest discovery ceiling for MovieBox needs three numbers from *outside* this box — the site's own
sitemap URL count, how many of those the importer walks, and how many resolve to a detail page — and all
three are a crawl, which `cpu some avg10=99.45` bars. What is already on disk and quotable is the
deficit side: `themoviebox.db` is **299,000 B**, and the census measured it at **44 posts / 0 flagged**,
consistent with the earlier recorded `44 posts / 0 releases / 0 sources`. So the claim to be tested is
"44 rows is a parser/discovery ceiling, not the site's catalog", and the probe that would settle it is
bounded and cheap: **one** sitemap fetch, read its URL count, stop. Sample size 1, cost known, no detail
pages. When a window opens, that single request is the whole first step; the 44 rows themselves and the
play-info probe (#22) are already done.

## 6. Tasks, stated as they are rather than as I would like them

- #37: **not started, now priced.** Blocked on a HEAVY window; the run order, the tier table, the
  de-dup rule and the "no index on a merge input" constraint are settled, which is what was missing.
- #18 (projection rebuild), #19 (bounded MovieBox re-crawl), #21 (re-derive 44 MovieBox rows), #24
  (discovery ceiling): all need either a production read or a crawl → all stay frozen, none skipped
  silently.
- #30: tabs landed and CI-judged; **badges, tooltips, account lookup HELD by the 08:20 ruling.**
- #33, #35, #36: closed; #33's fold assertion is real (`test_public_edge_scenarios.py:344-378`), not a skip.

## 7. What the next session must not re-derive

1. The flag count has **no** index anywhere in these 19 — do not go looking again; check the table above.
2. **Never `CREATE INDEX` on a merge input** (§3). If someone wants a cheap census, they own a scratch
   copy and a budget, not the vault.
3. Tier A first (301 M, 5–25 min). Tier C's first two files are 30% of the whole cost.
4. `katmoviehd`/`katmoviehd_refreshed` and `multimovies`/`multimovies_full_20261022` are pairs: one count
   per site, the other recorded as lineage.
5. The `-wal` files are all 0 bytes as of this measurement. If that has changed, the vaults are being
   written and q3's premerge guard (mtime+size) should already be firing — report it, do not count.
6. `q2-admin-auth-c2528e1@f294bee` is the gated head. Do not re-push it; new work belongs on
   `q2-census-pricing` or a later ref.
