# HITPATH_CONNECTIONS.md — database connections per cache-hit download request

**Order:** CROWN qoder14, 2026-11-05 (read-only; no new module; check trunk first).
**Author:** qoder14 (host classifier lane).
**Code baseline:** lane `feat/phase1-resolved-cache` at `fd86e76`
(`e9b78ba` for the route harness). Trunk checked at `/tmp/crown_trunk`
(`b99814e`): **no upstream doc or test counts connections on the v1 download
hit path** — the only upstream precedents are the v2/accounts *contract*
(`api_v2.py:249` "One connection per request, committed on success", tested by
`test_accounts_api.py:331` "one read-only catalog connection per request").
This v1 path does not live under that contract; today it opens **3 catalog
connects plus 1–2 user-state (analytics) connects** — see the rebase note
below the table.

**Rebase note (2026-11-11, onto main `14d9063`):** the branch's count of 3
predates two main-side changes: the quality gate (`quality_gate_block_reason`,
main's security release — one more catalog `get_db` on every public
download) and the playback-analytics tail (`_count_playback` — one or two
user-state connects per request). The shortener tail the branch counted
opens nothing on this path any more (it runs only for `?via=web` since the
2026-11-06 owner decision). The pin test was re-scoped in the same commit
to pin the catalog 3 exactly and the analytics 1–2 as a range; the doc and
the test change together, per the pin's own update ritual.

**Scope:** one PUBLIC-port (`full=False`), free-tier (`redirect=1`, no VIP
credential, no `?via=web`) `/api/v1/download` request that **hits** the resolved cache and is
served as `kind='file'` — viewer.py:4602-4760. Nothing was executed against
production; every number below is a static file:line trace verified against the
route harness, plus qoder11's measured profile timings as evidence.

## The answer: 3 catalog `sqlite3.connect()` calls + 1–2 analytics ones, warm

| # | Opened by | File:line | What it does on the hit path | Cost evidence |
|---|---|---|---|---|
| 1 | `redact.link_is_adult(int(source_id), DB_PATH)` — adult gate, runs BEFORE any cache work (viewer.py:4602) | `redact.py:1373` — bare `sqlite3.connect(db_path)` (NOT a `mode=ro` URI), one `download_sources JOIN releases JOIN posts` SELECT, closed by the `with` | 1 connection per request, read-write mode for a pure read | qoder11 profile `dbb49ab`: `link_is_adult` stage **p50 8.57 ms** of a **19.4 ms** `do_GET` total (≈44%), measured n=8 at load 6.25, harness `/tmp/q11_hitpath_profile.py`, explicitly labelled NOT-A-GATE |
| 2 | Quality gate — `quality_gate_block_reason(int(source_id), …)` (viewer.py:4610) | `viewer.py:533` — `with get_db() as conn:` → `viewer.py:170` `sqlite3.connect(DB_PATH)`; reads `app_remote_config.feature_quality_gate` + the release's band columns | 1 connection per public request (fail-open: an unreadable ledger means free tier); main's security release, postdates the branch's count | new since the branch audit; no qoder11 timing (the gate reads one config row + one release row) |
| 3 | Cache lookup — `with get_db() as conn: resolved_cache.lookup_cache(conn, …, want="download")` (viewer.py:4636) | `viewer.py:170` — `sqlite3.connect(DB_PATH)`; `get_db()` opens fresh on EVERY call (no pooling); `lookup_cache` itself uses only the passed conn | 1 connection (SELECT + row→dict); fragment strip and `_viewer_shaped` re-check are pure functions on the passed conn | qoder11 `lookup` stage p50 3.6 ms (its note: "the get_db OPEN sits in remainder, honestly attributed") |
| 4 | Playback analytics, schema check — `accounts_api.state_db()` inside `_count_playback` (viewer.py:4119 → 3982) | `accounts_api.py:370` — `accounts.connect(path)` → `accounts.py:519` `sqlite3.connect(user_state.db)`; runs ONLY when the process-global `_SCHEMA_READY` is False (once per process) | 0–1 connections per request: 1 on a cold process, 0 once any earlier request warmed the flag — this is why the total varies 4↔5 across runs | analytics, not catalog; the write is one UPSERT, swallowed on failure |
| 5 | Playback analytics, event write — `usage_stats.record_event(…, metric="playback_start", …)` inside `_count_playback` (viewer.py:3981) | `usage_stats.py:474` — `_borrow(db)` → `accounts.connect(handle)` → `accounts.py:519` `sqlite3.connect(user_state.db)`; opens fresh on EVERY call | 1 connection per request, always | analytics, not catalog; `usage_stats` swallows every failure — analytics never gets to be the reason playback was slow |

**Total, warm cache-hit download request = 3 catalog + 1–2 analytics
connects (4 or 5 overall)**, each opened and closed inside the single
request (the service holds no idle DB fds — qoder11 measured
`/proc/<pid>/fd` zero `.db` files, checkpoint `20261101-01xx` line 165).
The pin test asserts the catalog 3 exactly and the analytics 1–2 as a
range, and that no connect targets any third database.

## What does NOT connect on this path (each verified at the line)

- `_public_gate` / rate limiter: `redact.limiter.check` is an **in-memory**
  token bucket (`redact.py:1104-1127` comment: "a restart is a reset"). 0.
- `redact.parse_token` / `mint_token` / `parse_vip_pass`: HMAC only. 0.
- `signing_secret()` → `redact.stream_secret` (`redact.py:953` connect) is
  process-cached in `viewer._SIGNING_SECRET` (`viewer.py:80-87`): **1 cold
  connect on the first request per process**, zero after.
- `_ensure_schema()` (which would call `fast_fetch.init_db` +
  `redact.site_needles`, `redact.py:1194` ro connect) is invoked only on the
  accounts/v2/`/api/data` branches (`viewer.py:3024`, `:3037`, others) — the
  `/api/v1/download` branch never calls it. 0.
- `request_is_vip` (`viewer.py:389-411`): no bearer + no `vip` param ⇒ no DB
  at all; the `accounts.vip_status` connect fires ONLY for a bearer-token VIP
  request (different path, +1 to a *different* DB — the accounts state DB).
- Free-tier shortener tail (`shorten_download_url`, viewer.py:4736): 0 on
  THIS path — it runs only for `?via=web` (owner decision 2026-11-06: the
  shortener earns only on web-page downloads; the app's native downloads
  never carry the marker). With `?via=web` it opens one more catalog
  `get_db`, inside the 302 success branch.
- Hit-path response flush (`send_response(302)`, headers, `end_headers`) and
  `cors_headers_for`: 0.

## Variant counts (for the refactor conversation, measured the same way)

| Path | Connects | Why it differs |
|---|---|---|
| Public HIT, free, redirect (this audit) | **3 catalog + 1–2 analytics** | table above |
| Public HIT, free, redirect, `?via=web` | 3 catalog + 1–2 analytics + 1 shortener | the shortener tail opens its `get_db` only for web downloads |
| Public MISS → live resolver | 3 catalog + 1–2 analytics + whatever `fast_fetch.resolve_live_source` opens (its own `get_db` family) + 1 writeback `with get_db()` (or the `note_failure_from_probe` one on failure) | out of scope here; the writeback is a further viewer.py connect |
| Cached `kind='playlist'` row, `want=download` | same as MISS | `lookup_cache` SQL refuses it and the route's `hit.get("kind") == "file"` veto keeps `res=None` — TWO independent gates, both proven by `test_host_classifier.py::test_download_gate_refuses_viewer_shaped_rows` |
| VIP download (signed pass, no bearer) | **3 catalog + 1–2 analytics** | shortener tail skipped entirely (and was already `via_web`-only); the quality gate still reads (it returns free for VIP) |
| Operator port (`full=True`) | 0 on the cache block + resolver's own | adult gate, quality gate, cache are all `not full`; the operator keeps live-resolver diagnostics by design |

## The pin

`Fast_Fetch/test_host_classifier.py::TestViewerShapeGate::test_hit_path_connection_count_is_pinned`
boots the real `ThreadedHTTPServer`/`DashboardHandler` on an ephemeral port,
wraps the **stdlib `sqlite3.connect` attribute itself** (one module object, so
`viewer`, `redact`, and `admin_panel` callers are all observed — a new opener
anywhere in the hit path fails the pin, not just a viewer.py grep), drives one
warm-hit request, and asserts **exactly 3** connects targeting the fixture
DB (adult gate, quality gate, cache lookup) plus **1–2** targeting the
user-state DB (playback analytics), and nothing anywhere else. The resolver stub raises if reached, so the pin only counts the
true hit path. Mutation-verified by construction: the assert requires three
*observed* connects, so a non-functional wrapper fails the test too.
Measured at load 4.58: `Ran 72 tests, OK` (zero skips).

**Update ritual:** changing `3` (or the `1–2` analytics range) means changing
this document in the SAME commit, with the crown's sign-off — the whole
point of the pin is that a silent extra connect per request is a regression,
not a refactor detail. (Rebased 2026-11-11 onto main `14d9063`: the catalog
3 gained the quality gate and lost the shortener tail; the analytics 1–2
is new. See the rebase note at the top.)

## The wiring diff I would want (viewer.py is HELD — proposed, NOT applied)

Collapse the hit path from 3 connects to 1, per the v2 contract already
precedented upstream (`api_v2.py:249`):

1. `viewer.py` `/api/v1/download` branch: open ONE `with get_db() as req` at
   the top of the branch; pass `req` to the adult gate, `lookup_cache`, and
   `shorten_download_url`. The hit path is pure reads plus the shortener's
   idempotent `CREATE TABLE IF NOT EXISTS`/`INSERT OR REPLACE` — safe under
   `get_db`'s commit-at-exit.
2. `redact.link_is_adult`: accept an optional `conn=None`; with a conn it skips
   its own connect; without one (every existing caller keeps working) it
   should switch from the bare `sqlite3.connect(db_path)` at `redact.py:1086`
   to `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)` — a read-only
   open for a read-only walk, matching what `site_needles` already does at
   `redact.py:1194`.
3. Expected effect on the profile: −2 connect/close pairs per hit; the adult
   stage's 8.57 ms p50 is the first thing to re-measure (part of it is the
   open itself), with qoder11's harness (`/tmp/q11_hitpath_profile.py`).

Not applied: viewer.py per the crown's HELD ruling, redact.py not assigned to
me tonight. Handing the sketch above to the crown is the deliverable; the pin
test keeps the count honest either way.

*Provenance: every line number was read from the lane working tree at
`fd86e76` on 2026-11-05; timings are quoted from qoder11's commit `dbb49ab`
(n=8, NOT-A-GATE, load 6.25) and were NOT re-measured here — static trace +
the connect-count pin only.*
