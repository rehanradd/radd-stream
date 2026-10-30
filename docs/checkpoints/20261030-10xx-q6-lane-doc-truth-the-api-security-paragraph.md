# 2026-10-30 10:xx — q6 lane `[Q6-DOC-TRUTH]`: the API-security paragraph was wrong on four of five points, and the dead workflow copies finally went

Lane: account4 / q6, working from a fresh worktree at trunk `024f554`. Docs-only; **no Python and no
Kotlin changed**, no database touched, no service restarted, no tag.

## Why this session started, and the finding that outranks everything else

The owner asked for the usual three things: the small fixes first, delete the old docs and test files,
and rewrite the docs so agents stop burning context on them. The plan was approved against
`/opt/radd-stream`, and **that tree is 103 commits behind trunk and carries 33 modified + 8 untracked
files from other lanes.** It supersedes the `85 behind / 22 dirty` measurement in
`20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md` — same defect, worse now.

Consequence, stated plainly because it is the reason two of the three requested jobs were not done:

- **The adult-flag reconciliation the owner asked for had already shipped.** `20f5fcc` put
  `fast_fetch.inherit_key_adult()` + `Fast_Fetch/backfill_adult_key.py` + `audit_adult_flags.py` on
  both trunk refs, with ~473 new test lines across `test_database.py` and `test_redact.py`. Writing it
  again would have been a revert wearing a new name.
- **The specific SQL I had drafted was the wrong design**, and is recorded here so nobody re-tries it:
  a blanket `UPDATE posts SET is_18_plus = 1 WHERE canonical_key IN (SELECT canonical_key FROM posts
  WHERE is_18_plus = 1)` is unbounded, and it files the degenerate `unknown` key, so one titleless
  page would hide unrelated titles. Under key-level law a false row-flag hides a whole work — which is
  exactly how `\buncut\b`/`\bunrated\b` came to mis-flag 7,663 of 15,068 rows. The shipped code
  reconciles inside the write, bounded by `idx_posts_canonical_key`, and refuses `unknown`.
- **The docs "already 80 % fixed"**: `CHAT_HISTORY.md` (5.2 MB) is gone, the layered logs are rotated
  into `docs/checkpoints/` + `Fast_Fetch/checkpoints/`, and the three auto-loaded `AGENTS.md` files are
  350 / 205 / 243 = **798 lines ≈ 56 KB**, not the 126 K-line wall the stale tree implied. Corpus total
  is 198 `.md` / 29,692 lines, but 106 of those files are a LOG no agent auto-loads.
- **A docs deletion list would have turned CI red on purpose.** `Fast_Fetch/test_docs_invariants.py`
  (32nd `🧪` step) enforces ~90 verbatim law phrases, ≥20 `SPEC_*.md`, ≥10 files per `checkpoints/`
  dir, README index counts equal to the directory listing, and link reachability. "Delete all old docs"
  is not available without editing that guard, which is a deliberate documented change, not a cleanup.

Everything below is what was actually left to do, and what the owner approved: items 1+2 only.

## Part 1 — eleven false statements about the API, corrected against code

Every claim was re-measured in this worktree before being written down. Code truth at `024f554`:

| Claim repeated across the docs | Measured reality |
|---|---|
| `send_json()` answers everything with `Access-Control-Allow-Origin: *` | `CORS_ALLOW_ORIGINS` is an **empty `frozenset`** (`redact.py:1309`); `cors_headers_for()` (`:1312`) emits the header only for an allow-listed origin, so today **no** response carries it — verified `grep -n "Access-Control-Allow-Origin" *.py` hits only that one line plus a fake server in `test_link_health.py` |
| "no rate limiting anywhere in `viewer.py`" | `_public_gate()` (`viewer.py:3379`) denies operator-only routes, runs one token bucket per client per route family through `redact.limiter`, stamps `RateLimit-*` on every answer, and returns **429 + `Retry-After`** (v2 gets an RFC-7807 `rate_limited` problem document) |
| nginx has no edge limit | `limit_req zone=radd_stream_api burst=30 nodelay` is live in `/etc/nginx/sites-available/radd-stream` |
| `start_server()` binds `0.0.0.0` | defaults `host="127.0.0.1"` (`viewer.py:3929`); `fast_fetch.py serve --host` also defaults `127.0.0.1` (`:6083`), so a manual run no longer re-opens the old exposure |
| "the API implements no authentication, no token, no session" — full stop | the **catalog** routes are anonymous, but two credentials exist: `RADD_ADMIN_TOKEN` (`admin_panel.py:404`, loopback port, guards `/admin`) and account sync keys (`accounts.py:585`) |

**Still true, and kept stated as loudly as before:** no TLS anywhere, Oracle serves plain HTTP, and
`/api/v1/posts` needs no credential — so nothing behind it is private. A throttle is not an
authentication; the rewrites say that in those words so the correction is not read as an all-clear.

Files corrected (11 spots, all present-tense false claims, none of them a guard-pinned phrase):
`README.md` §Authentication and transport · `Fast_Fetch/AGENTS.md` rule 9 · `App/AGENTS.md` ⚠️ Reality
bullet · `App/docs/TECH_STACK.md` · `App/docs/PLAN.md` §3.3 · `Fast_Fetch/ANDROID_INTEGRATION.md` (the
`/api/v1/stream` 302 shape, and the "still stamps `*` / still defaults `0.0.0.0`" paragraph) ·
`Fast_Fetch/API_V2.md` (defect table row 6 **and** §16.7 — both asserted the module default was still
`0.0.0.0`; `radd-stream.service` is not the only bind any more) · `docs/PROJECT_MAP.md` (retired its own
third stale claim "no rate limit", and dropped the drifted line numbers in favour of symbol names) ·
`docs/SPEC_PLATFORM_NOTES.md` · `docs/SPEC_INCOMING_AGENT_CHECKLIST.md` (the 2026-10-13 "Deployment
gate" paragraph, marked history rather than rewritten) · `AGENTS.md` (the "≤ 20-line index" claim:
`CONTINUITY.md` is 119 lines and `SESSION_CHECKPOINT.md` 54 — the guard ceiling is ≤120 lines / ≤12 KB).

The client-visible consequence of the rate-limit correction is in `App/` twice: a 429 with
`Retry-After` means the app must back off, not retry immediately. That was never written down before.

## Part 2 — the never-discovered workflow copies are deleted

`git rm App/.github/workflows/{ci.yml,release.yml,pr-check.yml}`. GitHub only discovers repo-root
`.github/workflows/`; these three could never have fired, and both `AGENTS.md` files had been saying
"they are inert and are being retired" for a week. All references to them were past-tense history
(`backend-ci.yml`/`ci.yml` header comments, `ORACLE_DEPLOYMENT.md` §GitHub Actions status) and stay.

**What left with them:** `pr-check.yml` was the only file in the repository with a `pull_request`
trigger. It never ran, so nothing is lost functionally — but there is now, honestly, **no PR gate**:
CI runs on push. Recorded in `AGENTS.md`, `docs/PROJECT_MAP.md`, `docs/SPEC_AGENTS_MEASURED_NOTES.md`
and `docs/AGENT_BOOTSTRAP.md` (which also claimed root had only `ci.yml` + `release.yml`, omitting
`backend-ci.yml`). If PR gating is ever wanted it must be authored fresh at the root.

## Gate

- `python3 -S <module>` one per invocation, from repo root, the full CI list — **32/32 green**:
  `test_database test_vidout test_catalog_v2 test_release_descriptor test_link_health test_link_state
  test_evidence_writeback test_api_v2 test_redact test_tiers test_catalog_api test_provenance_stamping
  test_merge_catalogs test_site_scout test_backup_manager test_usage_stats test_operator_isolation
  test_media_search test_migrate_search_indexes test_bounded_ledger test_project_readonly
  test_posts_query_plan test_adult_twin_probe test_link_sweep_budget importers/test_themoviebox_links
  importers/test_themoviebox_detail_api test_admin_panel test_host_serialiser test_docs_invariants
  test_operator_read_bounds test_engagement_ladder test_operator_adult_projection`
  (`grep -c 'name: 🧪' .github/workflows/backend-ci.yml` = **32**; re-count it, never remember it.)
- `test_docs_invariants.py` 18 tests OK **before and after** — the byte ceilings hold: root 29,045 B
  (of 32,000), `App/AGENTS.md` 12,435 (of 15,000), `Fast_Fetch/AGENTS.md` 14,469 (of 18,000).
- Note `test_database.py` is **green here and failed 2 tests in `/opt/radd-stream`** — the two failures
  (`test_operator_dashboard_payload_exposes_every_site_page`, `..._legacy_release_attribution`) read the
  developer's live `Fast_Fetch/fast_fetch.db`. That is the stale tree talking, not a code defect, and it
  retires the local "76 tests must pass" panic the checkpoint log carries.

## Deferred by the owner, not forgotten

1. **Re-key migration** — the real adult residual. 953 works flagged in the projection while **1,190
   ledger rows stay public under a different key** (`suzume-2022` vs `suzume_2022`); concentrated in
   filmyzilla 437 / 9xmovies 344 / moviezguru 190 / hindilinks4u 151. Measured blast radius **2,600 keys,
   3,486 publicly served rows, 69,773 rows to re-key**. Owner: leave planned this round. It also cannot
   be run blind — `CONTINUITY.md` queued item 3 says no command exists yet to count twins against the
   live 6.4 GB catalog, and one `WHERE is_18_plus=1` count already cost 26.46 s on a single vCPU.
2. **SPEC vs big-doc dedup** — 6 files restate `SITES.md` / `DATABASE_SCHEMA.md` / `API_V2.md` /
   `App/design/*`: `SPEC_FAST_FETCH_SITES` (224), `SPEC_APP_API_CONTRACT` (217), `SPEC_BRIDGE_CDN` (82),
   `SPEC_APP_SCREENS` (53), `SPEC_FAST_FETCH_SCHEMA` (40), `SPEC_APP_DESIGN_QUICKREF` (26) ≈ 650 lines.
   Removing them requires lowering the `≥20 SPEC files` floor in `test_docs_invariants.py:362-369`
   first, in the same commit, or CI fails. Declined this round.
3. **`.replit` is git-TRACKED**, which contradicts root `AGENTS.md`'s own law and the guard phrase at
   `test_docs_invariants.py:144`. `git rm --cached .replit` + a `.gitignore` entry would make the repo
   match its stated policy without rewriting history. Declined this round (it needs the owner's call).

## Two measurements that contradict the docs, reported not "fixed"

1. **`redact.link_is_adult()` returns False for an unknown link id.** Its docstring says "An unknown
   link answers True too, so a vanished row, a typo and a flagged title are indistinguishable — and
   none of them plays", and root `AGENTS.md` repeats it. The code is `return bool(row and row[0])`, so
   `row is None` → **False**: a typo is *allowed past the adult gate* and stopped later by
   `resolve_live_source`. q3 measured this first (`checkpoints/20261030-09xx-q3-lane-job-b…`) and also
   reported it unfixed. This is a fail-open in a deny-by-default rule — a behaviour change, so it needs
   its own reviewed commit with a test, not a drive-by doc edit. **Neither the doc nor the code was
   touched here.**
2. **`Fast_Fetch/CONTINUITY.md` is at 11,831 B of its 12,000 B ceiling and 119 of 120 lines.** The next
   backend lane that follows rule 6 ("log every session in CONTINUITY.md") will fail CI simply by
   writing it down. The diet needs one deliberate line trimmed or the ceiling raised as a documented
   edit. This session logged to `docs/checkpoints/` instead, per this file's own rule 4.
