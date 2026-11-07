# Session 100 — server playback resolve: fail fast on dead copies (2026-11-07 ~23:49 PKT)

## Phase 1 — measured (live, read-only; no DB writes, no restarts)

Pushpa 2 The Rule (post 125647), detail says 1080p/720p/480p all `playable: true`,
`mode: play`, `kind: resolve`. The player still never starts. Measured stream times:

| copy | result | time |
|---|---|---|
| 1080p top `AdPyZ_tMEBGVJS89Tw` | 404 `no_playable_source` | 27.4 s |
| 720p top `AdPyZ_tMEBGdWxADFw` | 404 | 25.3 s |
| 480p top `AdPyZ_tMEBGHPW7ujA` | 404 | 35.5 s |
| 1080p backup `AdPyZ_tMEBGWD-vXZw` | 404 | 23.8 s |
| Pushpa 1 (post 141141) 720p top | 404 | 8.0 s |
| Pushpa 2 v2-top (fastdl, dead token) | 404 | 1.2 s |
| Pushpa 2 v2-2nd (vcloud, dead token) | 404 | 1.3 s |
| Pushpa 1 v2-top / v2-2nd | 404 | 1.7 s / 1.6 s |

### Why the 404 (legacy copies)

The 1080p release (legacy `releases.id` 1490518) holds 8 copies, all landing pages of
hosts with NO unwrapper in the resolver: clicknupload, 1fichier, 1cloudfile, gofile,
multiup, hidan x2, koramaup (read off the live catalog DB, read-only). `resolve_live_source`
spends the time proving a negative, serially: Stage-2 cached probe of the landing page
fails (HTML, not media) -> no unwrap branch matches -> Stage-2 general failover tries
7 same-release + 10 cross-release siblings, and **each sibling pays TWO probes of the
same URL** (its cached probe, then the fall-through stale probe of the identical
address) -> ~35 probes x ~0.7 s = 25-35 s -> honest 404 `no_playable_source`.

### Why `playable: true` is stale

`viewer.link_view` computes `playable` from `kind in ("direct", "resolve") and status
not in UNPLAYABLE_STATES` — a static ledger projection, never a probe. These rows have
`status: active` (a storage default) and `last_checked_at: NULL`: never probed, ever.
A never-probed row must NOT be demoted to unplayable on that basis alone — a fresh
pixeldrain row is playable — so the fix is fail-fast, not verdict-changing.

### Why the v2-top copies 404 fast

Cat release 1246479 (the bundle's best print for work 78991) has 5 candidates; the top
two are previously-unwrapped `video-downloads.googleusercontent.com` tokens whose
window expired. Cached probe fails fast, the fastdl embed re-unwrap fails fast,
Stage-1 failover fails fast -> 404 in ~1.2 s. Dead token, not a slow bridge.

### The app's V2 call can never succeed for v1-detail prints (found, NOT fixed)

`DetailViewModel.playV2` sends `RankedPrint.releaseId`, which is the LEGACY
`releases.id` from the v1 detail (1490518 for Pushpa 2 1080p). `/api/v2/play`
(`release_detail`) looks it up in `cat_releases`, where it does not exist
(verified: 0 rows for 1490518/1490519/1490520) -> **404 `not_found`**, "No playable
print exists for that target" (1.3 s warm, 12.3 s cold). The app then falls back to
the v1 stream route and eats the 25-35 s. A server-side mapping is NOT small: there
is no post->work foreign key; `cat_works.work_key` (`movie:pushpa 2:2024`) is derived
from title/year while the legacy post carries "Pushpa 2 The Rule", so the join would
be fuzzy title matching — a bigger design, left for a follow-up session. Even with
the mapping, Pushpa 2 would still 404 (its v2 candidates are dead too); the mapping
only matters for titles whose v2 candidates actually resolve, and no such title
has been proven yet through the live stream route.

### Transient: public POST /api/v2/play hung twice, then worked

Two public POSTs (release 1490518, work 78991) hung with no response at 70 s and
30 s; loopback POST to 127.0.0.1:8080 answered 200 in 0.026 s during the same
window, and later public retries answered 200 in 9.0 s / 1.3-2.0 s. Cause not
established (nginx `limit_req zone=radd_stream_api burst=30 nodelay` returns 503,
not a hang, so it is not the limiter). Not chased; noted for the parent.

## Phase 2 — built (smallest correct fix, `Fast_Fetch/fast_fetch.py`)

Two changes inside `resolve_live_source`, no schema change, no new hosts, no change
to Stage-1/Stage-2 backends, no app change, no API-shape change:

1. **Skip the redundant stale probe.** The fall-through re-probed the stale URL even
   when the cached probe had just failed on that exact address in the same call.
   A `_cached_probe_failed_url` local records the address the Stage-1 or Stage-2
   cached probe failed on; the fall-through returns the byte-identical refusal
   (`no_playable_source` / `stale_probe_failed` / `stale: True`) without the second
   network round trip. When the failure came from elsewhere (expiry, age, dead
   status — no probe ran), the stale probe still runs as before.
2. **Bound the sibling failover: `_FAILOVER_BUDGET_SECONDS = 10.0`.** The Stage-2
   general failover loop stops trying new siblings past 10 s from loop start and
   falls through to the honest refusal. The copy the user picked keeps its full,
   unbounded unwrap attempt (a slow bridge can take 7-42 s and still play); only
   the silent backups are budgeted. Worst case for a dead release is now roughly
   primary probes (~2 s) + 10 s failover, ~12 s instead of 25-35 s — inside the
   app's 30 s player give-up (Session 99) and nginx's 60 s stream timeout.

Deliberately NOT built: a warm unwrap cache (the fresh-unwrap result is ALREADY
persisted as `final_url` + `expires_at` + measured columns — that IS the warm cache,
and it works when an unwrap succeeds; these copies never unwrap, so there is
nothing to cache), a cross-request negative cache (needs a new column/TTL rule and
changes refusal semantics — follow-up design), the V2 legacy-id mapping (see above).

## Tests

- NEW `test_resolve_skips_second_probe_of_same_failed_address` (test_database.py):
  one dead copy, counting `_stage2_probe` mock — exactly 1 probe, reason
  `stale_probe_failed`.
- NEW `test_failover_stops_after_budget`: 6-copy release, faked `time.monotonic`
  (deadline at 1000.0, +6 s per call) — exactly 1 sibling tried, 2 probes total
  (primary + sibling), remaining 4 siblings never tried.
- `test_database.py`: 140 tests OK. `test_redact`: 76 OK. Full backend gate run
  before push (see commit message / CI run id in the parent's report).

## Deploy note (parent runs the gate deploy)

App-only file change is NONE; server change is `Fast_Fetch/fast_fetch.py` only
(+ tests + docs). Gate deploy as usual: backup set first (catalog + user-state +
live tree + admin-v2 + nginx), checkout `tracking-a-20261107` on the live tree,
restart `radd-stream.service`, live-test `GET /api/v1/stream` on a known dead copy
(expect fast 404, ~seconds not ~30 s) and on a healthy title if one is proven by
then. No DB migration, no config change, no nginx change. Expected behaviour change
after deploy: dead releases answer `no_playable_source` in ~10-12 s worst case
instead of 25-35 s; successful plays are unaffected (primary unwrap unbounded,
cached-probe pass path untouched).
