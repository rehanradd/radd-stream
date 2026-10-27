#!/usr/bin/env python3
"""Offline tests for `admin_panel.py` — the operator's read-only surface.

The gate is the product here, so most of these files are about what a caller
must NOT be able to do: reach it from a non-loopback peer, reach it without the
token, reach it through a path that is not `/admin`, or get a site name out of a
screen whose data is scraped. Everything runs as a plain function call — no
port is opened, no live database is touched.

    python3 -S Fast_Fetch/test_admin_panel.py
"""
import ast
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import admin_panel          # noqa: E402
import api_v2               # noqa: E402
import catalog_v2           # noqa: E402
import fast_fetch           # noqa: E402
import redact               # noqa: E402
import viewer               # noqa: E402

TOKEN = "operator-token-for-tests"
NEEDLE = "clicknupload"          # one of redact's own needles, not an invented word

# `viewer._ensure_schema()` repoints `redact`'s process-global needle set at the
# database it was last handed and never restores it. test_database runs first in
# the full suite and leaves its fixture hostnames there, so an admin body that
# merely contains a saved address would fail its own leak scan. This module is
# imported before any test executes, which makes the set captured here the
# deployment default the admin surface is written against.
_BASELINE_NEEDLES = redact.needles()
_BASELINE_TEXT_NEEDLES = redact.text_needles()


class Fixture(unittest.TestCase):
    """A real ledger → real `catalog_v2` projection, because a hand-drawn `cat_*`
    fixture would test the screens against columns the projector does not write."""

    def setUp(self):
        redact.set_needles(_BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.addCleanup(redact.set_needles, _BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
                        mock.patch.object(viewer, "DB_PATH", self.db_path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)

    def ingest(self, *, title="Example Film", site="somecdn.site", is_18_plus=0,
               sources=({"source_url": "https://cdn.example/one.mp4",
                         "quality": "1080p", "status": "active"},)):
        data = {
            "url": f"https://{site}/movie/{title.lower().replace(' ', '-')}/",
            "slug": title.lower().replace(" ", "-"),
            "title": f"{title} ({2024})",
            "clean_title": title,
            "year": 2024,
            "content_type": "movie",
            "poster_url": "https://cdn/poster.jpg",
            "genres": '["Action"]',
            "synopsis": f"{title} synopsis",
            "is_18_plus": is_18_plus,
            "source_site": site,
            "industry": "Bollywood",
            "country": "India",
            "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
            "releases": [{"release_title": f"{title} 1080p", "quality": "1080p",
                          "codec": "x264", "size": "1.5GB", "languages": '["Hindi"]',
                          "season": "", "episode": "", "intermediate_url": "",
                          "origin_url": "", "source_site": site,
                          "sources": [dict(s) for s in sources]}],
        }
        fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
        self.conn.commit()
        catalog_v2.project(self.conn, rev=1, verbose=False)
        self.conn.commit()


class Gate(Fixture):
    def get(self, path="/admin", peer="127.0.0.1", header=f"Bearer {TOKEN}"):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            return admin_panel.route_get(path, {}, db_path=self.db_path,
                                         peer_address=peer, token_header=header)

    def post(self, path, peer="127.0.0.1", header=f"Bearer {TOKEN}"):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            return admin_panel.route_post(path, {}, db_path=self.db_path,
                                          peer_address=peer, token_header=header)

    # ── reachability ─────────────────────────────────────────────────────
    def test_a_remote_peer_is_refused_before_any_sql_runs(self):
        refused = self.get(peer="203.0.113.9")
        self.assertEqual(refused[0], 403)
        self.assertEqual(refused[1], admin_panel.CONTENT_PROBLEM)
        self.assertIn("loopback", refused[2].decode())

    def test_loopback_checks_run_before_the_token_check(self):
        """Order matters: a remote caller with a *correct* token must still learn
        only "loopback only", or the token becomes a remote-access password for a
        page that is supposed to be unreachable by design."""
        refused = admin_panel.route_get("/admin", {}, db_path=self.db_path,
                                        peer_address="10.0.0.5",
                                        token_header=f"Bearer {TOKEN}")
        self.assertEqual(refused[0], 403)

    def test_no_configured_token_denies_everything_including_an_empty_bearer(self):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": ""}):
            denied = admin_panel.route_get("/admin", {}, db_path=self.db_path,
                                           peer_address="127.0.0.1", token_header="")
        self.assertEqual(denied[0], 401)

    def test_a_missing_and_a_wrong_token_answer_identically(self):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            missing = admin_panel.route_get("/admin", {}, db_path=self.db_path,
                                            peer_address="127.0.0.1", token_header="")
            wrong = admin_panel.route_get("/admin", {}, db_path=self.db_path,
                                          peer_address="127.0.0.1",
                                          token_header="Bearer not-it")
        self.assertEqual(missing, wrong)

    def test_the_right_token_on_loopback_is_allowed(self):
        self.ingest()
        self.assertEqual(self.get()[0], 200)

    def test_ipv6_loopback_is_loopback(self):
        self.ingest()
        self.assertEqual(self.get(peer="::1")[0], 200)

    # ── namespace ────────────────────────────────────────────────────────
    def test_paths_outside_the_prefix_fall_through_as_none(self):
        for path in ("/api/v2/browse", "/administration", "/adminx", "/",
                     "/api/v2/account"):
            self.assertIsNone(self.get(path), path)
            self.assertIsNone(self.post(path), path)

    def test_an_unknown_screen_or_action_is_404_not_a_fallthrough(self):
        self.assertEqual(self.get("/admin/api/teleport")[0], 404)
        self.assertEqual(self.post("/admin/api/links/1/teleport")[0], 404)
        self.assertEqual(self.get("/admin/deep/nested/path")[0], 404)


class Screens(Fixture):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)

    def screen(self, name):
        answered = admin_panel.route_get(f"/admin/api/{name}", {}, db_path=self.db_path,
                                         peer_address="127.0.0.1",
                                         token_header=f"Bearer {TOKEN}")
        self.assertIsNotNone(answered)
        return answered

    def payload(self, name):
        status, _type, body = self.screen(name)
        self.assertEqual(status, 200)
        return json.loads(body.decode("utf-8"))

    # ── honest empty states ──────────────────────────────────────────────
    def test_a_ledger_with_no_projection_says_so_instead_of_crashing(self):
        for name in ("projection", "link-health", "review", "adult", "catalog"):
            data = self.payload(name)
            self.assertFalse(data["available"], name)
            self.assertIn(admin_panel.NOT_BUILT, json.dumps(data))

    def test_the_html_page_renders_empty_states_rather_than_blanks(self):
        answered = admin_panel.route_get("/admin", {}, db_path=self.db_path,
                                         peer_address="127.0.0.1",
                                         token_header=f"Bearer {TOKEN}")
        self.assertEqual(answered[0], 200)
        self.assertEqual(answered[1], "text/html; charset=utf-8")
        self.assertIn(admin_panel.NOT_BUILT, answered[2].decode())

    # ── a real projection ────────────────────────────────────────────────
    def test_projection_counts_the_work_it_was_given(self):
        self.ingest()
        data = self.payload("projection")
        self.assertTrue(data["available"])
        self.assertGreaterEqual(data["table_counts"].get("cat_works", 0), 1)

    def test_adult_proof_reports_the_flagged_work_as_projected_by_design(self):
        """Adult rows inside `cat_*` are the correct state — suppression is the
        edge's job — so the screen must count them without calling them a failure."""
        self.ingest(title="Grown Up Picture", site="adultcdn.example", is_18_plus=1)
        self.ingest(title="Normal Picture")
        data = self.payload("adult")
        self.assertTrue(data["available"])
        self.assertEqual(data["ledger_flagged_posts"], 1, data)
        self.assertEqual(data["projected_flagged_works"], 1, data)
        self.assertEqual(data["works_that_lost_their_flag"], 0, data)
        self.assertTrue(data["suppression_holds"], data)

    def test_adult_proof_fails_when_a_projected_work_lost_its_flag(self):
        """The one way display filtering can actually break: a work built from a
        flagged post that reached `cat_works` unflagged would be served to everyone.
        If the screen cannot see that, it is not proof of anything."""
        self.ingest(title="Grown Up Picture", site="adultcdn.example", is_18_plus=1)
        self.conn.execute("UPDATE cat_works SET is_18_plus = 0")
        self.conn.commit()
        data = self.payload("adult")
        self.assertEqual(data["works_that_lost_their_flag"], 1, data)
        self.assertEqual(data["exposed_rows_if_leaked"]["links"], 1, data)
        self.assertFalse(data["suppression_holds"], data)

    def test_link_health_reports_the_projected_link(self):
        self.ingest()
        data = self.payload("link-health")
        self.assertEqual(sum(data["by_state"].values()), 1, data)

    # ── provenance ───────────────────────────────────────────────────────
    def test_a_screen_that_names_a_forbidden_column_is_refused_whole(self):
        """`_provenance_offenders` is checked on the serialised body, so a SELECT
        list gaining `source_site` by accident fails the screen instead of
        publishing the site."""
        self.ingest()
        with mock.patch.object(admin_panel, "screen_projection",
                               lambda conn: {"available": True, "source_site": "katmoviehd"}):
            answered = self.screen("projection")
        self.assertEqual(answered[0], 500)
        self.assertEqual(answered[2].decode(), admin_panel.LEAK_MESSAGE)

    def test_a_brand_that_reaches_a_screen_body_collapses_the_response(self):
        """A scraped value that slips past `redact.scrub_text` must never be
        partially rendered: the whole answer becomes one fixed, clean string."""
        self.ingest()
        self.conn.execute("UPDATE cat_links SET playability = ?", (NEEDLE,))
        self.conn.commit()
        answered = self.screen("link-health")
        self.assertEqual(answered[0], 500)
        self.assertNotIn(NEEDLE, answered[2].decode())

    def test_a_site_shaped_release_label_is_scrubbed_not_rendered(self):
        """The gentler half of the same rule: a title carrying a brand is cleaned
        at build time, so the operator sees the work and nobody sees the site."""
        self.ingest(title="VegaMovies Showcase Special")
        data = self.payload("catalog")
        blob = json.dumps(data).lower()
        self.assertNotIn("vegamovies", blob)

    def test_no_screen_names_a_url_or_site_column_at_all(self):
        """Read the module's SQL, not its prose. A SELECT list is where a
        provenance leak would be written first, but a docstring is *allowed* to
        name a column it forbids — so parse the literals an `execute()` could see
        and skip only the docstrings."""
        tree = ast.parse(Path(admin_panel.__file__).read_text(encoding="utf-8"))
        doc_nodes = set()
        holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        for node in ast.walk(tree):
            if isinstance(node, holders) and node.body:
                first = node.body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    doc_nodes.add(id(first.value))
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in doc_nodes or "SELECT" not in node.value.upper():
                continue
            for statement in ("source_site", "origin_url", "page_url", "final_url"):
                if statement in node.value:
                    offenders.append((statement, node.value.strip()[:80]))
        self.assertEqual(offenders, [], f"a SQL literal selects provenance: {offenders}")


class TheOneWrite(Fixture):
    def post(self, path):
        with mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN}):
            return admin_panel.route_post(path, {}, db_path=self.db_path,
                                          peer_address="127.0.0.1",
                                          token_header=f"Bearer {TOKEN}")

    def test_re_folding_evidence_touches_only_the_named_link(self):
        self.ingest()
        link_id = self.conn.execute("SELECT id FROM cat_links LIMIT 1").fetchone()[0]
        self.conn.execute(
            "INSERT INTO cat_link_evidence(link_id, probed_at, ok, latency_ms)"
            " VALUES(?, 1730000000, 0, 900)", (link_id,))
        self.conn.commit()
        answered = self.post(f"/admin/api/links/{link_id}/evidence")
        self.assertEqual(answered[0], 200, answered)
        body = json.loads(answered[2].decode())
        self.assertTrue(body["ok"])
        self.assertEqual(body["evidence"]["link_id"], int(link_id))
        state = self.conn.execute("SELECT state FROM cat_links WHERE id = ?",
                                 (link_id,)).fetchone()[0]
        self.assertEqual(state, "dead")

    def test_a_link_that_is_not_in_the_projection_is_404(self):
        self.ingest()
        status, content_type, body = self.post("/admin/api/links/987654/evidence")
        self.assertEqual(status, 404)
        self.assertEqual(content_type, admin_panel.CONTENT_PROBLEM)
        self.assertEqual(json.loads(body)["code"], "not_found")

    def test_a_non_numeric_link_id_is_400(self):
        self.ingest()
        status, content_type, body = self.post("/admin/api/links/abc/evidence")
        self.assertEqual(status, 400)
        self.assertEqual(content_type, admin_panel.CONTENT_PROBLEM)
        self.assertEqual(json.loads(body)["code"], "invalid_params")

    def test_admin_only_uses_codes_the_public_manifest_declares(self):
        """§16.4 is a closed vocabulary and `/manifest` publishes it. An admin
        refusal with an invented code would be a shape a client cannot know."""
        for code, answer in admin_panel._PROBLEM.items():
            self.assertIn(code, api_v2.PROBLEM_CODES, code)
            self.assertEqual(answer, api_v2.PROBLEM_CODES[code], code)

    def test_the_action_needs_no_projection_and_never_invents_one(self):
        self.assertEqual(self.post("/admin/api/links/1/evidence")[0], 503)

    def test_no_review_resolve_route_exists(self):
        """`catalog_v2` exposes no setter for `cat_review_queue.resolved_at`, so a
        route that looked like one would be a button that does nothing."""
        self.ingest()
        self.assertEqual(self.post("/admin/api/review/1/resolve")[0], 404)


class Monetization(Fixture):
    """The operator's own settings card, its save action, and the app's read of
    the same row. The gate still decides everything, but the questions here are
    different: does a refused save write nothing, and does a credential ever
    reach a body a phone can fetch."""

    SAVE = "/admin/action/save-monetization"
    TOKEN_VALUE = "shrinkme-live-api-token-98765"

    def setUp(self):
        super().setUp()
        env = mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)

    def save(self, body, peer="127.0.0.1", header=None):
        return admin_panel.route_post(self.SAVE, {}, db_path=self.db_path,
                                      peer_address=peer,
                                      token_header=header if header is not None
                                      else f"Bearer {TOKEN}", body=body)

    def card(self):
        answered = admin_panel.route_get("/admin/api/monetization", {},
                                         db_path=self.db_path, peer_address="127.0.0.1",
                                         token_header=f"Bearer {TOKEN}")
        status, _type, raw = answered
        self.assertEqual(status, 200, answered)
        return json.loads(raw.decode("utf-8"))

    def public(self):
        with admin_panel._session(self.db_path) as conn:
            return admin_panel.remote_config(conn)

    def values(self):
        return {field["key"]: field["value"] for field in self.card()["fields"]}

    # ── the card ─────────────────────────────────────────────────────────
    def test_the_card_shows_the_pkr_defaults_before_anything_is_saved(self):
        """A card that 404s until the operator has saved once would be a screen
        that hides its own existence; defaults are the honest empty state, and
        the card needs no `cat_*` projection to answer."""
        data = self.card()
        self.assertTrue(data["available"])
        self.assertEqual(self.values()["vip_monthly_pkr"], "200")
        self.assertEqual(self.values()["vip_yearly_pkr"], "1500")
        self.assertFalse(self.values()["pak_till_id"])

    def test_the_card_is_on_the_html_page(self):
        self.ingest()
        status, _type, raw = admin_panel.route_get("/admin", {}, db_path=self.db_path,
                                                   peer_address="127.0.0.1",
                                                   token_header=f"Bearer {TOKEN}")
        self.assertEqual(status, 200)
        page = raw.decode("utf-8")
        self.assertIn("Monetag Rewarded Video zone ID", page)
        self.assertIn("EasyPaisa Mobile Number", page)

    # ── the save ─────────────────────────────────────────────────────────
    def test_a_save_persists_and_the_card_reads_it_back(self):
        answered = self.save({"pak_till_id": "123456",
                              "pak_jazzcash_number": "0300-1234567",
                              "pak_easypaisa_number": "0333 7654321",
                              "pak_raast_id": "03001234567",
                              "vip_monthly_pkr": "350",
                              "monetag_zone_id": "10293847"})
        self.assertEqual(answered[0], 200, answered)
        values = self.values()
        self.assertEqual(values["pak_till_id"], "123456")
        self.assertEqual(values["pak_jazzcash_number"], "0300-1234567")
        self.assertEqual(values["vip_monthly_pkr"], "350")
        self.assertGreater(self.card()["updated_at"], 0)

    def test_one_bad_field_refuses_the_whole_body(self):
        """Atomic: half a pricing block applied would bill a subscriber off a
        config nobody approved."""
        self.save({"vip_monthly_pkr": 200, "vip_yearly_pkr": 1500})
        status, _type, raw = self.save({"vip_monthly_pkr": 999,
                                        "vip_yearly_pkr": -5})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["code"], "invalid_params")
        self.assertEqual(self.values()["vip_monthly_pkr"], "200")

    def test_an_empty_body_does_not_clear_the_settings(self):
        self.save({"pak_till_id": "123456"})
        self.assertEqual(self.save({})[0], 400)
        self.assertEqual(self.values()["pak_till_id"], "123456")

    def test_an_unknown_setting_is_refused_and_writes_nothing(self):
        self.assertEqual(self.save({"pak_till_id": "123456",
                                    "hero_title_id": 42})[0], 400)
        self.assertFalse(self.values()["pak_till_id"])

    def test_a_field_the_edge_would_rewrite_is_refused_at_the_gate_of_the_row(self):
        """A stored value that `scrub_text` would edit is a payment handle the
        app shows with a piece missing. Refusing the paste beats a silent rewrite
        at the public edge — and beats the whole card collapsing to a 500."""
        status, _type, raw = self.save({"pak_till_id": NEEDLE})
        self.assertEqual(status, 400)
        self.assertIn("JazzCash Merchant Till ID", json.loads(raw)["detail"])
        self.assertFalse(self.values()["pak_till_id"])

    def test_an_address_in_an_identifier_field_is_refused(self):
        self.assertEqual(self.save({"pak_raast_id": "https://example.com/pay"}
                                   )[0], 400)
        self.assertFalse(self.values()["pak_raast_id"])

    def test_a_non_numeric_price_is_refused(self):
        for bad in ("two hundred", "-1", "1e6", True, [200]):
            self.assertEqual(self.save({"vip_monthly_pkr": bad})[0], 400, bad)

    def test_the_save_is_gated_like_every_other_admin_route(self):
        self.assertEqual(self.save({"pak_till_id": "1"}, peer="10.0.0.5")[0], 403)
        self.assertEqual(self.save({"pak_till_id": "1"}, header="Bearer wrong")[0], 401)
        self.assertFalse(self.values()["pak_till_id"])

    # ── the secrets ──────────────────────────────────────────────────────
    def test_a_shortener_token_never_reaches_a_body_whole(self):
        """The card masks, the public projection omits. A token in either is a
        stranger able to shorten on the operator's payout account over plain
        HTTP — which is how an affiliate gets banned."""
        self.save({"shrinkme_api_token": self.TOKEN_VALUE,
                   "droplink_api_token": ""})
        card_raw = json.dumps(self.card())
        page_raw = admin_panel.route_get("/admin", {}, db_path=self.db_path,
                                         peer_address="127.0.0.1",
                                         token_header=f"Bearer {TOKEN}")[2].decode()
        public_raw = json.dumps(self.public())
        for label, body in (("card", card_raw), ("page", page_raw),
                            ("public", public_raw)):
            self.assertNotIn(self.TOKEN_VALUE, body, f"{label} published the token")
        self.assertIn("*", self.values()["shrinkme_api_token"])
        self.assertTrue(self.card()["secrets_masked"])

    def test_the_public_projection_publishes_what_a_payment_screen_shows(self):
        self.save({"pak_till_id": "123456", "pak_jazzcash_number": "0300-1234567",
                   "pak_easypaisa_number": "03337654321", "pak_raast_id": "03001234567",
                   "vip_monthly_pkr": 200, "vip_yearly_pkr": 1500,
                   "monetag_zone_id": "10293847", "adsterra_tag_id": "0d1a7f3b9c",
                   "shrinkme_api_token": self.TOKEN_VALUE})
        data = self.public()
        self.assertTrue(data["success"])
        self.assertEqual(data["currency"], "PKR")
        self.assertEqual(data["vip"], {"monthly_pkr": 200, "yearly_pkr": 1500})
        self.assertEqual(data["payments"]["jazzcash"]["till_id"], "123456")
        self.assertEqual(data["payments"]["raast"]["instant_id"], "03001234567")
        self.assertEqual(data["ads"]["monetag_rewarded_zone_id"], "10293847")
        self.assertEqual(data["ads"]["adsterra_native_banner_id"], "0d1a7f3b9c")
        self.assertEqual(data["link_shorteners"],
                         [{"network": "shrinkme", "configured": True},
                          {"network": "droplink", "configured": False}])

    def test_the_public_projection_names_no_provenance_key(self):
        """This body leaves the box on the public port, so it obeys the same rule
        as every other emitter: no `url`/`site`/`service`/`hoster` key, whatever
        the operator pasted into a field."""
        self.save({"pak_till_id": "123456"})
        body = json.dumps(self.public()).lower()
        for key in redact.PROVENANCE:
            self.assertNotIn(f'"{key}"', body, key)

    def test_only_the_save_action_consumes_a_body(self):
        """The evidence re-fold still derives everything from the journal; a
        mount that read a body for it would be reading bytes nobody asked for."""
        self.assertTrue(admin_panel.takes_body(self.SAVE))
        self.assertFalse(admin_panel.takes_body("/admin/api/links/1/evidence"))
        self.assertFalse(admin_panel.takes_body("/admin/api/monetization"))

    def test_the_schema_is_the_field_spec_and_one_row(self):
        """`CHECK (id = 1)` is what makes a partial save unambiguous: there is no
        second settings row to guess between."""
        self.card()                       # the first read creates the table
        self.conn.rollback()              # end this connection's stale snapshot
        columns = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(app_remote_config)")}
        self.assertEqual(columns,
                         {"id", "updated_at"} | set(admin_panel._FIELD_BY_KEY))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM app_remote_config").fetchone()[0], 1)

    # ── the app's remote controls ─────────────────────────────────────────
    def test_remote_controls_have_honest_defaults_before_any_save(self):
        """An unconfigured deployment is open for business: no maintenance
        window, no update banner, and all three features on. A flag that
        defaulted off would look like a feature the owner had switched off."""
        data = self.public()
        self.assertFalse(data["maintenance_mode"])
        self.assertEqual(data["apk_update_url"], "")
        self.assertEqual(data["feature_flags"],
                         {"downloads": True, "pure_cinema": True,
                          "chromecast": True})

    def test_the_remote_controls_round_trip_through_the_save_and_the_public_body(self):
        answered = self.save({
            "maintenance_mode": True,
            "apk_update_url": "https://downloads.example/app/radd-stream.apk",
            "feature_downloads": False,
            "feature_pure_cinema": True,
            "feature_chromecast": False,
        })
        self.assertEqual(answered[0], 200, answered)
        data = self.public()
        self.assertTrue(data["maintenance_mode"])
        self.assertEqual(data["apk_update_url"],
                         "https://downloads.example/app/radd-stream.apk")
        self.assertEqual(data["feature_flags"],
                         {"downloads": False, "pure_cinema": True,
                          "chromecast": False})
        values = self.values()
        self.assertEqual(values["maintenance_mode"], "on")
        self.assertEqual(values["feature_downloads"], "off")
        self.assertEqual(values["feature_chromecast"], "off")

    def test_a_bad_flag_or_update_url_is_refused_and_writes_nothing(self):
        self.assertEqual(self.save({"maintenance_mode": "maybe"})[0], 400)
        for bad in ("javascript:alert(1)", "ftp://example.com/a.apk",
                    "https://", "//example.com/a.apk",
                    "https://user:pass@example.com/a.apk",
                    "https://example.com/a b.apk"):
            self.assertEqual(self.save({"apk_update_url": bad})[0], 400, bad)
        self.assertFalse(self.public()["maintenance_mode"])
        self.assertEqual(self.public()["apk_update_url"], "")

    def test_an_older_settings_row_gains_the_remote_control_columns(self):
        """A deployment whose row was created before this session must not lose
        its payment settings — and must not 500 because the new columns are
        absent. `CREATE TABLE IF NOT EXISTS` does not migrate, so this asserts
        the ALTER path and that the old value survives it."""
        self.conn.execute("DROP TABLE IF EXISTS app_remote_config")
        self.conn.execute(
            "CREATE TABLE app_remote_config ("
            " id INTEGER PRIMARY KEY CHECK (id = 1),"
            " pak_till_id TEXT NOT NULL DEFAULT '',"
            " updated_at INTEGER NOT NULL DEFAULT 0)")
        self.conn.execute(
            "INSERT INTO app_remote_config(id, pak_till_id) VALUES(1, '777')")
        self.conn.commit()

        data = self.public()
        self.assertEqual(data["payments"]["jazzcash"]["till_id"], "777")
        self.assertTrue(data["feature_flags"]["downloads"])
        columns = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(app_remote_config)")}
        self.assertTrue(set(admin_panel._FIELD_BY_KEY) <= columns, columns)


class Fleet(Fixture):
    """The Scraper Management card, its queue action and its audit journal.

    The panel's wider promise is that JSON bodies carry no provenance; the fleet
    is the one card whose HTML may name the engines the operator configured, so
    both halves are asserted here: the JSON screen stays opaque, the loopback page
    names the 18 configured crawlers, and a run can only be queued for a handle
    that maps onto that fixed tuple.
    """

    ACTION = admin_panel.RUN_SCRAPER_PATH

    def setUp(self):
        super().setUp()
        env = mock.patch.dict("os.environ", {"RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        self.status_dir = Path(self.tmp.name)
        for patcher in (
                mock.patch.object(admin_panel, "_status_dir",
                                  lambda: self.status_dir),
                mock.patch.object(admin_panel, "_running_sites", lambda: set())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, path="/admin/api/fleet"):
        return admin_panel.route_get(path, {}, db_path=self.db_path,
                                     peer_address="127.0.0.1",
                                     token_header=f"Bearer {TOKEN}")

    def payload(self, path="/admin/api/fleet"):
        status, _type, raw = self.get(path)
        self.assertEqual(status, 200, raw[:200])
        return json.loads(raw.decode("utf-8"))

    def post(self, body, peer="127.0.0.1", header=f"Bearer {TOKEN}",
             path=None, db_path=None):
        return admin_panel.route_post(path or self.ACTION, {}, db_path=db_path or self.db_path,
                                      peer_address=peer, token_header=header,
                                      body=body)

    def crawler_for(self, site):
        return next(crawler for crawler, name in admin_panel._CRAWLER_SITES.items()
                    if name == site)

    def test_the_fleet_is_exactly_the_eighteen_configured_crawlers(self):
        data = self.payload()
        self.assertEqual(data["total"], 18)
        self.assertEqual(len(data["crawlers"]), 18)
        self.assertEqual([row["crawler_id"] for row in data["crawlers"]],
                         [f"crawler-{i:02d}" for i in range(1, 19)])
        self.assertEqual(len(set(admin_panel.FLEET_SITES)), 18)

    def test_the_fleet_json_names_no_site_and_no_url(self):
        """The JSON screen is a machine surface like every other: handles only.
        A client that is not the loopback HTML page cannot learn the fleet."""
        self.ingest()
        blob = json.dumps(self.payload()).lower()
        for site in admin_panel.FLEET_SITES:
            self.assertNotIn(site, blob)
        for key in redact.PROVENANCE:
            self.assertNotIn(f'"{key}"', blob, key)

    def test_the_html_card_names_the_fleet_and_offers_both_actions(self):
        status, _type, raw = admin_panel.route_get(
            "/admin", {}, db_path=self.db_path, peer_address="127.0.0.1",
            token_header=f"Bearer {TOKEN}")
        self.assertEqual(status, 200, raw[:200])
        page = raw.decode("utf-8")
        for site in admin_panel.FLEET_SITES:
            self.assertIn(site, page)
        for label in ("Scraper management", "Recent scraper audit", "Sync now",
                      "Crawl", "Maintenance Mode", "Pure Cinema", "Chromecast",
                      "Background Downloads", "JazzCash Merchant Till ID",
                      "EasyPaisa Mobile Number", "Raast Instant ID"):
            self.assertIn(label, page, label)
        self.assertIn('id="crawl-limit"', page)
        self.assertIn(admin_panel.RUN_SCRAPER_PATH, page)
        self.assertNotIn(TOKEN, page, "the page embedded the bearer token")

    def test_a_status_file_drives_last_sync_and_progress(self):
        (self.status_dir / "vegamovies_status.json").write_text(json.dumps({
            "completed": 4, "total": 10, "failed": 1, "releases": 4,
            "sources": 9, "updated_at": "2026-10-27T00:00:00Z",
        }), encoding="utf-8")
        crawler = self.crawler_for("vegamovies")
        row = next(item for item in self.payload()["crawlers"]
                   if item["crawler_id"] == crawler)
        self.assertEqual((row["done"], row["total"], row["failed"]), (4, 10, 1))
        self.assertEqual(row["percent"], 40)
        self.assertEqual(row["last_sync_at"], 1793059200)
        self.assertEqual(row["state"], "idle")

    def test_a_running_process_is_reported_active(self):
        with mock.patch.object(admin_panel, "_running_sites",
                               lambda: {"vegamovies"}):
            crawler = self.crawler_for("vegamovies")
            data = self.payload()
        row = next(item for item in data["crawlers"]
                   if item["crawler_id"] == crawler)
        self.assertEqual(row["state"], "active")
        self.assertEqual(data["active"], 1)

    def test_a_valid_sync_or_crawl_is_queued_and_audited(self):
        calls = []

        def fake_spawn(site, mode, limit, crawler_id, audit_id, db_path):
            calls.append((site, mode, limit, crawler_id, audit_id))
            return 4321

        with mock.patch.object(admin_panel, "_spawn_fleet_run", fake_spawn):
            for site, mode in (("katmoviehd", "sync"), ("vegamovies", "crawl")):
                crawler = self.crawler_for(site)
                status, _type, raw = self.post(
                    {"crawler": crawler, "mode": mode, "limit": 7})
                self.assertEqual(status, 202, raw[:200])
                body = json.loads(raw.decode())
                self.assertTrue(body["accepted"])
                self.assertEqual(body["job"]["crawler_id"], crawler)
                self.assertEqual(body["job"]["action"], mode)
            audit = self.payload()["recent_audit"]
        self.assertEqual([(c[0], c[1], c[2]) for c in calls],
                         [("katmoviehd", "sync", 7), ("vegamovies", "crawl", 7)])
        self.assertEqual([row["action"] for row in audit], ["crawl", "sync"])
        self.assertEqual([row["crawler_id"] for row in audit],
                         [self.crawler_for("vegamovies"),
                          self.crawler_for("katmoviehd")])

    def test_a_bad_handle_mode_limit_or_extra_key_is_refused_before_any_spawn(self):
        called = []
        with mock.patch.object(admin_panel, "_spawn_fleet_run",
                               lambda *a, **k: called.append(a) or 1):
            for body in ({"crawler": "crawler-99"},
                         {"crawler": "vegamovies"},          # name is not a handle
                         {"crawler": "crawler-01", "mode": "nuke"},
                         {"crawler": "crawler-01", "limit": 0},
                         {"crawler": "crawler-01", "limit": 5000},
                         {"crawler": "crawler-01", "limit": "seven"},
                         {"crawler": "crawler-01", "limit": True},
                         {"crawler": "crawler-01", "extra": "x"}):
                status, content_type, raw = self.post(body)
                self.assertEqual(status, 400, (body, raw[:200]))
                self.assertEqual(content_type, admin_panel.CONTENT_PROBLEM)
                self.assertEqual(json.loads(raw)["code"], "invalid_params")
        self.assertEqual(called, [])
        self.assertEqual(self.payload()["recent_audit"], [])

    def test_the_action_is_gated_like_every_other_admin_route(self):
        body = {"crawler": "crawler-01", "mode": "sync"}
        with mock.patch.object(admin_panel, "_spawn_fleet_run",
                               lambda *a, **k: 1):
            self.assertEqual(self.post(body, peer="10.0.0.5")[0], 403)
            self.assertEqual(self.post(body, header="Bearer wrong")[0], 401)
        self.assertEqual(self.payload()["recent_audit"], [])

    def test_a_crawler_with_a_live_run_is_not_queued_twice(self):
        crawler = self.crawler_for("vegamovies")
        with mock.patch.object(admin_panel, "_running_sites",
                               lambda: {"vegamovies"}):
            status, _type, raw = self.post({"crawler": crawler, "mode": "sync"})
        self.assertEqual(status, 400, raw[:200])
        self.assertIn("in progress", json.loads(raw)["detail"])
        self.assertEqual(self.payload()["recent_audit"], [])

    def test_a_spawn_failure_is_recorded_and_never_echoes_the_exception(self):
        crawler = self.crawler_for("rogmovies")

        def boom(*_args, **_kwargs):
            raise OSError("secret /srv/path/leak")

        with mock.patch.object(admin_panel, "_spawn_fleet_run", boom):
            status, _type, raw = self.post({"crawler": crawler, "mode": "crawl"})
        self.assertEqual(status, 500)
        self.assertNotIn("secret", raw.decode())
        row = self.payload()["recent_audit"][0]
        self.assertEqual(row["status"], "failed")

    def test_every_crawler_has_a_fixed_command_in_both_modes(self):
        for site in admin_panel.FLEET_SITES:
            for mode in admin_panel.FLEET_MODES:
                command = admin_panel._fleet_command(site, mode, 5)
                self.assertIsInstance(command, list)
                self.assertEqual(command[0], admin_panel.sys.executable)
                self.assertNotIn(";", command)
                self.assertTrue(command[1].endswith((".py",)))
                for piece in command:
                    self.assertNotIn(" ", piece)
        self.assertEqual(admin_panel._fleet_command("multimovies", "crawl", 5)[2:],
                         ["--limit-roots", "5"])
        with self.assertRaises(ValueError):
            admin_panel._fleet_command("not-a-site", "sync", 5)

    def test_the_public_remote_config_carries_no_fleet_data(self):
        with admin_panel._session(self.db_path) as conn:
            public = admin_panel.remote_config(conn)
        blob = json.dumps(public).lower()
        self.assertNotIn("crawler", blob)
        for site in admin_panel.FLEET_SITES:
            self.assertNotIn(site, blob)

    def test_only_the_two_settings_actions_consume_a_body(self):
        self.assertTrue(admin_panel.takes_body(admin_panel.RUN_SCRAPER_PATH))
        self.assertTrue(admin_panel.takes_body(admin_panel.SAVE_MONETIZATION_PATH))
        self.assertFalse(admin_panel.takes_body("/admin/api/links/1/evidence"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
