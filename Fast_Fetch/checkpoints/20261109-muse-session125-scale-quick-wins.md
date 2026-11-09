# Session 125 — scale quick wins (A1/A2/A6)

2026-11-09 ~14:40–15:02 PKT, reconcile builder (parent-spawned). Finishes the
first builder's A2 work after a collision: at 14:34 PKT a self-check worker
started building the SAME pragmas in the SAME clone with a conflicting
approach (inline `cache_size -131072` on 3 connections) while the
parent-spawned builder was mid-build. The builder stopped editing at 14:38
PKT; the sibling then REVERTED all of its own edits. Reconcile ran on the
quiet tree: only `fast_fetch.get_db` + untracked `db_pragmas.py` survived.

## Decided (parent, 14:39 PKT) — winning approach, kept

- Centralized helper `Fast_Fetch/db_pragmas.py` (`apply_serve_pragmas` +
  `read_pragmas`, stdlib-only, imports only `sqlite3` — no import cycle
  possible), `cache_size -65536` (64 MiB), ALL serve-path connections. The
  sibling's inline `-131072` is superseded: it doubled worst-case memory
  and missed the bare viewer/api_v2 connections. Its test classes never
  landed either (tree was clean), so the pragma pins were written fresh in
  the new module below, not converted.

## The math (why -65536, not the build note's -131072)

- The server is `ThreadingMixIn`: one thread per TCP connection, unbounded
  by design, so the per-connection cap is the only bound that exists.
- Practical concurrency is the nginx edge: `limit_conn 32` per IP and the
  10 r/s browse bucket, requests ~0.15 s — even 32 IPs hammering at once is
  ~64 in-flight connections. 64 x 64 MiB = **4 GiB worst-case cap**, and
  the cap is not a preallocation (SQLite only allocates pages it touches),
  so the usual tens of connections hold well under 1 GiB.
- The note's -131072 would double the worst case to **8 GiB on a 12 GiB
  box**, too close to the MemAvailable < 1500 MB guardrail. `mmap_size`
  268435456 is address space, not RAM; `temp_store = MEMORY`;
  `busy_timeout` 30000 on catalog connections (the live value, kept);
  WAL + `synchronous = NORMAL` + `wal_autocheckpoint = 1000`, unchanged.

## Wiring (all serve paths now call the helper)

- `fast_fetch.get_db` (first builder, kept) — comment fixed: HEAD never
  set `-131072` inline; that was the sibling's uncommitted edit.
- `viewer.get_db`, `api_v2.session`, `admin_panel._session` — fresh calls;
  all three used to run on sqlite's 5 s default busy_timeout, now 30000
  like `fast_fetch.get_db`.
- `accounts._prepare` / `engagement._prepare` (both `connect`) — helper
  with `busy_timeout_ms` passed through; user-state keeps its 5000 ms.
- `accounts._open_catalog_read_only` — catalog connection, so the 30000 ms
  catalog value (its old value was 5000 via `DEFAULT_BUSY_TIMEOUT_MS`;
  changed deliberately so every catalog connection waits the same).
- `panel_feed._open_panel` — helper with `busy_timeout_ms=5000`: the panel
  DB is neither catalog nor user-state and no rule in this batch re-times
  it, so its live value (sqlite's 5000 ms default) is kept.
- `redact` has NO `_connect` function (the brief's inventory was wrong):
  six inline connect sites wired instead — `_read_legacy_db_secret`,
  `art_url_for`, `art_is_adult`, `link_is_adult`, `site_needles`,
  `site_text_needles` (each inside its existing fail-quiet try).
- Deliberately NOT touched: `catalog_v2.project_db`,
  `fast_fetch.reconcile_key_adult` (its one inline connect at the key
  scan), `import_*` staging writers, backfill/audit helpers — not request
  paths. `fast_fetch.get_db` is the only `fast_fetch.py` serve connect.

## Search limits (`viewer.py`)

- `api_v1_get_posts` clamps `limit` to 1–100 in-function (the HTTP layer
  already did; direct callers could ask for an unbounded page).
- By-media needs NO change: `media_search.search_by_media` already
  clamps `min(50, max(1, int(limit or 10)))` (line 350) — pinned by test.
- Deadline: progress handler, **10 s** (live nginx posts read timeout is
  15 s; 10 < 15 must hold), 503 `search_timeout` in the `/api/v1/posts`
  branch. Found while testing: a raise inside the progress handler is
  SWALLOWED by this Python's sqlite3 module and surfaces as
  `OperationalError("interrupted")` — so the handler returns 1 and the
  branch maps exactly `"interrupted"` to 503 (any other
  `OperationalError` re-raises). Also found: `SELECT COUNT(*)` without a
  WHERE clause executes ~0 handler invocations (fast path); the deadline
  only bites on row-visiting queries, which is what slow searches are.

## Nginx (artifact, NOT applied here — parent applies at gate-deploy)

- `~/workspace/nginx125-changes.py` (first builder, DONE and verified):
  four cached locations gain `http_504` + `background_update`;
  `= /api/v2/suggest` gains the 60 s cache (GET-only, public,
  `max-age=60`, adult excluded for public callers);
  `/api/v1/art` gains a 302 cache at **600 s, not 86400 s** — a post
  flagged 18+ after its art 302 is cached must stop serving its poster
  within 10 minutes, not a day; 404s cache 60 s.
- Zone `max_size` **500m, NOT the note's 2g**: disk is 2.6G free (99%),
  a 2g cap would leave ~0.6G for DB/WAL growth; 500m leaves >=2.1G.
  `worker_connections` 768 → 4096, `worker_rlimit_nofile` 8192,
  upstream `radd_backend` keepalive 32, `proxy_http_version 1.1`,
  keepalive 65/1000. NEVER cached, unchanged: Play 302s, download,
  `/api/v2/play`, account/coins/check-ins, anything authed.

## Tests (`Fast_Fetch/test_scale_pragmas.py`, NEW, 20 tests)

- Helper values read back on a file DB (all 8 pragmas); `read_pragmas`
  None-safe on `:memory:` (`mmap_size` is None there — assertions on it
  use file DBs only); constants pinned (-65536, 268435456, 30000).
- Every wired call site returns the helper values (catalog 30000;
  user-state + panel-feed 5000; read-only handles keep `journal_mode`
  "delete"); the six redact sites call the helper (recorded) and keep
  their answers.
- Search: clamp 500 → 100, 0/-3 → 1, 7 → 7; by-media 500 → 50 results;
  past deadline aborts the query; normal deadline answers 300 rows;
  HTTP proof: normal GET 200, past-deadline GET **503 `search_timeout`**.
- Registered in `backend-ci.yml` (65 🧪 steps now); NOT in UNREGISTERED
  (it was never listed there — nothing to remove).
- `python3 -S Fast_Fetch/test_scale_pragmas.py`: **20/20 OK**.
- `python3 -S Fast_Fetch/test_docs_invariants.py`: **22/22 OK**.

## Verification

- Every touched module imports clean (`viewer`, `api_v2`, `admin_panel`,
  `panel_feed`, `accounts`, `engagement`, `redact`, `db_pragmas`,
  `fast_fetch` — all OK under `python3 -S`).
- Full backend gate (local, `run-backend-gate.py`, `nice -n 19`, log
  `~/workspace/gate125.log`): **61/61 PASS, FAILED MODULES: 0** —
  scale_pragmas 20, redact 82, database 216, api_v2 71,
  docs_invariants 22. The 4 importer solos the runner does not cover
  also pass standalone: dub_collision_census 13, themoviebox_detail_api
  18, themoviebox_import 53, themoviebox_links 7. No load flake this
  run (test_redact green first try at load < 1).
- NOT done (parent): push + CI + merge to main + gate-deploy (incl.
  running the nginx artifact on the VM + `nginx -t` + reload + X-Cache
  HIT probes) + device verification. Out of scope by brief: A4
  Cloudflare/DNS, A5 per-device rate buckets, FTS5/B1, any App code.
