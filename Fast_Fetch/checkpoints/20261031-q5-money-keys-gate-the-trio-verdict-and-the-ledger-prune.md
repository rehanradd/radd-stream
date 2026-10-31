# 2026-10-31 — q5 `[Q5-MONEY-KEYS-GATE]`: the trio verdict, measured, then registered in CI

Branch `q5-register-money-keys`, from `8fe83e5` (the accepted derived-coverage guard). Two edits,
one commit `3163d76`: three `🧪` steps appended as one block to `.github/workflows/backend-ci.yml`
in the `run: python3 -S Fast_Fetch/<file>` form the guard's `RUN` regex parses, and the same three
names deleted from `WorkflowSuiteCoverageTests.UNREGISTERED`. Gate went 35 → 38 suite steps.

## The verdict Muse asked for — one line each, with the receipt it rests on

| suite | verdict | evidence |
|---|---|---|
| `Fast_Fetch/test_accounts.py` | **CAN run in CI offline** — no network, no live catalog, no token | `Ran 61 tests … OK`; every DB is `tempfile.TemporaryDirectory()`-made (`user_state.db`, `catalog_fixture.db`, `catalog_legacy.db` at `:71,593,611`) |
| `Fast_Fetch/test_accounts_api.py` | **CAN run in CI offline** | `Ran 38 tests … OK`; routes are called in-process — `accounts_api.route_get(path, query, db_path=self.state)` (`:65`) — and its `SECRET`/auth tokens are literal test strings |
| `Fast_Fetch/test_payments.py` | **CAN run in CI offline** | `Ran 85 tests … OK`; `mock.patch.dict("os.environ", {"RADD_USER_STATE_DB": …, "RADD_ADMIN_TOKEN": "operator-token-for-tests"})` (`:66-67`), `SECRET = "test-install-secret"`, and the panel is invoked as a function with `peer_address="127.0.0.1"` — an argument, never a connection |

All three were run here (load 2.10, `nice -n 19`, one at a time): 230.606 s / 59.978 s / 56.819 s.
The 230 s is this box, not the suite — Fleet rule 7; only CI's per-step wall decides otherwise. No
`urllib|http.client|socket|requests` in any of the three, and none opens a repo catalog path. The
supervisor's own suite `test_link_health.py` binds a throwaway server on loopback; none of these
three even does that.

## Why the ledger entry was a state claim, and which mutation proves the guard bites

`UNREGISTERED` asserted *this suite runs on no one's push*. That sentence went false in the commit
that registers the suite — the same shape as CONTINUITY's "all 32 steps now". Checked, not assumed:
with the three names pruned from the ledger, deleting the `test_payments.py` step turned the guard
red — `FAIL: test_every_module_is_registered_or_recorded_as_debt: ['test_payments.py'] is not false
… Register it in backend-ci.yml, or add it to UNREGISTERED with the reason it cannot run`
(22 tests, 0.326 s). Restore, re-run → OK. The other direction was already proven at `8fe83e5`: a
name re-added for a suite the gate now runs fails `test_no_suite_runs_twice`.

The guard's own comment quoted "the gate runs 35 of the 86 test modules" and named this trio as the
example of known debt. Both halves became false in this commit, so the sentence is gone rather than
re-numbered — no check in the file quotes a total, so nothing here needs a count maintained.

## Push blocked, again, and what that costs

`git push` via the temporary 0700 askpass helper → `remote: Invalid username or token`. `3163d76`
is handed as a sha; the supervisor pushes and gates it onto trunk at `0a1894d`. The retired
push scripts stay retired.

## Honest note on method

Mid-task I used `git checkout --` to undo a mutation probe and it reverted my *intended* guard edit
too — a discarded change I had not meant to discard. The fix was to reset the whole tree, re-apply
both edits as reviewable writes, and stop using `git checkout` to undo a probe: revert a mutation by
reversing the mutation, never by restoring a file.

## Not done here

The 16 state-shaped `INVARIANTS` pins Q1 assigned are still open; the two keystore-history pins and
the rule-7 timing samples need law-shaped replacements, and each conversion owes the same three-part
commit message (before / derived form / catching mutation).
