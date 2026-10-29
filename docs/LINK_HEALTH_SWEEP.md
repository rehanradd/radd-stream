# Link-health sweep — how to knock on 3.7 M doors on one vCPU

Status: **design + arithmetic only.** Nothing in this file was probed against a hoster and
nothing was read out of the 6.4 GB catalog. Every code-derived number below was taken from
the source at `54662d2` (cited by line), and every arithmetic consequence is pinned by
`Fast_Fetch/test_link_sweep_budget.py` (`python3 -S Fast_Fetch/test_link_sweep_budget.py`,
in-memory, ~1 s). Written at host load **10.2 on one vCPU**, which is itself the reason the
design is a sample and not a sweep.

## 0. The gap, as measured by the qoder4 master tonight (cited, not repeated)

`docs/CAPACITY_MEASURED.md` at `54662d2` records two independent reads that agree:

- `cat_projection_meta` (live, 18 rows, stamped 2026-10-25): `links_by_state = {"unchecked":
  3456460}`, `link_coverage = 0.0`.
- `GET 127.0.0.1:8080/api/v1/stats`: `sources: 3705474`, `active_sources: 0`,
  `resumable_sources: 0`, `sources_by_state = {unchecked: 3696910, dead: 21, unknown: 8543}`.

So **`active_sources: 0` is accurate, not a bug.** The consequence is product-wide: the
quality ladder, "fastest server", rendition failover and any speed-ranked playback promise
are today unmeasured guesses, because `score_link()` and `rank_score` (`link_health.py:695`)
derive from a `latency_ms` / `download_speed_mbps` that no row carries. `viewer.py:2894`
states the reason in the code's own words: *"A scraper writes 'active' into every row at
ingest and only `link_state.propagate()` retires that claim"* — so the projection maps an
unprobed `active` back to `unchecked` (`viewer.py:2896-2900`, `_LEDGER_STATE_SQL`), which is
why 3.46 M links are `unchecked` rather than 3.46 M links being `active`.

## 1. COST — what one probe actually is

From the code path, not from intent (`link_health.py`):

| knob | value | line |
|---|---|---|
| per-socket budget (connect, headers, each read) | `DEFAULT_TIMEOUT = 8.0` s | `:125` |
| body sample read to decide `resumable` / content | `DEFAULT_SAMPLE_BYTES = 524288` (512 KiB) | `:126` |
| redirect hops per phase | `DEFAULT_MAX_REDIRECTS = 5` | `:127` |
| phase 1 | `HEAD`, then `_chain()` follows redirects | `:535-536`, `_chain` `:329` |
| phase 2 | `GET` with `Range: bytes=0-<sample-1>`, only when HEAD answered nothing useful | `:568-571` |
| pool | `workers = 8` default in `probe_many()` | `:1015` |

So one link costs **1 HEAD** in the good case; **up to 6 requests** when HEAD bounces through
the redirect chain; **up to 12 requests + 512 KiB read** when HEAD is uninformative (405/400/501)
and the ranged GET also redirects (`_chain` is called per phase, `_raw_request` reads exactly
`sample_bytes` at `:302`). `resumable` is decided from the *response*, not from a download: 206
with `Content-Range` proves it, and a 200 that ignores `Range` only proves it when the server
also says `Accept-Ranges: bytes` (`:632-634`). No branch reads the whole file.

**Where the time goes, and why it is not CPU.** This is a network-bound workload: 512 KiB of
TLS-compressed bytes and a few KB of headers is tens of milliseconds of one vCPU's work; the
rest is waiting on somebody else's server. That distinction is the whole design problem, because
on this box waiting is *also* scarce — every parked worker is a thread on a 1-core scheduler
under a load average of 10, and the service itself needs that core.

**The three rates, and what follows.** Call a reachable host `T_ok` and an unreachable one
`T_bad`. `T_ok` is RTT + TLS + server time; on this class of hoster, ~0.3–0.8 s, so take
**0.6 s**. `T_bad` is bounded by the code, not by hope: a black-holed connect burns the full
**8.0 s** (`:125`), so a dead-tail probe costs ~13× a live one.

- At `workers = 8` and an idealised 0.6 s per link: 3,705,474 × 0.6 / 8 = **277,910 s ≈ 77 h ≈
  3.2 days of continuous wall time**, CPU-seconds in the low thousands.
- Add a realistic dead tail, priced as its own term. If 10 % of links are dead or firewalled,
  each burns the full 8.0 s: `0.1 × 3,705,474 × 8 s / 8 workers = 370,547 s ≈ 4.3 days`, on
  top of the live term `0.9 × 3,705,474 × 0.6 s / 8 = 69 h`. **Thread-bound total ≈ 7.2 days;**
  the politeness ceiling alone (§3) is `3,705,474 × 1 s / 8 = 128.6 h ≈ 5.4 days`. The larger
  governs, so the honest estimate is **≈ 7 days of the box's only core doing nothing else.**
- Politeness is the actual binding constraint (§3). At 1 in-flight request per host and 1 s
  between requests to the same host, the achievable rate is set by the number of *distinct
  hosts*, not by `workers`: with 8 hosts you cannot exceed 8 links/s however many threads you
  open, and 3.7 M links at 8/s is **128 hours**.

**Answer, plainly: a full sweep is not feasible on this box.** Not "slow" — infeasible: ≈ 7
days of continuous single-core time, every day of it competing with a live service that was
OOM-killed at 19:14:31 and restarts being the owner's call. What *is* feasible is a bounded
sample that supports a bounded claim, plus incremental coverage earned by traffic (§8).

## 2. SAMPLE THAT SUPPORTS A CLAIM

Failure is not uniform across links, so the question is which stratum predicts playback
success. The candidates and why they lose:

- **By title / site / quality tier** — wrong, because the outcome does not depend on the work.
  `4 Play` from hindilinks4u does not fail because it is `4 Play`.
- **By release vs download** — partially real (different URL shapes) but it is a *proxy* for
  the host, and it is already implied by the host stratum.
- **By host** — the right answer, and the code agrees with the reasoning: token rot
  (`401/403/429`) is `expired` **because a host's tokens rotted** (`link_health.py:875-894`,
  `link_state.classify()` `:274` maps 401/403/429 → `expired`), `Accept-Ranges`/206 support is
  a property of the *server software*, `cors_open` is a *server header*, and a dead CDN edge
  takes every link on it down together. One host's verdicts therefore generalise across that
  host's links and not across others.

Stratify by **registered host of `cat_links.url`** (`link_health._host_of`, `:683`), allocate
proportionally to each host's link count, and sample within a host across services and quality
tiers so a tier is never confounded with a host.

The arithmetic (normal-approximation margin `1.96·sqrt(p(1-p)/n)`, worst case `p = 0.5`):

| claim | n per stratum | margin at 95 % | probes | wall time at the §3 rate |
|---|---|---|---|---|
| overall "X % alive" | 384 | ±5.0 % | 384 (proportional) | minutes |
| overall, tighter | 1,000 | ±3.1 % | 1,000 | ~20 min |
| overall, ±2 % | 2,401 | ±2.0 % | 2,401 | ~40 min |
| **per-host** ±5 % | **384 within that host** | ±5.0 % | 384 × hosts | see below |

Consequences stated honestly:

1. **A 1,000-link proportional sample supports one sentence: "between P−3.1 % and P+3.1 % of
2. **A per-host table costs 384 × (number of hosts you want to name)** — and it is cheap,
   which is the design's whole point. At 8 hosts in flight and 1 s spacing the ceiling is 8
   probes/s, so 20 named hosts × 384 = 7,680 probes is **0.27 h politeness-bound, 0.36 h once
   the 10 % dead tail is priced in — about 22 minutes of work**; 40 hosts (15,360 probes) is
   ~43 minutes. Wall *clock* is a separate choice: spread over hours, never a burst.
   ≥ 2 days of clock time to stay polite; 40 named hosts is 15,360 probes ≈ 4.3 h of work.
   That is the largest honest thing this box can do in a weekend.
3. **A host sampled below 30 links supports no percentage at all.** Below that the interval is
   wider than the number and the table would be decoration. `test_link_sweep_budget.py` pins
   this as a refusal, not a warning.
4. **Do not write a survival percentage from a sample of the links *people play*** — traffic
   sampling measures what works, not what is there, and the product question ("how many of the
   catalog's doors open") needs a probability sample of rows.

What the sample buys immediately, and cheaply: the `unknown`/`unchecked` wall becomes a number
with error bars, and `rank_score` starts having a distribution to calibrate against.

## 3. POLITENESS AND BLAST RADIUS

- **Concurrency: 1 in-flight request per host**, never per link. `probe_many(workers=8)`
  parallelises *across* hosts; a host key must never be touched by two workers at once
  (`_one()` is per-thread but nothing today serialises per host — this is the one code change
  the sweep needs, and it is a queue, not a rewrite).
- **Spacing: ≥ 1.0 s between requests to the same host**, jittered 0.7–1.6 s so the run does not
  look like a metronome. 8 hosts max in flight ⇒ ≤ 8 links/s globally, which is also the answer
  to "why not 64 workers": the ceiling is per-host, and extra threads only deepen the queue.
- **Hard host rule, already in the code and to be respected, not re-invented:**
  `_blocked_host_reason()` (`link_health.py:191`) and `_block_reason()` (`:226`) refuse the
  known-hostile and private targets, `_is_blocklisted()` (`:997`) skips `dropgalaxy.vip`-style
  names and TLD suffixes, and a skipped link returns `error="blocklisted"` **without touching
  the network** (`:1043-1045`). `allow_private` stays False — a sweep that reaches loopback or
  RFC1918 from the production box is an SSRF, not a probe.
- **On 429/403: record, never retry-storm.** The vocabulary already does the right thing —
  401/403/429 is `expired` (`link_state.py:274`; `verdict_state` `link_health.py:889-891`),
  i.e. "the file exists, our token rotted". The sweep must additionally **park that host for
  the rest of the run** on a 429: a 429 is a request to slow down, and returning twenty seconds
  later is how an IP gets a permanent block. Exponential host backoff (`60 s → 900 s → this
  run never returns`), counted in the checkpoint, is bounded and cheap.
- **Total blast radius cap per run:** 10,000 requests, hard stop, printed as a number. That is
  ~2.8 h at the polite ceiling and it keeps a misconfigured loop from becoming the reason a
  hoster blocks this address.

## 4. RESUMABILITY AND MEMORY GUARD

The scraper rule is the template and is adopted unchanged: **stop below 2,500 MB
`MemAvailable` or 800 MB `SwapFree`, flush every N links, never write outside a staging file.**

- **Batch size: 500 links per page**, which is the unit of both the flush and the abort check.
  At ≤ 8 links/s that is ~60 s per batch: short enough that a kill loses minutes, long enough
  that the checkpoint write is not the bottleneck. The bounded page is already the code's
  contract: `link_state.iter_pending()` (`:445-459`) returns `(rows, page_end_id)` and its
  docstring is explicit that *"the scan may reach past them so un-probeable URLs (magnet:,
  empty) cannot wedge the cursor forever. The caller advances to `page_end_id`, the highest id
  actually seen, probed or not."* **Advance the cursor to `page_end_id`, never to the last
  probed id** — that single rule is what makes an interrupted run resumable instead of stuck.
- **Checkpoint table** (in the staging file, one row, so progress is a stored number — §6):

  ```sql
  CREATE TABLE IF NOT EXISTS link_sweep_run (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      started_at REAL, updated_at REAL,
      after_id INTEGER NOT NULL DEFAULT 0,   -- resume cursor: WHERE id > after_id
      links_done INTEGER NOT NULL DEFAULT 0, -- stored counters, never a scan
      alive INTEGER, dead INTEGER, expired INTEGER, blocked INTEGER,
      no_verdict INTEGER, host_parked INTEGER,
      rows_written INTEGER, notes TEXT
  );
  ```
  One `UPDATE … WHERE id = 1` per batch, inside the same transaction as the evidence rows, so
  the cursor and the results cannot disagree after a kill.
- **Resume without re-probing:** `iter_pending(only_unchecked=True)` already asks for rows
  without a verdict, so a re-run picks up where the cursor is; and the journal is idempotent by
  construction — `merge_evidence_journal()` (`link_health.py:964`) merges samples with an EWMA
  (`DEFAULT_EWMA_WEIGHT = 0.4`, `:129`), and `apply_evidence` stamps `last_evidence_at`, so a
  row that has been probed is simply not pending any more. A killed run therefore costs the
  ≤ 500 links of the interrupted batch, nothing else.
- **Memory guard**: read `MemAvailable`/`SwapFree` from `/proc/meminfo` **per batch** (a file
  read, not a scan). The workers hold at most `8 × 512 KiB = 4 MiB` of sample bodies at a time,
  so the sweep's own footprint is trivial and the guard exists for what else is on the box —
  five lanes and the service, which is why it is checked and not assumed.
- **Never above load 4.** Add a gate the fleet rule can be enforced by: if
  `getloadavg()[0] > 4.0`, sleep 60 s and re-check; if it is still above 4 after 30 min, exit
  0 with `notes` naming the load. This design's whole claim is that it can run unattended
  without hurting production, and that is false without this gate.

## 5. WRITE PATH — staging first, merged by the existing door

The sweep writes to a **staging file** (`/tmp/link_sweep_<runid>.db`, or the operator's chosen
scratch path — never anything under `/home/ubuntu/radd-stream-data/`), with the same
`cat_links`-shaped evidence columns, and the merge into the projection is
`catalog_v2.apply_evidence()` and nothing else (`admin_panel.py:2542` calls it as
`catalog_v2.apply_evidence(conn, link_ids=[...])`; `link_health.py:972` notes it is designed so
it "can run from cron as often as it likes"). Zero new write path, zero new vocabulary.

The hazard being avoided is measured, not theoretical: **a second writer on a file that a
caller already holds a write transaction on waits `timeout=60` and then raises
`database is locked`.** That is exactly the failure the qoder4 master fixed in
`import_themoviebox.py::export_staging` at `1aafddb`, and the fix was to **thread one connection
through instead of opening two**. Adopted here as a rule, not a suggestion:

1. One `sqlite3.connect()` per process, for the staging file; one for the read-only catalog
   opened as `file:…?mode=ro`; **never** a connection to a writable live catalog.
2. Every probe batch: `BEGIN IMMEDIATE`, write evidence + bump the cursor, `COMMIT`. If
   `database is locked` appears anywhere in a sweep, that is a bug in the sweep, because a
   design that opens two writers was rejected on purpose.
3. The merge into production is a separate, scheduled, single-connection step run by whoever
   owns the file — it is a write to the catalog the service has open, so it is the owner's call
   and it happens with the same review discipline as `migrate_search_indexes.py`
   (`docs/SEARCH_LATENCY_FINDINGS.md` records why an unreviewed write to a live catalog is the
   mistake that produced a false "missing index" report).

## 6. THE 26-SECOND LESSON — progress is a stored number

Cited from the qoder4 master's measurement (2026-10-30), not repeated here because re-running
it at load 10 breaks the fleet rule: `SELECT COUNT(*) FROM posts` = **0.91 s**, the same read
with `WHERE is_18_plus = 1` = **26.46 s**. The lesson is not "counts are slow", it is *which*
count is slow: the wide-row predicate read costs 29× the index-only one.

Therefore in this design: **no progress counter, coverage figure, or `state` tally is ever
computed by scanning.** They are read from `link_sweep_run` (§4) and from
`cat_projection_meta`'s stamped `links_by_state` / `link_coverage`, which
`link_state.status_summary()` (`:885-915`) computes once at the end of a merge and writes as
data. The dashboard and `/api/v1/stats` must read those stored values. If a future operator
panel ever answers a coverage question with `GROUP BY state` over `cat_links`, it has
reintroduced a 26-second read into a request path and should be treated as a defect, not a
style preference.

## 7. WHAT "ACTIVE" MAY MEAN — and what no probe can ever know

First, where the 21 `dead` and 8,543 `unknown` came from, since `active_sources: 0` proves
nothing was swept. The vocabulary is closed and documented: **`cat_links.state` accepts
`unchecked|active|dead|expired|unknown`** (`catalog_v2.py:1341`), and `unknown` is already
counted as *not alive* — `WHEN state IN ('unknown','unchecked') THEN 0` (`catalog_v2.py:488`).
The writer of `unknown` is the **embed/host resolver**, not the sweep: `importers/host_resolvers.py`
returns `status="unknown"` whenever an attempt produced no verdict — `:669` splits
`"blocked" if status in (401,403,429) else "unknown"`, and `:675`, `:729`, `:739`, `:800`, `:913`
each set it on a path that got an answer it could not interpret. The 21 `dead` are rows that
earned a *measured* failure verdict, via the two pure classifiers
(`link_health.verdict_state()` `:875-894` → `catalog_v2.py:2378`, and
`link_state.classify()` `:263-275`), most plausibly written by `apply_evidence()` on the JIT
path when the resolver actually used a link. **I did not re-count either bucket** — I read the
code that can produce them, which is the question asked.

What a probe may assert, tiered by the evidence it required:

| assertion | evidence a probe has | admissible? |
|---|---|---|
| **reachable now** | 2xx/3xx on HEAD, or a ranged GET that returned bytes | **yes**, and it means "answered at `last_evidence_at`" — a timestamp, not a property |
| **reachable with a `Range` header** | 206 + `Content-Range`, or 200 that honoured the range and said `Accept-Ranges: bytes` (`:632-634`) | **yes** — this is exactly what `resumable_sources` is allowed to count |
| **reachable but HTML-bridge** | `_classify()`/`_sniff()` (`:394-438`) saw `text/html`, and `_hls_has_media()` (`:459`) tells a real manifest from a portal page | **yes, as a different kind of fact**: the URL is alive, the *media* is behind a page. `score_link()` must not rank it with a byte stream |
| **token rotted** | 401/403/429 → `expired` | **yes**, and it is the honest word: the file is there, our URL is not |
| **gone** | 404/410/451 (`link_state.py:54`) → `dead` | **yes** |
| **"this link is fast enough for 1080p"** | 512 KiB of a multi-GB file | **no** |

What no probe can know **without downloading the media**: whether the bytes are the film
(wrong-cut, cam-rip, a re-encoded stub, a 4-KiB placeholder that sniffs as MP4); whether they
*remain* playable (a host that serves 200 today and 404 next week is a rotting catalog, not a
live one); whether playback succeeds on a phone (codec profile, DRM, Media3 behaviour —
`App/docs/PLAYER_SPEC.md` still correctly says nothing in that player has run on Android); and
whether a bridge page's *second* hop works, which needs the resolver, not the prober. So
`active` may mean **"answered, with these protocol properties, at this instant"** and may never
be rendered as "playable". The one product promise this design can support is exactly the
sentence in §2, plus per-host tables at 384 samples each.

## 8. What to build, in order, and the cost of each

1. **A per-host serialiser in front of `probe_many()`** — the only code change the sweep needs
   (§3). Days of work: small. Without it the politeness story is a comment, not a guarantee.
2. **`link_sweep.py`** with `plan | run --limit N | status`, following
   `migrate_search_indexes.py`'s shape (a required `--target`, a refusal to write anywhere
   else, `plan` printing the cost before anything runs). Cost: modest; the arithmetic is done.
3. **A 1,000-link proportional sample** on a quiet window (load < 4): ±3.1 % overall, ~20 min
   of the box, ~2 GB of egress at worst. **This is the first honest coverage number the project
   will have had.**
4. **Per-host tables, 384 each, only for hosts the app actually routes through** — ~22 minutes of probe time per 20
   named hosts. Do this after 3, because 3 tells you which hosts matter.
5. **Incremental coverage earned by traffic** (the free half): every resolve/serve event is a
   probe opportunity, `merge_evidence_journal()` (`:964`) already ages samples correctly, and it
   costs no dedicated sweep time. This is how 3.46 M `unchecked` becomes a number without ever
   running the infeasible sweep — and it is why `resumable_sources` can become non-zero before
   `active_sources` does.

`test_link_sweep_budget.py` is CI-safe (in-memory, ~1 s, no network) and is added as a step. The
`sweep` itself is **not** in CI and never will be: a suite that opens 384 sockets to third-party
hosts is a test that fails when the world is healthy.
