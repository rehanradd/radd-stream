# HITPATH_CONNECTIONS.md — database connections per cache-hit download request

**Order:** CROWN qoder14, 2026-11-05 (read-only; no new module; check trunk first).
**Author:** qoder14 (host classifier lane).
**Code baseline:** lane `feat/phase1-resolved-cache` at `fd86e76`
(`e9b78ba` for the route harness). Trunk checked at `/tmp/crown_trunk`
(`b99814e`): **no upstream doc or test counts connections on the v1 download
hit path** — the only upstream precedents are the v2/accounts *contract*
(`api_v2.py:249` "One connection per request, committed on success", tested by
`test_accounts_api.py:331` "one read-only catalog connection per request").
This v1 path does not live under that contract; today it opens **three**.

**Scope:** one PUBLIC-port (`full=False`), free-tier (`redirect=1`, no VIP
credential) `/api/v1/download` request that **hits** the resolved cache and is
served as `kind='file'` — viewer.py:3295-3416. Nothing was executed against
production; every number below is a static file:line trace verified against the
route harness, plus qoder11's measured profile timings as evidence.

## The answer: 3 distinct `sqlite3.connect()` calls, warm

| # | Opened by | File:line | What it does on the hit path | Cost evidence |
|---|---|---|---|---|
| 1 | `redact.link_is_adult(int(source_id), DB_PATH)` — adult gate, runs BEFORE any cache work (viewer.py:3303) | `redact.py:1086` — bare `sqlite3.connect(db_path)` (NOT a `mode=ro` URI), one `download_sources JOIN releases JOIN posts` SELECT, closed by the `with` | 1 connection per request, read-write mode for a pure read | qoder11 profile `dbb49ab`: `link_is_adult` stage **p50 8.57 ms** of a **19.4 ms** `do_GET` total (≈44%), measured n=8 at load 6.25, harness `/tmp/q11_hitpath_profile.py`, explicitly labelled NOT-A-GATE |
| 2 | Cache lookup — `with get_db() as conn: resolved_cache.lookup_cache(conn, …, want="download")` (viewer.py:3325-3327) | `viewer.py:140` — `sqlite3.connect(DB_PATH)`; `get_db()` opens fresh on EVERY call (no pooling); `lookup_cache` itself uses only the passed conn (`resolved_cache.py:414-456`) | 1 connection (SELECT + row→dict); fragment strip and `_viewer_shaped` re-check are pure functions on the passed conn | qoder11 `lookup` stage p50 3.6 ms (its note: "the get_db OPEN sits in remainder, honestly attributed") |
| 3 | Free-tier shortener tail — `with get_db() as conn: shorten_download_url(target, conn)` (viewer.py:3398-3400), inside the 302 success branch | `viewer.py:140` again; `admin_panel.shortener_targets(conn)` (admin_panel.py:1313) reads the settings on the PASSED conn — it adds no connect of its own | 1 connection **even when no shortener is configured** (the route opens the conn before learning targets is empty; `shorten_download_url` returns None and the 302 proceeds direct) | inside qoder11's `remainder` stage p50 5.0 ms |

**Total, warm cache-hit download request = 3 connections**, each opened and
closed inside the single request (the service holds no idle DB fds — qoder11
measured `/proc/<pid>/fd` zero `.db` files, checkpoint
`20261101-01xx` line 165).

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
- Hit-path response flush (`send_response(302)`, headers, `end_headers`) and
  `cors_headers_for`: 0.

## Variant counts (for the refactor conversation, measured the same way)

| Path | Connects | Why it differs |
|---|---|---|
| Public HIT, free, redirect (this audit) | **3** | table above |
| Public MISS → live resolver | 3 + whatever `fast_fetch.resolve_live_source` opens (its own `get_db` family) + 1 writeback `with get_db()` at `viewer.py:3364` (or the `note_failure_from_probe` one at `:3377` on failure) | out of scope here; the writeback is a 4th-5th viewer.py connect |
| Cached `kind='playlist'` row, `want=download` | same as MISS | `lookup_cache` SQL refuses it (`resolved_cache.py:436-437`) and the route's `hit.get("kind") == "file"` veto (`viewer.py:3330`) keeps `res=None` — TWO independent gates, both proven by `test_host_classifier.py::test_download_gate_refuses_viewer_shaped_rows` |
| VIP download (signed pass, no bearer) | **2** | shortener tail skipped entirely at `viewer.py:3392` |
| Operator port (`full=True`) | 0 on the cache block + resolver's own | adult gate `:3303`, cache `:3321`, shortener `:3392` are all `not full`; the operator keeps live-resolver diagnostics by design |

## The pin

`Fast_Fetch/test_host_classifier.py::TestViewerShapeGate::test_hit_path_connection_count_is_pinned`
boots the real `ThreadedHTTPServer`/`DashboardHandler` on an ephemeral port,
wraps the **stdlib `sqlite3.connect` attribute itself** (one module object, so
`viewer`, `redact`, and `admin_panel` callers are all observed — a new opener
anywhere in the hit path fails the pin, not just a viewer.py grep), drives one
warm-hit request, and asserts **exactly 3** connects, all targeting the
fixture DB. The resolver stub raises if reached, so the pin only counts the
true hit path. Mutation-verified by construction: the assert requires three
*observed* connects, so a non-functional wrapper fails the test too.
Measured at load 4.58: `Ran 72 tests, OK` (zero skips).

**Update ritual:** changing `3` means changing this document in the SAME
commit, with the crown's sign-off — the whole point of the pin is that a
silent fourth connect per request is a regression, not a refactor detail.

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
