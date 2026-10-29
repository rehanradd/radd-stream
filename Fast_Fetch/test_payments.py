#!/usr/bin/env python3
"""Offline tests for `payments.py` — the PKR ledger, the operator approval and the
VIP entitlement it buys (`docs/FULL_MASTER_FEATURE_INVENTORY.md` §M-MON-01).

Same discipline as `test_accounts.py` / `test_accounts_api.py` /
`test_admin_panel.py`: every case is a plain function call against a temp
`user_state.db` in a temp directory. No port is opened, no network is touched, no
live database is read or written — and `RADD_USER_STATE_DB` is pinned to the temp
file for the whole test so a forgotten path argument cannot reach the deployment's
real ledger. `python3 -S` runs it with no installed dependencies, which is the
only supported way to run this project's tests.

    python3 -S Fast_Fetch/test_payments.py

What these files are actually about, in order of how much they matter:
  1. a client can never set its own price, and a price of 0 sells nothing;
  2. one payment can credit exactly one term, however many times it is approved;
  3. a renewal banks the days already paid for instead of restarting them;
  4. a reject cannot move `vip_until` at all;
  5. a transaction id never leaves on the account surface, and a review needs a
     token this process minted for that one row.
"""
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts            # noqa: E402
import accounts_api        # noqa: E402
import admin_panel         # noqa: E402
import api_v2              # noqa: E402
import payments            # noqa: E402
import redact              # noqa: E402

SECRET = "test-install-secret"
TOKEN = "operator-token-for-tests"
P = accounts_api.PREFIX
DAY = 86400.0
#: A fixed epoch, so "inside the 5-minute window" is arithmetic and not a race
#: with the wall clock. Routes that go through the HTTP edge use real time.
NOW = 1_800_000_000.0
#: Names that must never appear in a body, and the fixture's own polluted work
#: key, which is what a real leaked site name looks like in this catalog.
NEEDLES = {"katmoviehd", "vegamovies", "rareanimes", "sample-site"}
JAZZ_TID = "9823145671"
EASY_TID = "150923456789"
RAAST_TID = "RAST2024AB39C7D1E5"


class Fixture(unittest.TestCase):
    """One temp accounts ledger, one temp catalog, one enrolled account."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "user_state.db"
        self.catalog = root / "catalog.db"
        env = mock.patch.dict("os.environ", {"RADD_USER_STATE_DB": str(self.state),
                                             "RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        # The catalog gets the two tables the payment code can read: the visibility
        # oracle's `cat_works` and the operator's own `app_remote_config` prices.
        with closing(sqlite3.connect(str(self.catalog))) as conn:
            conn.execute("CREATE TABLE cat_works (work_key TEXT,"
                         " is_18_plus INTEGER DEFAULT 0)")
            conn.execute("INSERT INTO cat_works VALUES"
                         " ('movie:in:1000:sample katmoviehd title', 0)")
            conn.commit()
            admin_panel._ensure_monetization(conn)
            conn.commit()
        self.conn = accounts.connect(self.state)        # installs the schema
        self.addCleanup(self.conn.close)
        self.key = accounts.new_sync_key()
        self.account_id = accounts.create_account(self.conn, key=self.key)["account_id"]

    # ── ledger helpers ───────────────────────────────────────────────────
    def file(self, account_id=None):
        """The stored ledger row, as the database sees it."""
        row = self.conn.execute(
            "SELECT id, account_id, plan, amount_pkr, method, tid, status,"
            " submitted_at, reviewed_at, reviewer_note FROM payment_transactions"
            " WHERE id = ?", (account_id,)).fetchone()
        self.assertIsNotNone(row)
        self.conn.commit()
        return row

    def set_vip(self, until, account_id=None):
        self.conn.execute("UPDATE user_accounts SET vip_until = ? WHERE id = ?",
                          (float(until), account_id or self.account_id))
        self.conn.commit()

    def vip(self, account_id=None):
        return float(self.conn.execute(
            "SELECT vip_until FROM user_accounts WHERE id = ?",
            (account_id or self.account_id,)).fetchone()[0])

    def audit_rows(self, payment_id):
        return self.conn.execute(
            "SELECT payment_id, action, reviewer, prior_vip_until, new_vip_until"
            " FROM payment_review_audit WHERE payment_id = ? ORDER BY id",
            (payment_id,)).fetchall()

    def save_price(self, plan_column, value):
        with admin_panel._session(self.catalog) as conn:
            saved, rejected = admin_panel._save_monetization(
                conn, {plan_column: value})
        self.assertIsNone(rejected, saved)

    def file_claim(self, plan="vip_monthly", method="jazzcash", tid=JAZZ_TID,
                   now=NOW, **extra):
        return payments.submit_payment(self.conn, self.account_id, plan=plan,
                                       method=method, tid=tid,
                                       catalog_path=self.catalog, now=now, **extra)

    # ── response helpers ─────────────────────────────────────────────────
    def post(self, path, body=None, headers=None):
        return accounts_api.route_post(path, body or {}, db_path=self.state,
                                       catalog_path=self.catalog, secret=SECRET,
                                       headers={} if headers is None else headers)

    def get(self, path, query=None, headers=None):
        return accounts_api.route_get(path, query or {}, db_path=self.state,
                                      catalog_path=self.catalog, secret=SECRET,
                                      headers={} if headers is None else headers)

    def auth(self):
        return {"Authorization": f"Bearer {self.key}"}

    def payload(self, answered) -> dict:
        self.assertIsNotNone(answered)
        return json.loads(answered[2].decode("utf-8"))

    def status(self, answered) -> int:
        self.assertIsNotNone(answered)
        return answered[0]

    def assert_clean_public_body(self, answered, label, *, forbid_tid=None):
        """No provenance key, no needle, no payment artifact, no account id.

        The rule under test is `redact.py`'s: a public body is a projection, so
        what it must NOT contain is checked by name rather than by trusting the
        emitter to have remembered."""
        _status, _type, raw = answered
        text = raw.decode("utf-8")
        payload = json.loads(text)
        offenders = redact.is_clean(payload, NEEDLES)
        self.assertEqual(offenders, [], f"{label} leaks provenance: {offenders}")
        for key in redact.PROVENANCE:
            self.assertNotIn(f'"{key}"', text, f"{label} publishes {key}")
        for forbidden in ('"tid"', '"key_hash"', '"account_id"', '"work_key"',
                          '"source_site"', '"sync_key"', "Traceback"):
            self.assertNotIn(forbidden, text, label)
        if forbid_tid is not None:
            self.assertNotIn(forbid_tid, text, f"{label} echoes the transaction id")

    def admin_get(self, path, query=None, peer="127.0.0.1", header=f"Bearer {TOKEN}"):
        return admin_panel.route_get(path, query or {}, db_path=self.catalog,
                                     peer_address=peer, token_header=header,
                                     state_db_path=self.state)

    def admin_post(self, path, body, peer="127.0.0.1", header=f"Bearer {TOKEN}"):
        return admin_panel.route_post(path, {}, db_path=self.catalog,
                                      peer_address=peer, token_header=header,
                                      body=body, state_db_path=self.state)


class Schema(Fixture):
    def test_the_ledger_is_created_by_the_accounts_init_path(self):
        """`accounts.ensure_schema` is the one migration path in this project, so
        the payment tables must arrive through it and through nothing else."""
        names = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("payment_transactions", names)
        self.assertIn("payment_review_audit", names)

    def test_the_payment_transactions_columns_are_exactly_the_spec(self):
        columns = [row[1] for row in self.conn.execute(
            "PRAGMA table_info(payment_transactions)")]
        self.assertEqual(columns, ["id", "account_id", "plan", "amount_pkr",
                                   "method", "tid", "status", "submitted_at",
                                   "reviewed_at", "reviewer_note"])
        defaults = {row[1]: row[4] for row in self.conn.execute(
            "PRAGMA table_info(payment_transactions)")}
        self.assertEqual(str(defaults["status"]).strip("'" + chr(34) + '"'), "pending")

    def test_the_operator_queue_index_exists(self):
        sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND name = 'idx_user_payment_status'").fetchone()[0]
        self.assertIn("status", sql)
        self.assertIn("submitted_at", sql)

    def test_the_rate_limit_index_exists(self):
        sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND name = 'idx_user_payment_account'").fetchone()[0]
        self.assertIn("account_id", sql)

    def test_an_older_state_file_gains_the_ledger_on_next_open(self):
        """A deployment whose `user_state.db` predates this release must not be
        one `ALTER TABLE` away from a 500 on the operator page."""
        older = Path(self.tmp.name) / "older.db"
        legacy = accounts.DDL.split("CREATE TABLE IF NOT EXISTS payment_transactions")[0]
        with closing(sqlite3.connect(str(older))) as conn:
            conn.executescript(legacy)
            conn.execute("INSERT INTO user_accounts(key_hash, created_at)"
                         " VALUES('sha256:old', 1.0)")
            conn.commit()
        with closing(accounts.connect(older)) as conn:
            added = accounts.ensure_schema(conn)
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                " AND name = 'payment_transactions'").fetchone())
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM user_accounts"
                                          ).fetchone()[0], 1,
                             "a migration that loses an account is not a migration")
            self.assertEqual(added["added_columns"], [])

    def test_the_schema_version_is_untouched_by_an_additive_table(self):
        self.assertEqual(accounts.schema_version(self.conn), accounts.SCHEMA_VERSION)


class PlanAndPrice(Fixture):
    def test_an_unknown_plan_is_refused(self):
        for plan in ("vip_forever", "", "MONTHLY", None, "v1p_monthly",
                     "amount", "vip_monthly;drop"):
            with self.subTest(plan=plan):
                with self.assertRaises(payments.InvalidPayment):
                    self.file_claim(plan=plan)

    def test_the_stored_amount_is_the_servers_price_not_the_callers(self):
        """There is no `amount` parameter on the submit path at all: the only way
        a caller can name a price is by naming a plan."""
        import inspect
        parameters = inspect.signature(payments.submit_payment).parameters
        self.assertFalse([name for name in parameters if "amount" in name],
                         parameters)
        filed = self.file_claim(plan="vip_yearly")
        self.assertEqual(filed["amount_pkr"], 1500)
        row = self.file(filed["payment_id"])
        self.assertEqual(int(row["amount_pkr"]), 1500)
        self.assertEqual(row["plan"], "vip_yearly")

    def test_the_operator_saved_price_wins(self):
        self.save_price("vip_monthly_pkr", 350)
        self.assertEqual(payments.price_for("vip_monthly", self.catalog), 350)
        filed = self.file_claim()
        self.assertEqual(filed["amount_pkr"], 350)

    def test_a_zero_price_refuses_rather_than_selling_vip_for_free(self):
        self.save_price("vip_monthly_pkr", 0)
        with self.assertRaises(payments.PaymentError):
            self.file_claim()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM payment_transactions").fetchone()[0], 0)

    def test_an_unreadable_or_absent_catalog_falls_back_to_the_documented_price(self):
        # 250 is `MONETIZATION_AND_FLEET_PLAN.md:46` ("Monthly VIP: ₨ 250"), the
        # authoritative price per the owner's 2026-10-29 ruling; the earlier 200 was
        # a defect, not a second source. If this ever reads 200 again, a code default
        # drifted — fix the default, do not "correct" this assertion back to 200.
        self.assertEqual(payments.price_for("vip_monthly", None), 250,
                         "the never-configured monthly fallback must match the plan doc")
        self.assertEqual(payments.price_for("vip_monthly",
                                            Path(self.tmp.name) / "nope.db"), 250)
        self.assertEqual(payments.price_for("vip_yearly", self.state), 1500)

    def test_only_the_documented_plans_are_sellable(self):
        self.assertEqual(payments.plan_names(), ("vip_monthly", "vip_yearly"))
        self.assertEqual(payments.plan_days("vip_monthly"), 30)
        self.assertEqual(payments.plan_days("vip_yearly"), 365)
        self.assertEqual(payments.plan_days("vip_decade"), 0)


class TidShape(Fixture):
    def test_each_method_gets_its_own_shape(self):
        cases = (("jazzcash", JAZZ_TID), ("jazzcash", "1234567890"),
                 ("easypaisa", EASY_TID), ("easypaisa", "1234567890"),
                 ("raast", RAAST_TID), ("raast", "abcdefghijkl234567"))
        for index, (method, tid) in enumerate(cases):
            with self.subTest(method=method, tid=tid):
                # each case steps past the 5-minute window, or the rate limiter
                # (tested on its own below) would answer before the shape check
                filed = self.file_claim(method=method, tid=tid,
                                        now=NOW + index * 400)
                row = self.file(filed["payment_id"])
                self.assertEqual(row["tid"], tid)
                self.assertEqual(row["status"], "pending")

    def test_a_tid_that_is_not_a_tid_is_refused(self):
        bad = [("jazzcash", "12345"), ("jazzcash", "12345678901"),
               ("jazzcash", "982314567a"), ("jazzcash", ""),
               ("jazzcash", "9823 1456 71"), ("jazzcash", "https://x.io/1234567890"),
               ("easypaisa", "123456789"), ("easypaisa", "abc"),
               ("raast", "short1234"), ("raast", "RAST-2024-abcd"),
               ("raast", "x" * 400)]
        for method, tid in bad:
            with self.subTest(method=method, tid=tid[:20]):
                with self.assertRaises(payments.InvalidPayment):
                    self.file_claim(method=method, tid=tid)

    def test_an_unknown_method_is_refused(self):
        for method in ("nayapay", "till_id", "bank", "", None, "JazzCash!"):
            with self.subTest(method=method):
                with self.assertRaises(payments.InvalidPayment):
                    self.file_claim(method=method)

    def test_the_method_is_case_and_space_insensitive_but_nothing_else(self):
        filed = self.file_claim(method="  JAZZCASH ", tid=JAZZ_TID)
        self.assertEqual(self.file(filed["payment_id"])["method"], "jazzcash")


class RateLimit(Fixture):
    def test_the_second_submit_inside_five_minutes_is_blocked(self):
        first = self.file_claim(now=NOW)
        with self.assertRaises(payments.PaymentRateLimited) as caught:
            self.file_claim(now=NOW + payments.PAYMENT_MIN_INTERVAL_SECONDS - 1)
        self.assertGreaterEqual(caught.exception.retry_after, 1)
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM payment_transactions").fetchone()[0], 1)
        self.assertEqual(first["status"], "pending")

    def test_a_submit_after_the_window_is_allowed(self):
        self.file_claim(now=NOW)
        again = self.file_claim(method="easypaisa", tid=EASY_TID,
                                now=NOW + payments.PAYMENT_MIN_INTERVAL_SECONDS + 1)
        self.assertEqual(again["payment_id"], 2)

    def test_the_window_is_per_account(self):
        self.file_claim(now=NOW)
        other = accounts.create_account(self.conn, key=accounts.new_sync_key())
        fresh = payments.submit_payment(self.conn, other["account_id"],
                                        plan="vip_yearly", method="jazzcash",
                                        tid="1111111111", catalog_path=self.catalog,
                                        now=NOW + 1)
        self.assertEqual(fresh["amount_pkr"], 1500)

    def test_a_closed_row_does_not_block_a_new_claim(self):
        """The queue is a work list, and a payer whose claim was rejected must be
        able to try again once the window has passed."""
        filed = self.file_claim(now=NOW)
        payments.reject_payment(self.conn, filed["payment_id"], now=NOW + 60)
        again = self.file_claim(now=NOW + payments.PAYMENT_MIN_INTERVAL_SECONDS + 1)
        self.assertEqual(again["status"], "pending")


class Approval(Fixture):
    def test_approve_credits_the_plan_and_closes_the_row(self):
        filed = self.file_claim()
        result = payments.approve_payment(self.conn, filed["payment_id"],
                                          reviewer="dao", now=NOW)
        self.assertTrue(result["changed"])
        self.assertEqual(result["days"], 30)
        self.assertAlmostEqual(result["vip_until"], NOW + 30 * DAY, delta=2)
        self.assertEqual(self.vip(), result["vip_until"])
        self.assertEqual(self.file(filed["payment_id"])["status"], "approved")

    def test_approve_extends_an_existing_future_vip_until(self):
        """A renewal bought on day 20 of a 30-day term must land on day 50, not
        restart at today — the payer already paid for the days they have left."""
        remaining = 12 * DAY
        self.set_vip(NOW + remaining)
        filed = self.file_claim()
        result = payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        self.assertEqual(result["prior_vip_until"], NOW + remaining)
        self.assertAlmostEqual(result["vip_until"],
                               NOW + remaining + 30 * DAY, delta=2)
        self.assertGreater(self.vip(), NOW + 41 * DAY)

    def test_approve_of_an_expired_term_starts_from_now(self):
        self.set_vip(NOW - 100 * DAY)
        filed = self.file_claim(plan="vip_yearly", method="raast", tid=RAAST_TID)
        result = payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        self.assertAlmostEqual(result["vip_until"], NOW + 365 * DAY, delta=2)

    def test_double_approve_does_not_double_credit(self):
        filed = self.file_claim()
        first = payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        second = payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["status"], "approved")
        self.assertEqual(self.vip(), first["vip_until"])
        self.assertEqual(len(self.audit_rows(filed["payment_id"])), 1,
                         "a replay must not write a second credit's audit row")

    def test_a_replayed_approve_from_a_later_time_still_credits_once(self):
        filed = self.file_claim()
        payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        later = payments.approve_payment(self.conn, filed["payment_id"],
                                         now=NOW + 3 * DAY)
        self.assertFalse(later["changed"])
        self.assertAlmostEqual(self.vip(), NOW + 30 * DAY, delta=2)

    def test_reject_leaves_vip_until_untouched(self):
        existing = NOW + 7 * DAY
        self.set_vip(existing)
        filed = self.file_claim()
        result = payments.reject_payment(self.conn, filed["payment_id"],
                                         reviewer="dao", note="wrong amount",
                                         now=NOW)
        self.assertTrue(result["changed"])
        self.assertEqual(self.vip(), existing)
        self.assertEqual(result["days"], 0)
        row = self.file(filed["payment_id"])
        self.assertEqual(row["status"], "rejected")
        self.assertEqual(row["reviewer_note"], "wrong amount")

    def test_reject_of_a_never_vip_account_still_leaves_zero(self):
        filed = self.file_claim()
        payments.reject_payment(self.conn, filed["payment_id"], now=NOW)
        self.assertEqual(self.vip(), 0.0)

    def test_approve_writes_one_audit_row_and_reject_another(self):
        approved = self.file_claim()
        payments.approve_payment(self.conn, approved["payment_id"],
                                 reviewer="dao", now=NOW)
        audit = self.audit_rows(approved["payment_id"])
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "approved")
        self.assertEqual(audit[0]["reviewer"], "dao")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM payment_review_audit").fetchone()[0], 1)
        self.set_vip(0)
        rejected = self.file_claim(method="easypaisa", tid=EASY_TID,
                                   now=NOW + 400)
        payments.reject_payment(self.conn, rejected["payment_id"],
                                reviewer="hamza", now=NOW + 401)
        self.assertEqual(self.audit_rows(rejected["payment_id"])[0]["action"],
                         "rejected")

    def test_an_audit_row_holds_no_transaction_id_and_no_key_hash(self):
        filed = self.file_claim()
        payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        blob = "".join(str(value) for row in self.conn.execute(
            "SELECT * FROM payment_review_audit") for value in tuple(row))
        self.assertNotIn(JAZZ_TID, blob)
        self.assertNotIn("sha256:", blob)

    def test_approving_a_payment_for_a_revoked_account_is_refused(self):
        """A credit nobody can ever read is a lie in the audit trail, so the row
        stays pending for the operator to reject instead."""
        filed = self.file_claim()
        self.conn.execute("UPDATE user_accounts SET revoked_at = ? WHERE id = ?",
                          (NOW, self.account_id))
        self.conn.commit()
        with self.assertRaises(payments.PaymentNotFound):
            payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        self.assertEqual(self.file(filed["payment_id"])["status"], "pending")
        self.assertEqual(self.vip(), 0.0)

    def test_a_reject_of_a_revoked_account_still_closes_the_row(self):
        filed = self.file_claim()
        self.conn.execute("UPDATE user_accounts SET revoked_at = ? WHERE id = ?",
                          (NOW, self.account_id))
        self.conn.commit()
        result = payments.reject_payment(self.conn, filed["payment_id"], now=NOW)
        self.assertTrue(result["changed"])

    def test_an_unknown_or_silly_payment_id_is_refused_without_writing(self):
        for identifier in (0, -1, "abc", None, 999999):
            with self.subTest(identifier=identifier):
                with self.assertRaises((payments.InvalidPayment,
                                        payments.PaymentNotFound)):
                    payments.approve_payment(self.conn, identifier, now=NOW)

    def test_two_approvals_racing_on_open_connections_credit_once(self):
        """Two operator connections, one row: the second writer either waits on
        the IMMEDIATE lock or loses the `status = 'pending'` guard."""
        filed = self.file_claim()
        results = []
        for _ in range(2):
            with closing(accounts.connect(self.state)) as other:
                results.append(payments.approve_payment(other, filed["payment_id"],
                                                        now=NOW))
        self.assertEqual(sorted(r["changed"] for r in results), [False, True])
        self.assertEqual(len(self.audit_rows(filed["payment_id"])), 1)
        self.assertAlmostEqual(self.vip(), NOW + 30 * DAY, delta=2)


class Entitlement(Fixture):
    def test_entitlement_reports_pending(self):
        self.file_claim()
        earned = payments.entitlement(self.conn, self.key, now=NOW)
        self.assertEqual(earned, {"vip": False, "vip_until": 0.0, "pending": True})

    def test_entitlement_without_a_claim_is_not_pending(self):
        earned = payments.entitlement(self.conn, self.key, now=NOW)
        self.assertFalse(earned["pending"])
        self.assertFalse(earned["vip"])

    def test_entitlement_is_vip_after_approval_and_no_longer_pending(self):
        filed = self.file_claim()
        payments.approve_payment(self.conn, filed["payment_id"], now=NOW)
        earned = payments.entitlement(self.conn, self.key, now=NOW + 1)
        self.assertTrue(earned["vip"])
        self.assertFalse(earned["pending"])
        self.assertAlmostEqual(earned["vip_until"], NOW + 30 * DAY, delta=2)

    def test_entitlement_is_expired_membership_with_a_stale_pending_claim(self):
        """`vip` is `vip_until > now`, and `pending` is a claim nobody has closed.
        Both true at once is the honest state after a late renewal."""
        self.set_vip(NOW - DAY)
        self.file_claim()
        earned = payments.entitlement(self.conn, self.key, now=NOW)
        self.assertEqual(earned, {"vip": False, "vip_until": NOW - DAY,
                                 "pending": True})

    def test_reject_clears_pending(self):
        filed = self.file_claim()
        payments.reject_payment(self.conn, filed["payment_id"], now=NOW)
        self.assertFalse(payments.entitlement(self.conn, self.key,
                                             now=NOW)["pending"])

    def test_the_ledger_outlives_a_pruned_account(self):
        """`payment_transactions.account_id` deliberately has no CASCADE: a money
        ledger that vanishes when an idle account is pruned is not auditable."""
        filed = self.file_claim(now=NOW)
        accounts.prune_accounts(self.conn, idle_days=0, now=NOW + 10 * DAY)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM payment_transactions WHERE id = ?",
            (filed["payment_id"],)).fetchone()[0], 1)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM user_accounts WHERE id = ?",
            (self.account_id,)).fetchone()[0], 0)

    def test_account_hint_is_a_stable_one_way_label(self):
        row = self.conn.execute("SELECT key_hash FROM user_accounts WHERE id = ?",
                                (self.account_id,)).fetchone()
        hint = payments.account_hint(row["key_hash"])
        self.assertEqual(hint, payments.account_hint(row["key_hash"]))
        self.assertTrue(hint.startswith("acct-"))
        self.assertEqual(len(hint), len("acct-") + 8)
        self.assertNotIn(row["key_hash"], hint)
        self.assertNotIn("sha256", hint)
        self.assertEqual(payments.account_hint(None), "")


class AccountEdge(Fixture):
    """`POST /api/v2/account/payment` and `GET /api/v2/account/entitlement`."""

    def submit(self, body, headers=None):
        return self.post(f"{P}/payment", body, headers if headers is not None
                         else self.auth())

    def good(self, **extra):
        body = {"plan": "vip_monthly", "method": "jazzcash", "tid": JAZZ_TID}
        body.update(extra)
        return body

    def test_a_payment_needs_a_bearer_key(self):
        refused = self.submit(self.good(), headers={})
        self.assertEqual(self.status(refused), 401)
        self.assertEqual(self.payload(refused)["code"], "unauthorised")

    def test_a_payment_needs_a_real_account(self):
        refused = self.post(f"{P}/payment", self.good(),
                            headers={"Authorization": "Bearer " + "z" * 20})
        self.assertEqual(self.status(refused), 404)

    def test_a_filed_payment_answers_201_with_a_receipt_and_no_tid(self):
        filed = self.submit(self.good())
        self.assertEqual(self.status(filed), 201)
        receipt = self.payload(filed)["payment"]
        self.assertEqual(set(receipt), {"payment_id", "status", "plan",
                                        "amount_pkr", "method", "submitted_at"})
        self.assertEqual(receipt["status"], "pending")
        # 250, not 200: the fixture's `app_remote_config` row is created by
        # `admin_panel._ensure_monetization`, whose `vip_monthly_pkr` column default is
        # 250 — the owner's authoritative Monthly VIP (`MONETIZATION_AND_FLEET_PLAN.md:46`,
        # ruled 2026-10-29). The server prices the claim from that row, so the receipt is
        # 250. This is the same number the never-configured fallback test pins; if it
        # reads 200 again the default drifted — fix the default, not this assertion.
        self.assertEqual(receipt["amount_pkr"], 250)
        self.assert_clean_public_body(filed, "payment receipt", forbid_tid=JAZZ_TID)

    def test_the_edge_refuses_a_client_supplied_amount(self):
        for body in (self.good(amount_pkr=1), self.good(amount=1),
                     self.good(days=3650), self.good(vip_until=NOW + 10 * DAY)):
            with self.subTest(keys=sorted(body)):
                refused = self.submit(body)
                self.assertEqual(self.status(refused), 400)
                self.assertEqual(self.payload(refused)["code"], "invalid_params")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM payment_transactions").fetchone()[0], 0)

    def test_an_unknown_plan_is_a_clean_400(self):
        refused = self.submit(self.good(plan="vip_forever"))
        self.assertEqual(self.status(refused), 400)
        _status, content_type, raw = refused
        self.assertEqual(content_type, accounts_api.PROBLEM)
        text = raw.decode("utf-8")
        self.assertNotIn("Traceback", text)
        self.assertNotIn(".py", text)
        self.assertNotIn("vip_forever", text, "the refusal echoed the input")

    def test_a_bad_tid_is_a_clean_400(self):
        refused = self.submit(self.good(tid="not-a-tid"))
        self.assertEqual(self.status(refused), 400)
        self.assertEqual(self.payload(refused)["code"], "invalid_params")

    def test_a_missing_field_is_a_400_not_a_500(self):
        for body in ({}, {"plan": "vip_monthly"}, {"tid": JAZZ_TID},
                     {"plan": 7, "method": 7, "tid": 7}):
            with self.subTest(body=body):
                refused = self.submit(body)
                self.assertIn(self.status(refused), (400, 404))
                self.assertLess(self.status(refused), 500)

    def test_a_non_object_body_is_refused(self):
        refused = self.post(f"{P}/payment", None, headers=self.auth())
        self.assertEqual(self.status(refused), 400)

    def test_the_rate_limit_is_enforced_at_the_edge_with_retry_after(self):
        first = self.submit(self.good())
        self.assertEqual(self.status(first), 201)
        again = self.submit(self.good(method="easypaisa", tid=EASY_TID))
        self.assertEqual(self.status(again), 429)
        problem = self.payload(again)
        self.assertEqual(problem["code"], "rate_limited")
        self.assertGreaterEqual(problem["retry_after"], 1)
        self.assertLessEqual(problem["retry_after"], 300)

    def test_entitlement_needs_a_key(self):
        refused = self.get(f"{P}/entitlement", headers={})
        self.assertEqual(self.status(refused), 401)

    def test_entitlement_shape_and_pending_flag(self):
        earned = self.get(f"{P}/entitlement", headers=self.auth())
        self.assertEqual(self.status(earned), 200)
        self.assertEqual(set(self.payload(earned)["entitlement"]),
                         {"vip", "vip_until", "pending"})
        self.assertFalse(self.payload(earned)["entitlement"]["pending"])
        self.submit(self.good())
        after = self.payload(self.get(f"{P}/entitlement", headers=self.auth()))
        self.assertTrue(after["entitlement"]["pending"])
        self.assertFalse(after["entitlement"]["vip"])
        self.assert_clean_public_body(earned, "entitlement", forbid_tid=JAZZ_TID)

    def test_the_projection_is_what_publishes_the_entitlement(self):
        """Deny-by-default, in the schema: a key this server invents later cannot
        reach a client until it is named in `redact.VIEWS`."""
        for view in ("account_entitlement", "account_payment"):
            self.assertIn(view, redact.VIEWS, view)
        self.assertEqual(redact.VIEWS["account_entitlement"],
                         frozenset({"vip", "vip_until", "pending"}))
        self.assertNotIn("tid", redact.VIEWS["account_payment"])
        self.assertNotEqual(redact.project({"vip": True, "vip_until": 1.0,
                                            "pending": False, "source_site": "x"},
                                           "account_entitlement").get("source_site"),
                            "x")

    def test_an_unknown_account_route_is_still_404(self):
        self.assertEqual(self.status(self.get(f"{P}/payments",
                                             headers=self.auth())), 404)
        self.assertEqual(self.status(self.post(f"{P}/payments", self.good(),
                                               headers=self.auth())), 404)

    def test_no_account_body_ever_names_the_operator_or_a_payment_artifact(self):
        """The account surface's whole vocabulary about a payment: an id, a state
        and a price."""
        filed = self.submit(self.good())
        earned = self.get(f"{P}/entitlement", headers=self.auth())
        for answered, label in ((filed, "receipt"), (earned, "entitlement")):
            text = answered[2].decode("utf-8")
            for needle in (JAZZ_TID, self.key, "sha256:", "csrf", "reviewer",
                           "vip_until" if label == "receipt" else "acct-"):
                self.assertNotIn(needle, text, f"{label} leaks {needle}")


class OperatorPanel(Fixture):
    def setUp(self):
        super().setUp()
        self.filed = self.file_claim()

    def queue_page(self, peer="127.0.0.1", header=f"Bearer {TOKEN}"):
        return admin_panel.route_get(admin_panel.PAYMENTS_PATH, {},
                                     db_path=self.catalog, peer_address=peer,
                                     token_header=header, state_db_path=self.state)

    def csrf(self, action, payment_id):
        return admin_panel._csrf_token(action, payment_id)

    def approve(self, payment_id, token=None, *, peer="127.0.0.1",
                header=f"Bearer {TOKEN}", **extra):
        body = {"payment_id": str(payment_id),
                "csrf": self.csrf("approved", payment_id) if token is None else token}
        body.update(extra)
        return self.admin_post(admin_panel.APPROVE_PAYMENT_PATH, body,
                               peer=peer, header=header)

    def reject(self, payment_id, token=None, *, peer="127.0.0.1",
               header=f"Bearer {TOKEN}", **extra):
        body = {"payment_id": str(payment_id),
                "csrf": self.csrf("rejected", payment_id) if token is None else token}
        body.update(extra)
        return self.admin_post(admin_panel.REJECT_PAYMENT_PATH, body,
                               peer=peer, header=header)

    # ── the gate ─────────────────────────────────────────────────────────
    def test_a_remote_peer_never_sees_the_queue(self):
        refused = self.queue_page(peer="203.0.113.9")
        self.assertEqual(refused[0], 403)
        self.assertNotIn(JAZZ_TID, refused[2].decode())

    def test_a_missing_and_a_wrong_token_answer_identically(self):
        missing = self.queue_page(header="")
        wrong = self.queue_page(header="Bearer nope")
        self.assertEqual(missing[0], 401)
        self.assertEqual(wrong[0], 401)
        # A gate refusal carries a per-call request id, so compare everything but
        # that: nothing else about the body may tell the two apart.
        strip = lambda answered: json.dumps(
            {k: v for k, v in self.payload(answered).items() if k != "request_id"},
            sort_keys=True)
        self.assertEqual(strip(missing), strip(wrong))
        self.assertEqual(missing[1], wrong[1])
        self.assertNotIn(JAZZ_TID, missing[2].decode())

    def test_a_payment_action_from_a_remote_peer_is_refused_before_the_ledger(self):
        refused = self.approve(self.filed["payment_id"], peer="10.0.0.5")
        self.assertEqual(refused[0], 403)
        self.assertEqual(self.vip(), 0.0)

    def test_the_queue_is_not_mounted_on_the_public_port(self):
        """`viewer.OPERATOR_ONLY_PREFIXES` is the mount's answer; this asserts the
        prefix still covers the new page rather than trusting prose."""
        import viewer
        self.assertTrue(viewer.OPERATOR_ONLY_PREFIXES)
        self.assertTrue(admin_panel.ADMIN_PREFIX in viewer.OPERATOR_ONLY_PREFIXES
                        or admin_panel.PAYMENTS_PATH.startswith(
                            viewer.OPERATOR_ONLY_PREFIXES))

    # ── the page ─────────────────────────────────────────────────────────
    def test_the_page_lists_the_claim_with_both_actions(self):
        answered = self.queue_page()
        self.assertEqual(answered[0], 200)
        self.assertEqual(answered[1], admin_panel.CONTENT_HTML)
        text = answered[2].decode()
        self.assertIn(JAZZ_TID, text, "an operator cannot check a TID they cannot see")
        # The page's server price list must show the authoritative monthly price —
        # 250, per `MONETIZATION_AND_FLEET_PLAN.md:46` and the owner's 2026-10-29
        # ruling. It used to read 200 here; that literal was the old `PLAN_DEFAULTS`
        # value leaking through, so it is asserted at 250 now, not removed.
        self.assertIn("250", text)
        self.assertIn("vip_monthly", text)
        self.assertIn(payments.account_hint(self.conn.execute(
            "SELECT key_hash FROM user_accounts WHERE id = ?",
            (self.account_id,)).fetchone()[0]), text)
        self.assertIn("Approve", text)
        self.assertIn("Reject", text)
        self.assertIn(admin_panel.APPROVE_PAYMENT_PATH, text)

    def test_the_page_carries_a_csrf_token_per_button(self):
        text = self.queue_page()[2].decode()
        tokens = re.findall(r'name="csrf" value="([0-9a-f]+)"', text)
        self.assertEqual(len(tokens), 2, "one approve and one reject token")
        self.assertIn(self.csrf("approved", self.filed["payment_id"]), tokens)
        self.assertIn(self.csrf("rejected", self.filed["payment_id"]), tokens)

    def test_the_page_is_provenance_clean(self):
        answered = self.queue_page()
        offenders = admin_panel._provenance_offenders(answered[2].decode("utf-8"))
        self.assertEqual(offenders, [])

    def test_the_json_screen_lists_pending_rows_and_no_hash(self):
        answered = self.admin_get("/admin/api/payments")
        self.assertEqual(answered[0], 200)
        data = self.payload(answered)
        self.assertTrue(data["available"])
        self.assertEqual(data["pending_count"], 1)
        self.assertEqual(data["pending"][0]["tid"], JAZZ_TID)
        self.assertNotIn("key_hash", json.dumps(data))
        self.assertNotIn("sha256:", json.dumps(data))
        self.assertEqual(admin_panel._provenance_offenders(
            answered[2].decode("utf-8")), [])

    def test_the_queue_answers_even_with_no_projection_and_no_claims(self):
        empty = admin_panel.route_get(admin_panel.PAYMENTS_PATH, {},
                                      db_path=Path(self.tmp.name) / "bare.db",
                                      peer_address="127.0.0.1",
                                      token_header=f"Bearer {TOKEN}",
                                      state_db_path=Path(self.tmp.name) / "bare.db")
        self.assertEqual(empty[0], 200)
        self.assertIn("Payment queue", empty[2].decode())

    # ── the writes ───────────────────────────────────────────────────────
    def test_approve_credits_once_and_the_second_click_credits_nobody(self):
        first = self.approve(self.filed["payment_id"])
        self.assertEqual(first[0], 200)
        credited = self.vip()
        self.assertTrue(self.payload(first)["review"]["changed"])
        again = self.approve(self.filed["payment_id"])
        self.assertEqual(again[0], 200)
        self.assertFalse(self.payload(again)["review"]["changed"])
        self.assertEqual(self.vip(), credited)
        self.assertEqual(len(self.audit_rows(self.filed["payment_id"])), 1)

    def test_approve_then_reject_credits_the_same_once(self):
        self.approve(self.filed["payment_id"])
        credited = self.vip()
        second = self.reject(self.filed["payment_id"])
        self.assertEqual(second[0], 200)
        self.assertFalse(self.payload(second)["review"]["changed"])
        self.assertEqual(self.vip(), credited)

    def test_a_missing_csrf_token_is_refused_and_credits_nothing(self):
        refused = self.approve(self.filed["payment_id"], token="")
        self.assertEqual(refused[0], 403)
        self.assertEqual(self.payload(refused)["code"], "forbidden")
        self.assertEqual(self.vip(), 0.0)
        self.assertEqual(self.file(self.filed["payment_id"])["status"], "pending")

    def test_a_forged_or_recycled_token_is_refused(self):
        other = self.file_claim(method="easypaisa", tid=EASY_TID, now=NOW + 400)
        stolen = self.csrf("approved", other["payment_id"])
        refused = self.approve(self.filed["payment_id"], token=stolen)
        self.assertEqual(refused[0], 403)
        self.assertEqual(self.vip(), 0.0)
        # and a reject token cannot approve
        wrong_action = self.approve(self.filed["payment_id"],
                                   token=self.csrf("rejected", self.filed["payment_id"]))
        self.assertEqual(wrong_action[0], 403)

    def test_a_token_this_process_did_not_mint_is_refused(self):
        refused = self.approve(self.filed["payment_id"],
                              token="0" * admin_panel._CSRF_CHARS)
        self.assertEqual(refused[0], 403)

    def test_reject_leaves_vip_until_untouched(self):
        existing = NOW + 5 * DAY
        self.set_vip(existing)
        answered = self.reject(self.filed["payment_id"], note="no such amount")
        self.assertEqual(answered[0], 200)
        self.assertTrue(self.payload(answered)["review"]["changed"])
        self.assertEqual(self.vip(), existing)
        self.assertEqual(self.file(self.filed["payment_id"])["status"], "rejected")

    def test_a_form_post_answers_with_the_refreshed_page_not_json(self):
        answered = self.approve(self.filed["payment_id"],
                                **{"_form": "1", "reviewer": "dao"})
        self.assertEqual(answered[0], 200)
        self.assertEqual(answered[1], admin_panel.CONTENT_HTML)
        text = answered[2].decode()
        self.assertIn("approved", text)
        # the claim left the pending list; it still appears in "Recently
        # reviewed", which is the point of keeping the queue auditable
        self.assertIn('<h2>Pending</h2><div class="empty">nothing to show</div>',
                      text, "a closed claim leaves the pending list")

    def test_a_replayed_form_post_says_no_second_credit_was_made(self):
        self.approve(self.filed["payment_id"], _form="1")
        again = self.approve(self.filed["payment_id"], _form="1")
        self.assertIn("no second credit", again[2].decode())

    def test_the_json_receipt_carries_no_transaction_id(self):
        text = self.approve(self.filed["payment_id"])[2].decode()
        self.assertNotIn(JAZZ_TID, text)
        self.assertNotIn("tid", text)

    def test_an_unknown_review_key_is_refused(self):
        body = {"payment_id": "1", "csrf": self.csrf("approved", 1),
                "amount_pkr": 0}
        refused = self.admin_post(admin_panel.APPROVE_PAYMENT_PATH, body)
        self.assertEqual(refused[0], 400)

    def test_a_non_numeric_or_absent_payment_id_is_400(self):
        for bad in ("abc", "0", "-3", ""):
            with self.subTest(bad=bad):
                refused = self.admin_post(admin_panel.APPROVE_PAYMENT_PATH,
                                          {"payment_id": bad,
                                           "csrf": self.csrf("approved", bad)})
                self.assertEqual(refused[0], 400)

    def test_a_claim_that_does_not_exist_is_404(self):
        refused = self.approve(424242)
        self.assertEqual(refused[0], 404)

    def test_a_non_dict_body_is_refused(self):
        refused = self.admin_post(admin_panel.APPROVE_PAYMENT_PATH, ["payment_id"])
        self.assertEqual(refused[0], 400)

    def test_only_the_documented_actions_consume_a_body(self):
        self.assertTrue(admin_panel.takes_body(admin_panel.APPROVE_PAYMENT_PATH))
        self.assertTrue(admin_panel.takes_body(admin_panel.REJECT_PAYMENT_PATH))
        self.assertTrue(admin_panel.takes_body(admin_panel.SAVE_MONETIZATION_PATH))
        self.assertTrue(admin_panel.takes_body(admin_panel.RUN_SCRAPER_PATH))
        self.assertFalse(admin_panel.takes_body("/admin/api/links/1/evidence"))
        self.assertFalse(admin_panel.takes_body("/admin/payments"))

    def test_the_pages_form_encoding_round_trips_through_the_helpers(self):
        import urllib.parse
        self.assertTrue(admin_panel.form_encoded(
            "application/x-www-form-urlencoded; charset=UTF-8"))
        self.assertFalse(admin_panel.form_encoded("application/json"))
        raw = urllib.parse.urlencode({"payment_id": "7", "csrf": "abc",
                                      "_form": "1", "note": "no sms"}).encode()
        self.assertEqual(admin_panel.parse_form_body(raw),
                         {"payment_id": "7", "csrf": "abc", "_form": "1",
                          "note": "no sms"})
        self.assertNotIn("payment_id", admin_panel.parse_form_body(b"%%%%"))
        self.assertEqual(admin_panel.parse_form_body(None), {})

    def test_a_review_note_is_stored_but_never_a_credential(self):
        self.reject(self.filed["payment_id"], note="x" * 400)
        note = self.file(self.filed["payment_id"])["reviewer_note"]
        self.assertLessEqual(len(note or ""), admin_panel._MAX_NOTE)

    def test_the_admin_page_links_to_the_queue(self):
        answered = self.admin_get("/admin")
        self.assertEqual(answered[0], 200)
        self.assertIn(admin_panel.PAYMENTS_PATH, answered[2].decode())

    def test_the_operator_surface_refuses_an_unmappable_payment_code(self):
        """§16.4 is a closed vocabulary: a payment error carrying an invented code
        must collapse to a declared one instead of publishing a new string."""
        refused = self.admin_post(admin_panel.APPROVE_PAYMENT_PATH,
                                 {"payment_id": "1", "csrf": "bad"})
        self.assertIn(self.payload(refused)["code"], api_v2.PROBLEM_CODES)


class NoLeakAnywhere(Fixture):
    def test_no_account_surface_body_ever_contains_a_tid(self):
        filed = self.post(f"{P}/payment", {"plan": "vip_monthly",
                                          "method": "jazzcash", "tid": JAZZ_TID},
                         headers=self.auth())
        seen = []
        for path in (P, f"{P}/entitlement", f"{P}/favorites", f"{P}/progress"):
            answered = self.get(path, headers=self.auth())
            if answered is not None:
                seen.append(path)
                self.assertNotIn(JAZZ_TID, answered[2].decode(), path)
        self.assertEqual(len(seen), 4)
        self.assertEqual(self.status(filed), 201)

    def test_the_ledger_keeps_everything_the_edge_does_not_send(self):
        """Redaction is a serialization decision at the edge; the ledger still
        holds the full claim, exactly as the Zero Data Loss rule requires."""
        self.post(f"{P}/payment", {"plan": "vip_monthly", "method": "jazzcash",
                                  "tid": JAZZ_TID}, headers=self.auth())
        row = self.conn.execute(
            "SELECT tid, method, plan, amount_pkr, status FROM payment_transactions"
            " ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["tid"], JAZZ_TID)
        self.assertEqual(row["status"], "pending")

    def test_an_unknown_key_never_reaches_an_account_body(self):
        payload = {"vip": True, "vip_until": 1.0, "pending": False,
                   "final_url": "https://vegamovies.gallery/x",
                   "source_site": "vegamovies", "work_key": "movie:x katmoviehd"}
        projected = redact.project(payload, "account_entitlement")
        self.assertEqual(projected, {"vip": True, "vip_until": 1.0,
                                    "pending": False})
        self.assertEqual(redact.is_clean(projected, NEEDLES), [])

    def test_a_dead_column_stays_dead(self):
        """`payments.payment()` is the internal read; nothing at the edge calls it,
        so an account_id cannot ride out by accident."""
        filed = self.file_claim()
        row = payments.payment(self.conn, filed["payment_id"])
        self.assertIn("account_id", row)
        self.assertNotIn("tid", row, "even the internal read hands out no TID")
        text = self.get(f"{P}/entitlement", headers=self.auth())[2].decode()
        self.assertNotIn("account_id", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
