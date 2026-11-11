"""HTTP server for Admin Panel v2. Stdlib only (http.server).

Auth: session cookie (HttpOnly, Secure when HTTPS, SameSite=Lax,
Path=/admin) + CSRF header/field on every write. GET never changes
state. Security headers on every /admin response. HSTS is sent only
over HTTPS (the gated live step); this workspace server over plain
HTTP must not claim HSTS, and strict-host mode (Host must be the
panel domain + HTTPS) is off by default here and on at the gate.
"""
import json
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import fixture_app, templates
from .errors import ApiError
from .security import mask_ip
from .services import TUNING_BOUNDS, Service
from .store import COIN_REDEEM_FIELDS, FLEET_SITES

STRICT_HOST = "raddstream.duckdns.org"


class RateLimiter:
    def __init__(self):
        self.events = {}

    def allow(self, key, limit, window_s):
        now = time.time()
        lst = [t for t in self.events.get(key, []) if now - t < window_s]
        if len(lst) >= limit:
            self.events[key] = lst
            return False
        lst.append(now)
        self.events[key] = lst
        return True


def check_strict_host(host, proto, strict):
    """Gate rule: /admin only on the panel domain over HTTPS."""
    if not strict:
        return True
    return host == STRICT_HOST and proto == "https"


def parse_cookies(header):
    out = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, _, v = part.strip().partition("=")
            out[k] = v
    return out


class AdminApp:
    """Testable core: routes + auth, without the socket layer."""

    def __init__(self, service, strict_host=False, domain_checker=None, stream_checker=None):
        self.service = service
        self.strict_host = strict_host
        self.domain_checker = domain_checker
        self.stream_checker = stream_checker
        self.limiter = RateLimiter()

    # -- request handling -------------------------------------------------
    def handle(self, method, path, query, headers, body_bytes):
        """Returns (status, content_type, body_bytes, set_cookie_or_None, location_or_None)."""
        host = headers.get("Host", "")
        proto = headers.get("X-Forwarded-Proto", "http")
        if path.startswith("/admin") and not check_strict_host(host, proto, self.strict_host):
            return self._json(403, {"success": False, "error": {"code": "forbidden",
                "message": "Admin is only served on its panel domain over HTTPS."}}, None, None)
        try:
            return self._dispatch(method, path, query, headers, body_bytes)
        except ApiError as exc:
            return self._json(exc.status, {"success": False, "error": {"code": exc.code,
                "message": exc.message}}, None, None)
        except Exception as exc:  # never leak a stack trace or SQL
            return self._json(500, {"success": False, "error": {"code": "internal",
                "message": "Something went wrong. Try again."}}, None, None)

    def _json(self, status, payload, cookie, location):
        return (status, "application/json", json.dumps(payload).encode(), cookie, location)

    def _html(self, status, page):
        return (status, "text/html", page.encode(), None, None)

    def _auth(self, headers):
        cookies = parse_cookies(headers.get("Cookie", ""))
        user, sess = self.service.validate_session(cookies.get("admin_session", ""))
        return user, sess

    def _require_auth(self, headers):
        user, sess = self._auth(headers)
        if not user:
            raise ApiError("unauthenticated", "Log in to use the admin panel.", 401)
        return user, sess

    def _csrf(self, headers, body, sess):
        token = headers.get("X-CSRF-Token") or body.get("csrf_token")
        self.service.check_csrf(sess, token)

    def _rate(self, key, limit, window):
        if not self.limiter.allow(key, limit, window):
            raise ApiError("rate_limited", "Too many tries. Wait a moment and try again.", 429)

    def _dispatch(self, method, path, query, headers, body_bytes):
        svc = self.service
        # Public contract: no session, no token, no raw link ever.
        if method == "GET" and path == "/api/v1/app/remote-config":
            return self._json(200, {"success": True,
                "data": fixture_app.public_remote_config(svc),
                "meta": {"config_version": svc._config_row()["config_version"]}}, None, None)
        # Login page + login API.
        if path == "/admin/login":
            if method == "GET":
                user, _sess = self._auth(headers)
                if user:
                    return (303, "text/html", b"", None, "/admin")
                return self._html(200, templates.login_page(query.get("error", [""])[0]))
            if method == "POST":
                body = self._body(headers, body_bytes)
                ip = mask_ip(headers.get("X-Forwarded-For", "127.0.0.1"))
                if not self.limiter.allow("login:" + ip, 5, 60):
                    raise ApiError("rate_limited", "Too many tries. Wait a moment and try again.", 429)
                res = svc.login(body.get("username", ""), body.get("password", ""),
                                body.get("totp"), ip=ip, ua_label=headers.get("User-Agent", "")[:40])
                cookie = ("admin_session=%s; Path=/admin; HttpOnly; SameSite=Lax; Secure"
                          % res["session_token"])
                if self._is_form(headers):
                    return (303, "text/html", b"", cookie, "/admin")
                return self._json(200, {"success": True,
                    "data": {"user": res["user"], "csrf_token": res["csrf_token"]}}, cookie, None)
        if path == "/admin/logout":
            user, sess = self._auth(headers)
            if sess:
                svc.logout(_cookie(headers), ip=mask_ip(headers.get("X-Forwarded-For", "")))
            return (303, "text/html", b"",
                    "admin_session=; Path=/admin; Max-Age=0; HttpOnly; SameSite=Lax", "/admin/login")
        # HTML screens (session required, read-only rendering).
        html_routes = {
            "/admin": ("home", self._page_dashboard),
            "/admin/content": ("content", self._page_content),
            "/admin/sections": ("sections", self._page_sections),
            "/admin/users": ("users", self._page_users),
            "/admin/money": ("money", self._page_money),
            "/admin/inbox": ("inbox", self._page_inbox),
            "/admin/requests": ("requests", self._page_requests),
            "/admin/reports": ("reports", self._page_reports),
            "/admin/broadcasts": ("broadcasts", self._page_broadcasts),
            "/admin/live": ("live", self._page_live),
            "/admin/live-tv": ("live-tv", self._page_live_tv),
            "/admin/domains": ("domains", self._page_domains),
            "/admin/fleet": ("fleet", self._page_fleet),
            "/admin/analytics": ("analytics", self._page_analytics),
            "/admin/usage": ("usage", self._page_usage),
            "/admin/tuning": ("tuning", self._page_tuning),
            "/admin/monetization": ("monetization", self._page_monetization),
            "/admin/data-health": ("data-health", self._page_data_health),
            "/admin/settings": ("settings", self._page_settings),
            "/admin/more": ("more", self._page_more),
            "/admin/search": ("search", self._page_search),
        }
        # Trailing slash: /admin/ (and any admin page with one) redirects
        # to the clean URL instead of 404ing (audit §Cosmetic). API
        # paths never match a page key, so they are untouched.
        if method == "GET" and path.startswith("/admin/") and path.endswith("/") and len(path) > 1:
            clean = path.rstrip("/") or "/admin"
            if clean in html_routes or clean in ("/admin/login", "/admin/logout"):
                return (303, "text/html", b"", None, clean)
        if method == "GET" and path in html_routes:
            try:
                user, sess = self._require_auth(headers)
            except ApiError as exc:
                if exc.code == "unauthenticated":
                    return (303, "text/html", b"", None, "/admin/login")
                raise
            active, fn = html_routes[path]
            page = fn(user, sess, query)
            return self._html(200, page)
        # JSON API v2.
        if path.startswith("/admin/api/v2/"):
            return self._api(method, path, query, headers, body_bytes)
        return self._json(404, {"success": False, "error": {"code": "not_found",
            "message": "That page was not found."}}, None, None)

    def _is_form(self, headers):
        return "application/x-www-form-urlencoded" in headers.get("Content-Type", "")

    def _body(self, headers, body_bytes):
        if not body_bytes:
            return {}
        if "application/json" in headers.get("Content-Type", ""):
            try:
                data = json.loads(body_bytes.decode())
                return data if isinstance(data, dict) else {}
            except Exception:
                raise ApiError("invalid_params", "That request body is not valid JSON.", 400)
        parsed = urllib.parse.parse_qs(body_bytes.decode())
        out = {}
        for k, v in parsed.items():
            out[k] = v[0] if len(v) == 1 else v
        # Form checkboxes/flags: "on"/"true"/"1" -> True for confirm-style fields.
        for k in ("confirm",):
            if k in out and isinstance(out[k], str):
                out[k] = out[k] in ("on", "true", "1", "True")
        return out

    def _wrap(self, headers, body, fn, is_write, session_key=""):
        """Rate-limit, CSRF for writes, then run fn and wrap the result."""
        user, sess = self._require_auth(headers)
        if is_write:
            self._rate("write:" + str(sess["id"]), 60, 60)
            self._csrf(headers, body, sess)
        else:
            self._rate("read:" + str(sess["id"]), 300, 60)
        # Transport fields only, read above: the CSRF token and the
        # post-redirect target must never reach a service body validator.
        # Every HTML form carries both, and _validate_body refuses unknown
        # fields — a form POST to fleet/run 400'd on "Unknown field:
        # _next,csrf_token" until this strip (found porting /admin/requests,
        # D2.6). No service reads either field; the redirect keeps _next.
        nxt = body.pop("_next", None) if isinstance(body, dict) else None
        if isinstance(body, dict):
            body.pop("csrf_token", None)
        data = fn(user)
        ip = mask_ip(headers.get("X-Forwarded-For", ""))
        _ = ip
        if self._is_form(headers) and is_write:
            return (303, "text/html", b"", None, nxt or "/admin")
        return self._json(200, {"success": True, "data": data,
            "meta": {"config_version": self.service._config_row()["config_version"]}}, None, None)


def _cookie(headers):
    return parse_cookies(headers.get("Cookie", "")).get("admin_session", "")


# -- API dispatch (attached to AdminApp) ---------------------------------

def _api(self, method, path, query, headers, body_bytes):
    svc = self.service
    body = self._body(headers, body_bytes) if method in ("POST", "PUT", "DELETE", "PATCH") else {}
    ip = mask_ip(headers.get("X-Forwarded-For", "127.0.0.1"))
    idem = headers.get("Idempotency-Key")
    q = lambda k, d=None: (query.get(k, [d])[0] if query.get(k) else d)
    after = q("after_id"); limit = q("limit", 20)
    m = re.match

    def wrap(fn, write=False):
        # Capture ip for audit calls inside fn via closure argument.
        def call(user):
            return fn(user, ip)
        return self._wrap(headers, body, call, write)

    # Auth (login handled above; logout/me/password-change here).
    if path == "/admin/api/v2/auth/me" and method == "GET":
        return wrap(lambda u, _ip: {"user": u}, write=False)
    if path == "/admin/api/v2/auth/logout" and method == "POST":
        user, sess = self._require_auth(headers)
        self._csrf(headers, body, sess)
        return self._json(200, {"success": True, "data": svc.logout(_cookie(headers), ip=ip)}, None, None)
    if path == "/admin/api/v2/auth/password-change" and method == "POST":
        user, sess = self._require_auth(headers)
        self._csrf(headers, body, sess)
        res = svc.change_password(user, _cookie(headers), body.get("current", ""),
                                  body.get("new", ""), ip=ip)
        cookie = ("admin_session=%s; Path=/admin; HttpOnly; SameSite=Lax; Secure"
                  % res["session_token"])
        if self._is_form(headers):
            return (303, "text/html", b"", cookie, body.get("_next") or "/admin/settings")
        return self._json(200, {"success": True, "data": {"csrf_token": res["csrf_token"]}}, cookie, None)

    if path == "/admin/api/v2/analytics/export" and method == "GET":
        user, sess = self._require_auth(headers)
        csv = svc.export_analytics_csv(user)
        return (200, "text/csv", csv.encode(), None, None)

    routes = []
    # (method, regex, handler(user, ip) -> data, write?)
    R = routes.append
    R(("GET", r"^/admin/api/v2/dashboard$", lambda u, _ip: svc.dashboard(u), False))
    R(("GET", r"^/admin/api/v2/audit$", lambda u, _ip: svc.list_audit(u, action=q("action"), actor_id=q("actor"), after_id=after, limit=limit), False))
    R(("GET", r"^/admin/api/v2/audit/export$", lambda u, _ip: {"csv": svc.export_audit_csv(u)}, False))
    R(("GET", r"^/admin/api/v2/sessions$", lambda u, _ip: svc.list_sessions(u), False))
    R(("GET", r"^/admin/api/v2/sections$", lambda u, _ip: svc.list_sections(u), False))
    R(("POST", r"^/admin/api/v2/sections$", lambda u, _ip: svc.create_section(u, body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/sections/([^/]+)/cards$", lambda u, _ip, k=None: svc.list_cards(u, _last(path)), False))
    R(("POST", r"^/admin/api/v2/sections/([^/]+)/cards$", lambda u, _ip: svc.add_card(u, _last2(path), body, ip=_ip), True))
    R(("PUT", r"^/admin/api/v2/cards/(\d+)$", lambda u, _ip, cid=None: svc.update_card(u, int(_last(path)), body, ip=_ip), True))
    R(("DELETE", r"^/admin/api/v2/cards/(\d+)$", lambda u, _ip: svc.delete_card(u, int(_last(path)), ip=_ip), True))
    R(("PUT", r"^/admin/api/v2/sections/([^/]+)$", lambda u, _ip: svc.update_section(u, _last(path), body, ip=_ip), True))
    R(("DELETE", r"^/admin/api/v2/sections/([^/]+)$", lambda u, _ip: svc.delete_section(u, _last(path), ip=_ip), True))
    R(("POST", r"^/admin/api/v2/sections/([^/]+)/toggle$", lambda u, _ip: svc.toggle_section(u, _last2(path), ip=_ip), True))
    R(("GET", r"^/admin/api/v2/content/search$", lambda u, _ip: svc.search_works(u, q=q("q", ""), wtype=q("type"), after_id=after, limit=limit), False))
    R(("GET", r"^/admin/api/v2/content/hidden$", lambda u, _ip: svc.list_hidden(u), False))
    R(("POST", r"^/admin/api/v2/content/hide$", lambda u, _ip: svc.hide_content(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/content/unhide$", lambda u, _ip: svc.unhide_content(u, int(body.get("visibility_id", 0)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/categories$", lambda u, _ip: svc.list_categories(u), False))
    R(("POST", r"^/admin/api/v2/categories$", lambda u, _ip: svc.create_category(u, body, ip=_ip), True))
    R(("PUT", r"^/admin/api/v2/categories/([^/]+)$", lambda u, _ip: svc.update_category(u, _last(path), body, ip=_ip), True))
    R(("DELETE", r"^/admin/api/v2/categories/([^/]+)$", lambda u, _ip: svc.delete_category(u, _last(path), ip=_ip), True))
    R(("GET", r"^/admin/api/v2/categories/([^/]+)/works$", lambda u, _ip: svc.list_category_works(u, _last2(path)), False))
    R(("POST", r"^/admin/api/v2/categories/([^/]+)/works$", lambda u, _ip: svc.assign_category_work(u, _last2(path), body, ip=_ip), True))
    R(("DELETE", r"^/admin/api/v2/categories/([^/]+)/works/(\d+)$", lambda u, _ip: svc.unassign_category_work(u, _last3(path), int(_last(path)), ip=_ip), True))
    R(("GET", r"^/admin/api/v2/content-safety$", lambda u, _ip: svc.get_content_safety(u), False))
    R(("PUT", r"^/admin/api/v2/content-safety$", lambda u, _ip: svc.update_content_safety(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/content-safety/block$", lambda u, _ip: svc.block_adult_globally(u, body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/tuning$", lambda u, _ip: svc.get_tuning(u), False))
    R(("PUT", r"^/admin/api/v2/tuning$", lambda u, _ip: svc.put_tuning(u, body, ip=_ip), True))
    # POST alias so the HTML Tuning form can save (forms cannot PUT).
    R(("POST", r"^/admin/api/v2/tuning$", lambda u, _ip: svc.put_tuning(u, body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/pauses$", lambda u, _ip: svc.list_pauses(u), False))
    R(("POST", r"^/admin/api/v2/pauses$", lambda u, _ip: svc.pause(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/pauses/(\d+)/resume$", lambda u, _ip: svc.resume_pause(u, int(_last2(path)), ip=_ip), True))
    R(("GET", r"^/admin/api/v2/users/search$", lambda u, _ip: svc.search_users(u, q=q("q", ""), tier=q("tier")), False))
    R(("POST", r"^/admin/api/v2/users/([^/]+)/vip-grant$", lambda u, _ip: svc.vip_grant(u, urllib.parse.unquote(_last2(path)), body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/users/([^/]+)/flag$", lambda u, _ip: svc.flag_user(u, urllib.parse.unquote(_last2(path)), body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/users/([^/]+)/flag-clear$", lambda u, _ip: svc.clear_flag(u, int(body.get("flag_id", 0)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/payments$", lambda u, _ip: svc.list_payments(u, status=q("status"), method=q("method"), after_id=after, limit=limit), False))
    R(("GET", r"^/admin/api/v2/payments/(\d+)$", lambda u, _ip: svc.get_payment(u, int(_last(path))), False))
    R(("GET", r"^/admin/api/v2/payments/search$", lambda u, _ip: svc.search_payment_by_tid(u, q("tid", "")), False))
    R(("POST", r"^/admin/api/v2/payments/(\d+)/approve$", lambda u, _ip: svc.approve_payment(u, int(_last2(path)), body, idempotency_key=idem, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/payments/(\d+)/reject$", lambda u, _ip: svc.reject_payment(u, int(_last2(path)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/monetization$", lambda u, _ip: svc.get_monetization(u), False))
    R(("PUT", r"^/admin/api/v2/monetization$", lambda u, _ip: svc.put_monetization(u, body, ip=_ip), True))
    # POST alias so the HTML Monetization form can save (forms cannot PUT).
    R(("POST", r"^/admin/api/v2/monetization$", lambda u, _ip: svc.put_monetization(u, body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/data-health$", lambda u, _ip: svc.data_health(u), False))
    R(("GET", r"^/admin/api/v2/contact$", lambda u, _ip: svc.list_contact(u, status=q("status"), category=q("category"), after_id=after, limit=limit), False))
    R(("POST", r"^/admin/api/v2/contact/(\d+)/status$", lambda u, _ip: svc.update_contact(u, int(_last2(path)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/reports$", lambda u, _ip: svc.list_reports(u, status=q("status"), reason=q("reason"), after_id=after, limit=limit), False))
    R(("POST", r"^/admin/api/v2/reports/(\d+)/action$", lambda u, _ip: svc.report_action(u, int(_last2(path)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/broadcasts$", lambda u, _ip: svc.list_broadcasts(u), False))
    R(("POST", r"^/admin/api/v2/broadcasts$", lambda u, _ip: svc.create_broadcast(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/broadcasts/(\d+)/publish$", lambda u, _ip: svc.publish_broadcast(u, int(_last2(path)), body, idempotency_key=idem, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/broadcasts/(\d+)/retract$", lambda u, _ip: svc.retract_broadcast(u, int(_last2(path)), ip=_ip), True))
    R(("GET", r"^/admin/api/v2/remote-config$", lambda u, _ip: svc.get_remote_config(u), False))
    R(("PUT", r"^/admin/api/v2/remote-config$", lambda u, _ip: svc.draft_remote_config(u, body, ip=_ip), True))
    # POST alias so the HTML Live draft form can save (forms cannot PUT).
    R(("POST", r"^/admin/api/v2/remote-config$", lambda u, _ip: svc.draft_remote_config(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/remote-config/publish$", lambda u, _ip: svc.publish_remote_config(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/remote-config/rollback$", lambda u, _ip: svc.rollback_remote_config(u, body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/remote-config/history$", lambda u, _ip: svc.list_config_history(u), False))
    R(("GET", r"^/admin/api/v2/live$", lambda u, _ip: svc.get_live(u), False))
    R(("GET", r"^/admin/api/v2/live-tv$", lambda u, _ip: svc.list_live_tv(u), False))
    R(("POST", r"^/admin/api/v2/live-tv$", lambda u, _ip: svc.add_live_tv_channel(u, body, checker=self.stream_checker, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/live-tv/(\d+)$", lambda u, _ip: svc.set_live_tv_channel(u, int(_last(path)), body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/live-tv/(\d+)/edit$", lambda u, _ip: svc.update_live_tv_channel(u, int(_last2(path)), body, checker=self.stream_checker, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/live-tv/(\d+)/delete$", lambda u, _ip: svc.delete_live_tv_channel(u, int(_last2(path)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/remote-config/scheduled$", lambda u, _ip: svc.list_scheduled(u), False))
    R(("POST", r"^/admin/api/v2/remote-config/schedule$", lambda u, _ip: svc.schedule_publish(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/remote-config/schedule/(\d+)/cancel$", lambda u, _ip: svc.cancel_scheduled_publish(u, int(_last2(path)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/domains$", lambda u, _ip: svc.list_domains(u), False))
    R(("GET", r"^/admin/api/v2/domains/([^/]+)$", lambda u, _ip: svc.get_domain(u, _last(path)), False))
    R(("GET", r"^/admin/api/v2/domains/([^/]+)/health$", lambda u, _ip: svc.domain_health(u, _last2(path)), False))
    R(("GET", r"^/admin/api/v2/domains/([^/]+)/history$", lambda u, _ip: svc.domain_history(u, _last2(path)), False))
    R(("POST", r"^/admin/api/v2/domains/([^/]+)/candidates$", lambda u, _ip: svc.add_candidate(u, _last2(path), body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/domains/([^/]+)/validate$", lambda u, _ip: svc.validate_domain(u, _last2(path), body, checker=self.domain_checker, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/domains/([^/]+)/apply$", lambda u, _ip: svc.apply_domain(u, _last2(path), body, checker=self.domain_checker, idempotency_key=idem, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/domains/([^/]+)/rollback$", lambda u, _ip: svc.rollback_domain(u, _last2(path), body, checker=self.domain_checker, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/domains/([^/]+)/auto-failover$", lambda u, _ip: svc.set_auto_failover(u, _last2(path), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/fleet$", lambda u, _ip: svc.list_fleet(u), False))
    R(("POST", r"^/admin/api/v2/fleet/run$", lambda u, _ip: svc.run_fleet(u, body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/requests$", lambda u, _ip: svc.list_requests(u), False))
    R(("POST", r"^/admin/api/v2/requests/(\d+)/indexed$", lambda u, _ip: svc.review_request(u, int(_last2(path)), "indexed", body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/requests/(\d+)/declined$", lambda u, _ip: svc.review_request(u, int(_last2(path)), "declined", body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/requests/trigger$", lambda u, _ip: svc.trigger_request_crawl(u, body, ip=_ip), True))
    R(("POST", r"^/admin/api/v2/links/(\d+)/evidence$", lambda u, _ip: svc.refold_evidence(u, int(_last2(path)), ip=_ip), True))
    R(("GET", r"^/admin/api/v2/analytics$", lambda u, _ip: svc.get_analytics(u), False))
    R(("GET", r"^/admin/api/v2/usage$", lambda u, _ip: svc.usage_summary(u), False))
    R(("POST", r"^/admin/api/v2/analytics/compute$", lambda u, _ip: svc.compute_analytics_day(u, body.get("day", "2026-11-05")), True))
    R(("POST", r"^/admin/api/v2/contact$", lambda u, _ip: svc.create_contact(u, body), True))
    R(("POST", r"^/admin/api/v2/reports$", lambda u, _ip: svc.create_report(u, body), True))
    R(("PUT", r"^/admin/api/v2/broadcasts/(\d+)$", lambda u, _ip: svc.update_broadcast(u, int(_last(path)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/users/([^/]+)/payments$", lambda u, _ip: svc.user_payment_history(u, urllib.parse.unquote(_last2(path))), False))
    R(("POST", r"^/admin/api/v2/payments/(\d+)/refund-note$", lambda u, _ip: svc.add_refund_note(u, int(_last2(path)), body, ip=_ip), True))
    R(("GET", r"^/admin/api/v2/sections/([^/]+)/preview$", lambda u, _ip: svc.resolve_section_preview(u, _last2(path)), False))
    R(("GET", r"^/admin/api/v2/analytics/export$", lambda u, _ip: {"csv": svc.export_analytics_csv(u)}, False))
    R(("GET", r"^/admin/api/v2/fleet/([^/]+)/audit$", lambda u, _ip: svc.live.fleet_audit(_last2(path)) if svc.live is not None and svc.live.has_catalog else {"items": [], "count": 0, "note": "no live catalog wired"}, False))
    R(("GET", r"^/admin/api/v2/review-queue$", lambda u, _ip: svc.live.review_queue() if svc.live is not None and svc.live.has_catalog else {"items": [], "count": 0, "note": "no live catalog wired"}, False))
    R(("GET", r"^/admin/api/v2/search$", lambda u, _ip: svc.global_search(u, q("q", "")), False))
    R(("GET", r"^/admin/api/v2/settings$", lambda u, _ip: svc.panel_settings(u), False))
    R(("POST", r"^/admin/api/v2/prune$", lambda u, _ip: svc.prune(u), True))
    R(("DELETE", r"^/admin/api/v2/sessions/(\d+)$", lambda u, _ip: svc.revoke_session(u, int(_last(path)), ip=_ip), True))

    for meth, pattern, fn, write in routes:
        if meth != method:
            continue
        if re.match(pattern + "$", path):
            return wrap(fn, write=write)
    return self._json(404, {"success": False, "error": {"code": "not_found",
        "message": "That page was not found."}}, None, None)


def _last(path):
    return path.rstrip("/").split("/")[-1]


def _last2(path):
    return path.rstrip("/").split("/")[-2]


def _last3(path):
    return path.rstrip("/").split("/")[-3]


AdminApp._api = _api


# -- HTML pages -----------------------------------------------------------

def _page_dashboard(self, user, sess, query):
    svc = self.service
    try:
        d = svc.dashboard(user)
    except Exception:
        d = {"pending_payments": 0, "open_reports": 0, "failed_domains": 0,
             "active_broadcasts": 0, "maintenance_mode": False,
             "config_version": 0, "cert_expiry": "Unknown", "paused": [],
             "needs_you_now": ["Could not load counts. Try again."]}
    state = (query.get("state", [""])[0] if query.get("state") else "")
    error = (query.get("error", [""])[0] if query.get("error") else "")
    needs = "".join("<li>%s</li>" % templates.esc(n) for n in d.get("needs_you_now", [])) or \
        "<li>All clear — nothing needs you right now.</li>"
    paused = "".join("<li>%s %s — %s</li>" % (templates.esc(p["target_type"]),
        templates.esc(p["target_id"]), templates.esc(p.get("reason", "")))
        for p in d.get("paused", [])) or "<li>No pauses right now — nothing is paused.</li>"
    stats = [
        ("Pending payments", d.get("pending_payments") or 0,
         templates.badge("Pending") if d.get("pending_payments") else ""),
        ("Open reports", d.get("open_reports") or 0,
         templates.badge("Pending") if d.get("open_reports") else ""),
        ("Failed domains", d.get("failed_domains") or 0,
         templates.badge("Failed") if d.get("failed_domains") else ""),
        ("Active broadcasts", d.get("active_broadcasts") or 0, ""),
    ]
    stat_html = "".join(
        '<div class="stat"><div class="stat-label">%s</div>'
        '<div class="stat-num">%s</div>%s</div>' % (label, num, b)
        for label, num, b in stats)
    sys_line = "Maintenance: %s. Config version: %s. Certificate expiry: %s." % (
        "On" if d.get("maintenance_mode") else "Off", d.get("config_version"),
        d.get("cert_expiry") or "Unknown")
    if d.get("catalog_posts") is not None:
        sys_line += " Catalog: %s posts, %s works, %s releases, %s sources (%s active, %s resumable)." % (
            d.get("catalog_posts"), d.get("catalog_works"), d.get("catalog_releases"), d.get("catalog_sources"),
            d.get("active_sources"), d.get("resumable_sources"))
        if d.get("projection_age_h") is not None:
            sys_line += " Projection age: %s h." % d.get("projection_age_h")
    if d.get("review_queue_count"):
        sys_line += " Review queue: %s items." % d.get("review_queue_count")
    if d.get("link_health", {}).get("failed_total"):
        sys_line += " Failed links: %s." % d.get("link_health", {}).get("failed_total")
    if d.get("service_state") not in (None, "unknown"):
        sys_line += " Service: %s." % d.get("service_state")
    if d.get("disk_free_gb") is not None:
        sys_line += " Disk free: %s GB of %s GB." % (d.get("disk_free_gb"), d.get("disk_total_gb"))
    if d.get("load_1m") is not None:
        sys_line += " Load (1m): %.2f." % d.get("load_1m")
    if d.get("quality") == "stale":
        age_min = max(0, int(d.get("stale_age_s") or 0) // 60)
        sys_line += " Counts updated %d min ago." % age_min
    body = """
<div class="stats">%s</div>
<div class="card"><h2>Needs you now</h2><ul>%s</ul></div>
<div class="card"><h2>Paused</h2><ul>%s</ul></div>
<div class="card"><h2>Quick actions</h2>
<p><a class="btn secondary" href="/admin/content">Hide a title</a>
<a class="btn secondary" href="/admin/money">Approve a payment</a>
<a class="btn secondary" href="/admin/broadcasts">Publish a broadcast</a>
<a class="btn secondary" href="/admin/domains">Change a domain</a></p></div>
<div class="card"><h2>System</h2>
<p>%s</p></div>
""" % (stat_html, needs, paused, sys_line)
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin")
    body += """<div class="card"><h3>Pause something</h3>
<p class="muted">Pauses are recorded here, but the backend does not enforce them yet — pausing changes nothing in the app until a backend consumer reads them.</p>
<form method="post" action="/admin/api/v2/pauses">%s
<label for="pause-target-type">Target type</label><select id="pause-target-type" name="target_type">
<option value="import_global">import_global</option><option value="prefetch_global">prefetch_global</option>
<option value="source">source</option><option value="section">section</option>
<option value="category">category</option><option value="feature">feature</option>
<option value="broadcast">broadcast</option><option value="domain_checks">domain_checks</option></select>
<label for="pause-target-id">Target id</label><input id="pause-target-id" name="target_id" required>
<label for="pause-reason">Reason</label><input id="pause-reason" name="reason" required>
<div class="stickybar"><button type="submit">Pause</button></div></form></div>
<div class="card"><h3>Resume a pause</h3>
<p>Each paused item below has its own resume button with its pause id in the form action.</p></div>""" % hid
    # Per-pause resume forms (correct URL per pause id).
    for p in d.get("paused", []):
        body += """<div class="card"><h3>Resume pause %s</h3>
<form method="post" action="/admin/api/v2/pauses/%s/resume">%s
<p>%s %s — %s</p>
<div class="stickybar"><button type="submit" class="secondary">Resume this pause</button></div></form></div>""" % (
            templates.esc(p.get("id", "")), templates.esc(p.get("id", "")), hid,
            templates.esc(p.get("target_type", "")), templates.esc(p.get("target_id", "")),
            templates.esc(p.get("reason", "")))
    return templates.layout("Dashboard", body, active="home", state=state, error=error)


def _page_content(self, user, sess, query):
    svc = self.service
    q = (query.get("q", [""])[0] if query.get("q") else "")
    wtype = (query.get("type", [""])[0] if query.get("type") else "") or None
    after = (query.get("after_id", [""])[0] if query.get("after_id") else "") or None
    res = svc.search_works(user, q=q, wtype=wtype, after_id=after, limit=20)
    works = res["items"]
    hidden = svc.list_hidden(user)["items"]
    ov = svc.catalog_overview(user)
    if ov.get("available"):
        body = ("<p>Catalog: %s works, %s posts — %s adult-flagged posts, "
                "%s adult-flagged works (hidden from the app, visible here).</p>" % (
                    ov.get("works"), ov.get("posts"),
                    ov.get("adult_posts"), ov.get("adult_works")))
    else:
        body = ""
    rows = [[w["id"], w["title"], w["type"], w["year"],
             templates.Raw(templates.badge(w.get("poster_state") or "Unknown")),
             templates.Raw(templates.badge(
                 "Adult" if w["adult_flag"] == 1 else ("Unknown" if w["adult_flag"] is None else "Safe")))]
            for w in works]
    body += """<form method="get" action="/admin/content" class="filterbar" aria-label="Search works">
<div class="field"><label for="content-q">Search works</label>
<input id="content-q" name="q" value="%s" placeholder="Title"></div>
<div class="field"><label for="content-type">Type</label>
<select id="content-type" name="type">
<option value=""%s>All types</option>
<option value="movie"%s>Movie</option>
<option value="series"%s>Series</option></select></div>
<button type="submit">Search</button></form>""" % (
        templates.esc(q),
        " selected" if not wtype else "",
        " selected" if wtype == "movie" else "",
        " selected" if wtype == "series" else "")
    body += "<h2>Works</h2>" + templates.table(
        ["ID", "Title", "Type", "Year", "Poster", "Adult flag"], rows, "No works yet")
    if res.get("next_after_id"):
        params = {"after_id": res["next_after_id"]}
        if q:
            params["q"] = q
        if wtype:
            params["type"] = wtype
        body += '<p class="pager"><a class="btn secondary" href="/admin/content?%s">Next page</a></p>' % (
            urllib.parse.urlencode(params))
    body += "<h2>Hidden now</h2>" + templates.table(
        ["ID", "Scope", "Scope ID", "Reason"], [[h["id"], h["scope"], h["scope_id"], h["reason"]] for h in hidden],
        "Nothing is hidden")
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/content")
    body += """<div class="card"><h3>Hide a work</h3>
<form method="post" action="/admin/api/v2/content/hide">%s
<label for="scope">Scope</label><select id="scope" name="scope"><option value="work">Work</option><option value="section">Section</option></select>
<label for="scope_id">Work or section id</label><input id="scope_id" name="scope_id" required>
<label for="reason">Reason</label><select id="reason" name="reason"><option value="owner">Owner</option><option value="takedown">Takedown</option><option value="quality">Quality</option><option value="duplicate">Duplicate</option></select>
<div class="stickybar"><button type="submit" class="danger">Hide</button></div></form>
<p>Visible on next app refresh. Hiding never deletes a catalog row.</p></div>
<div class="card"><h3>Unhide</h3>
<form method="post" action="/admin/api/v2/content/unhide">%s
<label for="unhide-id">Visibility id</label><input id="unhide-id" name="visibility_id" type="number" min="1" required>
<label for="unhide-note">Note</label><input id="unhide-note" name="note">
<div class="stickybar"><button type="submit">Unhide</button></div></form></div>
<div class="card"><h3>Create a category</h3>
<form method="post" action="/admin/api/v2/categories">%s
<label for="cat-key">Category key (lowercase, dash or underscore)</label><input id="cat-key" name="key" required>
<label for="cat-name">Display name</label><input id="cat-name" name="display_name" required>
<label for="cat-position">Position</label><input id="cat-position" name="position" type="number" value="0">
<div class="stickybar"><button type="submit">Create category</button></div></form></div>""" % (hid, hid, hid)
    cats = svc.list_categories(user)["items"]
    body += "<h2>Categories</h2>" + templates.table(
        ["Key", "Display name", "Position"], [[c["key"], c["display_name"], c["position"]] for c in cats],
        "No categories yet")
    for c in cats:
        body += """<div class="card"><h3>Assign a work to %s</h3>
<form method="post" action="/admin/api/v2/categories/%s/works">%s
<label for="assign-work-%s">Work id</label><input id="assign-work-%s" name="work_id" type="number" min="1" required>
<label for="assign-pos-%s">Position</label><input id="assign-pos-%s" name="position" type="number" value="0">
<div class="stickybar"><button type="submit">Assign work</button></div></form></div>""" % (
            templates.esc(c["key"]), templates.esc(c["key"]), hid,
            templates.esc(c["key"]), templates.esc(c["key"]),
            templates.esc(c["key"]), templates.esc(c["key"]))
    # CSRF tokens are per-session form secrets and are meant to be
    # embedded in forms for the authenticated session. The session
    # token itself stays in the HttpOnly cookie only, never in HTML.
    return templates.layout("Content", body, active="content")


def _page_sections(self, user, sess, query):
    secs = self.service.list_sections(user)["items"]
    rows = [[s["key"], s["title"], s["position"],
             templates.Raw(templates.badge("Enabled" if s["is_enabled"] else "Disabled"))] for s in secs]
    body = templates.table(["Key", "Title", "Position", "State"], rows, "No sections yet", "/admin/content")
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/sections")
    body += """<div class="card"><h3>Create a section</h3>
<form method="post" action="/admin/api/v2/sections">%s
<label for="sec-key">Section key (lowercase, dash or underscore)</label><input id="sec-key" name="key" required>
<label for="sec-title">Title</label><input id="sec-title" name="title" required>
<label for="sec-position">Position</label><input id="sec-position" name="position" type="number" value="0">
<label for="sec-source">Source</label><select id="sec-source" name="source_rule">
<option value="latest">latest</option><option value="trending">trending</option>
<option value="category">category</option><option value="curated">curated</option></select>
<label for="sec-category">Category key (only for source category)</label><input id="sec-category" name="category_key">
<div class="stickybar"><button type="submit">Create section</button></div></form></div>""" % hid
    for s in secs:
        key = templates.esc(s["key"])
        body += """<div class="card"><h3>%s</h3>
<form method="post" action="/admin/api/v2/sections/%s/toggle">%s
<p>Currently: %s</p>
<div class="stickybar"><button type="submit" class="secondary">%s</button></div></form>
<form method="post" action="/admin/api/v2/sections/%s/cards">%s
<label for="card-work-%s">Work id</label><input id="card-work-%s" name="work_id" type="number" min="1" required>
<label for="card-pos-%s">Position</label><input id="card-pos-%s" name="position" type="number" value="0">
<label for="card-title-%s">Title override</label><input id="card-title-%s" name="title_override">
<div class="stickybar"><button type="submit">Add card</button></div></form></div>""" % (
            key, key, hid, templates.badge("Enabled" if s["is_enabled"] else "Disabled"),
            "Disable section" if s["is_enabled"] else "Enable section",
            key, hid, key, key, key, key, key, key)
    return templates.layout("Sections", body, active="sections")


def _page_users(self, user, sess, query):
    q = (query.get("q", [""])[0] if query.get("q") else "")
    tier = (query.get("tier", [""])[0] if query.get("tier") else "") or None
    after = (query.get("after_id", [""])[0] if query.get("after_id") else "") or None
    res = self.service.search_users(user, q=q, tier=tier, after_id=after, limit=20)
    users = res["items"]
    rows = [[u["account_hint"], templates.Raw(templates.badge(u["tier"])),
             templates.fmt_date(u["vip_until"]),
             # None means "unknown, not zero": a per-account device count
             # cannot be computed (see LiveStores.search_users), so the
             # cell says so instead of printing an empty cell or a lying 0.
             u["device_count"] if u["device_count"] is not None else "unknown",
             "%d coins" % (u.get("balance") or 0)]
            for u in users]
    body = """<form method="get" action="/admin/users" class="filterbar" aria-label="Search users">
<div class="field"><label for="users-q">Search users</label>
<input id="users-q" name="q" value="%s" placeholder="Account hint"></div>
<div class="field"><label for="users-tier">Tier</label>
<select id="users-tier" name="tier">
<option value=""%s>All tiers</option>
<option value="free"%s>Free</option>
<option value="vip"%s>VIP</option></select></div>
<button type="submit">Search</button></form>""" % (
        templates.esc(q),
        " selected" if not tier else "",
        " selected" if tier == "free" else "",
        " selected" if tier == "vip" else "")
    body += templates.table(["Account hint", "Tier", "VIP until", "Devices", "Coins"], rows, "No users yet")
    if res.get("next_after_id"):
        params = {"after_id": res["next_after_id"]}
        if q:
            params["q"] = q
        if tier:
            params["tier"] = tier
        body += '<p class="pager"><a class="btn secondary" href="/admin/users?%s">Next page</a></p>' % (
            urllib.parse.urlencode(params))
    body += "<p>Ban and device flags are stored, not enforced, until an app/backend gate lands.</p>"
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/users")
    for i, u in enumerate(users):
        hint = u["account_hint"]
        qhint = urllib.parse.quote(hint, safe="")
        body += """<div class="card"><h3>%s</h3>
<form method="post" action="/admin/api/v2/users/%s/vip-grant">%s
<label for="vip-months-%d">VIP months (1 to 24)</label><input id="vip-months-%d" name="months" type="number" min="1" max="24" required>
<label for="vip-reason-%d">Reason</label><input id="vip-reason-%d" name="reason" required>
<div class="stickybar"><button type="submit">Grant VIP</button></div></form>
<form method="post" action="/admin/api/v2/users/%s/flag">%s
<label for="flag-%d">Flag</label><select id="flag-%d" name="flag">
<option value="banned">banned</option><option value="device_reset_requested">device_reset_requested</option></select>
<label for="flag-reason-%d">Reason</label><input id="flag-reason-%d" name="reason" required>
<div class="stickybar"><button type="submit" class="danger">Flag user</button></div></form></div>""" % (
            templates.esc(hint), qhint, hid, i, i, i, i, qhint, hid, i, i, i, i)
    return templates.layout("Users", body, active="users")


def _page_money(self, user, sess, query):
    status = (query.get("status", [""])[0] if query.get("status") else "") or None
    after = (query.get("after_id", [""])[0] if query.get("after_id") else "") or None
    res = self.service.list_payments(user, status=status, after_id=after)
    pays = res["items"]
    rows = [[p["id"], p["account_hint"], p["method"], templates.fmt_pkr(p["amount_pkr"]),
             templates.fmt_date(p.get("submitted_at") or p.get("created_at")),
             templates.Raw(templates.badge(p["status"]))] for p in pays]
    mon = self.service.get_monetization(user)
    body = """<form method="get" action="/admin/money" class="filterbar" aria-label="Filter payments">
<div class="field"><label for="money-status">Status</label>
<select id="money-status" name="status">
<option value=""%s>All statuses</option>
<option value="pending"%s>Pending</option>
<option value="approved"%s>Approved</option>
<option value="rejected"%s>Rejected</option></select></div>
<button type="submit">Filter</button></form>""" % (
        " selected" if not status else "",
        " selected" if status == "pending" else "",
        " selected" if status == "approved" else "",
        " selected" if status == "rejected" else "")
    body += templates.table(["ID", "Account hint", "Method", "Amount", "Submitted", "Status"], rows, "No pending payments")
    if res.get("next_after_id"):
        params = {"after_id": res["next_after_id"]}
        if status:
            params["status"] = status
        body += '<p class="pager"><a class="btn secondary" href="/admin/money?%s">Next page</a></p>' % (
            urllib.parse.urlencode(params))
    body += "<div class='card'><h3>VIP prices</h3><p>Monthly: %s. Yearly: %s. New prices affect new purchases only.</p></div>" % (
        templates.fmt_pkr(mon["vip_monthly_pkr"]), templates.fmt_pkr(mon["vip_yearly_pkr"]))
    body += ("<div class='card'><h3>Coin prices</h3><p>Day pass: %s coins. Weekend: %s. Monthly: %s. "
             "Download: %s. Movie request: %s. Theme: %s.</p>"
             "<p><a class=\"btn secondary\" href=\"/admin/monetization\">Edit prices in Monetization</a></p></div>" % (
                 mon.get("coin_redeem_day"), mon.get("coin_redeem_weekend"),
                 mon.get("coin_redeem_monthly"), mon.get("coin_redeem_download"),
                 mon.get("coin_redeem_request"), mon.get("coin_redeem_theme")))
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/money")
    for p in pays:
        pid = p["id"]
        body += """<div class="card"><h3>Payment %s — %s</h3>
<form method="post" action="/admin/api/v2/payments/%s/approve">%s
<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm approve</span></label>
<div class="stickybar"><button type="submit">Approve payment</button></div></form>
<form method="post" action="/admin/api/v2/payments/%s/reject">%s
<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm reject</span></label>
<label for="reject-note-%s">Note</label><input id="reject-note-%s" name="note">
<div class="stickybar"><button type="submit" class="danger">Reject payment</button></div></form></div>""" % (
            templates.esc(pid), templates.esc(p["status"]), pid, hid, pid, hid, pid, pid)
    return templates.layout("Money", body, active="money")


def _page_inbox(self, user, sess, query):
    msgs = self.service.list_contact(user)["items"]
    def _body_preview(m):
        text = (m.get("body") or "").strip()
        if not text:
            return "—"
        return text[:80] + ("…" if len(text) > 80 else "")
    rows = [[m["id"], m.get("app_account_hint") or "—", m["category"], m["subject"] or "",
             templates.fmt_datetime(m.get("created_at")),
             _body_preview(m),
             templates.Raw(templates.badge(m["status"]))] for m in msgs]
    body = templates.table(["ID", "Sender", "Category", "Subject", "Date", "Message", "Status"], rows, "No contact messages yet")
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/inbox")
    for m in msgs:
        body += """<div class="card"><h3>Message %s</h3>
<p>From %s · %s</p>
<p>%s</p>
<form method="post" action="/admin/api/v2/contact/%s/status">%s
<label for="contact-status-%s">Status</label><select id="contact-status-%s" name="status">
<option value="open">Open</option><option value="in_progress">In progress</option>
<option value="resolved">Resolved</option><option value="spam">Spam</option></select>
<label for="contact-note-%s">Internal note</label><input id="contact-note-%s" name="internal_note" value="%s">
<div class="stickybar"><button type="submit">Update status</button></div></form></div>""" % (
            templates.esc(m["id"]),
            templates.esc(m.get("app_account_hint") or "—"),
            templates.fmt_datetime(m.get("created_at")),
            templates.esc(m.get("body") or "—"),
            m["id"], hid, m["id"], m["id"], m["id"], m["id"],
            templates.esc(m.get("internal_note") or ""))
    return templates.layout("Inbox", body, active="inbox")


def _page_reports(self, user, sess, query):
    reps = self.service.list_reports(user)["items"]
    def _sla(r):
        if r.get("sla_breached"):
            return "Breached — over 48h"
        left = r.get("sla_hours_left")
        return ("%.1f h left" % left) if left is not None else "—"
    rows = [[r["id"], r["reason"], templates.Raw(templates.badge(r["status"])), _sla(r)] for r in reps]
    body = templates.table(["ID", "Reason", "Status", "48h SLA"], rows, "No reports yet")
    body += "<p>Takedown flow: temporary hide within 48 hours, then verify, then permanent or restore.</p>"
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/reports")
    for r in reps:
        body += """<div class="card"><h3>Report %s</h3>
<form method="post" action="/admin/api/v2/reports/%s/action">%s
<label for="report-action-%s">Action</label><select id="report-action-%s" name="action">
<option value="temp_hide">Temp hide</option><option value="restore">Restore</option>
<option value="permanent">Permanent</option><option value="blocklist_note">Blocklist note</option>
<option value="reject">Reject</option><option value="request_info">Request info</option></select>
<label for="report-note-%s">Note</label><input id="report-note-%s" name="note">
<div class="stickybar"><button type="submit">Take report action</button></div></form></div>""" % (
            templates.esc(r["id"]), r["id"], hid, r["id"], r["id"], r["id"], r["id"])
    return templates.layout("Reports", body, active="reports")


def _page_broadcasts(self, user, sess, query):
    bcs = self.service.list_broadcasts(user)["items"]
    rows = [[b["id"], b["title"], templates.Raw(templates.badge(b["severity"])),
             templates.Raw(templates.badge(b["status"]))] for b in bcs]
    body = templates.table(["ID", "Title", "Severity", "Status"], rows, "No broadcasts yet")
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/broadcasts")
    body += """<div class="card"><h3>Create a broadcast</h3>
<form method="post" action="/admin/api/v2/broadcasts">%s
<label for="bc-title">Title</label><input id="bc-title" name="title" required>
<label for="bc-body">Body</label><textarea id="bc-body" name="body" required></textarea>
<label for="bc-severity">Severity</label><select id="bc-severity" name="severity">
<option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option></select>
<label for="bc-target">Target</label><select id="bc-target" name="target">
<option value="all">All</option><option value="free">Free</option><option value="vip">VIP</option>
<option value="region">Region</option><option value="version">Version</option></select>
<label for="bc-detail">Target detail</label><input id="bc-detail" name="target_detail">
<p>Region needs one of pakistan, india, asia, international; version needs one exact version name like 1.0.4; all, free and vip take no detail.</p>
<label for="bc-starts">Starts at</label><input id="bc-starts" name="starts_at" type="datetime-local">
<label for="bc-ends">Ends at (required to publish)</label><input id="bc-ends" name="ends_at" type="datetime-local">
<div class="stickybar"><button type="submit">Create broadcast</button></div></form></div>""" % hid
    for b in bcs:
        body += """<div class="card"><h3>%s</h3>
<form method="post" action="/admin/api/v2/broadcasts/%s/publish">%s
<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm publish</span></label>
<div class="stickybar"><button type="submit">Publish broadcast</button></div></form>
<form method="post" action="/admin/api/v2/broadcasts/%s/retract">%s
<label class="check"><input type="checkbox" name="confirm"> <span>Confirm retract</span></label>
<div class="stickybar"><button type="submit" class="danger">Retract broadcast</button></div></form></div>""" % (
            templates.esc(b["title"]), b["id"], hid, b["id"], hid)
    return templates.layout("Broadcasts", body, active="broadcasts")


def _page_live(self, user, sess, query):
    live = self.service.get_live(user)
    sched = self.service.list_scheduled(user)["items"]
    hist = self.service.list_config_history(user)["items"]
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/live")
    body = ""
    # ── What is live now ──
    if live["live"] is None:
        body += ('<div class="card"><h3>Live now</h3>'
                 '<p>Nothing has been published yet. The app is serving its built-in defaults.</p></div>')
    else:
        lv = live["live"]
        body += ('<div class="card"><h3>Live now — version %s</h3>'
                 '<p>Published %s by %s · %s enabled section(s).</p></div>') % (
            templates.esc(lv["config_version"]),
            templates.fmt_datetime(lv["published_at"]),
            templates.esc(lv.get("published_by_name") or "system"),
            templates.esc(lv["sections"]))
    changed = live["changed_keys"]
    if changed:
        body += ('<div class="card"><h3>Waiting to go out</h3>'
                 '<p>Draft version %s · %s enabled section(s) · these settings differ from live: %s.</p>'
                 '<form method="post" action="/admin/api/v2/remote-config/publish">%s'
                 '<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm publish</span></label>'
                 '<div class="stickybar"><button type="submit">Publish now</button></div></form></div>') % (
            templates.esc(live["draft"]["config_version"]),
            templates.esc(live["draft"]["sections"]),
            templates.esc(", ".join(changed)), hid)
    else:
        body += ('<div class="card"><h3>Waiting to go out</h3>'
                 '<p>Draft version %s matches live — nothing to publish.</p></div>') % (
            templates.esc(live["draft"]["config_version"]))
    # ── Draft settings (force-update / versions / brand / region) ──
    # These fields had an API (PUT remote-config) but no HTML form, so
    # the operator could never set them from the panel. They save as a
    # draft (no version bump); publish to go live. Only min_version_code
    # reaches the app today — the rest are served once the backend
    # remote-config carries them (backend batch).
    dc = live["draft"]["config"]

    def _dv(name):
        v = dc.get(name)
        return "" if v is None else str(v)

    def _dnum(name):
        v = dc.get(name)
        return "" if v is None else str(int(v))

    def _dflag(name):
        cur = 1 if dc.get(name) else 0
        return ('<select name="%s"><option value="0"%s>Off</option>'
                '<option value="1"%s>On</option></select>') % (
                    name, " selected" if cur == 0 else "",
                    " selected" if cur == 1 else "")
    body += ('<div class="card"><h3>Draft settings</h3>'
             '<p>App update, brand and region. Saves as a draft — publish to go live.</p>'
             '<form method="post" action="/admin/api/v2/remote-config">%s'
             '<label>Minimum version code</label><input name="min_version_code" type="number" value="%s">'
             '<label>Latest version code</label><input name="latest_version_code" type="number" value="%s">'
             '<label>Latest version name</label><input name="latest_version_name" value="%s">'
             '<label>Force update</label>%s'
             '<label>Force update message</label><input name="force_update_message" value="%s">'
             '<label>Maintenance message</label><input name="maintenance_message" value="%s">'
             '<label>Brand primary (#RRGGBB)</label><input name="brand_primary" value="%s">'
             '<label>Brand accent (#RRGGBB)</label><input name="brand_accent" value="%s">'
             '<label>Region order (comma list)</label><input name="region_order" value="%s">'
             '<label>Free quality cap</label><select name="free_quality_cap">'
             '<option value="480p"%s>480p</option><option value="720p"%s>720p</option></select>'
             '<label>Maintenance mode</label>%s'
             '<label>APK update URL</label><input name="apk_update_url" value="%s">'
             '<div class="stickybar"><button type="submit">Save draft</button></div></form></div>') % (
                 hid,
                 _dnum("min_version_code"), _dnum("latest_version_code"),
                 templates.esc(_dv("latest_version_name")),
                 _dflag("force_update"),
                 templates.esc(_dv("force_update_message")),
                 templates.esc(_dv("maintenance_message")),
                 templates.esc(_dv("brand_primary")),
                 templates.esc(_dv("brand_accent")),
                 templates.esc(_dv("region_order")),
                 " selected" if _dv("free_quality_cap") == "480p" else "",
                 " selected" if _dv("free_quality_cap") == "720p" else "",
                 _dflag("maintenance_mode"),
                 templates.esc(_dv("apk_update_url")))
    # ── Schedule a publish ──
    body += """<div class="card"><h3>Schedule a publish</h3>
<p>The draft as it stands at that moment goes out — keep editing until then.</p>
<form method="post" action="/admin/api/v2/remote-config/schedule">%s
<label for="sch-at">Publish at</label><input id="sch-at" name="scheduled_at" type="datetime-local" required>
<label for="sch-note">Note (optional)</label><input id="sch-note" name="note">
<div class="stickybar"><button type="submit">Schedule publish</button></div></form></div>""" % hid
    rows = [[s["id"], templates.fmt_datetime(s["scheduled_at"]),
             templates.Raw(templates.badge(s["status"])),
             templates.esc(s.get("note") or ""),
             templates.fmt_datetime(s.get("fired_at")) if s.get("fired_at") else "—"] for s in sched]
    body += templates.table(["ID", "Publish at", "Status", "Note", "Fired at"], rows, "No scheduled publishes")
    for s in sched:
        if s["status"] != "pending":
            continue
        body += """<div class="card"><h3>Schedule %s</h3>
<form method="post" action="/admin/api/v2/remote-config/schedule/%s/cancel">%s
<div class="stickybar"><button type="submit" class="danger">Cancel schedule</button></div></form></div>""" % (
            templates.esc(s["id"]), templates.esc(s["id"]), hid)
    # ── Change history ──
    rows = [[h["config_version"], templates.fmt_datetime(h["published_at"]),
             templates.esc(h.get("published_by_name") or "system")] for h in hist]
    body += templates.table(["Version", "Published", "By"], rows, "No publishes yet")
    for h in hist:
        if h["config_version"] == (live["live"]["config_version"] if live["live"] else None):
            continue
        body += """<div class="card"><h3>Version %s</h3>
<form method="post" action="/admin/api/v2/remote-config/rollback">%s
<input type="hidden" name="version" value="%s">
<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm rollback to this version</span></label>
<div class="stickybar"><button type="submit">Roll back to version %s</button></div></form></div>""" % (
            templates.esc(h["config_version"]), hid,
            templates.esc(h["config_version"]), templates.esc(h["config_version"]))
    return templates.layout("Live", body, active="live")


def _page_live_tv(self, user, sess, query):
    """Live TV channels: add / edit / delete / enable-disable.

    Reads live_tv_registry.json through the live store; the backend
    re-reads the registry per call, so a change takes effect on the
    next app refresh with no service restart. A disabled channel never
    plays (live_tv.py fail-closed). Adding or saving a channel probes
    its stream URL first; a dead stream refuses unless force is set.
    A duplicate name or stream URL is a warning, not a refusal."""
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/live-tv")
    try:
        res = self.service.list_live_tv(user)
        channels = res["channels"]
    except Exception as exc:
        body = ('<div class="card"><h3>Live TV</h3>'
                '<p>Live TV registry is not available: %s</p></div>') % templates.esc(str(exc))
        return templates.layout("Live TV", body, active="live-tv")
    enabled = sum(1 for c in channels if c["enabled"])
    rows = []
    for c in channels:
        rows.append([c["id"], c["name"], c["category"] or "—", c["country"] or "—",
                     c["source"] or "—",
                     templates.Raw(templates.badge("On" if c["enabled"] else "Off")),
                     c["disabled_reason"] or "—"])
    body = ('<div class="card"><h3>Live TV — %d of %d channels on</h3>'
            '<p>Toggle a channel to hide it from the app. The app reads the registry '
            'on every refresh, so the change is live immediately — no restart.</p></div>') % (
                enabled, len(channels))
    body += ('<div class="card"><h3>Add channel</h3>'
             '<p>The stream URL is checked before saving — a dead link refuses '
             'unless you tick force. A name or stream URL already in use shows a warning.</p>'
             '<form method="post" action="/admin/api/v2/live-tv">%s'
             '<label for="lt-add-name">Name</label>'
             '<input id="lt-add-name" name="name" required>'
             '<label for="lt-add-category">Category</label>'
             '<input id="lt-add-category" name="category">'
             '<label for="lt-add-country">Country</label>'
             '<input id="lt-add-country" name="country">'
             '<label for="lt-add-language">Language</label>'
             '<input id="lt-add-language" name="language">'
             '<label for="lt-add-stream">Stream URL</label>'
             '<input id="lt-add-stream" name="stream_url" required placeholder="https://.../playlist.m3u8">'
             '<label for="lt-add-logo">Logo URL</label>'
             '<input id="lt-add-logo" name="logo_url">'
             '<label for="lt-add-source">Source</label>'
             '<select id="lt-add-source" name="source">'
             '<option value="official" selected>official</option>'
             '<option value="aggregator">aggregator</option></select>'
             '<label for="lt-add-enabled">State</label>'
             '<select id="lt-add-enabled" name="enabled">'
             '<option value="1" selected>Enabled</option>'
             '<option value="0">Disabled</option></select>'
             '<label class="check"><input type="checkbox" name="force" value="1"> <span>Add even if the stream does not answer</span></label>'
             '<div class="stickybar"><button type="submit">Add channel</button></div>'
             '</form></div>') % hid
    body += templates.table(["ID", "Channel", "Category", "Country", "Source", "State", "Disabled reason"],
                            rows, "No channels in the registry")
    for c in channels:
        cid = templates.esc(c["id"])
        body += ('<div class="card"><h3>%s</h3>'
                 '<form method="post" action="/admin/api/v2/live-tv/%s">%s'
                 '<input type="hidden" name="enabled" value="%s">'
                 '<label for="lt-reason-%s">Reason (shown when disabling)</label>'
                 '<input id="lt-reason-%s" name="reason" value="%s">'
                 '<div class="stickybar"><button type="submit" class="%s">%s</button></div>'
                 '</form></div>') % (
                     templates.esc(c["name"]), cid, hid,
                     "0" if c["enabled"] else "1",
                     cid, cid, templates.esc(c["disabled_reason"] or ""),
                     "danger" if c["enabled"] else "",
                     "Disable channel" if c["enabled"] else "Enable channel")
        src = c.get("source") or "official"
        body += ('<div class="card"><h3>Edit %s</h3>'
                 '<form method="post" action="/admin/api/v2/live-tv/%s/edit">%s'
                 '<label for="lt-name-%s">Name</label>'
                 '<input id="lt-name-%s" name="name" value="%s" required>'
                 '<label for="lt-category-%s">Category</label>'
                 '<input id="lt-category-%s" name="category" value="%s">'
                 '<label for="lt-country-%s">Country</label>'
                 '<input id="lt-country-%s" name="country" value="%s">'
                 '<label for="lt-language-%s">Language</label>'
                 '<input id="lt-language-%s" name="language" value="%s">'
                 '<label for="lt-stream-%s">Stream URL</label>'
                 '<input id="lt-stream-%s" name="stream_url" value="%s" required>'
                 '<label for="lt-logo-%s">Logo URL</label>'
                 '<input id="lt-logo-%s" name="logo_url" value="%s">'
                 '<label for="lt-source-%s">Source</label>'
                 '<select id="lt-source-%s" name="source">'
                 '<option value="official"%s>official</option>'
                 '<option value="aggregator"%s>aggregator</option></select>'
                 '<label for="lt-enabled-%s">State</label>'
                 '<select id="lt-enabled-%s" name="enabled">'
                 '<option value="1"%s>Enabled</option>'
                 '<option value="0"%s>Disabled</option></select>'
                 '<label for="lt-disreason-%s">Disabled reason</label>'
                 '<input id="lt-disreason-%s" name="disabled_reason" value="%s">'
                 '<label class="check"><input type="checkbox" name="force" value="1"> <span>Save even if the stream does not answer</span></label>'
                 '<div class="stickybar"><button type="submit">Save changes</button></div>'
                 '</form>'
                 '<form method="post" action="/admin/api/v2/live-tv/%s/delete">%s'
                 '<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm delete %s</span></label>'
                 '<div class="stickybar"><button type="submit" class="danger">Delete channel</button></div>'
                 '</form></div>') % (
                     templates.esc(c["name"]), cid, hid,
                     cid, cid, templates.esc(c["name"]),
                     cid, cid, templates.esc(c["category"] or ""),
                     cid, cid, templates.esc(c["country"] or ""),
                     cid, cid, templates.esc(c["language"] or ""),
                     cid, cid, templates.esc(c["stream_url"] or ""),
                     cid, cid, templates.esc(c["logo_url"] or ""),
                     cid,
                     " selected" if src == "official" else "",
                     " selected" if src == "aggregator" else "",
                     cid,
                     " selected" if c["enabled"] else "",
                     " selected" if not c["enabled"] else "",
                     cid, cid, templates.esc(c["disabled_reason"] or ""),
                     cid, hid, templates.esc(c["name"]))
    return templates.layout("Live TV", body, active="live-tv")


def _page_domains(self, user, sess, query):
    doms = self.service.list_domains(user)["items"]
    rows = [[d["site_key"], d["active_domain"] or "—",
             templates.Raw(templates.badge(d["status"])),
             templates.fmt_datetime(d.get("last_checked_at")),
             d.get("last_redirect_to") or "—",
             d.get("last_failure_reason") or "—"] for d in doms]
    body = templates.table(["Site", "Active domain", "Status", "Last checked", "Redirected to", "Failure reason"], rows, "No domains in the registry yet")
    if self.service.live is not None and self.service.live.registry_path:
        body += "<p>Applies write domain_registry.json (a backup is taken before the first live write) and the resolver reads that file. Validate before apply; rollback re-validates the previous domain.</p>"
    else:
        body += "<p>Changing a domain is stored, not yet live until the resolver lookup gate lands. Validate before apply; rollback re-validates the previous domain.</p>"
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/domains")
    # Forms for every known site (registry rows first, then fleet sites
    # not yet in the registry), so a first domain can be added from
    # this page even when the registry starts empty.
    by_key = {d["site_key"]: d for d in doms}
    site_keys = [d["site_key"] for d in doms] + [s for s in FLEET_SITES if s not in by_key]
    for site_key in site_keys:
        d = by_key.get(site_key, {"site_key": site_key, "active_domain": None})
        key = templates.esc(site_key)
        cur = templates.esc(d["active_domain"] or "")
        body += """<div class="card"><h3>%s</h3>
<form method="post" action="/admin/api/v2/domains/%s/validate">%s
<label for="dom-validate-%s">Domain to validate (domain only, no scheme or path)</label>
<input id="dom-validate-%s" name="domain" value="%s" required>
<div class="stickybar"><button type="submit" class="secondary">Validate domain</button></div></form>
<form method="post" action="/admin/api/v2/domains/%s/apply">%s
<label for="dom-apply-%s">Domain to apply (must already be validated)</label>
<input id="dom-apply-%s" name="domain" value="%s" required>
<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm apply</span></label>
<div class="stickybar"><button type="submit">Apply domain</button></div></form>
<form method="post" action="/admin/api/v2/domains/%s/rollback">%s
<label class="check"><input type="checkbox" name="confirm" required> <span>Confirm rollback to previous domain</span></label>
<div class="stickybar"><button type="submit" class="secondary">Rollback domain</button></div></form></div>""" % (
            key, key, hid, key, key, cur, key, hid, key, key, cur, key, hid)
    return templates.layout("Domains", body, active="domains")


def _page_fleet(self, user, sess, query):
    fleet = self.service.list_fleet(user)["items"]
    rows = [[f["site_key"], templates.Raw(templates.badge(f["status"])), f["progress"],
             f.get("last_good_domain") or "—", f.get("failure_reason") or "—",
             # "Never ran" is the honest label for a crawler with no
             # status file and no audit row (8 of 18 live sites) — the
             # old page showed a bare date or nothing at all.
             templates.fmt_mixed_datetime(f.get("last_sync_at")) if f.get("ever_ran") else "Never ran"] for f in fleet]
    body = templates.table(["Crawler", "Status", "Progress", "Last-good domain", "Failure reason", "Last sync"],
                           rows, "No crawlers configured")
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/fleet")
    options = "".join('<option value="%s">%s</option>' % (templates.esc(f["site_key"]), templates.esc(f["site_key"]))
                      for f in fleet)
    body += """<div class="card"><h3>Run a crawler</h3>
<form method="post" action="/admin/api/v2/fleet/run">%s
<label for="fleet-crawler">Crawler</label><select id="fleet-crawler" name="crawler">%s</select>
<label for="fleet-mode">Mode</label><select id="fleet-mode" name="mode">
<option value="sync">sync</option><option value="crawl">crawl</option></select>
<label for="fleet-limit">Limit (10 to 1000)</label><input id="fleet-limit" name="limit" type="number" min="10" max="1000" value="25" required>
<div class="stickybar"><button type="submit">Run crawler</button></div></form>
<p>%s</p></div>""" % (hid, options, ("Runs execute the real crawler command and write the fleet audit in the catalog DB." if (self.service.live is not None and self.service.live.has_catalog) else "Queued runs only in this build; a run does not import live data here."))
    return templates.layout("Fleet", body, active="fleet")


def _page_requests(self, user, sess, query):
    """Movie requests (v1 /admin/requests, Session 78; D2.6).

    The queue the operator works oldest-first, the recent history, and
    the trigger that queues one bounded crawler run for one site. A
    trigger never closes the request — the operator marks it indexed
    when the title appears, or declined when it is not wanted.
    """
    data = self.service.list_requests(user)
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/requests")
    if not data.get("available"):
        body = ('<div class="card"><p>No live ledger is wired here, so there '
                "are no movie requests to show. Requests live in the "
                "user-state ledger.</p></div>")
        return templates.layout("Requests", body, active="requests")
    open_rows = data["open"]
    rows = []
    for r in open_rows:
        account = r["hint"] + ((" (%s)" % r["profile"]) if r.get("profile") else "")
        actions = (
            '<form method="post" action="/admin/api/v2/requests/%d/indexed" style="display:inline">%s'
            '<input type="hidden" name="confirm" value="1">'
            '<button type="submit">Indexed</button></form> '
            '<form method="post" action="/admin/api/v2/requests/%d/declined" style="display:inline">%s'
            '<input type="hidden" name="confirm" value="1">'
            '<button type="submit">Declined</button></form>'
            % (r["id"], hid, r["id"], hid))
        rows.append([r["id"], r["title"], r["notes"] or "—", account,
                     "%d coins" % r["balance"],
                     templates.fmt_datetime(r["created_at"]),
                     templates.Raw(actions)])
    body = "<h3>Open requests (%d)</h3>" % data["open_count"]
    body += templates.table(
        ["ID", "Title", "Notes", "Account", "Balance", "Requested", "Close"],
        rows, "No open requests.")
    recent_rows = [[r["id"], r["title"],
                    templates.Raw(templates.badge(r["status"])),
                    r["hint"], templates.fmt_datetime(r["created_at"])]
                   for r in data["recent"]]
    body += "<h3>Recent</h3>" + templates.table(
        ["ID", "Title", "Status", "Account", "Requested"],
        recent_rows, "No requests yet.")
    req_options = "".join(
        '<option value="%d">#%d %s</option>' % (
            r["id"], r["id"], templates.esc(r["title"])) for r in open_rows)
    crawler_options = "".join(
        '<option value="%s"%s>%s</option>' % (
            templates.esc(c["crawler_id"]),
            " selected" if c["crawler_id"] == "multimovies" else "",
            templates.esc(c["crawler_id"]))
        for c in data["crawlers"])
    body += """<div class="card"><h3>Trigger a crawler for a request</h3>
<form method="post" action="/admin/api/v2/requests/trigger">%s
<label for="req-id">Request</label><select id="req-id" name="request_id">%s</select>
<label for="req-crawler">Crawler</label><select id="req-crawler" name="crawler">%s</select>
<label for="req-mode">Mode</label><select id="req-mode" name="mode">
<option value="sync">sync</option><option value="crawl">crawl</option></select>
<label for="req-limit">Limit (10 to 1000)</label><input id="req-limit" name="limit" type="number" min="10" max="1000" value="25" required>
<div class="stickybar"><button type="submit">Trigger crawler</button></div></form>
<p>%s</p></div>""" % (hid, req_options, crawler_options, templates.esc(data["note"]))
    return templates.layout("Requests", body, active="requests")


def _page_analytics(self, user, sess, query):
    rows_data = self.service.get_analytics(user)["items"]
    rows = [[r["day"], r["catalog_works"],
             ("%s h" % r["projection_age_h"]) if r.get("projection_age_h") else "—",
             r["pending_payments"], r["open_reports"], r["failed_domains"]] for r in rows_data]
    body = templates.table(
        ["Day", "Catalog works", "Projection age", "Pending payments", "Open reports", "Failed domains"],
        rows, "No analytics yet. Compute a day first.")
    body += '<p><a class="btn secondary" href="/admin/api/v2/analytics/export">Download CSV</a> (daily aggregates only, no per-user rows)</p>' 
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/analytics")
    body += """<div class="card"><h3>Compute a day</h3>
<form method="post" action="/admin/api/v2/analytics/compute">%s
<label for="analytics-day">Day</label><input id="analytics-day" name="day" placeholder="YYYY-MM-DD" required>
<div class="stickybar"><button type="submit">Compute day</button></div></form></div>""" % hid
    return templates.layout("Analytics", body, active="analytics")


def _page_usage(self, user, sess, query):
    """Aggregates-only usage (Tracking A, Session 97).

    Mirrors v1 admin_panel.render_usage_page, card for card, from the
    same payload shape. Every value passes through templates.table's
    esc(), because a dimension label arrives from a client header — the
    shape check in usage_stats.clean_value is the first gate and
    escaping is the second. No number is coloured or phrased as a trend:
    the window is printed, the reader decides.
    """
    data = self.service.usage_summary(user)
    if not data.get("available"):
        body = ("<p>%s — nothing has been counted yet, and a page of zeros "
                "is not a measurement.</p>") % templates.esc(
                    str(data.get("detail") or "no_usage_data_yet"))
        return templates.layout("Usage", body, active="usage")

    def fmt(value):
        return "—" if value is None else value

    installs = data.get("installs", {})
    active = data.get("active_users", {})
    live = data.get("live_sessions", {})
    accounts_row = data.get("accounts", {})
    body = ('<p>Aggregates only — no per-device timeline, no IP, no name '
            'join. Window: %s days.</p>') % templates.esc(
                str(data.get("window_days")))
    body += "<h3>Devices</h3>" + templates.table(
        ["Measure", "Count"],
        [["Distinct installs", installs.get("distinct_devices")],
         ["New today", installs.get("new_today")],
         ["New this window", installs.get("new_this_window")],
         ["Live last 5 min", live.get("5m")],
         ["Live last 30 min", live.get("30m")],
         ["Live last 60 min", live.get("60m")],
         ["DAU", active.get("dau")],
         ["WAU", active.get("wau")],
         ["MAU", active.get("mau")]],
        "No installs counted yet")
    body += "<h3>Accounts</h3>" + templates.table(
        ["Measure", "Count"],
        [["Total", accounts_row.get("total")],
         ["VIP active", accounts_row.get("vip_active")],
         ["Revoked", accounts_row.get("revoked")]],
        "No accounts counted yet")
    retention = data.get("retention", {})
    body += "<h3>Retention (returned on or after D+n)</h3>" + templates.table(
        ["Cohort", "Returned / installs (rate)"],
        [[name, "%s / %s (%s)" % (fmt(row.get("returned")),
                                  fmt(row.get("cohort_installs")),
                                  fmt(row.get("rate")))]
         for name, row in sorted(retention.items())],
        "No retention cohorts yet")
    playback = data.get("playback", {})
    body += "<h3>Playback</h3>" + templates.table(
        ["Measure", "Value"],
        [["Server stream starts", fmt(playback.get("server_stream_starts"))],
         ["Client playback attempts",
          fmt(playback.get("client_playback_attempts"))],
         ["Buffer failures", fmt(playback.get("buffer_failures"))],
         ["Buffer failure rate", fmt(playback.get("buffer_failure_rate"))],
         ["Rate denominator", fmt(playback.get("rate_denominator"))],
         ["Starts per device", fmt(playback.get("starts_per_device"))]],
        "No playback counted yet")
    for title, key in (("Crash by device class", "crash_by_class"),
                       ("Error by device class", "error_by_class"),
                       ("Buffer failure by device class",
                        "buffer_failure_by_class")):
        body += "<h3>%s</h3>" % templates.esc(title) + templates.table(
            ["Device class", "Count"],
            sorted((data.get(key) or {}).items()),
            "Nothing counted in this window")
    installed = data.get("per_dimension_installed") or {}
    active_dims = data.get("per_dimension_active") or {}
    for dim in ("geo", "locale", "app_version", "device_class", "region",
                "audio_lang", "subtitle_lang"):
        pairs = []
        for value in sorted(set(installed.get(dim) or {})
                            | set(active_dims.get(dim) or {})):
            pairs.append([value, "%s installed / %s active"
                          % ((installed.get(dim) or {}).get(value, 0),
                             (active_dims.get(dim) or {}).get(value, 0))])
        body += "<h3>%s</h3>" % templates.esc(dim) + templates.table(
            ["Value", "Installed / active"], pairs,
            "Nothing counted for this dimension yet")
    payments_row = data.get("payments", {})
    pay_rows = [[tier, "%s × PKR %s" % (row.get("purchases"),
                                        row.get("amount_pkr"))]
                for tier, row in (payments_row.get("by_tier") or {}).items()]
    pay_rows.append(["Total PKR", payments_row.get("total_pkr")])
    pay_rows.append(["Pending queue", payments_row.get("pending")])
    body += "<h3>Pass purchases (approved)</h3>" + templates.table(
        ["Tier", "Purchases"], pay_rows, "No pass purchases yet")
    estimate = data.get("revenue_estimate", {})
    assumptions = estimate.get("assumptions", {})
    body += "<h3>Revenue estimate (assumptions printed)</h3>" + templates.table(
        ["Measure", "Value"],
        [["Ad USD in window", fmt(estimate.get("ad_usd_in_window"))],
         ["Ad USD per 1000 users",
          fmt(estimate.get("ad_usd_per_1000_users"))],
         ["Ad USD per 1000 users per day",
          fmt(estimate.get("ad_usd_per_1000_users_per_day"))],
         ["CTR", fmt(estimate.get("ctr"))],
         ["Rewarded per 1000 users",
          fmt(estimate.get("rewarded_per_1000_users"))],
         ["eCPM assumed (USD)", fmt(assumptions.get("ecpm_usd"))],
         ["PKR per USD assumed", fmt(assumptions.get("pkr_per_usd"))],
         ["Basis", fmt(assumptions.get("basis"))]],
        "No revenue estimate yet")
    pending = data.get("sources", {}).get("reported_by_client_pending") or []
    body += "<h3>Client-reported families still pending</h3><p>%s</p>" % (
        templates.esc(", ".join(pending))
        if pending else "None — every client family has reported in this window.")
    return templates.layout("Usage", body, active="usage")


def _page_tuning(self, user, sess, query):
    """Tuning controls (audit §Tuning): the 24 controls the API already
    had, now reachable from the UI. Every control shows its honest
    consumer label — what the app actually applies vs what is only
    stored. 0/1 flags are selects, never checkboxes: a form checkbox
    posts "on", which put_tuning's int() would refuse."""
    tuning = self.service.get_tuning(user)
    consumers = tuning.get("consumers", {})
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/tuning")

    def consumer_note(name):
        c = consumers.get(name, "")
        if "remote-config" in c or "panel feed" in c:
            return '<p class="muted">Applies: %s</p>' % templates.esc(c)
        return '<p class="muted">Stored only — %s</p>' % templates.esc(c)

    def num_field(name, label):
        lo, hi = TUNING_BOUNDS[name]
        return ('<label for="tun-%s">%s (%d to %d)</label>'
                '<input id="tun-%s" name="%s" type="number" min="%d" max="%d" value="%s" required>'
                '%s') % (name, label, lo, hi, name, name, lo, hi,
                         templates.esc(tuning.get(name)), consumer_note(name))

    def flag_field(name, label):
        cur = int(tuning.get(name) or 0)
        return ('<label for="tun-%s">%s</label>'
                '<select id="tun-%s" name="%s">'
                '<option value="0"%s>Off</option><option value="1"%s>On</option></select>%s') % (
                    name, label, name, name,
                    " selected" if cur == 0 else "",
                    " selected" if cur == 1 else "", consumer_note(name))

    def text_field(name, label, input_type="text", placeholder=""):
        return ('<label for="tun-%s">%s</label>'
                '<input id="tun-%s" name="%s" type="%s" value="%s" placeholder="%s">%s') % (
                    name, label, name, name, input_type,
                    templates.esc(tuning.get(name) or ""), placeholder,
                    consumer_note(name))

    def select_field(name, label, options):
        cur = str(tuning.get(name) or "")
        opts = "".join('<option value="%s"%s>%s</option>' % (
            templates.esc(v), " selected" if v == cur else "", templates.esc(v))
            for v in options)
        return ('<label for="tun-%s">%s</label>'
                '<select id="tun-%s" name="%s">%s</select>%s') % (
                    name, label, name, name, opts, consumer_note(name))

    body = ('<p>The disclaimer text and email, tabs, quality cap and '
            'theme live here. Controls labelled "Stored only" are saved '
            'but no backend code reads them yet — they are shown, not faked.</p>')
    body += ('<form method="post" action="/admin/api/v2/tuning">%s'
             '<div class="card"><h3>Disclaimer</h3>'
             '<label for="tun-disclaimer_text">Disclaimer text (shown once on first install, and in Settings)</label>'
             '<textarea id="tun-disclaimer_text" name="disclaimer_text" rows="4">%s</textarea>%s'
             '%s'
             '<label for="tun-disclaimer_version">Disclaimer version (raise to show it again)</label>'
             '<input id="tun-disclaimer_version" name="disclaimer_version" type="number" min="0" max="9999" value="%s" required>%s'
             '</div>'
             '<div class="card"><h3>App look</h3>%s%s%s%s%s%s%s%s</div>'
             '<div class="card"><h3>Resolver and import</h3>%s</div>'
             '<label for="tun-reason">Reason for this change</label>'
             '<input id="tun-reason" name="reason" placeholder="Why are you changing this?">'
             '<div class="stickybar"><button type="submit">Save tuning</button></div></form>') % (
        hid,
        templates.esc(tuning.get("disclaimer_text") or ""),
        consumer_note("disclaimer_text"),
        text_field("disclaimer_email", "Disclaimer email (takedown contact)"),
        templates.esc(tuning.get("disclaimer_version")),
        consumer_note("disclaimer_version"),
        select_field("free_quality_cap", "Free quality cap", ("480p", "720p")),
        select_field("theme_mode", "Theme mode", ("dark", "light", "system")),
        text_field("theme_accent", "Theme accent (#RRGGBB, empty for default)", "text", "#7C3AED"),
        flag_field("theme_dynamic_color", "Dynamic colour"),
        flag_field("theme_hero_autoplay", "Hero autoplay"),
        num_field("theme_hero_interval_s", "Hero interval (seconds)"),
        num_field("hero_max", "Hero cards"),
        text_field("tabs", "Tabs (comma list: home, search, my_list, settings, live_tv)"),
        "".join(num_field(k, k.replace("_", " ").title())
                for k in ("resolver_concurrency", "candidate_cap", "cache_ttl_h",
                          "warmup_count", "warmup_interval_h", "rate_limit_play_per_min",
                          "import_cap", "import_concurrency", "prefetch_queue",
                          "prefetch_concurrency", "section_cap", "home_sections_max",
                          "domain_check_interval_min")),
    )
    return templates.layout("Tuning", body, active="tuning")


def _page_monetization(self, user, sess, query):
    """Monetization (audit §Tuning/Money): the 22 controls the API
    already had — VIP prices, the six coin pass prices, payment rails,
    ad zones, feature flags — now reachable from the UI. Token inputs
    are password fields, never prefilled: blank means "keep the stored
    token" (put_monetization strips empty tokens before saving)."""
    mon = self.service.get_monetization(user)
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/monetization")

    def num_field(name, label, unit):
        return ('<label for="mon-%s">%s (%s, 0 to 10,000,000)</label>'
                '<input id="mon-%s" name="%s" type="number" min="0" max="10000000" value="%s" required>') % (
                    name, label, unit, name, name, templates.esc(mon.get(name)))

    def text_field(name, label, input_type="text"):
        return ('<label for="mon-%s">%s</label>'
                '<input id="mon-%s" name="%s" type="%s" value="%s">') % (
                    name, label, name, name, input_type,
                    templates.esc(mon.get(name) or ""))

    def flag_field(name, label):
        cur = int(mon.get(name) or 0)
        return ('<label for="mon-%s">%s</label>'
                '<select id="mon-%s" name="%s">'
                '<option value="0"%s>Off</option><option value="1"%s>On</option></select>') % (
                    name, label, name, name,
                    " selected" if cur == 0 else "",
                    " selected" if cur == 1 else "")

    coin_rows = "".join(
        "<tr><td>%s</td><td class=\"num\">%s coins</td></tr>" % (
            k.replace("coin_redeem_", "").replace("_", " ").title(),
            templates.esc(mon.get(k)))
        for k in COIN_REDEEM_FIELDS)
    body = ('<p>VIP and coin prices, payment rails, ad zones and feature '
            'flags. New prices affect new purchases only. Tokens are never '
            'shown here — leave a token blank to keep the stored one.</p>')
    body += ('<div class="card"><h3>Coin prices now</h3>'
             '<table><thead><tr><th>Pass</th><th>Price</th></tr></thead>'
             '<tbody>%s</tbody></table></div>') % coin_rows
    body += ('<form method="post" action="/admin/api/v2/monetization">%s'
             '<div class="card"><h3>VIP prices (PKR)</h3>%s%s</div>'
             '<div class="card"><h3>Coin prices</h3>%s</div>'
             '<div class="card"><h3>Payment rails (PKR)</h3>%s%s%s%s</div>'
             '<div class="card"><h3>Ad zones</h3>%s%s</div>'
             '<div class="card"><h3>Tokens (blank keeps the stored one)</h3>'
             '<p class="muted">ShrinkMe: %s. Droplink: %s.</p>%s%s</div>'
             '<div class="card"><h3>Flags</h3>%s%s%s%s%s</div>'
             '<label for="mon-apk_update_url">APK update URL</label>'
             '<input id="mon-apk_update_url" name="apk_update_url" type="text" value="%s">'
             '<div class="stickybar"><button type="submit">Save monetization</button></div></form>') % (
        hid,
        num_field("vip_monthly_pkr", "VIP monthly", "PKR"),
        num_field("vip_yearly_pkr", "VIP yearly", "PKR"),
        "".join(num_field(k, k.replace("coin_redeem_", "").replace("_", " ").title() + " pass", "coins")
                for k in COIN_REDEEM_FIELDS),
        text_field("pak_till_id", "Till ID"),
        text_field("pak_jazzcash_number", "JazzCash number"),
        text_field("pak_easypaisa_number", "EasyPaisa number"),
        text_field("pak_raast_id", "Raast ID"),
        text_field("monetag_zone_id", "Monetag zone ID"),
        text_field("adsterra_tag_id", "Adsterra tag ID"),
        "Configured" if mon.get("shrinkme_configured") else "Not set",
        "Configured" if mon.get("droplink_configured") else "Not set",
        text_field("shrinkme_api_token", "ShrinkMe API token", "password"),
        text_field("droplink_api_token", "Droplink API token", "password"),
        flag_field("maintenance_mode", "Maintenance mode"),
        flag_field("feature_downloads", "Downloads"),
        flag_field("feature_pure_cinema", "Pure cinema"),
        flag_field("feature_chromecast", "Chromecast"),
        flag_field("feature_quality_gate", "Quality gate"),
        templates.esc(mon.get("apk_update_url") or ""),
    )
    return templates.layout("Monetization", body, active="monetization")


def _page_data_health(self, user, sess, query):
    """Data health (audit §Missing views): what the server already
    knows, in one place — negative cache, review queue, projection
    truth, adult volume, coin ledger, fleet with last-sync ages."""
    data = self.service.data_health(user)
    if not data.get("available"):
        body = ("<p>No live catalog or ledger is wired here, so there is "
                "no data truth to show.</p>")
        return templates.layout("Data health", body, active="data-health")
    lh = data.get("link_health") or {}
    proj = data.get("projection") or {}
    drift = data.get("drift") or {}
    adult = data.get("adult") or {}
    coins = data.get("coins") or {}
    body = ""
    # Projection drift (Session 107): a stale projection is the one
    # operator-visible staleness signal — the v2 catalog silently hides
    # every post that arrived after the last build. Show it first, in
    # plain words, only when it fires; silence is the current signal.
    if drift.get("stale"):
        def _drift_value(key):
            value = drift.get(key)
            return "unknown" if value is None else value
        body += ("<div class='card'><h3>Projection drift %s</h3><p>%s</p>"
                 "<p>Ledger posts: %s. Projected posts: %s. Drift: %s.</p></div>") % (
            templates.badge("Warning"),
            templates.esc("; ".join(drift.get("reasons") or ["stale projection"])),
            templates.esc(_drift_value("ledger_posts")),
            templates.esc(_drift_value("projected_posts")),
            templates.esc(_drift_value("drift_posts")))
    # Negative cache.
    by_class = lh.get("by_failure_class") or {}
    class_rows = "".join(
        "<tr><td>%s</td><td class=\"num\">%s</td></tr>" % (
            templates.esc(k), templates.esc(v)) for k, v in sorted(by_class.items()))
    svc_rows = "".join(
        "<tr><td>%s</td><td class=\"num\">%s</td></tr>" % (
            templates.esc(r.get("service")), templates.esc(r.get("failed")))
        for r in (lh.get("by_service") or []))
    body += ("<div class='card'><h3>Failed links (negative cache)</h3>"
             "<p>%s links failed their last probe and are skipped for 12 hours.</p>"
             "%s%s</div>") % (
        templates.esc(lh.get("failed_total") or 0),
        ("<table><thead><tr><th>Failure class</th><th>Links</th></tr></thead><tbody>%s</tbody></table>" % class_rows) if class_rows else "",
        ("<table><thead><tr><th>Service</th><th>Failed</th></tr></thead><tbody>%s</tbody></table>" % svc_rows) if svc_rows else "")
    # Projection truth.
    body += ("<div class='card'><h3>Projection truth</h3><p>Revision: %s. Age: %s h. "
             "Link coverage: %s. Unchecked links: %s. Identity suspects: %s. "
             "Release duplicates: %s. ID-map rows: %s. "
             "Ledger posts: %s. Projected posts: %s.</p></div>") % (
        templates.esc(proj.get("rev")), templates.esc(proj.get("age_h")),
        templates.esc(proj.get("link_coverage")),
        templates.esc(proj.get("unchecked_links")),
        templates.esc(proj.get("identity_suspect")),
        templates.esc(proj.get("release_dups")),
        templates.esc(proj.get("id_map_rows")),
        templates.esc(drift.get("ledger_posts")),
        templates.esc(drift.get("projected_posts")
                      if drift.get("projected_posts") is not None else "unknown"))
    # Review queue.
    rq = data.get("review_queue") or []
    rq_rows = [[r.get("id"), r.get("kind"), r.get("work_id"),
                templates.fmt_datetime(r.get("raised_at"))] for r in rq]
    body += ("<div class='card'><h3>Review queue (%s items)</h3></div>") % (
        templates.esc(data.get("review_queue_count") or 0))
    body += templates.table(["ID", "Kind", "Work ID", "Raised"], rq_rows,
                            "Review queue is empty")
    # Adult volume.
    body += ("<div class='card'><h3>Adult content</h3><p>%s flagged posts, "
             "%s flagged works. Flagged rows are hidden from the app and "
             "visible only here, in the operator panel.</p></div>") % (
        templates.esc(adult.get("posts")), templates.esc(adult.get("works")))
    # Coins.
    if coins.get("available"):
        reason_rows = "".join(
            "<tr><td>%s</td><td class=\"num\">%s</td><td class=\"num\">%s</td></tr>" % (
                templates.esc(k), templates.esc(v.get("rows")),
                templates.esc(v.get("total")))
            for k, v in sorted((coins.get("by_reason") or {}).items()))
        body += ("<div class='card'><h3>Coin ledger</h3><p>%s rows. Granted: %s. "
                 "Spent: %s.</p>%s</div>") % (
            templates.esc(coins.get("rows")), templates.esc(coins.get("granted")),
            templates.esc(coins.get("spent")),
            ("<table><thead><tr><th>Reason</th><th>Rows</th><th>Total</th></tr></thead>"
             "<tbody>%s</tbody></table>" % reason_rows) if reason_rows else "")
    else:
        body += ("<div class='card'><h3>Coin ledger</h3><p>No coin ledger yet.</p></div>")
    # Fleet.
    fleet = data.get("fleet") or []
    fl_rows = [[f.get("site_key"), templates.Raw(templates.badge(f.get("status"))),
                f.get("progress"),
                templates.fmt_mixed_datetime(f.get("last_sync_at")) if f.get("ever_ran") else "Never ran",
                f.get("failure_reason") or "—"] for f in fleet]
    body += "<h3>Fleet</h3>" + templates.table(
        ["Crawler", "Status", "Progress", "Last sync", "Failure reason"],
        fl_rows, "No crawlers configured")
    return templates.layout("Data health", body, active="data-health")


def _page_settings(self, user, sess, query):
    s = self.service.panel_settings(user)
    audit = self.service.list_audit(user, limit=10)["items"]
    rows = [[a["id"], a["action"], a["target_type"], a["target_id"]] for a in audit]
    sys_extra = ""
    if s.get("disk_free_gb") is not None:
        sys_extra = " Disk free: %s GB of %s GB. Load (1m): %.2f." % (
            s.get("disk_free_gb"), s.get("disk_total_gb"), s.get("load_1m"))
    body = "<div class='card'><h3>Panel settings (display only)</h3><p>Session: %s hours absolute, %s hours idle. Certificate expiry: %s.%s</p><p>%s</p></div>" % (
        s["session_absolute_hours"], s["session_idle_hours"], s["cert_expiry"], sys_extra, s["https_note"])
    attempts = self.service.list_login_attempts(user, limit=10)["items"]
    arows = [[a["id"], a["username_attempted"],
              templates.Raw(templates.badge("Success" if a["success"] else "Failed")),
              templates.fmt_datetime(a["attempted_at"])] for a in attempts]
    body += "<h3>Recent login attempts</h3>" + templates.table(
        ["ID", "Username", "Result", "When"], arows, "No login attempts yet")
    hid = templates.form_hidden(sess.get("csrf_token"), "/admin/settings")
    body += """<div class="card"><h3>Change password</h3>
<form method="post" action="/admin/api/v2/auth/password-change">%s
<label for="pw-current">Current password</label><input id="pw-current" name="current" type="password" autocomplete="current-password" required>
<label for="pw-new">New password (12 to 128 characters)</label><input id="pw-new" name="new" type="password" autocomplete="new-password" required>
<div class="stickybar"><button type="submit">Change password</button></div></form>
<p>After a change you stay signed in with a new session.</p></div>
<div class="card"><h3>Sign out</h3>
<form method="post" action="/admin/logout">%s
<div class="stickybar"><button type="submit" class="secondary">Log out</button></div></form></div>""" % (hid, hid)
    body += "<h3>Recent audit</h3>" + templates.table(["ID", "Action", "Target", "Target ID"], rows, "No audit rows yet")
    return templates.layout("Settings", body, active="settings")


def _page_more(self, user, sess, query):
    links = [("/admin/sections", "Sections"), ("/admin/users", "Users"),
             ("/admin/money", "Money"), ("/admin/inbox", "Inbox"),
             ("/admin/requests", "Requests"), ("/admin/reports", "Reports"),
             ("/admin/broadcasts", "Broadcasts"), ("/admin/live", "Live"),
             ("/admin/domains", "Domains"), ("/admin/fleet", "Fleet"),
             ("/admin/analytics", "Analytics"), ("/admin/usage", "Usage"),
             ("/admin/tuning", "Tuning"), ("/admin/monetization", "Monetization"),
             ("/admin/data-health", "Data health"),
             ("/admin/settings", "Settings"),
             ("/admin/live-tv", "Live TV"),
             ("/admin/search", "Search")]
    body = "".join('<p><a class="btn secondary" href="%s">%s</a></p>' % (h, l) for h, l in links)
    return templates.layout("More", body, active="more")


def _page_search(self, user, sess, query):
    q = (query.get("q", [""])[0] if query.get("q") else "")
    res = self.service.global_search(user, q) if q else {"works": [], "users": [], "payments": [], "reports": [], "domains": [], "broadcasts": []}
    body = '<form method="get" action="/admin/search"><label for="q">Search works, users, payments, reports, domains, broadcasts</label><input id="q" name="q" value="%s"><div class="stickybar"><button type="submit">Search</button></div></form>' % templates.esc(q)
    for key in ("works", "users", "payments", "reports", "domains", "broadcasts"):
        items = res.get(key, [])
        body += "<h3>%s (%d)</h3>" % (key, len(items))
        body += templates.table(["Item"], [[str(i.get("title") or i.get("id") or i.get("site_key") or i.get("account_hint"))] for i in items],
                                "No %s found" % key)
    return templates.layout("Search", body, active="more")


for _name, _fn in list(locals().items()):
    if _name.startswith("_page_"):
        setattr(AdminApp, _name, _fn)


# -- Socket layer ---------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    app = None  # set by serve()

    def log_message(self, *args):
        pass  # never log request bodies, tokens, or ids

    def _run(self, method):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {k: v for k, v in self.headers.items()}
        status, ctype, data, cookie, location = self.app.handle(
            method, parsed.path, query, headers, body)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; script-src 'none'")
        if headers.get("X-Forwarded-Proto") == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._run("GET")

    def do_POST(self):
        self._run("POST")

    def do_PUT(self):
        self._run("PUT")

    def do_DELETE(self):
        self._run("DELETE")


def serve(service, host="127.0.0.1", port=8080, strict_host=False, domain_checker=None, stream_checker=None):
    app = AdminApp(service, strict_host=strict_host, domain_checker=domain_checker, stream_checker=stream_checker)
    Handler.app = app
    server = ThreadingHTTPServer((host, port), Handler)
    print("Admin Panel v2 (workspace build) on %s:%d — not a live deploy" % (host, port))
    server.serve_forever()
