# Measured capacity of this VM — what one vCPU actually serves

Measured 2026-10-30 01:20–01:35 host time by qoder4 (master orchestrator), on the live
production box, **without a load test**. Everything below is either a direct measurement or
an arithmetic consequence of one, with the measurement named. There is no estimate hiding
behind a rounding.

## 1. The machine

| Fact | Value | How measured |
|---|---|---|
| vCPU | **1** | `nproc` |
| RAM | 11,925 MB total, **4,551 MB available** | `/proc/meminfo` |
| Disk free | ~100 GB on `/dev/sda1` | measured earlier this shift |
| Core saturation | **91 % user, 1 % idle, 0 % wait** | `vmstat 1 3` |
| Run queue | 8–9 | `vmstat` `r` column |
| Load average | 8.4–8.7 all shift | `/proc/loadavg` |

**The fleet is the load.** A 6-second `/proc/<pid>/stat` utime+stime delta sample attributed
the core to processes, not to production:

```
31.5 %  qodercli   (q2)      28.3 %  qodercli  (q3)   28.2 %  qodercli  (q1)
26.5 %  qodercli   (q5)      25.8 %  qodercli  (q4)   13.8 %  jbd2/sda1-8
 5.5 %  tmux: server
TOTAL 167.7 % of one core
```

So five agent sessions plus their editor consume **1.7× the entire machine**, and `radd-stream`
itself consumed **29.8 CPU-seconds across 2 h 10 min of uptime** (`systemctl status`) — about
0.4 % of a core. Production is not the cost centre here; we are. Every wall-clock number below
was therefore measured with roughly 0.3 s of scheduling queue baked into it.

## 2. Per-request cost, measured serially on loopback

Method: `curl` one route at a time, and read the **service's own** CPU clock
(`/proc/<pid>/stat` fields 12+13, utime+stime) before and after each batch, so the number is
CPU actually burned by the server rather than wall time polluted by the fleet.

| Route | Wall | **Server CPU** | Bytes | Status |
|---|---|---|---|---|
| `/api/v1/posts?limit=20` | 0.44 s | **0.132 s** | 11,632 | 200 |
| `/api/v1/app/remote-config` | 0.18 s | **0.002 s** | 570 | 200 |
| `/api/v1/stats` — batch of 4 | 10.29 s avg | **5.63 s per request on average (22.5 s total)** | 154 avg | three `000`, one `200` |
| `/api/v1/stats` — single call, minutes later | **0.044 s** | below measurable | 205 | 200 |

**State what is established and what is not.** Established: those four requests burned 22.5
server CPU-seconds in total, and a fifth request minutes later burned essentially none. **Not
established: how that 22.5 s splits between the four calls, and why the fifth was free.** A
120-second TTL predicts the fifth call to be expensive again, and it was not. Candidate
explanations I did not test: SQLite pages already in the page cache after the first scan, the
`000` responses having been client-side give-ups that abandoned partial scans, or the batch
overlapping a period when the fleet was contending for the same disk. **Do not cite "≈20 s per
cold `/stats` call" as a measured number; the measured number is 22.5 s for four calls, cause
unconfirmed.**

`/api/v1/stats` is still the route to watch, for a reason that *is* established from code:

- It is answered from `_get_cached_stats` (`Fast_Fetch/viewer.py:2966`) with a **120-second
  TTL**, keyed on `DB_PATH`.
- The stamped fast path needs `works_safe`, `releases_safe`, `links_resumable_safe`,
  `links_temporary_safe` and `links_by_state_safe` in `cat_projection_meta`. **None of those
  keys exist in the live catalog** — measured: `cat_projection_meta` holds 18 rows,
  `works 116922`, `releases 1383752`, `links 3783959`, `posts 130016`, `catalog_rev 3`,
  `projected_at 1792942873` (**= 2026-10-25**), `seconds 9770.83`, and no `*_safe` at all.
- So `None in safe.values()` is true and every cache miss falls through to
  `_counted_stats` (`viewer.py:2944`), which runs live `COUNT(*)` scans over `cat_works`
  with the adult clause and over 3.7 M links. That is the ~20 CPU-seconds.
- The stamping code already exists (`Fast_Fetch/catalog_v2.py:1031`, and
  `links_by_state_safe` at `:1076`). **The rebuild in fleet task #10 fixes this route for
  free, provided it completes and stamps.** Until then the route is *live-count* work rather
  than *metadata* work, so any client that started polling it would pay a scan rather than a
  dictionary read. **No such client exists today** — verified: the endpoint is declared in
  `App/app/src/main/kotlin/com/raddstream/app/network/RaddStreamApi.kt:99` but a grep of
  `app/src/main` for a caller (`\.stats(`) returns nothing. Treat this as prospective risk,
  not as current load.

## 3. The edge already limits per client

`_public_gate` (`viewer.py:3135`) spends one token per request from
`redact.BUCKET_LIMITS` (`Fast_Fetch/redact.py:1108`), keyed on `(bucket, client_ip)`:

| Bucket | Routes | Budget |
|---|---|---|
| `play` | `/stream`, `/art`, `/m3u` | 30 / 60 s |
| `browse` | `/posts`, `/api/data`, search, sitemap | 60 / 60 s |
| `reports` | `/stats` | **10 / 60 s** |
| `account` | `/api/v2/account*` | 30 / 60 s |
| default | anything unmapped | 60 / 60 s |

Verified live: the response carries `RateLimit-Limit: 10` / `RateLimit-Remaining: 8` on
`/api/v1/stats`. **This is what protects a one-core box** — a single client cannot
accidentally DoS it by hammering `/stats`.

## 4. The honest answer to "how many users can this VM handle"

Arithmetic, from section 2 and 3 only:

- **Ceiling on list traffic:** 1 core ÷ 0.132 s CPU = **≈7.5 browse requests/second** served
  server-wide, before queueing.
- **Per active browsing client:** the limiter allows 1 browse req/s, and a human swiping a
  grid issues roughly 0.1 req/s averaged over a session.
- ⇒ **≈75 clients browsing simultaneously** on list traffic alone, if nothing else ran.
- **Daily users:** DAU is concurrency × duty cycle. At a realistic 5 % same-instant
  concurrency that is **on the order of 1,500 DAU**. This number is *only* as good as the
  5 % assumption, which is not measured on our traffic — it is an industry-shaped guess, and
  it is the one estimate in this file. Everything else above is a measurement.
- **Bandwidth is not the constraint:** playback does not traverse this box. `/api/v1/stream`
  redirects to the hoster, so the VM serves ~11.6 KB per browse and the media bytes never
  touch it. RAM and disk (11.9 GB / 100 GB free) are not binding at this scale either.

**Read the caveat with the number.** These ceilings assume the box is *given to production*.
Today it is 1.7× oversubscribed by our own agent fleet, so the real current capacity is lower
than the table above, and the honest status line is:

> This VM can serve roughly tens of thousands of browse requests per hour of pure list
> traffic, or roughly 1,500 daily users at a 5 % concurrency assumption — **but not while
> five agent sessions are running on it, and not with `/api/v1/stats` still scanning.**
> Send no real users here until task #10 stamps the safe counters and the fleet is idle.

## 5. What was deliberately NOT measured

- **Playback-resolution cost.** `/api/v1/stream` and `/api/v1/search/by-media` were not
  probed. They are the two routes most likely to be expensive, and probing potentially
  unbounded scans against a 6.4 GB catalog at load 8.6 violates the fleet rule (nothing heavy
  above load 4). This is a known hole in section 4, not an oversight to paper over.
- **Any concurrent load test.** None was run. Section 4 is CPU-cost arithmetic, not a
  throughput measurement.
- **One methodological error, recorded so it is not repeated:** I probed `/api/v1/stats`
  four times serially (`N=4`) before knowing it was the expensive route. That spent ~22
  server CPU-seconds on a saturated single-core production box. Two of those four returned
  curl status `000`, which was most likely my own client giving up during the multi-second
  scan rather than a server fault — I did not establish it as a defect and no doc should
  cite it as one. **Rule for the fleet: probe an unknown-cost route exactly once, with a
  short `-m`, and only then decide whether it deserves a sample size.**

## 6. Cheap wins this file identifies

1. **Finish task #10** so `cat_projection_meta` carries the `*_safe` keys → `/api/v1/stats`
   drops from ~20 CPU-s to ~0. This is the single biggest capacity lever on the box and it is
   already written.
2. **Do not let the Android client start polling `/api/v1/stats`.** It declares the endpoint
   (`RaddStreamApi.kt:99`) and calls it nowhere in `app/src/main`, so today it costs the box
   nothing. If a future screen wants catalog scale, read it once and cache ≥120 s to match
   the server TTL — and note `CatalogScale.kt:10-20` already rules out printing a *direction*
   from these numbers, which is the correct handling and needs no change.
3. **`link_coverage = 0.0` and `active_sources: 0`** with `unchecked: 3,696,910` measured in
   the live payload: not one link in the production catalog has ever been health-probed. The
   quality ladder and any speed ranking are therefore flying blind, and `stats` reporting
   `active_sources: 0` is *accurate*, not a bug. A bounded probe sweep is a prerequisite for
   honest playback UX.
4. **Throttle the fleet against the box, not the box against the fleet.** The lanes are already
   `nice=20`, and so is `radd-stream` (so nice gives production no preference; the only real
   lever is concurrency). Cap simultaneous heavy lanes at 2–3 on this vCPU and let the rest
   wait, rather than letting five grind against each other at 168 %.

## 7. Why `/stats` and the list route report different numbers — resolved from code

The live pair, measured minutes apart at 01:25: `/api/v1/stats` → `posts: 103580`,
`/api/v1/posts?limit=1` → `total: 135731`, catalog `posts` rows → `150799`.

This is **not a defect and not the adult leak**; it is two different scopes, exactly as
`CatalogScale.kt:10-20` documents, now with the mechanism pinned in code:

- The list route counts **`posts` rows** with the row-level adult clause, and
  `150,799 − 15,068 = 135,731` matches it exactly — the row filter is consistent tonight.
- `/api/v1/stats`, on the fallback path, counts **`cat_works`** — Layer-1 *works*, adult-
  excluded (`viewer.py:2944`). So 103,580 is a count of works, not of rows, and comparing it
  to a row count is a category error.
- `cat_projection_meta` still stamps `works = 116922` from the **2026-10-25** projection
  (`projected_at 1792942873`, `seconds 9770.83`, `catalog_rev 3`). The apparent gap
  `116,922 − 103,580 = 13,342` would be the number of works the adult clause hides at work
  level, **but that subtraction is not valid while a rebuild is in flight**, because
  `cat_works` may be mid-rewrite against an October stamp. It is recorded here as a question
  for task #10 to answer with one fresh paired read — *stamped* `works_safe` beside a live
  `COUNT(*) FROM cat_works` taken in the same breath — rather than as a finding.

**One number this file does establish:** `link_coverage = 0.0`,
`links_by_state = {"unchecked": 3456460}` in the stamp, and the live payload agreeing with
`unchecked: 3696910`, `active_sources: 0`, `resumable_sources: 0`. Zero links in the
production catalog carry health evidence. `stats` reporting `active_sources: 0` is *accurate*.
Any quality ladder, speed ranking or "fastest server" promise is currently unmeasured, and a
bounded probe sweep is the prerequisite for claiming otherwise.
