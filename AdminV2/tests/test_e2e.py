import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import bad_checker, good_checker, make_service  # noqa: E402
from admin_v2 import fixture_app  # noqa: E402


class TestE2E(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()

    def _home_keys(self):
        return [s["key"] for s in fixture_app.home_layout(self.svc)]

    def test_home_publish_and_undo(self):
        before = self._home_keys()
        self.svc.create_section(self.owner, {"key": "comedy-rail", "title": "Comedy", "position": 9})
        # Draft does not appear in the app until publish.
        self.assertEqual(self._home_keys(), before)
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        self.assertIn("comedy-rail", self._home_keys())
        self.svc.delete_section(self.owner, "comedy-rail")
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        self.assertNotIn("comedy-rail", self._home_keys())

    def test_visibility_global_and_section_only(self):
        self.svc.add_card(self.owner, "movie", {"work_id": 1, "position": 0})
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        movies = [s for s in fixture_app.home_layout(self.svc) if s["key"] == "movie"][0]
        self.assertTrue(any(c["work_id"] == 1 for c in movies["cards"]))
        vis = self.svc.hide_content(self.owner, {"scope": "work", "scope_id": "1", "reason": "owner"})
        self.assertFalse(any(c["work_id"] == 1 for c in
                             [s for s in fixture_app.home_layout(self.svc) if s["key"] == "movie"][0]["cards"]))
        self.svc.unhide_content(self.owner, vis["id"], {})
        movies = [s for s in fixture_app.home_layout(self.svc) if s["key"] == "movie"][0]
        self.assertTrue(any(c["work_id"] == 1 for c in movies["cards"]))

    def test_category_flow(self):
        self.svc.create_category(self.owner, {"key": "drama", "display_name": "Drama"})
        self.svc.assign_category_work(self.owner, "drama", {"work_id": 2, "position": 0})
        works = self.svc.list_category_works(self.owner, "drama")["items"]
        self.assertEqual(len(works), 1)
        self.svc.unassign_category_work(self.owner, "drama", 2)
        self.assertEqual(len(self.svc.list_category_works(self.owner, "drama")["items"]), 0)

    def test_adult_e2e(self):
        # Adult work can never appear on a non-adult surface, even after
        # an unhide, because the adult clause outranks visibility.
        vis = self.svc.hide_content(self.owner, {"scope": "work", "scope_id": "3", "reason": "owner"})
        self.svc.unhide_content(self.owner, vis["id"], {})
        layout = fixture_app.home_layout(self.svc)
        for sec in layout:
            self.assertFalse(any(c["work_id"] == 3 for c in sec["cards"]))

    def test_tuning_e2e(self):
        self.svc.put_tuning(self.owner, {"cache_ttl_h": 12, "reason": "test"})
        self.assertEqual(self.svc.get_tuning(self.owner)["cache_ttl_h"], 12)

    def test_pause_section_e2e(self):
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        self.assertIn("movie", self._home_keys())
        p = self.svc.pause(self.owner, {"target_type": "section", "target_id": "movie", "reason": "test"})
        self.assertNotIn("movie", self._home_keys())
        self.svc.resume_pause(self.owner, p["id"])
        self.assertIn("movie", self._home_keys())

    def test_broadcast_e2e(self):
        import time
        now = int(time.time())
        bc = self.svc.create_broadcast(self.owner, {"title": "MOCK", "body": "Hi",
                                                    "starts_at": now - 10, "ends_at": now + 3600})
        self.assertEqual(len(fixture_app.public_remote_config(self.svc)["active_broadcasts"]), 0)
        self.svc.publish_broadcast(self.owner, bc["id"], {"confirm": True})
        self.assertEqual(len(fixture_app.public_remote_config(self.svc)["active_broadcasts"]), 1)
        self.svc.retract_broadcast(self.owner, bc["id"])
        self.assertEqual(len(fixture_app.public_remote_config(self.svc)["active_broadcasts"]), 0)

    def test_domain_e2e(self):
        self.svc.add_candidate(self.owner, "multimovies", {"domain": "example.org"})
        v = self.svc.validate_domain(self.owner, "multimovies", {"domain": "example.org"}, checker=good_checker)
        self.assertTrue(v["validated"])
        res = self.svc.apply_domain(self.owner, "multimovies", {"domain": "example.org", "confirm": True})
        self.assertEqual(res["to_domain"], "example.org")
        self.assertEqual(self.svc.resolve_domain("multimovies")[0], "example.org")
        # Second domain, then rollback to the first.
        self.svc.add_candidate(self.owner, "multimovies", {"domain": "example.net"})
        self.svc.validate_domain(self.owner, "multimovies", {"domain": "example.net"}, checker=good_checker)
        self.svc.apply_domain(self.owner, "multimovies", {"domain": "example.net", "confirm": True})
        rb = self.svc.rollback_domain(self.owner, "multimovies", {"confirm": True}, checker=good_checker)
        self.assertEqual(rb["to_domain"], "example.org")

    def test_vip_payment_e2e(self):
        before = fixture_app.vip_status(self.svc, "ac***01")
        self.assertEqual(before["tier"], "free")
        self.svc.approve_payment(self.owner, 1, {"confirm": True})
        after = fixture_app.vip_status(self.svc, "ac***01")
        self.assertEqual(after["tier"], "vip")
        self.assertGreater(after["vip_until"], before["vip_until"] or 0)

    def test_remote_config_rollback_e2e(self):
        v0 = self.svc._config_row()["config_version"]
        self.svc.draft_remote_config(self.owner, {"brand_primary": "#111111"})
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        self.assertEqual(self.svc._config_row()["brand_primary"], "#111111")
        self.svc.rollback_remote_config(self.owner, {"version": v0, "confirm": True})
        cfg = fixture_app.public_remote_config(self.svc)
        self.assertEqual(cfg["config_version"], v0 + 2)


if __name__ == "__main__":
    unittest.main()
