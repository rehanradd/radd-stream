# 2026-11-12 — app-fix builder [APPFIX-DETAIL-SALAAR]: Appetize FAILED 2 + FAILED 1

Branch `muse/appfix-detail-salaar-20261112`, from main `199e8bc2`. Fixes the two
Appetize v1.1.2 device-test failures (Pixel 6/7, Android 13). No live-tree or
live-DB touch, no service restart, no tag, no release — the coordinator owns
v1.1.3. Full diagnosis: `~/workspace/goals/radd-stream-on-oracle-vm/hidden_files/appfix-detail-salaar-20261112.md`.

## Root causes (measured from the Oracle VM, not guessed)

**FAILED 2 — first detail load fails, Retry always works.** The v2 detail chain
for Salaar (v2 work id 74537, v1 post 79881) costs 6.5–10 s of server time:
`GET /api/v2/works/74537` 1.37 s (of which `catalog_rev`'s `MAX(source_rev)`
is a 0.25–0.37 s full scan of 197,530 `cat_works` rows on EVERY v2 GET), the
work-ref bridge `GET /api/v1/posts?work_ref=…` 4.7–6.4 s, the detail itself
0.23–0.45 s. The bridge cost is `_resolve_work_ref`'s family lookup: a
full-table scan applying the Python `radd_norm_title` UDF to every row
(4.804 s measured in-process on the live DB). The observed error is
`friendlyNetworkError`'s fallback branch, which rules out a read/connect
timeout, 429/404/5xx, DNS, connect failure and cleartext — the failure class
is transient (deadline/reset under load), which is why Retry always works.
Note the id-space trap found en route: v1 works ids ≠ v2 `cat_works` ids
(`/api/v1/works/4220` is Salaar; `/api/v2/works/4220` is Squid Game).

**FAILED 1 — Salaar did not play on its default version.** The API can play
Salaar: post 79881's 720p auto, 480p and sd handles all pressed 302 (plain
GET, no follow) from the Oracle VM, corroborating the 05:59 PKT audit. The
mechanism: detail opens start a daemon warm of the auto tier (~9.25 s for
Salaar 720p). A Play press before it banks finds a cache MISS and starts a
SECOND full resolve; the 8 s player watchdog fires before either finishes;
the retry starts a THIRD resolve and the failover hop a FOURTH — ~30 s of
parallel cold resolves, all abandoned, ending in `NO_CANDIDATE_LEFT`.
There was no in-flight resolve coalescing anywhere, and failover hops
FORWARD to cold links while earlier links warm behind it, never going back.
`playV2` is DB-only (no resolve), so the client-side 2 s `playV2` ceiling
could not help either.

## The fix

**Server — S1, two indexes** (`fast_fetch.init_db` + `catalog_v2.py` DDL, so
rebuilds mint them too):
- `idx_posts_year ON posts(year)` — the family lookup seeks the year's rows
  before the UDF runs (~5 s → ~0.1 s when the year is known; no-year keys
  still scan, documented residual). A title-expression index was measured
  and rejected (it makes the grouped page query 3–4× slower).
- `idx_cat_works_source_rev ON cat_works(source_rev)` — `catalog_rev`
  becomes an index seek (~0 ms). Guarded on table AND column: a hand-made
  stub `cat_works` without `source_rev` (a test fixture carries one) must
  skip the index, never break `init_db` — that exact bug was caught by the
  suite run and fixed before commit.
- Gate-deploy flag: one-time index builds on the first request after
  restart (197k–340k rows; seconds, not minutes — exact cost unmeasured);
  the first request may be slow.

**Server — S2, resolve coalescing** (`viewer.py:_resolve_coalesced`,
`_RESOLVE_WAIT_SECONDS = 12.0`, keyed by `(source_id, v2, want)`): the
leader runs `resolve_live_source`; a waiter joins the in-flight resolve
and uses the leader's answer (fresh copy per caller). A waiter that times
out, or whose leader failed, falls back to its own resolve — the old
behaviour — so a stuck leader can never wedge a request. Used by the
stream handler, the download handler, and the daemon warm
(`_resolve_and_bank`). The v2 metadata resolve (`resolve_target`) is
deliberately NOT coalesced. This is the root-cause fix for FAILED 1: a
Play press during the warm now waits for the banking resolve and 302s at
~9.25 s, inside the retry watchdog window (deadline 16.8 s).

**App — A1, `loadDetail` auto-retry** (`DetailViewModel.kt`,
`fetchDetailWithRetry`; pure policy in `DetailPreResolve.kt`): up to 3
attempts, backoff 600 ms → 1.5 s; retries only `IOException` (incl.
timeouts) and `HttpException` 429/5xx — never parse/mapping errors or
400/403/404. A null detail retries once, because the v2 path swallows
HTTP/IO failures into null inside the repository. `CancellationException`
is rethrown (it was swallowed by the generic catch).

**App — A2, `playV2` ceilings** (`DetailPreResolve.kt` constants):
`preresolveTopLink` 2 s → 10 s (background, silent), `playPrint`'s
`playV2` 2 s → 6 s. The 2 s ceiling timed out healthy calls under load
(the server alone pays 0.25–0.37 s CPU per request); the fallback was a
cold single link, strictly worse than the ranked bundle with runner-ups.
Neither call resolves a link, so the longer ceiling cannot stall
playback. Watchdog 8 s UNCHANGED.

**App — A3, scope-warm dedup wart** (`warmScopeLink`): `lastScopeWarmHandle`
is set only when the warm SUCCEEDS — a failed warm used to poison the
dedup so reopening the card never retried the link.

## Tests (all green locally, this VM, `nice -n 19`)

- `test_work_ref.py` 6 — family lookup plan uses `idx_posts_year`.
- `test_database.py` 227 (1 skipped) — `init_db` mints both indexes;
  stub-table-without-column branch pinned.
- `test_api_v2.py` 74 — `catalog_rev` plan seeks
  `idx_cat_works_source_rev`.
- `test_edge_phase1.py` 19 — coalescing: two concurrent resolves run the
  upstream once; different contracts do not share; leader failure falls
  back; timed-out waiter resolves on its own; no leaked in-flight entries.
- `test_catalog_v2.py` 105, `test_ci_manifest.py` 10,
  `test_download_endpoint.py` 26, `test_redact.py` 96.
- App: 5 new tests in `PreResolveTest` (transient vs deterministic errors,
  backoff values, attempt/null budgets, ceiling values). No local Gradle by
  owner order — Android CI is the verification path.

Pre-push checks: full import diff per edited Kotlin file (see
`~/workspace/import-diff.py` — run after commit); duplicate top-level type
scan over the whole App tree: 581 declarations, 0 duplicates.

## Not done / still needs a device

- Push + Android CI + Backend CI verdicts (coordinator watches).
- Device proof (Appetize minutes exhausted): first-load detail on 3 titles
  incl. Salaar + McLintock (no Retry tap); Salaar default-version Play
  pressed within seconds of detail load; cold-tap timing; 402 locked-1080p
  behaviour. CI green proves the code compiles and the unit tests pass,
  not that a video plays.
- Residuals: no-year family keys still full-scan; first request after the
  gate deploy may be slow (index builds); `resolve_target` not coalesced
  by design; the exact first-failure exception on the device was never
  captured (no logcat) — the fix covers the whole transient class.
