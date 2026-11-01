# 2026-11-01 — q6 supervisor lane `[Q6-AUDIT-TID]`: audit critical 6 — one TID, one live claim, across every account

Branch `q6-audit-tid-20261101` from `origin/main` (`b99814e`), commit `25103e5`, pushed to the
lane ref only. Rules honoured: no trunk push, no tag, no service restart, no live-DB write, no
credential read, no VM Gradle; `/opt/radd-stream` untouched — every edit in `git worktree`
`/tmp/q6_tid`. Verification: this lane's suites run offline on the VM, and the pushed branch
gets one hosted CI run whose verdict is reported back to the supervisor.

## The owner decision this implements

Audit critical 6 (duplicate payment TID): the same transaction id may buy at most one live
claim. **Reject a TID that carries ANY pending or approved row — normalised (case-folded) and
cross-account — no family-account exception.** A `rejected` row blocks nothing, so a payer whose
claim was wrongly rejected can still re-file the same reference.

## What changed

- `payments.py` — `submit_payment` now calls `_tid_already_filed(conn, reference)` after the rate
  check and before the insert, inside the same `BEGIN IMMEDIATE` transaction: `lower(tid) =
  lower(?)` with `status IN ('pending','approved')` and deliberately **no** `account_id` filter.
  New `DuplicatePayment` (code `forbidden`, 403 — the closed §16.4 list has no conflict code; a
  400 `invalid_params` would misshapen a state refusal into a syntax one; `PaymentError`'s bare
  400 would read as "free VIP" territory). Detail: "that transaction id has already been
  submitted" — names no TID, no account. `sqlite3.IntegrityError` from the insert is caught and
  answered as the same 403, so the schema backstop never surfaces as a 500, and a race between
  two parallel POSTs loses exactly once.
- `accounts.py` — `ensure_schema` gained `_install_live_tid_guard(conn)`: partial unique index
  `ux_payment_tid_live ON payment_transactions(lower(tid)) WHERE status IN ('pending',
  'approved')`. It is NOT in `_INDEXES`, because `executescript` aborts the whole script on its
  first error and a live ledger that already holds duplicates (the very damage this critical is
  about) would take the service down at its next `connect()`. The guard checks for existing
  duplicates and **declines** rather than raises; collapsing money rows is an operator migration,
  and this lane wrote nothing to any live database.
- Tests — `test_payments.py`: new `DuplicateTid` class (cross-account pending and approved
  refusal, same-account re-file, recased Raast refusal, rejected-does-not-block, the 429
  ordering preserved, index presence, a raw duplicate `INSERT` hitting `IntegrityError`, and a
  legacy ledger that pre-dates the guard with duplicates still opening and still refusing in
  code) + a clean-403 edge case. `payments._selfcheck()`: the thief is now refused, not filed
  pending. Two tests that pinned the OLD behaviour ("a TID has no unique index, one payment can
  be claimed twice"; the thief's stolen claim answering `pending`) are rewritten, and
  `test_usage_stats.PaymentsCounterTests.file()` gives each label a distinct TID — it had been
  filing three accounts on one TID, which is exactly the shape critical 6 forbids.

## Measured verdicts (offline, `python3 -S`, this VM)

- `payments.py` selfcheck: OK. `test_payments.py`: **95/95 OK**.
  `test_device_trials_and_webhook.py`: 83 OK. `test_usage_stats.py`: OK.
  `test_accounts.py`, `test_accounts_api.py`, `test_admin_panel.py`: OK.
- Every module in `backend-ci.yml`'s step list run once per invocation: 40 total — all green
  **except `test_docs_invariants.py`**, which fails the `App/AGENTS.md` byte-budget check
  (16,242 B vs its 15,000 B ceiling) **identically on the untouched base `b99814e`** (verified
  in a clean detached worktree at `/tmp/q6_base`). It is pre-existing trunk condition in the
  App lane's auto-loaded file; this lane touched no `App/` path and adds no docs failure of its
  own. The hosted run on this branch will show the same single inherited red unless the App lane
  trims its file first.

## For whoever lands this

The index installs itself on next start for ledgers without duplicates; a ledger that HAS them
keeps the service up and stays guarded by the code path only — the operator dedup
(`SELECT lower(tid) FROM payment_transactions WHERE status IN ('pending','approved') GROUP BY
lower(tid) HAVING COUNT(*) > 1`) is the prerequisite for the schema half to take on that file.
