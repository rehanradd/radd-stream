# 📊 PROBE_COVERAGE.md — "active" is a column default, not a verdict

> Measured on the live production catalog, read-only, 2026-11-05 (host local), by lane
> **qoder13**, under crown order `qoder13_commit_and_proofs.md` follow-up.
> Every number below is **measured**, **derived** (arithmetic on measured numbers), or
> labelled **not measured**. Nothing here is transcribed from memory.
>
> **This document ships no code change.** `/api/v1/stats` is untouched, no production
> apply, no index created, no `link_state.py` or `viewer.py` edit. Deliverable = this doc
> + `Fast_Fetch/test_probe_coverage.py`.

---

## 1. The answer, in one line

Of **4,073,865** source rows the emitter reports as **4,006,773 active**, exactly **10**
carry any probe evidence. The published `active_sources` figure overstates
evidence-backed liveness by **400,677×**.

The ledger states this in its own schema (`sqlite_master`, read from production):

```sql
CREATE TABLE download_sources (
    ...
    status        TEXT      DEFAULT 'active',   -- ← the default IS the claim
    is_resumable  INTEGER   DEFAULT 0,
    http_status   INTEGER   DEFAULT NULL,
    last_checked_at TIMESTAMP DEFAULT NULL,
    ...
)
```

A row inserted by any importer that does not explicitly probe acquires `status='active'`
by **omission**. `http_status` and `last_checked_at` stay `NULL` because nobody wrote
them. So `status='active'` on 4.0M rows is not a statement that the link works; it is a
statement that **nobody knocked**.

---

## 2. Measured numbers (production, `mode=ro`)

Database: `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` (6,396,915,712 bytes,
WAL, symlinked as `Fast_Fetch/fast_fetch.db`). mtime during measurement: `Nov 4 23:04`
— **another lane was actively writing this DB while these reads ran.**

| Metric | Value | How | Cost |
|---|---:|---|---|
| total source rows | 4,073,865 | `COUNT(*)` in grouped pass | 75.5 s (single sequential `SCAN`) |
| distinct `service` values | **800** | covering index walk | 1.3 s |
| `status='active'` | 4,006,773 | covering index | 1.3 s |
| `status='unverified'` | 40,560 | covering index | 1.3 s |
| `status='js_required'` | 17,132 | covering index | 1.3 s |
| `status='unknown'` | 9,314 | covering index | 1.3 s |
| `status='expired'` | 61 | covering index | 1.3 s |
| `status='dead'` | 23 | covering index | 1.3 s |
| `status='blocked'` | 2 | covering index | 1.3 s |
| rows ever given a `last_checked_at` | **71** | `COUNT(*) WHERE` | 9.5 s |
| rows ever given a real `http_status` | **10** | single-pass aggregate | 20.6 s |
| rows with **either** evidence column | **71** | single-pass aggregate | 20.6 s |
| `status='active'` **with** evidence | **10** | single-pass aggregate | 20.6 s |
| `status='active'` **without** evidence | **4,006,763** | single-pass aggregate | 20.6 s |
| rows claiming `is_resumable = 1` | **2** | single-pass aggregate | 20.6 s |
| **verification coverage (by evidence)** | **0.00174 %** | derived: 71 / 4,073,865 | — |

Cross-checks that make these numbers safe to publish:

* The seven status counts sum to 4,073,865 exactly.
* 4,006,773 active = 10 (evidence) + 4,006,763 (none) exactly.
* The 10 code-bearing rows are a **subset** of the 71 timestamped rows (71 ∪ 10 = 71),
  which is what `run_health_check`'s write-back shape predicts for a transport failure.
* Per-service probe counts (§4) sum to 71 exactly, reconciling the grouped pass against
  the `COUNT(*)` pass run an hour apart on a DB another lane was writing.

---

## 3. What "probed" looks like in this ledger — all 71 rows

Every one of the 61 timestamped non-`active` rows has **`http_status = NULL`**:

| service | status | rows | has `last_checked_at` | has real `http_status` |
|---|---|---:|---:|---:|
| `bcdnxw.hakunaymatata.com` | expired | 60 | 60 | **0** |
| `fsl_r2` | expired | 1 | 1 | **0** |
| `new1.filesdl.co` | js_required | 17,132 | **0** | **0** |
| `bridge` | unknown | 9,314 | **0** | **0** |
| `bridge` | dead | 23 | **0** | **0** |
| `upbolt` | blocked | 2 | **0** | **0** |

Two findings, both measured, neither expected:

1. **The only host this deployment has ever knocked on is one host.** 60 of 71 probes are
   `bcdnxw.hakunaymatata.com`, `expired`, timestamped between `2026-11-02 01:34:43` and
   `2026-11-04 18:09:33`, all with `http_status = NULL` — i.e. a transport failure that
   answered no HTTP code. That is precisely the shape `test_transient_dead_heal.py` proves
   is a verdict about **our** probe being recorded as a verdict about **their** link.
2. **A non-default status label is not evidence of a probe either.** The 23 `dead` rows,
   the 17,132 `js_required`, the 9,314 `unknown` and the 2 `blocked` carry **zero**
   `last_checked_at` and **zero** `http_status`. They are scrape-time labels written by
   importers, not outcomes of a knock. `status='dead'` on those 23 rows is a parser's
   opinion.

---

## 4. Per-service coverage — exact, all 800 services

Got it in **one sequential pass** (75.5 s), grouping in Python so the query plan stayed
`SCAN download_sources` with **no `USE TEMP B-TREE`** (see §7 for why the SQL `GROUP BY
service` form is the expensive way to ask this).

**8 of 800 services have ever been probed. 792 have never been probed, and they hold
89.7 % of every row in the ledger.**

| service | rows ever probed | rows total | % of that service probed |
|---|---:|---:|---:|
| `bcdnxw.hakunaymatata.com` | 60 | 2,069 | **2.900 %** |
| `fsl_r2` | 2 | 49,117 | 0.004 % |
| `cineverse` | 2 | 70,050 | 0.003 % |
| `gdmirror` | 2 | 10,889 | 0.018 % |
| `vidrift` | 2 | 69,782 | 0.003 % |
| `pixeldrain` | 1 | 89,926 | 0.001 % |
| `vidbolt` | 1 | 69,782 | 0.001 % |
| `gd-mirror` | 1 | 59,896 | 0.002 % |
| *(other 792 services)* | 0 | 3,621,132 | **0.000 %** |

The biggest services are not slightly under-covered, they are **untouched**: `filepress`
170,387 rows / 0 probed, `gofile` 154,228 / 0, `1fichier` 149,916 / 0, `hubcloud` 136,786
/ 0, `fastdl` 121,071 / 0, `google_cdn` 116,604 / 0, `streamtape` 101,737 / 0, `mega`
68,502 / 0. `PIXELDRAIN_API.md` proves this host **can** answer a `Range` request with
`206` and sets `is_resumable = 1` legitimately — yet only 1 of its 89,926 ledger rows has
ever been looked at, and only 2 rows in the whole 4.07M-row ledger claim resumability.

### A taxonomy defect found on the way

`service` carries **800** distinct values, including `www72` … `www97` at exactly **1 row
each**. That is an importer storing the first hostname label as a service name. It means
"how many services do we have" cannot be answered from this column, and it will fragment
any per-service coverage dashboard across hundreds of singleton buckets. Not fixed here
(it is a write-path change in files other lanes own); recorded because the measurement is
the thing that exposed it.

---

## 5. The 374× inflation inside the *honest* module — a trap for whoever wires this up

`link_state.py` already ships the classifier this order asked for. It is good code and it
already gets the central fact right — `_summary_sql()` re-labels an `active` row with no
`http_status` and no `last_checked_at` as `unverified`:

```sql
WHEN status <> 'active' THEN status          -- ← this line is the leak
WHEN <no evidence columns> THEN 'unverified'
```

But `status_summary()` then computes coverage as "state is not `unverified`":

```python
if name not in unknown:      # unknown = (STATUS_UNVERIFIED,)
    checked += count
```

so a **label-only** verdict (`dead`, `js_required`, `unknown`, `blocked` — all with zero
probe evidence, §3) counts as checked. On today's ledger:

* coverage **by status label** = 26,542 / 4,073,865 = **0.6515 %**
* coverage **by probe evidence** = 71 / 4,073,865 = **0.00174 %**
* ratio = **374×**

Same class of error as `active_sources`, one layer down, and it survives the wiring the
obvious way. Anyone who switches `/api/v1/stats` to `link_state.stats_payload()` and sees
coverage jump from 100 % to 0.65 % has not fixed it — they have moved the goalpost.
`test_probe_coverage.py::TestLabelIsNotEvidence` pins this behaviour so the discrepancy is
visible and a later fix cannot pass silently.

**I did not change `link_state.py`.** qoder12 is live in `resolved_cache.py` on the
`_derive_kind` fix tonight, this order ships no code change to a live module, and the
correct resolution (report `verdict_labelled_sources` and `evidence_backed_sources` as two
fields) is a design decision for the Crown, not a lane's unilateral edit.

---

## 6. The read-only query the stats emitter should use

Run it `mode=ro` with `PRAGMA query_only=ON`. `evidence` means — **with the outer
parentheses, which are load-bearing**:

```sql
( ( d.last_checked_at IS NOT NULL AND d.last_checked_at <> '' )
  OR ( d.http_status  IS NOT NULL AND d.http_status  <> 0 ) )
```

> ⚠️ **Precedence trap, found by `test_probe_coverage.py` before this shipped.** Written
> without that outer pair, `A OR B` interpolates into
> `d.status = 'active' AND NOT <evidence>` as `status AND ((NOT A) OR B)`. Every probed
> row then satisfies *both* the checked and the unchecked arm, so
> `checked_active + unchecked_active` silently exceeds `active_sources` — measured on the
> fixture: **5 rows reported as 7**. A coverage field that double-counts is worse than the
> conflation it replaces, because it looks like a fix. `test_checked_plus_unchecked_equals_
> the_published_active_count` is the assertion that catches it; keep it.

`http_status = 0` is excluded deliberately: `0` is what our own probe writes when **we**
failed to connect, not an answer from the host. Treating `0` as evidence would record a
verdict about our probe as a verdict about their link.

```sql
-- READ-ONLY coverage report: "unchecked" separated from "checked-and-active".
SELECT
    COUNT(*)                                                          AS sources,
    SUM(CASE WHEN <evidence> THEN 1 ELSE 0 END)                       AS checked_sources,
    SUM(CASE WHEN <evidence> THEN 0 ELSE 1 END)                       AS unchecked_sources,
    SUM(CASE WHEN d.status = 'active' AND  <evidence> THEN 1 ELSE 0 END) AS checked_active_sources,
    SUM(CASE WHEN d.status = 'active' AND NOT <evidence> THEN 1 ELSE 0 END)
                                                                       AS unchecked_active_sources,
    ROUND(100.0 * SUM(CASE WHEN <evidence> THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 4)                              AS verification_coverage
  FROM download_sources d;
```

**Today's `active_sources` → the honest replacement** is the swap of one predicate: from
`d.status = 'active'` to `d.status = 'active' AND <evidence>`. Same rows scanned, two more
columns read, no new join.

On the current ledger that query returns `checked_active_sources = 10` and
`unchecked_active_sources = 4,006,763`.

### If the emitter must keep its adult clause (it must)

`viewer.py`'s `/api/v1/stats` does not count the raw table; it counts the **public**
subset, and that is correct behaviour this doc does not disturb:

```sql
  FROM download_sources d
  JOIN releases r ON r.id = d.release_id
  JOIN posts    p ON p.id = r.post_id
 WHERE p.is_18_plus IS NULL OR p.is_18_plus = 0
```

Keep that join and apply `<evidence>` inside the same `CASE` expressions. Two caveats the
Crown should weigh before wiring:

* The row-level clause above is the **same-key-only** shield. Until `backfill_adult_key.py`
  has actually run on the deploying DB, a cross-key adult twin is counted in this denominator
  (see `catalog_exporter.py`'s HONEST LIMIT block). A count is not a display surface, so this
  does not leak a flagged work, but it is not the public catalog either.
* **I measured the bare-table cost (20.6 s), not the joined cost.** The joined form runs
  inside the pass the emitter already performs, so the marginal cost is two column reads,
  but that is reasoning, not measurement. `not measured` — flagged as such.

### Bounded variants that are cheap enough to run on a hot path

Both of these are covering-index walks measured at **1.3 s** each on the live 6.4 GB box at
load 4–6, with `EXPLAIN QUERY PLAN` confirming no table fetch and no temp b-tree:

```sql
SELECT status, COUNT(*)  FROM download_sources GROUP BY status;   -- idx_sources_status_temp
SELECT service, COUNT(*) FROM download_sources GROUP BY service;  -- idx_sources_service
```

Neither can answer "was it probed" — the evidence columns are in no index (§7). A coverage
number on a hot path needs either a materialised counter or the index; there is no third
option in this schema.

---

## 7. Why the honest number costs a full pass, and what I did not do about it

There are **five indexes** on `download_sources` and **none** contains `last_checked_at`,
`http_status`, `updated_at` or `expires_at`:

```
idx_sources_rel         (release_id)
idx_sources_res         (resource_id)
idx_sources_status_temp (status, is_temporary)
idx_sources_rel_status  (release_id, status)
idx_sources_service     (service)
```

Measured plans for the coverage question:

| query | plan | verdict |
|---|---|---|
| `COUNT(*) … last_checked_at IS NOT NULL` | `SCAN download_sources` | 9.5 s |
| evidence aggregate, no `GROUP BY` | `SCAN download_sources` | 20.6 s |
| same, grouped in Python | `SCAN download_sources` | 75.5 s (4.07M `Row` objects) |
| `service, COUNT(*), SUM(…last_checked_at…)` `GROUP BY service` | `SCAN … USING INDEX idx_sources_service` | **worst option** — not covering, so 4.07M row fetches in service order (scattered I/O) instead of one rowid-order pass |
| `service, COUNT(*)` only | `SCAN … USING COVERING INDEX idx_sources_service` | 1.3 s — index-only, no fetch |

That table is why the SQL that reads most naturally (`GROUP BY service` with an evidence
aggregate) is the expensive way to ask: sqlite follows `idx_sources_service` for the
grouping and then fetches every row to get `last_checked_at`. One sequential `SCAN` plus
Python-side grouping was ~3.6× cheaper in wall clock than the aggregate alone predicted,
and produced all 800 services exactly.

**The one thing that would make this ~1 s** is `CREATE INDEX ON download_sources(last_checked_at)`
(or a partial index on `last_checked_at IS NOT NULL`). **I did not create it.** That is a
write to a 6.4 GB production database, on a host at 95 % disk with another lane's sweep
running, and index creation is a production apply — explicitly out of scope for this order.
It is a Crown decision, and the trade is: ~150–250 MB of index and a slower writer, against
making the honest number cheap enough to publish continuously.

---

## 8. Mandate rule 10 — the aggregate verdict

Rule 10 of `AGENTS.md` ("Zero Data Loss & Clone-Ready Fidelity") requires: *"record their
status (`active`, `dead`, etc.) so link health is fully auditable"*.

**False in aggregate, measured.** 4,006,763 of 4,073,865 rows (98.35 %) carry a status
label and no status evidence. There is nothing to audit: an auditor querying "how healthy
are our links?" is handed a column whose default answers for them. The rule is satisfied
for the **71** rows anybody actually probed and for nobody else.

The rule does not need renegotiation — it needs the distinction this doc names written
into it: **a recorded status is auditable only when it is accompanied by the evidence
column that produced it.** `status` without evidence is a *claim*; `status` with evidence
is a *measurement*. Reporting the first as the second is what made 100 % liveness
producible without anyone noticing.

---

## 9. Load and fleet discipline record (this is the part that could get someone hurt)

`/api/v1/stats` (loopback operator port 8081) timed before, between and after every read
run here. Numbers are wall-clock of a single bounded request, `timeout 25`.

| moment | `/api/v1/stats` | load avg (1 m) | what I had just done |
|---|---:|---:|---|
| baseline, before any read | **8.70 s** | 3.87 | nothing — qoder12's sweep was live |
| after two 1.3 s index walks | 0.28 s | 4.58 | covering-index counts |
| after the 75.5 s full pass | **10.88 s** | 6.30 | one sequential `SCAN` |
| after the 20.6 s aggregate | **0.18 s** | 5.82 | one sequential `SCAN` |

I am **not** claiming innocence. The endpoint was already at 8.70 s before I read anything,
and it fell to 0.18 s immediately after my most expensive pass, so the oscillation is
dominated by the other lane's sweep and by cache state, not by my queries — but a 10.88 s
sample did land right after my 75.5 s scan, and 4.07M-row reads evict the page cache the
live service is serving from on a 6.1 GB box. Honest summary: **five passes over the whole
ledger were run here (9.5 + 20.6 + 75.5 + ~0.2 + ~0.2 s of work) and I cannot separate my
contribution from qoder12's in the 10.88 s sample.**

Because of that I **stopped** rather than answering the last open question with a sixth
pass. Held and not run: the exact per-service × `http_status` cross-tab, the joined
(adult-clause) cost measurement, and the three disk-artifact suites.

Rules that governed these reads, for the next lane: `mode=ro` URI, `PRAGMA query_only=ON`,
one pass at a time, no copies, no writes, no `--apply`, `EXPLAIN QUERY PLAN` before every
aggregate, and a latency sample after each pass instead of an assumption.

---

## 10. Sample vs exact — a methodological warning

Before the exact pass I estimated coverage from **12 windows × 20,000 rowids = 220,000
rows** (`SEARCH … USING INTEGER PRIMARY KEY (rowid>? AND rowid<?)`, 2.5 s total) and got
**0.00091 %** with a rule-of-three upper bound of 0.00136 %.

The exact answer was **0.00174 %** — **above my own stated upper bound.**

The reason is not bad arithmetic, it is a false premise: uniform rowid sampling assumes the
rare population is *spread out*. It is not — 60 of 71 probes sit on **one host**, in
**one id band**, from **one health-check run** on 2026-11-02→04. Sampling could have
returned zero, and the bound would still have been "proven" wrong. For clustered rare
populations, stratify by the clustering key (`service`, `release_id`) or pay the one pass.
**Pay the one pass.** It cost 75 s and it is the only honest way to publish this number.

---

## 11. Exact / derived / not measured

**Measured** (production, `mode=ro`, this session): the seven status counts; 800 distinct
services; per-service row totals; 71 / 10 / 71 / 10 / 4,006,763 / 2 evidence aggregates;
the per-service probe table; the 61 timestamped-but-codeless rows and their host; the
`www72…www97` singletons; `cat_link_evidence` = **0 rows** on this catalog; every query
plan and every wall-clock cost in §7; all `/api/v1/stats` latencies in §9.

**Derived** (arithmetic on measured numbers, no new read): 0.00174 %; 400,677×; 374×;
0.6515 %; 89.7 % of rows on never-probed services; 26,542 label-counted-as-checked;
3,621,132 rows on never-probed services; all reconciliation checks in §2.

**Not measured** (do not quote these as findings): the joined/adult-clause cost of the
§6 query; the exact per-service `http_status` cross-tab; `updated_at`-based probe history;
whether production holds any `last_checked_at = ''` rows (my counts used
`IS NOT NULL AND <> ''`, so such rows are counted as *unchecked* and never surfaced — the
divergence from `link_state`'s `IS NULL` test is pinned in
`test_an_empty_string_timestamp_is_not_a_knock` but not measured against production);
whether the 60 `bcdnxw.hakunaymatata.com` failures are our egress or their abuse defence
(a 429/reset discipline stopped me from probing a third party for it); which importer
writes the label-only `dead`/`unknown`/`js_required` statuses.

---

## 12. What I recommend, in priority order — and what I deliberately did not do

1. **Do not publish a coverage dashboard until the evidence column is indexed.** The
   decision is the Crown's (production apply, §7).
2. **Wire `/api/v1/stats` to emit `checked_active_sources` and `unchecked_active_sources`
   as separate fields**, not one `active_sources`. `link_state.stats_payload()` is 90 % of
   the way there; §5 explains the remaining 10 % and why wiring it as-is is not a fix.
3. **Fix the write path, not the read path.** A scraper that inserts `status='active'` by
   default is the source of all of this. `status TEXT DEFAULT 'active'` should become an
   explicit default of `unverified`/`unchecked`, or `NULL` with the emitter treating NULL as
   unknown. That is a schema + importer change and it belongs to whoever owns `save_scraped_data`.
4. **Reconcile the `service` taxonomy** before any per-service view is built on it.
5. `cat_link_evidence` is **empty on the production merged catalog** while `link_state.py`
   writes probe rows into it. Probe evidence therefore has no history here — a `dead` today
   silently overwrites whatever was true yesterday. Worth a look at whether the merge
   dropped it or the writer never ran against this DB. **Not measured which.**

**Not done, on order:** no change to `viewer.py`, `link_state.py`, `resolved_cache.py`,
`fast_fetch.py`, `config.py`; no index; no `--apply`; no nginx change; no restart; no
`/opt` edit; no deploy. This is a doc and a test.
