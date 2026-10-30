# Session 2026-10-30 (q2 lane) — `[Q2-MB-STOPFLAG]`: a refused MovieBox run can no longer look finished

Branch `q2-mb-stopflag`, worktree `/tmp/q2_moviebox`, rebased onto trunk `609d38e`.
Offline only: no crawl, no network, no `/opt/radd-stream`, no Gradle, no service restart.

## The defect, measured by qoder4 at 07:0x and reproduced here

```
$ python3 -S Fast_Fetch/importers/import_themoviebox.py harvest --pages 1 --limit 10
[!] [themoviebox] feed stopped: MemAvailable 2216 MB < 2500 MB
[✓] [themoviebox] harvest items=0 posts=0 duplicates=0 skipped_type=0
{"duplicates":0,"items":0,"posts":0,"queued":0,"skipped_type":0,"stopped_for_memory":false}
```

Zero requests were made, the memory floor refused the run, and the summary claimed a clean
completion with rc 0. This is the vacuous-pass class again: the caller — a timer, the campaign
ledger, the orchestrator judging coverage — could not tell a refusal from a finished crawl.

## The contract now

- Every memory-floor bail records **why**: `totals["stopped_for_memory"] = True` and
  `totals["stop_reason"]` carrying the measured numbers (`"MemAvailable 1682 MB < 2500 MB"`).
  The three sites are `_walk_feed` (reported to its caller through a `state` dict, because a
  generator cannot return a value to the run that abandoned it), `harvest_catalog`'s batch flush,
  and `crawl_pending`'s pre-start and post-flush checks. `sync_catalog` and `harvest_catalog`
  merge the walker's state into their totals.
- **rc 3** when `stopped_for_memory` is set, rc 0 otherwise — the convention q4 verified on
  fzmovies, so sites stay consistent to a script that only reads the exit code.
- `[✓]` is printed only on real completion; a refusal logs as `[!] … stopped: <reason>`.

## Evidence from this tree (offline)

Refused, against the live floor on this box — the gate runs before any request:

```
[!] [themoviebox] feed stopped: MemAvailable 1682 MB < 2500 MB
[!] [themoviebox] harvest stopped: MemAvailable 1682 MB < 2500 MB (items=0 posts=0)
{ "duplicates": 0, "items": 0, "posts": 0, "queued": 0, "skipped_type": 0,
  "stop_reason": "MemAvailable 1682 MB < 2500 MB", "stopped_for_memory": true }
rc=3
```

Clean, through the same `main()` with `_api_request` replaced by the measured fixture (one
"request", no socket):

```
[✓] [themoviebox] harvest items=1 posts=1 duplicates=0 skipped_type=0
{ "duplicates": 0, "items": 1, "posts": 1, "queued": 1, "skipped_type": 0,
  "stop_reason": null, "stopped_for_memory": false }
rc=0
```

## Tests

`test_themoviebox_import.py` gains `MemoryGateTests` (5 tests) driving the real `main()`, so the
flag, the reason, the log symbol and the exit code are asserted as one contract: refused harvest,
refused sync (the generator state channel), refused crawl (seeded pending row; the gate sits
before the pool), plus a finished harvest and a finished crawl that must still report
`stopped_for_memory: false`, `stop_reason: null` and rc 0.

Measured, one module per invocation, `nice -n 19`:
`test_themoviebox_import.py` **52 OK**, `test_themoviebox_links.py` **7 OK**,
`test_themoviebox_detail_api.py` **18 OK**, `test_database.py` **133 OK**.

## NOT run (and why)

No crawl of any size. Box was amber throughout: MemAvailable ~1.6–2.2 GiB against a 2500 MB floor,
SwapFree 2.6 GiB of 6.1, load1 2.9 — below the crawl gate's swap requirement. `import_fzmovies.py`
is not in this trunk, so the rc=3 convention is implemented from the stated rule, not copied from
q5's file. No DB schema change and no re-derivation in this commit.
