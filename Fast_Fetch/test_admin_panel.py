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
import viewer               # noqa: E402

TOKEN = "operator-token-for-tests"
NEEDLE = "clicknupload"          # one of redact's own needles, not an invented word


class Fixture(unittest.TestCase):
    """A real ledger → real `catalog_v2` projection, because a hand-drawn `cat_*`
    fixture would test the screens against columns the projector does not write."""

    def setUp(self):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
