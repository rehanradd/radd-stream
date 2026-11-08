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

import hashlib
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

#: The public form is unauthenticated, so it is the one surface a bot can
#: hammer for free. Two cheap controls, both in the panel database next to
#: the inbox they protect:
#: * a honeypot field named `website` — a human form leaves it empty, and
#:   the app does not send it at all, so a filled one is a bot, answered
#:   with a silent success (nothing written, nothing learned);
#: * a per-address daily budget (`CONTACT_IP_DAILY_LIMIT` messages a day)
#:   plus a same-day dedup on the body hash, so one address cannot flood
#:   the inbox and a double-tap cannot file the same message twice.
#: The address is stored as a SHA-256 hash, never raw, and a caller with no
#: address (a direct library call, the operator's own tooling) is charged
#: nothing — the budget is an edge control.
CONTACT_IP_DAILY_LIMIT = 10

_BUDGET_DDL = """
CREATE TABLE IF NOT EXISTS contact_ip_budget (
    ip_hash TEXT PRIMARY KEY,
    day_bucket TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    last_body_hash TEXT,
    last_body_at REAL
)
"""

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


def _day_bucket(now):
    """The UTC calendar day, `YYYY-MM-DD`: the budget's day boundary. UTC,
    not Karachi — a spam cap is an edge control, not a viewer-facing day,
    and the boundary only has to be stable and shared."""
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _ip_hash(client_ip):
    text = str(client_ip or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def submit_contact(panel_path=None, *, category, subject, body, account_hint=None,
                   client_ip=None, honeypot=None, now=None):
    """Store one contact message in the panel's inbox.

    Returns ``(True, row_id)`` on success, ``(False, code)`` otherwise:
    ``"invalid_params"`` for a category outside the panel's five or an empty
    or over-long body, ``"unavailable"`` when the panel database or its
    `contact_messages` table is missing, or the write fails (locked included),
    ``"rate_limited"`` when one address already sent
    `CONTACT_IP_DAILY_LIMIT` messages today. A filled honeypot or a
    same-day duplicate of a message this address already sent answers
    `(True, None)`: success to the caller, nothing written — the first so a
    bot learns nothing, the second so a double-tap files nothing twice.
    """
    if category not in CONTACT_CATEGORIES:
        return False, "invalid_params"
    clean_body = _clean(body, BODY_LIMIT)
    if not clean_body:
        return False, "invalid_params"
    clean_subject = _clean(subject, SUBJECT_LIMIT)
    hint = _mask_hint(account_hint)
    moment = time.time() if now is None else float(now)
    if str(honeypot or "").strip():
        # A bot filled the field a human never sees. Answer success and
        # write nothing: an error would teach it which field gave it away.
        return True, None
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
        ip_hash = _ip_hash(client_ip)
        if ip_hash is not None:
            conn.execute(_BUDGET_DDL)
            bucket = _day_bucket(moment)
            body_hash = hashlib.sha256(
                clean_body.encode("utf-8")).hexdigest()
            row = conn.execute(
                "SELECT day_bucket, count, last_body_hash FROM contact_ip_budget"
                " WHERE ip_hash = ?", (ip_hash,)).fetchone()
            if row is not None and row[0] == bucket:
                if row[2] == body_hash:
                    # Already in the inbox today: success, no second row.
                    return True, None
                if int(row[1]) >= CONTACT_IP_DAILY_LIMIT:
                    return False, "rate_limited"
                conn.execute(
                    "UPDATE contact_ip_budget SET count = count + 1,"
                    " last_body_hash = ?, last_body_at = ? WHERE ip_hash = ?",
                    (body_hash, moment, ip_hash))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO contact_ip_budget"
                    "(ip_hash, day_bucket, count, last_body_hash, last_body_at)"
                    " VALUES(?, ?, 1, ?, ?)",
                    (ip_hash, bucket, body_hash, moment))
        try:
            cur = conn.execute(
                "INSERT INTO contact_messages "
                "(app_account_hint, category, subject, body, status, "
                "linked_report_id, linked_work_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (hint, category, clean_subject, clean_body, "open",
                 None, None, int(moment)))
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            return False, "unavailable"
        return True, cur.lastrowid
    finally:
        conn.close()
