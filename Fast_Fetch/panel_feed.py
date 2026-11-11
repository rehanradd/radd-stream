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

import json
import os
import re
import sqlite3
import time
from pathlib import Path

import redact
import title_clean
import db_pragmas  # serve-path SQLite pragmas (Session 125)

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
        # Session 125: serve-path pragmas (read-only handle — the helper
        # guards journal_mode). Inside the try so a pragma failure still
        # answers None, the fail-quiet contract of this module. The
        # busy_timeout stays 5000 ms — this handle's live value (sqlite's
        # default): the panel database is neither the catalog nor the
        # user-state DB, and no rule in this batch re-times it.
        db_pragmas.apply_serve_pragmas(conn, busy_timeout_ms=5000)
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

    Every target rides along — the APP filters by its own region, tier and
    version, because only the phone knows those. A broadcast whose target
    the app cannot read is dropped here, never served half-targeted: a
    `region` row with no region, or a `version` row with no version, stays
    unpublished to the app rather than leaking to the wrong audience. Text
    is scrubbed the same way every other public string is. A broadcast the
    operator PAUSED (`pauses`, target_type `broadcast`, target_id the
    broadcast id) is omitted even though it is published — a pause is a
    stop, and the panel's own list enforces the same rule.
    """
    now = int(now if now is not None else time.time())
    conn = _open_panel(panel_path)
    if conn is None:
        return []
    try:
        if not _has_table(conn, "broadcasts"):
            return []
        paused = {target_id for target_type, target_id in _paused_targets(conn)
                  if target_type == "broadcast"}
        try:
            rows = conn.execute(
                "SELECT id, title, body, severity, target, target_detail FROM broadcasts "
                "WHERE status = 'published' "
                "AND (starts_at IS NULL OR starts_at <= ?) "
                "AND (ends_at IS NULL OR ends_at > ?) "
                "ORDER BY id DESC", (now, now)).fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    out = []
    for r in rows:
        if str(r["id"]) in paused:
            continue
        try:
            target = str(r["target"] or "all").strip().lower()
        except (KeyError, IndexError):
            target = "all"
        try:
            detail = str(r["target_detail"] or "").strip()
        except (KeyError, IndexError):
            detail = ""
        if target not in ("all", "free", "vip", "region", "version"):
            continue
        if target in ("region", "version") and not detail:
            continue
        out.append({
            "id": int(r["id"]),
            "title": _plain_text(r["title"]),
            "body": _plain_text(r["body"]),
            "severity": str(r["severity"] or "info"),
            "target": target,
            "target_detail": detail,
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


#: The tabs the bottom bar shows, in the operator's order, as set in
#: `tuning_settings.tabs` (a comma list). The app's own five are the default;
#: Home is pinned first by the APP, not here — the server only validates.
#: `live_tv` joins the default list because the app ships a Live TV screen
#: and the panel now carries the channels (17 on, 18 off): a panel that never
#: set its tabs still shows the tab. The order matches the panel's own
#: stored default (home, search, my_list, settings, live_tv).
TABS_DEFAULT = ["home", "search", "my_list", "settings", "live_tv"]
TAB_IDS = frozenset(TABS_DEFAULT)


def _tuning_int(conn, name, default, lo, hi):
    """One INTEGER tuning value, clamped to the panel's own bounds.

    A missing table, row or column answers the default; a non-integer or
    out-of-range value answers the nearest bound, never the operator's typo.
    """
    try:
        if not _has_table(conn, "tuning_settings"):
            return default
        row = conn.execute(
            "SELECT %s FROM tuning_settings WHERE id = 1" % name).fetchone()
    except sqlite3.Error:
        return default
    if row is None:
        return default
    try:
        value = int(_theme_col(row, name) or 0)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def read_section_caps(panel_path=None):
    """How many home sections, and how many works one section carries.

    The operator's `home_sections_max` / `section_cap` tuning keys, clamped
    to the panel's own bounds (1..12 sections, 5..50 works). A panel that
    predates the keys answers the shipped caps — the feed never grows
    unbounded because a row is missing.
    """
    conn = _open_panel(panel_path)
    if conn is None:
        return {"sections_max": SECTION_MAX, "section_cap": SECTION_ITEM_CAP}
    try:
        return {
            "sections_max": _tuning_int(conn, "home_sections_max", SECTION_MAX, 1, 12),
            "section_cap": _tuning_int(conn, "section_cap", SECTION_ITEM_CAP, 5, 50),
        }
    finally:
        conn.close()


def read_free_quality_cap(panel_path=None):
    """The best picture a free viewer may play: "480p" or "720p".

    The operator's `free_quality_cap` tuning key. Anything else — a missing
    key, a typo, an older panel — answers the shipped "720p", never a
    stricter cap the operator did not ask for.
    """
    conn = _open_panel(panel_path)
    if conn is None:
        return "720p"
    try:
        if not _has_table(conn, "tuning_settings"):
            return "720p"
        try:
            row = conn.execute(
                "SELECT free_quality_cap FROM tuning_settings WHERE id = 1").fetchone()
        except sqlite3.Error:
            return "720p"
        if row is None:
            return "720p"
        cap = _theme_col(row, "free_quality_cap")
        return cap if isinstance(cap, str) and cap in ("480p", "720p") else "720p"
    finally:
        conn.close()


def _published_snapshot(panel_path=None):
    """The latest PUBLISHED config snapshot, or None.

    The panel's publish is a real gate: `_do_publish` writes one row per
    publish into ``app_remote_config_history`` with the whole published
    config (``{"config": {...}, "home": {"sections": [...], ...}}``) as
    ``snapshot_json``. The draft never lands here, so whatever this returns
    is what the operator actually published — and a panel that never
    published answers None, which every caller reads as "no publication
    yet". Never raises: a missing table, a bad row, or bad JSON is None.
    """
    conn = _open_panel(panel_path)
    if conn is None:
        return None
    try:
        if not _has_table(conn, "app_remote_config_history"):
            return None
        try:
            row = conn.execute(
                "SELECT snapshot_json FROM app_remote_config_history "
                "ORDER BY config_version DESC LIMIT 1").fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            snap = json.loads(row["snapshot_json"])
        except (TypeError, ValueError):
            return None
        return snap if isinstance(snap, dict) else None
    finally:
        conn.close()


def read_min_version(panel_path=None):
    """The lowest app version code the operator still supports, or 0.

    Read from the latest PUBLISHED config snapshot — the draft does not
    count, because an unpublished minimum is not a minimum yet. A panel
    with no publish history, a missing table, or an unreadable snapshot
    answers 0, which the app reads as "no minimum".
    """
    snap = _published_snapshot(panel_path)
    if snap is None:
        return 0
    try:
        version = int(snap.get("config", {}).get("min_version_code") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0
    return version if version >= 0 else 0


#: The regions a `region_order` list may name, in the panel's own order.
#: Anything else in the stored list is dropped, never served to the app.
REGION_ORDER_KNOWN = ("pakistan", "india", "asia", "international")

#: The force-update block the app reads from the published snapshot, and
#: the safe answer when nothing was ever published. A null latest code is
#: "no latest published"; an empty name is "no name published"; force off
#: is "do not force". The brand colours are empty until the operator sets
#: them (the app falls back to its own brand), and the region order is an
#: empty list until published.
FORCE_UPDATE_DEFAULTS = {
    "latest_version_code": 0,
    "latest_version_name": "",
    "force_update": False,
    "force_update_message": "",
    "maintenance_message": "",
    "brand_primary": "",
    "brand_accent": "",
    "region_order": [],
}


def read_force_update(panel_path=None):
    """The operator's published force-update block, or safe defaults.

    Read from the latest PUBLISHED config snapshot — the same snapshot
    `read_min_version` reads — so a force-update the operator drafted but
    never published never reaches a phone. `latest_version_code` /
    `latest_version_name` name the newest APK the operator published;
    `force_update` says whether an older app must update before it may
    play; the two messages are the copy the app shows for a forced update
    and for maintenance; `brand_primary` / `brand_accent` are the operator's
    brand colours (empty means the app's own brand); `region_order` is the
    operator's region priority as a list. A panel that never published, a
    missing table, or an unreadable snapshot answers the defaults — the app
    reads that as "no update published, no force, own brand, no order".
    Never raises.
    """
    out = dict(FORCE_UPDATE_DEFAULTS)
    out["region_order"] = []
    snap = _published_snapshot(panel_path)
    if snap is None:
        return out
    try:
        cfg = snap.get("config") or {}
    except AttributeError:
        return out
    if not isinstance(cfg, dict):
        return out
    try:
        latest = int(cfg.get("latest_version_code") or 0)
        if latest >= 0:
            out["latest_version_code"] = latest
    except (TypeError, ValueError):
        pass
    name = cfg.get("latest_version_name")
    if isinstance(name, str) and name.strip():
        out["latest_version_name"] = name.strip()[:64]
    try:
        out["force_update"] = int(cfg.get("force_update") or 0) == 1
    except (TypeError, ValueError):
        pass
    for key in ("force_update_message", "maintenance_message"):
        text = cfg.get(key)
        if isinstance(text, str) and text.strip():
            out[key] = redact.scrub_text(text.strip())[:500]
    for key in ("brand_primary", "brand_accent"):
        colour = cfg.get(key)
        if (isinstance(colour, str) and len(colour) == 7 and colour[0] == "#"
                and all(c in "0123456789abcdefABCDEF" for c in colour[1:])):
            out[key] = colour
    order = cfg.get("region_order")
    if isinstance(order, str) and order.strip():
        seen = []
        for part in order.split(","):
            region = part.strip().lower()
            if region in REGION_ORDER_KNOWN and region not in seen:
                seen.append(region)
        out["region_order"] = seen
    elif isinstance(order, list):
        seen = []
        for part in order:
            region = str(part or "").strip().lower()
            if region in REGION_ORDER_KNOWN and region not in seen:
                seen.append(region)
        out["region_order"] = seen
    return out


#: The 11 tuning knobs the panel stores and the backend now applies, with
#: the panel's own safe bounds and seed defaults (store.py TUNING_DEFAULTS,
#: services.py TUNING_BOUNDS — the panel refuses a save outside these
#: bounds, so a stored value is already inside them; the clamp here is
#: defence for a panel database that predates the bounds, and the default
#: is the answer when the panel is unwired or the column is missing).
#: The bound is the operator's safe range, not a suggestion: a consumer
#: must use the clamped value, never the raw stored one.
TUNING_KNOBS = {
    "resolver_concurrency": (2, 1, 4),
    "candidate_cap": (10, 3, 20),
    "cache_ttl_h": (6, 1, 24),
    "warmup_count": (50, 0, 200),
    "warmup_interval_h": (24, 6, 168),
    "rate_limit_play_per_min": (30, 10, 120),
    "import_cap": (25, 10, 1000),
    "import_concurrency": (1, 1, 3),
    "prefetch_queue": (100, 0, 500),
    "prefetch_concurrency": (1, 1, 2),
    "domain_check_interval_min": (60, 30, 1440),
}


def read_tuning_knobs(panel_path=None):
    """The operator's 11 tuning knobs, clamped to the panel's own bounds.

    Reads ``tuning_settings`` (id = 1), read-only, the same tolerant
    pattern as :func:`read_theme`: a missing database, table, row or
    column answers the panel's seed default for that knob; a non-integer
    or out-of-range value answers the nearest bound. Every knob has a
    consumer now (see the callers): resolver_concurrency caps the batch
    resolver's workers, candidate_cap caps the play route's candidate
    prints, cache_ttl_h caps the resolved-cache temporary horizon,
    warmup_count / warmup_interval_h drive the prefetch pool's sweep,
    rate_limit_play_per_min is the play bucket, import_cap /
    import_concurrency bound the sync, prefetch_queue /
    prefetch_concurrency bound the pool, and domain_check_interval_min
    is the domain re-verify interval. Never raises.
    """
    out = {name: default for name, (default, _lo, _hi) in TUNING_KNOBS.items()}
    conn = _open_panel(panel_path)
    if conn is None:
        return out
    try:
        if not _has_table(conn, "tuning_settings"):
            return out
        try:
            row = conn.execute(
                "SELECT %s FROM tuning_settings WHERE id = 1"
                % ", ".join(TUNING_KNOBS)).fetchone()
        except sqlite3.Error:
            return out
        if row is None:
            return out
        for name, (default, lo, hi) in TUNING_KNOBS.items():
            try:
                value = int(_theme_col(row, name) or 0)
            except (TypeError, ValueError):
                continue
            out[name] = max(lo, min(hi, value))
        return out
    finally:
        conn.close()


#: The pause targets the panel can pause (services.py PAUSE_TARGETS), and
#: what each one stops in the backend. A pause row is live while
#: ``is_paused = 1`` and ``resumed_at IS NULL``; a resumed row stops
#: nothing. The target_id is the panel's own spelling: a broadcast id, a
#: section key, a category key, a feature name, a source name.
PAUSE_TARGETS = (
    "import_global", "prefetch_global", "source", "section", "category",
    "feature", "broadcast", "domain_checks",
)


def _paused_targets(conn):
    """{(target_type, target_id)}: the pauses live right now.

    Only rows with ``is_paused = 1`` and no ``resumed_at`` count — a
    resumed pause is history, not a stop. An unknown target type is
    carried anyway (the panel is the authority on what it paused); the
    consumers only act on the types they know.
    """
    out = set()
    if conn is None or not _has_table(conn, "pauses"):
        return out
    try:
        rows = conn.execute(
            "SELECT target_type, target_id FROM pauses "
            "WHERE is_paused = 1 AND resumed_at IS NULL").fetchall()
    except sqlite3.Error:
        return out
    for r in rows:
        try:
            target_type = str(r["target_type"] or "").strip()
            target_id = str(r["target_id"] or "").strip()
        except (KeyError, IndexError):
            continue
        if target_type and target_id:
            out.add((target_type, target_id))
    return out


def is_paused(panel_path=None, target_type=None, target_id=None):
    """True when the panel paused this target. Never raises.

    ``target_type`` is one of PAUSE_TARGETS and ``target_id`` is the
    panel's spelling of the target (a broadcast id, a section key, a
    category key, a feature name, a source name). The two global targets
    (``import_global``, ``prefetch_global``, ``domain_checks``) carry a
    conventional target_id of ``"all"``. A missing database, a missing
    table, or an unknown target answers False — nothing is paused by
    default, so an unwired panel never stops the backend.
    """
    if not target_type or target_id is None:
        return False
    conn = _open_panel(panel_path)
    if conn is None:
        return False
    try:
        return (str(target_type), str(target_id)) in _paused_targets(conn)
    finally:
        conn.close()


def paused_features(panel_path=None):
    """The feature names the operator paused, or an empty set.

    One read of the pauses table, for the remote-config route: a paused
    feature is served as off, whatever the catalog row says. Never raises.
    """
    conn = _open_panel(panel_path)
    if conn is None:
        return set()
    try:
        return {target_id for target_type, target_id in _paused_targets(conn)
                if target_type == "feature"}
    finally:
        conn.close()


def tuning_knob(panel_path=None, name=None, default=None):
    """One knob's value, or `default` when the panel cannot answer it.

    The per-consumer primitive: a consumer's shipped behaviour is its own
    default, not the panel's seed. When the panel is unwired, the table or
    column is missing, or the stored value is not an integer, the caller
    gets `default` — its own shipped value — and nothing changes. When the
    panel IS wired, the stored value (clamped to the panel's own bounds)
    wins, because the operator set it. Never raises.
    """
    if name not in TUNING_KNOBS:
        return default
    _seed, lo, hi = TUNING_KNOBS[name]
    conn = _open_panel(panel_path)
    if conn is None:
        return default
    try:
        if not _has_table(conn, "tuning_settings"):
            return default
        try:
            row = conn.execute(
                "SELECT %s FROM tuning_settings WHERE id = 1" % name).fetchone()
        except sqlite3.Error:
            return default
        if row is None:
            return default
        try:
            value = int(_theme_col(row, name) or 0)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, value))
    finally:
        conn.close()


def read_tabs(panel_path=None):
    """Operator tab list for the app, or the default four. Never raises.

    Reads the ``tabs`` TEXT column from ``tuning_settings`` (id = 1), read-only.
    A missing database, table, row or column answers the defaults; unknown ids
    are dropped, duplicates collapse, and an empty or unreadable value answers
    the defaults — the app keeps its own rails either way.
    """
    conn = _open_panel(panel_path)
    if conn is None:
        return list(TABS_DEFAULT)
    try:
        if not _has_table(conn, "tuning_settings"):
            return list(TABS_DEFAULT)
        try:
            row = conn.execute(
                "SELECT tabs FROM tuning_settings WHERE id = 1").fetchone()
        except sqlite3.Error:
            return list(TABS_DEFAULT)
        if row is None:
            return list(TABS_DEFAULT)
        raw = _theme_col(row, "tabs")
        if not isinstance(raw, str) or not raw.strip():
            return list(TABS_DEFAULT)
        seen = []
        for part in raw.split(","):
            tab = part.strip().lower()
            if tab in TAB_IDS and tab not in seen:
                seen.append(tab)
        return seen or list(TABS_DEFAULT)
    finally:
        conn.close()


#: The disclaimer the operator publishes, as set in
#: `tuning_settings.disclaimer_text` / `disclaimer_version` /
#: `disclaimer_email`. The app shows it once per version; an empty text
#: means "nothing published", and the version is what the app remembers
#: having shown. The text is cut at 4000 — the panel refuses anything
#: longer — so a long policy can never bloat the config body the phone
#: polls every five minutes. The email is the takedown contact the app
#: shows under the text; an empty email means "no contact published".
DISCLAIMER_MAX_CHARS = 4000


def read_disclaimer(panel_path=None):
    """Operator disclaimer for the app, or the empty one. Never raises.

    Reads ``disclaimer_text`` / ``disclaimer_version`` / ``disclaimer_email``
    from ``tuning_settings`` (id = 1), read-only, the same tolerant pattern
    as :func:`read_theme`: a missing database, table, row or column answers
    empty; a non-integer version answers 0. A panel that predates the email
    column still answers its text and version (the three-column read falls
    back to the two-column one). The app treats an empty text as "no
    disclaimer published" and shows nothing — the operator writes the
    words, this module never invents them.
    """
    out = {"text": "", "version": 0, "email": ""}
    conn = _open_panel(panel_path)
    if conn is None:
        return out
    try:
        if not _has_table(conn, "tuning_settings"):
            return out
        try:
            row = conn.execute(
                "SELECT disclaimer_text, disclaimer_version, disclaimer_email "
                "FROM tuning_settings WHERE id = 1").fetchone()
        except sqlite3.Error:
            try:
                row = conn.execute(
                    "SELECT disclaimer_text, disclaimer_version "
                    "FROM tuning_settings WHERE id = 1").fetchone()
            except sqlite3.Error:
                return out
        if row is None:
            return out
        text = _theme_col(row, "disclaimer_text")
        if isinstance(text, str) and text.strip():
            out["text"] = text.strip()[:DISCLAIMER_MAX_CHARS]
        email = _theme_col(row, "disclaimer_email")
        if isinstance(email, str):
            email = email.strip()
            local, sep, domain = email.partition("@")
            if (sep and "@" not in domain and " " not in email
                    and local and "." in domain and len(email) <= 254):
                out["email"] = email
        try:
            version = int(_theme_col(row, "disclaimer_version") or 0)
            if version >= 0:
                out["version"] = version
        except (TypeError, ValueError):
            pass
        return out
    finally:
        conn.close()


#: The hero is a shop window, not an archive: only films from this year
#: onward may headline it, and only with a real poster to show.
_HERO_MIN_YEAR = 2000

#: How many newest posts the hero scan reads. Bounded: the scan is one
#: id-ordered read plus one join, never a full-catalog grouping.
_HERO_CANDIDATE_SCAN = 2000


def _hero_rows(catalog_conn, limit, hidden):
    """Hero candidates: recent, well-posted, with a real poster.

    Audit #16: the hero must never be a 1938 title with a blurry
    credits-screen "poster". The newest 2000 posts are read once, then
    filtered in Python — year >= 2000, a non-empty poster_url, adult-ok
    and not hidden — and ordered by prints + mirrors, best first. The
    same list backs the curated hero's fallback, so the top of Home
    always has something worth showing.
    """
    try:
        rows = catalog_conn.execute(
            "SELECT p.*, COUNT(DISTINCT r.id) AS _rc,"
            " COUNT(DISTINCT s.id) AS _sc"
            " FROM (SELECT * FROM posts ORDER BY id DESC LIMIT ?) p"
            " LEFT JOIN releases r ON r.post_id = p.id"
            " LEFT JOIN download_sources s ON s.release_id = r.id"
            " GROUP BY p.id",
            (_HERO_CANDIDATE_SCAN,)).fetchall()
    except sqlite3.Error:
        return []
    candidates = []
    for r in rows:
        if not _adult_ok(r):
            continue
        try:
            if int(r["id"]) in hidden:
                continue
            year = int(r["year"]) if r["year"] is not None else None
            poster = r["poster_url"]
            prints = int(r["_rc"] or 0) + int(r["_sc"] or 0)
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        if year is None or year < _HERO_MIN_YEAR:
            continue
        if not str(poster or "").strip():
            continue
        candidates.append((prints, int(r["id"]), r))
    candidates.sort(key=lambda c: (-c[0], -c[1]))
    return [r for _prints, _post_id, r in candidates[:limit]]


def _work_candidate(row):
    """A row as `title_clean.group_work_rows` reads it."""
    def _get(key, default=None):
        try:
            return row[key]
        except (KeyError, IndexError):
            return default
    try:
        post_id = int(_get("id") or 0)
    except (TypeError, ValueError):
        post_id = 0
    return {
        "id": post_id,
        "clean_title": _get("clean_title") or "",
        "title": _get("title") or "",
        "year": _get("year"),
        "content_type": _get("content_type") or "",
        "release_count": int(_get("release_count") or _get("_rc") or 0),
        "source_count": int(_get("source_count") or _get("_sc") or 0),
    }


def _drop_seen_works(rows, seen):
    """Rows whose work is new, in the section's own order.

    Audit #17: the same film must not repeat across rails on one
    screen. `seen` is the candidate dicts of every row already served
    (earlier sections); a row is dropped when its work group already
    holds a seen row, and a work that appears twice inside this one
    section is kept once, as its best representative. The caller's
    `seen` is NOT extended here — it extends it with what it kept.
    """
    new_cands = [_work_candidate(r) for r in rows]
    if not seen:
        # Nothing to repeat against, but the section itself still
        # collapses to one row per work.
        groups = title_clean.group_work_rows(new_cands)
        kept = [title_clean.representative(g) for g in groups]
        order = {int(c["id"]): i for i, c in enumerate(new_cands)}
        kept.sort(key=lambda c: order[int(c["id"])])
        by_id = {int(r["id"]): r for r in rows}
        return [by_id[int(c["id"])] for c in kept if int(c["id"]) in by_id]
    groups = title_clean.group_work_rows(list(seen) + new_cands)
    seen_ids = {int(c["id"]) for c in seen}
    keep_ids: list[int] = []
    for group in groups:
        ids = {int(c["id"]) for c in group}
        if ids & seen_ids:
            continue
        keep_ids.append(int(title_clean.representative(group)["id"]))
    order = {int(c["id"]): i for i, c in enumerate(new_cands)}
    keep_ids.sort(key=lambda post_id: order[post_id])
    by_id = {int(r["id"]): r for r in rows}
    return [by_id[post_id] for post_id in keep_ids if post_id in by_id]


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


def _snapshot_sections(snapshot):
    """(sections, cards_by_key): the published home feed, or ([], {}).

    The published snapshot carries the home feed under ``home.sections``:
    a list of ``{"section": {...}, "cards": [...]}`` — the section row as
    the panel stored it, plus that section's slider cards. Only enabled
    sections come back, in the snapshot's own order (the panel already
    ordered them by position). A snapshot without a ``home`` block, without
    a ``sections`` list, or with no enabled sections answers empty, which
    the caller reads as "no publication to serve" and falls back to the
    live table. The cards are the published card order (position, then
    id); a disabled card, or one outside its window, is not carried — the
    window is judged at the caller's `now`, not at publish time, because
    a card that expired after publish must stop, not linger.
    """
    if not isinstance(snapshot, dict):
        return [], {}
    home = snapshot.get("home")
    if not isinstance(home, dict):
        return [], {}
    entries = home.get("sections")
    if not isinstance(entries, list):
        return [], {}
    sections = []
    cards_by_key = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sec = entry.get("section")
        if not isinstance(sec, dict):
            continue
        try:
            if int(sec.get("is_enabled") or 0) != 1:
                continue
            key = str(sec["key"])
        except (KeyError, TypeError, ValueError):
            continue
        sections.append(sec)
        cards = entry.get("cards")
        if not isinstance(cards, list):
            cards = []
        work_ids = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            try:
                if int(card.get("is_enabled") or 0) != 1:
                    continue
                work_ids.append(int(card["work_id"]))
            except (KeyError, TypeError, ValueError):
                continue
        cards_by_key[key] = work_ids
    return sections, cards_by_key


def load_panel_feed(catalog_conn, panel_path=None, now=None):
    """Sections, broadcasts and hides for the app feed.

    ``catalog_conn`` is the catalog connection the caller already holds;
    ``panel_path`` overrides the configured panel database. The sections carry
    raw post rows under ``rows`` — the caller projects them through the same
    ``post_brief`` + art-pair shape the posts route serves, because this
    module owns resolution and filtering, not the wire shape.

    Publish is a real gate now: the sections come from the latest PUBLISHED
    snapshot (``app_remote_config_history``), not the live ``home_sections``
    table — a section the operator enabled but never published does not
    reach a phone. A panel that never published, or a snapshot without a
    home feed, falls back to the live table, so a panel that predates
    publish still serves what it always served. The curated cards come
    from the snapshot too; the live ``slider_cards`` table is only read on
    that same fallback. Hides and broadcasts are live by nature (a hide
    expires, a broadcast has a window), so they are always read from the
    live tables, never the snapshot.

    Pauses are enforced here: a section whose key is paused, and a
    category section whose category is paused, are skipped outright.
    The hero is never left empty: a curated hero with no live cards falls
    back to the newest posts, so the top of Home always has something.
    """
    now = int(now if now is not None else time.time())
    empty = {"sections": [], "broadcasts": [], "hidden_work_ids": []}
    panel = _open_panel(panel_path)
    if panel is None:
        return empty
    try:
        caps = read_section_caps(panel_path)
        global_hidden, section_hidden = _active_hides(panel, now)
        hidden = set(sorted(global_hidden)[:HIDDEN_IDS_CAP])
        paused = _paused_targets(panel)
        broadcasts = active_broadcasts(panel_path, now)
        # The published snapshot is the feed when one exists; the live
        # table is the fallback for a panel that never published.
        snap = _published_snapshot(panel_path)
        snap_sections, snap_cards = _snapshot_sections(snap)
        live_sections = None
        if snap_sections:
            sections = [
                {"key": str(sec["key"]),
                 "title": str(sec.get("title") or ""),
                 "rule": str(sec.get("source_rule") or "latest"),
                 "category_key": sec.get("category_key"),
                 "is_adult_only": sec.get("is_adult_only"),
                 "cards": snap_cards.get(str(sec["key"]), [])}
                for sec in snap_sections
            ][:caps["sections_max"]]
        else:
            if not _has_table(panel, "home_sections"):
                return {"sections": [], "broadcasts": broadcasts,
                        "hidden_work_ids": sorted(hidden)}
            try:
                live_sections = panel.execute(
                    "SELECT * FROM home_sections WHERE is_enabled = 1 "
                    "ORDER BY position ASC, id ASC LIMIT ?",
                    (caps["sections_max"],)).fetchall()
            except sqlite3.Error:
                return {"sections": [], "broadcasts": broadcasts,
                        "hidden_work_ids": sorted(hidden)}
            sections = [
                {"key": str(sec["key"]),
                 "title": str(_theme_col(sec, "title") or ""),
                 "rule": str(_theme_col(sec, "source_rule") or "latest"),
                 "category_key": _theme_col(sec, "category_key"),
                 "is_adult_only": _theme_col(sec, "is_adult_only"),
                 "cards": None}
                for sec in live_sections
            ]
        out_sections = []
        seen_rows: list[dict] = []
        for sec in sections:
            try:
                if int(sec["is_adult_only"] or 0):
                    continue
                key = sec["key"]
                title = redact.scrub_text(str(sec["title"] or ""))
                rule = sec["rule"]
                category_key = sec["category_key"]
            except (KeyError, IndexError):
                continue
            # A paused section, or a category section whose category is
            # paused, is skipped outright — a pause is a stop.
            if ("section", key) in paused:
                continue
            if (rule == "category" and category_key
                    and ("category", str(category_key)) in paused):
                continue
            if rule == "curated":
                if sec["cards"] is not None:
                    curated_ids = [int(i) for i in sec["cards"]
                                   if str(i).strip()]
                elif _has_table(panel, "slider_cards"):
                    try:
                        sec_id = None
                        for live in (live_sections or []):
                            if str(live["key"]) == key:
                                sec_id = live["id"]
                                break
                        if sec_id is None:
                            curated_ids = []
                        else:
                            cards = panel.execute(
                                "SELECT work_id FROM slider_cards "
                                "WHERE section_id = ? AND is_enabled = 1 "
                                "AND (starts_at IS NULL OR starts_at <= ?) "
                                "AND (ends_at IS NULL OR ends_at > ?) "
                                "ORDER BY position ASC, id ASC",
                                (sec_id, now, now)).fetchall()
                            curated_ids = [c["work_id"] for c in cards]
                    except sqlite3.Error:
                        curated_ids = []
                else:
                    curated_ids = []
            else:
                curated_ids = []
            section_hide = {
                int(suffix) for tag in section_hidden
                if tag.startswith(key + ":")
                for suffix in [tag[len(key) + 1:]]
                if suffix.isdigit()
            }
            if key == "hero" and rule != "curated":
                # A hero on an automatic rule is a shop window, not the
                # newest scrape: recent, posted, with a real poster. Only
                # when nothing is eligible does it fall back to the
                # rule's own rows, so the top of Home is never empty.
                rows = _hero_rows(
                    catalog_conn, caps["section_cap"], hidden | section_hide)
                if not rows:
                    rows = _resolve_rows(
                        catalog_conn, rule, category_key, [],
                        caps["section_cap"], hidden | section_hide)
            else:
                rows = _resolve_rows(
                    catalog_conn, rule, category_key, curated_ids,
                    caps["section_cap"], hidden | section_hide)
                # Hero fallback: a curated hero with no live cards must not
                # leave the top of Home empty — fill it with hero
                # candidates first, and only when none is eligible, with
                # the newest posts.
                if key == "hero" and rule == "curated" and not rows:
                    rows = _hero_rows(
                        catalog_conn, caps["section_cap"],
                        hidden | section_hide)
                    if not rows:
                        rows = _resolve_rows(
                            catalog_conn, "latest", None, [],
                            caps["section_cap"], hidden | section_hide)
            if rule != "curated":
                # Audit #17: one film, one rail. A curated section keeps
                # the operator's cards exactly as placed — even a repeat —
                # but every served row still joins `seen`, so a later
                # automatic rail never repeats a curated pick either.
                rows = _drop_seen_works(rows, seen_rows)
            seen_rows.extend(_work_candidate(r) for r in rows)
            out_sections.append({"key": key, "title": title, "rows": rows})
        return {"sections": out_sections,
                "broadcasts": broadcasts,
                "hidden_work_ids": sorted(hidden)}
    finally:
        panel.close()
