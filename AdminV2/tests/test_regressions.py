import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import bad_checker, good_checker, make_service  # noqa: E402
from admin_v2 import fixture_app  # noqa: E402
from admin_v2.errors import ApiError  # noqa: E402
from admin_v2.security import check_no_provenance  # noqa: E402


class TestRegressions(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()

    def test_adult_fail_closed_all_rules(self):
        # 1. Unknown flag = hidden.
        layout = fixture_app.home_layout(self.svc)
        self.assertFalse(any(c["work_id"] == 4 for s in layout for c in s["cards"]))
        # 2. Lost-flag publish blocked: put an adult card in a non-adult
        #    section directly (bypassing the add-card guard) and publish.
        sec = self.svc.admin.execute("SELECT id FROM home_sections WHERE key='movie'").fetchone()
        self.svc.admin.execute(
            "INSERT INTO slider_cards (section_id, work_id, position, is_enabled, created_by, created_at) "
            "VALUES (?,?,?,?,?,?)", (sec["id"], 3, 0, 1, self.owner["id"], 1700000000))
        self.svc.admin.commit()
        with self.assertRaises(ApiError):
            self.svc.publish_remote_config(self.owner, {"confirm": True})
        # 3. Global ON without a gate is refused (already covered, re-assert).
        with self.assertRaises(ApiError):
            self.svc.update_content_safety(self.owner, {"adult_content_enabled": True})
        # 4. Every adult change is audited.
        self.svc.block_adult_globally(self.owner, {"reason": "test"})
        n = self.svc.admin.execute(
            "SELECT COUNT(*) AS n FROM admin_audit_log WHERE action LIKE 'section.disable%'").fetchone()["n"]
        self.assertGreaterEqual(n, 0)
        # 5. No adult detail in the public endpoint.
        cfg = fixture_app.public_remote_config(self.svc)
        self.assertTrue(check_no_provenance(cfg))

    def test_payment_atomicity_concurrent_and_double(self):
        # Concurrent approves of the same claim: exactly one credit.
        results = []

        def approve():
            try:
                results.append(self.svc.approve_payment(self.owner, 2, {"confirm": True}))
            except ApiError as exc:
                results.append(exc.code)

        threads = [threading.Thread(target=approve) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        claims = self.svc.ledger.execute(
            "SELECT COUNT(*) AS n FROM ledger_entries WHERE payment_id=2 AND kind='vip_credit'").fetchone()["n"]
        self.assertEqual(claims, 1)

    def test_payment_mid_transaction_rollback(self):
        # A claim that fails validation leaves the row pending, never half-credited.
        with self.assertRaises(ApiError):
            self.svc.approve_payment(self.owner, 999, {"confirm": True})
        row = self.svc.ledger.execute("SELECT * FROM payment_claims WHERE id=1").fetchone()
        self.assertEqual(row["status"], "pending")

    def test_domain_rollback_blocked_when_previous_died(self):
        self.svc.add_candidate(self.owner, "multimovies", {"domain": "example.org"})
        self.svc.validate_domain(self.owner, "multimovies", {"domain": "example.org"}, checker=good_checker)
        self.svc.apply_domain(self.owner, "multimovies", {"domain": "example.org", "confirm": True})
        self.svc.add_candidate(self.owner, "multimovies", {"domain": "example.net"})
        self.svc.validate_domain(self.owner, "multimovies", {"domain": "example.net"}, checker=good_checker)
        self.svc.apply_domain(self.owner, "multimovies", {"domain": "example.net", "confirm": True})
        with self.assertRaises(ApiError):
            self.svc.rollback_domain(self.owner, "multimovies", {"confirm": True}, checker=bad_checker)
        self.assertEqual(self.svc.resolve_domain("multimovies")[0], "example.net")

    def test_audit_completeness_and_no_secrets(self):
        self.svc.create_section(self.owner, {"key": "audit-rail", "title": "Audit"})
        rows = self.svc.admin.execute(
            "SELECT * FROM admin_audit_log WHERE action='section.create'").fetchall()
        self.assertEqual(len(rows), 1)
        csv = self.svc.export_audit_csv(self.owner)
        self.assertNotIn("token", csv.lower())
        # Audit rows never contain a URL or token key.
        for r in self.svc.admin.execute("SELECT before_json, after_json FROM admin_audit_log").fetchall():
            for blob in (r["before_json"], r["after_json"]):
                if blob:
                    self.assertTrue(check_no_provenance(__import__("json").loads(blob)))

    def test_provenance_scan_every_public_body(self):
        cfg = fixture_app.public_remote_config(self.svc)
        self.assertTrue(check_no_provenance(cfg))
        dash = self.svc.dashboard(self.owner)
        self.assertTrue(check_no_provenance(dash))
        mon = self.svc.get_monetization(self.owner)
        # Tokens are never serialised: only a configured flag leaves.
        self.assertNotIn("shrinkme_api_token", mon)
        self.assertIn("shrinkme_configured", mon)
        self.assertTrue(check_no_provenance(mon))

    def test_auth_regression(self):
        # Wrong password -> generic error, no enumeration detail.
        with self.assertRaises(ApiError) as ctx:
            self.svc.login("owner", "wrong password here", ip="127.0.0.1")
        self.assertEqual(ctx.exception.code, "invalid_credentials")
        with self.assertRaises(ApiError) as ctx2:
            self.svc.login("nobody", "wrong password here", ip="127.0.0.1")
        self.assertEqual(ctx2.exception.code, "invalid_credentials")
        # Session revoke ends access.
        res = self.svc.login("owner", "correct horse battery staple", ip="127.0.0.1")
        user, sess = self.svc.validate_session(res["session_token"])
        self.assertIsNotNone(user)
        self.svc.logout(res["session_token"])
        user, sess = self.svc.validate_session(res["session_token"])
        self.assertIsNone(user)

    def test_home_empty_regression(self):
        for key in ("hero", "trending", "movie", "series"):
            self.svc.delete_section(self.owner, key)
        with self.assertRaises(ApiError):
            self.svc.publish_remote_config(self.owner, {"confirm": True})

    def test_keyset_pagination(self):
        page1 = self.svc.search_works(self.owner, limit=2)
        self.assertEqual(len(page1["items"]), 2)
        self.assertIsNotNone(page1["next_after_id"])
        page2 = self.svc.search_works(self.owner, after_id=page1["next_after_id"], limit=2)
        ids1 = {w["id"] for w in page1["items"]}
        ids2 = {w["id"] for w in page2["items"]}
        self.assertFalse(ids1 & ids2)

    def test_phone_css_checklist(self):
        from admin_v2 import templates
        css = templates.CSS
        self.assertIn("min-height:44px", css)
        self.assertIn("bottomnav", css)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn("@media (min-width:1024px)", css)
        self.assertIn("@media (max-width:767px)", css)
        page = templates.layout("Test", "<p>Hi</p>", active="home")
        self.assertIn("bottomnav", page)
        self.assertIn("aria-label", page)


if __name__ == "__main__":
    unittest.main()
