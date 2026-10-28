#!/usr/bin/env python3
"""
Offline tests for host_resolvers.py — no live socket, no database, no pip.

The fixtures are real: `PACKED_PAGE` is the mxdrop embed HTML for
`/e/7kk0mpgdsmoqd4` as fetched from this host on 2026-10-28 (the packer call is
verbatim, the surrounding markup reduced to what the unpacker has to survive),
and `UNPACKED_CONFIG` is what the packer's own loop produces for it.
`PK_PACKED_PAGE` is the same for `/embed-g64v61whic26.html` on pkembed.site —
whole, including its base-36 packer call, so the unpacker is tested against the
bytes the host actually served. The stale signature case is the response the
CDN actually returns for an expired `e`.

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
import time
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

PK_PACKED_PAGE = """<html><head><title>pkembed</title></head><body>
<div id="vplayer" style="width:100%;height:100%;"></div>
<script type='text/javascript'>eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}('$(\\'#1f\\').4g(\\'<q 4f="1t" 4e="11:j%; z:j%;" 4d="4c"><20 x="2://1e.1d.1c/v/1b/1a/4b/l.r?t=4a-49&s=13&e=1z&v=14&1y=1x&i=0.3" 1w="q/r" 1v="48 47 1u"><20 x="2://1e.1d.1c/v/1b/1a/46/n.r?t=45&s=13&e=1z&v=14&1y=1x&i=0.3" 1w="q/r" 1v="44 43 1u"> </q>\\');12 b=42(\\'1t\\',{41:{40:\\'2://1e.1d.1c/i/1b/1a/1i.3z\\',3y:\\'3x\\',3w:a,3v:{3u:a,3t:5,3s:19},3r:{3q:a,3p:[{3o:\\'2://w.u\\',3n:\\'3m\\'}]},3l:a,3k:19,3j:{1r:a},},3i:(1s)=>{1s.3h=19},3g:{3f:a,3e:[{9:\\'3d\\',8:\\'\\'},{9:\\'p\\',8:\\'2://6.g.f/6?d=c\\',o:y},{9:\\'p\\',8:\\'2://6.g.f/6?d=c\\',o:3c},{9:\\'p\\',8:\\'2://6.g.f/6?d=c\\',o:3b},{9:\\'p\\',8:\\'2://6.g.f/6?d=c\\',o:3a},{9:\\'39\\',8:\\'2://6.g.f/6?d=c\\'}]},});12 16,17;b.18(\\'1h\\',7(){1p()});b.18(\\'38\\',7(){$(\\'k.1o\\').1r()});b.18(\\'37\\',7(1q){15(5>0&&1q>=5&&17!=1){17=1;$(\\'k.36\\').35(\\'34\\')}});7 1p(){$(\\'k.1o\\').33();15(16)32;16=1;m=0;15(31.30==1){m=1}$.2z(\\'2://w.u/2y?1j=2x&2w=14&2v=13-2u&2t=1&m=\\'+m,7(1n){$(\\'#2s\\').2r(1n)})}7 2q(){2p(\\'2o\\').2n();12 $h=$("<k />").1m({2m:"2l",11:"j%",z:"j%",2k:0,1k:0,1l:2j,2i:"2h(10%, 10%, 10%, 0.4)","2g-2f":"2e"});$("<2d />").1m({11:"y%",z:"y%",1l:2c,"2b-1k":"2a"}).29({\\'x\\':\\'2://w.u/?1j=28&27=1i\\',\\'26\\':\\'0\\',\\'25\\':\\'24\\'}).1g($h);$h.23(7(){$(22).21();b.1h()});$h.1g($(\\'#1f\\'))}',36,161,'||https||||vast|function|vastTag|roll|true|player|1472528|spot_id||xyz|yomeno|dd||100|div||adb||timer|midRoll|video|mp4|||net||vkplus|src|60|height||width|var|1793148018|77081502|if|vvplay|vvad|on|false|00002|01|site|vkpluscdn|plus1|vplayer|appendTo|play|g64v61whic26|op|top|zIndex|css|data|video_ad|doPlay|currentTime|show|request|fplayer|kbps|title|type|3000|sp|43200|source|remove|this|click|no|scrolling|frameborder|file_code|upload_srt|prop|50px|margin|1000001|iframe|center|align|text|rgba|background|1000000|left|absolute|position|pause|vjsplayer|videojs|showCCform|html|fviews|embed|796a58cbca5e373b628b4f97be6ace2e|hash|view_id|view|dl|get|adbon|window|return|hide|slow|fadeIn|video_ad_fadein|timeupdate|ended|postRoll|1500|900|300|preRoll|adList|allowVPAID|vastOptions|withCredentials|onBeforeXMLHttpRequest|controlForwardBackward|allowTheatre|playbackRateEnabled|VkPlus|label|href|links|controls|contextMenu|animated|autoHideTimeout|autoHide|controlBar|playButtonShowing|auto|preload|jpg|posterImage|layoutControls|fluidPlayer|562|480p|BqXY2lCE5L77IMC9sybLm7pa1NHMqtCctY4RKPSO9ug|g64v61whic26_n|326|360p|fqbbp3Q|KHH6I0tMZ1p4B6gjpVUIrfGYldCDbEHRVS4|g64v61whic26_l|anonymous|crossOrigin|style|id|append'.split('|')))
</script>
</body></html>"""

PK_EMBED = "https://pkembed.site/embed-g64v61whic26.html"
PK_BARE_EMBED = "https://pkembed.site/zp8vd43rpa80.html"
PK_L_MP4 = ("https://plus1.vkpluscdn.site/v/01/00002/g64v61whic26_l/l.mp4"
            "?t=KHH6I0tMZ1p4B6gjpVUIrfGYldCDbEHRVS4-fqbbp3Q&s=1793148018&e=43200"
            "&v=77081502&sp=3000&i=0.3")
PK_N_MP4 = ("https://plus1.vkpluscdn.site/v/01/00002/g64v61whic26_n/n.mp4"
            "?t=BqXY2lCE5L77IMC9sybLm7pa1NHMqtCctY4RKPSO9ug&s=1793148018&e=43200"
            "&v=77081502&sp=3000&i=0.3")
PK_POSTER = "https://plus1.vkpluscdn.site/i/01/00002/g64v61whic26.jpg"

# The other CDN the same host was measured on (owner, 2026-10-28): a rendition
# list must accept either hostname, because the payload names it and we do not.
VKCDN5_CONFIG = (
    '\'<video id="fplayer"><source '
    'src="https://stoplus.vkcdn5.com/v/01/00002/fi_l/l.mp4'
    '?t=sig&s=1793147688&e=43200&v=77&sp=3000&i=0.3" '
    'type="video/mp4" title="480p 658 kbps"> </video>\';')

# Google Drive, as the owner measured it live on 2026-10-28 against a real
# animahd.com episode id: the download endpoint answers a large file with this
# "Virus scan warning" page, and the form it publishes is what replayed with a
# Range header returns 206, `Content-Range bytes 0-511/253161185` and body bytes
# starting `1A 45 DF A3` under `Content-Type: application/octet-stream`.
GD_FILE_ID = "1BvFM6gGdKlXkL8d5sJ7hQ9wZ3tR2yP4c"
GD_DOWNLOAD_PAGE = f"https://drive.google.com/uc?export=download&id={GD_FILE_ID}"
GD_UUID = "8c9f0d2e-1c4a-4a55-9b23-2a1a2b3c4d5e"
GD_REPLAY = ("https://drive.usercontent.google.com/download?"
             f"id={GD_FILE_ID}&export=download&confirm=t&uuid={GD_UUID}")
GD_INTERSTITIAL = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>animahd-ep-01.mkv - Google Drive</title></head><body>
<div class="drive-file-msg-title">Can't view this file in Preview</div>
<form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
  <input type="hidden" name="id" value="{GD_FILE_ID}">
  <input type="hidden" name="export" value="download">
  <input type="hidden" name="confirm" value="t">
  <input type="hidden" name="uuid" value="{GD_UUID}">
  <input id="downloadButton" type="submit" class="ldl43c" value="Download anyway">
</form></body></html>"""
# What a private file answers instead: the same endpoint, a sign-in wall, and no
# form that would ever lead to bytes.
GD_SIGNIN_WALL = """<!DOCTYPE html><html><head><title>Sign in</title></head>
<body><form action="https://accounts.google.com/ServiceLogin" method="get">
<input type="hidden" name="continue" value="https://drive.google.com/uc">
</form></body></html>"""
GD_MKV_HEAD = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1f\x42\x82\x45\x9c"



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

    def test_206_octet_stream_holding_ebml_is_active_because_of_its_header(self):
        # Drive's answer: no video content type, a real Matroska stream. Without
        # the container check this probe could never report a Drive file active.
        fetch = scripted_fetch({"a": (206, GD_MKV_HEAD, {
            "content-type": "application/octet-stream",
            "content-range": "bytes 0-511/253161185"})})
        verdict = hr.probe_range("https://h/a", fetch=fetch)
        self.assertEqual((verdict["status"], verdict["size_bytes"]),
                         ("active", 253161185))
        self.assertIn("holds a matroska container", verdict["reason"])

    def test_200_octet_stream_holding_ftyp_is_active_and_flagged_full_body(self):
        fetch = scripted_fetch({"a": (200, b"\x00\x00\x00 ftypisom" + b"z" * 20,
                                      {"content-type": "application/octet-stream"})})
        verdict = hr.probe_range("https://h/a", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertIn("full_body", verdict["reason"])
        self.assertEqual(verdict["size_bytes"], 32)

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
# pkembed — recognition, the base-36 packer, renditions, expiry
# ---------------------------------------------------------------------------

class TestPkembedRecognition(unittest.TestCase):
    def test_the_real_embed_shape_is_accepted(self):
        self.assertTrue(hr.is_pkembed_embed(PK_EMBED))

    def test_the_bare_filecode_page_is_a_pkembed_too(self):
        """`/<code>.html` is the second shape the host serves, measured live.

        `pkembed.site/zp8vd43rpa80.html` answers 200 with the same packed config
        as `/embed-<code>.html` and probes `206 video/mp4`; it is what this
        catalog writes into a `download` row. Requiring the `embed-` prefix would
        leave a resolvable file filed as an iframe.
        """
        self.assertTrue(hr.is_pkembed_embed(PK_BARE_EMBED))

    def test_an_ordinary_page_on_the_host_is_not_a_filecode(self):
        for url in ("https://pkembed.site/index.html",
                    "https://pkembed.site/embed-x.html",
                    "https://pkembed.site/",
                    "https://pkembed.site/embed-g64v61whic26"):
            self.assertFalse(hr.is_pkembed_embed(url), url)

    def test_a_protocol_relative_embed_url_is_accepted(self):
        # MoviesMela publishes some players as `//host/…`; a matcher that
        # requires a scheme would drop them.
        self.assertTrue(hr.is_pkembed_embed("//pkembed.site/embed-g64v61whic26.html"))

    def test_mxdrop_path_shape_is_not_a_pkembed(self):
        # The owner's trap in both directions: a matcher written for `/e/<id>`
        # finds zero pkembeds, and a pkembed matcher must not claim mxdrop's.
        self.assertFalse(hr.is_pkembed_embed("https://pkembed.site/e/g64v61whic26"))
        self.assertFalse(hr.is_mxdrop_embed(PK_EMBED))

    def test_a_look_alike_host_is_not_pkembed(self):
        self.assertFalse(hr.is_pkembed_embed(
            "https://pkembed.site.evil.test/embed-x.html"))
        self.assertFalse(hr.is_pkembed_embed("https://notpkembed.site/embed-x.html"))

    def test_an_empty_or_pathless_url_is_nothing(self):
        self.assertFalse(hr.is_pkembed_embed(""))
        self.assertFalse(hr.is_pkembed_embed("/embed-x.html"))
        self.assertFalse(hr.is_mxdrop_embed(""))


class TestPkembedPacker(unittest.TestCase):
    def test_the_four_argument_base_36_call_unpacks_to_the_player(self):
        config = hr.find_packed_config(PK_PACKED_PAGE)
        self.assertIn('<source src="https://plus1.vkpluscdn.site/v/01/00002'
                      '/g64v61whic26_l/l.mp4', config)
        self.assertIn("posterImage:'" + PK_POSTER + "'", config)

    def test_js_escapes_are_resolved_before_the_substitutions_run(self):
        # The packer substitutes on the parsed string value, so `\'` is a quote
        # by the time the indices are walked. Substituting first would leave a
        # backslash inside every inserted key.
        config = hr.find_packed_config(PK_PACKED_PAGE)
        self.assertNotIn("\\", config)
        self.assertIn("$('#vplayer').append(", config)

    def test_indices_are_written_in_base_36_not_in_decimal(self):
        keys = [""] * 52
        keys[10], keys[35], keys[36], keys[51] = "TEN", "THIRTYFIVE", "THIRTYSIX", "FIFTYONE"
        # 10 -> "a", 35 -> "z", 36 -> "10", 51 -> "1f". A decimal-only unpacker
        # would leave every one of these four untouched.
        out = hr.unpack_packed_js("v1=a v2=z v3=10 v4=1f", 36, 52, keys)
        self.assertEqual(out, "v1=TEN v2=THIRTYFIVE v3=THIRTYSIX v4=FIFTYONE")

    def test_base_36_renderings(self):
        self.assertEqual(hr.to_base(10, 36), "a")
        self.assertEqual(hr.to_base(35, 36), "z")
        self.assertEqual(hr.to_base(36, 36), "10")

    def test_the_empty_first_key_leaves_literal_zeros_alone(self):
        # Every real pkembed call has k[0] == ''. Replacing "0" with it — even
        # with the empty string — would eat the zeros out of the file path and
        # the player settings.
        payload = "i=0.3;sp=3000;p=01/00002"
        self.assertEqual(hr.unpack_packed_js(payload, 36, 2, ["", "X"]), payload)


class TestPkembedRenditions(unittest.TestCase):
    def test_both_tags_are_kept_with_the_host_s_own_labels(self):
        renditions = hr.pkembed_renditions(hr.find_packed_config(PK_PACKED_PAGE))
        self.assertEqual([item["url"] for item in renditions], [PK_L_MP4, PK_N_MP4])
        self.assertEqual([item["label"] for item in renditions],
                         ["360p 326 kbps", "480p 562 kbps"])
        self.assertEqual([item["mime"] for item in renditions], ["video/mp4", "video/mp4"])

    def test_the_media_host_is_whatever_the_payload_says(self):
        # plusN.vkpluscdn.site and stoplus.vkcdn5.com were both measured; the
        # hostname is never pinned, so a rendition on either is accepted.
        found = hr.pkembed_renditions(VKCDN5_CONFIG)
        self.assertEqual(len(found), 1)
        self.assertIn("stoplus.vkcdn5.com", found[0]["url"])

    def test_the_l_rendition_is_preferred(self):
        renditions = hr.pkembed_renditions(hr.find_packed_config(PK_PACKED_PAGE))
        self.assertEqual(hr.select_rendition(renditions)["url"], PK_L_MP4)

    def test_the_n_rendition_is_the_fallback(self):
        only_n = [{"url": PK_N_MP4, "mime": "video/mp4", "label": "480p"}]
        self.assertEqual(hr.select_rendition(only_n)["url"], PK_N_MP4)

    def test_any_rendition_is_better_than_none(self):
        other = [{"url": "https://h/v/x.mp4", "mime": "", "label": ""}]
        self.assertEqual(hr.select_rendition(other)["url"], "https://h/v/x.mp4")
        self.assertIsNone(hr.select_rendition([]))

    def test_a_media_url_without_a_source_tag_is_still_found(self):
        found = hr.pkembed_renditions('file:"//c.site/v/a.m3u8",x:1')
        self.assertEqual(found, [{"url": "https://c.site/v/a.m3u8", "mime": "",
                                  "label": ""}])

    def test_a_poster_is_never_a_rendition(self):
        self.assertEqual(
            hr.pkembed_renditions("posterImage:'https://h/i/x.jpg'"), [])

    def test_a_source_tag_without_a_media_extension_is_ignored(self):
        self.assertEqual(hr.pkembed_renditions('<source src="https://h/track">'), [])


class TestPkembedExpiry(unittest.TestCase):
    def test_lifetime_expiry_is_the_issue_epoch_plus_the_window(self):
        expires_at, expires_in = hr.duration_expiry_from_url(PK_L_MP4)
        self.assertEqual(expires_at, 1793148018 + 43200)
        self.assertAlmostEqual(expires_in, expires_at - time.time(), delta=5)

    def test_mxdrop_absolute_expiry_is_not_read_as_a_lifetime(self):
        # mxdrop's `s` is the signature, not a timestamp, so the lifetime reader
        # refuses it instead of inventing an expiry.
        self.assertEqual(hr.duration_expiry_from_url(WURL), (None, None))

    def test_pkembed_lifetime_is_not_read_as_an_absolute_expiry(self):
        # `e=43200` read as an epoch is 1970: a live file would be reported as
        # long expired. The digit-count guard is what keeps the two hosts apart.
        self.assertEqual(hr.expiry_from_url(PK_L_MP4), (None, None))

    def test_a_query_without_both_numbers_has_no_expiry(self):
        self.assertEqual(hr.duration_expiry_from_url(
            "https://h/x.mp4?s=1793148018"), (None, None))
        self.assertEqual(hr.duration_expiry_from_url(
            "https://h/x.mp4?s=123&e=43200"), (None, None))


class TestUnwrapPkembed(unittest.TestCase):
    def scripted(self, **over):
        script = {PK_EMBED: (200, PK_PACKED_PAGE, {}),
                  ".mp4": (206, b"\x00\x00\x00 ftypisom",
                           {"content-type": "video/mp4",
                            "content-range": "bytes 0-511/201886684"})}
        script.update(over)
        return scripted_fetch(script)

    def test_full_chain_active(self):
        fetch = self.scripted()
        verdict = hr.unwrap_pkembed(PK_EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "pkembed")
        self.assertTrue(verdict["is_temporary"])
        self.assertEqual(verdict["embed_url"], PK_EMBED)
        self.assertEqual(verdict["final_url"], PK_L_MP4)
        self.assertEqual(verdict["poster_url"], PK_POSTER)
        self.assertEqual(verdict["quality"], "360p 326 kbps")
        self.assertEqual([item["url"] for item in verdict["sources"]],
                         [PK_L_MP4, PK_N_MP4])
        self.assertEqual(verdict["signed_params"], ["e", "s", "t"])
        self.assertEqual(verdict["size_bytes"], 201886684)
        self.assertEqual(verdict["subtitles"], [])
        self.assertEqual(verdict["notes"], [])

    def test_the_bare_filecode_page_resolves_through_the_same_chain(self):
        fetch = self.scripted(**{PK_BARE_EMBED: (200, PK_PACKED_PAGE, {})})
        verdict = hr.unwrap_pkembed(PK_BARE_EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "active", verdict["notes"])
        self.assertEqual(verdict["embed_url"], PK_BARE_EMBED)
        self.assertEqual([item["url"] for item in verdict["sources"]],
                         [PK_L_MP4, PK_N_MP4])

    def test_the_signed_url_is_reported_not_stored(self):
        verdict = hr.unwrap_pkembed(PK_EMBED, fetch=self.scripted())
        # The durable field is the embed URL; the media URL is only ever a
        # return value, so a caller that persists `embed_url` keeps nothing that
        # expires.
        self.assertEqual(verdict["embed_url"], PK_EMBED)
        self.assertTrue(verdict["final_url"].startswith("https://plus1.vkpluscdn.site/"))

    def test_no_media_request_carries_a_referer(self):
        fetch = self.scripted()
        hr.unwrap_pkembed(PK_EMBED, fetch=fetch,
                          referer="https://www.moviesmela.com/watch/x/")
        for _url, headers, _method in fetch.calls:
            self.assertNotIn("Referer", headers)

    def test_a_forbidden_referer_is_recorded_as_withheld(self):
        verdict = hr.unwrap_pkembed(
            PK_EMBED, fetch=self.scripted(), referer="https://www.moviesmela.com/x")
        self.assertIn("referrer withheld", verdict["notes"][0])

    def test_verify_off_is_one_request_and_says_so(self):
        fetch = scripted_fetch({PK_EMBED: (200, PK_PACKED_PAGE, {})})
        verdict = hr.unwrap_pkembed(PK_EMBED, fetch=fetch, verify=False)
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(len(fetch.calls), 1)
        self.assertIn("not probed", json.dumps(verdict["notes"]))

    def test_a_non_pkembed_url_is_refused_before_any_request(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_pkembed(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("not a pkembed embed URL", verdict["notes"])
        self.assertEqual(fetch.calls, [])

    def test_embed_page_failure_shapes(self):
        for status, expected in ((404, "dead"), (410, "dead"), (403, "blocked"),
                                 (429, "blocked"), (500, "unknown"), (204, "unknown")):
            fetch = scripted_fetch({PK_EMBED: (status, b"", {})})
            verdict = hr.unwrap_pkembed(PK_EMBED, fetch=fetch)
            self.assertEqual(verdict["status"], expected, status)
            self.assertEqual(verdict["notes"], [f"embed page HTTP {status}"])

    def test_a_page_that_publishes_no_media_url_is_unknown(self):
        # A page that unpacks but names no byte endpoint (a deleted file, a
        # premium gate) is reported as unknown, not as a dead host.
        config = "$('#vplayer').append('<div>upgrade to watch</div>');"
        fetch = scripted_fetch({PK_EMBED: (200, PK_PACKED_PAGE, {})})
        with mock.patch.object(hr, "find_packed_config", lambda _html: config):
            verdict = hr.unwrap_pkembed(PK_EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(verdict["final_url"], "")
        self.assertIn("publishes no media URL", json.dumps(verdict["notes"]))
        self.assertEqual(len(fetch.calls), 1)

    def test_blocked_media_with_a_live_poster_is_an_expired_signature(self):
        fetch = self.scripted(**{
            ".mp4": (403, b"<html>no</html>", {"content-type": "text/html"}),
            ".jpg": (200, b"j", {"content-type": "image/jpeg"})})
        verdict = hr.unwrap_pkembed(PK_EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "blocked")
        self.assertIn("signature expired", json.dumps(verdict["notes"]))

    def test_blocked_media_with_a_dead_poster_is_dead(self):
        fetch = self.scripted(**{
            ".mp4": (403, b"", {"content-type": "text/html"}),
            ".jpg": (404, b"", {"content-type": "text/html"})})
        verdict = hr.unwrap_pkembed(PK_EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "dead")
        self.assertIn("host no longer serves", json.dumps(verdict["notes"]))

    def test_media_that_answers_html_is_not_called_active(self):
        fetch = self.scripted(**{".mp4": (206, b"<html>", {"content-type": "text/html"})})
        verdict = hr.unwrap_pkembed(PK_EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("206 text/html", json.dumps(verdict["notes"]))

    def test_a_published_caption_url_becomes_a_track(self):
        config = ('<source src="//c.site/v/x_l/l.mp4?t=1&s=1793148018&e=43200"'
                  ' type="video/mp4">tracks:[{file:"//c.site/v/x.en.vtt"}]')
        with mock.patch.object(hr, "find_packed_config", lambda _html: config):
            verdict = hr.unwrap_pkembed(PK_EMBED, fetch=self.scripted())
        self.assertEqual(verdict["subtitles"],
                         [{"language": "subtitle", "url": "https://c.site/v/x.en.vtt"}])

    def test_the_view_ping_is_not_mistaken_for_a_caption(self):
        # pkembed's script mentions `upload_srt` as a query parameter on its own
        # statistics call; a parameter name is not a track.
        verdict = hr.unwrap_pkembed(PK_EMBED, fetch=self.scripted())
        self.assertEqual(verdict["subtitles"], [])

    def test_unparsable_expiry_is_recorded(self):
        config = ('<source src="//c.site/v/x_l/l.mp4?t=1&s=12&e=43200" '
                  'type="video/mp4">')
        with mock.patch.object(hr, "find_packed_config", lambda _html: config):
            verdict = hr.unwrap_pkembed(PK_EMBED, fetch=self.scripted())
        self.assertIsNone(verdict["expires_in"])
        self.assertIn("no parsable expiry", json.dumps(verdict["notes"]))


# ---------------------------------------------------------------------------
# Google Drive: recognition, the interstitial, the container header
# ---------------------------------------------------------------------------

class TestContainerMagic(unittest.TestCase):
    def test_ebml_is_a_matroska_container(self):
        self.assertEqual(hr.container_magic(GD_MKV_HEAD), "matroska")

    def test_ftyp_at_offset_four_is_the_iso_base_media_family(self):
        self.assertEqual(hr.container_magic(b"\x00\x00\x00 ftypisom"), "mp4")

    def test_a_page_or_a_short_slice_names_no_container(self):
        self.assertEqual(hr.container_magic(b"<html><body>"), "")
        self.assertEqual(hr.container_magic(b"\x1a\x45"), "")

    def test_a_text_body_is_judged_on_its_bytes(self):
        self.assertEqual(hr.container_magic("no video here"), "")


class TestGdriveRecognition(unittest.TestCase):
    def test_the_download_endpoint_query_names_the_file(self):
        self.assertEqual(hr.gdrive_file_id(GD_DOWNLOAD_PAGE), GD_FILE_ID)
        self.assertTrue(hr.is_gdrive_link(GD_DOWNLOAD_PAGE))

    def test_the_viewer_path_names_the_same_file(self):
        self.assertEqual(
            hr.gdrive_file_id(f"https://drive.google.com/file/d/{GD_FILE_ID}/view"),
            GD_FILE_ID)

    def test_a_protocol_relative_drive_url_is_read_the_same_way(self):
        self.assertEqual(
            hr.gdrive_file_id(f"//drive.google.com/uc?id={GD_FILE_ID}"), GD_FILE_ID)

    def test_another_host_is_not_a_drive_file(self):
        self.assertEqual(hr.gdrive_file_id(f"https://mxdrop.to/uc?id={GD_FILE_ID}"), "")
        self.assertEqual(hr.gdrive_file_id(""), "")

    def test_a_drive_page_without_an_id_names_no_file(self):
        self.assertEqual(hr.gdrive_file_id("https://drive.google.com/drive/folders/x"), "")

    def test_an_id_that_is_too_short_or_not_url_safe_is_refused(self):
        self.assertEqual(hr.gdrive_file_id("https://drive.google.com/uc?id=abc123"), "")
        self.assertEqual(
            hr.gdrive_file_id("https://drive.google.com/uc?id=" + "a" * 30 + "%2F.."), "")

    def test_the_stored_identifier_is_the_endpoint_and_the_id(self):
        self.assertEqual(hr.gdrive_download_url(GD_FILE_ID), GD_DOWNLOAD_PAGE)


class TestDriveConfirmForm(unittest.TestCase):
    def test_the_interstitial_replay_url_is_what_the_page_published(self):
        self.assertEqual(hr.drive_confirm_form(GD_INTERSTITIAL), GD_REPLAY)

    def test_a_form_on_somebody_else_s_host_is_not_replayed(self):
        # The action is the page's data, not an instruction about where the next
        # request goes; a forged interstitial must not become an outbound request
        # to an attacker's host.
        page = GD_INTERSTITIAL.replace("https://drive.usercontent.google.com/download",
                                       "https://evil.test/steal")
        self.assertEqual(hr.drive_confirm_form(page), "")

    def test_a_page_with_no_form_publishes_no_replay(self):
        self.assertEqual(hr.drive_confirm_form(GD_SIGNIN_WALL), "")
        self.assertEqual(hr.drive_confirm_form(""), "")

    def test_a_form_with_no_fields_is_not_turned_into_a_bare_url(self):
        self.assertEqual(hr.drive_confirm_form(
            '<form action="https://drive.usercontent.google.com/download"></form>'), "")

    def test_single_quotes_and_an_unnamed_input_are_both_survived(self):
        page = ("""<form action='https://drive.usercontent.google.com/download'>"""
                """<input type='hidden' name='id' value='%s'>"""
                """<input type='submit' value='go'></form>""" % GD_FILE_ID)
        self.assertEqual(hr.drive_confirm_form(page),
                         "https://drive.usercontent.google.com/download?"
                         f"id={GD_FILE_ID}")

    def test_a_relative_action_is_absolute_before_it_is_checked(self):
        page = ('<form action="//drive.usercontent.google.com/download">'
                '<input type="hidden" name="id" value="%s"></form>' % GD_FILE_ID)
        self.assertTrue(hr.drive_confirm_form(page).startswith("https://"))


class TestUnwrapGdrive(unittest.TestCase):
    def scripted(self, **over):
        script = {
            "drive.google.com/uc": (200, GD_INTERSTITIAL, {"content-type": "text/html"}),
            "drive.usercontent.google.com/download": (
                206, GD_MKV_HEAD, {"content-type": "application/octet-stream",
                                   "content-range": "bytes 0-511/253161185"}),
        }
        script.update(over)
        return scripted_fetch(script)

    def test_the_two_step_chain_reaches_a_real_matroska_stream(self):
        fetch = self.scripted()
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "active", verdict["notes"])
        self.assertEqual(verdict["service"], "gdrive")
        self.assertEqual(verdict["file_id"], GD_FILE_ID)
        self.assertEqual(verdict["embed_url"], GD_DOWNLOAD_PAGE)
        self.assertEqual(verdict["final_url"], GD_REPLAY)
        self.assertTrue(verdict["is_temporary"])
        self.assertEqual(verdict["size_bytes"], 253161185)
        self.assertEqual([item["url"] for item in verdict["sources"]], [GD_REPLAY])
        self.assertEqual([url for url, _h, _m in fetch.calls],
                         [GD_DOWNLOAD_PAGE, GD_REPLAY])
        self.assertIn("confirmation page, replayed once", json.dumps(verdict["notes"]))

    def test_the_viewer_url_resolves_through_the_same_chain(self):
        verdict = hr.unwrap_gdrive(
            f"https://drive.google.com/file/d/{GD_FILE_ID}/view", fetch=self.scripted())
        self.assertEqual(verdict["embed_url"], GD_DOWNLOAD_PAGE)
        self.assertEqual(verdict["status"], "active", verdict["notes"])

    def test_the_verdict_is_signed_param_free_and_carries_no_token(self):
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=self.scripted())
        self.assertEqual(verdict["signed_params"], [])

    def test_no_request_this_resolver_makes_carries_a_referer(self):
        fetch = self.scripted()
        hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch, referer="https://animahd.com/x")
        for _url, headers, _method in fetch.calls:
            self.assertNotIn("Referer", headers)

    def test_a_forbidden_referer_is_recorded_as_withheld(self):
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=self.scripted(),
                                   referer="https://www.moviesmela.com/x")
        self.assertIn("referrer withheld", verdict["notes"][0])

    def test_verify_off_asks_drive_for_nothing_at_all(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch, verify=False)
        self.assertEqual(fetch.calls, [])
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(verdict["final_url"], GD_DOWNLOAD_PAGE)
        self.assertFalse(verdict["is_temporary"])
        self.assertIn("without a request", json.dumps(verdict["notes"]))

    def test_a_non_drive_url_is_refused_before_any_request(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_gdrive(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("not a Google Drive file URL", verdict["notes"])
        self.assertEqual(fetch.calls, [])

    def test_a_small_public_file_leads_straight_to_its_bytes(self):
        # The first answer is not a page: the endpoint redirects to the byte host
        # and serves the file, so the resolver must not go looking for a form that
        # was never published. The stand-in reports the redirect target as
        # `http_request` would, which is what the probe then has to be pointed at.
        byte_url = ("https://drive.usercontent.google.com/download?id="
                    + GD_FILE_ID + "&export=download&authuser=0")
        calls = []

        def fetch(url, headers=None, timeout=None, method="GET", follow=True):
            calls.append((url, headers or {}, method))
            if "usercontent" in url:
                return (206, GD_MKV_HEAD, {"content-type": "application/octet-stream",
                                           "content-range": "bytes 0-511/4096"}, url)
            return (200, GD_MKV_HEAD,
                    {"content-type": "application/octet-stream"}, byte_url)

        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "active", verdict["notes"])
        self.assertEqual(verdict["final_url"], byte_url)
        self.assertFalse(verdict["is_temporary"])
        self.assertIn("led straight to its bytes", json.dumps(verdict["notes"]))
        self.assertEqual(verdict["size_bytes"], 4096)
        self.assertEqual([url for url, _h, _m in calls], [GD_DOWNLOAD_PAGE, byte_url])

    def test_a_deleted_file_is_dead_and_says_which_one(self):
        for status in (404, 410):
            fetch = scripted_fetch({"drive.google.com/uc": (status, b"", {})})
            verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
            self.assertEqual(verdict["status"], "dead", status)
            self.assertIn(GD_FILE_ID, json.dumps(verdict["notes"]))

    def test_a_refused_or_broken_endpoint_is_unverified_not_dead(self):
        for status in (403, 429, 503, 0):
            fetch = scripted_fetch({"drive.google.com/uc": (status, b"quota", {})})
            verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
            self.assertEqual(verdict["status"], "unverified", status)
            self.assertEqual(len(fetch.calls), 1)
            self.assertIn("not a verdict about the file", json.dumps(verdict["notes"]))

    def test_a_probe_refused_by_the_quota_is_replayed_once_and_stops_unverified(self):
        # The interstitial parsed fine; only the byte endpoint throttled. One
        # attempt was spent and the file is left unverified rather than retried
        # or called dead.
        fetch = self.scripted(**{
            "drive.usercontent.google.com/download": (403, b"", {"content-type": "text/html"})})
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(len(fetch.calls), 2)
        self.assertIn("per-file download quota", json.dumps(verdict["notes"]))

    def test_a_page_that_offers_no_download_form_is_blocked_not_unverified(self):
        fetch = scripted_fetch({"drive.google.com/uc": (200, GD_SIGNIN_WALL,
                                                       {"content-type": "text/html"})})
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "blocked")
        self.assertIn("the file is not public", json.dumps(verdict["notes"]))
        self.assertEqual(len(fetch.calls), 1)

    def test_an_html_answer_under_an_octet_stream_label_is_still_an_interstitial(self):
        # A mislabelled response must not be mistaken for the file's bytes: the
        # body, not the header alone, decides which branch runs.
        fetch = scripted_fetch({
            "drive.google.com/uc": (200, GD_INTERSTITIAL,
                                    {"content-type": "application/octet-stream"}),
            "drive.usercontent": (206, GD_MKV_HEAD,
                                  {"content-type": "application/octet-stream",
                                   "content-range": "bytes 0-511/10"}),
        })
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
        self.assertEqual(verdict["final_url"], GD_REPLAY)
        self.assertEqual(verdict["status"], "active", verdict["notes"])

    def test_bytes_that_are_not_a_video_container_are_not_called_active(self):
        fetch = self.scripted(**{
            "drive.usercontent.google.com/download": (
                206, b"PK\x03\x04 zip data", {"content-type": "application/octet-stream"})})
        verdict = hr.unwrap_gdrive(GD_DOWNLOAD_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("octet-stream", json.dumps(verdict["notes"]))


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

    def test_a_pkembed_url_dispatches_to_the_pkembed_resolver(self):
        fetch = scripted_fetch({PK_EMBED: (200, PK_PACKED_PAGE, {}),
                                ".mp4": (206, b"x", {"content-type": "video/mp4"})})
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main([PK_EMBED]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "pkembed")
        self.assertEqual(printed["status"], "active")

    def test_a_drive_url_dispatches_to_the_drive_resolver(self):
        fetch = scripted_fetch({
            "drive.google.com/uc": (200, GD_INTERSTITIAL, {"content-type": "text/html"}),
            "drive.usercontent": (206, GD_MKV_HEAD,
                                  {"content-type": "application/octet-stream",
                                   "content-range": "bytes 0-511/253161185"})})
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main([GD_DOWNLOAD_PAGE]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "gdrive")
        self.assertEqual(printed["status"], "active")

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
