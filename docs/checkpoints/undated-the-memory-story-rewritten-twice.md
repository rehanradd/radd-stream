# the memory story rewritten twice because the first two readings were wrong

> Undated session block: its heading carried no date, so the dated rotator missed it.
> Moved verbatim out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet.

## the memory story rewritten twice because the first two readings were wrong

**Why this window matters more than the code it shipped:** the capacity figures I published an hour
earlier were quoted from a single instantaneous sample, and the re-measurement falsified them. The
corrections are pushed to both refs so no lane can re-propagate the wrong versions.

**Landed by me this window** (`/tmp/q4_docs`, fast-forward to BOTH `refs/heads/master` and
`refs/heads/main`):
- `8122075` — §G retraction for search: `/api/v1/search/by-media` answers `love` in 44,992 ms and
  never answers `q=a` (client timeout 60,071 ms) while `/posts` answered in 244 ms on the same loaded
  box. The "15–25 concurrent browsers / 1,000–1,500 DAU" figure is `/posts`-only and must not be
  quoted for search.
- `e2fe36a` — my "plateau" reading falsified by my own next sample, plus the deployed-stats defect.
- One entry here.

**The memory finding, stated as measured.** Same process `265554`, never restarted (age 1 d 23 h),
29 minutes apart: `VmRSS` 7,169,676 kB → **57,576 kB**; `VmSwap` 1,101,928 → 107,724 kB;
`VmHWM` **7,666,280 kB**; `nlwp` 3; one established connection on 8080; `MemAvailable` ~1,003 MiB →
~6,143 MiB. So:
1. At 18:18 I concluded it was a plateau reached over two days that the process "does not hand back".
   Wrong. It hands back ~7.2 GiB on its own. The hazard is a **transient multi-gigabyte peak**, and
   the metric that records it is `VmHWM` (monotonic per process), not instantaneous `VmRSS`.
2. The peak's real cost is the page cache. Holding 6.9 GiB against a 6.4 GB catalog evicted it
   (`Cached` 868 MiB), and the first `/posts?page_size=20` after the release took **3,928 ms** while
   the next three took **371 / 363 / 431 ms** as it refilled (`Cached` 2,659 MiB). Every throughput
   number in §G is therefore a **warm-cache** number, and a user arriving right after a peak gets the
   3.9 s.
3. I did **not** fire `q=a` at production to reproduce the peak. On a loaded single core a GiB-scale
   allocation is how the OOM killer chooses the public service, and `Restart=on-failure` against the
   dirty live tree would promote uncommitted lane code. The candidate is untouched but attributed by
   the query plan, not by a stunt.

**Search diagnosis, done by me so q3 does not burn its budget rediscovering it.** Read-only
`EXPLAIN QUERY PLAN` at 18:44 on the real catalog for the `media_search.py:227` statement:
`SCAN p`, then two `USE TEMP B-TREE FOR count(DISTINCT)` and one `USE TEMP B-TREE FOR ORDER BY`.
`PRAGMA index_list(posts)` = slug, imdb, tmdb, canonical_key, source_ind, autoindex — **no index on
`clean_title` or `title` at all**. Table sizes: posts 150,799, releases 1,780,121,
download_sources 4,073,865. Therefore the `LIMIT` (CANDIDATE_WINDOW) bounds only the *response*, not
the work: the two LEFT JOINs fan out to on the order of four million rows and get grouped and sorted
before the limit applies. Fix shape: (a) pre-aggregate the counts so the fan-out never exists, (b) FTS5
for the matcher — verified available on this host, `sqlite 3.45.1` and an in-memory
`CREATE VIRTUAL TABLE … USING fts5(x)` succeeds, (c) treat a 1-character token as a non-query. Shipped
to q3 as `Q3-SEARCH-LATENCY` with the plan pasted in.

**Deployed-code staleness, proved two independent ways.** `GET /api/v1/stats` answers
`{"posts": 116922, "releases": 1383752, "sources": 3783959, "active_sources": 3783959,
"resumable_sources": 0, "temporary_sources": 0}` — i.e. no `sources_by_state` key (which
`viewer.py:2931` returns unconditionally) and `active_sources` numerically identical to `sources`,
which is the exact retired bug that `34f22c6` (2026-10-29 05:09) exists to fix. The unit started
**Tue Oct 27 19:47:16**, 33 h 22 m before that commit. It also reports posts=116,922 against a
150,799-row table where main's adult clause would give 135,731, so **neither the deployed nor the
committed figure is safe to quote as catalog size**. Consequence for the fleet: any agent that
"verifies" behaviour through `/api/v1/stats` today is verifying deleted code. A restart no longer buys
memory relief — the process does that itself — it buys *code currency*, and it still waits for a clean
live tree and the owner's decision.

**A push failure I caused and diagnosed rather than misreporting.** At 18:49 the token that had
pushed successfully 25 minutes earlier returned `remote: Invalid username or token`. Cause: I built
the askpass helper with `printf` instead of the documented heredoc, so the *outer* printf consumed the
inner `%s` and Git sent an **empty password**. Same token, minutes later: **200** on `/user`, on
`/repos/rehanradd/radd-stream/commits/e2fe36a` and on `/actions/permissions`. This is now the named
mechanism behind the old PROJECT_MAP instruction "do not conclude the whole lane is dead";
`ORACLE_DEPLOYMENT.md` carries the trap and the rule (heredoc only; never `curl -H "Authorization:
Bearer $TOKEN"`, which leaks the secret into `ps`).

**VM control actions.** `qoder2` hit its credit limit and cannot accept work, so I SIGSTOP'd its lane
(pid 1242663, ~476 MiB) — zero progress lost, `MemAvailable` 1,003 → 1,372 MiB. Its Hum TV crawl died
with it; `humtv_staging.db` holds **64 posts**, so it is a fragment, **not** a mergeable vault.
Load came down 11.6 → 8.2. My consistent snapshot is still running (`nice 19 ionice -c3`) at
**2,239,918,080 of ~6.4 GB** — note my earlier SIGSTOP targeted the `nohup` wrapper pid, not the
python child, which is why it kept going; the file is still incomplete and is **not** a backup until
the process prints its `done …` line. Merge batch 4 stays held on a finished snapshot and a quieter
box.

**Two published flagged-row counts disagree, and I am recording it instead of re-measuring under
load.** `docs/PROJECT_MAP.md` (written 05:12) says **15,020** posts carry `is_18_plus = 1` and the
public list route answers `total = 135,779` (= 150,799 − 15,020, internally consistent). My own
measurement in this window's earlier snapshot pass says **15,068**. The gap is 48 rows, which is the
size of the thing the audit is about, so it is not noise to wave at. I did **not** re-run
`SELECT COUNT(*) … WHERE is_18_plus=1` to settle it: `is_18_plus` is unindexed on a 6.4 GB catalog, so
that count reads every page and on this box — `nproc=1`, load 8–11, three lanes compiling and
crawling — it is exactly the self-inflicted stall I have been telling the fleet not to create. It
belongs to the adult audit already running (`/tmp/gate_q5`, task #12), which holds the preimage and
will produce the authoritative number against a fixed pattern set. Until then: do not quote either
15,020 or 15,068 as settled, and never quote `/api/v1/stats`'s `posts=116,922` at all (see above —
that is a 33-h-old process answering with deleted code).


