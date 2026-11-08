#!/usr/bin/env python3
"""test_bundle_handles.py — Session 111: a v2 bundle handle names a ledger row.

The bug (proven live by the parent 2026-11-08, work_id 54221): POST
/api/v2/play answered 200 with 5 candidates, but pressing the bundle's OWN
`stream_id` tokens at /api/v1/stream 404'd on all 5. Decoding a bundle token
gave 1915585 — a `cat_links` id — while /api/v1/stream parses its token as a
`download_sources` id, and no such ledger row exists. The copies were fine:
the same release's ledger rows pressed 302 when minted directly.

`catalog_api._link_view` minted the handle from the projected row's own id
(`link["id"]`); every consumer of a `stream_id` — /api/v1/stream,
/api/v1/download, `link_is_adult`, the quality gate — treats the parsed id
as a ledger id. The projected `cat_links.ledger_link_id` IS that id. The
fix mints from it, and a row without one carries no playable stream handle
(`stream_id` None, `playable` False) instead of a handle to nothing. The
same mismatch lived in the v2 /resolve JSON, which echoed its cat-id
`link_ref` under the name `stream_id`; it now mints the ledger id there.

Why the old tests never caught it: in every projected fixture the two id
spaces coincide — `cat_links` ids are assigned in projection order from 1
while the ledger ids were assigned in ingest order from 1, so `cat id ==
ledger id` for every row and minting either one presses the same row. This
suite breaks the coincidence the way production does: a rebuild re-assigns
`cat_links` ids from 1 while ledger ids keep growing, so the fixture bumps
every `cat_links.id` by 500 after projecting (cat 501 <-> ledger 1). A test
that passes on the old code here proves nothing; the negative control in
the Session 111 checkpoint shows (a), (b), (c) and (e) fail without the
fix, while (d) and (f) pass on both — they are regression guards, not
discriminators.

The end-to-end press is real, not mocked: a loopback media server serves a
video/mp4 with Range support, the fixture copy points at it, and the bundle
handle is pressed through a real /api/v1/stream socket server with the real
resolver (Stage-2 probe included). No external network: both servers bind
127.0.0.1 only. The print is 720p so the quality gate (1080p/2160p) never
interferes with the handle question.

    python3 -S Fast_Fetch/test_bundle_handles.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")

import api_v2          # noqa: E402
import catalog_api     # noqa: E402
import catalog_v2      # noqa: E402
import fast_fetch      # noqa: E402
import redact          # noqa: E402
import viewer          # noqa: E402

SECRET = "session-111-bundle-handles-test-secret"

#: The rebuild offset: cat ids are renumbered from 1 on every projection
#: while ledger ids keep growing, so production's two universes never agree
#: for long. 500 keeps the fixture's cat ids far from its ledger ids (1, 2)
#: with no overlap either way.
CAT_ID_OFFSET = 500

MEDIA_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _MediaHandler(BaseHTTPRequestHandler):
    """One fake video file: 206 + video/mp4 on a Range read, 200 otherwise."""

    def log_message(self, *args):
        pass

    def _serve(self):
        rng = self.headers.get("Range") or ""
        if rng.startswith("bytes="):
            try:
                start, end = rng[6:].split("-", 1)
                start = int(start or 0)
                end = int(end) if end else len(MEDIA_BYTES) - 1
            except ValueError:
                start, end = 0, len(MEDIA_BYTES) - 1
            end = min(end, len(MEDIA_BYTES) - 1)
            body = MEDIA_BYTES[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Range",
                             f"bytes {start}-{end}/{len(MEDIA_BYTES)}")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(MEDIA_BYTES)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(MEDIA_BYTES)

    do_GET = _serve

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(MEDIA_BYTES)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()


class _ReplyHandler:
    """The `api_v2.route_get` half of test_api_v2's FakeHandler, minimal."""

    def __init__(self):
        self.headers = {}
        self.rate_headers = []
        self.replies = []

    def send_response(self, code):
        self.replies.append({"kind": "raw", "status": int(code), "headers": [],
                             "body": b"", "payload": None})

    def send_header(self, name, value):
        if not self.replies:
            self.send_response(200)
        self.replies[-1]["headers"].append((str(name), str(value)))

    def end_headers(self):
        pass

    def send_bytes(self, data, content_type="text/html; charset=utf-8",
                   status=200, extra_headers=None):
        headers = [("Content-Type", str(content_type)),
                   ("Content-Length", str(len(bytes(data)))),
                   ("Connection", "close")]
        headers.extend((str(k), str(v)) for k, v in (extra_headers or []))
        self.replies.append({"kind": "bytes", "status": int(status),
                             "headers": headers, "body": bytes(data),
                             "content_type": content_type, "payload": None})

    def send_json(self, data, status=200, extra_headers=None):
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"),
                        content_type="application/json; charset=utf-8",
                        status=status, extra_headers=extra_headers)
        self.replies[-1]["payload"] = data


class BundleHandlesFixture(unittest.TestCase):
    """One projected print per test, cat ids offset from ledger ids."""

    def setUp(self):
        os.environ["RADD_STREAM_SECRET"] = SECRET
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "wire.db"

        # A fake video file on loopback, so the real resolver's Stage-2
        # probe can pass without any external network.
        self.media = ThreadingHTTPServer(("127.0.0.1", 0), _MediaHandler)
        threading.Thread(target=self.media.serve_forever, daemon=True).start()
        self.addCleanup(self.media.shutdown)
        self.addCleanup(self.media.server_close)
        self.media_url = (
            f"http://127.0.0.1:{self.media.server_address[1]}/film.mp4")

        self._patches = [
            unittest.mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
            unittest.mock.patch.object(viewer, "DB_PATH", self.db_path),
        ]
        for patcher in self._patches:
            patcher.start()
        self.addCleanup(self._stop_patches)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self._build_corpus()

        # The real v1 socket server, public port: the press in (b)/(d) goes
        # through the same handler the app hits, quality gate included.
        self.public = viewer.make_server("127.0.0.1", 0, operator=False)
        threading.Thread(target=self.public.serve_forever, daemon=True).start()
        self.addCleanup(self.public.shutdown)
        self.addCleanup(self.public.server_close)
        self.public_url = f"http://127.0.0.1:{self.public.server_address[1]}"

    def _stop_patches(self):
        for patcher in reversed(self._patches):
            patcher.stop()

    def _build_corpus(self):
        url = "https://somecdn.site/movie/loopback-film/"
        data = {
            "url": url, "slug": "loopback-film",
            "title": "Loopback Film (2024)", "clean_title": "Loopback Film",
            "year": 2024, "content_type": "movie",
            "poster_url": "https://cdn/poster.jpg", "genres": '["Action"]',
            "synopsis": "Loopback Film synopsis", "is_18_plus": 0,
            "source_site": "somecdn.site", "industry": "Bollywood",
            "country": "India", "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(
                "Loopback Film", 2024),
            "releases": [{
                "release_title": "Loopback Film 720p", "quality": "720p",
                "codec": "x264", "size": "1.5GB", "languages": '["Hindi"]',
                "season": "", "episode": "", "intermediate_url": "",
                "origin_url": "", "source_site": "somecdn.site",
                "sources": [
                    {"source_name": "CDN", "service": "google_cdn",
                     "resource_id": "LB-MAIN", "source_url": self.media_url,
                     "final_url": self.media_url, "playback_type": "direct",
                     "is_temporary": 0, "status": "active"},
                    {"source_name": "CDN", "service": "google_cdn",
                     "resource_id": "LB-NULL",
                     "source_url": self.media_url.replace(
                         "/film.mp4", "/film2.mp4"),
                     "final_url": self.media_url.replace(
                         "/film.mp4", "/film2.mp4"),
                     "playback_type": "direct",
                     "is_temporary": 0, "status": "active"},
                ],
            }],
        }
        fast_fetch.save_scraped_data(data, enrich_metadata=False,
                                     ensure_db=False)
        for row in self.conn.execute(
                "SELECT id, source_url FROM download_sources").fetchall():
            self.conn.execute(
                "UPDATE download_sources SET final_url = ?, status = 'active',"
                " is_temporary = 0, is_resumable = 1, mime_type = 'video/mp4',"
                " http_status = 200, last_checked_at = CURRENT_TIMESTAMP"
                " WHERE id = ?", (row[1], row[0]))
        self.conn.commit()
        catalog_v2.project(self.conn, rev=1, verbose=False)
        # The divergence itself: a rebuild renumbers cat_links from 1 while
        # the ledger keeps its ids, so cat 501 names ledger 1 — exactly the
        # live shape (cat 1915585 naming ledger 903161). Evidence follows
        # the renumbering so the bundle's measured fields stay coherent.
        self.conn.execute("UPDATE cat_links SET id = id + ?", (CAT_ID_OFFSET,))
        self.conn.execute(
            "UPDATE cat_link_evidence SET link_id = link_id + ?",
            (CAT_ID_OFFSET,))
        # LB-NULL is the row a projection predating `ledger_link_id` leaves
        # behind: present in the catalog, with no ledger row to press.
        self.conn.execute(
            "UPDATE cat_links SET ledger_link_id = NULL"
            " WHERE resource_id = 'LB-NULL'")
        self.conn.commit()
        self.release_id = int(self.conn.execute(
            "SELECT id FROM cat_releases").fetchone()[0])
        self.main_cat_id, self.main_ledger_id = self._link_ids("LB-MAIN")
        self.null_cat_id = self._link_ids("LB-NULL")[0]

    def _link_ids(self, tag):
        row = self.conn.execute(
            "SELECT id, ledger_link_id FROM cat_links WHERE resource_id = ?",
            (tag,)).fetchone()
        self.assertIsNotNone(row, f"no cat_links row for tag {tag}")
        return int(row[0]), (int(row[1]) if row[1] is not None else None)

    # ---- the wire ---------------------------------------------------------
    def token(self, ledger_id):
        return redact.mint_token(int(ledger_id), SECRET)

    def fetch(self, path, *, follow=False, headers=None):
        opener = (urllib.request.build_opener() if follow else
                  urllib.request.build_opener(_NoRedirect))
        request = urllib.request.Request(
            self.public_url + path, headers=headers or {})
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def v2_get(self, path, query=None):
        """One `api_v2.route_get` call, no socket (resolve/feed live here)."""
        handler = _ReplyHandler()
        params = {k: [str(v)] for k, v in (query or {}).items()}
        ok = api_v2.route_get(handler, path, params, db_path=self.db_path,
                              operator=False, base_url="http://our.host",
                              secret=SECRET)
        self.assertTrue(ok, f"route_get refused {path}")
        reply = handler.replies[0]
        return reply["status"], reply["body"], reply["payload"]

    def bundle(self):
        bundle = catalog_api.play_bundle(
            self.conn, release_id=self.release_id)
        self.assertTrue(bundle.get("ok"), bundle)
        return bundle

    def candidate(self, bundle, cat_id):
        for link in bundle.get("candidates") or []:
            if int(link["link_id"]) == int(cat_id):
                return link
        self.fail(f"no candidate with link_id {cat_id} in {bundle}")

    def parse(self, handle):
        return redact.parse_token(handle, SECRET, signed_only=True)

    # ---- (a) the mint -------------------------------------------------------
    def test_link_view_mints_the_ledger_id_not_the_cat_id(self):
        """Session 111 (a): the handle names the ledger row, not the print."""
        link = self.candidate(self.bundle(), self.main_cat_id)
        self.assertNotEqual(link["link_id"], self.main_ledger_id,
                            "fixture failed to diverge the two universes")
        handle = link["stream_id"]
        self.assertIsNotNone(handle, "a linked copy carries no handle")
        self.assertNotEqual(handle, str(link["link_id"]),
                            "the opaque id is the row id in disguise")
        self.assertEqual(self.parse(handle), self.main_ledger_id,
                         "the handle is not the ledger row the bundle named")

    # ---- (b) the press ------------------------------------------------------
    def test_the_bundles_own_handle_plays_through_v1_stream(self):
        """Session 111 (b): the bundle's own handle 302s, live, no mock.

        Old code: the handle parsed to cat 501, no ledger row 501 exists,
        /api/v1/stream 404'd — the exact live shape for work_id 54221.
        """
        link = self.candidate(self.bundle(), self.main_cat_id)
        status, headers, _body = self.fetch(
            f"/api/v1/stream?id={urllib.parse.quote(link['stream_id'])}")
        self.assertEqual(status, 302, _body)
        self.assertEqual(headers.get("Location"), self.media_url)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    # ---- (c) no ledger id, no handle ----------------------------------------
    def test_a_link_without_a_ledger_id_carries_no_playable_handle(self):
        """Session 111 (c): NULL ledger_link_id means no handle, not a lie.

        The row stays in the bundle (zero data loss — it is still listed,
        still counted) but it must never win a play tier or travel as a
        backup: the tier's auto pick is the linked copy, and no backup
        handle names the unlinked row.
        """
        bundle = self.bundle()
        link = self.candidate(bundle, self.null_cat_id)
        self.assertIsNone(link["stream_id"],
                          "an unlinked row must not carry a stream handle")
        self.assertFalse(link["playable"],
                         "an unlinked row must not read as playable")
        auto = bundle.get("auto") or {}
        self.assertTrue(auto.get("playable"),
                        "the tier with a linked copy must stay playable")
        winner = (bundle.get("tiers") or [{}])[0].get("link") or {}
        self.assertEqual(self.parse(winner.get("stream_id")),
                         self.main_ledger_id,
                         "the tier winner is not the linked copy")
        for tier in bundle.get("tiers") or []:
            self.assertNotIn(None, tier.get("backup_handles") or [])
            for handle in tier.get("backup_handles") or []:
                self.assertNotEqual(self.parse(handle), self.null_cat_id)

    # ---- (d) the direct mint still works ------------------------------------
    def test_a_directly_minted_ledger_handle_still_resolves(self):
        """Session 111 (d): the old proof shape is unchanged by the fix.

        Minted-handle presses proved the resolver before, and still do: a
        token minted straight from the ledger id 302s to the media URL.
        This passes on the old code too — it is the no-regression guard.
        """
        status, headers, _body = self.fetch(
            f"/api/v1/stream?id={self.token(self.main_ledger_id)}")
        self.assertEqual(status, 302, _body)
        self.assertEqual(headers.get("Location"), self.media_url)

    # ---- (e) the resolve JSON -----------------------------------------------
    def test_the_resolve_route_names_the_ledger_id_as_stream_id(self):
        """Session 111 (e): /resolve's `stream_id` is a v1 handle, not an echo.

        The route's own namespace is the cat id (`link_ref`), but a field
        named `stream_id` is pressed at /api/v1/stream — so it must mint
        the ledger id. A row with no ledger id carries None there too.
        """
        handle = redact.mint_token(self.main_cat_id, SECRET)
        status, _body, payload = self.v2_get(
            f"/api/v2/resolve/{handle}", {"redirect": "0"})
        self.assertEqual(status, 200, _body)
        self.assertEqual(self.parse(payload["link_ref"]), self.main_cat_id)
        self.assertEqual(self.parse(payload["stream_id"]), self.main_ledger_id)
        self.assertNotEqual(payload["link_ref"], payload["stream_id"],
                            "the two handles name two different universes")
        null_handle = redact.mint_token(self.null_cat_id, SECRET)
        status, _body, payload = self.v2_get(
            f"/api/v2/resolve/{null_handle}", {"redirect": "0"})
        self.assertEqual(status, 200, _body)
        self.assertEqual(self.parse(payload["link_ref"]), self.null_cat_id)
        self.assertIsNone(payload["stream_id"],
                          "an unlinked row must not carry a stream handle")

    # ---- (f) the feed stays cat-native ---------------------------------------
    def test_feed_handles_stay_cat_native(self):
        """Regression guard: /feed.m3u handles address /resolve, not /stream.

        The feed's handles are link_refs (cat ids) by design — the audit
        must not 'fix' them into ledger ids, or every playlist entry would
        resolve the wrong link (or none) at /resolve.
        """
        status, body, _payload = self.v2_get("/api/v2/feed.m3u")
        self.assertEqual(status, 200, body)
        cat_ids = {int(r[0]) for r in self.conn.execute(
            "SELECT id FROM cat_links").fetchall()}
        handles = [urllib.parse.unquote(line.rsplit("/", 1)[-1])
                   for line in body.decode("utf-8").splitlines()
                   if line and not line.startswith("#")]
        self.assertTrue(handles, "the feed named no links")
        for handle in handles:
            resolved = self.parse(handle)
            self.assertIsNotNone(resolved, handle)
            self.assertIn(resolved, cat_ids,
                          "a feed handle does not name a cat link")


if __name__ == "__main__":
    print("fixture: %s (offline — loopback servers only, no catalog read)"
          % Path(__file__).name)
    unittest.main(verbosity=2)
