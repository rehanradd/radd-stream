"""UI overhaul tests: login nav, HTML auth redirects, phone tables,
password-change form redirect, section toggle, and daily-action forms.
Fixtures are MOCK only; no real credential, token, URL, or
transaction id is used anywhere in these tests."""
import os
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import make_service  # noqa: E402
from admin_v2 import templates  # noqa: E402
from admin_v2.server import AdminApp  # noqa: E402


def _login(app):
    import json
    status, _ctype, payload, cookie, _loc = app.handle(
        "POST", "/admin/login", {},
        {"Content-Type": "application/json"},
        json.dumps({"username": "owner",
                    "password": "correct horse battery staple"}).encode())
    assert status == 200, payload.decode()
    data = json.loads(payload.decode())
    return cookie.split(";")[0], data["data"]["csrf_token"]


class TestUiOverhaul(unittest.TestCase):
    def setUp(self):
        svc, self.owner, self.auditor = make_service()
        self.app = AdminApp(svc)
        self.cookie, self.csrf = _login(self.app)

    def _get(self, path, cookie=None):
        headers = {}
        if cookie:
            headers["Cookie"] = cookie
        return self.app.handle("GET", path, {}, headers, b"")

    def test_login_form_action_is_admin_login(self):
        page = templates.login_page()
        self.assertIn('action="/admin/login"', page)
        self.assertNotIn("/admin/api/v2/auth/login", page)

    def test_login_page_has_no_sidebar_nav(self):
        page = templates.login_page()
        self.assertNotIn('class="sidebar"', page)
        self.assertNotIn('class="bottomnav"', page)
        self.assertIn('name="username"', page)

    def test_unauthenticated_html_redirects_to_login(self):
        for path in ("/admin", "/admin/content", "/admin/sections",
                     "/admin/users", "/admin/money", "/admin/settings"):
            status, _ctype, _payload, _cookie, location = self._get(path)
            self.assertEqual(status, 303, path)
            self.assertEqual(location, "/admin/login", path)

    def test_logged_in_login_page_redirects_to_dashboard(self):
        status, _ctype, _payload, _cookie, location = self._get(
            "/admin/login", cookie="admin_session=" + self.cookie.split("=", 1)[1]
            if "=" in self.cookie else self.cookie)
        # _get already sets Cookie header from the full cookie string.
        self.assertEqual(status, 303)
        self.assertEqual(location, "/admin")

    def test_phone_table_cells_carry_data_label(self):
        html = templates.table(["ID", "Title"], [[1, "Mock Title"]], "None")
        self.assertIn('<td data-label="ID">1</td>', html)
        self.assertIn('<td data-label="Title">Mock Title</td>', html)
        self.assertIn("td::before", templates.CSS)
        self.assertIn("attr(data-label)", templates.CSS)

    def test_password_change_form_post_redirects(self):
        body = urllib.parse.urlencode({
            "csrf_token": self.csrf,
            "current": "correct horse battery staple",
            "new": "another correct horse battery staple",
            "_next": "/admin/settings",
        }).encode()
        status, _ctype, _payload, cookie, location = self.app.handle(
            "POST", "/admin/api/v2/auth/password-change", {},
            {"Content-Type": "application/x-www-form-urlencoded",
             "Cookie": self.cookie}, body)
        self.assertEqual(status, 303)
        self.assertEqual(location, "/admin/settings")
        self.assertTrue(cookie and cookie.startswith("admin_session="))
        # New session cookie opens Settings.
        status, _ctype, payload, _c, _l = self._get(
            "/admin/settings", cookie=cookie.split(";")[0])
        self.assertEqual(status, 200)
        self.assertIn("Change password", payload.decode())

    def test_section_toggle_flips_state(self):
        import json
        svc = self.app.service
        section = svc.create_section(
            {"id": self.owner["id"], "role": "owner"},
            {"key": "toggle-test", "title": "Toggle Test", "position": 1})
        self.assertTrue(section["is_enabled"])
        status, _ctype, payload, _c, _l = self.app.handle(
            "POST", "/admin/api/v2/sections/toggle-test/toggle", {},
            {"Content-Type": "application/json", "Cookie": self.cookie,
             "X-CSRF-Token": self.csrf}, b"{}")
        self.assertEqual(status, 200, payload.decode())
        self.assertFalse(json.loads(payload.decode())["data"]["is_enabled"])
        status, _ctype, payload, _c, _l = self.app.handle(
            "POST", "/admin/api/v2/sections/toggle-test/toggle", {},
            {"Content-Type": "application/json", "Cookie": self.cookie,
             "X-CSRF-Token": self.csrf}, b"{}")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(payload.decode())["data"]["is_enabled"])

    def test_daily_action_forms_present_on_pages(self):
        # Seed the three pages whose fixtures start empty, so their
        # per-row forms exist to check (per-row forms need a row).
        svc = self.app.service
        svc.create_contact(self.owner, {
            "app_account_hint": "ac***01", "category": "bug",
            "subject": "Mock subject", "body": "Mock body"})
        svc.create_report(self.owner, {
            "source": "app_report", "work_id": 1, "reason": "broken",
            "detail": "Mock detail", "reporter_hint": "ac***01"})
        svc.create_broadcast(self.owner, {
            "title": "Mock News", "body": "Hello", "severity": "info",
            "target": "all", "starts_at": 1700000000, "ends_at": 1800000000})
        checks = {
            "/admin/content": ("/admin/api/v2/content/unhide",
                               "/admin/api/v2/categories"),
            "/admin/sections": ("/admin/api/v2/sections",
                                "/toggle"),
            "/admin/users": ("vip-grant", "/flag"),
            "/admin/money": ("/approve", "/reject"),
            "/admin/inbox": ("/status",),
            "/admin/reports": ("/action",),
            "/admin/broadcasts": ("/admin/api/v2/broadcasts",
                                  "/publish", "/retract"),
            "/admin/domains": ("/validate", "/apply", "/rollback"),
            "/admin/fleet": ("/admin/api/v2/fleet/run",),
            "/admin/analytics": ("/admin/api/v2/analytics/compute",),
            "/admin/settings": ("/admin/api/v2/auth/password-change",
                                "/admin/logout"),
            "/admin": ("/admin/api/v2/pauses",),
        }
        for path, needles in checks.items():
            status, _ctype, payload, _c, _l = self._get(path, cookie=self.cookie)
            self.assertEqual(status, 200, path)
            html = payload.decode()
            for needle in needles:
                self.assertIn(needle, html, "%s missing %s" % (path, needle))
            # Every form on an authenticated page carries CSRF + _next.
            self.assertIn('name="csrf_token"', html, path)
            self.assertIn('name="_next"', html, path)

    def _post_form(self, path, fields):
        body = dict(fields)
        body["csrf_token"] = self.csrf
        body["_next"] = path.rsplit("/", 1)[0] or "/admin"
        return self.app.handle(
            "POST", path, {}, {"Cookie": self.cookie,
                               "Content-Type": "application/x-www-form-urlencoded"},
            urllib.parse.urlencode(body).encode())

    def test_trailing_slash_redirects_to_clean_url(self):
        for path, clean in (("/admin/", "/admin"), ("/admin/users/", "/admin/users"),
                            ("/admin/tuning/", "/admin/tuning")):
            status, _c, _p, _k, location = self._get(path, cookie=self.cookie)
            self.assertEqual(status, 303, path)
            self.assertEqual(location, clean, path)
        # API paths are untouched by the redirect: still a 404, not a 303.
        status, _c, _p, _k, _l = self._get("/admin/api/v2/dashboard/", cookie=self.cookie)
        self.assertEqual(status, 404)

    def test_tuning_page_renders_all_controls_honestly(self):
        status, _c, payload, _k, _l = self._get("/admin/tuning", cookie=self.cookie)
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("Disclaimer", html)
        self.assertIn('name="disclaimer_text"', html)
        self.assertIn('name="disclaimer_email"', html)
        self.assertIn("Save tuning", html)
        # Honest labels: some controls are stored-only, never faked.
        self.assertIn("Stored only", html)
        self.assertIn("Applies:", html)

    def test_monetization_page_renders_coin_prices_without_tokens(self):
        status, _c, payload, _k, _l = self._get("/admin/monetization", cookie=self.cookie)
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("Coin prices", html)
        self.assertIn('name="coin_redeem_day"', html)
        self.assertIn('value="500"', html)
        self.assertIn('value="5000"', html)
        self.assertIn("Save monetization", html)
        # Token inputs exist but are never prefilled.
        self.assertIn('name="shrinkme_api_token" type="password"', html)
        self.assertNotIn("tok-", html)

    def test_tuning_form_save_via_post_alias(self):
        status, _c, _p, _k, location = self._post_form(
            "/admin/api/v2/tuning",
            {"cache_ttl_h": "12", "reason": "form test",
             "disclaimer_email": "radddao1@gmail.com",
             "disclaimer_text": "", "tabs": "home,search,my_list,settings",
             "free_quality_cap": "720p", "theme_mode": "dark",
             "theme_accent": "", "disclaimer_version": "0",
             "resolver_concurrency": "2", "candidate_cap": "10",
             "warmup_count": "50", "warmup_interval_h": "24",
             "rate_limit_play_per_min": "30", "import_cap": "25",
             "import_concurrency": "1", "prefetch_queue": "100",
             "prefetch_concurrency": "1", "hero_max": "6", "section_cap": "20",
             "home_sections_max": "12", "domain_check_interval_min": "60",
             "theme_dynamic_color": "0", "theme_hero_autoplay": "1",
             "theme_hero_interval_s": "5"})
        self.assertEqual(status, 303)
        self.assertEqual(self.app.service.get_tuning(self.owner)["cache_ttl_h"], 12)

    def test_monetization_form_save_via_post_alias(self):
        status, _c, _p, _k, _l = self._post_form(
            "/admin/api/v2/monetization",
            {"vip_monthly_pkr": "250", "vip_yearly_pkr": "1500",
             "coin_redeem_day": "600", "coin_redeem_weekend": "1200",
             "coin_redeem_monthly": "5000", "coin_redeem_download": "100",
             "coin_redeem_request": "300", "coin_redeem_theme": "250",
             "pak_till_id": "", "pak_jazzcash_number": "",
             "pak_easypaisa_number": "", "pak_raast_id": "",
             "monetag_zone_id": "", "adsterra_tag_id": "",
             "shrinkme_api_token": "", "droplink_api_token": "",
             "maintenance_mode": "0", "feature_downloads": "1",
             "feature_pure_cinema": "1", "feature_chromecast": "1",
             "feature_quality_gate": "0", "apk_update_url": ""})
        self.assertEqual(status, 303)
        mon = self.app.service.get_monetization(self.owner)
        self.assertEqual(mon["vip_monthly_pkr"], 250)
        self.assertEqual(mon["coin_redeem_day"], 600)

    def test_data_health_page_without_live_says_so(self):
        status, _c, payload, _k, _l = self._get("/admin/data-health", cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertIn("No live catalog", payload.decode())

    def test_more_page_lists_new_pages(self):
        status, _c, payload, _k, _l = self._get("/admin/more", cookie=self.cookie)
        self.assertEqual(status, 200)
        html = payload.decode()
        for href in ("/admin/users", "/admin/money", "/admin/live",
                     "/admin/tuning", "/admin/monetization", "/admin/data-health"):
            self.assertIn('href="%s"' % href, html)

    def test_users_page_shows_coins_and_fleet_shows_never_ran(self):
        status, _c, payload, _k, _l = self._get("/admin/users", cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertIn("Coins", payload.decode())
        status, _c, payload, _k, _l = self._get("/admin/fleet", cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertIn("Never ran", payload.decode())
        self.assertIn("Last sync", payload.decode())


if __name__ == "__main__":
    unittest.main()
