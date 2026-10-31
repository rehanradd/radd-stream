#!/usr/bin/env python3
"""A flagged work is auditable on the operator port and unplayable there.

The root law (`AGENTS.md`, "What This Is NOT" → the adult invariant) is that no
public surface may list *or play* an `is_18_plus = 1` row, while the operator panel
must keep seeing the row — an audit of flag coverage needs the badge, and Zero Data
Loss needs the URL to stay in the ledger. Both halves were true and both are still
true; what was not true is the middle:

  * `fetch_database_payload(full=True)` handed the dashboard every column of every
    source row, including `final_url`, `source_url`, `resource_id` and the release's
    `intermediate_url`. The panel then rendered **Copy Direct URL**, **▶ Play JIT**
    and **⚡ Stream / DL** for a flagged work, so the operator's own page published
    the upstream file address of an adult title. The endpoints behind those buttons
    refuse (`redact.link_is_adult`, unknown id ⇒ refuse), so nothing played — but a
    raw hoster URL pasted into a browser never touches our endpoints at all.
  * `/api/m3u` already returned `""` for a flagged post, and the dashboard still
    rendered a **📺 VLC Playlist** anchor pointed at that empty file.

The fix is a projection, not a deletion: `_withhold_playable` strips the playable
columns from the JSON of a flagged row and puts a `playback_withheld` note in their
place, and the dashboard renders the note instead of the buttons. The stored rows
are untouched — this edits the answer, never the ledger.

What this suite proves, in order:

  1. a flagged row's operator payload carries none of `_WITHHELD_PLAYABLE`, and none
     of its upstream file addresses appear anywhere in the serialized body;
  2. the audit survives: the flag, the badge data, the hoster's name and `service`,
     the row's status, health, size and mime all stay, and the refusal is *named*;
  3. an unflagged row still publishes all of it — this is not a blanket filter;
  4. the `🔞 18+ ADULT` badge stays operator-only: the public (`full=False`) payload
     never lists the flagged post at all;
  5. the row id the panel still shows is not a play — over a real loopback socket,
     `/api/v1/stream?id=<flagged source id>` and `/api/v1/download?id=…` both answer
     404 and `fast_fetch.resolve_live_source` is never called for it;
  6. the dashboard HTML builds the playlist anchor and the source buttons behind the
     flag, and renders the withheld note.

The unknown-id contradiction is resolved in favour of the documented law (2026-10-31):
`redact.link_is_adult` used to return `bool(row and row[0])`, so an unknown link id
answered **False** while its docstring and root `AGENTS.md` claimed True. It now refuses
a missing row on both branches — an id that was never minted and a link whose release or
post has gone — so `/api/v1/stream?id=999999999` is answered `not_found` before
`resolve_live_source` sees it. The test that pinned the old behaviour
(`..._reaches_the_resolver_today`) is flipped with it; the suite's `resolved` recorder
proves the resolver is not called.

Offline: a `tempfile` catalog, real `HTTPServer` bound to 127.0.0.1 with port 0 (the
process, not nginx, which forwards neither port), no network — `resolve_live_source`
is mocked to fail the test if it is ever called.

    python3 -S Fast_Fetch/test_operator_adult_projection.py
"""
from __future__ import annotations

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

import fast_fetch    # noqa: E402
import redact        # noqa: E402
import viewer        # noqa: E402

TOKEN = "adult-projection-suite-credential"

#: The upstream addresses this fixture seeds, so a test can name exactly what must
#: not be in the answer instead of asserting on a shape.
ADULT_PAGE = "https://adultsite.example/flagged-film/"
ADULT_RELEASE_BRIDGE = "https://adultsite.example/bridge/1"
ADULT_SOURCE_URL = "https://adultsite.example/watch-1"
ADULT_FILE_URL = "https://cdn-hoster.example/file/flagged-1080p.mp4"
ADULT_RESOURCE_ID = "flagged-resource-777"
CLEAN_FILE_URL = "https://cdn-hoster.example/file/clean-1080p.mp4"


def _media(slug, *, adult, title, page, bridge, source_url, final_url,
           resource_id):
    return {
        "url": page,
        "slug": slug,
        "title": title,
        "clean_title": title,
        "year": 2024,
        "content_type": "movie",
        "seasons": None,
        "poster_url": None,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": None,
        "synopsis": None,
        # The flag is set explicitly and with a neutral title, so a test that reads
        # `is_18_plus` is reading the stored column and not the title heuristic
        # `save_scraped_data` also applies.
        "is_18_plus": 1 if adult else 0,
        "is_animated": 0,
        "source_site": "adultsite" if adult else "cleansite",
        "industry": "Hollywood",
        "country": "USA",
        "language": "English",
        "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
        "tmdb_id": None,
        "imdb_id": None,
        "releases": [{
            "release_title": f"{title} 1080p",
            "quality": "1080p",
            "codec": "x264",
            "size": "1GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": bridge,
            "sources": [{
                "source_name": "Flagged CDN" if adult else "Clean CDN",
                "service": "test-service",
                "resource_id": resource_id,
                "source_url": source_url,
                "final_url": final_url,
                "is_temporary": 0,
            }],
        }],
    }


def _seed_adult():
    return _media("flagged-film", adult=True, title="Flagged Film", page=ADULT_PAGE,
                  bridge=ADULT_RELEASE_BRIDGE, source_url=ADULT_SOURCE_URL,
                  final_url=ADULT_FILE_URL, resource_id=ADULT_RESOURCE_ID)


def _seed_clean():
    return _media("clean-film", adult=False, title="Clean Film",
                  page="https://cleansite.example/clean-film/",
                  bridge="https://cleansite.example/bridge/2",
                  source_url="https://cleansite.example/watch-2",
                  final_url=CLEAN_FILE_URL, resource_id="clean-resource-888")


class CatalogFixture(unittest.TestCase):
    """One temp catalog holding exactly one flagged work and one clean work."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "catalog.db"
        self.addCleanup(self.tmp.cleanup)
        for target in (fast_fetch, viewer):
            patcher = mock.patch.object(target, "DB_PATH", self.db_path)
            patcher.start()
            self.addCleanup(patcher.stop)
        cinemeta = mock.patch.object(fast_fetch, "fetch_cinemeta_metadata",
                                     return_value=None)
        cinemeta.start()
        self.addCleanup(cinemeta.stop)
        fast_fetch.init_db()
        fast_fetch.save_scraped_data(_seed_adult())
        fast_fetch.save_scraped_data(_seed_clean())
        with sqlite3.connect(self.db_path) as conn:
            self.adult_post = int(conn.execute(
                "SELECT id FROM posts WHERE slug = 'flagged-film'").fetchone()[0])
            self.clean_post = int(conn.execute(
                "SELECT id FROM posts WHERE slug = 'clean-film'").fetchone()[0])
            self.adult_source = int(conn.execute(
                "SELECT s.id FROM download_sources s JOIN releases r ON r.id = s.release_id"
                " WHERE r.post_id = ?", (self.adult_post,)).fetchone()[0])
            self.clean_source = int(conn.execute(
                "SELECT s.id FROM download_sources s JOIN releases r ON r.id = s.release_id"
                " WHERE r.post_id = ?", (self.clean_post,)).fetchone()[0])

    def operator_payload(self, **kwargs):
        return viewer.fetch_database_payload("", full=True, limit=50, page=1, **kwargs)

    def post_in(self, payload, post_id):
        for post in payload["posts"]:
            if post["id"] == post_id:
                return post
        raise AssertionError(f"post {post_id} is not in the operator payload: "
                             f"{[p['id'] for p in payload['posts']]}")

    def sources_of(self, post):
        return [source for release in post["releases"] for source in release["sources"]]


class WithheldProjectionTests(CatalogFixture):
    """The operator's JSON for a flagged work has no way to watch it in."""

    def test_a_flagged_source_publishes_no_playable_field(self):
        post = self.post_in(self.operator_payload(), self.adult_post)
        for source in self.sources_of(post):
            for column in viewer._WITHHELD_PLAYABLE:
                self.assertNotIn(column, source,
                                 f"a flagged row published {column} to the panel")
            self.assertNotIn("stream_id", source,
                             "the ledger view mints no handle for any row")
        for release in post["releases"]:
            self.assertNotIn("intermediate_url", release)

    def test_the_withholding_is_named_rather_than_an_empty_button(self):
        post = self.post_in(self.operator_payload(), self.adult_post)
        for source in self.sources_of(post):
            self.assertEqual(source["playback_withheld"], viewer.WITHHELD_NOTE)
        for release in post["releases"]:
            self.assertEqual(release["playback_withheld"], viewer.WITHHELD_NOTE)

    def test_no_upstream_file_address_of_a_flagged_work_reaches_the_wire(self):
        """The strongest form: serialize the whole answer and look for the strings.

        A key-by-key assertion only proves the fields we thought of. This proves the
        seeded hoster URL, bridge, watch URL and hoster file id are nowhere in what
        the dashboard receives, whatever key they might have travelled under."""
        body = json.dumps(self.operator_payload())
        for leaked in (ADULT_FILE_URL, ADULT_SOURCE_URL, ADULT_RELEASE_BRIDGE,
                       ADULT_RESOURCE_ID):
            self.assertNotIn(leaked, body, leaked)

    def test_the_audit_of_a_flagged_row_survives(self):
        """Withholding play is not withholding the flag — that would defeat the
        reason the panel shows these rows at all."""
        post = self.post_in(self.operator_payload(), self.adult_post)
        self.assertEqual(int(post["is_18_plus"]), 1)
        self.assertEqual(post["clean_title"], "Flagged Film")
        self.assertEqual(post["url"], ADULT_PAGE)      # the page it was scraped from
        source = self.sources_of(post)[0]
        for kept in ("id", "release_id", "source_name", "service", "status",
                     "is_resumable", "file_size_bytes", "mime_type",
                     "playback_type", "is_temporary"):
            self.assertIn(kept, source, kept)
        self.assertEqual(source["source_name"], "Flagged CDN")
        self.assertEqual(source["service"], "test-service")

    def test_an_unflagged_row_still_publishes_everything_it_used_to(self):
        """This is a projection for flagged rows, not a global field filter: a
        healer that lost `final_url` would stop being able to do its job."""
        post = self.post_in(self.operator_payload(), self.clean_post)
        source = self.sources_of(post)[0]
        for column in ("source_url", "final_url", "resource_id"):
            self.assertIn(column, source, column)
        self.assertEqual(source["final_url"], CLEAN_FILE_URL)
        self.assertNotIn("playback_withheld", source)
        self.assertIn("intermediate_url", post["releases"][0])
        self.assertEqual(post["releases"][0]["intermediate_url"],
                         "https://cleansite.example/bridge/2")

    def test_the_stored_rows_are_untouched_by_the_projection(self):
        """Zero Data Loss: the ledger keeps the URL, the answer does not publish it."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT final_url, resource_id FROM download_sources"
                               " WHERE id = ?", (self.adult_source,)).fetchone()
        self.assertEqual(row[0], ADULT_FILE_URL)
        self.assertEqual(row[1], ADULT_RESOURCE_ID)

    def test_the_projection_is_a_copy_and_does_not_mutate_the_row(self):
        clean = {"id": 1, "final_url": "x", "source_url": "y", "resource_id": "z"}
        withheld = viewer._withhold_playable(clean)
        self.assertEqual(clean, {"id": 1, "final_url": "x", "source_url": "y",
                                 "resource_id": "z"})
        self.assertNotIn("final_url", withheld)
        self.assertEqual(withheld["id"], 1)


class PublicSurfaceUnchangedTests(CatalogFixture):
    """The badge is operator-only and the public reads do not change shape."""

    def test_the_public_payload_never_lists_the_flagged_work(self):
        payload = viewer.fetch_database_payload("", full=False, limit=50, page=1)
        ids = [post["id"] for post in payload["posts"]]
        self.assertIn(self.clean_post, ids)
        self.assertNotIn(self.adult_post, ids,
                         "the 18+ badge is an operator audit tool, not a public row")

    def test_the_public_projection_still_mints_its_own_handles(self):
        payload = viewer.fetch_database_payload("", full=False, limit=50, page=1)
        post = self.post_in(payload, self.clean_post)
        source = self.sources_of(post)[0]
        self.assertIn("stream_id", source)
        self.assertNotIn("final_url", source,
                         "the public answer already named no hoster; that did not move")

    def test_the_flagged_works_playlist_is_still_empty_on_both_ports(self):
        self.assertEqual(viewer.generate_m3u_playlist(self.adult_post, full=True), "")
        self.assertEqual(viewer.generate_m3u_playlist(self.adult_post, full=False), "")
        clean = viewer.generate_m3u_playlist(self.clean_post, full=True)
        self.assertIn(CLEAN_FILE_URL, clean)


class OperatorSocketTests(CatalogFixture):
    """Over a real loopback socket: the id the panel still shows is not a play."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict("os.environ", {
            "RADD_ADMIN_TOKEN": TOKEN,
            "RADD_SIGNING_SECRET": "adult-projection-test-secret",
            "RADD_USER_STATE_DB": str(Path(self.tmp.name) / "user_state.db"),
        })
        env.start()
        self.addCleanup(env.stop)
        # The refusal must happen before any resolution: reaching the resolver would
        # mean the server had already agreed to serve the link. The probe records the
        # call instead of raising, so a failure names the link that got resolved.
        self.resolved = []
        resolver = mock.patch.object(
            fast_fetch, "resolve_live_source",
            side_effect=lambda source_id, **kwargs: (
                self.resolved.append(source_id)
                or {"success": False, "error": "no_playable_source"}))
        resolver.start()
        self.addCleanup(resolver.stop)
        self.server = viewer.make_server("127.0.0.1", 0, operator=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(self, path, token=TOKEN):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib.request.Request(self.url + path, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_the_ledger_feed_over_the_wire_withholds_the_flagged_row(self):
        status, body = self.get("/api/data?limit=50")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        text = json.dumps(payload)
        for leaked in (ADULT_FILE_URL, ADULT_SOURCE_URL, ADULT_RESOURCE_ID):
            self.assertNotIn(leaked, text, leaked)
        post = self.post_in(payload, self.adult_post)
        self.assertEqual(self.sources_of(post)[0]["playback_withheld"],
                         viewer.WITHHELD_NOTE)

    def test_a_flagged_source_id_never_reaches_the_resolver(self):
        """`/api/v1/stream` on the operator port accepts a bare row id (the operator's
        own curl and healing scripts depend on it), and the panel still shows that id
        for a flagged row. That id is not a play: `link_is_adult` refuses it before
        the server resolves anything, and the answer is the one a link that does not
        exist gets."""
        self.assertTrue(redact.link_is_adult(self.adult_source, self.db_path))
        self.assertFalse(redact.link_is_adult(self.clean_source, self.db_path))
        stream = self.get(f"/api/v1/stream?id={self.adult_source}&redirect=1")
        self.assertEqual(stream[0], 404, stream)
        self.assertIn(b"not_found", stream[1])
        download = self.get(f"/api/v1/download?id={self.adult_source}")
        self.assertEqual(download[0], 404, download)
        self.assertEqual(self.resolved, [],
                         f"a flagged link was resolved: {self.resolved}")

    def test_an_unrecognized_link_id_is_refused_before_the_resolver(self):
        """Was a characterization of `bool(row and row[0])` answering False.

        Flipped with the fail-closed `redact.link_is_adult` (2026-10-31): an id that
        exists nowhere is refused by the adult guard, with the same 404 a flagged row
        gets, and `resolve_live_source` is never called for it."""
        unknown = self.get("/api/v1/stream?id=999999999&redirect=1")
        self.assertEqual(unknown[0], 404, unknown)
        self.assertEqual(self.resolved, [],
                         "an unknown id must not reach the resolver")
        self.assertTrue(redact.link_is_adult(999999999, self.db_path))

    def test_the_flagged_works_playlist_over_the_wire_is_zero_bytes(self):
        status, body = self.get(f"/api/m3u?id={self.adult_post}")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"", body[:80])


class DashboardRenderingTests(unittest.TestCase):
    """The page builds its handles behind the flag, not beside it."""

    def test_the_vlc_playlist_anchor_is_built_behind_the_flag(self):
        html = viewer.DASHBOARD_HTML
        guard = html.index("p.is_18_plus")
        anchor = html.index('/api/m3u?id=${p.id}')
        self.assertLess(guard, anchor,
                        "the playlist anchor must be inside the flag's ternary")
        self.assertIn("🔞 no playlist", html)

    def test_the_source_buttons_are_built_from_the_withheld_note(self):
        html = viewer.DASHBOARD_HTML
        self.assertIn("s.playback_withheld", html)
        self.assertIn("${withheld}", html)
        block = html[html.index("const withheld"):]
        block = block[:block.index("html += `")]
        for handle in ("Play JIT", "Copy Direct URL", "/api/v1/stream?id="):
            self.assertIn(handle, block,
                          "the buttons exist, but only in the un-withheld branch")

    def test_the_adult_badge_is_rendered_for_a_flagged_row(self):
        self.assertIn("badge-18", viewer.DASHBOARD_HTML)
        self.assertIn("🔞 18+ ADULT", viewer.DASHBOARD_HTML)


if __name__ == "__main__":
    print("fixture: %s (offline — temp SQLite + one loopback socket, no network, "
          "no production catalog)" % Path(__file__).name)
    unittest.main(verbosity=2)
