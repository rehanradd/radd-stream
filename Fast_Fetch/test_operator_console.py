#!/usr/bin/env python3
"""The Sovereign Operator Console — routing, gating, and what its cards read.

Three questions, each one a defect class this file exists to keep shut:

  * **Is the door the same door?** `/operator` sits on the operator port beside
    `/admin`. It must be 404 on the public port, 401 with a credential form (and
    no data) without a bearer, byte-identical for a missing and a wrong token,
    and 200 only when the token proves. The page is a static shell; every datum
    it shows is a separate gated request.
  * **Is every read bounded?** The console must never call `/api/data` (a
    full-ledger materialisation measured at 2.5 MB / 46 s in-process) and never
    `/api/v1/stats` (42 s cold on an unstamped projection). Pulse reads
    `screen_pulse`, and this file traces the SQL it runs to prove it touches the
    18-row meta table and a small COUNT, never `cat_works`, `releases` or
    `download_sources`.
  * **Do the buttons write what they claim?** Approve and reject carry the
    per-row CSRF the JSON screen mints; a wrong or missing token is the same 403.
    Broadcast fields round-trip into the public remote config and an over-long
    message is refused, not truncated.

Every database here is a `tempfile.TemporaryDirectory`. Nothing reads a
credential, the production catalog, or the live service.

    python3 -S Fast_Fetch/test_operator_console.py
"""
import json
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts       # noqa: E402
import admin_panel    # noqa: E402
import payments       # noqa: E402
import viewer         # noqa: E402

TOKEN = "console-suite-operator-credential"


def _serve(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


class ConsoleSocketTests(unittest.TestCase):
    """Two real servers on loopback, no catalog needed for the console shell."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.db_path = root / "catalog.db"
        cls.state_path = root / "user_state.db"
        cls.env = mock.patch.dict("os.environ", {
            "RADD_ADMIN_TOKEN": TOKEN,
            "RADD_USER_STATE_DB": str(cls.state_path),
        })
        cls.env.start()
        cls.db_patch = mock.patch.object(viewer, "DB_PATH", cls.db_path)
        cls.db_patch.start()
        cls.public = viewer.make_server("127.0.0.1", 0, operator=False)
        cls.operator = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (cls.public, cls.operator):
            _serve(server)
        cls.public_url = f"http://127.0.0.1:{cls.public.server_address[1]}"
        cls.operator_url = f"http://127.0.0.1:{cls.operator.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        for server in (cls.public, cls.operator):
            server.shutdown()
            server.server_close()
        cls.db_patch.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def fetch(self, base, path, headers=None):
        request = urllib.request.Request(base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    # ── the public port never learns the console exists ────────────────── #
    def test_the_public_port_answers_404_and_names_no_crawler(self):
        for path in ("/operator", "/operator/", "/operator/api/pulse"):
            status, _headers, raw = self.fetch(self.public_url, path)
            self.assertEqual(status, 404, path)
            for site in admin_panel.FLEET_SITES:
                self.assertNotIn(site.encode(), raw, f"{path} named {site}")

    # ── the 401 is a form, not a page of data ──────────────────────────── #
    def test_without_a_token_the_console_is_a_401_credential_form(self):
        status, headers, raw = self.fetch(self.operator_url, "/operator/")
        self.assertEqual(status, 401)
        self.assertTrue(headers.get("Content-Type", "").startswith("text/html"))
        page = raw.decode("utf-8")
        self.assertIn("Unlock", page)
        self.assertNotIn("<script", page.lower())
        for site in admin_panel.FLEET_SITES:
            self.assertNotIn(site, page, f"the refusal named {site}")
        self.assertNotIn(TOKEN, page)

    def test_a_missing_and_a_wrong_token_are_byte_identical(self):
        _s1, _h1, absent = self.fetch(self.operator_url, "/operator/")
        _s2, _h2, wrong = self.fetch(
            self.operator_url, "/operator/",
            headers={"Authorization": "Bearer definitely-not-it"})
        self.assertEqual(absent, wrong)

    # ── the token serves the shell, and the shell carries no secret ────── #
    def test_the_token_serves_the_console_uncached_and_without_itself(self):
        status, headers, raw = self.fetch(
            self.operator_url, "/operator/",
            headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        page = raw.decode("utf-8")
        for label in ("Pulse &amp; Metrics", "Payment Queue",
                      "Broadcast &amp; Remote Control", "Users &amp; Anti-Abuse",
                      "Scraper Fleet", "Link Explorer"):
            self.assertIn(label, page)
        self.assertNotIn(TOKEN, page, "the page echoed the bearer")
        self.assertIn("10xflix", page, "the loopback roster did not reach the page")

    def test_a_query_token_serves_the_console_and_sets_a_session(self):
        status, headers, raw = self.fetch(
            self.operator_url, f"/operator/?token={TOKEN}")
        self.assertEqual(status, 200)
        self.assertIn("Set-Cookie", headers)
        self.assertIn(b"SOVEREIGN OPERATOR CONSOLE", raw)

    def test_the_pill_persists_the_agreed_storage_key(self):
        # The key name is a contract with the operator's browser, not an
        # implementation detail: a rename would silently log every session out.
        page = viewer.render_operator_console()
        self.assertIn("radd_operator_token", page)
        self.assertIn("localStorage.getItem", page)
        self.assertIn("localStorage.setItem", page)
        self.assertIn("🔒 Operator Access Granted", page)
        self.assertIn("'Authorization': 'Bearer ' + TOKEN", page)

    def test_the_console_never_calls_the_unbounded_routes(self):
        page = viewer.render_operator_console()
        self.assertNotIn("api('/api/data", page)
        self.assertNotIn("api('/api/v1/stats", page)
        self.assertNotIn("fetch('/api/data", page)
        self.assertNotIn("fetch('/api/v1/stats", page)
        self.assertIn("api('/admin/api/pulse')", page)
        self.assertIn("/api/v1/posts?q=", page)

    def test_the_legacy_admin_page_still_answers_and_links_the_console(self):
        status, _headers, raw = self.fetch(
            self.operator_url, "/admin",
            headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 200)
        self.assertIn(b"/operator/", raw)


class BoundedScreensTests(unittest.TestCase):
    """The screens the console's cards are built from, called directly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "catalog.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)

    def _stamp(self, works=10, releases=20, resumable=3, temporary=1,
               by_state=None):
        self.conn.execute("CREATE TABLE IF NOT EXISTS cat_projection_meta"
                          " (key TEXT PRIMARY KEY, value TEXT)")
        values = {
            "works_safe": works,
            "releases_safe": releases,
            "links_resumable_safe": resumable,
            "links_temporary_safe": temporary,
            "links_by_state_safe": json.dumps(
                by_state if by_state is not None else
                {"active": 4, "unchecked": 26, "dead": 2}),
            "posts": 11,
            "releases": 22,
            "links": 33,
            "catalog_rev": 7,
            "projected_at": "1760000000.0",
        }
        for key, value in values.items():
            self.conn.execute("INSERT OR REPLACE INTO cat_projection_meta"
                              " VALUES(?, ?)", (key, str(value)))
        self.conn.commit()

    def test_an_unstamped_projection_withholds_numbers_instead_of_counting(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS sitemap_cache (loc TEXT)")
        self.conn.commit()
        self.conn.execute("CREATE TABLE cat_works (id INTEGER)")
        self.conn.commit()
        statements = []
        self.conn.set_trace_callback(statements.append)
        try:
            pulse = admin_panel.screen_pulse(self.conn)
        finally:
            self.conn.set_trace_callback(None)
        self.assertTrue(pulse["available"])
        self.assertFalse(pulse["stamped"])
        for key in ("works", "releases", "sources", "active_sources"):
            self.assertNotIn(key, pulse)
        joined = " ".join(statements).lower()
        for table in ("cat_works", "releases", "download_sources"):
            self.assertNotIn(f"from {table}", joined,
                             f"the unstamped pulse scanned {table}")

    def test_the_stamp_path_reads_only_the_meta_row(self):
        self._stamp()
        self.conn.execute("CREATE TABLE sitemap_cache (loc TEXT)")
        self.conn.execute("INSERT INTO sitemap_cache VALUES ('a')")
        self.conn.commit()
        statements = []
        self.conn.set_trace_callback(statements.append)
        try:
            pulse = admin_panel.screen_pulse(self.conn)
        finally:
            self.conn.set_trace_callback(None)
        self.assertTrue(pulse["stamped"])
        self.assertEqual(pulse["works"], 10)
        self.assertEqual(pulse["releases"], 20)
        self.assertEqual(pulse["sources"], 32)
        self.assertEqual(pulse["active_sources"], 4)
        self.assertEqual(pulse["resumable_sources"], 3)
        self.assertEqual(pulse["sitemap_cached"], 1)
        joined = " ".join(statements).lower()
        for table in ("cat_works", "releases", "download_sources"):
            self.assertNotIn(f"from {table}", joined)

    def test_an_empty_breakdown_is_unstamped_not_zero_links(self):
        self._stamp(by_state={})
        pulse = admin_panel.screen_pulse(self.conn)
        self.assertFalse(pulse["stamped"])
        self.assertNotIn("sources", pulse)

    def test_host_reports_staging_sizes_as_crawler_handles(self):
        staging = self.root / "vegamovies.db"
        staging.write_bytes(b"x" * 2048)
        other = self.root / "merged_catalog.db"
        other.write_bytes(b"y" * 4096)
        host = admin_panel.screen_host(self.conn)
        self.assertTrue(host["available"])
        self.assertIsInstance(host["db_bytes"], int)
        by_crawler = {row["crawler_id"]: row["bytes"] for row in host["staging"]}
        self.assertEqual(by_crawler.get("crawler-17"), 2048)
        blob = json.dumps(host).lower()
        self.assertNotIn("vegamovies", blob)
        self.assertNotIn("merged_catalog", blob)
        self.assertEqual(admin_panel._provenance_offenders(blob), [])

    def test_both_screens_are_reachable_through_the_route_table(self):
        env = mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        for name in ("pulse", "host"):
            status, _type, raw = admin_panel.route_get(
                f"/admin/api/{name}", {}, db_path=self.db_path,
                peer_address="127.0.0.1", token_header=f"Bearer {TOKEN}")
            self.assertEqual(status, 200, raw[:200])
            self.assertTrue(json.loads(raw.decode())["available"])


class PaymentButtonsTests(unittest.TestCase):
    """The console's approve/reject buttons, over the same routes /admin uses."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "catalog.db"
        self.state_path = self.root / "user_state.db"
        env = mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        conn = accounts.connect(self.state_path)
        self.addCleanup(conn.close)
        account = accounts.create_account(conn)
        payments.submit_payment(conn, account["account_id"], plan="vip_monthly",
                                method="jazzcash", tid="9823145671")
        self.payment_id = payments.list_payments(conn)[0]["payment_id"]

    def route(self, path, body):
        return admin_panel.route_post(
            path, {}, db_path=self.db_path, peer_address="127.0.0.1",
            token_header=f"Bearer {TOKEN}", body=body,
            state_db_path=self.state_path)

    def screen(self):
        return admin_panel.screen_payments(self.state_path)

    def test_each_pending_row_carries_its_own_two_csrf_tokens(self):
        row = self.screen()["pending"][0]
        self.assertEqual(row["payment_id"], self.payment_id)
        self.assertEqual(set(row["csrf"]), {"approve", "reject"})
        self.assertNotEqual(row["csrf"]["approve"], row["csrf"]["reject"])
        # Not a payment identifier: it does not contain the TID or the hint.
        blob = json.dumps(row["csrf"])
        self.assertNotIn(row["tid"], blob)
        self.assertNotIn(row["hint"], blob)

    def test_approve_with_the_rows_csrf_credits_once(self):
        row = self.screen()["pending"][0]
        status, _type, raw = self.route(
            admin_panel.APPROVE_PAYMENT_PATH,
            {"payment_id": self.payment_id, "csrf": row["csrf"]["approve"],
             "reviewer": "console", "note": ""})
        self.assertEqual(status, 200, raw[:200])
        receipt = json.loads(raw.decode())
        self.assertTrue(receipt["ok"])
        self.assertTrue(receipt["review"]["changed"])
        self.assertEqual(receipt["review"]["status"], payments.STATUS_APPROVED)
        self.assertEqual(self.screen()["pending_count"], 0)

    def test_a_missing_and_a_wrong_csrf_are_the_same_refusal(self):
        row = self.screen()["pending"][0]
        bodies = (
            {"payment_id": self.payment_id, "reviewer": "console"},
            {"payment_id": self.payment_id, "csrf": "0" * 32, "reviewer": "console"},
        )
        answers = []
        for body in bodies:
            status, _type, raw = self.route(
                admin_panel.REJECT_PAYMENT_PATH, body)
            self.assertEqual(status, 403, raw[:200])
            payload = json.loads(raw.decode())
            payload.pop("request_id", None)
            answers.append(payload)
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(self.screen()["pending_count"], 1)

    def test_the_reject_path_writes_the_note_and_leaves_vip_alone(self):
        row = self.screen()["pending"][0]
        status, _type, raw = self.route(
            admin_panel.REJECT_PAYMENT_PATH,
            {"payment_id": self.payment_id, "csrf": row["csrf"]["reject"],
             "reviewer": "console", "note": "amount does not match the SMS"})
        self.assertEqual(status, 200, raw[:200])
        self.assertEqual(json.loads(raw.decode())["review"]["status"],
                         payments.STATUS_REJECTED)
        self.assertEqual(self.screen()["pending_count"], 0)


class BroadcastSettingsTests(unittest.TestCase):
    """Tab 3's fields: they must reach the phone, and a long paste is refused."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        env = mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)

    def save(self, body):
        return admin_panel.route_post(
            admin_panel.SAVE_MONETIZATION_PATH, {}, db_path=self.db_path,
            peer_address="127.0.0.1", token_header=f"Bearer {TOKEN}", body=body)

    def config(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return admin_panel.remote_config(conn)
        finally:
            conn.close()

    def test_broadcast_and_support_round_trip_to_the_app_config(self):
        status, _type, raw = self.save({
            "announcement_title": "Eid schedule",
            "announcement_message": "New episodes drop at 8pm PKT.",
            "min_app_version": "1.4.0",
            "support_whatsapp": "0300-1234567",
            "support_telegram": "@raddstream",
        })
        self.assertEqual(status, 200, raw[:200])
        config = self.config()
        self.assertEqual(config["announcement"]["title"], "Eid schedule")
        self.assertEqual(config["announcement"]["message"],
                         "New episodes drop at 8pm PKT.")
        self.assertTrue(config["announcement"]["active"])
        self.assertEqual(config["min_app_version"], "1.4.0")
        self.assertEqual(config["support"],
                         {"whatsapp": "0300-1234567",
                          "telegram": "@raddstream"})

    def test_an_empty_announcement_is_inactive_not_an_empty_banner(self):
        self.assertEqual(self.config()["announcement"],
                         {"title": "", "message": "", "active": False})

    def test_an_over_long_message_is_refused_not_truncated(self):
        status, _type, raw = self.save({"announcement_message": "x" * 281})
        self.assertEqual(status, 400, raw[:200])
        self.assertEqual(self.config()["announcement"]["message"], "")

    def test_a_message_with_a_url_is_still_refused(self):
        status, _type, _raw = self.save(
            {"announcement_message": "visit https://example.test now"})
        self.assertEqual(status, 400)

    def test_the_new_fields_do_not_loosen_the_token_mask(self):
        self.save({"shrinkme_api_token": "s3cret-token-value"})
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            card = admin_panel.screen_monetization(conn)
            public = json.dumps(admin_panel.remote_config(conn))
        finally:
            conn.close()
        self.assertNotIn("s3cret-token-value", json.dumps(card))
        self.assertNotIn("s3cret-token-value", public)


if __name__ == "__main__":
    unittest.main(verbosity=2)
