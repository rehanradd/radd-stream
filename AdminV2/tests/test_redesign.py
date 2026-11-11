"""Redesign tests: brand layout, badges, date/money formatting,
filter forms, checkbox labels, and the login card. Design only —
no route, form action, CSRF, or service behaviour is changed here.
Fixtures are MOCK only."""
import json
import os
import re
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import make_service  # noqa: E402
from admin_v2 import templates  # noqa: E402
from admin_v2.server import AdminApp  # noqa: E402


def _login(app):
    status, _ctype, payload, cookie, _loc = app.handle(
        "POST", "/admin/login", {},
        {"Content-Type": "application/json"},
        json.dumps({"username": "owner",
                    "password": "correct horse battery staple"}).encode())
    assert status == 200, payload.decode()
    data = json.loads(payload.decode())
    return cookie.split(";")[0], data["data"]["csrf_token"]


class TestRedesign(unittest.TestCase):
    def setUp(self):
        svc, self.owner, self.auditor = make_service()
        self.app = AdminApp(svc)
        self.cookie, self.csrf = _login(self.app)

    def _get(self, path, cookie=None):
        headers = {}
        if cookie:
            headers["Cookie"] = cookie
        return self.app.handle("GET", path, {}, headers, b"")

    # -- layout: header lives inside the main column, never under a sidebar
    def test_sidebar_is_grid_not_fixed_overlay(self):
        self.assertIn("grid-template-columns:264px", templates.CSS)
        self.assertNotIn(".sidebar{display:block;position:fixed", templates.CSS)
        page = templates.layout("Dashboard", "<p>Hi</p>", active="home")
        self.assertIn('<div class="shell">', page)
        self.assertIn('<header class="pagehead"><h1>Dashboard</h1>', page)
        # Header comes after the sidebar in the document: it sits in
        # the main column, so the sidebar can never cover it.
        self.assertLess(page.index('class="sidebar"'),
                        page.index('<header class="pagehead">'))

    def test_sidebar_has_brand_and_icons_and_active(self):
        page = templates.layout("Users", "<p>Hi</p>", active="users")
        self.assertIn("Radd Stream", page)
        self.assertIn("<svg", page)
        self.assertIn('class="navitem active"', page)
        self.assertIn("/admin/users", page)

    def test_bottomnav_has_icons_and_active_state(self):
        page = templates.layout("Money", "<p>Hi</p>", active="money")
        self.assertIn('class="bottomnav"', page)
        self.assertIn('class="active"><span class="nav-ico">', page)
        # Content clears the fixed bottom bar: tall bottom padding.
        self.assertIn("padding:16px 16px 120px", templates.CSS)

    def test_content_uses_full_width(self):
        self.assertIn("max-width:1200px", templates.CSS)
        self.assertNotIn("max-width:720px", templates.CSS)
        self.assertNotIn("max-width:1024px", templates.CSS)

    def test_tables_scroll_never_hide_columns(self):
        self.assertIn(".tablewrap{overflow-x:auto", templates.CSS)
        self.assertIn("white-space:nowrap", templates.CSS)

    # -- formatters and badges
    def test_fmt_date_renders_a_real_date(self):
        self.assertRegex(templates.fmt_date(1796436747), r"\d{2} [A-Z][a-z]{2} \d{4}")
        self.assertNotIn("1796436747", templates.fmt_date(1796436747))
        self.assertEqual(templates.fmt_date(None), "—")
        self.assertEqual(templates.fmt_date(0), "—")

    def test_fmt_pkr(self):
        self.assertEqual(templates.fmt_pkr(1500), "PKR 1,500")
        self.assertEqual(templates.fmt_pkr(200), "PKR 200")

    def test_badges_cover_tier_status_and_flags(self):
        self.assertIn("badge success", templates.badge("vip"))
        self.assertIn("badge info", templates.badge("free"))
        self.assertIn("badge warning", templates.badge("pending"))
        self.assertIn("badge success", templates.badge("Safe"))
        self.assertIn("badge danger", templates.badge("Adult"))
        self.assertIn("badge warning", templates.badge("Unknown"))
        self.assertIn("badge success", templates.badge("Enabled"))

    def test_badges_show_capitalised_labels_not_raw_enums(self):
        # Audit §Cosmetic: raw lowercase "pending" in a table badge.
        # The lookup still uses the raw label; only the display changes.
        html = templates.badge("pending")
        self.assertIn("Pending", html)
        self.assertNotIn(">pending<", html)
        html = templates.badge("in_progress")
        self.assertIn("In Progress", html)
        self.assertNotIn("in_progress", html)
        self.assertIn("badge success", templates.badge("vip"))
        self.assertIn("Vip", templates.badge("vip"))

    def test_table_raw_cells_render_badges_plain_cells_stay_escaped(self):
        html = templates.table(
            ["Tier", "Note"],
            [[templates.Raw(templates.badge("vip")), "<b>no</b>"]], "None")
        self.assertIn('class="badge success"', html)
        self.assertIn("&lt;b&gt;no&lt;/b&gt;", html)
        self.assertIn('<td data-label="Tier">', html)

    # -- pages show formatted data, not raw values
    def test_users_page_shows_date_and_tier_badges(self):
        _s, _c, payload, _k, _l = self._get("/admin/users", cookie=self.cookie)
        html = payload.decode()
        self.assertNotIn("1796436747", html)
        self.assertRegex(html, r"\d{2} [A-Z][a-z]{2} \d{4}")
        self.assertIn('class="badge success"', html)  # vip tier
        self.assertIn('class="badge info"', html)     # free tier
        self.assertIn('name="q"', html)               # search affordance
        self.assertIn('name="tier"', html)

    def test_money_page_shows_pkr_and_status_badges(self):
        _s, _c, payload, _k, _l = self._get("/admin/money", cookie=self.cookie)
        html = payload.decode()
        self.assertIn("PKR 200", html)
        self.assertIn("PKR 1,500", html)
        self.assertNotIn(">200<", html)
        self.assertNotIn(">1500<", html)
        self.assertIn('class="badge warning"', html)  # pending
        self.assertIn('name="status"', html)

    def test_content_page_badges_and_search(self):
        _s, _c, payload, _k, _l = self._get("/admin/content", cookie=self.cookie)
        html = payload.decode()
        self.assertIn('class="badge success"', html)  # Safe flag / Real poster
        self.assertIn('class="badge danger"', html)   # Adult flag
        self.assertIn('name="q"', html)
        self.assertIn('name="type"', html)

    def test_content_search_filters(self):
        _s, _c, payload, _k, _l = self.app.handle(
            "GET", "/admin/content", {"q": ["Series"]}, {"Cookie": self.cookie}, b"")
        html = payload.decode()
        self.assertIn("MOCK Series One", html)
        self.assertNotIn("MOCK Movie One", html)

    def test_users_search_filters_by_tier(self):
        _s, _c, payload, _k, _l = self.app.handle(
            "GET", "/admin/users", {"tier": ["vip"]}, {"Cookie": self.cookie}, b"")
        html = payload.decode()
        self.assertIn("ac***02", html)
        self.assertNotIn("ac***01", html)

    # -- buttons and forms
    def test_checkbox_labels_do_not_wrap_below_the_box(self):
        _s, _c, payload, _k, _l = self._get("/admin/money", cookie=self.cookie)
        html = payload.decode()
        self.assertIn('class="check"', html)
        self.assertNotIn('style="width:auto;min-height:44px"', html)
        self.assertIn("label.check{display:flex", templates.CSS)

    def test_destructive_buttons_are_danger_secondary_is_ghost(self):
        _s, _c, payload, _k, _l = self._get("/admin/money", cookie=self.cookie)
        html = payload.decode()
        self.assertIn('class="danger">Reject payment<', html)
        self.assertIn(".btn.danger", templates.CSS)
        self.assertIn(".btn.secondary", templates.CSS)
        self.assertIn("background:transparent", templates.CSS)

    def test_buttons_are_not_trapped_in_grey_boxes(self):
        self.assertNotIn(".stickybar{position:sticky", templates.CSS)
        self.assertNotIn("background:var(--surface);\npadding:12px;border:1px solid",
                         templates.CSS)

    def test_dashboard_has_stat_cards_and_filled_content(self):
        _s, _c, payload, _k, _l = self._get("/admin", cookie=self.cookie)
        html = payload.decode()
        self.assertIn('class="stats"', html)
        self.assertIn('class="stat-num">2<', html)  # pending payments
        self.assertIn("Pending payments: 2", html)   # needs-you-now, formatted
        self.assertIn("System", html)

    # -- login page
    def test_login_page_is_a_centered_card_with_logo(self):
        page = templates.login_page()
        self.assertIn('class="auth-card"', page)
        self.assertIn("<svg", page)
        self.assertIn('action="/admin/login"', page)
        self.assertNotIn('class="sidebar"', page)
        self.assertNotIn('class="bottomnav"', page)
        self.assertIn(".auth-card{", templates.CSS)

    # -- identity: no external assets, system fonts only
    def test_no_external_assets(self):
        self.assertNotIn("http://", templates.CSS)
        self.assertNotIn("https://", templates.CSS)
        self.assertNotIn("@import", templates.CSS)
        self.assertNotIn("url(", templates.CSS)
        self.assertIn("system-ui", templates.CSS)
        page = templates.layout("Test", "<p>Hi</p>", active="home")
        self.assertNotIn("<script", page)
        self.assertNotIn("fonts.googleapis", page)


if __name__ == "__main__":
    unittest.main()
