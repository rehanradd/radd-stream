#!/usr/bin/env python3
"""The public contact intake: `POST /api/v1/contact` writes where the panel reads.

The panel already has the inbox — `contact_messages` in the admin database,
listed and triaged from `/admin` (`services.list_contact` / `update_contact`).
What it never had is a public way in: its own `create_contact` needs an
operator actor, and the app had no form at all. This module is the public
way in, and it writes the same table with the same rules, so a message the
app sends lands in the same inbox, under the same validation, as one the
operator typed:

* category must be one of the panel's five (`CONTACT_CATEGORIES`);
* the body must be non-empty, and is cut at 2000 characters;
* the subject is cut at 200 characters;
* the contact hint (an email the viewer may leave so the operator can reply)
  is stored masked, first 2 + ``***`` + last 2 — never the full address —
  exactly like the panel's `security.mask_hint`;
* markup is stripped and URLs are replaced, so the inbox never renders a
  link or a tag a stranger typed.

The write goes straight to the panel database (read-write, short timeout),
because the panel's own intake needs an operator actor the public server
cannot hold. The table is the only thing this module touches, and a panel
that is missing, unwired or locked answers "unavailable" — the caller gets
an honest 503 to retry, never a message swallowed into a void. Nothing here
raises: every failure is a code.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time

import panel_feed

#: The panel's own five categories (`admin_v2/services.py CONTACT_CATEGORIES`).
CONTACT_CATEGORIES = frozenset({"bug", "payment", "content", "takedown", "other"})

#: The same limits the panel's `create_contact` enforces.
SUBJECT_LIMIT = 200
BODY_LIMIT = 2000

_TAG_RE = re.compile(r"<[^>]*>")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_WS_RE = re.compile(r"\s+")


def _clean(text, limit):
    """Plain text, no markup, no live links, cut at `limit`."""
    out = _TAG_RE.sub("", str(text or ""))
    out = _URL_RE.sub("[link removed]", out)
    out = _WS_RE.sub(" ", out).strip()
    return out[:limit]


def _mask_hint(value):
    """Truncated contact hint: first 2 and last 2 characters only.

    The panel's `security.mask_hint`, copied so the two writers can never
    drift apart: a short hint shows its first character plus stars, an empty
    one stores empty.
    """
    if not value:
        return ""
    v = str(value).strip()
    if not v:
        return ""
    if len(v) <= 4:
        return v[:1] + "***"
    return v[:2] + "***" + v[-2:]


def submit_contact(panel_path=None, *, category, subject, body, account_hint=None):
    """Store one contact message in the panel's inbox.

    Returns ``(True, row_id)`` on success, ``(False, code)`` otherwise:
    ``"invalid_params"`` for a category outside the panel's five or an empty
    or over-long body, ``"unavailable"`` when the panel database or its
    `contact_messages` table is missing, or the write fails (locked included).
    """
    if category not in CONTACT_CATEGORIES:
        return False, "invalid_params"
    clean_body = _clean(body, BODY_LIMIT)
    if not clean_body:
        return False, "invalid_params"
    clean_subject = _clean(subject, SUBJECT_LIMIT)
    hint = _mask_hint(account_hint)
    path = panel_path or panel_feed.panel_db_path()
    if not path or not os.path.exists(path):
        return False, "unavailable"
    try:
        conn = sqlite3.connect(path, timeout=5.0)
    except sqlite3.Error:
        return False, "unavailable"
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "contact_messages" not in tables:
            return False, "unavailable"
        try:
            cur = conn.execute(
                "INSERT INTO contact_messages "
                "(app_account_hint, category, subject, body, status, "
                "linked_report_id, linked_work_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (hint, category, clean_subject, clean_body, "open",
                 None, None, int(time.time())))
            conn.commit()
        except sqlite3.Error:
            return False, "unavailable"
        return True, cur.lastrowid
    finally:
        conn.close()
