#!/usr/bin/env python3
"""Socket-level tests for `GET /api/v1/download`.

The endpoint is the download twin of `/api/v1/stream`: same signed handle, same
adult gate, same resolver — and the same rule that a public body never names the
hoster or the upstream file URL. Only a socket can prove the 302, the JSON
descriptor and the provenance split, so this file boots the real server on
loopback against a temporary catalog.

    python3 -S Fast_Fetch/test_download_endpoint.py
"""
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts        # noqa: E402
import admin_panel     # noqa: E402
import fast_fetch      # noqa: E402
import redact          # noqa: E402
import viewer          # noqa: E402

SITE = "somecdn.site"
DIRECT_URL = "https://media.example.test/film.mp4"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _ingest(conn, title, *, is_18_plus, direct_url):
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
        "releases": [{
            "release_title": f"{title} 1080p", "quality": "1080p",
            "codec": "x264", "size": "1.5GB", "languages": '["Hindi"]',
            "season": "", "episode": "", "intermediate_url": "",
            "origin_url": "", "source_site": SITE,
            "sources": [{"source_url": direct_url, "quality": "1080p",
                         "status": "active"}],
        }],
    }
    fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
    conn.commit()
    row = conn.execute(
        "SELECT id FROM download_sources ORDER BY id DESC LIMIT 1").fetchone()
    conn.execute(
        "UPDATE download_sources SET final_url = ?, status = 'active', "
        "is_temporary = 0, is_resumable = 1, mime_type = 'video/mp4' WHERE id = ?",
        (direct_url, row[0]))
    conn.commit()
    return row[0]


class DownloadEndpointTests(unittest.TestCase):
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
        self.source_id = _ingest(self.conn, "Ordinary Film", is_18_plus=0,
                                 direct_url=DIRECT_URL)
        self.adult_id = _ingest(self.conn, "Grown Up Film", is_18_plus=1,
                                direct_url="https://media.example.test/adult.mp4")

        self.public = viewer.make_server("127.0.0.1", 0, operator=False)
        self.operator = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (self.public, self.operator):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)
        self.public_url = f"http://127.0.0.1:{self.public.server_address[1]}"
        self.operator_url = f"http://127.0.0.1:{self.operator.server_address[1]}"

    def token(self, source_id):
        return redact.mint_token(source_id, viewer.signing_secret())

    def fetch(self, base, path, *, follow=True, headers=None):
        opener = urllib.request.build_opener() if follow else \
            urllib.request.build_opener(_NoRedirect)
        request = urllib.request.Request(base + path, headers=headers or {})
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def configure_shorteners(self, *, shrinkme="", droplink="", enabled=True):
        admin_panel._ensure_monetization(self.conn)
        self.conn.execute(
            "UPDATE app_remote_config SET shrinkme_api_token = ?, "
            "droplink_api_token = ?, feature_link_shorteners = ? WHERE id = 1",
            (shrinkme, droplink, 1 if enabled else 0))
        self.conn.commit()

    # ---- public JSON descriptor ------------------------------------------- #
    def test_json_descriptor_has_a_handle_and_no_upstream_address(self):
        token = self.token(self.source_id)
        status, _headers, raw = self.fetch(
            self.public_url, f"/api/v1/download?id={token}&redirect=0")
        self.assertEqual(status, 200, raw)
        body = json.loads(raw)
        self.assertTrue(body["success"])
        self.assertEqual(body["stream_id"], token)
        self.assertEqual(body["kind"], "download")
        self.assertEqual(body["mime_type"], "video/mp4")
        self.assertTrue(body["resumable"])
        self.assertTrue(body["filename"].endswith(".mp4"))
        self.assertIn(f"/api/v1/download?id={token}&redirect=1", body["download_url"])
        self.assertNotIn("media.example.test", raw.decode("utf-8", "replace"))
        self.assertNotIn(SITE, raw.decode("utf-8", "replace"))

    def test_redirect_points_at_the_resolved_media_url(self):
        token = self.token(self.source_id)
        status, headers, _body = self.fetch(
            self.public_url, f"/api/v1/download?id={token}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertTrue(headers["Content-Disposition"].rstrip('"').endswith(".mp4"))

    # ---- the handle and the adult gate ------------------------------------ #
    def test_a_plain_row_id_is_refused_on_the_public_port(self):
        status, _headers, _raw = self.fetch(
            self.public_url, f"/api/v1/download?id={self.source_id}&redirect=0")
        self.assertEqual(status, 400)

    def test_missing_or_forged_handle_is_refused(self):
        for token in ("", "not-a-token", str(self.source_id)):
            status, _headers, _raw = self.fetch(
                self.public_url, f"/api/v1/download?id={token}&redirect=0")
            self.assertEqual(status, 400, token)

    def test_adult_source_answers_like_an_absent_one(self):
        token = self.token(self.adult_id)
        status, _headers, raw = self.fetch(
            self.public_url, f"/api/v1/download?id={token}&redirect=0")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw),
                         {"success": False, "error": "not_found"})

    def test_handle_for_a_vanished_source_is_404(self):
        token = redact.mint_token(999999, viewer.signing_secret())
        status, _headers, raw = self.fetch(
            self.public_url, f"/api/v1/download?id={token}&redirect=0")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw),
                         {"success": False, "error": "not_found"})

    # ---- failures are failures -------------------------------------------- #
    def test_a_link_that_cannot_be_re_resolved_is_not_a_download(self):
        self.conn.execute(
            "UPDATE download_sources SET final_url = '', status = 'dead', "
            "source_url = '' WHERE id = ?", (self.source_id,))
        self.conn.commit()
        token = self.token(self.source_id)
        status, _headers, raw = self.fetch(
            self.public_url, f"/api/v1/download?id={token}&redirect=0")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw),
                         {"success": False, "error": "no_playable_source"})

    # ---- the operator port still sees provenance -------------------------- #
    def test_operator_port_accepts_a_plain_id_and_returns_the_resolved_url(self):
        status, _headers, raw = self.fetch(
            self.operator_url,
            f"/api/v1/download?id={self.source_id}&redirect=0")
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["url"], DIRECT_URL)

    def test_operator_port_is_never_monetized_by_a_shortener(self):
        self.configure_shorteners(shrinkme="shrinkme-token")
        with mock.patch.object(
                viewer, "call_shortener",
                side_effect=AssertionError("operator must not be shortened")):
            status, headers, _body = self.fetch(
                self.operator_url,
                f"/api/v1/download?id={self.source_id}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)

    # ---- free-tier shorteners --------------------------------------------- #
    def test_a_free_download_uses_the_configured_shortener_and_caches_it(self):
        self.configure_shorteners(shrinkme="shrinkme-token")
        token = self.token(self.source_id)
        with mock.patch.object(
                viewer, "call_shortener",
                return_value="https://short.test/once") as call:
            status, headers, _body = self.fetch(
                self.public_url, f"/api/v1/download?id={token}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://short.test/once")
        # A shortened target is a landing page, not the file.
        self.assertNotIn("Content-Disposition", headers)
        call.assert_called_once_with("shrinkme", "shrinkme-token", DIRECT_URL)
        columns = [row[1] for row in self.conn.execute(
            "PRAGMA table_info(cat_shortened_links)")]
        self.assertEqual(columns, ["original_url", "shortener_name",
                                   "shortened_url", "created_at"])
        row = self.conn.execute(
            "SELECT shortener_name, shortened_url FROM cat_shortened_links"
            " WHERE original_url = ?", (DIRECT_URL,)).fetchone()
        self.assertEqual(tuple(row), ("shrinkme", "https://short.test/once"))

        # Cache first: the second request must not spend another API call.
        with mock.patch.object(
                viewer, "call_shortener",
                side_effect=AssertionError("cache was not used")):
            status, headers, _body = self.fetch(
                self.public_url, f"/api/v1/download?id={token}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://short.test/once")

    def test_an_unconfigured_or_failing_shortener_falls_back_to_direct(self):
        token = self.token(self.source_id)
        status, headers, _body = self.fetch(
            self.public_url, f"/api/v1/download?id={token}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)

        self.configure_shorteners(shrinkme="shrinkme-token")
        with mock.patch.object(viewer, "call_shortener",
                               side_effect=OSError("network down")):
            status, headers, _body = self.fetch(
                self.public_url, f"/api/v1/download?id={token}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_a_saved_token_alone_does_not_reenable_the_retired_detour(self):
        """The owner's directive is structural now, not an accident of empty columns.

        "LINK SHORTENERS ARE PERMANENTLY DROPPED & RETIRED … All media downloads and
        streams are 100% direct." Until `feature_link_shorteners` existed the shipped
        behavior satisfied that only because nobody had typed a token: one save in
        /admin would have detoured every free download, silently, with no flag to
        notice and nothing to flip back.
        """
        self.configure_shorteners(shrinkme="shrinkme-token", enabled=False)
        self.assertEqual(admin_panel.shortener_targets(self.conn), [],
                         "a retired detour must hand the route no targets")
        # `shortener_targets` migrates the settings schema on a second connection; leave it
        # no lock, or the handler's own `get_db()` waits on it and the request never lands.
        self.conn.commit()
        token = self.token(self.source_id)
        with mock.patch.object(
                viewer, "call_shortener",
                side_effect=AssertionError("the retired detour was called")):
            status, headers, _body = self.fetch(
                self.public_url, f"/api/v1/download?id={token}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)
        self.assertIn("attachment", headers["Content-Disposition"],
                      "a direct file must still download as a file")

    def test_the_detour_runs_only_when_the_retired_flag_is_deliberately_flipped(self):
        self.configure_shorteners(shrinkme="shrinkme-token", enabled=False)
        self.assertEqual(admin_panel.shortener_targets(self.conn), [])
        self.conn.execute(
            "UPDATE app_remote_config SET feature_link_shorteners = 1 WHERE id = 1")
        self.conn.commit()
        self.assertEqual(admin_panel.shortener_targets(self.conn),
                         [("shrinkme", "shrinkme-token")])

    def test_a_live_account_vip_skips_the_shortener(self):
        self.configure_shorteners(shrinkme="shrinkme-token")
        key = accounts.new_sync_key()
        created = accounts.create_account(accounts.default_db_path(), key=key)
        with sqlite3.connect(str(self.state_path)) as state:
            state.execute("UPDATE user_accounts SET vip_until = ? WHERE id = ?",
                          (time.time() + 3600, created["account_id"]))
            state.commit()
        token = self.token(self.source_id)
        with mock.patch.object(
                viewer, "call_shortener",
                side_effect=AssertionError("VIP must not be shortened")):
            status, headers, _body = self.fetch(
                self.public_url, f"/api/v1/download?id={token}", follow=False,
                headers={"Authorization": f"Bearer {key}"})
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_an_expired_account_vip_is_treated_as_free(self):
        self.configure_shorteners(shrinkme="shrinkme-token")
        key = accounts.new_sync_key()
        created = accounts.create_account(accounts.default_db_path(), key=key)
        with sqlite3.connect(str(self.state_path)) as state:
            state.execute("UPDATE user_accounts SET vip_until = ? WHERE id = ?",
                          (time.time() - 1, created["account_id"]))
            state.commit()
        token = self.token(self.source_id)
        with mock.patch.object(viewer, "call_shortener",
                               return_value="https://short.test/free") as call:
            status, headers, _body = self.fetch(
                self.public_url, f"/api/v1/download?id={token}", follow=False,
                headers={"Authorization": f"Bearer {key}"})
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://short.test/free")
        call.assert_called_once()

    def test_a_signed_vip_pass_skips_the_shortener_but_a_forged_one_does_not(self):
        self.configure_shorteners(shrinkme="shrinkme-token")
        token = self.token(self.source_id)
        pass_token = redact.mint_vip_pass(time.time() + 3600,
                                          viewer.signing_secret())
        with mock.patch.object(
                viewer, "call_shortener",
                side_effect=AssertionError("signed pass must not be shortened")):
            status, headers, _body = self.fetch(
                self.public_url,
                f"/api/v1/download?id={token}&vip={pass_token}", follow=False)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)

        expired = redact.mint_vip_pass(time.time() - 1, viewer.signing_secret())
        viewer.ensure_shortened_links(self.conn)
        for forged in ("1", "true", expired, "not-a-pass"):
            self.conn.execute("DELETE FROM cat_shortened_links")
            self.conn.commit()
            with mock.patch.object(viewer, "call_shortener",
                                   return_value="https://short.test/free") as call:
                status, headers, _body = self.fetch(
                    self.public_url,
                    f"/api/v1/download?id={token}&vip={forged}", follow=False)
            self.assertEqual(status, 302, forged)
            self.assertEqual(headers["Location"], "https://short.test/free", forged)
            call.assert_called_once()

    def test_shortener_replies_are_parsed_conservatively(self):
        parse = viewer._shortened_from_body
        original = "https://media.example.test/film.mp4"
        self.assertEqual(
            parse(b'{"status":"success","shortenedUrl":"https://s.test/a"}', original),
            "https://s.test/a")
        self.assertEqual(
            parse(b'{"status":"success","shortened_url":"https://s.test/b"}', original),
            "https://s.test/b")
        self.assertEqual(parse(b"https://s.test/c\n", original), "https://s.test/c")
        self.assertIsNone(parse(b'{"status":"error","shortenedUrl":"https://s.test/d"}',
                                original))
        self.assertIsNone(parse(b'{"status":"success","shortenedUrl":"javascript:alert(1)"}',
                                original))
        self.assertIsNone(parse(json.dumps({"shortenedUrl": original}).encode(),
                                original))

    def test_shortener_rotation_advances_by_the_hour(self):
        targets = [("shrinkme", "a"), ("droplink", "b")]
        self.assertEqual(viewer.rotate_shortener_targets(targets, now=0)[0][0],
                         "shrinkme")
        self.assertEqual(viewer.rotate_shortener_targets(targets, now=3600)[0][0],
                         "droplink")
        self.assertEqual(viewer.rotate_shortener_targets(targets, now=7200)[0][0],
                         "shrinkme")

    # ---- shared plumbing -------------------------------------------------- #
    def test_download_pays_into_the_play_bucket(self):
        self.assertEqual(viewer.DashboardHandler._bucket_for(None, "/api/v1/download"),
                         "play")

    def test_filename_never_copies_the_declared_mime(self):
        self.assertEqual(viewer.download_filename("abcdefghijklmnop", "video/mp4"),
                         "radd-abcdefghijkl.mp4")
        self.assertEqual(
            viewer.download_filename("abcdefghijklmnop", "video/mp4; codecs=avc1"),
            "radd-abcdefghijkl.mp4")
        self.assertEqual(viewer.download_filename("abcdefghijklmnop",
                                                  'video/x-evil"\r\nX: y'),
                         "radd-abcdefghijkl.bin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
