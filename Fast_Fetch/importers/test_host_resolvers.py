#!/usr/bin/env python3
"""
Offline tests for host_resolvers.py — no live socket, no database, no pip.

The fixtures are real: `PACKED_PAGE` is the mxdrop embed HTML for
`/e/7kk0mpgdsmoqd4` as fetched from this host on 2026-10-28 (the packer call is
verbatim, the surrounding markup reduced to what the unpacker has to survive),
and `UNPACKED_CONFIG` is what the packer's own loop produces for it. The stale
signature case is the response the CDN actually returns for an expired `e`.

Every request goes through an injected `fetch`, so the network code is covered
by calling the real functions with a fake transport, never by monkey-patching a
call away. `socket.socket` is replaced with a raiser so an accidental live
request fails the run instead of passing it.
"""

from __future__ import annotations

import io
import json
import runpy
import socket
import ssl
import sys
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_resolvers as hr  # noqa: E402


class _NoLiveSocket:
    def __init__(self, *a, **k):
        raise AssertionError("test attempted a live socket")


socket.socket = _NoLiveSocket  # type: ignore[attr-defined]


@contextmanager
def silenced():
    out, err = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        yield sys.stdout
    finally:
        sys.stdout, sys.stderr = out, err


PACKED_PAGE = """<html><head><title>MXDrop</title></head><body>
<div id="video-holder"></div>
<script type="text/javascript">
eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){w...
}('1.26="//2.5.4/25/24.23";1.22=" ";1.21="//2.5.4/20/19.3?18=17&16=15&14=13";1.12="11.3";1.10="2";1.9="";1.8=0;1.7="";1.6="";',10,27,'|MDCore|n1sxu2vld|mp4|net|mxcontent|referrer|adTagUrl|chromeInject|remotesub|vserver|1556c1dc1420032a1cb272746a51ce74|vfile|1793145991|_t|1793165221|e|48AjKsiDaW4sYoHGdYvQiA|s|7kk0mpgdsmoqd4|v2|wurl|furl|jpg|7kk0mpgdsmoqd4_4x4|thumbs|poster'.split('|'),0,{}))
</script>
</body></html>"""

UNPACKED_CONFIG = (
    'MDCore.poster="//n1sxu2vld.mxcontent.net/thumbs/7kk0mpgdsmoqd4_4x4.jpg";'
    'MDCore.furl=" ";'
    'MDCore.wurl="//n1sxu2vld.mxcontent.net/v2/7kk0mpgdsmoqd4.mp4'
    '?s=48AjKsiDaW4sYoHGdYvQiA&e=1793165221&_t=1793145991";'
    'MDCore.vfile="1556c1dc1420032a1cb272746a51ce74.mp4";'
    'MDCore.vserver="n1sxu2vld";MDCore.remotesub="";MDCore.chromeInject=0;'
    'MDCore.adTagUrl="";MDCore.referrer="";')

WURL = ("https://n1sxu2vld.mxcontent.net/v2/7kk0mpgdsmoqd4.mp4"
        "?s=48AjKsiDaW4sYoHGdYvQiA&e=1793165221&_t=1793145991")
EMBED = "https://mxdrop.to/e/7kk0mpgdsmoqd4"
POSTER = "https://n1sxu2vld.mxcontent.net/thumbs/7kk0mpgdsmoqd4_4x4.jpg"


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, url="https://x.test/"):
        self.status = status
        self._body = body if isinstance(body, bytes) else str(body).encode()
        self.headers = dict(headers or {})
        self.url = url

    def read(self, size=-1):
        return self._body if size < 0 else self._body[:size]

    def getheaders(self):
        return list(self.headers.items())

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def scripted_fetch(script):
    """
    A `fetch(url, headers, timeout, method, follow)` stand-in.

    `script` maps a URL (or the substring a URL must contain) to either a
    (status, body, headers) triple or an Exception to raise.
    """
    calls = []

    def fetch(url, headers=None, timeout=None, method="GET", follow=True):
        calls.append((url, headers or {}, method))
        for key, value in script.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                status, body, extra = value
                merged = {"content-type": "text/html"}
                merged.update(extra or {})
                return status, body, merged, url
        return 404, b"", {"content-type": "text/html"}, url
    fetch.calls = calls                                    # type: ignore[attr-defined]
    return fetch


# ---------------------------------------------------------------------------
# The packer
# ---------------------------------------------------------------------------

class TestBaseConversion(unittest.TestCase):
    def test_zero_is_the_first_digit(self):
        self.assertEqual(hr.to_base(0, 10), "0")

    def test_decimal_and_radix62(self):
        self.assertEqual(hr.to_base(9, 10), "9")
        self.assertEqual(hr.to_base(27, 10), "27")
        self.assertEqual(hr.to_base(35, 62), "z")
        self.assertEqual(hr.to_base(61, 62), "Z")
        self.assertEqual(hr.to_base(62, 62), "10")

    def test_unsupported_radix_is_refused(self):
        for base in (1, len(hr.BASE_ALPHABET) + 1):
            with self.assertRaises(ValueError):
                hr.to_base(5, base)


class TestUnpacker(unittest.TestCase):
    def test_real_page_unpacks_to_the_stored_config(self):
        self.assertEqual(hr.find_packed_config(PACKED_PAGE), UNPACKED_CONFIG)

    def test_page_without_a_packer_yields_nothing(self):
        self.assertEqual(hr.find_packed_config("<html><body>no script</body></html>"), "")
        self.assertEqual(hr.find_packed_config(""), "")

    def test_digits_inside_an_inserted_value_are_not_re_read(self):
        # Index 12 of this key list is a hash made of digits; the packer walks
        # highest-first, so "13" must survive the substitution of "12".
        keys = [""] * 14
        keys[13] = "TAIL"
        keys[12] = "9e1462c13"
        out = hr.unpack_packed_js('a="12";b="13"', 10, 14, keys)
        self.assertEqual(out, 'a="9e1462c13";b="TAIL"')

    def test_empty_key_slots_are_skipped(self):
        self.assertEqual(hr.unpack_packed_js("1 2 3", 10, 3, ["", "x", ""]), "x 2 3")

    def test_count_larger_than_the_keylist_is_bounded(self):
        self.assertEqual(hr.unpack_packed_js("1 9", 10, 99, ["", "x"]), "x 9")


class TestConfigParsing(unittest.TestCase):
    def test_string_fields(self):
        fields = hr.parse_mdcore(UNPACKED_CONFIG)
        self.assertEqual(fields["vfile"], "1556c1dc1420032a1cb272746a51ce74.mp4")
        self.assertEqual(fields["vserver"], "n1sxu2vld")
        self.assertEqual(fields["poster"], POSTER.replace("https:", ""))

    def test_array_field_parsed_as_json_pairs(self):
        fields = hr.parse_mdcore('MDCore.sublangs=[["English","//h/en.vtt"]];')
        self.assertEqual(fields["sublangs"], [("English", "//h/en.vtt")])

    def test_array_field_parsed_by_regex_when_json_is_malformed(self):
        fields = hr.parse_mdcore('MDCore.sublangs=[["Hindi","//h/hi.vtt",],];')
        self.assertEqual(fields["sublangs"], [("Hindi", "//h/hi.vtt")])

    def test_array_field_with_no_pairs_is_dropped(self):
        self.assertNotIn("sublangs", hr.parse_mdcore("MDCore.sublangs=[oops];"))

    def test_scalar_array_is_dropped(self):
        self.assertNotIn("flags", hr.parse_mdcore("MDCore.flags=[1,2];"))

    def test_absolutize_forms(self):
        self.assertEqual(hr.absolutize("//h/a"), "https://h/a")
        self.assertEqual(hr.absolutize("https://h/a"), "https://h/a")
        self.assertEqual(hr.absolutize("  "), "")


class TestExpiryAndSigning(unittest.TestCase):
    def test_expiry_is_read_from_the_signed_query(self):
        expires_at, delta = hr.expiry_from_url(WURL)
        self.assertEqual(expires_at, 1793165221)
        self.assertIsInstance(delta, int)

    def test_alternative_expiry_names(self):
        self.assertEqual(hr.expiry_from_url("https://h/f?expires=1793165221")[0], 1793165221)
        self.assertEqual(hr.expiry_from_url("https://h/f?exp=1793165221")[0], 1793165221)

    def test_missing_or_silly_expiry_is_none(self):
        self.assertEqual(hr.expiry_from_url("https://h/f"), (None, None))
        self.assertEqual(hr.expiry_from_url("https://h/f?e=abc"), (None, None))
        self.assertEqual(hr.expiry_from_url("https://h/f?e=123"), (None, None))

    def test_signature_params_are_masked(self):
        self.assertEqual(hr.signature_params(WURL),
                         {"_t": "present", "e": "present", "s": "present"})
        self.assertEqual(hr.signature_params(""), {})


class TestEmbedRecognition(unittest.TestCase):
    def test_mxdrop_embed_shapes(self):
        for url in (EMBED, "//mxdrop.top/e/abc123", "https://mxdrop.to/embed/abc",
                    "https://mxdrop.to/e/abc/"):
            self.assertTrue(hr.is_mxdrop_embed(url), url)

    def test_other_hosts_and_paths_are_not_mxdrop(self):
        for url in ("https://pkembed.site/e/abc", "https://notmxdrop.to/e/abc",
                    "https://mxdrop.to/other/abc", "https://mxdrop.to/", ""):
            self.assertFalse(hr.is_mxdrop_embed(url), url)


# ---------------------------------------------------------------------------
# The transport seam
# ---------------------------------------------------------------------------

class TestTransport(unittest.TestCase):
    def test_http_request_returns_the_response_shape(self):
        def fake_open(request, timeout, follow=True):
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("User-agent"), hr.USER_AGENT)
            self.assertIsNone(request.get_header("Referer"))
            self.assertEqual(timeout, 5)
            self.assertTrue(follow)
            return FakeResponse(200, "ok", {"Content-Type": "text/plain"}, "https://x.test/a")
        with mock.patch.object(hr, "_open", fake_open):
            status, body, headers, final = hr.http_request("https://x.test/a", timeout=5)
        self.assertEqual((status, body, final), (200, b"ok", "https://x.test/a"))
        self.assertEqual(headers["content-type"], "text/plain")

    def test_http_request_passes_extra_headers_and_method(self):
        seen = {}

        def fake_open(request, timeout, follow=True):
            seen["range"] = request.get_header("Range")
            seen["method"] = request.get_method()
            return FakeResponse(206, b"x")
        with mock.patch.object(hr, "_open", fake_open):
            hr.http_request("https://x.test/a", headers={"Range": "bytes=0-1"},
                            method="GET")
        self.assertEqual(seen, {"range": "bytes=0-1", "method": "GET"})

    def test_no_follow_is_passed_to_the_primitive(self):
        seen = {}

        def fake_open(request, timeout, follow):
            seen["timeout"], seen["follow"] = timeout, follow
            return FakeResponse(302, b"")
        with mock.patch.object(hr, "_open", fake_open):
            status, _body, _headers, _final = hr.http_request(
                "https://x.test/a", follow=False, timeout=7)
        self.assertEqual((status, seen), (302, {"timeout": 7, "follow": False}))

    def test_http_error_becomes_a_status_and_a_body(self):
        error = urllib.error.HTTPError("https://x.test/a", 403, "Forbidden",
                                       {"Content-Type": "text/html"}, io.BytesIO(b"no"))
        with mock.patch.object(hr, "_open", side_effect=error):
            status, body, headers, final = hr.http_request("https://x.test/a")
        self.assertEqual((status, body), (403, b"no"))
        self.assertEqual(headers["content-type"], "text/html")
        self.assertEqual(final, "https://x.test/a")

    def test_http_error_without_headers_still_reports(self):
        error = urllib.error.HTTPError("https://x.test/a", 500, "Err", None, None)
        with mock.patch.object(hr, "_open", side_effect=error):
            status, _body, headers, _final = hr.http_request("https://x.test/a")
        self.assertEqual((status, headers), (500, {}))

    def test_transport_failure_reports_status_zero(self):
        with mock.patch.object(hr, "_open", side_effect=OSError("dns down")):
            status, body, headers, final = hr.http_request("https://x.test/a")
        self.assertEqual((status, body, headers, final), (0, "dns down", {}, "https://x.test/a"))

    def test_open_picks_the_opener_the_caller_asked_for(self):
        calls = []

        class Opener:
            def __init__(self, name):
                self.name = name

            def open(self, request, timeout):
                calls.append((self.name, timeout))
                return FakeResponse(200, b"body")

        with mock.patch.object(hr, "_FOLLOW", Opener("follow")), \
                mock.patch.object(hr, "_NO_FOLLOW", Opener("strict")):
            first = hr._open(urllib.request.Request("https://x.test/a"), 3)
            second = hr._open(urllib.request.Request("https://x.test/a"), 3,
                              follow=False)
        self.assertEqual(calls, [("follow", 3), ("strict", 3)])
        self.assertEqual((first.read(4), second.read(4)), (b"body", b"body"))

    def test_openers_are_cached_per_context(self):
        context = ssl.create_default_context()
        self.assertIs(hr._build_openers(context), hr._build_openers(context))
        self.assertEqual(hr._build_openers(hr._SSL_CONTEXT),
                         (hr._FOLLOW, hr._NO_FOLLOW))
        # An omitted context means "make a fresh one", so two calls are two caches.
        self.assertIsNot(hr._build_openers(), hr._build_openers())

    def test_stop_redirect_handler_refuses_to_follow(self):
        handler = hr._StopRedirect()
        request = urllib.request.Request("https://x.test/a")
        self.assertIsNone(handler.redirect_request(
            request, None, 302, "Found", {}, "https://x.test/b"))


# ---------------------------------------------------------------------------
# Range probe
# ---------------------------------------------------------------------------

class TestRangeProbe(unittest.TestCase):
    def test_206_video_is_active_with_a_size(self):
        fetch = scripted_fetch({WURL: (206, b"\x00\x00\x00 ftypisom",
                                       {"content-type": "video/mp4",
                                        "content-range": "bytes 0-511/425208621"})})
        verdict = hr.probe_range(WURL, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["size_bytes"], 425208621)
        self.assertEqual(verdict["content_type"], "video/mp4")
        self.assertEqual(fetch.calls[0][1]["Range"], "bytes=0-511")

    def test_206_without_a_range_header_has_no_size(self):
        fetch = scripted_fetch({"a": (206, b"x", {"content-type": "video/mp4"})})
        self.assertIsNone(hr.probe_range("https://h/a", fetch=fetch)["size_bytes"])

    def test_206_of_the_wrong_type_is_unknown(self):
        fetch = scripted_fetch({"a": (206, b"x", {"content-type": "text/html"})})
        verdict = hr.probe_range("https://h/a", fetch=fetch)
        self.assertEqual((verdict["status"], verdict["reason"]), ("unknown", "206 text/html"))

    def test_200_video_is_active_and_flagged_full_body(self):
        fetch = scripted_fetch({"a": (200, b"x" * 40, {"content-type": "video/mp4"})})
        verdict = hr.probe_range("https://h/a", fetch=fetch)
        self.assertEqual((verdict["status"], verdict["reason"], verdict["size_bytes"]),
                         ("active", "full_body", 40))

    def test_200_html_is_blocked(self):
        fetch = scripted_fetch({"a": (200, b"x", {"content-type": "text/html"})})
        verdict = hr.probe_range("https://h/a", fetch=fetch)
        self.assertEqual((verdict["status"], verdict["reason"]), ("blocked", "200 text/html"))

    def test_403_is_blocked_and_404_is_dead(self):
        fetch = scripted_fetch({"a": (403, b"no", {}), "b": (404, b"", {})})
        self.assertEqual(hr.probe_range("https://h/a", fetch=fetch)["status"], "blocked")
        self.assertEqual(hr.probe_range("https://h/b", fetch=fetch)["status"], "dead")

    def test_410_is_dead(self):
        fetch = scripted_fetch({"b": (410, b"", {})})
        self.assertEqual(hr.probe_range("https://h/b", fetch=fetch)["status"], "dead")

    def test_server_error_and_unexpected_status_are_errors(self):
        fetch = scripted_fetch({"a": (503, b"", {}), "b": (302, b"", {}),
                                "c": (204, b"", {})})
        self.assertEqual(hr.probe_range("https://h/a", fetch=fetch)["status"], "error")
        self.assertEqual(hr.probe_range("https://h/b", fetch=fetch)["reason"], "HTTP 302")
        self.assertEqual(hr.probe_range("https://h/c", fetch=fetch)["reason"], "HTTP 204")

    def test_transport_failure_is_reported_as_error(self):
        fetch = scripted_fetch({"a": (0, "timeout", {})})
        verdict = hr.probe_range("https://h/a", fetch=fetch)
        self.assertEqual((verdict["status"], verdict["reason"]), ("error", "timeout"))

    def test_custom_probe_size(self):
        fetch = scripted_fetch({"a": (206, b"", {"content-type": "video/mp4"})})
        hr.probe_range("https://h/a", size=64, fetch=fetch)
        self.assertEqual(fetch.calls[0][1]["Range"], "bytes=0-63")


class TestPosterLiveness(unittest.TestCase):
    def test_no_poster_is_an_unknown(self):
        self.assertIsNone(hr.host_is_alive("", fetch=lambda *a, **k: (200, b"", {}, "")))

    def test_image_answer_is_alive(self):
        fetch = scripted_fetch({POSTER: (200, b"j", {"content-type": "image/jpeg"})})
        self.assertTrue(hr.host_is_alive(POSTER, fetch=fetch))

    def test_200_with_no_type_is_still_the_host_answering(self):
        fetch = scripted_fetch({POSTER: (200, b"j", {"content-type": ""})})
        self.assertTrue(hr.host_is_alive(POSTER, fetch=fetch))

    def test_refused_poster_is_not_alive(self):
        fetch = scripted_fetch({POSTER: (403, b"", {"content-type": "text/html"})})
        self.assertFalse(hr.host_is_alive(POSTER, fetch=fetch))


# ---------------------------------------------------------------------------
# unwrap_mxdrop
# ---------------------------------------------------------------------------

class TestUnwrapMxdrop(unittest.TestCase):
    def test_full_chain_active(self):
        fetch = scripted_fetch({
            EMBED: (200, PACKED_PAGE, {}),
            ".mp4": (206, b"\x00\x00\x00 ftypisom",
                     {"content-type": "video/mp4", "content-range": "bytes 0-511/999"}),
        })
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "mxdrop")
        self.assertTrue(verdict["is_temporary"])
        self.assertEqual(verdict["final_url"], WURL)
        self.assertEqual(verdict["poster_url"], POSTER)
        self.assertEqual(verdict["vfile"], "1556c1dc1420032a1cb272746a51ce74.mp4")
        self.assertEqual(verdict["vserver"], "n1sxu2vld")
        self.assertEqual(verdict["signed_params"], ["_t", "e", "s"])
        self.assertEqual(verdict["size_bytes"], 999)
        self.assertEqual(verdict["subtitles"], [])
        self.assertIn("48AjKsiDaW4sYoHGdYvQiA", json.dumps(verdict))

    def test_no_media_request_carries_the_catalog_referer(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        hr.unwrap_mxdrop(EMBED, fetch=fetch, referer="https://www.moviesmela.com/x/")
        for _url, headers, _method in fetch.calls:
            self.assertNotIn("Referer", headers)

    def test_an_allowed_referer_is_passed_through(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        hr.unwrap_mxdrop(EMBED, fetch=fetch, referer="https://mxdrop.top/e/x")
        self.assertNotIn("withheld", json.dumps(
            hr.unwrap_mxdrop(EMBED, fetch=fetch, referer="https://mxdrop.top/e/x")["notes"]))

    def test_forbidden_referer_is_withheld_and_said_so(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch,
                                   referer="https://www.moviesmela.com/watch/x/")
        self.assertIn("referrer withheld", verdict["notes"][0])

    def test_verify_off_unpacks_without_touching_the_cdn(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch, verify=False)
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(verdict["final_url"], WURL)
        self.assertEqual(len(fetch.calls), 1)
        self.assertIn("not probed", json.dumps(verdict["notes"]))

    def test_a_host_that_ignores_range_is_active_and_says_so(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (200, b"y" * 64,
                                         {"content-type": "video/mp4"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["notes"], ["full_body"])

    def test_non_mxdrop_url_is_refused_before_any_request(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_mxdrop("https://pkembed.site/e/abc", fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(fetch.calls, [])

    def test_embed_page_failure_shapes(self):
        for status, expected in ((404, "dead"), (410, "dead"), (403, "blocked"),
                                 (429, "blocked"), (500, "unknown"), (204, "unknown")):
            fetch = scripted_fetch({EMBED: (status, b"", {})})
            verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
            self.assertEqual(verdict["status"], expected, status)
            self.assertEqual(verdict["notes"], [f"embed page HTTP {status}"])

    def test_page_without_a_packer_is_unknown(self):
        fetch = scripted_fetch({EMBED: (200, "<html>plain</html>", {})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("no recognisable packed config", verdict["notes"][0])

    def test_missing_wurl_is_unknown(self):
        page = PACKED_PAGE.replace(
            '1.21="//2.5.4/20/19.3?18=17&16=15&14=13"', '1.21=""')
        fetch = scripted_fetch({EMBED: (200, page, {})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("MDCore.wurl", verdict["notes"][0])

    def test_relative_only_config_is_unknown(self):
        page = PACKED_PAGE.replace(
            '1.21="//2.5.4/20/19.3?18=17&16=15&14=13"', '1.21="/only/path"')
        fetch = scripted_fetch({EMBED: (200, page, {})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(verdict["final_url"], "")

    def test_unparsable_expiry_is_recorded(self):
        page = PACKED_PAGE.replace("16=15", "16=1x").replace("|e|", "|x|")
        fetch = scripted_fetch({EMBED: (200, page, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertIsNone(verdict["expires_in"])
        self.assertIn("no parsable expiry", json.dumps(verdict["notes"]))

    def test_subtitles_come_from_sublangs_and_the_subs_param(self):
        page = PACKED_PAGE.replace(
            "1.9=", '1.sublangs=[["English","//h/en.vtt"],["Hindi","//h/hi.vtt"]];1.9=')
        fetch = scripted_fetch({EMBED: (200, page, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["subtitles"],
                         [{"language": "English", "url": "https://h/en.vtt"},
                          {"language": "Hindi", "url": "https://h/hi.vtt"}])

    def test_subs_query_param_becomes_a_track(self):
        page = PACKED_PAGE.replace(
            '14=13"', '14=13&subs=//h/en.vtt"')
        fetch = scripted_fetch({EMBED: (200, page, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["subtitles"],
                         [{"language": "subs", "url": "https://h/en.vtt"}])

    def test_remotesub_is_not_invented_as_a_track(self):
        page = PACKED_PAGE.replace('1.9=""', '1.9="//h/orphan.vtt"')
        fetch = scripted_fetch({EMBED: (200, page, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        fields = hr.parse_mdcore(hr.find_packed_config(page))
        self.assertEqual(fields["remotesub"], "//h/orphan.vtt")
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["subtitles"], [])

    def test_blocked_media_with_a_live_poster_is_an_expired_signature(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (403, b"<html>403</html>",
                                         {"content-type": "text/html"}),
                                "thumbs": (200, b"j", {"content-type": "image/jpeg"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "blocked")
        self.assertIn("signature expired", json.dumps(verdict["notes"]))

    def test_blocked_media_with_a_dead_poster_is_dead(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (403, b"", {"content-type": "text/html"}),
                                "thumbs": (404, b"", {"content-type": "text/html"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "dead")
        self.assertIn("host no longer serves", json.dumps(verdict["notes"]))

    def test_blocked_media_with_no_poster_says_so(self):
        page = PACKED_PAGE.replace("1.26=", "1.98=")
        fetch = scripted_fetch({EMBED: (200, page, {}),
                                ".mp4": (403, b"", {"content-type": "text/html"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "blocked")
        self.assertIn("poster unavailable", json.dumps(verdict["notes"]))

    def test_unknown_media_verdict_is_carried_into_the_notes(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (500, b"", {"content-type": "text/html"})})
        verdict = hr.unwrap_mxdrop(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "error")
        self.assertIn("HTTP 500", json.dumps(verdict["notes"]))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

class TestMain(unittest.TestCase):
    def test_usage_without_arguments(self):
        with silenced() as buf:
            self.assertEqual(hr.main([]), 2)
        self.assertIn("usage:", buf.getvalue())

    def test_active_verdict_prints_json_and_exits_zero(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main([EMBED]), 0)
        self.assertEqual(json.loads(buf.getvalue())["status"], "active")

    def test_no_verify_flag_skips_the_byte_probe(self):
        fetch = scripted_fetch({EMBED: (200, PACKED_PAGE, {})})
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main([EMBED, "--no-verify"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["status"], "unverified")

    def test_a_dead_verdict_exits_one(self):
        fetch = scripted_fetch({EMBED: (404, b"", {})})
        with mock.patch.object(hr, "http_request", fetch), silenced():
            self.assertEqual(hr.main([EMBED]), 1)

    def test_the_module_runs_as_a_script(self):
        """
        `if __name__ == "__main__"` itself, with the no-network answer.

        runpy re-executes the module in a fresh namespace, so mocks on the
        imported `hr` are invisible to it; what it must prove is that a script
        run with no reachable host still produces a verdict and a non-zero
        exit instead of hanging or pretending success.
        """
        with mock.patch.object(sys, "argv", ["host_resolvers.py", EMBED]), silenced():
            with self.assertRaises(SystemExit) as stop:
                runpy.run_module("host_resolvers", run_name="__main__")
        self.assertEqual(stop.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
