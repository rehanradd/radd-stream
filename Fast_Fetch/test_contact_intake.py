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


if __name__ == "__main__":
    unittest.main()
