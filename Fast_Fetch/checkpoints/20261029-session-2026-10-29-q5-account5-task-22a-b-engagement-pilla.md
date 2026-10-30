# Session 2026-10-29 (q5 account5 — Task #22a+b: engagement pillars design + module) `[Q5-ENGAGE]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (q5 account5 — Task #22a+b: engagement pillars design + module) `[Q5-ENGAGE]`

**Deliverable (a) landed on tip.** `docs/MONETIZATION_PILLARS_SCHEMA.md` committed as
`7817918` and pushed to `master` and `main` (both fast-forwarded from `62e7eff`; the doc is
additive-only so a same-evening q3 push onto the new tip is a trivial merge). Re-measured the
cited line numbers against `62e7eff` before pushing: `admin_panel.MONETIZATION_FIELDS` is
**at `:1070`** with **17 fields**, `vip_monthly_pkr` default **200** at `:1075`,
`remote_config()` at `:1392` publishes only `vip` (1439) and `ads` (1449) — R9's `:924-953`
was on an older base. `payments.PLAN_DEFAULTS["vip_monthly"]` still `(200, 30)` on the tip
(my prior `250` fix on branch `q5-monet-fields-20261029` was never merged, and this task says
leave `payments.py` alone); Monthly VIP is stated as **₨250 in `engagement.PASS_LADDER` per
plan doc `:46`**, and q4's reconciliation of the two is a separate call.

**Deliverable (b) built.** `Fast_Fetch/engagement.py` and `Fast_Fetch/test_engagement.py`
cover the four pillars MONETIZATION_FIELDS does not — ad cadence caps as data, the coin
wallet, the PKT streak, the PKR micro-pass ladder. Design choices that are worth flagging
to a downstream reader:

- Schema lives in the **user-state DB** (`RADD_USER_STATE_DB`, resolved through
  `accounts.default_db_path()`), NOT `app_remote_config`, because a wallet/streak/cadence
  is per-account state. `engagement.ensure_schema(conn)` calls `accounts.ensure_schema(conn)`
  first so the FK parent exists whichever module opens the file first — mirrors
  `accounts.SCHEMA_VERSION` and stamps `engagement_schema_version` under a distinct meta key
  to avoid a collision with accounts.
- **Append-only is structural, not aspirational**: two `BEFORE UPDATE|DELETE ON coin_ledger`
  triggers `RAISE(ABORT, 'coin_ledger is append-only: …')`. A correction is a fresh `-amount`
  `reason='refund'` row (SPEND_REASONS widened to include `refund` for exactly that).
- **Balance is derived**: `SUM(delta)`, no `balance` column. `spend_coins` runs its balance
  check **and** its insert as one atomic `INSERT … SELECT … WHERE balance >= cost` — a
  concurrent double-redemption cannot both pass a separate read-check and go negative.
- **No client source**: `SERVER_SOURCES = {server, admin}` and the `usage_stats` telemetry
  ingest is deliberately **not** wired here. Positive deltas require server/admin only.
- **Day bucket = local calendar date shifted back by the boundary hour (default 04:00)**.
  A 02:00 PKT call lands in the *previous* bucket, so a past-midnight session neither
  resets the streak nor earns a second Day-1. `zoneinfo` when present, else fixed UTC+05:00
  for Karachi rather than the host's local zone. Tested at 01:59 / 02:01 / 03:59 / 04:00 /
  04:01 / 23:59.
- **Rewarded-ad daily cap** counted in `coin_ledger` rows for `reason='rewarded_ad' AND
  created_at ∈ [bucket_start, bucket_start+86400)` (tz-aware). A `RADD_ENGAGEMENT_NO_REWARDED_CAP=1`
  env is the *only* bypass and is off by default; no test relies on it.
- **Pass mint reuses `redact.mint_vip_pass(expires_at, secret)`** (already honoured on
  `/api/v1/download` per M-MON-02). The signed token packs an int expiry, so `engagement`
  reports `expires_at` truncated to whole seconds — a float that wouldn't survive a parse
  round trip is a lie about what the token actually says. Day-7 streak milestone mints a
  24-hour pass; `redeem_pass(plan, pass_secret=…)` spends coins through the same atomic
  path (raises `InsufficientCoins` and mints nothing when short).
- **Cadence is server-side first**: `ad_grant(account_id, slot=…)` records the frequency and
  denies inside the window with `next_eligible_at`; `resolve_caps` treats a 0 or negative
  override as the default (never "unlimited") and clamps absurd values.

**Boundaries respected in (b).** No edit to `admin_panel.MONETIZATION_FIELDS`, no edit to the
`app_remote_config` migration, no edit to `payments.py`, `usage_stats.py`, or the
`accounts_api` telemetry route. Deliverable (c) — the admin knobs for the caps/costs/grants
— waits for q3's sha to land and then takes a fresh worktree off the new tip.

**Numbers.** 25 tests in `test_engagement.py` (fixture DB printed as the run's first line:
`/tmp/tmpXXXX/user_state.db`, never the live one). `python3 -S Fast_Fetch/engagement.py`
self-check green. Both ran in ~5 s each; imports are `accounts` + `engagement` + `redact`
only — no `viewer`/`catalog_v2`/`api_v2`, no HTTP, no `/api/data`, no `/api/v1/stats` call
this session (rule 1 and 2 observed; the box has been 5–8 load all evening).

**Gated and landed.** The box stayed above load 4 all evening, so I did **not** run the 17-module
suite locally. Instead I pushed the branch, which triggered the **hosted** Backend CI (clean
ubuntu runner) on the identical sha — the authoritative gate — then fast-forwarded `master` and
`main`. All three runs (`q5-engagement-pillars-20261029`, `master`, `main`, sha `eebdec8`)
are `completed success`; the master job shows **17/17 suite steps green, 0 non-success**
(test_database, test_vidout, test_catalog_v2, test_release_descriptor, test_link_health,
test_link_state, test_evidence_writeback, test_api_v2, test_redact, test_tiers, test_catalog_api,
test_provenance_stamping, test_merge_catalogs, test_site_scout, test_backup_manager,
test_usage_stats, test_operator_isolation). My `test_engagement.py` (25 tests) is green locally
but is **not yet in the CI list** — adding an 18th step edits the shared `backend-ci.yml`, so it
belongs in deliverable (c) on a fresh worktree once q3 lands, exactly like the MONETIZATION_FIELDS
knobs. Both files (`engagement.py`, `test_engagement.py`) are additive new modules that no other
lane imports, so master/main stayed green without them in CI.

---

