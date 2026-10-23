#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Offline tests for link_health.py — no third-party network traffic at all.

Every probe here hits a ``ThreadingHTTPServer`` that this file starts on
127.0.0.1 with an ephemeral port, and passes ``allow_private=True`` (which the
suite also proves is mandatory). Everything else is pure function math.

Run from the repo root:  python -S Fast_Fetch/test_link_health.py
"""

import http.client
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import link_health as lh

MP4_TOTAL = 1024 * 1024          # 1 MiB declared size for /movie.mp4
MP4_BODY = b"\x00\x00\x00\x18ftypmp42" + b"m" * (MP4_TOTAL - 12)  # mp4 magic
SMALL_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"a" * (128 * 1024 - 12)
HLS_MASTER = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=1280x720\n"
              b"720/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=600000\n480/index.m3u8\n")
EMBED_HTML = (b"<!doctype html><html><head><title>Bridge</title></head><body>"
              b"<iframe src=\"https://player.example.test/embed/abc\" width=640 height=360>"
              b"</iframe></body></html>")
ARTICLE_HTML = (b"<!doctype html><html><body><h1>Some article</h1>"
                b"<p>nothing playable here</p></body></html>")


# ── request handlers ─────────────────────────────────────────────────────────

class _Quiet(BaseHTTPRequestHandler):
    """Common plumbing: HTTP/1.1 so lengths are honoured, no stderr spam."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def handle(self):
        # a probe that times out closes mid-write; the resulting EPIPE is the
        # test's business, not a traceback on the console
        try:
            super().handle()
        except (OSError, http.client.HTTPException):
            pass

    # helpers ------------------------------------------------------------
    def requested_range(self):
        return self.headers.get("Range", "")

    def _send(self, status, body, ctype, *, length=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length if length is not None else len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)


class MediaHandler(_Quiet):
    """Range-capable CDN: 206 + Content-Range + Accept-Ranges + wildcard CORS."""

    seen_ranges = []          # class-level audit of what the probe asked for

    def _movie(self, partial_ok=True):
        rng = self.requested_range()
        MediaHandler.seen_ranges.append(rng)
        start, end, total = 0, MP4_TOTAL - 1, MP4_TOTAL
        if partial_ok and rng.lower().startswith("bytes="):
            spec = rng.split("=", 1)[1].strip()
            if "-" in spec:
                lo, _, hi = spec.partition("-")
                if lo.isdigit():
                    start = int(lo)
                end = min(int(hi) if hi.isdigit() else total - 1, total - 1)
                status = 206
                body = MP4_BODY[start:end + 1]
                self._send(status, body, "video/mp4", extra={
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "Accept-Ranges": "bytes",
                    "Access-Control-Allow-Origin": "*",
                })
                return
        body = MP4_BODY if self.command != "HEAD" else b""
        self._send(200, MP4_BODY, "video/mp4", extra={
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
        })

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/movie.mp4":
            self._movie()
        elif path == "/chunked.mp4":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(0, 24576, 8192):
                chunk = MP4_BODY[i:i + 8192]
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        elif path == "/drip.mp4":
            # slow drip so the speed measurement has a real denominator
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", "65536")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            payload = MP4_BODY[:65536]
            for i in range(0, 65536, 8192):
                self.wfile.write(payload[i:i + 8192])
                self.wfile.flush()
                time.sleep(0.02)
        elif path == "/empty.mp4":
            self._send(200, b"", "video/mp4")
        elif path == "/notfound.mp4":
            self._send(404, b"<html><body>nope</body></html>", "text/html")
        elif path == "/boom":
            self._send(500, b"<html><body>boom</body></html>", "text/html")
        elif path == "/manifest":
            # HLS master playlist, no file extension, correct content type
            self._send(200, HLS_MASTER, "application/vnd.apple.mpegurl", extra={
                "Accept-Ranges": "bytes",
            })
        elif path == "/embed":
            self._send(200, EMBED_HTML, "text/html")
        elif path == "/article":
            self._send(200, ARTICLE_HTML, "text/html")
        elif path == "/token":
            # extensionless direct link whose final_url hint says mp4
            self._send(200, SMALL_MP4, "application/octet-stream",
                       extra={"Accept-Ranges": "bytes"})
        else:
            self._send(404, b"<html>lost</html>", "text/html")

    def do_HEAD(self):
        path = self.path.split("?")[0]
        if path == "/movie.mp4":
            self._send(200, b"", "video/mp4", length=MP4_TOTAL, extra={
                "Accept-Ranges": "bytes",
                "Access-Control-Allow-Origin": "*",
            })
        elif path == "/manifest":
            self._send(200, b"", "application/vnd.apple.mpegurl", length=len(HLS_MASTER),
                       extra={"Accept-Ranges": "bytes"})
        elif path in ("/chunked.mp4", "/drip.mp4"):
            if path == "/chunked.mp4":
                # a chunked host cannot declare a total or range support
                self._send(200, b"", "video/mp4", length=0)
            else:
                self._send(200, b"", "video/mp4", length=65536,
                           extra={"Accept-Ranges": "bytes"})
        elif path == "/empty.mp4":
            self._send(200, b"", "video/mp4")
        elif path == "/notfound.mp4":
            self._send(404, b"", "text/html")
        elif path == "/boom":
            self._send(500, b"", "text/html")
        elif path in ("/embed", "/article", "/token"):
            self._send(200, b"", "text/html" if path != "/token" else "application/octet-stream",
                       length=len(EMBED_HTML if path == "/embed" else
                                  ARTICLE_HTML if path == "/article" else SMALL_MP4),
                       extra={"Accept-Ranges": "bytes"})
        else:
            self._send(404, b"", "text/html")


class NoRangeHandler(_Quiet):
    """Dumb host: always 200, ignores Range, never advertises Accept-Ranges."""

    def _reply(self):
        self._send(200, SMALL_MP4, "video/mp4")

    do_GET = _reply

    def do_HEAD(self):
        self._send(200, b"", "video/mp4", length=len(SMALL_MP4))


class NoHeadHandler(_Quiet):
    """Only speaks GET — HEAD comes back 501 and the probe must fall through."""

    def do_GET(self):
        self._send(200, SMALL_MP4, "video/mp4", extra={"Accept-Ranges": "bytes"})


class SlowHandler(_Quiet):
    """Never answers inside the probe's budget."""

    def do_GET(self):
        time.sleep(0.6)
        self._send(200, SMALL_MP4, "video/mp4")

    def do_HEAD(self):
        time.sleep(0.6)
        self._send(200, b"", "video/mp4", length=len(SMALL_MP4))


class RedirectHandler(_Quiet):
    """Relative + absolute hops, and a self-referencing loop."""

    port = 0

    def _loc(self, target):
        return target if target.startswith("http") else f"http://127.0.0.1:{self.port}{target}"

    def _reply(self):
        path = self.path.split("?")[0]
        if path == "/r1":
            self.send_response(302)
            self.send_header("Location", self._loc("/r2"))
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/r2":
            self.send_response(301)
            self.send_header("Location", self._loc("/final.mp4"))
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/final.mp4":
            self._send(200, SMALL_MP4, "video/mp4", extra={"Accept-Ranges": "bytes"})
        elif path == "/loop":
            self.send_response(302)
            self.send_header("Location", self._loc("/loop"))
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/chain":
            # endless fresh targets -> redirect_limit, not a cycle
            self.send_response(302)
            self.send_header("Location", self._loc(f"/chain?n={time.time_ns()}"))
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(404, b"<html>lost</html>", "text/html")

    do_GET = _reply

    def do_HEAD(self):
        self._reply()


class BrokenHandler(_Quiet):
    """Hangs up without answering — exercises the reset path."""

    def do_GET(self):
        self.close_connection = True
        self.connection.close()

    do_HEAD = do_GET


# ── server plumbing ──────────────────────────────────────────────────────────

def _start(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    if handler_cls is RedirectHandler:
        handler_cls.port = srv.server_address[1]
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


SERVERS = {}


def setUpModule():
    for name, cls in (("media", MediaHandler), ("norange", NoRangeHandler),
                      ("nohead", NoHeadHandler), ("slow", SlowHandler),
                      ("redirect", RedirectHandler), ("broken", BrokenHandler)):
        SERVERS[name] = _start(cls)


def tearDownModule():
    for srv, _ in SERVERS.values():
        srv.shutdown()
        srv.server_close()
    SERVERS.clear()


class _ProbeCase(unittest.TestCase):
    """Base: helpers that keep the private-target guard honest."""

    def url(self, which, path):
        return f"{SERVERS[which][1]}{path}"

    def check(self, which, path, **kw):
        """Probe a local path; assert allow_private is what makes it possible."""
        url = self.url(which, path)
        blocked = lh.probe(url)
        self.assertFalse(blocked.ok, "guard must refuse loopback by default")
        self.assertEqual(blocked.error, "blocked_target")
        self.assertEqual(blocked.protocol, "unusable")
        kw.setdefault("allow_private", True)
        kw.setdefault("timeout", 5.0)
        return lh.probe(url, **kw)


# ── live protocol behaviour ──────────────────────────────────────────────────

class ProgressiveTests(_ProbeCase):
    def test_mp4_with_range_support_is_streamable_resumable(self):
        res = self.check("media", "/movie.mp4")
        self.assertEqual(res.error, "")
        self.assertTrue(res.ok)
        self.assertEqual(res.http_status, 206)
        self.assertEqual(res.protocol, "progressive")
        self.assertEqual(res.content_type, "video/mp4")
        self.assertEqual(res.size_bytes, MP4_TOTAL)   # total, not the slice
        self.assertTrue(res.accepts_ranges)
        self.assertTrue(res.downloadable)
        self.assertTrue(res.resumable)
        self.assertTrue(res.streamable)
        self.assertTrue(res.cors_open)
        self.assertGreaterEqual(res.latency_ms, 0)
        self.assertGreater(res.checked_at, 0.0)
        self.assertEqual(res.redirects_to, "")
        # the sample is bounded, never the whole 1 MiB file
        self.assertIn(f"bytes=0-{lh.DEFAULT_SAMPLE_BYTES - 1}", MediaHandler.seen_ranges)

    def test_sample_bytes_caps_the_body_read(self):
        res = self.check("media", "/movie.mp4", sample_bytes=4096)
        self.assertEqual(res.http_status, 206)
        self.assertEqual(res.size_bytes, MP4_TOTAL)
        self.assertIn("bytes=0-4095", MediaHandler.seen_ranges)

    def test_server_that_ignores_range_is_not_resumable(self):
        res = self.check("media", "/movie.mp4", sample_bytes=2048)
        self.assertEqual(res.http_status, 206)
        norange = self.check("norange", "/f.mp4")
        self.assertTrue(norange.ok)
        self.assertEqual(norange.http_status, 200)
        self.assertEqual(norange.protocol, "progressive")
        self.assertEqual(norange.size_bytes, len(SMALL_MP4))
        self.assertFalse(norange.accepts_ranges)
        self.assertFalse(norange.resumable)
        self.assertTrue(norange.downloadable)
        self.assertTrue(norange.streamable)
        self.assertFalse(norange.cors_open)

    def test_chunked_response_has_no_declared_size(self):
        res = self.check("media", "/chunked.mp4")
        self.assertTrue(res.ok)
        self.assertEqual(res.protocol, "progressive")
        self.assertEqual(res.size_bytes, 0)          # nothing was declared
        self.assertFalse(res.streamable)             # size unknown -> not trusted
        self.assertTrue(res.downloadable)
        self.assertFalse(res.accepts_ranges)

    def test_head_unsupported_falls_back_to_get(self):
        res = self.check("nohead", "/anything.mp4")
        self.assertTrue(res.ok)
        self.assertEqual(res.protocol, "progressive")
        self.assertTrue(res.resumable)

    def test_allow_download_false_stays_head_only(self):
        res = self.check("media", "/movie.mp4", allow_download=False)
        self.assertTrue(res.ok)
        self.assertEqual(res.http_status, 200)
        self.assertEqual(res.protocol, "progressive")
        self.assertEqual(res.size_bytes, MP4_TOTAL)
        self.assertEqual(res.download_speed_mbps, 0.0)   # nothing was sampled
        self.assertTrue(res.streamable)
        blocked = self.check("nohead", "/x.mp4", allow_download=False)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.error, "head_unsupported")

    def test_dripping_server_yields_a_real_speed_number(self):
        res = self.check("media", "/drip.mp4")
        self.assertTrue(res.ok)
        # 64 KiB over ~160 ms of deliberate sleeping -> a few Mbps, never absurd
        self.assertGreater(res.download_speed_mbps, 0.0)
        self.assertLess(res.download_speed_mbps, 200.0)

    def test_tiny_sample_reports_zero_speed_not_a_fantasy(self):
        res = self.check("media", "/movie.mp4", sample_bytes=1024)
        self.assertLess(res.download_speed_mbps, float(lh.MIN_SAMPLE_FOR_SPEED) * 8 / 1e6 + 1)

    def test_zero_byte_200_is_empty_body(self):
        res = self.check("media", "/empty.mp4")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "empty_body")
        self.assertEqual(res.protocol, "unusable")
        self.assertEqual(res.http_status, 200)
        self.assertEqual(res.size_bytes, 0)
        self.assertEqual(lh.score_link(res), 0)

    def test_final_url_extension_hints_the_protocol(self):
        res = self.check("media", "/token", final_url="https://cdn.example.test/m/movie.mp4")
        self.assertEqual(res.protocol, "progressive")
        self.assertTrue(res.downloadable)


class ManifestTests(_ProbeCase):
    def test_hls_master_playlist_without_extension(self):
        res = self.check("media", "/manifest")
        self.assertTrue(res.ok)
        self.assertEqual(res.protocol, "hls")
        self.assertEqual(res.content_type, "application/vnd.apple.mpegurl")
        self.assertTrue(res.streamable)              # manifests size nothing
        self.assertTrue(res.downloadable)            # variants are resolvable
        self.assertTrue(res.accepts_ranges)
        self.assertTrue(res.resumable)               # ranges + downloadable
        self.assertEqual(res.http_status, 200)
        self.assertFalse(res.cors_open)

    def test_hls_sniffed_from_body_without_any_hint(self):
        # /sniff is not in the media handler, so drive the classifier directly:
        # a manifest body must win over an octet-stream content type.
        self.assertEqual(lh._sniff(HLS_MASTER), "hls")
        self.assertEqual(lh._classify("", "application/octet-stream", HLS_MASTER), "hls")


class HttpErrorTests(_ProbeCase):
    def test_404_is_unusable(self):
        res = self.check("media", "/notfound.mp4")
        self.assertFalse(res.ok)
        self.assertEqual(res.http_status, 404)
        self.assertEqual(res.error, "http_404")
        self.assertEqual(res.protocol, "unusable")
        self.assertEqual(lh.score_link(res), 0)

    def test_500_is_unusable(self):
        res = self.check("media", "/boom")
        self.assertFalse(res.ok)
        self.assertEqual(res.http_status, 500)
        self.assertEqual(res.error, "http_500")
        self.assertEqual(res.protocol, "unusable")

    def test_connection_reset_does_not_raise(self):
        res = self.check("broken", "/x.mp4", timeout=2.0)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "conn_reset")
        self.assertEqual(res.protocol, "unusable")
        self.assertEqual(lh.score_link(res), 0)


class TimeoutTests(_ProbeCase):
    def test_slow_server_reports_timeout(self):
        started = time.monotonic()
        res = self.check("slow", "/movie.mp4", timeout=0.2)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "timeout")
        self.assertEqual(res.protocol, "unusable")
        self.assertLess(time.monotonic() - started, 2.0, "probe must not hang")


class EmbedTests(_ProbeCase):
    def test_iframe_page_is_an_embed(self):
        res = self.check("media", "/embed")
        self.assertTrue(res.ok)                    # the page itself answered
        self.assertEqual(res.protocol, "embed")
        self.assertFalse(res.streamable)
        self.assertFalse(res.downloadable)
        self.assertFalse(res.resumable)
        self.assertEqual(res.content_type, "text/html")

    def test_plain_html_page(self):
        res = self.check("media", "/article")
        self.assertEqual(res.protocol, "html_page")
        self.assertFalse(res.streamable)
        self.assertFalse(res.downloadable)
        self.assertTrue(res.ok)
        # a page that merely answers can never outrank a playable file
        self.assertGreater(lh.score_link(res), 0)
        self.assertLess(lh.score_link(res), lh.score_link(_fake()))

    def test_embed_scores_below_a_plain_page(self):
        embed = self.check("media", "/embed")
        page = self.check("media", "/article")
        self.assertLess(lh.score_link(embed), lh.score_link(page))


class RedirectTests(_ProbeCase):
    def test_chain_of_hops_reports_the_final_url(self):
        res = self.check("redirect", "/r1")
        self.assertTrue(res.ok)
        self.assertEqual(res.protocol, "progressive")
        self.assertTrue(res.redirects_to.endswith("/final.mp4"))
        self.assertEqual(lh._host_of(res.redirects_to), "127.0.0.1")

    def test_host_drift_stays_ok_and_is_visible_in_redirects_to(self):
        res = self.check("redirect", "/r1",
                         final_url="https://old-cdn.example.test/final.mp4")
        self.assertTrue(res.ok)
        self.assertEqual(res.error, "")            # drift is a note, not a failure
        self.assertNotEqual(lh._host_of(res.redirects_to),
                           lh._host_of("https://old-cdn.example.test/final.mp4"))

    def test_redirect_loop_terminates(self):
        started = time.monotonic()
        res = self.check("redirect", "/loop", timeout=2.0)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "redirect_loop")
        self.assertLess(time.monotonic() - started, 3.0)

    def test_endless_distinct_hits_the_hop_budget(self):
        started = time.monotonic()
        res = self.check("redirect", "/chain", timeout=2.0)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "redirect_limit")
        self.assertLess(time.monotonic() - started, 5.0)


# ── the SSRF / hygiene guard ─────────────────────────────────────────────────

class GuardTests(unittest.TestCase):
    def test_non_http_scheme_is_blocked(self):
        for bad in ("ftp://cdn.example.test/x.mp4", "file:///etc/passwd",
                    "gopher://h:1/", "//cdn.example.test/x.mp4"):
            with self.subTest(bad=bad):
                res = lh.probe(bad)
                self.assertFalse(res.ok)
                self.assertEqual(res.error, "blocked_target")

    def test_metadata_endpoint_is_blocked(self):
        res = lh.probe("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(res.error, "blocked_target")

    def test_credentials_in_url_are_blocked(self):
        res = lh.probe("https://user:pass@host.example.test/x.mp4")
        self.assertEqual(res.error, "blocked_target")

    def test_localhost_is_blocked(self):
        res = lh.probe("http://localhost/x.mp4")
        self.assertEqual(res.error, "blocked_target")

    def test_private_ranges_are_blocked(self):
        for bad in ("http://127.0.0.1:8080/x.mp4", "http://10.1.2.3/x.mp4",
                    "http://172.16.0.9/x.mp4", "http://192.168.1.1/x.mp4",
                    "http://[::1]/x.mp4", "http://[fe80::1]/x.mp4",
                    "http://127.5.5.5/x.mp4", "http://0.0.0.0/x.mp4"):
            with self.subTest(bad=bad):
                self.assertEqual(lh.probe(bad).error, "blocked_target")

    def test_allow_private_opens_the_gate_and_is_required(self):
        port = SERVERS["media"][0].server_address[1]
        url = f"http://localhost:{port}/movie.mp4"       # same server, name form
        blocked = lh.probe(url)
        self.assertEqual(blocked.error, "blocked_target")
        self.assertEqual(blocked.http_status, 0)
        opened = lh.probe(url, allow_private=True, timeout=5.0)
        self.assertNotEqual(opened.error, "blocked_target")
        self.assertTrue(opened.ok)                       # the gate really opened
        self.assertEqual(opened.protocol, "progressive")

    def test_blocked_urls_never_open_a_socket(self):
        """The guard must fire before any connection attempt, not after."""
        import unittest.mock

        seen = []

        def spy(url, *args, **kwargs):
            seen.append(url)
            return _original_raw(url, *args, **kwargs)

        _original_raw = lh._raw_request
        bad = ("http://169.254.169.254/latest/meta-data",
               "https://user:pass@host.example.test/x.mp4",
               "http://localhost/x.mp4", "http://127.0.0.1:9/x.mp4",
               "http://10.0.0.5/x.mp4", "http://[::1]/x.mp4",
               "ftp://cdn.example.test/x.mp4", "file:///etc/passwd",
               "http://host:NotAPort/x.mp4")
        with unittest.mock.patch.object(lh, "_raw_request", spy):
            for url in bad:
                res = lh.probe(url)
                self.assertIn(res.error, ("blocked_target", "invalid_url"))
        self.assertEqual(seen, [], "guard must refuse before touching the network")

        # positive control: the same spy does record the allowed local probe
        port = SERVERS["media"][0].server_address[1]
        with unittest.mock.patch.object(lh, "_raw_request", spy):
            ok = lh.probe(f"http://127.0.0.1:{port}/movie.mp4", allow_private=True,
                          timeout=5.0)
        self.assertTrue(ok.ok)
        self.assertEqual(seen, [f"http://127.0.0.1:{port}/movie.mp4"] * 2)  # HEAD + GET

    def test_public_literal_addresses_are_allowed(self):
        # the guard is about ranges, not about "is this our site". Only literals
        # here: a bare hostname would need a resolver, and tests stay offline.
        self.assertEqual(lh._block_reason("https://92.4.95.252/x.mp4", False), "")
        self.assertEqual(lh._block_reason("http://[2606::1]/x.mp4", False), "")

    def test_hostname_that_resolves_into_a_private_range_is_blocked(self):
        """DNS rebinding must not be a way in — and no resolver is contacted."""
        import unittest.mock

        inside = [(2, 1, 6, "", ("169.254.169.254", 80))]
        outside = [(2, 1, 6, "", ("93.184.216.34", 80))]
        with unittest.mock.patch.object(lh.socket, "getaddrinfo",
                                        return_value=inside) as resolver:
            res = lh.probe("https://rebind.example.invalid/x.mp4")
            self.assertEqual(res.error, "blocked_target")
            self.assertFalse(res.ok)
        self.assertEqual(resolver.call_count, 1)
        with unittest.mock.patch.object(lh.socket, "getaddrinfo", return_value=outside):
            self.assertEqual(lh._block_reason("https://ok.example.invalid/x.mp4", False), "")
        # allow_private skips the resolution gate entirely (tests only)
        with unittest.mock.patch.object(lh.socket, "getaddrinfo") as resolver:
            self.assertEqual(lh._block_reason("https://any.example.invalid/x.mp4", True), "")
        resolver.assert_not_called()

    def test_non_string_url_is_a_programming_error(self):
        with self.assertRaises(TypeError):
            lh.probe(None)
        with self.assertRaises(TypeError):
            lh.probe(123)

    def test_unparseable_url_is_reported_not_raised(self):
        res = lh.probe("http://host:NotAPort/x.mp4")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "invalid_url")   # distinct from a policy block
        self.assertEqual(res.protocol, "unusable")
        # a scheme we refuse is a policy block, not a parse failure
        self.assertEqual(lh.probe("http://user@host/x.mp4").error, "blocked_target")


# ── scoring ──────────────────────────────────────────────────────────────────

def _fake(**kw):
    base = dict(url="https://cdn.example.test/x.mp4", ok=True, http_status=206,
                protocol="progressive", content_type="video/mp4", size_bytes=MP4_TOTAL,
                accepts_ranges=True, resumable=True, cors_open=True, latency_ms=90,
                download_speed_mbps=18.0, streamable=True, downloadable=True,
                redirects_to="", error="", checked_at=1700000000.0)
    base.update(kw)
    return lh.ProbeResult(**base)


class ScoreTests(unittest.TestCase):
    def test_monotonic_ordering(self):
        fast = _fake()
        embed = _fake(protocol="embed", streamable=False, downloadable=False,
                      resumable=False, accepts_ranges=False, size_bytes=0,
                      download_speed_mbps=0.0, latency_ms=900, error="", ok=True)
        dead = _fake(ok=False, protocol="unusable", http_status=404, streamable=False,
                     downloadable=False, resumable=False, accepts_ranges=False,
                     cors_open=False, size_bytes=0, download_speed_mbps=0.0,
                     latency_ms=400, error="http_404")
        self.assertGreater(lh.score_link(fast), lh.score_link(embed))
        self.assertGreater(lh.score_link(embed), lh.score_link(dead))
        self.assertEqual(lh.score_link(dead), 0)

    def test_exact_formula(self):
        # 300 streamable + 150 downloadable + 100 ranges + 80 cors
        # + 100*18/20 (=90) + 100*latency(90ms -> full) + 100*tier1 = 920
        res = _fake()
        self.assertEqual(lh.score_link(res), 920)
        mid = _fake(latency_ms=1575, download_speed_mbps=10.0, cors_open=False,
                    accepts_ranges=False, resumable=False, downloadable=False,
                    streamable=False, protocol="hls")
        # 0 + 0 + 0 + 0 + 50 (speed) + 50 (latency midpoint) + 100 (tier) = 200
        self.assertEqual(lh.score_link(mid), 200)

    def test_clamped_to_zero_and_one_thousand(self):
        # the documented weights sum to a practical ceiling of 930, so a perfect
        # link tops out there; the 1000 clamp is headroom for future bonuses
        perfect = _fake(latency_ms=10, download_speed_mbps=25.0)
        self.assertEqual(lh.score_link(perfect), 930)
        self.assertLessEqual(lh.score_link(perfect), 1000)
        # an alive but unplayable page: tier 100 - embed 100 = 0, never negative
        worst_alive = _fake(protocol="embed", streamable=False, downloadable=False,
                            resumable=False, accepts_ranges=False, cors_open=False,
                            latency_ms=99999, download_speed_mbps=0.0, size_bytes=0)
        self.assertEqual(lh.score_link(worst_alive), 0)
        # a temporary link would fall below zero without the lower clamp
        self.assertEqual(lh.score_link(worst_alive, is_temporary=1), 0)
        self.assertEqual(lh.score_link(_fake(ok=False)), 0)
        for score in (lh.score_link(_fake()), lh.score_link(_fake(latency_ms=0)),
                      lh.score_link(_fake(ok=False))):
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 1000)

    def test_service_tier_effect(self):
        base = _fake(latency_ms=150, download_speed_mbps=0.0, cors_open=False,
                     accepts_ranges=False, resumable=False, downloadable=False,
                     streamable=False)
        t1 = lh.score_link(base, service_tier=1)
        t2 = lh.score_link(base, service_tier=2)
        t3 = lh.score_link(base, service_tier=3)
        t9 = lh.score_link(base, service_tier=9)
        self.assertEqual((t1, t2, t3), (200, 170, 140))
        self.assertEqual(t9, 140)                      # unknown tiers floor at 0.4

    def test_temporary_penalty(self):
        base = _fake(latency_ms=150, download_speed_mbps=0.0, cors_open=False,
                     accepts_ranges=False, resumable=False, downloadable=False,
                     streamable=False)
        self.assertEqual(lh.score_link(base, is_temporary=0), 200)
        self.assertEqual(lh.score_link(base, is_temporary=1), 50)

    def test_embed_penalty(self):
        embed = _fake(protocol="embed", latency_ms=150, download_speed_mbps=0.0,
                      cors_open=False, accepts_ranges=False, resumable=False,
                      downloadable=False, streamable=False)
        self.assertEqual(lh.score_link(embed), 100)     # 100 + 100 tier - 100 embed

    def test_playback_type_does_not_change_the_score(self):
        res = _fake()
        for kind in ("", "url", "download", "direct"):
            self.assertEqual(lh.score_link(res, playback_type=kind),
                             lh.score_link(res))

    def test_speed_and_latency_scaling_is_linear_and_capped(self):
        def ux_only(speed, latency):
            # stripped of every playability bonus: only the UX band + tier move
            return lh.score_link(_fake(latency_ms=latency, download_speed_mbps=speed,
                                       cors_open=False, accepts_ranges=False,
                                       resumable=False, downloadable=False,
                                       streamable=False, protocol="hls"))
        self.assertEqual(ux_only(20.0, 150) - ux_only(10.0, 150), 50)   # linear speed
        self.assertEqual(ux_only(40.0, 150), ux_only(20.0, 150))        # speed caps at 20
        self.assertEqual(ux_only(0.0, 150) - ux_only(0.0, 3000), 100)   # full latency band
        self.assertEqual(ux_only(0.0, 5000), ux_only(0.0, 3000))        # latency floors
        self.assertEqual(ux_only(0.0, 50), ux_only(0.0, 150))           # sub-150ms is flat


# ── aggregation & history ────────────────────────────────────────────────────

class SummarizeTests(unittest.TestCase):
    def test_counts(self):
        results = [
            _fake(),
            _fake(protocol="hls", streamable=True, downloadable=True, ok=True,
                  http_status=200, accepts_ranges=True, resumable=False,
                  cors_open=False, latency_ms=250, download_speed_mbps=4.0),
            _fake(ok=False, protocol="unusable", error="http_404", http_status=404,
                  streamable=False, downloadable=False, resumable=False,
                  accepts_ranges=False, cors_open=False, latency_ms=100,
                  download_speed_mbps=0.0),
            _fake(protocol="embed", ok=True, streamable=False, downloadable=False,
                  resumable=False, accepts_ranges=False, cors_open=False,
                  latency_ms=400, download_speed_mbps=0.0),
        ]
        s = lh.summarize(results)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["ok"], 3)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["streamable"], 2)
        self.assertEqual(s["downloadable"], 2)
        self.assertEqual(s["resumable"], 1)
        self.assertEqual(s["cors_open"], 1)
        self.assertEqual(s["by_protocol"]["progressive"], 1)
        self.assertEqual(s["by_protocol"]["hls"], 1)
        self.assertEqual(s["by_protocol"]["embed"], 1)
        self.assertEqual(s["by_protocol"]["unusable"], 1)
        self.assertEqual(s["by_error"], {"http_404": 1})
        self.assertEqual(s["avg_latency_ms"], round((90 + 250 + 100 + 400) / 4))
        self.assertAlmostEqual(s["avg_speed_mbps"], round((18.0 + 4.0) / 4, 2))
        self.assertAlmostEqual(s["ok_ratio"], 0.75)

    def test_empty_batch(self):
        s = lh.summarize([])
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["avg_latency_ms"], 0)
        self.assertEqual(s["avg_speed_mbps"], 0.0)
        self.assertEqual(s["ok_ratio"], 0.0)


class HistoryTests(unittest.TestCase):
    def test_three_sample_ewma_by_hand(self):
        # weight 0.4 -> keep 0.6 of history
        a = lh.merge_health_history({}, _fake(latency_ms=100, download_speed_mbps=8.0),
                                    weight=0.4)
        self.assertEqual(a["checks"], 1)
        self.assertEqual(a["success_ema"], 1.0)      # first sample seeds the record
        self.assertEqual(a["latency_ms_ema"], 100)
        self.assertEqual(a["speed_mbps_ema"], 8.0)

        b = lh.merge_health_history(a, _fake(latency_ms=200, download_speed_mbps=4.0))
        self.assertEqual(b["checks"], 2)
        self.assertEqual(b["success_ema"], 1.0)                    # 1*0.6 + 1*0.4
        self.assertEqual(b["latency_ms_ema"], 140)                 # 100*.6 + 200*.4
        self.assertEqual(b["speed_mbps_ema"], 6.4)                 # 8*.6 + 4*.4

        # a failure with no timing data: success decays, latencies carry forward
        c = lh.merge_health_history(b, _fake(ok=False, error="http_503", latency_ms=0,
                                             download_speed_mbps=0.0,
                                             protocol="unusable", checked_at=2.0))
        self.assertEqual(c["checks"], 3)
        self.assertAlmostEqual(c["success_ema"], 0.6)              # 1*.6 + 0*.4
        self.assertEqual(c["latency_ms_ema"], 140)                 # untouched
        self.assertEqual(c["speed_mbps_ema"], 6.4)
        self.assertEqual(c["last_error"], "http_503")
        self.assertEqual(c["last_checked"], 2.0)

        d = lh.merge_health_history(c, _fake(ok=False, error="timeout", latency_ms=0,
                                             download_speed_mbps=0.0))
        self.assertAlmostEqual(d["success_ema"], 0.36)             # .6*.6
        e = lh.merge_health_history(d, _fake(ok=False, error="timeout", latency_ms=0,
                                             download_speed_mbps=0.0))
        self.assertAlmostEqual(e["success_ema"], 0.216)            # decays fast

    def test_previous_dict_is_not_mutated(self):
        prev = {"checks": 1, "success_ema": 1.0, "latency_ms_ema": 50,
                "speed_mbps_ema": 1.0, "last_error": "", "last_checked": 1.0}
        snapshot = dict(prev)
        lh.merge_health_history(prev, _fake(latency_ms=500, download_speed_mbps=2.0))
        self.assertEqual(prev, snapshot)

    def test_weight_is_clamped(self):
        prev = {"checks": 5, "success_ema": 1.0, "latency_ms_ema": 100,
                "speed_mbps_ema": 5.0}
        self.assertEqual(lh.merge_health_history(prev, _fake(latency_ms=1000,
                                                             download_speed_mbps=1.0),
                                                 weight=5.0)["success_ema"], 1.0)
        self.assertEqual(lh.merge_health_history(prev, _fake(ok=False, latency_ms=1000),
                                                 weight=0.0)["success_ema"], 1.0)


# ── batch probing ────────────────────────────────────────────────────────────

class ProbeManyTests(_ProbeCase):
    def test_preserves_input_order(self):
        links = [{"url": self.url("media", "/movie.mp4"), "allow_private": True},
                 {"url": self.url("media", "/notfound.mp4"), "allow_private": True},
                 {"url": self.url("media", "/manifest"), "allow_private": True},
                 {"url": self.url("media", "/embed"), "allow_private": True},
                 {"url": "ftp://x/y"}]
        res = lh.probe_many(links, workers=4, timeout=5.0)
        self.assertEqual(len(res), len(links))
        self.assertEqual([r.url for r in res], [l["url"] for l in links])
        self.assertEqual([r.protocol for r in res],
                         ["progressive", "unusable", "hls", "embed", "unusable"])
        self.assertEqual(res[4].error, "blocked_target")

    def test_never_raises_when_a_server_dies_mid_flight(self):
        srv, base = _start(SlowHandler)          # live now, gone on purpose
        links = [{"url": f"{base}/movie.mp4", "allow_private": True, "timeout": 0.4},
                 {"url": self.url("media", "/movie.mp4"), "allow_private": True,
                  "timeout": 5.0},
                 {"url": self.url("broken", "/x.mp4"), "allow_private": True,
                  "timeout": 2.0}]
        srv.shutdown()
        srv.server_close()
        res = lh.probe_many(links, workers=3, timeout=5.0)
        self.assertEqual(len(res), 3)
        self.assertFalse(res[0].ok)
        self.assertIn(res[0].error, ("conn_reset", "conn_error", "timeout"))
        self.assertTrue(res[1].ok)
        self.assertEqual(res[1].protocol, "progressive")
        self.assertFalse(res[2].ok)
        self.assertEqual(res[2].error, "conn_reset")

    def test_blocklist_skips_known_hostile_services(self):
        calls_before = len(MediaHandler.seen_ranges)
        links = [{"url": self.url("media", "/movie.mp4"), "allow_private": True},
                 {"url": "https://dropgalaxy.vip/abc", "allow_private": True},
                 {"url": "https://sub.dropgalaxy.vip/abc", "allow_private": True},
                 {"url": "http://169.254.169.254/latest/meta-data"}]
        res = lh.probe_many(links, workers=2, timeout=5.0,
                            url_blocklist=["dropgalaxy.vip"])
        self.assertEqual(len(res), 4)
        self.assertTrue(res[0].ok)                            # real probe ran
        self.assertEqual(res[1].error, "blocklisted")         # exact host
        self.assertEqual(res[2].error, "blocklisted")         # subdomain
        # the SSRF guard is independent of the blocklist and still applies:
        # no allow_private here, so this link must never touch the wire
        self.assertEqual(res[3].error, "blocked_target")
        self.assertEqual(len(MediaHandler.seen_ranges), calls_before + 1)

    def test_blocklist_never_opens_a_private_target(self):
        # allow_private=True + a blocklisted local host must not touch the wire
        res = lh.probe_many([{"url": "http://localhost/x.mp4", "allow_private": True}],
                            workers=1, url_blocklist=["localhost"])
        self.assertEqual(res[0].error, "blocklisted")

    def test_empty_and_scalar_inputs(self):
        self.assertEqual(lh.probe_many([]), [])
        res = lh.probe_many([{"url": "ftp://h/x"}], workers=1)
        self.assertEqual(res[0].error, "blocked_target")
        res = lh.probe_many(["https://user:pass@host/x.mp4"], workers=1)
        self.assertEqual(res[0].error, "blocked_target")

    def test_probe_many_passes_shared_kwargs(self):
        links = [{"url": self.url("media", "/movie.mp4")},
                 {"url": self.url("media", "/token")}]
        res = lh.probe_many(links, workers=2, timeout=5.0, allow_private=True,
                            sample_bytes=4096)
        self.assertTrue(all(r.ok for r in res))
        self.assertEqual(res[0].size_bytes, MP4_TOTAL)
        self.assertIn("bytes=0-4095", MediaHandler.seen_ranges)


class StyleTests(unittest.TestCase):
    """Guardrails against accidental API drift / shared mutable state."""

    def test_probe_result_is_frozen(self):
        with self.assertRaises(Exception):
            _fake().protocol = "hls"

    def test_public_surface(self):
        for name in ("ProbeResult", "probe", "score_link", "summarize",
                     "merge_health_history", "probe_many"):
            self.assertTrue(hasattr(lh, name), name)

    def test_probe_fields_match_the_contract(self):
        fields = {f.name for f in lh.ProbeResult.__dataclass_fields__.values()}
        self.assertEqual(fields, {
            "url", "ok", "http_status", "protocol", "content_type", "size_bytes",
            "accepts_ranges", "resumable", "cors_open", "latency_ms",
            "download_speed_mbps", "streamable", "downloadable", "redirects_to",
            "error", "checked_at"})

    def test_probe_many_does_not_share_mutable_state(self):
        links = [{"url": self_url} for self_url in [f"{SERVERS['media'][1]}/movie.mp4"] * 6]
        out = lh.probe_many(links, workers=6, timeout=5.0, allow_private=True)
        self.assertEqual(len({id(r) for r in out}), len(out))
        self.assertTrue(all(r.ok for r in out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
