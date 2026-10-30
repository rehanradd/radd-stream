# q3 lane, 2026-10-29 ~19:4x host time — the operator port stops trusting loopback, the counters exist, and my own test suite was writing the production ledger `[Q3-ADMIN-DEVICE-TRACKING]`

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## q3 lane, 2026-10-29 ~19:4x host time — the operator port stops trusting loopback, the counters exist, and my own test suite was writing the production ledger `[Q3-ADMIN-DEVICE-TRACKING]`

Worktree `/tmp/q3_admin` off **`f0c1ca3`**; the work was rebased twice while in flight — onto the
then-current `master`/`main` tip **`2164cce`** (ten commits ahead of `f0c1ca3`), and again onto
**`092bc35`**, which had landed while the 17-module gate was running (both refs moved again while the
gate ran; the doc-append conflict was resolved by keeping every lane's entry, and `viewer.py`,
`test_redact.py`, `test_database.py` auto-merged against the rate-bucket fix and the adult-token
change). The rebased tree was then re-gated: **17 modules, 782 tests, all OK** (`/tmp/q3_gate2.log`).
Owner's four items, in order; full session log in `Fast_Fetch/CONTINUITY.md`.

- **B — the operator-port defect is closed, not documented.** `viewer._operator_gate` runs
  `admin_panel.gate_operator_port()` first, before any SQL, on every GET/POST of an `operator=True`
  server: off-loopback peer → 403, no or wrong credential → 401 with a byte-identical body, a proven
  bearer mints the stateless HMAC `radd_admin_session` cookie so the panel's own polling keeps
  working. Previously `RADD_ADMIN_TOKEN` guarded `/admin` only, so `/` served the 46,476-byte dashboard
  to anyone who reached the socket and `/api/v1/stats` + `/api/v1/rules` answered 200 to a bogus token.
  Proof 1: 21 live socket checks against a two-port service started from **this worktree's code**
  (refused / served / expired / forged / cross-token, public port unchanged). Proof 2: `ss -ltnp`
  binds 8080+8081 to `127.0.0.1` only and `/etc/nginx/sites-available/radd-stream` proxies 8080 and
  code-server 8443 — never 8081. Proof 3 — read this one: the *deployed* unit is **not** fixed yet.
  Re-measured ~20:0x on this host against pid 1361081 (started 19:14:36, running a pre-fix tree):
  `GET /` on `127.0.0.1:8081` with no credential → 200 / 46,476 B, and with a deliberately bogus
  bearer → the same 200 / 46,476 B; `/api/v1/rules` with no credential → 200 / 1,129 B. The hole
  closes one restart later, and restarting is the owner's call; `docs/API_SURFACE_AUDIT.md` §2.2 now
  carries that correction so its (accurate) table is not mistaken for current-code behavior.
- **A — aggregates-only device + monetization counters.** New `Fast_Fetch/usage_stats.py`
  (`usage_device` / `usage_metric` / `usage_dim_metric`, all UPSERT-on-write, salted truncated device
  bucket, 900 s seen-write floor) plus `/admin/usage` on the operator port: installs, live 5/30/60 m,
  DAU/WAU/MAU, D1/D7/D30 cohort retention, per-geo/locale/version/class, crash/error/buffer rates per
  class with a printed denominator, the ad funnel, coins, purchases by tier with the pending queue
  beside the money, and a revenue estimate whose assumptions ship in the payload. Wired **only** into
  the already-authenticated `/api/v2/account*` surface and the existing progress POST — no new public
  route, no nginx change, no `posts` scan. New `Fast_Fetch/test_usage_stats.py`: **94 tests**, which
  found five real defects (500 on the empty panel, an uncommitted anonymous counter, a double `day_of`,
  a **guessed-key-creates-a-device** amplifier now gated by new read-only `accounts.key_is_known`, and
  an analytics hook that could have failed a user's save).
- **C — partner contract gained the one property it only claimed.** `PARTNER_API.md`/`partner_api.py`
  were already in the base (`c4a1302` merge); §2.2 + `usage_for(conn, tenant)` now make cross-tenant
  metering reads unexpressible rather than merely forbidden, proven by a `--self-test` assertion (five
  now). `ANDROID_INTEGRATION.md` §7.4 documents the `X-Install-Id` / `X-App-Version` /
  `X-Device-Class` / `Accept-Language` headers and the optional `usage` block — previously code-only.
- **Gate (measured at this sha, one module per invocation): 17 invocations, 780 tests, failures=0** —
  `test_database` 124, `test_vidout` 6, `test_catalog_v2` 96, `test_release_descriptor` 24,
  `test_link_health` 57, `test_link_state` 28, `test_evidence_writeback` 12, `test_api_v2` 46,
  `test_redact` **59**, `test_tiers` 23, `test_catalog_api` 127, `test_provenance_stamping` 12,
  `test_merge_catalogs` 5, `test_site_scout` 25, `test_backup_manager` 14, `test_usage_stats` **94**,
  `test_operator_isolation` **28**. `backend-ci.yml` now runs the last two as steps (it was 15 modules;
  the file header list and both new steps were added in this push). The 7 `test_redact` failures seen
  mid-session were item B's correct fallout — fixed by giving those fixtures a real operator credential,
  not by relaxing the gate.
- **Live numbers, from a backup copy of `user_state.db` (read-only, aggregates only): the account lane
  has no traffic yet** — accounts 0, favorites 0, progress 0, `payment_transactions` 0,
  `payment_review_audit` 0, `sync_key_attempts` 3 probes (none created a device, which is the abuse
  gate holding on live data). So "active, live, accounts, how much" today is **zero, and the panel
  prints it as an absence, not a zero** — say this before anyone misreads a fresh dashboard as broken.
- **Defect I caused and then pinned: `test_redact.py` was writing into the production ledger.**
  `viewer._count_playback` counts at `accounts_api.state_db()` — the live path unless a test pins
  `RADD_USER_STATE_DB` — and the redact HTTP fixtures never did, so **42 `playback_start` rows and 4
  `usage_dim_metric` rows for day 20755 are sitting in `/home/ubuntu/radd-stream-data/user_state.db`**
  as this lane's test traffic. Both fixtures now sandbox the state DB and
  `test_the_playback_counters_cannot_reach_the_production_ledger` asserts it; re-measured live counters
  42.0 before and 42.0 after a full 59-test run. **Owner's call, not mine:** those 5 rows are inert
  until this ships and will read as 42 plays nobody made; deleting them is a write to the live ledger.
  `test_download_endpoint.py` / `test_operator_isolation.py` already pinned the path; `test_api_v2.py`
  builds no server and touches no account route.
- **Untouched, on purpose:** `/opt/radd-stream` was not committed from, reset or cleaned; `radd-stream`
  was not restarted; no nginx file was edited; no secret was read, printed or copied (the token env
  file `/etc/radd-stream/admin.env` is not readable by this account and was never attempted).
- **Next in this lane:** (1) the owner lands the sha and deploys it, then `RADD_ADMIN_TOKEN` +
  `RADD_USAGE_SALT` become load-bearing on the unit; (2) the app lane implements §7.4 — an install id
  and the four headers, or the panel keeps printing installs-equal-accounts and an honest
  "not yet reported" for every phone-side metric; (3) per-tenant `allow_tier_b` stays 0 and
  `PARTNER_TIER_B_ENABLED` stays False until the owner's written decision.

