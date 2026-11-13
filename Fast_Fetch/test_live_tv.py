"""Tests for the Live TV tab backend: registry, channels endpoint, TV handles.

The fixture registry points at a fake playlist server on loopback, so no
test here touches the network. The real seeded registry is only loaded and
validated (shape + counts), never probed.
"""

import copy
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import live_tv
import redact
import viewer

SECRET = "live-tv-test-secret"

MASTER_PLAYLIST = (
    b"#EXTM3U\n"
    b"#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=640x360\n"
    b"live-360.m3u8\n"
    b"#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720\n"
    b"live-720.m3u8\n"
)


class _PlaylistHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/live.m3u8":
            self.send_response(200)
            self.send_header("Content-Type",
                             "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(MASTER_PLAYLIST)))
            self.end_headers()
            self.wfile.write(MASTER_PLAYLIST)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args):  # keep the test output readable
        pass


def _fixture_registry(media_base):
    def channel(channel_id, name, category, path, source, enabled=True):
        return {
            "id": channel_id,
            "name": name,
            "category": category,
            "country": "PK",
            "language": "ur",
            "logo_url": "https://example.test/logo%d.png" % channel_id,
            "stream_url": media_base + path,
            "source": source,
            "verified_at": "2026-11-08T19:25:00Z",
            "enabled": enabled,
            "disabled_reason": "" if enabled else "third-party restream",
        }

    return {
        "version": "1.0",
        "updated_at": "2026-11-08T19:25:00Z",
        "channels": [
            channel(1, "Test News One", "news", "/live.m3u8", "official"),
            channel(2, "Test Sports One", "sports", "/live.m3u8",
                    "public-broadcaster"),
            channel(3, "Test Disabled", "news", "/live.m3u8", "aggregator",
                    enabled=False),
            channel(4, "Test Dead", "news", "/dead.m3u8", "official"),
        ],
    }


class LiveTvFixture(unittest.TestCase):
    def setUp(self):
        self._old_env = os.environ.get("RADD_STREAM_SECRET")
        os.environ["RADD_STREAM_SECRET"] = SECRET
        self._old_signing = viewer._SIGNING_SECRET
        viewer._SIGNING_SECRET = None
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.media = ThreadingHTTPServer(("127.0.0.1", 0), _PlaylistHandler)
        threading.Thread(target=self.media.serve_forever, daemon=True).start()
        self.addCleanup(self.media.shutdown)
        self.addCleanup(self.media.server_close)
        self.media_base = (
            f"http://127.0.0.1:{self.media.server_address[1]}")

        self.registry_path = Path(self.tmp.name) / "live_tv_registry.json"
        self.registry_path.write_text(
            json.dumps(_fixture_registry(self.media_base)),
            encoding="utf-8")
        self._old_registry_path = live_tv.REGISTRY_PATH
        live_tv.REGISTRY_PATH = str(self.registry_path)
        live_tv.clear_cache()
        self.registry = live_tv.load_registry()

        self.public = viewer.make_server("127.0.0.1", 0, operator=False)
        threading.Thread(target=self.public.serve_forever, daemon=True).start()
        self.addCleanup(self.public.shutdown)
        self.addCleanup(self.public.server_close)
        self.public_port = self.public.server_address[1]

    def tearDown(self):
        live_tv.REGISTRY_PATH = self._old_registry_path
        live_tv.clear_cache()
        viewer._SIGNING_SECRET = self._old_signing
        if self._old_env is None:
            os.environ.pop("RADD_STREAM_SECRET", None)
        else:
            os.environ["RADD_STREAM_SECRET"] = self._old_env

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.public_port,
                                          timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def _tv_handle(self, channel_id, **kwargs):
        return redact.mint_live_tv_handle(channel_id, SECRET, **kwargs)


class RegistryValidationTests(LiveTvFixture):
    def test_fixture_loads(self):
        self.assertEqual(len(self.registry["channels"]), 4)

    def test_duplicate_id_rejected(self):
        bad = copy.deepcopy(self.registry)
        bad["channels"][1]["id"] = 1
        with self.assertRaises(ValueError):
            live_tv.validate_registry(bad)

    def test_unknown_category_rejected(self):
        bad = copy.deepcopy(self.registry)
        bad["channels"][0]["category"] = "reality"
        with self.assertRaises(ValueError):
            live_tv.validate_registry(bad)

    def test_plain_http_stream_url_rejected(self):
        bad = copy.deepcopy(self.registry)
        bad["channels"][0]["stream_url"] = (
            "http://example.test/live.m3u8")
        with self.assertRaises(ValueError):
            live_tv.validate_registry(bad)

    def test_non_playlist_stream_url_rejected(self):
        bad = copy.deepcopy(self.registry)
        bad["channels"][0]["stream_url"] = "https://example.test/live.mp4"
        with self.assertRaises(ValueError):
            live_tv.validate_registry(bad)

    def test_empty_channels_rejected(self):
        with self.assertRaises(ValueError):
            live_tv.validate_registry({"version": "1.0", "channels": []})

    def test_missing_registry_raises(self):
        with self.assertRaises(ValueError):
            live_tv.load_registry("/nonexistent/live_tv_registry.json")


class ProjectionTests(LiveTvFixture):
    def test_only_enabled_channels_listed(self):
        shown = live_tv.list_channels(self.registry, secret=SECRET)
        self.assertEqual([c["id"] for c in shown], [1, 2, 4])

    def test_projection_hides_upstream_url_and_source(self):
        for shown in live_tv.list_channels(self.registry, secret=SECRET):
            self.assertNotIn("stream_url", shown)
            self.assertNotIn("source", shown)
            self.assertNotIn("disabled_reason", shown)
            self.assertEqual(
                sorted(shown.keys()),
                ["category", "country", "id", "language", "logo_url",
                 "name", "stream_id"])

    def test_stream_id_round_trips_to_channel_id(self):
        for shown in live_tv.list_channels(self.registry, secret=SECRET):
            self.assertEqual(
                redact.parse_live_tv_handle(shown["stream_id"], SECRET),
                shown["id"])

    def test_category_filter(self):
        sports = live_tv.list_channels(self.registry, category="sports",
                                       secret=SECRET)
        self.assertEqual([c["id"] for c in sports], [2])
        self.assertEqual(
            live_tv.list_channels(self.registry, category="nope",
                                  secret=SECRET), [])

    def test_categories_only_for_enabled(self):
        self.assertEqual(live_tv.list_categories(self.registry),
                         ["news", "sports"])

    def test_get_channel_hides_disabled_and_unknown(self):
        self.assertIsNotNone(live_tv.get_channel(self.registry, 1))
        self.assertIsNone(live_tv.get_channel(self.registry, 3))
        self.assertIsNone(live_tv.get_channel(self.registry, 999))
        self.assertIsNone(live_tv.get_channel(self.registry, "nope"))


class ChannelsEndpointTests(LiveTvFixture):
    def test_list_all(self):
        status, _headers, body = self._get("/api/v1/live-tv/channels")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["success"])
        self.assertEqual([c["id"] for c in data["channels"]], [1, 2, 4])
        self.assertEqual(data["categories"], ["news", "sports"])

    def test_category_query(self):
        status, _headers, body = self._get(
            "/api/v1/live-tv/channels?category=sports")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual([c["name"] for c in data["channels"]],
                         ["Test Sports One"])

    def test_response_leaks_no_upstream_url(self):
        _status, _headers, body = self._get("/api/v1/live-tv/channels")
        self.assertNotIn(b".m3u8", body)
        self.assertNotIn(b"127.0.0.1", body)
        self.assertNotIn(b"example.test/live", body)


class StreamRouteTests(LiveTvFixture):
    def test_live_channel_302s_to_playlist(self):
        handle = self._tv_handle(1)
        status, headers, _body = self._get(
            "/api/v1/stream?id=" + handle)
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), self.media_base + "/live.m3u8")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_redirect_zero_returns_json_shape(self):
        handle = self._tv_handle(2)
        status, _headers, body = self._get(
            "/api/v1/stream?id=" + handle + "&redirect=0")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["success"])
        self.assertEqual(data["kind"], "url")
        self.assertEqual(data["mime_type"],
                         "application/vnd.apple.mpegurl")
        self.assertEqual(
            redact.parse_live_tv_handle(data["stream_id"], SECRET), 2)

    def test_dead_channel_honest_404(self):
        handle = self._tv_handle(4)
        status, _headers, body = self._get("/api/v1/stream?id=" + handle)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "no_playable_source")

    def test_disabled_channel_404s_like_missing(self):
        handle = self._tv_handle(3)
        status, _headers, body = self._get("/api/v1/stream?id=" + handle)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_unknown_channel_404s(self):
        handle = self._tv_handle(999)
        status, _headers, body = self._get("/api/v1/stream?id=" + handle)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_expired_handle_falls_through_to_movie_branch(self):
        handle = self._tv_handle(1, ttl_seconds=0, now=1000000)
        status, _headers, body = self._get("/api/v1/stream?id=" + handle)
        self.assertEqual(status, 400)
        self.assertIn(b"invalid source id", body.lower())

    def test_tampered_handle_rejected(self):
        handle = self._tv_handle(1)
        # Tamper the second-to-last char: it carries the high 6 bits of
        # the final tag byte, so any change alters the decoded tag. (The
        # final char's low 4 bits are base64 padding bits the decoder
        # ignores, so replacing the last two chars with "AA" is a 1-in-256
        # no-op whenever the tag's last byte happens to be 0x00 — that
        # flaked CI run 43445507410 with 302 instead of 400.)
        flipped = "B" if handle[-2] != "B" else "C"
        tampered = handle[:-2] + flipped + handle[-1]
        status, _headers, _body = self._get("/api/v1/stream?id=" + tampered)
        self.assertEqual(status, 400)


class SeededRegistryTests(unittest.TestCase):
    """The shipped registry itself: shape + counts, no network."""

    def test_seeded_registry_loads_and_counts(self):
        # 2026-11-11: panel dropped the 18 third-party restreams outright
        # (user order) and added 6 public test channels (ids 36-41), so the
        # shipped registry is now exactly the 23 live channels, all enabled.
        registry = live_tv.load_registry()
        self.assertEqual(len(registry["channels"]), 23)
        enabled = [c for c in registry["channels"] if c["enabled"]]
        self.assertEqual(len(enabled), 23)
        self.assertEqual(len({c["id"] for c in registry["channels"]}), 23)

    def test_seeded_enabled_sports_are_three(self):
        registry = live_tv.load_registry()
        sports = [c["name"] for c in registry["channels"]
                  if c["enabled"] and c["category"] == "sports"]
        self.assertEqual(sports, ["DD Sports", "Eurosport India", "FUEL TV"])

    def test_seeded_enabled_sources_are_official(self):
        registry = live_tv.load_registry()
        official = {"official", "official-group", "official-playout",
                    "official-fast", "official-cdn", "public-broadcaster",
                    "channel-cdn", "official-geoblocked"}
        for channel in registry["channels"]:
            if channel["enabled"]:
                self.assertIn(channel["source"], official)
            else:
                self.assertTrue(channel["disabled_reason"])


if __name__ == "__main__":
    unittest.main()
