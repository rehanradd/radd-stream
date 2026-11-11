#!/usr/bin/env python3
"""test_subtitle_tracks.py — gap A3: subtitle tracks in the v2 bundle (G-1).

The live catalog already holds 125,686 subtitle rows (`download_sources`
playback_type='subtitle', kisskh's eleven .vtt tracks per episode) — but the
projection fed them into `cat_links` as cloud_page rows, so the play ladder
carried .vtt files as if they were video, and the bundle's `tracks.subtitles`
was always empty. This suite proves the three halves of the fix:

  1. projection — a subtitle ledger row lands in `cat_subtitles` (lang parsed
     from the filename, format from the extension) and NEVER in `cat_links`;
  2. bundle — every link view of the print carries `tracks` with the audio the
     release declares and the subtitle tracks addressed by OUR OWN
     `/api/v2/subtitle/<handle>` route, with no upstream host anywhere in the
     payload (`redact.scrub` would strip a key named `url`, so the address
     rides as `subtitle_url`);
  3. route — `GET /api/v2/subtitle/{handle}` 302s to the stored file, and a
     video handle, a bad handle or a flagged work answers exactly like a
     missing track.

Stdlib only. In-memory ledger via `save_scraped_data` + `project`, no socket.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")

import api_v2
import catalog_api
import catalog_v2
import fast_fetch
import redact
import viewer

HOST = "http://our.host"
SECRET = "test-only-subtitle-secret"

#: The upstream hosts the fixture deliberately puts into the ledger, so that
#: finding either in a bundle payload is a proven leak rather than an empty test.
UPSTREAM_HOSTS = ("res.cloudinary.com", "sub.cdnauto.xyz")


def video(tag, *, status="unverified"):
    url = f"https://video-downloads.googleusercontent.com/{tag}"
    return {"source_name": "CDN", "service": "google_cdn", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "direct",
            "is_temporary": 0, "status": status}


def subtitle(lang_name, code, *, ext="vtt", host="res.cloudinary.com"):
    """One kisskh-shaped subtitle track: the name is the `source_name`, the code
    rides in the filename (`1.en.vtt`)."""
    url = (f"https://{host}/sub2t9/raw/upload/v1759504074/"
           f"Player%20Uncut/1.{code}.{ext}")
    return {"source_name": lang_name, "service": host, "resource_id": f"SUB-{code}",
            "source_url": url, "final_url": url, "playback_type": "subtitle",
            "is_temporary": 0, "status": "unverified"}


class SubtitleFixture(unittest.TestCase):
    """One projected corpus per test: full isolation, no shared mutable state."""

    def setUp(self):
        os.environ["RADD_STREAM_SECRET"] = SECRET
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "subs.db"
        self._patches = [
            unittest.mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
            unittest.mock.patch.object(viewer, "DB_PATH", self.db_path),
        ]
        for patcher in self._patches:
            patcher.start()
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        for patcher in self._patches:
            patcher.stop()
        self.tmp.cleanup()

    def add_post(self, *, title="Example Film", year=2024, is_18_plus=0,
                 sources=(), languages='["Hindi"]'):
        data = {
            "url": f"https://example.test/{title.lower().replace(' ', '-')}-{year}/",
            "slug": f"{title.lower().replace(' ', '-')}-{year}",
            "title": f"{title} ({year})", "clean_title": title, "year": year,
            "content_type": "movie", "seasons": None,
            "poster_url": "https://cdn/poster.jpg", "backdrop_urls": None,
            "imdb_rating": 7.5, "genres": '["Action"]',
            "synopsis": f"{title} synopsis", "is_18_plus": is_18_plus,
            "is_animated": 0, "source_site": "example",
            "industry": "Bollywood", "country": "India", "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(title, year),
            "tmdb_id": None, "imdb_id": None,
            "releases": [{
                "release_title": f"{title} ({year}) 1080p",
                "season": "", "episode": "", "quality": "1080p", "codec": "x264",
                "size": "1.5GB", "languages": languages,
                "intermediate_url": "", "origin_url": "", "source_site": "",
                "sources": list(sources),
            }],
        }
        post_id = fast_fetch.save_scraped_data(data, enrich_metadata=False,
                                               ensure_db=False)
        self.conn.commit()
        return post_id

    def project(self):
        self.conn.commit()
        return catalog_v2.project(self.conn, rev=1, verbose=False)

    def subtitles(self, release_id):
        return self.conn.execute(
            "SELECT * FROM cat_subtitles WHERE release_id = ? ORDER BY id",
            (release_id,)).fetchall()

    def links(self, release_id):
        return self.conn.execute(
            "SELECT * FROM cat_links WHERE release_id = ?", (release_id,)).fetchall()


# ── 1. projection ────────────────────────────────────────────────────────────

class SubtitleProjectionTests(SubtitleFixture):

    def test_subtitle_rows_project_to_cat_subtitles_not_cat_links(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en"),
                               subtitle("Arabic", "ar", host="sub.cdnauto.xyz")])
        summary = self.project()
        self.assertEqual(summary.get("subtitles"), 2)
        work = self.conn.execute("SELECT id FROM cat_works").fetchone()
        release = self.conn.execute(
            "SELECT id FROM cat_releases WHERE work_id = ?", (work["id"],)).fetchone()
        subs = self.subtitles(release["id"])
        self.assertEqual([(row["lang"], row["format"]) for row in subs],
                         [("en", "vtt"), ("ar", "vtt")])
        self.assertEqual([row["label"] for row in subs], ["English", "Arabic"])
        self.assertTrue(all(row["ledger_link_id"] for row in subs))
        links = self.links(release["id"])
        self.assertEqual(len(links), 1, "only the video row may be a link")
        self.assertNotIn("vtt", (links[0]["url"] or "") + (links[0]["final_url"] or ""))

    def test_lang_falls_back_to_the_stored_name_when_the_filename_has_no_code(self):
        nameless = subtitle("English", "en")
        nameless["source_url"] = nameless["final_url"] = (
            "https://res.cloudinary.com/sub2t9/raw/upload/v1759504074/track.vtt")
        self.add_post(sources=[video("VID-1"), nameless])
        self.project()
        release = self.conn.execute("SELECT id FROM cat_releases").fetchone()
        subs = self.subtitles(release["id"])
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["lang"], "en")

    def test_unknown_format_is_stored_blank_not_invented(self):
        odd = subtitle("English", "en", ext="txt")
        self.add_post(sources=[video("VID-1"), odd])
        self.project()
        release = self.conn.execute("SELECT id FROM cat_releases").fetchone()
        subs = self.subtitles(release["id"])
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["format"], "")

    def test_reprojection_replaces_the_subtitle_table(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en")])
        self.project()
        self.project()
        release = self.conn.execute("SELECT id FROM cat_releases").fetchone()
        self.assertEqual(len(self.subtitles(release["id"])), 1,
                         "reset must clear cat_subtitles or rows double")


# ── 2. bundle ────────────────────────────────────────────────────────────────

class SubtitleBundleTests(SubtitleFixture):

    def _bundle(self):
        self.project()
        release = self.conn.execute("SELECT id FROM cat_releases").fetchone()
        bundle = catalog_api.play_bundle(self.conn, release_id=int(release["id"]),
                                         legacy_release_id=False)
        self.assertTrue(bundle.get("ok"), bundle)
        return bundle

    def test_link_views_carry_tracks_with_our_own_subtitle_addresses(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en"),
                               subtitle("Arabic", "ar", host="sub.cdnauto.xyz")])
        bundle = self._bundle()
        self.assertTrue(bundle["candidates"])
        for link in bundle["candidates"]:
            tracks = link["tracks"]
            self.assertEqual([item["lang"] for item in tracks["subtitles"]],
                             ["en", "ar"])
            self.assertEqual([item["kind"] for item in tracks["subtitles"]],
                             ["subtitles", "subtitles"])
            self.assertEqual([item["format"] for item in tracks["subtitles"]],
                             ["vtt", "vtt"])
            self.assertEqual([item["default"] for item in tracks["subtitles"]],
                             [True, False], "English is the house default")
            for item in tracks["subtitles"]:
                self.assertTrue(item["subtitle_url"].startswith("/api/v2/subtitle/"),
                                item)
                self.assertFalse(item["subtitle_url"].startswith("http"))
        dumped = json.dumps(bundle)
        for host in UPSTREAM_HOSTS:
            self.assertNotIn(host, dumped, "an upstream subtitle host leaked")

    def test_audio_tracks_come_from_the_release_descriptor(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en")],
                      languages='["Hindi", "English"]')
        bundle = self._bundle()
        audio = bundle["candidates"][0]["tracks"]["audio"]
        self.assertEqual([item["lang"] for item in audio], ["Hindi", "English"])
        self.assertEqual([item["default"] for item in audio], [True, False])

    def test_a_print_without_subtitles_still_serves_audio_and_an_empty_list(self):
        self.add_post(sources=[video("VID-1")])
        bundle = self._bundle()
        tracks = bundle["candidates"][0]["tracks"]
        self.assertEqual(tracks["subtitles"], [])
        self.assertEqual([item["lang"] for item in tracks["audio"]], ["Hindi"])


# ── 3. route ─────────────────────────────────────────────────────────────────

class FakeHandler:
    """The reply primitives `viewer.DashboardHandler` gives a route, recorded."""

    def __init__(self, headers=None):
        self.headers = dict(headers or {})
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

    def send_bytes(self, data, content_type="text/html; charset=utf-8", status=200,
                   extra_headers=None):
        headers = [("Content-Type", str(content_type)),
                   ("Content-Length", str(len(bytes(data)))),
                   ("Connection", "close")]
        headers.extend((str(k), str(v)) for k, v in (extra_headers or []))
        self.replies.append({"kind": "bytes", "status": int(status),
                             "headers": headers, "body": bytes(data),
                             "content_type": content_type, "payload": None})

    def send_json(self, data, status=200, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, content_type="application/json; charset=utf-8",
                        status=status, extra_headers=extra_headers)
        self.replies[-1]["payload"] = data


class SubtitleRouteTests(SubtitleFixture):

    def _get(self, path, *, operator=False):
        handler = FakeHandler()
        api_v2.route_get(handler, path, {}, db_path=str(self.db_path),
                         operator=operator, base_url=HOST, secret=SECRET)
        self.assertEqual(len(handler.replies), 1, "the route answered twice")
        return handler.replies[0]

    @staticmethod
    def _problem(reply):
        """The problem+json body: `problem()` writes it with `send_bytes`, so
        the recorded reply carries the JSON in `body`, not in `payload`."""
        return json.loads(reply["body"].decode("utf-8"))

    def _ledger_id(self, *, playback_type="subtitle"):
        row = self.conn.execute(
            "SELECT id FROM download_sources WHERE playback_type = ?",
            (playback_type,)).fetchone()
        self.assertIsNotNone(row, f"no ledger row with playback_type={playback_type}")
        return int(row["id"])

    def test_valid_handle_302s_to_the_stored_file(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en")])
        self.project()
        stored = self.conn.execute(
            "SELECT final_url FROM download_sources"
            " WHERE playback_type = 'subtitle'").fetchone()["final_url"]
        handle = redact.mint_token(self._ledger_id(), SECRET)
        reply = self._get(f"/api/v2/subtitle/{handle}")
        self.assertEqual(reply["status"], 302)
        self.assertIsNone(reply["payload"], "a redirect carries no JSON body")
        location = dict(reply["headers"]).get("Location", "")
        self.assertEqual(location, stored)
        self.assertEqual(dict(reply["headers"]).get("Cache-Control"), "no-store")

    def test_a_video_handle_answers_not_found_like_a_missing_track(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en")])
        self.project()
        handle = redact.mint_token(self._ledger_id(playback_type="direct"), SECRET)
        reply = self._get(f"/api/v2/subtitle/{handle}")
        self.assertEqual(reply["status"], 404)
        self.assertEqual(self._problem(reply)["code"], "not_found")

    def test_a_garbage_handle_is_invalid_not_a_leak(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en")])
        self.project()
        reply = self._get("/api/v2/subtitle/not-a-handle")
        self.assertEqual(reply["status"], 400)
        self.assertEqual(self._problem(reply)["code"], "invalid_params")

    def test_a_flagged_works_subtitle_answers_like_a_missing_track(self):
        self.add_post(title="Flagged Film", is_18_plus=1,
                      sources=[video("VID-1"), subtitle("English", "en")])
        self.project()
        handle = redact.mint_token(self._ledger_id(), SECRET)
        reply = self._get(f"/api/v2/subtitle/{handle}")
        self.assertEqual(reply["status"], 404)
        self.assertEqual(self._problem(reply)["code"], "not_found")

    def test_shape_without_a_handle_is_not_found(self):
        self.add_post(sources=[video("VID-1"), subtitle("English", "en")])
        self.project()
        reply = self._get("/api/v2/subtitle")
        self.assertEqual(reply["status"], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
