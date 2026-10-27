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
import json
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

import accounts           # noqa: E402
import admin_panel        # noqa: E402
import api_v2             # noqa: E402
import catalog_v2         # noqa: E402
import fast_fetch         # noqa: E402
import redact             # noqa: E402
import viewer             # noqa: E402

TOKEN = "socket-level-operator-token"
SITE = "somecdn.site"


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
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            base + path, data=data, method=method,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
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
