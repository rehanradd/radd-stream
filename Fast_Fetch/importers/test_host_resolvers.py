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
import base64
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

# AnimaHD's own player, as saved from this host on 2026-10-28 into
# /tmp/animahd_player_194_0.html (84,066 bytes) and
# /tmp/animahd_secure_194_0.html (57,526 bytes) for file id
# `10i-vf0OzJqDkR0-a7MpPWKI0qERYAOp1` (Naruto Shippuden S01E01). What is kept
# below is each page's own markup verbatim, reduced to what the resolver has to
# read; the redirect literal, the `<source>` tag and the quota wording are the
# bytes the hosts served. The `eid` is real; the `token` is its first 64
# characters — the live value runs to 2,732 characters and is this host's
# per-load secret, which the resolver is not allowed to need. Replaying the
# saved chain answered 206, `video/x-matroska`,
# `Content-Range bytes 0-511/253161185`, EBML magic, with no Referer sent.
AH_FILE_ID = "10i-vf0OzJqDkR0-a7MpPWKI0qERYAOp1"
AH_PLAYER_URL = f"https://animahd.com/player/?file_id={AH_FILE_ID}&show_id=194&ep=0"
AH_EID = ("MjAyMTc4M2M2Nzc3MjE1ZTZiNWI2MDU1N2E0MzIxM2M3MDI2NWM2MTQxNDY1YTU4"
          "MjE2MDU0NDM0ODUwNWU2MTIw")
AH_TOKEN = "Njg3MDIzMjgzZjcyM2Y3MjIxNTA0YjI1NzM1ZjYxNGIyMDVmMjkyOTdhNzY2MzVjN2E3"
AH_WORKER_URL = ("https://cdndirectstreamwithoutbreaking.animahd011.workers.dev/"
                 f"?eid={AH_EID}&token={AH_TOKEN}&v=0&ext=.mp4")
AH_SECURE_URL = f"https://theultimateanimehub.animahd.fun/?id={AH_FILE_ID}"
AH_PLAYER_PAGE = """<!DOCTYPE html><html><head><title>ANIMAHD</title></head><body>
<div class="cinema-deck-frame">
    <div class="animesuki-loader"><span></span><span></span><span></span></div>
    <div class="loading-text-anim">Connecting to Secure Player...</div>
</div>

<script>
document.addEventListener('DOMContentLoaded', () => {
    const targetStreamUrl = "https://theultimateanimehub.animahd.fun/?id=10i-vf0OzJqDkR0-a7MpPWKI0qERYAOp1";

    if (targetStreamUrl) {
        // Use location.replace() so users don't get trapped in a back-button loop
        setTimeout(() => {
            window.location.replace(targetStreamUrl);
        }, 800); // 800ms delay to allow the animation to display smoothly
    }
});
</script>
</body></html>"""
AH_SECURE_PAGE = """<!DOCTYPE html><html><head>
<title>[ANIMAHD.COM] S01E01 Naruto Shippuden.mkv</title></head><body>
<video id="player" playsinline controls preload="metadata">
    <source src="%(worker)s" type="video/mp4" onerror="window.handleVideoError()" />
</video>
<script>
    function handleVideoError() {
        container.innerHTML = '<h3>Stream Locked by Google</h3>'
            + '<p>The API limit has been reached. Auto-switching to the Alternative '
            + 'Player in 3 seconds...</p>';
        window.location.href = '?eid=%(eid)s&fallback=1';
    }
    window.proxyDownloadUrl = '%(worker)s&filename=%%5BANIMAHD.COM%%5D.mkv&v=0';
</script>
</body></html>""" % {"worker": AH_WORKER_URL, "eid": AH_EID}
AH_WORKER_HEAD = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1f\x42\x82\x45\x9c"



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
    A `fetch(url, headers, timeout, method, follow, data)` stand-in.

    `script` maps a URL (or the substring a URL must contain) to either a
    (status, body, headers) triple or an Exception to raise.
    """
    calls = []

    def fetch(url, headers=None, timeout=None, method="GET", follow=True, data=None):
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

    def test_transport_failure_is_retried_then_succeeds(self):
        # Session 126 follow-up: the MovieBox edge resets ~2 of 3 handshakes,
        # so the first reset must not be the verdict — a retry that answers
        # is a success, not a transport failure.
        calls = {"n": 0}

        def flaky_open(request, timeout, follow=True):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("TLS reset")
            return FakeResponse(200, "ok", {}, "https://x.test/a")

        with mock.patch.object(hr, "_open", flaky_open), \
                mock.patch.object(time, "sleep"):
            status, body, _headers, _final = hr.http_request("https://x.test/a")
        self.assertEqual((status, body, calls["n"]), (200, b"ok", 3))

    def test_transport_failure_after_all_retries_reports_status_zero(self):
        calls = {"n": 0}

        def dead_open(request, timeout, follow=True):
            calls["n"] += 1
            raise OSError("TLS reset")

        with mock.patch.object(hr, "_open", dead_open), \
                mock.patch.object(time, "sleep"):
            status, _body, _headers, _final = hr.http_request("https://x.test/a")
        self.assertEqual((status, calls["n"]),
                         (0, hr.TRANSPORT_RETRIES + 1))

    def test_http_error_is_never_retried(self):
        # An HTTP answer is evidence about the URL, not the network: a 429
        # returns at once, however many transport retries are budgeted.
        error = urllib.error.HTTPError("https://x.test/a", 429, "Slow down",
                                       {}, io.BytesIO(b"slow"))
        calls = {"n": 0}

        def counting_open(request, timeout, follow=True):
            calls["n"] += 1
            raise error

        with mock.patch.object(hr, "_open", counting_open), \
                mock.patch.object(time, "sleep"):
            status, _body, _headers, _final = hr.http_request("https://x.test/a")
        self.assertEqual((status, calls["n"]), (429, 1))

    def test_explicit_zero_retries_means_one_attempt(self):
        calls = {"n": 0}

        def dead_open(request, timeout, follow=True):
            calls["n"] += 1
            raise OSError("TLS reset")

        with mock.patch.object(hr, "_open", dead_open), \
                mock.patch.object(time, "sleep"):
            status, _body, _headers, _final = hr.http_request(
                "https://x.test/a", transport_retries=0)
        self.assertEqual((status, calls["n"]), (0, 1))

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
# Vidbolt & Vibuxer
# ---------------------------------------------------------------------------

class TestVidboltRecognition(unittest.TestCase):
    def test_movie_url_is_recognized(self):
        self.assertTrue(hr.is_vidbolt_embed("https://vidbolt.xyz/movie/550"))
        self.assertTrue(hr.is_vidbolt_embed("https://vidbolt.xyz/embed/movie/550"))
        self.assertTrue(hr.is_vidbolt_embed("https://vidbolt.pro/movie/550"))

    def test_tv_url_is_recognized(self):
        self.assertTrue(hr.is_vidbolt_embed("https://vidbolt.xyz/tv/194718/1/1"))
        self.assertTrue(hr.is_vidbolt_embed("https://vidbolt.xyz/embed/tv/194718/1/1"))

    def test_invalid_url_is_rejected(self):
        self.assertFalse(hr.is_vidbolt_embed("https://vidbolt.xyz/"))
        self.assertFalse(hr.is_vidbolt_embed("https://vidbolt.xyz/about"))
        self.assertFalse(hr.is_vidbolt_embed("https://evilvidbolt.xyz/movie/550"))

    def test_url_parser_extracts_content_keys(self):
        movie = hr.vidbolt_parse_url("https://vidbolt.xyz/movie/550")
        self.assertEqual(movie, {"type": "movie", "tmdb_id": "550", "season": None, "episode": None})
        tv = hr.vidbolt_parse_url("https://vidbolt.xyz/tv/194718/2/5")
        self.assertEqual(tv, {"type": "tv", "tmdb_id": "194718", "season": "2", "episode": "5"})


class TestVibuxerRecognition(unittest.TestCase):
    def test_embed_url_is_recognized(self):
        self.assertTrue(hr.is_vibuxer_embed("https://vibuxer.com/e/i4p45adamelv"))
        self.assertTrue(hr.is_vibuxer_embed("https://vibuxer.com/embed/i4p45adamelv"))
        # DB row may have a tab character before path
        self.assertTrue(hr.is_vibuxer_embed("https://vibuxer.com\t/e/i4p45adamelv"))

    def test_invalid_url_is_rejected(self):
        self.assertFalse(hr.is_vibuxer_embed("https://vibuxer.com/"))
        self.assertFalse(hr.is_vibuxer_embed("https://vibuxer.com/login"))
        self.assertFalse(hr.is_vibuxer_embed("https://evilvibuxer.com/e/i4p45adamelv"))


class TestVidriftRecognition(unittest.TestCase):
    def test_movie_url_is_recognized(self):
        self.assertTrue(hr.is_vidrift_embed("https://embed.vidrift.net/embed/movie/550"))
        self.assertTrue(hr.is_vidrift_embed("https://embed.vidrift.net/movie/550"))

    def test_tv_url_is_recognized(self):
        self.assertTrue(hr.is_vidrift_embed("https://embed.vidrift.net/embed/tv/194718/1/1"))
        self.assertTrue(hr.is_vidrift_embed("https://embed.vidrift.net/tv/194718/1/1"))

    def test_invalid_url_is_rejected(self):
        self.assertFalse(hr.is_vidrift_embed("https://embed.vidrift.net/"))
        self.assertFalse(hr.is_vidrift_embed("https://embed.vidrift.net/about"))
        self.assertFalse(hr.is_vidrift_embed("https://fakevidrift.net/movie/550"))

    def test_url_parser_extracts_content_keys(self):
        movie = hr.vidrift_parse_url("https://embed.vidrift.net/embed/movie/550")
        self.assertEqual(movie, {"type": "movie", "tmdb_id": "550", "season": None, "episode": None})
        tv = hr.vidrift_parse_url("https://embed.vidrift.net/embed/tv/194718/2/5")
        self.assertEqual(tv, {"type": "tv", "tmdb_id": "194718", "season": "2", "episode": "5"})


class TestIqsmartRecognition(unittest.TestCase):
    def test_movie_url_is_recognized(self):
        self.assertTrue(hr.is_iqsmart_embed("https://streams.iqsmartgames.com/embed/movie/tt35786199?key=abc"))
        self.assertTrue(hr.is_iqsmart_embed("https://streams.iqsmartgames.com/embed/movie/12345?key=abc"))

    def test_tv_url_is_recognized(self):
        self.assertTrue(hr.is_iqsmart_embed("https://streams.iqsmartgames.com/embed/tv/139512/2/2?key=abc"))

    def test_invalid_url_is_rejected(self):
        self.assertFalse(hr.is_iqsmart_embed("https://streams.iqsmartgames.com/"))
        self.assertFalse(hr.is_iqsmart_embed("https://fakegames.com/embed/movie/123"))

    def test_url_parser_extracts_content_keys(self):
        movie = hr.iqsmart_parse_url("https://streams.iqsmartgames.com/embed/movie/tt35786199?key=mykey")
        self.assertEqual(movie, {"type": "movie", "id": "tt35786199", "season": None, "episode": None, "key": "mykey"})
        tv = hr.iqsmart_parse_url("https://streams.iqsmartgames.com/embed/tv/139512/2/3?key=mykey")
        self.assertEqual(tv, {"type": "tv", "id": "139512", "season": "2", "episode": "3", "key": "mykey"})


class TestFilmuRecognition(unittest.TestCase):
    def test_filmu_url_is_recognized(self):
        self.assertTrue(hr.is_filmu_embed("https://embed.filmu.in/movie/550"))
        self.assertTrue(hr.is_filmu_embed("https://embed.filmu.in/tv/194718/1/1"))

    def test_vidly_url_is_recognized(self):
        self.assertTrue(hr.is_filmu_embed("https://vidly.pro/movie/550"))
        self.assertTrue(hr.is_filmu_embed("https://vidly.pro/tv/194718/1/1"))

    def test_invalid_url_is_rejected(self):
        self.assertFalse(hr.is_filmu_embed("https://embed.filmu.in/"))
        self.assertFalse(hr.is_filmu_embed("https://evilfilmu.in/movie/550"))


class TestCineverseRecognition(unittest.TestCase):
    def test_movie_url_is_recognized(self):
        self.assertTrue(hr.is_cineverse_embed("https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=550"))

    def test_tv_url_is_recognized(self):
        self.assertTrue(hr.is_cineverse_embed("https://rozgarlelo.modiplay.xyz/embed/tmdb/tv?id=194718&s=1&e=1"))

    def test_invalid_url_is_rejected(self):
        self.assertFalse(hr.is_cineverse_embed("https://rozgarlelo.modiplay.xyz/"))
        self.assertFalse(hr.is_cineverse_embed("https://fakemodiplay.xyz/embed/tmdb/movie?id=550"))


class TestVidboltUnpack(unittest.TestCase):
    def test_movie_resolve_active(self):
        api_resp = json.dumps({
            "stream": {
                "server": "orion",
                "sources": [
                    {"url": "https://cdn.example.com/stream.m3u8", "kind": "hls", "quality": "1080p"}
                ]
            }
        }).encode("utf-8")
        fetch = scripted_fetch({
            "api/resolve": (200, api_resp, {"content-type": "application/json"}),
            "stream.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_vidbolt("https://vidbolt.xyz/movie/550", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "vidbolt")
        self.assertEqual(verdict["final_url"], "https://cdn.example.com/stream.m3u8")
        self.assertEqual(verdict["expires_in"], hr.VIDBOLT_DEFAULT_EXPIRY_SECONDS)

    def test_empty_stream_is_dead(self):
        api_resp = json.dumps({"stream": None}).encode("utf-8")
        fetch = scripted_fetch({
            "api/resolve": (200, api_resp, {"content-type": "application/json"}),
        })
        verdict = hr.unwrap_vidbolt("https://vidbolt.xyz/movie/999999", fetch=fetch)
        self.assertEqual(verdict["status"], "dead")
        self.assertIn("returned no stream", json.dumps(verdict["notes"]))


class TestVibuxerUnpack(unittest.TestCase):
    def test_full_chain_active(self):
        packed = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){w..."
            "}('1.2=\"https://cdn.example.com/hls/master.m3u8?s=1794021195&e=129600\";',10,3,"
            "'|var|links'.split('|'),0,{}))"
        )
        html = f"<html><body><script>{packed}</script></body></html>"
        fetch = scripted_fetch({
            "vibuxer.com/e/": (200, html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-STREAM-INF\nv.m3u8", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_vibuxer("https://vibuxer.com/e/i4p45adamelv", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "vibuxer")
        self.assertEqual(verdict["final_url"], "https://cdn.example.com/hls/master.m3u8?s=1794021195&e=129600")
        self.assertAlmostEqual(verdict["expires_in"], (1794021195 + 129600) - time.time(), delta=10)

    def test_no_m3u8_in_script_is_unknown(self):
        packed = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){w..."
            "}('1.2=\"no video\";',10,3,'|var|links'.split('|'),0,{}))"
        )
        html = f"<html><body><script>{packed}</script></body></html>"
        fetch = scripted_fetch({
            "vibuxer.com/e/": (200, html, {"content-type": "text/html"}),
        })
        verdict = hr.unwrap_vibuxer("https://vibuxer.com/e/i4p45adamelv", fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("publishes no m3u8", json.dumps(verdict["notes"]))


class TestVidriftUnpack(unittest.TestCase):
    def test_movie_resolve_active(self):
        page_html = """
        <html><body>
        <script>
        var embedMeta = {
            "tmdbId": "550",
            "type": "movie",
            "orionStreams": [
                {"url": "/api/orion/abc123hash/master.m3u8?s=123&e=456", "type": "hls", "name": "Orion · Original"}
            ],
            "bigbangSubtitles": [{"label": "English", "url": "/sub.vtt"}]
        };
        </script>
        </body></html>
        """
        fetch = scripted_fetch({
            "embed/movie/550": (200, page_html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_vidrift("https://embed.vidrift.net/embed/movie/550", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "vidrift")
        self.assertEqual(verdict["final_url"], "https://embed.vidrift.net/api/orion/abc123hash/master.m3u8?s=123&e=456")
        self.assertEqual(len(verdict["subtitles"]), 1)

    def test_empty_streams_is_dead(self):
        page_html = '<html><script>var embedMeta = {"orionStreams": []};</script></html>'
        fetch = scripted_fetch({
            "embed/movie/999": (200, page_html, {"content-type": "text/html"}),
        })
        verdict = hr.unwrap_vidrift("https://embed.vidrift.net/embed/movie/999", fetch=fetch)
        self.assertEqual(verdict["status"], "dead")
        self.assertIn("publishes no active streams", json.dumps(verdict["notes"]))


class TestIqsmartUnpack(unittest.TestCase):
    def test_movie_resolve_active(self):
        api_resp = json.dumps({"data": [{"fileslug": "slug123"}]}).encode("utf-8")
        mresult_raw = json.dumps({"smwh": "hanerix_hash"}).encode("utf-8")
        mresult_b64 = base64.b64encode(mresult_raw).decode("utf-8")
        helper_resp = json.dumps({"mresult": mresult_b64}).encode("utf-8")
        han_packed = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){w..."
            "}('1.2=\"https://cdn.example.com/hls/master.m3u8?s=123&e=456\";',10,3,"
            "'|var|links'.split('|'),0,{}))"
        )
        han_html = f"<html><script>{han_packed}</script></html>"

        fetch = scripted_fetch({
            "mymovieapi": (200, api_resp, {"content-type": "application/json"}),
            "embedhelper2.php": (200, helper_resp, {"content-type": "application/json"}),
            "hanerix.com/e/": (200, han_html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_iqsmart("https://streams.iqsmartgames.com/embed/movie/tt35786199?key=mykey", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "iqsmart")
        self.assertEqual(verdict["final_url"], "https://cdn.example.com/hls/master.m3u8?s=123&e=456")

    def test_tv_resolve_active(self):
        api_resp = json.dumps({"data": [{"fileslug": "slug_tv"}]}).encode("utf-8")
        mresult_raw = json.dumps({"smwh": "han_tv"}).encode("utf-8")
        mresult_b64 = base64.b64encode(mresult_raw).decode("utf-8")
        helper_resp = json.dumps({"mresult": mresult_b64}).encode("utf-8")
        han_packed = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){w..."
            "}('1.2=\"https://cdn.example.com/hls/tv_master.m3u8?s=123&e=456\";',10,3,"
            "'|var|links'.split('|'),0,{}))"
        )
        han_html = f"<html><script>{han_packed}</script></html>"

        fetch = scripted_fetch({
            "myseriesapi": (200, api_resp, {"content-type": "application/json"}),
            "embedhelper2.php": (200, helper_resp, {"content-type": "application/json"}),
            "hanerix.com/e/": (200, han_html, {"content-type": "text/html"}),
            "tv_master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_iqsmart("https://streams.iqsmartgames.com/embed/tv/139512/2/2?key=mykey", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["final_url"], "https://cdn.example.com/hls/tv_master.m3u8?s=123&e=456")

    def test_empty_api_is_dead(self):
        api_resp = json.dumps({"data": []}).encode("utf-8")
        fetch = scripted_fetch({
            "mymovieapi": (200, api_resp, {"content-type": "application/json"}),
        })
        verdict = hr.unwrap_iqsmart("https://streams.iqsmartgames.com/embed/movie/tt999999?key=mykey", fetch=fetch)
        self.assertEqual(verdict["status"], "dead")


class TestFilmuUnpack(unittest.TestCase):
    def test_hls_stream_active(self):
        page_html = (
            '<html><body>'
            'var stream = "https://dash-hls-bridge.workers.dev/?url=https%3A%2F%2Fsacdn.example.com%2Fmaster.m3u8\\u0026Policy=abc";'
            '</body></html>'
        )
        fetch = scripted_fetch({
            "vidly.pro/movie/550": (200, page_html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_filmu("https://vidly.pro/movie/550", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "filmu")
        self.assertEqual(verdict["final_url"], "https://dash-hls-bridge.workers.dev/?url=https%3A%2F%2Fsacdn.example.com%2Fmaster.m3u8&Policy=abc")

    def test_no_stream_is_dead(self):
        page_html = "<html><body>No stream available</body></html>"
        fetch = scripted_fetch({
            "vidly.pro/movie/999": (200, page_html, {"content-type": "text/html"}),
        })
        verdict = hr.unwrap_filmu("https://vidly.pro/movie/999", fetch=fetch)
        self.assertEqual(verdict["status"], "dead")


class TestCineverseUnpack(unittest.TestCase):
    def test_direct_vidrift_active(self):
        proxy_html = (
            '<html><script>'
            'var src="https:\\/\\/embed.vidrift.net\\/api\\/orion\\/abcdef123\\/master.m3u8";'
            '</script></html>'
        )
        fetch = scripted_fetch({
            "proxy.php": (200, proxy_html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_cineverse("https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=550", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "cineverse")
        self.assertEqual(verdict["final_url"], "https://embed.vidrift.net/api/orion/abcdef123/master.m3u8")

    def test_vidbolt_fallback_active(self):
        proxy_html = (
            '<html><script>'
            'var EMBED_URL="https:\\/\\/vidbolt.xyz\\/embed\\/movie\\/550?autoPlay=true";'
            '</script></html>'
        )
        vb_api = json.dumps({
            "stream": {
                "server": "orion",
                "sources": [
                    {"url": "https://cdn.example.com/stream.m3u8", "kind": "hls", "quality": "1080p"}
                ]
            }
        }).encode("utf-8")
        fetch = scripted_fetch({
            "proxy.php": (200, proxy_html, {"content-type": "text/html"}),
            "api/resolve": (200, vb_api, {"content-type": "application/json"}),
            "stream.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_cineverse("https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=550", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "cineverse")
        self.assertEqual(verdict["final_url"], "https://cdn.example.com/stream.m3u8")

    def test_relative_stream_proxy_url_active(self):
        proxy_html = (
            '<html><script>'
            r'var src="\/stream_proxy.php?url=https%3A%2F%2Fexample.com%2Fmaster.m3u8";'
            '</script></html>'
        )
        fetch = scripted_fetch({
            "stream_proxy.php": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
            "/proxy.php": (200, proxy_html, {"content-type": "text/html"}),
        })
        verdict = hr.unwrap_cineverse("https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=550", fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "cineverse")
        self.assertEqual(verdict["final_url"], "https://rozgarlelo.modiplay.xyz/stream_proxy.php?url=https%3A%2F%2Fexample.com%2Fmaster.m3u8")


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

class TestAnimahdRecognition(unittest.TestCase):
    def test_the_player_url_is_recognised_in_its_published_shape(self):
        self.assertTrue(hr.is_animahd_player(AH_PLAYER_URL))
        self.assertTrue(hr.is_animahd_player("https://animahd.com/player"))
        self.assertTrue(hr.is_animahd_player("https://animahd.com/player/?file_id=abc123"))

    def test_a_page_that_is_not_the_player_is_not_the_player(self):
        for url in ("https://animahd.com/naruto-shippuden/",
                    "https://animahd.com/player-extra/",
                    "https://animahd.com", EMBED,
                    GD_DOWNLOAD_PAGE, AH_SECURE_URL, AH_WORKER_URL):
            self.assertFalse(hr.is_animahd_player(url), url)

    def test_a_look_alike_host_is_refused(self):
        self.assertFalse(hr.is_animahd_player(
            "https://animahd.com.evil.test/player/?file_id=" + AH_FILE_ID))
        self.assertFalse(hr.is_animahd_player("not a url"))

    def test_the_row_file_id_is_read_out_of_the_player_url(self):
        self.assertEqual(hr.animahd_player_file_id(AH_PLAYER_URL), AH_FILE_ID)

    def test_the_file_id_is_only_read_from_an_animahd_host(self):
        self.assertEqual(hr.animahd_player_file_id(
            "https://other.test/player/?file_id=" + AH_FILE_ID), "")
        self.assertEqual(hr.animahd_player_file_id(
            "https://animahd.com/player/?file_id=short"), "")
        self.assertEqual(hr.animahd_player_file_id("https://animahd.com/player/"), "")


class TestAnimahdPageReading(unittest.TestCase):
    def test_the_redirect_literal_is_taken_from_the_page_itself(self):
        self.assertEqual(hr.animahd_target(AH_PLAYER_PAGE), (AH_SECURE_URL, AH_FILE_ID))

    def test_a_player_page_with_no_target_reports_nothing(self):
        self.assertEqual(hr.animahd_target("<html><body>loading</body></html>"), ("", ""))
        self.assertEqual(hr.animahd_target(""), ("", ""))

    def test_the_second_host_is_read_the_same_way(self):
        # Measured: two files on this site redirect to two different secure hosts,
        # so the label is data, not a constant.
        page = AH_PLAYER_PAGE.replace("theultimateanimehub", "animeepisodesandmore")
        url, file_id = hr.animahd_target(page)
        self.assertEqual(url, f"https://animeepisodesandmore.animahd.fun/?id={AH_FILE_ID}")
        self.assertEqual(file_id, AH_FILE_ID)

    def test_the_source_tag_is_found_with_its_declared_type(self):
        renditions = hr.animahd_renditions(AH_SECURE_PAGE)
        self.assertEqual([item["url"] for item in renditions], [AH_WORKER_URL])
        self.assertEqual(renditions[0]["declared_mime"], "video/mp4")
        self.assertEqual(renditions[0]["mime"], "")

    def test_a_source_that_is_not_a_byte_endpoint_is_not_a_rendition(self):
        cases = {
            "no src attribute": '<video><source type="video/mp4"></video>',
            "plain http": f'<source src="http://a.workers.dev/?eid={AH_EID}&token=t">',
            "not the worker host": '<source src="https://ads.example.test/e.mp4">',
            "no signed query": '<source src="https://a.animahd011.workers.dev/x.mp4">',
            "eid without token": '<source src="https://a.workers.dev/?eid=x">',
            "protocol relative is upgraded": (
                f'<source src="//a.workers.dev/?eid={AH_EID}&token=t">'),
        }
        self.assertEqual(hr.animahd_renditions(cases["no src attribute"]), [])
        self.assertEqual(hr.animahd_renditions(cases["not the worker host"]), [])
        self.assertEqual(hr.animahd_renditions(cases["no signed query"]), [])
        self.assertEqual(hr.animahd_renditions(cases["plain http"]), [])
        self.assertEqual([item["url"] for item in
                          hr.animahd_renditions(cases["protocol relative is upgraded"])],
                         ["https://a.workers.dev/?" + f"eid={AH_EID}&token=t"])
        self.assertEqual(hr.animahd_renditions(""), [])


class TestUnwrapAnimahd(unittest.TestCase):
    def scripted(self, **over):
        script = {
            "animahd.com/player": (200, AH_PLAYER_PAGE, {"content-type": "text/html"}),
            "animahd.fun/?id=": (200, AH_SECURE_PAGE, {"content-type": "text/html"}),
            "workers.dev": (206, AH_WORKER_HEAD,
                            {"content-type": "video/x-matroska",
                             "content-range": "bytes 0-511/253161185"}),
        }
        script.update(over)
        return scripted_fetch(script)

    def test_the_chain_ends_at_the_signed_worker_url(self):
        fetch = self.scripted()
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active", verdict["notes"])
        self.assertEqual(verdict["service"], "animahd-player")
        self.assertEqual(verdict["embed_url"], AH_PLAYER_URL)
        self.assertEqual(verdict["file_id"], AH_FILE_ID)
        self.assertEqual(verdict["bridge_url"], AH_SECURE_URL)
        self.assertEqual(verdict["final_url"], AH_WORKER_URL)
        self.assertTrue(verdict["is_temporary"])
        self.assertEqual(verdict["size_bytes"], 253161185)
        self.assertEqual(verdict["http_status"], 206)
        self.assertEqual(verdict["content_type"], "video/x-matroska")
        self.assertEqual([item["url"] for item in verdict["sources"]], [AH_WORKER_URL])
        self.assertEqual([item["mime"] for item in verdict["sources"]],
                         ["video/x-matroska"])
        self.assertEqual([url for url, _h, _m in fetch.calls],
                         [AH_PLAYER_URL, AH_SECURE_URL, AH_WORKER_URL])

    def test_three_requests_is_the_whole_bill(self):
        # Player page, secure page, one Range probe. Nothing is retried, because a
        # resolver that re-fetched on every refusal is how a host gets blocked.
        fetch = self.scripted(**{"workers.dev": (403, b"", {})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(len(fetch.calls), 3)
        self.assertEqual(verdict["status"], "unverified")

    def test_the_page_that_declares_mp4_while_serving_matroska_says_so(self):
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=self.scripted())
        self.assertIn("the page declares video/mp4", json.dumps(verdict["notes"]))

    def test_every_request_names_a_user_agent_and_no_referer(self):
        # Measured: the secure host answers 403 to a request with no User-Agent,
        # and 200 to the same request with a browser UA and no Referer at all.
        seen = {}

        def fake_open(request, timeout, follow=True):
            seen.setdefault("headers", []).append(dict(request.header_items()))
            body = (AH_PLAYER_PAGE if "animahd.com" in request.full_url
                    else AH_SECURE_PAGE if "animahd.fun" in request.full_url
                    else AH_WORKER_HEAD)
            headers = ({"Content-Type": "video/x-matroska",
                        "Content-Range": "bytes 0-511/253161185"}
                       if "workers.dev" in request.full_url else {})
            return FakeResponse(206 if "workers.dev" in request.full_url else 200,
                                body, headers, request.full_url)

        with mock.patch.object(hr, "_open", fake_open):
            verdict = hr.unwrap_animahd(AH_PLAYER_URL, referer="https://animahd.com/x")
        self.assertEqual(verdict["status"], "active", verdict["notes"])
        self.assertEqual(len(seen["headers"]), 3)
        for headers in seen["headers"]:
            self.assertEqual(headers.get("User-agent"), hr.USER_AGENT)
            self.assertNotIn("Referer", headers)

    def test_the_signed_query_is_named_but_its_token_is_not_an_expiry(self):
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=self.scripted())
        self.assertEqual(verdict["signed_params"], ["token"])
        self.assertEqual(verdict["expires_in"], hr.ANIMAHD_TOKEN_SECONDS)
        self.assertIn("carries no expiry of its own", json.dumps(verdict["notes"]))

    def test_a_host_that_does_publish_an_expiry_is_believed_over_the_estimate(self):
        page = AH_SECURE_PAGE.replace(
            "&v=0&ext=.mp4", "&v=0&e=2000000000&ext=.mp4", 1)
        signed = AH_WORKER_URL.replace("&v=0&ext=.mp4", "&v=0&e=2000000000&ext=.mp4")
        fetch = self.scripted(**{"animahd.fun/?id=": (200, page, {"content-type": "text/html"})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(verdict["final_url"], signed)
        self.assertEqual(verdict["expires_in"], 2000000000 - int(time.time()))
        self.assertNotIn("carries no expiry of its own", json.dumps(verdict["notes"]))

    def test_verify_off_spends_nothing(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch, verify=False)
        self.assertEqual(fetch.calls, [])
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(verdict["final_url"], AH_PLAYER_URL)
        self.assertTrue(verdict["is_temporary"])
        self.assertIn("without a request", json.dumps(verdict["notes"]))

    def test_a_non_player_url_is_refused_before_any_request(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_animahd(EMBED, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("not an animahd player URL", verdict["notes"])
        self.assertEqual(fetch.calls, [])

    def test_a_player_page_that_refuses_is_reported_as_it_answered(self):
        for status, expected in ((403, "blocked"), (404, "dead"), (500, "unknown"),
                                 (429, "blocked"), (401, "blocked"), (410, "dead")):
            fetch = self.scripted(**{"animahd.com/player": (status, b"", {})})
            verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
            self.assertEqual(verdict["status"], expected, status)
            self.assertIn(f"player page HTTP {status}", verdict["notes"])
            self.assertEqual(len(fetch.calls), 1)

    def test_a_player_page_with_no_literal_resolves_to_nothing(self):
        fetch = self.scripted(**{
            "animahd.com/player": (200, "<html>loading</html>", {"content-type": "text/html"})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("no <host>.animahd.fun/?id= target", json.dumps(verdict["notes"]))
        self.assertEqual(len(fetch.calls), 1)

    def test_a_player_url_that_carries_no_file_id_still_resolves(self):
        fetch = self.scripted()
        verdict = hr.unwrap_animahd("https://animahd.com/player/?file_id=" + AH_FILE_ID
                                    + "&show_id=194", fetch=fetch)
        self.assertEqual(verdict["status"], "active", verdict["notes"])

    def test_a_page_that_redirects_elsewhere_than_the_row_named_is_reported(self):
        page = AH_PLAYER_PAGE.replace(AH_FILE_ID, "9zOtherFileIdValue000000000000000")
        fetch = self.scripted(**{"animahd.com/player": (200, page, {"content-type": "text/html"})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertIn("which is not the", json.dumps(verdict["notes"]))
        self.assertEqual(verdict["bridge_url"],
                         "https://theultimateanimehub.animahd.fun/?id=9zOtherFileIdValue000000000000000")
        self.assertEqual(verdict["status"], "active", verdict["notes"])

    def test_a_secure_page_that_refuses_names_the_user_agent_rule(self):
        for status, expected in ((403, "blocked"), (404, "dead"), (500, "unknown")):
            fetch = self.scripted(**{"animahd.fun/?id=": (status, b"", {})})
            verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
            self.assertEqual(verdict["status"], expected, status)
            self.assertTrue(any(n.startswith(f"secure page HTTP {status}")
                                for n in verdict["notes"]),
                            f"no 'secure page HTTP {status}' note in {verdict['notes']}")
            self.assertEqual(("403" if expected == "blocked" else ""),
                             "403" if "no User-Agent" in json.dumps(verdict["notes"]) else "")

    def test_the_google_quota_page_is_a_blocked_file_not_a_missing_one(self):
        page = AH_SECURE_PAGE.replace(
            f'<source src="{AH_WORKER_URL}"', f'<p data-x="{AH_WORKER_URL}"')
        fetch = self.scripted(**{"animahd.fun/?id=": (200, page, {"content-type": "text/html"})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "blocked")
        self.assertIn("the Google quota lock", json.dumps(verdict["notes"]))

    def test_a_secure_page_with_no_endpoint_and_no_quota_words_is_unknown(self):
        fetch = self.scripted(**{
            "animahd.fun/?id=": (200, "<html><body>no player here</body></html>",
                                 {"content-type": "text/html"})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("no byte endpoint", json.dumps(verdict["notes"]))

    def test_a_refusal_from_the_byte_host_is_never_a_verdict_about_the_file(self):
        for status in (403, 429, 503, 0):
            fetch = self.scripted(**{"workers.dev": (status, b"", {})})
            verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
            self.assertEqual(verdict["status"], "unverified", status)
            self.assertIn("recorded unverified, not retried",
                          json.dumps(verdict["notes"]))
            self.assertEqual(len(fetch.calls), 3)

    def test_a_non_video_content_type_keeps_the_measured_mime_and_says_why(self):
        fetch = self.scripted(**{
            "workers.dev": (206, b"<html/>", {"content-type": "text/html"})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        # `content_type` is the host's literal answer; the measured matroska is
        # what `sources[].mime` keeps. The name promises the second, the field
        # records the first — assert both so the pair cannot drift apart again.
        self.assertEqual(verdict["content_type"], "text/html")
        self.assertEqual([item["mime"] for item in verdict["sources"]],
                         [hr.ANIMAHD_MIME])
        self.assertIn("mime reported as the measured", json.dumps(verdict["notes"]))

    def test_a_plain_200_from_the_byte_host_is_active_and_full_body(self):
        fetch = self.scripted(**{
            "workers.dev": (200, AH_WORKER_HEAD, {"content-type": "video/x-matroska"})})
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active", verdict["notes"])
        self.assertIn("full_body", json.dumps(verdict["notes"]))

    def test_a_dead_probe_that_leaves_no_content_type_is_still_labelled(self):
        fetch = self.scripted(**{"workers.dev": (410, b"", {})}),
        verdict = hr.unwrap_animahd(AH_PLAYER_URL, fetch=fetch[0])
        self.assertEqual(verdict["status"], "dead")
        self.assertEqual(verdict["sources"][0]["mime"], hr.ANIMAHD_MIME)

    def test_a_transport_failure_is_reported_not_raised(self):
        # A transport failure is `http_request`'s to absorb, not a scripted
        # fetch's: injecting a raising fetch would bypass the try/except that
        # turns the socket error into status 0. Inject at `hr._open` (the only
        # socket call) so the chain runs against the real transport.
        with mock.patch.object(hr, "_open", side_effect=OSError("dns down")):
            verdict = hr.unwrap_animahd(AH_PLAYER_URL)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("player page HTTP 0", verdict["notes"])


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

    def test_a_vidbolt_url_dispatches_to_the_vidbolt_resolver(self):
        vb_api_body = json.dumps({
            "stream": {
                "server": "orion",
                "sources": [
                    {"url": "https://cdn.example.com/stream.m3u8", "kind": "hls", "quality": "1080p"}
                ]
            }
        }).encode("utf-8")
        fetch = scripted_fetch({
            "api/resolve": (200, vb_api_body, {"content-type": "application/json"}),
            "stream.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main(["https://vidbolt.xyz/movie/550"]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "vidbolt")
        self.assertEqual(printed["status"], "active")

    def test_a_vibuxer_url_dispatches_to_the_vibuxer_resolver(self):
        packed = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){w..."
            "}('1.2=\"https://cdn.example.com/hls/master.m3u8?s=123&e=456\";',10,3,"
            "'|var|links'.split('|'),0,{}))"
        )
        html = f"<html><body><script>{packed}</script></body></html>"
        fetch = scripted_fetch({
            "vibuxer.com/e/": (200, html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-STREAM-INF\nv.m3u8", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main(["https://vibuxer.com/e/i4p45adamelv"]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "vibuxer")
        self.assertEqual(printed["status"], "active")

    def test_a_vidrift_url_dispatches_to_the_vidrift_resolver(self):
        page_html = '<html><script>var embedMeta = {"orionStreams": [{"url": "https://cdn.example.com/stream.m3u8", "type": "hls"}]};</script></html>'
        fetch = scripted_fetch({
            "embed.vidrift.net/embed/movie/550": (200, page_html, {"content-type": "text/html"}),
            "stream.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main(["https://embed.vidrift.net/embed/movie/550"]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "vidrift")
        self.assertEqual(printed["status"], "active")

    def test_an_iqsmart_url_dispatches_to_the_iqsmart_resolver(self):
        api_resp = json.dumps({"data": [{"fileslug": "slug123"}]}).encode("utf-8")
        mresult_raw = json.dumps({"smwh": "hanerix_hash"}).encode("utf-8")
        mresult_b64 = base64.b64encode(mresult_raw).decode("utf-8")
        helper_resp = json.dumps({"mresult": mresult_b64}).encode("utf-8")
        han_packed = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String)){w..."
            "}('1.2=\"https://cdn.example.com/hls/master.m3u8?s=123&e=456\";',10,3,"
            "'|var|links'.split('|'),0,{}))"
        )
        han_html = f"<html><script>{han_packed}</script></html>"

        fetch = scripted_fetch({
            "mymovieapi": (200, api_resp, {"content-type": "application/json"}),
            "embedhelper2.php": (200, helper_resp, {"content-type": "application/json"}),
            "hanerix.com/e/": (200, han_html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main(["https://streams.iqsmartgames.com/embed/movie/tt35786199?key=mykey"]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "iqsmart")
        self.assertEqual(printed["status"], "active")

    def test_a_filmu_url_dispatches_to_the_filmu_resolver(self):
        page_html = '<html>var stream = "https://dash-hls-bridge.workers.dev/?url=https%3A%2F%2Fexample.com%2Fmaster.m3u8";</html>'
        fetch = scripted_fetch({
            "vidly.pro/movie/550": (200, page_html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main(["https://vidly.pro/movie/550"]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "filmu")
        self.assertEqual(printed["status"], "active")

    def test_a_cineverse_url_dispatches_to_the_cineverse_resolver(self):
        proxy_html = '<html><script>var src="https:\\/\\/embed.vidrift.net\\/api\\/orion\\/abcdef123\\/master.m3u8";</script></html>'
        fetch = scripted_fetch({
            "proxy.php": (200, proxy_html, {"content-type": "text/html"}),
            "master.m3u8": (200, b"#EXTM3U\n#EXT-X-VERSION:3", {"content-type": "application/vnd.apple.mpegurl"}),
        })
        with mock.patch.object(hr, "http_request", fetch), silenced() as buf:
            self.assertEqual(hr.main(["https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=550"]), 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["service"], "cineverse")
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


# Session 104b: the pure helpers behind the three new unwrappers. The
# end-to-end chains (page -> API -> probe) live in test_database.py, next
# to the Session 103 unwrapper tests; these pin the parsing rules the
# chains depend on, against the exact shapes measured live on 2026-11-08.
class TestSession104bHelpers(unittest.TestCase):
    def test_uploadflix_dllink_prefers_a_video_anchor(self):
        page = """<a href='https://1uploadflix.net/f/abc'>file</a>
<a rel="nofollow" href='https://cloud.secure-storage.top:8080/d/tok1234567890abcdef1234/Some Film (2024) 480p x264 ESub.mkv'>dl</a>
<a href='https://cloud.secure-storage.top:8080/d/tok1234567890abcdef1234/readme.txt'>txt</a>"""
        link = hr._uploadflix_dllink(page, "1uploadflix.net")
        self.assertTrue(link.startswith(
            "https://cloud.secure-storage.top:8080/d/tok1234567890abcdef1234/"))
        self.assertIn("Some%20Film%20(2024)", link)
        self.assertTrue(link.endswith(".mkv"))

    def test_uploadflix_dllink_ignores_a_same_host_d_path(self):
        page = """<a href='https://1uploadflix.net/d/abc1234567890abcdef1234/file.mkv'>x</a>"""
        self.assertEqual(hr._uploadflix_dllink(page, "1uploadflix.net"), "")

    def test_uploadflix_form_fields_read_download1(self):
        body = """<form name="F1" method="POST" action="">
<input type="hidden" name="op" value="download1">
<input type="hidden" name="id" value="abc123">
<input type="hidden" name="method_premium" value="Premium Download">
</form>"""
        self.assertEqual(hr._xfs_form_fields(body),
                         {"op": "download1", "id": "abc123",
                          "method_premium": "Premium Download"})

    def test_uploadflix_form_fields_ignore_a_form_without_op(self):
        self.assertIsNone(hr._xfs_form_fields(
            "<form><input name='q' value='x'></form>"))

    def test_1xplayer_variants_pick_the_highest(self):
        master = ("#EXTM3U\n"
                  "#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x268\n"
                  "./360/index.m3u8\n"
                  "#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x804\n"
                  "./1080/index.m3u8\n")
        variants = hr._m3u8_variants(
            master, "https://i-arch-400.example/stream2/x/index.m3u8")
        self.assertEqual(len(variants), 2)
        self.assertEqual(max(variants, key=lambda item: item[0]),
                         (804, "https://i-arch-400.example/stream2/x/1080/index.m3u8"))

    def test_ts_segment_ok_needs_the_sync_bytes(self):
        good = b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 187 + b"\x47"
        self.assertTrue(hr._ts_segment_ok(good, "application/octet-stream"))
        self.assertTrue(hr._ts_segment_ok(b"x" * 512, "video/mp2t"))
        self.assertFalse(hr._ts_segment_ok(b"<html>error</html>", "text/html"))
        self.assertFalse(hr._ts_segment_ok(b"\x47" + b"\x00" * 100, "text/html"))

    def test_moviebox_pick_stream_skips_locked_and_empty(self):
        streams = [
            {"format": "MP4", "url": "", "resolutions": "1080",
             "vipLocked": True},
            {"format": "MP4", "url": "https://cdn.example/a.mp4",
             "resolutions": "480", "vipLocked": False},
            {"format": "MP4", "url": "https://cdn.example/b.mp4",
             "resolutions": "1080", "vipLocked": False},
            {"format": "DASH", "url": "https://cdn.example/c.mpd",
             "resolutions": "1080", "vipLocked": False},
        ]
        picked = hr._moviebox_pick_stream(streams)
        self.assertEqual(picked["url"], "https://cdn.example/b.mp4")
        self.assertIsNone(hr._moviebox_pick_stream(streams[:1]))


# ---------------------------------------------------------------------------
# Castle (bulwik.com) — signed tlnob re-extraction
# ---------------------------------------------------------------------------

CASTLE_PAGE = "https://www.bulwik.com/movie/all-pass/10285268178004214"
CASTLE_PAGE_HTML = """<!DOCTYPE html><html><head>
<title>All Pass Full Movie Watch Online Free</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Movie","name":"All Pass","image":"https://img1.bhcxy.com/image/2daffdb21745b63ab6b4769d8052b350fa0d753c.jpg","description":"Three families in North Chennai share peaceful lives.","genre":["Drama"],"datePublished":"2026-10-09","duration":"PT123M","contentRating":"PG"}]}</script>
</head><body>
<video><source src="https://img01.tlnob.com/video/30a719e0b2063f6666445411191bb26c2be59d31/index_401.m3u8?auth_key=n2W309DOxzOumDaP%2FwlhF3eC9U%2FWdODY93ycfLmbH04%3D\\u0026expire=1893456000000"></video>
</body></html>"""
CASTLE_PLAYLIST = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:52\n"
CASTLE_SIGNED = ("https://img01.tlnob.com/video/30a719e0b2063f6666445411191bb26c2be59d31/"
                 "index_401.m3u8?auth_key=n2W309DOxzOumDaP%2FwlhF3eC9U%2FWdODY93ycfLmbH04%3D"
                 "&expire=1893456000000")
# Live 2026-11-10 (meesaya-murukku): the img1 form (index_365) serves
# ~30% of titles — same signing, different host.
CASTLE_PAGE_HTML_IMG1 = CASTLE_PAGE_HTML.replace(
    "https://img01.tlnob.com/video/30a719e0b2063f6666445411191bb26c2be59d31/"
    "index_401.m3u8",
    "https://img1.tlnob.com/video/c94c96ebab3cab74f0cd0ce20d732551/"
    "index_365.m3u8")
CASTLE_SIGNED_IMG1 = ("https://img1.tlnob.com/video/c94c96ebab3cab74f0cd0ce20d732551/"
                      "index_365.m3u8?auth_key=n2W309DOxzOumDaP%2FwlhF3eC9U%2FWdODY93ycfLmbH04%3D"
                      "&expire=1893456000000")


class TestUnwrapCastle(unittest.TestCase):
    def test_full_chain_active_and_unescaped(self):
        fetch = scripted_fetch({
            "bulwik.com/movie/all-pass": (200, CASTLE_PAGE_HTML, {}),
            "index_401.m3u8": (200, CASTLE_PLAYLIST,
                               {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_castle(CASTLE_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "castle")
        self.assertTrue(verdict["is_temporary"])
        self.assertEqual(verdict["final_url"], CASTLE_SIGNED)
        self.assertIn("&expire=", verdict["final_url"])
        self.assertNotIn("\\u0026", verdict["final_url"])
        self.assertGreater(verdict["expires_in"], 0)

    def test_verify_off_returns_unverified_without_probing(self):
        fetch = scripted_fetch({
            "bulwik.com/movie/all-pass": (200, CASTLE_PAGE_HTML, {}),
        })
        verdict = hr.unwrap_castle(CASTLE_PAGE, fetch=fetch, verify=False)
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(verdict["final_url"], CASTLE_SIGNED)
        self.assertEqual(len(fetch.calls), 1)
        self.assertIn("not probed", json.dumps(verdict["notes"]))

    def test_non_castle_url_is_refused_before_any_request(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_castle("https://www.example.com/movie/x/1",
                                   fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(fetch.calls, [])

    def test_homepage_is_not_a_re_extract_target(self):
        self.assertFalse(hr.is_castle_page("https://www.bulwik.com/"))
        self.assertFalse(hr.is_castle_page("https://www.bulwik.com/movies"))
        self.assertTrue(hr.is_castle_page(CASTLE_PAGE))
        self.assertTrue(hr.is_castle_page(
            "https://www.bulwik.com/series/marshals-season-2/10290779789781498"))

    def test_page_without_a_signed_stream_is_unknown(self):
        fetch = scripted_fetch({
            "bulwik.com/movie/all-pass": (200, "<html>no player</html>", {}),
        })
        verdict = hr.unwrap_castle(CASTLE_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("no signed stream", json.dumps(verdict["notes"]))

    def test_page_failure_shapes(self):
        for status, expected in ((404, "dead"), (410, "dead"), (403, "blocked"),
                                 (429, "blocked"), (500, "unknown")):
            fetch = scripted_fetch({
                "bulwik.com/movie/all-pass": (status, b"", {}),
            })
            verdict = hr.unwrap_castle(CASTLE_PAGE, fetch=fetch)
            self.assertEqual(verdict["status"], expected, status)
            self.assertEqual(verdict["notes"], [f"Castle page HTTP {status}"])

    def test_expired_signature_probes_blocked(self):
        fetch = scripted_fetch({
            "bulwik.com/movie/all-pass": (200, CASTLE_PAGE_HTML, {}),
            "index_401.m3u8": (403, b"<html>403</html>",
                               {"content-type": "text/html"}),
        })
        verdict = hr.unwrap_castle(CASTLE_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "blocked")
        self.assertIn("HTTP 403", json.dumps(verdict["notes"]))

    def test_img1_index_365_variant_resolves(self):
        fetch = scripted_fetch({
            "bulwik.com/movie/all-pass": (200, CASTLE_PAGE_HTML_IMG1, {}),
            "index_365.m3u8": (200, CASTLE_PLAYLIST,
                               {"content-type": "application/vnd.apple.mpegurl"}),
        })
        verdict = hr.unwrap_castle(CASTLE_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["final_url"], CASTLE_SIGNED_IMG1)
        self.assertIn("img1.tlnob.com", verdict["final_url"])
        self.assertGreater(verdict["expires_in"], 0)

    def test_truncated_url_without_expire_is_never_served(self):
        # A page that only carries the auth_key half (no &expire=) must not
        # yield a final_url: the CDN 403s it, and the unwrapper must say so
        # instead of handing out a URL that cannot play.
        html = CASTLE_PAGE_HTML.replace("\\u0026expire=1893456000000", "")
        fetch = scripted_fetch({
            "bulwik.com/movie/all-pass": (200, html, {}),
            "index_401.m3u8": (403, b"<html>403</html>",
                               {"content-type": "text/html"}),
        })
        verdict = hr.unwrap_castle(CASTLE_PAGE, fetch=fetch)
        self.assertEqual(verdict["status"], "blocked")
        self.assertNotIn("expire=", verdict["final_url"])


# ---------------------------------------------------------------------------
# HubCloud
# ---------------------------------------------------------------------------

# A hubcloud drive page + gamerxyt page, reduced to what the resolver has
# to read but structurally faithful to the live pages (drive fetched from
# the Oracle VM 2026-11-13; gamerxyt page saved 2026-11-12 as
# /tmp/fslv2-gx-rx1co7nls9ct5zp.html). The R2 URLs carry the real account
# hashes and key shapes from that trace (readable filename for FSLv2, hex
# key for FSL) with a FAKE signature and credential — they are never
# fetched live here; scripted_fetch answers them. X-Amz-Date is minted at
# import time so expires_in stays positive while the test runs.
HC_DRIVE_ID = "rn_37lnqqexentk"
HC_DRIVE_URL = f"https://hubcloud.pw/drive/{HC_DRIVE_ID}"
HC_TOKEN = "A" * 60
HC_GAMERXYT_URL = ("https://gamerxyt.com/hubcloud.php?host=hubcloud"
                   f"&id={HC_DRIVE_ID}&token={HC_TOKEN}")


def _hc_r2_url(account, key, lifetime):
    now = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return (f"https://{account}.r2.cloudflarestorage.com/hub/{key}"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            "&X-Amz-Credential=FAKECRED%2F20261113%2Fauto%2Fs3%2Faws4_request"
            f"&X-Amz-Date={now}&X-Amz-Expires={lifetime}"
            "&X-Amz-SignedHeaders=host&X-Amz-Signature=" + "0" * 64)


HC_FSLV2_URL = _hc_r2_url("1c8e2ebb17c55ccc855414dc97ed1e80",
                          "Ramayana.2026.720p.mkv", 18000)
HC_FSL_URL = _hc_r2_url("b26be7ab2ca58cec9372503da5e7eb9a",
                        "79cc21f44d8f883216a4e509f53a3a7e", 28800)
HC_PIXEL_HREF = "https://pixeldrain.dev/u/negn6f"
HC_PIXEL_URL = "https://pixeldrain.dev/api/file/negn6f?download"
HC_10GBPS_URL = "https://pixel.hubcloud.pw/?id=deadbeef::cafef00d"
HC_BUZZ_HREF = "https://buzz.example.com/9f8e7d"
HC_BUZZ_URL = "https://buzzcdn.example.com/file.mkv?token=abc"
HC_WATCH_URL = "https://hbplay.pages.dev/?u=aHR0cHM6Ly9leGFtcGxlLmNvbS9maWxlLm1rdg=="

HC_DRIVE_PAGE = f"""<!DOCTYPE html><html><head><title>Maari.2015.1080p.WEB.DL.HIN.TAM.2.0.ESub.x264.moviesdrives.com.mkv - HubCloud</title></head><body>
<div class="vd" style="display:none">
<a id="download" href="{HC_GAMERXYT_URL}">Download</a>
</div>
</body></html>"""

HC_GAMERXYT_PAGE = f"""<!DOCTYPE html><html><head><title>HubCloud</title></head><body>
<h2><div class="main" id="section2"><div class="card h6">
<div class="card-header text-white bg-primary mb-3"> Maari.2015.1080p.WEB.DL.HIN.TAM.2.0.ESub.x264.moviesdrives.com.mkv </div>
<div class="card-body"><ul class="list-group">
<li class="list-group-item d-flex justify-content-between align-items-center">File Size<i id="size">1.59 GB</i></li>
<li class="list-group-item d-flex justify-content-between align-items-center">File Type<i>video/x-matroska</i></li>
</ul></div></div></div></h2>
<a href="{HC_FSLV2_URL}" id="s3" rel="noreferrer nofollow noopener" target="_blank" class="btn btn-success btn-lg h6">Download [FSLv2 Server]</a>
<a href="{HC_PIXEL_HREF}" id="pxl-1" rel="noreferrer nofollow noopener" target="_blank" class="btn btn-success btn-lg h6">Download [PixelServer : 2]</a>
<a href="{HC_FSL_URL}" id="fsl" rel="noreferrer nofollow noopener" target="_blank" class="btn btn-success btn-lg h6">Download [FSL Server]</a>
<a href="{HC_10GBPS_URL}" rel="noreferrer nofollow noopener" target="_blank" class="btn btn-danger btn-lg h6">Download [Server : 10Gbps]</a>
<a href="{HC_WATCH_URL}" target="_blank" rel="noopener noreferrer nofollow" class="btn btn-primary btn-lg h6" id="tgbtn">Watch Online</a>
<script>
var size = document.getElementById("size").innerHTML
if(size == 'NAN '){{swal({{
    title: "Token Expired!",
    text: "Token Link has been expired Please Click on Ok Button To Generate New Link!",
    type: "success"
}}).then(function() {{
    window.location = document.location.href = sharelink;
}})}}
</script>
</body></html>"""

HC_MKV_HEAD = GD_MKV_HEAD
HC_R2_HEADERS = {"content-type": "application/octet-stream",
                 "content-range": "bytes 0-511/1705388883"}
HC_NOT_ENTITLED = (b'<?xml version="1.0" encoding="UTF-8"?><Error>'
                   b'<Code>NotEntitled</Code><Message>Please enable R2 through '
                   b'the Cloudflare Dashboard.</Message></Error>')


def _hc_fetch(fslv2_probe, fsl_probe, pixel_probe=None, gbps_probe=None,
              gx_page=HC_GAMERXYT_PAGE):
    script = {
        "hubcloud.pw/drive/rn_37lnqqexentk": (200, HC_DRIVE_PAGE, {}),
        "gamerxyt.com/hubcloud.php": (200, gx_page, {}),
        "1c8e2ebb17c55ccc855414dc97ed1e80": fslv2_probe,
        "b26be7ab2ca58cec9372503da5e7eb9a": fsl_probe,
    }
    if pixel_probe is not None:
        script["pixeldrain.dev/api/file/negn6f"] = pixel_probe
    if gbps_probe is not None:
        script["pixel.hubcloud.pw"] = gbps_probe
    return scripted_fetch(script)


class TestUnwrapHubcloud(unittest.TestCase):
    def test_recognition(self):
        self.assertTrue(hr.is_hubcloud_drive(HC_DRIVE_URL))
        self.assertTrue(hr.is_hubcloud_drive(
            "https://hubcloud.ist/drive/abc123_-XYZ"))
        self.assertEqual(hr.hubcloud_drive_id(HC_DRIVE_URL), HC_DRIVE_ID)
        self.assertFalse(hr.is_hubcloud_drive("https://hubcloud.pw/"))
        self.assertFalse(hr.is_hubcloud_drive("https://hubcloud.pw/drive/"))
        self.assertFalse(hr.is_hubcloud_drive("https://example.com/drive/abc"))
        self.assertFalse(hr.is_hubcloud_drive(HC_GAMERXYT_URL))
        self.assertTrue(hr.is_hubcloud_bridge(HC_GAMERXYT_URL))
        self.assertFalse(hr.is_hubcloud_bridge("https://gamerxyt.com/"))
        self.assertFalse(hr.is_hubcloud_bridge(
            "https://gamerxyt.com/hubcloud.php?host=hubcloud"))
        self.assertFalse(hr.is_hubcloud_bridge(HC_DRIVE_URL))

    def test_r2_presigned_expiry(self):
        _at, fslv2_in = hr.r2_presigned_expiry(HC_FSLV2_URL)
        self.assertGreater(fslv2_in, 17000)
        self.assertLessEqual(fslv2_in, 18000)
        _at, fsl_in = hr.r2_presigned_expiry(HC_FSL_URL)
        self.assertGreater(fsl_in, 27000)
        self.assertLessEqual(fsl_in, 28800)
        self.assertEqual(hr.r2_presigned_expiry(
            "https://x.r2.cloudflarestorage.com/hub/f?X-Amz-Expires=18000"),
            (None, None))
        self.assertEqual(hr.r2_presigned_expiry(
            "https://x.r2.cloudflarestorage.com/hub/f?X-Amz-Date=20261113T080000Z"),
            (None, None))
        self.assertEqual(hr.r2_presigned_expiry(
            "https://x.r2.cloudflarestorage.com/hub/f?X-Amz-Date=not-a-date"
            "&X-Amz-Expires=18000"), (None, None))
        self.assertEqual(hr.r2_presigned_expiry("https://example.com/f.mp4"),
                         (None, None))

    def test_full_chain_active_via_fslv2(self):
        fetch = _hc_fetch(
            (206, HC_MKV_HEAD, HC_R2_HEADERS),
            (206, HC_MKV_HEAD, HC_R2_HEADERS))
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["service"], "hubcloud")
        self.assertTrue(verdict["is_temporary"])
        self.assertEqual(verdict["final_url"], HC_FSLV2_URL)
        self.assertEqual([s["label"] for s in verdict["sources"]],
                         ["FSLv2", "FSL", "PixelServer", "10Gbps"])
        self.assertEqual(verdict["quality"], "1080p")
        self.assertGreater(verdict["expires_in"], 17000)
        self.assertLessEqual(verdict["expires_in"], 18000)
        self.assertEqual(verdict["http_status"], 206)
        self.assertEqual(verdict["size_bytes"], 1705388883)
        self.assertIn("Watch Online", json.dumps(verdict["notes"]))
        # Exactly three requests: drive, gamerxyt, one probe. The fixture
        # gamerxyt page carries the static "Token Expired!" swal script on
        # every page, live or dead — it must never trigger a retry.
        self.assertEqual(len(fetch.calls), 3)
        gx_call = [c for c in fetch.calls if "gamerxyt.com" in c[0]][0]
        self.assertEqual(gx_call[1].get("Referer"), HC_DRIVE_URL)
        self.assertEqual(gx_call[1].get("Cookie"), "xla=s4t")

    def test_fslv2_blocked_falls_back_to_fsl(self):
        fetch = _hc_fetch(
            (403, HC_NOT_ENTITLED, {"content-type": "application/xml"}),
            (206, HC_MKV_HEAD, HC_R2_HEADERS))
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["final_url"], HC_FSL_URL)
        self.assertGreater(verdict["expires_in"], 27000)
        self.assertLessEqual(verdict["expires_in"], 28800)
        self.assertIn("FSLv2", json.dumps(verdict["notes"]))
        self.assertIn("HTTP 403", json.dumps(verdict["notes"]))

    def test_both_r2_blocked_falls_back_to_pixel(self):
        fetch = _hc_fetch(
            (403, HC_NOT_ENTITLED, {"content-type": "application/xml"}),
            (403, HC_NOT_ENTITLED, {"content-type": "application/xml"}),
            pixel_probe=(206, HC_MKV_HEAD, HC_R2_HEADERS))
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["final_url"], HC_PIXEL_URL)
        probed = [c[0] for c in fetch.calls]
        self.assertTrue(any("pixeldrain.dev/api/file/negn6f?download" in u
                            for u in probed))

    def test_verify_off_returns_first_candidate_unverified(self):
        fetch = _hc_fetch(
            (206, HC_MKV_HEAD, HC_R2_HEADERS),
            (206, HC_MKV_HEAD, HC_R2_HEADERS))
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch, verify=False)
        self.assertEqual(verdict["status"], "unverified")
        self.assertEqual(verdict["final_url"], HC_FSLV2_URL)
        self.assertEqual(len(fetch.calls), 2)
        self.assertIn("not probed", json.dumps(verdict["notes"]))

    def test_non_hubcloud_url_is_refused_before_any_request(self):
        fetch = scripted_fetch({})
        verdict = hr.unwrap_hubcloud("https://www.example.com/drive/abc",
                                     fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(fetch.calls, [])

    def test_drive_page_failure_shapes(self):
        for status, expected in ((404, "dead"), (410, "dead"), (403, "blocked"),
                                 (429, "blocked"), (500, "unknown")):
            fetch = scripted_fetch({
                "hubcloud.pw/drive/rn_37lnqqexentk": (status, b"", {}),
            })
            verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
            self.assertEqual(verdict["status"], expected, status)
            self.assertEqual(verdict["notes"],
                             [f"hubcloud drive page HTTP {status}"])

    def test_drive_page_without_download_link_is_unknown(self):
        fetch = scripted_fetch({
            "hubcloud.pw/drive/rn_37lnqqexentk":
                (200, "<html><body>no download here</body></html>", {}),
        })
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("no download link", json.dumps(verdict["notes"]))

    def test_gamerxyt_page_without_buttons_retries_once_then_unknown(self):
        empty_page = ("<html><body><div class=\"card-header\">x 720p</div>"
                      "no buttons</body></html>")
        fetch = scripted_fetch({
            "hubcloud.pw/drive/rn_37lnqqexentk": (200, HC_DRIVE_PAGE, {}),
            "gamerxyt.com/hubcloud.php": (200, empty_page, {}),
        })
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("no server buttons", json.dumps(verdict["notes"]))
        drive_calls = [c for c in fetch.calls if "hubcloud.pw/drive" in c[0]]
        gx_calls = [c for c in fetch.calls if "gamerxyt.com" in c[0]]
        self.assertEqual(len(drive_calls), 2)
        self.assertEqual(len(gx_calls), 2)

    def test_dead_token_first_page_then_fresh_token_succeeds(self):
        empty_page = "<html><body>no buttons</body></html>"
        calls = {"gx": 0}

        def fetch(url, headers=None, timeout=None, method="GET",
                  follow=True, data=None):
            if "hubcloud.pw/drive" in url:
                return 200, HC_DRIVE_PAGE, {"content-type": "text/html"}, url
            if "gamerxyt.com" in url:
                calls["gx"] += 1
                page = empty_page if calls["gx"] == 1 else HC_GAMERXYT_PAGE
                return 200, page, {"content-type": "text/html"}, url
            if "1c8e2ebb17c55ccc855414dc97ed1e80" in url:
                return 206, HC_MKV_HEAD, dict(HC_R2_HEADERS), url
            return 404, b"", {"content-type": "text/html"}, url

        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["final_url"], HC_FSLV2_URL)
        self.assertEqual(calls["gx"], 2)

    def test_all_candidates_dead_is_dead(self):
        fetch = _hc_fetch(
            (404, b"", {"content-type": "text/html"}),
            (404, b"", {"content-type": "text/html"}),
            pixel_probe=(404, b"", {"content-type": "text/html"}),
            gbps_probe=(404, b"", {"content-type": "text/html"}))
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "dead")

    def test_all_candidates_blocked_is_unknown_not_dead(self):
        fetch = _hc_fetch(
            (403, HC_NOT_ENTITLED, {"content-type": "application/xml"}),
            (403, HC_NOT_ENTITLED, {"content-type": "application/xml"}),
            pixel_probe=(403, b"", {"content-type": "text/html"}),
            gbps_probe=(200, b"<html>download page</html>",
                        {"content-type": "text/html"}))
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(verdict["final_url"], HC_FSLV2_URL)

    def test_10gbps_only_page_is_not_served(self):
        gx_page = ("<html><body><div class=\"card-header\">x 720p</div>"
                   f"<a href=\"{HC_10GBPS_URL}\" class=\"btn btn-danger\">"
                   "Download [Server : 10Gbps]</a></body></html>")
        fetch = scripted_fetch({
            "hubcloud.pw/drive/rn_37lnqqexentk": (200, HC_DRIVE_PAGE, {}),
            "gamerxyt.com/hubcloud.php": (200, gx_page, {}),
            "pixel.hubcloud.pw": (200, b"<html>download page</html>",
                                  {"content-type": "text/html"}),
        })
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertEqual(verdict["final_url"], HC_10GBPS_URL)

    def test_buzz_hx_redirect_is_followed(self):
        gx_page = ("<html><body><div class=\"card-header\">x 720p</div>"
                   f"<a href=\"{HC_BUZZ_HREF}\" class=\"btn btn-success\">"
                   "BuzzServer</a></body></html>")
        seen = []

        def fetch(url, headers=None, timeout=None, method="GET",
                  follow=True, data=None):
            seen.append((url, dict(headers or {}), method, follow))
            if "hubcloud.pw/drive" in url:
                return 200, HC_DRIVE_PAGE, {"content-type": "text/html"}, url
            if "gamerxyt.com" in url:
                return 200, gx_page, {"content-type": "text/html"}, url
            if "buzz.example.com/9f8e7d/download" in url:
                return 200, b"", {"content-type": "text/html",
                                  "hx-redirect": HC_BUZZ_URL}, url
            if "buzzcdn.example.com" in url:
                return 206, HC_MKV_HEAD, dict(HC_R2_HEADERS), url
            return 404, b"", {"content-type": "text/html"}, url

        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["final_url"], HC_BUZZ_URL)
        hop = [s for s in seen if "buzz.example.com/9f8e7d/download" in s[0]]
        self.assertEqual(len(hop), 1)
        self.assertFalse(hop[0][3])

    def test_buzz_without_hx_redirect_is_skipped(self):
        gx_page = ("<html><body><div class=\"card-header\">x 720p</div>"
                   f"<a href=\"{HC_BUZZ_HREF}\" class=\"btn btn-success\">"
                   "BuzzServer</a></body></html>")
        fetch = scripted_fetch({
            "hubcloud.pw/drive/rn_37lnqqexentk": (200, HC_DRIVE_PAGE, {}),
            "gamerxyt.com/hubcloud.php": (200, gx_page, {}),
            "buzz.example.com/9f8e7d/download": (200, b"", {}),
        })
        verdict = hr.unwrap_hubcloud(HC_DRIVE_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("BuzzServer", json.dumps(verdict["notes"]))

    def test_bridge_url_starts_at_gamerxyt(self):
        fetch = _hc_fetch(
            (206, HC_MKV_HEAD, HC_R2_HEADERS),
            (206, HC_MKV_HEAD, HC_R2_HEADERS))
        verdict = hr.unwrap_hubcloud(HC_GAMERXYT_URL, fetch=fetch)
        self.assertEqual(verdict["status"], "active")
        self.assertEqual(verdict["final_url"], HC_FSLV2_URL)
        self.assertEqual([c for c in fetch.calls if "hubcloud.pw/drive" in c[0]],
                         [])
        gx_call = [c for c in fetch.calls if "gamerxyt.com" in c[0]][0]
        self.assertEqual(gx_call[1].get("Referer"),
                         f"https://hubcloud.ist/drive/{HC_DRIVE_ID}")

    def test_pixel_url_rule(self):
        self.assertEqual(
            hr._hubcloud_pixel_url("https://pixeldrain.dev/u/negn6f"),
            "https://pixeldrain.dev/api/file/negn6f?download")
        self.assertEqual(
            hr._hubcloud_pixel_url(
                "https://pixel.example.com/api/file/abc?download"),
            "https://pixel.example.com/api/file/abc?download")

    def test_dispatch_prefers_id_over_text(self):
        self.assertEqual(hr._hubcloud_dispatch({"id": "s3"}, "Something else"),
                         "fslv2")
        self.assertEqual(hr._hubcloud_dispatch({"id": "pxl-1"}, "Download"),
                         "pixel")
        self.assertEqual(hr._hubcloud_dispatch({}, "Download [FSL Server]"),
                         "fsl")
        self.assertEqual(hr._hubcloud_dispatch({}, "Download [FSLv2 Server]"),
                         "fslv2")
        self.assertEqual(hr._hubcloud_dispatch({}, "Watch Online"), "")
        self.assertEqual(hr._hubcloud_dispatch({}, "Telegram"), "")


if __name__ == "__main__":
    unittest.main()
