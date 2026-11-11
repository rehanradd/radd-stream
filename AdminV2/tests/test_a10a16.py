"""Panel polish A10-A16 (2026-11-11).

A11: inbox shows sender, date and message body (list + detail).
A12: failed domains show the failure reason.
A13: broadcast / scheduled-publish times accept a date picker
     (datetime-local, read as UTC) as well as Unix seconds.
A14: the 360px "More" page links every sidebar section, incl. Live TV.
A16: Live author shows the admin username, and the seeded first
     publish shows "system" instead of "user 0".

A10 and A15 are not covered here: A10's flag does not exist anywhere
in the panel, the backend or the app (nothing to turn off), and A15
was already fixed before this batch (the comment/note is correct).
"""
import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import good_checker, make_service  # noqa: E402
from admin_v2.errors import ApiError  # noqa: E402
from admin_v2.server import AdminApp  # noqa: E402
from admin_v2.services import _parse_broadcast_time  # noqa: E402


def _utc(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


class TestParseBroadcastTime(unittest.TestCase):
    def test_unix_seconds_int_passes_through(self):
        self.assertEqual(_parse_broadcast_time(1794346587, "starts_at"), 1794346587)

    def test_unix_seconds_string_passes_through(self):
        self.assertEqual(_parse_broadcast_time("1794346587", "starts_at"), 1794346587)

    def test_datetime_local_read_as_utc(self):
        self.assertEqual(_parse_broadcast_time("2026-11-11T14:30", "starts_at"),
                         _utc(2026, 11, 11, 14, 30))

    def test_empty_is_none(self):
        self.assertIsNone(_parse_broadcast_time(None, "starts_at"))
        self.assertIsNone(_parse_broadcast_time("", "starts_at"))

    def test_garbage_raises(self):
        with self.assertRaises(ApiError):
            _parse_broadcast_time("not-a-date", "starts_at")


class TestBroadcastDatetimeLocal(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()

    def test_create_with_datetime_local_stores_unix_seconds(self):
        bc = self.svc.create_broadcast(self.owner, {
            "title": "T", "body": "B",
            "starts_at": "2026-11-11T14:30", "ends_at": "2026-11-11T15:30"})
        self.assertEqual(bc["starts_at"], _utc(2026, 11, 11, 14, 30))
        self.assertEqual(bc["ends_at"], _utc(2026, 11, 11, 15, 30))

    def test_create_with_unix_seconds_still_works(self):
        bc = self.svc.create_broadcast(self.owner, {
            "title": "T", "body": "B",
            "starts_at": 1794346587, "ends_at": 1794350187})
        self.assertEqual(bc["starts_at"], 1794346587)
        self.assertEqual(bc["ends_at"], 1794350187)

    def test_update_with_datetime_local(self):
        bc = self.svc.create_broadcast(self.owner, {"title": "T", "body": "B"})
        updated = self.svc.update_broadcast(self.owner, bc["id"], {
            "starts_at": "2026-11-11T14:30", "ends_at": "2026-11-11T15:30"})
        self.assertEqual(updated["starts_at"], _utc(2026, 11, 11, 14, 30))

    def test_schedule_publish_with_datetime_local(self):
        row = self.svc.schedule_publish(self.owner, {
            "scheduled_at": "2099-01-01T00:00", "note": "future"})
        self.assertEqual(row["scheduled_at"], _utc(2099, 1, 1, 0, 0))


class TestInboxShowsSenderDateBody(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()
        self.app = AdminApp(self.svc, domain_checker=good_checker)
        self.msg_id = self.svc.create_contact(self.owner, {
            "app_account_hint": "acc-1234", "category": "bug",
            "subject": "Play fails", "body": "tap play, nothing happens"})
        status, _c, payload, cookie, _l = self.app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            json.dumps({"username": "owner",
                        "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200)
        self.headers = {"Cookie": cookie.split(";")[0]}

    def test_list_contact_returns_body(self):
        items = self.svc.list_contact(self.owner)["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["body"], "tap play, nothing happens")
        self.assertEqual(items[0]["subject"], "Play fails")

    def test_inbox_page_shows_sender_date_body(self):
        status, _c, payload, _k, _l = self.app.handle(
            "GET", "/admin/inbox", {}, self.headers, b"")
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("Sender", html)
        self.assertIn("Date", html)
        self.assertIn("Message", html)
        self.assertIn("tap play, nothing happens", html)


class TestDomainsShowFailureReason(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()
        self.app = AdminApp(self.svc, domain_checker=good_checker)
        self.svc.admin.execute(
            "INSERT INTO domain_registry (site_key, active_domain, status, last_checked_at, last_failure_reason) "
            "VALUES (?,?,?,?,?)",
            ("9xmovies", "9xmovie.bayern", "failed", 1794346587, "redirect_hijack"))
        self.svc.admin.commit()
        status, _c, payload, cookie, _l = self.app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            json.dumps({"username": "owner",
                        "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200)
        self.headers = {"Cookie": cookie.split(";")[0]}

    def test_domains_page_shows_failure_reason(self):
        status, _c, payload, _k, _l = self.app.handle(
            "GET", "/admin/domains", {}, self.headers, b"")
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("Failure reason", html)
        self.assertIn("redirect_hijack", html)


class TestMorePageLinksLiveTv(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()
        self.app = AdminApp(self.svc, domain_checker=good_checker)
        status, _c, payload, cookie, _l = self.app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            json.dumps({"username": "owner",
                        "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200)
        self.headers = {"Cookie": cookie.split(";")[0]}

    def test_more_page_links_live_tv(self):
        status, _c, payload, _k, _l = self.app.handle(
            "GET", "/admin/more", {}, self.headers, b"")
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("/admin/live-tv", html)
        self.assertIn("Live TV", html)


class TestLiveAuthorName(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()
        self.app = AdminApp(self.svc, domain_checker=good_checker)
        status, _c, payload, cookie, _l = self.app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            json.dumps({"username": "owner",
                        "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200)
        self.headers = {"Cookie": cookie.split(";")[0]}

    def test_display_name(self):
        self.assertEqual(self.svc._admin_display_name(self.owner["id"]), "owner")
        self.assertEqual(self.svc._admin_display_name(0), "system")
        self.assertEqual(self.svc._admin_display_name(None), "system")
        self.assertEqual(self.svc._admin_display_name(999), "user 999")

    def test_seeded_publish_is_system_then_owner_after_publish(self):
        live = self.svc.get_live(self.owner)
        self.assertEqual(live["live"]["published_by_name"], "system")
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        live = self.svc.get_live(self.owner)
        self.assertEqual(live["live"]["published_by_name"], "owner")
        hist = self.svc.list_config_history(self.owner)["items"]
        names = {h["config_version"]: h["published_by_name"] for h in hist}
        self.assertEqual(names[1], "system")
        self.assertEqual(names[2], "owner")

    def test_live_page_names_the_author(self):
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        status, _c, payload, _k, _l = self.app.handle(
            "GET", "/admin/live", {}, self.headers, b"")
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("by owner", html)
        self.assertIn("system", html)
        self.assertNotIn("user 0", html)


if __name__ == "__main__":
    unittest.main()
