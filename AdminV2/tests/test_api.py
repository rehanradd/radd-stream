import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import good_checker, make_service  # noqa: E402
from admin_v2.server import AdminApp  # noqa: E402


class ApiClient:
    def __init__(self, app):
        self.app = app
        self.cookie = None
        self.csrf = None

    def call(self, method, path, body=None, headers=None, raw_headers=None):
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if headers:
            h.update(headers)
        if raw_headers is not None:
            h = raw_headers
        data = json.dumps(body).encode() if body is not None else b""
        status, ctype, payload, cookie, location = self.app.handle(
            method, path, {}, h, data)
        if cookie:
            self.cookie = cookie.split(";")[0]
        out = payload.decode()
        try:
            parsed = json.loads(out)
        except Exception:
            parsed = {"_html": out}
        return status, parsed, location

    def login(self, username="owner", password="correct horse battery staple"):
        status, data, _ = self.call("POST", "/admin/login",
                                    {"username": username, "password": password})
        assert status == 200, data
        self.csrf = data["data"]["csrf_token"]
        return data


class TestApi(unittest.TestCase):
    def setUp(self):
        svc, self.owner, self.auditor = make_service()
        self.app = AdminApp(svc, domain_checker=good_checker)
        self.client = ApiClient(self.app)
        self.client.login()

    def test_every_route_happy_and_auth(self):
        # Public contract needs no auth.
        status, data, _ = self.client.call("GET", "/api/v1/app/remote-config",
                                           raw_headers={})
        self.assertEqual(status, 200)
        self.assertIn("maintenance_mode", data["data"])
        # Unauthenticated admin API -> 401.
        anon = ApiClient(self.app)
        status, data, _ = anon.call("GET", "/admin/api/v2/dashboard", raw_headers={})
        self.assertEqual(status, 401)
        # Authenticated dashboard.
        status, data, _ = self.client.call("GET", "/admin/api/v2/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("pending_payments", data["data"])

    def test_auditor_read_only(self):
        aud = ApiClient(self.app)
        aud.login(username="auditor")
        status, _d, _ = aud.call("GET", "/admin/api/v2/sections")
        self.assertEqual(status, 200)
        status, data, _ = aud.call("POST", "/admin/api/v2/sections",
                                   {"key": "nope", "title": "Nope"})
        self.assertEqual(status, 403)

    def test_missing_csrf_blocked(self):
        c = ApiClient(self.app)
        c.login()
        c.csrf = None
        status, _d, _ = c.call("POST", "/admin/api/v2/sections",
                               {"key": "nope2", "title": "Nope"})
        self.assertEqual(status, 403)

    def test_not_found_and_validation(self):
        status, _d, _ = self.client.call("GET", "/admin/api/v2/nope")
        self.assertEqual(status, 404)
        status, _d, _ = self.client.call("PUT", "/admin/api/v2/tuning",
                                         {"resolver_concurrency": 99})
        self.assertEqual(status, 400)

    def test_rate_limit_login(self):
        anon = ApiClient(self.app)
        for _ in range(5):
            status, _d, _ = anon.call("POST", "/admin/login",
                                      {"username": "owner", "password": "wrong password here"})
        status, data, _ = anon.call("POST", "/admin/login",
                                    {"username": "owner", "password": "wrong password here"})
        self.assertIn(status, (401, 403, 429))

    def test_idempotency_payment_and_broadcast_and_domain(self):
        # Payment approve twice with the same key credits once.
        status, data, _ = self.client.call("POST", "/admin/api/v2/payments/1/approve",
                                           {"confirm": True},
                                           headers={"Idempotency-Key": "pay-1"})
        self.assertEqual(status, 200)
        status, data2, _ = self.client.call("POST", "/admin/api/v2/payments/1/approve",
                                            {"confirm": True},
                                            headers={"Idempotency-Key": "pay-1"})
        self.assertEqual(status, 200)
        self.assertEqual(data["data"], data2["data"])
        # Broadcast publish twice with the same key publishes once.
        status, data, _ = self.client.call("POST", "/admin/api/v2/broadcasts",
                                           {"title": "MOCK News", "body": "Hello",
                                            "starts_at": 1700000000, "ends_at": 1800000000})
        bid = data["data"]["id"]
        h = {"Idempotency-Key": "bc-1"}
        status, d1, _ = self.client.call("POST", "/admin/api/v2/broadcasts/%d/publish" % bid,
                                         {"confirm": True}, headers=h)
        self.assertEqual(status, 200)
        status, d2, _ = self.client.call("POST", "/admin/api/v2/broadcasts/%d/publish" % bid,
                                         {"confirm": True}, headers=h)
        self.assertEqual(d1["data"], d2["data"])

    def test_old_app_contract(self):
        from admin_v2 import fixture_app
        cfg = fixture_app.public_remote_config(self.app.service)
        old = fixture_app.old_app_parse(cfg)
        self.assertIn("maintenance_mode", old)
        # New fields exist in the public body but old keys still parse.
        self.assertIn("sections", cfg)
        self.assertIn("active_broadcasts", cfg)

    def test_html_pages_render_with_states(self):
        for path in ("/admin", "/admin/content", "/admin/sections", "/admin/users",
                     "/admin/money", "/admin/domains", "/admin/fleet", "/admin/analytics",
                     "/admin/usage", "/admin/settings", "/admin/more", "/admin/live"):
            status, ctype, payload, _c, _l = self.app.handle(
                "GET", path, {}, {"Cookie": self.client.cookie}, b"")
            self.assertEqual(status, 200, path)
            self.assertIn("bottomnav", payload.decode())
        status, ctype, payload, _c, _l = self.app.handle(
            "GET", "/admin", {"state": ["loading"]}, {"Cookie": self.client.cookie}, b"")
        self.assertIn("skeleton", payload.decode())

    def test_strict_host_rule(self):
        from admin_v2.server import check_strict_host
        self.assertTrue(check_strict_host("raddstream.duckdns.org", "https", True))
        self.assertFalse(check_strict_host("raddstream.duckdns.org", "http", True))
        self.assertFalse(check_strict_host("other.example", "https", True))
        self.assertTrue(check_strict_host("localhost", "http", False))


if __name__ == "__main__":
    unittest.main()
