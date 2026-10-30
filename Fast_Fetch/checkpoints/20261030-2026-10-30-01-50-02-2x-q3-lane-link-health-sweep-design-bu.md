# 2026-10-30 01:50–02:2x — q3 lane, LINK-HEALTH SWEEP: design + budget arithmetic only

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-30 01:50–02:2x — q3 lane, LINK-HEALTH SWEEP: design + budget arithmetic only

**Nothing was probed and nothing heavy was read.** Load was 10.2 on one vCPU at the start of
this task, so the deliverable is `docs/LINK_HEALTH_SWEEP.md` plus
`Fast_Fetch/test_link_sweep_budget.py` (15 tests, in-memory, **0.96 s**, no sockets, no catalog
read), which is now a CI step. Zero outbound requests, zero writes under
`/home/ubuntu/radd-stream-data/`.

**Established from the code at `54662d2`, with line cites (not from intent):**
`link_health.py` `DEFAULT_TIMEOUT = 8.0` (`:125`), `DEFAULT_SAMPLE_BYTES = 524288` (`:126`),
`DEFAULT_MAX_REDIRECTS = 5` (`:127`), phase 1 `HEAD` (`:535`), phase 2 ranged `GET` only when
HEAD answered nothing useful (`:568-571`), body read bounded at `resp.read(sample_bytes)`
(`:302`), `resumable` decided from 206/`Content-Range` or `Accept-Ranges` (`:632-634`), pool
`workers = 8` (`:1015`), and the host rules that already exist (`_blocked_host_reason` `:191`,
`_block_reason` `:226`, `_is_blocklisted` `:997`, `error="blocklisted"` without touching the
network `:1043-1045`). So one link = 1 HEAD best case, ≤ 6 requests per phase, ≤ 12 requests and
≤ 512 KiB read worst case.

**The number I am most confident in:** the **full sweep is infeasible**, priced both ways and
taking the max, because the two ceilings are independent —
`0.1 × 3,705,474 × 8 s / 8 workers = 370,547 s ≈ 4.3 days` of dead-tail alone, on top of the
live term `≈ 69 h`, gives **thread-bound ≈ 7.2 days**, while politeness
(`3,705,474 × 1 s / 8 = 128.6 h ≈ 5.4 days`) binds *below* it once the tail is priced. All of
that is one vCPU doing nothing else, competing with a service that was OOM-killed at 19:14:31.
The bounded alternative, also pinned: **20 named hosts × 384 samples = 7,680 probes ≈ 0.36 h
(~22 minutes) of work**, and `1,000` proportional samples buys **±3.1 % at 95 %** for one
overall sentence — with a hard refusal for any host sampled below 30 (`per_host_claim()` returns
`None`, not a warning).

**Where the 21 `dead` and 8,543 `unknown` came from (item 7, answered by reading, not counting):**
the state vocabulary is closed and documented at `catalog_v2.py:1341`
(`unchecked|active|dead|expired|unknown`) and `unknown` is already scored as *not alive* at
`catalog_v2.py:488` (`WHEN state IN ('unknown','unchecked') THEN 0`). Its writer is the
**embed/host resolver**, not any sweep: `importers/host_resolvers.py:669` splits
`"blocked" if status in (401,403,429) else "unknown"` and `:675`, `:729`, `:739`, `:800`, `:913`
each set `status="unknown"` on a path that got an answer it could not interpret. The 21 `dead`
are measured failures via the two pure classifiers (`link_health.verdict_state():875-894` →
`catalog_v2.py:2378`; `link_state.classify():263-275`), written by `apply_evidence()` on the JIT
path. And `viewer.py:2894-2900` is why 3.46 M rows read `unchecked` rather than `active`: *"a
scraper writes 'active' into every row at ingest and only `link_state.propagate()` retires that
claim"*. I did not re-count any bucket — the question was which code can produce them.

**Adopted from the fleet's own hard-won rules:** (5) **one connection threaded through, never
two writers** — a second writer on a file a caller holds a write transaction on waits
`timeout=60` and raises `database is locked`, the exact failure the qoder4 master fixed in
`import_themoviebox.py::export_staging` at `1aafddb`; the sweep writes only to a `/tmp` staging
file and the merge is `catalog_v2.apply_evidence()` (`admin_panel.py:2542`), never in place.
(6) **progress is a stored number**, never a scan — `COUNT(*) FROM posts` 0.91 s vs the same
read `WHERE is_18_plus=1` at 26.46 s (qoder4, 2026-10-30, cited because re-running it at load 10
breaks the rule), hence `link_sweep_run`'s single-row counters. (4) resumability uses
`link_state.iter_pending()`'s existing contract (`:445-459`): advance the cursor to
`page_end_id`, the highest id *seen*, not the last one probed — otherwise a `magnet:` row wedges
the run forever.

**Limits stated, not smoothed.** No probe can tell you the bytes are the film, that they stay
playable, or that playback works on a phone (`App/docs/PLAYER_SPEC.md` still correctly says
nothing in that player has run on Android); `active` may only ever mean "answered, with these
protocol properties, at `last_evidence_at`" and must never be rendered as "playable".
And the one code change this design needs before it can run at all is **a per-host serialiser in
front of `probe_many()`** — today nothing stops two workers touching one host in the same second.
*(Superseded by the next q3 entry in this file: `link_health.host_gate()` now exists, is wired
into `_chain()`, and is proven offline. Read that line as the state at `54662d2`, not as today.)*

**Push.** Docs + one offline test module + the CI step. `backend-ci.yml` filters on
`Fast_Fetch/**`, and this push *does* touch `Fast_Fetch/` (the new test and `CONTINUITY.md`), so
a backend run is expected here — unlike the earlier docs-only pushes, which legitimately produced
zero. Heredoc askpass from `ORACLE_DEPLOYMENT.md` (verified 2 `%s` lines), both refs, one attempt,
no force, no tags, `/opt/radd-stream` untouched, no service action.

---

