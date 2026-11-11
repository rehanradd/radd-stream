"""VIP grant must not leave a ledger grant without a grant record.

Two SQLite files cannot share one transaction, so the service uses
a compensating rollback: if the admin record fails, the ledger
grant is undone. These tests prove both the happy path and that
rollback, using mock accounts only.
"""
import unittest

from tests.helpers import make_service


def seed_account(svc, hint="test.user"):
    svc.ledger.execute(
        "INSERT INTO app_accounts (account_hint, tier, vip_until, device_count) VALUES (?,?,?,?)",
        (hint, "free", None, 1))
    svc.ledger.commit()


class TestVipGrant(unittest.TestCase):
    def test_happy_path_grants_and_records(self):
        svc, owner, _auditor = make_service()
        seed_account(svc)
        out = svc.vip_grant(owner, "test.user", {"months": 1, "reason": "test grant"})
        acct = svc.ledger.execute(
            "SELECT * FROM app_accounts WHERE account_hint=?", ("test.user",)).fetchone()
        self.assertEqual(acct["tier"], "vip")
        self.assertEqual(acct["vip_until"], out["vip_until"])
        grant = svc.admin.execute(
            "SELECT * FROM vip_grants WHERE account_hint=?", ("test.user",)).fetchone()
        self.assertIsNotNone(grant)
        self.assertEqual(grant["months"], 1)

    def test_admin_failure_rolls_back_ledger(self):
        svc, owner, _auditor = make_service()
        seed_account(svc)
        # Force the admin record to fail, after the ledger grant.
        svc.admin.execute("DROP TABLE vip_grants")
        svc.admin.commit()
        with self.assertRaises(Exception):
            svc.vip_grant(owner, "test.user", {"months": 1, "reason": "test grant"})
        acct = svc.ledger.execute(
            "SELECT * FROM app_accounts WHERE account_hint=?", ("test.user",)).fetchone()
        self.assertEqual(acct["tier"], "free")
        self.assertIsNone(acct["vip_until"])
        entries = svc.ledger.execute(
            "SELECT * FROM ledger_entries WHERE account_hint=?", ("test.user",)).fetchall()
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
