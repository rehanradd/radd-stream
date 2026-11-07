# Session 101 — Resolver Phase A (audit §3.4 items 1, 2, 5, 6, 3)

Date: 2026-11-08. Branch: tracking-a-20261107. Parent commit: f1fe4624 (Session 100).
Backend only — no app code, no panel code, no live-tree change.

## What the audit asked for

The 01:26 PKT 2026-11-08 scraper+resolver audit (§3.4) ordered five small
resolver fixes before any new scraper work: a cross-request negative cache,
per-host timeouts, failover order by the direct-first ranking, a budget on the
Stage-1 sibling failover, and parallel probing. All five are built here.

## 1. Negative cache (biggest)

Two new columns on `download_sources`:

- `last_failed_at REAL DEFAULT NULL` — epoch seconds of the last failed resolve.
- `failure_class TEXT DEFAULT NULL` — one of `probe_failed`,
  `no_unwrapper`, `unwrap_failed`.

Both are in the CREATE TABLE DDL and in the `PRAGMA table_info` migration
block beside `expires_at`/`ttl_source`, so a fresh DB gets them and an old DB
gains them on first open. `NEGATIVE_CACHE_TTL_SECONDS = 12 * 3600` (12 h, the
midpoint of the audit's 6–24 h range, a named constant so it is one edit to
tune).

`resolve_live_source` checks the cache at the top, after the row load and the
adult gate: a fresh record returns `no_playable_source` with
`reason: "negative_cache"` plus the stored `failure_class`, `stale: False`,
and no probe at all. An expired record is cleared (`_clear_resolve_failure`)
and the resolve proceeds normally.

Recording points (`_record_resolve_failure`, best-effort UPDATE, validates
the class):

- cached-probe fail, Stage-1 and Stage-2 → `probe_failed`;
- one point after the unwrap dispatch + bridge guard + fresh gate probe,
  when `fresh_url` is None → `unwrap_failed` if a branch ran
  (`_unwrap_branch_taken`, set as the first line of each of the 13 elif
  branches) or Stage-1 was tried, else `no_unwrapper`. A later, more
  specific verdict overwrites an earlier one — e.g. a cached-probe fail
  followed by "no branch matched" ends as `no_unwrapper`.

Success clears the record inline in the UPDATEs (Stage-1 cached pass,
Stage-2 cached pass, fresh persist, Stage-1 failover winner row); the
stale-success path clears via the helper only after the stale probe passes —
a row with no URLs returns a pre-existing "success" with `url: None`, and
clearing there would erase a legitimate record. The primary keeps its
failure record when a failover sibling wins (the sibling's own success
clears the sibling's row). A fresh scrape writes new rows (releases are
replaced per page), so old records die with old rows — the cache cannot
block freshly scraped copies.

Live copies are untouched: only failures are cached, and expiry clears the
record. A copy that starts working again (host back, link fixed) serves on
the first attempt after its record expires, and a passing probe clears the
record immediately.

## 2. Per-host timeouts

Named constants beside `_FAILOVER_BUDGET_SECONDS`:

- `RESOLVE_LANDING_TIMEOUT_SECONDS = 5`
- `RESOLVE_LANDING_MAX_RETRIES = 0`
- `RESOLVE_UNWRAP_MAX_RETRIES = 1`

Capped inline in the unwrap functions (importers store the landing page on
unwrap failure, so nothing is lost at ingest — resolution just defers to
play time):

- `unwrap_fastdl`: 1 call, 5 s / 0 retries (was 15 s × 3 = 45 s).
- `unwrap_vcloud`: 2 calls (landing + token URL), both 5 s / 0 retries.
- `unwrap_hubcloud_drive`: 10 s / 12 s, max_retries 1 (was 3).
- `unwrap_gdflix`: 10 s, max_retries 1 (was 3).
- `unwrap_greenmotors`: 2 calls, 10 s default, max_retries 1 (was 3).

Left alone: `unwrap_hubcloud` (already 5 s / 1 retry — the precedent),
`unwrap_direct_cloud` / `unwrap_hubcdn` (single-attempt opener-based
fetches), `unwrap_pixeldrain` / `unwrap_vegadrive` (pure rewrites, no
fetch). `probe_media` / `default_fetch` (15 s, no retry) deliberately NOT
touched — the audit's 45 s figure is `http_get`-only.

## 3. Failover order

`tiers.py` gained `candidate_order_sql(alias="")` — the old
`CANDIDATE_ORDER_SQL` is now `candidate_order_sql()` (verified byte-identical
to the HEAD version; the first attempt failed because `.format()` binds only
to the last string literal, so `{p}` in the first part was never
substituted — rewritten with f-strings). Note: grep showed
`CANDIDATE_ORDER_SQL` was defined but used by NO code (only a comment in
`link_state.py`) — the audit's "direct-first ranking already exists" was
only half true. It is now applied to all three sibling queries in
`resolve_live_source` (Stage-1 siblings, Stage-2 same-release, Stage-2
cross-release with alias `"s"` — required because `releases` also has
`created_at` and `id`, so unqualified names are ambiguous).

## 4. Stage-1 budget

`current_hosts.resolve_release(rows, fetch, probe, deadline=None)` — new
optional `deadline` (absolute `time.monotonic`); the lazy scheduler checks
it before starting each new sibling. The caller passes
`deadline = time.monotonic() + _FAILOVER_BUDGET_SECONDS` (the same 10 s
Session 100 added for Stage-2). `resolve_release` has no callers outside
fast_fetch's Stage-1 failover (via alias `_ch_release`), so the optional
parameter is safe.

## 5. Parallel probing

`resolve_release` resolves siblings on a `ThreadPoolExecutor`, max 4
workers, probe-only. Safe because `resolve_copy` is network-only (unwrap +
probe via injected fetch/probe): no DB access, no shared mutable state in
`current_hosts.py` (only constant tuples/dicts), and `default_fetch` builds
a fresh request per call. The recursive resolver is never run in a thread
(it shares the caller's SQLite connection).

The scheduler is lazy, not submit-all: it keeps up to 4 workers busy and
submits the next sibling only while before the deadline, so the budget
still means "no new sibling is started past the deadline" — a sibling
started just before it runs to its own probe verdict, exactly as the serial
ladder did. Results are re-sorted into input order before
`select_watch`/`select_download`, so winners are deterministic (both
selectors are stable sorts). One sibling raising no longer aborts the whole
Stage-1 failover: its exception is swallowed and the other copies still get
their chance (the serial path propagated; the single-row path still does,
preserving its old contract).

## Tests

`test_database.py` 140 → 152 (+12), `test_tiers.py` 35 → 36 (+1),
`test_redact.py` 76, unchanged. New tests, all in
`DatabaseSaveTests` unless noted:

- Negative cache hit: failing probe → record written (`no_unwrapper`) →
  second resolve refused with `reason: "negative_cache"`, probe count 0.
- Negative cache expiry: record aged past TTL + 60 s → passing probe
  serves, columns NULL again.
- `unwrap_failed` class: hubcloud `/drive/` fixture, mocked
  `unwrap_hubcloud_drive` → `[]` → class `unwrap_failed`.
- Failover order: primary + bridge sibling + direct sibling → probe order
  `[primary, direct, bridge]`, 3 probes total.
- Stage-1 budget: vidbolt fixture, faked monotonic +6 s/call → exactly 2
  `resolve_copy` calls (primary + 1 sibling), reason
  `stage1_all_copies_failed`.
- Timeout caps: fastdl (5 s / 0, 1 call), vcloud (both calls 5 s / 0),
  hubcloud_drive (10 s / 1), gdflix (10 s / 1), greenmotors (10 s / 1).
- Parallel probe: 4 vidbolt rows, fake fetch sleeps 50 ms → 4 distinct
  thread ids, 4 failures. (Found in testing: setUp stubs
  `classify_backend` to `"unknown"`, so these tests re-patch it to
  `"vidbolt"`; also `classify_backend` only maps `vidbolt.xyz`, not
  `vidbolt.example`.)
- Deadline unit test: faked monotonic, deadline 1010 → 2 of 6 siblings
  tried.
- `test_tiers.py::FailoverTests::test_candidate_order_sql_alias_qualifies_columns`:
  aliased form contains `s.`-qualified columns, no bare `id`/`created_at`,
  and `candidate_order_sql() == CANDIDATE_ORDER_SQL`.

Full backend gate: 49/49 PASS (FAILED MODULES: 0), run 01:49 PKT 2026-11-08
on the Session 101 tree (test_database 152 OK, test_tiers 36 OK,
test_redact 76 OK).

## Measured behaviour change

Before (measured read-only against live, 01:49 PKT 2026-11-08, Session 100
code still deployed): dead Pushpa 2 1080p stream 404s in 13.5 s — every
press re-proves the negative. After this deploys, the first press for a
dead copy still costs ~13 s (it must prove the negative once and record
it), but the second press within 12 h should answer 404 in milliseconds
from the negative cache — that after-value can only be measured once the
code is live, so it is owed at the gate deploy, not here.

## Deliberately left out

- The V2 legacy-id / wrong-film fix (Phase D, big design — separate
  session).
- New unwrappers (gofile/1fichier — Phase C).
- Projection rebuild; panel changes; app code.
- `probe_media`/`default_fetch` timeouts (see §2).
- A mid-playback stall watchdog (Session 99 follow-up, still open).
