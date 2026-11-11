"""Tests for admin_v2.domain_check: fingerprint logic + failure paths.

No live network is required: DNS failure is tested with a patched
resolver (real resolvers differ on .invalid), and fingerprint
logic is tested directly on bodies. A passing live HTTPS domain is
verified manually on the VM (raddstream.duckdns.org), not in CI.
"""
import socket
import unittest
from unittest.mock import patch

from admin_v2.domain_check import check_domain, fingerprint_check, fingerprint_ok_for_body

# A realistic homepage: title, quality markers, internal links, and
# over 2,000 bytes. A 65-byte page is a doorway, not a homepage, and
# the checker must reject it (admin-panel audit §Domains).
HTML = (b"<html><head><title>Radd Stream</title></head><body>"
        b"<p>" + b"Watch movies in 720p and 1080p WEB-DL quality. " * 60 + b"</p>"
        b'<a href="/movie/1">Movie 1</a><a href="/movie/2">Movie 2</a>'
        b'<a href="/movie/3">Movie 3</a></body></html>')


def _big_page(title=b"Vegamovies", slug_links=True):
    links = (b'<a href="/movie/1">One</a><a href="/movie/2">Two</a>'
             b'<a href="/movie/3">Three</a>') if slug_links else b""
    return (b"<html><head><title>" + title + b"</title></head><body>"
            b"<p>" + b"Watch movies in 720p and 1080p WEB-DL quality. " * 60 + b"</p>"
            + links + b"</body></html>")


class _FakeResp:
    def __init__(self, status, headers, body):
        self.status = status
        self._headers = headers
        self._body = body

    def getheader(self, name, default=None):
        return self._headers.get(name, default)

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]


class _FakeConn:
    routes = {}

    def __init__(self, host, *args, **kwargs):
        self.host = host

    def request(self, method, path, headers=None):
        pass

    def getresponse(self):
        return _FakeResp(*self.routes[self.host])

    def close(self):
        pass


class _CheckContext:
    """Patches DNS/TCP/TLS + the HTTPS connection so check_domain runs
    against canned routes, with no live network at all."""

    def __init__(self, routes):
        self.routes = routes

    def __enter__(self):
        from unittest.mock import MagicMock
        self._patches = [
            patch("admin_v2.domain_check.socket.getaddrinfo",
                  return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]),
            patch("admin_v2.domain_check.socket.create_connection",
                  return_value=MagicMock()),
            patch("admin_v2.domain_check.ssl.create_default_context",
                  return_value=MagicMock()),
            patch("admin_v2.domain_check.http.client.HTTPSConnection", _FakeConn),
        ]
        for p in self._patches:
            p.__enter__()
        _FakeConn.routes = self.routes
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.__exit__(*exc)
        return False


class TestFingerprint(unittest.TestCase):
    def test_real_html_page_passes(self):
        self.assertTrue(fingerprint_ok_for_body(HTML, "text/html; charset=utf-8"))

    def test_empty_body_fails(self):
        self.assertFalse(fingerprint_ok_for_body(b"", "text/html"))

    def test_non_html_fails(self):
        self.assertFalse(fingerprint_ok_for_body(b"{}", "application/json"))

    def test_parking_page_fails(self):
        body = b"<html><title>Parked</title><body>This domain is for sale</body></html>"
        self.assertFalse(fingerprint_ok_for_body(body, "text/html"))

    def test_expected_marker_must_be_present(self):
        self.assertTrue(fingerprint_ok_for_body(b"hello world", "text/plain", "world"))
        self.assertFalse(fingerprint_ok_for_body(b"hello world", "text/plain", "radd"))


class TestCheckDomainFailures(unittest.TestCase):
    def test_dns_failure_stops_before_tcp(self):
        # Patch DNS only: real resolvers differ, so do not rely on a
        # live .invalid lookup. Everything else stays real.
        with patch("admin_v2.domain_check.socket.getaddrinfo",
                   side_effect=socket.gaierror("Name or service not known")):
            result = check_domain("example.invalid", timeout=5)
        self.assertFalse(result["dns_ok"])
        self.assertFalse(result["tcp_ok"])
        self.assertFalse(result["tls_ok"])
        self.assertFalse(result["fingerprint_ok"])
        self.assertEqual(result["failure_reason"], "dns_failed")
        self.assertIsNone(result["http_status"])
        # No IP addresses or body content leak into the result.
        self.assertNotIn("body", result)
        self.assertNotIn("ip", " ".join(result.keys()))


class TestFingerprintReasons(unittest.TestCase):
    def test_doorway_body_too_small(self):
        ok, reason = fingerprint_check(
            b"<html><head><title>Site</title></head><body>x</body></html>",
            "text/html")
        self.assertFalse(ok)
        self.assertEqual(reason, "content_too_small")

    def test_parked_markers_extended(self):
        for marker in (b"sedo", b"afternic", b"dan.com", b"hugedomains",
                       b"bodis", b"parkingcrew", b"is for sale",
                       b"this domain has expired", b"domain parking"):
            body = (b"<html><head><title>Site</title></head><body>"
                    + b"filler " * 400 + marker + b"</body></html>")
            ok, reason = fingerprint_check(body, "text/html")
            self.assertFalse(ok, marker)
            self.assertEqual(reason, "parked", marker)

    def test_bot_challenge_is_unverifiable_not_dead(self):
        body = (b"<html><head><title>Just a moment</title></head><body>"
                + b"Checking your browser. " * 100 + b"</body></html>")
        ok, reason = fingerprint_check(body, "text/html")
        self.assertFalse(ok)
        self.assertEqual(reason, "bot_challenge")

    def test_final_host_without_slug_is_hijack(self):
        ok, reason = fingerprint_check(
            _big_page(), "text/html", site_key="desicinemas",
            final_host="koi5000sultan.com")
        self.assertFalse(ok)
        self.assertEqual(reason, "redirect_hijack")

    def test_no_content_evidence(self):
        body = (b"<html><head><title>Something Else</title></head><body>"
                + b"lorem ipsum dolor sit amet. " * 100 + b"</body></html>")
        ok, reason = fingerprint_check(body, "text/html",
                                       site_key="vegamovies",
                                       final_host="vegamovies.example.test")
        self.assertFalse(ok)
        self.assertEqual(reason, "no_content_evidence")

    def test_slug_in_title_passes(self):
        ok, reason = fingerprint_check(
            _big_page(title=b"Vegamovies Download", slug_links=False),
            "text/html", site_key="vegamovies",
            final_host="vegamovies.example.test")
        self.assertTrue(ok)
        self.assertIsNone(reason)


class TestCheckDomainRedirects(unittest.TestCase):
    def test_redirect_followed_to_real_site(self):
        routes = {
            "vegamovies.example.test": (
                301, {"Location": "https://vegamovies-new.example.test/", "Content-Type": "text/html"}, b""),
            "vegamovies-new.example.test": (
                200, {"Content-Type": "text/html; charset=utf-8"}, _big_page()),
        }
        with _CheckContext(routes):
            result = check_domain("vegamovies.example.test", site_key="vegamovies")
        self.assertTrue(result["fingerprint_ok"])
        self.assertTrue(result["redirected"])
        self.assertEqual(result["redirect_count"], 1)
        self.assertEqual(result["final_domain"], "vegamovies-new.example.test")
        self.assertIsNone(result["failure_reason"])

    def test_redirect_to_unrelated_host_is_hijack(self):
        routes = {
            "desicinemas.example.test": (
                301, {"Location": "https://koi5000sultan.com/", "Content-Type": "text/html"}, b""),
            "koi5000sultan.com": (
                200, {"Content-Type": "text/html"}, _big_page()),
        }
        with _CheckContext(routes):
            result = check_domain("desicinemas.example.test", site_key="desicinemas")
        self.assertFalse(result["fingerprint_ok"])
        self.assertEqual(result["failure_reason"], "redirect_hijack")
        self.assertEqual(result["final_domain"], "koi5000sultan.com")

    def test_redirect_body_itself_is_never_fingerprinted(self):
        # The audit's exact bug: a 301 body has a <title> and no parking
        # marker, so the old checker passed it. The new checker must
        # fail when the FINAL body is a doorway, whatever the 301 said.
        routes = {
            "vegamovies.example.test": (
                301, {"Location": "https://vegamovies-new.example.test/", "Content-Type": "text/html"},
                b"<html><head><title>Moved</title></head><body>hi</body></html>"),
            "vegamovies-new.example.test": (
                200, {"Content-Type": "text/html"},
                b"<html><head><title>x</title></head><body>y</body></html>"),
        }
        with _CheckContext(routes):
            result = check_domain("vegamovies.example.test", site_key="vegamovies")
        self.assertFalse(result["fingerprint_ok"])
        self.assertEqual(result["failure_reason"], "content_too_small")

    def test_redirect_loop(self):
        routes = {
            "loop.example.test": (
                301, {"Location": "https://loop.example.test/", "Content-Type": "text/html"}, b""),
        }
        with _CheckContext(routes):
            result = check_domain("loop.example.test")
        self.assertFalse(result["fingerprint_ok"])
        self.assertEqual(result["failure_reason"], "redirect_loop")

    def test_redirect_to_plain_http_refused(self):
        routes = {
            "vegamovies.example.test": (
                301, {"Location": "http://vegamovies.example.test/", "Content-Type": "text/html"}, b""),
        }
        with _CheckContext(routes):
            result = check_domain("vegamovies.example.test")
        self.assertFalse(result["fingerprint_ok"])
        self.assertEqual(result["failure_reason"], "redirect_to_http")

    def test_no_redirect_reports_final_domain(self):
        routes = {
            "vegamovies.example.test": (
                200, {"Content-Type": "text/html"}, _big_page()),
        }
        with _CheckContext(routes):
            result = check_domain("vegamovies.example.test", site_key="vegamovies")
        self.assertTrue(result["fingerprint_ok"])
        self.assertFalse(result["redirected"])
        self.assertEqual(result["redirect_count"], 0)
        self.assertEqual(result["final_domain"], "vegamovies.example.test")


if __name__ == "__main__":
    unittest.main()
