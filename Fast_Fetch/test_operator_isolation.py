#!/usr/bin/env python3
"""Socket-level tests for the two-port policy — what nginx cannot undo.

Every other suite in this directory calls a route function and inspects the tuple
it returns. This one is deliberately different: it opens the real
`viewer.make_server` twice on loopback, speaks HTTP with `urllib`, and asks the
questions that only a socket can answer — is `/admin` *invisible* (not merely
denied) on the public port, does an account key survive a real round trip, does
the rate-limit triple reach a response built by someone else's code, and does any
body served publicly name a source site. A unit test passes when the routing in
`do_GET` is deleted, which is precisely the bug this file would catch.

Nothing here binds a non-loopback address, opens the production catalog, or
disturbs the live service.

    python3 -S Fast_Fetch/test_operator_isolation.py
"""
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts           # noqa: E402
import admin_panel        # noqa: E402
import api_v2             # noqa: E402
import catalog_v2         # noqa: E402
import fast_fetch         # noqa: E402
import redact             # noqa: E402
import viewer             # noqa: E402

TOKEN = "socket-level-operator-token"
SITE = "somecdn.site"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow: `redirect_request` returning None makes `urllib` raise the
    3xx as an `HTTPError`, so the caller sees the redirect as the server sent it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _without_request_id(raw: bytes) -> bytes:
    """A refusal body with its per-call id removed, so two answers can be compared
    for equality of *information*: same status, same code, same shape."""
    body = json.loads(raw.decode("utf-8", "replace") or "{}")
    body.pop("request_id", None)
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _serve(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


class TwoPortFixture(unittest.TestCase):
    """One catalog, one state DB, the real public and operator servers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db_path = root / "catalog.db"
        self.state_path = root / "user_state.db"
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
                        mock.patch.object(viewer, "DB_PATH", self.db_path),
                        mock.patch.dict("os.environ",
                                        {"RADD_USER_STATE_DB": str(self.state_path)})):
            patcher.start()
            self.addCleanup(patcher.stop)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self._ingest(title="Ordinary Film")
        self._ingest(title="Grown Up Film", is_18_plus=1)
        catalog_v2.project(self.conn, rev=1, verbose=False)
        self.conn.commit()

        self.public = viewer.make_server("127.0.0.1", 0, operator=False)
        self.operator = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (self.public, self.operator):
            _serve(server)
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)
        self.public_url = f"http://127.0.0.1:{self.public.server_address[1]}"
        self.operator_url = f"http://127.0.0.1:{self.operator.server_address[1]}"

    def _ingest(self, *, title="Ordinary Film", is_18_plus=0):
        data = {
            "url": f"https://{SITE}/movie/{title.lower().replace(' ', '-')}/",
            "slug": title.lower().replace(" ", "-"),
            "title": f"{title} (2024)",
            "clean_title": title,
            "year": 2024,
            "content_type": "movie",
            "poster_url": "https://cdn/poster.jpg",
            "genres": '["Action"]',
            "synopsis": f"{title} synopsis",
            "is_18_plus": is_18_plus,
            "source_site": SITE,
            "industry": "Bollywood",
            "country": "India",
            "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
            "releases": [{"release_title": f"{title} 1080p", "quality": "1080p",
                          "codec": "x264", "size": "1.5GB", "languages": '["Hindi"]',
                          "season": "", "episode": "", "intermediate_url": "",
                          "origin_url": "", "source_site": SITE,
                          "sources": [{"source_url": "https://cdn.example/one.mp4",
                                       "quality": "1080p", "status": "active"}]}],
        }
        fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
        self.conn.commit()

    # ---- the socket ------------------------------------------------------- #
    def fetch(self, base, path, method="GET", body=None, headers=None):
        """One request, answered exactly as sent: redirects are never followed.

        A 30x is the thing under test here, and an opener that followed it would
        report some other route's status as though this one had said it — and for a
        stream redirect, would take the test off the box to a third-party host.
        """
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            base + path, data=data, method=method,
            headers={"Content-Type": "application/json", **(headers or {})})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def public_fetch(self, path, **kw):
        return self.fetch(self.public_url, path, **kw)

    def operator_fetch(self, path, **kw):
        return self.fetch(self.operator_url, path, **kw)

    def work_ref(self, title="Ordinary Film"):
        """A handle minted the way the server mints them, for the POST bodies."""
        key = self.conn.execute(
            "SELECT work_key FROM cat_works WHERE title LIKE ?",
            (f"%{title.split()[0]}%",)).fetchone()[0]
        return redact.mint_text(key, viewer.signing_secret()), key


class AdminInvisibleOnThePublicPort(TwoPortFixture):
    def test_the_page_and_every_route_under_it_are_404_not_403(self):
        """The mandate is that a stranger cannot learn the panel exists. A 403 or
        a 401 would advertise it; `OPERATOR_ONLY_PREFIXES` answers the plain v1
        404 the rest of the server uses for a path it has never heard of."""
        for method, path in (("GET", "/admin"), ("GET", "/admin/api/projection"),
                             ("GET", "/admin/api/adult"),
                             ("GET", "/admin/api/monetization"),
                             ("GET", "/admin/api/fleet"),
                             ("POST", "/admin/api/links/1/evidence"),
                             ("POST", admin_panel.SAVE_MONETIZATION_PATH),
                             ("POST", admin_panel.RUN_SCRAPER_PATH)):
            status, _headers, raw = self.public_fetch(path, method=method,
                                                      body={} if method == "POST" else None)
            self.assertEqual(status, 404, f"{method} {path}: {raw[:200]!r}")
            self.assertNotIn(b"admin", raw.lower(), f"{method} {path} mentions the panel")

    def test_a_token_on_the_public_port_changes_nothing(self):
        """Presenting the right bearer does not unlock a public-port route: the
        port is the policy, and a header is something any client can forge."""
        status, _h, raw = self.public_fetch(
            "/admin", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 404)

    def test_the_prefix_rule_is_a_prefix_and_not_one_exact_path(self):
        for path in ("/admin/", "/admin/api/review", "/admin/api/catalog?n=5"):
            self.assertEqual(self.public_fetch(path)[0], 404, path)

    def test_a_path_that_merely_starts_like_admin_still_works_as_usual(self):
        """/administration is not /admin: `startswith` is applied to the whole
        segment, so a public route must not be swallowed by the rule."""
        status, _h, raw = self.public_fetch("/administration")
        self.assertEqual(status, 404)          # unknown route, but not via the gate
        self.assertNotIn(b"admin panel", raw.lower())


class AdminOnTheOperatorPort(TwoPortFixture):
    def test_the_page_answers_with_html_when_the_token_is_right(self):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            status, headers, raw = self.operator_fetch(
                "/admin", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 200)
        self.assertTrue(headers.get("Content-Type", "").startswith("text/html"))
        self.assertIn(b"<!DOCTYPE", raw[:200])

    def test_an_unset_token_denies_everything(self):
        """Fail closed: no configuration must never mean an open panel."""
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("RADD_ADMIN_TOKEN", None)
            status, headers, _raw = self.operator_fetch(
                "/admin", headers={"Authorization": "Bearer x"})
        self.assertEqual(status, 401)

    def test_a_missing_and_a_wrong_token_are_the_same_bytes(self):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            _s1, _h1, absent = self.operator_fetch("/admin")
            _s2, _h2, wrong = self.operator_fetch(
                "/admin", headers={"Authorization": "Bearer not-it"})
        self.assertEqual(absent, wrong)

    def test_the_screens_reach_the_projection_over_a_socket(self):
        """`screen_adult_proof` and friends were written as functions; this proves
        the route table maps `/admin/api/<name>` onto them at all."""
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            for name in ("projection", "adult", "link-health", "review",
                         "catalog", "fleet"):
                status, headers, raw = self.operator_fetch(
                    f"/admin/api/{name}",
                    headers={"Authorization": f"Bearer {TOKEN}"})
                self.assertEqual(status, 200, f"{name}: {raw[:200]!r}")
                self.assertTrue(headers.get("Content-Type", "").startswith(
                    "application/json"), name)
                self.assertTrue(json.loads(raw)["available"], name)

    def test_the_scraper_action_reads_its_body_and_refuses_an_unknown_handle(self):
        """The mount reads a body only for the actions that declare one. An
        unknown handle must be a 400 before any child process is imagined."""
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            status, headers, raw = self.operator_fetch(
                admin_panel.RUN_SCRAPER_PATH, method="POST",
                body={"crawler": "crawler-99", "mode": "sync"},
                headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 400, raw[:200])
        self.assertTrue(headers.get("Content-Type", "").startswith(
            "application/problem+json"), headers)
        self.assertEqual(json.loads(raw)["code"], "invalid_params")

    def test_the_one_write_action_works_over_a_socket(self):
        link_id = self.conn.execute("SELECT id FROM cat_links LIMIT 1").fetchone()[0]
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            status, _h, raw = self.operator_fetch(
                f"/admin/api/links/{link_id}/evidence", method="POST", body={},
                headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 200, raw[:200])
        self.assertTrue(json.loads(raw)["ok"])


class EveryRouteOnTheOperatorPortIsGated(TwoPortFixture):
    """The defect the owner measured at 05:47 and nobody fixed: on `127.0.0.1:8081`
    the dashboard at `/` was served to whoever reached the socket, and
    `/api/v1/stats` and `/api/v1/rules` answered 200 to a bogus bearer token,
    because `RADD_ADMIN_TOKEN` was checked only by `admin_panel._gate` — which
    guards `/admin` and nothing else. Loopback was being read as a credential.

    These are the assertions that make closing it permanent: every route on this
    port refuses a missing credential and a nonsense one with the same 401, the
    real token serves them, and the public port is untouched by any of it.
    """

    GATED = ("/", "/client", "/api/data", "/api/v1/rules", "/api/v1/stats", "/admin")

    def test_no_credential_is_refused_on_every_route_not_just_on_admin(self):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            for path in self.GATED:
                status, _headers, raw = self.operator_fetch(path)
                self.assertEqual(status, 401, f"{path} served {status} to nobody: "
                                               f"{raw[:160]!r}")
                self.assertNotIn(b"<!DOCTYPE", raw, f"{path} leaked the dashboard")
                self.assertNotIn(b"vegamovies", raw, f"{path} leaked provenance")

    def test_a_bogus_token_is_refused_on_every_route(self):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            for path in self.GATED:
                status, _headers, raw = self.operator_fetch(
                    path, headers={"Authorization": "Bearer definitely-not-it"})
                self.assertEqual(status, 401, f"{path} accepted a forged token")

    def test_a_refusal_without_and_with_a_wrong_token_says_the_same_thing(self):
        """A gate that explains itself to a guesser is an oracle; one that answers
        identically tells the prober nothing about which routes exist here."""
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            for path in self.GATED:
                _s1, _h1, absent = self.operator_fetch(path)
                _s2, _h2, wrong = self.operator_fetch(
                    path, headers={"Authorization": "Bearer nope"})
                self.assertEqual(_without_request_id(absent),
                                 _without_request_id(wrong), path)

    def test_the_real_token_serves_the_routes_it_used_to_hand_out_freely(self):
        """Closing the hole must not close the panel: `/` is how the operator sees
        the badges, and it still works when they prove who they are."""
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            for path in self.GATED:
                status, _headers, raw = self.operator_fetch(
                    path, headers={"Authorization": f"Bearer {TOKEN}"})
                self.assertEqual(status, 200, f"{path} → {status} {raw[:160]!r}")

    def test_an_unset_token_failscloses_the_whole_port(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("RADD_ADMIN_TOKEN", None)
            for path in self.GATED:
                status, _headers, _raw = self.operator_fetch(
                    path, headers={"Authorization": "Bearer x"})
                self.assertEqual(status, 401, path)

    def test_the_public_port_still_answers_without_any_credential(self):
        """The gate is a property of the operator instance, not of the handler: a
        phone that has never heard of `RADD_ADMIN_TOKEN` must not start seeing 401."""
        status, _headers, raw = self.public_fetch("/")
        self.assertEqual(status, 200, raw[:160])
        status, _headers, raw = self.public_fetch("/api/v1/stats")
        self.assertEqual(status, 200, raw[:160])


class SignInOverTheWire(TwoPortFixture):
    """Username and password, asked of a real socket: what a browser actually does.

    `OperatorLogin` in `test_admin_panel.py` already covers the credential as a
    function. This class is the part only a socket can answer — that the form is
    reachable before any credential exists, that the session it mints then opens the
    dashboard the bearer token opens, that the door being open did not reopen the
    token-free `/`, and that the two independent brakes (per-name lockout, per-address
    bucket) both bite over the wire.

    A deliberate limitation is asserted rather than hidden: this session is a stateless
    signed value, so signing out deletes the browser's copy and cannot invalidate a
    copy somebody kept. See `test_logout_deletes_the_cookie_and_cannot_revoke_a_kept_one`.
    """

    NAME = "rehan"
    PASSWORD = "socket-sign-in-password"
    SESSION_KEY = "socket-session-key"

    def setUp(self):
        super().setUp()
        admin_panel.reset_login_lockouts()
        self.addCleanup(admin_panel.reset_login_lockouts)
        # Both brakes are process-global and every request here comes from one
        # loopback address, so a budget left over from the previous test would decide
        # the next assertion. Each test gets a fresh limiter, and the real one comes
        # back on cleanup.
        fresh = mock.patch.object(redact, "limiter", redact.RateLimiter())
        fresh.start()
        self.addCleanup(fresh.stop)
        spec = mock.patch.dict("os.environ", {
            "RADD_ADMIN_TOKEN": TOKEN,
            admin_panel.PASSWORD_HASH_ENV: admin_panel.mint_password_hash(
                self.PASSWORD, kdf="pbkdf2-sha256", rounds=1_000),
            admin_panel.ADMIN_USERNAME_ENV: self.NAME,
            admin_panel.SESSION_SECRET_ENV: self.SESSION_KEY,
            admin_panel.PLAINTEXT_PASSWORD_ENV: "",
        })
        spec.start()
        self.addCleanup(spec.stop)

    def post_form(self, path, form, headers=None):
        """A real `<form method="post">` submission: urlencoded, not JSON.

        Redirects are NOT followed, and that is load-bearing: a successful sign-in
        is a 303 with the session cookie on it, and an opener that followed it would
        report the landing route's 401 as though the credential had failed. The
        redirect itself is the thing under test.
        """
        body = urllib.parse.urlencode(form).encode("utf-8")
        request = urllib.request.Request(
            self.operator_url + path, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     **(headers or {})})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def signed_in_cookie(self):
        status, headers, raw = self.post_form(
            admin_panel.LOGIN_PATH, {"username": self.NAME,
                                     "password": self.PASSWORD})
        self.assertEqual(status, 303, raw[:200])
        value = admin_panel.cookie_value(headers.get("Set-Cookie", ""),
                                         admin_panel.OPERATOR_COOKIE)
        self.assertTrue(value, headers)
        return value

    def test_get_on_the_login_path_is_the_form_and_spends_no_sign_in_budget(self):
        limit = redact.BUCKET_LIMITS["auth"][0]
        for _ in range(3):
            status, headers, raw = self.operator_fetch(admin_panel.LOGIN_PATH)
            self.assertEqual(status, 200, raw[:200])
            self.assertIn(b'type="password"', raw)
            self.assertIn("no-store", headers.get("Cache-Control", ""))
            self.assertNotIn(b"Ordinary Film", raw, "the door now shows the room")
        self.assertEqual(limit, redact.limiter.peek("auth", "127.0.0.1")["remaining"],
                         "a page view was charged as an attempt, so reloading the "
                         "form locks a human out of their own panel")

    def test_the_operator_login_path_serves_the_same_form_as_the_admin_one(self):
        for path in (admin_panel.LOGIN_PATH, admin_panel.OPERATOR_LOGIN_PATH):
            status, _headers, raw = self.operator_fetch(path)
            self.assertEqual(status, 200, (path, raw[:160]))
            self.assertIn(f'action="{path}"'.encode(), raw)

    def test_a_get_on_the_logout_path_is_405_and_signs_nobody_out(self):
        """A prefetcher, a link scanner or an image loader follows GETs nobody typed.
        A logout it can reach is a denial of service against the one person allowed
        here, so sign-out is POST and nothing else."""
        value = self.signed_in_cookie()
        cookie = {admin_panel.OPERATOR_COOKIE: value}
        status, headers, _raw = self.operator_fetch(
            admin_panel.LOGOUT_PATH, headers={"Cookie": f"{admin_panel.OPERATOR_COOKIE}={value}"})
        self.assertEqual(status, 405, headers)
        self.assertEqual("POST", headers.get("Allow"))
        self.assertEqual(200, self.operator_fetch("/", headers={
            "Cookie": f"{admin_panel.OPERATOR_COOKIE}={value}"})[0],
            "the refused GET signed the operator out anyway")

    def test_the_session_the_form_mints_opens_the_dashboard_a_stranger_cannot_see(self):
        value = self.signed_in_cookie()
        header = f"{admin_panel.OPERATOR_COOKIE}={value}"
        status, headers, raw = self.operator_fetch("/", headers={"Cookie": header})
        self.assertEqual(status, 200, raw[:200])
        self.assertIn(b"<!DOCTYPE", raw[:300])
        # A caller that already holds a valid session is not handed a second cookie.
        # Re-minting per response would extend the TTL on every page view and turn an
        # eight-hour session into one that never ends.
        self.assertNotIn(admin_panel.OPERATOR_COOKIE, headers.get("Set-Cookie", ""),
                         "a proven bearer/session should not re-mint on every request")
        # A bearer-only caller DOES get one, because the dashboard's own `/api/data`
        # fetch sends no `Authorization` header — that cookie is why the panel works.
        bearer_status, bearer_headers, _raw = self.operator_fetch(
            "/", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(200, bearer_status)
        self.assertIn(admin_panel.OPERATOR_COOKIE, bearer_headers.get("Set-Cookie", ""),
                      "the machine credential hands out no session, so the panel breaks")
        self.assertEqual(401, self.operator_fetch("/")[0])
        self.assertEqual(401, self.operator_fetch(
            "/", headers={"Cookie": f"{admin_panel.OPERATOR_COOKIE}=9999999999.deadbeef"})[0])

    def test_a_token_in_the_url_no_longer_opens_anything(self):
        """The credential left the URL for good: browser history, the `Referer` of
        every asset the page pulls, and the nginx access log all outlive a session,
        and this box's log is world-readable to the `adm` group."""
        for path in ("/", "/admin", "/api/data", "/api/v1/stats"):
            status, _headers, raw = self.operator_fetch(f"{path}?token={TOKEN}")
            self.assertEqual(status, 401, (path, raw[:160]))

    def test_five_bad_passwords_lock_the_name_and_the_answer_says_locked_not_wrong(self):
        for index in range(admin_panel.LOGIN_FAIL_LIMIT):
            status, _headers, raw = self.post_form(
                admin_panel.LOGIN_PATH, {"username": self.NAME,
                                         "password": f"nope-{index}"})
            self.assertEqual(status, 401, (index, raw[:160]))
        status, headers, raw = self.post_form(
            admin_panel.LOGIN_PATH, {"username": self.NAME, "password": "one more"})
        self.assertEqual(status, 429, raw[:160])
        self.assertIn(b"Too many failed attempts", raw)
        self.assertIn("no-store", headers.get("Cache-Control", ""))

    def test_the_address_bucket_refuses_the_eleventh_attempt_before_the_body_is_read(self):
        """Two independent brakes. The lockout is per username, so a caller cycling
        through names walks straight past it; the bucket is per address and stops the
        one who never authenticates at all — including the memory-hard derive."""
        limit = redact.BUCKET_LIMITS["auth"][0]
        for _ in range(limit):
            admin_panel.reset_login_lockouts()
            status, headers, _raw = self.post_form(
                admin_panel.LOGIN_PATH, {"username": self.NAME, "password": "wrong"})
            self.assertEqual(status, 401, status)
            self.assertIn("RateLimit-Limit", headers, headers)
            self.assertIn("RateLimit-Remaining", headers)
        admin_panel.reset_login_lockouts()
        status, headers, raw = self.post_form(
            admin_panel.LOGIN_PATH, {"username": self.NAME, "password": self.PASSWORD})
        self.assertEqual(status, 429, raw[:200])
        self.assertIn(b"sign-in attempts from this address", raw)
        self.assertGreater(int(headers.get("Retry-After") or 0), 0, headers)

    def test_a_json_login_body_is_refused_because_the_form_is_urlencoded(self):
        """Pinned, not accidental: `parse_form_body` reads a urlencoded body, so JSON
        keys are unknown keys and `_LOGIN_BODY_KEYS` refuses them. A browser posts the
        form; a machine uses the bearer header. Nothing here accepts both shapes."""
        status, _headers, raw = self.operator_fetch(
            admin_panel.LOGIN_PATH, method="POST",
            body={"username": self.NAME, "password": self.PASSWORD})
        self.assertEqual(status, 400, raw[:200])

    def test_logout_deletes_the_cookie_and_cannot_revoke_a_kept_one(self):
        """The honest shape of a stateless session. Signing out answers 303 with an
        expired cookie, which is what a browser needs; it cannot reach into a copy
        somebody kept. What bounds that is the 8-hour TTL, `HttpOnly`, `SameSite=Strict`
        and the fact that changing any configured secret rotates every session — there
        is no session table to trust, and this file says so rather than testing a
        revocation that does not exist."""
        value = self.signed_in_cookie()
        status, headers, raw = self.operator_fetch(
            admin_panel.LOGOUT_PATH, method="POST", body={},
            headers={"Cookie": f"{admin_panel.OPERATOR_COOKIE}={value}"})
        self.assertEqual(status, 303, raw[:200])
        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn("Max-Age=0", set_cookie)
        self.assertTrue(set_cookie.endswith(admin_panel.OPERATOR_COOKIE_ATTRS))
        self.assertEqual(admin_panel.LOGIN_PATH, headers.get("Location"))
        self.assertEqual(200, self.operator_fetch("/", headers={
            "Cookie": f"{admin_panel.OPERATOR_COOKIE}={value}"})[0],
            "a documented limitation just changed shape: the kept value still works")

    def test_the_login_surface_is_invisible_on_the_public_port(self):
        for method in ("GET", "POST"):
            for path in (admin_panel.LOGIN_PATH, admin_panel.OPERATOR_LOGIN_PATH,
                         admin_panel.LOGOUT_PATH, admin_panel.OPERATOR_LOGOUT_PATH):
                status, _headers, raw = self.public_fetch(path, method=method,
                                                          body={} if method == "POST" else None)
                self.assertEqual(status, 404, (method, path, raw[:160]))
                self.assertNotIn(b"password", raw.lower(), (method, path))

    def test_a_proxy_marker_on_the_operator_port_is_404_rather_than_a_form(self):
        """Measured 2026-10-31: the live nginx had `location /operator/ { proxy_pass
        http://127.0.0.1:8081/; }`, which would make a login box reachable from the
        internet. The owner's fix is to delete that block; this is the code-side wall
        that keeps the sentence true until it is, and the door is refused like the
        room — not found, so a scanner learns nothing."""
        for marker in ("X-Forwarded-For", "X-Real-IP", "X-Forwarded-Proto"):
            for path in (admin_panel.LOGIN_PATH, admin_panel.LOGOUT_PATH, "/"):
                status, _headers, raw = self.operator_fetch(
                    path, headers={marker: "203.0.113.7"})
                self.assertEqual(status, 404, (marker, path, raw[:160]))
                self.assertNotIn(b'type="password"', raw)
            # The opt-out is real, and it is the operator's choice, not ours.
            with mock.patch.dict("os.environ", {"RADD_TRUST_EDGE_PROXY": "1"}):
                self.assertEqual(200, self.operator_fetch(
                    admin_panel.LOGIN_PATH,
                    headers={marker: "203.0.113.7"})[0])

    def test_a_malformed_id_answers_400_and_the_connection_is_not_dropped(self):
        """The class of bug `/api/m3u` was fixed for on trunk: a bare `int()` on a
        query value raised out of `do_GET`, and a handler that raises mid-request
        closes the socket with no status and no body, which looks to the operator
        exactly like the server having died. `?id=abc` is the caller's error, so it is
        answered as one. Only malformed ids are sent: a well-formed one would probe
        upstreams, and nothing here reaches the network."""
        for path in ("/api/health-check?id=abc", "/api/heal?id=abc", "/api/m3u?id=abc",
                     "/api/health-check?id=1%2C2", "/api/heal?id="):
            try:
                status, _headers, raw = self.operator_fetch(
                    path, headers={"Authorization": f"Bearer {TOKEN}"})
            except (http.client.RemoteDisconnected, ConnectionResetError,
                    urllib.error.URLError) as dropped:
                self.fail(f"{path} dropped the connection instead of answering: "
                          f"{type(dropped).__name__}: {dropped}")
            self.assertEqual(status, 400, (path, raw[:200]))
            self.assertEqual({"error": "Invalid post ID"}, json.loads(raw), path)

    def test_a_missing_post_heal_answers_404_not_success_with_an_error(self):
        """The shape `/api/heal` used to answer for a post that does not exist:
        `{"success": true, "error": "Post not found"}` — a 200 that contradicts
        itself. A well-formed id for a post that is not in the catalog is the
        caller's error, so it is answered as one. The healer returns before it
        touches any upstream, so this reaches no network."""
        status, _headers, raw = self.operator_fetch(
            "/api/heal?id=999999", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 404, raw[:200])
        self.assertEqual({"success": False, "error": "Post not found"},
                         json.loads(raw))


class AccountRoundTrip(TwoPortFixture):
    def test_a_key_is_issued_once_and_the_favorite_round_trips(self):
        status, headers, raw = self.public_fetch("/api/v2/account", method="POST",
                                                 body={})
        self.assertEqual(status, 201, raw[:200])
        account = json.loads(raw)["account"]
        key = account["sync_key"]
        self.assertGreaterEqual(len(key), accounts.MIN_SYNC_KEY_CHARS)
        ref, work_key = self.work_ref()

        status, _h, raw = self.public_fetch("/api/v2/account/favorites", method="POST",
                                            body={"work_ref": ref},
                                            headers={"Authorization": f"Bearer {key}"})
        self.assertEqual(status, 201, raw[:200])
        self.assertEqual(json.loads(raw)["favorite"][accounts.PUBLIC_REF_KEY], ref)

        status, _h, raw = self.public_fetch("/api/v2/account/favorites",
                                            headers={"Authorization": f"Bearer {key}"})
        self.assertEqual(status, 200, raw[:200])
        blob = raw.decode()
        self.assertIn(ref, blob)
        self.assertNotIn("work_key", blob, "the ledger column name reached the wire")
        self.assertNotIn(work_key, blob, "a raw work key reached the wire")
        self.assertNotIn(SITE, blob.lower(), "a source site reached the wire")

    def test_creation_is_idempotent_and_never_shows_the_key_twice(self):
        first, _h, raw = self.public_fetch("/api/v2/account", method="POST", body={})
        shown = json.loads(raw)["account"]["sync_key"]
        status, _h, raw = self.public_fetch("/api/v2/account", method="POST",
                                            body={"sync_key": shown})
        self.assertEqual(status, 200, raw[:200])
        self.assertIs(json.loads(raw)["account"]["created"], False)
        self.assertNotIn("sync_key", json.loads(raw)["account"])

    def test_an_unminted_ref_is_a_400_that_does_not_quote_the_input(self):
        _s, _h, raw = self.public_fetch("/api/v2/account", method="POST", body={})
        key = json.loads(raw)["account"]["sync_key"]
        forged = "not-a-handle-we-minted-99999"
        status, headers, raw = self.public_fetch(
            "/api/v2/account/favorites", method="POST", body={"work_ref": forged},
            headers={"Authorization": f"Bearer {key}"})
        self.assertEqual(status, 400)
        self.assertTrue(headers.get("Content-Type", "").startswith(
            "application/problem+json"), headers)
        self.assertNotIn(forged, raw.decode())

    def test_no_key_is_the_same_answer_as_a_key_nobody_issued(self):
        """One oracle for both cases, or the endpoint becomes a key checker."""
        anonymous, _h, raw_a = self.public_fetch("/api/v2/account/favorites")
        stranger = "K" * 43
        denied, _h, raw_b = self.public_fetch(
            "/api/v2/account/favorites", headers={"Authorization": f"Bearer {stranger}"})
        self.assertEqual(anonymous, denied)
        self.assertEqual(_without_request_id(raw_a), _without_request_id(raw_b))

    def test_the_rate_limit_triple_reaches_an_answer_built_elsewhere(self):
        """`send_triple` exists so the bucket's headers survive the last hop; if it
        dropped them the §16.5 contract would be silently broken for these routes."""
        _s, headers, _raw = self.public_fetch("/api/v2/account", method="POST", body={})
        for name in ("RateLimit-Limit", "RateLimit-Remaining", "RateLimit-Reset"):
            self.assertIn(name, headers, headers)

    def test_the_account_routes_get_a_bucket_of_their_own(self):
        """`self` is unused in `_bucket_for`, so the mapping is checkable without a
        handler — and `account` must win before the generic v2 `browse` answer."""
        self.assertEqual(viewer.DashboardHandler._bucket_for(
            None, "/api/v2/account"), "account")
        self.assertEqual(viewer.DashboardHandler._bucket_for(
            None, "/api/v2/account/favorites", "POST"), "account")
        self.assertEqual(viewer.DashboardHandler._bucket_for(None, "/api/v2/works"),
                         viewer.DashboardHandler._bucket_for(None, "/posts"))

    def test_a_body_over_the_server_ceiling_is_refused_not_buffered(self):
        """/api/v2/account* reads through `api_v2.read_body`, so an oversized POST
        is a refusal with a bounded read, not a memory problem on a 1 CPU box."""
        status, _h, raw = self.public_fetch(
            "/api/v2/account", method="POST",
            body={"pad": "x" * (api_v2.MAX_BODY_BYTES + 4096)})
        self.assertEqual(status, 400, raw[:200])
        self.assertLess(len(raw), 4096, "the refusal echoed the body back")


class NothingPublicCarriesProvenance(TwoPortFixture):
    def test_every_public_answer_survives_the_sentinel_scan(self):
        """Not one needle — from the site table or the deny-list — may appear in a
        public body, including the new account routes."""
        needles = set(redact.needles()) | {SITE}
        _s, _h, raw = self.public_fetch("/api/v2/account", method="POST", body={})
        key = json.loads(raw)["account"]["sync_key"]
        ref, _work_key = self.work_ref()
        self.public_fetch("/api/v2/account/favorites", method="POST",
                          body={"work_ref": ref},
                          headers={"Authorization": f"Bearer {key}"})
        seen = []
        for path in ("/api/v2/manifest", "/api/v2/works", "/api/v2/account",
                     "/api/v2/account/favorites", "/api/v1/app/remote-config",
                     "/posts", "/client"):
            try:
                status, _h, raw = self.public_fetch(
                    path, headers={"Authorization": f"Bearer {key}"})
            except OSError as error:
                self.fail(f"{path} did not answer: {error}")
            text = raw.decode("utf-8", "replace")
            for needle in needles:
                if needle and needle in text.lower():
                    seen.append((path, needle))
            self.assertLess(status, 500, f"{path} → {status}")
        self.assertEqual(seen, [], f"provenance reached the public wire: {seen}")


class RemoteConfigOverTheWire(TwoPortFixture):
    """The monetization row, saved through the admin socket and read through the
    public one. A unit call cannot show that `do_POST` reads the body it is handed
    and that `do_GET` answers at all, which is what this is for."""

    PATH = "/api/v1/app/remote-config"
    SECRET = "shrinkme-live-api-token-445566"

    def save(self, body):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            return self.operator_fetch(admin_panel.SAVE_MONETIZATION_PATH,
                                       method="POST", body=body,
                                       headers={"Authorization": f"Bearer {TOKEN}"})

    def test_the_settings_save_through_the_real_admin_socket(self):
        status, _h, raw = self.save({"pak_till_id": "123456",
                                     "vip_monthly_pkr": 200,
                                     "shrinkme_api_token": self.SECRET})
        self.assertEqual(status, 200, raw[:200])
        self.assertIn("pak_till_id", json.loads(raw)["saved"])

    def test_the_public_port_serves_the_payment_screen(self):
        self.save({"pak_till_id": "123456", "pak_raast_id": "03001234567",
                   "vip_yearly_pkr": 1500, "monetag_zone_id": "10293847"})
        status, headers, raw = self.public_fetch(self.PATH)
        self.assertEqual(status, 200, raw[:200])
        self.assertTrue(headers.get("Content-Type", "").startswith("application/json"))
        data = json.loads(raw)
        self.assertEqual(data["payments"]["jazzcash"]["till_id"], "123456")
        self.assertEqual(data["payments"]["raast"]["instant_id"], "03001234567")
        self.assertEqual(data["vip"]["yearly_pkr"], 1500)
        self.assertEqual(data["ads"]["monetag_rewarded_zone_id"], "10293847")

    def test_neither_port_ever_hands_out_a_shortener_token(self):
        """Both answers go out over plain HTTP to a box that has no TLS. A token
        in either is the operator's payout account, usable by whoever reads it."""
        self.save({"shrinkme_api_token": self.SECRET})
        for base, label in ((self.public_url, "public"), (self.operator_url, "operator")):
            _s, _h, raw = self.fetch(base, self.PATH)
            self.assertNotIn(self.SECRET.encode(), raw, f"{label} port leaked it")
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            _s, _h, page = self.operator_fetch("/admin",
                                               headers={"Authorization":
                                                        f"Bearer {TOKEN}"})
            self.assertNotIn(self.SECRET.encode(), page, "the card printed it")

    def test_an_unset_row_still_answers_rather_than_500(self):
        """A fresh install has no settings table until the first read makes it; a
        phone polling config on launch must get defaults, not an error page."""
        status, _h, raw = self.public_fetch(self.PATH)
        self.assertEqual(status, 200, raw[:200])
        data = json.loads(raw)
        self.assertEqual(data["vip"], {"monthly_pkr": 200, "yearly_pkr": 1500})
        self.assertEqual(data["payments"]["jazzcash"]["till_id"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
