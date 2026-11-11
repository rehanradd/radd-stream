"""Business logic for Admin Panel v2. Stdlib only, workspace only.

Rules enforced here (not just in the UI):
- owner writes, auditor reads only; moderator/support rejected.
- unknown fields refused, whole body refused on any bad field.
- payment/VIP/adult/price reads are always fresh (never cached).
- adult fail-closed: unknown flag = hidden; global adult ON is blocked
  (OD-18, gate not confirmed); unhide never overrides the adult clause.
- every write writes exactly one redacted audit row in the same
  transaction where the design requires atomicity.
- no provenance leak: responses are passed through redact_payload()
  before leaving this module, except the ledger search path which
  returns a match confirmation without ever rendering a transaction id.
"""
import hashlib
import inspect
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone

from . import security, smart
from .errors import ApiError, bad, conflict, forbidden, not_found
from .live_stores import (
    FLEET_SITES as _LIVE_FLEET_SITES,  # noqa: F401  (same list, live-verified)
    LiveStores, LiveUnavailable, PLAN_DAYS, REMOTE_CONFIG_FIELDS,
)
from .security import (
    SESSION_ABSOLUTE_S, SESSION_IDLE_S, check_password, check_totp,
    hash_password, mask_contact, mask_hint, mask_ip, mask_secret,
    new_token, redact_payload, scrub_text, token_hash, valid_domain,
    valid_hex, valid_slug,
)
from .store import (
    COIN_REDEEM_FIELDS, FLEET_SITES, MONETIZATION_FIELDS, TUNING_DEFAULTS,
    WRITE_LOCK, connect, init_catalog_fixture, init_ledger_fixture, migrate,
)

NOW = lambda: int(time.time())


def _coerce_bool(value, default=True):
    """Coerce a form/JSON flag to bool. "0"/"false"/"off"/"" -> False.

    (A bare bool("0") is True in Python, so the Live TV toggle form's
    hidden enabled="0" used to never disable a channel.)"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "on", "yes")


def _live_tv_audit_view(channel):
    """Audit-safe channel summary: no stream/logo URL (provenance).

    redact_payload refuses any string containing a URL, so the audit
    log only ever carries the identity fields."""
    if channel is None:
        return None
    return {k: channel.get(k) for k in
            ("id", "name", "category", "country", "language", "source",
             "enabled", "disabled_reason")}


def _parse_broadcast_time(value, field):
    """Accept a schedule time as Unix seconds or as a datetime-local
    string ("YYYY-MM-DDTHH:MM", as an HTML datetime-local input posts
    it). A datetime-local value has no timezone, so it is read as UTC —
    the same zone the panel renders dates in (templates.fmt_datetime).
    Returns Unix seconds, or None when the value is empty/None.
    Anything else raises bad()."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise bad("%s must be unix seconds or a date-time like 2026-11-11T14:30." % field)


def _call_checker(checker, domain, site_key):
    """Call a domain checker with the site key when it accepts one.

    The real checker takes site_key (its hijack detection needs the
    site slug); injected test fakes take only the domain. The
    signature is inspected once — a TypeError from inside a real
    check must never silently retry without the key.
    """
    try:
        sig = inspect.signature(checker)
    except (TypeError, ValueError):
        return checker(domain)
    if "site_key" in sig.parameters:
        return checker(domain, site_key=site_key)
    return checker(domain)

# Dashboard cache (D2.4): fresh rows serve for 10 min; rows the live path
# wrote may serve stale for up to 1 h while the background tick refreshes.
DASHBOARD_CACHE_TTL_S = 600
DASHBOARD_CACHE_STALE_S = 3600
DASHBOARD_CACHE_ORIGIN_LIVE = "live"
# Single-flight guard for the background dashboard refresh, so
# overlapping minute ticks never pile up recomputes.
_DASHBOARD_REFRESH_LOCK = threading.Lock()

VISIBILITY_REASONS = {"takedown", "quality", "duplicate", "owner", "other"}
REPORT_REASONS = {"copyright", "wrong_content", "adult_leak", "broken", "spam", "other"}
REPORT_ACTIONS = {"temp_hide", "restore", "permanent", "blocklist_note", "reject", "request_info"}
CONTACT_CATEGORIES = {"bug", "payment", "content", "takedown", "other"}
CONTACT_STATUSES = {"open", "in_progress", "resolved", "spam"}
PAUSE_TARGETS = {
    "import_global", "prefetch_global", "source", "section", "category",
    "feature", "broadcast", "domain_checks",
}
TUNING_BOUNDS = {
    "resolver_concurrency": (1, 4), "candidate_cap": (3, 20),
    "cache_ttl_h": (1, 24), "warmup_count": (0, 200),
    "warmup_interval_h": (6, 168), "rate_limit_play_per_min": (10, 120),
    "import_cap": (10, 1000), "import_concurrency": (1, 3),
    "prefetch_queue": (0, 500), "prefetch_concurrency": (1, 2),
    "hero_max": (0, 6), "section_cap": (5, 50),
    "home_sections_max": (1, 12), "domain_check_interval_min": (30, 1440),
    "theme_dynamic_color": (0, 1), "theme_hero_autoplay": (0, 1),
    "theme_hero_interval_s": (1, 30), "disclaimer_version": (0, 9999),
}
SOURCE_RULES = {"latest", "trending", "category", "curated"}


def _row(d):
    return dict(d) if d is not None else None


def _public_user(row):
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "is_active": bool(row["is_active"]),
            "last_login_at": row["last_login_at"]}


class Service:
    def __init__(self, base_dir, totp_key=b"workspace-totp-key-change-at-gate",
                 live_catalog_path=None, live_ledger_path=None,
                 live_registry_path=None, live_status_dir=None,
                 live_cert_path=None, live_fleet_base_dir=None,
                 live_fleet_runner=None, live=None):
        import os
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self.admin_path = os.path.join(base_dir, "admin_v2.db")
        self.catalog_path = os.path.join(base_dir, "catalog_fixture.db")
        self.ledger_path = os.path.join(base_dir, "ledger_fixture.db")
        self.totp_key = totp_key
        self.admin = connect(self.admin_path)
        migrate(self.admin)
        self.catalog = init_catalog_fixture(self.catalog_path)
        self.ledger = init_ledger_fixture(self.ledger_path)
        self._domain_cache = {}  # site_key -> (domain_or_None, expires_at)
        # Live stores: injected LiveStores, or built from explicit
        # paths. None = no live store configured (fixture behaviour).
        # Workspace tests pass temp copies; the live gate passes the
        # real paths only after a backup.
        if live is not None:
            self.live = live
        elif any((live_catalog_path, live_ledger_path, live_registry_path,
                  live_status_dir, live_cert_path, live_fleet_base_dir,
                  live_fleet_runner)):
            self.live = LiveStores(
                catalog_path=live_catalog_path, ledger_path=live_ledger_path,
                registry_path=live_registry_path, status_dir=live_status_dir,
                cert_path=live_cert_path,
                fleet_base_dir=live_fleet_base_dir or "/opt/radd-stream/Fast_Fetch",
                fleet_runner=live_fleet_runner)
        else:
            self.live = None
        self._bg_stop = None
        self._seed_published_home()
        if self.live is not None:
            self.seed_domains_from_registry()

    # -- live-store helpers ------------------------------------------------
    def _live_catalog(self):
        return self.live if (self.live is not None and self.live.has_catalog) else None

    def _live_ledger(self):
        return self.live if (self.live is not None and self.live.has_ledger) else None

    def _get_work_any(self, work_id):
        """One work from the real catalog when wired, else the fixture.
        Returns the unified work dict or None. Adult flag is read-only
        in both cases (no setter exists anywhere)."""
        live = self._live_catalog()
        if live is not None:
            try:
                return live.get_work(work_id)
            except Exception:
                return None
        row = self.catalog.execute(
            "SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
        return _row(row) if row else None

    def resolve_section_preview(self, actor, section_key):
        """Execute a section's source_rule against the real catalog
        (or the fixture when no live catalog is wired). Preview /
        resolution only — the panel sections stay the store of record,
        and the Android app reads them (HomeViewModel.mergePanelFeed,
        Phase 7), so a preview here is what the app will show."""
        self.require_role(actor, write=False)
        sec = self.admin.execute(
            "SELECT * FROM home_sections WHERE key=?", (section_key,)).fetchone()
        if not sec:
            raise not_found()
        rule = sec["source_rule"]
        cap = 20
        live = self._live_catalog()
        if live is not None:
            items = live.resolve_section(rule, sec["category_key"], limit=cap)
        else:
            rows = self.catalog.execute(
                "SELECT * FROM works ORDER BY id DESC LIMIT ?", (cap,)).fetchall()
            items = [_row(r) for r in rows]
            if rule == "category" and sec["category_key"]:
                items = [w for w in items
                         if sec["category_key"].lower() in (w.get("title") or "").lower()]
            elif rule == "curated":
                items = []
        # Adult fail-closed applies to resolved works too.
        visible = []
        for w in items:
            if w.get("adult_flag") != 0 and not sec["is_adult_only"]:
                continue
            if self.is_work_hidden(w["id"], section_key):
                continue
            visible.append(w)
        return {"section": _row(sec), "source_rule": rule,
                "items": visible, "count": len(visible),
                "app_read": "live",
                "note": "Preview from the real catalog. The Android app "
                        "reads panel sections (HomeViewModel.mergePanelFeed)."}

    def seed_domains_from_registry(self):
        """Seed the panel registry from domain_registry.json (read at
        runtime from the configured path). Idempotent: only fills a
        site whose panel row is missing or has no active domain, so a
        manual override is never overwritten by a seed."""
        if self.live is None:
            return {"seeded": 0, "sites": 0}
        sites = self.live.load_registry()
        now = NOW()
        seeded = 0
        with WRITE_LOCK:
            for site_key, entry in sites.items():
                if site_key not in FLEET_SITES:
                    continue
                url = (entry or {}).get("active_base_url") or ""
                domain = url.replace("https://", "").replace("http://", "").rstrip("/") or None
                row = self.admin.execute(
                    "SELECT * FROM domain_registry WHERE site_key=?", (site_key,)).fetchone()
                if row is None:
                    self.admin.execute(
                        "INSERT INTO domain_registry (site_key, kind, active_domain, status, "
                        "created_at, updated_at) VALUES (?, 'source_site', ?, ?, ?, ?)",
                        (site_key, domain,
                         "healthy" if (entry or {}).get("status") == "active" else "degraded",
                         now, now))
                    seeded += 1
                elif not row["active_domain"] and domain:
                    self.admin.execute(
                        "UPDATE domain_registry SET active_domain=?, updated_at=? WHERE site_key=?",
                        (domain, now, site_key))
                    seeded += 1
            self.admin.commit()
        return {"seeded": seeded, "sites": len(sites)}

    def list_login_attempts(self, actor, limit=20):
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT id, username_attempted, ip_masked, success, attempted_at "
            "FROM admin_login_attempts ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit or 20), 100)),)).fetchall()
        return {"items": [_row(r) for r in rows]}

    def tuning_consumers(self, actor):
        """Honest labelling per tuning control (OD-04 pattern).

        A read-only grep of the VM Fast_Fetch code on 2026-11-05 found
        NO consumer for 13 of the 20 controls. Only the ones that ride
        in remote-config reach the app (VIP prices via monetization,
        free quality cap, the theme knobs and hero_max via the public
        config). The rest are stored, not yet applied by the backend —
        labelled, never pretended."""
        self.require_role(actor, write=False)
        applied = {"vip_monthly_pkr": "remote-config (app reads it)",
                   "vip_yearly_pkr": "remote-config (app reads it)",
                   "free_quality_cap": "remote-config (app reads it)",
                   "theme_mode": "remote-config (app reads it)",
                   "theme_accent": "remote-config (app reads it)",
                   "theme_dynamic_color": "remote-config (app reads it)",
                   "theme_hero_autoplay": "remote-config (app reads it)",
                   "theme_hero_interval_s": "remote-config (app reads it)",
                   "hero_max": "remote-config (app reads it)",
                   "tabs": "remote-config (app reads it)",
                   "disclaimer_text": "remote-config (app reads it)",
                   "disclaimer_version": "remote-config (app reads it)",
                   "disclaimer_email": "remote-config (app reads it)",
                   "home_sections_max": "panel feed (server applies it)",
                   "section_cap": "panel feed (server applies it)"}
        out = {}
        for name in TUNING_DEFAULTS:
            out[name] = applied.get(name, "stored, not yet applied by the backend")
        return out

    def start_background_jobs(self, domain_checker=None, interval_s=3600,
                              analytics_interval_s=86400):
        """Opt-in background thread (OFF by default, never in tests):
        staggered domain health (OD-10: every 60 min, staggered per
        site) + scheduled daily analytics compute. Started only by
        run.py --background-jobs. Returns a stop function."""
        import threading
        if self._bg_stop is not None:
            return self._bg_stop
        stop = threading.Event()
        self._bg_stop = stop

        def _loop():
            import hashlib as _h
            last_analytics = 0.0
            while not stop.wait(60):
                now = time.time()
                # Stagger: each site checks once per interval, at an
                # offset derived from its key, so 18 sites never burst.
                for site in FLEET_SITES:
                    offset = int(_h.sha256(site.encode()).hexdigest()[:4], 16) % interval_s
                    if (int(now) + offset) % interval_s < 60:
                        try:
                            reg = self.admin.execute(
                                "SELECT active_domain FROM domain_registry WHERE site_key=?",
                                (site,)).fetchone()
                            domain = reg["active_domain"] if reg else None
                            if domain and domain_checker is not None:
                                actor = {"id": 0, "role": "owner", "username": "background"}
                                self.record_health(actor, site, {**_call_checker(domain_checker, domain, site), "domain": domain})
                        except Exception:
                            pass
                if now - last_analytics >= analytics_interval_s:
                    last_analytics = now
                    try:
                        actor = {"id": 0, "role": "owner", "username": "background"}
                        day = time.strftime("%Y-%m-%d", time.gmtime(now))
                        self.compute_analytics_day(actor, day)
                    except Exception:
                        pass
                # Scheduled publishes fire on this same minute tick: a due
                # schedule is a job, and this loop is where jobs run.
                try:
                    self.fire_due_scheduled_publishes(now=now)
                except Exception:
                    pass
                # Dashboard cache refresh on this same minute tick (D2.4):
                # an expired row is recomputed here, never on a page load.
                try:
                    self.refresh_dashboard_cache()
                except Exception:
                    pass

        threading.Thread(target=_loop, daemon=True).start()
        return stop

    def stop_background_jobs(self):
        if self._bg_stop is not None:
            self._bg_stop.set()
            self._bg_stop = None

    # -- generic helpers -------------------------------------------------
    def audit(self, actor_id, action, target_type, target_id, before, after, ip=""):
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT INTO admin_audit_log (actor_id, action, target_type, target_id, "
                "before_json, after_json, ip_masked, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (actor_id, action, target_type, str(target_id) if target_id is not None else None,
                 json.dumps(redact_payload(before)) if before is not None else None,
                 json.dumps(redact_payload(after)) if after is not None else None,
                 mask_ip(ip), NOW()),
            )
            self.admin.commit()

    def require_role(self, actor, write=True):
        if actor is None:
            from .errors import unauth
            raise unauth()
        if write and actor["role"] != "owner":
            raise forbidden("Only the owner can change that.")
        if actor["role"] not in ("owner", "auditor"):
            raise forbidden("That role is disabled in this version.")

    def _actor_id(self, actor):
        return actor["id"] if actor else None

    def _validate_body(self, body, allowed):
        if not isinstance(body, dict):
            raise bad()
        unknown = sorted(set(body) - set(allowed))
        if unknown:
            raise bad("Unknown field: %s" % ",".join(unknown))
        return body

    def _list(self, rows, after_id, limit):
        items = [_row(r) for r in rows]
        nxt = items[-1]["id"] if items and len(items) >= limit else None
        return {"items": items, "next_after_id": nxt, "count": len(items)}

    # -- auth ------------------------------------------------------------
    def create_owner(self, username, password):
        """Setup path only (VM-terminal command). Refuses if any user exists."""
        if not isinstance(username, str) or not (3 <= len(username) <= 32):
            raise bad("Username must be 3 to 32 characters.")
        username = username.lower()
        if len(password) < 12 or len(password) > 128:
            raise bad("Password must be 12 to 128 characters.")
        with WRITE_LOCK:
            n = self.admin.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()["n"]
            if n:
                raise conflict("An owner account already exists.")
            cur = self.admin.execute(
                "INSERT INTO admin_users (username, password_hash, password_changed_at, "
                "role, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (username, hash_password(password), NOW(), "owner", NOW(), NOW()),
            )
            self.admin.commit()
            return cur.lastrowid

    def login(self, username, password, totp=None, ip="", ua_label=""):
        ip_m = mask_ip(ip)
        now = NOW()
        with WRITE_LOCK:
            # Lockout: 5 failures / 15 min per account, 20 / 15 min per IP.
            since = now - 15 * 60
            acc = self.admin.execute(
                "SELECT COUNT(*) AS n FROM admin_login_attempts WHERE username_attempted=? "
                "AND success=0 AND attempted_at>=?", (str(username).lower(), since)
            ).fetchone()["n"]
            ipc = self.admin.execute(
                "SELECT COUNT(*) AS n FROM admin_login_attempts WHERE ip_masked=? "
                "AND success=0 AND attempted_at>=?", (ip_m, since)
            ).fetchone()["n"]
            user = self.admin.execute(
                "SELECT * FROM admin_users WHERE username=?", (str(username).lower(),)
            ).fetchone()
            locked = False
            if user and user["locked_until"] and user["locked_until"] > now:
                locked = True
            if acc >= 5 or ipc >= 20 or locked:
                self.admin.execute(
                    "INSERT INTO admin_login_attempts (username_attempted, ip_masked, success, attempted_at) "
                    "VALUES (?,?,0,?)", (str(username).lower(), ip_m, now),
                )
                self.admin.commit()
                self.audit(None, "auth.lockout", "admin_user", user["id"] if user else None,
                          None, {"locked": True}, ip)
                raise ApiError("locked", "That account is locked for a short time. Try again later.", 403)
            ok = bool(user) and user["is_active"] and check_password(password, user["password_hash"])
            if ok and user["totp_secret_encrypted"]:
                from .security import xor_decrypt
                secret = xor_decrypt(self.totp_key, user["totp_secret_encrypted"])
                if secret and not check_totp(secret, totp or ""):
                    # Recovery codes are a second chance, checked hashed.
                    row = self.admin.execute(
                        "SELECT * FROM admin_recovery_codes WHERE user_id=? AND used_at IS NULL",
                        (user["id"],),
                    ).fetchall()
                    used = None
                    for r in row:
                        if r["code_hash"] == hashlib.sha256(str(totp).encode()).hexdigest():
                            used = r
                            break
                    if used is None:
                        ok = False
                    else:
                        self.admin.execute(
                            "UPDATE admin_recovery_codes SET used_at=? WHERE id=?", (now, used["id"]))
            self.admin.execute(
                "INSERT INTO admin_login_attempts (username_attempted, ip_masked, success, attempted_at) "
                "VALUES (?,?,?,?)", (str(username).lower(), ip_m, 1 if ok else 0, now),
            )
            if not ok:
                if user and acc + 1 >= 5:
                    self.admin.execute(
                        "UPDATE admin_users SET locked_until=? WHERE id=?", (now + 15 * 60, user["id"]))
                self.admin.commit()
                raise ApiError("invalid_credentials", "Username or password is not correct.", 401)
            self.admin.execute(
                "UPDATE admin_users SET last_login_at=?, failed_attempts=0, locked_until=NULL WHERE id=?",
                (now, user["id"]),
            )
            session_token, csrf_token = new_token(), new_token()
            self.admin.execute(
                "INSERT INTO admin_sessions (user_id, session_token_hash, csrf_token_hash, csrf_token, "
                "created_at, last_seen_at, expires_at, ip_masked, user_agent_label) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (user["id"], token_hash(session_token), token_hash(csrf_token), csrf_token,
                 now, now, now + SESSION_ABSOLUTE_S, ip_m, (ua_label or "")[:40]),
            )
            self.admin.commit()
            self.audit(user["id"], "auth.login", "admin_user", user["id"], None,
                       {"username": user["username"]}, ip)
            return {"session_token": session_token, "csrf_token": csrf_token,
                    "user": _public_user(user)}

    def validate_session(self, session_token):
        if not session_token:
            return None, None
        row = self.admin.execute(
            "SELECT * FROM admin_sessions WHERE session_token_hash=? AND revoked_at IS NULL",
            (token_hash(session_token),),
        ).fetchone()
        if not row:
            return None, None
        now = NOW()
        if now > row["expires_at"] or now - row["last_seen_at"] > SESSION_IDLE_S:
            with WRITE_LOCK:
                self.admin.execute(
                    "UPDATE admin_sessions SET revoked_at=? WHERE id=?", (now, row["id"]))
                self.admin.commit()
            return None, None
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE admin_sessions SET last_seen_at=? WHERE id=?", (now, row["id"]))
            self.admin.commit()
        user = self.admin.execute(
            "SELECT * FROM admin_users WHERE id=?", (row["user_id"],)).fetchone()
        if not user or not user["is_active"]:
            return None, None
        return _public_user(user), _row(row)

    def check_csrf(self, session_row, csrf_token):
        if not session_row or not csrf_token:
            raise forbidden("That request is missing its safety token.")
        if token_hash(csrf_token) != session_row["csrf_token_hash"]:
            raise forbidden("That request has an invalid safety token.")

    def logout(self, session_token, ip=""):
        user, sess = self.validate_session(session_token)
        if sess:
            with WRITE_LOCK:
                self.admin.execute(
                    "UPDATE admin_sessions SET revoked_at=? WHERE id=?", (NOW(), sess["id"]))
                self.admin.commit()
            self.audit(self._actor_id(user), "auth.logout", "admin_session", sess["id"],
                       None, {"revoked": True}, ip)
        return {"ok": True}

    def list_sessions(self, actor):
        self.require_role(actor, write=False)
        if actor["role"] == "owner":
            rows = self.admin.execute(
                "SELECT id, user_id, created_at, last_seen_at, expires_at, ip_masked, "
                "user_agent_label, revoked_at FROM admin_sessions ORDER BY id DESC LIMIT 100"
            ).fetchall()
        else:
            rows = self.admin.execute(
                "SELECT id, user_id, created_at, last_seen_at, expires_at, ip_masked, "
                "user_agent_label, revoked_at FROM admin_sessions WHERE user_id=? ORDER BY id DESC LIMIT 100",
                (actor["id"],),
            ).fetchall()
        return {"items": [_row(r) for r in rows]}

    def revoke_session(self, actor, session_id, ip=""):
        self.require_role(actor, write=True)
        row = self.admin.execute(
            "SELECT * FROM admin_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise not_found()
        if actor["role"] != "owner" and row["user_id"] != actor["id"]:
            raise forbidden()
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE admin_sessions SET revoked_at=? WHERE id=?", (NOW(), session_id))
            self.admin.commit()
        self.audit(actor["id"], "auth.session_revoke", "admin_session", session_id,
                   None, {"revoked": True}, ip)
        return {"ok": True}

    def change_password(self, actor, session_token, current, new, ip=""):
        self.require_role(actor, write=False)
        user = self.admin.execute(
            "SELECT * FROM admin_users WHERE id=?", (actor["id"],)).fetchone()
        if not check_password(current, user["password_hash"]):
            raise ApiError("invalid_credentials", "The current password is not correct.", 401)
        if len(new) < 12 or len(new) > 128:
            raise bad("New password must be 12 to 128 characters.")
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE admin_users SET password_hash=?, password_changed_at=? WHERE id=?",
                (hash_password(new), NOW(), actor["id"]),
            )
            # Rotate the session: revoke the old one, issue a new one.
            _u, sess = self.validate_session(session_token)
            if sess:
                self.admin.execute(
                    "UPDATE admin_sessions SET revoked_at=? WHERE id=?", (NOW(), sess["id"]))
            st, ct = new_token(), new_token()
            now = NOW()
            self.admin.execute(
                "INSERT INTO admin_sessions (user_id, session_token_hash, csrf_token_hash, "
                "created_at, last_seen_at, expires_at, ip_masked, user_agent_label) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (actor["id"], token_hash(st), token_hash(ct), now, now,
                 now + SESSION_ABSOLUTE_S, mask_ip(ip), ""),
            )
            self.admin.commit()
        self.audit(actor["id"], "auth.password_change", "admin_user", actor["id"],
                   None, {"changed": True}, ip)
        return {"session_token": st, "csrf_token": ct}

    def enable_totp_setup(self, actor):
        """Setup-path only (not an HTTP control): returns secret + codes once.

        The caller (the VM-terminal setup command) shows them once and
        never stores them in a file. This build stores only the encrypted
        secret and hashed codes; see the decisions file for the gate
        review note on the placeholder-grade wrapping.
        """
        self.require_role(actor, write=True)
        import base64 as _b64, secrets as _s
        secret = _b64.b32encode(_s.token_bytes(20)).decode()
        codes = ["%08d" % _s.randbelow(100_000_000) for _ in range(10)]
        from .security import xor_encrypt
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE admin_users SET totp_secret_encrypted=? WHERE id=?",
                (xor_encrypt(self.totp_key, secret), actor["id"]),
            )
            for c in codes:
                self.admin.execute(
                    "INSERT INTO admin_recovery_codes (user_id, code_hash, created_at) VALUES (?,?,?)",
                    (actor["id"], hashlib.sha256(c.encode()).hexdigest(), NOW()),
                )
            self.admin.commit()
        self.audit(actor["id"], "auth.totp_enabled", "admin_user", actor["id"],
                   None, {"enabled": True}, "")
        return {"secret": secret, "recovery_codes": codes}

    # -- catalog / content ----------------------------------------------
    def search_works(self, actor, q="", wtype=None, after_id=None, limit=20):
        self.require_role(actor, write=False)
        live = self._live_catalog()
        if live is not None:
            return live.search_works(q=q, wtype=wtype, after_id=after_id, limit=limit)
        limit = max(1, min(int(limit or 20), 100))
        sql = "SELECT id, title, type, year, adult_flag, language, dub_label, poster_state FROM works WHERE 1=1"
        params = []
        if q:
            sql += " AND title LIKE ?"; params.append("%" + q + "%")
        if wtype:
            sql += " AND type=?"; params.append(wtype)
        if after_id:
            sql += " AND id < ?"; params.append(int(after_id))
        sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
        rows = self.catalog.execute(sql, params).fetchall()
        return self._list(rows, after_id, limit)

    def get_work(self, actor, work_id):
        self.require_role(actor, write=False)
        work = self._get_work_any(work_id)
        if not work:
            raise not_found()
        return work

    def _adult_blockers(self):
        """Sections/categories that would leak adult or unknown-flag works."""
        blockers = []
        cards = self.admin.execute(
            "SELECT s.key AS skey, s.is_adult_only, c.work_id FROM slider_cards c "
            "JOIN home_sections s ON s.id=c.section_id WHERE c.is_enabled=1 AND s.is_enabled=1"
        ).fetchall()
        for c in cards:
            w = self._get_work_any(c["work_id"])
            if w and not c["is_adult_only"] and w.get("adult_flag") != 0:
                blockers.append({"section": c["skey"], "work_id": c["work_id"],
                                 "reason": "adult or unknown flag in a non-adult section"})
        return blockers

    def list_sections(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT * FROM home_sections ORDER BY position ASC, id ASC").fetchall()
        return {"items": [_row(r) for r in rows]}

    def create_section(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"key", "title", "position", "is_enabled",
                                   "is_adult_only", "visible_to", "source_rule", "category_key"})
        key = body.get("key", "")
        if not valid_slug(key):
            raise bad("Section key must be lowercase letters, numbers, dash or underscore.")
        if body.get("visible_to", "all") != "all":
            raise bad("Visibility targeting is all users only in this version.")
        if body.get("source_rule", "latest") not in SOURCE_RULES:
            raise bad("Unknown section source.")
        title = scrub_text(body.get("title", ""), 100)
        if not title:
            raise bad("Section title is required.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO home_sections (key, title, position, is_enabled, is_adult_only, "
                "visible_to, source_rule, category_key, created_by, updated_by, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, title, int(body.get("position", 0)), 1 if body.get("is_enabled", True) else 0,
                 1 if body.get("is_adult_only", False) else 0, "all",
                 body.get("source_rule", "latest"), body.get("category_key"),
                 actor["id"], actor["id"], NOW(), NOW()),
            )
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM home_sections WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "section.create", "home_section", key, None, _row(row), ip)
        return _row(row)

    def update_section(self, actor, key, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"title", "position", "is_enabled", "is_adult_only",
                                   "source_rule", "category_key"})
        row = self.admin.execute("SELECT * FROM home_sections WHERE key=?", (key,)).fetchone()
        if not row:
            raise not_found()
        if "source_rule" in body and body["source_rule"] not in SOURCE_RULES:
            raise bad("Unknown section source.")
        before = _row(row)
        updates = {}
        if "title" in body:
            updates["title"] = scrub_text(body["title"], 100)
        if "position" in body:
            updates["position"] = int(body["position"])
        if "is_enabled" in body:
            updates["is_enabled"] = 1 if body["is_enabled"] else 0
        if "is_adult_only" in body:
            updates["is_adult_only"] = 1 if body["is_adult_only"] else 0
        if "source_rule" in body:
            updates["source_rule"] = body["source_rule"]
        if "category_key" in body:
            updates["category_key"] = body["category_key"]
        if updates:
            updates["updated_by"] = actor["id"]; updates["updated_at"] = NOW()
            with WRITE_LOCK:
                self.admin.execute(
                    "UPDATE home_sections SET %s WHERE key=?"
                    % ", ".join("%s=?" % k for k in updates),
                    list(updates.values()) + [key])
                self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM home_sections WHERE key=?", (key,)).fetchone())
        self.audit(actor["id"], "section.update", "home_section", key, before, after, ip)
        return after

    def toggle_section(self, actor, key, ip=""):
        """Flip a section's is_enabled flag (HTML toggle form only)."""
        self.require_role(actor, write=True)
        row = self.admin.execute("SELECT * FROM home_sections WHERE key=?", (key,)).fetchone()
        if not row:
            raise not_found()
        before = _row(row)
        new_state = 0 if row["is_enabled"] else 1
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE home_sections SET is_enabled=?, updated_by=?, updated_at=? WHERE key=?",
                (new_state, actor["id"], NOW(), key))
            self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM home_sections WHERE key=?", (key,)).fetchone())
        self.audit(actor["id"], "section.toggle", "home_section", key, before, after, ip)
        return after

    def delete_section(self, actor, key, ip=""):
        """Delete = disable + audit, never a hard delete. Cards stay."""
        self.require_role(actor, write=True)
        row = self.admin.execute("SELECT * FROM home_sections WHERE key=?", (key,)).fetchone()
        if not row:
            raise not_found()
        before = _row(row)
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE home_sections SET is_enabled=0, updated_by=?, updated_at=? WHERE key=?",
                (actor["id"], NOW(), key))
            self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM home_sections WHERE key=?", (key,)).fetchone())
        self.audit(actor["id"], "section.disable", "home_section", key, before, after, ip)
        return after

    def list_cards(self, actor, section_key):
        self.require_role(actor, write=False)
        sec = self.admin.execute("SELECT * FROM home_sections WHERE key=?", (section_key,)).fetchone()
        if not sec:
            raise not_found()
        rows = self.admin.execute(
            "SELECT * FROM slider_cards WHERE section_id=? ORDER BY position ASC, id ASC",
            (sec["id"],)).fetchall()
        return {"items": [_row(r) for r in rows], "section": _row(sec)}

    def add_card(self, actor, section_key, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"work_id", "position", "title_override", "starts_at", "ends_at"})
        sec = self.admin.execute("SELECT * FROM home_sections WHERE key=?", (section_key,)).fetchone()
        if not sec:
            raise not_found()
        work = self._get_work_any(body.get("work_id"))
        if not work:
            raise bad("That work does not exist in the catalog.")
        if not sec["is_adult_only"] and work.get("adult_flag") != 0:
            raise forbidden("That work is adult or its adult flag is unknown, so it cannot go in a non-adult section.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO slider_cards (section_id, work_id, position, title_override, "
                "is_enabled, starts_at, ends_at, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (sec["id"], work["id"], int(body.get("position", 0)),
                 scrub_text(body["title_override"], 100) if body.get("title_override") else None,
                 1, body.get("starts_at"), body.get("ends_at"), actor["id"], NOW()),
            )
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM slider_cards WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "card.create", "slider_card", row["id"], None, _row(row), ip)
        return _row(row)

    def update_card(self, actor, card_id, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"position", "title_override", "is_enabled", "starts_at", "ends_at"})
        row = self.admin.execute("SELECT * FROM slider_cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            raise not_found()
        before = _row(row)
        updates = {}
        if "position" in body:
            updates["position"] = int(body["position"])
        if "title_override" in body:
            updates["title_override"] = scrub_text(body["title_override"], 100) if body["title_override"] else None
        if "is_enabled" in body:
            updates["is_enabled"] = 1 if body["is_enabled"] else 0
        if "starts_at" in body:
            updates["starts_at"] = body["starts_at"]
        if "ends_at" in body:
            updates["ends_at"] = body["ends_at"]
        if updates:
            with WRITE_LOCK:
                self.admin.execute(
                    "UPDATE slider_cards SET %s WHERE id=?" % ", ".join("%s=?" % k for k in updates),
                    list(updates.values()) + [card_id])
                self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM slider_cards WHERE id=?", (card_id,)).fetchone())
        self.audit(actor["id"], "card.update", "slider_card", card_id, before, after, ip)
        return after

    def delete_card(self, actor, card_id, ip=""):
        """Deletes the pointer only. The catalog work is never touched."""
        self.require_role(actor, write=True)
        row = self.admin.execute("SELECT * FROM slider_cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            raise not_found()
        before = _row(row)
        with WRITE_LOCK:
            self.admin.execute("DELETE FROM slider_cards WHERE id=?", (card_id,))
            self.admin.commit()
        self.audit(actor["id"], "card.delete", "slider_card", card_id, before, None, ip)
        return {"ok": True}

    def hide_content(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"scope", "scope_id", "reason", "note", "expires_at"})
        if body.get("scope") not in ("work", "release", "section", "host_kind", "section_work"):
            raise bad("Unknown hide scope.")
        if body.get("reason") not in VISIBILITY_REASONS:
            raise bad("Unknown hide reason.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO content_visibility (scope, scope_id, is_hidden, reason, note, "
                "expires_at, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (body["scope"], str(body["scope_id"]), 1, body["reason"],
                 scrub_text(body.get("note", ""), 200) if body.get("note") else None,
                 body.get("expires_at"), actor["id"], NOW()),
            )
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM content_visibility WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "content.hide", "content_visibility", row["id"], None, _row(row), ip)
        return _row(row)

    def unhide_content(self, actor, visibility_id, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"note"})
        row = self.admin.execute("SELECT * FROM content_visibility WHERE id=?", (visibility_id,)).fetchone()
        if not row:
            raise not_found()
        before = _row(row)
        # Unhide never overrides the adult clause: the fixture app still
        # hides adult/unknown works on non-adult surfaces after restore.
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE content_visibility SET restored_at=?, restored_by=? WHERE id=?",
                (NOW(), actor["id"], visibility_id))
            self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM content_visibility WHERE id=?", (visibility_id,)).fetchone())
        self.audit(actor["id"], "content.unhide", "content_visibility", visibility_id, before, after, ip)
        return after

    def list_hidden(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT * FROM content_visibility WHERE is_hidden=1 AND restored_at IS NULL "
            "ORDER BY id DESC LIMIT 100").fetchall()
        return {"items": [_row(r) for r in rows]}

    def is_work_hidden(self, work_id, section_key=None):
        now = NOW()
        rows = self.admin.execute(
            "SELECT * FROM content_visibility WHERE is_hidden=1 AND restored_at IS NULL").fetchall()
        for r in rows:
            if r["expires_at"] and r["expires_at"] < now:
                continue
            if r["scope"] == "work" and str(r["scope_id"]) == str(work_id):
                return True
            if section_key and r["scope"] == "section_work" and r["scope_id"] == "%s:%s" % (section_key, work_id):
                return True
        return False

    # -- categories --------------------------------------------------------
    def list_categories(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute("SELECT * FROM categories ORDER BY position ASC, id ASC").fetchall()
        return {"items": [_row(r) for r in rows]}

    def create_category(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"key", "display_name", "position", "is_enabled", "is_adult_only"})
        if not valid_slug(body.get("key", "")):
            raise bad("Category key must be lowercase letters, numbers, dash or underscore.")
        sec = self.admin.execute("SELECT * FROM home_sections WHERE key=?", (body["key"],)).fetchone()
        if sec:
            raise conflict("That key is already used by a home section.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO categories (key, display_name, position, is_enabled, is_adult_only, "
                "created_by, updated_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (body["key"], scrub_text(body.get("display_name", ""), 100),
                 int(body.get("position", 0)), 1 if body.get("is_enabled", True) else 0,
                 1 if body.get("is_adult_only", False) else 0, actor["id"], actor["id"], NOW(), NOW()),
            )
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM categories WHERE id=?", (cur.lastrowid,)).fetchone()
            self.admin.execute(
                "INSERT INTO category_history (category_id, action, before_json, after_json, actor_id, created_at) "
                "VALUES (?,?,?,?,?,?)", (row["id"], "create", None, json.dumps(_row(row)), actor["id"], NOW()))
            self.admin.commit()
        self.audit(actor["id"], "category.create", "category", body["key"], None, _row(row), ip)
        return _row(row)

    def update_category(self, actor, key, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"display_name", "position", "is_enabled", "is_adult_only"})
        row = self.admin.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone()
        if not row:
            raise not_found()
        before = _row(row)
        updates = {}
        if "display_name" in body:
            updates["display_name"] = scrub_text(body["display_name"], 100)
        if "position" in body:
            updates["position"] = int(body["position"])
        if "is_enabled" in body:
            updates["is_enabled"] = 1 if body["is_enabled"] else 0
        if "is_adult_only" in body:
            updates["is_adult_only"] = 1 if body["is_adult_only"] else 0
        if updates:
            updates["updated_by"] = actor["id"]; updates["updated_at"] = NOW()
            with WRITE_LOCK:
                self.admin.execute(
                    "UPDATE categories SET %s WHERE key=?" % ", ".join("%s=?" % k for k in updates),
                    list(updates.values()) + [key])
                self.admin.execute(
                    "INSERT INTO category_history (category_id, action, before_json, after_json, actor_id, created_at) "
                    "VALUES (?,?,?,?,?,?)", (row["id"], "update", json.dumps(before),
                     json.dumps(_row(self.admin.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone())),
                     actor["id"], NOW()))
                self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone())
        self.audit(actor["id"], "category.update", "category", key, before, after, ip)
        return after

    def delete_category(self, actor, key, ip=""):
        self.require_role(actor, write=True)
        row = self.admin.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone()
        if not row:
            raise not_found()
        n_works = self.admin.execute(
            "SELECT COUNT(*) AS n FROM category_works WHERE category_id=?", (row["id"],)).fetchone()["n"]
        n_secs = self.admin.execute(
            "SELECT COUNT(*) AS n FROM home_sections WHERE category_key=? AND is_enabled=1", (key,)).fetchone()["n"]
        if n_works or n_secs:
            raise conflict("Remove its works and change its sections first. That category is still in use.")
        with WRITE_LOCK:
            self.admin.execute("DELETE FROM categories WHERE key=?", (key,))
            self.admin.commit()
        self.audit(actor["id"], "category.delete", "category", key, _row(row), None, ip)
        return {"ok": True}

    def assign_category_work(self, actor, key, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"work_id", "position"})
        cat = self.admin.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone()
        if not cat:
            raise not_found()
        work = self._get_work_any(body.get("work_id"))
        if not work:
            raise bad("That work does not exist in the catalog.")
        if not cat["is_adult_only"] and work.get("adult_flag") != 0:
            raise forbidden("That work is adult or its adult flag is unknown, so it cannot go in a non-adult category.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO category_works (category_id, work_id, position, created_by, created_at) "
                "VALUES (?,?,?,?,?)",
                (cat["id"], work["id"], int(body.get("position", 0)), actor["id"], NOW()))
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM category_works WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "category.assign", "category_work", row["id"], None, _row(row), ip)
        return _row(row)

    def list_category_works(self, actor, key):
        self.require_role(actor, write=False)
        cat = self.admin.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone()
        if not cat:
            raise not_found()
        rows = self.admin.execute(
            "SELECT * FROM category_works WHERE category_id=? ORDER BY position ASC, id ASC",
            (cat["id"],)).fetchall()
        return {"items": [_row(r) for r in rows], "category": _row(cat)}

    def unassign_category_work(self, actor, key, work_id, ip=""):
        self.require_role(actor, write=True)
        cat = self.admin.execute("SELECT * FROM categories WHERE key=?", (key,)).fetchone()
        if not cat:
            raise not_found()
        with WRITE_LOCK:
            self.admin.execute(
                "DELETE FROM category_works WHERE category_id=? AND work_id=?", (cat["id"], work_id))
            self.admin.commit()
        self.audit(actor["id"], "category.unassign", "category_work", work_id, None, None, ip)
        return {"ok": True}

    # -- adult safety ------------------------------------------------------
    def get_content_safety(self, actor):
        self.require_role(actor, write=False)
        row = self.admin.execute("SELECT * FROM content_safety WHERE id=1").fetchone()
        return _row(row)

    def update_content_safety(self, actor, body, ip=""):
        """Global adult switch stays OFF (OD-18). Any attempt to turn it
        ON is refused, not warned-and-continued."""
        self.require_role(actor, write=True)
        self._validate_body(body, {"adult_content_enabled", "reason"})
        if body.get("adult_content_enabled"):
            raise forbidden("Adult content cannot be turned on from the panel: the app adult gate is not confirmed.")
        row = self.admin.execute("SELECT * FROM content_safety WHERE id=1").fetchone()
        before = _row(row)
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE content_safety SET adult_content_enabled=0, updated_by=?, updated_at=? WHERE id=1",
                (actor["id"], NOW()))
            self.admin.execute(
                "INSERT INTO content_safety_history (field, before_value, after_value, actor_id, reason, created_at) "
                "VALUES ('adult_content_enabled', ?, '0', ?, ?, ?)",
                (str(before["adult_content_enabled"]), actor["id"],
                 scrub_text(body.get("reason", ""), 200), NOW()))
            self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM content_safety WHERE id=1").fetchone())
        self.audit(actor["id"], "content_safety.update", "content_safety", 1, before, after, ip)
        return after

    def block_adult_globally(self, actor, body, ip=""):
        """Disable every adult-only section/category; data kept, restorable."""
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"reason"})
        with WRITE_LOCK:
            secs = self.admin.execute(
                "SELECT * FROM home_sections WHERE is_adult_only=1 AND is_enabled=1").fetchall()
            cats = self.admin.execute(
                "SELECT * FROM categories WHERE is_adult_only=1 AND is_enabled=1").fetchall()
            for s in secs:
                self.admin.execute("UPDATE home_sections SET is_enabled=0 WHERE id=?", (s["id"],))
                self.audit(actor["id"], "section.disable", "home_section", s["key"],
                           _row(s), {"is_enabled": 0}, ip)
            for c in cats:
                self.admin.execute("UPDATE categories SET is_enabled=0 WHERE id=?", (c["id"],))
                self.audit(actor["id"], "category.update", "category", c["key"],
                           _row(c), {"is_enabled": 0}, ip)
            self.admin.execute(
                "UPDATE content_safety SET adult_content_enabled=0, updated_by=?, updated_at=? WHERE id=1",
                (actor["id"], NOW()))
            self.admin.commit()
        return {"disabled_sections": len(secs), "disabled_categories": len(cats),
                "adult_content_enabled": 0}

    # -- remote config / monetization / publish ----------------------------
    def _config_row(self):
        return _row(self.admin.execute("SELECT * FROM app_remote_config_v2 WHERE id=1").fetchone())

    def _redacted_config(self, row):
        out = dict(row)
        # Token keys are removed entirely, not masked in place: a
        # redacted body must not contain a token key at all, or the
        # provenance scanner (correctly) fails it closed.
        out["shrinkme_configured"] = bool(row.get("shrinkme_api_token"))
        out["droplink_configured"] = bool(row.get("droplink_api_token"))
        out.pop("shrinkme_api_token", None)
        out.pop("droplink_api_token", None)
        # apk_update_url is a real URL: it must never reach the audit
        # log / redacted payload (the provenance scanner fails closed
        # on any URL value). Keep only a configured flag here; the app
        # reads the real URL from the live catalog row, not this dict.
        out["apk_update_url_configured"] = bool(row.get("apk_update_url"))
        out.pop("apk_update_url", None)
        return redact_payload(out)

    def get_remote_config(self, actor):
        self.require_role(actor, write=False)
        row = self._config_row()
        out = self._redacted_config(row)
        live = self._live_catalog()
        if live is not None:
            try:
                real = live.read_remote_config_masked()
                for k in REMOTE_CONFIG_FIELDS:
                    if k in real:
                        out[k] = real[k]
                out["shrinkme_configured"] = real.get("shrinkme_configured", False)
                out["droplink_configured"] = real.get("droplink_configured", False)
                out["live_source"] = "app_remote_config (catalog DB, id=1) — what the app reads"
            except LiveUnavailable:
                out["live_source"] = "panel only (no live catalog wired)"
        else:
            out["live_source"] = "panel only (no live catalog wired)"
        return out

    def get_monetization(self, actor):
        self.require_role(actor, write=False)
        live = self._live_catalog()
        if live is not None:
            try:
                return live.read_remote_config_masked()
            except LiveUnavailable:
                pass
        row = self._config_row()
        out = {}
        for k in MONETIZATION_FIELDS:
            if k in ("shrinkme_api_token", "droplink_api_token"):
                continue  # never serialised; see *_configured flags below
            out[k] = row[k]
        out["shrinkme_configured"] = bool(row.get("shrinkme_api_token"))
        out["droplink_configured"] = bool(row.get("droplink_api_token"))
        return out

    def put_monetization(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, set(MONETIZATION_FIELDS))
        if not body:
            raise bad("Empty body clears nothing. Send at least one field.")
        # An empty token field never wipes a stored token: the
        # Monetization form leaves token inputs blank to mean "keep",
        # and a JSON caller sending "" means the same. A token is
        # replaced only by sending a new value. Filtered here (not in
        # the form) so JSON and form callers get the same protection.
        body = {k: v for k, v in body.items()
                if not (k in ("shrinkme_api_token", "droplink_api_token")
                        and not str(v or "").strip())}
        if not body:
            raise bad("Empty body clears nothing. Send at least one field.")
        for k in ("vip_monthly_pkr", "vip_yearly_pkr"):
            if k in body and not (0 <= int(body[k]) <= 10_000_000):
                raise bad("VIP price must be between 0 and 10,000,000.")
        for k in COIN_REDEEM_FIELDS:
            if k in body and not (0 <= int(body[k]) <= 10_000_000):
                raise bad("Coin price must be between 0 and 10,000,000.")
        for k in ("maintenance_mode", "feature_downloads", "feature_pure_cinema",
                  "feature_chromecast", "feature_quality_gate"):
            if k in body and int(body[k]) not in (0, 1):
                raise bad("That flag must be 0 or 1.")
        before = self.get_monetization(actor)
        live = self._live_catalog()
        if live is not None:
            # The live app_remote_config row is the source of truth the
            # app reads. WRITE path: tests run this on a COPY; live use
            # needs a catalog backup before first use (see handoff).
            live.save_remote_config(dict(body))
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE app_remote_config_v2 SET %s WHERE id=1"
                % ", ".join("%s=?" % k for k in body), list(body.values()))
            self.admin.commit()
        after = self.get_monetization(actor)
        self.audit(actor["id"], "monetization.save", "app_remote_config", 1, before, after, ip)
        return after

    def draft_remote_config(self, actor, body, ip=""):
        """Draft only: writes the row, does NOT bump config_version."""
        self.require_role(actor, write=True)
        allowed = {"min_version_code", "latest_version_code", "latest_version_name",
                   "force_update", "force_update_message", "maintenance_message",
                   "brand_primary", "brand_accent", "region_order", "free_quality_cap",
                   "maintenance_mode", "apk_update_url"}
        self._validate_body(body, allowed)
        # Form posts send "" for a cleared number; store NULL, not "".
        for k in ("min_version_code", "latest_version_code"):
            if k in body and (body[k] == "" or body[k] is None):
                body[k] = None
            elif k in body:
                try:
                    body[k] = int(body[k])
                except (TypeError, ValueError):
                    raise bad("%s must be a whole number." % k)
        for k in ("force_update", "maintenance_mode"):
            if k in body:
                try:
                    body[k] = int(body[k])
                except (TypeError, ValueError):
                    raise bad("%s must be 0 or 1." % k)
        if "brand_primary" in body and not valid_hex(body["brand_primary"]):
            raise bad("Brand colour must be a hex colour.")
        if "brand_accent" in body and not valid_hex(body["brand_accent"]):
            raise bad("Brand colour must be a hex colour.")
        if "region_order" in body:
            parts = [p.strip() for p in body["region_order"].split(",")]
            if any(p not in ("pakistan", "india", "asia", "international") for p in parts):
                raise bad("Region order must use only pakistan, india, asia, international.")
        if "free_quality_cap" in body and body["free_quality_cap"] not in ("480p", "720p"):
            raise bad("Free quality cap is 480p or 720p only in this version.")
        before = self._redacted_config(self._config_row())
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE app_remote_config_v2 SET %s, updated_by=?, updated_at=? WHERE id=1"
                % ", ".join("%s=?" % k for k in body),
                list(body.values()) + [actor["id"], NOW()])
            self.admin.commit()
        # maintenance_mode / apk_update_url are real app fields: when a
        # live catalog is wired, the draft also writes them to the live
        # app_remote_config row (the app reads that row, not the draft).
        # v2-only fields (versions, brand, region order) stay panel-only
        # and are served via v2's own endpoint, labelled app-side pending.
        live = self._live_catalog()
        if live is not None:
            real_fields = {k: body[k] for k in ("maintenance_mode", "apk_update_url") if k in body}
            if real_fields:
                live.save_remote_config(real_fields)
        after = self._redacted_config(self._config_row())
        self.audit(actor["id"], "remote_config.draft", "app_remote_config", 1, before, after, ip)
        return after

    def _home_snapshot(self):
        sections = self.admin.execute(
            "SELECT * FROM home_sections ORDER BY position ASC, id ASC").fetchall()
        out = []
        for s in sections:
            cards = self.admin.execute(
                "SELECT * FROM slider_cards WHERE section_id=? ORDER BY position ASC, id ASC",
                (s["id"],)).fetchall()
            out.append({"section": _row(s), "cards": [_row(c) for c in cards]})
        return {"sections": out, "visibility": self.list_hidden({"role": "auditor"})["items"]}

    def _seed_published_home(self):
        n = self.admin.execute("SELECT COUNT(*) AS n FROM app_remote_config_history").fetchone()["n"]
        if n:
            return
        row = self._config_row()
        snap = {"config": self._redacted_config(row), "home": self._home_snapshot()}
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT INTO app_remote_config_history (config_version, snapshot_json, published_by, published_at) "
                "VALUES (?,?,NULL,?)", (row["config_version"], json.dumps(snap), NOW()))
            self.admin.commit()

    def _do_publish(self, published_by):
        """The publish itself: guards, version bump, history row.

        Shared by the manual publish and the scheduled fire, so the two can
        never drift apart: the same adult blockers and the same empty-home
        refusal apply at fire time as at click time. Returns the new version.
        Raises the same ApiError the manual path raises; the caller decides
        what a refusal means (an error to the operator, a blocked schedule).
        """
        blockers = self._adult_blockers()
        if blockers:
            raise forbidden("Publish is blocked: an adult or unknown-flag work is in a non-adult section.")
        sections = self.admin.execute(
            "SELECT COUNT(*) AS n FROM home_sections WHERE is_enabled=1").fetchone()["n"]
        if sections == 0:
            raise forbidden("This would leave the app home empty. Enable at least one section first.")
        row = self._config_row()
        new_version = row["config_version"] + 1
        snap = {"config": self._redacted_config(row), "home": self._home_snapshot()}
        snap["config"]["config_version"] = new_version
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE app_remote_config_v2 SET config_version=?, updated_by=?, updated_at=? WHERE id=1",
                (new_version, published_by, NOW()))
            self.admin.execute(
                "INSERT INTO app_remote_config_history (config_version, snapshot_json, published_by, published_at) "
                "VALUES (?,?,?,?)", (new_version, json.dumps(snap), published_by, NOW()))
            self.admin.commit()
        return new_version

    def publish_remote_config(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"confirm"})
        if not body or not body.get("confirm"):
            raise bad("Publish needs confirm set to true.")
        before_version = self._config_row()["config_version"]
        new_version = self._do_publish(actor["id"])
        self.audit(actor["id"], "remote_config.publish", "app_remote_config", 1,
                   {"config_version": before_version}, {"config_version": new_version}, ip)
        return {"config_version": new_version, "refresh_note": "visible on next app refresh"}

    def _admin_display_name(self, user_id):
        """Who an author id is, for the Live page: the admin's username
        when known, "system" for the seeded NULL/0 row, and "user N" as
        a fallback for an id with no admin row. The seeded first publish
        was never a person, so it must never render as "user 0"."""
        if user_id is None:
            return "system"
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return "system"
        if uid == 0:
            return "system"
        row = self.admin.execute(
            "SELECT username FROM admin_users WHERE id=?", (uid,)).fetchone()
        if row:
            return row["username"]
        return "user %d" % uid

    def get_live(self, actor):
        """What the app is actually serving, against the draft waiting to go out.

        `live` is the newest published snapshot (None before the first
        publish); `draft` is the current draft row plus its home snapshot.
        `changed_keys` names the config keys whose draft value differs from
        the live snapshot's — the honest answer to "what would publishing do
        right now". Section counts are the same question for the home rails.
        """
        self.require_role(actor, write=False)
        hist = self.admin.execute(
            "SELECT * FROM app_remote_config_history ORDER BY config_version DESC LIMIT 1").fetchone()
        live = None
        if hist is not None:
            snap = json.loads(hist["snapshot_json"])
            live = {
                "config_version": hist["config_version"],
                "published_by": hist["published_by"],
                "published_by_name": self._admin_display_name(hist["published_by"]),
                "published_at": hist["published_at"],
                "config": snap.get("config", {}),
                "sections": len(snap.get("home", {}).get("sections", [])),
            }
        draft_row = self._config_row()
        draft_config = self._redacted_config(draft_row)
        draft_sections = self.admin.execute(
            "SELECT COUNT(*) AS n FROM home_sections WHERE is_enabled=1").fetchone()["n"]
        changed = []
        if live is not None:
            live_config = live["config"]
            for key in sorted(set(draft_config) | set(live_config)):
                # Bookkeeping, not operator settings: the publish itself
                # bumps these, so they would differ after every publish.
                if key in ("config_version", "updated_at", "updated_by"):
                    continue
                if draft_config.get(key) != live_config.get(key):
                    changed.append(key)
        return {
            "live": live,
            "draft": {"config_version": draft_row["config_version"],
                      "config": draft_config, "sections": draft_sections},
            "changed_keys": changed,
        }

    def schedule_publish(self, actor, body, ip=""):
        """Queue a publish for a future moment. The draft is published as it
        stands when the moment arrives — not as it stood when scheduled — so
        an operator can queue the slot and keep editing until then.
        """
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"scheduled_at", "note"})
        at = _parse_broadcast_time(body.get("scheduled_at"), "scheduled_at")
        if at is None:
            raise bad("scheduled_at is required.")
        if at <= int(time.time()):
            raise bad("scheduled_at must be in the future.")
        note = scrub_text(body.get("note", ""), 200) if body.get("note") else ""
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO scheduled_publishes "
                "(scheduled_at, status, created_by, created_at, note) "
                "VALUES (?,?,?,?,?)",
                (at, "pending", actor["id"], NOW(), note))
            self.admin.commit()
            row_id = cur.lastrowid
        self.audit(actor["id"], "remote_config.schedule", "scheduled_publish", row_id,
                   {}, {"scheduled_at": at}, ip)
        return self._scheduled_row(row_id)

    def cancel_scheduled_publish(self, actor, schedule_id, body=None, ip=""):
        """Cancel a pending schedule. A fired, blocked or already-cancelled
        schedule is history, not something to cancel."""
        self.require_role(actor, write=True)
        row = self.admin.execute(
            "SELECT * FROM scheduled_publishes WHERE id=?", (schedule_id,)).fetchone()
        if row is None:
            raise not_found("That scheduled publish was not found.")
        if row["status"] != "pending":
            raise bad("Only a pending schedule can be cancelled.")
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE scheduled_publishes SET status='cancelled', cancel_at=?, cancel_by=? WHERE id=?",
                (NOW(), actor["id"], schedule_id))
            self.admin.commit()
        self.audit(actor["id"], "remote_config.schedule_cancel", "scheduled_publish",
                   schedule_id, {"status": "pending"}, {"status": "cancelled"}, ip)
        return self._scheduled_row(schedule_id)

    def list_scheduled(self, actor):
        """Pending schedules first, then the recent finished ones."""
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT * FROM scheduled_publishes "
            "ORDER BY (status = 'pending') DESC, scheduled_at ASC LIMIT 20").fetchall()
        return {"items": [_row(r) for r in rows]}

    def _scheduled_row(self, schedule_id):
        row = self.admin.execute(
            "SELECT * FROM scheduled_publishes WHERE id=?", (schedule_id,)).fetchone()
        return _row(row)

    def fire_due_scheduled_publishes(self, now=None):
        """Publish every due schedule. Called by the background loop, never
        by a request: a scheduled publish is a job, not a click.

        A schedule fires the draft as it stands at the moment, through the
        same guards as a manual publish. A guard refusal marks that schedule
        `blocked` and moves on — it is not retried, because a blocker that
        appeared since scheduling is a decision for the operator, not a
        transient to spin on. Returns how many fired.
        """
        at = int(now if now is not None else time.time())
        due = self.admin.execute(
            "SELECT * FROM scheduled_publishes WHERE status='pending' AND scheduled_at<=? "
            "ORDER BY scheduled_at ASC", (at,)).fetchall()
        fired = 0
        for row in due:
            try:
                new_version = self._do_publish(row["created_by"])
            except ApiError:
                with WRITE_LOCK:
                    self.admin.execute(
                        "UPDATE scheduled_publishes SET status='blocked' WHERE id=?",
                        (row["id"],))
                    self.admin.commit()
                continue
            with WRITE_LOCK:
                self.admin.execute(
                    "UPDATE scheduled_publishes SET status='fired', fired_at=?, fired_version=? WHERE id=?",
                    (at, new_version, row["id"]))
                self.admin.commit()
            self.audit(row["created_by"], "remote_config.publish_scheduled",
                       "scheduled_publish", row["id"],
                       {"status": "pending"},
                       {"status": "fired", "config_version": new_version}, "")
            fired += 1
        return fired

    def rollback_remote_config(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"version", "confirm"})
        if not body.get("confirm"):
            raise bad("Rollback needs confirm set to true.")
        hist = self.admin.execute(
            "SELECT * FROM app_remote_config_history WHERE config_version=? ORDER BY id DESC LIMIT 1",
            (body["version"],)).fetchone()
        if not hist:
            raise not_found("That config version was not found in history.")
        snap = json.loads(hist["snapshot_json"])
        cfg = snap["config"]
        row = self._config_row()
        new_version = row["config_version"] + 1
        # Apply the snapshot as a NEW version; history rows are never edited.
        allowed = [k for k in cfg if k in MONETIZATION_FIELDS or k in (
            "min_version_code", "latest_version_code", "latest_version_name", "force_update",
            "force_update_message", "maintenance_message", "brand_primary", "brand_accent",
            "region_order", "free_quality_cap")]
        values = {}
        for k in allowed:
            v = cfg[k]
            if k in ("shrinkme_api_token", "droplink_api_token"):
                continue  # tokens are never restored from a redacted snapshot
            values[k] = v
        with WRITE_LOCK:
            if values:
                self.admin.execute(
                    "UPDATE app_remote_config_v2 SET %s WHERE id=1"
                    % ", ".join("%s=?" % k for k in values), list(values.values()))
            self.admin.execute(
                "UPDATE app_remote_config_v2 SET config_version=?, updated_by=?, updated_at=? WHERE id=1",
                (new_version, actor["id"], NOW()))
            new_snap = {"config": self._redacted_config(self._config_row()), "home": snap.get("home")}
            new_snap["config"]["config_version"] = new_version
            self.admin.execute(
                "INSERT INTO app_remote_config_history (config_version, snapshot_json, published_by, published_at) "
                "VALUES (?,?,?,?)", (new_version, json.dumps(new_snap), actor["id"], NOW()))
            self.admin.commit()
        # The live catalog is the source of truth the app reads: a
        # rollback that only restores the panel row leaves the app
        # seeing the pre-rollback prices/flags. Push the restored
        # monetization fields (the ones the live catalog carries) back
        # to the live app_remote_config row as well. v2-only fields
        # (versions, brand, region order) stay panel-only.
        live = self._live_catalog()
        if live is not None and values:
            live_fields = {k: v for k, v in values.items()
                           if k in MONETIZATION_FIELDS}
            if live_fields:
                live.save_remote_config(live_fields)
        self.audit(actor["id"], "remote_config.rollback", "app_remote_config", 1,
                   {"config_version": row["config_version"]}, {"config_version": new_version}, ip)
        return {"config_version": new_version, "restored_from": body["version"],
                "refresh_note": "visible on next app refresh"}

    def list_config_history(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT id, config_version, published_by, published_at FROM app_remote_config_history "
            "ORDER BY config_version DESC LIMIT 50").fetchall()
        items = []
        for r in rows:
            item = _row(r)
            item["published_by_name"] = self._admin_display_name(r["published_by"])
            items.append(item)
        return {"items": items}

    # -- users / VIP / payments (ledger flow only) -------------------------
    def search_users(self, actor, q="", tier=None, after_id=None, limit=20):
        self.require_role(actor, write=False)
        live = self._live_ledger()
        if live is not None:
            return live.search_users(q=q, tier=tier, limit=limit)
        rows = self.ledger.execute("SELECT * FROM app_accounts ORDER BY account_hint ASC").fetchall()
        items = []
        for r in rows:
            d = _row(r)
            if q and q not in d["account_hint"]:
                continue
            if tier and d["tier"] != tier:
                continue
            items.append(d)
        return {"items": items, "count": len(items)}

    def user_payment_history(self, actor, account_hint):
        """Per-user payment history (real ledger when wired)."""
        self.require_role(actor, write=False)
        live = self._live_ledger()
        if live is not None:
            return live.user_payment_history(account_hint)
        rows = self.ledger.execute(
            "SELECT id, account_hint, method, amount_pkr, months, status, created_at, decided_at "
            "FROM payment_claims WHERE account_hint=? ORDER BY id DESC LIMIT 100",
            (account_hint,)).fetchall()
        return {"items": [_row(r) for r in rows], "count": len(rows)}

    def _idempotency_check(self, key, action, target_id):
        if not key:
            return None
        row = self.admin.execute(
            "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,)).fetchone()
        # Table is created lazily below; see _ensure_idempotency.
        if row and row["action"] == action and str(row["target_id"]) == str(target_id):
            return json.loads(row["result_json"])
        return None

    def _ensure_idempotency(self):
        self.admin.execute(
            "CREATE TABLE IF NOT EXISTS idempotency_keys (idempotency_key TEXT PRIMARY KEY, "
            "action TEXT, target_id TEXT, result_json TEXT, created_at INTEGER)")
        self.admin.commit()

    def _record_idempotency(self, key, action, target_id, result):
        if not key:
            return
        self._ensure_idempotency()
        self.admin.execute(
            "INSERT OR IGNORE INTO idempotency_keys VALUES (?,?,?,?,?)",
            (key, action, str(target_id), json.dumps(result), NOW()))

    def approve_payment(self, actor, payment_id, body, idempotency_key=None, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"confirm", "note"})
        if not body or not body.get("confirm"):
            raise bad("Approve needs confirm set to true.")
        live = self._live_ledger()
        if live is not None:
            # v1 semantics + the cross-account TID rule, in one
            # BEGIN IMMEDIATE txn inside LiveStores. A replay returns
            # changed: False (no double credit) instead of an error.
            note = scrub_text(body.get("note", ""), 200) if body.get("note") else ""
            res = live.approve_payment(
                payment_id, reviewer=actor.get("username", "operator"),
                note=note)
            if res.get("changed"):
                self.audit(actor["id"], "payment.approve", "payment", payment_id,
                           {"status": "pending"}, {"status": "approved"}, ip)
            return res
        self._ensure_idempotency()
        # The status check AND the credit must hold one lock together:
        # checking outside the lock let concurrent approves all see
        # "pending" and credit twice. The lock covers check + write.
        with WRITE_LOCK:
            cached = self._idempotency_check(idempotency_key, "payment.approve", payment_id)
            if cached is not None:
                return cached
            claim = self.ledger.execute(
                "SELECT * FROM payment_claims WHERE id=?", (payment_id,)).fetchone()
            if not claim:
                raise not_found()
            if claim["status"] != "pending":
                raise conflict("That payment is no longer pending.")
            now = NOW()
            # Ledger transaction first: credit + close the row together.
            acct = self.ledger.execute(
                "SELECT * FROM app_accounts WHERE account_hint=?", (claim["account_hint"],)).fetchone()
            base = max(acct["vip_until"] or now, now) if acct else now
            new_until = base + claim["months"] * 30 * 86400
            self.ledger.execute(
                "UPDATE payment_claims SET status='approved', decided_at=?, decided_by=? WHERE id=?",
                (now, actor["id"], payment_id))
            if acct:
                self.ledger.execute(
                    "UPDATE app_accounts SET tier='vip', vip_until=? WHERE account_hint=?",
                    (new_until, claim["account_hint"]))
            self.ledger.execute(
                "INSERT INTO ledger_entries (account_hint, kind, months, payment_id, note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (claim["account_hint"], "vip_credit", claim["months"], payment_id, "approved", now))
            self.ledger.commit()
            result = {"payment_id": payment_id, "status": "approved",
                      "account_hint": claim["account_hint"], "vip_until": new_until}
            self._record_idempotency(idempotency_key, "payment.approve", payment_id, result)
            self.admin.commit()
        self.audit(actor["id"], "payment.approve", "payment", payment_id,
                   {"status": "pending"}, {"status": "approved"}, ip)
        return result

    def reject_payment(self, actor, payment_id, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"confirm", "note"})
        if not body or not body.get("confirm"):
            raise bad("Reject needs confirm set to true.")
        live = self._live_ledger()
        if live is not None:
            note = scrub_text(body.get("note", ""), 200) if body.get("note") else ""
            res = live.reject_payment(
                payment_id, reviewer=actor.get("username", "operator"),
                note=note)
            if res.get("changed"):
                self.audit(actor["id"], "payment.reject", "payment", payment_id,
                           {"status": "pending"}, {"status": "rejected"}, ip)
            return {"payment_id": payment_id, "status": res["status"],
                    "changed": res.get("changed", True)}
        claim = self.ledger.execute(
            "SELECT * FROM payment_claims WHERE id=?", (payment_id,)).fetchone()
        if not claim:
            raise not_found()
        if claim["status"] != "pending":
            raise conflict("That payment is no longer pending.")
        with WRITE_LOCK:
            self.ledger.execute(
                "UPDATE payment_claims SET status='rejected', decided_at=?, decided_by=? WHERE id=?",
                (NOW(), actor["id"], payment_id))
            self.ledger.commit()
        self.audit(actor["id"], "payment.reject", "payment", payment_id,
                   {"status": "pending"}, {"status": "rejected"}, ip)
        return {"payment_id": payment_id, "status": "rejected"}

    def add_refund_note(self, actor, payment_id, body, ip=""):
        """Refund/adjustment NOTE only: audited, no status or VIP
        change, no money movement. On the real ledger it lands as a
        payment_review_audit 'adjustment_note' row; on fixtures it is
        recorded in the panel audit log only."""
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"note"})
        note = scrub_text(body.get("note", ""), 200) if body.get("note") else ""
        if not note:
            raise bad("A refund/adjustment note needs note text.")
        live = self._live_ledger()
        if live is not None:
            res = live.add_refund_note(
                payment_id, reviewer=actor.get("username", "operator"), note=note)
            self.audit(actor["id"], "payment.refund_note", "payment", payment_id,
                       None, {"note": note}, ip)
            return res
        row = self.ledger.execute(
            "SELECT * FROM payment_claims WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise not_found()
        self.audit(actor["id"], "payment.refund_note", "payment", payment_id,
                   None, {"note": note}, ip)
        return {"payment_id": payment_id, "status": row["status"], "note": note,
                "note_only": True}

    def list_payments(self, actor, status=None, method=None, after_id=None, limit=20,
                      min_amount=None, max_amount=None, from_ts=None, to_ts=None):
        self.require_role(actor, write=False)
        live = self._live_ledger()
        if live is not None:
            return live.list_payments(status=status, method=method, after_id=after_id,
                                      limit=limit, min_amount=min_amount,
                                      max_amount=max_amount, from_ts=from_ts,
                                      to_ts=to_ts)
        sql = "SELECT id, account_hint, method, amount_pkr, months, status, created_at, decided_at FROM payment_claims WHERE 1=1"
        params = []
        if status:
            sql += " AND status=?"; params.append(status)
        if method:
            sql += " AND method=?"; params.append(method)
        if after_id:
            sql += " AND id < ?"; params.append(int(after_id))
        sql += " ORDER BY id DESC LIMIT ?"; params.append(max(1, min(int(limit or 20), 100)))
        rows = self.ledger.execute(sql, params).fetchall()
        # List view never renders a transaction id, even a hashed one.
        return self._list(rows, after_id, limit)

    def get_payment(self, actor, payment_id):
        """Operator-only detail: confirms a match, never renders the id.

        This is deliberately stricter than the v1 display rule: the
        operator matches a claim by amount/method/hint and by searching
        with the id (see search_payment_by_tid), but the panel never
        prints the id back, so a screenshot or log cannot leak it.
        """
        self.require_role(actor, write=False)
        live = self._live_ledger()
        if live is not None:
            return live.get_payment(payment_id)
        row = self.ledger.execute(
            "SELECT id, account_hint, method, amount_pkr, months, status, created_at, decided_at, "
            "CASE WHEN tid_value IS NOT NULL THEN 1 ELSE 0 END AS tid_present "
            "FROM payment_claims WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise not_found()
        return _row(row)

    def search_payment_by_tid(self, actor, tid_value):
        """Operator-only: returns the matching claim without rendering the id.

        The caller supplies the id (from their own message); the server
        compares its stored hash and returns the claim with tid_present
        only. The supplied value is never logged or audited.
        """
        self.require_role(actor, write=False)
        if not tid_value:
            raise bad("A transaction id is required to search.")
        live = self._live_ledger()
        if live is not None:
            return live.search_payment_by_tid(tid_value)
        digest = hashlib.sha256(str(tid_value).encode()).hexdigest()
        rows = self.ledger.execute(
            "SELECT id, account_hint, method, amount_pkr, months, status, created_at "
            "FROM payment_claims WHERE tid_value=?", (digest,)).fetchall()
        return {"items": [_row(r) for r in rows], "count": len(rows)}

    # -- movie requests (v1 /admin/requests, Session 78; D2.6) --------------
    def usage_summary(self, actor, window_days=30):
        """Aggregates-only usage (Tracking A): installs, live devices,
        retention, playback, per-dimension counts, money.

        Mirrors v1 admin_panel.screen_usage, which returns
        `usage_stats.summary()` — the panel's own read is
        `LiveStores.usage_summary()`, the same numbers from the same three
        tables. No live ledger means an honest empty state, like every
        other v1 screen.
        """
        self.require_role(actor, write=False)
        live = self._live_ledger()
        if live is None:
            return {"available": False, "detail": "no_usage_data_yet",
                    "window_days": max(1, int(window_days or 30))}
        return live.usage_summary(window_days=window_days)

    def list_requests(self, actor):
        """The operator's queue: open requests oldest-first + recent history.

        Mirrors v1 admin_panel._request_rows: titles and notes are the
        viewer's own words, so they are scrubbed at the edge (URLs
        removed); the account column is the one-way hint plus the linked
        profile name; the balance is the derived coin wallet. No live
        ledger means an honest empty state, like every other v1 screen.
        """
        self.require_role(actor, write=False)
        live = self._live_ledger()
        if live is None:
            return {"available": False, "open_count": 0, "open": [],
                    "recent": [], "crawlers": [],
                    "note": "That live store is not available here."}
        open_rows = live.list_movie_requests(status="open", oldest_first=True)
        recent = live.list_movie_requests(limit=20)
        ids = sorted({r["account_id"] for r in open_rows + recent})
        handles = live.request_account_handles(ids)
        balances = live.request_coin_balances(ids)
        for row in open_rows + recent:
            handle = handles.get(row["account_id"],
                                 {"hint": "acct-?", "profile": ""})
            row["hint"] = handle["hint"]
            row["profile"] = handle["profile"]
            row["balance"] = balances.get(row["account_id"], 0)
            row["title"] = scrub_text(row["title"], 100)
            row["notes"] = scrub_text(row["notes"], 200)
        return {
            "available": True,
            "open_count": len(open_rows),
            "open": open_rows,
            "recent": recent,
            # Handles only, no site names beyond the fleet list: the
            # trigger form offers the same crawlers the Fleet page does.
            "crawlers": [{"crawler_id": s} for s in sorted(FLEET_SITES)],
            "note": ("a trigger queues one bounded sync run for one site you pick;"
                     " it picks the title up only if that site lists it, so watch"
                     " the Fleet page for the run and mark the request indexed"
                     " when the title appears, or declined when it is not wanted."),
        }

    def review_request(self, actor, request_id, status, body=None, ip=""):
        """Close one request row (indexed / declined). One action per
        path, like v1's two review paths; the session CSRF token already
        binds the call, so the body carries only confirm.
        """
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"confirm"})
        if not body or not body.get("confirm"):
            raise bad("Review needs confirm set to true.")
        if status not in ("indexed", "declined"):
            raise bad("Unknown request status.")
        live = self._live_ledger()
        if live is None:
            raise LiveUnavailable()
        res = live.set_request_status(request_id, status)
        if res is None:
            raise not_found("No such request.")
        if res.get("changed"):
            self.audit(actor["id"], "request.review", "movie_request",
                       request_id, {"status": "open"},
                       {"status": status}, ip)
        return res

    def trigger_request_crawl(self, actor, body, ip=""):
        """Queue one bounded sync run for one open request (v1 trigger).

        The row is read before anything is queued, so a bad id or a
        closed request queues nothing. The run itself goes through the
        same fleet path as a manual crawler run — same audit, same
        bounded limit — and the request stays open until the operator
        has seen the title.
        """
        self.require_role(actor, write=True)
        self._validate_body(body or {},
                            {"request_id", "crawler", "mode", "limit"})
        try:
            request_id = int(body.get("request_id"))
        except (TypeError, ValueError):
            raise bad("Request id must be a positive integer.")
        if request_id < 1:
            raise bad("Request id must be a positive integer.")
        live = self._live_ledger()
        if live is None:
            raise LiveUnavailable()
        open_rows = live.list_movie_requests(status="open", limit=1000)
        if not any(r["id"] == request_id for r in open_rows):
            raise not_found("No such open request.")
        return self.run_fleet(actor, {
            "crawler": body.get("crawler"),
            "mode": body.get("mode", "sync"),
            "limit": body.get("limit", 25)}, ip)

    def vip_grant(self, actor, account_hint, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"months", "reason"})
        months = int(body.get("months", 0))
        if months < 1 or months > 24:
            raise bad("VIP grant must be 1 to 24 months.")
        live = self._live_ledger()
        if live is not None:
            # Real ledger: ledger-first (single BEGIN IMMEDIATE txn in
            # the ledger, audit row, no fake payment row), then the
            # panel-side vip_grants record, with compensating rollback
            # if the panel record fails.
            acct = live.get_account_by_hint(account_hint)
            reason = scrub_text(body.get("reason", ""), 200)
            result, audit_id = live.vip_grant_manual(
                acct["id"], months, reviewer=actor.get("username", "operator"),
                note=reason)
            try:
                with WRITE_LOCK:
                    cur = self.admin.execute(
                        "INSERT INTO vip_grants (account_hint, payment_id, months, reason, granted_by, created_at) "
                        "VALUES (?,?,?,?,?,?)",
                        (account_hint, None, months, reason, actor["id"], NOW()))
                    self.admin.commit()
                    grant = self.admin.execute("SELECT * FROM vip_grants WHERE id=?", (cur.lastrowid,)).fetchone()
            except Exception:
                live.rollback_manual_grant(acct["id"], result["prior_vip_until"], audit_id)
                raise
            self.audit(actor["id"], "vip.grant", "vip_grant", grant["id"], None, _row(grant), ip)
            return {"grant": _row(grant), "vip_until": result["vip_until"]}
        acct = self.ledger.execute(
            "SELECT * FROM app_accounts WHERE account_hint=?", (account_hint,)).fetchone()
        if not acct:
            raise not_found("That account was not found.")
        now = NOW()
        # Two SQLite files cannot share one transaction, so a grant
        # is ledger-first with a compensating rollback: if the admin
        # record fails, the ledger grant is undone before the error
        # is reported, instead of leaving VIP granted with no record.
        orig_tier, orig_until = acct["tier"], acct["vip_until"]
        cur_ledger = None
        with WRITE_LOCK:
            try:
                cur_ledger = self.ledger.execute(
                    "INSERT INTO ledger_entries (account_hint, kind, months, payment_id, note, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (account_hint, "vip_grant", months, None, scrub_text(body.get("reason", ""), 200), now))
                base = max(acct["vip_until"] or now, now)
                new_until = base + months * 30 * 86400
                self.ledger.execute(
                    "UPDATE app_accounts SET tier='vip', vip_until=? WHERE account_hint=?",
                    (new_until, account_hint))
                self.ledger.commit()
                cur = self.admin.execute(
                    "INSERT INTO vip_grants (account_hint, payment_id, months, reason, granted_by, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (account_hint, None, months, scrub_text(body.get("reason", ""), 200), actor["id"], now))
                self.admin.commit()
                grant = self.admin.execute("SELECT * FROM vip_grants WHERE id=?", (cur.lastrowid,)).fetchone()
            except Exception:
                try:
                    self.admin.rollback()
                except Exception:
                    pass
                try:
                    if cur_ledger is not None:
                        self.ledger.execute(
                            "DELETE FROM ledger_entries WHERE id=?", (cur_ledger.lastrowid,))
                    self.ledger.execute(
                        "UPDATE app_accounts SET tier=?, vip_until=? WHERE account_hint=?",
                        (orig_tier, orig_until, account_hint))
                    self.ledger.commit()
                except Exception:
                    try:
                        self.ledger.rollback()
                    except Exception:
                        pass
                raise
        self.audit(actor["id"], "vip.grant", "vip_grant", grant["id"], None, _row(grant), ip)
        return {"grant": _row(grant), "vip_until": new_until}

    def flag_user(self, actor, account_hint, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"flag", "reason", "expires_at"})
        if body.get("flag") not in ("banned", "device_reset_requested"):
            raise bad("Unknown user flag.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO user_flags (account_hint, flag, reason, expires_at, created_by, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (account_hint, body["flag"], scrub_text(body.get("reason", ""), 200),
                 body.get("expires_at"), actor["id"], NOW()))
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM user_flags WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "user.flag", "user_flag", row["id"], None, _row(row), ip)
        out = _row(row)
        out["enforcement"] = "stored, not enforced"
        return out

    def clear_flag(self, actor, flag_id, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"note"})
        row = self.admin.execute("SELECT * FROM user_flags WHERE id=?", (flag_id,)).fetchone()
        if not row:
            raise not_found()
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE user_flags SET cleared_at=?, cleared_by=? WHERE id=?",
                (NOW(), actor["id"], flag_id))
            self.admin.commit()
        self.audit(actor["id"], "user.flag_clear", "user_flag", flag_id, _row(row), {"cleared": True}, ip)
        return {"ok": True, "enforcement": "stored, not enforced"}

    # -- contact / reports -----------------------------------------------
    def list_contact(self, actor, status=None, category=None, after_id=None, limit=20):
        self.require_role(actor, write=False)
        sql = "SELECT id, app_account_hint, category, subject, body, status, linked_report_id, linked_work_id, created_at, resolved_at, internal_note FROM contact_messages WHERE 1=1"
        params = []
        if status:
            sql += " AND status=?"; params.append(status)
        if category:
            sql += " AND category=?"; params.append(category)
        if after_id:
            sql += " AND id < ?"; params.append(int(after_id))
        sql += " ORDER BY id DESC LIMIT ?"; params.append(max(1, min(int(limit or 20), 100)))
        rows = self.admin.execute(sql, params).fetchall()
        items = []
        for r in rows:
            d = _row(r)
            d["app_account_hint"] = mask_hint(d.get("app_account_hint"))
            items.append(d)
        return {"items": items, "count": len(items)}

    def create_contact(self, actor, body):
        """Panel-side intake route. The in-app form that posts here is
        still owed (app-side work); this never invents rows."""
        self.require_role(actor, write=True)
        self._validate_body(body, {"app_account_hint", "category", "subject", "body",
                                   "linked_report_id", "linked_work_id"})
        if body.get("category") not in CONTACT_CATEGORIES:
            raise bad("Unknown contact category.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO contact_messages (app_account_hint, category, subject, body, status, "
                "linked_report_id, linked_work_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (mask_hint(body.get("app_account_hint")), body["category"],
                 scrub_text(body.get("subject", ""), 200), scrub_text(body.get("body", ""), 2000),
                 "open", body.get("linked_report_id"), body.get("linked_work_id"), NOW()))
            self.admin.commit()
            return cur.lastrowid

    def update_contact(self, actor, msg_id, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"status", "internal_note"})
        row = self.admin.execute("SELECT * FROM contact_messages WHERE id=?", (msg_id,)).fetchone()
        if not row:
            raise not_found()
        if body.get("status") not in CONTACT_STATUSES:
            raise bad("Unknown contact status.")
        before = {"status": row["status"]}
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE contact_messages SET status=?, internal_note=?, resolved_at=?, resolved_by=? WHERE id=?",
                (body["status"], scrub_text(body.get("internal_note", ""), 1000) if body.get("internal_note") else row["internal_note"],
                 NOW() if body["status"] == "resolved" else row["resolved_at"],
                 actor["id"] if body["status"] == "resolved" else row["resolved_by"], msg_id))
            self.admin.commit()
        after = {"status": body["status"]}
        self.audit(actor["id"], "contact.status", "contact_message", msg_id, before, after, ip)
        return after

    def list_reports(self, actor, status=None, reason=None, after_id=None, limit=20):
        self.require_role(actor, write=False)
        sql = "SELECT id, source, work_id, reason, status, temp_hidden_at, verified_at, created_at FROM reports WHERE 1=1"
        params = []
        if status:
            sql += " AND status=?"; params.append(status)
        if reason:
            sql += " AND reason=?"; params.append(reason)
        if after_id:
            sql += " AND id < ?"; params.append(int(after_id))
        sql += " ORDER BY id DESC LIMIT ?"; params.append(max(1, min(int(limit or 20), 100)))
        rows = self.admin.execute(sql, params).fetchall()
        items = []
        for r in rows:
            d = _row(r); d["reporter_hint"] = None
            # 48h takedown SLA clock: from temp_hidden_at when set, else
            # from creation. sla_hours_left < 0 means the clock ran out.
            base = d.get("temp_hidden_at") or d.get("created_at") or 0
            d["sla_hours_left"] = round((base + 48 * 3600 - NOW()) / 3600.0, 1) if base else None
            d["sla_breached"] = bool(base and NOW() > base + 48 * 3600
                                     and d["status"] in ("open", "triage", "temp_hidden"))
            items.append(d)
        return {"items": items, "count": len(items)}

    def create_report(self, actor, body):
        """Panel-side intake route. The in-app one-tap report form is
        still owed (app-side work); this never invents rows."""
        self.require_role(actor, write=True)
        self._validate_body(body, {"source", "work_id", "reason", "detail", "reporter_hint"})
        if body.get("reason") not in REPORT_REASONS:
            raise bad("Unknown report reason.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO reports (source, work_id, reason, detail, reporter_hint, status, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (body.get("source", "app_report"), body.get("work_id"), body["reason"],
                 scrub_text(body.get("detail", ""), 2000), mask_hint(body.get("reporter_hint")),
                 "open", NOW()))
            self.admin.commit()
            return cur.lastrowid

    def report_action(self, actor, report_id, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"action", "note", "importer_key"})
        action = body.get("action")
        if action not in REPORT_ACTIONS:
            raise bad("Unknown report action.")
        rep = self.admin.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not rep:
            raise not_found()
        before = {"status": rep["status"]}
        now = NOW()
        with WRITE_LOCK:
            # Paired writes in ONE transaction: report_action + visibility.
            self.admin.execute(
                "INSERT INTO report_actions (report_id, action, actor_id, note, created_at) VALUES (?,?,?,?,?)",
                (report_id, action, actor["id"], scrub_text(body.get("note", ""), 1000), now))
            new_status = rep["status"]
            if action == "temp_hide" and rep["work_id"]:
                self.admin.execute(
                    "INSERT INTO content_visibility (scope, scope_id, is_hidden, reason, note, created_by, created_at) "
                    "VALUES ('work', ?, 1, 'takedown', ?, ?, ?)",
                    (str(rep["work_id"]), scrub_text(body.get("note", ""), 200), actor["id"], now))
                new_status = "temp_hidden"
                self.admin.execute("UPDATE reports SET temp_hidden_at=? WHERE id=?", (now, report_id))
            elif action == "restore" and rep["work_id"]:
                self.admin.execute(
                    "UPDATE content_visibility SET restored_at=?, restored_by=? "
                    "WHERE scope='work' AND scope_id=? AND restored_at IS NULL",
                    (now, actor["id"], str(rep["work_id"])))
                new_status = "restored"
            elif action == "permanent" and rep["work_id"]:
                self.admin.execute(
                    "INSERT INTO content_visibility (scope, scope_id, is_hidden, reason, note, created_by, created_at) "
                    "VALUES ('work', ?, 1, 'takedown', ?, ?, ?)",
                    (str(rep["work_id"]), scrub_text(body.get("note", ""), 200), actor["id"], now))
                if body.get("importer_key"):
                    if not valid_slug(body["importer_key"]):
                        raise bad("Importer key must be a slug.")
                    self.admin.execute(
                        "INSERT INTO importer_blocklist_notes (importer_key, reason, created_by, created_at, active) "
                        "VALUES (?,?,?,?,1)",
                        (body["importer_key"], scrub_text(body.get("note", ""), 500), actor["id"], now))
                new_status = "permanent"
            elif action == "reject":
                new_status = "rejected"
            elif action == "request_info":
                new_status = "triage"
            elif action == "blocklist_note":
                if not body.get("importer_key") or not valid_slug(body["importer_key"]):
                    raise bad("A blocklist note needs a slug importer key.")
                self.admin.execute(
                    "INSERT INTO importer_blocklist_notes (importer_key, reason, created_by, created_at, active) "
                    "VALUES (?,?,?,?,1)",
                    (body["importer_key"], scrub_text(body.get("note", ""), 500), actor["id"], now))
                new_status = rep["status"]
            self.admin.execute(
                "UPDATE reports SET status=?, decided_by=?, decision_note=? WHERE id=?",
                (new_status, actor["id"], scrub_text(body.get("note", ""), 1000), report_id))
            self.admin.commit()
        after = {"status": new_status}
        self.audit(actor["id"], "report.action", "report", report_id, before, after, ip)
        return after

    # -- broadcasts ---------------------------------------------------------
    def list_broadcasts(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute("SELECT * FROM broadcasts ORDER BY id DESC LIMIT 100").fetchall()
        return {"items": [_row(r) for r in rows]}

    def _validate_broadcast_target(self, target, detail):
        """A target names an audience; the detail names which one.

        `region` needs one of the panel's regions (pakistan, india, asia,
        international); `version` needs the exact app version name it is for
        ("1.0.4" — the app matches it exactly, no ranges); `all`, `free`
        and `vip` take no detail, because a detail nobody reads is a
        promise nobody keeps. Called with the MERGED values on update, so
        changing the target without its detail is refused, not half-saved.
        """
        detail = (detail or "").strip()
        if target == "region":
            if detail not in ("pakistan", "india", "asia", "international"):
                raise bad("A region broadcast needs one of pakistan, india, asia, international.")
        elif target == "version":
            if not detail or len(detail) > 32 or any(c.isspace() for c in detail):
                raise bad("A version broadcast needs one exact version name, no spaces.")
        elif target in ("all", "free", "vip"):
            if detail:
                raise bad("That target takes no detail.")
        else:
            raise bad("Unknown broadcast target.")

    def create_broadcast(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"title", "body", "severity", "target", "target_detail", "starts_at", "ends_at"})
        if body.get("severity", "info") not in ("info", "warning", "critical"):
            raise bad("Unknown broadcast severity.")
        if body.get("target", "all") not in ("all", "free", "vip", "region", "version"):
            raise bad("Unknown broadcast target.")
        self._validate_broadcast_target(body.get("target", "all"), body.get("target_detail", ""))
        starts_at = _parse_broadcast_time(body.get("starts_at"), "starts_at")
        ends_at = _parse_broadcast_time(body.get("ends_at"), "ends_at")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO broadcasts (title, body, severity, target, target_detail, starts_at, ends_at, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,'draft',?,?)",
                (scrub_text(body.get("title", ""), 200), scrub_text(body.get("body", ""), 2000),
                 body.get("severity", "info"), body.get("target", "all"),
                 (body.get("target_detail") or "").strip() or None,
                 starts_at, ends_at, NOW(), NOW()))
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM broadcasts WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "broadcast.create", "broadcast", row["id"], None, _row(row), ip)
        return _row(row)

    def update_broadcast(self, actor, broadcast_id, body, ip=""):
        """Edit a broadcast. Drafts may change freely; a published
        broadcast keeps its window rules (end after start). Served via
        remote-config; the app reads it and filters by target."""
        self.require_role(actor, write=True)
        self._validate_body(body, {"title", "body", "severity", "target", "target_detail", "starts_at", "ends_at"})
        row = self.admin.execute("SELECT * FROM broadcasts WHERE id=?", (broadcast_id,)).fetchone()
        if not row:
            raise not_found()
        if body.get("severity") and body["severity"] not in ("info", "warning", "critical"):
            raise bad("Unknown broadcast severity.")
        if body.get("target") and body["target"] not in ("all", "free", "vip", "region", "version"):
            raise bad("Unknown broadcast target.")
        # The target and its detail are one rule: validate what the row
        # would say after this edit, not just what the edit says.
        merged_target = body.get("target", row["target"])
        merged_detail = body.get("target_detail", row["target_detail"] or "")
        self._validate_broadcast_target(merged_target, merged_detail)
        before = _row(row)
        updates = {}
        for k in ("title", "body"):
            if k in body:
                updates[k] = scrub_text(body[k], 2000 if k == "body" else 200)
        for k in ("severity", "target"):
            if k in body:
                updates[k] = body[k]
        for k in ("starts_at", "ends_at"):
            if k in body:
                updates[k] = _parse_broadcast_time(body[k], k)
        if "target_detail" in body:
            updates["target_detail"] = (body["target_detail"] or "").strip() or None
        if updates:
            starts = updates.get("starts_at", row["starts_at"])
            ends = updates.get("ends_at", row["ends_at"])
            if starts and ends and ends <= starts:
                raise bad("Broadcast end must be after its start.")
            updates["updated_at"] = NOW()
            with WRITE_LOCK:
                self.admin.execute(
                    "UPDATE broadcasts SET %s WHERE id=?" % ", ".join("%s=?" % k for k in updates),
                    list(updates.values()) + [broadcast_id])
                self.admin.commit()
        after = _row(self.admin.execute("SELECT * FROM broadcasts WHERE id=?", (broadcast_id,)).fetchone())
        self.audit(actor["id"], "broadcast.update", "broadcast", broadcast_id, before, after, ip)
        return after

    def publish_broadcast(self, actor, broadcast_id, body, idempotency_key=None, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"confirm"})
        if not body or not body.get("confirm"):
            raise bad("Publish needs confirm set to true.")
        self._ensure_idempotency()
        cached = self._idempotency_check(idempotency_key, "broadcast.publish", broadcast_id)
        if cached is not None:
            return cached
        row = self.admin.execute("SELECT * FROM broadcasts WHERE id=?", (broadcast_id,)).fetchone()
        if not row:
            raise not_found()
        if not row["ends_at"]:
            raise bad("A broadcast without an end date cannot be published.")
        if row["ends_at"] and row["starts_at"] and row["ends_at"] <= row["starts_at"]:
            raise bad("Broadcast end must be after its start.")
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE broadcasts SET status='published', published_by=?, updated_at=? WHERE id=?",
                (actor["id"], NOW(), broadcast_id))
            self.admin.commit()
            result = {"broadcast_id": broadcast_id, "status": "published",
                      "refresh_note": "visible on next app refresh"}
            self._record_idempotency(idempotency_key, "broadcast.publish", broadcast_id, result)
            self.admin.commit()
        self.audit(actor["id"], "broadcast.publish", "broadcast", broadcast_id,
                   {"status": row["status"]}, {"status": "published"}, ip)
        return result

    def retract_broadcast(self, actor, broadcast_id, ip=""):
        self.require_role(actor, write=True)
        row = self.admin.execute("SELECT * FROM broadcasts WHERE id=?", (broadcast_id,)).fetchone()
        if not row:
            raise not_found()
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE broadcasts SET status='retracted', updated_at=? WHERE id=?", (NOW(), broadcast_id))
            self.admin.commit()
        self.audit(actor["id"], "broadcast.retract", "broadcast", broadcast_id,
                   {"status": row["status"]}, {"status": "retracted"}, ip)
        return {"broadcast_id": broadcast_id, "status": "retracted",
                "refresh_note": "visible on next app refresh"}

    def active_broadcasts(self):
        now = NOW()
        rows = self.admin.execute(
            "SELECT * FROM broadcasts WHERE status='published' AND (starts_at IS NULL OR starts_at<=?) "
            "AND (ends_at IS NULL OR ends_at>=?) ORDER BY id DESC", (now, now)).fetchall()
        # A paused broadcast is omitted even if published.
        paused = {r["target_id"] for r in self.admin.execute(
            "SELECT * FROM pauses WHERE target_type='broadcast' AND is_paused=1 AND resumed_at IS NULL").fetchall()}
        return [_row(r) for r in rows if str(r["id"]) not in paused]

    # -- tuning / pauses ------------------------------------------------------
    def get_tuning(self, actor):
        self.require_role(actor, write=False)
        row = self.admin.execute("SELECT * FROM tuning_settings WHERE id=1").fetchone()
        d = _row(row)
        out = {k: d.get(k) for k in TUNING_DEFAULTS}
        # Honest labelling: a read-only grep of the VM Fast_Fetch code
        # found NO consumer for 13 of the 20 controls. Only VIP prices,
        # the free quality cap, the theme knobs and hero_max ride in
        # remote-config to the app.
        out["consumers"] = self.tuning_consumers(actor)
        return out

    def put_tuning(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, set(TUNING_DEFAULTS) | {"reason"})
        if "free_quality_cap" in body and body["free_quality_cap"] not in ("480p", "720p"):
            raise bad("Free quality cap is 480p or 720p only.")
        if "theme_mode" in body and body["theme_mode"] not in ("dark", "light", "system"):
            raise bad("Theme mode is dark, light or system only.")
        if "theme_accent" in body:
            accent = str(body["theme_accent"] or "")
            if accent and not (len(accent) == 7 and accent[0] == "#"
                              and all(c in "0123456789abcdefABCDEF" for c in accent[1:])):
                raise bad("Theme accent is empty or a #RRGGBB hex colour.")
        if "tabs" in body:
            # A comma list of tab ids the app knows; anything else is a typo
            # the app would silently drop, so the panel refuses it out loud.
            # An empty list names no tab at all, which the app would read as
            # "use the defaults" — the operator who wants defaults leaves the
            # field alone instead of clearing it.
            named = [p.strip().lower() for p in str(body["tabs"] or "").split(",")]
            named = [p for p in named if p]
            if not named or any(p not in ("home", "search", "my_list", "settings", "live_tv") for p in named):
                raise bad("Tabs is a comma list of home, search, my_list, settings and live_tv.")
        if "disclaimer_text" in body and len(str(body["disclaimer_text"] or "")) > 4000:
            raise bad("Disclaimer text is at most 4000 characters.")
        if "disclaimer_email" in body:
            email = str(body["disclaimer_email"] or "")
            # Empty means "no email set" — the panel's own default is "",
            # so a blank field must be submittable, not an error. A
            # non-empty value must still be one valid address.
            if email and (len(email) > 254 or "@" not in email or " " in email
                    or email.count("@") != 1 or not email.split("@")[0]
                    or "." not in email.split("@", 1)[1]
                    or not email.rsplit(".", 1)[-1]):
                raise bad("Disclaimer email must be one valid email address.")
        for k, v in body.items():
            if k in ("reason", "free_quality_cap", "theme_mode", "theme_accent", "tabs", "disclaimer_text", "disclaimer_email"):
                continue
            lo, hi = TUNING_BOUNDS[k]
            if not (lo <= int(v) <= hi):
                raise bad("That value is outside its safe range for %s." % k)
        before = self.get_tuning(actor)
        with WRITE_LOCK:
            for k, v in body.items():
                if k == "reason":
                    continue
                self.admin.execute(
                    "UPDATE tuning_settings SET %s=?, updated_by=?, updated_at=? WHERE id=1" % k,
                    (v, actor["id"], NOW()))
                self.admin.execute(
                    "INSERT INTO tuning_history (control_name, before_value, after_value, actor_id, reason, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (k, str(before.get(k)), str(v), actor["id"],
                     scrub_text(body.get("reason", ""), 200), NOW()))
            self.admin.commit()
        after = self.get_tuning(actor)
        self.audit(actor["id"], "tuning.save", "tuning_settings", 1, before, after, ip)
        return after

    def is_paused(self, target_type, target_id):
        row = self.admin.execute(
            "SELECT * FROM pauses WHERE target_type=? AND target_id=? AND is_paused=1 AND resumed_at IS NULL "
            "ORDER BY id DESC LIMIT 1", (target_type, str(target_id))).fetchone()
        return bool(row)

    def list_pauses(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT * FROM pauses WHERE is_paused=1 AND resumed_at IS NULL ORDER BY id DESC").fetchall()
        return {"items": [_row(r) for r in rows]}

    def pause(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"target_type", "target_id", "reason"})
        if body["target_type"] not in PAUSE_TARGETS:
            raise bad("Unknown pause target.")
        if not body.get("reason"):
            raise bad("A pause needs a reason.")
        if self.is_paused(body["target_type"], body["target_id"]):
            raise conflict("That target is already paused.")
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO pauses (target_type, target_id, is_paused, reason, paused_by, paused_at) "
                "VALUES (?,?,1,?,?,?)",
                (body["target_type"], str(body["target_id"]), scrub_text(body["reason"], 500),
                 actor["id"], NOW()))
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM pauses WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "pause.create", "pause", row["id"], None, _row(row), ip)
        return _row(row)

    def resume_pause(self, actor, pause_id, ip=""):
        self.require_role(actor, write=True)
        row = self.admin.execute("SELECT * FROM pauses WHERE id=?", (pause_id,)).fetchone()
        if not row:
            raise not_found()
        if row["resumed_at"]:
            raise conflict("That pause is already resumed.")
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE pauses SET resumed_at=?, resumed_by=? WHERE id=?",
                (NOW(), actor["id"], pause_id))
            self.admin.commit()
        self.audit(actor["id"], "pause.resume", "pause", pause_id, _row(row), {"resumed": True}, ip)
        return {"ok": True}

    # -- domains ---------------------------------------------------------------
    def list_domains(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute("SELECT * FROM domain_registry ORDER BY site_key ASC").fetchall()
        return {"items": [_row(r) for r in rows]}

    def get_domain(self, actor, site_key):
        self.require_role(actor, write=False)
        row = self.admin.execute("SELECT * FROM domain_registry WHERE site_key=?", (site_key,)).fetchone()
        if not row:
            raise not_found()
        return _row(row)

    # -- live tv ---------------------------------------------------------------
    def list_live_tv(self, actor):
        """Live TV channels (id, name, enabled) for the operator."""
        self.require_role(actor, write=False)
        if self.live is None:
            raise LiveUnavailable("No live store is configured here.")
        return self.live.list_live_tv_channels()

    def set_live_tv_channel(self, actor, channel_id, body, ip=""):
        """Enable/disable one Live TV channel."""
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"enabled", "reason"})
        if self.live is None:
            raise LiveUnavailable("No live store is configured here.")
        before = self.live.list_live_tv_channels()
        prev = [c["enabled"] for c in before["channels"]
                if c["id"] == int(channel_id)]
        result = self.live.set_live_tv_channel(
            int(channel_id), _coerce_bool(body.get("enabled"), True),
            str(body.get("reason") or ""))
        self.audit(actor["id"], "live_tv.channel", "live_tv_channel", channel_id,
                   {"enabled": prev[0] if prev else None},
                   {"enabled": result["enabled"]}, ip)
        return result

    def add_live_tv_channel(self, actor, body, checker=None, ip=""):
        """Add a Live TV channel (operator). The stream URL is probed
        first; a dead stream refuses unless force is set. A duplicate
        name or stream URL comes back as a warning, not a refusal."""
        self.require_role(actor, write=True)
        body = body or {}
        self._validate_body(body, {"name", "category", "country", "language",
                                   "stream_url", "logo_url", "source",
                                   "enabled", "force"})
        if self.live is None:
            raise LiveUnavailable("No live store is configured here.")
        if not str(body.get("name") or "").strip():
            raise bad("Channel name is required.")
        if not str(body.get("stream_url") or "").strip():
            raise bad("Stream URL is required.")
        fields = {
            "name": body.get("name"), "category": body.get("category"),
            "country": body.get("country"), "language": body.get("language"),
            "stream_url": body.get("stream_url"), "logo_url": body.get("logo_url"),
            "source": body.get("source"),
            "enabled": _coerce_bool(body.get("enabled", True), True),
            "force": _coerce_bool(body.get("force", False), False),
        }
        result = self.live.add_live_tv_channel(fields, stream_checker=checker)
        self.audit(actor["id"], "live_tv.channel_add", "live_tv_channel",
                   result["channel"]["id"], None,
                   _live_tv_audit_view(result["channel"]), ip)
        return result

    def update_live_tv_channel(self, actor, channel_id, body, checker=None, ip=""):
        """Edit a Live TV channel (operator). Only the fields present
        in the body change. A changed stream URL is probed first."""
        self.require_role(actor, write=True)
        body = body or {}
        self._validate_body(body, {"name", "category", "country", "language",
                                   "stream_url", "logo_url", "source", "enabled",
                                   "disabled_reason", "force"})
        if self.live is None:
            raise LiveUnavailable("No live store is configured here.")
        before = self.live.list_live_tv_channels()
        prev = [c for c in before["channels"] if c["id"] == int(channel_id)]
        if not prev:
            raise not_found("That Live TV channel was not found.")
        fields = {}
        for key in ("name", "category", "country", "language", "stream_url",
                    "logo_url", "source", "disabled_reason"):
            if key in body:
                fields[key] = body[key]
        if "enabled" in body:
            fields["enabled"] = _coerce_bool(body.get("enabled"), True)
        if "force" in body:
            fields["force"] = _coerce_bool(body.get("force"), False)
        result = self.live.update_live_tv_channel(
            int(channel_id), fields, stream_checker=checker)
        self.audit(actor["id"], "live_tv.channel_edit", "live_tv_channel",
                   channel_id, _live_tv_audit_view(prev[0]),
                   _live_tv_audit_view(result["channel"]), ip)
        return result

    def delete_live_tv_channel(self, actor, channel_id, body, ip=""):
        """Delete a Live TV channel (operator). Requires confirm."""
        self.require_role(actor, write=True)
        body = body or {}
        self._validate_body(body, {"confirm"})
        if self.live is None:
            raise LiveUnavailable("No live store is configured here.")
        if not _coerce_bool(body.get("confirm"), False):
            raise bad("Tick the confirm box to delete this channel.")
        before = self.live.list_live_tv_channels()
        prev = [c for c in before["channels"] if c["id"] == int(channel_id)]
        if not prev:
            raise not_found("That Live TV channel was not found.")
        result = self.live.delete_live_tv_channel(int(channel_id))
        self.audit(actor["id"], "live_tv.channel_delete", "live_tv_channel",
                   channel_id, _live_tv_audit_view(prev[0]), None, ip)
        return result

    def add_candidate(self, actor, site_key, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"domain", "note"})
        if not valid_domain(body.get("domain", "")):
            raise bad("Domain only: no scheme, path, query, or token.")
        now = NOW()
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT OR IGNORE INTO domain_registry (site_key, kind, active_domain, status, created_at, updated_at) "
                "VALUES (?, 'source_site', NULL, 'healthy', ?, ?)", (site_key, now, now))
            cur = self.admin.execute(
                "INSERT INTO domain_candidates (site_key, domain, source, first_seen_at, last_seen_at, status) "
                "VALUES (?,?, 'owner_typed', ?, ?, 'candidate')",
                (site_key, body["domain"], now, now))
            self.admin.commit()
            row = self.admin.execute("SELECT * FROM domain_candidates WHERE id=?", (cur.lastrowid,)).fetchone()
        self.audit(actor["id"], "domain.candidate", "domain_candidate", row["id"], None, _row(row), ip)
        return _row(row)

    def validate_domain(self, actor, site_key, body, checker=None, ip=""):
        """Dry-run only: never switches anything. checker is injected
        (tests) or wired in run.py as admin_v2.domain_check.check_domain,
        a real DNS/TLS/HTTP fingerprint probe that never bypasses TLS
        and never downloads a file."""
        self.require_role(actor, write=True)
        self._validate_body(body, {"domain"})
        domain = body["domain"]
        if not valid_domain(domain):
            raise bad("Domain only: no scheme, path, query, or token.")
        if checker is None:
            result = {"dns_ok": False, "tcp_ok": False, "tls_ok": False,
                      "http_status": None, "fingerprint_ok": False,
                      "failure_reason": "no checker wired: validation cannot pass in this workspace build"}
        else:
            result = _call_checker(checker, domain, site_key)
        ok = bool(result.get("dns_ok") and result.get("tcp_ok") and result.get("tls_ok")
                  and result.get("fingerprint_ok"))
        now = NOW()
        with WRITE_LOCK:
            cand = self.admin.execute(
                "SELECT * FROM domain_candidates WHERE site_key=? AND domain=? ORDER BY id DESC LIMIT 1",
                (site_key, domain)).fetchone()
            if cand:
                self.admin.execute(
                    "UPDATE domain_candidates SET fingerprint_ok=?, last_seen_at=?, times_seen=times_seen+1, "
                    "status=?, validated_at=? WHERE id=?",
                    (1 if ok else 0, now, "validated" if ok else "candidate",
                     now if ok else None, cand["id"]))
            else:
                self.admin.execute(
                    "INSERT INTO domain_candidates (site_key, domain, source, fingerprint_ok, first_seen_at, "
                    "last_seen_at, status, validated_at) VALUES (?,?, 'owner_typed', ?, ?, ?, ?, ?)",
                    (site_key, domain, 1 if ok else 0, now, now,
                     "validated" if ok else "candidate", now if ok else None))
            self.admin.execute(
                "INSERT INTO domain_health_checks (site_key, domain_checked, checked_at, dns_ok, tcp_ok, "
                "tls_ok, http_status, fingerprint_ok, latency_ms, failure_reason, network, final_domain) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'vm',?)",
                (site_key, domain, now, 1 if result.get("dns_ok") else 0,
                 1 if result.get("tcp_ok") else 0, 1 if result.get("tls_ok") else 0,
                 result.get("http_status"), 1 if result.get("fingerprint_ok") else 0,
                 result.get("latency_ms"), result.get("failure_reason"),
                 result.get("final_domain")))
            self.admin.commit()
        return {"domain": domain, "validated": ok, "checks": result}

    def apply_domain(self, actor, site_key, body, checker=None, idempotency_key=None, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"domain", "confirm"})
        if not body.get("confirm"):
            raise bad("Apply needs confirm set to true.")
        domain = body["domain"]
        if not valid_domain(domain):
            raise bad("Domain only: no scheme, path, query, or token.")
        self._ensure_idempotency()
        cached = self._idempotency_check(idempotency_key, "domain.apply", site_key)
        if cached is not None:
            return cached
        cand = self.admin.execute(
            "SELECT * FROM domain_candidates WHERE site_key=? AND domain=? AND status='validated' "
            "ORDER BY id DESC LIMIT 1", (site_key, domain)).fetchone()
        if not cand or not cand["validated_at"] or NOW() - cand["validated_at"] > 86400:
            raise forbidden("That domain has not passed validation. Validate it first.")
        reg = self.admin.execute("SELECT * FROM domain_registry WHERE site_key=?", (site_key,)).fetchone()
        before = reg["active_domain"] if reg else None
        now = NOW()
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT OR IGNORE INTO domain_registry (site_key, kind, created_at, updated_at) "
                "VALUES (?, 'source_site', ?, ?)", (site_key, now, now))
            self.admin.execute(
                "UPDATE domain_registry SET active_domain=?, status='manual_override', "
                "override_by=?, override_at=?, updated_at=? WHERE site_key=?",
                (domain, actor["id"], now, now, site_key))
            self.admin.execute(
                "UPDATE domain_candidates SET status='applied' WHERE id=?", (cand["id"],))
            self.admin.execute(
                "INSERT INTO domain_history (site_key, from_domain, to_domain, changed_by, "
                "change_reason, validated_at, applied_at) VALUES (?,?,?,?, 'manual_override', ?, ?)",
                (site_key, before, domain, actor["id"], cand["validated_at"], now))
            self.admin.commit()
            self._domain_cache.pop(site_key, None)
            result = {"site_key": site_key, "from_domain": before, "to_domain": domain,
                      "live_note": "stored, not yet live until the resolver lookup gate lands",
                      "refresh_note": "visible on next app refresh"}
            if self.live is not None and self.live.registry_path:
                # WRITE path: domain_registry.json, with a backup taken
                # before the first live write (see live_stores).
                written = self.live.write_registry_domain(site_key, domain)
                result["registry_backup"] = written["backup"]
                result["live_note"] = ("written to domain_registry.json "
                                       "(backup %s); the resolver reads this file"
                                       % written["backup"])
            self._record_idempotency(idempotency_key, "domain.apply", site_key, result)
            self.admin.commit()
        self.audit(actor["id"], "domain.apply", "domain_registry", site_key,
                   {"active_domain": before}, {"active_domain": domain}, ip)
        return result

    def rollback_domain(self, actor, site_key, body, checker=None, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body or {}, {"confirm"})
        if not body or not body.get("confirm"):
            raise bad("Rollback needs confirm set to true.")
        hist = self.admin.execute(
            "SELECT * FROM domain_history WHERE site_key=? ORDER BY id DESC LIMIT 2",
            (site_key,)).fetchall()
        if len(hist) < 2:
            raise conflict("There is no previous domain to roll back to.")
        previous = hist[1]["to_domain"]
        if not previous:
            raise conflict("The previous domain is empty, so rollback is not possible.")
        # Re-validate the previous domain: it may itself have died since.
        if checker is None:
            raise forbidden("Rollback is blocked: the previous domain could not be re-validated.")
        check = checker(previous)
        if not (check.get("dns_ok") and check.get("tcp_ok") and check.get("tls_ok")
                and check.get("fingerprint_ok")):
            raise forbidden("Rollback is blocked: the previous domain no longer passes validation.")
        reg = self.admin.execute("SELECT * FROM domain_registry WHERE site_key=?", (site_key,)).fetchone()
        before = reg["active_domain"] if reg else None
        now = NOW()
        with WRITE_LOCK:
            self.admin.execute(
                "UPDATE domain_registry SET active_domain=?, status='manual_override', "
                "override_by=?, override_at=?, updated_at=? WHERE site_key=?",
                (previous, actor["id"], now, now, site_key))
            self.admin.execute(
                "INSERT INTO domain_history (site_key, from_domain, to_domain, changed_by, "
                "change_reason, validated_at, applied_at) VALUES (?,?,?,?, 'rollback', ?, ?)",
                (site_key, before, previous, actor["id"], now, now))
            self.admin.commit()
            self._domain_cache.pop(site_key, None)
        if self.live is not None and self.live.registry_path:
            written = self.live.write_registry_domain(site_key, previous)
            backup = written["backup"]
        else:
            backup = None
        self.audit(actor["id"], "domain.rollback", "domain_registry", site_key,
                   {"active_domain": before}, {"active_domain": previous}, ip)
        return {"site_key": site_key, "from_domain": before, "to_domain": previous,
                "registry_backup": backup}

    def set_auto_failover(self, actor, site_key, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"enabled"})
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT OR IGNORE INTO domain_registry (site_key, kind, created_at, updated_at) "
                "VALUES (?, 'source_site', ?, ?)", (site_key, NOW(), NOW()))
            self.admin.execute(
                "UPDATE domain_registry SET auto_failover=? WHERE site_key=?",
                (1 if body["enabled"] else 0, site_key))
            self.admin.commit()
        self.audit(actor["id"], "domain.auto_failover", "domain_registry", site_key,
                   None, {"auto_failover": bool(body["enabled"])}, ip)
        return {"site_key": site_key, "auto_failover": bool(body["enabled"])}

    def record_health(self, actor, site_key, result, ip=""):
        """Health job (read-only job, never on the request path).

        3 consecutive failures -> failed; 2 consecutive successes ->
        healthy; otherwise degraded if any failure. Auto-failover only
        when explicitly enabled, a validated candidate exists, and the
        pattern is met — otherwise it only alerts (status change)."""
        self.require_role(actor, write=False)
        if self.is_paused("domain_checks", site_key):
            return {"site_key": site_key, "status": "checks paused", "switched": False}
        now = NOW()
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT INTO domain_health_checks (site_key, domain_checked, checked_at, dns_ok, tcp_ok, "
                "tls_ok, http_status, fingerprint_ok, latency_ms, failure_reason, network, final_domain) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'vm',?)",
                (site_key, result.get("domain"), now,
                 1 if result.get("dns_ok") else 0, 1 if result.get("tcp_ok") else 0,
                 1 if result.get("tls_ok") else 0, result.get("http_status"),
                 1 if result.get("fingerprint_ok") else 0, result.get("latency_ms"),
                 result.get("failure_reason"), result.get("final_domain")))
            recent = self.admin.execute(
                "SELECT * FROM domain_health_checks WHERE site_key=? ORDER BY id DESC LIMIT 3",
                (site_key,)).fetchall()
            def ok(r):
                return bool(r["dns_ok"] and r["tcp_ok"] and r["tls_ok"] and r["fingerprint_ok"])
            if len(recent) >= 3 and all(not ok(r) for r in recent):
                status = "failed"
            elif len(recent) >= 2 and all(ok(r) for r in recent[:2]):
                status = "healthy"
            elif any(not ok(r) for r in recent):
                status = "degraded"
            else:
                status = "healthy"
            self.admin.execute(
                "INSERT OR IGNORE INTO domain_registry (site_key, kind, created_at, updated_at) "
                "VALUES (?, 'source_site', ?, ?)", (site_key, now, now))
            self.admin.execute(
                "UPDATE domain_registry SET status=?, last_checked_at=?, "
                "last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END, "
                "last_failure_reason=?, updated_at=? WHERE site_key=?",
                (status, now, 1 if ok(recent[0]) else 0, now,
                 result.get("failure_reason"), now, site_key))
            # Where the check actually landed: a redirect means the
            # registry's active domain is stale, and the Domains page
            # shows the redirect target instead of blessing it healthy.
            final = result.get("final_domain")
            if final and final != result.get("domain"):
                self.admin.execute(
                    "UPDATE domain_registry SET last_redirect_to=? "
                    "WHERE site_key=?", (final, site_key))
            self.admin.commit()
        switched = False
        reg = self.admin.execute("SELECT * FROM domain_registry WHERE site_key=?", (site_key,)).fetchone()
        if status == "failed" and reg and reg["auto_failover"]:
            cand = self.admin.execute(
                "SELECT * FROM domain_candidates WHERE site_key=? AND status='validated' "
                "ORDER BY id DESC LIMIT 1", (site_key,)).fetchone()
            if cand:
                # Switch only via the validated-apply path, with audit.
                try:
                    self.apply_domain({"id": actor["id"], "role": "owner", "username": actor.get("username", "")},
                                      site_key, {"domain": cand["domain"], "confirm": True}, ip=ip)
                    switched = True
                except Exception:
                    switched = False
        return {"site_key": site_key, "status": status, "switched": switched}

    def domain_history(self, actor, site_key):
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT * FROM domain_history WHERE site_key=? ORDER BY id DESC LIMIT 50",
            (site_key,)).fetchall()
        return {"items": [_row(r) for r in rows]}

    def domain_health(self, actor, site_key):
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT * FROM domain_health_checks WHERE site_key=? ORDER BY id DESC LIMIT 50",
            (site_key,)).fetchall()
        return {"items": [_row(r) for r in rows]}

    def resolve_domain(self, site_key):
        """Registry lookup with a 10-minute cache (OD-10). Manual
        override wins; disabled means skip with a plain reason."""
        now = NOW()
        cached = self._domain_cache.get(site_key)
        if cached and cached[1] > now:
            return cached[0]
        reg = self.admin.execute("SELECT * FROM domain_registry WHERE site_key=?", (site_key,)).fetchone()
        if not reg:
            value = (None, "no registry entry: existing behaviour unchanged")
        elif reg["status"] == "disabled":
            value = (None, "disabled in registry")
        else:
            value = (reg["active_domain"], "registry")
        self._domain_cache[site_key] = (value, now + 600)
        return value

    # -- fleet / analytics / dashboard / misc --------------------------------
    def list_fleet(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute("SELECT * FROM fleet_crawlers ORDER BY site_key ASC").fetchall()
        items = [_row(r) for r in rows]
        live = self.live
        if live is not None and (live.has_catalog or live.status_dir or live.registry_path):
            real = {f["site_key"]: f for f in live.list_fleet()}
            for item in items:
                r = real.get(item["site_key"])
                if r:
                    item["status"] = r["status"]
                    item["progress"] = r["progress"]
                    item["failure_reason"] = r["failure_reason"]
                    item["last_good_domain"] = r["last_good_domain"]
                    item["last_sync_at"] = r["last_sync_at"]
                    item["ever_ran"] = r["ever_ran"]
                    item["source"] = "real"
                else:
                    item["source"] = "panel"
        return {"items": items}

    def run_fleet(self, actor, body, ip=""):
        self.require_role(actor, write=True)
        self._validate_body(body, {"crawler", "mode", "limit"})
        site = body.get("crawler")
        if site not in FLEET_SITES:
            raise bad("Unknown crawler.")
        if self.is_paused("import_global", "global"):
            raise forbidden("Imports are paused by the owner. Resume imports first.")
        if self.is_paused("source", site):
            raise forbidden("That source is paused by the owner. Resume it first.")
        limit = int(body.get("limit", 25))
        if limit < 10 or limit > 1000:
            raise bad("Fleet run limit must be 10 to 1000.")
        running = self.admin.execute(
            "SELECT COUNT(*) AS n FROM fleet_runs WHERE site_key=? AND status IN ('queued','running')",
            (site,)).fetchone()["n"]
        if running:
            raise conflict("That crawler already has a run queued or running.")
        live = self.live
        if live is not None and live.has_catalog:
            # v1 run-scraper: audit 'running' + spawn the SAME bounded
            # command + watcher. Tests inject a fake runner and use a
            # COPY; live use needs a catalog backup before first use.
            res = live.run_fleet(site, body.get("mode", "sync"), limit,
                                 actor_id=actor["id"])
            with WRITE_LOCK:
                cur = self.admin.execute(
                    "INSERT INTO fleet_runs (site_key, mode, limit_n, status, created_by, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (site, body.get("mode", "sync"), limit, "running", actor["id"], NOW()))
                self.admin.execute(
                    "INSERT INTO fleet_audit (site_key, action, detail, created_at) VALUES (?,?,?,?)",
                    (site, "run_started", "audit %d pid %s" % (res["audit_id"], res["pid"]), NOW()))
                self.admin.commit()
            self.audit(actor["id"], "fleet.run", "fleet_run", cur.lastrowid, None,
                       {"site_key": site, "limit": limit, "audit_id": res["audit_id"]}, ip)
            return {"run_id": cur.lastrowid, "site_key": site, "limit": limit,
                    "audit_id": res["audit_id"], "pid": res["pid"],
                    "command": res["command"], "status": "running"}
        with WRITE_LOCK:
            cur = self.admin.execute(
                "INSERT INTO fleet_runs (site_key, mode, limit_n, status, created_by, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (site, body.get("mode", "sync"), limit, "queued", actor["id"], NOW()))
            self.admin.execute(
                "INSERT INTO fleet_audit (site_key, action, detail, created_at) VALUES (?,?,?,?)",
                (site, "run_queued", "limit %d" % limit, NOW()))
            job = smart.enqueue_job(self.admin, "fleet_run",
                                    {"site_key": site, "limit": limit},
                                    "fleet-%s-%d" % (site, cur.lastrowid), actor["id"])
            self.admin.commit()
        self.audit(actor["id"], "fleet.run", "fleet_run", cur.lastrowid, None,
                   {"site_key": site, "limit": limit}, ip)
        return {"run_id": cur.lastrowid, "job": job, "site_key": site, "limit": limit}

    def refold_evidence(self, actor, link_id, ip=""):
        """v1 evidence re-fold: re-derive the cat_links row from its
        cat_link_evidence journal. Real when a live catalog is wired
        (WRITE path — tests run it on a COPY; live use needs a catalog
        backup first); otherwise an audited no-body record only."""
        self.require_role(actor, write=True)
        live = self._live_catalog()
        if live is not None:
            res = live.refold_evidence(link_id)
            self.audit(actor["id"], "link.evidence_refold", "link", link_id, None,
                       {"refolded": res.get("refolded"), "state": res.get("state")}, ip)
            return res
        self.audit(actor["id"], "link.evidence_refold", "link", link_id, None,
                   {"requested": True}, ip)
        return {"link_id": link_id, "refolded": False,
                "note": "recorded only in this build; no live catalog is wired"}

    def compute_analytics_day(self, actor, day):
        self.require_role(actor, write=True)
        live_cat = self._live_catalog()
        live_led = self._live_ledger()
        if live_cat is not None:
            counts = live_cat.catalog_counts()
            # Works are rows in cat_works (116,922 live) — NOT rows in
            # posts (150,799 live). The old code stored posts here, so
            # every Analytics row and the CSV overstated the catalog
            # by ~34,000 (audit §Catalog). Fall back to posts only when
            # the catalog has no cat_works table at all.
            works = counts["works"] if counts.get("works") is not None else counts["posts"]
            proj_age = counts["projection_age_h"]
            proj_age = int(proj_age) if proj_age is not None else None
        else:
            counts = {}
            works = self.catalog.execute("SELECT COUNT(*) AS n FROM works").fetchone()["n"]
            proj_age = None
        if live_led is not None:
            led = live_led.ledger_counts()
            pending, approved = led["pending_payments"], led["approved_payments"]
            rejected = led.get("rejected_payments", 0)
        else:
            pending = self.ledger.execute(
                "SELECT COUNT(*) AS n FROM payment_claims WHERE status='pending'").fetchone()["n"]
            approved = self.ledger.execute(
                "SELECT COUNT(*) AS n FROM payment_claims WHERE status='approved'").fetchone()["n"]
            rejected = self.ledger.execute(
                "SELECT COUNT(*) AS n FROM payment_claims WHERE status='rejected'").fetchone()["n"]
        open_rep = self.admin.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE status IN ('open','triage','temp_hidden')").fetchone()["n"]
        failed = self.admin.execute(
            "SELECT COUNT(*) AS n FROM domain_registry WHERE status='failed'").fetchone()["n"]
        active_bc = len(self.active_broadcasts())
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT OR REPLACE INTO analytics_daily (day, catalog_works, projection_age_h, "
                "pending_payments, approved_payments, open_reports, failed_domains, active_broadcasts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (day, works, proj_age if proj_age is not None else 0, pending, approved, open_rep, failed, active_bc))
            self.admin.commit()
        out = {"day": day, "catalog_works": works, "pending_payments": pending,
               "approved_payments": approved, "rejected_payments": rejected,
               "open_reports": open_rep, "failed_domains": failed,
               "active_broadcasts": active_bc,
               "projection_age_h": proj_age,
               "catalog_posts": counts.get("posts"),
               "catalog_releases": counts.get("releases"),
               "catalog_sources": counts.get("sources"),
               "active_sources": counts.get("active_sources"),
               "resumable_sources": counts.get("resumable_sources"),
               "links_by_state": counts.get("links_by_state") or {}}
        return out

    def export_analytics_csv(self, actor):
        """CSV export of the daily aggregates (no per-user rows)."""
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT * FROM analytics_daily ORDER BY day DESC LIMIT 90").fetchall()
        lines = ["day,catalog_works,projection_age_h,pending_payments,approved_payments,"
                 "open_reports,failed_domains,active_broadcasts"]
        for r in rows:
            lines.append("%s,%s,%s,%s,%s,%s,%s,%s" % (
                r["day"], r["catalog_works"], r["projection_age_h"],
                r["pending_payments"], r["approved_payments"], r["open_reports"],
                r["failed_domains"], r["active_broadcasts"]))
        return "\n".join(lines)

    def get_analytics(self, actor):
        self.require_role(actor, write=False)
        rows = self.admin.execute("SELECT * FROM analytics_daily ORDER BY day DESC LIMIT 90").fetchall()
        return {"items": [_row(r) for r in rows]}

    def catalog_overview(self, actor):
        """Live catalog truth in one read (works/posts/adult/projection).

        The Content page shows the adult counts; the dashboard shows
        works vs posts. Returns {"available": False} when no catalog
        is wired, never an error.
        """
        self.require_role(actor, write=False)
        live = self._live_catalog()
        if live is None:
            return {"available": False}
        return {"available": True, **live.catalog_counts()}

    def data_health(self, actor):
        """Everything the server already knows about data truth, in
        one answer — the Data health page (audit §Missing views):

        - negative cache: failed download_sources rows by failure class
        - review queue: total count + the first 50 rows
        - projection truth: rev, age, link coverage, unchecked links,
          identity suspects, release dups, id-map rows
        - adult volume: flagged posts and works
        - coins: ledger rows, granted, spent, by reason
        - fleet: per-crawler status with last-sync ages
        Every read is guarded: a missing table or a dead store yields
        an honest zero/empty, never a 500.
        """
        self.require_role(actor, write=False)
        live_cat = self._live_catalog()
        live_led = self._live_ledger()
        out = {"available": False, "link_health": {}, "review_queue_count": 0,
               "review_queue": [], "projection": {}, "drift": {}, "adult": {},
               "coins": {}, "fleet": []}
        if live_cat is not None:
            out["available"] = True
            try:
                counts = live_cat.catalog_counts()
            except Exception:
                counts = {}
            out["projection"] = {
                "rev": counts.get("projection_rev"),
                "age_h": counts.get("projection_age_h"),
                "link_coverage": counts.get("link_coverage"),
                "unchecked_links": (counts.get("links_by_state") or {}).get("unchecked"),
                "identity_suspect": counts.get("identity_suspect"),
                "release_dups": counts.get("release_dups"),
                "id_map_rows": counts.get("id_map_rows"),
            }
            try:
                out["drift"] = live_cat.projection_drift()
            except Exception:
                out["drift"] = {}
            out["adult"] = {"posts": counts.get("adult_posts"),
                            "works": counts.get("adult_works")}
            try:
                out["link_health"] = live_cat.link_health()
            except Exception:
                out["link_health"] = {}
            try:
                out["review_queue_count"] = live_cat.review_queue_count()
                out["review_queue"] = live_cat.review_queue(limit=50)["items"]
            except Exception:
                pass
            try:
                out["fleet"] = self.list_fleet(actor)["items"]
            except Exception:
                pass
        if live_led is not None:
            out["available"] = True
            try:
                out["coins"] = live_led.coin_summary()
            except Exception:
                pass
        return out

    def dashboard(self, actor):
        self.require_role(actor, write=False)
        cached = self.admin.execute(
            "SELECT * FROM dashboard_cache WHERE cache_key='dashboard'").fetchone()
        now = NOW()
        if cached:
            data = json.loads(cached["value_json"])
            is_live_row = data.get("cache_origin") == DASHBOARD_CACHE_ORIGIN_LIVE
            # Strip envelope keys the writer stored, so a stored row can
            # never override the quality we report for this read.
            data.pop("cache_origin", None)
            data.pop("quality", None)
            data.pop("stale_age_s", None)
            if cached["expires_at"] > now:
                return {"quality": "full", **data}
            # Serve stale ONLY for rows the live path wrote (marked at
            # write time with cache_origin == "live"). Old fixture-era
            # rows without the marker still recompute, exactly as
            # before — they can carry fixture counts, a hardcoded cert
            # date, and lowercase needs text.
            if cached["stale_until"] > now and is_live_row:
                return {"quality": "stale",
                        "stale_age_s": now - cached["created_at"], **data}
        data = self._compute_dashboard_data(actor)
        self._write_dashboard_cache(data, now)
        return {"quality": "full", **data}

    def _compute_dashboard_data(self, actor):
        # The synchronous recompute behind dashboard() and the
        # background refresh. Reads the live stores; never serves a
        # cached row itself.
        live_led = self._live_ledger()
        if live_led is not None:
            led = live_led.ledger_counts()
            pending = led["pending_payments"]
        else:
            pending = self.ledger.execute(
                "SELECT COUNT(*) AS n FROM payment_claims WHERE status='pending'").fetchone()["n"]
        open_rep = self.admin.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE status IN ('open','triage','temp_hidden')").fetchone()["n"]
        stale_rep = self.admin.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE status IN ('open','triage','temp_hidden') "
            "AND created_at < ?", (NOW() - 24 * 3600,)).fetchone()["n"]
        failed = self.admin.execute(
            "SELECT COUNT(*) AS n FROM domain_registry WHERE status='failed'").fetchone()["n"]
        cfg = self._config_row()
        live_cat = self._live_catalog()
        counts = live_cat.catalog_counts() if live_cat is not None else {}
        cert = None
        if self.live is not None:
            cert = self.live.cert_expiry()
        sys_health = self.live.system_health(self.base_dir, service_port=8080) if self.live is not None else {}
        review_q = 0
        link_health = {}
        if live_cat is not None:
            try:
                review_q = live_cat.review_queue_count()
            except Exception:
                review_q = 0
            try:
                link_health = live_cat.link_health()
            except Exception:
                link_health = {}
        data = {
            "pending_payments": pending, "open_reports": open_rep, "failed_domains": failed,
            "active_broadcasts": len(self.active_broadcasts()),
            "maintenance_mode": bool(cfg["maintenance_mode"]),
            "config_version": cfg["config_version"],
            "cert_expiry": cert["date"] if cert else "Unknown",
            "cert_expiry_iso": cert["iso"] if cert else None,
            "cert_warning": "Certificate renews outside the panel. Warn before expiry." if not cert else None,
            "catalog_posts": counts.get("posts"),
            "catalog_works": counts.get("works"),
            "catalog_releases": counts.get("releases"),
            "catalog_sources": counts.get("sources"),
            "active_sources": counts.get("active_sources"),
            "resumable_sources": counts.get("resumable_sources"),
            "projection_age_h": counts.get("projection_age_h"),
            "review_queue_count": review_q,
            "link_health": link_health,
            "disk_free_gb": sys_health.get("disk_free_gb"),
            "disk_total_gb": sys_health.get("disk_total_gb"),
            "load_1m": sys_health.get("load_1m"),
            "service_state": sys_health.get("service_state", "unknown"),
            "paused": self.list_pauses(actor)["items"],
            "needs_you_now": [],
            "refresh_note": "visible on next app refresh",
        }
        if pending:
            data["needs_you_now"].append("Pending payments: %d" % pending)
        if open_rep:
            data["needs_you_now"].append("Open reports: %d" % open_rep)
        if stale_rep:
            data["needs_you_now"].append(
                "Reports open over 24 hours: %d — the 48h takedown clock is running" % stale_rep)
        if failed:
            data["needs_you_now"].append("Failed domains: %d" % failed)
        if review_q:
            data["needs_you_now"].append("Review queue: %d items waiting" % review_q)
        proj_age = counts.get("projection_age_h")
        if proj_age is not None and proj_age > 168:
            data["needs_you_now"].append(
                "Projection is %d h old — the app serves stale data" % int(proj_age))
        if link_health.get("failed_total"):
            data["needs_you_now"].append(
                "Failed links: %d need a host fix" % link_health["failed_total"])
        data["needs_you_now"] = data["needs_you_now"][:5]
        if not data["needs_you_now"]:
            data["needs_you_now"] = ["Nothing needs you now"]
        return data

    def _write_dashboard_cache(self, data, now):
        stored = dict(data)
        stored["cache_origin"] = DASHBOARD_CACHE_ORIGIN_LIVE
        with WRITE_LOCK:
            self.admin.execute(
                "INSERT OR REPLACE INTO dashboard_cache VALUES ('dashboard', ?, ?, ?, ?)",
                (json.dumps(stored), now + DASHBOARD_CACHE_TTL_S,
                 now + DASHBOARD_CACHE_STALE_S, now))
            self.admin.commit()

    def refresh_dashboard_cache(self):
        """Background refresh for the minute tick (D2.4): if the cached
        row is expired, recompute it off the page-load path. Returns
        True when a recompute ran. Single-flight, so overlapping ticks
        never pile up; a slow catalog can never kill the tick — the
        caller wraps this in try/except like the other tick jobs."""
        if not _DASHBOARD_REFRESH_LOCK.acquire(blocking=False):
            return False
        try:
            cached = self.admin.execute(
                "SELECT * FROM dashboard_cache WHERE cache_key='dashboard'").fetchone()
            now = NOW()
            if cached and cached["expires_at"] > now:
                return False
            actor = {"id": 0, "role": "owner", "username": "background"}
            data = self._compute_dashboard_data(actor)
            self._write_dashboard_cache(data, now)
            return True
        finally:
            _DASHBOARD_REFRESH_LOCK.release()

    def list_audit(self, actor, action=None, actor_id=None, after_id=None, limit=20):
        self.require_role(actor, write=False)
        sql = "SELECT id, actor_id, action, target_type, target_id, ip_masked, created_at FROM admin_audit_log WHERE 1=1"
        params = []
        if action:
            sql += " AND action=?"; params.append(action)
        if actor_id:
            sql += " AND actor_id=?"; params.append(int(actor_id))
        if after_id:
            sql += " AND id < ?"; params.append(int(after_id))
        sql += " ORDER BY id DESC LIMIT ?"; params.append(max(1, min(int(limit or 20), 100)))
        rows = self.admin.execute(sql, params).fetchall()
        return {"items": [_row(r) for r in rows]}

    def export_audit_csv(self, actor):
        """Redacted CSV only: no tokens, no transaction ids, no URLs."""
        self.require_role(actor, write=False)
        rows = self.admin.execute(
            "SELECT id, actor_id, action, target_type, target_id, created_at FROM admin_audit_log "
            "ORDER BY id DESC LIMIT 1000").fetchall()
        lines = ["id,actor_id,action,target_type,target_id,created_at"]
        for r in rows:
            lines.append("%s,%s,%s,%s,%s,%s" % (r["id"], r["actor_id"], r["action"],
                                               r["target_type"], r["target_id"], r["created_at"]))
        return "\n".join(lines)

    def global_search(self, actor, q):
        self.require_role(actor, write=False)
        q = (q or "").strip()
        if not q:
            return {"works": [], "users": [], "payments": [], "reports": [], "domains": [], "broadcasts": []}
        works = self.search_works(actor, q=q, limit=10)["items"]
        users = [u for u in self.search_users(actor, q=q)["items"]]
        if q.isdigit() and self._live_ledger() is not None:
            try:
                pays = [self._live_ledger().get_payment(int(q))]
            except Exception:
                pays = []
        else:
            pays = self.ledger.execute(
                "SELECT id, account_hint, method, amount_pkr, status FROM payment_claims WHERE id=?",
                (q,) if q.isdigit() else (-1,)).fetchall()
        reps = self.admin.execute(
            "SELECT id, reason, status FROM reports WHERE id=?",
            (q,) if q.isdigit() else (-1,)).fetchall()
        doms = self.admin.execute(
            "SELECT site_key, active_domain, status FROM domain_registry WHERE site_key LIKE ?",
            ("%" + q + "%",)).fetchall()
        bcs = self.admin.execute(
            "SELECT id, title, status FROM broadcasts WHERE title LIKE ?", ("%" + q + "%",)).fetchall()
        return {"works": works, "users": users,
                "payments": [r if isinstance(r, dict) else _row(r) for r in pays],
                "reports": [_row(r) for r in reps],
                "domains": [_row(r) for r in doms], "broadcasts": [_row(r) for r in bcs]}

    def panel_settings(self, actor):
        """Read-only display: session lifetimes are fixed by OD-09 and
        are not changeable from the panel."""
        self.require_role(actor, write=False)
        cert = self.live.cert_expiry() if self.live is not None else None
        sys_health = self.live.system_health(self.base_dir, service_port=8080) if self.live is not None else {}
        return {"session_absolute_hours": 12, "session_idle_hours": 8,
                "session_changeable_from_panel": False,
                "cert_expiry": cert["date"] if cert else "Unknown",
                "cert_expiry_iso": cert["iso"] if cert else None,
                "disk_free_gb": sys_health.get("disk_free_gb"),
                "disk_total_gb": sys_health.get("disk_total_gb"),
                "load_1m": sys_health.get("load_1m"),
                "service_state": sys_health.get("service_state", "unknown"),
                "https_note": "Live HTTPS wiring (nginx, HSTS, redirect) is a gated live step, not done here."}

    def prune(self, actor):
        """Retention pruning (OD-06) + cache/job caps. Bounded, audited."""
        self.require_role(actor, write=True)
        now = NOW()
        with WRITE_LOCK:
            self.admin.execute(
                "DELETE FROM admin_login_attempts WHERE attempted_at < ?", (now - 90 * 86400,))
            self.admin.execute(
                "DELETE FROM admin_audit_log WHERE created_at < ?", (now - 2 * 365 * 86400,))
            self.admin.execute(
                "DELETE FROM contact_messages WHERE status='resolved' AND resolved_at < ?",
                (now - 365 * 86400,))
            self.admin.execute(
                "DELETE FROM reports WHERE status IN ('rejected','restored','permanent') AND created_at < ?",
                (now - 365 * 86400,))
            self.admin.execute(
                "DELETE FROM analytics_daily WHERE day < date('now','-2 years')")
            self.admin.execute(
                "DELETE FROM resolved_cache WHERE stale_until < ?", (now,))
            self.admin.execute(
                "DELETE FROM jobs WHERE status='done' AND updated_at < ?", (now - 30 * 86400,))
            self.admin.commit()
        self.audit(actor["id"], "panel.prune", "panel", "retention", None, {"pruned": True}, "")
        return {"ok": True}
