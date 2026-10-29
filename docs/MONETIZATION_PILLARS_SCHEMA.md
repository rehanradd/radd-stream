# 💠 MONETIZATION_PILLARS_SCHEMA — engagement storage, read path, and admin write path

> **Owner/Task:** QODER4 → QODER5, Task #22. Deliverable **(a)** (this doc), before any code.
> **Author:** q5 (account5). **Base:** tip `62e7eff`. **Stdlib only.**
> **Status:** design. Code lands in `Fast_Fetch/engagement.py` + `test_engagement.py` (deliverable b),
> then — and only after **q3's sha is pushed** — the admin knobs are added to
> `admin_panel.MONETIZATION_FIELDS` on a fresh worktree off the new tip (deliverable c).

---

## 0. Scope, and the three boundaries that keep two lanes out of one table

This module owns the **engagement pillars that `MONETIZATION_FIELDS` does not cover at all**
(gap **M-MON** in `docs/FULL_MASTER_FEATURE_INVENTORY.md`): ad-cadence caps as tunable data, the coin
wallet (balance + append-only earn/spend ledger + redemption), the 7-day streak state machine, and the
PKR micro-pass ladder. Every earning way in the app must be controllable from the admin panel — today
these are literals in the APK (`docs/MONETIZATION_AND_FLEET_PLAN.md` Pillars 1–3), so the owner cannot
tune them without shipping a build.

| Boundary | Rule | Why |
|---|---|---|
| **q3 is live on `app_remote_config` / `MONETIZATION_FIELDS`** | This module **never writes** `MONETIZATION_FIELDS` or that table's migration in deliverables (a)/(b). The admin *knobs* are specified here but **added only in (c)**, on a fresh worktree off q3's pushed sha. | Two lanes editing one tuple/one table is how we lose work. `RADD_RELAY_AND_AUTH_ARCHITECTURE.md` R9 lists q3's exact new fields (`trial_days_on_install`, `anonymous_mint_enabled`, `radd_relay_enabled`, `device_tracking_enabled`, `coin_earn_watch_minutes`, `coin_value_pkr`, …). |
| **`payments.py` is a collision zone** | The pass ladder / price table lives **in `engagement.py`**, not `payments.py`. Q4 reconciles the two when both land. | Q4's explicit instruction. `payments.PLAN_DEFAULTS` still says monthly 200; the plan doc `:46` says **250** and is authoritative; I do not touch payments. |
| **link-shortener law (permanent)** | Nothing here mints a redirect, CAPTCHA, or timer. `shortener_targets()` stays `[]` unless `feature_link_shorteners=1`; this module does not call it and cannot route a viewer through a shortener. | Owner directive; retired forever. |

**Coin-vs-q3 overlap, resolved:** q3 owns the *admin-side earning knobs* (`coin_earn_watch_minutes`,
`coin_value_pkr` — "how much a watch is worth"). This module owns the *ledger and balance* ("what a user
actually has, and what they may spend it on"). They are different tables: q3 writes one config row, I
write a per-account ledger. At read time the config values (defaults defined here, overridable in (c))
feed the ledger's earn arithmetic. No double-definition.

---

## 1. Grounding — measured facts on tip `62e7eff` (do not re-assume; re-measure)

1. **`MONETIZATION_FIELDS` is 17 fields** (`admin_panel.py:1070`, re-measured on this base; `RADD_RELAY…`
   R9's `:924-953` was an earlier base) with `vip_monthly_pkr` default **200** (`:1075`);
   `remote_config()` (`admin_panel.py:1392`) publishes `vip` + `ads` blocks and **no** `wallet`/`streak`/
   `passes`/cadence keys. So the pillars are genuinely absent on the tip (an earlier `q5-monet-fields`
   branch added cadence/wallet/pass keys but was **never merged**).
2. **`Fast_Fetch/usage_stats.py` already treats `coin_granted` / `rewarded_completion` as
   client-reported *telemetry*** (`:293`, `:112-113`, `:126-127`). Telemetry is analytics, not money:
   the route that ingests it must **not** create a balance. This is the single reason the wallet here is
   server-derived and the client cannot set it.
3. **The accounts DB is the right home.** `accounts.py` holds the per-user state (`user_accounts`,
   `payment_transactions`, …) in the file `connect()`d from `RADD_USER_STATE_DB`. Engagement is
   per-account state, so it lives in the same database, **not** `app_remote_config` (which is a single
   operator row). Its schema install is `ensure_schema` = `executescript(DDL)` + guarded
   `_NEW_COLUMNS` `ALTER`s (each via `PRAGMA table_info`) + `_INDEXES` created **after** the ALTERs +
   a `user_state_meta.schema_version` stamp — idempotent, additive, never drops, never rewrites a row.
   `engagement.py` mirrors this pattern exactly.
4. **Pass primitives already exist:** `redact.mint_vip_pass(expires_at, secret)` (`redact.py:890`) and
   `redact.parse_vip_pass(token, secret, now)` (`:904`). The download route already honours a signed
   VIP pass. Redemption therefore reuses these rather than inventing a token format.
5. **Schema drift is real and must be assumed.** The live `app_remote_config` has **18 columns** and does
   **not** carry `feature_link_shorteners` while the code lists it (`RADD_RELAY…` R9 "Schema caution").
   Lesson applied here: `engagement.ensure_schema` reads `PRAGMA table_info` and never assumes the
   deployed shape equals the pushed one.

---

## 2. Tables (sketch; exact DDL is in `engagement.py`)

All in the user-state DB. `account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE`
where the row is meaningless without the account (wallet ledger, streak, cadence). Money-adjacent
history that must outlive the account follows `payment_transactions` and **omits** `ON DELETE CASCADE`;
the coin ledger is *entitlement* state, not a receipt, so it cascades (a deleted account's coins die with
it — there is no cash value to preserve, per §A).

### 2.1 `coin_ledger` — append-only, the only thing that can create a coin

```
id            INTEGER PRIMARY KEY AUTOINCREMENT
account_id    INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE
delta         INTEGER NOT NULL           -- signed. earn > 0, spend < 0. Whole coins only.
reason        TEXT    NOT NULL           -- 'rewarded_ad' | 'streak_day' | 'redeem_pass' | 'admin_grant' | 'refund'
ref           TEXT                        -- what it points at (pass id, streak day, admin note id). never a title.
idempotency_key TEXT UNIQUE              -- NULLable. Duplicate key = INSERT OR IGNORE = the SAME grant, once.
source        TEXT    NOT NULL           -- 'server' | 'admin'. There is NO 'client' source for a positive delta.
created_at    REAL    NOT NULL
```

**Structural invariants (enforced in the DB, not only in code):**
- **Append-only:** `BEFORE UPDATE`/`BEFORE DELETE` triggers on `coin_ledger` `RAISE(ABORT, …)`. The
  ledger cannot be edited or retracted; corrections are a new compensating row (`reason='refund'`).
  This makes "append-only" a property of the storage, not a promise in a docstring.
- **No client-created coin:** the only write API is `engagement.grant_coins(...)` / `spend_coins(...)`,
  both requiring a `source` in the server set. The `accounts_api` telemetry route (`usage_stats` ingest)
  is **not** wired to these. A client body that says "I earned 50 coins" cannot reach the ledger.
- **Balance is derived, never stored:** `coin_balance(conn, account_id) =
  SELECT COALESCE(SUM(delta),0) FROM coin_ledger WHERE account_id=?`. No `balance` column means a race
  cannot corrupt it and a tamper cannot set it. An index on `account_id` keeps the SUM from scanning.
- **Idempotent grants:** a rewarded-completion S2S callback retried 5× lands as **one** row because the
  network's callback id is the `idempotency_key`; `INSERT OR IGNORE` + the UNIQUE index deduplicates.
- **No negative balance:** `spend_coins` runs inside one transaction, checks `SUM(delta) >= cost`
  **after** locking the account's rows, and refuses (`InsufficientCoins`) rather than writing a row that
  would make the balance negative. A pass is minted only if the spend committed.

### 2.2 `streak_state` — the 7-day machine, one row per account

```
account_id        INTEGER PRIMARY KEY REFERENCES user_accounts(id) ON DELETE CASCADE
tz                TEXT    NOT NULL DEFAULT 'Asia/Karachi'   -- the zone the day is measured in
day_boundary_hour INTEGER NOT NULL DEFAULT 4                -- civil-day rollover hour, local (see §3)
last_counted_day  TEXT                                      -- 'YYYY-MM-DD' bucket last credited, or NULL
current_streak    INTEGER NOT NULL DEFAULT 0
best_streak       INTEGER NOT NULL DEFAULT 0
last_grant_reason TEXT
updated_at        REAL    NOT NULL
```

`record_engagement_day(conn, account_id, now, cfg)` is the only mutator. It returns the transition
(`advanced` / `same_day_noop` / `reset`) and any grant it made, so the caller never guesses.

### 2.3 `ad_cadence_state` — server-side frequency, so a client cannot out-serve the plan

```
account_id            INTEGER PRIMARY KEY REFERENCES user_accounts(id) ON DELETE CASCADE
last_preroll_at       REAL NOT NULL DEFAULT 0
last_app_open_at      REAL NOT NULL DEFAULT 0
native_poster_cursor  INTEGER NOT NULL DEFAULT 0   -- count of posters served since the last native card
updated_at            REAL NOT NULL DEFAULT 0
```

The **caps** (25 min / 12 posters / 4 h) are *config* (defaults in §4; overridable from
`app_remote_config` in deliverable c). This table is the *state* the caps are checked against. Enforcement
is server-side first and client-side second: `ad_grant(conn, account_id, slot, now, caps)` answers allow /
deny + `next_eligible_at`. A phone that ignores the cap still cannot get a second pre-roll inside 25 min
from the server, which is what keeps the "1 per 25 min" promise true for a person who binge-watches.

---

## 3. Timezone, and the Pakistani user at 02:00 (the part Q4 asked about explicitly)

A "day" for a streak must not be a UTC date and must not be raw local midnight, because both are wrong
for a person whose viewing session runs past midnight. Design:

- **A day-bucket** = the local calendar date in `tz` (default `Asia/Karachi` = PKT, UTC+5), **with a
  configurable rollover hour** `day_boundary_hour` (default **04:00 local**).
- Concretely, the bucket of an instant `now` is the calendar date of `now` shifted back by the boundary:
  `bucket(now) = date( (now - boundary_seconds) in tz )`. So a login at **02:00 PKT** falls in the
  **previous** day's bucket, not a brand-new one. A user up past midnight finishing an episode does not
  see their streak reset or jump, and does not get a second "Day 1" coin for the same evening.
- **Reset semantics:** on `record_engagement_day`, compare `bucket(now)` to `last_counted_day`:
  - same bucket → `same_day_noop` (no grant, no increment — idempotent per civil day);
  - exactly one bucket after (`(today - last) == 1 day`) → `current_streak += 1`, `advanced`;
  - a gap of ≥2 buckets (they skipped a whole day-bucket) → `reset` to 1 (the missed day restarts the
    streak; the plan's Day-7 reward requires *consecutive* days by design).
- **Grants fire on transition into the milestone buckets** using the plan's ladder (Pillar 2, lines 33–35):
  Day 1 → 10 coins, Day 3 → 30 coins, Day 7 → a 24-hour ad-free VIP pass (minted via §5), with each grant
  written to `coin_ledger` under `idempotency_key = 'streak:{account}:{bucket}'` so even a replayed call
  credits once.
- **`tz` fallback:** `zoneinfo.ZoneInfo` (stdlib, py3.9+). If the tz database is absent on the box, fall
  back to a fixed `UTC+05:00` offset for `Asia/Karachi` rather than silently using the machine's local
  zone — the streak must mean the same day to every Pakistani user regardless of where the server sits.

---

## 4. Ad-cadence caps as data (Pillar 1) — keys, defaults, and where each lives

`docs/MONETIZATION_AND_FLEET_PLAN.md` lines 18/21/26. Defaults are the plan's own numbers, so an operator
who has never opened `/admin` still ships the capped behaviour:

| Cap | Default | Meaning | Admin key (added in c, `MONETIZATION_FIELDS`) | Read path now |
|---|---|---|---|---|
| `ad_preroll_min_gap_minutes` | **25** | ≥25 min between pre-rolls, per account | `_INT` | `engagement.resolve_caps()` default until (c) |
| `ad_native_card_every_posters` | **12** | 1 sponsored card per 12 posters | `_INT` | same |
| `ad_app_open_min_gap_minutes` | **240** | ≥4 h between app-open ads | `_INT` | same |

`engagement.CAPS_DEFAULT` is the single literal source; `resolve_caps(overrides)` merges a caller's dict
(the values that will come from `app_remote_config` in (c)) over these defaults and **bounds** them
(non-negative, sane maximum) so a bad save cannot make the cadence "0 = unlimited" — a cap of 0 is
interpreted as "use the default," never "serve constantly." The app reads the resolved caps through
`/api/v1/app/remote-config` under an `ads.cadence` block (see §6).

---

## 5. Pass ladder + coin redemption (Pillars 2–3), with the anti-deception law from §A

The ladder lives in **this module** (not `payments.py`), as a published price table:

| Pass | PKR (plan `:44-46`) | Duration (server truth) | Coin cost (redemption path) |
|---|---|---|---|
| `day` | **20** | 24 h from grant | `REDEEM_DAY_COINS` |
| `weekend` | **50** | Fri→Sun (next local weekend end in `tz`) | `REDEEM_WEEKEND_COINS` |
| `monthly_vip` | **250** | 30 days | `REDEEM_MONTHLY_COINS` |

- **Monthly VIP = 250** per `MONETIZATION_AND_FLEET_PLAN.md:46`, which Q4 ruled authoritative. This
  module states 250; `payments.PLAN_DEFAULTS` keeps its own value untouched and **Q4 reconciles the two**.
- **Grant mechanism:** a purchased or redeemed pass extends `user_accounts.vip_until` (`max(now,
  vip_until) + duration`) — the same column the paid path uses, because the download route asks one
  question: *is this account VIP right now?* A **rewarded** 4 h pass (Pillar 2, lines 37–38) is minted
  as a signed token via `redact.mint_vip_pass(expires_at, secret)` so it can be honoured on
  `/api/v1/download` and cannot be replayed after expiry (M-MON-02). Duration 4 h, hard max 24 h.
- **Coin earn path (rewarded ads):** 3–5 rewarded completions unlock 4 h ad-free (plan line 37), capped at
  10 rewarded ads/user/day (line 38). Modelled as: each *server-verified* `rewarded_ad` completion
  (`idempotency_key = network callback id`) credits `coin_value` coins (q3's knob, default defined here);
  redemption of `REDEEM_*_COINS` mints the pass. The daily cap is enforced in `grant_coins` against
  `coin_ledger` rows for `reason='rewarded_ad' AND bucket(today)`, so no client can exceed it.
- **§A — no deception, stated as invariants (this is the whole reason the design is shaped this way):**
  1. Coins are spendable **only** on these passes — there is no cash-out path in the schema at all.
  2. Every pass's coin cost is **published** (in `remote-config`) and reachable: an actively daily user
     earns the Day-7 pass with no hidden multiplier; the numbers in `coin_ledger` are the real numbers.
  3. `coin_value`, grant sizes, and costs are **server config**, never returned by the client, and the
     earn path requires a **server-verified** proof (S2S callback id or an admin grant), so "watch an ad"
     cannot be self-declared.
  4. There is no "hope to withdraw but can't" mechanism: the reward is a real 24 h pass on a real
     balance, and the withdrawal scheme in the plan doc §A is **not implemented**.

---

## 6. Read path (`/api/v1/app/remote-config`) and write path (admin) — sequencing

- **Read (what a phone gets):** `admin_panel.remote_config()` is extended — **in (c)** — to publish an
  `engagement` object: `{wallet: {coin_value_pkr, redeem_costs, expiry}, streak: {grants, day_boundary_hour,
  tz}, passes: {day, weekend, monthly_vip pkr+coins}, ads.cadence: {…25/12/240}}`. Until (c),
  `engagement.remote_view()` (same module) exposes these **from defaults** so the client can integrate
  against the shape now; the admin knobs simply override defaults later.
- **Write (what the operator does):** the admin *edit* of those caps/grants is the `MONETIZATION_FIELDS`
  addition in (c). Per-account **state** (balance, streak, cadence) is **not** operator-editable except
  through the audited admin grant/refund action (`reason='admin_grant'`, `source='admin'`), which writes
  a ledger row like any other — there is no "set balance to 9999" field, by design.
- **Migration for `app_remote_config` in (c)** must be additive/idempotent and guarded by
  `PRAGMA table_info` (the fact R9 records — 18 live columns vs code — is exactly why we never assume).

---

## 7. Migration sketch for the engagement tables

```
engagement.DDL           CREATE TABLE IF NOT EXISTS coin_ledger / streak_state / ad_cadence_state
engagement._TRIGGERS     CREATE TRIGGER IF NOT EXISTS ... BEFORE UPDATE|DELETE ON coin_ledger BEGIN
                           SELECT RAISE(ABORT,'coin_ledger is append-only'); END;
engagement._NEW_COLUMNS  name -> (decl, backfill) for anything a later release adds, mirroring accounts.py
engagement._INDEXES      created AFTER _NEW_COLUMNS ALTERs: idx on coin_ledger(account_id),
                           ux on coin_ledger(idempotency_key) (UNIQUE), idx streak_state(account_id)
engagement.ensure_schema executescript(DDL); _migrate_columns(); executescript(_TRIGGERS);
                           executescript(_INDEXES); stamp schema_version. Idempotent, additive, never drops.
```

Triggers and indexes are created after the column ALTERs (the `import_hindilinks4u` lesson, reused by
`accounts.ensure_schema`): an index or trigger that touches a migrated column must not be installed
before the column exists.

---

## 8. Security & compliance invariants (test targets)

1. **Append-only ledger** — an `UPDATE`/`DELETE` on `coin_ledger` aborts (trigger-proven).
2. **Balance derived** — no `balance` column exists; `coin_balance == SUM(delta)` always.
3. **No client-created coin** — `grant_coins` rejects `source not in {server, admin}`; the telemetry
   ingest path is not wired to the ledger.
4. **Idempotency** — the same `idempotency_key` twice yields one row and one balance change.
5. **No negative balance** — a spend above balance raises `InsufficientCoins` and mints no pass, atomically.
6. **Rewarded daily cap** — an 11th `rewarded_ad` grant on the same day-bucket is refused (10/day).
7. **Streak day-bucket** — a 02:00 PKT call lands in the previous bucket: no double Day-1, no reset.
8. **Streak reset** — a missed day-bucket sets `current_streak=1` on next credit; `best_streak` monotone.
9. **Cadence server-enforced** — two pre-roll requests inside `min_gap` → second is `deny` with a
   `next_eligible_at`; caps of 0 resolve to defaults, never "unlimited".
10. **§A no-deception** — coin cost + grant numbers published; no cash-out field exists in any table.

---

## 9. Test plan (deliverable b)

`Fast_Fetch/test_engagement.py` runs against a **fixture** `RADD_USER_STATE_DB` inside a `tempfile`
directory and **prints the resolved path** so the proof is in the run (rule 5: never the live
`/home/ubuntu/radd-stream-data/user_state.db`). Imports only `accounts` + `engagement` + `redact` —
deliberately **not** `viewer`/`catalog_v2`/`api_v2`, so it is light enough to run while the shared box is
loaded, and it never touches `/api/data` or `/api/v1/stats`. It covers invariants 1–10, the timezone
boundaries (01:59 / 02:01 / 03:59 / 04:01 local), and a rewarded→redeem→expiry round trip. `engagement.py`
carries a `python3 -S Fast_Fetch/engagement.py` self-check (temp file, no port) in the `payments.py` style.

---

## 10. Explicit non-goals / collisions avoided

- Do **not** edit `admin_panel.MONETIZATION_FIELDS`, its `app_remote_config` migration, `payments.py`,
  `usage_stats.py`, or the `accounts_api` telemetry route in (a)/(b). Those are (c) or another lane.
- Do **not** add a redirect, CAPTCHA, or timed path anywhere (shortener law).
- Do **not** run anything against the live catalog or `/api/data`; shape is measured on fixtures.
- Do **not** build the withdrawal/"fake currency" scheme the plan §A rejects.
