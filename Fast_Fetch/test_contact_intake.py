#!/usr/bin/env python3
"""Tests for the public contact intake (`contact_intake.py`).

The fixture is the panel's own table, built the way the panel builds it
(`contact_messages` as in `admin_v2/store.py`): every assertion names the
exact row that must appear, and the exact value that must be stored — above
all the contact hint, which must never reach the table unmasked.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

import contact_intake


def _build_panel(path, with_table=True):
    conn = sqlite3.connect(path)
    if with_table:
        conn.execute(
            "CREATE TABLE contact_messages ("
            "id INTEGER PRIMARY KEY, app_account_hint TEXT, "
            "category TEXT NOT NULL DEFAULT 'other', subject TEXT, body TEXT, "
            "status TEXT NOT NULL DEFAULT 'open', linked_report_id INTEGER, "
            "linked_work_id INTEGER, created_at INTEGER, resolved_at INTEGER, "
            "resolved_by INTEGER, internal_note TEXT)")
    conn.commit()
    conn.close()


class ContactIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.panel_path = os.path.join(self.tmp.name, "admin_v2.db")
        _build_panel(self.panel_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self):
        conn = sqlite3.connect(self.panel_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM contact_messages").fetchall()
        conn.close()
        return rows

    def test_valid_message_lands_open_with_masked_hint(self):
        ok, row_id = contact_intake.submit_contact(
            self.panel_path, category="bug", subject="Play fails",
            body="The film stops after ten seconds.",
            account_hint="rehan@example.com")
        self.assertTrue(ok)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], row_id)
        self.assertEqual(rows[0]["category"], "bug")
        self.assertEqual(rows[0]["subject"], "Play fails")
        self.assertEqual(rows[0]["body"], "The film stops after ten seconds.")
        self.assertEqual(rows[0]["status"], "open")
        # The full address never reaches the table.
        self.assertEqual(rows[0]["app_account_hint"], "re***om")
        self.assertNotIn("example.com", rows[0]["app_account_hint"])
        self.assertIsNotNone(rows[0]["created_at"])

    def test_markup_stripped_and_links_removed(self):
        ok, _ = contact_intake.submit_contact(
            self.panel_path, category="content", subject="<b>Hi</b>",
            body="See https://evil.example/x and <script>alert(1)</script> thanks",
            account_hint=None)
        self.assertTrue(ok)
        row = self._rows()[0]
        self.assertNotIn("<", row["subject"])
        self.assertNotIn("<", row["body"])
        self.assertNotIn("evil.example", row["body"])
        self.assertIn("[link removed]", row["body"])

    def test_unknown_category_is_refused(self):
        ok, code = contact_intake.submit_contact(
            self.panel_path, category="complaint", subject="x",
            body="Hello", account_hint=None)
        self.assertFalse(ok)
        self.assertEqual(code, "invalid_params")
        self.assertEqual(self._rows(), [])

    def test_empty_body_is_refused(self):
        for body in ("", "   ", None):
            ok, code = contact_intake.submit_contact(
                self.panel_path, category="other", subject="x",
                body=body, account_hint=None)
            self.assertFalse(ok)
            self.assertEqual(code, "invalid_params")
        self.assertEqual(self._rows(), [])

    def test_long_body_is_cut_not_refused(self):
        # The panel truncates at its limit too; the intake matches it.
        ok, _ = contact_intake.submit_contact(
            self.panel_path, category="other", subject="x",
            body="a" * 2500, account_hint=None)
        self.assertTrue(ok)
        self.assertEqual(len(self._rows()[0]["body"]), 2000)

    def test_short_hint_masks_to_first_char(self):
        ok, _ = contact_intake.submit_contact(
            self.panel_path, category="other", subject="x",
            body="Hello", account_hint="abc")
        self.assertTrue(ok)
        self.assertEqual(self._rows()[0]["app_account_hint"], "a***")

    def test_missing_panel_db_is_unavailable(self):
        ok, code = contact_intake.submit_contact(
            os.path.join(self.tmp.name, "nope.db"), category="bug",
            subject="x", body="Hello", account_hint=None)
        self.assertFalse(ok)
        self.assertEqual(code, "unavailable")

    def test_missing_table_is_unavailable(self):
        empty_path = os.path.join(self.tmp.name, "empty.db")
        _build_panel(empty_path, with_table=False)
        ok, code = contact_intake.submit_contact(
            empty_path, category="bug", subject="x", body="Hello",
            account_hint=None)
        self.assertFalse(ok)
        self.assertEqual(code, "unavailable")

    # ── the spam controls ────────────────────────────────────────────────
    def test_a_filled_honeypot_is_a_silent_success_that_writes_nothing(self):
        """A bot fills the `website` field a human form never sends. It is
        answered with success — an error would teach it which field gave it
        away — and nothing reaches the inbox."""
        ok, row_id = contact_intake.submit_contact(
            self.panel_path, category="bug", subject="x", body="Hello",
            account_hint=None, client_ip="203.0.113.7",
            honeypot="https://spam.example")
        self.assertTrue(ok)
        self.assertIsNone(row_id)
        self.assertEqual(self._rows(), [])

    def test_ten_messages_a_day_per_address_then_the_eleventh_is_refused(self):
        ip = "203.0.113.7"
        for i in range(contact_intake.CONTACT_IP_DAILY_LIMIT):
            ok, _ = contact_intake.submit_contact(
                self.panel_path, category="other", subject="x",
                body="Message %d" % i, account_hint=None, client_ip=ip)
            self.assertTrue(ok, i)
        ok, code = contact_intake.submit_contact(
            self.panel_path, category="other", subject="x",
            body="Message eleven", account_hint=None, client_ip=ip)
        self.assertFalse(ok)
        self.assertEqual(code, "rate_limited")
        self.assertEqual(len(self._rows()),
                         contact_intake.CONTACT_IP_DAILY_LIMIT)

    def test_the_same_message_twice_from_one_address_files_once(self):
        ip = "203.0.113.8"
        for _ in range(2):
            ok, _ = contact_intake.submit_contact(
                self.panel_path, category="bug", subject="x",
                body="The film stops after ten seconds.",
                account_hint=None, client_ip=ip)
            self.assertTrue(ok)
        self.assertEqual(len(self._rows()), 1)
        # The duplicate did not spend the budget either: ten distinct
        # messages still fit after it.
        for i in range(9):
            ok, _ = contact_intake.submit_contact(
                self.panel_path, category="other", subject="x",
                body="Distinct %d" % i, account_hint=None, client_ip=ip)
            self.assertTrue(ok, i)
        self.assertEqual(len(self._rows()), 10)

    def test_a_second_address_has_its_own_budget(self):
        for i in range(contact_intake.CONTACT_IP_DAILY_LIMIT):
            ok, _ = contact_intake.submit_contact(
                self.panel_path, category="other", subject="x",
                body="Message %d" % i, account_hint=None,
                client_ip="203.0.113.9")
            self.assertTrue(ok, i)
        ok, _ = contact_intake.submit_contact(
            self.panel_path, category="other", subject="x", body="Hello",
            account_hint=None, client_ip="203.0.113.10")
        self.assertTrue(ok)

    def test_the_budget_resets_the_next_day(self):
        ip = "203.0.113.11"
        day_one = 1_800_000_000.0
        for i in range(contact_intake.CONTACT_IP_DAILY_LIMIT):
            ok, _ = contact_intake.submit_contact(
                self.panel_path, category="other", subject="x",
                body="Message %d" % i, account_hint=None, client_ip=ip,
                now=day_one)
            self.assertTrue(ok, i)
        ok, code = contact_intake.submit_contact(
            self.panel_path, category="other", subject="x",
            body="One more today", account_hint=None, client_ip=ip,
            now=day_one)
        self.assertFalse(ok)
        self.assertEqual(code, "rate_limited")
        ok, _ = contact_intake.submit_contact(
            self.panel_path, category="other", subject="x",
            body="Tomorrow", account_hint=None, client_ip=ip,
            now=day_one + 86_400)
        self.assertTrue(ok)

    def test_no_address_means_no_budget_and_no_dedup(self):
        """A direct library call carries no address, so it is charged
        nothing: eleven identical messages all land, exactly as before
        this release."""
        for _ in range(contact_intake.CONTACT_IP_DAILY_LIMIT + 1):
            ok, _ = contact_intake.submit_contact(
                self.panel_path, category="other", subject="x",
                body="Same message", account_hint=None)
            self.assertTrue(ok)
        self.assertEqual(len(self._rows()),
                         contact_intake.CONTACT_IP_DAILY_LIMIT + 1)

    def test_the_address_is_stored_hashed_never_raw(self):
        ip = "203.0.113.12"
        contact_intake.submit_contact(
            self.panel_path, category="bug", subject="x", body="Hello",
            account_hint=None, client_ip=ip)
        conn = sqlite3.connect(self.panel_path)
        row = conn.execute("SELECT ip_hash FROM contact_ip_budget").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertNotIn(ip, row[0])
        self.assertEqual(len(row[0]), 64)  # sha256 hex


if __name__ == "__main__":
    unittest.main()
