# q3 lane, 2026-10-29 ~17:05 host time — the audit blessed the leak, and here is the counterfactual

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## q3 lane, 2026-10-29 ~17:05 host time — the audit blessed the leak, and here is the counterfactual

- **What shipped (4 paths, base `7e5bd05`):** `validate_catalog_full.py` split into
  `PROJECTION_STATES` (closed) and `LEDGER_STATUSES` (`PROJECTION_STATES | {"unverified"}`), plus a
  projection-leak check and a ledger enum check; `test_catalog_v2.LinkStateVocabularyTests` (5 tests)
  binds the projector to the audit's own set so the two cannot drift; `Fast_Fetch/PARTNER_API.md` and
  `Fast_Fetch/partner_api.py` (spec + inert skeleton, nothing registered).
- **The defect was in the audit, not the projector, and it was live on `main`.** The projector's fold
  landed at `64c0b1b`. But `validate_catalog_full.py:47` kept one set for both vocabularies and
  applied it to `cat_links.state` at line 124 — so the full-catalog audit graded a fifth-state row as
  legal and the check meant to catch a regression could not see one. **Measured both ways against the
  same catalog with one `cat_links.state = 'unverified'` row injected:** `7e5bd05`'s audit reports
  `30/30 checks passed`, **exit 0**; this commit reports `30/32`, **exit 1**, naming
  `link state is a legal enum value` and `no ledger-only status leaked into the projection`. A clean
  projection reports 32/32 here with ledger `unverified` → projection `unchecked`.
- **Gate at this sha: 16/16 PASS, 823 tests, zero timeouts.** One invocation per module, `nice -n 19`,
  600s ceiling, clean worktree — 119 / 6 / 96 / 24 / 57 / 28 / 12 / 46 / 58 / 23 / 127 / 12 / 5 / 25 /
  14 / 171. Zero real skips (the `skip` hits at `test_api_v2.py:1376,1409` are keyset-pagination
  docstrings, not `skipTest`). `test_merge_catalogs` is **green at this base**, so its stale
  `status == 'active'` assertion was already corrected upstream.
- **The `master` ref moved mid-flight and this sha is the cherry-pick onto it.** `main` took the commit
  at parent `7e5bd05`; `master` had advanced to `8ad9862` ("the un-flag auditor cannot write in report
  mode"), so the push to `master` was rejected non-fast-forward and is re-committed on top of it
  rather than forced. The cherry-pick applies with no conflicts and `8ad9862` touches
  `audit_adult_flags.py` and `test_database.py` only — neither of this commit's five paths. Re-gated on
  that exact base: **16/16 PASS, 828 tests** (124 / 6 / 96 / 24 / 57 / 28 / 12 / 46 / 58 / 23 / 127 /
  12 / 5 / 25 / 14 / 171) plus `partner_api.py --self-test` OK. Note the delta is **5** tests, not 84:
  `8ad9862` adds 84 *lines* to `test_database.py`, and I said "84 tests" when I reported the rebase
  — the count moved 119 → 124.
- **Hosted proof on `main`, independent of this box.** Run `40864414373`, `🐍 Backend CI`, branch
  `main`, sha `6b28e48`: `status=completed`, `conclusion=success`, **all 15 test steps success** on
  the x86_64 runner — including `test_catalog_api`, which on this single-core box needs a 600s ceiling
  to show its 127 tests passing in ~130s.
- **Why this lane initially mis-scoped it, recorded because the failure mode is repeatable:** local
  `master` sits at `bf9e565` and the remote is at `7e5bd05` — **diverged**, with parallel rebased
  copies of the same doc work (`5b96765` remote / `94d40fc` local, identical subject) and 21 remote
  commits local does not carry. Measuring `_link_state_of` at `bf9e565` therefore showed the pre-64c0b1b
  code and looked like an unpushed fix. `/opt/radd-stream`'s working tree is carrying a **superseded
  draft of code that is already pushed** (`catalog_v2.py`, `viewer.py`, `redact.py`,
  `test_catalog_api.py`, `test_merge_catalogs.py`, 508 insertions) — reported here rather than
  committed over, per the live-tree rule. **Read `ls-remote` before concluding anything about what is
  or is not shipped.**
- **Two claims in this file and elsewhere are now superseded by measurement, kept not deleted.**
  (1) The credential: the record has oscillated today — `401` at 21:40, `200 login=rehanradd` at
  22:05 (line 314), `401 Bad credentials` again at line 365. Re-measured 16:20 host time on this box:
  `GET /user` → **200 `login=rehanradd`**; `GET /repos/rehanradd/radd-stream` → **`permissions
  {admin:true, push:true, pull:true}`, `private:false`**; `GET /actions/permissions` → **`{enabled:
  true, allowed_actions:"all"}`**. There is no standing verdict available: **the token must be probed
  in the same minute as the push**, and a green `ls-remote` on a public repo proves read, not write.
  (2) `AGENTS.md` still says `test_database.py` is "76 tests (measured 2026-10-29)"; at this sha it is
  **119**, and `test_catalog_api` is 127, `test_redact` 58. That line, plus the credential claims in
  `docs/PROJECT_MAP.md` and `App/AGENTS.md`, is **not edited here because the live tree holds
  uncommitted edits to those files** — it belongs to whoever owns that changeset.
- **Gate timeouts on this box produce phantom reds.** `test_catalog_api` hit my 180s and 240s
  ceilings and looked like a failure; at 600s it is **PASS, 127 tests, 120s**, and `SearchTests` alone
  is 12 tests in 5.1s. Box measured `nproc=1`, `loadavg 5.99` with five agent CLIs resident. A
  timeout must be reported as TIMEOUT, not FAIL, or lanes will keep chasing defects that do not exist.
- **Partner API: Tier B is fenced twice and Tier A is documented as not yet resellable.**
  `api_tenants.allow_tier_b` is `NOT NULL DEFAULT 0` with no request-reachable setter, and
  `PARTNER_TIER_B_ENABLED = False` at module level — **both** must be true, and `handle()` routes
  every Tier B decision through the single `release_allowed()` function. The `--self-test` is
  mutation-tested: breaking either half fails a named assertion. It initially did not — the first
  version asserted `not release_allowed(promoted,"B")` while the global was off, which is vacuously
  true and passed while the tenant flag was being ignored entirely. Nothing imports `partner_api`;
  the nginx block is written but **not applied** (owner's action), and §7.1 states that partner
  traffic cannot be offered before TLS exists on this host, which today answers plain HTTP.
- **Dissent recorded against `docs/MONETIZATION_AND_FLEET_PLAN.md` §D, and it is not a footnote.**
  (1) Tier A as written includes "link-health scores"; per-endpoint liveness tells a customer which
  infringing copies are up without handing them URLs, which is Tier B in substance — `/health/aggregate`
  therefore returns counts per work and per site only. (2) "what a partner can legally build on" is
  assumed, not established: posters, synopsis, genres, ratings and `tmdb_id`/`imdb_id` arrive via the
  TMDB enrichment path and default TMDB terms do not grant onward commercial redistribution, so §1.2
  gates invoicing on a license or a rights-clean subset and every response carries a `prov` map. Also
  §2.1: the adult law binds rows, and `AGENTS.md` measures a work-level gap (`4 Play` id 23519), so
  "18+ never appears" is not yet a claimable promise for a partner integrating today.
- **Not done, and deliberately not started:** no production route is registered; `viewer.py` and
  `fast_fetch.py` are untouched by this sha; the 8081 loopback-only operator port (`/` serving the
  dashboard with no token, measured 05:47) is a separate fix that predates any tracking endpoint and
  is still the owner's to schedule.


