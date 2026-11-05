#!/usr/bin/env python3
"""The admin panel's live feed for the app: sections, broadcasts, hides.

The panel (admin v2) owns three things the phone has never read: the home
sections it builds, the broadcasts it publishes, and the works it hides. This
module is the one reader that carries them to the public edge, and it is
deliberately boring. It also carries the operator's theme knobs (dark/light,
accent, hero behaviour) from the same panel database, read-only the same way.

* Read-only. The panel database is opened ``mode=ro`` and never written, and
  the catalog connection it is handed is only ever SELECTed from.
* Fail-closed and fail-quiet. A missing panel database, a missing table, or a
  locked file answers with empty lists, never an exception — the public
  ``/api/v1/app/remote-config`` route must keep answering when the panel is
  down, and the app falls back to its own rails.
* Adult fail-closed, the same predicate the public list route already uses
  (``redact.adult_clause``): a flagged row never reaches a section. A section
  the operator marked adult-only is not served to the app at all, because the
  app has no adult mode to show it in.
* No provenance. What leaves here is a resolved post row for the caller to
  project through the same ``post_brief`` + art-pair shape every other v1 list
  already serves, plus scrubbed broadcast text. A site name, a hoster name, or
  an upstream URL cannot ride along: the section resolver never selects one.

The panel database is wired by environment only (``RADD_ADMIN_V2_DB``, see
``config.PANEL_DB_PATH``). Unset or pointing at nothing means the feature is
off, not broken: every function answers empty and the caller carries on.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

import redact

try:
    from config import PANEL_DB_PATH
except Exception:  # pragma: no cover - config is always importable in-repo
    PANEL_DB_PATH = None

#: How many panel sections the app feed ever carries, and how many works one
#: section ever carries. The panel's own preview uses the same 20-item cap.
SECTION_MAX = 12
SECTION_ITEM_CAP = 20

#: A hide list longer than this is not a hide list any more; the posts route
#: caps the exclusion at the same number so one bad row cannot build a
#: megabyte of SQL parameters.
HIDDEN_IDS_CAP = 1000


def panel_db_path():
    """The panel database to read, or None when the feature is unwired."""
    if PANEL_DB_PATH:
        return Path(PANEL_DB_PATH)
    env = os.environ.get("RADD_ADMIN_V2_DB")
    return Path(env) if env else None


def _open_panel(panel_path=None):
    """Read-only handle on the panel database, or None when it cannot open."""
    path = panel_path or panel_db_path()
    if not path:
        return None
    try:
        if not Path(path).is_file():
            return None
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _has_table(conn, name):
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,)).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _active_hides(conn, now):
    """(global_ids, section_ids): unexpired, unrestored hides.

    ``global_ids`` hides a work everywhere (scope ``work``); ``section_ids``
    hides one work inside one section (scope ``section_work``, stored as
    ``"<section_key>:<work_id>"``). A row whose expiry passed, or one the
    operator restored, hides nothing.
    """
    global_ids = set()
    section_ids = set()
    if conn is None or not _has_table(conn, "content_visibility"):
        return global_ids, section_ids
    try:
        rows = conn.execute(
            "SELECT scope, scope_id, expires_at FROM content_visibility "
            "WHERE is_hidden = 1 AND restored_at IS NULL").fetchall()
    except sqlite3.Error:
        return global_ids, section_ids
    for r in rows:
        try:
            expires = r["expires_at"]
        except (KeyError, IndexError):
            expires = None
        if expires and int(expires) < now:
            continue
        scope = r["scope"]
        scope_id = str(r["scope_id"] or "")
        if scope == "work":
            try:
                global_ids.add(int(scope_id))
            except ValueError:
                continue
        elif scope == "section_work" and ":" in scope_id:
            section_ids.add(scope_id)
    return global_ids, section_ids


def hidden_work_ids(panel_path=None, now=None):
    """Work ids the operator hid, everywhere. Never raises."""
    now = int(now if now is not None else time.time())
    conn = _open_panel(panel_path)
    if conn is None:
        return set()
    try:
        global_ids, _section_ids = _active_hides(conn, now)
        return set(sorted(global_ids)[:HIDDEN_IDS_CAP])
    finally:
        conn.close()


def _plain_text(value):
    """Broadcast copy as the phone renders it: plain text, no markup.

    The panel stores what the operator typed, and the panel page renders it
    as HTML; the app draws it in a plain text banner, where a tag would show
    up literally. Strip tags first, then scrub site tokens the same way
    every other public string is scrubbed.
    """
    text = re.sub(r"<[^>]*>", "", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return redact.scrub_text(text)


def active_broadcasts(panel_path=None, now=None):
    """Published broadcasts live right now, for every phone.

    Only ``target = 'all'`` is served: the panel also names free, VIP, region
    and version targets, and this app has no targeting to honour them with, so
    a narrower broadcast stays unpublished to the app rather than leaking to
    the wrong audience. Text is scrubbed the same way every other public
    string is.
    """
    now = int(now if now is not None else time.time())
    conn = _open_panel(panel_path)
    if conn is None:
        return []
    try:
        if not _has_table(conn, "broadcasts"):
            return []
        rows = conn.execute(
            "SELECT id, title, body, severity FROM broadcasts "
            "WHERE status = 'published' AND target = 'all' "
            "AND (starts_at IS NULL OR starts_at <= ?) "
            "AND (ends_at IS NULL OR ends_at > ?) "
            "ORDER BY id DESC", (now, now)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "id": int(r["id"]),
            "title": _plain_text(r["title"]),
            "body": _plain_text(r["body"]),
            "severity": str(r["severity"] or "info"),
        })
    return out


def _adult_ok(row):
    """The public adult predicate, in Python: only a set flag hides a row."""
    try:
        flag = row["is_18_plus"]
    except (KeyError, IndexError):
        return True
    return flag is None or int(flag) == 0


#: What the app falls back to when the panel has no theme set: dark, the
#: brand accent (empty means the app's own default), no dynamic colour, a
#: hero that auto-advances every 5 s, at most 6 slides.
THEME_DEFAULTS = {
    "mode": "dark", "accent": "", "dynamic_color": False,
    "hero_autoplay": True, "hero_interval_s": 5, "hero_max": 6,
}

_THEMES_MODES = ("dark", "light", "system")


def _theme_col(row, name):
    """One tuning column, or None when the panel predates the column."""
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def read_theme(panel_path=None):
    """Operator theme knobs for the app, or safe defaults. Never raises.

    Reads ``tuning_settings`` from the panel database, read-only. A missing
    database, table, row or column answers defaults; an out-of-range value
    answers its own default, never the operator's typo. The app treats an
    empty accent as "use the brand default".
    """
    out = dict(THEME_DEFAULTS)
    conn = _open_panel(panel_path)
    if conn is None:
        return out
    try:
        if not _has_table(conn, "tuning_settings"):
            return out
        try:
            row = conn.execute(
                "SELECT theme_mode, theme_accent, theme_dynamic_color, "
                "theme_hero_autoplay, theme_hero_interval_s, hero_max "
                "FROM tuning_settings WHERE id = 1").fetchone()
        except sqlite3.Error:
            return out
        if row is None:
            return out
        mode = _theme_col(row, "theme_mode")
        if isinstance(mode, str) and mode in _THEMES_MODES:
            out["mode"] = mode
        accent = _theme_col(row, "theme_accent")
        if isinstance(accent, str) and accent:
            if (len(accent) == 7 and accent[0] == "#"
                    and all(c in "0123456789abcdefABCDEF" for c in accent[1:])):
                out["accent"] = accent
        for key, col in (("dynamic_color", "theme_dynamic_color"),
                         ("hero_autoplay", "theme_hero_autoplay")):
            try:
                out[key] = int(_theme_col(row, col) or 0) == 1
            except (TypeError, ValueError):
                pass
        try:
            interval = int(_theme_col(row, "theme_hero_interval_s") or 0)
            if 1 <= interval <= 30:
                out["hero_interval_s"] = interval
        except (TypeError, ValueError):
            pass
        try:
            hero_max = int(_theme_col(row, "hero_max") or 0)
            if 0 <= hero_max <= 6:
                out["hero_max"] = hero_max
        except (TypeError, ValueError):
            pass
        return out
    finally:
        conn.close()


def _resolve_rows(catalog_conn, rule, category_key, curated_ids, limit, hidden):
    """Post rows for one section rule, adult-filtered and hide-filtered.

    ``curated_ids`` is only read for the ``curated`` rule; every other rule
    resolves against the catalog itself. The returned rows keep catalog order
    (newest first, or the card order for a curated section).
    """
    if rule == "curated":
        ids = [int(i) for i in (curated_ids or []) if str(i).strip()]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        try:
            rows = catalog_conn.execute(
                "SELECT * FROM posts WHERE id IN (%s)" % placeholders,
                ids).fetchall()
        except sqlite3.Error:
            return []
        by_id = {int(r["id"]): r for r in rows}
        ordered = [by_id[i] for i in ids if i in by_id]
    else:
        try:
            if rule == "trending" and _has_table(catalog_conn, "cat_works"):
                cols = [c[1] for c in catalog_conn.execute(
                    "PRAGMA table_info(cat_works)").fetchall()]
                if "best_quality_score" in cols and "work_key" in cols:
                    order = ("w.best_quality_score DESC, w.release_count DESC"
                             if "release_count" in cols
                             else "w.best_quality_score DESC")
                    rows = catalog_conn.execute(
                        "SELECT p.* FROM posts p JOIN cat_works w "
                        "ON w.work_key = p.canonical_key "
                        "ORDER BY %s LIMIT ?" % order, (limit,)).fetchall()
                else:
                    rows = catalog_conn.execute(
                        "SELECT * FROM posts ORDER BY id DESC LIMIT ?",
                        (limit,)).fetchall()
            elif rule == "category" and category_key:
                rows = catalog_conn.execute(
                    "SELECT * FROM posts WHERE "
                    "(genres LIKE ? OR content_type = ?) "
                    "ORDER BY id DESC LIMIT ?",
                    ("%" + category_key + "%", category_key, limit)).fetchall()
            else:
                rows = catalog_conn.execute(
                    "SELECT * FROM posts ORDER BY id DESC LIMIT ?",
                    (limit,)).fetchall()
        except sqlite3.Error:
            return []
        ordered = list(rows)
    out = []
    for r in ordered:
        if not _adult_ok(r):
            continue
        try:
            if int(r["id"]) in hidden:
                continue
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def load_panel_feed(catalog_conn, panel_path=None, now=None):
    """Sections, broadcasts and hides for the app feed.

    ``catalog_conn`` is the catalog connection the caller already holds;
    ``panel_path`` overrides the configured panel database. The sections carry
    raw post rows under ``rows`` — the caller projects them through the same
    ``post_brief`` + art-pair shape the posts route serves, because this
    module owns resolution and filtering, not the wire shape.
    """
    now = int(now if now is not None else time.time())
    empty = {"sections": [], "broadcasts": [], "hidden_work_ids": []}
    panel = _open_panel(panel_path)
    if panel is None:
        return empty
    try:
        global_hidden, section_hidden = _active_hides(panel, now)
        hidden = set(sorted(global_hidden)[:HIDDEN_IDS_CAP])
        if not _has_table(panel, "home_sections"):
            return {"sections": [], "broadcasts": active_broadcasts(panel_path, now),
                    "hidden_work_ids": sorted(hidden)}
        try:
            sections = panel.execute(
                "SELECT * FROM home_sections WHERE is_enabled = 1 "
                "ORDER BY position ASC, id ASC LIMIT ?",
                (SECTION_MAX,)).fetchall()
        except sqlite3.Error:
            return {"sections": [], "broadcasts": active_broadcasts(panel_path, now),
                    "hidden_work_ids": sorted(hidden)}
        out_sections = []
        for sec in sections:
            try:
                if int(sec["is_adult_only"] or 0):
                    continue
                key = str(sec["key"])
                title = redact.scrub_text(str(sec["title"] or ""))
                rule = str(sec["source_rule"] or "latest")
                category_key = sec["category_key"]
            except (KeyError, IndexError):
                continue
            curated_ids = []
            if rule == "curated" and _has_table(panel, "slider_cards"):
                try:
                    cards = panel.execute(
                        "SELECT work_id FROM slider_cards "
                        "WHERE section_id = ? AND is_enabled = 1 "
                        "AND (starts_at IS NULL OR starts_at <= ?) "
                        "AND (ends_at IS NULL OR ends_at > ?) "
                        "ORDER BY position ASC, id ASC",
                        (sec["id"], now, now)).fetchall()
                    curated_ids = [c["work_id"] for c in cards]
                except sqlite3.Error:
                    curated_ids = []
            section_hide = {
                int(suffix) for tag in section_hidden
                if tag.startswith(key + ":")
                for suffix in [tag[len(key) + 1:]]
                if suffix.isdigit()
            }
            rows = _resolve_rows(
                catalog_conn, rule, category_key, curated_ids,
                SECTION_ITEM_CAP, hidden | section_hide)
            out_sections.append({"key": key, "title": title, "rows": rows})
        return {"sections": out_sections,
                "broadcasts": active_broadcasts(panel_path, now),
                "hidden_work_ids": sorted(hidden)}
    finally:
        panel.close()
